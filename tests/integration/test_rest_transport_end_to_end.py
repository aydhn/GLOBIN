"""The REST transport over a real loopback socket, from connect to close.

**Every test here carries ``loopback``**, and that marker narrows the autouse guard
in ``tests/conftest.py`` rather than lifting it: outbound connections to anything
that is not this machine still fail. A mistake here that reached Binance would be
caught, not permitted.

**Why a real server rather than a mock.** The whole status and body matrix — 200,
204, malformed JSON, a venue error payload, 403, 409, 418, 429 with ``Retry-After``,
500, 502, 503, a binary body — travels through the actual ``http.client`` code path:
the socket, the header parsing, the body framing, the keep-alive decision. A mocked
connection would prove that :func:`~globin.domain.rest.classify` was called with
whatever the mock was told to say, which is a much weaker claim than the one this
phase needs.

Three failures cannot be produced by a local server — a DNS failure, a TLS
handshake failure, and a reset before any byte is written — so those use a
connection factory that raises. They are in ``tests/unit/test_rest_transport.py``,
beside the rest of the failure mapping.
"""

import http.client
import http.server
import json
import threading
from collections.abc import Iterator
from typing import Final

import pytest

from globin.adapters.rest_transport import HttpRestTransport
from globin.domain.clock import Duration, MonotonicReading
from globin.domain.rest import (
    BodyShape,
    EndpointRole,
    HttpMethod,
    RequestOutcome,
    RequestSecurityIntent,
    ResponseEncoding,
    RestRequest,
    SbeSchemaReference,
    SendState,
    SideEffect,
)
from globin.domain.rest_endpoint import EndpointResolution, ResolutionStatus, ResolvedEndpoint
from tests.support import ManualMonotonicClock

pytestmark = pytest.mark.loopback

ENVIRONMENT: Final[str] = "testnet"
"""What the transport under test is bound to. Never ``production``."""

CASES: Final[dict[str, tuple[int, str, bytes]]] = {
    "/ok": (200, "application/json", b'{"serverTime":1700000000000}'),
    "/array": (200, "application/json", b"[1,2,3]"),
    "/scalar": (200, "application/json", b"42"),
    "/empty": (204, "application/json", b""),
    "/malformed": (200, "application/json", b"{not json"),
    "/venue-error": (400, "application/json", b'{"code":-1121,"msg":"Invalid symbol."}'),
    "/waf": (403, "text/html", b"<html><body>blocked</body></html>"),
    "/conflict": (409, "application/json", b'{"code":-2021,"msg":"partially failed"}'),
    "/banned": (418, "application/json", b'{"code":-1003,"msg":"IP banned"}'),
    "/limited": (429, "application/json", b'{"code":-1003,"msg":"too many requests"}'),
    "/internal": (500, "application/json", b'{"code":-1000,"msg":"internal"}'),
    "/gateway": (502, "text/plain", b"bad gateway"),
    "/unavailable": (
        503,
        "application/json",
        b'{"code":-1007,"msg":"Timeout waiting for response from backend server."}',
    ),
    "/binary": (200, "application/sbe", b"\x00\x01\x02\x03binary"),
    "/wrong-type": (200, "application/octet-stream", b"who knows"),
}
"""Every response a documented Binance REST surface can produce, served locally."""


class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves :data:`CASES` and the limit headers a real venue sends."""

    protocol_version = "HTTP/1.1"
    """Keep-alive, so the connection pool has something to reuse.

    The default is HTTP/1.0, under which every response closes its connection —
    which would make the pooling tests silently vacuous rather than failing.
    """

    def do_GET(self) -> None:
        """Answer one request from the table."""
        status, content_type, body = CASES.get(
            self.path, (404, "application/json", b'{"code":-1121,"msg":"unknown"}')
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-MBX-USED-WEIGHT-1M", "42")
        self.send_header("X-MBX-ORDER-COUNT-10S", "3")
        if status == 429:
            self.send_header("Retry-After", "17")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        """Silence. The standard library logs every request to stderr otherwise."""


def _plain(host: str, port: int, timeout: float) -> http.client.HTTPConnection:
    """A plaintext connection to a server this test started.

    Args:
        host: The loopback address.
        port: The port the server bound.
        timeout: How long a socket operation may take.

    Returns:
        The connection.

    **Substituting the whole factory is the seam, and there is no verification flag
    to set.** ``secure_context`` takes no arguments and
    :class:`~globin.domain.rest_endpoint.ResolvedEndpoint` refuses any URL that is
    not HTTPS, so nothing here opens a route to a plaintext *venue* endpoint — only
    to a server on this machine, over a connection this test made itself.
    """
    return http.client.HTTPConnection(host, port, timeout=timeout)


@pytest.fixture
def server() -> Iterator[int]:
    """A local HTTP server, and the port it bound.

    Yields:
        The port.

    Shut down and joined on the way out, so a test that leaked a thread fails the
    autouse process-state fixture rather than slowing every test after it.
    """
    listener = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=listener.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(listener.server_address[1])
    finally:
        listener.shutdown()
        listener.server_close()
        thread.join(timeout=5)


@pytest.fixture
def resolution(server: int) -> EndpointResolution:
    """A resolution pointing at the local server, filed under a non-production environment."""
    endpoint = ResolvedEndpoint(
        family="spot",
        environment=ENVIRONMENT,
        role=EndpointRole.PRIMARY,
        url=f"https://127.0.0.1:{server}",
        host="127.0.0.1",
        port=server,
        path_prefix="",
        capabilities=("market_data",),
        auth="none",
        carries_real_capital=False,
        source="test-source",
    )
    return EndpointResolution(
        outcome=ResolutionStatus.RESOLVED,
        requested_family="spot",
        requested_environment=ENVIRONMENT,
        requested_capability="market_data",
        intent=RequestSecurityIntent.PUBLIC,
        encoding=ResponseEncoding.JSON,
        endpoint=endpoint,
    )


@pytest.fixture
def transport() -> Iterator[HttpRestTransport]:
    """An open transport bound to the test environment, closed on the way out."""
    clock = ManualMonotonicClock(current=MonotonicReading(0), step=Duration(1_000_000))
    built = HttpRestTransport(environment=ENVIRONMENT, clock=clock, connect=_plain)
    built.open()
    try:
        yield built
    finally:
        built.close()


def _request(path: str, effect: SideEffect = SideEffect.READ_ONLY, **extra: object) -> RestRequest:
    """One request against the local server."""
    return RestRequest(
        operation="test.probe",
        method=HttpMethod.GET,
        path=path,
        side_effect=effect,
        correlation_id="test-correlation",
        **extra,  # type: ignore[arg-type]
    )


class TestBodyShapes:
    """Every body a documented surface can send, told apart before anything reads it."""

    @pytest.mark.parametrize(
        ("path", "shape"),
        [
            pytest.param("/ok", BodyShape.OBJECT, id="json-object"),
            pytest.param("/array", BodyShape.ARRAY, id="json-array"),
            pytest.param("/scalar", BodyShape.SCALAR, id="json-scalar"),
            pytest.param("/empty", BodyShape.EMPTY, id="no-content"),
            pytest.param("/malformed", BodyShape.MALFORMED_JSON, id="declared-json-and-is-not"),
            pytest.param("/waf", BodyShape.HTML, id="a-firewall-page"),
            pytest.param("/gateway", BodyShape.TEXT, id="an-intermediarys-text"),
            pytest.param("/binary", BodyShape.BINARY, id="binary-by-content-type"),
            pytest.param("/wrong-type", BodyShape.UNEXPECTED_CONTENT_TYPE, id="unplaceable"),
        ],
    )
    def test_the_shape_is_decided_before_the_body_is_used(
        self,
        transport: HttpRestTransport,
        resolution: EndpointResolution,
        path: str,
        shape: BodyShape,
    ) -> None:
        """Eight distinguishable cases, over a real socket.

        The two that matter most are the firewall's HTML and the binary payload:
        both arrive on an endpoint that answers JSON by default, and feeding either
        to a JSON parser produces an exception about column one of a document
        nobody meant to send.
        """
        exchange = transport.send(resolution, _request(path))
        assert exchange.response is not None
        assert exchange.response.shape is shape

    def test_a_binary_body_never_reaches_the_json_decoder(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """The guarantee the SBE half of this phase exists to provide.

        The payload arrives labelled binary, wrapped opaquely, with no decoded
        value — and GLOBIN has no decoder, which is Phase 047's question rather than
        this phase's.
        """
        exchange = transport.send(resolution, _request("/binary"))
        assert exchange.response is not None
        assert exchange.response.payload is None
        assert exchange.response.binary is not None
        assert exchange.response.binary.payload == b"\x00\x01\x02\x03binary"

    def test_a_decoded_object_is_available_to_a_caller(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """The happy path, so the refusals above are not the only thing proved."""
        exchange = transport.send(resolution, _request("/ok"))
        assert exchange.response is not None
        assert exchange.response.payload == {"serverTime": 1700000000000}


class TestOutcomeOverARealSocket:
    """The classification, driven by real responses rather than by constructed inputs."""

    @pytest.mark.parametrize(
        ("path", "read_outcome", "write_outcome"),
        [
            pytest.param(
                "/ok",
                RequestOutcome.SUCCESS_CONFIRMED,
                RequestOutcome.SUCCESS_CONFIRMED,
                id="200",
            ),
            pytest.param(
                "/empty",
                RequestOutcome.SUCCESS_CONFIRMED,
                RequestOutcome.SUCCESS_CONFIRMED,
                id="204",
            ),
            pytest.param(
                "/malformed",
                RequestOutcome.FAILURE_CONFIRMED,
                RequestOutcome.UNKNOWN,
                id="200-with-an-unreadable-body",
            ),
            pytest.param(
                "/venue-error",
                RequestOutcome.FAILURE_CONFIRMED,
                RequestOutcome.FAILURE_CONFIRMED,
                id="400-with-a-venue-code",
            ),
            pytest.param(
                "/waf",
                RequestOutcome.FAILURE_CONFIRMED,
                RequestOutcome.FAILURE_CONFIRMED,
                id="403-waf",
            ),
            pytest.param(
                "/conflict", RequestOutcome.FAILURE_CONFIRMED, RequestOutcome.UNKNOWN, id="409"
            ),
            pytest.param(
                "/banned",
                RequestOutcome.FAILURE_CONFIRMED,
                RequestOutcome.FAILURE_CONFIRMED,
                id="418",
            ),
            pytest.param(
                "/limited",
                RequestOutcome.FAILURE_CONFIRMED,
                RequestOutcome.FAILURE_CONFIRMED,
                id="429",
            ),
            pytest.param(
                "/internal", RequestOutcome.FAILURE_CONFIRMED, RequestOutcome.UNKNOWN, id="500"
            ),
            pytest.param(
                "/gateway", RequestOutcome.FAILURE_CONFIRMED, RequestOutcome.UNKNOWN, id="502"
            ),
            pytest.param(
                "/unavailable",
                RequestOutcome.FAILURE_CONFIRMED,
                RequestOutcome.UNKNOWN,
                id="503-with--1007",
            ),
        ],
    )
    def test_a_read_and_a_write_are_classified_differently(
        self,
        transport: HttpRestTransport,
        resolution: EndpointResolution,
        path: str,
        read_outcome: RequestOutcome,
        write_outcome: RequestOutcome,
    ) -> None:
        """The whole security property of the phase, over a real exchange.

        Read the ``409``, ``500``, ``502`` and ``503`` rows: the same response
        classifies as a confirmed failure for a query and as ``UNKNOWN`` for a
        write, because for a write the matching engine may have acted.
        """
        read = transport.send(resolution, _request(path, SideEffect.READ_ONLY))
        write = transport.send(resolution, _request(path, SideEffect.MUTATING))
        assert read.outcome is read_outcome
        assert write.outcome is write_outcome

    def test_at_risk_is_set_on_exactly_the_ambiguous_writes(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """The flag a future order engine reads before deciding anything."""
        ambiguous = transport.send(resolution, _request("/unavailable", SideEffect.MUTATING))
        confirmed = transport.send(resolution, _request("/limited", SideEffect.MUTATING))
        assert ambiguous.at_risk is True
        assert confirmed.at_risk is False

    def test_a_venue_error_is_not_a_transport_failure(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """The exchange completed and the venue refused; those are different facts.

        Collapsing them is how a system convinces itself an order failed when it
        did not, which is why ``globin.errors`` has carried both classes since
        Phase 005 waiting for this caller.
        """
        exchange = transport.send(resolution, _request("/venue-error"))
        assert exchange.failure is None
        assert exchange.response is not None
        assert exchange.response.fault is not None
        assert exchange.response.fault.code == -1121
        assert exchange.response.fault.message == "Invalid symbol."


class TestRateLimitExtraction:
    """The headers Phase 042 will need, typed rather than left in a raw map."""

    def test_used_weight_and_order_count_are_extracted_by_interval(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """The interval is part of the header name, so it becomes the key."""
        exchange = transport.send(resolution, _request("/ok"))
        assert exchange.response is not None
        limits = exchange.response.limits
        assert dict(limits.used_weight) == {"1M": 42}
        assert dict(limits.order_count) == {"10S": 3}

    def test_retry_after_is_read_and_not_obeyed(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """Observed only. A transport that slept on this would be an undeclared limiter."""
        exchange = transport.send(resolution, _request("/limited"))
        assert exchange.response is not None
        assert exchange.response.limits.retry_after_seconds == 17

    def test_an_absent_retry_after_is_absent_rather_than_zero(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """A venue that said nothing did not say to wait no time."""
        exchange = transport.send(resolution, _request("/ok"))
        assert exchange.response is not None
        assert exchange.response.limits.retry_after_seconds is None


class TestLifecycle:
    """Open, reuse, close — and nothing held afterwards."""

    def test_a_connection_is_reused_across_requests(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """Keep-alive, which is what the pool exists for."""
        for _ in range(5):
            transport.send(resolution, _request("/ok"))
        assert transport.held_connections == 1

    def test_the_pool_never_exceeds_its_bound(self, resolution: EndpointResolution) -> None:
        """A bound that is declared and then not enforced is worse than none."""
        clock = ManualMonotonicClock(current=MonotonicReading(0), step=Duration(1_000_000))
        with HttpRestTransport(
            environment=ENVIRONMENT, clock=clock, connect=_plain, pool_size=1
        ) as transport:
            for _ in range(4):
                transport.send(resolution, _request("/ok"))
            assert transport.held_connections <= 1

    def test_closing_leaves_nothing_held(self, resolution: EndpointResolution) -> None:
        """A leaked session is a number this can assert rather than a claim it repeats."""
        clock = ManualMonotonicClock(current=MonotonicReading(0), step=Duration(1_000_000))
        transport = HttpRestTransport(environment=ENVIRONMENT, clock=clock, connect=_plain)
        transport.open()
        transport.send(resolution, _request("/ok"))
        assert transport.held_connections == 1
        transport.close()
        assert transport.held_connections == 0

    def test_closing_twice_is_safe(self, resolution: EndpointResolution) -> None:
        """Idempotent, so a caller need not track the state in a second place."""
        clock = ManualMonotonicClock(current=MonotonicReading(0), step=Duration(1_000_000))
        transport = HttpRestTransport(environment=ENVIRONMENT, clock=clock, connect=_plain)
        transport.open()
        transport.send(resolution, _request("/ok"))
        transport.close()
        transport.close()
        assert transport.held_connections == 0

    def test_repeated_runs_are_identical(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """The same request twice produces the same record, timings aside."""
        first = transport.send(resolution, _request("/ok")).diagnostics.as_record()
        second = transport.send(resolution, _request("/ok")).diagnostics.as_record()
        first.pop("elapsed_nanoseconds")
        second.pop("elapsed_nanoseconds")
        assert first == second


class TestDiagnostics:
    """What a completed exchange is allowed to write down."""

    def test_the_record_carries_no_url_and_no_header_value(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """Safe by construction: there is no field for either."""
        exchange = transport.send(resolution, _request("/ok"))
        rendered = json.dumps(exchange.diagnostics.as_record())
        assert "127.0.0.1" in rendered
        assert "https://" not in rendered
        assert "User-Agent" not in rendered

    def test_a_credential_shaped_query_never_reaches_the_record(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """The redaction contract, driven end to end rather than asserted on a helper.

        The request carries parameters named exactly as a signed Binance request's
        are. Neither name's *value* may appear anywhere in the exchange's record.
        """
        from globin.domain.rest import QueryParameters

        request = RestRequest(
            operation="test.signed",
            method=HttpMethod.GET,
            path="/ok",
            query=QueryParameters(
                items=(
                    ("symbol", "BTCUSDT"),
                    (
                        "signature",
                        "3c6c1f4d9e2b8a7f0d5e4c3b2a1908f7e6d5c4b3a291807f6e5d4c3b2a190807",
                    ),
                    ("apiKey", "AAAABBBBCCCCDDDDEEEEFFFF00001111"),
                )
            ),
            correlation_id="test-correlation",
        )
        exchange = transport.send(resolution, request)
        rendered = json.dumps(exchange.as_record())
        assert "3c6c1f4d" not in rendered
        assert "AAAABBBB" not in rendered

    def test_the_correlation_id_propagates_from_request_to_record(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """One exchange, one identifier, tying every event about it together."""
        exchange = transport.send(resolution, _request("/ok"))
        assert exchange.diagnostics.correlation_id == "test-correlation"

    def test_the_record_states_how_far_the_request_got(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """The field the outcome model turns on."""
        exchange = transport.send(resolution, _request("/ok"))
        assert exchange.diagnostics.send_state == SendState.COMPLETED.value
        assert exchange.diagnostics.response_bytes > 0


class TestRefusalsBeforeAnySocket:
    """Three things the transport declines without opening anything."""

    def test_a_refused_resolution_is_never_sent(self, transport: HttpRestTransport) -> None:
        """The resolver's refusal survives into the exchange rather than being retried."""
        refusal = EndpointResolution(
            outcome=ResolutionStatus.SURFACE_UNDOCUMENTED,
            requested_family="options",
            requested_environment=ENVIRONMENT,
            requested_capability="market_data",
            intent=RequestSecurityIntent.PUBLIC,
            encoding=ResponseEncoding.JSON,
            detail="the REST surface for options is recorded as unknown",
        )
        exchange = transport.send(refusal, _request("/ok"))
        assert exchange.outcome is RequestOutcome.REJECTED_BEFORE_SEND
        assert exchange.send_state is SendState.REFUSED
        assert exchange.response is None

    def test_a_resolution_from_another_environment_is_refused(
        self, transport: HttpRestTransport, server: int
    ) -> None:
        """A transport shared between environments is one argument from a live order.

        The binding is a field rather than a convention, and the refusal names both
        environments so the mistake is legible rather than merely blocked.
        """
        endpoint = ResolvedEndpoint(
            family="spot",
            environment="production",
            role=EndpointRole.PRIMARY,
            url=f"https://127.0.0.1:{server}",
            host="127.0.0.1",
            port=server,
            path_prefix="",
            capabilities=("market_data",),
            auth="none",
            carries_real_capital=True,
            source="test-source",
        )
        elsewhere = EndpointResolution(
            outcome=ResolutionStatus.RESOLVED,
            requested_family="spot",
            requested_environment="production",
            requested_capability="market_data",
            intent=RequestSecurityIntent.PUBLIC,
            encoding=ResponseEncoding.JSON,
            endpoint=endpoint,
        )
        exchange = transport.send(elsewhere, _request("/ok"))
        assert exchange.outcome is RequestOutcome.REJECTED_BEFORE_SEND
        assert "production" in exchange.detail
        assert ENVIRONMENT in exchange.detail

    def test_an_unopened_transport_refuses_to_send(self, resolution: EndpointResolution) -> None:
        """A fault in GLOBIN, so this one raises rather than returning an outcome."""
        from globin.errors import ValidationError

        clock = ManualMonotonicClock(current=MonotonicReading(0), step=Duration(1_000_000))
        transport = HttpRestTransport(environment=ENVIRONMENT, clock=clock, connect=_plain)
        with pytest.raises(ValidationError, match="never opened"):
            transport.send(resolution, _request("/ok"))


class TestSbeNegotiationOverASocket:
    """The headers actually reach the wire, and a mismatch is refused."""

    def test_a_json_answer_to_an_sbe_request_is_a_content_type_mismatch(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """The fallback GLOBIN refuses to accept silently.

        The venue documents that offering both media types makes an unsupported
        schema fall back to JSON. GLOBIN offers one so that cannot happen — and if a
        JSON body arrives anyway, something negotiated behind its back, which is a
        mismatch rather than a convenience.
        """
        request = _request(
            "/ok",
            encoding=ResponseEncoding.SBE,
            schema_reference=SbeSchemaReference(identifier=3, version=5),
        )
        exchange = transport.send(resolution, request)
        assert exchange.response is not None
        assert exchange.response.shape is BodyShape.UNEXPECTED_CONTENT_TYPE
        assert exchange.response.payload is None

    def test_a_binary_answer_to_an_sbe_request_is_carried_opaquely(
        self, transport: HttpRestTransport, resolution: EndpointResolution
    ) -> None:
        """Accepted, wrapped, and not decoded — Phase 047 owns the decoder."""
        request = _request(
            "/binary",
            encoding=ResponseEncoding.SBE,
            schema_reference=SbeSchemaReference(identifier=3, version=5),
        )
        exchange = transport.send(resolution, request)
        assert exchange.response is not None
        assert exchange.response.shape is BodyShape.BINARY
        assert exchange.response.binary is not None
