"""The three signers, against real keys and against the documented traps.

**Every key here is generated in the test.** Nothing key-shaped is committed, so
the secret scanner has nothing to find and no fixture can drift into being mistaken
for a real credential. `docs/security/SECURITY_BASELINE.md` forbids committed key
material; generating means the prohibition costs nothing to keep.

**The RSA tests are the slow ones and they are worth it.** Generating a 2048-bit
key takes tens of milliseconds, and the alternative — a committed key — is the
thing being avoided. A module-scoped fixture pays it once.

Three checks here exist because the venue's documentation is wrong or easy to
misread, and each is grounded in a quotation rather than in caution:

*PSS must not verify.* *"We currently do not support the PSS signature scheme."*
The two padding schemes are one argument apart and produce signatures of identical
length, so nothing distinguishes them from outside except a verification attempt
under each.

*Ed25519 must be 64 bytes.* RFC 8032 fixes it. Both worked examples the venue
publishes decode to 256 bytes or not at all — see
`docs/research/phase_035_sources.md` S-05 — so this is the assertion that would
have caught the documentation error had anyone copied it.

*No message may carry key material.* Checked by searching every refusal for any
run of the material it was given, excluding only strings this module publishes
itself. The first draft of `_refuse_key_format` echoed the first line of the input,
which is armour for a well-formed PEM and forty-eight characters of private key for
the input that actually reaches the error path.
"""

import base64
from typing import Final

import pytest

from globin.adapters.signing import (
    ED25519_SIGNATURE_BYTES,
    RSA_MAX_KEY_BITS,
    RSA_MIN_KEY_BITS,
    Ed25519Signer,
    HmacSigner,
    RsaSigner,
    UnavailableAsymmetricSigner,
    asymmetric_signers,
    available_algorithms,
    hmac_signer,
    known_armour,
    pkcs8_encrypted_header,
    pkcs8_header,
    signers,
)
from globin.domain.auth import (
    GeneratedSignature,
    SignatureAlgorithm,
    SignatureEncoding,
    SigningPayload,
    encoding_for,
)
from globin.domain.secrets import SecretValue
from globin.errors import ValidationError

cryptography = pytest.importorskip(
    "cryptography",
    reason="the asymmetric signers need the cryptography distribution, which is absent-safe",
    exc_type=ImportError,
)
"""Skip the whole module where the library is absent, which is every CI `quality` run.

`exc_type` is passed rather than left to the default for two reasons. pytest 9.1
makes the current default an error, so this is where that arrives if it is not
stated. And it makes the skip work when the absence is *simulated* — an import hook
that blocks the module raises `ImportError` rather than being silently absent, which
is how the absent arm is exercised on a machine that has the library installed.
"""

from cryptography.exceptions import InvalidSignature  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa  # noqa: E402

PAYLOAD: Final[str] = "symbol=BTCUSDT&side=SELL&timestamp=1668481559918&recvWindow=5000"
"""A payload shaped like a real one, and carrying nothing sensitive."""

WINDOW: Final[int] = 12
"""How long a run of the material must be to count as leaked.

Twelve characters of base64 is nine bytes of key, which is more than enough to be
a leak and short enough that a coincidental match is implausible.
"""


def _pkcs8(key: object) -> str:
    """Serialise a generated key the way the venue requires.

    Args:
        key: An RSA or Ed25519 private key.

    Returns:
        Unencrypted PKCS#8 PEM.
    """
    encoded: bytes = key.private_bytes(  # type: ignore[attr-defined]
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return encoded.decode("ascii")


@pytest.fixture(scope="module")
def rsa_key() -> object:
    """A 2048-bit RSA key, generated once because generating is not cheap."""
    return rsa.generate_private_key(public_exponent=65537, key_size=RSA_MIN_KEY_BITS)


@pytest.fixture(scope="module")
def ed_key() -> object:
    """An Ed25519 key."""
    return ed25519.Ed25519PrivateKey.generate()


@pytest.fixture(scope="module")
def payload() -> SigningPayload:
    """The payload every signer here is given."""
    return SigningPayload(query_span=PAYLOAD)


def _rsa_signer() -> RsaSigner:
    """The real RSA signer, or a skip if the library is absent."""
    signer, _ = asymmetric_signers()
    assert isinstance(signer, RsaSigner)
    return signer


def _ed_signer() -> Ed25519Signer:
    """The real Ed25519 signer."""
    _, signer = asymmetric_signers()
    assert isinstance(signer, Ed25519Signer)
    return signer


def _leaked(material: str, message: str) -> str | None:
    """Any run of the material appearing verbatim in a message.

    Args:
        material: What was handed to the signer.
        message: What the refusal said.

    Returns:
        The offending run, or ``None``.

    Runs that also appear in a string this module publishes are not counted: a PEM
    armour line the loader is entitled to name will inevitably share characters
    with the material's own armour, and counting that would make the check
    unsatisfiable rather than strict.
    """
    published = (
        pkcs8_header(),
        pkcs8_encrypted_header(),
        *(armour for armour, _ in known_armour()),
    )
    for start in range(len(material) - WINDOW + 1):
        chunk = material[start : start + WINDOW]
        if not chunk.strip() or chunk not in message:
            continue
        if any(chunk in item for item in published):
            continue
        return chunk
    return None


# ---------------------------------------------------------------------------
# HMAC
# ---------------------------------------------------------------------------


def test_hmac_produces_lowercase_hex(payload: SigningPayload) -> None:
    """The documented encoding, and the case GLOBIN chose for determinism."""
    produced = hmac_signer().sign(payload, SecretValue("a-shared-secret"))
    assert produced.algorithm is SignatureAlgorithm.HMAC_SHA256
    assert produced.value() == produced.value().lower()
    assert len(produced.value()) == 64
    bytes.fromhex(produced.value())


def test_hmac_is_deterministic(payload: SigningPayload) -> None:
    """Two runs of one payload with one secret must agree, or nothing else here means anything."""
    secret = SecretValue("a-shared-secret")
    assert hmac_signer().sign(payload, secret) == hmac_signer().sign(payload, secret)


def test_one_changed_byte_changes_the_signature() -> None:
    """The property the whole exact-bytes invariant rests on."""
    secret = SecretValue("a-shared-secret")
    first = hmac_signer().sign(SigningPayload(query_span=PAYLOAD), secret)
    second = hmac_signer().sign(SigningPayload(query_span=PAYLOAD + "0"), secret)
    assert first != second


def test_a_changed_secret_changes_the_signature(payload: SigningPayload) -> None:
    """The other half, which a payload-only test would not catch."""
    first = hmac_signer().sign(payload, SecretValue("one-secret"))
    second = hmac_signer().sign(payload, SecretValue("another-secret"))
    assert first != second


def test_hmac_is_always_available() -> None:
    """It is `hmac` and `hashlib`, so it has one arm rather than two."""
    assert hmac_signer().available is True
    assert isinstance(hmac_signer(), HmacSigner)
    assert SignatureAlgorithm.HMAC_SHA256 in available_algorithms()


# ---------------------------------------------------------------------------
# RSA
# ---------------------------------------------------------------------------


def test_rsa_verifies_under_pkcs1v15(rsa_key: object, payload: SigningPayload) -> None:
    """The documented scheme, verified against the matching public key."""
    produced = _rsa_signer().sign(payload, SecretValue(_pkcs8(rsa_key)))
    raw = base64.b64decode(produced.value(), validate=True)
    rsa_key.public_key().verify(  # type: ignore[attr-defined]
        raw, payload.as_bytes(), padding.PKCS1v15(), hashes.SHA256()
    )


def test_rsa_does_not_verify_under_pss(rsa_key: object, payload: SigningPayload) -> None:
    """The trap the venue states outright: PSS is not a scheme it supports.

    A PSS signature is the same length and the same shape; the only way to tell it
    apart from outside is to try to verify under each scheme. Without this test a
    signer that used PSS would pass every other assertion in this file and be
    rejected by the venue with `-1022`.
    """
    produced = _rsa_signer().sign(payload, SecretValue(_pkcs8(rsa_key)))
    raw = base64.b64decode(produced.value(), validate=True)
    with pytest.raises(InvalidSignature):
        rsa_key.public_key().verify(  # type: ignore[attr-defined]
            raw,
            payload.as_bytes(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )


def test_rsa_output_is_base64_with_no_case_transform(
    rsa_key: object, payload: SigningPayload
) -> None:
    """RSA signatures are documented case-sensitive, so nothing may normalise one."""
    produced = _rsa_signer().sign(payload, SecretValue(_pkcs8(rsa_key)))
    value = produced.value()
    assert encoding_for(produced.algorithm) is SignatureEncoding.BASE64
    assert value != value.lower()
    assert value != value.upper()


def test_a_pkcs1_block_is_refused(rsa_key: object, payload: SigningPayload) -> None:
    """The venue supports only PKCS#8, and this library would read PKCS#1 happily.

    Refusing here means an operator learns at enrolment rather than at the first
    signed request.
    """
    material = rsa_key.private_bytes(  # type: ignore[attr-defined]
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    with pytest.raises(ValidationError, match="PKCS#8"):
        _rsa_signer().sign(payload, SecretValue(material))


def test_an_encrypted_key_is_refused_with_its_own_message(
    rsa_key: object, payload: SigningPayload
) -> None:
    """GLOBIN has no way to collect a passphrase, so this is the operator's to resolve."""
    material = rsa_key.private_bytes(  # type: ignore[attr-defined]
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(b"a-passphrase"),
    ).decode("ascii")
    with pytest.raises(ValidationError, match="passphrase"):
        _rsa_signer().sign(payload, SecretValue(material))


@pytest.mark.parametrize("bits", [1024, 8192], ids=["below-the-floor", "above-the-ceiling"])
def test_a_key_outside_the_documented_size_range_is_refused(
    bits: int, payload: SigningPayload
) -> None:
    """The venue supports RSA keys from 2048 up to 4096 bits, and nothing outside."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    with pytest.raises(ValidationError, match=f"{RSA_MIN_KEY_BITS} to {RSA_MAX_KEY_BITS}"):
        _rsa_signer().sign(payload, SecretValue(_pkcs8(key)))


# ---------------------------------------------------------------------------
# Ed25519
# ---------------------------------------------------------------------------


def test_ed25519_verifies_against_the_matching_public_key(
    ed_key: object, payload: SigningPayload
) -> None:
    """The property no fixed vector can give, and the one that actually matters."""
    produced = _ed_signer().sign(payload, SecretValue(_pkcs8(ed_key)))
    raw = base64.b64decode(produced.value(), validate=True)
    ed_key.public_key().verify(raw, payload.as_bytes())  # type: ignore[attr-defined]


def test_an_ed25519_signature_is_sixty_four_bytes(ed_key: object, payload: SigningPayload) -> None:
    """RFC 8032 fixes it, and the venue's own worked examples do not satisfy it.

    Both Ed25519 examples `rest-api.md` publishes decode to 256 bytes or not at
    all. This assertion is what would have caught that had the examples been used
    as vectors.
    """
    produced = _ed_signer().sign(payload, SecretValue(_pkcs8(ed_key)))
    assert len(base64.b64decode(produced.value(), validate=True)) == ED25519_SIGNATURE_BYTES


def test_ed25519_is_deterministic(ed_key: object, payload: SigningPayload) -> None:
    """RFC 8032 §5.1.6: the nonce is derived from the key and the message, with no randomness.

    This is the test that distinguishes Ed25519 from ECDSA, which would produce a
    different signature on every call and pass every other assertion here.
    """
    material = SecretValue(_pkcs8(ed_key))
    assert _ed_signer().sign(payload, material) == _ed_signer().sign(payload, material)


def test_ed25519_matches_the_rfc_8032_vectors() -> None:
    """The known-answer test, from the algorithm's defining document.

    The venue's own worked examples are unusable (S-05), so the vectors come from
    RFC 8032 §7.1 instead — TEST 2 and TEST 3, which are short enough to read.
    These exercise the primitive rather than GLOBIN's PEM path, which is the point:
    they establish that the library computes Ed25519, and the tests above establish
    that GLOBIN uses it correctly.
    """
    vectors = (
        (
            "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
            "72",
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
            "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
        ),
        (
            "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
            "af82",
            "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
            "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
        ),
    )
    for secret, message, expected in vectors:
        key = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(secret))
        assert key.sign(bytes.fromhex(message)).hex() == expected


# ---------------------------------------------------------------------------
# Key type confusion
# ---------------------------------------------------------------------------


def test_an_rsa_key_filed_as_ed25519_is_refused(rsa_key: object, payload: SigningPayload) -> None:
    """Both arrive as PKCS#8 blocks with one armour line, indistinguishable by eye."""
    with pytest.raises(ValidationError, match="parsed as"):
        _ed_signer().sign(payload, SecretValue(_pkcs8(rsa_key)))


def test_an_ed25519_key_filed_as_rsa_is_refused(ed_key: object, payload: SigningPayload) -> None:
    """The other direction, which a one-way test would miss."""
    with pytest.raises(ValidationError, match="parsed as"):
        _rsa_signer().sign(payload, SecretValue(_pkcs8(ed_key)))


def test_a_corrupt_pkcs8_block_is_refused(payload: SigningPayload) -> None:
    """A truncated or damaged key fails with a message, not with a library traceback."""
    material = f"{pkcs8_header()}\nbm90IGEga2V5IGF0IGFsbA==\n-----END PRIVATE KEY-----\n"
    with pytest.raises(ValidationError, match="did not parse"):
        _ed_signer().sign(payload, SecretValue(material))


# ---------------------------------------------------------------------------
# No material in any message
# ---------------------------------------------------------------------------


def test_no_refusal_carries_any_run_of_the_material(
    rsa_key: object, ed_key: object, payload: SigningPayload
) -> None:
    """The check that found a real leak before any reviewer did.

    `_refuse_key_format` used to echo the first line of the input. That is armour
    for a well-formed PEM — and forty-eight characters of private key for an
    operator who pasted the base64 body by mistake, which is exactly the input that
    reaches the error path.
    """
    der = rsa_key.private_bytes(  # type: ignore[attr-defined]
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cases = {
        "pkcs1": rsa_key.private_bytes(  # type: ignore[attr-defined]
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii"),
        "encrypted": rsa_key.private_bytes(  # type: ignore[attr-defined]
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(b"pw"),
        ).decode("ascii"),
        "bare-base64": base64.b64encode(der).decode("ascii"),
        "bare-hex": der.hex(),
        "wrong-type": _pkcs8(ed_key),
        "corrupt": f"{pkcs8_header()}\nbm90IGEga2V5\n-----END PRIVATE KEY-----\n",
    }
    for label, material in cases.items():
        with pytest.raises(ValidationError) as caught:
            _rsa_signer().sign(payload, SecretValue(material))
        found = _leaked(material, str(caught.value))
        assert found is None, f"{label}: the refusal carries {found!r} from the material"


def test_an_unrecognised_shape_is_described_rather_than_quoted(
    payload: SigningPayload,
) -> None:
    """Nothing the operator supplied reaches the message, however odd its shape."""
    material = "x" * 200
    with pytest.raises(ValidationError) as caught:
        _rsa_signer().sign(payload, SecretValue(material))
    assert "not a PEM block at all" in str(caught.value)
    assert "xxxx" not in str(caught.value)


@pytest.mark.parametrize("armour", [item for item, _ in known_armour()])
def test_a_recognised_armour_is_named_from_the_table(armour: str, payload: SigningPayload) -> None:
    """Named from a fixed table, so no slice of the input can reach the message."""
    material = f"{armour}\nc29tZSBib2R5\n-----END-----\n"
    with pytest.raises(ValidationError) as caught:
        _rsa_signer().sign(payload, SecretValue(material))
    assert "c29tZSBib2R5" not in str(caught.value)


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_the_registry_is_total_over_the_enumeration() -> None:
    """A mapping with holes would make every caller write the same missing-key branch."""
    assert set(signers()) == set(SignatureAlgorithm)


def test_an_unavailable_signer_refuses_rather_than_substituting() -> None:
    """The whole reason the stand-in exists, and the one place this pattern differs.

    Every other stand-in in this repository reports a lost measurement. This one
    would be tempted to sign with HMAC instead, which is a different algorithm with
    a key the operator enrolled for something else, on the algorithm the venue
    calls deprecated.
    """
    stand_in = UnavailableAsymmetricSigner(SignatureAlgorithm.ED25519, "not installed here")
    assert stand_in.available is False
    assert stand_in.algorithm is SignatureAlgorithm.ED25519
    with pytest.raises(ValidationError, match="refuses rather than signing"):
        stand_in.sign(SigningPayload(query_span="x=1"), SecretValue("anything"))


def test_an_unavailable_signer_reads_no_material() -> None:
    """The refusal happens before the material is touched, so it cannot be a leak route.

    Checked by handing it a value whose material accessor would raise if called.
    """

    class Exploding(SecretValue):
        """A value that refuses to be read."""

        def material(self) -> str:
            """Fail loudly if anything reads this.

            Raises:
                AssertionError: Always.
            """
            message = "an unavailable signer read the material"
            raise AssertionError(message)

    stand_in = UnavailableAsymmetricSigner(SignatureAlgorithm.RSA_PKCS1V15_SHA256, "absent")
    with pytest.raises(ValidationError):
        stand_in.sign(SigningPayload(query_span="x=1"), Exploding("material"))


def test_a_generated_signature_refuses_a_value_its_encoding_cannot_hold() -> None:
    """A hex signature that is not hex, and a base64 one that is not base64."""
    with pytest.raises(ValidationError, match="declared hex"):
        GeneratedSignature("zzzz", SignatureAlgorithm.HMAC_SHA256)
    with pytest.raises(ValidationError, match="declared base64"):
        GeneratedSignature("not base64!!", SignatureAlgorithm.ED25519)
    with pytest.raises(ValidationError, match="empty"):
        GeneratedSignature("", SignatureAlgorithm.HMAC_SHA256)
