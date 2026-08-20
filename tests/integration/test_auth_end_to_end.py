"""A signed request, driven through the real transport to a real socket.

**The claim this file exists to check cannot be checked offline.** Every other
test asserts that the signed span is a prefix of what
`RestRequest.canonical_target` renders — which is a comparison between two things
GLOBIN computes. This one captures the **raw request line the server received** and
compares the signed span against that, so nothing between the signer and the wire
can re-encode a parameter without failing.

`http.client` is the specific risk. It receives a target string and writes it
verbatim, and this test is what establishes that rather than assuming it. A client
that normalised a percent-escape, reordered a query or re-encoded a `+` would break
every signature GLOBIN produces and would break nothing else.

**No credential and no venue is involved.** The store is a double, the signer is
real, the server is on loopback, and the resolution is filed under a non-production
environment. The autouse offline fixture still permits this because the connection
is made to a server this test started.
"""

import http.client
import http.server
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final
from urllib.parse import unquote

import pytest

from globin.adapters.rest_transport import HttpRestTransport
from globin.adapters.signing import hmac_signer
from globin.application.auth import AuthPolicy, resolve_auth, sign_request
from globin.domain.api_reality import ApiKeyType
from globin.domain.auth import (
    SIGNATURE_PARAMETER,
    AuthStatus,
    CredentialBinding,
    SecurityType,
    SignatureAlgorithm,
)
from globin.domain.auth_timing import RecvWindow, TimestampUnit
from globin.domain.clock import Instant, MonotonicReading, instant
from globin.domain.environment_class import (
    EnvironmentClass,
    EnvironmentClassification,
)
from globin.domain.identifiers import EnvironmentId
from globin.domain.rest import (
    EndpointRole,
    HttpMethod,
    QueryParameters,
    RequestSecurityIntent,
    ResponseEncoding,
    SendState,
)
from globin.domain.rest_endpoint import (
    EndpointResolution,
    ResolutionStatus,
    ResolvedEndpoint,
)
from globin.domain.secrets import (
    SecretKind,
    SecretReference,
    SecretResolution,
    SecretSlot,
    SecretValue,
    StoreFault,
)
from tests.support import signing_timing

pytestmark = pytest.mark.loopback
"""Every test here opens a socket to a server it started on this machine.

`docs/TESTING_STRATEGY.md` requires the marker rather than inferring it from the
address, so that a test reaching a real remote cannot pass by pointing at
something that happens to resolve locally.
"""

ENVIRONMENT: Final[str] = "testnet"
"""Which environment the resolution is filed under. Never production."""

API_KEY: Final[str] = "an-api-key-identifier"
"""A key identifier this test invented. It authenticates nothing anywhere."""

SIGNING_SECRET: Final[str] = "a-signing-secret-this-test-made-up"  # noqa: S105 -- invented here
"""Material this test invented, which protects nothing."""

UNICODE_SYMBOL: Final[str] = "这是测试币456"
"""The Unicode symbol the venue added to its own testnet for exactly this purpose.

Recorded in the CHANGELOG on 2025-12-18: assets and a symbol were added to Spot
Testnet *"for testing endpoints/methods with a Unicode symbol"*. Using the venue's
own is better than inventing one, because it is a value a real request could carry.
"""

RECEIVED: list[str] = []
"""Every raw request line the server saw, in order.

A module-level list because `BaseHTTPRequestHandler` is instantiated per request by
the server and has nowhere else to put it. Cleared by the fixture, so two tests
cannot see each other's requests.
"""


class _CaptureHandler(http.server.BaseHTTPRequestHandler):
    """Records the raw path it received and answers with an empty JSON object."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        """Record the raw target and answer."""
        RECEIVED.append(self.path)
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        """Silence. The standard library logs every request to stderr otherwise."""


class _StubStore:
    """A store that answers two references and refuses everything else."""

    def health(self) -> StoreFault | None:
        """Always usable."""
        return None

    def resolve(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> SecretResolution:
        """Return the material for a known reference.

        Args:
            reference: What to resolve.
            slot: Ignored.

        Returns:
            The resolution.
        """
        del slot
        material = {"venue_key": API_KEY, "venue_secret": SIGNING_SECRET}.get(reference.name)
        if material is None:
            return SecretResolution(reference=reference, fault=StoreFault.ABSENT)
        return SecretResolution(reference=reference, value=SecretValue(material))

    def store(
        self, reference: SecretReference, value: SecretValue, slot: SecretSlot = SecretSlot.CURRENT
    ) -> StoreFault | None:
        """Refuse; nothing here writes."""
        del reference, value, slot
        return StoreFault.PROVIDER_READ_ONLY

    def delete(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> StoreFault | None:
        """Refuse; nothing here writes."""
        del reference, slot
        return StoreFault.PROVIDER_READ_ONLY

    def inventory(self) -> tuple[SecretReference, ...]:
        """Nothing is enumerated here."""
        return ()


class _FixedClock:
    """A monotonic clock the transport can read without a real one moving."""

    def __init__(self) -> None:
        """Start at zero."""
        self.value = 0

    def reading(self) -> MonotonicReading:
        """Advance by a millisecond and report.

        Returns:
            The reading.
        """
        self.value += 1_000_000
        return MonotonicReading(nanoseconds=self.value)


def _plain(host: str, port: int, timeout: float) -> http.client.HTTPConnection:
    """A plaintext connection to a server this test started.

    Args:
        host: The loopback address.
        port: The port the server bound.
        timeout: How long a socket operation may take.

    Returns:
        The connection.

    The whole factory is substituted, which is the only seam there is —
    `secure_context()` takes no arguments and `ResolvedEndpoint` refuses a
    non-HTTPS URL, so this opens no route to a plaintext venue endpoint.
    """
    return http.client.HTTPConnection(host, port, timeout=timeout)


@pytest.fixture
def server() -> Iterator[int]:
    """A local HTTP server that records what it receives.

    Yields:
        The port it bound.
    """
    RECEIVED.clear()
    listener = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
    thread = threading.Thread(target=listener.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(listener.server_address[1])
    finally:
        listener.shutdown()
        listener.server_close()
        thread.join(timeout=5)
        RECEIVED.clear()


@pytest.fixture
def resolution(server: int) -> EndpointResolution:
    """A resolution pointing at the local server, documenting all three key types."""
    endpoint = ResolvedEndpoint(
        family="spot",
        environment=ENVIRONMENT,
        role=EndpointRole.PRIMARY,
        url=f"https://127.0.0.1:{server}",
        host="127.0.0.1",
        port=server,
        path_prefix="/api",
        capabilities=("market_data", "trading", "account_data"),
        auth="signed",
        carries_real_capital=False,
        source="spot-rest",
        key_types=(ApiKeyType.HMAC, ApiKeyType.RSA, ApiKeyType.ED25519),
    )
    return EndpointResolution(
        outcome=ResolutionStatus.RESOLVED,
        requested_family="spot",
        requested_environment=ENVIRONMENT,
        requested_capability="account_data",
        intent=RequestSecurityIntent.SIGNED,
        encoding=ResponseEncoding.JSON,
        endpoint=endpoint,
    )


def _classification() -> EnvironmentClassification:
    """The classes this test needs."""
    return EnvironmentClassification(
        entries=(
            ("testnet", EnvironmentClass.VENUE_TESTNET),
            ("paper", EnvironmentClass.INTERNAL_SIMULATION),
        )
    )


def _credentials() -> dict[tuple[str, str], CredentialBinding]:
    """One HMAC credential enrolled for testnet."""
    return {
        ("spot", ENVIRONMENT): CredentialBinding(
            api_key=SecretReference(
                environment=EnvironmentId(ENVIRONMENT),
                kind=SecretKind.API_KEY,
                name="venue_key",
            ),
            material=SecretReference(
                environment=EnvironmentId(ENVIRONMENT),
                kind=SecretKind.API_SECRET,
                name="venue_secret",
            ),
            key_type=ApiKeyType.HMAC,
        )
    }


def _moment() -> Instant:
    """A fixed moment, so the timestamp in every assertion is the same one."""
    return instant(datetime(2017, 7, 12, 2, 41, 59, 559000, tzinfo=UTC))


def _send(
    resolution: EndpointResolution,
    parameters: QueryParameters,
    *,
    policy: AuthPolicy | None = None,
) -> tuple[str, str]:
    """Sign a request, send it, and report what was signed and what arrived.

    Args:
        resolution: Where to send it.
        parameters: What the caller asked for, without timing or signature.
        policy: What the operator configured.

    Returns:
        The signed span, and the raw request target the server received.
    """
    authorisation = resolve_auth(
        resolution,
        security_type=SecurityType.USER_DATA,
        policy=policy or AuthPolicy(),
        classification=_classification(),
        credentials=_credentials(),
        available=(SignatureAlgorithm.HMAC_SHA256,),
    )
    assert authorisation.permitted, authorisation.detail
    outcome = sign_request(
        authorisation,
        operation="spot.account",
        method=HttpMethod.GET,
        path="/v3/account",
        parameters=parameters,
        timing=signing_timing(
            _moment(),
            unit=(policy or AuthPolicy()).timestamp_unit,
            recv_window=(policy or AuthPolicy()).window,
        ),
        store=_StubStore(),
        signer=hmac_signer(),
        correlation_id="auth-end-to-end",
    )
    assert outcome.signed, outcome.detail
    assert outcome.request is not None
    with HttpRestTransport(
        environment=ENVIRONMENT, clock=_FixedClock(), connect=_plain
    ) as transport:
        exchange = transport.send(resolution, outcome.request.request)
    assert exchange.send_state is SendState.COMPLETED, exchange.detail
    assert RECEIVED, "the server received nothing"
    return outcome.request.signed_span, RECEIVED[-1]


# ---------------------------------------------------------------------------
# The invariant, against a socket
# ---------------------------------------------------------------------------


def test_the_bytes_signed_are_the_bytes_the_server_received(
    resolution: EndpointResolution,
) -> None:
    """The claim this file exists for, checked against what actually arrived."""
    signed, received = _send(resolution, QueryParameters(items=(("omitZeroBalances", True),)))
    _path, _, query = received.partition("?")
    assert query.startswith(f"{signed}&{SIGNATURE_PARAMETER}=")


def test_a_unicode_symbol_survives_the_whole_path(resolution: EndpointResolution) -> None:
    """The venue's own testnet Unicode symbol, signed and sent without re-encoding.

    This is the case the 2026-01-15 change is about. The symbol is percent-encoded
    before it is signed, and the percent-escapes reach the server unchanged — which
    is what makes the signature verifiable at the other end.
    """
    signed, received = _send(resolution, QueryParameters(items=(("symbol", UNICODE_SYMBOL),)))
    _path, _, query = received.partition("?")
    assert query.startswith(f"{signed}&{SIGNATURE_PARAMETER}=")
    assert "%E8%BF%99" in signed
    assert "%E8%BF%99" in query
    assert UNICODE_SYMBOL not in query
    assert unquote(query.split("&")[0].removeprefix("symbol=")) == UNICODE_SYMBOL


@pytest.mark.parametrize(
    ("name", "value"),
    [
        pytest.param("space", "a b c", id="space"),
        pytest.param("plus", "a+b", id="plus"),
        pytest.param("slash", "BTC/USDT", id="slash"),
        pytest.param("equals", "a=b", id="equals"),
        pytest.param("ampersand", "a&b", id="ampersand"),
        pytest.param("percent", "100%", id="percent"),
        pytest.param("tilde", "a~b", id="tilde"),
        pytest.param("empty", "", id="empty-string"),
    ],
)
def test_every_awkward_character_survives_the_whole_path(
    resolution: EndpointResolution, name: str, value: str
) -> None:
    """Each character that could be re-encoded, delimited or dropped in transit.

    `+` and space are the pair worth naming: GLOBIN renders a space as `%20` rather
    than `+`, so a client that helpfully converted one to the other would break the
    signature. `&` and `=` are the delimiters, which must arrive escaped or the
    venue would read one parameter as three.
    """
    signed, received = _send(resolution, QueryParameters(items=((name, value),)))
    _path, _, query = received.partition("?")
    assert query.startswith(f"{signed}&{SIGNATURE_PARAMETER}=")
    first = query.split("&")[0]
    assert unquote(first.removeprefix(f"{name}=")) == value


def test_a_decimal_keeps_its_scale_all_the_way_to_the_server(
    resolution: EndpointResolution,
) -> None:
    """A quantity the venue compares against a step size must not be normalised."""
    signed, received = _send(
        resolution, QueryParameters(items=(("quantity", Decimal("0.00010000")),))
    )
    assert "quantity=0.00010000" in signed
    assert "quantity=0.00010000" in received


def test_a_three_decimal_window_reaches_the_server_intact(
    resolution: EndpointResolution,
) -> None:
    """The venue's own `6000.346` example, through configuration and onto the wire."""
    policy = AuthPolicy(recv_window=RecvWindow(Decimal("6000.346")))
    signed, received = _send(resolution, QueryParameters(), policy=policy)
    assert "recvWindow=6000.346" in signed
    assert "recvWindow=6000.346" in received


def test_a_microsecond_timestamp_reaches_the_server(resolution: EndpointResolution) -> None:
    """Both documented units, exercised rather than only modelled."""
    policy = AuthPolicy(timestamp_unit=TimestampUnit.MICROSECONDS)
    signed, received = _send(resolution, QueryParameters(), policy=policy)
    assert "timestamp=1499827319559000" in signed
    assert "timestamp=1499827319559000" in received


def test_the_api_key_travels_in_a_header_and_never_in_the_query(
    resolution: EndpointResolution,
) -> None:
    """The key identifies and does not authenticate, so it is never part of the payload."""
    signed, received = _send(resolution, QueryParameters(items=(("symbol", "BTCUSDT"),)))
    assert API_KEY not in signed
    assert API_KEY not in received


def test_the_signing_secret_reaches_nothing(resolution: EndpointResolution) -> None:
    """The material is used to compute a signature and appears nowhere else."""
    signed, received = _send(resolution, QueryParameters(items=(("symbol", "BTCUSDT"),)))
    assert SIGNING_SECRET not in signed
    assert SIGNING_SECRET not in received


# ---------------------------------------------------------------------------
# What the transport records
# ---------------------------------------------------------------------------


def test_the_diagnostic_record_carries_neither_key_nor_signature(
    resolution: EndpointResolution,
) -> None:
    """Phase 034's record has no field for a URL or a header, and this confirms it holds.

    `RestDiagnosticsRecord` was written before any signature existed, so this is the
    first time it carries one — or rather, the first time it demonstrably does not.
    """
    authorisation = resolve_auth(
        resolution,
        security_type=SecurityType.USER_DATA,
        policy=AuthPolicy(),
        classification=_classification(),
        credentials=_credentials(),
        available=(SignatureAlgorithm.HMAC_SHA256,),
    )
    outcome = sign_request(
        authorisation,
        operation="spot.account",
        method=HttpMethod.GET,
        path="/v3/account",
        parameters=QueryParameters(items=(("symbol", "BTCUSDT"),)),
        timing=signing_timing(_moment()),
        store=_StubStore(),
        signer=hmac_signer(),
        correlation_id="auth-end-to-end",
    )
    assert outcome.request is not None
    signature = dict(outcome.request.request.parameters.items)[SIGNATURE_PARAMETER]
    with HttpRestTransport(
        environment=ENVIRONMENT, clock=_FixedClock(), connect=_plain
    ) as transport:
        exchange = transport.send(resolution, outcome.request.request)
    rendered = str(exchange.as_record())
    assert API_KEY not in rendered
    assert SIGNING_SECRET not in rendered
    assert str(signature) not in rendered
    assert exchange.diagnostics.intent == "signed"


def test_a_simulated_environment_never_reaches_the_transport(
    resolution: EndpointResolution,
) -> None:
    """Gate 1, end to end: nothing is signed and nothing is sent."""
    paper = EndpointResolution(
        outcome=ResolutionStatus.RESOLVED,
        requested_family="spot",
        requested_environment="paper",
        requested_capability="account_data",
        intent=RequestSecurityIntent.SIGNED,
        encoding=ResponseEncoding.JSON,
        endpoint=resolution.endpoint,
    )
    authorisation = resolve_auth(
        paper,
        security_type=SecurityType.USER_DATA,
        policy=AuthPolicy(),
        classification=_classification(),
        credentials=_credentials(),
        available=(SignatureAlgorithm.HMAC_SHA256,),
    )
    assert authorisation.outcome is AuthStatus.ENVIRONMENT_FORBIDS_CREDENTIAL
    assert RECEIVED == []
