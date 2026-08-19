"""What the endpoint resolver refuses, and why each refusal cannot be bypassed.

Six of these tests assert a *refusal*. That ratio is the point: the resolver's job
is almost entirely to say no, and the one case where it says yes is the easy half.

Every snapshot here is built by hand rather than read from
``docs/engineering/binance-api-reality.toml``. A test that read the committed
registry would pass for as long as the registry happened to be shaped conveniently
and would stop testing the rule the day somebody edited a row —
``tests/integration/test_rest_end_to_end.py`` is where the real document is used,
deliberately and separately.
"""

from dataclasses import replace

import pytest

from globin.domain.api_reality import (
    ApiRealitySnapshot,
    AuthMechanism,
    CapabilityRecord,
    EncodingKind,
    EndpointRecord,
    EnvironmentName,
    EnvironmentRecord,
    EvidenceKind,
    ProductFamily,
    ProductProfile,
    ProductScope,
    ProtocolKind,
    SchemaFamilyName,
    SchemaLifecycleState,
    SchemaVersion,
    SourceAuthority,
    SourceObservation,
    SourceRegime,
    SurfaceCapability,
    SurfaceRecord,
    SurfaceStatus,
    TransportKind,
)
from globin.domain.rest import EndpointRole, RequestSecurityIntent, ResponseEncoding
from globin.domain.rest_endpoint import ResolutionStatus, resolve, survey
from globin.errors import ValidationError

SOURCE = "test-source"
SPOT = ProductFamily("spot")
PRODUCTION = EnvironmentName("production")
TESTNET = EnvironmentName("testnet")
DEMO = EnvironmentName("demo")


def _capability(status: SurfaceStatus = SurfaceStatus.SUPPORTED) -> CapabilityRecord:
    """One capability record with a condition where the status needs one."""
    condition = "an eligibility the venue states" if status is SurfaceStatus.RESTRICTED else ""
    return CapabilityRecord(
        status=status,
        evidence=EvidenceKind.DOCUMENTED,
        source=SOURCE,
        condition=condition,
    )


def _source(identifier: str = SOURCE) -> SourceObservation:
    """One declared source, so every record has something to cite."""
    return SourceObservation(
        identifier=identifier,
        title="A document",
        location="https://example.invalid/doc.md",
        authority=SourceAuthority.PRIMARY,
        accessed="2026-08-19",
        regime=SourceRegime.DIGEST,
        digest="sha256:" + "0" * 64,
    )


def _endpoint(
    *,
    environment: EnvironmentName = PRODUCTION,
    url: str = "https://example.invalid/api",
    capabilities: tuple[SurfaceCapability, ...] = (SurfaceCapability.MARKET_DATA,),
    auth: AuthMechanism = AuthMechanism.NONE,
    status: SurfaceStatus = SurfaceStatus.SUPPORTED,
    source: str = SOURCE,
) -> EndpointRecord:
    """One REST endpoint."""
    return EndpointRecord(
        family=SPOT,
        environment=environment,
        protocol=ProtocolKind.REST,
        url=url,
        transport=TransportKind.HTTPS,
        request_encoding=EncodingKind.JSON,
        response_encoding=EncodingKind.JSON,
        auth=auth,
        capability=CapabilityRecord(
            status=status,
            evidence=EvidenceKind.DOCUMENTED,
            source=source,
            condition="a stated condition" if status is SurfaceStatus.RESTRICTED else "",
        ),
        capabilities=capabilities,
        path_prefix="/api",
    )


def _snapshot(
    *,
    endpoints: tuple[EndpointRecord, ...] = (),
    environments: tuple[EnvironmentRecord, ...] | None = None,
    surface_status: SurfaceStatus = SurfaceStatus.SUPPORTED,
    schemas: tuple[SchemaVersion, ...] = (),
    products: tuple[ProductProfile, ...] | None = None,
    sources: tuple[SourceObservation, ...] | None = None,
) -> ApiRealitySnapshot:
    """A snapshot carrying exactly what one test needs."""
    if environments is None:
        environments = (
            EnvironmentRecord(
                family=SPOT,
                environment=PRODUCTION,
                semantics="real capital",
                capability=_capability(),
                carries_real_capital=True,
            ),
        )
    if products is None:
        products = (
            ProductProfile(
                family=SPOT, scope=ProductScope.TRADING, title="Spot", capability=_capability()
            ),
        )
    return ApiRealitySnapshot(
        sources=sources if sources is not None else (_source(),),
        products=products,
        surfaces=(
            SurfaceRecord(
                family=SPOT,
                protocol=ProtocolKind.REST,
                capability=_capability(surface_status),
            ),
        ),
        environments=environments,
        endpoints=endpoints,
        schemas=schemas,
    )


class TestTheHappyCase:
    """The one branch that says yes, so the refusals are not vacuously true."""

    def test_a_documented_surface_resolves_to_one_endpoint(self) -> None:
        """A supported product, environment and endpoint produce an address."""
        snapshot = _snapshot(endpoints=(_endpoint(),))
        answer = resolve(snapshot, family=SPOT, environment=PRODUCTION)
        assert answer.permitted
        assert answer.endpoint is not None
        assert answer.endpoint.host == "example.invalid"
        assert answer.endpoint.path_prefix == "/api"

    def test_the_resolution_carries_whether_real_capital_is_at_risk(self) -> None:
        """An operator reading a resolution is checking exactly this."""
        snapshot = _snapshot(endpoints=(_endpoint(),))
        answer = resolve(snapshot, family=SPOT, environment=PRODUCTION)
        assert answer.endpoint is not None
        assert answer.endpoint.carries_real_capital is True


class TestEnvironmentIsolation:
    """The three substitutions that must be impossible rather than merely forbidden."""

    def test_asking_for_testnet_with_none_recorded_never_yields_production(self) -> None:
        """The security property of the phase, asserted on the refusal itself.

        There is no branch in which a production URL is reachable from a testnet
        request, because the candidate set comes from ``endpoints_for``, which
        filters on the environment before returning anything.
        """
        snapshot = _snapshot(endpoints=(_endpoint(environment=PRODUCTION),))
        answer = resolve(snapshot, family=SPOT, environment=TESTNET)
        assert answer.outcome is ResolutionStatus.ENVIRONMENT_UNDOCUMENTED
        assert answer.endpoint is None
        assert "example.invalid" not in answer.detail

    def test_asking_for_demo_with_only_testnet_recorded_refuses(self) -> None:
        """Two non-production environments are not interchangeable.

        The venue documents them as separate kinds with separate hosts, and
        substituting one for the other would run a paper strategy against an
        account nobody meant to touch.
        """
        environments = (
            EnvironmentRecord(
                family=SPOT,
                environment=TESTNET,
                semantics="no real capital",
                capability=_capability(),
                host_marker="testnet",
            ),
        )
        snapshot = _snapshot(
            endpoints=(_endpoint(environment=TESTNET, url="https://testnet.example.invalid/api"),),
            environments=environments,
        )
        answer = resolve(snapshot, family=SPOT, environment=DEMO)
        assert answer.outcome is ResolutionStatus.ENVIRONMENT_UNDOCUMENTED
        assert answer.endpoint is None

    def test_a_resolution_never_returns_an_endpoint_from_another_environment(self) -> None:
        """Stated over every declared pair, so no single case can be the exception."""
        environments = (
            EnvironmentRecord(
                family=SPOT,
                environment=PRODUCTION,
                semantics="real capital",
                capability=_capability(),
                carries_real_capital=True,
            ),
            EnvironmentRecord(
                family=SPOT,
                environment=TESTNET,
                semantics="no real capital",
                capability=_capability(),
                host_marker="testnet",
            ),
        )
        snapshot = _snapshot(
            endpoints=(
                _endpoint(environment=PRODUCTION),
                _endpoint(environment=TESTNET, url="https://testnet.example.invalid/api"),
            ),
            environments=environments,
        )
        for asked in (PRODUCTION, TESTNET):
            answer = resolve(snapshot, family=SPOT, environment=asked)
            assert answer.endpoint is not None
            assert answer.endpoint.environment == asked.slug


class TestCapabilityGating:
    """A host documented for one thing is never handed another."""

    def test_a_market_data_only_host_is_refused_a_trading_request(self) -> None:
        """The venue publishes exactly such a host, and Phase 033 records it as such."""
        snapshot = _snapshot(endpoints=(_endpoint(capabilities=(SurfaceCapability.MARKET_DATA,)),))
        answer = resolve(
            snapshot,
            family=SPOT,
            environment=PRODUCTION,
            capability=SurfaceCapability.TRADING,
            intent=RequestSecurityIntent.SIGNED,
        )
        assert answer.outcome is ResolutionStatus.CAPABILITY_ABSENT
        assert answer.endpoint is None

    def test_a_credentialled_request_is_refused_an_unauthenticated_endpoint(self) -> None:
        """A signed request to a host that accepts no credential fails confusingly.

        Refusing here means the failure names the cause instead of arriving as a
        401 from a host that was never going to work.
        """
        snapshot = _snapshot(
            endpoints=(
                _endpoint(
                    capabilities=(SurfaceCapability.MARKET_DATA, SurfaceCapability.ACCOUNT_DATA),
                    auth=AuthMechanism.NONE,
                ),
            )
        )
        answer = resolve(
            snapshot,
            family=SPOT,
            environment=PRODUCTION,
            capability=SurfaceCapability.ACCOUNT_DATA,
            intent=RequestSecurityIntent.SIGNED,
        )
        assert answer.outcome is ResolutionStatus.AUTHENTICATION_UNAVAILABLE

    def test_an_unknown_auth_mechanism_is_not_treated_as_usable(self) -> None:
        """*Not documented* is not permission.

        Phase 033 keeps ``UNKNOWN`` apart from ``NONE`` because they are different
        facts; for the question *may GLOBIN send a credential here*, both answer no.

        **The trading case cannot even be built**, which is a stronger guarantee
        than this test could assert: ``EndpointRecord`` refuses a ``TRADING``
        capability with ``UNKNOWN`` authentication at construction, so a registry
        containing one is rejected before any resolver sees it. Account data is not
        covered by that rule, which is why it is the capability used here — the
        resolver's gate is then the only thing standing.
        """
        snapshot = _snapshot(
            endpoints=(
                _endpoint(
                    capabilities=(SurfaceCapability.ACCOUNT_DATA, SurfaceCapability.MARKET_DATA),
                    auth=AuthMechanism.UNKNOWN,
                ),
            )
        )
        answer = resolve(
            snapshot,
            family=SPOT,
            environment=PRODUCTION,
            capability=SurfaceCapability.ACCOUNT_DATA,
            intent=RequestSecurityIntent.SIGNED,
        )
        assert answer.outcome is ResolutionStatus.AUTHENTICATION_UNAVAILABLE

    def test_the_registry_refuses_an_unauthenticated_trading_endpoint_outright(self) -> None:
        """The stronger half of the rule above, asserted where it actually lives."""
        with pytest.raises(ValidationError, match="claims trading"):
            _endpoint(capabilities=(SurfaceCapability.TRADING,), auth=AuthMechanism.UNKNOWN)

    def test_a_public_request_may_use_an_endpoint_that_also_accepts_credentials(self) -> None:
        """The reverse is not symmetrical, and conflating them would break every probe.

        An endpoint that *supports* signed requests does not *require* one, and
        ``/api/v3/ping`` on the main host is the documented case.
        """
        snapshot = _snapshot(
            endpoints=(
                _endpoint(
                    capabilities=(SurfaceCapability.MARKET_DATA, SurfaceCapability.TRADING),
                    auth=AuthMechanism.SIGNED,
                ),
            )
        )
        answer = resolve(snapshot, family=SPOT, environment=PRODUCTION)
        assert answer.permitted


class TestUndocumentedCombinations:
    """Every way the registry can decline to describe something."""

    def test_a_product_the_registry_never_heard_of_refuses(self) -> None:
        """Distinct from a product recorded ``UNKNOWN``: nobody asked, versus it does not say."""
        snapshot = _snapshot(endpoints=(_endpoint(),))
        answer = resolve(snapshot, family=ProductFamily("options"), environment=PRODUCTION)
        assert answer.outcome is ResolutionStatus.PRODUCT_UNKNOWN

    @pytest.mark.parametrize(
        "status",
        [
            SurfaceStatus.UNKNOWN,
            SurfaceStatus.UNSUPPORTED,
            SurfaceStatus.DEPRECATED,
            SurfaceStatus.ANNOUNCED,
            SurfaceStatus.RESTRICTED,
        ],
    )
    def test_only_a_supported_surface_resolves(self, status: SurfaceStatus) -> None:
        """Five status words, and exactly one of them is permission.

        ``UNKNOWN`` in particular is never read as yes — that is the failure the
        whole registry exists to prevent, and this is where it would happen.
        """
        endpoints = () if status is SurfaceStatus.UNSUPPORTED else (_endpoint(),)
        snapshot = _snapshot(endpoints=endpoints, surface_status=status)
        answer = resolve(snapshot, family=SPOT, environment=PRODUCTION)
        assert answer.outcome is ResolutionStatus.SURFACE_UNDOCUMENTED
        assert status.value in answer.detail

    def test_a_supported_surface_with_no_recorded_address_refuses(self) -> None:
        """An honest state: *documented as available* and *GLOBIN knows where* differ."""
        snapshot = _snapshot(endpoints=())
        answer = resolve(snapshot, family=SPOT, environment=PRODUCTION)
        assert answer.outcome is ResolutionStatus.NO_ENDPOINT

    def test_an_endpoint_whose_own_status_is_not_supported_is_not_a_candidate(self) -> None:
        """The surface may be supported while one address is restricted."""
        snapshot = _snapshot(endpoints=(_endpoint(status=SurfaceStatus.RESTRICTED),))
        answer = resolve(snapshot, family=SPOT, environment=PRODUCTION)
        assert answer.outcome is ResolutionStatus.NO_ENDPOINT


class TestStaleness:
    """The join between Phase 034's two halves."""

    def test_an_endpoint_resting_on_a_stale_source_refuses(self) -> None:
        """A record nobody has re-read may be describing a venue that has moved."""
        snapshot = _snapshot(endpoints=(_endpoint(),))
        answer = resolve(snapshot, family=SPOT, environment=PRODUCTION, stale_sources=(SOURCE,))
        assert answer.outcome is ResolutionStatus.SOURCE_STALE
        assert answer.endpoint is None
        assert SOURCE in answer.detail

    def test_a_stale_source_nothing_rests_on_changes_nothing(self) -> None:
        """Only the source the chosen endpoint cites matters."""
        snapshot = _snapshot(
            endpoints=(_endpoint(),), sources=(_source(), _source("another-source"))
        )
        answer = resolve(
            snapshot, family=SPOT, environment=PRODUCTION, stale_sources=("another-source",)
        )
        assert answer.permitted


class TestEncodingNegotiation:
    """SBE resolves only where the registry publishes a current schema."""

    def test_sbe_without_a_current_schema_refuses(self) -> None:
        """Fail closed rather than send a header naming a schema nobody published."""
        snapshot = _snapshot(endpoints=(_endpoint(),))
        answer = resolve(
            snapshot,
            family=SPOT,
            environment=PRODUCTION,
            encoding=ResponseEncoding.SBE,
        )
        assert answer.outcome is ResolutionStatus.ENCODING_UNAVAILABLE

    def test_sbe_with_a_current_schema_resolves_and_carries_the_reference(self) -> None:
        """Derived from the schema lifecycle, not from the endpoint's own encoding.

        A Spot REST endpoint records ``json`` because that is its *default*; SBE is
        negotiated by header on the same address. Gating on the endpoint's encoding
        would refuse a combination the venue documents as available.
        """
        schemas = (
            SchemaVersion(
                family=SchemaFamilyName("spot_sbe"),
                environment=PRODUCTION,
                schema_id=3,
                version=5,
                state=SchemaLifecycleState.LATEST,
                released="2026-01-01",
                source=SOURCE,
            ),
        )
        snapshot = _snapshot(endpoints=(_endpoint(),), schemas=schemas)
        answer = resolve(
            snapshot,
            family=SPOT,
            environment=PRODUCTION,
            encoding=ResponseEncoding.SBE,
        )
        assert answer.permitted
        assert answer.endpoint is not None
        assert answer.endpoint.schema_reference is not None
        assert answer.endpoint.schema_reference.identifier == 3
        assert answer.endpoint.schema_reference.version == 5


class TestRolesAndAlternates:
    """Alternates are reported and never chosen between."""

    def test_the_first_general_endpoint_is_primary_and_the_rest_alternate(self) -> None:
        """Declaration order decides, because the venue lists its principal host first."""
        capabilities = (SurfaceCapability.MARKET_DATA, SurfaceCapability.TRADING)
        snapshot = _snapshot(
            endpoints=(
                _endpoint(
                    url="https://one.example.invalid/api",
                    capabilities=capabilities,
                    auth=AuthMechanism.SIGNED,
                ),
                _endpoint(
                    url="https://two.example.invalid/api",
                    capabilities=capabilities,
                    auth=AuthMechanism.SIGNED,
                ),
            )
        )
        answer = resolve(snapshot, family=SPOT, environment=PRODUCTION)
        assert answer.endpoint is not None
        assert answer.endpoint.role is EndpointRole.PRIMARY
        assert answer.alternates == ("https://two.example.invalid/api",)

    def test_a_market_data_only_endpoint_takes_that_role(self) -> None:
        """Its capabilities are exactly one, which is what makes the role derivable."""
        snapshot = _snapshot(
            endpoints=(
                _endpoint(
                    url="https://one.example.invalid/api",
                    capabilities=(SurfaceCapability.MARKET_DATA, SurfaceCapability.TRADING),
                    auth=AuthMechanism.SIGNED,
                ),
                _endpoint(url="https://data.example.invalid/api"),
            )
        )
        answer = resolve(
            snapshot, family=SPOT, environment=PRODUCTION, role=EndpointRole.MARKET_DATA_ONLY
        )
        assert answer.endpoint is not None
        assert answer.endpoint.url == "https://data.example.invalid/api"

    def test_two_resolutions_of_one_ask_agree(self) -> None:
        """A resolution is deterministic; nothing rotates between hosts."""
        snapshot = _snapshot(
            endpoints=(
                _endpoint(url="https://one.example.invalid/api"),
                _endpoint(url="https://two.example.invalid/api"),
            )
        )
        first = resolve(snapshot, family=SPOT, environment=PRODUCTION)
        second = resolve(snapshot, family=SPOT, environment=PRODUCTION)
        assert first.endpoint is not None
        assert second.endpoint is not None
        assert first.endpoint.url == second.endpoint.url


class TestTheResolutionTypeItself:
    """A refusal offers nothing, structurally."""

    def test_a_refusal_cannot_be_constructed_carrying_an_endpoint(self) -> None:
        """A caller that ignored the outcome would otherwise read a plausible URL.

        Here there is nothing to read: the type refuses the combination, so the
        mistake is impossible rather than discouraged.
        """
        from globin.domain.rest_endpoint import EndpointResolution, ResolvedEndpoint

        endpoint = ResolvedEndpoint(
            family="spot",
            environment="production",
            role=EndpointRole.PRIMARY,
            url="https://example.invalid/api",
            host="example.invalid",
            port=0,
            path_prefix="/api",
            capabilities=("market_data",),
            auth="none",
            carries_real_capital=True,
            source=SOURCE,
        )
        with pytest.raises(ValidationError, match="refusal must offer nothing"):
            EndpointResolution(
                outcome=ResolutionStatus.SOURCE_STALE,
                requested_family="spot",
                requested_environment="production",
                requested_capability="market_data",
                intent=RequestSecurityIntent.PUBLIC,
                encoding=ResponseEncoding.JSON,
                endpoint=endpoint,
                detail="stale",
            )

    def test_a_refusal_must_explain_itself(self) -> None:
        """An operator reading a refusal needs to know which thing to change."""
        from globin.domain.rest_endpoint import EndpointResolution

        with pytest.raises(ValidationError, match="explains nothing"):
            EndpointResolution(
                outcome=ResolutionStatus.NO_ENDPOINT,
                requested_family="spot",
                requested_environment="production",
                requested_capability="market_data",
                intent=RequestSecurityIntent.PUBLIC,
                encoding=ResponseEncoding.JSON,
            )

    def test_a_non_https_endpoint_is_refused_at_the_point_of_use(self) -> None:
        """Phase 033 refuses one at registry construction; this is the second assertion."""
        from globin.domain.rest_endpoint import ResolvedEndpoint

        with pytest.raises(ValidationError, match="not HTTPS"):
            ResolvedEndpoint(
                family="spot",
                environment="production",
                role=EndpointRole.PRIMARY,
                url="http://example.invalid/api",
                host="example.invalid",
                port=0,
                path_prefix="/api",
                capabilities=("market_data",),
                auth="none",
                carries_real_capital=True,
                source=SOURCE,
            )


class TestSurvey:
    """Refusals are counted rather than filtered out."""

    def test_every_declared_pair_appears_including_the_refusals(self) -> None:
        """A survey listing only what resolves would report a fail-closed registry as empty."""
        environments = (
            EnvironmentRecord(
                family=SPOT,
                environment=PRODUCTION,
                semantics="real capital",
                capability=_capability(),
                carries_real_capital=True,
            ),
            EnvironmentRecord(
                family=SPOT,
                environment=TESTNET,
                semantics="no real capital",
                capability=_capability(),
                host_marker="testnet",
            ),
        )
        snapshot = _snapshot(endpoints=(_endpoint(),), environments=environments)
        answers = survey(snapshot)
        assert len(answers) == 2
        assert sum(1 for item in answers if item.permitted) == 1
        assert sum(1 for item in answers if not item.permitted) == 1


class TestTheLastRefusals:
    """Branches a correct registry never reaches, and one parser corner."""

    def test_an_endpoint_with_no_host_is_refused(self) -> None:
        """A URL that parses to nothing is a URL nothing can connect to."""
        from globin.domain.rest_endpoint import ResolvedEndpoint

        with pytest.raises(ValidationError, match="resolves to no host"):
            ResolvedEndpoint(
                family="spot",
                environment="production",
                role=EndpointRole.PRIMARY,
                url="https://",
                host="",
                port=0,
                path_prefix="",
                capabilities=("market_data",),
                auth="none",
                carries_real_capital=True,
                source=SOURCE,
            )

    def test_a_success_that_names_no_endpoint_is_refused(self) -> None:
        """The other half of the rule that a refusal offers nothing.

        Without it, a resolution could report success and hand a caller ``None``,
        which is the same failure in the opposite direction.
        """
        from globin.domain.rest_endpoint import EndpointResolution

        with pytest.raises(ValidationError, match="names no endpoint"):
            EndpointResolution(
                outcome=ResolutionStatus.RESOLVED,
                requested_family="spot",
                requested_environment="production",
                requested_capability="market_data",
                intent=RequestSecurityIntent.PUBLIC,
                encoding=ResponseEncoding.JSON,
            )

    def test_an_explicit_port_is_read_out_of_the_url(self) -> None:
        """The registry records a port on some endpoints and not on others.

        Parsed by hand rather than with ``urllib.parse``, which a domain module may
        not import, so the split needs its own case.
        """
        snapshot = _snapshot(endpoints=(_endpoint(url="https://example.invalid:8443/api"),))
        answer = resolve(snapshot, family=SPOT, environment=PRODUCTION)
        assert answer.endpoint is not None
        assert answer.endpoint.host == "example.invalid"
        assert answer.endpoint.port == 8443

    def test_a_product_whose_sbe_family_name_is_unspellable_refuses(self) -> None:
        """The suffix derivation can produce a name the slug rules refuse.

        A long product slug plus ``_sbe`` can exceed the identifier bound, and the
        answer is *no current schema* rather than an exception — the same refusal a
        product with no published schema gets.
        """
        long_family = ProductFamily("a" * 45)
        snapshot = ApiRealitySnapshot(
            sources=(_source(),),
            products=(
                ProductProfile(
                    family=long_family,
                    scope=ProductScope.TRADING,
                    title="Long",
                    capability=_capability(),
                ),
            ),
            surfaces=(
                SurfaceRecord(
                    family=long_family,
                    protocol=ProtocolKind.REST,
                    capability=_capability(),
                ),
            ),
            environments=(
                EnvironmentRecord(
                    family=long_family,
                    environment=PRODUCTION,
                    semantics="real capital",
                    capability=_capability(),
                    carries_real_capital=True,
                ),
            ),
            endpoints=(
                EndpointRecord(
                    family=long_family,
                    environment=PRODUCTION,
                    protocol=ProtocolKind.REST,
                    url="https://example.invalid/api",
                    transport=TransportKind.HTTPS,
                    request_encoding=EncodingKind.JSON,
                    response_encoding=EncodingKind.JSON,
                    auth=AuthMechanism.NONE,
                    capability=_capability(),
                    capabilities=(SurfaceCapability.MARKET_DATA,),
                    path_prefix="/api",
                ),
            ),
        )
        answer = resolve(
            snapshot,
            family=long_family,
            environment=PRODUCTION,
            encoding=ResponseEncoding.SBE,
        )
        assert answer.outcome is ResolutionStatus.ENCODING_UNAVAILABLE

    def test_asking_for_a_role_no_endpoint_plays_refuses(self) -> None:
        """Every candidate is general, so the market-data-only role matches none."""
        snapshot = _snapshot(
            endpoints=(
                _endpoint(
                    capabilities=(SurfaceCapability.MARKET_DATA, SurfaceCapability.TRADING),
                    auth=AuthMechanism.SIGNED,
                ),
            )
        )
        answer = resolve(
            snapshot,
            family=SPOT,
            environment=PRODUCTION,
            role=EndpointRole.MARKET_DATA_ONLY,
        )
        assert answer.outcome is ResolutionStatus.NO_ENDPOINT
        assert "market_data_only" in answer.detail

    def test_a_host_that_contradicts_its_environment_marker_refuses(self) -> None:
        """Defence in depth: the snapshot validates this too, and this is the point of use.

        Reached by declaring an environment whose marker no endpoint carries, which
        ``ApiRealitySnapshot`` would refuse — so the resolution is built against a
        snapshot assembled field by field rather than through the registry reader.
        """
        environments = (
            EnvironmentRecord(
                family=SPOT,
                environment=TESTNET,
                semantics="no real capital",
                capability=_capability(),
                host_marker="testnet",
            ),
        )
        endpoint = _endpoint(environment=TESTNET, url="https://testnet.example.invalid/api")
        snapshot = _snapshot(endpoints=(endpoint,), environments=environments)
        assert resolve(snapshot, family=SPOT, environment=TESTNET).permitted

        stripped = replace(environments[0], host_marker="absentmarker")
        forged = object.__new__(ApiRealitySnapshot)
        object.__setattr__(forged, "sources", (_source(),))
        object.__setattr__(forged, "products", snapshot.products)
        object.__setattr__(forged, "surfaces", snapshot.surfaces)
        object.__setattr__(forged, "environments", (stripped,))
        object.__setattr__(forged, "endpoints", (endpoint,))
        object.__setattr__(forged, "schemas", ())
        answer = resolve(forged, family=SPOT, environment=TESTNET)
        assert answer.outcome is ResolutionStatus.ENVIRONMENT_MISMATCH
        assert answer.endpoint is None
