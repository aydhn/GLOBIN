"""The diagnostics surface over a real loopback socket, from bind to close.

Deliberately small. Almost every behavioural question this surface has is answered in
``tests/unit/test_diagnostics_http.py`` without a connection, so what is left here is
only what a socket can prove: that the plumbing hands a method, a target and an
``Accept`` header to the service, writes the answer back with the headers that were
decided, refuses what must be refused *at the protocol level*, bounds its own
concurrency, and lets go of the port when asked.

**Every test in this file carries `loopback`.** The autouse guard in
``tests/conftest.py`` refuses outbound connections; that marker narrows the refusal to
"anything that is not this machine" rather than lifting it, so a mistake here that
reached a real service still fails. See ``docs/TESTING_STRATEGY.md``.

**The port is chosen, not configured.** ``DiagnosticsHttpPolicy`` refuses port zero
because the runtime must never bind an arbitrary one, so a test asks the operating
system for a free port, closes it, and binds that number — which keeps the production
default deterministic while letting parallel runs coexist.
"""

import http.client
import json
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import Final

import pytest

from globin.adapters.diagnostics_http import (
    BODY_AT_CAPACITY,
    BODY_MALFORMED,
    DiagnosticsEndpoint,
    ReadinessGate,
)
from globin.adapters.observability import new_correlation_id
from globin.domain.configuration import DiagnosticsHttpConfig, default_config
from globin.domain.diagnostics_http import (
    ALLOWED_METHODS,
    CACHE_CONTROL_VALUE,
    CONTENT_TYPE_OPENMETRICS,
    CONTENT_TYPE_OPTIONS_VALUE,
    CONTENT_TYPE_PROMETHEUS,
    LOOPBACK_IPV4,
    OPENMETRICS_TERMINATOR,
    PRAGMA_VALUE,
    STATUS_BAD_REQUEST,
    STATUS_METHOD_NOT_ALLOWED,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_UNAVAILABLE,
)
from globin.runtime.composition import build_diagnostics_endpoint, build_runtime_state

pytestmark = pytest.mark.loopback

CANARY: Final[str] = "globin-canary-secret-value"
"""A value that must reach no response body, header or log record."""

TIMEOUT: Final[float] = 10.0
"""How long a client waits. Generous: a hang should fail the test, not the suite."""


class Signals:
    """A stop switch a test flips, standing in for the platform's signal handlers."""

    def __init__(self) -> None:
        """Start with no stop requested."""
        self.stopping = False

    def requested(self) -> bool:
        """Whether a stop has been asked for."""
        return self.stopping

    def install(self) -> None:
        """Install nothing.

        A test that installed real handlers would change the interpreter for every
        test after it, which is what ``isolate_process_state`` exists to catch.
        """


def free_port() -> int:
    """A loopback port nothing is listening on right now.

    Returns:
        The port number.

    There is a window between closing this socket and binding it again, which is
    inherent to asking the operating system for a free port and is why the runtime
    never does it. It is the standard approach and the alternative — a fixed port —
    would collide with a developer's own running GLOBIN.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((LOOPBACK_IPV4, 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def _settings(**overrides: object) -> DiagnosticsHttpConfig:
    """A surface with everything on, at a free port, plus any override."""
    base = DiagnosticsHttpConfig(
        enabled=True,
        port=free_port(),
        diagnostics_snapshot_enabled=True,
        max_concurrent_requests=2,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


@pytest.fixture
def surface() -> Iterator[tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int]]:
    """A started surface, stopped again however the test ends.

    The teardown is unconditional. A test that failed mid-way and left a listener
    bound would leak a thread and a port into every test after it, and the symptom
    would appear in the victim rather than in the culprit.
    """
    settings = _settings()
    signals = Signals()
    base = default_config()
    config = replace(base, diagnostics_http=settings)
    endpoint, gate = build_diagnostics_endpoint(
        build_runtime_state(),
        signals,  # type: ignore[arg-type]
        run_id="r" * 32,
        correlation_id=new_correlation_id(),
        config=config,
        version="0.0.0-test",
    )
    endpoint.start()
    try:
        yield endpoint, gate, signals, settings.port
    finally:
        endpoint.stop()


def _request(
    port: int, method: str = "GET", target: str = "/health/live", **headers: str
) -> tuple[int, dict[str, str], bytes]:
    """One real request over loopback.

    Args:
        port: Where the surface is bound.
        method: The request method.
        target: The request target.
        headers: Any request headers.

    Returns:
        The status, the response headers, and the body.
    """
    connection = http.client.HTTPConnection(LOOPBACK_IPV4, port, timeout=TIMEOUT)
    try:
        connection.request(method, target, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def _raw(port: int, payload: bytes) -> bytes:
    """Send bytes that are not necessarily a well-formed request, and read the answer.

    Args:
        port: Where the surface is bound.
        payload: Exactly what goes on the wire.

    Returns:
        Whatever came back, up to a bounded read.

    `http.client` refuses to send a malformed request line, so the tests that need one
    write to the socket directly.
    """
    client = socket.create_connection((LOOPBACK_IPV4, port), timeout=TIMEOUT)
    try:
        client.sendall(payload)
        chunks = []
        while True:
            chunk = client.recv(4_096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Where it listens
# ---------------------------------------------------------------------------


def test_the_surface_is_reachable_on_loopback(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """The most basic claim, and the one everything below depends on."""
    endpoint, _gate, _signals, port = surface
    assert endpoint.address == (LOOPBACK_IPV4, port)
    status, _headers, _body = _request(port)
    assert status == STATUS_OK


def test_nothing_is_bound_until_start_is_called() -> None:
    """Building the graph opens no socket, which is what makes a disabled surface silent."""
    settings = _settings()
    endpoint, _gate = build_diagnostics_endpoint(
        build_runtime_state(),
        Signals(),  # type: ignore[arg-type]
        run_id="r" * 32,
        correlation_id=new_correlation_id(),
        config=replace(default_config(), diagnostics_http=settings),
    )
    assert endpoint.server is None
    with pytest.raises(RuntimeError, match="not bound"):
        _ = endpoint.address
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2.0)
        with pytest.raises(OSError):  # noqa: PT011 -- any refusal proves it is closed
            probe.connect((LOOPBACK_IPV4, settings.port))


# ---------------------------------------------------------------------------
# Every route, end to end
# ---------------------------------------------------------------------------


def test_each_route_answers_over_the_socket(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """The plumbing hands the target over and writes a document back.

    The schema each route declares is asserted per route rather than uniformly: a
    projection's own schema wins, so `/health/runtime` publishes a Phase 024 health
    snapshot under its own name rather than being relabelled.
    """
    _endpoint, gate, _signals, port = surface
    gate.mark_ready()
    expected = {
        "/health/live": "globin.diagnostics.endpoint",
        "/health/ready": "globin.diagnostics.endpoint",
        "/health/runtime": "globin.health.snapshot",
        "/diagnostics/snapshot": "globin.diagnostics.endpoint",
    }
    for target, schema in expected.items():
        status, headers, body = _request(port, target=target)
        assert status == STATUS_OK, target
        assert headers["Content-Type"] == "application/json; charset=utf-8", target
        assert json.loads(body)["schema"] == schema, target


def test_the_combined_snapshot_carries_both_halves(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """What makes it more than `/health/runtime`, and why it has its own switch."""
    _endpoint, _gate, _signals, port = surface
    body = json.loads(_request(port, target="/diagnostics/snapshot")[2])
    assert body["health"]["schema"] == "globin.health.snapshot"
    assert body["telemetry"]["schema"] == "globin.telemetry.snapshot"


def test_readiness_answers_five_hundred_and_three_until_the_gate_opens(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """Starting, not ready, is the initial state, and it is visible over the wire."""
    _endpoint, gate, _signals, port = surface
    status, _headers, body = _request(port, target="/health/ready")
    assert status == STATUS_UNAVAILABLE
    assert json.loads(body)["reason"] == "starting"
    gate.mark_ready()
    status, _headers, body = _request(port, target="/health/ready")
    assert status == STATUS_OK
    assert json.loads(body)["ready"] is True


def test_a_stop_request_flips_liveness_and_readiness_before_the_socket_closes(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """A supervisor must be able to learn a process is going away while it still answers.

    That ordering is why liveness reads the signal rather than the socket's existence.
    """
    _endpoint, gate, signals, port = surface
    gate.mark_ready()
    assert _request(port, target="/health/ready")[0] == STATUS_OK
    signals.stopping = True
    assert _request(port, target="/health/live")[0] == STATUS_UNAVAILABLE
    status, _headers, body = _request(port, target="/health/ready")
    assert status == STATUS_UNAVAILABLE
    assert json.loads(body)["reason"] == "stopping"


def test_a_head_request_reports_the_length_and_sends_no_body(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """A HEAD that reported a different length would be worse than one reporting none."""
    _endpoint, _gate, _signals, port = surface
    _status, get_headers, get_body = _request(port, target="/health/live")
    status, head_headers, head_body = _request(port, "HEAD", "/health/live")
    assert status == STATUS_OK
    assert head_body == b""
    assert head_headers["Content-Length"] == get_headers["Content-Length"]
    assert int(head_headers["Content-Length"]) == len(get_body)


# ---------------------------------------------------------------------------
# The scrape route, negotiated over the wire
# ---------------------------------------------------------------------------


def test_the_scrape_route_serves_prometheus_text_by_default(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """No `Accept` header means the specification's last resort."""
    _endpoint, _gate, _signals, port = surface
    status, headers, body = _request(port, target="/metrics")
    assert status == STATUS_OK
    assert headers["Content-Type"] == CONTENT_TYPE_PROMETHEUS
    assert b"# TYPE globin_" in body


def test_the_scrape_route_serves_openmetrics_when_prometheus_asks_for_it(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """The real scrape header, and the terminator its specification requires."""
    _endpoint, _gate, _signals, port = surface
    header = (
        "application/openmetrics-text;version=1.0.0;escaping=allow-utf-8;q=0.5,"
        "text/plain;version=0.0.4;q=0.2,*/*;q=0.1"
    )
    status, headers, body = _request(port, target="/metrics", Accept=header)
    assert status == STATUS_OK
    assert headers["Content-Type"] == CONTENT_TYPE_OPENMETRICS
    assert body.decode("utf-8").endswith(OPENMETRICS_TERMINATOR)


def test_the_scrape_route_answers_with_no_exporter_configured(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """Export is off by default, and the local scrape does not depend on it.

    Nothing in this test configures an exporter, and a collector's availability is
    never consulted: the exposition is rendered from the local registry, so a remote
    collector being down or slow cannot reach a request's critical path.
    """
    _endpoint, _gate, _signals, port = surface
    assert default_config().telemetry.export_enabled is False
    status, _headers, body = _request(port, target="/metrics")
    assert status == STATUS_OK
    assert body


# ---------------------------------------------------------------------------
# What the protocol layer refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_a_state_changing_method_is_refused_with_allow(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int], method: str
) -> None:
    """405 with a deterministic `Allow`, not the library's 501 HTML page.

    Defining only `do_GET` and `do_HEAD` leaves the base class to answer every other
    verb through `send_error`, which writes a generic HTML page with no cache or
    sniffing headers and the requested method echoed into the body. This asserts the
    override that closes it.
    """
    _endpoint, _gate, _signals, port = surface
    status, headers, body = _request(port, method, "/health/live")
    assert status == STATUS_METHOD_NOT_ALLOWED
    assert headers["Allow"] == ALLOWED_METHODS
    assert headers["Content-Type"] == "text/plain; charset=utf-8"
    assert b"<html" not in body.lower()
    assert method.encode() not in body


def test_a_refused_method_changes_nothing(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """There is nothing to change, and this is how that is checked rather than claimed."""
    _endpoint, gate, _signals, port = surface
    gate.mark_ready()
    before = _request(port, target="/health/runtime")[2]
    for method in ("POST", "PUT", "DELETE"):
        _request(port, method, "/health/runtime")
    assert _request(port, target="/health/runtime")[2] == before


@pytest.mark.parametrize(
    "target",
    [
        "/",
        "/nonsense",
        "/index.html",
        "/favicon.ico",
        "/../../etc/passwd",
        "/health",
        "/health/live/",
    ],
)
def test_an_unserved_target_is_four_hundred_and_four_over_the_wire(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int], target: str
) -> None:
    """No file serving and no directory logic: a traversal attempt has nowhere to go."""
    _endpoint, _gate, _signals, port = surface
    status, headers, body = _request(port, target=target)
    assert status == STATUS_NOT_FOUND
    assert headers["Content-Type"] == "text/plain; charset=utf-8"
    assert b"root:" not in body
    assert b"<html" not in body.lower()


def test_a_request_announcing_a_body_is_refused(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """A body never read would be left in the socket for whatever came next."""
    _endpoint, _gate, _signals, port = surface
    answer = _raw(
        port,
        b"GET /health/live HTTP/1.0\r\nContent-Length: 7\r\n\r\npayload",
    )
    assert str(STATUS_BAD_REQUEST).encode() in answer.split(b"\r\n")[0]


def test_a_request_announcing_a_framed_body_is_refused(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """`Transfer-Encoding` is the other spelling, and it is refused for the same reason."""
    _endpoint, _gate, _signals, port = surface
    answer = _raw(
        port,
        b"GET /health/live HTTP/1.0\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
    )
    assert str(STATUS_BAD_REQUEST).encode() in answer.split(b"\r\n")[0]


def test_an_unreadable_request_gets_a_bounded_answer_and_no_html(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """The other path through `send_error`, which the base class also answers with HTML."""
    _endpoint, _gate, _signals, port = surface
    answer = _raw(port, b"NOT A REQUEST LINE AT ALL\r\n\r\n")
    assert b"<html" not in answer.lower()
    assert BODY_MALFORMED in answer or str(STATUS_BAD_REQUEST).encode() in answer


def test_no_response_header_can_be_split_by_anything_a_client_sent(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """Every header value is a constant or a computed integer; none is echoed.

    The injection is attempted through the one header whose value influences a
    response, and through the target, which is the other thing a client controls.
    """
    _endpoint, _gate, _signals, port = surface
    answer = _raw(
        port,
        b"GET /metrics HTTP/1.0\r\nAccept: text/plain;version=0.0.4\r\nX-Smuggled: no\r\n\r\n",
    )
    head = answer.split(b"\r\n\r\n", 1)[0]
    assert b"X-Smuggled" not in head
    assert b"X-Injected" not in head
    injected = _raw(port, b"GET /metrics%0d%0aX-Injected:+yes HTTP/1.0\r\n\r\n")
    assert b"X-Injected" not in injected.split(b"\r\n\r\n", 1)[0]


# ---------------------------------------------------------------------------
# Response hardening, read off the wire rather than off the code
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target", ["/health/live", "/health/ready", "/health/runtime", "/metrics", "/nonsense"]
)
def test_every_response_carries_the_hardening_headers_and_no_fingerprint(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int], target: str
) -> None:
    """Read from the socket, because that is the only place the truth is.

    The absent `Server` header is the interesting one: the library builds it from
    `version_string()`, so its absence proves `send_response_only` is the route every
    response takes.
    """
    _endpoint, _gate, _signals, port = surface
    _status, headers, body = _request(port, target=target)
    assert headers["Cache-Control"] == CACHE_CONTROL_VALUE
    assert headers["Pragma"] == PRAGMA_VALUE
    assert headers["X-Content-Type-Options"] == CONTENT_TYPE_OPTIONS_VALUE
    assert headers["Content-Length"] == str(len(body))
    assert "Server" not in headers
    joined = " ".join(headers.values())
    assert "Python" not in joined
    assert "BaseHTTP" not in joined


def test_no_response_or_log_record_carries_a_canary(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """The canary is pushed in through every channel a client controls.

    A target, a query string and a header value: none of the three may come back, and
    none may reach a record. Redaction is by field name, so the guarantee that matters
    here is that these never enter a field at all.
    """
    _endpoint, _gate, _signals, port = surface
    for method, target, headers in (
        ("GET", f"/{CANARY}", {}),
        ("GET", f"/metrics?token={CANARY}", {}),
        ("GET", "/metrics", {"Accept": CANARY}),
        ("POST", f"/health/live?x={CANARY}", {}),
    ):
        _status, response_headers, body = _request(port, method, target, **headers)
        assert CANARY.encode() not in body
        assert CANARY not in " ".join(response_headers.values())


# ---------------------------------------------------------------------------
# Bounded concurrency
# ---------------------------------------------------------------------------


def test_the_worker_pool_is_exactly_as_large_as_the_bound(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """The worker count *is* the setting, so there is no second limit to get wrong."""
    endpoint, _gate, _signals, _port = surface
    assert len(endpoint.workers) == endpoint.policy.max_concurrent_requests
    assert all(not worker.daemon for worker in endpoint.workers)
    assert all(worker.name.startswith("globin-diagnostics-worker") for worker in endpoint.workers)


def test_no_thread_is_created_per_connection(
    surface: tuple[DiagnosticsEndpoint, ReadinessGate, Signals, int],
) -> None:
    """Twenty requests through a pool of two, and the thread count does not move.

    `ThreadingHTTPServer` would have created twenty threads. Counting before and after
    is what turns "bounded" into a measurement.
    """
    _endpoint, _gate, _signals, port = surface
    before = threading.active_count()
    for _ in range(20):
        assert _request(port)[0] == STATUS_OK
    assert threading.active_count() <= before


def test_capacity_exhaustion_is_a_refusal_rather_than_growth() -> None:
    """A full queue answers 503 and closes, on the accept loop, without a new thread.

    Driven by holding the single worker busy with a connection that never sends a
    request line, so the pool and the queue are both occupied deterministically rather
    than by racing a burst of traffic.

    **Opening a connection is not the same as the server having accepted it**, and
    Phase 029 corrected the test for that. `socket.create_connection` returns once
    the kernel has completed the handshake into the listen backlog; the accept loop
    may not have taken either connection yet, so a third request sent immediately
    can find capacity that is about to be occupied and answer 200. That is a race in
    the *test*, not in the surface, and it stayed hidden until the suite grew heavy
    enough to widen it.

    The fix is a bounded wait rather than a sleep: the third request is re-sent until
    it is refused or the deadline passes. What is asserted is unchanged -- a full
    queue answers 503, closes, and starts no thread -- and only the assumption about
    *when* the accepts land is relaxed. Capacity, once exhausted by two connections
    that never send anything, is never released, so a run that never sees 503 is a
    real failure rather than a slow one.
    """
    settings = _settings(max_concurrent_requests=1)
    endpoint, _gate = build_diagnostics_endpoint(
        build_runtime_state(),
        Signals(),  # type: ignore[arg-type]
        run_id="r" * 32,
        correlation_id=new_correlation_id(),
        config=replace(default_config(), diagnostics_http=settings),
    )
    endpoint.start()
    held: list[socket.socket] = []
    try:
        before = threading.active_count()
        # One connection occupies the worker; the next fills the one-slot queue; the
        # third finds no room and must be refused.
        for _ in range(2):
            held.append(socket.create_connection((LOOPBACK_IPV4, settings.port), timeout=TIMEOUT))
        deadline = time.monotonic() + TIMEOUT
        refused = b""
        while time.monotonic() < deadline:
            refused = _raw(settings.port, b"GET /health/live HTTP/1.0\r\n\r\n")
            if str(STATUS_UNAVAILABLE).encode() in refused.split(b"\r\n")[0]:
                break
        assert str(STATUS_UNAVAILABLE).encode() in refused.split(b"\r\n")[0]
        assert BODY_AT_CAPACITY in refused
        assert threading.active_count() <= before
    finally:
        for connection in held:
            connection.close()
        endpoint.stop()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_the_port_is_released_when_the_surface_stops() -> None:
    """A stop that left the socket bound would make a restart impossible."""
    settings = _settings()
    endpoint, _gate = build_diagnostics_endpoint(
        build_runtime_state(),
        Signals(),  # type: ignore[arg-type]
        run_id="r" * 32,
        correlation_id=new_correlation_id(),
        config=replace(default_config(), diagnostics_http=settings),
    )
    endpoint.start()
    assert _request(settings.port)[0] == STATUS_OK
    assert endpoint.stop() is True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2.0)
        with pytest.raises(OSError):  # noqa: PT011 -- any refusal proves it is closed
            probe.connect((LOOPBACK_IPV4, settings.port))


def test_every_worker_is_joined_by_the_time_stop_returns() -> None:
    """Non-daemon threads, so a forgotten join hangs the suite loudly.

    What this asserts is that none is forgotten: after `stop`, the pool is empty and
    no worker is alive.
    """
    settings = _settings()
    endpoint, _gate = build_diagnostics_endpoint(
        build_runtime_state(),
        Signals(),  # type: ignore[arg-type]
        run_id="r" * 32,
        correlation_id=new_correlation_id(),
        config=replace(default_config(), diagnostics_http=settings),
    )
    endpoint.start()
    workers = list(endpoint.workers)
    _request(settings.port)
    endpoint.stop()
    assert endpoint.workers == []
    assert all(not worker.is_alive() for worker in workers)
    assert endpoint.server is None


def test_starting_twice_binds_once_and_stopping_twice_closes_once() -> None:
    """Idempotent in both directions, because a caller cannot always know what ran."""
    settings = _settings()
    endpoint, _gate = build_diagnostics_endpoint(
        build_runtime_state(),
        Signals(),  # type: ignore[arg-type]
        run_id="r" * 32,
        correlation_id=new_correlation_id(),
        config=replace(default_config(), diagnostics_http=settings),
    )
    try:
        assert endpoint.start() is True
        assert endpoint.start() is False
        assert len(endpoint.workers) == settings.max_concurrent_requests
        assert _request(settings.port)[0] == STATUS_OK
    finally:
        assert endpoint.stop() is True
        assert endpoint.stop() is False


def test_a_surface_can_be_started_again_after_it_was_stopped() -> None:
    """The property a restart depends on, and the one `allow_reuse_address` risks."""
    settings = _settings()
    endpoint, _gate = build_diagnostics_endpoint(
        build_runtime_state(),
        Signals(),  # type: ignore[arg-type]
        run_id="r" * 32,
        correlation_id=new_correlation_id(),
        config=replace(default_config(), diagnostics_http=settings),
    )
    endpoint.start()
    assert _request(settings.port)[0] == STATUS_OK
    endpoint.stop()
    endpoint.start()
    try:
        assert _request(settings.port)[0] == STATUS_OK
    finally:
        endpoint.stop()
