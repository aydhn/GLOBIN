"""Secrets at rest in this user's own DPAPI envelopes.

**This is the only module in the package that names** ``crypt32``, and
``tests/architecture/test_credential_discipline.py`` enforces it alongside the
same rule for ``advapi32`` and ``kernel32``. The load lives inside
:func:`secret_vault` rather than at module scope, so importing
:mod:`globin.adapters` on a host with no ``crypt32`` — every non-Windows CI
runner — costs nothing.

**Why a second mechanism exists at all.** ``phase_028_sources.md`` S-11 measured
what the chosen store cannot do: ``CRED_MAX_CREDENTIAL_BLOB_SIZE`` is 2560 bytes
and an RSA-4096 private key in PEM form is 3324. That is not scope Phase 028
declined; it is scope Phase 028 discovered it could not have. The vault takes
what exceeds :data:`~globin.domain.secrets.MAX_SECRET_BYTES` and the Credential
Manager takes what does not, so **the two are disjoint by arithmetic rather than
by policy** and no value belongs to both or to neither.

**This is not a fallback, and the absence of one is enforced rather than
promised.** ``SECRET_STORE_CONTRACT.md`` §3 requires that an unreachable store is
a typed refusal and names what is forbidden: "never a quiet fall back to
somewhere less protected". Nothing here catches
:attr:`~globin.domain.secrets.StoreFault.NO_CREDENTIAL_SET` or
:attr:`~globin.domain.secrets.StoreFault.BACKEND_UNAVAILABLE` from another store,
because nothing here can see another store — routing is
:class:`~globin.application.secrets.ProviderRoutedStore`'s and it consults
exactly one mechanism per reference.

**Machine scope is refused by construction.** :data:`CRYPTPROTECT_LOCAL_MACHINE`
is defined here *precisely so that its absence from* :data:`PROTECT_FLAGS` *can
be asserted*, in the way :mod:`globin.domain.secrets` tests for a missing encoder
rather than trusting it. S-06 records what the flag does: protected data becomes
readable by **every** account on the computer, which
``SECRET_STORE_CONTRACT.md`` §7 already lists as refused and which matters more
here than on a single-operator host, because GLOBIN is cloned onto several
machines and run by several people under their own accounts.

**The envelope's integrity is checked before the platform is reached**, for a
reason the vendor supplies: S-04 records that ``CryptUnprotectData`` may return
either of two statuses on corruption "or in some cases may **succeed with
corrupted output**", and that applications must not rely on a code to detect
tampering. :func:`~globin.domain.secret_vault.read_envelope` is what runs first.
"""

import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from globin.adapters.environment import windows_local_free
from globin.adapters.runtime_state import AtomicDocumentWriter, FileOperations
from globin.domain.runtime_state import RuntimePersistenceError, segment_problems
from globin.domain.secret_vault import (
    encode_envelope,
    read_envelope,
    vault_entropy,
    vault_filename,
)
from globin.domain.secrets import (
    MAX_SECRET_BYTES,
    SecretReference,
    SecretResolution,
    SecretSlot,
    SecretValue,
    StoreFault,
)
from globin.errors import ValidationError

CRYPTPROTECT_UI_FORBIDDEN: Final[int] = 0x1
"""Fail rather than raise a dialogue.

``phase_031_sources.md`` S-07: "When this flag is set and a UI is specified for
either the protect or unprotect operation, the operation fails and
``GetLastError`` returns the ``ERROR_PASSWORD_RESTRICTION`` code." Set on **both**
calls. On unprotect it is load-bearing: a blob protected elsewhere with a prompt
requirement, dropped into this directory, would otherwise attempt a dialogue in a
process that may have no interactive desktop, and a scheduled task would block
invisibly. On protect it is redundant today — the prompt structure is always null
— and is set anyway as a tripwire, the identical reasoning
:meth:`~globin.adapters.secrets.WindowsCredentialStore.store` gives for
re-checking an encoded length it has already bounded.
"""

CRYPTPROTECT_LOCAL_MACHINE: Final[int] = 0x4
"""Machine scope, defined here **so that it can be asserted absent**.

Never passed. S-06 records the consequence of setting it: "Any user on the
computer on which ``CryptProtectData`` is called can use ``CryptUnprotectData``
to decrypt the data." An absence does not appear in a diff, which is why
``tests/unit/test_secret_vault_adapter.py`` asserts
``PROTECT_FLAGS & CRYPTPROTECT_LOCAL_MACHINE == 0`` rather than trusting that
nobody adds it.
"""

PROTECT_FLAGS: Final[int] = CRYPTPROTECT_UI_FORBIDDEN
"""What both calls are given.

One name, used twice, so protect and unprotect cannot drift apart — and so the
machine-scope assertion above has a single thing to check.
"""

ERROR_INVALID_DATA: Final[int] = 13
ERROR_INVALID_PARAMETER: Final[int] = 87
ERROR_PASSWORD_RESTRICTION: Final[int] = 1325

VAULT_LABEL: Final[str] = "the secret vault directory"
"""What the vault directory is called in a failure message.

Not a path. ``RUNTIME_FILESYSTEM.md`` records that nothing published anywhere
names the runtime root, and a message an operator sees is published the moment
they paste it somewhere.
"""


class _DATA_BLOB(ctypes.Structure):  # noqa: N801 -- the platform's own name
    """``DATA_BLOB``, in the documented field order.

    ``phase_031_sources.md`` S-10 gives the definition: ``DWORD cbData`` then
    ``BYTE *pbData``, from ``Wincrypt.h``.

    ``pbData`` is declared :class:`ctypes.c_void_p` rather than
    ``POINTER(c_byte)`` for the reason ``_CREDENTIALW`` gives: the latter is a
    *call*, and a module reached at import may perform none. Both are
    pointer-sized, so the layout is identical, and the value is cast where it is
    used.

    Field names and count are pinned by a unit test, because a wrong ``ctypes``
    width does not raise — it reads a neighbouring field — so a reordering during
    an edit would corrupt reads silently.
    """

    _fields_ = (
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.c_void_p),
    )


def _fault_for(status: int) -> StoreFault:
    """Classify a platform status.

    Args:
        status: What ``GetLastError`` reported.

    Returns:
        The fault it means.

    Total over an unbounded input and defaulting to
    :attr:`~globin.domain.secrets.StoreFault.BACKEND_REFUSED`, the same shape
    :func:`~globin.adapters.secrets._fault_for` has and for the same reason:
    "should be unreachable" is a claim about code that may change, and an
    unrecognised status must degrade to a named refusal rather than to a wrong
    classification.

    Both corruption statuses map to
    :attr:`~globin.domain.secrets.StoreFault.ENVELOPE_CORRUPT` — but note that
    most corruption never reaches this function at all, because the envelope's
    own digest is checked first. What survives to here is corruption *inside*
    what the platform protected, which is the one gap the digest cannot close.

    :data:`ERROR_PASSWORD_RESTRICTION` is deliberately **not** given a branch of
    its own. S-07 records it as what
    :data:`CRYPTPROTECT_UI_FORBIDDEN` produces when the platform wanted a
    dialogue, and the honest classification of that is the same
    :attr:`~globin.domain.secrets.StoreFault.BACKEND_REFUSED` the default
    already gives. A branch returning what the fall-through returns would be a
    distinction no test could observe and no operator could act on differently.
    """
    if status in {ERROR_INVALID_DATA, ERROR_INVALID_PARAMETER}:
        return StoreFault.ENVELOPE_CORRUPT
    return StoreFault.BACKEND_REFUSED


@dataclass(frozen=True, slots=True)
class DpapiSecretVault:
    """Secrets at rest in this user's own DPAPI envelopes.

    Args:
        library: The loaded ``crypt32`` handle.
        local_free: The one deallocator DPAPI obliges a caller to use. **A
            callable, never a library handle** — see
            :func:`~globin.adapters.environment.windows_local_free`.
        writer: The one atomic publication sequence, shared with the state store.
        directory: Where envelopes live. Created by the first write, never at
            start-up, so that the directory's existence is itself evidence that
            something was stored.
        declared: The references :meth:`inventory` may look for.
    """

    library: Any
    local_free: Callable[[int | None], None]
    writer: AtomicDocumentWriter
    directory: Path
    declared: tuple[SecretReference, ...] = ()

    def health(self) -> StoreFault | None:
        """Report whether the vault can be reached at all.

        Returns:
            ``None`` when the directory is usable or absent, and the fault that
            prevents it otherwise.

        **An absent directory is healthy.** It means nothing has been stored yet,
        which is the ordinary state of a fresh installation and not a
        malfunction — the same judgement
        :meth:`~globin.adapters.secrets.WindowsCredentialStore.health` makes when
        the platform answers ``ERROR_NOT_FOUND``. Writing nothing here is
        deliberate: a health check that created a directory would make asking the
        question change the answer.
        """
        parent = self.directory.parent
        if not parent.exists():
            return StoreFault.BACKEND_UNAVAILABLE
        return None

    def _target(self, reference: SecretReference, slot: SecretSlot) -> Path:
        """Where one envelope goes, refusing a name that could leave the vault.

        Args:
            reference: Which secret.
            slot: Which copy.

        Returns:
            The destination.

        Raises:
            ValidationError: If the filename is not a plain segment, or the
                resolved path is not inside the vault directory.

        **Two checks rather than one.** The first judges the name that was
        composed; the second judges the path that resulted, which is the
        discipline ``ProjectRuntimeTree._temporary`` states — the value that
        reaches a write must be verified where the write happens, not only where
        the name was chosen. The filename is built by
        :func:`~globin.domain.secret_vault.vault_filename` from
        :func:`~globin.domain.secrets.store_key`, whose alphabet excludes every
        separator, so neither check can fire today; they are what keeps that true
        if the alphabet ever moves.
        """
        filename = vault_filename(reference, slot)
        problems = segment_problems(filename, named="vault entry")
        if problems:
            raise ValidationError("; ".join(problems))
        directory = self.directory.resolve()
        target = (directory / filename).resolve()
        if not target.is_relative_to(directory) or target == directory:
            msg = f"{filename!r} would not land inside the vault directory"
            raise ValidationError(msg)
        return target

    def resolve(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> SecretResolution:
        """Look one reference up.

        Args:
            reference: What to resolve.
            slot: Which copy of the material.

        Returns:
            The resolution, carrying either the material or the fault that
            explains its absence.

        The ordering is the safety argument, and every step before the platform
        is deliberate: compose the filename, judge the path, read the file,
        then check magic, schema version, identity and digest — **and only then**
        call ``CryptUnprotectData``. S-04 records that the platform's own check
        may succeed on corrupted input, so checking afterwards would mean
        corrupted bytes had already been through the cryptography and a corrupted
        plaintext had already existed as a Python string, which is unrecallable.
        """
        try:
            target = self._target(reference, slot)
        except ValidationError:
            return SecretResolution(reference=reference, fault=StoreFault.ABSENT)
        try:
            document = self.writer.read(target)
        except (RuntimePersistenceError, ValidationError):
            return SecretResolution(reference=reference, fault=StoreFault.ENVELOPE_CORRUPT)
        if document is None:
            return SecretResolution(reference=reference, fault=StoreFault.ABSENT)
        try:
            protected = read_envelope(document, reference, slot)
        except ValidationError:
            return SecretResolution(reference=reference, fault=StoreFault.ENVELOPE_CORRUPT)
        return self._unprotect(reference, slot, protected)

    def _unprotect(
        self, reference: SecretReference, slot: SecretSlot, protected: bytes
    ) -> SecretResolution:
        """Ask the platform to decrypt one envelope.

        Args:
            reference: Which secret, for the entropy and the answer.
            slot: Which copy, for the entropy.
            protected: The ciphertext, already proved intact.

        Returns:
            The resolution.

        The native buffer is copied out, **overwritten, and freed**, all three in
        a ``finally``. The overwrite is the one place in this repository where
        Microsoft's ``SecureZeroMemory`` guidance can actually be followed:
        ``SECRET_STORE_CONTRACT.md`` §7's blanket claim that nothing can be
        erased is about a Python :class:`str`, which is immutable, may be interned
        and is moved by the allocator. This is a native allocation with a known
        address and length, so it can be erased, and the contract now says so
        precisely rather than claiming the stronger absence.
        """
        entropy = vault_entropy(
            environment=reference.environment.text,
            kind=reference.kind.value,
            name=reference.name,
            slot=slot.value,
        )
        blob_in, held_in = _blob_of(protected)
        blob_entropy, held_entropy = _blob_of(entropy)
        blob_out = _DATA_BLOB()
        succeeded = self.library.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            ctypes.byref(blob_entropy),
            None,
            None,
            PROTECT_FLAGS,
            ctypes.byref(blob_out),
        )
        del held_in, held_entropy
        if not succeeded:
            status = ctypes.get_last_error()
            return SecretResolution(reference=reference, fault=_fault_for(status))
        if not blob_out.pbData or not blob_out.cbData:
            self._release(blob_out)
            return SecretResolution(reference=reference, fault=StoreFault.ENVELOPE_CORRUPT)
        try:
            material = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            self._release(blob_out)
        try:
            text = material.decode("utf-8")
        except UnicodeDecodeError:
            return SecretResolution(reference=reference, fault=StoreFault.ENVELOPE_CORRUPT)
        try:
            value = SecretValue(text)
        except ValidationError:
            return SecretResolution(reference=reference, fault=StoreFault.VALUE_TOO_LARGE)
        return SecretResolution(reference=reference, value=value)

    def _release(self, blob: _DATA_BLOB) -> None:
        """Overwrite and free a platform allocation.

        Args:
            blob: What the platform filled in.

        The overwrite happens **before** the free, because after the free the
        memory is not ours to touch — S-03 records that examining or modifying it
        then "may" corrupt the heap or raise an access violation. The free is
        unguarded because S-03 also records that a null handle is ignored and
        returns null, so there is no branch here that only runs when something
        else already failed.
        """
        if blob.pbData:
            ctypes.memset(blob.pbData, 0, blob.cbData)
        self.local_free(blob.pbData)

    def store(
        self,
        reference: SecretReference,
        value: SecretValue,
        slot: SecretSlot = SecretSlot.CURRENT,
    ) -> StoreFault | None:
        """Protect a value and publish its envelope.

        Args:
            reference: What to store it under.
            value: The material.
            slot: Which copy to write.

        Returns:
            ``None`` on success, or the fault that prevented the write.

        The envelope is published through the same atomic sequence every other
        small document in this repository uses — a temporary file in the
        destination's own directory, ``flush``, ``fsync``, ``replace`` — so a
        crash mid-write leaves the previous envelope intact rather than a
        half-written one. **No plaintext temporary file is ever created**: what
        reaches the writer is already ciphertext.
        """
        try:
            target = self._target(reference, slot)
        except ValidationError:
            return StoreFault.BACKEND_REFUSED
        protected = self._protect(reference, slot, value)
        if isinstance(protected, StoreFault):
            return protected
        try:
            document = encode_envelope(reference, slot, protected)
        except ValidationError:
            return StoreFault.VALUE_TOO_LARGE
        try:
            self.writer.publish(target, document, label=VAULT_LABEL)
        except (RuntimePersistenceError, ValidationError):
            return StoreFault.BACKEND_REFUSED
        return None

    def _protect(
        self, reference: SecretReference, slot: SecretSlot, value: SecretValue
    ) -> bytes | StoreFault:
        """Ask the platform to encrypt one value.

        Args:
            reference: Which secret, for the entropy.
            slot: Which copy, for the entropy.
            value: The material.

        Returns:
            The ciphertext, or the fault that prevented it.

        The plaintext buffer handed to the platform is overwritten before this
        returns, for the same reason and with the same honesty as
        :meth:`_release`: the ``bytes`` object the material was read from is
        immutable and is *not* erased, and the contract says so.
        """
        entropy = vault_entropy(
            environment=reference.environment.text,
            kind=reference.kind.value,
            name=reference.name,
            slot=slot.value,
        )
        blob_in, held_in = _blob_of(value.material().encode("utf-8"))
        blob_entropy, held_entropy = _blob_of(entropy)
        blob_out = _DATA_BLOB()
        succeeded = self.library.CryptProtectData(
            ctypes.byref(blob_in),
            None,
            ctypes.byref(blob_entropy),
            None,
            None,
            PROTECT_FLAGS,
            ctypes.byref(blob_out),
        )
        del held_in, held_entropy
        if not succeeded:
            return _fault_for(ctypes.get_last_error())
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            self._release(blob_out)

    def delete(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> StoreFault | None:
        """Remove one envelope.

        Args:
            reference: What to remove.
            slot: Which copy.

        Returns:
            ``None`` on success, or
            :attr:`~globin.domain.secrets.StoreFault.ABSENT` when there was
            nothing to remove.
        """
        try:
            target = self._target(reference, slot)
        except ValidationError:
            return StoreFault.ABSENT
        if not target.exists():
            return StoreFault.ABSENT
        try:
            self.writer.discard(target)
        except RuntimePersistenceError:
            return StoreFault.BACKEND_REFUSED
        return None

    def inventory(self) -> tuple[SecretReference, ...]:
        """List what this vault holds, by name only.

        Returns:
            Every declared reference that has an envelope, sorted.

        **Never a directory walk.** The declared set is asked for one file at a
        time, the same discipline
        :meth:`~globin.adapters.secrets.WindowsCredentialStore.inventory` follows
        by refusing to enumerate the platform's credential set: a walk would
        report whatever happened to be in the directory, including something
        another tool put there, as though GLOBIN owned it.
        """
        found: list[SecretReference] = []
        for reference in self.declared:
            try:
                target = self._target(reference, SecretSlot.CURRENT)
            except ValidationError:
                continue
            if target.exists():
                found.append(reference)
        return tuple(sorted(found))


def _blob_of(payload: bytes) -> tuple[_DATA_BLOB, Any]:
    """Wrap bytes in the structure the platform takes.

    Args:
        payload: What to wrap.

    Returns:
        The blob, **and the buffer it points at**.

    **The buffer is returned rather than kept, and that is the whole reason this
    function exists.** Assigning a cast pointer into a
    :class:`ctypes.Structure` field copies an integer address; ``ctypes`` does
    not record the buffer as a dependency of the structure the way it does for a
    cast's own result. A version of this that built the blob from a temporary
    would leave a pointer to freed memory — and would read as working, because
    the bytes usually survive long enough. Handing the buffer back forces every
    caller to hold it in a local for as long as the blob is passed to the
    platform.
    """
    buffer = (ctypes.c_byte * len(payload)).from_buffer_copy(payload)
    blob = _DATA_BLOB()
    blob.cbData = len(payload)
    blob.pbData = ctypes.cast(buffer, ctypes.c_void_p)
    return blob, buffer


@dataclass(frozen=True, slots=True)
class UnavailableSecretVault:
    """The answer where this host offers no data-protection facility.

    Args:
        fault: What to report. Defaults to
            :attr:`~globin.domain.secrets.StoreFault.BACKEND_UNAVAILABLE`.

    Every method answers with the fault and touches nothing.
    :meth:`store` **never reads its value**, and that it does not is the point:
    a stand-in that handled the material would be one that had held it.
    """

    fault: StoreFault = StoreFault.BACKEND_UNAVAILABLE

    def health(self) -> StoreFault | None:
        """Report the absence."""
        return self.fault

    def resolve(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> SecretResolution:
        """Report the absence.

        Args:
            reference: What was asked for.
            slot: Which copy was asked for, and is not consulted.
        """
        del slot
        return SecretResolution(reference=reference, fault=self.fault)

    def store(
        self,
        reference: SecretReference,
        value: SecretValue,
        slot: SecretSlot = SecretSlot.CURRENT,
    ) -> StoreFault | None:
        """Report the absence without reading the material.

        Args:
            reference: What was asked for, and is not consulted.
            value: The material, which is **not** read.
            slot: Which copy, and is not consulted.
        """
        del reference, value, slot
        return self.fault

    def delete(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> StoreFault | None:
        """Report the absence.

        Args:
            reference: What was asked for, and is not consulted.
            slot: Which copy, and is not consulted.
        """
        del reference, slot
        return self.fault

    def inventory(self) -> tuple[SecretReference, ...]:
        """Report nothing, because nothing is held."""
        return ()


def secret_vault(
    directory: Path,
    declared: tuple[SecretReference, ...] = (),
    operations: FileOperations | None = None,
) -> DpapiSecretVault | UnavailableSecretVault:
    """Build the vault this host can offer.

    Args:
        directory: Where envelopes live.
        declared: The references :meth:`DpapiSecretVault.inventory` looks for.
        operations: The filesystem steps, substitutable one at a time.

    Returns:
        A DPAPI-backed vault where ``crypt32`` loads **and** the deallocator is
        available, and one that records the absence otherwise.

    **Two absences compose into one recorded state.** The deallocator lives in
    another module because ``kernel32`` has exactly one permitted loader, so this
    factory can fail for either reason; a host where ``crypt32`` loads and
    ``kernel32`` does not is not one anybody has seen, and it is handled rather
    than assumed away.

    The platform check is :data:`sys.platform` rather than a ``try``/``except``
    around the load, for the reason
    :func:`~globin.adapters.secrets.windows_credential_store` gives:
    :class:`ctypes.WinDLL` does not exist as an attribute on non-Windows
    CPython, so reaching for it there raises :class:`AttributeError` and not
    :class:`OSError`.
    """
    if sys.platform != "win32":
        return UnavailableSecretVault()
    free = windows_local_free()
    if free is None:
        return UnavailableSecretVault()
    try:
        library = ctypes.WinDLL("crypt32", use_last_error=True)
    except OSError:
        return UnavailableSecretVault()
    _bind(library)
    return DpapiSecretVault(
        library=library,
        local_free=free,
        writer=AtomicDocumentWriter(operations=operations or FileOperations()),
        directory=directory,
        declared=declared,
    )


def _bind(library: Any) -> None:
    """Declare both calls' argument and return types.

    Args:
        library: The loaded ``crypt32`` handle.

    ``pPromptStruct`` is typed :class:`ctypes.c_void_p` and is always ``None``,
    and **the type is the point**: S-05 records that the prompt-based flow "will
    be removed in February 2027" and that passing null takes the non-interactive
    path, so declaring the parameter as a pointer to a structure would put a type
    in this package that a later edit could populate. There is none, which is the
    same absence-as-design :mod:`globin.ports.secrets` uses about its own surface.

    ``ppszDataDescr`` is likewise ``None``. S-02 records that a non-null
    description must *also* be freed with ``LocalFree``; passing null removes the
    second obligation entirely.
    """
    blob = ctypes.POINTER(_DATA_BLOB)
    library.CryptProtectData.argtypes = (
        blob,
        wintypes.LPCWSTR,
        blob,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        blob,
    )
    library.CryptProtectData.restype = wintypes.BOOL
    library.CryptUnprotectData.argtypes = (
        blob,
        ctypes.POINTER(wintypes.LPWSTR),
        blob,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        blob,
    )
    library.CryptUnprotectData.restype = wintypes.BOOL


def vault_ceiling() -> int:
    """The size at or below which the Credential Manager is the right mechanism.

    Returns:
        :data:`~globin.domain.secrets.MAX_SECRET_BYTES`.

    A function rather than a re-export, so that a caller deciding where material
    belongs reads the store's own constant and the two cannot drift into
    disagreeing about which values each takes.
    """
    return MAX_SECRET_BYTES
