"""The one module in GLOBIN that reaches outward, and everything it is bounded by.

Until this phase ``src/globin`` opened no outbound connection at all, and
``tests/architecture/test_library_discipline.py`` named exactly one module that
could reach a socket — the loopback diagnostics listener. It now names two, and
this is the second. The rule did not relax: the count is still exact, still
asserted in both directions, and the outbound half is *narrower* than before,
because that test previously guarded ``socket`` and ``socketserver`` while leaving
``http.client``, ``ssl`` and ``urllib.request`` unnamed. Any module could have
reached the internet; now one can.

**TLS verification cannot be switched off, because there is no switch.**
:func:`secure_context` takes no arguments and returns a context that has already
had ``check_hostname`` and ``verify_mode`` asserted. Nothing in this module accepts
a "verify" flag, a "insecure" mode or a CA override, so an operator cannot disable
verification through configuration and a caller cannot disable it through an
argument. ``tests/contract/test_rest_contract.py`` additionally proves the package
contains no ``CERT_NONE`` token anywhere — the same absence check
``test_library_discipline.py`` uses for wildcard bind addresses, and for the same
reason: a validator can only refuse what reaches it.

**It cannot choose where to go.** :meth:`HttpRestTransport.send` is handed an
:class:`~globin.domain.rest_endpoint.EndpointResolution` and has no access to the
registry. There is no code path here that reads a base URL, picks between hosts, or
retries against a second one. Endpoint substitution is absent from the object graph
rather than forbidden by a rule.

**It never retries, and there is no parameter that would make it.** No loop, no
backoff, no replay. Phase 043 owns retry and inherits one rule from here: an
outcome of :attr:`~globin.domain.rest.RequestOutcome.UNKNOWN` is never replayed,
because replaying a mutating request whose fate is unknown is how one order becomes
two.

**Connecting is an explicit step, and that is what makes the outcome honest.**
``http.client`` connects lazily inside ``request()``, which would fold a DNS
failure and a half-written request into one exception and leave GLOBIN unable to
say whether any bytes left the process. :meth:`_exchange` therefore calls
``connect()`` itself, so a failure before that point is provably
:attr:`~globin.domain.rest.SendState.NOT_SENT` and a failure after it is
conservatively :attr:`~globin.domain.rest.SendState.SENT`.
"""

import http.client
import json
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from globin.domain.clock import MonotonicReading
from globin.domain.rest import (
    MAX_RESPONSE_BYTES,
    MEDIA_TYPE_HTML,
    MEDIA_TYPE_JSON,
    MEDIA_TYPE_SBE,
    MEDIA_TYPE_TEXT_PREFIX,
    NO_EXCHANGE_CODE,
    NO_STATUS,
    ORDER_COUNT_PREFIX,
    RETRY_AFTER_HEADER,
    USED_WEIGHT_PREFIX,
    BodyShape,
    ExchangeFault,
    RateLimitReport,
    RequestOutcome,
    ResponseEncoding,
    RestDiagnosticsRecord,
    RestExchange,
    RestOutcomeInputs,
    RestRequest,
    RestResponse,
    RestTiming,
    SbeEnvelope,
    SendState,
    TransportFailureKind,
    classify,
    negotiation_headers,
)
from globin.domain.rest_endpoint import EndpointResolution, ResolvedEndpoint
from globin.errors import ValidationError
from globin.ports.clock import MonotonicClock

DEFAULT_POOL_SIZE: Final[int] = 4
"""How many connections one transport may hold open at once.

Small on purpose. GLOBIN is one process on one machine talking to one venue, and a
pool sized for a web server would hold sockets nobody is using against a rate limit
that counts requests rather than connections.
"""

DEFAULT_MAX_USES: Final[int] = 100
"""How many requests one connection may carry before it is retired.

Bounds the blast radius of a connection that has silently gone bad — a state a
keep-alive socket can reach without either end noticing until the next write.
"""

DEFAULT_KEEPALIVE_NANOSECONDS: Final[int] = 60 * 1_000_000_000
"""How long an idle pooled connection stays useful.

Sixty seconds, below any documented idle timeout GLOBIN would be subject to, so the
common case is that GLOBIN closes a connection rather than discovering the venue
already did.
"""

JSON_MEDIA_TYPES: Final[tuple[str, ...]] = (MEDIA_TYPE_JSON, "text/json")
"""Content types this transport will hand to a JSON parser, and no others.

``text/json`` is here because intermediaries emit it. Anything else — including an
absent content type — is :attr:`~globin.domain.rest.BodyShape.UNEXPECTED_CONTENT_TYPE`
rather than a guess, which is what stops a firewall's HTML page reaching a parser
that would report a syntax error about column one.
"""

EXCHANGE_CODE_KEY: Final[str] = "code"
"""What Binance calls the error code in its documented error payload."""

EXCHANGE_MESSAGE_KEY: Final[str] = "msg"
"""What Binance calls the error text in its documented error payload."""


def secure_context() -> ssl.SSLContext:
    """A TLS context that verifies, with no way to ask it not to.

    Returns:
        A context with hostname checking and certificate verification on.

    Raises:
        ValidationError: If the standard library ever returns a context that does not
            verify. Asserted rather than assumed, because this is the one property
            whose silent loss would be invisible in every test that passes.

    **No parameters, by design.** A ``verify: bool`` argument here would be the
    whole security posture of the transport reduced to a keyword somebody could
    default wrongly. ``ssl.create_default_context`` already verifies; this asserts
    that it did and hands back the result.
    """
    context = ssl.create_default_context()
    if not context.check_hostname or context.verify_mode is not ssl.CERT_REQUIRED:
        msg = (
            "the platform's default TLS context does not verify certificates; "
            "GLOBIN will not send a request over it"
        )
        raise ValidationError(msg)
    return context


type ConnectionFactory = Callable[[str, int, float], http.client.HTTPConnection]
"""How a connection is made, so that a test can reach a server it started itself.

**The seam is the factory, never a verification flag.** The default,
:func:`https_connection`, always builds an
:class:`http.client.HTTPSConnection` over :func:`secure_context`, and there is no
argument that changes what it builds. A test substitutes the whole factory — a
substitution that is visible in a constructor call rather than hidden in a
configuration value — which is how ``tests/integration`` exercises the real status
and body matrix against a local server without a certificate authority.

What this does *not* open up: :class:`~globin.domain.rest_endpoint.ResolvedEndpoint`
refuses any URL that is not HTTPS, so no factory can be pointed at a plaintext venue
endpoint. The scheme is guarded where the address is decided, not where the socket
is made.
"""


def https_connection(host: str, port: int, timeout: float) -> http.client.HTTPConnection:
    """The production connection factory. Verifies, always.

    Args:
        host: The endpoint's hostname.
        port: Its port, or ``0`` for the scheme default.
        timeout: How long any single socket operation may take.

    Returns:
        An unconnected HTTPS connection.
    """
    if port:
        return http.client.HTTPSConnection(host, port, timeout=timeout, context=secure_context())
    return http.client.HTTPSConnection(host, timeout=timeout, context=secure_context())


@dataclass(slots=True)
class _Pooled:
    """One connection the transport is holding, and what bounds its reuse."""

    connection: http.client.HTTPConnection
    opened: MonotonicReading
    uses: int = 0
    connected: bool = False
    """Whether this connection's socket is up.

    Tracked rather than inferred because ``HTTPConnection.connect`` called twice
    replaces the socket, silently abandoning the first. One flag is cheaper than
    that class of bug.
    """


def _fault_of(fault: BaseException, *, before_send: bool) -> TransportFailureKind:
    """Place a standard-library exception in GLOBIN's own vocabulary.

    Args:
        fault: What was raised.
        before_send: Whether it happened before any byte could have left.

    Returns:
        The kind.

    Total by construction: an exception this mapping does not recognise becomes
    :attr:`~globin.domain.rest.TransportFailureKind.UNCLASSIFIED` rather than
    escaping. A library exception reaching an application layer is the leak
    ``ENGINEERING_CONTRACT.md`` forbids, and *"we did not anticipate this one"* is a
    reportable state rather than a reason to stop reporting.

    Order matters and is not alphabetical. ``socket.gaierror``,
    ``ssl.SSLError``, ``TimeoutError``, ``ConnectionRefusedError`` and
    ``ConnectionResetError`` are all subclasses of ``OSError``, so the general case
    is checked last or it would swallow every specific one.
    """
    if isinstance(fault, socket.gaierror):
        return TransportFailureKind.DNS_FAILURE
    if isinstance(fault, ssl.SSLError):
        return TransportFailureKind.TLS_FAILURE
    if isinstance(fault, TimeoutError):
        return (
            TransportFailureKind.TIMEOUT_BEFORE_SEND
            if before_send
            else TransportFailureKind.TIMEOUT_AFTER_SEND
        )
    if isinstance(fault, ConnectionRefusedError):
        return TransportFailureKind.CONNECTION_REFUSED
    if isinstance(fault, ConnectionResetError):
        return TransportFailureKind.CONNECTION_RESET
    if isinstance(fault, http.client.HTTPException):
        return TransportFailureKind.MALFORMED_RESPONSE
    if isinstance(fault, OSError):
        return TransportFailureKind.CONNECTION_RESET
    return TransportFailureKind.UNCLASSIFIED


def _rate_limits(headers: dict[str, str]) -> RateLimitReport:
    """Pull the limit headers out of the response, typed rather than left as text.

    Args:
        headers: Every response header, with lowercase names.

    Returns:
        The report. Absent headers produce empty fields, never zeroes — a venue that
        said nothing about weight is not a venue that said the weight was zero.

    The interval is part of the header *name* in Binance's documented spelling
    (``X-MBX-USED-WEIGHT-(intervalNum)(intervalLetter)``), so the suffix becomes the
    key. A fixed set of fields would have had to guess which intervals exist.
    """
    used: list[tuple[str, int]] = []
    orders: list[tuple[str, int]] = []
    retry: int | None = None
    for name, value in headers.items():
        if name == RETRY_AFTER_HEADER.lower():
            retry = int(value) if value.strip().isdigit() else None
        elif name.startswith(USED_WEIGHT_PREFIX.lower()) and value.strip().lstrip("-").isdigit():
            used.append((name[len(USED_WEIGHT_PREFIX) :].upper(), int(value)))
        elif name.startswith(ORDER_COUNT_PREFIX.lower()) and value.strip().lstrip("-").isdigit():
            orders.append((name[len(ORDER_COUNT_PREFIX) :].upper(), int(value)))
    return RateLimitReport(
        retry_after_seconds=retry,
        used_weight=tuple(sorted(used)),
        order_count=tuple(sorted(orders)),
    )


def _shape_and_payload(
    body: bytes, content_type: str, requested: ResponseEncoding
) -> tuple[BodyShape, object, SbeEnvelope | None]:
    """Decide what arrived, before anything tries to use it.

    Args:
        body: The bytes read from the response.
        content_type: The response's media type, lowercased and without parameters.
        requested: What GLOBIN asked for.

    Returns:
        The shape, the decoded payload when there is one, and the opaque envelope
        when the body is binary.

    **A binary body never reaches the JSON parser**, which is the guarantee this
    function exists for. When SBE was requested, a *JSON* content type is treated as
    a mismatch rather than a convenience: Binance documents that offering both media
    types makes an unsupported schema fall back to JSON, GLOBIN offers only one
    precisely so that cannot happen, and JSON arriving anyway means something
    negotiated behind GLOBIN's back.
    """
    if not body:
        return BodyShape.EMPTY, None, None
    if requested is ResponseEncoding.SBE:
        if content_type in JSON_MEDIA_TYPES:
            return BodyShape.UNEXPECTED_CONTENT_TYPE, None, None
        return BodyShape.BINARY, None, SbeEnvelope(payload=body)
    if content_type == MEDIA_TYPE_SBE:
        return BodyShape.BINARY, None, SbeEnvelope(payload=body)
    if content_type == MEDIA_TYPE_HTML:
        return BodyShape.HTML, None, None
    if content_type not in JSON_MEDIA_TYPES:
        if content_type.startswith(MEDIA_TYPE_TEXT_PREFIX):
            return BodyShape.TEXT, None, None
        return BodyShape.UNEXPECTED_CONTENT_TYPE, None, None
    try:
        decoded = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return BodyShape.MALFORMED_JSON, None, None
    if isinstance(decoded, dict):
        return BodyShape.OBJECT, decoded, None
    if isinstance(decoded, list):
        return BodyShape.ARRAY, decoded, None
    return BodyShape.SCALAR, decoded, None


def _fault_in(payload: object) -> ExchangeFault | None:
    """The venue's own refusal, if the payload carries one.

    Args:
        payload: The decoded body.

    Returns:
        The fault, or ``None``.

    A payload carrying ``{"code": ..., "msg": ...}`` is the venue answering, not the
    transport failing. Keeping the two apart is the distinction
    :class:`~globin.errors.ExchangeError` and :class:`~globin.errors.TransportError`
    were created for in Phase 005, whose docstrings both say *"Phases 033-048
    introduce the callers"*.
    """
    if not isinstance(payload, dict):
        return None
    code = payload.get(EXCHANGE_CODE_KEY)
    if not isinstance(code, int) or isinstance(code, bool) or code == NO_EXCHANGE_CODE:
        return None
    message = payload.get(EXCHANGE_MESSAGE_KEY)
    return ExchangeFault(code=code, message=message if isinstance(message, str) else "")


class HttpRestTransport:
    """A pooled, bounded, verifying REST client bound to exactly one environment.

    Raises:
        ValidationError: On a non-positive pool bound at construction.

    **Bound to one environment at construction**, and :meth:`send` refuses a
    resolution from another. A single transport shared between testnet and
    production would be one mistaken argument away from sending a live order to the
    wrong place, so the binding is a field rather than a convention — and the
    refusal names both environments so the mistake is legible.

    Not a singleton, not global, and not lazily opened. The composition root builds
    one and closes it; ``tests`` assert that closing leaves nothing behind.
    """

    __slots__ = (
        "_open",
        "_pool",
        "clock",
        "connect",
        "environment",
        "keepalive_nanoseconds",
        "max_uses",
        "pool_size",
    )

    def __init__(
        self,
        *,
        environment: str,
        clock: MonotonicClock,
        pool_size: int = DEFAULT_POOL_SIZE,
        max_uses: int = DEFAULT_MAX_USES,
        keepalive_nanoseconds: int = DEFAULT_KEEPALIVE_NANOSECONDS,
        connect: ConnectionFactory = https_connection,
    ) -> None:
        """Build a transport bound to one environment.

        Args:
            environment: Which environment this transport may talk to, and only this.
            clock: How elapsed time is read. Injected because ``adapters`` may not
                import ``adapters`` and because a test needs a clock it controls.
            pool_size: How many connections may be held at once.
            max_uses: How many requests one connection may carry.
            keepalive_nanoseconds: How long an idle connection stays useful.
            connect: How a connection is made. Defaults to the verifying one.

        Raises:
            ValidationError: On a non-positive bound, or an empty environment.

        **A plain class rather than a dataclass**, and the reason is the layer
        contract rather than taste: a pool is a mutable ``dict``, a dataclass needs
        ``field(default_factory=dict)`` to hold one, and
        ``test_layer_modules_execute_no_work_when_imported`` bans every call in a
        class body. Assigning inside ``__init__`` puts the call in a function body,
        where it belongs — this object has a lifecycle and a constructor is the
        honest way to say so.
        """
        bounds: tuple[tuple[str, object], ...] = (
            ("pool_size", pool_size),
            ("max_uses", max_uses),
            ("keepalive_nanoseconds", keepalive_nanoseconds),
        )
        for name, value in bounds:
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                msg = f"{name} must be a positive integer, and is {value!r}"
                raise ValidationError(msg)
        if not environment:
            msg = "a transport must be bound to an environment"
            raise ValidationError(msg)
        self.environment = environment
        self.clock = clock
        self.pool_size = pool_size
        self.max_uses = max_uses
        self.keepalive_nanoseconds = keepalive_nanoseconds
        self.connect = connect
        self._pool: dict[tuple[str, int], list[_Pooled]] = {}
        self._open = False

    def open(self) -> None:
        """Make the transport ready to send. Idempotent."""
        self._open = True

    def close(self) -> None:
        """Close every connection this transport holds. Idempotent.

        After this returns the pool is empty and no socket is held, which is what
        the lifecycle tests assert rather than assume. Safe on a transport that was
        never opened, and safe to call twice.
        """
        for held in self._pool.values():
            for item in held:
                item.connection.close()
        self._pool.clear()
        self._open = False

    def __enter__(self) -> "HttpRestTransport":
        """Open on entry, so a caller cannot forget to."""
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        """Close on exit, whatever happened in between."""
        self.close()

    @property
    def held_connections(self) -> int:
        """How many connections the pool is holding.

        Returns:
            The count. Read by the lifecycle tests, which is the point: "no leaked
            sessions" is a number a test can assert rather than a claim.
        """
        return sum(len(held) for held in self._pool.values())

    def send(self, resolution: EndpointResolution, request: RestRequest) -> RestExchange:
        """Send one request to an already-chosen endpoint and report what happened.

        Args:
            resolution: Where to send it. Never raises on a refusal.
            request: What to send.

        Returns:
            The exchange, whatever its outcome. See
            :mod:`globin.ports.rest` on why a network condition is returned rather
            than raised.

        Raises:
            ValidationError: Only for a fault in GLOBIN — a transport that was never
                opened, or a request that could not be constructed.

        Three refusals happen before any socket is touched, in this order: the
        resolution was itself a refusal; the resolution names an environment this
        transport is not bound to; the transport is not open.
        """
        if not resolution.permitted or resolution.endpoint is None:
            return self._refused(
                resolution,
                request,
                f"the endpoint resolution reports {resolution.outcome.value}: {resolution.detail}",
            )
        endpoint = resolution.endpoint
        if endpoint.environment != self.environment:
            return self._refused(
                resolution,
                request,
                (
                    f"this transport is bound to {self.environment!r} and the resolution "
                    f"names {endpoint.environment!r}; a transport is never shared between "
                    "environments"
                ),
            )
        if not self._open:
            msg = "a request was given to a transport that was never opened"
            raise ValidationError(msg)
        return self._exchange(resolution, request, endpoint)

    def _refused(
        self, resolution: EndpointResolution, request: RestRequest, detail: str
    ) -> RestExchange:
        """Build the exchange for a request GLOBIN declined to send.

        Args:
            resolution: What was asked for.
            request: What would have been sent.
            detail: Why it was not.

        Returns:
            An exchange whose send state is
            :attr:`~globin.domain.rest.SendState.REFUSED` and which touched no socket.
        """
        endpoint = resolution.endpoint
        diagnostics = RestDiagnosticsRecord(
            correlation_id=request.correlation_id or "unset",
            operation=request.operation,
            family=resolution.requested_family,
            environment=resolution.requested_environment,
            role=endpoint.role.value if endpoint else "",
            host=endpoint.host if endpoint else "",
            method=request.method.value,
            intent=request.intent.value,
            side_effect=request.side_effect.value,
            encoding=request.encoding.value,
            time_unit=request.time_unit.value,
            send_state=SendState.REFUSED.value,
            outcome=RequestOutcome.REJECTED_BEFORE_SEND.value,
        )
        return RestExchange(
            operation=request.operation,
            outcome=RequestOutcome.REJECTED_BEFORE_SEND,
            send_state=SendState.REFUSED,
            diagnostics=diagnostics,
            detail=detail,
        )

    def _exchange(
        self, resolution: EndpointResolution, request: RestRequest, endpoint: ResolvedEndpoint
    ) -> RestExchange:
        """Perform one request against one endpoint, tracking how far it got.

        Args:
            resolution: What was asked for.
            request: What to send.
            endpoint: Where to send it.

        Returns:
            The exchange.
        """
        started = self.clock.reading()
        target = request.canonical_target(endpoint.path_prefix)
        headers = dict(negotiation_headers(request))
        body = request.body.content if request.body else None
        state = SendState.NOT_SENT
        pooled: _Pooled | None = None
        try:
            pooled = self._acquire(endpoint, request.timeout_policy.effective_seconds)
            if not pooled.connected:
                pooled.connection.connect()
                pooled.connected = True
            # From here the socket is up and the next call writes. A failure after
            # this line cannot be proved to have left the bytes in this process, so
            # the state advances BEFORE the write rather than after it. Advancing
            # afterwards would report a half-written order as `NOT_SENT`, which is
            # the one direction this model must never be wrong in.
            state = SendState.SENT
            pooled.connection.request(request.method.value, target, body=body, headers=headers)
            answer = pooled.connection.getresponse()
            payload = answer.read(MAX_RESPONSE_BYTES + 1)
            status = answer.status
            content_type = answer.headers.get_content_type().lower()
            reply_headers = {name.lower(): value for name, value in answer.headers.items()}
            reusable = not answer.will_close
        except (OSError, http.client.HTTPException) as fault:
            self._discard(endpoint, pooled)
            return self._failed(
                resolution,
                request,
                endpoint,
                started,
                state,
                fault,
                before_send=state is SendState.NOT_SENT,
            )
        if len(payload) > MAX_RESPONSE_BYTES:
            self._discard(endpoint, pooled)
            return self._failed(
                resolution,
                request,
                endpoint,
                started,
                SendState.SENT,
                None,
                kind=TransportFailureKind.RESPONSE_TOO_LARGE,
                detail=(
                    f"the response exceeds {MAX_RESPONSE_BYTES} bytes; a truncated body that "
                    "happened to parse would be worse than no body at all"
                ),
            )
        self._release(endpoint, pooled, reusable=reusable)
        return self._completed(
            resolution,
            request,
            endpoint,
            started,
            status=status,
            body=payload,
            content_type=content_type,
            headers=reply_headers,
        )

    def _acquire(self, endpoint: ResolvedEndpoint, timeout: float) -> _Pooled:
        """A connection for one endpoint, reused when one is still good.

        Args:
            endpoint: Where the request is going.
            timeout: How long any one socket operation may take.

        Returns:
            A pooled connection, either taken from the pool or newly made. A newly
            made one is **not yet connected**: the caller connects it as a separate
            step so that a connection failure is distinguishable from a send
            failure, which is what :class:`~globin.domain.rest.SendState` turns on.

        A held connection is reused only while it is under both bounds — uses and
        age. Anything else is closed here rather than discovered to be dead on the
        next write.
        """
        key = (endpoint.host, endpoint.port)
        held = self._pool.setdefault(key, [])
        now = self.clock.reading()
        while held:
            candidate = held.pop()
            fresh = now.since(candidate.opened).nanoseconds < self.keepalive_nanoseconds
            if fresh and candidate.uses < self.max_uses:
                candidate.uses += 1
                return candidate
            candidate.connection.close()
        connection = self.connect(endpoint.host, endpoint.port, timeout)
        return _Pooled(connection=connection, opened=now, uses=1)

    def _release(
        self, endpoint: ResolvedEndpoint, pooled: _Pooled | None, *, reusable: bool
    ) -> None:
        """Put a connection back, or close it.

        Args:
            endpoint: Where it goes.
            pooled: The connection, or ``None`` when none was acquired.
            reusable: Whether the response said the connection survives.
        """
        if pooled is None:
            return
        key = (endpoint.host, endpoint.port)
        held = self._pool.setdefault(key, [])
        if reusable and pooled.uses < self.max_uses and self.held_connections < self.pool_size:
            held.append(pooled)
            return
        pooled.connection.close()

    def _discard(self, endpoint: ResolvedEndpoint, pooled: _Pooled | None) -> None:
        """Close a connection that must not be reused.

        Args:
            endpoint: Where it was going.
            pooled: The connection, or ``None``.

        Called on every failure path. A connection that raised, or whose body was
        left unread because it exceeded the cap, has undefined bytes still in it —
        returning it to the pool would corrupt the *next* request rather than this
        one, which is the hardest possible bug to trace back here.
        """
        del endpoint
        if pooled is not None:
            pooled.connection.close()

    def _failed(
        self,
        resolution: EndpointResolution,
        request: RestRequest,
        endpoint: ResolvedEndpoint,
        started: MonotonicReading,
        state: SendState,
        fault: BaseException | None,
        *,
        before_send: bool = True,
        kind: TransportFailureKind | None = None,
        detail: str = "",
    ) -> RestExchange:
        """Build the exchange for a request that produced no usable answer.

        Args:
            resolution: What was asked for.
            request: What was sent.
            endpoint: Where it went.
            started: When the attempt began.
            state: How far it got.
            fault: What was raised, when something was.
            before_send: Whether the fault preceded any byte leaving.
            kind: An explicit failure kind, when there was no exception.
            detail: An explicit message, when there was no exception.

        Returns:
            The exchange, whose outcome is
            :attr:`~globin.domain.rest.RequestOutcome.UNKNOWN` for anything with
            something at stake.
        """
        resolved_kind = kind or _fault_of(fault or OSError("no exception"), before_send=before_send)
        elapsed = self.clock.reading().since(started).nanoseconds
        outcome = classify(
            RestOutcomeInputs(
                side_effect=request.side_effect,
                send_state=state,
                answer_understood=False,
            )
        )
        message = detail or f"{resolved_kind.value}: {type(fault).__name__}"
        diagnostics = self._record(
            resolution,
            request,
            endpoint,
            state=state,
            outcome=outcome,
            elapsed=elapsed,
            failure=resolved_kind.value,
        )
        return RestExchange(
            operation=request.operation,
            outcome=outcome,
            send_state=state,
            diagnostics=diagnostics,
            failure=resolved_kind,
            detail=message,
        )

    def _completed(
        self,
        resolution: EndpointResolution,
        request: RestRequest,
        endpoint: ResolvedEndpoint,
        started: MonotonicReading,
        *,
        status: int,
        body: bytes,
        content_type: str,
        headers: dict[str, str],
    ) -> RestExchange:
        """Build the exchange for a request that got a complete HTTP answer.

        Args:
            resolution: What was asked for.
            request: What was sent.
            endpoint: Where it went.
            started: When the attempt began.
            status: The HTTP status.
            body: The bytes read.
            content_type: The response's media type.
            headers: Every response header, with lowercase names.

        Returns:
            The exchange.
        """
        elapsed = self.clock.reading().since(started).nanoseconds
        shape, payload, envelope = _shape_and_payload(body, content_type, request.encoding)
        fault = _fault_in(payload)
        understood = shape not in {
            BodyShape.MALFORMED_JSON,
            BodyShape.HTML,
            BodyShape.TEXT,
            BodyShape.UNEXPECTED_CONTENT_TYPE,
        }
        outcome = classify(
            RestOutcomeInputs(
                side_effect=request.side_effect,
                send_state=SendState.COMPLETED,
                status=status,
                exchange_code=fault.code if fault else NO_EXCHANGE_CODE,
                answer_understood=understood,
            )
        )
        limits = _rate_limits(headers)
        response = RestResponse(
            status=status,
            shape=shape,
            outcome=outcome,
            payload=payload,
            binary=envelope,
            fault=fault,
            rate_limits=limits,
            timing=RestTiming(elapsed_nanoseconds=elapsed),
            encoding=request.encoding,
            content_type=content_type,
        )
        diagnostics = self._record(
            resolution,
            request,
            endpoint,
            state=SendState.COMPLETED,
            outcome=outcome,
            elapsed=elapsed,
            status=status,
            exchange_code=fault.code if fault else NO_EXCHANGE_CODE,
            response_bytes=len(body),
            limits=limits,
        )
        return RestExchange(
            operation=request.operation,
            outcome=outcome,
            send_state=SendState.COMPLETED,
            diagnostics=diagnostics,
            response=response,
        )

    def _record(
        self,
        resolution: EndpointResolution,
        request: RestRequest,
        endpoint: ResolvedEndpoint,
        *,
        state: SendState,
        outcome: RequestOutcome,
        elapsed: int,
        status: int = NO_STATUS,
        exchange_code: int = NO_EXCHANGE_CODE,
        failure: str = "",
        response_bytes: int = 0,
        limits: RateLimitReport | None = None,
    ) -> RestDiagnosticsRecord:
        """Build the one diagnostic record this exchange may safely publish.

        Args:
            resolution: What was asked for.
            request: What was sent.
            endpoint: Where it went.
            state: How far it got.
            outcome: What it means.
            elapsed: How long it took, in nanoseconds.
            status: The HTTP status, when there was one.
            exchange_code: The venue's code, when there was one.
            failure: The transport failure, when there was one.
            response_bytes: How large the answer was.
            limits: What the venue said about consumption.

        Returns:
            The record.

        **No URL, no query string, no header value and no body reaches this.** The
        fields are GLOBIN's own vocabulary and numbers, plus the resolved host —
        which is a hostname rather than a target, so it cannot carry a credential.
        Redaction downstream is a second line of defence over a record that already
        carries nothing to redact.
        """
        return RestDiagnosticsRecord(
            correlation_id=request.correlation_id or "unset",
            operation=request.operation,
            family=resolution.requested_family,
            environment=resolution.requested_environment,
            role=endpoint.role.value,
            host=endpoint.host,
            method=request.method.value,
            intent=request.intent.value,
            side_effect=request.side_effect.value,
            encoding=request.encoding.value,
            time_unit=request.time_unit.value,
            send_state=state.value,
            outcome=outcome.value,
            status=status,
            exchange_code=exchange_code,
            failure=failure,
            response_bytes=response_bytes,
            elapsed_nanoseconds=elapsed,
            rate_limits=limits or RateLimitReport(),
        )


__all__ = [
    "DEFAULT_KEEPALIVE_NANOSECONDS",
    "DEFAULT_MAX_USES",
    "DEFAULT_POOL_SIZE",
    "ConnectionFactory",
    "HttpRestTransport",
    "https_connection",
    "secure_context",
]
