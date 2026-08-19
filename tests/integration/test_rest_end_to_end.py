"""The committed registry, resolved end to end, with nothing constructed by hand.

``tests/unit/test_rest_endpoint.py`` builds its own snapshots, deliberately: a unit
test that read the real document would stop testing the *rule* the day somebody
edited a row. This is the other half — it reads
``docs/engineering/binance-api-reality.toml`` exactly as a running GLOBIN does, and
it is what would fail if a registry edit broke resolution.

**Nothing here opens a socket.** Resolution is pure by the layer contract: the
resolver is in ``domain``, which may import nothing I/O-capable.
"""

from pathlib import Path

import pytest

from globin.adapters.api_reality import REGISTRY_PATH, read_registry
from globin.adapters.ingestion import POLICY_PATH, read_policy
from globin.adapters.rest import CONTRACT_PATH, read_contract
from globin.application.rest import self_test, survey_report
from globin.domain.api_reality import (
    ApiRealitySnapshot,
    EnvironmentName,
    ProductFamily,
    SurfaceCapability,
)
from globin.domain.ingestion import assess
from globin.domain.rest import EndpointRole, RequestSecurityIntent, ResponseEncoding
from globin.domain.rest_contract import TransportContract
from globin.domain.rest_endpoint import ResolutionStatus, resolve

SPOT = ProductFamily("spot")


@pytest.fixture(scope="module")
def registry(repo_root: Path) -> ApiRealitySnapshot:
    """Phase 033's committed registry."""
    found = read_registry(repo_root / REGISTRY_PATH)
    assert found is not None
    return found


@pytest.fixture(scope="module")
def contract(repo_root: Path) -> TransportContract:
    """Phase 034's committed transport contract."""
    found = read_contract(repo_root / CONTRACT_PATH)
    assert found is not None
    return found


class TestTheCommittedRegistryResolves:
    """What the real document actually permits today."""

    @pytest.mark.parametrize("environment", ["production", "testnet", "demo"])
    def test_spot_resolves_in_every_declared_environment(
        self, registry: ApiRealitySnapshot, environment: str
    ) -> None:
        """Spot is the one family with a documented REST surface, in all three."""
        answer = resolve(registry, family=SPOT, environment=EnvironmentName(environment))
        assert answer.permitted, answer.detail
        assert answer.endpoint is not None
        assert answer.endpoint.environment == environment

    @pytest.mark.parametrize(
        "family",
        [
            "cross_margin",
            "isolated_margin",
            "usds_m_futures",
            "coin_m_futures",
            "options",
            "portfolio_margin",
            "portfolio_margin_pro",
        ],
    )
    def test_every_other_family_refuses(self, registry: ApiRealitySnapshot, family: str) -> None:
        """The honest answer, and the best demonstration that the gate works.

        The venue's derivatives documentation is a client-rendered application with
        no admissible route — ``SOURCE_POLICY.md`` forbids both scraping it and
        accepting a generated summary — so every non-Spot surface is recorded
        ``unknown``. A transport that resolved one anyway would be inventing an
        endpoint, which is exactly what Phase 033's registry exists to prevent.
        """
        answer = resolve(
            registry, family=ProductFamily(family), environment=EnvironmentName("production")
        )
        assert not answer.permitted
        assert answer.outcome is ResolutionStatus.SURFACE_UNDOCUMENTED
        assert answer.endpoint is None

    def test_no_environment_resolves_to_another_environments_host(
        self, registry: ApiRealitySnapshot
    ) -> None:
        """The security property, over every pair the real document declares.

        Each non-production environment declares the substring its hosts are spelled
        with, and production declares none — so a production endpoint must carry no
        other environment's marker and each other must carry its own.
        """
        markers = {item.environment.slug: item.host_marker for item in registry.environments}
        for record in registry.environments:
            answer = resolve(registry, family=record.family, environment=record.environment)
            if not answer.permitted or answer.endpoint is None:
                continue
            host = answer.endpoint.host.lower()
            own = markers[record.environment.slug]
            if own:
                assert own in host
            else:
                strays = [marker for slug, marker in markers.items() if marker and marker in host]
                assert not strays, f"a production host is spelled like {strays}"

    def test_the_market_data_only_host_is_reachable_only_by_its_role(
        self, registry: ApiRealitySnapshot
    ) -> None:
        """The venue publishes an unauthenticated market-data-only host.

        Asking for it by role returns it; asking for a trading capability never can,
        because the capability gate runs before the role filter.
        """
        production = EnvironmentName("production")
        by_role = resolve(
            registry, family=SPOT, environment=production, role=EndpointRole.MARKET_DATA_ONLY
        )
        assert by_role.permitted
        assert by_role.endpoint is not None
        assert by_role.endpoint.capabilities == ("market_data",)
        assert by_role.endpoint.auth == "none"

        trading = resolve(
            registry,
            family=SPOT,
            environment=production,
            capability=SurfaceCapability.TRADING,
            intent=RequestSecurityIntent.SIGNED,
            role=EndpointRole.MARKET_DATA_ONLY,
        )
        assert not trading.permitted

    def test_sbe_resolves_in_production_and_not_in_testnet(
        self, registry: ApiRealitySnapshot
    ) -> None:
        """Derived from the schema lifecycle the registry publishes, not from a guess.

        Production carries a ``LATEST`` ``spot_sbe`` schema and testnet does not, so
        the same request resolves in one environment and fails closed in the other —
        which is what a capability-gated negotiation is for.
        """
        production = resolve(
            registry,
            family=SPOT,
            environment=EnvironmentName("production"),
            encoding=ResponseEncoding.SBE,
        )
        testnet = resolve(
            registry,
            family=SPOT,
            environment=EnvironmentName("testnet"),
            encoding=ResponseEncoding.SBE,
        )
        assert production.permitted
        assert production.endpoint is not None
        assert production.endpoint.schema_reference is not None
        assert testnet.outcome is ResolutionStatus.ENCODING_UNAVAILABLE

    def test_the_survey_covers_every_declared_pair(self, registry: ApiRealitySnapshot) -> None:
        """One resolution per declared product-and-environment pair, refusals included."""
        report = survey_report(registry)
        assert len(report["resolutions"]) == len(registry.environments)  # type: ignore[arg-type]
        assert report["resolved"] == 3
        assert report["refused"] == len(registry.environments) - 3


class TestTheCommittedDocumentsAgree:
    """The three documents a running GLOBIN reads, together."""

    def test_the_self_test_passes_against_the_committed_contract(
        self, contract: TransportContract
    ) -> None:
        """The offline half of the phase's evidence, on the real document."""
        report = self_test(contract)
        assert report.passed, [item.detail for item in report.failures]

    def test_every_declared_probe_resolves_against_the_registry(
        self, registry: ApiRealitySnapshot, contract: TransportContract
    ) -> None:
        """A probe declared for a family the registry cannot resolve would never run.

        This is the join between the two committed documents: the contract says
        *which path*, the registry says *whether anywhere*, and a probe naming a
        family with no documented surface is a row nobody could use.
        """
        for probe in contract.probes:
            answer = resolve(
                registry,
                family=probe.family,
                environment=EnvironmentName("production"),
                capability=probe.capability,
            )
            assert answer.permitted, f"{probe.operation} resolves to nothing: {answer.detail}"

    def test_no_source_the_registry_declares_is_stale_today(
        self, repo_root: Path, registry: ApiRealitySnapshot
    ) -> None:
        """Every source was read on the date the registry records, so nothing has aged.

        The assertion is against the *recorded* date rather than against today,
        because otherwise this test would begin failing on a calendar rather than on
        a change — and what it is here to catch is a source whose cadence was
        declared shorter than the interval it was actually read at.
        """
        policy = read_policy(repo_root / POLICY_PATH)
        assert policy is not None
        newest = max(item.accessed for item in registry.sources)
        report = assess(registry, policy, as_of=newest)
        assert report.stale == ()
        assert report.ahead_of_clock == ()
