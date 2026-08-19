"""The only tests in this repository that reach Binance, and how they are kept out.

**Every test here carries ``external``**, whose registered description is *"talks to
a real external system; skipped by default (Phases 033-048)"*. Every selection in
``tools/quality/commands.py`` — smoke, unit, architecture, integration, property,
coverage, shards — appends ``and not external``, so none of this runs in CI, in
``full``, or in an ordinary ``pytest`` invocation of the gate. Running it is a
deliberate act:

    python -m pytest -q -m external

**What these may do, stated as narrowly as it can be.** Public, read-only,
unauthenticated GET requests to endpoints Binance documents as security ``NONE``,
against the *testnet* environment, at a declared weight of 1. No credential is read,
because the probe path accepts only
:attr:`~globin.domain.rest.RequestSecurityIntent.PUBLIC` and there is no parameter
that changes that. Nothing is written at the venue, because the request is built
here with :attr:`~globin.domain.rest.SideEffect.READ_ONLY` hardcoded.

**Why testnet rather than production.** Both would be safe — the endpoints are
public and weight 1 — and testnet is chosen anyway, because a test suite that
reaches a live trading venue by default is a habit rather than a risk assessment.
The production path is exercised by an operator typing ``globin rest ping``, where
the command prints what it is about to do first.
"""

from pathlib import Path

import pytest

from globin.adapters.api_reality import REGISTRY_PATH, read_registry
from globin.adapters.clock import SystemMonotonicClock
from globin.adapters.rest import CONTRACT_PATH, read_contract
from globin.adapters.rest_transport import HttpRestTransport
from globin.application.rest import run_probe
from globin.domain.api_reality import EnvironmentName, ProductFamily
from globin.domain.rest import (
    BodyShape,
    HttpMethod,
    RequestOutcome,
    RequestSecurityIntent,
    SendState,
)
from globin.domain.rest_contract import TransportContract
from globin.domain.rest_endpoint import EndpointResolution, resolve

pytestmark = pytest.mark.external

FAMILY = ProductFamily("spot")
ENVIRONMENT = EnvironmentName("testnet")


@pytest.fixture
def probe_context(repo_root: Path) -> tuple[EndpointResolution, TransportContract]:
    """The registry, the contract, and a resolution against testnet.

    Args:
        repo_root: Where the committed documents live.

    Returns:
        The resolution and the declared contract.
    """
    registry = read_registry(repo_root / REGISTRY_PATH)
    contract = read_contract(repo_root / CONTRACT_PATH)
    assert registry is not None
    assert contract is not None
    resolution = resolve(registry, family=FAMILY, environment=ENVIRONMENT)
    assert resolution.permitted, resolution.detail
    assert resolution.endpoint is not None
    assert resolution.endpoint.carries_real_capital is False
    return resolution, contract


def test_the_connectivity_probe_reaches_the_venue(
    probe_context: tuple[EndpointResolution, TransportContract],
) -> None:
    """One documented, public, weight-1 GET against testnet.

    This is the only claim in Phase 034 that cannot be made offline: that the
    transport, the resolver and the negotiation actually work against the real
    thing. Everything else in this phase is proved against a local server.
    """
    resolution, contract = probe_context
    descriptor = contract.probe(FAMILY, "spot.ping")
    assert descriptor is not None
    assert descriptor.security == "NONE"
    with HttpRestTransport(environment=ENVIRONMENT.slug, clock=SystemMonotonicClock()) as transport:
        exchange = run_probe(
            transport,
            resolution,
            operation=descriptor.operation,
            method=descriptor.method,
            path=descriptor.path,
            correlation_id="external-probe-ping",
        )
    assert exchange.outcome is RequestOutcome.SUCCESS_CONFIRMED, exchange.detail
    assert exchange.send_state is SendState.COMPLETED
    assert exchange.response is not None
    assert exchange.response.status == 200


def test_the_server_time_probe_returns_a_timestamp(
    probe_context: tuple[EndpointResolution, TransportContract],
) -> None:
    """Read for its shape, and never used to set a clock.

    Phase 040 owns clock synchronisation. What this asserts is that the JSON
    decoder handed back an object — no offset is computed and none is stored.
    """
    resolution, contract = probe_context
    descriptor = contract.probe(FAMILY, "spot.time")
    assert descriptor is not None
    with HttpRestTransport(environment=ENVIRONMENT.slug, clock=SystemMonotonicClock()) as transport:
        exchange = run_probe(
            transport,
            resolution,
            operation=descriptor.operation,
            method=descriptor.method,
            path=descriptor.path,
            correlation_id="external-probe-time",
        )
    assert exchange.outcome is RequestOutcome.SUCCESS_CONFIRMED, exchange.detail
    assert exchange.response is not None
    assert exchange.response.shape is BodyShape.OBJECT
    assert isinstance(exchange.response.payload, dict)
    assert "serverTime" in exchange.response.payload


def test_the_real_venue_sends_the_rate_limit_headers_the_contract_declares(
    probe_context: tuple[EndpointResolution, TransportContract],
) -> None:
    """The one thing a local server cannot prove: that the header names are right.

    ``rest-transport.toml`` records ``X-MBX-USED-WEIGHT-`` as the documented prefix
    and a contract test compares it against the package's constant — but both are
    reading the same transcription. This checks the venue agrees.
    """
    resolution, contract = probe_context
    descriptor = contract.probe(FAMILY, "spot.ping")
    assert descriptor is not None
    with HttpRestTransport(environment=ENVIRONMENT.slug, clock=SystemMonotonicClock()) as transport:
        exchange = run_probe(
            transport,
            resolution,
            operation=descriptor.operation,
            method=descriptor.method,
            path=descriptor.path,
            correlation_id="external-probe-headers",
        )
    assert exchange.response is not None
    assert exchange.response.limits.used_weight, (
        "the venue sent no X-MBX-USED-WEIGHT-* header; the declared prefix may have moved"
    )


def test_a_probe_refuses_a_credentialled_resolution(
    probe_context: tuple[EndpointResolution, TransportContract],
) -> None:
    """Structural, and asserted here as well as in the unit tests.

    The probe path builds its own request with ``PUBLIC`` and ``READ_ONLY``
    hardcoded. This is the guard on the other side: a resolution that asked for a
    credential is refused before a socket opens, so no external run can be talked
    into an authenticated request.
    """
    from dataclasses import replace

    from globin.errors import ValidationError

    resolution, _ = probe_context
    credentialled = replace(resolution, intent=RequestSecurityIntent.SIGNED)
    with (
        HttpRestTransport(environment=ENVIRONMENT.slug, clock=SystemMonotonicClock()) as transport,
        pytest.raises(ValidationError, match="credential-free"),
    ):
        run_probe(
            transport,
            credentialled,
            operation="spot.ping",
            method=HttpMethod.GET,
            path="/v3/ping",
            correlation_id="external-probe-refusal",
        )
