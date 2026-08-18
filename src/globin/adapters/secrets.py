r"""The Windows Credential Manager, and what to do when it is not there.

**This is the only module in the package that names** ``advapi32``, and
``tests/architecture/test_credential_discipline.py`` enforces that on the real
import graph — the same rule, for the same reason,
``test_probe_discipline.py`` applies to ``psutil``. The CI ``quality`` job runs
on a hosted Windows runner under a logon that may have no credential set at all,
and the suite must also import cleanly on a non-Windows interpreter, so the
absence is handled in one place and every layer above is written as though the
store were present.

:func:`windows_credential_store` is the factory, and the ``ctypes`` load lives
*inside* it. At module scope a ``WinDLL`` load would run when
:mod:`globin.adapters` is imported, which the smoke test does; here the cost is
one cached handle per process and the failure is a recorded
:class:`~globin.domain.secrets.StoreFault`.

**Every fact encoded below was measured on this host**, and
``docs/research/phase_028_sources.md`` records each with what it answered. Three
of them would have been got wrong from the documentation alone:

- The blob ceiling is exactly 2560 bytes, and one byte over returns **1783**,
  ``RPC_X_BAD_STUB_DATA`` — a status ``CredWriteW``'s own documentation never
  mentions (S-04, S-05). Nothing here classifies by matching the documented
  list, and the domain refuses an oversized value before this module is
  reached.
- A target name is case-insensitive *silently*: a credential written under one
  spelling is returned for another with no error (S-06). The key builder folds
  case, and this module never composes a key itself.
- The ceiling is enforced in **bytes**, and which bytes depends on the encoding
  this module picks — see :data:`BLOB_ENCODING` for why that is UTF-8 and what
  the obvious alternative would have broken.
- All three persistence scopes work here (S-07), so
  :data:`CRED_PERSIST_ENTERPRISE` is declined by GLOBIN's policy rather than by
  the platform's refusal, and the docstring says which.

**No value is logged, echoed, returned to a stream or held.** A blob read from
the platform becomes a :class:`~globin.domain.secrets.SecretValue` and the
intermediate buffer goes out of scope; §7 of the store contract is explicit that
CPython cannot promise erasure, so this claims bounded lifetime and no
persistence and never more.
"""

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Final

from globin.domain.secrets import (
    MAX_SECRET_BYTES,
    SecretReference,
    SecretResolution,
    SecretSlot,
    SecretValue,
    StoreFault,
    store_key,
)

CRED_TYPE_GENERIC: Final[int] = 1
"""The credential type GLOBIN writes.

A generic credential is the one the operating system does not interpret, which
is what an application storing its own material wants. The other types are for
domain logons and certificates and carry semantics GLOBIN would be borrowing
without needing.
"""

CRED_PERSIST_LOCAL_MACHINE: Final[int] = 2
"""How long a credential lives, and where it is visible.

``phase_020_sources.md`` S-08 records the platform's own description: this scope
is "visible to other logon sessions of this same user on this same computer and
not visible to logon sessions for this user on other computers".

The two alternatives are declined deliberately, and **neither is refused by the
platform** — S-07 measured all three succeeding on this host, so describing this
as a platform constraint would be false. ``CRED_PERSIST_ENTERPRISE`` is declined
because it additionally makes the credential visible on *other computers*, which
widens the blast radius of a compromise past the single machine ADR-0009
declares GLOBIN runs on. ``CRED_PERSIST_SESSION`` is declined because a
credential that vanished at logoff would make an unattended restart fail in a
way indistinguishable from corruption.
"""

ERROR_NOT_FOUND: Final[int] = 1168
"""What reading an absent target name reports. Measured: S-06."""

ERROR_NO_SUCH_LOGON_SESSION: Final[int] = 1312
"""What a logon session with no credential set reports.

Documented on both ``CredReadW`` and ``CredWriteW``, and recorded as
``phase_020_sources.md`` S-09: "Network logon sessions do not have an associated
credential set." A state to record, never a crash.
"""

RPC_X_BAD_STUB_DATA: Final[int] = 1783
"""What an oversized credential blob reports on this host.

Undocumented for this function — ``phase_028_sources.md`` S-04 records that
``CredWriteW`` lists no status for exceeding the blob limit, and S-05 records
this value arriving at 2561 bytes while 2560 succeeds. Named here so that the
one failure the ceiling exists to cause is classified rather than filed under
"the store refused and did not say why". It should be unreachable, because
:class:`~globin.domain.secrets.SecretValue` refuses an oversized value at
construction; it is mapped anyway, because "should be unreachable" is a claim
about code that may change.
"""

BLOB_ENCODING: Final[str] = "utf-8"
"""How material is encoded into the credential blob.

A credential blob is opaque bytes to the platform, so the encoding is GLOBIN's
to choose. **UTF-8 is chosen so that the domain's ceiling is measured in the
same unit the platform enforces**, and that is not a stylistic preference — it
was a defect found by a test.

The obvious choice is UTF-16 little-endian, which is what most Windows
credential tooling writes. Under it the two bounds disagree by a factor of two
for ASCII, because UTF-16 spends two bytes on a character UTF-8 spends one on:
a 2560-character ASCII secret satisfies
:data:`~globin.domain.secrets.MAX_SECRET_BYTES` and produces a 5120-byte blob
the platform refuses. An API key is ASCII, so that is the ordinary case rather
than an exotic one, and the domain's refusal would have been advertising a
limit twice the real one.

UTF-8 makes the two exact for every input, and doubles the usable capacity for
the material GLOBIN will actually hold. It also matches every other encoding
decision in this repository. :meth:`WindowsCredentialStore.store` re-checks the
encoded length anyway, because "the two units agree" is a property of this
constant and a constant can be changed.
"""


class _FILETIME(ctypes.Structure):
    """The platform's timestamp, present only because the structure has one."""

    _fields_ = (
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    )


class _CREDENTIALW(ctypes.Structure):
    """The ``CREDENTIALW`` structure, in the documented field order.

    Field order and widths are load-bearing in a way ordinary Python is not: a
    wrong offset does not raise, it reads a neighbouring field. The order below
    is the one Microsoft's reference gives, and
    ``tests/unit/test_secrets_adapter.py`` asserts the field names and count so
    that a reordering during an edit fails a test rather than corrupting a read.
    """

    _fields_ = (
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        # `c_void_p` rather than `POINTER(c_byte)`: the latter is a *call*, and
        # `tests/architecture/test_architecture_contract.py` forbids a layer
        # module from performing one at import. Both are pointer-sized, so the
        # structure layout is identical; the address is cast where it is used.
        ("CredentialBlob", ctypes.c_void_p),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    )


@dataclass(frozen=True, slots=True)
class UnavailableSecretStore:
    """A store on a host that has none, answering every question the same way.

    Args:
        fault: Why the store is unavailable.

    Returned by :func:`windows_credential_store` where ``advapi32`` cannot be
    loaded, which covers every non-Windows interpreter and any Windows host
    where the library is missing. It answers rather than raises, so that a
    readiness check on such a host reports a state instead of unwinding — the
    rule ADR-0045 sets for a platform capability and the shape
    :class:`~globin.adapters.health.UnavailableProcessProbe` already has.
    """

    fault: StoreFault = StoreFault.BACKEND_UNAVAILABLE

    def health(self) -> StoreFault | None:
        """Report the fault that makes this store unusable.

        Returns:
            The fault, always.
        """
        return self.fault

    def resolve(
        self,
        reference: SecretReference,
        slot: SecretSlot = SecretSlot.CURRENT,  # noqa: ARG002 -- the protocol's shape
    ) -> SecretResolution:
        """Resolve nothing, and say why.

        Args:
            reference: What was asked for, echoed back in the resolution.
            slot: Unused. There is no store, so both slots are equally absent.

        Returns:
            A resolution carrying the fault.
        """
        return SecretResolution(reference=reference, fault=self.fault)

    def store(
        self,
        reference: SecretReference,  # noqa: ARG002 -- the protocol's shape
        value: SecretValue,  # noqa: ARG002 -- deliberately never read; see below
        slot: SecretSlot = SecretSlot.CURRENT,  # noqa: ARG002 -- the protocol's shape
    ) -> StoreFault | None:
        """Refuse to write.

        Args:
            reference: Unused.
            value: Unused, and **the fact that it is never read is the point**.
                A null store that touched the material would be a null store
                that had held it.
            slot: Unused.

        Returns:
            The fault, always.
        """
        return self.fault

    def delete(
        self,
        reference: SecretReference,  # noqa: ARG002 -- the protocol's shape
        slot: SecretSlot = SecretSlot.CURRENT,  # noqa: ARG002 -- the protocol's shape
    ) -> StoreFault | None:
        """Refuse to delete.

        Args:
            reference: Unused.
            slot: Unused.

        Returns:
            The fault, always.
        """
        return self.fault

    def inventory(self) -> tuple[SecretReference, ...]:
        """List nothing.

        Returns:
            An empty tuple.

        Empty rather than a refusal, because "this host holds no GLOBIN
        credentials" is a true answer on a host with no credential store, and a
        caller rendering an inventory does not need it to raise.
        """
        return ()


@dataclass(frozen=True, slots=True)
class WindowsCredentialStore:
    """The Windows Credential Manager, reached through ``advapi32``.

    Args:
        library: The loaded ``advapi32`` handle, injected so a test can
            substitute a fake without owning a credential store. Typed as
            :class:`~typing.Any` because ``ctypes`` gives a ``WinDLL`` no
            structural type a protocol could express.

    Every method returns rather than raises. A platform status is mapped to a
    bounded :class:`~globin.domain.secrets.StoreFault` by :func:`_fault_for`,
    and an unrecognised one becomes
    :attr:`~globin.domain.secrets.StoreFault.BACKEND_REFUSED` rather than being
    re-derived from the number.
    """

    library: Any
    declared: tuple[SecretReference, ...] = ()

    def health(self) -> StoreFault | None:
        """Ask the store a question with no side effects.

        Returns:
            ``None`` when a read completes or reports a plain absence, and the
            fault otherwise.

        Reads a target name that is never written, so the expected answer is
        :data:`ERROR_NOT_FOUND` — which proves the facility answers. A
        health check that *wrote* something would leave a credential behind on
        every start-up, and one that listed the store would be an inventory.
        """
        probe = f"globin:health-probe:{SecretSlot.CURRENT.value}"
        pointer = ctypes.POINTER(_CREDENTIALW)()
        ctypes.set_last_error(0)
        ok = self.library.CredReadW(probe, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer))
        if ok:
            self.library.CredFree(pointer)
            return None
        status = ctypes.get_last_error()
        if status == ERROR_NOT_FOUND:
            return None
        return _fault_for(status)

    def resolve(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> SecretResolution:
        """Read one credential.

        Args:
            reference: What to resolve.
            slot: Which copy.

        Returns:
            The resolution, carrying the material or the fault.

        The buffer is freed in a ``finally`` so that a decode failure cannot
        leak the platform's allocation, and the decoded string is handed
        straight to :class:`~globin.domain.secrets.SecretValue` so that it
        spends the shortest possible time as an ordinary string.
        """
        pointer = ctypes.POINTER(_CREDENTIALW)()
        ctypes.set_last_error(0)
        ok = self.library.CredReadW(
            store_key(reference, slot), CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)
        )
        if not ok:
            return SecretResolution(reference=reference, fault=_fault_for(ctypes.get_last_error()))
        try:
            size = int(pointer.contents.CredentialBlobSize)
            raw = ctypes.string_at(pointer.contents.CredentialBlob, size)
        finally:
            self.library.CredFree(pointer)
        try:
            material = raw.decode(BLOB_ENCODING)
        except UnicodeDecodeError:
            return SecretResolution(reference=reference, fault=StoreFault.KIND_MISMATCH)
        return SecretResolution(reference=reference, value=SecretValue(material))

    def store(
        self,
        reference: SecretReference,
        value: SecretValue,
        slot: SecretSlot = SecretSlot.CURRENT,
    ) -> StoreFault | None:
        """Write one credential, creating or replacing.

        Args:
            reference: What to store it under.
            value: The material.
            slot: Which copy to write.

        Returns:
            ``None`` on success, or the fault that prevented it.

        The encoded length is re-checked here even though
        :class:`~globin.domain.secrets.SecretValue` already refused an oversized
        value. Under :data:`BLOB_ENCODING` the two counts are identical, so this
        is redundant *today* — and it is kept because that identity is a property
        of one constant. A phase that changed the encoding for interoperability
        would otherwise reintroduce the two-to-one gap silently, which is exactly
        how it arrived the first time.
        """
        encoded = value.material().encode(BLOB_ENCODING)
        if len(encoded) > MAX_SECRET_BYTES:
            return StoreFault.VALUE_TOO_LARGE
        buffer = (ctypes.c_byte * len(encoded)).from_buffer_copy(encoded)
        credential = _CREDENTIALW(
            Flags=0,
            Type=CRED_TYPE_GENERIC,
            TargetName=store_key(reference, slot),
            Comment=None,
            LastWritten=_FILETIME(),
            CredentialBlobSize=len(encoded),
            CredentialBlob=ctypes.cast(buffer, ctypes.c_void_p),
            Persist=CRED_PERSIST_LOCAL_MACHINE,
            AttributeCount=0,
            Attributes=None,
            TargetAlias=None,
            UserName=None,
        )
        ctypes.set_last_error(0)
        ok = self.library.CredWriteW(ctypes.byref(credential), 0)
        return None if ok else _fault_for(ctypes.get_last_error())

    def delete(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> StoreFault | None:
        """Remove one credential.

        Args:
            reference: What to remove.
            slot: Which copy.

        Returns:
            ``None`` on success, or the fault that prevented it.
        """
        ctypes.set_last_error(0)
        ok = self.library.CredDeleteW(store_key(reference, slot), CRED_TYPE_GENERIC, 0)
        return None if ok else _fault_for(ctypes.get_last_error())

    def inventory(self) -> tuple[SecretReference, ...]:
        """List what GLOBIN holds here.

        Returns:
            An empty tuple.

        **Deliberately empty, and this is not a stub.** Enumerating the store
        would mean calling ``CredEnumerateW`` over every credential the account
        holds — including every one written by every other application on the
        machine — and filtering by prefix. That reads material belonging to
        software GLOBIN has nothing to do with, in order to answer a question
        about GLOBIN, and ``SECRET_STORE_CONTRACT.md`` §5 permits listing
        without requiring the listing be discovered by walking somebody else's
        credentials.

        **Phase 029 made good on that promise**, and the shape is exactly what
        the previous version of this docstring described: the declaration
        resolved one reference at a time through :meth:`resolve`, touching
        nothing GLOBIN did not write.

        It still returns empty on this host, and for a different reason than
        before -- :attr:`declared` is fed from
        :func:`globin.domain.entitlements.required_credentials`, which is empty
        because GLOBIN reaches no venue. The mechanism exists; the set does not.

        Every resolved value is discarded immediately. What is returned is a
        tuple of references, which
        ``SECRET_STORE_CONTRACT.md`` section 1 calls ordinary data.
        """
        return tuple(
            sorted(reference for reference in self.declared if self.resolve(reference).resolved)
        )


def _fault_for(status: int) -> StoreFault:
    """Map a platform status code to a bounded fault.

    Args:
        status: What ``GetLastError`` reported.

    Returns:
        The fault, defaulting to
        :attr:`~globin.domain.secrets.StoreFault.BACKEND_REFUSED`.

    A total function over an unbounded input, which is the point: an
    unrecognised status becomes a named refusal rather than being interpreted.
    ``phase_028_sources.md`` S-04 is why the default matters — ``CredWriteW``
    documents no status for the one failure its own size limit causes, so any
    mapping written from the documentation alone is incomplete by construction.
    """
    if status == ERROR_NOT_FOUND:
        return StoreFault.ABSENT
    if status == ERROR_NO_SUCH_LOGON_SESSION:
        return StoreFault.NO_CREDENTIAL_SET
    if status == RPC_X_BAD_STUB_DATA:
        return StoreFault.VALUE_TOO_LARGE
    return StoreFault.BACKEND_REFUSED


def windows_credential_store(
    declared: tuple[SecretReference, ...] = (),
) -> WindowsCredentialStore | UnavailableSecretStore:
    """Build the store this host can offer.

    Args:
        declared: The references GLOBIN is allowed to look for, which is
            what :meth:`WindowsCredentialStore.inventory` resolves one at a
            time. Empty on a host with no requirement, which is every host
            today.

    Returns:
        A Credential Manager-backed store where ``advapi32`` loads, and one that
        records the platform's absence where it does not.

    The ``ctypes`` load is inside the function deliberately, and this is the
    only place in the package that performs it. At module scope it would run
    when :mod:`globin.adapters` is imported, which the smoke test does on hosts
    where this library does not exist at all.

    The platform check is :data:`sys.platform` rather than a ``try``/``except``
    around the load alone, because ``ctypes.WinDLL`` does not exist as an
    attribute on non-Windows CPython — reaching for it there is an
    :class:`AttributeError` rather than an :class:`OSError`, and catching the
    wrong one would turn a portable absence into a crash.
    """
    if sys.platform != "win32":
        return UnavailableSecretStore()
    try:
        library = ctypes.WinDLL("advapi32", use_last_error=True)
    except OSError:
        return UnavailableSecretStore()
    library.CredWriteW.argtypes = (ctypes.POINTER(_CREDENTIALW), wintypes.DWORD)
    library.CredWriteW.restype = wintypes.BOOL
    library.CredReadW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
    )
    library.CredReadW.restype = wintypes.BOOL
    library.CredDeleteW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
    library.CredDeleteW.restype = wintypes.BOOL
    library.CredFree.argtypes = (ctypes.c_void_p,)
    library.CredFree.restype = None
    return WindowsCredentialStore(library=library, declared=declared)
