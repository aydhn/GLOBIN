"""The adapter that turns a REST exchange into a server-time reading.

Four ways it answers `None`, and none of them is an exception. That matters more
than it looks: a failed calibration is an ordinary, expected state the caller
records as `DEGRADED`, and raising would make every caller responsible for
telling *the venue did not answer* apart from *GLOBIN is broken*.

The fourth way is the one worth having a test of its own: a body that **parsed**
but carried no `serverTime` is a usable HTTP response and an unusable clock
reading. Collapsing those would let a changed venue contract look like a network
problem.

The transport here is a hand-written double satisfying
`globin.ports.rest.RestTransport`, which is what `docs/TESTING_STRATEGY.md` asks
for in preference to a mock. It records what it was asked to send, so the test can
assert that a refused resolution produces **no send at all** rather than a send
whose result was discarded.
"""

from pathlib import Path

import pytest

from globin.adapters.api_reality import read_registry
from globin.adapters.clock_sync import RestServerTimeSource
from globin.adapters.rest import read_contract
from globin.domain.api_reality import (
    ApiRealitySnapshot,
    EnvironmentName,
    ProductFamily,
    ProtocolKind,
)
from globin.domain.clock_sync import ClockDomain
from globin.domain.rest import (
    BodyShape,
    RequestOutcome,
    RestDiagnosticsRecord,
    RestExchange,
    RestRequest,
    RestResponse,
    SendState,
    TransportFailureKind,
)
from globin.domain.rest_contract import TransportContract
from globin.domain.rest_endpoint import EndpointResolution

SPOT = ClockDomain(
    family=ProductFamily("spot"),
    environment=EnvironmentName("testnet"),
    protocol=ProtocolKind.REST,
)
FUTURES = ClockDomain(
    family=ProductFamily("usds_m_futures"),
    environment=EnvironmentName("production"),
    protocol=ProtocolKind.REST,
)


class _Transport:
    """A `RestTransport` that answers with whatever the test handed it.

    Args:
        exchange: What `send` returns, or ``None`` to make `send` refuse to be
            called at all.
    """

    def __init__(self, exchange: RestExchange | None = None) -> None:
        """Record the answer and start with nothing sent."""
        self.exchange = exchange
        self.sent: list[RestRequest] = []

    def open(self) -> None:
        """Nothing to open."""

    def close(self) -> None:
        """Nothing to close."""

    def send(self, resolution: EndpointResolution, request: RestRequest) -> RestExchange:
        """Record the request and answer.

        Args:
            resolution: Where it would have gone.
            request: What was sent.

        Returns:
            The exchange the test supplied.

        Raises:
            AssertionError: If the test supplied none, which is how *nothing was
                sent* is asserted rather than merely hoped for.
        """
        del resolution
        self.sent.append(request)
        assert self.exchange is not None, "the transport was asked to send and should not have been"
        return self.exchange


def _exchange(
    payload: object,
    *,
    outcome: RequestOutcome = RequestOutcome.SUCCESS_CONFIRMED,
    with_response: bool = True,
) -> RestExchange:
    """One completed exchange carrying a chosen body.

    Args:
        payload: The decoded body.
        outcome: How it was classified.
        with_response: Whether it carries a response at all.

    Returns:
        The exchange.
    """
    diagnostics = RestDiagnosticsRecord(
        correlation_id="clock-source-test",
        operation="spot.time",
        family="spot",
        environment="testnet",
        role="primary",
        host="example.invalid",
        method="GET",
        intent="public",
        side_effect="read_only",
        encoding="json",
        time_unit="provider_default",
        send_state=SendState.COMPLETED.value,
        outcome=outcome.value,
        status=200,
    )
    if not with_response:
        return RestExchange(
            operation="spot.time",
            outcome=outcome,
            send_state=SendState.SENT,
            diagnostics=diagnostics,
            failure=TransportFailureKind.CONNECTION_REFUSED,
            detail="the connection dropped",
        )
    return RestExchange(
        operation="spot.time",
        outcome=outcome,
        send_state=SendState.COMPLETED,
        diagnostics=diagnostics,
        response=RestResponse(status=200, shape=BodyShape.OBJECT, outcome=outcome, payload=payload),
    )


@pytest.fixture(scope="module")
def snapshot(repo_root: Path) -> ApiRealitySnapshot:
    """The committed registry."""
    document = read_registry(repo_root / "docs" / "engineering" / "binance-api-reality.toml")
    assert document is not None
    return document


@pytest.fixture(scope="module")
def contract(repo_root: Path) -> TransportContract:
    """The committed transport contract."""
    document = read_contract(repo_root / "docs" / "engineering" / "rest-transport.toml")
    assert document is not None
    return document


def _source(
    snapshot: ApiRealitySnapshot,
    contract: TransportContract,
    transport: _Transport,
    stale: tuple[str, ...] = (),
) -> RestServerTimeSource:
    """A source over a controlled transport.

    Args:
        snapshot: The registry.
        contract: The transport contract.
        transport: The double.
        stale: Source identifiers past their re-check interval.

    Returns:
        The source.
    """
    return RestServerTimeSource(
        transport=transport,
        snapshot=snapshot,
        contract=contract,
        correlation=lambda: "clock-source-test",
        stale_sources=stale,
    )


# ---------------------------------------------------------------------------
# The answering path
# ---------------------------------------------------------------------------


def test_a_documented_body_becomes_a_reading(
    snapshot: ApiRealitySnapshot, contract: TransportContract
) -> None:
    """The venue's own published response, end to end through the adapter."""
    transport = _Transport(_exchange({"serverTime": 1499827319559}))
    reading = _source(snapshot, contract, transport).sample(SPOT)
    assert reading is not None
    assert reading.epoch_micros == 1499827319559 * 1_000


def test_the_request_it_sends_is_the_declared_probe(
    snapshot: ApiRealitySnapshot, contract: TransportContract
) -> None:
    """The path comes from the contract, so it is asserted against the contract."""
    transport = _Transport(_exchange({"serverTime": 1}))
    _source(snapshot, contract, transport).sample(SPOT)
    assert len(transport.sent) == 1
    sent = transport.sent[0]
    descriptor = contract.probe(ProductFamily("spot"), "spot.time")
    assert descriptor is not None
    assert sent.path == descriptor.path
    assert sent.method is descriptor.method
    assert sent.operation == descriptor.operation


def test_the_request_is_public_and_read_only(
    snapshot: ApiRealitySnapshot, contract: TransportContract
) -> None:
    """A calibration carries no credential, and there is no parameter that changes it."""
    transport = _Transport(_exchange({"serverTime": 1}))
    _source(snapshot, contract, transport).sample(SPOT)
    sent = transport.sent[0]
    assert sent.intent.value == "public"
    assert sent.side_effect.value == "read_only"
    assert sent.headers == ()
    # No query at all rather than an empty one: the documented probe takes
    # "Parameters: NONE", so a caller cannot smuggle one in through this path.
    assert sent.query is None


# ---------------------------------------------------------------------------
# The four refusals
# ---------------------------------------------------------------------------


def test_an_unresolvable_domain_sends_nothing(
    snapshot: ApiRealitySnapshot, contract: TransportContract
) -> None:
    """The transport raises if asked, so *nothing sent* is asserted rather than hoped."""
    transport = _Transport(exchange=None)
    assert _source(snapshot, contract, transport).sample(FUTURES) is None
    assert transport.sent == []


def test_a_stale_source_sends_nothing(
    snapshot: ApiRealitySnapshot, contract: TransportContract
) -> None:
    """Phase 034's ninth gate, reached through the clock layer.

    A cached resolution would survive a source going stale, which is why the source
    resolves per call rather than once.
    """
    transport = _Transport(exchange=None)
    source = _source(snapshot, contract, transport, stale=("spot-testnet",))
    assert source.sample(SPOT) is None
    assert transport.sent == []


def test_a_resolvable_family_with_no_declared_probe_sends_nothing(
    snapshot: ApiRealitySnapshot,
) -> None:
    """The gate that keeps *a path is never guessed* structural.

    Spot resolves and declares a `spot.time` probe, so this branch is unreachable
    from the committed pair. Reaching it needs a contract with an empty probe table,
    which is what a new product family looks like on the day its endpoint is
    recorded and its probe is not.
    """

    class _NoProbes:
        """A contract declaring no probe for anything."""

        def probe(self, family: object, operation: str) -> None:
            """Answer that nothing is declared.

            Args:
                family: Which family.
                operation: Which operation.

            Returns:
                ``None``, always.
            """
            del family, operation
            return

    transport = _Transport(exchange=None)
    source = RestServerTimeSource(
        transport=transport,
        snapshot=snapshot,
        contract=_NoProbes(),  # type: ignore[arg-type]
        correlation=lambda: "clock-source-test",
    )
    assert source.sample(SPOT) is None
    assert transport.sent == []


def test_an_exchange_that_did_not_confirm_success_yields_nothing(
    snapshot: ApiRealitySnapshot, contract: TransportContract
) -> None:
    """A transport failure is a failed calibration, not an exception."""
    transport = _Transport(_exchange(None, outcome=RequestOutcome.FAILURE_CONFIRMED))
    assert _source(snapshot, contract, transport).sample(SPOT) is None


def test_an_exchange_with_no_response_yields_nothing(
    snapshot: ApiRealitySnapshot, contract: TransportContract
) -> None:
    """The other half of the same guard: an outcome without a body."""
    transport = _Transport(
        _exchange(None, outcome=RequestOutcome.FAILURE_CONFIRMED, with_response=False)
    )
    assert _source(snapshot, contract, transport).sample(SPOT) is None


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="an-empty-object"),
        pytest.param({"code": -1121, "msg": "Invalid symbol."}, id="an-error-body"),
        pytest.param({"serverTime": "1499827319559"}, id="a-string"),
        pytest.param([1499827319559], id="a-list"),
        pytest.param({"serverTime": 0}, id="a-zero"),
    ],
)
def test_a_body_that_is_not_the_documented_shape_yields_nothing_rather_than_raising(
    snapshot: ApiRealitySnapshot, contract: TransportContract, payload: object
) -> None:
    """A usable HTTP response and an unusable clock reading are different facts.

    Every one of these is a **successful** exchange as far as the transport is
    concerned. Letting the `ValidationError` escape would report a changed venue
    contract as a defect in GLOBIN, and swallowing it into the same `None` a
    connection failure produces is the price of not doing so — paid deliberately,
    because the caller's next action is identical either way.
    """
    transport = _Transport(_exchange(payload))
    assert _source(snapshot, contract, transport).sample(SPOT) is None
