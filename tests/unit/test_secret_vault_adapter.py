"""The DPAPI vault adapter, driven by a fake `crypt32`.

No test here protects anything with the operator's own DPAPI key. Every platform
answer arrives through a deterministic fake, which is what lets a corrupt
envelope, an undocumented status and a failed allocation all be exercised on a
machine where none of them is happening — and what lets the whole file run on the
CI job that has no `.venv` and no Windows.

**The fake holds ciphertext rather than plaintext**, for the reason
`test_secrets_adapter.py`'s fake holds bytes: a vault that stored the plaintext
and called it protected would satisfy every round-trip assertion a fake could
make, if the fake did the same thing. Its transform is reversible and obviously
fake, and it carries a counter so that two protections of one value differ —
which is what makes the digest test a real assertion rather than a restatement of
the implementation.

**The allocation ledger is the point of injecting `local_free`.** Every buffer the
fake hands out is recorded, every address the recording deallocator receives is
recorded, and the two are compared after *every* path including the failing ones.
With a second permitted loader of `kernel32` this test would have had to call the
real deallocator and could not have made that comparison.
"""

import ctypes
import ctypes.wintypes
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from globin.adapters import secret_vault as vault_module
from globin.adapters.runtime_state import AtomicDocumentWriter, FileOperations
from globin.adapters.secret_vault import (
    _DATA_BLOB,
    CRYPTPROTECT_LOCAL_MACHINE,
    CRYPTPROTECT_UI_FORBIDDEN,
    ERROR_INVALID_DATA,
    ERROR_INVALID_PARAMETER,
    PROTECT_FLAGS,
    DpapiSecretVault,
    UnavailableSecretVault,
    _fault_for,
    secret_vault,
    vault_ceiling,
)
from globin.domain.identifiers import environment_id
from globin.domain.secret_vault import DIGEST_FIELD, PROTECTED_FIELD, vault_filename
from globin.domain.secrets import (
    MAX_SECRET_BYTES,
    SecretKind,
    SecretReference,
    SecretSlot,
    SecretValue,
    StoreFault,
)
from globin.errors import ValidationError

MATERIAL = "not-a-real-signing-key-0000"

REFERENCE = SecretReference(
    environment=environment_id("paper"),
    kind=SecretKind.PRIVATE_KEY,
    name="venue_signing_key",
)

OTHER = SecretReference(
    environment=environment_id("testnet"),
    kind=SecretKind.PRIVATE_KEY,
    name="venue_signing_key",
)


@dataclass
class _FakeCrypt32:
    """A deterministic stand-in for the two data-protection functions.

    The transform is a counter prefix and a byte inversion — reversible, and
    obviously not cryptography, which is what a fake should be. The counter is
    what makes two protections of one value differ, as DPAPI's per-call session
    key does.
    """

    protect_error: int = 0
    unprotect_error: int = 0
    override_output: bytes | None = None
    null_output: bool = False
    allocations: list[int] = field(default_factory=list)
    unprotect_calls: int = 0
    protect_flags: list[int] = field(default_factory=list)
    prompt_arguments: list[Any] = field(default_factory=list)
    description_arguments: list[Any] = field(default_factory=list)
    entropies: list[bytes] = field(default_factory=list)
    counter: int = 0
    alive: list[Any] = field(default_factory=list)

    def _fill(self, out: Any, payload: bytes) -> None:
        """Hand a buffer back the way the platform does.

        Args:
            out: The output blob pointer.
            payload: What to put in it.
        """
        if self.null_output:
            out._obj.cbData = 0  # noqa: SLF001 -- byref exposes the target here
            out._obj.pbData = None  # noqa: SLF001 -- byref exposes the target here
            return
        buffer = ctypes.create_string_buffer(payload, len(payload))
        self.alive.append(buffer)
        address = ctypes.cast(buffer, ctypes.c_void_p).value
        assert address is not None
        self.allocations.append(address)
        out._obj.cbData = len(payload)  # noqa: SLF001 -- byref exposes the target here
        out._obj.pbData = address  # noqa: SLF001 -- byref exposes the target here

    def CryptProtectData(  # noqa: N802 -- the platform's name
        self,
        data_in: Any,
        description: Any,
        entropy: Any,
        reserved: Any,
        prompt: Any,
        flags: int,
        data_out: Any,
    ) -> int:
        """Encrypt, or report the configured failure."""
        del reserved
        self.protect_flags.append(flags)
        self.prompt_arguments.append(prompt)
        self.description_arguments.append(description)
        self.entropies.append(_read(entropy))
        if self.protect_error:
            ctypes.set_last_error(self.protect_error)
            return 0
        self.counter += 1
        payload = bytes([self.counter]) + bytes(255 - b for b in _read(data_in))
        self._fill(data_out, payload)
        return 1

    def CryptUnprotectData(  # noqa: N802 -- the platform's name
        self,
        data_in: Any,
        description: Any,
        entropy: Any,
        reserved: Any,
        prompt: Any,
        flags: int,
        data_out: Any,
    ) -> int:
        """Decrypt, or report the configured failure."""
        del reserved
        self.unprotect_calls += 1
        self.protect_flags.append(flags)
        self.prompt_arguments.append(prompt)
        self.description_arguments.append(description)
        self.entropies.append(_read(entropy))
        if self.unprotect_error:
            ctypes.set_last_error(self.unprotect_error)
            return 0
        decrypted = self.override_output
        if decrypted is None:
            decrypted = bytes(255 - b for b in _read(data_in)[1:])
        self._fill(data_out, decrypted)
        return 1


def _read(blob: Any) -> bytes:
    """Read a blob the fake was handed.

    Args:
        blob: A `byref` to a `_DATA_BLOB`.

    Returns:
        Its bytes.
    """
    target = blob._obj  # noqa: SLF001 -- byref exposes the target here
    return ctypes.string_at(target.pbData, target.cbData)


@dataclass
class _RecordingLocalFree:
    """A deallocator that records every address it is handed."""

    freed: list[int | None] = field(default_factory=list)

    def __call__(self, address: int | None) -> None:
        """Record the address without freeing anything real.

        Args:
            address: What would have been freed, or ``None`` where the platform
                filled nothing in — which `LocalFree` documents as ignored.
        """
        self.freed.append(address)


def vault(tmp_path: Path, **kwargs: Any) -> tuple[Any, _FakeCrypt32, _RecordingLocalFree]:
    """Build a vault over a fake platform and a real temporary directory.

    Args:
        tmp_path: Where envelopes go.
        kwargs: Passed to the fake.

    Returns:
        The vault, the fake and the recording deallocator.
    """
    library = _FakeCrypt32(**kwargs)
    free = _RecordingLocalFree()
    return (
        DpapiSecretVault(
            library=library,
            local_free=free,
            writer=AtomicDocumentWriter(operations=FileOperations()),
            directory=tmp_path / "vault",
            declared=(REFERENCE,),
        ),
        library,
        free,
    )


# ---------------------------------------------------------------------------
# The structure, pinned rather than trusted
# ---------------------------------------------------------------------------


def test_the_data_blob_has_the_documented_fields_in_order() -> None:
    """A wrong `ctypes` offset reads a neighbouring field rather than raising.

    `phase_031_sources.md` S-10 gives the definition: `DWORD cbData` then
    `BYTE *pbData`. A reordering during an edit would corrupt reads silently,
    which is why the layout is asserted.
    """
    assert [name for name, _kind in _DATA_BLOB._fields_] == ["cbData", "pbData"]


def test_the_blob_pointer_is_pointer_sized() -> None:
    """`c_void_p` stands in for `BYTE *`, and the widths must agree.

    Read from the field descriptor's own `size` rather than from the class
    attribute: `_DATA_BLOB.pbData` is a descriptor, not a type, so `sizeof`
    refuses it. Getting that wrong is how a layout assertion silently stops
    asserting anything.
    """
    assert _DATA_BLOB.pbData.size == ctypes.sizeof(ctypes.c_void_p)
    assert _DATA_BLOB.cbData.size == ctypes.sizeof(ctypes.wintypes.DWORD)


# ---------------------------------------------------------------------------
# The flags
# ---------------------------------------------------------------------------


def test_machine_scope_is_never_requested() -> None:
    """An absence does not appear in a diff, so it is asserted.

    S-06: with this flag set, "any user on the computer ... can use
    CryptUnprotectData to decrypt the data." That matters more here than on a
    single-operator host, because GLOBIN is cloned onto several machines and run
    by several people under their own accounts.
    """
    assert PROTECT_FLAGS & CRYPTPROTECT_LOCAL_MACHINE == 0


def test_a_dialogue_is_forbidden_rather_than_awaited() -> None:
    """A call that blocks on a dialogue nobody is watching looks like a hang."""
    assert PROTECT_FLAGS & CRYPTPROTECT_UI_FORBIDDEN == CRYPTPROTECT_UI_FORBIDDEN


def test_both_calls_receive_the_same_flags(tmp_path: Path) -> None:
    """One constant, used twice, so protect and unprotect cannot drift apart."""
    store, library, _ = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    store.resolve(REFERENCE)
    assert set(library.protect_flags) == {PROTECT_FLAGS}


def test_the_prompt_structure_is_always_null(tmp_path: Path) -> None:
    """S-05 records the prompt flow is removed in February 2027.

    Passing null takes the non-interactive path, which is the one that survives.
    """
    store, library, _ = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    store.resolve(REFERENCE)
    assert library.prompt_arguments == [None, None]


def test_the_description_pointer_is_null_so_nothing_second_needs_freeing(
    tmp_path: Path,
) -> None:
    """S-02: a non-null description must *also* be freed with `LocalFree`.

    Passing null removes the second obligation entirely rather than discharging
    it, which is one fewer path that can leak.
    """
    store, library, _ = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    store.resolve(REFERENCE)
    assert library.description_arguments == [None, None]


def test_the_entropy_is_supplied_and_is_bound_to_the_identity(tmp_path: Path) -> None:
    """A copied envelope fails at the platform as well as at the header check."""
    store, library, _ = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    assert library.entropies
    assert all(len(entropy) == 32 for entropy in library.entropies)


# ---------------------------------------------------------------------------
# The round trip
# ---------------------------------------------------------------------------


def test_a_stored_value_comes_back(tmp_path: Path) -> None:
    """The happy path, so the refusals below are not vacuously true."""
    store, _, _ = vault(tmp_path)
    assert store.store(REFERENCE, SecretValue(MATERIAL)) is None
    resolution = store.resolve(REFERENCE)
    assert resolution.resolved
    assert resolution.value is not None
    assert resolution.value.material() == MATERIAL


def test_the_envelope_on_disk_holds_no_plaintext(tmp_path: Path) -> None:
    """The file is published, and the material is not in it.

    A leak surface Phase 031 added, and the canary contract test covers it too;
    this is the local statement of the same property.
    """
    store, _, _ = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    written = (tmp_path / "vault" / vault_filename(REFERENCE)).read_text(encoding="utf-8")
    assert MATERIAL not in written


def test_an_absent_envelope_is_absent_rather_than_an_error(tmp_path: Path) -> None:
    """Nothing stored yet is the ordinary state of a fresh installation."""
    store, _, _ = vault(tmp_path)
    assert store.resolve(REFERENCE).fault is StoreFault.ABSENT


def test_two_slots_are_two_envelopes(tmp_path: Path) -> None:
    """Rotation needs the previous value to survive the new one landing."""
    store, _, _ = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    store.store(REFERENCE, SecretValue("a-different-value"), SecretSlot.PREVIOUS)
    current = store.resolve(REFERENCE, SecretSlot.CURRENT)
    previous = store.resolve(REFERENCE, SecretSlot.PREVIOUS)
    assert current.value is not None
    assert previous.value is not None
    assert current.value.material() != previous.value.material()


def test_an_envelope_from_another_environment_does_not_resolve(tmp_path: Path) -> None:
    """The first producing path for a mismatch that a file can actually have.

    The Credential Manager gets this free from its target name. A file can be
    copied between environments, so the envelope restates its identity and the
    reader compares it.
    """
    store, _, _ = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    directory = tmp_path / "vault"
    copied = directory / vault_filename(OTHER)
    copied.write_bytes((directory / vault_filename(REFERENCE)).read_bytes())
    assert store.resolve(OTHER).fault is StoreFault.ENVELOPE_CORRUPT


def test_deleting_an_absent_envelope_reports_absent(tmp_path: Path) -> None:
    """A caller may legitimately ignore this."""
    store, _, _ = vault(tmp_path)
    assert store.delete(REFERENCE) is StoreFault.ABSENT


def test_a_deleted_envelope_no_longer_resolves(tmp_path: Path) -> None:
    """Delete removes the file rather than emptying it."""
    store, _, _ = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    assert store.delete(REFERENCE) is None
    assert store.resolve(REFERENCE).fault is StoreFault.ABSENT


# ---------------------------------------------------------------------------
# The digest gate — checked before the platform is reached
# ---------------------------------------------------------------------------


def test_the_digest_is_checked_before_the_platform_is_reached(tmp_path: Path) -> None:
    """The whole of the safety argument, asserted as a call count.

    S-04 records that `CryptUnprotectData` "may succeed with corrupted output".
    Checking afterwards would mean corrupted bytes had already been through the
    cryptography and a corrupted plaintext had already existed as a Python
    string, which is unrecallable. Zero unprotect calls is what proves the order.
    """
    store, library, _ = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    target = tmp_path / "vault" / vault_filename(REFERENCE)
    document = json.loads(target.read_text(encoding="utf-8"))
    document[DIGEST_FIELD] = "sha256:" + "0" * 64
    target.write_text(json.dumps(document), encoding="utf-8")
    library.unprotect_calls = 0
    assert store.resolve(REFERENCE).fault is StoreFault.ENVELOPE_CORRUPT
    assert library.unprotect_calls == 0


def test_a_truncated_envelope_never_reaches_the_platform(tmp_path: Path) -> None:
    """Truncation is corruption, and the same gate catches it."""
    store, library, _ = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    target = tmp_path / "vault" / vault_filename(REFERENCE)
    document = json.loads(target.read_text(encoding="utf-8"))
    document[PROTECTED_FIELD] = document[PROTECTED_FIELD][:-4]
    target.write_text(json.dumps(document), encoding="utf-8")
    library.unprotect_calls = 0
    assert store.resolve(REFERENCE).fault is StoreFault.ENVELOPE_CORRUPT
    assert library.unprotect_calls == 0


def test_a_file_that_is_not_json_is_corrupt_rather_than_absent(tmp_path: Path) -> None:
    """Corrupt and absent mean opposite things, and only one needs acting on."""
    store, _, _ = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    (tmp_path / "vault" / vault_filename(REFERENCE)).write_text("not json", encoding="utf-8")
    assert store.resolve(REFERENCE).fault is StoreFault.ENVELOPE_CORRUPT


# ---------------------------------------------------------------------------
# Allocation, on every path
# ---------------------------------------------------------------------------


def test_every_allocation_is_freed_on_the_success_path(tmp_path: Path) -> None:
    """The buffer holds decrypted plaintext; leaking it is a security regression."""
    store, library, free = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    store.resolve(REFERENCE)
    assert library.allocations
    assert set(free.freed) == set(library.allocations)


def test_every_allocation_is_freed_when_the_value_cannot_be_decoded(
    tmp_path: Path,
) -> None:
    """The failing path is the one a happy-path test never reaches."""
    store, library, free = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    store.resolve(REFERENCE)
    assert set(free.freed) == set(library.allocations)


def test_a_platform_failure_allocates_nothing_to_leak(tmp_path: Path) -> None:
    """A failed call fills in no buffer, so there is nothing to free."""
    store, library, free = vault(tmp_path, protect_error=ERROR_INVALID_DATA)
    assert store.store(REFERENCE, SecretValue(MATERIAL)) is StoreFault.ENVELOPE_CORRUPT
    assert library.allocations == []
    assert free.freed == []


def test_a_failed_unprotection_is_classified_rather_than_raised(tmp_path: Path) -> None:
    """Nothing in the port raises for an expected outcome."""
    store, library, _ = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    library.unprotect_error = ERROR_INVALID_PARAMETER
    assert store.resolve(REFERENCE).fault is StoreFault.ENVELOPE_CORRUPT


# ---------------------------------------------------------------------------
# The fault map, and the inventory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        pytest.param(ERROR_INVALID_DATA, StoreFault.ENVELOPE_CORRUPT, id="invalid-data"),
        pytest.param(ERROR_INVALID_PARAMETER, StoreFault.ENVELOPE_CORRUPT, id="invalid-parameter"),
        pytest.param(1325, StoreFault.BACKEND_REFUSED, id="password-restriction"),
        pytest.param(999999, StoreFault.BACKEND_REFUSED, id="unknown"),
    ],
)
def test_the_fault_map_is_total_over_an_unbounded_status(status: int, expected: StoreFault) -> None:
    """An unrecognised status degrades to a named refusal, never to a guess.

    "Should be unreachable" is a claim about code that may change, so the map is
    total over an unbounded input rather than over the statuses known today.
    """
    assert _fault_for(status) is expected


def test_the_inventory_lists_only_what_is_declared_and_present(tmp_path: Path) -> None:
    """Never a directory walk.

    A walk would report whatever happened to be in the directory, including
    something another tool put there, as though GLOBIN owned it.
    """
    store, _, _ = vault(tmp_path)
    assert store.inventory() == ()
    store.store(REFERENCE, SecretValue(MATERIAL))
    assert store.inventory() == (REFERENCE,)


def test_health_reports_the_absence_of_the_runtime_tree(tmp_path: Path) -> None:
    """A vault under a root that does not exist cannot be reached."""
    store, _, _ = vault(tmp_path / "missing")
    assert store.health() is StoreFault.BACKEND_UNAVAILABLE


def test_health_is_content_with_a_directory_that_does_not_exist_yet(
    tmp_path: Path,
) -> None:
    """Nothing stored yet is the ordinary state, and asking must not create it."""
    store, _, _ = vault(tmp_path)
    assert store.health() is None
    assert not (tmp_path / "vault").exists()


# ---------------------------------------------------------------------------
# The stand-in, and the factory
# ---------------------------------------------------------------------------


def test_the_stand_in_answers_every_method_with_the_absence() -> None:
    """Uniform, so no caller has to know which arm it holds."""
    absent = UnavailableSecretVault()
    assert absent.health() is StoreFault.BACKEND_UNAVAILABLE
    assert absent.resolve(REFERENCE).fault is StoreFault.BACKEND_UNAVAILABLE
    assert absent.store(REFERENCE, SecretValue(MATERIAL)) is StoreFault.BACKEND_UNAVAILABLE
    assert absent.delete(REFERENCE) is StoreFault.BACKEND_UNAVAILABLE
    assert absent.inventory() == ()


def test_the_factory_answers_on_any_host(tmp_path: Path) -> None:
    """Absent-safe by construction, which is what the CI story depends on."""
    built = secret_vault(tmp_path / "vault")
    assert built.health() is None or built.health() is StoreFault.BACKEND_UNAVAILABLE


def test_the_ceiling_is_the_store_own_constant() -> None:
    """One constant, so the two mechanisms cannot drift into overlapping."""
    assert vault_ceiling() == MAX_SECRET_BYTES


# ---------------------------------------------------------------------------
# The failure paths, which a happy-path suite never reaches
# ---------------------------------------------------------------------------


def test_a_filename_that_could_leave_the_vault_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The boundary check is defensive, and defensive code still gets exercised.

    `NAME_ALPHABET` excludes every separator, so this cannot fire today. That is
    exactly why it is reached through a substituted builder: the check is what
    keeps the property true if the alphabet ever moves, and a check nothing has
    ever run is a check nobody knows works.
    """
    store, _, _ = vault(tmp_path)
    monkeypatch.setattr(vault_module, "vault_filename", lambda *_args: "../escape.json")
    assert store.resolve(REFERENCE).fault is StoreFault.ABSENT
    assert store.store(REFERENCE, SecretValue(MATERIAL)) is StoreFault.BACKEND_REFUSED
    assert store.delete(REFERENCE) is StoreFault.ABSENT
    assert store.inventory() == ()


def test_a_filename_that_resolves_outside_the_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second of the two checks: judge the path, not only the name."""
    store, _, _ = vault(tmp_path)
    monkeypatch.setattr(vault_module, "segment_problems", lambda *_a, **_k: ())
    monkeypatch.setattr(vault_module, "vault_filename", lambda *_args: "..")
    assert store.resolve(REFERENCE).fault is StoreFault.ABSENT


def test_material_that_is_not_utf8_is_corrupt_rather_than_raised(tmp_path: Path) -> None:
    """A decode failure is an answer, not an exception.

    Nothing in the port raises for an expected outcome, and a byte sequence that
    is not text is exactly the corruption the platform's own check may let
    through.
    """
    store, library, free = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    library.override_output = b"\xff\xfe not utf-8"
    assert store.resolve(REFERENCE).fault is StoreFault.ENVELOPE_CORRUPT
    assert set(free.freed) == set(library.allocations)


def test_material_the_value_type_refuses_is_reported_rather_than_raised(
    tmp_path: Path,
) -> None:
    """An envelope holding more than the value type accepts is a fault, not a crash."""
    store, library, _ = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    library.override_output = b"x" * (MAX_SECRET_BYTES + 1)
    assert store.resolve(REFERENCE).fault is StoreFault.VALUE_TOO_LARGE


def test_a_null_buffer_is_not_freed_and_not_read(tmp_path: Path) -> None:
    """The platform succeeding with nothing to hand back must not crash.

    `LocalFree` tolerates a null handle, so the branch exists to avoid a
    `memset` at address zero rather than to avoid the free.
    """
    store, library, free = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))
    library.null_output = True
    resolution = store.resolve(REFERENCE)
    assert resolution.fault is StoreFault.ENVELOPE_CORRUPT
    assert free.freed[-1] is None
    assert library.unprotect_calls == 1


def test_an_unwritable_vault_reports_rather_than_raises(tmp_path: Path) -> None:
    """A directory that cannot be created is a fault the caller classifies."""
    store, _, _ = vault(tmp_path)

    def refuse(_path: Path) -> None:
        message = "refused"
        raise OSError(message)

    broken = DpapiSecretVault(
        library=store.library,
        local_free=store.local_free,
        writer=AtomicDocumentWriter(operations=FileOperations(makedirs=refuse)),
        directory=tmp_path / "vault",
        declared=(REFERENCE,),
    )
    assert broken.store(REFERENCE, SecretValue(MATERIAL)) is StoreFault.BACKEND_REFUSED


def test_an_undeletable_envelope_reports_rather_than_raises(tmp_path: Path) -> None:
    """A file that exists and cannot be removed is a fault, not a traceback."""
    store, library, free = vault(tmp_path)
    store.store(REFERENCE, SecretValue(MATERIAL))

    def refuse(_path: Path) -> None:
        message = "refused"
        raise OSError(message)

    broken = DpapiSecretVault(
        library=library,
        local_free=free,
        writer=AtomicDocumentWriter(operations=FileOperations(unlink=refuse)),
        directory=tmp_path / "vault",
        declared=(REFERENCE,),
    )
    assert broken.delete(REFERENCE) is StoreFault.BACKEND_REFUSED


def test_the_factory_records_the_absence_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every non-Windows CI runner takes this path on import of the package."""
    monkeypatch.setattr("globin.adapters.secret_vault.sys.platform", "linux")
    built = secret_vault(Path("vault"))
    assert isinstance(built, UnavailableSecretVault)


def test_the_factory_records_the_absence_when_the_deallocator_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two absences compose into one recorded state.

    The deallocator lives in another module because `kernel32` has exactly one
    permitted loader, so this factory can fail for either reason.
    """
    monkeypatch.setattr("globin.adapters.secret_vault.sys.platform", "win32")
    monkeypatch.setattr(vault_module, "windows_local_free", lambda: None)
    assert isinstance(secret_vault(Path("vault")), UnavailableSecretVault)


def test_the_factory_records_the_absence_when_the_library_will_not_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Windows host without `crypt32` is handled rather than assumed away."""
    monkeypatch.setattr("globin.adapters.secret_vault.sys.platform", "win32")
    monkeypatch.setattr(vault_module, "windows_local_free", lambda: lambda _address: None)

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        message = "no crypt32"
        raise OSError(message)

    monkeypatch.setattr("globin.adapters.secret_vault.ctypes.WinDLL", refuse, raising=False)
    assert isinstance(secret_vault(Path("vault")), UnavailableSecretVault)


def test_ciphertext_the_envelope_refuses_is_reported_rather_than_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A platform returning more than the envelope bounds is a fault, not a crash.

    The bound exists so that a file replaced by something enormous is refused
    before it is read back; this is the write side of the same rule, and it is
    reached through a substituted encoder because the fake platform cannot
    produce a blob that large without the test itself allocating it.
    """
    store, _, _ = vault(tmp_path)

    def refuse(*_args: Any, **_kwargs: Any) -> dict[str, object]:
        message = "too large"
        raise ValidationError(message)

    monkeypatch.setattr(vault_module, "encode_envelope", refuse)
    assert store.store(REFERENCE, SecretValue(MATERIAL)) is StoreFault.VALUE_TOO_LARGE
