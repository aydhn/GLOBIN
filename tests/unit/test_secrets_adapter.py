"""The Credential Manager adapter, driven by a fake `advapi32`.

No test here touches the real credential store. Every platform answer arrives
through a deterministic fake, which is what lets a logon session with no
credential set, an oversized blob and an undocumented status code all be
exercised on a machine where none of them is happening.

**The structure layout is asserted rather than trusted.** A wrong `ctypes` field
width does not raise — it reads a neighbouring field — so a reordering during an
edit would corrupt reads silently. The field names and count are pinned here for
the same reason `test_bootstrap_contract.py` pins the exit codes.
"""

import ctypes
from dataclasses import dataclass, field
from typing import Any

import pytest

from globin.adapters.secrets import (
    _CREDENTIALW,
    BLOB_ENCODING,
    CRED_PERSIST_LOCAL_MACHINE,
    CRED_TYPE_GENERIC,
    ERROR_NO_SUCH_LOGON_SESSION,
    ERROR_NOT_FOUND,
    RPC_X_BAD_STUB_DATA,
    UnavailableSecretStore,
    WindowsCredentialStore,
    _fault_for,
    windows_credential_store,
)
from globin.domain.identifiers import environment_id
from globin.domain.secrets import (
    MAX_SECRET_BYTES,
    SecretKind,
    SecretReference,
    SecretSlot,
    SecretValue,
    StoreFault,
    store_key,
)

MATERIAL = "not-a-real-secret-0000"

REFERENCE = SecretReference(
    environment=environment_id("paper"),
    kind=SecretKind.API_KEY,
    name="venue_key",
)


@dataclass
class _FakeAdvapi32:
    """A deterministic stand-in for the platform's credential functions.

    Args:
        stored: What the store currently holds, keyed by target name.
        write_error: A status to fail every write with, or ``0`` to succeed.
        read_error: A status to fail every read with, or ``0`` for the real answer.

    Holds bytes rather than strings, because the encoding boundary is part of
    what is under test: a round trip through the wrong codec returns material
    that is nearly right, and this fake would not catch that if it stored the
    decoded form.
    """

    stored: dict[str, bytes] = field(default_factory=dict)
    write_error: int = 0
    read_error: int = 0
    freed: int = 0

    def CredWriteW(self, credential: Any, flags: int) -> int:  # noqa: N802 -- the platform's name
        del flags
        if self.write_error:
            ctypes.set_last_error(self.write_error)
            return 0
        record = credential._obj  # noqa: SLF001 -- byref exposes the object this way
        size = int(record.CredentialBlobSize)
        self.stored[record.TargetName] = ctypes.string_at(record.CredentialBlob, size)
        return 1

    def CredReadW(self, target: str, kind: int, flags: int, out: Any) -> int:  # noqa: N802
        del kind, flags
        if self.read_error:
            ctypes.set_last_error(self.read_error)
            return 0
        if target not in self.stored:
            ctypes.set_last_error(ERROR_NOT_FOUND)
            return 0
        blob = self.stored[target]
        buffer = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
        record = _CREDENTIALW(
            CredentialBlobSize=len(blob),
            CredentialBlob=ctypes.cast(buffer, ctypes.c_void_p),
        )
        record._keepalive = buffer  # noqa: SLF001 -- keeps the buffer alive past the call
        out._obj.contents = record  # noqa: SLF001
        self._alive = record  # keep the record and its buffer from being collected
        return 1

    def CredDeleteW(self, target: str, kind: int, flags: int) -> int:  # noqa: N802
        del kind, flags
        if target not in self.stored:
            ctypes.set_last_error(ERROR_NOT_FOUND)
            return 0
        del self.stored[target]
        return 1

    def CredFree(self, pointer: Any) -> None:  # noqa: N802
        del pointer
        self.freed += 1


def store(**kwargs: Any) -> tuple[WindowsCredentialStore, _FakeAdvapi32]:
    """A store over a fake library, and the fake, so a test can inspect both."""
    library = _FakeAdvapi32(**kwargs)
    return WindowsCredentialStore(library=library), library


# ---------------------------------------------------------------------------
# The structure
# ---------------------------------------------------------------------------


def test_the_credential_structure_has_the_documented_fields_in_order() -> None:
    """A wrong offset reads a neighbouring field rather than raising.

    Pinned to the order Microsoft's `CREDENTIALW` reference gives, so that an
    edit which reorders or drops one fails here instead of returning material
    from the wrong member.
    """
    assert [name for name, _type in _CREDENTIALW._fields_] == [
        "Flags",
        "Type",
        "TargetName",
        "Comment",
        "LastWritten",
        "CredentialBlobSize",
        "CredentialBlob",
        "Persist",
        "AttributeCount",
        "Attributes",
        "TargetAlias",
        "UserName",
    ]


def test_the_blob_pointer_field_is_pointer_sized() -> None:
    """`c_void_p` replaced `POINTER(c_byte)` to avoid a call at import.

    The substitution is only safe because the two have the same width, and that
    is asserted rather than assumed — a narrower field would silently truncate
    the address on a 64-bit host.
    """
    fields = dict(_CREDENTIALW._fields_)
    assert ctypes.sizeof(fields["CredentialBlob"]) == ctypes.sizeof(ctypes.c_void_p)


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_a_written_value_reads_back_identically() -> None:
    """The whole point, and the encoding boundary is inside it."""
    credentials, _ = store()
    assert credentials.store(REFERENCE, SecretValue(MATERIAL)) is None
    assert credentials.resolve(REFERENCE).value == SecretValue(MATERIAL)


def test_a_value_is_written_under_the_key_the_builder_produced() -> None:
    """This module never composes a key, which section 2 requires."""
    credentials, library = store()
    credentials.store(REFERENCE, SecretValue(MATERIAL))
    assert set(library.stored) == {store_key(REFERENCE, SecretSlot.CURRENT)}


def test_the_two_slots_are_two_credentials() -> None:
    """Rotation depends on the previous value surviving the new write."""
    credentials, library = store()
    credentials.store(REFERENCE, SecretValue(MATERIAL), SecretSlot.CURRENT)
    credentials.store(REFERENCE, SecretValue("older-value-000000000"), SecretSlot.PREVIOUS)
    assert len(library.stored) == 2
    assert credentials.resolve(REFERENCE, SecretSlot.PREVIOUS).value == SecretValue(
        "older-value-000000000"
    )


def test_the_blob_is_written_in_the_declared_encoding() -> None:
    """A round trip through the wrong codec returns material that is nearly right."""
    credentials, library = store()
    credentials.store(REFERENCE, SecretValue(MATERIAL))
    assert next(iter(library.stored.values())) == MATERIAL.encode(BLOB_ENCODING)


def test_a_blob_that_is_not_valid_in_the_declared_encoding_is_a_kind_mismatch() -> None:
    """Something else wrote this credential, and a decode error is the good failure."""
    credentials, library = store()
    library.stored[store_key(REFERENCE)] = b"\xff\xfe\xfd"
    assert credentials.resolve(REFERENCE).fault is StoreFault.KIND_MISMATCH


def test_the_platform_buffer_is_freed_after_a_read() -> None:
    """A leak here would be an allocation per resolution for the life of the process."""
    credentials, library = store()
    credentials.store(REFERENCE, SecretValue(MATERIAL))
    credentials.resolve(REFERENCE)
    assert library.freed == 1


def test_the_buffer_is_freed_even_when_the_decode_fails() -> None:
    """The `finally` is the point: a decode error must not leak the allocation."""
    credentials, library = store()
    library.stored[store_key(REFERENCE)] = b"\xff\xfe\xfd"
    credentials.resolve(REFERENCE)
    assert library.freed == 1


def test_a_write_uses_the_local_machine_persistence_scope() -> None:
    """Enterprise roams to other computers; session vanishes at logoff. Neither is used."""
    recorded: dict[str, int] = {}
    credentials, library = store()

    original = library.CredWriteW

    def capture(credential: Any, flags: int) -> int:
        recorded["persist"] = int(credential._obj.Persist)  # noqa: SLF001
        recorded["type"] = int(credential._obj.Type)  # noqa: SLF001
        return original(credential, flags)

    library.CredWriteW = capture  # type: ignore[method-assign]
    credentials.store(REFERENCE, SecretValue(MATERIAL))
    assert recorded == {"persist": CRED_PERSIST_LOCAL_MACHINE, "type": CRED_TYPE_GENERIC}


# ---------------------------------------------------------------------------
# Faults
# ---------------------------------------------------------------------------


def test_reading_an_absent_reference_is_absent_not_an_error() -> None:
    """Section 3: explicit, and never a silent `None`."""
    credentials, _ = store()
    resolution = credentials.resolve(REFERENCE)
    assert resolution.value is None
    assert resolution.fault is StoreFault.ABSENT


def test_a_logon_session_with_no_credential_set_is_a_recorded_state() -> None:
    """`phase_020_sources.md` S-09: a network logon has no credential set.

    ADR-0045's rule applied to a facility rather than a device: a state, never a
    crash, and never a quiet fall back to somewhere less protected.
    """
    credentials, _ = store(read_error=ERROR_NO_SUCH_LOGON_SESSION)
    assert credentials.resolve(REFERENCE).fault is StoreFault.NO_CREDENTIAL_SET


def test_the_undocumented_oversize_status_is_classified_rather_than_guessed_at() -> None:
    """`phase_028_sources.md` S-04 and S-05.

    `CredWriteW` documents no status for exceeding the blob limit, and this host
    answers 1783 `RPC_X_BAD_STUB_DATA` — a name describing an RPC marshalling
    fault. Anything classifying against the documented list would file the one
    failure the ceiling exists to cause under "unknown".
    """
    credentials, _ = store(write_error=RPC_X_BAD_STUB_DATA)
    assert credentials.store(REFERENCE, SecretValue(MATERIAL)) is StoreFault.VALUE_TOO_LARGE


def test_an_unrecognised_status_becomes_a_named_refusal() -> None:
    """Total over an unbounded input: a new status is refused, never interpreted."""
    assert _fault_for(999_999) is StoreFault.BACKEND_REFUSED


def test_deleting_something_that_is_not_there_reports_absent() -> None:
    """A caller may legitimately ignore this, which is why it is not an error."""
    credentials, _ = store()
    assert credentials.delete(REFERENCE) is StoreFault.ABSENT


def test_health_treats_a_plain_absence_as_proof_the_facility_answers() -> None:
    """The probe target is never written, so `ERROR_NOT_FOUND` is the success case."""
    credentials, _ = store()
    assert credentials.health() is None


def test_health_reports_a_session_with_no_credential_set() -> None:
    """The one fault a health check exists to surface before anything is asked for."""
    credentials, _ = store(read_error=ERROR_NO_SUCH_LOGON_SESSION)
    assert credentials.health() is StoreFault.NO_CREDENTIAL_SET


def test_health_writes_nothing() -> None:
    """A health check that wrote would leave a credential behind on every start-up."""
    credentials, library = store()
    credentials.health()
    assert library.stored == {}


def test_the_domain_bound_and_the_platform_bound_are_the_same_number_of_bytes() -> None:
    """The property `BLOB_ENCODING` exists to hold, asserted rather than assumed.

    This test is why the encoding is UTF-8. Under UTF-16 little-endian — the
    obvious choice, and what most Windows credential tooling writes — an ASCII
    secret encodes to twice its length, so a value of exactly
    `MAX_SECRET_BYTES` characters satisfies `SecretValue` and produces a blob the
    platform refuses. An API key is ASCII, so that was the ordinary case.

    Checked across a range rather than at one length, and including non-ASCII, so
    that an encoding whose expansion depends on the input cannot pass by being
    tried only on the half that happens to agree.
    """
    for material in ("x" * MAX_SECRET_BYTES, "é" * (MAX_SECRET_BYTES // 2), "key-0000"):
        assert len(material.encode(BLOB_ENCODING)) == len(material.encode("utf-8"))


def test_a_value_at_the_ceiling_is_written_rather_than_refused() -> None:
    """The consequence of the encodings agreeing: the advertised limit is the real one."""
    credentials, library = store()
    assert credentials.store(REFERENCE, SecretValue("x" * MAX_SECRET_BYTES)) is None
    assert len(next(iter(library.stored.values()))) == MAX_SECRET_BYTES


def test_the_adapter_still_refuses_an_oversized_encoded_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The re-check is redundant today and kept for the day the encoding changes.

    Simulated by forcing the encoding back to the one that caused the defect, so
    the guard is exercised rather than merely present. Without it, a phase that
    changed `BLOB_ENCODING` for interoperability would silently reintroduce a
    two-to-one gap between what the domain promises and what the platform allows.
    """
    monkeypatch.setattr("globin.adapters.secrets.BLOB_ENCODING", "utf-16-le")
    credentials, library = store()
    material = "x" * MAX_SECRET_BYTES
    assert credentials.store(REFERENCE, SecretValue(material)) is StoreFault.VALUE_TOO_LARGE
    assert library.stored == {}


# ---------------------------------------------------------------------------
# The store this host does not have
# ---------------------------------------------------------------------------


def test_the_unavailable_store_answers_every_question_with_the_same_fault() -> None:
    """What CI and every non-Windows interpreter gets, and it never raises."""
    absent = UnavailableSecretStore()
    assert absent.health() is StoreFault.BACKEND_UNAVAILABLE
    assert absent.resolve(REFERENCE).fault is StoreFault.BACKEND_UNAVAILABLE
    assert absent.store(REFERENCE, SecretValue(MATERIAL)) is StoreFault.BACKEND_UNAVAILABLE
    assert absent.delete(REFERENCE) is StoreFault.BACKEND_UNAVAILABLE


def test_the_unavailable_store_lists_nothing_rather_than_refusing() -> None:
    """Holding no GLOBIN credentials is a true answer, not an error."""
    assert UnavailableSecretStore().inventory() == ()


def test_the_real_store_lists_nothing_and_the_emptiness_is_owned() -> None:
    """Deliberately empty, and pinned so it cannot be forgotten.

    Enumerating would mean walking every credential the account holds, including
    every one written by unrelated software, to answer a question about GLOBIN.
    The required set is declared rather than discovered, and the declaration is
    Phase 029's.
    """
    credentials, _ = store()
    credentials.store(REFERENCE, SecretValue(MATERIAL))
    assert credentials.inventory() == ()


def test_the_factory_returns_something_that_satisfies_the_port_on_any_host() -> None:
    """Whichever half this machine gets, the caller sees one shape."""
    built = windows_credential_store()
    assert hasattr(built, "resolve")
    assert hasattr(built, "health")
    assert built.health() in {None, *list(StoreFault)}


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        pytest.param(ERROR_NOT_FOUND, StoreFault.ABSENT, id="absent"),
        pytest.param(
            ERROR_NO_SUCH_LOGON_SESSION, StoreFault.NO_CREDENTIAL_SET, id="no credential set"
        ),
        pytest.param(RPC_X_BAD_STUB_DATA, StoreFault.VALUE_TOO_LARGE, id="the undocumented one"),
        pytest.param(0, StoreFault.BACKEND_REFUSED, id="success is never mapped here"),
        pytest.param(5, StoreFault.BACKEND_REFUSED, id="access denied is not special-cased"),
    ],
)
def test_the_status_mapping_is_total(status: int, expected: StoreFault) -> None:
    """Every branch of the mapping, including the default."""
    assert _fault_for(status) is expected


def test_health_succeeds_when_the_probe_target_happens_to_exist() -> None:
    """The branch that frees the buffer and reports healthy.

    The probe reads a target GLOBIN never writes, so on a real host the answer is
    always `ERROR_NOT_FOUND`. The success branch is still real code — it frees
    the platform's allocation — and a branch nobody has seen run is
    indistinguishable from one that cannot.
    """
    credentials, library = store()
    library.stored[f"globin:health-probe:{SecretSlot.CURRENT.value}"] = b"anything"
    assert credentials.health() is None
    assert library.freed == 1
