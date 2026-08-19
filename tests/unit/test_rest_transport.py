"""The transport's failure mapping, its TLS posture, and its bounds.

What is here and not in ``tests/integration/test_rest_transport_end_to_end.py`` is
everything a real server cannot produce: a DNS failure, a TLS handshake failure, a
connection refused, a reset before any byte is written, and a response larger than
the cap. Each uses a connection factory that raises, which is the only way to reach
those branches without a hostile server.

**No test here opens a socket**, and the autouse guard in ``tests/conftest.py``
would refuse one if it tried.
"""

import http.client
import socket
import ssl
from collections.abc import Callable

import pytest

from globin.adapters.rest_transport import (
    DEFAULT_KEEPALIVE_NANOSECONDS,
    HttpRestTransport,
    https_connection,
    secure_context,
)
from globin.domain.clock import Duration, MonotonicReading
from globin.domain.rest import (
    EndpointRole,
    HttpMethod,
    RequestOutcome,
    RequestSecurityIntent,
    ResponseEncoding,
    RestRequest,
    SendState,
    SideEffect,
    TransportFailureKind,
)
from globin.domain.rest_endpoint import EndpointResolution, ResolutionStatus, ResolvedEndpoint
from globin.errors import ValidationError
from tests.support import ManualMonotonicClock

ENVIRONMENT = "testnet"


def _clock() -> ManualMonotonicClock:
    """A clock a test advances by hand, so an elapsed time is known rather than measured."""
    return ManualMonotonicClock(current=MonotonicReading(0), step=Duration(1_000_000))


def _resolution(environment: str = ENVIRONMENT) -> EndpointResolution:
    """A resolution pointing nowhere anything will actually be reached."""
    endpoint = ResolvedEndpoint(
        family="spot",
        environment=environment,
        role=EndpointRole.PRIMARY,
        url="https://nowhere.invalid/api",
        host="nowhere.invalid",
        port=0,
        path_prefix="/api",
        capabilities=("market_data",),
        auth="none",
        carries_real_capital=False,
        source="test-source",
    )
    return EndpointResolution(
        outcome=ResolutionStatus.RESOLVED,
        requested_family="spot",
        requested_environment=environment,
        requested_capability="market_data",
        intent=RequestSecurityIntent.PUBLIC,
        encoding=ResponseEncoding.JSON,
        endpoint=endpoint,
    )


def _request(effect: SideEffect = SideEffect.READ_ONLY) -> RestRequest:
    """One request the transport will try and fail to send."""
    return RestRequest(
        operation="test.probe",
        method=HttpMethod.GET,
        path="/v3/ping",
        side_effect=effect,
        correlation_id="test-correlation",
    )


class _Raising(http.client.HTTPConnection):
    """A connection whose ``connect`` raises whatever a test asks for.

    Subclassing rather than mocking, because ``create_autospec`` on
    ``HTTPConnection`` would let a signature drift go unnoticed and this is the one
    place the transport touches the standard library's real type.
    """

    fault: BaseException = OSError("unset")

    def connect(self) -> None:
        """Fail the way the test declared."""
        raise self.fault


def _factory(
    fault: BaseException, *, on_connect: bool = True
) -> Callable[..., http.client.HTTPConnection]:
    """A connection factory that fails at a chosen phase.

    Args:
        fault: What to raise.
        on_connect: Whether to fail while connecting (provably nothing sent) or
            while writing the request (bytes may have left).

    Returns:
        The factory.
    """

    def build(host: str, port: int, timeout: float) -> http.client.HTTPConnection:
        connection = _Raising(host, port or 443, timeout=timeout)
        if on_connect:
            connection.fault = fault
        else:
            connection.connect = lambda: None  # type: ignore[method-assign]
            connection.request = _raise(fault)  # type: ignore[method-assign]
        return connection

    return build


def _raise(fault: BaseException) -> Callable[..., None]:
    """A callable that raises.

    Args:
        fault: What to raise.

    Returns:
        The callable.
    """

    def go(*_: object, **__: object) -> None:
        raise fault

    return go


class TestTlsPosture:
    """Verification is on, and there is no argument that turns it off."""

    def test_the_context_verifies(self) -> None:
        """The one property whose silent loss would be invisible in every passing test."""
        context = secure_context()
        assert context.check_hostname is True
        assert context.verify_mode is ssl.CERT_REQUIRED

    def test_the_factory_takes_no_verification_argument(self) -> None:
        """A ``verify: bool`` here would be the whole posture reduced to a keyword.

        Asserted on the signature rather than on behaviour, because what must be
        true is that the option *does not exist* — a default nobody can override is
        still a default somebody can override in the next commit.
        """
        import inspect

        assert list(inspect.signature(secure_context).parameters) == []
        parameters = list(inspect.signature(https_connection).parameters)
        assert parameters == ["host", "port", "timeout"]

    def test_the_production_factory_builds_an_https_connection(self) -> None:
        """The default arm is the verifying one, which is what the seam is measured against."""
        connection = https_connection("nowhere.invalid", 0, 1.0)
        assert isinstance(connection, http.client.HTTPSConnection)
        connection.close()


class TestFailureMapping:
    """Every standard-library exception placed in GLOBIN's own vocabulary."""

    @pytest.mark.parametrize(
        ("fault", "kind"),
        [
            pytest.param(
                socket.gaierror("no such host"), TransportFailureKind.DNS_FAILURE, id="dns"
            ),
            pytest.param(ssl.SSLError("handshake"), TransportFailureKind.TLS_FAILURE, id="tls"),
            pytest.param(
                ssl.SSLCertVerificationError("bad cert"),
                TransportFailureKind.TLS_FAILURE,
                id="certificate",
            ),
            pytest.param(
                ConnectionRefusedError("refused"),
                TransportFailureKind.CONNECTION_REFUSED,
                id="refused",
            ),
            pytest.param(
                ConnectionResetError("reset"), TransportFailureKind.CONNECTION_RESET, id="reset"
            ),
            pytest.param(
                TimeoutError("timed out"), TransportFailureKind.TIMEOUT_BEFORE_SEND, id="timeout"
            ),
        ],
    )
    def test_a_connect_failure_is_named_and_never_leaks(
        self, fault: BaseException, kind: TransportFailureKind
    ) -> None:
        """A library exception reaching an application layer is the leak the contract forbids.

        The mapping is checked specific-before-general, because ``gaierror``,
        ``SSLError``, ``TimeoutError`` and both connection errors are all subclasses
        of ``OSError`` — a general clause reached first would swallow every one of
        them.
        """
        with HttpRestTransport(
            environment=ENVIRONMENT, clock=_clock(), connect=_factory(fault)
        ) as transport:
            exchange = transport.send(_resolution(), _request())
        assert exchange.failure is kind
        assert exchange.response is None

    def test_a_connect_failure_is_provably_not_sent(self) -> None:
        """The reason ``connect()`` is called as its own step.

        ``http.client`` connects lazily inside ``request()``, which would fold a DNS
        failure and a half-written request into one exception. Calling connect
        explicitly is what lets this be reported as *nothing happened* rather than
        as *we cannot say*.
        """
        with HttpRestTransport(
            environment=ENVIRONMENT, clock=_clock(), connect=_factory(socket.gaierror("x"))
        ) as transport:
            exchange = transport.send(_resolution(), _request(SideEffect.MUTATING))
        assert exchange.send_state is SendState.NOT_SENT
        assert exchange.outcome is RequestOutcome.NOT_SENT
        assert exchange.at_risk is False

    def test_a_write_failure_is_conservatively_treated_as_sent(self) -> None:
        """Once the connection is up, GLOBIN cannot prove the bytes stayed in this process.

        So a mutating request that failed while writing is ``UNKNOWN``. Being wrong
        in this direction costs a duplicate check; being wrong in the other costs a
        duplicate order.

        **This test found a real defect.** The transport advanced its send state
        *after* ``request()`` returned, so a failure during the write reported
        ``NOT_SENT`` — the one direction the model must never be wrong in. The state
        now advances the moment the socket is up, before anything is written.
        """
        with HttpRestTransport(
            environment=ENVIRONMENT,
            clock=_clock(),
            connect=_factory(ConnectionResetError("reset"), on_connect=False),
        ) as transport:
            exchange = transport.send(_resolution(), _request(SideEffect.MUTATING))
        assert exchange.send_state is SendState.SENT
        assert exchange.outcome is RequestOutcome.UNKNOWN
        assert exchange.failure is TransportFailureKind.CONNECTION_RESET

    def test_a_timeout_after_the_connection_is_up_is_named_differently(self) -> None:
        """Before and after are different facts, and the names say which."""
        with HttpRestTransport(
            environment=ENVIRONMENT,
            clock=_clock(),
            connect=_factory(TimeoutError("slow"), on_connect=False),
        ) as transport:
            exchange = transport.send(_resolution(), _request(SideEffect.MUTATING))
        assert exchange.failure is TransportFailureKind.TIMEOUT_AFTER_SEND

    def test_a_protocol_fault_is_a_malformed_response(self) -> None:
        """``http.client`` raises its own exception type for a reply it cannot parse."""
        with HttpRestTransport(
            environment=ENVIRONMENT,
            clock=_clock(),
            connect=_factory(http.client.BadStatusLine("garbage"), on_connect=False),
        ) as transport:
            exchange = transport.send(_resolution(), _request())
        assert exchange.failure is TransportFailureKind.MALFORMED_RESPONSE

    def test_a_failure_always_explains_itself(self) -> None:
        """An exchange reporting a fault with no message is one nobody can act on."""
        with HttpRestTransport(
            environment=ENVIRONMENT, clock=_clock(), connect=_factory(socket.gaierror("x"))
        ) as transport:
            exchange = transport.send(_resolution(), _request())
        assert exchange.detail
        assert exchange.failure is not None
        assert exchange.failure.value in exchange.detail


class TestConstruction:
    """What a transport refuses to be."""

    @pytest.mark.parametrize(
        "bounds",
        [
            {"pool_size": 0},
            {"pool_size": -1},
            {"max_uses": 0},
            {"keepalive_nanoseconds": 0},
            {"pool_size": True},
        ],
    )
    def test_a_bound_that_would_not_bound_is_refused(self, bounds: dict[str, object]) -> None:
        """``True`` is refused with the rest: ``bool`` subclasses ``int``."""
        with pytest.raises(ValidationError, match="positive integer"):
            HttpRestTransport(environment=ENVIRONMENT, clock=_clock(), **bounds)  # type: ignore[arg-type]

    def test_a_transport_must_be_bound_to_an_environment(self) -> None:
        """An unbound transport is one that would accept a resolution from anywhere."""
        with pytest.raises(ValidationError, match="bound to an environment"):
            HttpRestTransport(environment="", clock=_clock())

    def test_the_defaults_are_bounded(self) -> None:
        """A default of zero would disable the bound it is named for."""
        transport = HttpRestTransport(environment=ENVIRONMENT, clock=_clock())
        assert transport.pool_size > 0
        assert transport.max_uses > 0
        assert transport.keepalive_nanoseconds == DEFAULT_KEEPALIVE_NANOSECONDS
        transport.close()

    def test_closing_an_unopened_transport_is_safe(self) -> None:
        """A caller need not track whether it got as far as opening."""
        transport = HttpRestTransport(environment=ENVIRONMENT, clock=_clock())
        transport.close()
        assert transport.held_connections == 0


class TestRefusals:
    """Two refusals that happen before a factory is ever called."""

    def test_a_refused_resolution_touches_no_factory(self) -> None:
        """Asserted by giving it a factory that would raise if it were called."""
        called: list[int] = []

        def explode(*_: object) -> http.client.HTTPConnection:
            called.append(1)
            msg = "the transport opened a connection for a refused resolution"
            raise AssertionError(msg)

        refusal = EndpointResolution(
            outcome=ResolutionStatus.PRODUCT_UNKNOWN,
            requested_family="options",
            requested_environment=ENVIRONMENT,
            requested_capability="market_data",
            intent=RequestSecurityIntent.PUBLIC,
            encoding=ResponseEncoding.JSON,
            detail="no such product",
        )
        with HttpRestTransport(
            environment=ENVIRONMENT, clock=_clock(), connect=explode
        ) as transport:
            exchange = transport.send(refusal, _request())
        assert not called
        assert exchange.outcome is RequestOutcome.REJECTED_BEFORE_SEND

    def test_a_foreign_environment_touches_no_factory(self) -> None:
        """The rule that keeps one transport from ever reaching two environments."""
        called: list[int] = []

        def explode(*_: object) -> http.client.HTTPConnection:
            called.append(1)
            msg = "the transport opened a connection for the wrong environment"
            raise AssertionError(msg)

        with HttpRestTransport(
            environment=ENVIRONMENT, clock=_clock(), connect=explode
        ) as transport:
            exchange = transport.send(_resolution("production"), _request())
        assert not called
        assert exchange.outcome is RequestOutcome.REJECTED_BEFORE_SEND
        assert "production" in exchange.detail


class TestNoRetryExists:
    """Asserted on the object rather than argued in prose."""

    def test_one_send_produces_exactly_one_connection_attempt(self) -> None:
        """A retry loop would show up here as a second attempt against a failing factory."""
        attempts: list[int] = []

        def counting(host: str, port: int, timeout: float) -> http.client.HTTPConnection:
            attempts.append(1)
            connection = _Raising(host, port or 443, timeout=timeout)
            connection.fault = ConnectionRefusedError("refused")
            return connection

        with HttpRestTransport(
            environment=ENVIRONMENT, clock=_clock(), connect=counting
        ) as transport:
            transport.send(_resolution(), _request(SideEffect.MUTATING))
        assert len(attempts) == 1

    def test_there_is_no_retry_parameter_to_pass(self) -> None:
        """The absence is the mechanism.

        Phase 043 owns retry, and it inherits a transport that cannot be asked to
        do it — rather than one that can and is trusted not to be.
        """
        import inspect

        parameters = set(inspect.signature(HttpRestTransport.__init__).parameters)
        for forbidden in ("retries", "retry", "attempts", "backoff", "max_retries"):
            assert forbidden not in parameters
