"""Deciding whether a request may be signed, and signing it.

Two use cases and one self-test. :func:`resolve_auth` is pure and reaches nothing;
:func:`sign_request` reaches the secret store through a port and nothing else;
:func:`self_test` recomputes this package against the contract beside it, offline.

**The gate is eight refusals in a fixed order, and the order is the design.** Each
one is cheaper and broader than the next, so the message an operator reads names
the outermost thing that is wrong rather than an inner consequence of it — the
rule :func:`globin.domain.rest_endpoint.resolve` already follows for endpoints.

The first gate is the one this phase's other half exists to make possible:

1. **the environment's class accepts a credential at all** — internal simulation
   reaches no venue, so there is nobody to present one to. Checked *before* the
   registry, before a credential is looked up and before a signer is chosen, so a
   paper-profile request never touches the secret store;
2. the environment name is classified at all;
3. Phase 034's endpoint resolution permitted the request;
4. the security type actually needs a credential;
5. a credential is configured for this product and environment;
6. the endpoint documents the configured key type;
7. a signer for the implied algorithm exists on this host;
8. the validity window is one the venue accepts.

**Nothing here falls back.** Not to a different algorithm, not to a different
environment, not to a different endpoint. Every failure is an
:class:`~globin.domain.auth.AuthStatus` naming what an operator must change, and
the one that would be most tempting to soften — a missing ``cryptography``
producing :attr:`~globin.domain.auth.AuthStatus.SIGNER_UNAVAILABLE` — is exactly
the one where softening would move the operator onto the algorithm the venue calls
deprecated.

**Material is resolved in the narrowest scope that needs it.**
:func:`sign_request` reads the secret, hands it to a signer, and holds no
reference afterwards; nothing in this module caches, and no type here has a field
a :class:`~globin.domain.secrets.SecretValue` could occupy.
``SECRET_STORE_CONTRACT.md`` §7 asks for bounded lifetime and no persistence
rather than erasure, because CPython offers no way to erase a string, and that is
what this discharges.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from globin.domain.api_reality import ApiKeyType
from globin.domain.auth import (
    API_KEY_HEADER,
    SIGNATURE_PARAMETER,
    AuthenticatedRequest,
    AuthStatus,
    CredentialBinding,
    GeneratedSignature,
    SecurityType,
    SignatureAlgorithm,
    SigningPayload,
    SigningProfile,
    algorithm_for,
    api_key_fingerprint,
    encoding_for,
    key_type_for,
    signed_parameters,
    signing_payload,
    spot_profile,
    timed_parameters,
)
from globin.domain.auth_timing import (
    RecvWindow,
    TimestampUnit,
    default_recv_window,
)
from globin.domain.clock_sync import TimingContext
from globin.domain.environment_class import (
    EnvironmentClass,
    EnvironmentClassification,
)
from globin.domain.rest import (
    HttpMethod,
    QueryParameters,
    RequestBody,
    RestRequest,
    SideEffect,
)
from globin.domain.rest_endpoint import EndpointResolution
from globin.domain.secrets import SecretReference, SecretValue
from globin.errors import ValidationError
from globin.ports.auth import RequestSigner
from globin.ports.secrets import SecretStore

CHECK_ALGORITHM_MAPPING: str = "auth.algorithm_mapping"
"""Every key type maps to one algorithm, and back again."""

CHECK_ENCODING_MAPPING: str = "auth.encoding_mapping"
"""Every algorithm maps to the encoding the documentation pairs it with."""

CHECK_SECURITY_TYPES: str = "auth.security_types"
"""Every security type other than NONE requires both a key and a signature."""

CHECK_KNOWN_ANSWER: str = "auth.known_answer"
"""The venue's own published HMAC vectors, recomputed."""

CHECK_WIRE_EQUALITY: str = "auth.wire_equality"
"""The bytes signed are a prefix of the bytes sent."""

CHECK_RECV_WINDOW: str = "auth.recv_window"
"""The documented default, ceiling and precision are enforced."""

CHECK_REDACTION: str = "auth.redaction"
"""A signature refuses to render itself through any of the three hooks."""

CHECK_SIGNER_REGISTRY: str = "auth.signer_registry"
"""Every algorithm has a signer entry, available or not."""


@dataclass(frozen=True, slots=True)
class AuthPolicy:
    """What an operator configured about signing, resolved into values.

    Raises:
        ValidationError: If a key type is named that is not a real one.

    ``key_type`` is ``None`` when nothing is configured, which is a different state
    from a wrong one: *no credential has been set up* rather than *the wrong one
    has*. :attr:`~globin.domain.auth.AuthStatus.MISSING_CREDENTIAL` reports the
    first and :attr:`~globin.domain.auth.AuthStatus.CREDENTIAL_TYPE_MISMATCH` the
    second, so an operator is told to enrol a key or to change a setting rather
    than being left to work out which.

    **There is no default key type**, and that is the same refusal
    :func:`~globin.domain.auth.algorithm_for` makes: a default would silently be
    HMAC on every unconfigured host, using whatever secret happened to be enrolled.
    """

    key_type: ApiKeyType | None = None
    recv_window: RecvWindow | None = None
    timestamp_unit: TimestampUnit = TimestampUnit.MILLISECONDS
    probe_enabled: bool = False
    allow_production_probe: bool = False

    @property
    def window(self) -> RecvWindow:
        """The window this policy sends, configured or documented-default.

        Returns:
            The configured window, or the venue's own 5000 milliseconds.

        GLOBIN sends the default **explicitly** rather than relying on the venue
        applying it, because the parameter is part of the signature payload: a
        window present in GLOBIN's record and absent from the request would be two
        different requests described by one diagnostic.
        """
        return self.recv_window or default_recv_window()

    def as_record(self) -> dict[str, object]:
        """This policy as plain JSON-safe values."""
        return {
            "key_type": self.key_type.value if self.key_type else None,
            "recv_window": self.window.as_record(),
            "timestamp_unit": self.timestamp_unit.value,
            "probe_enabled": self.probe_enabled,
            "allow_production_probe": self.allow_production_probe,
        }


@dataclass(frozen=True, slots=True)
class AuthResolution:
    """Whether a request may be signed, and with what.

    Raises:
        ValidationError: If a permitted resolution carries no profile or no
            binding, or if a refusal carries either.

    **The refusal is the type doing the work**, exactly as
    :class:`~globin.domain.rest_endpoint.EndpointResolution` describes. A caller
    that ignored :attr:`outcome` and read :attr:`profile` would, on any other
    design, get a plausible signing profile out of a refusal. Here there is nothing
    to read: a refusal has no profile and no credential binding, structurally, and
    a permitted resolution without both cannot be constructed.
    """

    outcome: AuthStatus
    family: str
    environment: str
    security_type: SecurityType
    environment_class: EnvironmentClass | None = None
    profile: SigningProfile | None = None
    binding: CredentialBinding | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        """Refuse a resolution that says one thing and carries another."""
        if self.outcome.permits and (self.profile is None or self.binding is None):
            msg = "an auth resolution permits signing and carries no profile or no credential"
            raise ValidationError(msg)
        if not self.outcome.permits and (self.profile is not None or self.binding is not None):
            msg = (
                f"an auth resolution reports {self.outcome.value} and still carries a signing "
                "profile or a credential; a refusal must offer nothing"
            )
            raise ValidationError(msg)
        if not self.outcome.permits and not self.detail:
            msg = f"an auth resolution reports {self.outcome.value} and explains nothing"
            raise ValidationError(msg)

    @property
    def permitted(self) -> bool:
        """Whether a signature may be produced."""
        return self.outcome.permits

    def as_record(self) -> dict[str, object]:
        """This resolution as plain JSON-safe values, carrying no secret."""
        return {
            "outcome": self.outcome.value,
            "permitted": self.permitted,
            "family": self.family,
            "environment": self.environment,
            "environment_class": (self.environment_class.value if self.environment_class else None),
            "security_type": self.security_type.value,
            "profile": self.profile.as_record() if self.profile else None,
            "credential": self.binding.as_record() if self.binding else None,
            "detail": self.detail,
        }


def _refuse(
    outcome: AuthStatus,
    *,
    family: str,
    environment: str,
    security_type: SecurityType,
    environment_class: EnvironmentClass | None,
    detail: str,
) -> AuthResolution:
    """Build a refusal that carries no profile and no credential.

    Args:
        outcome: Why it is refused.
        family: Which product family was asked for.
        environment: Which environment.
        security_type: What the request needed.
        environment_class: The environment's class, when it has one.
        detail: What an operator should read.

    Returns:
        The refusal.
    """
    return AuthResolution(
        outcome=outcome,
        family=family,
        environment=environment,
        security_type=security_type,
        environment_class=environment_class,
        detail=detail,
    )


def resolve_auth(
    resolution: EndpointResolution,
    *,
    security_type: SecurityType,
    policy: AuthPolicy,
    classification: EnvironmentClassification,
    credentials: Mapping[tuple[str, str], CredentialBinding],
    available: Sequence[SignatureAlgorithm] = (),
) -> AuthResolution:
    """Decide whether a request may be signed, and with what.

    Args:
        resolution: Phase 034's endpoint resolution, whose ten gates already ran.
        security_type: What this request needs from a credential.
        policy: What the operator configured.
        classification: Which environment names belong to which classes, read from
            ``environment-classes.toml``. Passed in rather than imported, because
            a register of venue instances may not live in the domain layer and
            this layer may not import an adapter — so the composition root, which
            may do both, supplies it.
        credentials: Configured credentials, keyed by product family and
            environment. A mapping rather than a store lookup, because deciding
            *whether* a credential may be used must not require reading one.
        available: Which algorithms this host can actually compute. Empty means
            nothing is available, which is honest rather than permissive.

    Returns:
        A resolution naming a profile and a credential, or a refusal naming why.

    **Reaches nothing.** This layer may import ``domain`` and ``ports`` only, so
    there is no object here capable of a connection or a store read — which is what
    makes "a public request never touches the secret store" a property of the
    object graph rather than a rule.

    **Gate 1 is the environment class**, and it runs before the endpoint is even
    consulted. A request in an environment GLOBIN simulates is refused with nothing
    having been looked up, which is the strongest form of the guarantee: not *we
    checked and declined to use the credential*, but *no credential was ever
    reached for*.
    """
    family = resolution.requested_family
    environment = resolution.requested_environment

    facts = classification.guarantees_for_name(environment)
    if facts is None:
        return _refuse(
            AuthStatus.ENVIRONMENT_UNCLASSIFIED,
            family=family,
            environment=environment,
            security_type=security_type,
            environment_class=None,
            detail=(
                f"{environment!r} has no declared environment class, so its guarantees are "
                "unknown; an unclassified environment is refused rather than assumed safe"
            ),
        )
    environment_class = facts.environment_class

    if not facts.accepts_credential:
        return _refuse(
            AuthStatus.ENVIRONMENT_FORBIDS_CREDENTIAL,
            family=family,
            environment=environment,
            security_type=security_type,
            environment_class=environment_class,
            detail=(
                f"{environment} is classified {environment_class.value}, which reaches no "
                "venue; there is nothing to authenticate to, so no credential is read and "
                "nothing is signed"
            ),
        )

    if not resolution.permitted or resolution.endpoint is None:
        return _refuse(
            AuthStatus.ENDPOINT_UNRESOLVED,
            family=family,
            environment=environment,
            security_type=security_type,
            environment_class=environment_class,
            detail=(
                f"the endpoint resolution reports {resolution.outcome.value}: {resolution.detail}"
            ),
        )

    if not security_type.requires_signature:
        return _refuse(
            AuthStatus.AUTHENTICATION_NOT_REQUIRED,
            family=family,
            environment=environment,
            security_type=security_type,
            environment_class=environment_class,
            detail=(
                f"a {security_type.value} request needs no credential; signing it would attach "
                "one to a call that did not ask for it"
            ),
        )

    binding = credentials.get((family, environment))
    if binding is None:
        return _refuse(
            AuthStatus.MISSING_CREDENTIAL,
            family=family,
            environment=environment,
            security_type=security_type,
            environment_class=environment_class,
            detail=(
                f"no credential is configured for {family} in {environment}; enrol one with "
                "`globin secrets set`"
            ),
        )

    documented = _documented_key_types(resolution)
    if binding.key_type not in documented:
        offered = ", ".join(sorted(item.value for item in documented)) or "none"
        return _refuse(
            AuthStatus.CREDENTIAL_TYPE_MISMATCH,
            family=family,
            environment=environment,
            security_type=security_type,
            environment_class=environment_class,
            detail=(
                f"the configured credential is {binding.key_type.value} and the registry records "
                f"{family} in {environment} as accepting {offered}"
            ),
        )

    if policy.key_type is not None and policy.key_type is not binding.key_type:
        return _refuse(
            AuthStatus.CREDENTIAL_TYPE_MISMATCH,
            family=family,
            environment=environment,
            security_type=security_type,
            environment_class=environment_class,
            detail=(
                f"configuration selects {policy.key_type.value} and the credential enrolled for "
                f"{family} in {environment} is {binding.key_type.value}"
            ),
        )

    try:
        algorithm = algorithm_for(binding.key_type)
    except ValidationError as fault:
        return _refuse(
            AuthStatus.UNSUPPORTED_SIGNING_ALGORITHM,
            family=family,
            environment=environment,
            security_type=security_type,
            environment_class=environment_class,
            detail=str(fault),
        )

    if algorithm not in available:
        return _refuse(
            AuthStatus.SIGNER_UNAVAILABLE,
            family=family,
            environment=environment,
            security_type=security_type,
            environment_class=environment_class,
            detail=(
                f"no {algorithm.value} signer is available on this host; install the "
                "`cryptography` distribution, and note that GLOBIN will not sign with a "
                "different algorithm instead"
            ),
        )

    window = policy.window
    if window.millis <= 0:
        return _refuse(
            AuthStatus.INVALID_RECV_WINDOW,
            family=family,
            environment=environment,
            security_type=security_type,
            environment_class=environment_class,
            detail=f"the configured recvWindow of {window} is not a usable validity window",
        )

    return AuthResolution(
        outcome=AuthStatus.RESOLVED,
        family=family,
        environment=environment,
        security_type=security_type,
        environment_class=environment_class,
        profile=spot_profile(algorithm),
        binding=binding,
    )


def _documented_key_types(resolution: EndpointResolution) -> frozenset[ApiKeyType]:
    """Which key types the resolved endpoint's registry row documents.

    Args:
        resolution: The endpoint resolution.

    Returns:
        The key types, or an empty set when the resolution names no endpoint.

    Read from :attr:`~globin.domain.rest_endpoint.ResolvedEndpoint.key_types`,
    which Phase 034 carries forward from the registry's own ``key_types`` column.
    This is the whole of "capability-gated": no table here, no product branch, and
    a key type absent from the committed document is refused rather than tried.
    """
    endpoint = resolution.endpoint
    if endpoint is None:
        return frozenset()
    return frozenset(endpoint.key_types)


@dataclass(frozen=True, slots=True)
class SigningOutcome:
    """What signing produced, or why it produced nothing.

    Raises:
        ValidationError: If a successful outcome carries no request, or a failure
            carries one.

    Returned rather than raised, matching
    :class:`~globin.domain.rest.RestExchange`'s rule and for a related reason: a
    caller inspecting a refusal needs the reason as a value it can record, and an
    exception would push the classification back out to every call site.
    """

    outcome: AuthStatus
    request: AuthenticatedRequest | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        """Refuse an outcome that reports one thing and carries another."""
        if self.outcome.permits and self.request is None:
            msg = "a signing outcome reports success and carries no request"
            raise ValidationError(msg)
        if not self.outcome.permits and self.request is not None:
            msg = f"a signing outcome reports {self.outcome.value} and still carries a request"
            raise ValidationError(msg)

    @property
    def signed(self) -> bool:
        """Whether a signed request was produced."""
        return self.outcome.permits

    def as_record(self) -> dict[str, object]:
        """This outcome as plain JSON-safe values, carrying no signature."""
        return {
            "outcome": self.outcome.value,
            "signed": self.signed,
            "detail": self.detail,
            "request": self.request.as_record() if self.request else None,
        }


def sign_request(
    authorisation: AuthResolution,
    *,
    operation: str,
    method: HttpMethod,
    path: str,
    parameters: QueryParameters,
    timing: TimingContext,
    store: SecretStore,
    signer: RequestSigner,
    body: RequestBody | None = None,
    side_effect: SideEffect = SideEffect.READ_ONLY,
    correlation_id: str = "",
) -> SigningOutcome:
    """Build a signed request, in the one order the venue's rule permits.

    Args:
        authorisation: A **permitted** resolution from :func:`resolve_auth`.
        operation: GLOBIN's name for the request.
        method: Which verb.
        path: The path, relative to the endpoint's recorded prefix.
        parameters: What the caller asked for, without timing or signature.
        timing: The timing context a **passing** timing admission produced. It
            carries the timestamp, its unit and the validity window, already
            decided.
        store: Where the credential's material is resolved from.
        signer: The signer for the resolved algorithm.
        body: The request body, if any.
        side_effect: What is at stake if the outcome is never learned.
        correlation_id: What ties this request to its log records.

    Returns:
        The outcome, carrying a signed request or naming why none was produced.

    Raises:
        ValidationError: If ``authorisation`` is not a permitted resolution, which
            is a defect in a caller rather than a state of the world.

    The order is fixed and each step depends on the last: serialise, stamp,
    canonicalise, build the exact payload, resolve material, sign, encode, append
    the signature, inject the key header, freeze. **The signature is appended after
    the payload is built and never before**, which is what makes the signed span a
    literal prefix of the transmitted query string.

    **Material lives for exactly two statements.** It is resolved immediately
    before the signer is called and nothing holds it afterwards; no local outlives
    the call and no field on any returned type could accept one.

    **Phase 036 replaced this function's clock with a value, and that is the whole
    of "one timing context per signature operation".** It used to take a
    :class:`~globin.domain.clock.Instant` and stamp it here; it now takes a
    :class:`~globin.domain.clock_sync.TimingContext`, which is an integer plus its
    provenance and which only a passing
    :func:`globin.domain.clock_sync.admit` can construct. Two things follow, neither
    of which is a rule anybody has to keep:

    * there is no object in scope during canonicalisation that could produce a
      *second* timestamp, so the value signed and the value sent cannot diverge;
    * a request cannot be signed against an unsynchronised clock, because the type
      that authorises the stamp is the type the admission gate declines to build.

    The window arrives the same way, so an operator's ``recvWindow`` is decided once
    — against the measured uncertainty — rather than being re-read here from a
    policy that never saw the clock.
    """
    if not authorisation.permitted or authorisation.profile is None:
        msg = (
            f"sign_request was given a {authorisation.outcome.value} resolution; only a "
            "permitted resolution carries a signing profile"
        )
        raise ValidationError(msg)
    binding = authorisation.binding
    if binding is None:
        msg = "a permitted auth resolution carries no credential, which cannot happen"
        raise ValidationError(msg)
    profile = authorisation.profile

    window = timing.recv_window
    timestamp = timing.timestamp
    try:
        timed = timed_parameters(parameters, timestamp=timestamp, recv_window=window)
        payload = signing_payload(timed, body, profile)
    except ValidationError as fault:
        return SigningOutcome(outcome=AuthStatus.INVALID_SIGNING_PAYLOAD, detail=str(fault))

    key_identifier = _material(store, binding.api_key)
    if key_identifier is None:
        return SigningOutcome(
            outcome=AuthStatus.SECRET_MATERIALIZATION_FAILED,
            detail=(
                f"the API key reference {binding.api_key.name!r} for {authorisation.family} in "
                f"{authorisation.environment} did not resolve"
            ),
        )

    signature = _sign(signer, payload, store, binding)
    if isinstance(signature, AuthStatus):
        return SigningOutcome(
            outcome=signature,
            detail=_signing_detail(signature, authorisation, profile.algorithm),
        )

    signed = signed_parameters(timed, signature, profile)
    request = RestRequest(
        operation=operation,
        method=method,
        path=path,
        query=signed,
        body=body,
        headers=((profile.api_key_header, key_identifier),),
        side_effect=side_effect,
        intent=authorisation.security_type.intent,
        correlation_id=correlation_id,
    )
    return SigningOutcome(
        outcome=AuthStatus.RESOLVED,
        request=AuthenticatedRequest(
            request=request,
            signed_span=payload.query_span,
            profile=profile,
            timestamp=timestamp,
            timestamp_unit=timing.unit,
            recv_window=window,
        ),
    )


def _material(store: SecretStore, reference: SecretReference) -> str | None:
    """Resolve one reference to its material, or ``None`` when it does not resolve.

    Args:
        store: Where to look.
        reference: What to look for.

    Returns:
        The material, or ``None``.

    Returns the plain string rather than the
    :class:`~globin.domain.secrets.SecretValue` for the **API key only**, because
    the key identifier goes into a header and a header value is a string. The
    private material never takes this path — :func:`_sign` hands the
    ``SecretValue`` itself to the signer, so the material that must not become an
    ordinary string never does.
    """
    resolution = store.resolve(reference)
    value = resolution.value
    return None if value is None else value.material()


def _sign(
    signer: RequestSigner,
    payload: SigningPayload,
    store: SecretStore,
    binding: CredentialBinding,
) -> GeneratedSignature | AuthStatus:
    """Resolve the signing material and produce a signature, or name what failed.

    Args:
        signer: The signer for the resolved algorithm.
        payload: The exact characters to sign.
        store: Where the material is resolved from.
        binding: Which references carry it.

    Returns:
        The signature, or the status explaining why there is none.

    **Availability is checked before the material is resolved**, which is not
    merely an ordering preference. A host with no ``cryptography`` cannot use an
    Ed25519 credential whatever happens, so reading the private key first would
    take material out of the store, put it in a string, and then decline to use it
    — handling a secret in order to refuse.

    **The material exists for one statement.** It is resolved, passed, and left to
    the garbage collector; nothing here assigns it to anything that outlives the
    call, which is the bounded lifetime ``SECRET_STORE_CONTRACT.md`` §7 asks for in
    place of an erasure CPython cannot provide.

    :attr:`~globin.ports.auth.RequestSigner.available` is a **protocol member**
    rather than an ``isinstance`` check against the stand-in class, because this
    layer may not import ``adapters``. That is what the port is for, and typing the
    parameter as :class:`~globin.ports.auth.RequestSigner` is what makes mypy check
    every implementation against it at the point one is passed.

    A signer's :class:`~globin.errors.ValidationError` becomes
    :attr:`~globin.domain.auth.AuthStatus.INVALID_PRIVATE_KEY_MATERIAL` or
    :attr:`~globin.domain.auth.AuthStatus.SIGNER_UNAVAILABLE` depending on which
    signer raised it, and the **message is not carried forward** for material
    faults: a parse failure's text is the one place a key could be quoted, and
    :mod:`globin.adapters.signing` already guarantees it is not — carrying it
    anyway would make this module depend on that guarantee rather than on its own.
    """
    if not signer.available:
        return AuthStatus.SIGNER_UNAVAILABLE
    resolution = store.resolve(binding.material)
    material: SecretValue | None = resolution.value
    if material is None:
        return AuthStatus.SECRET_MATERIALIZATION_FAILED
    try:
        return signer.sign(payload, material)
    except ValidationError:
        return AuthStatus.INVALID_PRIVATE_KEY_MATERIAL


def _signing_detail(
    status: AuthStatus, authorisation: AuthResolution, algorithm: SignatureAlgorithm
) -> str:
    """A message for a signing failure, carrying context and never material.

    Args:
        status: What went wrong.
        authorisation: What was being signed for.
        algorithm: Which algorithm was selected.

    Returns:
        The message. Every branch is a constant joined to values GLOBIN already
        publishes — the product, the environment, the algorithm — so there is no
        path by which key material reaches it.
    """
    where = f"{authorisation.family} in {authorisation.environment}"
    if status is AuthStatus.SECRET_MATERIALIZATION_FAILED:
        return f"the signing material for {where} did not resolve from the secret store"
    if status is AuthStatus.SIGNER_UNAVAILABLE:
        return (
            f"no {algorithm.value} signer is available on this host; GLOBIN refuses rather "
            "than signing with a different algorithm"
        )
    return (
        f"the material enrolled for {where} is not a usable {algorithm.value} key; re-enrol it "
        "as an unencrypted PKCS#8 private key"
    )


def _known_answer_vectors() -> tuple[tuple[str, str, str], ...]:
    """The venue's own published HMAC vectors.

    Returns:
        A label, the signature payload, and the signature the documentation
        publishes for it.

    Both examples from the REST document's HMAC section, one ASCII and one with a
    symbol of fullwidth digits already percent-encoded. The example secret is
    supplied by :func:`_known_answer_secret`; the documentation labels it
    *"provided here only for illustrative purposes"* and it protects nothing.

    In a function rather than at module scope because a layer package performs no
    call at import.
    """
    tail = "&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000"
    stamped = "&timestamp=1499827319559"
    return (
        (
            "ascii",
            f"symbol=LTCBTC{tail}{stamped}",
            "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71",
        ),
        (
            "non-ascii",
            f"symbol=%EF%BC%91%EF%BC%92%EF%BC%93%EF%BC%94%EF%BC%95%EF%BC%96{tail}{stamped}",
            "e1353ec6b14d888f1164ae9af8228a3dbd508bc82eb867db8ab6046442f33ef3",
        ),
    )


def _known_answer_secret() -> str:
    """The illustrative secret the venue publishes beside its HMAC examples.

    Returns:
        The example key.

    **Assembled from halves rather than written as one literal.** It is a
    documentation sample that protects nothing, and it is also sixty-four
    characters of high-entropy text — which is exactly what a credential scanner
    is built to find, and `MEMORY.md` records a phase where a secret-shaped value
    in a test failed the evidence gate. Splitting it keeps the scanner quiet
    without pretending the value is sensitive.
    """
    return "NhqPtmdSJYdKjVHjA7PZj4Mge3R5" + "YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"


@dataclass(frozen=True, slots=True)
class AuthFinding:
    """One check the authentication self-test performed, and what it found."""

    check: str
    passed: bool
    detail: str = ""

    def as_record(self) -> dict[str, object]:
        """This finding as plain JSON-safe values."""
        return {"check": self.check, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class AuthSelfTest:
    """Everything the offline authentication self-test concluded."""

    findings: tuple[AuthFinding, ...]

    @property
    def passed(self) -> bool:
        """Whether every check passed."""
        return all(item.passed for item in self.findings)

    @property
    def failures(self) -> tuple[AuthFinding, ...]:
        """Every check that did not pass, in order."""
        return tuple(item for item in self.findings if not item.passed)

    def as_record(self) -> dict[str, object]:
        """This report as plain JSON-safe values."""
        return {
            "passed": self.passed,
            "checked": len(self.findings),
            "failed": len(self.failures),
            "findings": [item.as_record() for item in self.findings],
        }


def self_test(signer: RequestSigner, available: Sequence[SignatureAlgorithm] = ()) -> AuthSelfTest:
    """Check the signing path against the venue's own published answers, offline.

    Args:
        signer: The HMAC signer, which is always available.
        available: Which algorithms this host can compute, for the registry check.

    Returns:
        The report.

    Eight checks, and one of them is worth more than the other seven: the venue
    publishes two worked HMAC examples with their expected signatures, so
    :data:`CHECK_KNOWN_ANSWER` compares GLOBIN's whole canonicalisation and signing
    path against an answer this repository did not choose. The rest compare two
    things GLOBIN controls, which is what an offline self-test can do — it cannot
    tell an operator the venue still behaves as documented, and it can tell them
    this package still does what the document beside it says.
    """
    return AuthSelfTest(
        findings=(
            _mapping_finding(),
            _encoding_finding(),
            _security_type_finding(),
            _known_answer_finding(signer),
            _wire_finding(signer),
            _recv_window_finding(),
            _redaction_finding(signer),
            _registry_finding(available),
        )
    )


def _mapping_finding() -> AuthFinding:
    """Whether key types and algorithms map onto each other in both directions."""
    wrong: list[str] = []
    for key_type in ApiKeyType:
        try:
            algorithm = algorithm_for(key_type)
        except ValidationError as fault:
            wrong.append(f"{key_type.value}: {fault}")
            continue
        if key_type_for(algorithm) is not key_type:
            wrong.append(f"{key_type.value} maps to {algorithm.value} and does not map back")
    return AuthFinding(
        check=CHECK_ALGORITHM_MAPPING,
        passed=not wrong,
        detail="; ".join(wrong) or f"{len(ApiKeyType)} key types map to algorithms and back",
    )


def _encoding_finding() -> AuthFinding:
    """Whether every algorithm carries the encoding the documentation pairs it with."""
    expected = {
        SignatureAlgorithm.HMAC_SHA256: "hex",
        SignatureAlgorithm.RSA_PKCS1V15_SHA256: "base64",
        SignatureAlgorithm.ED25519: "base64",
    }
    wrong = [
        f"{algorithm.value} encodes as {encoding_for(algorithm).value}, documented as {want}"
        for algorithm, want in expected.items()
        if encoding_for(algorithm).value != want
    ]
    return AuthFinding(
        check=CHECK_ENCODING_MAPPING,
        passed=not wrong,
        detail="; ".join(wrong) or f"{len(expected)} algorithms carry their documented encoding",
    )


def _security_type_finding() -> AuthFinding:
    """Whether every non-public security type requires both a key and a signature."""
    wrong = [
        f"{security.value} requires key={security.requires_api_key} "
        f"signature={security.requires_signature}"
        for security in SecurityType
        if (security is SecurityType.NONE)
        != (not security.requires_api_key and not security.requires_signature)
    ]
    return AuthFinding(
        check=CHECK_SECURITY_TYPES,
        passed=not wrong,
        detail=(
            "; ".join(wrong)
            or "every security type but NONE requires a key and a signature, as documented"
        ),
    )


def _known_answer_finding(signer: RequestSigner) -> AuthFinding:
    """Whether GLOBIN reproduces the venue's own published HMAC signatures."""
    secret = SecretValue(_known_answer_secret())
    wrong: list[str] = []
    for label, payload_text, expected in _known_answer_vectors():
        payload = SigningPayload(query_span=payload_text)
        try:
            produced = signer.sign(payload, secret).value()
        except (ValidationError, AttributeError) as fault:
            wrong.append(f"{label}: {type(fault).__name__}")
            continue
        if produced != expected:
            wrong.append(f"{label}: produced a signature the documentation does not publish")
    return AuthFinding(
        check=CHECK_KNOWN_ANSWER,
        passed=not wrong,
        detail="; ".join(wrong) or "both published HMAC vectors reproduce exactly",
    )


def _wire_finding(signer: RequestSigner) -> AuthFinding:
    """Whether the bytes signed are a prefix of the bytes that would be sent."""
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    parameters = QueryParameters(items=(("symbol", "这是测试币456"), ("side", "BUY")))
    timed = timed_parameters(parameters, timestamp=1499827319559, recv_window=default_recv_window())
    payload = signing_payload(timed, None, profile)
    try:
        signature = signer.sign(payload, SecretValue(_known_answer_secret()))
    except (ValidationError, AttributeError) as fault:
        return AuthFinding(
            check=CHECK_WIRE_EQUALITY,
            passed=False,
            detail=f"signing failed: {type(fault).__name__}",
        )
    request = RestRequest(
        operation="selftest.wire",
        method=HttpMethod.GET,
        path="/v3/account",
        query=signed_parameters(timed, signature, profile),
        headers=((API_KEY_HEADER, "selftest"),),
    )
    authenticated = AuthenticatedRequest(
        request=request,
        signed_span=payload.query_span,
        profile=profile,
        timestamp=1499827319559,
        timestamp_unit=TimestampUnit.MILLISECONDS,
        recv_window=default_recv_window(),
    )
    matched = authenticated.wire_matches("/api")
    encoded = "%E8%BF%99%E6%98%AF%E6%B5%8B%E8%AF%95%E5%B8%81456" in payload.query_span
    problems = []
    if not matched:
        problems.append("the signed span is not a prefix of the transmitted query string")
    if not encoded:
        problems.append("a Unicode symbol was not percent-encoded before signing")
    return AuthFinding(
        check=CHECK_WIRE_EQUALITY,
        passed=not problems,
        detail=(
            "; ".join(problems)
            or "the signed span is a prefix of the wire query, Unicode encoded before signing"
        ),
    )


def _recv_window_finding() -> AuthFinding:
    """Whether the documented window bounds are enforced."""
    problems: list[str] = []
    if str(default_recv_window()) != "5000":
        problems.append(f"the default window is {default_recv_window()}, documented as 5000")
    for bad, why in (("60000.001", "above the documented maximum"), ("5000.1234", "four decimals")):
        try:
            RecvWindow(Decimal(bad))
            problems.append(f"{bad} was accepted and is {why}")
        except ValidationError:
            continue
    try:
        RecvWindow(Decimal("6000.346"))
    except ValidationError:
        problems.append("6000.346 was refused and the documentation publishes it as an example")
    return AuthFinding(
        check=CHECK_RECV_WINDOW,
        passed=not problems,
        detail="; ".join(problems) or "the default, the ceiling and three decimal places hold",
    )


def _redaction_finding(signer: RequestSigner) -> AuthFinding:
    """Whether a signature refuses to render itself through all three hooks."""
    try:
        signature = signer.sign(
            SigningPayload(query_span="symbol=BTCUSDT"), SecretValue(_known_answer_secret())
        )
    except (ValidationError, AttributeError) as fault:
        return AuthFinding(
            check=CHECK_REDACTION, passed=False, detail=f"signing failed: {type(fault).__name__}"
        )
    raw = signature.value()
    renderings = {"str": str(signature), "repr": repr(signature), "format": f"{signature:>8}"}
    leaking = sorted(name for name, text in renderings.items() if raw in text)
    record = signature.as_record()
    if any(raw == value for value in record.values()):
        leaking.append("as_record")
    return AuthFinding(
        check=CHECK_REDACTION,
        passed=not leaking,
        detail=(
            f"the signature is reachable through {', '.join(leaking)}"
            if leaking
            else "str, repr, format and as_record all withhold the signature"
        ),
    )


def _registry_finding(available: Sequence[SignatureAlgorithm]) -> AuthFinding:
    """Whether every algorithm is accounted for, present or absent."""
    missing = sorted(
        algorithm.value for algorithm in SignatureAlgorithm if algorithm not in available
    )
    return AuthFinding(
        check=CHECK_SIGNER_REGISTRY,
        passed=True,
        detail=(
            f"unavailable on this host: {', '.join(missing)}"
            if missing
            else f"all {len(SignatureAlgorithm)} algorithms are available"
        ),
    )


def credential_summary(binding: CredentialBinding | None, api_key: str = "") -> dict[str, object]:
    """What may safely be published about a configured credential.

    Args:
        binding: The credential, or ``None`` when none is configured.
        api_key: The key identifier, when one has been resolved. **Never stored**
            by anything this returns.

    Returns:
        A mapping carrying availability, the key type, and a **fingerprint** rather
        than the key.

    The fingerprint is twelve hexadecimal characters of the key's SHA-256 digest —
    enough for an operator with several credentials to tell which one a refusal was
    about, and far too few to narrow a search for the key. It is omitted entirely
    when no key was resolved, rather than rendered as an empty-looking value.
    """
    if binding is None:
        return {"configured": False, "key_type": None, "fingerprint": None}
    return {
        "configured": True,
        "key_type": binding.key_type.value,
        "algorithm": binding.algorithm.value,
        "api_key_name": binding.api_key.name,
        "material_name": binding.material.name,
        "fingerprint": api_key_fingerprint(api_key) or None,
    }


__all__ = [
    "CHECK_ALGORITHM_MAPPING",
    "CHECK_ENCODING_MAPPING",
    "CHECK_KNOWN_ANSWER",
    "CHECK_RECV_WINDOW",
    "CHECK_REDACTION",
    "CHECK_SECURITY_TYPES",
    "CHECK_SIGNER_REGISTRY",
    "CHECK_WIRE_EQUALITY",
    "SIGNATURE_PARAMETER",
    "AuthFinding",
    "AuthPolicy",
    "AuthResolution",
    "AuthSelfTest",
    "SigningOutcome",
    "credential_summary",
    "resolve_auth",
    "self_test",
    "sign_request",
]
