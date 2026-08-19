"""Which endpoint a request may go to, decided only from what Phase 033 recorded.

The whole of GLOBIN's endpoint knowledge is one committed document, and this module
is the only thing that turns it into a decision. There is no table of base URLs
here, no ``if family == ...`` and no default host: every fact comes from an
:class:`~globin.domain.api_reality.ApiRealitySnapshot`, and a combination the
registry does not describe is refused rather than guessed at.

**Read-only by the layer contract, not by discipline.** This module is in the
domain layer, which ``docs/architecture/dependency-rules.toml`` forbids from
importing anything I/O-capable. So ``globin rest resolve`` cannot open a socket
even by mistake — the same argument
[ADR-0085](../../../docs/adr/0085-a-plan-is-derived-from-a-report-and-one-module-may-start-a-process.md)
makes for ``bootstrap plan`` being read-only because the planner is pure.

**Nothing falls back and nothing fails over.** Three refusals here are the security
property of Phase 034, and each is structural rather than a rule somebody follows:

*Testnet never becomes production.* The only source of candidates is
:meth:`~globin.domain.api_reality.ApiRealitySnapshot.endpoints_for`, which filters
on the environment *before* returning. An environment with no recorded endpoint
therefore yields an empty tuple and a refusal naming the absence. There is no
branch in which a production URL is reachable from a testnet request, because
production endpoints are never in the candidate set.

*Demo never becomes testnet.* Same mechanism. Phase 033 files them as distinct
environments with distinct host markers, so they never share a candidate set.

*A market-data host never serves an order.* The venue publishes an unauthenticated
market-data-only host, and Phase 033 records its capabilities as exactly
``["market_data"]``. A caller asks for the capability it needs, and an endpoint that
does not list it is not a candidate.

**A resolution is fixed for the life of a request.** :class:`EndpointRole` is
returned so a caller can *see* that alternates exist; nothing here chooses between
them dynamically and nothing retries against a second one. Replaying an ambiguous
mutating request against a different host is how one order becomes two, and Phase
043 inherits the prohibition rather than being trusted with the choice.
"""

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum

from globin.domain.api_reality import (
    ApiRealitySnapshot,
    AuthMechanism,
    EndpointRecord,
    EnvironmentName,
    ProductFamily,
    ProtocolKind,
    SchemaFamilyName,
    SurfaceCapability,
    SurfaceStatus,
)
from globin.domain.rest import (
    EndpointRole,
    RequestSecurityIntent,
    ResponseEncoding,
    SbeSchemaReference,
)
from globin.errors import ValidationError

REST: ProtocolKind = ProtocolKind.REST
"""The one protocol this module resolves. Named so callers need not import the enum."""

SBE_SCHEMA_FAMILY_SUFFIX: str = "_sbe"
"""How a product's SBE schema family is spelled, given the product's own slug.

Phase 033 records ``spot_sbe`` beside the ``spot`` product, and ``spot_fix_sbe``
for the FIX variant. Deriving the REST one by suffix keeps this module free of a
per-product table — which is the same reason the registry made product families
data rather than an enumeration.
"""

UNAUTHENTICATED: tuple[AuthMechanism, ...] = (AuthMechanism.NONE, AuthMechanism.UNKNOWN)
"""Authentication mechanisms that cannot carry a credentialled request.

:attr:`~globin.domain.api_reality.AuthMechanism.UNKNOWN` is here with
:attr:`~globin.domain.api_reality.AuthMechanism.NONE` deliberately. *Not documented*
and *documented as needing nothing* are different facts, and Phase 033 keeps them
apart — but for the purpose of *may GLOBIN send a signed request here*, both answer
no. Treating an unknown mechanism as usable would be the optimistic acceptance the
brief forbids.
"""


class ResolutionStatus(StrEnum):
    """Whether a request may proceed, and if not, precisely why.

    Nine refusal members rather than one, because an operator reading a refusal
    needs to know whether to change the ask, wait for the venue to document
    something, or refresh a stale record. A single ``refused`` would send all three
    to the same place.
    """

    RESOLVED = "resolved"
    """A single endpoint was chosen and every gate passed."""

    PRODUCT_UNKNOWN = "product_unknown"
    """The registry has no entry for this product family at all.

    Different from a product recorded :attr:`~globin.domain.api_reality.SurfaceStatus.UNKNOWN`,
    which means the documents were read and do not say. This means nobody asked.
    """

    SURFACE_UNDOCUMENTED = "surface_undocumented"
    """The product exists and its REST surface is not documented as supported.

    The state every non-Spot family is in today, and the reason a fail-closed
    transport refuses twelve of the thirteen recorded families.
    """

    ENVIRONMENT_UNDOCUMENTED = "environment_undocumented"
    """The product exists and this environment is not documented as supported for it."""

    NO_ENDPOINT = "no_endpoint"
    """Everything is documented as supported and the registry records no address.

    An honest state rather than a contradiction: Phase 033 keeps *the surface is
    supported* apart from *GLOBIN knows where it is*.
    """

    CAPABILITY_ABSENT = "capability_absent"
    """No candidate endpoint documents the capability the request needs.

    The refusal that stops a market-data-only host being handed an order.
    """

    AUTHENTICATION_UNAVAILABLE = "authentication_unavailable"
    """The request needs a credential and no candidate endpoint accepts one."""

    ENCODING_UNAVAILABLE = "encoding_unavailable"
    """SBE was asked for and no current schema is published for this environment."""

    SOURCE_STALE = "source_stale"
    """The endpoint's evidence is past the re-check interval its policy declares.

    Phase 034's other half computes this. A registry nobody has re-read is a
    registry that may be describing a venue that has moved, and acting on it is the
    optimistic acceptance the brief forbids.
    """

    ENVIRONMENT_MISMATCH = "environment_mismatch"
    """A chosen endpoint contradicts the environment it was filed under.

    Unreachable through :func:`resolve` unless a snapshot was constructed by
    something other than
    :class:`~globin.domain.api_reality.ApiRealitySnapshot`, which validates the same
    property. Kept as defence in depth because this module is what actually hands a
    URL to a socket, and the cost of the check is one comparison.
    """

    @property
    def permits(self) -> bool:
        """Whether this status allows a request to be sent."""
        return self is ResolutionStatus.RESOLVED


@dataclass(frozen=True, slots=True)
class ResolvedEndpoint:
    """One endpoint, with everything a transport needs and nothing it does not.

    Raises:
        ValidationError: On a URL that is not HTTPS, or on an empty host.

    The URL arrives from the registry at runtime; it is never a literal, which is
    what keeps ``tests/architecture/test_api_reality_discipline.py`` passing while
    this package finally makes a request.
    """

    family: str
    environment: str
    role: EndpointRole
    url: str
    host: str
    port: int
    path_prefix: str
    capabilities: tuple[str, ...]
    auth: str
    carries_real_capital: bool
    source: str
    schema_reference: SbeSchemaReference | None = None

    def __post_init__(self) -> None:
        """Refuse an endpoint that could not be reached safely.

        Raises:
            ValidationError: If the scheme is not HTTPS or the host is empty. Phase
                033 already refuses an unencrypted endpoint at registry
                construction; this is the second assertion, at the point of use.
        """
        if not self.url.startswith("https://"):
            msg = f"a REST endpoint is {self.url!r}, which is not HTTPS"
            raise ValidationError(msg)
        if not self.host:
            msg = f"a REST endpoint {self.url!r} resolves to no host"
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This endpoint as plain JSON-safe values."""
        return {
            "family": self.family,
            "environment": self.environment,
            "role": self.role.value,
            "url": self.url,
            "host": self.host,
            "port": self.port,
            "path_prefix": self.path_prefix,
            "capabilities": list(self.capabilities),
            "auth": self.auth,
            "carries_real_capital": self.carries_real_capital,
            "source": self.source,
            "schema_reference": (
                self.schema_reference.as_record() if self.schema_reference else None
            ),
        }


@dataclass(frozen=True, slots=True)
class EndpointResolution:
    """The answer to *may this request go anywhere, and if so where*.

    Raises:
        ValidationError: If a resolved answer carries no endpoint, or a refusal
            carries one.

    **That refusal is the type doing the work.** A caller that ignored
    :attr:`outcome` and read :attr:`endpoint` would, on any other design, get a
    plausible URL out of a refusal. Here there is nothing to read: a refusal has no
    endpoint, structurally, and a resolution without one cannot be constructed.
    """

    outcome: ResolutionStatus
    requested_family: str
    requested_environment: str
    requested_capability: str
    intent: RequestSecurityIntent
    encoding: ResponseEncoding
    endpoint: ResolvedEndpoint | None = None
    alternates: tuple[str, ...] = ()
    detail: str = ""
    considered: int = 0

    def __post_init__(self) -> None:
        """Refuse a resolution that says one thing and carries another."""
        if self.outcome.permits and self.endpoint is None:
            msg = "a resolution reports success and names no endpoint"
            raise ValidationError(msg)
        if not self.outcome.permits and self.endpoint is not None:
            msg = (
                f"a resolution reports {self.outcome.value} and still carries "
                f"{self.endpoint.url!r}; a refusal must offer nothing"
            )
            raise ValidationError(msg)
        if not self.outcome.permits and not self.detail:
            msg = f"a resolution reports {self.outcome.value} and explains nothing"
            raise ValidationError(msg)

    @property
    def permitted(self) -> bool:
        """Whether a request may be sent."""
        return self.outcome.permits

    def as_record(self) -> dict[str, object]:
        """This resolution as plain JSON-safe values."""
        return {
            "outcome": self.outcome.value,
            "requested_family": self.requested_family,
            "requested_environment": self.requested_environment,
            "requested_capability": self.requested_capability,
            "intent": self.intent.value,
            "encoding": self.encoding.value,
            "permitted": self.permitted,
            "endpoint": self.endpoint.as_record() if self.endpoint else None,
            "alternates": list(self.alternates),
            "detail": self.detail,
            "considered": self.considered,
        }


def _host_of(url: str) -> tuple[str, int]:
    """Split an endpoint URL into its host and port, without importing a parser.

    Args:
        url: An ``https://host[:port][/path]`` URL from the registry.

    Returns:
        The lowercase host, and the port or ``0`` when the URL states none.

    ``urllib.parse`` would do this in one call and is declared I/O-capable, so a
    domain module may not have it. The parsing needed here is narrow — Phase 033
    already refuses any endpoint whose scheme is not among three, and every REST one
    is HTTPS — so a split is honest rather than a reimplementation.
    """
    remainder = url.split("://", 1)[-1]
    authority = remainder.split("/", 1)[0]
    if ":" in authority:
        host, _, port = authority.rpartition(":")
        if port.isdigit():
            return host.lower(), int(port)
    return authority.lower(), 0


def _role_of(endpoint: EndpointRecord, *, first_general: bool) -> EndpointRole:
    """Which role an endpoint plays among those the registry offers.

    Args:
        endpoint: The candidate.
        first_general: Whether this is the first non-market-data-only candidate in
            declaration order.

    Returns:
        The role.

    Declaration order decides the primary, because the registry records endpoints in
    the order the venue's own documentation lists them and the venue lists the
    principal one first. That is a property of the document rather than a judgement
    this module makes, which is why no preference table appears here.
    """
    capabilities = set(endpoint.capabilities)
    if capabilities == {SurfaceCapability.MARKET_DATA}:
        return EndpointRole.MARKET_DATA_ONLY
    return EndpointRole.PRIMARY if first_general else EndpointRole.ALTERNATE


def _sbe_reference(
    snapshot: ApiRealitySnapshot, family: ProductFamily, environment: EnvironmentName
) -> SbeSchemaReference | None:
    """The current SBE schema for a product and environment, if one is published.

    Args:
        snapshot: The registry.
        family: Which product.
        environment: Which environment.

    Returns:
        The reference, or ``None`` when no current schema is recorded.

    **Derived from the schema lifecycle rather than from the endpoint's recorded
    encoding**, and the distinction is load-bearing. Phase 033 records
    ``response_encoding = "json"`` for every Spot REST endpoint because JSON is what
    they answer with by default; SBE is negotiated by header on those same
    endpoints. Gating on the endpoint's encoding would therefore refuse a
    combination the venue documents as available, while gating on *is there a
    current schema* is exactly the condition that makes negotiation meaningful.
    """
    try:
        schema_family = SchemaFamilyName(f"{family.slug}{SBE_SCHEMA_FAMILY_SUFFIX}")
    except ValidationError:
        return None
    current = snapshot.current_schema(schema_family, environment)
    if current is None:
        return None
    return SbeSchemaReference(identifier=current.schema_id, version=current.version)


@dataclass(frozen=True, slots=True)
class _Request:
    """What was asked for, gathered so the gates read as a sequence rather than a call."""

    family: ProductFamily
    environment: EnvironmentName
    capability: SurfaceCapability
    intent: RequestSecurityIntent
    encoding: ResponseEncoding
    role: EndpointRole | None
    stale_sources: tuple[str, ...] = ()


def _refuse(
    ask: _Request, outcome: ResolutionStatus, detail: str, considered: int = 0
) -> EndpointResolution:
    """Build a refusal that carries no endpoint.

    Args:
        ask: What was asked for.
        outcome: Why it is refused.
        detail: What an operator should read.
        considered: How many endpoints the registry offered before the refusal.

    Returns:
        The refusal.
    """
    return EndpointResolution(
        outcome=outcome,
        requested_family=ask.family.slug,
        requested_environment=ask.environment.slug,
        requested_capability=ask.capability.value,
        intent=ask.intent,
        encoding=ask.encoding,
        detail=detail,
        considered=considered,
    )


def resolve(
    snapshot: ApiRealitySnapshot,
    *,
    family: ProductFamily,
    environment: EnvironmentName,
    capability: SurfaceCapability = SurfaceCapability.MARKET_DATA,
    intent: RequestSecurityIntent = RequestSecurityIntent.PUBLIC,
    encoding: ResponseEncoding = ResponseEncoding.JSON,
    role: EndpointRole | None = None,
    stale_sources: Collection[str] = (),
) -> EndpointResolution:
    """Decide whether a request may be sent, and to exactly which address.

    Args:
        snapshot: Phase 033's registry. The only source of endpoints.
        family: Which product family.
        environment: Which environment. Never substituted.
        capability: What the request needs the endpoint to be documented for.
        intent: What the request needs from a credential.
        encoding: Which response encoding is being asked for.
        role: Restrict to one role, or ``None`` to take the registry's order.
        stale_sources: Source identifiers whose evidence is past its re-check
            interval, computed by Phase 034's ingestion policy.

    Returns:
        A resolution naming one endpoint, or a refusal naming why.

    The gates, in order, each refusing before the next is reached:

    1. the product is in the registry at all;
    2. its REST surface is documented as supported;
    3. this environment is documented as supported for it;
    4. the registry records at least one REST endpoint for the pair;
    5. at least one such endpoint is itself documented as supported;
    6. one of those documents the capability asked for;
    7. one of *those* accepts a credential, when the intent needs one;
    8. a current SBE schema exists, when SBE is asked for;
    9. the chosen endpoint's evidence is not stale;
    10. the chosen endpoint's host agrees with its environment.

    Ordered cheapest and broadest first, so the message an operator reads names the
    outermost thing that is wrong rather than an inner consequence of it.
    """
    ask = _Request(
        family=family,
        environment=environment,
        capability=capability,
        intent=intent,
        encoding=encoding,
        role=role,
        stale_sources=tuple(stale_sources),
    )

    if snapshot.product(family) is None:
        return _refuse(
            ask,
            ResolutionStatus.PRODUCT_UNKNOWN,
            f"the registry carries no product family called {family.slug!r}",
        )

    surface = snapshot.surface(family, REST)
    if surface is None or surface.capability.status is not SurfaceStatus.SUPPORTED:
        recorded = "no entry" if surface is None else surface.capability.status.value
        return _refuse(
            ask,
            ResolutionStatus.SURFACE_UNDOCUMENTED,
            f"the REST surface for {family.slug} is recorded as {recorded}, not supported",
        )

    recorded_environment = snapshot.environment(family, environment)
    if (
        recorded_environment is None
        or recorded_environment.capability.status is not SurfaceStatus.SUPPORTED
    ):
        recorded = (
            "no entry"
            if recorded_environment is None
            else recorded_environment.capability.status.value
        )
        return _refuse(
            ask,
            ResolutionStatus.ENVIRONMENT_UNDOCUMENTED,
            f"{environment.slug} for {family.slug} is recorded as {recorded}, not supported",
        )

    candidates = snapshot.endpoints_for(family, environment, REST)
    if not candidates:
        return _refuse(
            ask,
            ResolutionStatus.NO_ENDPOINT,
            f"the registry records no REST endpoint for {family.slug} in {environment.slug}",
        )

    supported = tuple(
        item for item in candidates if item.capability.status is SurfaceStatus.SUPPORTED
    )
    if not supported:
        return _refuse(
            ask,
            ResolutionStatus.NO_ENDPOINT,
            (
                f"every recorded REST endpoint for {family.slug} in {environment.slug} "
                "carries a status other than supported"
            ),
            considered=len(candidates),
        )

    capable = tuple(item for item in supported if capability in item.capabilities)
    if not capable:
        return _refuse(
            ask,
            ResolutionStatus.CAPABILITY_ABSENT,
            (
                f"no REST endpoint for {family.slug} in {environment.slug} is documented "
                f"for {capability.value}"
            ),
            considered=len(supported),
        )

    if intent is not RequestSecurityIntent.PUBLIC:
        credentialled = tuple(item for item in capable if item.auth not in UNAUTHENTICATED)
        if not credentialled:
            return _refuse(
                ask,
                ResolutionStatus.AUTHENTICATION_UNAVAILABLE,
                (
                    f"a {intent.value} request needs an endpoint that accepts a credential "
                    f"and none for {family.slug} in {environment.slug} is documented to"
                ),
                considered=len(capable),
            )
        capable = credentialled

    reference: SbeSchemaReference | None = None
    if encoding is ResponseEncoding.SBE:
        reference = _sbe_reference(snapshot, family, environment)
        if reference is None:
            return _refuse(
                ask,
                ResolutionStatus.ENCODING_UNAVAILABLE,
                (
                    f"SBE was asked for and the registry publishes no current schema for "
                    f"{family.slug} in {environment.slug}"
                ),
                considered=len(capable),
            )

    roles: list[tuple[EndpointRole, EndpointRecord]] = []
    seen_general = False
    for item in capable:
        assigned = _role_of(item, first_general=not seen_general)
        if assigned is not EndpointRole.MARKET_DATA_ONLY:
            seen_general = True
        roles.append((assigned, item))

    chosen = [pair for pair in roles if role is None or pair[0] is role]
    if not chosen:
        return _refuse(
            ask,
            ResolutionStatus.NO_ENDPOINT,
            (
                f"no REST endpoint for {family.slug} in {environment.slug} plays the "
                f"{role.value if role else 'requested'} role"
            ),
            considered=len(capable),
        )

    assigned_role, record = chosen[0]

    if record.capability.source in ask.stale_sources:
        return _refuse(
            ask,
            ResolutionStatus.SOURCE_STALE,
            (
                f"endpoint {record.url} rests on source {record.capability.source!r}, whose "
                "evidence is past the re-check interval its ingestion policy declares"
            ),
            considered=len(capable),
        )

    if record.environment != environment:
        return _refuse(
            ask,
            ResolutionStatus.ENVIRONMENT_MISMATCH,
            (
                f"endpoint {record.url} is filed under {record.environment.slug} and "
                f"{environment.slug} was asked for"
            ),
            considered=len(capable),
        )

    marker = recorded_environment.host_marker
    if marker and marker not in record.url.lower():
        return _refuse(
            ask,
            ResolutionStatus.ENVIRONMENT_MISMATCH,
            (
                f"endpoint {record.url} is filed under {environment.slug}, whose hosts are "
                f"spelled with {marker!r}, and does not carry it"
            ),
            considered=len(capable),
        )

    host, port = _host_of(record.url)
    resolved = ResolvedEndpoint(
        family=record.family.slug,
        environment=record.environment.slug,
        role=assigned_role,
        url=record.url,
        host=host,
        port=port,
        path_prefix=record.path_prefix,
        capabilities=tuple(item.value for item in record.capabilities),
        auth=record.auth.value,
        carries_real_capital=recorded_environment.carries_real_capital,
        source=record.capability.source,
        schema_reference=reference,
    )
    return EndpointResolution(
        outcome=ResolutionStatus.RESOLVED,
        requested_family=family.slug,
        requested_environment=environment.slug,
        requested_capability=capability.value,
        intent=intent,
        encoding=encoding,
        endpoint=resolved,
        alternates=tuple(item.url for assigned, item in roles if item.url != record.url),
        considered=len(capable),
    )


def survey(
    snapshot: ApiRealitySnapshot,
    *,
    stale_sources: Collection[str] = (),
) -> tuple[EndpointResolution, ...]:
    """Resolve every product-and-environment pair the registry declares.

    Args:
        snapshot: Phase 033's registry.
        stale_sources: Source identifiers past their re-check interval.

    Returns:
        One resolution per declared pair, in registry order, refusals included.

    What ``globin rest endpoints`` prints and what the Phase 034 evidence records.
    Refusals are kept rather than filtered out: a survey listing only what resolves
    would report a fail-closed registry as an empty one, and the twenty-one pairs
    that refuse today are the evidence that the gate works.
    """
    return tuple(
        resolve(
            snapshot,
            family=item.family,
            environment=item.environment,
            stale_sources=stale_sources,
        )
        for item in snapshot.environments
    )
