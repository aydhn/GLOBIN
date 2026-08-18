"""What a protected secret envelope is, and what may be believed about one.

This module holds the *file format* the Phase 031 vault writes, and nothing that
touches a platform. It is separate from :mod:`globin.domain.secrets` because that
module's docstring says it holds "the distinction §1 draws and nothing else", and
an on-disk representation is a different subject.

**The envelope carries its own integrity check, and that is not belt-and-braces.**
``CryptUnprotectData``'s own documentation states that on corruption it "may
return ERROR_INVALID_DATA, ERROR_INVALID_PARAMETER, **or in some cases may
succeed with corrupted output**", that applications "should not rely on a
specific error code to detect data tampering", and that robust detection needs
"additional integrity checks at the application level"
(``docs/research/phase_031_sources.md`` S-04). Delegating the question to the
platform would therefore be delegating it to something the vendor says will not
answer it reliably.

**The digest is not a fingerprint of the secret and cannot become one.** DPAPI
derives a fresh session key per call (S-09), so protecting one value twice
produces different ciphertext and therefore different digests. It is not a
function of the plaintext, so it cannot be used to test a guess — which is what
``SECRET_STORE_CONTRACT.md`` §5 constrains. A digest over the *plaintext* was
refused rather than overlooked: it would close the one gap this one cannot, and
would do so by writing an offline-guessable oracle into a file that anybody
holding the file could then attack at their own speed.

**It is unkeyed, and it is stored beside what it covers.** It detects
*corruption*. It does not detect *tampering* by somebody who can write the file,
and claiming otherwise would be the "appearance of protection without the
substance" ``SECURITY_BASELINE.md`` §2 names. That adversary is already this
user, whom ``phase_020_sources.md`` S-09 records can read what this user stored
in any case.

What this module does not decide: where the vault directory is (Phase 031's
adapter, from :class:`~globin.domain.runtime_state.RuntimeLayout`), which
provider holds which reference (:class:`~globin.domain.secrets.SecretLocator`),
and what a key type means for signing (Phases 033 onwards).
"""

import base64
import binascii
import hashlib
from typing import Final

from globin.domain.secrets import (
    KEY_SEPARATOR,
    SecretReference,
    SecretSlot,
    store_key,
)
from globin.errors import ValidationError

VAULT_MAGIC: Final[str] = "globin.secret.vault"
"""What every envelope announces itself as.

Refusing a JSON object that is not a GLOBIN envelope, rather than half-reading
one. The value is dotted rather than a byte sequence because the envelope is
JSON: a magic number belongs to a binary format, and a string is what a reader of
this file can check by eye.
"""

VAULT_SCHEMA_VERSION: Final[int] = 1
"""Which shape the envelope is written in.

Fails closed **in both directions**, the way
:func:`~globin.domain.config_evidence.check_schema_version` does: an envelope
announcing a later version is refused rather than read anyway, because a newer
GLOBIN may mean something different by the same field name and guessing is how a
credential is silently misread.
"""

VAULT_SUFFIX: Final[str] = ".vault.json"
"""What an envelope file is called, after its identity.

Doubled deliberately. ``.json`` says what a reader may parse it as, and
``.vault`` says what it is, so a directory listing distinguishes an envelope from
any other document without opening one.
"""

FILENAME_SEPARATOR: Final[str] = "."
"""What replaces :data:`~globin.domain.secrets.KEY_SEPARATOR` in a filename.

Necessary rather than cosmetic. The store key's separator is ``":"``, which
Windows refuses in a filename and which
:func:`~globin.domain.runtime_state.segment_problems` reads as a drive letter, so
a key used unmodified would be refused by GLOBIN's own boundary check before the
platform ever saw it.
"""

DIGEST_DOMAIN: Final[str] = "globin.secret.vault.digest.1"
"""What every envelope digest is prefixed with before hashing.

Domain separation, as :data:`~globin.domain.config_evidence.EVIDENCE_DIGEST_DOMAIN`
does it: two digests computed over different things must not be comparable by
accident, and a version in the domain string means a later change of what is
covered cannot collide with an older digest.
"""

ENTROPY_DOMAIN: Final[str] = "globin.secret.vault.entropy.1"
"""What the platform's optional entropy is derived from.

Separate from :data:`DIGEST_DOMAIN` so that the value bound into the protection
and the value written beside it are not the same bytes.
"""

MAX_PROTECTED_BYTES: Final[int] = 64 * 1024
"""The largest ciphertext an envelope may carry.

A bound on what will be read back, not a platform limit. DPAPI's overhead over a
plaintext bounded by :data:`~globin.domain.secrets.MAX_SECRET_BYTES` is a few
hundred bytes, so this is ample; what it prevents is an envelope file that has
been replaced by something enormous consuming memory before any check runs.
"""

MAGIC_FIELD: Final[str] = "magic"
VERSION_FIELD: Final[str] = "schema_version"
ENVIRONMENT_FIELD: Final[str] = "environment"
KIND_FIELD: Final[str] = "kind"
NAME_FIELD: Final[str] = "name"
SLOT_FIELD: Final[str] = "slot"
PROTECTED_FIELD: Final[str] = "protected"
DIGEST_FIELD: Final[str] = "digest"


def vault_filename(reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT) -> str:
    """What one reference's envelope is called on disk.

    Args:
        reference: Which secret.
        slot: Which copy of the material.

    Returns:
        A plain lowercase filename, for example
        ``globin.paper.api_key.venue_key.current.vault.json``.

    **A projection of** :func:`~globin.domain.secrets.store_key`, **not a second
    builder.** ``SECRET_STORE_CONTRACT.md`` §2 permits exactly one function
    mapping identity to a key and says nothing else composes one, anywhere. This
    applies one substitution to that function's output, so a filename and a
    Credential Manager target name can never disagree about which secret they
    address — and a change to the key scheme moves both at once.

    **The result is never parsed back.** An
    :class:`~globin.domain.identifiers.EnvironmentId` may itself contain a dot, so
    the segmentation is not reversible. Identity is carried by the envelope's own
    fields and cross-checked there; the filename is an address and nothing more.
    """
    key = store_key(reference, slot)
    return f"{key.replace(KEY_SEPARATOR, FILENAME_SEPARATOR)}{VAULT_SUFFIX}"


def _header(*, environment: str, kind: str, name: str, slot: str) -> str:
    """The identity fields, joined for hashing.

    Args:
        environment: The environment's text.
        kind: The kind's value.
        name: The secret's name.
        slot: The slot's value.

    Returns:
        One newline-joined string carrying the magic, the version and the four
        fields.

    Private, and shared by :func:`envelope_digest` and :func:`vault_entropy` so
    that the two cover the same fields by construction rather than by two lists
    somebody has to keep in step.
    """
    parts = (VAULT_MAGIC, str(VAULT_SCHEMA_VERSION), environment, kind, name, slot)
    return "\n".join(parts)


def envelope_digest(*, environment: str, kind: str, name: str, slot: str, protected: bytes) -> str:
    """A digest over the header and the ciphertext.

    Args:
        environment: The environment's text.
        kind: The kind's value.
        name: The secret's name.
        slot: The slot's value.
        protected: The platform's ciphertext.

    Returns:
        ``sha256:`` followed by the hexadecimal digest.

    Covers the magic, the schema version, all four identity fields and the
    protected bytes — so an envelope whose header was edited to address a
    different secret fails here, not only at the identity cross-check, and a
    truncated file fails before anything reaches the platform.

    See this module's docstring for why this is not a secret fingerprint and why
    a digest over the plaintext was refused.
    """
    header = _header(environment=environment, kind=kind, name=name, slot=slot)
    payload = f"{DIGEST_DOMAIN}\n{header}\n"
    digest = hashlib.sha256(payload.encode("utf-8") + protected)
    return f"sha256:{digest.hexdigest()}"


def vault_entropy(*, environment: str, kind: str, name: str, slot: str) -> bytes:
    """The optional entropy one protection is bound with.

    Args:
        environment: The environment's text.
        kind: The kind's value.
        name: The secret's name.
        slot: The slot's value.

    Returns:
        Thirty-two bytes derived from the header.

    **Binding, not secrecy, and blurring the two would be a false claim.** This
    repository is public (ADR-0046), so anything derived from source is known to
    anybody who wants it. What it buys is that an envelope copied into a
    different reference's filename fails to unprotect *at the platform* as well
    as failing the identity cross-check — two independent refusals for one
    mistake, one of which does not depend on GLOBIN's own code being correct.
    """
    header = _header(environment=environment, kind=kind, name=name, slot=slot)
    payload = f"{ENTROPY_DOMAIN}\n{header}"
    return hashlib.sha256(payload.encode("utf-8")).digest()


def encode_envelope(
    reference: SecretReference, slot: SecretSlot, protected: bytes
) -> dict[str, object]:
    """Build the document that is published.

    Args:
        reference: Which secret this holds.
        slot: Which copy.
        protected: The platform's ciphertext.

    Returns:
        The envelope, ready for the atomic writer.

    Raises:
        ValidationError: If there is no ciphertext, or there is more of it than
            :data:`MAX_PROTECTED_BYTES`.

    **No field here can hold plaintext.** The identity fields are the reference,
    which ``SECRET_STORE_CONTRACT.md`` §1 states is ordinary data and safe in a
    file, an error message or a manifest; ``protected`` is the platform's output;
    ``digest`` is a function of those two. There is no field a caller could put
    material in even by mistake, which is a stronger guarantee than a rule saying
    they should not.
    """
    if not protected:
        msg = (
            f"the vault was asked to write an empty envelope for {reference.name!r}, "
            f"and an envelope with no ciphertext protects nothing"
        )
        raise ValidationError(msg)
    if len(protected) > MAX_PROTECTED_BYTES:
        msg = (
            f"a protected envelope may be at most {MAX_PROTECTED_BYTES} bytes, "
            f"and this one is {len(protected)}"
        )
        raise ValidationError(msg)
    environment = reference.environment.text
    kind = reference.kind.value
    return {
        MAGIC_FIELD: VAULT_MAGIC,
        VERSION_FIELD: VAULT_SCHEMA_VERSION,
        ENVIRONMENT_FIELD: environment,
        KIND_FIELD: kind,
        NAME_FIELD: reference.name,
        SLOT_FIELD: slot.value,
        PROTECTED_FIELD: base64.b64encode(protected).decode("ascii"),
        DIGEST_FIELD: envelope_digest(
            environment=environment,
            kind=kind,
            name=reference.name,
            slot=slot.value,
            protected=protected,
        ),
    }


def read_envelope(document: object, reference: SecretReference, slot: SecretSlot) -> bytes:
    """Read an envelope back, refusing anything that is not this one's.

    Args:
        document: What was parsed from the file.
        reference: Which secret was asked for.
        slot: Which copy was asked for.

    Returns:
        The protected bytes, ready for the platform.

    Raises:
        ValidationError: If it is not an object, carries the wrong magic,
            announces another schema version, names another reference, is not
            decodable, or fails its own digest.

    **The order is load-bearing: magic, version, identity, digest — and only then
    does the caller reach the platform.** ``CryptUnprotectData``'s Remarks state
    that its own integrity check may return either of two statuses "or in some
    cases may succeed with corrupted output", and that applications must not rely
    on a code to detect tampering. Checking afterwards would mean corrupted bytes
    had already been through the cryptography and a corrupted plaintext had
    already existed as a Python string, which is unrecallable. Checking first
    means neither ever happens.
    """
    if not isinstance(document, dict):
        held = type(document).__name__
        msg = f"a vault envelope is an object, and this holds a {held}"
        raise ValidationError(msg)
    magic = document.get(MAGIC_FIELD)
    if magic != VAULT_MAGIC:
        msg = f"{magic!r} is not a GLOBIN vault envelope; expected {VAULT_MAGIC!r}"
        raise ValidationError(msg)
    version = document.get(VERSION_FIELD)
    if version != VAULT_SCHEMA_VERSION:
        msg = (
            f"this envelope announces schema version {version!r} and this GLOBIN "
            f"writes {VAULT_SCHEMA_VERSION}; it is refused rather than read anyway"
        )
        raise ValidationError(msg)
    _refuse_other_identity(document, reference, slot)
    encoded = document.get(PROTECTED_FIELD)
    if not isinstance(encoded, str) or not encoded:
        msg = "this envelope carries no protected material"
        raise ValidationError(msg)
    try:
        protected = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as fault:
        msg = f"this envelope's protected material is not decodable: {fault}"
        raise ValidationError(msg) from fault
    if not protected or len(protected) > MAX_PROTECTED_BYTES:
        msg = (
            f"this envelope's protected material is {len(protected)} bytes, "
            f"outside 1 to {MAX_PROTECTED_BYTES}"
        )
        raise ValidationError(msg)
    expected = envelope_digest(
        environment=reference.environment.text,
        kind=reference.kind.value,
        name=reference.name,
        slot=slot.value,
        protected=protected,
    )
    if document.get(DIGEST_FIELD) != expected:
        msg = (
            "this envelope failed its own integrity check and was not decrypted; "
            "the platform's check is documented as unreliable, so this one refuses "
            "before the material is reached"
        )
        raise ValidationError(msg)
    return protected


def _refuse_other_identity(
    document: dict[str, object], reference: SecretReference, slot: SecretSlot
) -> None:
    """Refuse an envelope that names a different secret.

    Args:
        document: The parsed envelope.
        reference: What was asked for.
        slot: Which copy was asked for.

    Raises:
        ValidationError: If any identity field disagrees.

    **This is where** :attr:`~globin.domain.secrets.StoreFault.ENVIRONMENT_MISMATCH`
    **and** :attr:`~globin.domain.secrets.StoreFault.KIND_MISMATCH` **acquire a
    producing code path for the first time.** The Credential Manager gets both
    free, because the environment and the kind are components of the target name
    and a mismatch simply cannot resolve. A file has no such property: it can be
    copied from one environment's vault into another's, keeping its contents and
    taking a new name. ``SECRET_STORE_CONTRACT.md`` §3 requires that isolation
    fails closed rather than advisory, so the envelope restates its identity and
    it is compared here.
    """
    expected: tuple[tuple[str, str], ...] = (
        (ENVIRONMENT_FIELD, reference.environment.text),
        (KIND_FIELD, reference.kind.value),
        (NAME_FIELD, reference.name),
        (SLOT_FIELD, slot.value),
    )
    for field, wanted in expected:
        found = document.get(field)
        if found != wanted:
            msg = (
                f"this envelope's {field} is {found!r} and {wanted!r} was asked for; "
                f"an envelope addresses exactly one secret"
            )
            raise ValidationError(msg)


def belongs_in_vault(size_bytes: int, ceiling: int) -> bool:
    """Whether material of this size belongs in the vault rather than the store.

    Args:
        size_bytes: How large the material is, encoded.
        ceiling: The store's own limit, which the caller passes so that the two
            cannot drift apart.

    Returns:
        Whether the vault is the right mechanism.

    **Disjoint by arithmetic rather than by policy**, which is what keeps a second
    mechanism from becoming a second answer to one question: the store takes what
    fits its ceiling and the vault takes what does not, so no value belongs to
    both and none belongs to neither.

    **There is deliberately no** :class:`~globin.domain.secrets.SecretKind`
    **parameter.** A private key that fits the ceiling belongs in the store, and a
    rule that routed by *type* rather than by *size* would be storage taking an
    opinion about signing — which is Phases 033 onwards and not this module's.
    Leaving the parameter out means nothing can branch on it, which is a stronger
    guarantee than a comment saying nothing should.
    """
    return size_bytes > ceiling
