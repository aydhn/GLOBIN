"""The diagnostics surface's defensive guards, each made to fire at least once.

Every case here exercises a branch that *should* be unreachable in a working
process: a worker that will not stop, a connection that fails at the socket level, a
peer that is not an address at all, a header that announces a body it cannot
describe. ``QUALITY_GATES.md``'s rule is the reason they are here rather than
trusted — a guard nobody has seen fire is indistinguishable from one that cannot.

**No socket is opened.** The endpoint is built with hand-written doubles standing in
for the server and its workers, and the two handler predicates are called against a
stand-in carrying only the headers they read. What a real socket proves is in
``tests/integration/test_diagnostics_endpoint_end_to_end.py``; what a real socket
cannot easily produce is a worker that refuses to join, which is exactly why these
are unit tests.
"""

from typing import Any, Final

import pytest

from globin.adapters.diagnostics_http import (
    BODY_AT_CAPACITY,
    EVENT_CONNECTION_FAILED,
    EVENT_DRAIN_INCOMPLETE,
    EVENT_STOPPED,
    REFUSAL_DRAIN_BYTES,
    BoundedDiagnosticsServer,
    DiagnosticsEndpoint,
    DiagnosticsRequestHandler,
    ReadinessGate,
    _refuse,
)
from globin.application.diagnostics_http import METRIC_INFLIGHT
from globin.application.observability import Logger
from globin.domain.diagnostics_http import (
    CONTENT_TYPE_PROMETHEUS,
    DiagnosticsHttpPolicy,
    ExpositionFormat,
    LoopbackAddress,
    ReadinessReason,
    content_type_for,
    media_ranges,
)
from globin.domain.observability import LogEvent
from globin.errors import ValidationError

MANY: Final[int] = 40
"""More media ranges than the parser will read, so the bound is crossed."""


class Sink:
    """A log sink that keeps every record."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.events: list[LogEvent] = []

    def emit(self, event: LogEvent) -> None:
        """Keep one record."""
        self.events.append(event)

    def names(self) -> list[str]:
        """Every event name recorded, in order."""
        return [event.event for event in self.events]


class Recorder:
    """A metric recorder that keeps what it was given."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.gauges: list[tuple[str, int]] = []
        self.counts: list[tuple[str, int]] = []

    def count(self, name: str, increment: int = 1, **attributes: str) -> None:
        """Record a counter increment."""
        del attributes
        self.counts.append((name, increment))

    def set_gauge(self, name: str, value: int, **attributes: str) -> None:
        """Record a gauge reading."""
        del attributes
        self.gauges.append((name, value))

    def observe(self, name: str, value: int, **attributes: str) -> None:
        """Record a histogram observation."""
        del name, value, attributes


class Worker:
    """A worker thread that can be told whether it ever finishes."""

    def __init__(self, *, finishes: bool = True) -> None:
        """Start unjoined."""
        self.finishes = finishes
        self.joins = 0

    def start(self) -> None:
        """Do nothing."""

    def join(self, timeout: float | None = None) -> None:
        """Record the join, and its deadline."""
        del timeout
        self.joins += 1

    def is_alive(self) -> bool:
        """Whether this worker outlived its deadline."""
        return not self.finishes


class Server:
    """A server double with the queue, the counter and the two request hooks."""

    def __init__(self, *, failing: bool = False) -> None:
        """Start with an empty queue."""
        self.failing = failing
        self.queued: list[object] = []
        self.closed = 0
        self.shutdowns = 0
        self.finished = 0
        self.discarded = 0
        self.pending = self
        self.server_address = ("127.0.0.1", 9_464)
        self.inflight = 0

    def get(self) -> object:
        """Take the next item, or the stop sentinel when there is none."""
        return self.queued.pop(0) if self.queued else None

    def put(self, item: object) -> None:
        """Add an item."""
        self.queued.append(item)

    def shutdown(self) -> None:
        """Record that accepting stopped."""
        self.shutdowns += 1

    def server_close(self) -> None:
        """Record that the socket closed."""
        self.closed += 1

    def finish_request(self, request: object, client_address: object) -> None:
        """Serve one connection, or fail the way a reset does.

        Raises:
            OSError: When this double was built to fail.
        """
        del request, client_address
        if self.failing:
            message = "the connection was reset by the peer at 203.0.113.7"
            raise OSError(message)
        self.finished += 1

    def shutdown_request(self, request: object) -> None:
        """Record that the connection was released."""
        del request
        self.discarded += 1

    def inflight_delta(self, delta: int) -> int:
        """Move the in-flight count."""
        self.inflight += delta
        return self.inflight


class Refusing:
    """A socket that fails every write, the way a vanished peer does."""

    def settimeout(self, timeout: float) -> None:
        """Accept the timeout."""
        del timeout

    def sendall(self, payload: bytes) -> None:
        """Refuse to write.

        Raises:
            OSError: Always.
        """
        del payload
        message = "the peer is gone"
        raise OSError(message)


class Accepting:
    """A socket that records what it was sent and how much was drained."""

    def __init__(self) -> None:
        """Start with nothing sent."""
        self.sent = b""
        self.drained = 0
        self.timeout: float | None = None

    def settimeout(self, timeout: float) -> None:
        """Record the deadline."""
        self.timeout = timeout

    def sendall(self, payload: bytes) -> None:
        """Record the write."""
        self.sent += payload

    def recv(self, size: int) -> bytes:
        """Record the drain, and return nothing."""
        self.drained = size
        return b""


class Headers:
    """A request-header stand-in carrying only what a predicate reads."""

    def __init__(self, **headers: str) -> None:
        """Hold the headers."""
        self.headers = headers

    def get(self, name: str, default: str | None = None) -> str | None:
        """One header, or the default."""
        return self.headers.get(name, default)


def _policy(shutdown_timeout_seconds: int = 5) -> DiagnosticsHttpPolicy:
    """A usable policy with a small pool."""
    return DiagnosticsHttpPolicy(
        address=LoopbackAddress("127.0.0.1"),
        port=9_464,
        request_timeout_seconds=5,
        shutdown_timeout_seconds=shutdown_timeout_seconds,
        max_concurrent_requests=2,
        max_response_bytes=1_048_576,
    )


def _endpoint(
    server: Server | None, workers: list[Any], sink: Sink, recorder: Recorder
) -> DiagnosticsEndpoint:
    """An endpoint whose server and pool are doubles, and which never bound anything."""
    endpoint = DiagnosticsEndpoint(
        # None, because every guard under test returns before the service is reached.
        service=None,  # type: ignore[arg-type]
        policy=_policy(),
        recorder=recorder,
        logger=Logger(sink=sink, correlation_id="c" * 32),
        workers=workers,
    )
    endpoint.server = server
    endpoint.started = server is not None
    return endpoint


# ---------------------------------------------------------------------------
# Stopping
# ---------------------------------------------------------------------------


def test_stopping_something_that_never_started_does_nothing() -> None:
    """Idempotent in the direction a caller reaches by accident."""
    sink, recorder = Sink(), Recorder()
    endpoint = _endpoint(None, [], sink, recorder)
    assert endpoint.stop() is False
    assert sink.events == []


def test_a_worker_that_outlives_the_deadline_is_recorded_and_left() -> None:
    """Joining without a bound would let one wedged request outlive the process.

    That is the failure Phase 025's watchdog exists to end, so the straggler is
    counted and abandoned rather than waited on.
    """
    sink, recorder = Sink(), Recorder()
    server = Server()
    stuck = Worker(finishes=False)
    endpoint = _endpoint(server, [stuck, Worker()], sink, recorder)
    assert endpoint.stop() is True
    assert EVENT_DRAIN_INCOMPLETE in sink.names()
    incomplete = next(e for e in sink.events if e.event == EVENT_DRAIN_INCOMPLETE)
    assert dict(incomplete.fields)["workers"] == 1
    assert stuck.joins == 1


def test_stopping_releases_the_socket_and_forgets_the_pool() -> None:
    """The positive case, so the straggler test above means something."""
    sink, recorder = Sink(), Recorder()
    server = Server()
    endpoint = _endpoint(server, [Worker(), Worker()], sink, recorder)
    assert endpoint.stop() is True
    assert server.shutdowns == 1
    assert server.closed == 1
    assert EVENT_DRAIN_INCOMPLETE not in sink.names()
    assert EVENT_STOPPED in sink.names()
    assert endpoint.workers == []
    assert endpoint.server is None


def test_one_stop_sentinel_is_queued_for_each_worker() -> None:
    """Exactly one, so exactly one worker exits per sentinel."""
    sink, recorder = Sink(), Recorder()
    server = Server()
    endpoint = _endpoint(server, [Worker(), Worker(), Worker()], sink, recorder)
    endpoint.stop()
    assert server.queued.count(None) == 3


# ---------------------------------------------------------------------------
# The worker loop
# ---------------------------------------------------------------------------


def test_a_worker_returns_when_there_is_no_server_left() -> None:
    """Reached when a stop raced a worker that had just woken."""
    sink, recorder = Sink(), Recorder()
    endpoint = _endpoint(None, [], sink, recorder)
    endpoint._work()  # noqa: SLF001 -- the loop is the unit under test
    assert sink.events == []


def test_a_worker_returns_on_the_stop_sentinel() -> None:
    """The ordinary way a worker ends."""
    sink, recorder = Sink(), Recorder()
    server = Server()
    server.put(None)
    endpoint = _endpoint(server, [], sink, recorder)
    endpoint._work()  # noqa: SLF001
    assert server.finished == 0


def test_a_worker_survives_a_connection_that_fails_at_the_socket_level() -> None:
    """A worker that died would silently shrink the pool.

    The surface would then look healthy while serving fewer requests than it claims,
    which is worse than a recorded failure.
    """
    sink, recorder = Sink(), Recorder()
    server = Server(failing=True)
    server.put((object(), ("127.0.0.1", 51_000)))
    endpoint = _endpoint(server, [], sink, recorder)
    endpoint._work()  # noqa: SLF001
    assert EVENT_CONNECTION_FAILED in sink.names()
    assert server.discarded == 1
    assert (METRIC_INFLIGHT, 0) in recorder.gauges


def test_a_failed_connection_records_the_exception_type_and_not_its_message() -> None:
    """A socket error's message can carry a peer address.

    ADR-0026's redaction is by field name rather than by content, so the message is
    never written in the first place.
    """
    sink, recorder = Sink(), Recorder()
    server = Server(failing=True)
    server.put((object(), ("127.0.0.1", 51_000)))
    _endpoint(server, [], sink, recorder)._work()  # noqa: SLF001
    failed = next(e for e in sink.events if e.event == EVENT_CONNECTION_FAILED)
    assert dict(failed.fields)["fault"] == "OSError"
    assert "203.0.113.7" not in str(dict(failed.fields))


def test_a_worker_serves_a_connection_and_returns_the_inflight_gauge() -> None:
    """The positive path through the same loop."""
    sink, recorder = Sink(), Recorder()
    server = Server()
    server.put((object(), ("127.0.0.1", 51_000)))
    _endpoint(server, [], sink, recorder)._work()  # noqa: SLF001
    assert server.finished == 1
    assert (METRIC_INFLIGHT, 0) in recorder.gauges


# ---------------------------------------------------------------------------
# Admission, and the refusal written on the accept loop
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        pytest.param("not-an-address", id="a-hostname"),
        pytest.param("", id="empty"),
        pytest.param("999.999.999.999", id="not-a-valid-address"),
    ],
)
def test_a_peer_that_is_not_an_address_is_refused(host: str) -> None:
    """Should be unreachable, since the socket is bound to loopback.

    Checked anyway so the guarantee does not rest solely on the bind having been
    correct — and called unbound because it reads only its argument.
    """
    verify = BoundedDiagnosticsServer.verify_request
    assert verify(None, None, (host, 51_000)) is False  # type: ignore[arg-type]


def test_a_loopback_peer_is_admitted() -> None:
    """The other direction, so the refusal above is not vacuous."""
    verify = BoundedDiagnosticsServer.verify_request
    assert verify(None, None, ("127.0.0.1", 51_000)) is True  # type: ignore[arg-type]


def test_a_non_loopback_peer_is_refused() -> None:
    """Defence in depth against a bind that was somehow wider than the type allows."""
    verify = BoundedDiagnosticsServer.verify_request
    assert verify(None, None, ("203.0.113.7", 51_000)) is False  # type: ignore[arg-type]


def test_a_socket_error_reported_by_the_library_says_nothing_on_standard_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The base class prints a traceback and the peer address; this prints nothing.

    Under `--json` that would corrupt a document, and at any time it would be a
    second, unstructured logging path beside Phase 023's.
    """
    BoundedDiagnosticsServer.handle_error(None, None, ("127.0.0.1", 1))  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_a_refusal_writes_the_body_then_drains_what_it_will_not_serve() -> None:
    """The drain is what makes the 503 arrive at all.

    Closing a socket that still holds unread received data sends a reset, and a reset
    discards whatever was in flight — so without the drain a caller at capacity gets a
    connection error instead of the deterministic refusal.
    """
    socket = Accepting()
    _refuse(socket, 5)
    assert socket.sent.startswith(b"HTTP/1.0 503")
    assert BODY_AT_CAPACITY in socket.sent
    assert b"Cache-Control: no-store" in socket.sent
    assert b"X-Content-Type-Options: nosniff" in socket.sent
    assert b"Server:" not in socket.sent
    assert socket.drained == REFUSAL_DRAIN_BYTES
    assert socket.timeout == 5.0


def test_a_refusal_to_a_peer_that_has_gone_is_contained() -> None:
    """This runs on the accept loop, so an exception here would stop admissions."""
    _refuse(Refusing(), 5)


# ---------------------------------------------------------------------------
# The two handler predicates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("headers", "carries"),
    [
        pytest.param({}, False, id="no-headers"),
        pytest.param({"Content-Length": "0"}, False, id="an-explicit-zero"),
        pytest.param({"Content-Length": "7"}, True, id="a-declared-body"),
        pytest.param({"Content-Length": "nonsense"}, True, id="an-unreadable-length"),
        pytest.param({"Content-Length": ""}, True, id="an-empty-length"),
        pytest.param({"Transfer-Encoding": "chunked"}, True, id="a-framed-body"),
        pytest.param({"Transfer-Encoding": "identity"}, True, id="any-transfer-encoding"),
    ],
)
def test_a_body_is_detected_however_it_was_announced(
    headers: dict[str, str], carries: bool
) -> None:
    """An unreadable length counts as a body, which is the safe direction.

    A body never consumed leaves bytes in the socket that the next request on a
    reused connection would read as its own request line.
    """
    predicate = DiagnosticsRequestHandler._has_body  # noqa: SLF001 -- a pure predicate
    assert predicate(Headers(**headers)) is carries  # type: ignore[arg-type]


def test_the_handler_writes_nothing_to_standard_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every request is already recorded by the service, with a normalised route."""
    DiagnosticsRequestHandler.log_message(None, "%s happened", "something")  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# ---------------------------------------------------------------------------
# The readiness gate's third state
# ---------------------------------------------------------------------------


class Signals:
    """A stop switch that is never flipped."""

    def requested(self) -> bool:
        """Whether a stop has been asked for."""
        return False

    def install(self) -> None:
        """Install nothing."""


def test_a_gate_can_be_marked_unready_again_after_it_was_ready() -> None:
    """The seam Phases 033-048 use: a dependency that went away.

    Setting a bounded reason rather than widening the type is how a later phase adds
    a condition, and `DEPENDENCY_UNREADY` is already a member.
    """
    gate = ReadinessGate(signals=Signals())  # type: ignore[arg-type]
    assert gate.readiness() is ReadinessReason.STARTING
    gate.mark_ready()
    assert gate.readiness() is ReadinessReason.READY
    gate.mark_unready(ReadinessReason.DEPENDENCY_UNREADY)
    assert gate.readiness() is ReadinessReason.DEPENDENCY_UNREADY


# ---------------------------------------------------------------------------
# Two domain guards that should be unreachable
# ---------------------------------------------------------------------------


def test_a_format_with_no_declared_content_type_is_refused() -> None:
    """Reachable only if `ExpositionFormat` gained a member and the table did not.

    A lookup that can miss keeps this branch reachable, where a chain mypy proves
    exhaustive would make `warn_unreachable` refuse the module.
    """

    class Invented:
        """A format the table has never heard of."""

    with pytest.raises(ValidationError, match="no declared content type"):
        content_type_for(Invented())  # type: ignore[arg-type]
    assert content_type_for(ExpositionFormat.PROMETHEUS_TEXT) == CONTENT_TYPE_PROMETHEUS


def test_media_ranges_stop_at_their_own_bound() -> None:
    """A client that appends a thousand ranges has still asked for what it put first."""
    header = ",".join(f"text/plain;q=0.{index % 9 + 1}" for index in range(MANY))
    assert len(media_ranges(header)) == 16


def test_an_empty_media_range_is_skipped_and_does_not_renumber_the_rest() -> None:
    """An entry naming no type is dropped, and the survivors keep their own position.

    Position exists only to break a tie by the order the client wrote things, so
    renumbering around a skipped entry would silently reorder two ranges of equal
    weight — which is the one thing that ordering is for.
    """
    parsed = media_ranges(",,text/plain,,")
    assert [entry.media_type for entry in parsed] == ["text/plain"]
    assert parsed[0].position == 2
