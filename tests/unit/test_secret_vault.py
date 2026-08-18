"""The vault envelope as a value, with no platform anywhere in the file.

Everything here is pure: a filename derived from the one key builder, a digest
over a header and some ciphertext, and a reader that refuses six different ways
before anything would reach the cryptography. That the module under test can be
exercised with no Windows, no `ctypes` and no filesystem is the property the
split between `globin.domain.secret_vault` and `globin.adapters.secret_vault`
exists to produce.

**The digest tests are the ones that matter.** `phase_031_sources.md` S-04
records that the platform's own integrity check "may succeed with corrupted
output", so the envelope carries its own and it is checked first. A mutation that
skipped that check would still round-trip every happy path, which is why the
refusals are asserted individually rather than through one "a bad envelope
fails".
"""

import base64

import pytest

from globin.domain.identifiers import environment_id
from globin.domain.secret_vault import (
    DIGEST_FIELD,
    ENVIRONMENT_FIELD,
    KIND_FIELD,
    MAGIC_FIELD,
    MAX_PROTECTED_BYTES,
    NAME_FIELD,
    PROTECTED_FIELD,
    SLOT_FIELD,
    VAULT_MAGIC,
    VAULT_SCHEMA_VERSION,
    VAULT_SUFFIX,
    VERSION_FIELD,
    belongs_in_vault,
    encode_envelope,
    envelope_digest,
    read_envelope,
    vault_entropy,
    vault_filename,
)
from globin.domain.secrets import (
    MAX_SECRET_BYTES,
    SecretKind,
    SecretReference,
    SecretSlot,
    store_key,
)
from globin.errors import ValidationError

CIPHERTEXT = b"\x01\x02\x03 not-real-ciphertext"

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


def envelope(protected: bytes = CIPHERTEXT) -> dict[str, object]:
    """A well-formed envelope for the reference under test.

    Args:
        protected: What ciphertext to carry.

    Returns:
        The envelope.
    """
    return encode_envelope(REFERENCE, SecretSlot.CURRENT, protected)


# ---------------------------------------------------------------------------
# The filename
# ---------------------------------------------------------------------------


def test_the_filename_is_the_store_key_with_one_substitution() -> None:
    """One builder, projected — never a second scheme.

    `SECRET_STORE_CONTRACT.md` section 2 permits exactly one function mapping
    identity to a key and says nothing else composes one, anywhere. If the
    filename were built independently, a change to the key scheme would move the
    Credential Manager target and leave the vault addressing the old one.
    """
    key = store_key(REFERENCE, SecretSlot.CURRENT)
    assert vault_filename(REFERENCE, SecretSlot.CURRENT) == f"{key.replace(':', '.')}{VAULT_SUFFIX}"


def test_the_filename_holds_no_character_a_path_could_use() -> None:
    """The separator substitution is necessary, not cosmetic.

    The store key's separator is a colon, which Windows refuses in a filename and
    which `segment_problems` reads as a drive letter — so the key used unmodified
    would be refused by GLOBIN's own boundary check before the platform saw it.
    """
    name = vault_filename(REFERENCE)
    assert ":" not in name
    assert "/" not in name
    assert "\\" not in name


def test_two_slots_are_two_files() -> None:
    """Rotation needs somewhere to put the previous value.

    The four-step rotation moves the current envelope aside before writing the
    new one; if both slots resolved to one filename there would be nothing left
    to retire.
    """
    assert vault_filename(REFERENCE, SecretSlot.CURRENT) != vault_filename(
        REFERENCE, SecretSlot.PREVIOUS
    )


def test_two_environments_are_two_files() -> None:
    """Section 3's isolation has to hold on disk as well as in a target name."""
    assert vault_filename(REFERENCE) != vault_filename(OTHER)


# ---------------------------------------------------------------------------
# The digest, and what it is not
# ---------------------------------------------------------------------------


def test_the_digest_changes_when_the_ciphertext_does() -> None:
    """A truncated or edited file must not verify."""
    first = envelope_digest(
        environment="paper", kind="private_key", name="k", slot="current", protected=b"aaaa"
    )
    second = envelope_digest(
        environment="paper", kind="private_key", name="k", slot="current", protected=b"aaab"
    )
    assert first != second


def test_the_digest_changes_when_the_header_does() -> None:
    """An envelope re-addressed to another secret must not verify.

    Covering the header is what makes a copied file fail here as well as at the
    identity cross-check — two independent refusals for one mistake.
    """
    first = envelope_digest(
        environment="paper", kind="private_key", name="k", slot="current", protected=CIPHERTEXT
    )
    second = envelope_digest(
        environment="testnet", kind="private_key", name="k", slot="current", protected=CIPHERTEXT
    )
    assert first != second


def test_two_protections_of_one_secret_produce_different_digests() -> None:
    """The digest is not a fingerprint of the secret, and cannot become one.

    DPAPI derives a fresh session key per call (S-09), so the same plaintext
    protected twice yields different ciphertext. This asserts the consequence:
    the digest is a function of what was written, not of what was protected, so
    it cannot be used to test a guess. That is the distinction
    `SECRET_STORE_CONTRACT.md` section 5 turns on.
    """
    first = envelope(b"ciphertext-from-the-first-call")
    second = envelope(b"ciphertext-from-the-second-call")
    assert first[DIGEST_FIELD] != second[DIGEST_FIELD]


def test_the_entropy_is_bound_to_the_identity() -> None:
    """A copied envelope fails at the platform as well as at the header check."""
    first = vault_entropy(environment="paper", kind="private_key", name="k", slot="current")
    second = vault_entropy(environment="testnet", kind="private_key", name="k", slot="current")
    assert first != second
    assert len(first) == 32


def test_the_entropy_and_the_digest_are_not_the_same_bytes() -> None:
    """Domain separation: what is bound in must differ from what is written beside."""
    entropy = vault_entropy(environment="paper", kind="private_key", name="k", slot="current")
    digest = envelope_digest(
        environment="paper", kind="private_key", name="k", slot="current", protected=b""
    )
    assert entropy.hex() not in digest


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def test_the_envelope_carries_the_identity_and_the_ciphertext() -> None:
    """Every field is either the reference or the platform's output."""
    document = envelope()
    assert document[MAGIC_FIELD] == VAULT_MAGIC
    assert document[VERSION_FIELD] == VAULT_SCHEMA_VERSION
    assert document[ENVIRONMENT_FIELD] == "paper"
    assert document[KIND_FIELD] == "private_key"
    assert document[NAME_FIELD] == "venue_signing_key"
    assert document[SLOT_FIELD] == "current"


def test_the_envelope_has_no_field_a_plaintext_could_occupy() -> None:
    """The absence is the guarantee, and it is stronger than a rule.

    There is no field a caller could put material into even by mistake, which is
    why this asserts the exact key set rather than that some particular key is
    missing.
    """
    assert set(envelope()) == {
        MAGIC_FIELD,
        VERSION_FIELD,
        ENVIRONMENT_FIELD,
        KIND_FIELD,
        NAME_FIELD,
        SLOT_FIELD,
        PROTECTED_FIELD,
        DIGEST_FIELD,
    }


def test_an_empty_envelope_is_refused() -> None:
    """An envelope with no ciphertext protects nothing."""
    with pytest.raises(ValidationError, match="empty envelope"):
        encode_envelope(REFERENCE, SecretSlot.CURRENT, b"")


def test_an_oversized_envelope_is_refused() -> None:
    """A file replaced by something enormous is refused before it is read back."""
    with pytest.raises(ValidationError, match="at most"):
        encode_envelope(REFERENCE, SecretSlot.CURRENT, b"x" * (MAX_PROTECTED_BYTES + 1))


# ---------------------------------------------------------------------------
# Reading back, which is where the refusals live
# ---------------------------------------------------------------------------


def test_a_well_formed_envelope_returns_its_ciphertext() -> None:
    """The round trip, so the refusals below are not vacuously true."""
    assert read_envelope(envelope(), REFERENCE, SecretSlot.CURRENT) == CIPHERTEXT


def test_something_that_is_not_an_object_is_refused() -> None:
    """A JSON array is not half an envelope."""
    with pytest.raises(ValidationError, match="is an object"):
        read_envelope([1, 2, 3], REFERENCE, SecretSlot.CURRENT)


def test_a_foreign_document_is_refused_on_its_magic() -> None:
    """Refusing a document that is not a GLOBIN envelope rather than half-reading it."""
    document = envelope()
    document[MAGIC_FIELD] = "something.else"
    with pytest.raises(ValidationError, match="not a GLOBIN vault envelope"):
        read_envelope(document, REFERENCE, SecretSlot.CURRENT)


def test_a_later_schema_version_is_refused_rather_than_read_anyway() -> None:
    """Fails closed in both directions.

    A newer GLOBIN may mean something different by the same field name, and
    guessing is how a credential is silently misread.
    """
    document = envelope()
    document[VERSION_FIELD] = VAULT_SCHEMA_VERSION + 1
    with pytest.raises(ValidationError, match="refused rather than read anyway"):
        read_envelope(document, REFERENCE, SecretSlot.CURRENT)


@pytest.mark.parametrize(
    "field",
    [ENVIRONMENT_FIELD, KIND_FIELD, NAME_FIELD, SLOT_FIELD],
)
def test_an_envelope_naming_another_secret_is_refused(field: str) -> None:
    """Where `ENVIRONMENT_MISMATCH` and `KIND_MISMATCH` acquire a producing path.

    The Credential Manager gets both free, because the environment and the kind
    are components of its target name and a mismatch simply cannot resolve. A
    file has no such property: it can be copied from one environment's vault into
    another's, keeping its contents and taking a new name.
    """
    document = envelope()
    document[field] = "elsewhere"
    with pytest.raises(ValidationError, match="addresses exactly one secret"):
        read_envelope(document, REFERENCE, SecretSlot.CURRENT)


def test_an_envelope_with_no_material_is_refused() -> None:
    """An envelope whose protected field was emptied is not an absent envelope."""
    document = envelope()
    document[PROTECTED_FIELD] = ""
    with pytest.raises(ValidationError, match="no protected material"):
        read_envelope(document, REFERENCE, SecretSlot.CURRENT)


def test_material_that_is_not_base64_is_refused() -> None:
    """A hand-edited file fails here rather than at the platform."""
    document = envelope()
    document[PROTECTED_FIELD] = "not base64 at all!!"
    with pytest.raises(ValidationError, match="not decodable"):
        read_envelope(document, REFERENCE, SecretSlot.CURRENT)


def test_a_tampered_envelope_fails_its_own_digest() -> None:
    """The check the platform's documentation says not to rely on it for.

    S-04: unprotection "may succeed with corrupted output", so an envelope whose
    ciphertext was edited must be refused by GLOBIN before the platform is asked.
    """
    document = envelope()
    document[DIGEST_FIELD] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="failed its own integrity check"):
        read_envelope(document, REFERENCE, SecretSlot.CURRENT)


def test_a_truncated_ciphertext_fails_the_digest() -> None:
    """Truncation is corruption, and is caught by the same check."""
    document = envelope()
    document[PROTECTED_FIELD] = base64.b64encode(CIPHERTEXT[:-1]).decode("ascii")
    with pytest.raises(ValidationError, match="failed its own integrity check"):
        read_envelope(document, REFERENCE, SecretSlot.CURRENT)


def test_an_envelope_carrying_too_much_is_refused_before_the_digest() -> None:
    """The size bound runs before the hash, so an enormous file is not hashed."""
    document = envelope()
    document[PROTECTED_FIELD] = base64.b64encode(b"x" * (MAX_PROTECTED_BYTES + 1)).decode("ascii")
    with pytest.raises(ValidationError, match="outside 1 to"):
        read_envelope(document, REFERENCE, SecretSlot.CURRENT)


# ---------------------------------------------------------------------------
# The admission rule
# ---------------------------------------------------------------------------


def test_the_two_mechanisms_are_disjoint_by_arithmetic() -> None:
    """No value belongs to both mechanisms, and none belongs to neither.

    This is what keeps a second store from becoming a second answer to one
    question, and it is why the ceiling is passed in rather than imported twice.
    """
    assert not belongs_in_vault(MAX_SECRET_BYTES, MAX_SECRET_BYTES)
    assert belongs_in_vault(MAX_SECRET_BYTES + 1, MAX_SECRET_BYTES)


def test_the_admission_rule_reads_the_store_own_ceiling() -> None:
    """An RSA-4096 PEM key does not fit the store, which is why the vault exists.

    `phase_028_sources.md` S-11 measured it at 3324 bytes against a 2560-byte
    ceiling. That is not scope Phase 028 declined; it is scope Phase 028
    discovered it could not have.
    """
    assert belongs_in_vault(3324, MAX_SECRET_BYTES)
