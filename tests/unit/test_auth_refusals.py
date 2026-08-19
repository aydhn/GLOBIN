"""Every refusal the authentication layer can produce, including the impossible ones.

The tests beside this file drive the paths a caller takes. This one drives the
paths a caller should never reach — the guards on states that would mean an
invariant had already broken, and the self-test's own failure branches.

**Two of them are reached by injecting a stub into the seam** rather than by
contorting a real key. `RsaSigner` and `Ed25519Signer` take their primitives as a
constructor argument, precisely so the library stays confined to one class; that
same seam is what lets a test hand them primitives that return the wrong thing and
check the guard fires. A signature of the wrong length is not something a real
Ed25519 key produces — and it is exactly what the venue's own published examples
are, so the guard is worth reaching.

**One is reached by making the library absent**, with an import hook. On this
machine `cryptography` is installed, so the stand-in arm would otherwise run only
on CI, which is the worst place to discover it is broken.
"""

import base64
import sys
from collections.abc import Iterator
from decimal import Decimal
from importlib.abc import MetaPathFinder
from typing import Any

import pytest

from globin.adapters.signing import (
    Ed25519Signer,
    RsaSigner,
    UnavailableAsymmetricSigner,
    _CryptographyPrimitives,
    _refuse_key_format,
    asymmetric_signers,
    hmac_signer,
)
from globin.application.auth import (
    AuthFinding,
    AuthPolicy,
    AuthResolution,
    SigningOutcome,
    self_test,
)
from globin.domain.api_reality import ApiKeyType
from globin.domain.auth import (
    API_KEY_HEADER,
    AuthenticatedRequest,
    AuthStatus,
    GeneratedSignature,
    ParameterPlacement,
    SecurityType,
    SignatureAlgorithm,
    SignatureEncoding,
    SigningPayload,
    SigningProfile,
    algorithm_for,
    encoding_for,
    key_type_for,
    signed_parameters,
    spot_profile,
)
from globin.domain.auth_timing import RecvWindow, default_recv_window
from globin.domain.rest import HttpMethod, QueryParameters, RestRequest
from globin.domain.secrets import SecretValue
from globin.errors import InternalError, ValidationError

# ---------------------------------------------------------------------------
# The mappings refuse what they cannot map
# ---------------------------------------------------------------------------


class _NotAKeyType:
    """Something shaped like an enum member and mapped by nothing."""

    value = "quantum"


@pytest.mark.parametrize(
    ("call", "phrase"),
    [
        pytest.param(algorithm_for, "no signature algorithm is mapped", id="algorithm"),
        pytest.param(encoding_for, "no signature encoding is mapped", id="encoding"),
        pytest.param(key_type_for, "no key type is mapped", id="key-type"),
    ],
)
def test_an_unmapped_member_is_refused_rather_than_defaulted(call: Any, phrase: str) -> None:
    """The absent default branch, exercised.

    A `return HMAC_SHA256` at the end of `algorithm_for` would be the single most
    dangerous default available, so the refusal has to be reachable to be worth
    anything.
    """
    with pytest.raises(ValidationError, match=phrase):
        call(_NotAKeyType())


@pytest.mark.parametrize(
    ("field", "phrase"),
    [
        pytest.param("signature_parameter", "no signature parameter", id="parameter"),
        pytest.param("api_key_header", "no API key header", id="header"),
    ],
)
def test_a_profile_naming_nothing_is_refused(field: str, phrase: str) -> None:
    """A profile with an empty name would render a parameter the venue cannot read."""
    with pytest.raises(ValidationError, match=phrase):
        SigningProfile(
            algorithm=SignatureAlgorithm.HMAC_SHA256,
            encoding=SignatureEncoding.HEX,
            placement=ParameterPlacement.QUERY_ONLY,
            **{field: ""},
        )


def test_a_signature_compared_against_a_foreign_type_defers() -> None:
    """`NotImplemented` rather than `False`, matching every value type here."""
    signature = GeneratedSignature("ab" * 32, SignatureAlgorithm.HMAC_SHA256)
    assert signature.__eq__("ab" * 32) is NotImplemented
    assert signature != "ab" * 32


def test_a_window_compared_against_a_foreign_type_defers() -> None:
    """Same convention, and the reason `RecvWindow` defines `__eq__` at all."""
    window = default_recv_window()
    assert window.__eq__(5000) is NotImplemented
    assert window != 5000


def test_a_window_is_hashable_by_value() -> None:
    """Unlike a signature, a window is ordinary data and may key a mapping."""
    assert hash(RecvWindow(Decimal(5000))) == hash(RecvWindow(Decimal(5000)))
    assert {RecvWindow(Decimal(5000)): "default"}[RecvWindow(Decimal(5000))] == "default"


def test_a_window_renders_for_a_diagnostic() -> None:
    """`repr` says what it is; `str` says what gets signed."""
    assert repr(RecvWindow(Decimal("6000.346"))) == "RecvWindow(6000.346)"
    assert str(RecvWindow(Decimal("6000.346"))) == "6000.346"


# ---------------------------------------------------------------------------
# The authenticated request refuses states that would be lies
# ---------------------------------------------------------------------------


def _signed_request() -> RestRequest:
    """A request carrying a signature and a key header.

    Returns:
        The request.
    """
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    signature = GeneratedSignature("ab" * 32, SignatureAlgorithm.HMAC_SHA256)
    return RestRequest(
        operation="x",
        method=HttpMethod.GET,
        path="/v3/x",
        query=signed_parameters(QueryParameters(items=(("a", "1"),)), signature, profile),
        headers=((API_KEY_HEADER, "identifier"),),
    )


def test_an_empty_signed_span_is_refused() -> None:
    """A request claiming to be signed over nothing."""
    from globin.domain.auth_timing import TimestampUnit

    with pytest.raises(ValidationError, match="empty signed span"):
        AuthenticatedRequest(
            request=_signed_request(),
            signed_span="",
            profile=spot_profile(SignatureAlgorithm.HMAC_SHA256),
            timestamp=1,
            timestamp_unit=TimestampUnit.MILLISECONDS,
        )


def test_wire_matching_is_false_when_there_is_no_query_at_all() -> None:
    """A target with no `?` cannot carry a signature, so the invariant is false.

    Unreachable through `sign_request`, which always appends a signature — kept
    because this method is what a caller checks, and a method that could not
    answer `False` would be a check that always passes.
    """
    from globin.domain.auth_timing import TimestampUnit

    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    authenticated = AuthenticatedRequest(
        request=_signed_request(),
        signed_span="a=1",
        profile=profile,
        timestamp=1,
        timestamp_unit=TimestampUnit.MILLISECONDS,
    )
    object.__setattr__(authenticated, "signed_span", "something-else")
    assert not authenticated.wire_matches("/api")


# ---------------------------------------------------------------------------
# The application types refuse to describe two things at once
# ---------------------------------------------------------------------------


def test_a_refusal_that_explains_nothing_is_refused() -> None:
    """An operator reading it would learn only that something failed."""
    with pytest.raises(ValidationError, match="explains nothing"):
        AuthResolution(
            outcome=AuthStatus.MISSING_CREDENTIAL,
            family="spot",
            environment="testnet",
            security_type=SecurityType.USER_DATA,
        )


def test_a_signing_outcome_that_succeeded_with_no_request_is_refused() -> None:
    """Success with nothing to send is a state no caller has a branch for."""
    with pytest.raises(ValidationError, match="carries no request"):
        SigningOutcome(outcome=AuthStatus.RESOLVED)


def test_a_signing_outcome_that_failed_and_carries_a_request_is_refused() -> None:
    """The other direction, which a one-way check would miss."""
    from globin.domain.auth_timing import TimestampUnit

    authenticated = AuthenticatedRequest(
        request=_signed_request(),
        signed_span="a=1",
        profile=spot_profile(SignatureAlgorithm.HMAC_SHA256),
        timestamp=1,
        timestamp_unit=TimestampUnit.MILLISECONDS,
    )
    with pytest.raises(ValidationError, match="still carries a request"):
        SigningOutcome(outcome=AuthStatus.MISSING_CREDENTIAL, request=authenticated)


def test_the_records_are_json_safe() -> None:
    """Every `as_record` on this surface, exercised so none can raise unnoticed."""
    assert AuthPolicy().as_record()["key_type"] is None
    assert AuthFinding(check="x", passed=True).as_record()["passed"] is True
    assert SigningOutcome(outcome=AuthStatus.MISSING_CREDENTIAL).as_record()["signed"] is False


# ---------------------------------------------------------------------------
# The signers refuse what they cannot sign
# ---------------------------------------------------------------------------


def test_no_secret_can_encode_to_no_bytes() -> None:
    """Why `HmacSigner` has no empty-key guard: the type already prevents the state.

    The first draft had one and it was unreachable — `SecretValue` refuses an empty
    string, and every non-empty string encodes to at least one byte, including the
    zero-width characters that look like they might not. Asserted here rather than
    argued in a comment, so the guard's removal stays justified.
    """
    with pytest.raises(ValidationError, match="cannot be empty"):
        SecretValue("")
    for material in ("a", "﻿", "​", " "):
        assert SecretValue(material).material().encode("utf-8")


def test_an_unavailable_signer_publishes_why() -> None:
    """The detail names a library and never a key, so it is safe to print."""
    stand_in = UnavailableAsymmetricSigner(SignatureAlgorithm.ED25519, "not installed here")
    assert stand_in.detail == "not installed here"


class _StubPrimitives(_CryptographyPrimitives):
    """Primitives that return whatever a test needs, to reach the guards.

    Subclassed rather than duplicated so the real `_load` and its refusals stay in
    play; only the two signing methods are replaced.
    """

    def __init__(self, produced: bytes) -> None:
        """Record what to return from both signing methods.

        Args:
            produced: The bytes to hand back.
        """
        self.produced = produced

    def sign_rsa(self, text: str, payload: bytes) -> bytes:
        """Return the recorded bytes.

        Args:
            text: Ignored.
            payload: Ignored.

        Returns:
            The recorded bytes.
        """
        del text, payload
        return self.produced

    def sign_ed25519(self, text: str, payload: bytes) -> bytes:
        """Return the recorded bytes.

        Args:
            text: Ignored.
            payload: Ignored.

        Returns:
            The recorded bytes.
        """
        del text, payload
        return self.produced


def test_an_rsa_signer_that_produced_nothing_raises_internally() -> None:
    """A valid key cannot produce an empty signature, so this is a defect if reached."""
    signer = RsaSigner(_StubPrimitives(b""))
    with pytest.raises(InternalError, match="empty signature"):
        signer.sign(SigningPayload(query_span="a=1"), SecretValue("material"))


def test_an_ed25519_signature_of_the_wrong_length_raises_internally() -> None:
    """The guard that would have caught the venue's own documentation error.

    Both worked Ed25519 examples `rest-api.md` publishes decode to 256 bytes or not
    at all, and an Ed25519 signature is 64. A signer wired to the wrong primitive
    fails here rather than at the venue.
    """
    signer = Ed25519Signer(_StubPrimitives(b"\x00" * 256))
    with pytest.raises(InternalError, match="RFC 8032 fixes it at 64"):
        signer.sign(SigningPayload(query_span="a=1"), SecretValue("material"))


def test_an_ed25519_signature_of_the_right_length_is_accepted() -> None:
    """The positive case, so the guard above is not vacuously satisfied."""
    signer = Ed25519Signer(_StubPrimitives(b"\x01" * 64))
    produced = signer.sign(SigningPayload(query_span="a=1"), SecretValue("material"))
    assert base64.b64decode(produced.value(), validate=True) == b"\x01" * 64


def test_an_unrecognised_pem_block_is_described_by_shape() -> None:
    """A PEM type this loader does not know, named by shape rather than quoted.

    Driven through `_refuse_key_format` rather than through a signer, which is
    both better isolation and the only form that works everywhere: the format
    check is a pure function of text, while reaching it through a signer needs
    `cryptography` and would fail on every host without it — which is every CI
    `quality` run. That was found by running this suite with the library blocked,
    not by reading it.
    """
    material = "-----BEGIN SOMETHING ELSE-----\nZm9vYmFy\n-----END SOMETHING ELSE-----\n"
    with pytest.raises(ValidationError, match="PEM block of some other type") as caught:
        _refuse_key_format(material, ApiKeyType.RSA)
    assert "Zm9vYmFy" not in str(caught.value)


# ---------------------------------------------------------------------------
# The library being absent
# ---------------------------------------------------------------------------


class _Blocked(MetaPathFinder):
    """Refuses to find `cryptography`, as a machine without it would."""

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        """Raise for the guarded distribution and defer for everything else.

        Args:
            fullname: The module being imported.
            path: Ignored.
            target: Ignored.

        Returns:
            ``None``, deferring to the next finder.

        Raises:
            ImportError: For the guarded distribution.
        """
        del path, target
        if fullname == "cryptography" or fullname.startswith("cryptography."):
            message = f"No module named {fullname!r}"
            raise ImportError(message, name=fullname)
        return


@pytest.fixture
def without_cryptography() -> Iterator[None]:
    """Make the library unimportable for the duration of one test.

    Yields:
        Nothing.

    Every already-imported `cryptography` submodule is removed and restored, so the
    factory's own `from … import …` actually reaches the finder rather than being
    served from `sys.modules`.
    """
    blocker = _Blocked()
    cached = {
        name: module for name, module in sys.modules.items() if name.startswith("cryptography")
    }
    for name in cached:
        del sys.modules[name]
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.update(cached)


@pytest.mark.usefixtures("without_cryptography")
def test_both_asymmetric_arms_move_together_when_the_library_is_absent() -> None:
    """The arm every CI `quality` run takes, exercised on a machine that has the library.

    One library supplies both algorithms, so a host has both or neither; returning
    one real signer beside one stand-in would describe a state that cannot occur.
    """
    rsa_signer, ed_signer = asymmetric_signers()
    assert isinstance(rsa_signer, UnavailableAsymmetricSigner)
    assert isinstance(ed_signer, UnavailableAsymmetricSigner)
    assert not rsa_signer.available
    assert not ed_signer.available
    assert "cryptography" in rsa_signer.detail


@pytest.mark.usefixtures("without_cryptography")
def test_hmac_still_signs_when_the_library_is_absent() -> None:
    """What the degradation actually costs: the recommended algorithm, not authentication."""
    from globin.adapters.signing import available_algorithms

    assert available_algorithms() == (SignatureAlgorithm.HMAC_SHA256,)
    produced = hmac_signer().sign(SigningPayload(query_span="a=1"), SecretValue("secret"))
    assert produced.algorithm is SignatureAlgorithm.HMAC_SHA256


@pytest.mark.usefixtures("without_cryptography")
def test_the_self_test_reports_the_absence_without_failing() -> None:
    """A degraded host is a state rather than a fault, matching every survey here."""
    from globin.adapters.signing import available_algorithms

    report = self_test(hmac_signer(), available_algorithms())
    assert report.passed, [item.detail for item in report.failures]
    registry = next(item for item in report.findings if item.check == "auth.signer_registry")
    assert "ed25519" in registry.detail
    assert "rsa_pkcs1v15_sha256" in registry.detail


# ---------------------------------------------------------------------------
# The self-test's own failure branches
# ---------------------------------------------------------------------------


class _BrokenSigner:
    """A signer that produces a valid-looking signature that is not the right one."""

    @property
    def algorithm(self) -> SignatureAlgorithm:
        """The algorithm it claims."""
        return SignatureAlgorithm.HMAC_SHA256

    @property
    def available(self) -> bool:
        """It claims to work."""
        return True

    def sign(self, payload: SigningPayload, material: SecretValue) -> GeneratedSignature:
        """Return a fixed wrong answer.

        Args:
            payload: Ignored.
            material: Ignored.

        Returns:
            A well-formed signature of the wrong value.
        """
        del payload, material
        return GeneratedSignature("00" * 32, SignatureAlgorithm.HMAC_SHA256)


class _RaisingSigner(_BrokenSigner):
    """A signer that refuses everything, to drive the self-test's exception paths."""

    def sign(self, payload: SigningPayload, material: SecretValue) -> GeneratedSignature:
        """Refuse.

        Args:
            payload: Ignored.
            material: Ignored.

        Raises:
            ValidationError: Always.
        """
        del payload, material
        message = "this signer refuses"
        raise ValidationError(message)


class _LeakingSigner(_BrokenSigner):
    """A signer whose signature renders itself, to prove the redaction check works."""

    def sign(self, payload: SigningPayload, material: SecretValue) -> GeneratedSignature:
        """Return a signature that does not hide.

        Args:
            payload: Ignored.
            material: Ignored.

        Returns:
            Something shaped like a signature and willing to render.
        """
        del payload, material

        class _Loud(GeneratedSignature):
            """A signature that renders itself, which the real one refuses to do."""

            def __repr__(self) -> str:
                """Render the value, which is exactly what must be caught."""
                return self.value()

            def as_record(self) -> dict[str, object]:
                """Publish the value, likewise."""
                return {"algorithm": self.algorithm.value, "value": self.value()}

        return _Loud("11" * 32, SignatureAlgorithm.HMAC_SHA256)


def _findings(signer: Any) -> dict[str, AuthFinding]:
    """Run the self-test and index its findings by check name.

    Args:
        signer: The signer to run it with.

    Returns:
        The findings.
    """
    report = self_test(signer, tuple(SignatureAlgorithm))
    return {item.check: item for item in report.findings}


def test_the_self_test_notices_a_wrong_known_answer() -> None:
    """The check that compares GLOBIN against an answer it did not choose."""
    finding = _findings(_BrokenSigner())["auth.known_answer"]
    assert not finding.passed
    assert "does not publish" in finding.detail


def test_the_self_test_notices_a_signer_that_refuses() -> None:
    """Three checks depend on a working signer, and each reports rather than raising."""
    findings = _findings(_RaisingSigner())
    for check in ("auth.known_answer", "auth.wire_equality", "auth.redaction"):
        assert not findings[check].passed, check
        detail = findings[check].detail
        assert "ValidationError" in detail or "signing failed" in detail, check


def test_the_self_test_notices_a_signature_that_renders_itself() -> None:
    """The redaction check, shown catching something rather than merely passing."""
    finding = _findings(_LeakingSigner())["auth.redaction"]
    assert not finding.passed
    assert "reachable through" in finding.detail
    assert "repr" in finding.detail
    assert "as_record" in finding.detail


def test_every_self_test_check_passes_with_the_real_signer() -> None:
    """The positive case for all eight, so none of the above is vacuous."""
    from globin.adapters.signing import available_algorithms

    report = self_test(hmac_signer(), available_algorithms())
    assert report.passed, [item.detail for item in report.failures]
    assert {item.check for item in report.findings} == {
        "auth.algorithm_mapping",
        "auth.encoding_mapping",
        "auth.security_types",
        "auth.known_answer",
        "auth.wire_equality",
        "auth.recv_window",
        "auth.redaction",
        "auth.signer_registry",
    }
