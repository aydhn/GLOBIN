"""The one module in GLOBIN that opens a listening socket.

Everything decidable without a connection is in `domain/diagnostics_http.py` and
`application/diagnostics_http.py`. What is left here is the part that genuinely
cannot be pure: accepting a connection, admitting or refusing it, reading a request
line, and writing bytes back. `tests/architecture/test_library_discipline.py` names
this module as the only one that may reach a socket at all, and fails if a second
one does.

**The standard library, and its own documentation says why that needs an argument.**
`http.server` is *"not recommended for production. It only implements basic security
checks"* — and that warning is about serving files to untrusted clients, which is
precisely what this does not do. There is no file serving, no directory logic, no CGI
and no routing framework; a request target is looked up in a five-entry table of
exact strings and is otherwise ``unknown``. What remains of the module is a request
parser and a socket, which is the smallest correct thing for a read-only surface that
only this machine can reach. A framework would have been a larger dependency and a
larger attack surface for the same five documents.

**A bounded pool, not a thread per connection.** `ThreadingHTTPServer` spawns one
thread per connection with no ceiling and marks them daemons, so a burst becomes
unbounded threads and a shutdown becomes threads killed mid-write. Instead
:meth:`BoundedDiagnosticsServer.process_request` — the same documented extension
point `ThreadingMixIn` overrides — hands the connection to a bounded queue drained by
a fixed pool of **non-daemon** workers created once at start. When the queue is full
the connection gets a deterministic 503 and is closed. So the worker count *is*
``max_concurrent_requests``, there is no second limit to get wrong, and capacity
exhaustion is a refusal rather than growth.

**`HTTP/1.0`, deliberately.** Setting `protocol_version` to `HTTP/1.1` would enable
persistent connections, and an idle keep-alive connection would hold a pool slot
against a surface whose whole pool is four. Closing after each response costs a
scraper one handshake every fifteen seconds and buys a bound that cannot be occupied.

**Responses go out through `send_response_only`, and that one choice carries two
guarantees.** `send_response()` writes a `Server` header built from
`version_string()` — which is where `BaseHTTP/0.6 Python/3.14.5` comes from — *and*
calls `log_request()`, which writes an unstructured line to standard error.
`send_response_only()` does neither, so there is no product fingerprint to strip and
no second logging path to silence. Every header this module sends comes from a
constant in the domain module or from an integer it computed; no request header is
ever echoed, which is why CR/LF response splitting has no source to come from.
"""

import http.server
import ipaddress
import queue
import socket
import socketserver
import threading
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import formatdate
from typing import Any, Final

from globin.adapters.telemetry_prometheus import render_exposition, render_openmetrics
from globin.application.diagnostics_http import (
    METRIC_INFLIGHT,
    METRIC_REJECTED,
    DiagnosticsService,
)
from globin.application.observability import Logger
from globin.domain.clock import Duration, MonotonicReading
from globin.domain.diagnostics_http import (
    CACHE_CONTROL_VALUE,
    CONTENT_TYPE_OPTIONS_VALUE,
    CONTENT_TYPE_TEXT,
    HEADER_ALLOW,
    HEADER_CACHE_CONTROL,
    HEADER_CONTENT_LENGTH,
    HEADER_CONTENT_TYPE,
    HEADER_CONTENT_TYPE_OPTIONS,
    HEADER_PRAGMA,
    PRAGMA_VALUE,
    STATUS_BAD_REQUEST,
    STATUS_NOT_IMPLEMENTED,
    STATUS_UNAVAILABLE,
    DiagnosticsHttpPolicy,
    DiagnosticsResponse,
    DiagnosticsRoute,
    ExpositionFormat,
    ReadinessReason,
    RejectionReason,
    RequestOutcome,
)
from globin.domain.metrics import TelemetrySnapshot
from globin.ports.clock import Clock, MonotonicClock
from globin.ports.diagnostics_http import HealthProjection
from globin.ports.runtime_state import ShutdownSignals
from globin.ports.telemetry import MetricRecorder, MetricSource

SERVER_THREAD_NAME: Final[str] = "globin-diagnostics-acceptor"
"""The acceptor thread's name, so a stack dump names it rather than `Thread-3`."""

WORKER_THREAD_PREFIX: Final[str] = "globin-diagnostics-worker"
"""What each worker thread is called, with its index appended."""

EVENT_STARTED: Final[str] = "diagnostics.http.started"
"""The surface bound a socket. Carries the address and port, which are not secrets."""

EVENT_STOPPED: Final[str] = "diagnostics.http.stopped"
"""The surface released its socket and joined every worker."""

EVENT_DRAIN_INCOMPLETE: Final[str] = "diagnostics.http.drain.incomplete"
"""A worker was still busy when the shutdown deadline passed."""

EVENT_CONNECTION_FAILED: Final[str] = "diagnostics.http.connection.failed"
"""One connection failed at the socket level, which a worker must survive."""

BODY_AT_CAPACITY: Final[bytes] = b"the diagnostics surface is at capacity\n"
"""What a refused connection is told. Small, constant, and it names no limit."""

BODY_MALFORMED: Final[bytes] = b"the request could not be read\n"
"""What an unparseable request is told.

It names nothing about what was wrong, because everything available at that point
came from the request — and a body that quotes the offending line is a body that
carries attacker-chosen text."""

EVENT_MALFORMED: Final[str] = "diagnostics.http.malformed"
"""One request the HTTP parser could not read at all."""

HEADER_DATE: Final[str] = "Date"
"""Written explicitly, because `send_response_only` does not add it."""

HEADER_TERMINATOR: Final[bytes] = b"\r\n"
"""What ends a header line, and what ends the header block a second time."""

TRANSFER_ENCODING: Final[str] = "Transfer-Encoding"
"""A header that announces a framed body, which this surface will not read."""

CONTENT_LENGTH: Final[str] = "Content-Length"
"""A header that announces a body's size."""

ACCEPT: Final[str] = "Accept"
"""The one request header whose *value* influences a response."""

REFUSAL_DRAIN_BYTES: Final[int] = 4_096
"""How much of an unserved request is read and discarded before closing.

One bounded read, not a loop: enough to clear the request line and headers of any
realistic request so that the close is graceful rather than a reset, and small enough
that a peer cannot make the accept loop read indefinitely. Nothing is parsed.
"""


@dataclass(slots=True)
class DiagnosticsEndpoint:
    """A bounded, loopback-only HTTP surface over one :class:`DiagnosticsService`.

    Args:
        service: What actually answers a request.
        policy: Every bound this surface runs inside.
        recorder: Where inflight and admission refusals are counted.
        logger: Where lifecycle records go.
        workers: The fixed pool. It has **no default**, for the reason
            :class:`~globin.application.lifecycle.Session` gives about its
            ``cleanups``: a default of ``[]`` would have to be constructed, and
            ``field(default_factory=list)`` is a call in a class body, which
            ``tests/architecture/test_architecture_contract.py`` forbids in every
            layer package. :func:`~globin.runtime.composition.build_diagnostics_endpoint`
            builds it, where a call is just a call.
        spawn: How a thread is created. Substitutable so a test can observe that one
            would have been started without starting it — the treatment
            `WatchdogThread` and `PlatformShutdownSignals` already get, and for the
            same reason: a test that started a real thread and then failed would leave
            it running for every test after it.
        server: The bound server, or ``None`` before :meth:`start` and after
            :meth:`stop`.
        acceptor: The thread running the accept loop.
        started: Whether a socket is currently bound.

    **Constructing this binds nothing.** The socket is opened by :meth:`start` and by
    nothing else, so a composition root that builds one and never starts it has opened
    no port — and a bootstrap with the surface disabled never builds one at all.
    """

    service: DiagnosticsService
    policy: DiagnosticsHttpPolicy
    recorder: MetricRecorder
    logger: Logger
    workers: list[Any]
    spawn: Callable[..., Any] = threading.Thread
    server: Any = None
    acceptor: Any = None
    started: bool = False

    @property
    def address(self) -> tuple[str, int]:
        """Where the socket actually is.

        Returns:
            The bound address and port. With a configured port of zero the second
            element is what the operating system chose, which is what an integration
            test needs and what the runtime default deliberately never uses.

        Raises:
            RuntimeError: If nothing is bound, because there is no honest answer.
        """
        if self.server is None:
            message = "the diagnostics surface is not bound"
            raise RuntimeError(message)
        bound: tuple[str, int] = self.server.server_address[:2]
        return bound

    def start(self) -> bool:
        """Bind the socket and start the pool.

        Returns:
            Whether this call started it. ``False`` when it was already running, so a
            caller that cannot know what already ran is safe — the idempotence
            `WatchdogThread.start` has.

        Raises:
            OSError: If the port cannot be bound. **Allowed through deliberately**:
                the caller asked for a surface, and a surface that silently failed to
                bind would leave a supervisor polling an endpoint that will never
                answer. The composition root turns this into a start-up refusal.

        The pool is created before the accept loop, so no connection can be admitted
        before there is something to admit it to.
        """
        if self.started:
            return False
        self.server = BoundedDiagnosticsServer(
            self.policy, self.recorder, self.logger, self._handler()
        )
        for index in range(self.policy.max_concurrent_requests):
            worker = self.spawn(
                target=self._work,
                name=f"{WORKER_THREAD_PREFIX}-{index}",
                daemon=False,
            )
            self.workers.append(worker)
            worker.start()
        self.acceptor = self.spawn(
            target=self.server.serve_forever, name=SERVER_THREAD_NAME, daemon=False
        )
        self.acceptor.start()
        self.started = True
        host, port = self.address
        self.logger.info(EVENT_STARTED, address=host, port=port, workers=len(self.workers))
        return True

    def stop(self) -> bool:
        """Stop accepting, drain what is in flight, close the socket, join every worker.

        Returns:
            Whether this call stopped it. ``False`` when nothing was running.

        **Stop accepting before draining**, which is `WatchdogThread.stop`'s ordering
        rule and matters for the same reason: a loop still admitting connections cannot
        be drained, because the thing being drained keeps refilling.

        The drain is bounded by ``shutdown_timeout_seconds``. A worker still busy when
        the deadline passes is recorded and left — joining it without a bound would make
        one wedged request able to prevent the process from ever exiting, which is
        exactly the failure Phase 025's watchdog exists to end.
        """
        if not self.started:
            return False
        self.started = False
        server = self.server
        if server is not None:
            server.shutdown()
        for _ in self.workers:
            self._enqueue_stop()
        deadline = float(self.policy.shutdown_timeout_seconds)
        stragglers = 0
        for worker in self.workers:
            worker.join(timeout=deadline)
            if worker.is_alive():
                stragglers += 1
        if self.acceptor is not None:
            self.acceptor.join(timeout=deadline)
        if server is not None:
            server.server_close()
        if stragglers:
            self.logger.warning(EVENT_DRAIN_INCOMPLETE, workers=stragglers)
        self.logger.info(EVENT_STOPPED, workers=len(self.workers))
        self.server = None
        self.acceptor = None
        self.workers.clear()
        return True

    def _handler(self) -> type["DiagnosticsRequestHandler"]:
        """A handler class bound to this endpoint's service and policy.

        Returns:
            A subclass carrying the two references a handler instance needs.

        `socketserver` instantiates the handler class per connection and passes it no
        application state, so the state is attached to a per-endpoint subclass rather
        than to a module-level global. Two endpoints in one process — which is what a
        test that starts a second one does — therefore cannot see each other's service.
        """
        service = self.service
        policy = self.policy
        logger = self.logger

        class Bound(DiagnosticsRequestHandler):
            """This endpoint's handler."""

            diagnostics = service
            timeout = policy.request_timeout_seconds
            endpoint_logger = logger

        return Bound

    def _work(self) -> None:
        """Serve connections from the queue until asked to stop.

        Every exception is contained: a worker that died would silently reduce the
        pool, and the surface would then look healthy while serving fewer requests
        than it claims to. The `DiagnosticsService` already answers a failed handler
        with a 500, so anything reaching here is a socket-level fault.
        """
        while True:
            server = self.server
            if server is None:
                return
            item = server.pending.get()
            if item is None:
                return
            request, client_address = item
            try:
                server.finish_request(request, client_address)
            except Exception as fault:
                # Recorded rather than swallowed, and through Phase 023's logger so it
                # is structured and redacted. Only the exception's *type* is written: a
                # socket error's message can carry a peer address, and ADR-0026's
                # redaction is by field name rather than by content.
                self.logger.warning(EVENT_CONNECTION_FAILED, fault=type(fault).__name__)
            finally:
                server.shutdown_request(request)
                self.recorder.set_gauge(METRIC_INFLIGHT, max(server.inflight_delta(-1), 0))

    def _enqueue_stop(self) -> None:
        """Put one stop sentinel on the queue, so exactly one worker exits."""
        server = self.server
        if server is not None:
            server.pending.put(None)


class BoundedDiagnosticsServer(socketserver.TCPServer):
    """A TCP server that admits a bounded number of connections and refuses the rest.

    Deliberately **not** built on `ThreadingMixIn`. That mixin's contract is one
    thread per connection, which is unbounded by construction, and its
    `ThreadingHTTPServer` subclass marks those threads daemons — so a shutdown kills
    them wherever they happen to be. What is kept from it is the extension point:
    `process_request` is the documented place to decide what happens with an accepted
    connection, and this hands it to a queue instead of to a new thread.
    """

    allow_reuse_address = False
    """Refuse to rebind a port another socket still holds.

    The library's own default is `True`, which on some platforms lets two processes
    bind the same port and share the incoming connections between them. For a surface
    whose whole job is to report on *this* process, a scrape that silently reached a
    different one would be worse than a refusal to start.
    """

    def __init__(
        self,
        policy: DiagnosticsHttpPolicy,
        recorder: MetricRecorder,
        logger: Logger,
        handler: type[http.server.BaseHTTPRequestHandler],
    ) -> None:
        """Bind the socket.

        Args:
            policy: Every bound, including the validated address.
            recorder: Where admission refusals and inflight are counted.
            logger: Where a refusal is recorded.
            handler: The per-connection handler class.

        Raises:
            OSError: If the address cannot be bound.

        The address family is chosen from the *parsed* address rather than from the
        string, so `::1` opens an IPv6 socket without anybody having configured a
        family.
        """
        self.address_family = socket.AF_INET6 if policy.address.is_ipv6 else socket.AF_INET
        self.policy = policy
        self.recorder = recorder
        self.endpoint_logger = logger
        self.pending: queue.Queue[tuple[Any, Any] | None] = queue.Queue(
            maxsize=policy.max_concurrent_requests
        )
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        super().__init__((policy.address.text, policy.port), handler, bind_and_activate=True)

    def verify_request(self, request: Any, client_address: Any) -> bool:
        """Refuse a peer that is not on this machine.

        Args:
            request: The accepted socket.
            client_address: Where it came from.

        Returns:
            Whether to serve it.

        **Defence in depth, and it should be unreachable.** The socket is bound to a
        loopback address that a value type has already refused unless it is loopback,
        so a non-loopback peer cannot arrive. Checking anyway costs one comparison per
        connection and means the guarantee does not rest solely on the bind having
        been correct.
        """
        del request
        host = client_address[0] if client_address else ""
        try:
            return ipaddress.ip_address(str(host)).is_loopback
        except ValueError:
            return False

    def process_request(self, request: Any, client_address: Any) -> None:
        """Hand an accepted connection to the pool, or refuse it.

        Args:
            request: The accepted socket.
            client_address: Where it came from.

        **This is where capacity becomes a refusal rather than growth.** A full queue
        means every worker is busy and the backlog is already at its bound, so the
        connection is answered with a 503 and closed here, on the accept loop. That
        costs the accept loop one small write, which is bounded, rather than a thread,
        which is not.
        """
        try:
            self.pending.put_nowait((request, client_address))
        except queue.Full:
            self.recorder.count(METRIC_REJECTED, reason=RejectionReason.ADMISSION.value)
            _refuse(request, self.policy.request_timeout_seconds)
            self.shutdown_request(request)
            return
        self.recorder.set_gauge(METRIC_INFLIGHT, self.inflight_delta(1))

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Say nothing on standard error.

        Args:
            request: Ignored.
            client_address: Ignored.

        The base class prints a traceback and the peer address to standard error.
        Under `--json` that would corrupt a document; at any time it would be an
        unstructured second logging path beside Phase 023's. The worker already
        records what it needs to.
        """
        del request, client_address

    def inflight_delta(self, delta: int) -> int:
        """Move the in-flight count and report the new value.

        Args:
            delta: ``+1`` on admission, ``-1`` on completion.

        Returns:
            The count after the change.

        Guarded by a lock because the accept loop increments it and a worker
        decrements it, and a gauge that drifted would be the one number an operator
        uses to decide whether the surface is wedged.
        """
        with self._inflight_lock:
            self._inflight += delta
            return self._inflight


class DiagnosticsRequestHandler(http.server.BaseHTTPRequestHandler):
    """Reads one request, asks the service, writes the answer.

    Almost nothing of the base class's behaviour survives: the `do_*` dispatch is
    replaced by two methods, `log_message` is silenced in favour of the structured
    logger, `send_error` is replaced so that no HTML page can be produced, and every
    response is written through `send_response_only` so that neither a `Server` header
    nor a standard-error access line is produced.

    **Overriding `send_error` is not tidiness; it closes a real hole.** Defining only
    `do_GET` and `do_HEAD` leaves the base class to answer every other method through
    `send_error(501)`, which writes a **generic HTML page** — with no `Cache-Control`,
    no `nosniff`, a `Content-Type` of `text/html`, and the requested method echoed into
    the body. It is also the path taken by an unparseable request line, an unsupported
    HTTP version, an over-long line and too many headers. One override catches all of
    them, which is why it is preferred to enumerating `do_POST`, `do_PUT` and whatever
    verb a scanner tries next.
    """

    diagnostics: DiagnosticsService
    endpoint_logger: Logger
    protocol_version = "HTTP/1.0"
    """No keep-alive. An idle connection must not be able to hold a pool slot."""

    server_version = ""
    """Emptied, though nothing reads it: no response goes through `send_response`."""

    sys_version = ""
    """Emptied for the same reason. The interpreter's version is not a client's business."""

    error_message_format = ""
    """Emptied so that even a path this class has not anticipated writes no HTML."""

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Answer a request the base class could not dispatch, without an HTML page.

        Args:
            code: What the base class decided.
            message: Ignored. It carries the requested method or the offending line.
            explain: Ignored, for the same reason.

        An unsupported method is routed through the service, so it is counted, logged
        with a bounded reason, and answered ``405`` with the ``Allow`` header a client
        needs. Anything else — a malformed request line, an unsupported version — is
        answered with a bounded ``400`` and no detail, because every detail available
        here came from the request.

        **Neither `message` nor `explain` is used.** Both are built by the base class
        from what the client sent, and echoing either into a body is how a response
        starts carrying attacker-chosen text.
        """
        del message, explain
        if code == STATUS_NOT_IMPLEMENTED and self.command:
            self._write(
                self.diagnostics.handle(self.command, self.path or "", has_body=self._has_body()),
                write_body=True,
            )
            return
        self.endpoint_logger.info(EVENT_MALFORMED, status=STATUS_BAD_REQUEST)
        self._write(
            DiagnosticsResponse(
                status=STATUS_BAD_REQUEST,
                content_type=CONTENT_TYPE_TEXT,
                body=BODY_MALFORMED,
                route=DiagnosticsRoute.UNKNOWN,
                outcome=RequestOutcome.REJECTED,
            ),
            write_body=True,
        )

    def do_GET(self) -> None:
        """Answer a ``GET``."""
        self._respond(write_body=True)

    def do_HEAD(self) -> None:
        """Answer a ``HEAD``.

        Identical to ``GET`` in every respect except that the body is not written. The
        status, the content type and the ``Content-Length`` are the ones ``GET`` would
        have produced, because a ``HEAD`` that reported a different length would be
        worse than one that reported none.
        """
        self._respond(write_body=False)

    def _respond(self, *, write_body: bool) -> None:
        """Ask the service and write what it said.

        Args:
            write_body: Whether the body reaches the socket.
        """
        self._write(
            self.diagnostics.handle(
                self.command or "",
                self.path or "",
                self.headers.get(ACCEPT, "") or "",
                has_body=self._has_body(),
            ),
            write_body=write_body,
        )

    def _write(self, response: DiagnosticsResponse, *, write_body: bool) -> None:
        """Write one response, headers and all.

        Args:
            response: What to send.
            write_body: Whether the body reaches the socket. ``False`` for a ``HEAD``,
                whose headers are otherwise identical.

        The one place bytes leave this surface, so the header set is stated once. Every
        value is a constant from the domain module or an integer computed here — no
        request header is echoed, which is why response splitting has no source.
        """
        self.send_response_only(response.status)
        self.send_header(HEADER_CONTENT_TYPE, response.content_type)
        self.send_header(HEADER_CONTENT_LENGTH, str(response.length))
        self.send_header(HEADER_CACHE_CONTROL, CACHE_CONTROL_VALUE)
        self.send_header(HEADER_PRAGMA, PRAGMA_VALUE)
        self.send_header(HEADER_CONTENT_TYPE_OPTIONS, CONTENT_TYPE_OPTIONS_VALUE)
        if response.allow:
            self.send_header(HEADER_ALLOW, response.allow)
        self.send_header(HEADER_DATE, formatdate(usegmt=True))
        self.end_headers()
        if write_body:
            self.wfile.write(response.body)

    def _has_body(self) -> bool:
        """Whether this request carried a body, or announced one.

        Returns:
            Whether the service should refuse it.

        Both spellings are refused. A ``Content-Length`` above zero announces a body
        this surface will not read, and any ``Transfer-Encoding`` announces a framed
        one — and a request whose body is never consumed leaves bytes in the socket
        that the *next* request on a reused connection would read as its own request
        line. That is request smuggling, and refusing is what makes it impossible
        rather than merely unlikely.
        """
        if self.headers.get(TRANSFER_ENCODING):
            return True
        declared = self.headers.get(CONTENT_LENGTH)
        if declared is None:
            return False
        try:
            return int(declared) > 0
        except ValueError:
            return True

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Write nothing to standard error.

        Args:
            format: Ignored.
            args: Ignored.

        The base class prefixes every line with the peer address and the wall-clock
        time and writes it to standard error. Phase 023 made GLOBIN's records
        structured and redacted; a second, unstructured path would be exactly the
        thing `tests/architecture/test_logging_discipline.py` exists to prevent. Every
        request is already recorded by `DiagnosticsService`, with a normalised route
        rather than the raw target.
        """
        del format, args


def _refuse(request: Any, timeout_seconds: int) -> None:
    """Write a minimal 503 to a connection that was not admitted.

    Args:
        request: The accepted socket.
        timeout_seconds: How long the write may take.

    Hand-written rather than routed through a handler, because constructing one would
    allocate the very thing there is no capacity for. Every byte is a constant, so
    nothing a client sent can influence it.
    """
    head = (
        f"HTTP/1.0 {STATUS_UNAVAILABLE} Service Unavailable",
        f"{HEADER_CONTENT_TYPE}: {CONTENT_TYPE_TEXT}",
        f"{HEADER_CONTENT_LENGTH}: {len(BODY_AT_CAPACITY)}",
        f"{HEADER_CACHE_CONTROL}: {CACHE_CONTROL_VALUE}",
        f"{HEADER_CONTENT_TYPE_OPTIONS}: {CONTENT_TYPE_OPTIONS_VALUE}",
    )
    payload = HEADER_TERMINATOR.join(line.encode("ascii") for line in head)
    try:
        # The timeout is not decoration. This write happens on the *accept loop*,
        # so a peer that opened a connection and stopped reading could otherwise
        # block the one thread that admits work — turning a refused connection
        # into a wedged surface, which is a worse outcome than the overload the
        # refusal exists to handle.
        request.settimeout(float(timeout_seconds))
        request.sendall(payload + HEADER_TERMINATOR + HEADER_TERMINATOR + BODY_AT_CAPACITY)
        # Then read the request that was never going to be served, and discard it.
        #
        # **Without this the client never sees the 503 it was just sent.** Closing a
        # socket that still holds unread received data makes the operating system send
        # a reset rather than a graceful shutdown, and a reset discards whatever was
        # in flight — so a caller at capacity would get a connection error instead of
        # the deterministic refusal this whole path exists to produce. Bounded by one
        # small read and by the timeout above, because the point is to clear the
        # buffer rather than to parse anything.
        request.recv(REFUSAL_DRAIN_BYTES)
    except OSError:
        return


HEALTH_CACHE_NANOSECONDS: Final[int] = 1_000_000_000
"""How long a health snapshot may be reused before another is measured.

**A bound on cost, not a performance tweak.** Producing a snapshot reads the process,
the host and the filesystem, and this surface is reachable by anything on the machine
that can open a socket — so without a floor on the interval, the polling rate would
decide how much work GLOBIN does. One second is the finest granularity worth
publishing about a process that reports uptime in seconds, and it caps any polling
rate at one measurement per second.

Not a setting. An operator has no basis for preferring 900 milliseconds, and
``CONFIGURATION_POLICY.md`` warns that this is exactly where speculative fields
accumulate.
"""


@dataclass(slots=True)
class ShutdownLiveness:
    """Liveness read from the shutdown signal and from nothing else.

    Args:
        signals: Where a stop request arrives.

    **The narrowness is the whole design.** This cannot reach a health probe, a
    filesystem, a library or a lock, because a liveness endpoint that failed when a
    disk filled up would tell a supervisor to restart a process that is running
    perfectly — and a supervisor that restarts a healthy process during a disk problem
    has turned one incident into two.
    """

    signals: ShutdownSignals

    def alive(self) -> bool:
        """Whether the process is live.

        Returns:
            ``False`` once a stop has been requested, ``True`` before that.
        """
        return not self.signals.requested()


@dataclass(slots=True)
class ReadinessGate:
    """Readiness as a state the run advances, not a measurement.

    Args:
        signals: Where a stop request arrives, which outranks whatever was set.
        reason: What to report while nothing has changed it.

    **Starting, not ready, is the initial state.** A gate that defaulted to ready
    would report a process as able to work during the window before its bootstrap had
    finished, which is precisely the window a readiness probe exists to describe.

    Mutable, unlike almost everything else here, because advancing through start-up is
    the one thing a run must be able to do to it. Phases 033-048 add their own
    conditions by setting a reason rather than by widening the type: the enum carries
    ``DEPENDENCY_UNREADY`` already.
    """

    signals: ShutdownSignals
    reason: ReadinessReason = ReadinessReason.STARTING

    def readiness(self) -> ReadinessReason:
        """Why the process is or is not ready.

        Returns:
            ``STOPPING`` once a stop has been requested, whatever was recorded
            otherwise.

        A stop request wins over a recorded ``READY``, because the ordering matters to
        whatever is sending work: it must stop sending *before* the process stops
        accepting, and the only way it learns that is by asking.
        """
        if self.signals.requested():
            return ReadinessReason.STOPPING
        return self.reason

    def mark_ready(self) -> None:
        """Record that start-up finished and work may arrive."""
        self.reason = ReadinessReason.READY

    def mark_unready(self, reason: ReadinessReason) -> None:
        """Record that the process cannot work, and why.

        Args:
            reason: Which bounded class of unreadiness applies.
        """
        self.reason = reason


@dataclass(slots=True)
class CachedHealthProjection:
    """The health snapshot as a publishable document, measured at most once a second.

    Args:
        take: Produces a fresh document. A callable rather than the collector itself,
            so this holds no opinion about what a snapshot needs — the composition root
            has already bound the run identity into it.
        monotonic: How the age of the cached document is measured.
        cached: The document last produced, or ``None`` before the first.
        measured_at: When it was produced.

    **The cache is a limit rather than an optimisation.** See
    :data:`HEALTH_CACHE_NANOSECONDS`.
    """

    take: Callable[[], dict[str, object]]
    monotonic: MonotonicClock
    cached: dict[str, object] | None = None
    measured_at: int = 0

    def document(self) -> dict[str, object]:
        """The health document, freshly measured or reused.

        Returns:
            Plain types, ready for canonical JSON.

        No lock. Two concurrent requests may both find the cache stale and both
        measure, which costs one extra snapshot and is the cheaper mistake: a lock here
        would let one slow measurement block every other request, which is the failure
        a bounded surface exists to avoid.
        """
        now = self.monotonic.reading().nanoseconds
        if self.cached is None or now - self.measured_at >= HEALTH_CACHE_NANOSECONDS:
            self.cached = self.take()
            self.measured_at = now
        return self.cached


@dataclass(slots=True)
class TelemetryExposition:
    """The current measurements, encoded in whichever format was negotiated.

    Args:
        source: Where the families come from — Phase 026's one registry.
        clock: Stamps the snapshot.
        monotonic: Measures uptime.
        started: The reading taken when the process started.
        run_id: Which run this is.

    **No exporter is reached.** The snapshot is taken from the local store and encoded
    in this process, so a scrape keeps working when a remote collector is down or slow —
    which is the property that stops a collector's timeout appearing in a request's
    critical path.
    """

    source: MetricSource
    clock: Clock
    monotonic: MonotonicClock
    started: MonotonicReading
    run_id: str

    def snapshot(self) -> TelemetrySnapshot:
        """Everything measured so far.

        Returns:
            The snapshot, stamped now.
        """
        elapsed = self.monotonic.reading().nanoseconds - self.started.nanoseconds
        return TelemetrySnapshot(
            generated_at=self.clock.now(),
            uptime=Duration(nanoseconds=max(elapsed, 0)),
            run_id=self.run_id,
            families=self.source.families(),
            drops=self.source.drop_counts(),
        )

    def render(self, exposition: ExpositionFormat) -> str:
        """Encode the current measurements.

        Args:
            exposition: Which format the negotiation chose.

        Returns:
            The exposition text.
        """
        document = self.snapshot().document()
        if exposition is ExpositionFormat.OPENMETRICS_TEXT:
            return render_openmetrics(document)
        return render_exposition(document)


@dataclass(slots=True)
class DiagnosticsSnapshotProjection:
    """The fuller document, which an operator must opt into twice.

    Args:
        health: The health projection, reused so a snapshot and ``/health/runtime``
            cannot disagree about the same process.
        exposition: Where the telemetry half comes from.

    **It writes nothing.** No archive is built, no file is touched, no directory is
    walked — those belong to ``diagnostics bundle``, which is a command an operator
    runs rather than a route a poller reaches. What makes this more than
    ``/health/runtime`` is that it carries what telemetry has measured beside the
    health verdict, which is also why it has its own switch.
    """

    health: HealthProjection
    exposition: TelemetryExposition

    def document(self) -> dict[str, object]:
        """The health verdict and the telemetry snapshot, together.

        Returns:
            Plain types, ready for canonical JSON.
        """
        return {
            "health": self.health.document(),
            "telemetry": self.exposition.snapshot().document(),
        }
