"""The eight-gate admission, and what signing does once it is through.

Every gate is exercised in its own test, in the order the gate runs, because the
*order* is part of the design: each refusal names the outermost thing that is
wrong, so an operator is told to classify an environment before they are told to
enrol a credential for it.

**Gate 1 is checked twice.** Once for the refusal it produces, and once for what it
does *not* do — a store that raises if anything reads it proves that a simulated
environment reaches no credential rather than reaching one and declining it. That
is a different guarantee from a refusal, and it is the one this phase's other half
exists to make possible.

The doubles here are hand-written and satisfy the `Protocol`, which is what
`docs/TESTING_STRATEGY.md` asks for by default.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from globin.application.auth import (
    AuthPolicy,
    AuthResolution,
    SigningOutcome,
    _documented_key_types,
    _mapping_finding,
    _recv_window_finding,
    _wire_finding,
    credential_summary,
    resolve_auth,
    self_test,
    sign_request,
)
from globin.domain.api_reality import ApiKeyType
from globin.domain.auth import (
    API_KEY_HEADER,
    SIGNATURE_PARAMETER,
    AuthStatus,
    CredentialBinding,
    GeneratedSignature,
    SecurityType,
    SignatureAlgorithm,
    SigningPayload,
)
from globin.domain.auth_timing import RecvWindow, TimestampUnit
from globin.domain.clock import instant
from globin.domain.environment_class import (
    EnvironmentClass,
    EnvironmentClassification,
)
from globin.domain.identifiers import EnvironmentId
from globin.domain.rest import (
    EndpointRole,
    HttpMethod,
    QueryParameters,
    RequestSecurityIntent,
    ResponseEncoding,
)
from globin.domain.rest_endpoint import (
    EndpointResolution,
    ResolutionStatus,
    ResolvedEndpoint,
)
from globin.domain.secrets import (
    SecretKind,
    SecretReference,
    SecretResolution,
    SecretSlot,
    SecretValue,
    StoreFault,
)
from globin.errors import ValidationError
from tests.support import signing_timing

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class StubStore:
    """A secret store that answers from a dictionary and records what was asked."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        """Hold the material this store will return.

        Args:
            values: Reference name mapped to its material.
        """
        self.values = values or {}
        self.asked: list[str] = []

    def health(self) -> StoreFault | None:
        """Always usable."""
        return None

    def resolve(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> SecretResolution:
        """Return the material, or an absence.

        Args:
            reference: What to resolve.
            slot: Ignored; this store keeps one copy.

        Returns:
            The resolution.
        """
        del slot
        self.asked.append(reference.name)
        material = self.values.get(reference.name)
        if material is None:
            return SecretResolution(reference=reference, fault=StoreFault.ABSENT)
        return SecretResolution(reference=reference, value=SecretValue(material))

    def store(
        self,
        reference: SecretReference,
        value: SecretValue,
        slot: SecretSlot = SecretSlot.CURRENT,
    ) -> StoreFault | None:
        """Refuse; nothing here writes."""
        del reference, value, slot
        return StoreFault.PROVIDER_READ_ONLY

    def delete(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> StoreFault | None:
        """Refuse; nothing here writes."""
        del reference, slot
        return StoreFault.PROVIDER_READ_ONLY

    def inventory(self) -> tuple[SecretReference, ...]:
        """Nothing is enumerated here."""
        return ()


class ExplodingStore(StubStore):
    """A store that fails the test if anything asks it for anything.

    The instrument for the guarantee gate 1 makes: an environment GLOBIN simulates
    must reach **no credential**, which is stronger than reaching one and declining
    it and cannot be shown by inspecting a refusal.
    """

    def resolve(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> SecretResolution:
        """Fail loudly.

        Args:
            reference: What was asked for.
            slot: Ignored.

        Raises:
            AssertionError: Always.
        """
        del slot
        msg = f"the secret store was asked for {reference.name!r} and must not have been"
        raise AssertionError(msg)


class StubSigner:
    """A signer that produces a fixed, well-formed signature."""

    def __init__(self, *, available: bool = True) -> None:
        """Record whether this signer claims to work.

        Args:
            available: What :attr:`available` answers.
        """
        self._available = available
        self.signed: list[str] = []

    @property
    def algorithm(self) -> SignatureAlgorithm:
        """The algorithm this signer claims."""
        return SignatureAlgorithm.HMAC_SHA256

    @property
    def available(self) -> bool:
        """Whether it can compute anything."""
        return self._available

    def sign(self, payload: SigningPayload, material: SecretValue) -> GeneratedSignature:
        """Return a fixed signature, recording the payload it was given.

        Args:
            payload: The exact characters to sign.
            material: The key material.

        Returns:
            The signature.
        """
        del material
        self.signed.append(payload.text)
        return GeneratedSignature("cd" * 32, SignatureAlgorithm.HMAC_SHA256)


class FailingSigner(StubSigner):
    """A signer that refuses the material it is given."""

    def sign(self, payload: SigningPayload, material: SecretValue) -> GeneratedSignature:
        """Refuse.

        Args:
            payload: Ignored.
            material: Ignored.

        Returns:
            Never.

        Raises:
            ValidationError: Always.
        """
        del payload, material
        msg = "a private key did not parse"
        raise ValidationError(msg)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _classification() -> EnvironmentClassification:
    """The four classes GLOBIN recognises, with names this test controls."""
    return EnvironmentClassification(
        entries=(
            ("production", EnvironmentClass.LIVE_CAPITAL),
            ("testnet", EnvironmentClass.VENUE_TESTNET),
            ("demo", EnvironmentClass.VENUE_DEMO),
            ("paper", EnvironmentClass.INTERNAL_SIMULATION),
        )
    )


def _resolution(
    *,
    environment: str = "testnet",
    outcome: ResolutionStatus = ResolutionStatus.RESOLVED,
    key_types: tuple[ApiKeyType, ...] = (ApiKeyType.HMAC, ApiKeyType.RSA, ApiKeyType.ED25519),
) -> EndpointResolution:
    """An endpoint resolution, permitted or refused.

    Args:
        environment: Which environment was asked for.
        outcome: Whether it resolved.
        key_types: What the registry records for the endpoint.

    Returns:
        The resolution.
    """
    if outcome is not ResolutionStatus.RESOLVED:
        return EndpointResolution(
            outcome=outcome,
            requested_family="spot",
            requested_environment=environment,
            requested_capability="account_data",
            intent=RequestSecurityIntent.SIGNED,
            encoding=ResponseEncoding.JSON,
            detail="the registry does not describe this",
        )
    return EndpointResolution(
        outcome=ResolutionStatus.RESOLVED,
        requested_family="spot",
        requested_environment=environment,
        requested_capability="account_data",
        intent=RequestSecurityIntent.SIGNED,
        encoding=ResponseEncoding.JSON,
        endpoint=ResolvedEndpoint(
            family="spot",
            environment=environment,
            role=EndpointRole.PRIMARY,
            url="https://example.invalid/api",
            host="example.invalid",
            port=0,
            path_prefix="/api",
            capabilities=("market_data", "trading", "account_data"),
            auth="signed",
            carries_real_capital=False,
            source="spot-rest",
            key_types=key_types,
        ),
    )


def _binding(
    key_type: ApiKeyType = ApiKeyType.HMAC, environment: str = "testnet"
) -> CredentialBinding:
    """A credential for one product and environment.

    Args:
        key_type: Which key type it declares.
        environment: Which environment it belongs to.

    Returns:
        The binding.
    """
    return CredentialBinding(
        api_key=SecretReference(
            environment=EnvironmentId(environment), kind=SecretKind.API_KEY, name="venue_key"
        ),
        material=SecretReference(
            environment=EnvironmentId(environment),
            kind=SecretKind.API_SECRET,
            name="venue_secret",
        ),
        key_type=key_type,
    )


def _credentials(
    key_type: ApiKeyType = ApiKeyType.HMAC, environment: str = "testnet"
) -> dict[tuple[str, str], CredentialBinding]:
    """The configured credential map.

    Args:
        key_type: Which key type is enrolled.
        environment: Which environment it is enrolled for.

    Returns:
        The map, keyed by product family and environment.
    """
    return {("spot", environment): _binding(key_type, environment)}


ALL_ALGORITHMS = tuple(SignatureAlgorithm)


def _resolve(**overrides: object) -> AuthResolution:
    """Run the gate with sensible defaults, overriding what a test cares about.

    Args:
        **overrides: Any argument to :func:`resolve_auth`.

    Returns:
        The resolution.
    """
    arguments: dict[str, object] = {
        "security_type": SecurityType.USER_DATA,
        "policy": AuthPolicy(),
        "classification": _classification(),
        "credentials": _credentials(),
        "available": ALL_ALGORITHMS,
    }
    arguments.update(overrides)
    resolution = arguments.pop("resolution", _resolution())
    return resolve_auth(resolution, **arguments)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The eight gates, in order
# ---------------------------------------------------------------------------


def test_gate_1_refuses_a_simulated_environment() -> None:
    """An environment GLOBIN simulates has no venue to authenticate to."""
    outcome = _resolve(
        resolution=_resolution(environment="paper"),
        credentials=_credentials(environment="paper"),
    )
    assert outcome.outcome is AuthStatus.ENVIRONMENT_FORBIDS_CREDENTIAL
    assert outcome.environment_class is EnvironmentClass.INTERNAL_SIMULATION
    assert not outcome.permitted
    assert outcome.profile is None
    assert outcome.binding is None


def test_gate_1_runs_before_anything_reads_a_credential() -> None:
    """The guarantee a refusal alone cannot show.

    `resolve_auth` never touches a store — it takes a mapping — so this checks the
    stronger property at the signing end: a refused resolution cannot be signed, so
    no store call can follow it.
    """
    outcome = _resolve(
        resolution=_resolution(environment="paper"),
        credentials=_credentials(environment="paper"),
    )
    store = ExplodingStore()
    with pytest.raises(ValidationError, match="only a permitted resolution"):
        sign_request(
            outcome,
            operation="spot.account",
            method=HttpMethod.GET,
            path="/v3/account",
            parameters=QueryParameters(),
            timing=signing_timing(instant(datetime(2026, 8, 19, tzinfo=UTC))),
            store=store,
            signer=StubSigner(),
        )
    assert store.asked == []


def test_gate_2_refuses_an_unclassified_environment() -> None:
    """A name nobody classified is not probably a testnet."""
    outcome = _resolve(resolution=_resolution(environment="staging"))
    assert outcome.outcome is AuthStatus.ENVIRONMENT_UNCLASSIFIED
    assert outcome.environment_class is None


def test_gate_3_refuses_when_the_endpoint_did() -> None:
    """Phase 034's ten gates already ran; this layer adds nothing there."""
    outcome = _resolve(
        resolution=_resolution(outcome=ResolutionStatus.SURFACE_UNDOCUMENTED),
    )
    assert outcome.outcome is AuthStatus.ENDPOINT_UNRESOLVED


def test_gate_4_refuses_to_sign_a_public_request() -> None:
    """Signing one would attach a credential to a call that did not ask for one."""
    outcome = _resolve(security_type=SecurityType.NONE)
    assert outcome.outcome is AuthStatus.AUTHENTICATION_NOT_REQUIRED


def test_gate_5_refuses_when_no_credential_is_configured() -> None:
    """The state every host is in today, reported as what to do rather than as a fault."""
    outcome = _resolve(credentials={})
    assert outcome.outcome is AuthStatus.MISSING_CREDENTIAL
    assert "globin secrets set" in outcome.detail


def test_gate_6_refuses_a_key_type_the_endpoint_does_not_document() -> None:
    """The capability gate, reading `key_types` from the registry rather than a table."""
    outcome = _resolve(
        resolution=_resolution(key_types=(ApiKeyType.HMAC,)),
        credentials=_credentials(ApiKeyType.ED25519),
    )
    assert outcome.outcome is AuthStatus.CREDENTIAL_TYPE_MISMATCH
    assert "accepting hmac" in outcome.detail


def test_gate_6_refuses_a_configured_type_that_contradicts_the_credential() -> None:
    """Configuration and enrolment disagreeing is a different fault from either alone."""
    outcome = _resolve(
        policy=AuthPolicy(key_type=ApiKeyType.ED25519),
        credentials=_credentials(ApiKeyType.HMAC),
    )
    assert outcome.outcome is AuthStatus.CREDENTIAL_TYPE_MISMATCH


def test_gate_7_refuses_when_no_signer_can_compute_the_algorithm() -> None:
    """A missing library, named — and never a downgrade to a different algorithm."""
    outcome = _resolve(
        credentials=_credentials(ApiKeyType.ED25519),
        available=(SignatureAlgorithm.HMAC_SHA256,),
    )
    assert outcome.outcome is AuthStatus.SIGNER_UNAVAILABLE
    assert "cryptography" in outcome.detail
    assert "will not sign with a different algorithm" in outcome.detail


def test_a_host_with_no_asymmetric_signer_still_signs_hmac() -> None:
    """Degradation removes the recommended algorithm, not authentication."""
    outcome = _resolve(available=(SignatureAlgorithm.HMAC_SHA256,))
    assert outcome.permitted
    assert outcome.profile is not None
    assert outcome.profile.algorithm is SignatureAlgorithm.HMAC_SHA256


def test_a_resolved_gate_carries_a_profile_and_a_credential() -> None:
    """The positive case, so every refusal above is not vacuously satisfied."""
    outcome = _resolve()
    assert outcome.permitted
    assert outcome.profile is not None
    assert outcome.binding is not None
    assert outcome.environment_class is EnvironmentClass.VENUE_TESTNET


def test_a_refusal_carries_neither_a_profile_nor_a_credential() -> None:
    """The type doing the work: a caller ignoring the outcome has nothing to read."""
    with pytest.raises(ValidationError, match="must offer nothing"):
        AuthResolution(
            outcome=AuthStatus.MISSING_CREDENTIAL,
            family="spot",
            environment="testnet",
            security_type=SecurityType.USER_DATA,
            binding=_binding(),
            detail="a refusal that offers something",
        )


def test_a_permitted_resolution_without_a_profile_cannot_be_built() -> None:
    """The other direction of the same rule."""
    with pytest.raises(ValidationError, match="carries no profile"):
        AuthResolution(
            outcome=AuthStatus.RESOLVED,
            family="spot",
            environment="testnet",
            security_type=SecurityType.USER_DATA,
        )


def test_a_resolution_record_carries_no_credential_material() -> None:
    """Names and a key type, which is what a reference is."""
    record = _resolve().as_record()
    assert "venue_secret" in str(record)
    assert record["credential"]["material_name"] == "venue_secret"  # type: ignore[index]


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------


def _sign(
    signer: StubSigner | None = None,
    store: StubStore | None = None,
    **overrides: object,
) -> SigningOutcome:
    """Sign a request with sensible defaults.

    Args:
        signer: Which signer to use.
        store: Where material comes from.
        **overrides: Any argument to :func:`sign_request`.

    Returns:
        The outcome.
    """
    arguments: dict[str, object] = {
        "operation": "spot.account",
        "method": HttpMethod.GET,
        "path": "/v3/account",
        "parameters": QueryParameters(items=(("omitZeroBalances", True),)),
        "timing": signing_timing(instant(datetime(2017, 7, 12, 2, 41, 59, 559000, tzinfo=UTC))),
        "store": store or StubStore({"venue_key": "an-identifier", "venue_secret": "a-secret"}),
        "signer": signer or StubSigner(),
    }
    arguments.update(overrides)
    authorisation = arguments.pop("authorisation", _resolve())
    return sign_request(authorisation, **arguments)  # type: ignore[arg-type]


def test_signing_produces_a_request_whose_signed_span_is_a_prefix() -> None:
    """The invariant, end to end through the application layer."""
    outcome = _sign()
    assert outcome.signed
    assert outcome.request is not None
    assert outcome.request.wire_matches("/api")


def test_the_signer_receives_the_exact_canonical_bytes() -> None:
    """What the signer saw and what the wire carries, compared as strings."""
    signer = StubSigner()
    outcome = _sign(signer)
    assert outcome.request is not None
    assert signer.signed == [outcome.request.signed_span]
    target = outcome.request.request.canonical_target("/api")
    assert target.endswith(f"{signer.signed[0]}&{SIGNATURE_PARAMETER}={'cd' * 32}")


def test_the_timing_parameters_reach_the_signed_span() -> None:
    """A window in GLOBIN's record and absent from the request would be two requests."""
    outcome = _sign()
    assert outcome.request is not None
    assert "timestamp=1499827319559" in outcome.request.signed_span
    assert "recvWindow=5000" in outcome.request.signed_span


def test_the_api_key_reaches_the_header_and_not_the_query() -> None:
    """The key identifies; it does not authenticate, so it is never signed."""
    outcome = _sign()
    assert outcome.request is not None
    headers = dict(outcome.request.request.headers)
    assert headers[API_KEY_HEADER] == "an-identifier"
    assert "an-identifier" not in outcome.request.signed_span


def test_a_microsecond_policy_stamps_microseconds() -> None:
    """Both units the venue documents, chosen by configuration rather than inferred."""
    outcome = _sign(
        timing=signing_timing(
            instant(datetime(2017, 7, 12, 2, 41, 59, 559000, tzinfo=UTC)),
            unit=TimestampUnit.MICROSECONDS,
        )
    )
    assert outcome.request is not None
    assert outcome.request.timestamp == 1499827319559000
    assert outcome.request.timestamp_unit is TimestampUnit.MICROSECONDS


def test_a_configured_window_reaches_the_request() -> None:
    """Including its scale, because the venue sees the rendering."""
    outcome = _sign(
        timing=signing_timing(
            instant(datetime(2017, 7, 12, 2, 41, 59, 559000, tzinfo=UTC)),
            recv_window=RecvWindow(Decimal("6000.346")),
        )
    )
    assert outcome.request is not None
    assert "recvWindow=6000.346" in outcome.request.signed_span


def test_an_absent_signing_secret_is_reported_as_such() -> None:
    """A credential that is configured and will not resolve is its own fault."""
    outcome = _sign(store=StubStore({"venue_key": "an-identifier"}))
    assert outcome.outcome is AuthStatus.SECRET_MATERIALIZATION_FAILED
    assert outcome.request is None


def test_an_absent_api_key_is_reported_before_signing() -> None:
    """The key is resolved first, so a missing one costs no signature."""
    outcome = _sign(store=StubStore({"venue_secret": "a-secret"}))
    assert outcome.outcome is AuthStatus.SECRET_MATERIALIZATION_FAILED


def test_a_signer_that_refuses_the_key_reports_invalid_material() -> None:
    """A parse failure becomes a named status rather than an escaping exception."""
    outcome = _sign(FailingSigner())
    assert outcome.outcome is AuthStatus.INVALID_PRIVATE_KEY_MATERIAL
    assert "re-enrol it" in outcome.detail


def test_a_failure_message_carries_no_material() -> None:
    """Every branch is a constant joined to values GLOBIN already publishes."""
    outcome = _sign(FailingSigner(), store=StubStore({"venue_key": "k", "venue_secret": "s3cret"}))
    assert "s3cret" not in outcome.detail
    assert "did not parse" not in outcome.detail


def test_an_unavailable_signer_reads_no_material() -> None:
    """Availability is checked before the store, so refusing costs no key handling."""
    store = StubStore({"venue_key": "an-identifier", "venue_secret": "a-secret"})
    outcome = _sign(StubSigner(available=False), store=store)
    assert outcome.outcome is AuthStatus.SIGNER_UNAVAILABLE
    assert "venue_secret" not in store.asked


def test_signing_a_refused_resolution_raises() -> None:
    """A defect in a caller rather than a state of the world."""
    with pytest.raises(ValidationError, match="only a permitted resolution"):
        _sign(authorisation=_resolve(credentials={}))


def test_a_signing_outcome_record_carries_no_signature() -> None:
    """The record is a diagnostic, not a place a request could be reconstructed from."""
    outcome = _sign()
    assert "cd" * 32 not in str(outcome.as_record())


# ---------------------------------------------------------------------------
# The self-test and the summary
# ---------------------------------------------------------------------------


def test_the_self_test_passes_against_the_real_hmac_signer() -> None:
    """It recomputes the venue's own published vectors, so a pass means something."""
    from globin.adapters.signing import available_algorithms, hmac_signer

    report = self_test(hmac_signer(), available_algorithms())
    assert report.passed, [item.detail for item in report.failures]
    assert len(report.findings) == 8


def test_the_self_test_notices_a_signer_that_is_wrong() -> None:
    """A report that could not fail would be a formality."""
    report = self_test(StubSigner(), ALL_ALGORITHMS)
    failed = {item.check for item in report.failures}
    assert "auth.known_answer" in failed


def test_the_self_test_reports_an_unavailable_algorithm_without_failing() -> None:
    """A degraded host is a state rather than a fault, matching every other survey here."""
    from globin.adapters.signing import hmac_signer

    outcome = self_test(hmac_signer(), (SignatureAlgorithm.HMAC_SHA256,))
    registry = next(item for item in outcome.findings if item.check == "auth.signer_registry")
    assert registry.passed
    assert "unavailable on this host" in registry.detail


def test_a_credential_summary_carries_a_fingerprint_rather_than_a_key() -> None:
    """Enough to tell two credentials apart, and nothing reversible."""
    identifier = "an-invented-api-key-identifier-for-this-test"
    summary = credential_summary(_binding(), identifier)
    assert summary["configured"] is True
    assert summary["key_type"] == "hmac"
    assert isinstance(summary["fingerprint"], str)
    assert len(summary["fingerprint"]) == 12
    assert summary["fingerprint"] not in identifier


def test_an_unconfigured_credential_summarises_as_absent() -> None:
    """Rather than as an empty-looking value that could read as a real one."""
    summary = credential_summary(None)
    assert summary == {"configured": False, "key_type": None, "fingerprint": None}


def test_a_summary_with_no_resolved_key_omits_the_fingerprint() -> None:
    """`None` rather than an empty string, which would look like a fingerprint of nothing."""
    assert credential_summary(_binding())["fingerprint"] is None


# ---------------------------------------------------------------------------
# Guarding the guard
# ---------------------------------------------------------------------------
#
# `self_test` recomputes the phase's invariants and reports findings. Every
# assertion above checks that it *passes* -- which it would also do if its failure
# arms were unreachable or silently swallowed a problem. These break one invariant
# at a time and check the corresponding finding actually notices, which is the same
# shape as `test_the_section_name_check_would_catch_the_defect_it_was_written_for`
# in `tests/contract/test_bootstrap_contract.py`.


def test_the_mapping_check_notices_a_key_type_that_maps_nowhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If `algorithm_for` stopped being total, the self-test must say so."""

    def refuse(key_type: ApiKeyType) -> SignatureAlgorithm:
        msg = f"no algorithm for {key_type.value}"
        raise ValidationError(msg)

    monkeypatch.setattr("globin.application.auth.algorithm_for", refuse)
    finding = _mapping_finding()
    assert not finding.passed
    assert "hmac" in finding.detail


def test_the_mapping_check_notices_an_algorithm_that_does_not_map_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The round trip is the property; a one-way mapping is the defect it guards."""

    def always_ed25519(algorithm: SignatureAlgorithm) -> ApiKeyType:
        del algorithm
        return ApiKeyType.ED25519

    monkeypatch.setattr("globin.application.auth.key_type_for", always_ed25519)
    finding = _mapping_finding()
    assert not finding.passed
    assert "does not map back" in finding.detail


def test_the_recv_window_check_notices_a_changed_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5000 ms is documented; a silent change to it must not pass unnoticed."""
    monkeypatch.setattr(
        "globin.application.auth.default_recv_window", lambda: RecvWindow(Decimal(4000))
    )
    finding = _recv_window_finding()
    assert not finding.passed
    assert "documented as 5000" in finding.detail


def test_the_recv_window_check_notices_a_ceiling_that_stopped_being_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A window type that accepted anything would pass every other assertion here.

    The check works by handing `RecvWindow` values the venue documents as invalid
    and requiring each to be refused. This replaces it with one that accepts them,
    which is precisely the regression the check exists to catch.
    """

    class _Permissive:
        def __init__(self, millis: Decimal) -> None:
            self.millis = millis

    monkeypatch.setattr("globin.application.auth.RecvWindow", _Permissive)
    finding = _recv_window_finding()
    assert not finding.passed
    assert "60000.001 was accepted" in finding.detail
    assert "5000.1234 was accepted" in finding.detail


def test_the_recv_window_check_notices_the_documented_example_being_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`6000.346` is the venue's own published example, so refusing it is a defect.

    The three-decimal allowance is easy to lose to a rounding or a validation
    tightened without reading the source, and nothing else here would notice.
    """

    class _RefusesEverything:
        def __init__(self, millis: Decimal) -> None:
            msg = f"refused {millis}"
            raise ValidationError(msg)

    monkeypatch.setattr("globin.application.auth.RecvWindow", _RefusesEverything)
    finding = _recv_window_finding()
    assert not finding.passed
    assert "6000.346 was refused" in finding.detail


# ---------------------------------------------------------------------------
# Admission refusals no other test reaches
# ---------------------------------------------------------------------------


def test_a_key_type_with_no_mapped_algorithm_is_refused_rather_than_substituted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate behind the no-fallback rule, exercised rather than assumed.

    `algorithm_for` is total over `ApiKeyType` today, so this branch cannot be
    reached by choosing an input -- which is exactly why it was never exercised. A
    later phase adding a key type the venue documents but GLOBIN has not mapped
    would reach it, and what must happen then is a refusal naming the key type, not
    a signature under whatever algorithm happened to be nearest.
    """

    def refuse(key_type: ApiKeyType) -> SignatureAlgorithm:
        msg = f"no algorithm is mapped for {key_type.value}"
        raise ValidationError(msg)

    monkeypatch.setattr("globin.application.auth.algorithm_for", refuse)
    outcome = resolve_auth(
        _resolution(),
        security_type=SecurityType.USER_DATA,
        policy=AuthPolicy(key_type=ApiKeyType.HMAC),
        classification=_classification(),
        credentials=_credentials(),
        available=ALL_ALGORITHMS,
    )
    assert not outcome.permitted
    assert outcome.outcome is AuthStatus.UNSUPPORTED_SIGNING_ALGORITHM
    assert outcome.profile is None, "a refusal must carry no signing profile"


def test_a_non_positive_recv_window_is_refused() -> None:
    """`RecvWindow` refuses this at construction, and the gate refuses it again.

    Two guards for one rule looks redundant until the policy is assembled from
    somewhere that did not go through the value type. The gate is what a request
    passes through, so it does not delegate the question.
    """

    class _Window:
        """A window that never went through `RecvWindow`."""

        millis = Decimal(0)

    policy = AuthPolicy(key_type=ApiKeyType.HMAC)
    object.__setattr__(policy, "recv_window", _Window())

    outcome = resolve_auth(
        _resolution(),
        security_type=SecurityType.USER_DATA,
        policy=policy,
        classification=_classification(),
        credentials=_credentials(),
        available=ALL_ALGORITHMS,
    )
    assert not outcome.permitted
    assert outcome.outcome is AuthStatus.INVALID_RECV_WINDOW


def test_an_unresolved_endpoint_documents_no_key_types_at_all() -> None:
    """Not "every key type" and not a default -- the empty set.

    The key types come from the registry through the resolved endpoint. With no
    endpoint there is no registry row, and answering with anything non-empty would
    invent a capability for a surface the venue has not documented.
    """
    unresolved = _resolution(outcome=ResolutionStatus.SURFACE_UNDOCUMENTED)
    assert _documented_key_types(unresolved) == frozenset()


def test_the_wire_check_notices_when_the_signed_span_stops_matching_the_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The phase's central claim, and the arm that would report it broken.

    `auth.wire_equality` asserts two things at once: that the signed span is a
    literal prefix of the query that would be transmitted, and that a non-ASCII
    symbol was percent-encoded *before* signing. Both are properties of code
    outside this function -- the canonical renderer and the payload builder -- so
    the self-test is how a change to either surfaces.

    Every other assertion about it checks that it passes, which it would also do
    if these two branches were unreachable. Replacing the payload with one that
    satisfies neither property fires both, and the detail must name both.
    """

    def unencoded(*args: object, **kwargs: object) -> SigningPayload:
        del args, kwargs
        return SigningPayload(query_span="symbol=UNENCODED", body_span="")

    monkeypatch.setattr("globin.application.auth.signing_payload", unencoded)
    finding = _wire_finding(StubSigner())
    assert not finding.passed
    assert "not a prefix of the transmitted query string" in finding.detail
    assert "not percent-encoded before signing" in finding.detail


def test_the_wire_check_reports_a_signer_that_refuses_rather_than_raising() -> None:
    """A self-test that raised would take the whole report down with it.

    `globin auth selftest` exists to say what is wrong. A signer that refuses --
    which is what an absent `cryptography` produces for two of the three
    algorithms -- must therefore become a finding rather than a traceback.
    """
    finding = _wire_finding(FailingSigner())
    assert not finding.passed
    assert "signing failed" in finding.detail
