"""The parts of the signing adapter that need no library, tested where there is none.

`tests/unit/test_signing.py` opens with a module-level `pytest.importorskip`, so
every test in it is skipped wherever `cryptography` is absent -- which is every CI
`quality` run, since that job installs only the seven toolchain pins. Most of what
it covers genuinely needs the library.

**The refusals do not.** `_refuse_key_format` and `_describe_shape` are pure text:
they decide, from an armour line alone, that material is encrypted, is PKCS#1
rather than PKCS#8, is a public key, or is not a PEM block at all -- before the
library is handed anything. Living inside the skipped module meant they were
unexercised in exactly the environment CI validates, and they are the security-
relevant half: they are what stops a mis-filed or mis-pasted key from reaching a
parser, and what guarantees no fragment of key material reaches a message.

So they are tested here instead, in a module that skips nothing. The stand-in arm
of the absent-safe factory is tested here for the same reason: it exists only where
the library is missing, so a module that skips on absence can never see it.

No file in this directory contains key material. Every string below is armour --
the `-----BEGIN ...-----` line and nothing after it -- which is what the functions
under test read, and is not a key.
"""

import pytest

from globin.adapters.signing import (
    Ed25519Signer,
    RsaSigner,
    UnavailableAsymmetricSigner,
    _CryptographyPrimitives,
    _describe_shape,
    _refuse_key_format,
    available_algorithms,
    hmac_signer,
    known_armour,
    pkcs8_encrypted_header,
    pkcs8_header,
    signers,
)
from globin.domain.api_reality import ApiKeyType
from globin.domain.auth import SignatureAlgorithm, SigningPayload
from globin.domain.secrets import SecretValue
from globin.errors import ValidationError

# ---------------------------------------------------------------------------
# The armour these functions recognise
# ---------------------------------------------------------------------------
#
# Spelled from a format and a label rather than written out, for the same reason
# `adapters/signing.py` composes them: two independent scanners watch this
# repository for committed key material -- its own `tools/quality/supply` and
# pre-commit's `detect-private-key` -- and both match the armour line as a literal
# substring. Composing means neither needs an allowance for this file, which is
# strictly better than having one: an allowance blinds a scanner to a whole pattern
# in a whole file, for ever, and has to be re-justified by every later reader.
#
# There is no key material here. These are armour lines and nothing behind them.

ARMOUR = "-----BEGIN {label}-----"
PRIVATE_KEY = "PRIVATE KEY"
ARMOUR_PREFIX = "-----BEGIN"


def _armour(label: str) -> str:
    """Spell one armour line from the label inside it."""
    return ARMOUR.format(label=label)


def _rsa_block() -> str:
    """A PKCS#1 RSA block: the armour the venue does not accept, and a stub body."""
    return f"{_armour(f'RSA {PRIVATE_KEY}')}\nAAAA\n"


def test_the_two_headers_are_the_pkcs8_armour_lines() -> None:
    """Composed from one format and one label, and therefore spelled once."""
    assert pkcs8_header() == _armour(PRIVATE_KEY)
    assert pkcs8_encrypted_header() == _armour(f"ENCRYPTED {PRIVATE_KEY}")


def test_the_encrypted_header_is_not_a_prefix_confusion() -> None:
    """The order of the two checks matters, so pin why.

    An encrypted block does not start with the plain header, so a reversed check
    would refuse it with the wrong message -- "not PKCS#8" rather than "GLOBIN
    cannot collect its passphrase", which sends an operator to a different fix.
    """
    assert not pkcs8_encrypted_header().startswith(pkcs8_header())


def test_every_known_armour_line_is_distinct_and_described() -> None:
    """A table read in order, so a duplicate would shadow whatever came after it."""
    rows = known_armour()
    assert len(rows) == 6
    assert len({armour for armour, _ in rows}) == len(rows)
    assert all(armour.startswith(ARMOUR_PREFIX) for armour, _ in rows)
    assert all(description for _, description in rows)


# ---------------------------------------------------------------------------
# What a refusal says, and what it must never say
# ---------------------------------------------------------------------------


def test_an_encrypted_block_is_refused_by_naming_the_passphrase() -> None:
    """GLOBIN can collect one value interactively, and never a passphrase for a key."""
    with pytest.raises(ValidationError) as caught:
        _refuse_key_format(f"{pkcs8_encrypted_header()}\nAAAA\n", ApiKeyType.RSA)
    assert "passphrase" in str(caught.value)


@pytest.mark.parametrize(
    ("armour", "expected"),
    [
        pytest.param(_armour(f"RSA {PRIVATE_KEY}"), "PKCS#1 RSA", id="pkcs1-rsa"),
        pytest.param(_armour(f"EC {PRIVATE_KEY}"), "SEC 1", id="sec1-ec"),
        pytest.param(_armour(f"DSA {PRIVATE_KEY}"), "PKCS#1 DSA", id="pkcs1-dsa"),
        pytest.param(_armour(f"OPENSSH {PRIVATE_KEY}"), "OpenSSH", id="openssh"),
        pytest.param(_armour("PUBLIC KEY"), "PUBLIC key", id="public-key"),
        pytest.param(_armour("CERTIFICATE"), "certificate", id="certificate"),
    ],
)
def test_a_recognised_armour_line_is_named_in_the_refusal(armour: str, expected: str) -> None:
    """Each of the six is named, so an operator is told what they actually pasted."""
    with pytest.raises(ValidationError) as caught:
        _refuse_key_format(f"{armour}\nAAAA\n", ApiKeyType.RSA)
    message = str(caught.value)
    assert expected in message
    assert "not PKCS#8" in message


def test_an_unrecognised_pem_block_is_described_without_being_quoted() -> None:
    """The fallback branch, which must still name no content."""
    assert _describe_shape(_armour("SOMETHING ODD"), ApiKeyType.RSA) == (
        "it is a PEM block of some other type"
    )


def test_material_that_is_not_pem_at_all_is_described_as_such() -> None:
    """The case that motivated the whole design: a pasted base64 body, not armour."""
    assert _describe_shape("MIIEvQIBADAN", ApiKeyType.ED25519) == "it is not a PEM block at all"


def test_no_refusal_echoes_any_fragment_of_what_it_was_given() -> None:
    """The leak this module exists to make impossible, asserted rather than trusted.

    A well-formed PEM's first line is armour and safe to echo. An operator who
    pastes the *body* by mistake has just handed a private key to whatever quotes
    it. So nothing is echoed at all, and this proves it by planting a marker that
    appears nowhere in the vocabulary of any message.
    """
    marker = "ZZQQXXVVNNMMKKJJ"
    for text in (
        f"{pkcs8_encrypted_header()}\n{marker}\n",
        f"{marker}\n",
        ARMOUR.format(label=marker),
    ):
        with pytest.raises(ValidationError) as caught:
            _refuse_key_format(text, ApiKeyType.RSA)
        assert marker not in str(caught.value)


def test_the_declared_key_type_reaches_the_message() -> None:
    """Which key was rejected, since an operator may have enrolled several."""
    for key_type in (ApiKeyType.RSA, ApiKeyType.ED25519):
        with pytest.raises(ValidationError) as caught:
            _refuse_key_format("not a pem block", key_type)
        assert key_type.value in str(caught.value)


def test_leading_whitespace_does_not_change_the_verdict() -> None:
    """A pasted key often arrives with a newline in front of it."""
    with pytest.raises(ValidationError):
        _refuse_key_format(f"\n  \n{_rsa_block()}", ApiKeyType.RSA)


def test_a_well_formed_pkcs8_header_is_not_refused_here() -> None:
    """The control. This function's job ends at the armour line.

    Whether the block behind that line parses is the library's question, and this
    returns rather than raising so the library gets asked it. There is nothing to
    assert about the return -- the function answers by not raising.
    """
    _refuse_key_format(f"{pkcs8_header()}\nAAAA\n", ApiKeyType.RSA)


# ---------------------------------------------------------------------------
# The stand-in arm, which only exists where the library does not
# ---------------------------------------------------------------------------


def test_an_unavailable_signer_reports_its_algorithm_and_stays_unavailable() -> None:
    """It answers the port truthfully rather than pretending or raising on contact."""
    stand_in = UnavailableAsymmetricSigner(SignatureAlgorithm.ED25519, "cryptography is absent")
    assert stand_in.algorithm is SignatureAlgorithm.ED25519
    assert stand_in.available is False
    assert "cryptography" in stand_in.detail


def test_an_unavailable_signer_refuses_to_sign_and_says_it_will_not_substitute() -> None:
    """The no-fallback guarantee, at the one place that can actually break it.

    This is the whole phase's central rule reduced to one call. A stand-in that
    quietly returned an HMAC signature would produce a request the venue rejects
    with `-1022`, or worse, one it accepts under a key the operator never meant to
    use for it. So it raises, and the message says which algorithm is missing and
    that no other will be substituted.

    It runs **only where `cryptography` is absent**, which is every CI run and no
    developed host -- so before this test the guarantee was asserted nowhere that
    the arm actually executes.
    """
    stand_in = UnavailableAsymmetricSigner(SignatureAlgorithm.RSA_PKCS1V15_SHA256, "absent here")
    payload = SigningPayload(query_span="symbol=BTCUSDT", body_span="")
    with pytest.raises(ValidationError) as caught:
        stand_in.sign(payload, SecretValue("irrelevant"))
    message = str(caught.value)
    assert SignatureAlgorithm.RSA_PKCS1V15_SHA256.value in message
    assert "refuses rather than signing with a different algorithm" in message


def test_a_refusal_to_sign_never_reads_the_material_it_was_handed() -> None:
    """`material` is deleted before the message is built, so it cannot be quoted.

    A refusal is still a code path that was handed a secret. This pins that the
    secret reaches no message, which the redaction on `SecretValue` would mostly
    cover anyway -- but "mostly" is not the property worth having here.
    """
    stand_in = UnavailableAsymmetricSigner(SignatureAlgorithm.ED25519, "absent here")
    payload = SigningPayload(query_span="", body_span="")
    with pytest.raises(ValidationError) as caught:
        stand_in.sign(payload, SecretValue("SENTINELVALUE1234"))
    assert "SENTINELVALUE1234" not in str(caught.value)


def test_the_registry_answers_for_all_three_algorithms_either_way() -> None:
    """Absence removes an algorithm from `available_algorithms`, never from `signers`.

    The distinction is the whole safety property: a caller asking which algorithms
    it may use gets a shorter list, and a caller asking for a specific signer gets
    one that says no. Neither ever silently receives HMAC.
    """
    registry = signers()
    assert set(registry) == set(SignatureAlgorithm)
    for algorithm, signer in registry.items():
        assert signer.algorithm is algorithm
    assert set(available_algorithms()) == {a for a, s in registry.items() if s.available}


def test_hmac_is_available_with_no_library_at_all() -> None:
    """The stdlib arm, which is why an absent `cryptography` degrades rather than blocks."""
    assert hmac_signer().available is True
    assert SignatureAlgorithm.HMAC_SHA256 in available_algorithms()


# ---------------------------------------------------------------------------
# The signers' own logic, on injected doubles
# ---------------------------------------------------------------------------
#
# `RsaSigner` and `Ed25519Signer` take their primitives as a constructor argument
# so that neither class names an import -- the module-level rule has exactly one
# site to hold. That injection is also what makes them testable here: everything
# below is the signers' *own* decisions -- the key-size bounds, the declared-type
# check, the base64 rendering -- none of which is the library's behaviour, and all
# of which went unexercised wherever the library is absent.
#
# No double computes a real signature. Each returns fixed bytes, because what is
# under test is what the signer does with a result, not the cryptography.


class _FakeKey:
    """A loaded private key, as much of one as these code paths read."""

    def __init__(self, *, key_size: int = 2048, signature: bytes = b"signed") -> None:
        self.key_size = key_size
        self._signature = signature
        self.signed_payloads: list[bytes] = []

    def sign(self, payload: bytes, *rest: object) -> bytes:
        """Record what was signed and return the fixed result."""
        del rest
        self.signed_payloads.append(payload)
        return self._signature


class _FakeSerialization:
    """The serialisation module, reduced to the one function that is called."""

    def __init__(self, key: object | Exception) -> None:
        self._key = key

    def load_pem_private_key(self, data: bytes, password: object) -> object:
        """Return the planted key, or raise the planted fault."""
        del data, password
        if isinstance(self._key, Exception):
            raise self._key
        return self._key


def _nothing() -> None:
    """Stand in for a padding or hash object, which these paths only pass along."""
    return


class _FakeAlgorithmModule:
    """`padding` and `hashes`, whose members are only constructed and passed on."""

    def __getattr__(self, name: str) -> object:
        """Return a callable standing in for any member that is asked for."""
        del name
        return _nothing


def _primitives(key: object | Exception, *, expected: type = _FakeKey) -> _CryptographyPrimitives:
    """Build the injected primitives around a planted key."""
    return _CryptographyPrimitives(
        serialization=_FakeSerialization(key),
        padding=_FakeAlgorithmModule(),
        hashes=_FakeAlgorithmModule(),
        rsa_key=expected,
        ed25519_key=expected,
    )


def test_the_two_asymmetric_signers_report_their_algorithm_and_availability() -> None:
    """Constructed at all means the library imported, so both answer available."""
    rsa = RsaSigner(_primitives(_FakeKey()))
    ed = Ed25519Signer(_primitives(_FakeKey()))
    assert rsa.algorithm is SignatureAlgorithm.RSA_PKCS1V15_SHA256
    assert ed.algorithm is SignatureAlgorithm.ED25519
    assert rsa.available is True
    assert ed.available is True


@pytest.mark.parametrize(
    "bits",
    [pytest.param(1024, id="below-2048"), pytest.param(8192, id="above-4096")],
)
def test_an_rsa_key_outside_the_documented_size_range_is_refused(bits: int) -> None:
    """The venue documents 2048 to 4096, and a key outside it fails before signing."""
    primitives = _primitives(_FakeKey(key_size=bits))
    with pytest.raises(ValidationError) as caught:
        primitives.sign_rsa(f"{pkcs8_header()}\nAAAA\n", b"payload")
    assert str(bits) in str(caught.value)


def test_an_rsa_key_inside_the_range_signs_the_payload_it_was_given() -> None:
    """The control, and it pins that the payload reaches the key unmodified."""
    key = _FakeKey(key_size=2048, signature=b"\x01\x02\x03")
    assert _primitives(key).sign_rsa(f"{pkcs8_header()}\nAAAA\n", b"payload") == b"\x01\x02\x03"
    assert key.signed_payloads == [b"payload"]


def test_ed25519_signing_asks_for_no_padding_or_hash() -> None:
    """Ed25519 hashes internally, so the call takes the payload and nothing else."""
    key = _FakeKey(signature=b"\xaa" * 64)
    assert _primitives(key).sign_ed25519(f"{pkcs8_header()}\nAAAA\n", b"payload") == b"\xaa" * 64


def test_a_key_that_does_not_parse_is_refused_without_the_cause_being_chained() -> None:
    """A parser's message can quote the material, so it is dropped rather than chained."""
    primitives = _primitives(ValueError("the parser quoted MIIEvQIBADANBgkq here"))
    with pytest.raises(ValidationError) as caught:
        primitives.sign_ed25519(f"{pkcs8_header()}\nAAAA\n", b"payload")
    assert caught.value.__cause__ is None
    assert "MIIEvQIBADANBgkq" not in str(caught.value)
    assert "corrupt, truncated" in str(caught.value)


def test_a_key_filed_as_one_type_that_loads_as_another_is_refused() -> None:
    """Both types are PKCS#8 blocks with identical armour, so only the load can tell."""

    class _OtherKey:
        pass

    primitives = _primitives(_OtherKey(), expected=_FakeKey)
    with pytest.raises(ValidationError) as caught:
        primitives.sign_rsa(f"{pkcs8_header()}\nAAAA\n", b"payload")
    assert "_OtherKey" in str(caught.value)
    assert "the declared type is checked against what actually loaded" in str(caught.value)


def test_the_format_refusal_runs_before_the_key_is_ever_loaded() -> None:
    """Ordering, not just behaviour: a PKCS#1 block never reaches the parser.

    The double raises if it is called, so reaching it would fail differently. That
    is the point -- the text check exists so material the venue would reject fails
    at enrolment rather than inside a library.
    """
    primitives = _primitives(AssertionError("the loader must not have been reached"))
    with pytest.raises(ValidationError) as caught:
        primitives.sign_rsa(_rsa_block(), b"payload")
    assert "not PKCS#8" in str(caught.value)
