"""The diagnostics surface's behaviour, decided without a socket anywhere.

Almost everything this surface does is a function of three strings — a method, a
target and an ``Accept`` header — and this file exercises all of it through
:meth:`DiagnosticsService.handle`. No socket is opened, so the offline guard is not
merely satisfied but irrelevant, and every case runs in microseconds.

What this file cannot answer is whether the socket plumbing hands those three strings
over and writes the bytes back. That is
``tests/integration/test_diagnostics_endpoint_end_to_end.py``, which is deliberately
small: the more behaviour lives here, the less has to be proved over a connection.
"""

import json
from dataclasses import replace
from typing import Final

import pytest

from globin.application.diagnostics_http import (
    BODY_INTERNAL_ERROR,
    BODY_TOO_LARGE,
    METRIC_DURATION,
    METRIC_REJECTED,
    METRIC_REQUESTS,
    METRIC_RESPONSE_BYTES,
    DiagnosticsService,
)
from globin.application.observability import Logger
from globin.domain.clock import Duration, MonotonicReading
from globin.domain.configuration import DiagnosticsHttpConfig
from globin.domain.diagnostics_http import (
    ALLOWED_METHODS,
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_OPENMETRICS,
    CONTENT_TYPE_PROMETHEUS,
    CONTENT_TYPE_TEXT,
    LOOPBACK_IPV4,
    LOOPBACK_IPV6,
    MAXIMUM_ACCEPT_LENGTH,
    MAXIMUM_CONCURRENT_REQUESTS,
    MAXIMUM_TARGET_LENGTH,
    STATUS_BAD_REQUEST,
    STATUS_METHOD_NOT_ALLOWED,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    DiagnosticsRoute,
    ExpositionFormat,
    LoopbackAddress,
    ReadinessReason,
    RejectionReason,
    RequestOutcome,
    RouteMethod,
    StatusClass,
    address_problems,
    content_type_for,
    method_of,
    negotiate,
    normalise_path,
    policy_problems,
    quality_of,
    rejection_reason_values,
    route_paths,
    route_values,
    routes,
    status_class,
    status_class_values,
)
from globin.domain.observability import LogEvent
from globin.errors import ValidationError
from tests.support import ManualMonotonicClock

CANARY: Final[str] = "globin-canary-secret-value"
"""A value that must never reach a body, a header, a log record or a metric label.

Spelled once so that every leak assertion looks for the same thing, and chosen to be
unmistakable in a diff if it ever does appear.
"""


class Recorder:
    """A metric recorder that keeps what it was given."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.counts: list[tuple[str, int, dict[str, str]]] = []
        self.gauges: list[tuple[str, int, dict[str, str]]] = []
        self.observations: list[tuple[str, int, dict[str, str]]] = []

    def count(self, name: str, increment: int = 1, **attributes: str) -> None:
        """Record a counter increment."""
        self.counts.append((name, increment, attributes))

    def set_gauge(self, name: str, value: int, **attributes: str) -> None:
        """Record a gauge reading."""
        self.gauges.append((name, value, attributes))

    def observe(self, name: str, value: int, **attributes: str) -> None:
        """Record a histogram observation."""
        self.observations.append((name, value, attributes))

    def labels(self, name: str) -> list[dict[str, str]]:
        """Every attribute set recorded against one metric."""
        return [
            attributes
            for recorded, _value, attributes in self.counts + self.gauges + self.observations
            if recorded == name
        ]


class Sink:
    """A log sink that keeps every record."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.events: list[LogEvent] = []

    def emit(self, event: LogEvent) -> None:
        """Keep one record."""
        self.events.append(event)

    def text(self) -> str:
        """Every record, flattened, so a canary search covers all of them."""
        return json.dumps([event.as_mapping() for event in self.events], default=str)


class Liveness:
    """A liveness probe a test can flip."""

    def __init__(self, live: bool = True) -> None:
        """Start live unless told otherwise."""
        self.live = live

    def alive(self) -> bool:
        """Whether the process is live."""
        return self.live


class Readiness:
    """A readiness probe a test can set."""

    def __init__(self, reason: ReadinessReason = ReadinessReason.READY) -> None:
        """Start ready unless told otherwise."""
        self.reason = reason

    def readiness(self) -> ReadinessReason:
        """Why the process is or is not ready."""
        return self.reason


class Document:
    """A projection returning a fixed document."""

    def __init__(self, payload: dict[str, object] | None = None) -> None:
        """Hold what will be returned."""
        self.payload: dict[str, object] = {"measured": True} if payload is None else payload

    def document(self) -> dict[str, object]:
        """The document."""
        return self.payload


class Exposition:
    """An exposition that records which format it was asked for."""

    def __init__(self, text: str = "# TYPE x counter\nx 1\n") -> None:
        """Hold what will be returned."""
        self.text = text
        self.asked: list[ExpositionFormat] = []

    def render(self, exposition: ExpositionFormat) -> str:
        """Encode, recording the format."""
        self.asked.append(exposition)
        return self.text


class Angry:
    """A projection that fails the way a wedged probe would."""

    def document(self) -> dict[str, object]:
        """Raise, carrying a canary the client must never see.

        Raises:
            RuntimeError: Always.
        """
        message = f"the probe failed while holding {CANARY}"
        raise RuntimeError(message)


def _service(
    surface: DiagnosticsHttpConfig | None = None,
    *,
    liveness: object | None = None,
    readiness: object | None = None,
    health: object | None = None,
    snapshot: object | None = None,
    exposition: object | None = None,
) -> tuple[DiagnosticsService, Recorder, Sink]:
    """A service over hand-written doubles, plus the recorder and sink behind it."""
    recorder = Recorder()
    sink = Sink()
    settings = DiagnosticsHttpConfig(enabled=True) if surface is None else surface
    service = DiagnosticsService(
        surface=settings,
        liveness=Liveness() if liveness is None else liveness,  # type: ignore[arg-type]
        readiness=Readiness() if readiness is None else readiness,  # type: ignore[arg-type]
        health=Document() if health is None else health,  # type: ignore[arg-type]
        snapshot=Document() if snapshot is None else snapshot,  # type: ignore[arg-type]
        exposition=Exposition() if exposition is None else exposition,  # type: ignore[arg-type]
        recorder=recorder,
        logger=Logger(sink=sink, correlation_id="c" * 32),
        monotonic=_ticks(),
    )
    return service, recorder, sink


def _ticks(step: int = 1_000_000) -> ManualMonotonicClock:
    """A monotonic clock a test advances by a known amount."""
    return ManualMonotonicClock(current=MonotonicReading(0), step=Duration(nanoseconds=step))


class Backwards:
    """A monotonic clock that goes backwards, which a platform clock should not.

    Nothing in `MonotonicReading` forbids it: the type promises only that the
    *difference* between two readings is meaningful, so a duration computed from a
    clock that moved backwards is the one case the recorder has to survive.
    """

    def __init__(self) -> None:
        """Start high so the second reading is lower."""
        self.readings = [500, 100]

    def reading(self) -> MonotonicReading:
        """The next reading, which may be lower than the last."""
        return MonotonicReading(self.readings.pop(0) if self.readings else 0)


def _open_everything() -> DiagnosticsHttpConfig:
    """Every route switched on, which is not the default for two of them."""
    return DiagnosticsHttpConfig(
        enabled=True, health_enabled=True, metrics_enabled=True, diagnostics_snapshot_enabled=True
    )


# ---------------------------------------------------------------------------
# The bind address, which is a type rather than a string
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(LOOPBACK_IPV4, id="ipv4-loopback"),
        pytest.param(LOOPBACK_IPV6, id="ipv6-loopback"),
        pytest.param("127.0.0.2", id="another-loopback-v4"),
        pytest.param("::ffff:127.0.0.1", id="ipv4-mapped-loopback"),
    ],
)
def test_a_loopback_address_is_accepted(text: str) -> None:
    """Every address that genuinely cannot leave this host."""
    assert LoopbackAddress(text).text == text
    assert address_problems(text) == ()


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("0.0.0.0", id="wildcard-v4"),  # noqa: S104 -- refusing it is the point
        pytest.param("::", id="wildcard-v6"),
        pytest.param("192.168.1.10", id="private-lan"),
        pytest.param("10.0.0.1", id="another-private-lan"),
        pytest.param("8.8.8.8", id="public"),
        pytest.param("localhost", id="a-hostname-that-would-resolve-to-loopback"),
        pytest.param("globin.example.com", id="a-resolvable-hostname"),
        pytest.param("2130706433", id="loopback-as-a-decimal-integer"),
        pytest.param("0", id="wildcard-as-a-bare-zero"),
        pytest.param("", id="empty"),
        pytest.param("not an address", id="nonsense"),
    ],
)
def test_every_address_that_is_not_loopback_is_refused(text: str) -> None:
    """The set is not enumerable, which is why the check parses instead of comparing.

    Four of these are spellings of "every interface" or of loopback that a denylist
    would plausibly have missed. `ipaddress` gets all of them from one rule.
    """
    assert address_problems(text), text
    with pytest.raises(ValidationError):
        LoopbackAddress(text)


def test_a_hostname_is_refused_rather_than_resolved() -> None:
    """Resolution is I/O, and a name that resolves to loopback today may not tomorrow."""
    problems = address_problems("localhost")
    assert "hostname is refused" in problems[0]


def test_an_ipv6_address_reports_its_family() -> None:
    """The one thing a caller opening a socket cannot read off the string safely."""
    assert LoopbackAddress(LOOPBACK_IPV6).is_ipv6
    assert not LoopbackAddress(LOOPBACK_IPV4).is_ipv6


# ---------------------------------------------------------------------------
# The policy, which cannot be constructed in a state it could not honour
# ---------------------------------------------------------------------------


def test_a_usable_policy_has_no_problems() -> None:
    """The positive case, so every refusal below means something."""
    assert DiagnosticsHttpConfig().policy().port == 9_464


@pytest.mark.parametrize(
    "surface",
    [
        pytest.param(DiagnosticsHttpConfig(port=80), id="privileged-port"),
        pytest.param(DiagnosticsHttpConfig(port=0), id="port-zero"),
        pytest.param(DiagnosticsHttpConfig(port=70_000), id="port-above-range"),
        pytest.param(DiagnosticsHttpConfig(request_timeout_seconds=0), id="no-request-timeout"),
        pytest.param(
            DiagnosticsHttpConfig(request_timeout_seconds=600), id="request-timeout-too-long"
        ),
        pytest.param(DiagnosticsHttpConfig(shutdown_timeout_seconds=0), id="no-shutdown-timeout"),
        pytest.param(DiagnosticsHttpConfig(max_concurrent_requests=0), id="no-workers"),
        pytest.param(
            DiagnosticsHttpConfig(max_concurrent_requests=MAXIMUM_CONCURRENT_REQUESTS + 1),
            id="too-many-workers",
        ),
        pytest.param(DiagnosticsHttpConfig(max_response_bytes=10), id="response-bound-too-small"),
        pytest.param(
            DiagnosticsHttpConfig(max_response_bytes=1 << 30), id="response-bound-too-large"
        ),
    ],
)
def test_an_unusable_bound_cannot_be_constructed(surface: DiagnosticsHttpConfig) -> None:
    """A policy that could not be honoured is refused rather than obeyed loosely.

    The section is built directly rather than through `dataclasses.replace`, because
    every one of these is a *field* whose value is wrong — and a helper taking a field
    name and an object would type-check nothing about the pairing.
    """
    with pytest.raises(ValidationError):
        surface.policy()


def test_a_boolean_is_not_a_number_even_though_python_thinks_so() -> None:
    """`max_concurrent_requests = true` meaning one worker is nobody's intent."""
    assert policy_problems(
        port=True,
        request_timeout_seconds=5,
        shutdown_timeout_seconds=5,
        max_concurrent_requests=4,
        max_response_bytes=4096,
    )


def test_the_policy_names_the_band_it_refused() -> None:
    """An operator who typed a number reads the accepted range rather than guessing."""
    problems = policy_problems(
        port=80,
        request_timeout_seconds=5,
        shutdown_timeout_seconds=5,
        max_concurrent_requests=4,
        max_response_bytes=4096,
    )
    assert "1024..65535" in problems[0]


# ---------------------------------------------------------------------------
# Routing, which is a table of exact strings and nothing else
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("path", "route"), route_paths())
def test_every_declared_path_names_its_route(path: str, route: DiagnosticsRoute) -> None:
    """The table read forwards."""
    assert normalise_path(path) is route


@pytest.mark.parametrize(
    "target",
    [
        pytest.param("/", id="root"),
        pytest.param("/health", id="a-prefix-of-a-route"),
        pytest.param("/health/live/", id="trailing-slash"),
        pytest.param("/HEALTH/LIVE", id="upper-case"),
        pytest.param("/health/liveness", id="a-longer-name"),
        pytest.param("/../../etc/passwd", id="traversal"),
        pytest.param("/..%2f..%2fetc%2fpasswd", id="encoded-traversal"),
        pytest.param("/metrics/../health/live", id="traversal-back-to-a-real-route"),
        pytest.param("//metrics", id="doubled-separator"),
        pytest.param("/index.html", id="a-static-file"),
        pytest.param("/favicon.ico", id="the-file-every-browser-asks-for"),
        pytest.param("http://elsewhere/metrics", id="an-absolute-uri"),
        pytest.param("/" + "a" * (MAXIMUM_TARGET_LENGTH + 1), id="over-long"),
    ],
)
def test_anything_not_in_the_table_is_unknown(target: str) -> None:
    """Traversal is not defended against — it simply has nowhere to go.

    There is no prefix match, no normalisation and no case folding, so the table is
    the complete list of targets that do anything.
    """
    assert normalise_path(target) is DiagnosticsRoute.UNKNOWN


@pytest.mark.parametrize(
    ("target", "route"),
    [
        pytest.param("/metrics?x=1", DiagnosticsRoute.METRICS, id="query"),
        pytest.param("/metrics?", DiagnosticsRoute.METRICS, id="empty-query"),
        pytest.param("/metrics#frag", DiagnosticsRoute.METRICS, id="fragment"),
        pytest.param("/health/live?a=b&c=d", DiagnosticsRoute.LIVENESS, id="two-parameters"),
    ],
)
def test_a_query_component_is_discarded_rather_than_parsed(
    target: str, route: DiagnosticsRoute
) -> None:
    """A scraper appending a cache-buster still scrapes; the parameter means nothing."""
    assert normalise_path(target) is route


def test_the_unknown_route_has_no_path_of_its_own() -> None:
    """It exists to bound a label, not to be reachable."""
    assert DiagnosticsRoute.UNKNOWN not in {route for _path, route in route_paths()}
    assert DiagnosticsRoute.UNKNOWN in routes()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("GET", RouteMethod.GET, id="get"),
        pytest.param("HEAD", RouteMethod.HEAD, id="head"),
        pytest.param("POST", RouteMethod.OTHER, id="post"),
        pytest.param("DELETE", RouteMethod.OTHER, id="delete"),
        pytest.param("PROPFIND", RouteMethod.OTHER, id="a-verb-nobody-planned-for"),
        pytest.param("get", RouteMethod.OTHER, id="lower-case-is-not-the-method"),
        pytest.param("", RouteMethod.OTHER, id="empty"),
    ],
)
def test_a_method_reduces_to_one_of_three(raw: str, expected: RouteMethod) -> None:
    """Collapsing every refused verb keeps a remote party from choosing a label."""
    assert method_of(raw) is expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        pytest.param(STATUS_OK, StatusClass.SUCCESS, id="200"),
        pytest.param(STATUS_BAD_REQUEST, StatusClass.CLIENT_ERROR, id="400"),
        pytest.param(STATUS_NOT_FOUND, StatusClass.CLIENT_ERROR, id="404"),
        pytest.param(STATUS_METHOD_NOT_ALLOWED, StatusClass.CLIENT_ERROR, id="405"),
        pytest.param(STATUS_UNAVAILABLE, StatusClass.SERVER_ERROR, id="503"),
    ],
)
def test_a_status_reduces_to_its_class(status: int, expected: StatusClass) -> None:
    """Three values answer "is anything wrong" and keep the series count computable."""
    assert status_class(status) is expected


# ---------------------------------------------------------------------------
# Content negotiation, which is total because the specification has no failure
# ---------------------------------------------------------------------------


def test_the_real_prometheus_scrape_header_selects_openmetrics() -> None:
    """The header Prometheus actually sends, and the format it most prefers.

    OpenMetrics 1.0 sits at q=0.5 and is the highest-weighted protocol GLOBIN
    produces, so it wins over the 0.0.4 offer at q=0.2 beneath it.
    """
    header = (
        "application/openmetrics-text;version=1.0.0;escaping=allow-utf-8;q=0.5,"
        "application/openmetrics-text;version=0.0.1;q=0.4,"
        "text/plain;version=1.0.0;escaping=allow-utf-8;q=0.3,"
        "text/plain;version=0.0.4;q=0.2,*/*;q=0.1"
    )
    assert negotiate(header) is ExpositionFormat.OPENMETRICS_TEXT


@pytest.mark.parametrize(
    "header",
    [
        pytest.param("", id="absent"),
        pytest.param("*/*", id="anything"),
        pytest.param("text/plain", id="bare-text-plain"),
        pytest.param("text/plain;version=0.0.4", id="explicit-0.0.4"),
        pytest.param("text/*", id="any-text-subtype"),
        pytest.param("text/plain;version=1.0.0", id="a-version-globin-does-not-produce"),
        pytest.param("application/openmetrics-text;version=0.0.1", id="openmetrics-0.0.1"),
        pytest.param("application/vnd.google.protobuf", id="the-protobuf-protocol"),
        pytest.param("nonsense", id="not-a-media-type"),
        pytest.param(";;;;", id="only-separators"),
        pytest.param("text/plain;q=0", id="explicitly-unacceptable"),
        pytest.param("text/plain;q=bogus", id="unreadable-weight"),
        pytest.param("x" * (MAXIMUM_ACCEPT_LENGTH + 1), id="over-long"),
        pytest.param("text/plain;version=0.0.4;q=0.9\r\nX-Injected: yes", id="crlf-in-the-header"),
    ],
)
def test_everything_unusable_lands_on_the_specifications_last_resort(header: str) -> None:
    """*"the target MUST use PrometheusText0.0.4 as a last resort"*.

    There is no 406 in this protocol, so a malformed, hostile or absent header and an
    explicit request for 0.0.4 all reach the same answer. That is what makes
    `negotiate` return an enum rather than an optional.
    """
    assert negotiate(header) is ExpositionFormat.PROMETHEUS_TEXT


@pytest.mark.parametrize(
    "header",
    [
        pytest.param("application/openmetrics-text", id="bare"),
        pytest.param("application/openmetrics-text;version=1.0.0", id="explicit"),
        pytest.param("APPLICATION/OPENMETRICS-TEXT;VERSION=1.0.0", id="upper-case"),
        pytest.param(" application/openmetrics-text ; version=1.0.0 ", id="generous-whitespace"),
        pytest.param("application/*", id="any-application-subtype"),
        pytest.param(
            "application/openmetrics-text;version=1.0.0;escaping=underscores",
            id="an-escaping-parameter-that-is-read-past",
        ),
    ],
)
def test_openmetrics_is_selected_when_it_is_asked_for(header: str) -> None:
    """Case-insensitive where the standard is, and tolerant of whitespace."""
    assert negotiate(header) is ExpositionFormat.OPENMETRICS_TEXT


def test_equal_weights_break_on_the_order_the_client_wrote() -> None:
    """Two ranges of equal weight resolve the client's way, not a dictionary's."""
    assert (
        negotiate("text/plain;q=0.9,application/openmetrics-text;q=0.9")
        is ExpositionFormat.PROMETHEUS_TEXT
    )
    assert (
        negotiate("application/openmetrics-text;q=0.9,text/plain;q=0.9")
        is ExpositionFormat.OPENMETRICS_TEXT
    )


def test_a_higher_weight_wins_wherever_it_appears() -> None:
    """Selection is by weight first, which is the specification's own rule."""
    assert (
        negotiate("text/plain;q=0.2,application/openmetrics-text;q=0.8")
        is ExpositionFormat.OPENMETRICS_TEXT
    )
    assert (
        negotiate("application/openmetrics-text;q=0.2,text/plain;q=0.8")
        is ExpositionFormat.PROMETHEUS_TEXT
    )


@pytest.mark.parametrize(
    ("value", "thousandths"),
    [
        pytest.param("1", 1_000, id="one"),
        pytest.param("1.0", 1_000, id="one-point-zero"),
        pytest.param("1.000", 1_000, id="one-with-three-zeroes"),
        pytest.param("0.5", 500, id="a-half"),
        pytest.param("0.123", 123, id="three-digits"),
        pytest.param("0", 0, id="zero-means-unacceptable"),
        pytest.param("0.1234", 0, id="too-many-digits"),
        pytest.param("1.5", 0, id="above-the-range"),
        pytest.param("2", 0, id="well-above-the-range"),
        pytest.param("", 0, id="empty"),
        pytest.param("abc", 0, id="not-a-number"),
        pytest.param("0.5x", 0, id="trailing-rubbish"),
        pytest.param("-0.5", 0, id="negative"),
    ],
)
def test_a_weight_is_read_as_thousandths_or_as_unacceptable(value: str, thousandths: int) -> None:
    """Integers throughout, so two spellings of one weight sort identically.

    Unreadable means zero, which RFC 9110 already defines as "not acceptable" — a
    reading the protocol has rather than a lenient one this repository invented.
    """
    assert quality_of(value) == thousandths


def test_each_format_has_exactly_one_content_type() -> None:
    """The header and the bytes cannot disagree, because both come from this table."""
    assert content_type_for(ExpositionFormat.PROMETHEUS_TEXT) == CONTENT_TYPE_PROMETHEUS
    assert content_type_for(ExpositionFormat.OPENMETRICS_TEXT) == CONTENT_TYPE_OPENMETRICS


# ---------------------------------------------------------------------------
# Liveness and readiness, which answer different questions
# ---------------------------------------------------------------------------


def test_liveness_is_two_hundred_while_the_process_is_live() -> None:
    """And its payload is two fields, neither of them measured."""
    service, _recorder, _sink = _service()
    response = service.handle("GET", "/health/live")
    assert response.status == STATUS_OK
    assert response.content_type == CONTENT_TYPE_JSON
    body = json.loads(response.body)
    assert body["live"] is True
    assert set(body) == {"schema", "schema_version", "live", "status"}


def test_liveness_is_five_hundred_and_three_once_the_process_is_stopping() -> None:
    """The one thing that may change this answer."""
    service, _recorder, _sink = _service(liveness=Liveness(live=False))
    response = service.handle("GET", "/health/live")
    assert response.status == STATUS_UNAVAILABLE
    assert json.loads(response.body)["live"] is False


def test_liveness_reaches_no_health_probe_at_all() -> None:
    """A liveness endpoint that failed when a disk filled would be worse than none.

    The health projection here raises. Liveness still answers, because it cannot
    reach one.
    """
    service, _recorder, _sink = _service(health=Angry())
    assert service.handle("GET", "/health/live").status == STATUS_OK


def test_readiness_is_two_hundred_only_when_the_reason_is_ready() -> None:
    """The positive case, and the payload names the reason either way."""
    service, _recorder, _sink = _service()
    response = service.handle("GET", "/health/ready")
    assert response.status == STATUS_OK
    assert json.loads(response.body) == {
        "schema": "globin.diagnostics.endpoint",
        "schema_version": 1,
        "ready": True,
        "reason": "ready",
    }


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param(ReadinessReason.STARTING, id="starting"),
        pytest.param(ReadinessReason.STOPPING, id="stopping"),
        pytest.param(ReadinessReason.CONFIGURATION_INVALID, id="configuration"),
        pytest.param(ReadinessReason.DEPENDENCY_UNREADY, id="dependency"),
        pytest.param(ReadinessReason.UNKNOWN, id="unknown"),
    ],
)
def test_every_other_reason_is_five_hundred_and_three(reason: ReadinessReason) -> None:
    """A bounded enum rather than a sentence, because this value is published."""
    service, _recorder, _sink = _service(readiness=Readiness(reason))
    response = service.handle("GET", "/health/ready")
    assert response.status == STATUS_UNAVAILABLE
    assert json.loads(response.body)["reason"] == reason.value


def test_a_truthful_unready_answer_is_recorded_as_a_success() -> None:
    """The status class is 5xx and the outcome is success, and both are right.

    Conflating them would make a healthy process that has not finished starting look
    broken on a dashboard.
    """
    service, _recorder, _sink = _service(readiness=Readiness(ReadinessReason.STARTING))
    response = service.handle("GET", "/health/ready")
    assert response.outcome is RequestOutcome.SUCCESS
    assert response.status_class is StatusClass.SERVER_ERROR


# ---------------------------------------------------------------------------
# The documents, and the bound on how large one may be
# ---------------------------------------------------------------------------


def test_the_runtime_route_serves_the_projection_it_was_given() -> None:
    """No second health engine: whatever the projection says is what is published."""
    service, _recorder, _sink = _service(health=Document({"state": "healthy"}))
    body = json.loads(service.handle("GET", "/health/runtime").body)
    assert body["state"] == "healthy"


def test_a_document_this_surface_invents_carries_its_schema() -> None:
    """So a consumer can tell what to parse a body as without inspecting its fields."""
    service, _recorder, _sink = _service(_open_everything())
    for target in ("/health/live", "/health/ready"):
        body = json.loads(service.handle("GET", target).body)
        assert body["schema"] == "globin.diagnostics.endpoint", target
        assert body["schema_version"] == 1, target


def test_a_projection_that_declares_its_own_schema_keeps_it() -> None:
    """Deliberate, not an accident of ordering.

    `/health/runtime` publishes the Phase 024 health snapshot, which already declares
    `globin.health.snapshot`. Stamping this surface's name over it would tell a
    consumer to parse a health document as an endpoint document.
    """
    service, _recorder, _sink = _service(
        _open_everything(),
        health=Document({"schema": "globin.health.snapshot", "state": "healthy"}),
    )
    body = json.loads(service.handle("GET", "/health/runtime").body)
    assert body["schema"] == "globin.health.snapshot"


def test_a_document_is_rendered_canonically() -> None:
    """Sorted keys and no incidental whitespace: same values, same bytes."""
    service, _recorder, _sink = _service(health=Document({"b": 2, "a": 1}))
    assert service.handle("GET", "/health/runtime").body == (
        b'{"a":1,"b":2,"schema":"globin.diagnostics.endpoint","schema_version":1}'
    )


def test_a_response_over_its_bound_is_refused_rather_than_truncated() -> None:
    """Half a JSON document is not a smaller answer.

    An OpenMetrics exposition without its terminator is refused by every conforming
    parser, so truncating would produce data a consumer cannot tell from corruption.
    """
    surface = replace(_open_everything(), max_response_bytes=1_024)
    service, recorder, _sink = _service(surface, health=Document({"padding": "x" * 4_000}))
    response = service.handle("GET", "/health/runtime")
    assert response.body == BODY_TOO_LARGE
    assert response.content_type == CONTENT_TYPE_TEXT
    assert response.outcome is RequestOutcome.ERROR
    assert (METRIC_REJECTED, 1, {"reason": RejectionReason.OVERSIZE.value}) in recorder.counts


def test_the_oversize_refusal_always_fits_inside_the_smallest_permitted_bound() -> None:
    """Otherwise the refusal could trigger the condition it reports."""
    assert len(BODY_TOO_LARGE) < 1_024
    assert len(BODY_INTERNAL_ERROR) < 1_024


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method",
    [
        pytest.param("POST", id="post"),
        pytest.param("PUT", id="put"),
        pytest.param("PATCH", id="patch"),
        pytest.param("DELETE", id="delete"),
        pytest.param("OPTIONS", id="options"),
        pytest.param("TRACE", id="trace"),
        pytest.param("PROPFIND", id="a-verb-nobody-planned-for"),
    ],
)
def test_an_unsupported_method_is_four_hundred_and_five_with_allow(method: str) -> None:
    """And it mutates nothing, because there is nothing here that could be mutated."""
    service, recorder, _sink = _service()
    response = service.handle(method, "/health/live")
    assert response.status == STATUS_METHOD_NOT_ALLOWED
    assert response.allow == ALLOWED_METHODS
    assert response.outcome is RequestOutcome.REJECTED
    assert (METRIC_REJECTED, 1, {"reason": RejectionReason.METHOD.value}) in recorder.counts


def test_an_unknown_target_is_four_hundred_and_four_and_does_not_echo_it() -> None:
    """A body that quoted the target would carry attacker-chosen text."""
    service, recorder, _sink = _service()
    response = service.handle("GET", f"/{CANARY}")
    assert response.status == STATUS_NOT_FOUND
    assert CANARY.encode() not in response.body
    assert response.route is DiagnosticsRoute.UNKNOWN
    assert (METRIC_REJECTED, 1, {"reason": RejectionReason.UNKNOWN_ROUTE.value}) in recorder.counts


def test_a_request_carrying_a_body_is_four_hundred() -> None:
    """A body this surface never reads would be left in the socket for the next request."""
    service, recorder, _sink = _service()
    response = service.handle("GET", "/health/live", has_body=True)
    assert response.status == STATUS_BAD_REQUEST
    assert (METRIC_REJECTED, 1, {"reason": RejectionReason.BODY_PRESENT.value}) in recorder.counts


@pytest.mark.parametrize(
    ("target", "surface"),
    [
        pytest.param("/health/live", DiagnosticsHttpConfig(health_enabled=False), id="liveness"),
        pytest.param("/health/ready", DiagnosticsHttpConfig(health_enabled=False), id="readiness"),
        pytest.param("/health/runtime", DiagnosticsHttpConfig(health_enabled=False), id="runtime"),
        pytest.param("/metrics", DiagnosticsHttpConfig(metrics_enabled=False), id="metrics"),
        pytest.param(
            "/diagnostics/snapshot", DiagnosticsHttpConfig(), id="snapshot-off-by-default"
        ),
    ],
)
def test_a_switched_off_route_answers_four_hundred_and_four(
    target: str, surface: DiagnosticsHttpConfig
) -> None:
    """404 rather than 403: which diagnostics an operator withheld is not a client's business."""
    service, recorder, _sink = _service(surface)
    response = service.handle("GET", target)
    assert response.status == STATUS_NOT_FOUND
    assert (
        METRIC_REJECTED,
        1,
        {"reason": RejectionReason.ROUTE_DISABLED.value},
    ) in recorder.counts


def test_the_snapshot_route_answers_once_it_is_switched_on() -> None:
    """The other direction, so the check above is not vacuously true."""
    service, _recorder, _sink = _service(_open_everything(), snapshot=Document({"deep": True}))
    response = service.handle("GET", "/diagnostics/snapshot")
    assert response.status == STATUS_OK
    assert json.loads(response.body)["deep"] is True


# ---------------------------------------------------------------------------
# The scrape route
# ---------------------------------------------------------------------------


def test_the_scrape_route_encodes_in_the_negotiated_format() -> None:
    """And sends the content type that matches what it encoded."""
    exposition = Exposition()
    service, _recorder, _sink = _service(_open_everything(), exposition=exposition)
    plain = service.handle("GET", "/metrics", "text/plain;version=0.0.4")
    open_metrics = service.handle("GET", "/metrics", "application/openmetrics-text;version=1.0.0")
    assert plain.content_type == CONTENT_TYPE_PROMETHEUS
    assert open_metrics.content_type == CONTENT_TYPE_OPENMETRICS
    assert exposition.asked == [
        ExpositionFormat.PROMETHEUS_TEXT,
        ExpositionFormat.OPENMETRICS_TEXT,
    ]


# ---------------------------------------------------------------------------
# Exception isolation, and what a client is told about it
# ---------------------------------------------------------------------------


def test_a_failing_projection_becomes_a_small_five_hundred() -> None:
    """An exception escaping here would reach a worker, and a worker can only die."""
    service, _recorder, _sink = _service(_open_everything(), health=Angry())
    response = service.handle("GET", "/health/runtime")
    assert response.status == 500
    assert response.body == BODY_INTERNAL_ERROR
    assert response.outcome is RequestOutcome.ERROR


def test_a_failure_tells_the_client_nothing_about_why() -> None:
    """Redaction is by field name, so an exception's *message* would be written verbatim.

    Not sending it is what makes that limitation harmless here.
    """
    service, _recorder, sink = _service(_open_everything(), health=Angry())
    response = service.handle("GET", "/health/runtime")
    assert CANARY.encode() not in response.body
    assert CANARY not in response.content_type
    assert CANARY not in sink.text()


def test_a_failure_records_the_exception_type_and_not_its_message() -> None:
    """Enough to diagnose, and nothing that came from the failure's own text."""
    service, _recorder, sink = _service(_open_everything(), health=Angry())
    service.handle("GET", "/health/runtime")
    failures = [event for event in sink.events if event.event == "diagnostics.http.failed"]
    assert failures
    assert dict(failures[0].fields)["fault"] == "RuntimeError"


def test_one_failing_route_leaves_the_others_answering() -> None:
    """Isolation is per request, not per surface."""
    service, _recorder, _sink = _service(_open_everything(), health=Angry())
    assert service.handle("GET", "/health/runtime").status == 500
    assert service.handle("GET", "/health/live").status == STATUS_OK
    assert service.handle("GET", "/metrics").status == STATUS_OK


# ---------------------------------------------------------------------------
# Self-observation: what is recorded, and what can never be
# ---------------------------------------------------------------------------


def test_every_answered_request_records_a_count_a_duration_and_its_bytes() -> None:
    """The documented order: the body exists, then the counters move."""
    service, recorder, _sink = _service()
    response = service.handle("GET", "/health/live")
    assert (
        METRIC_REQUESTS,
        1,
        {"route": "liveness", "status_class": "2xx"},
    ) in recorder.counts
    assert (METRIC_RESPONSE_BYTES, response.length, {"route": "liveness"}) in recorder.counts
    assert [name for name, _value, _labels in recorder.observations] == [METRIC_DURATION]


def test_a_duration_is_never_negative_even_if_a_clock_went_backwards() -> None:
    """`MonotonicReading` promises only that a *difference* is meaningful."""
    recorder = Recorder()
    service = DiagnosticsService(
        surface=DiagnosticsHttpConfig(enabled=True),
        liveness=Liveness(),
        readiness=Readiness(),
        health=Document(),
        snapshot=Document(),
        exposition=Exposition(),
        recorder=recorder,
        logger=Logger(sink=Sink(), correlation_id="c" * 32),
        monotonic=Backwards(),
    )
    service.handle("GET", "/health/live")
    assert all(value >= 0 for _name, value, _labels in recorder.observations)


@pytest.mark.parametrize(
    "target",
    [
        pytest.param(f"/{CANARY}", id="an-unknown-path"),
        pytest.param(f"/metrics?secret={CANARY}", id="a-query-string"),
        pytest.param("/../../etc/passwd", id="a-traversal-attempt"),
    ],
)
def test_no_label_ever_carries_anything_a_caller_wrote(target: str) -> None:
    """The cardinality argument applied to the one surface a remote party can reach.

    Ten thousand invented paths produce one series, and none of them contains the path.
    """
    service, recorder, _sink = _service(_open_everything())
    service.handle("GET", target)
    for name in (METRIC_REQUESTS, METRIC_RESPONSE_BYTES, METRIC_DURATION, METRIC_REJECTED):
        for attributes in recorder.labels(name):
            for value in attributes.values():
                assert CANARY not in value
                assert "/" not in value
                assert "?" not in value


def test_every_recorded_label_value_is_a_declared_enum_member() -> None:
    """A label the registry did not declare is a series the arithmetic did not predict."""
    permitted = {
        "route": set(route_values()),
        "status_class": set(status_class_values()),
        "reason": set(rejection_reason_values()),
    }
    service, recorder, _sink = _service(_open_everything())
    for method, target in (
        ("GET", "/health/live"),
        ("GET", "/health/ready"),
        ("GET", "/health/runtime"),
        ("GET", "/metrics"),
        ("GET", "/diagnostics/snapshot"),
        ("GET", "/nonsense"),
        ("POST", "/metrics"),
    ):
        service.handle(method, target)
    for name in (METRIC_REQUESTS, METRIC_RESPONSE_BYTES, METRIC_DURATION, METRIC_REJECTED):
        for attributes in recorder.labels(name):
            for key, value in attributes.items():
                assert key in permitted, key
                assert value in permitted[key], (key, value)


def test_a_scrape_reports_the_state_as_of_its_own_arrival() -> None:
    """The exposition is rendered before this request's own counters move.

    That ordering is what stops a scrape chasing a number it is itself changing.
    """
    seen: list[int] = []
    recorder = Recorder()

    class Counting:
        """An exposition that records how many requests had been counted when asked."""

        def render(self, exposition: ExpositionFormat) -> str:
            """Note the count so far."""
            del exposition
            seen.append(len([name for name, _v, _a in recorder.counts if name == METRIC_REQUESTS]))
            return "x 1\n"

    service = DiagnosticsService(
        surface=_open_everything(),
        liveness=Liveness(),
        readiness=Readiness(),
        health=Document(),
        snapshot=Document(),
        exposition=Counting(),
        recorder=recorder,
        logger=Logger(sink=Sink(), correlation_id="c" * 32),
        monotonic=_ticks(),
    )
    service.handle("GET", "/metrics")
    service.handle("GET", "/metrics")
    assert seen == [0, 1]


def test_no_log_record_carries_the_target_or_the_query() -> None:
    """A normalised route, never the raw request."""
    service, _recorder, sink = _service(_open_everything())
    service.handle("GET", f"/metrics?secret={CANARY}")
    service.handle("GET", f"/{CANARY}")
    text = sink.text()
    assert CANARY not in text
    assert "/metrics" not in text
