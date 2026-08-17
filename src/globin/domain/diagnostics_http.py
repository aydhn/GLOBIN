"""The diagnostics surface expressed as values: routes, formats, limits, addresses.

This is everything about GLOBIN's diagnostics endpoint that can be decided without
a socket, and it is deliberately almost all of it. Which path is which route, which
exposition format an ``Accept`` header asks for, whether a bind address is
loopback, what the limits may be — none of that needs a connection to answer, so
none of it lives near one. `adapters/diagnostics_http.py` is left with the part
that genuinely cannot be pure, which is why the bulk of this feature's tests open
nothing.

**A bind address is a value type, not a string.** :class:`LoopbackAddress` refuses
anything :mod:`ipaddress` does not call loopback, so the configuration field cannot
*hold* a wildcard, a LAN address or a hostname. That is stronger than validating on
the way in: there is no moment at which a non-loopback address exists inside GLOBIN
and is waiting to be checked. It is also why no wildcard address appears anywhere
in this repository's source — the check is a property of the parsed address rather
than a comparison against a list of spellings somebody has to keep complete.

**A route is an enum, and an unrecognised path is one member of it.** Every metric
this surface records is keyed by that enum, so a caller cannot inflate cardinality
by inventing paths: ten thousand distinct 404s produce one series labelled
``unknown``. The mapping from path to route is a declared table with no pattern
matching, no prefix logic and no path arithmetic, so a traversal attempt is not
defended against — it simply has nowhere to go and becomes ``unknown``.

**Negotiation is total.** :func:`negotiate` never raises and never reports failure,
because the Prometheus scrape protocol does not have a failure mode here: its own
rule is that a target which supports none of the offered protocols *"MUST use
PrometheusText0.0.4 as a last resort"*. A 406 would be this repository inventing a
status the specification declines to use. Malformed, hostile and absent headers all
converge on that same last resort, which is what makes the function's return type
an enum rather than an optional one.

What this module does not know: how to open a socket, how to read a clock, what
GLOBIN's health actually is, or what any metric currently reads. Those arrive
through `ports/diagnostics_http.py`.
"""

import ipaddress
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.errors import ValidationError

SCHEMA: Final[str] = "globin.diagnostics.endpoint"
"""What a document produced by this surface calls itself."""

SCHEMA_VERSION: Final[int] = 1
"""The version every document this surface emits is written against."""

LOOPBACK_IPV4: Final[str] = "127.0.0.1"
"""The IPv4 loopback address, and the default GLOBIN binds.

Spelled rather than derived because a layer package performs no call at import, so
``str(ipaddress.ip_address(...))`` is unavailable here. :class:`LoopbackAddress`
validates it anyway rather than trusting this constant, which is what makes the
constant a convenience instead of a second source of truth.
"""

LOOPBACK_IPV6: Final[str] = "::1"
"""The IPv6 loopback address.

Admissible, and never the default. A host with IPv6 disabled cannot bind it, and a
default that fails on some machines and not others is worse than a default that is
boring everywhere.
"""

IPV6_VERSION: Final[int] = 6
"""What :mod:`ipaddress` calls an IPv6 address's version."""

MINIMUM_PORT: Final[int] = 1_024
"""Below this a listener needs privilege on most hosts."""

MAXIMUM_PORT: Final[int] = 65_535
"""The highest addressable port."""

MINIMUM_TIMEOUT_SECONDS: Final[int] = 1
"""A timeout of zero would refuse every request the instant it arrived."""

MAXIMUM_TIMEOUT_SECONDS: Final[int] = 60
"""One minute.

Long past anything this surface does — the slowest route reads a health snapshot
whose own budget is five seconds — and short enough that a wedged request releases
its worker while somebody is still watching.
"""

MINIMUM_CONCURRENT_REQUESTS: Final[int] = 1
"""One worker still serves a scraper; zero would serve nothing."""

MAXIMUM_CONCURRENT_REQUESTS: Final[int] = 64
"""The most worker threads this surface will ever hold.

A hard ceiling on top of the operator's own number, because the worker count *is*
this setting: unlike a thread-per-connection server there is no separate limit to
get wrong, and the price of that is that this one must be bounded.
"""

MINIMUM_RESPONSE_BYTES: Final[int] = 1_024
"""Below this the smallest liveness document would not fit, so nothing could work."""

MAXIMUM_RESPONSE_BYTES: Final[int] = 8_388_608
"""8 MiB.

Matched to the support bundle's per-member bound rather than chosen freshly: the
largest thing this surface serves is a health snapshot, and Phase 024 already
decided how large one of those may be.
"""

MAXIMUM_TARGET_LENGTH: Final[int] = 256
"""The longest request target this surface will even look at.

Every path it serves is under thirty characters, so this is generous by an order of
magnitude and still bounds the work an unbounded target could ask for. A longer one
is ``unknown`` without being examined further.
"""

MAXIMUM_ACCEPT_LENGTH: Final[int] = 1_024
"""The most ``Accept`` header text that is parsed.

Prometheus's own scrape header is about 200 characters. Anything past this bound is
not truncated and re-parsed — the whole header is treated as unusable and the last
resort applies, because parsing half of a negotiation is how a parser starts
agreeing to something the client did not offer.
"""

MAXIMUM_ACCEPT_ITEMS: Final[int] = 16
"""The most media ranges parsed out of one ``Accept`` header.

Prometheus offers five. Items past this bound are ignored rather than making the
header unusable: the ones that matter are at the front, and a client that appends a
thousand ranges has still asked for whatever it put first.
"""

FULL_QUALITY: Final[int] = 1_000
"""``q=1`` in thousandths, which is also the ceiling RFC 9110 permits."""

QUALITY_DIGITS: Final[int] = 3
"""How many digits after the decimal point a q-value may carry."""

MEDIA_TYPE_PROMETHEUS: Final[str] = "text/plain"
"""The media type both Prometheus text formats share."""

MEDIA_TYPE_OPENMETRICS: Final[str] = "application/openmetrics-text"
"""The media type both OpenMetrics text formats share."""

MEDIA_RANGE_ANY: Final[str] = "*/*"
"""Any type at all, which every Prometheus scrape header ends with."""

MEDIA_RANGE_TEXT: Final[str] = "text/*"
"""Any text subtype, which GLOBIN answers with the text format it produces."""

MEDIA_RANGE_APPLICATION: Final[str] = "application/*"
"""Any application subtype, of which GLOBIN produces exactly one."""

VERSION_PARAMETER: Final[str] = "version"
"""The parameter that tells two protocols sharing a media type apart.

Load-bearing rather than decorative: ``text/plain`` alone names two protocols, and
GLOBIN produces one of them. Ignoring this parameter would mean answering a request
for PrometheusText1.0.0 with 0.0.4 bytes under a 1.0.0 content type.
"""

QUALITY_PARAMETER: Final[str] = "q"
"""The relative weight a client attaches to one media range."""

VERSION_PROMETHEUS_TEXT: Final[str] = "0.0.4"
"""The Prometheus text format version GLOBIN produces."""

VERSION_OPENMETRICS_TEXT: Final[str] = "1.0.0"
"""The OpenMetrics text format version GLOBIN produces."""

CONTENT_TYPE_PROMETHEUS: Final[str] = "text/plain; version=0.0.4; charset=utf-8"
"""The exact content type Prometheus text 0.0.4 is served under."""

CONTENT_TYPE_OPENMETRICS: Final[str] = "application/openmetrics-text; version=1.0.0; charset=utf-8"
"""The exact content type OpenMetrics 1.0 is served under.

Quoted from the specification rather than assembled: *"The content type MUST be:
``application/openmetrics-text; version=1.0.0; charset=utf-8``"*. See
``docs/research/phase_027_sources.md`` entry S-02.
"""

CONTENT_TYPE_JSON: Final[str] = "application/json; charset=utf-8"
"""The content type every JSON document this surface serves is sent under."""

CONTENT_TYPE_TEXT: Final[str] = "text/plain; charset=utf-8"
"""The content type an error body is sent under.

Deliberately plain text and deliberately tiny. An error body is the one response
that may be produced when rendering a document has already failed, so it must not
require the machinery that just broke.
"""

OPENMETRICS_TERMINATOR: Final[str] = "# EOF\n"
"""How an OpenMetrics exposition must end.

*"Expositions MUST end with EOF and SHOULD end with ``EOF\\n``"* — so this is the
SHOULD form of a MUST, and a truncated exposition that omits it is not a shorter
document but an invalid one. That is why a response over its size bound is refused
outright rather than cut short.
"""

STATUS_OK: Final[int] = 200
"""The request was answered."""

STATUS_BAD_REQUEST: Final[int] = 400
"""The request itself was not usable — a body where none is read, or an unparseable
request line.

Distinct from 404 on purpose. A body on a ``GET`` is a malformed *request*, and saying
so discloses nothing about what this surface serves; a route that is switched off is
answered 404 precisely *because* that discloses nothing.
"""

STATUS_NOT_FOUND: Final[int] = 404
"""No route serves that target, or the route that would is switched off."""

STATUS_METHOD_NOT_ALLOWED: Final[int] = 405
"""The route exists; the method is not one of the two this surface serves."""

STATUS_NOT_IMPLEMENTED: Final[int] = 501
"""What `http.server` chooses for a method it has no handler for.

Named here so the adapter can recognise it and answer 405 with an ``Allow`` header
instead. GLOBIN never *sends* a 501: an unsupported method is a method this surface
declines to serve, which is what 405 means, and 501 would claim the method is one
nobody could implement."""

STATUS_INTERNAL_ERROR: Final[int] = 500
"""Producing the answer failed, and the reason is not being sent to the client."""

STATUS_UNAVAILABLE: Final[int] = 503
"""Either the process is not ready, or the surface has no capacity to answer."""

ALLOWED_METHODS: Final[str] = "GET, HEAD"
"""The exact ``Allow`` header value a 405 carries.

A constant rather than a join over an enum, because it is written into a response
header: a header value assembled at run time is a header value something could
influence, and this one can be read off the page instead.
"""

HEADER_CONTENT_TYPE: Final[str] = "Content-Type"
"""Names the encoding of the body, and is never absent."""

HEADER_CONTENT_LENGTH: Final[str] = "Content-Length"
"""How many bytes the body is, sent on a ``HEAD`` too."""

HEADER_CACHE_CONTROL: Final[str] = "Cache-Control"
"""Where the no-store instruction goes."""

HEADER_PRAGMA: Final[str] = "Pragma"
"""The HTTP/1.0 spelling of the same instruction."""

HEADER_CONTENT_TYPE_OPTIONS: Final[str] = "X-Content-Type-Options"
"""Where the sniffing refusal goes."""

HEADER_ALLOW: Final[str] = "Allow"
"""What a 405 must carry to be useful."""

CACHE_CONTROL_VALUE: Final[str] = "no-store"
"""Never cache a diagnostics response.

``no-store`` rather than ``no-cache``: the latter permits storing the response and
merely requires revalidation, which for a document describing this process's
internals is the wrong half of the guarantee.
"""

PRAGMA_VALUE: Final[str] = "no-cache"
"""The HTTP/1.0 spelling, sent beside ``Cache-Control`` for the older intermediary."""

CONTENT_TYPE_OPTIONS_VALUE: Final[str] = "nosniff"
"""Take the declared content type at its word rather than guessing from the body."""


class DiagnosticsRoute(StrEnum):
    """Which of this surface's endpoints a request named.

    **Six members, and the sixth is the interesting one.** ``UNKNOWN`` exists so
    that an unrecognised path has a *bounded* name: every metric here is keyed by
    this enum, and a caller who tries ten thousand distinct paths produces one
    series rather than ten thousand. ADR-0068's cardinality argument applied to a
    dimension a remote party controls.

    **``LIVENESS`` rather than ``live``, and the path is still ``/health/live``.**
    ``tests/architecture/test_identifier_discipline.py`` refuses venue vocabulary as
    a live constant anywhere in the domain layer, and ``live`` is one of the four
    profile names. The guard was right for a reason beyond the rule it enforces:
    this value becomes a metric label, and ``route="live"`` on somebody's dashboard
    is genuinely ambiguous between *liveness* and *live trading*. The URL keeps the
    spelling operators expect from every other health endpoint; the label says which
    of the two it means.
    """

    LIVENESS = "liveness"
    READY = "ready"
    RUNTIME = "runtime"
    METRICS = "metrics"
    SNAPSHOT = "snapshot"
    UNKNOWN = "unknown"


class RouteMethod(StrEnum):
    """Which method a request used, reduced to the three cases that matter.

    ``OTHER`` collapses every method this surface refuses. Recording ``POST``,
    ``PUT``, ``DELETE``, ``PROPFIND`` and whatever a scanner invents separately
    would let a remote party choose a label value, which is the thing a bounded
    attribute domain exists to prevent.
    """

    GET = "GET"
    HEAD = "HEAD"
    OTHER = "other"


class StatusClass(StrEnum):
    """A status code reduced to its class.

    The full code is worth having in a log record and is not worth having in a
    metric label: three values answer "is anything wrong" and keep the series count
    to a number computable when the descriptor is written.
    """

    SUCCESS = "2xx"
    CLIENT_ERROR = "4xx"
    SERVER_ERROR = "5xx"


class RequestOutcome(StrEnum):
    """What happened to one request, from this surface's point of view.

    Distinct from :class:`StatusClass` because the two answer different questions.
    A 404 is a ``4xx`` and a ``REJECTED``; a readiness probe answered ``503``
    truthfully is a ``5xx`` and a ``SUCCESS``, because the surface did exactly its
    job. Collapsing them would make a healthy unready process look broken.
    """

    SUCCESS = "success"
    REJECTED = "rejected"
    ERROR = "error"


class RejectionReason(StrEnum):
    """Why a request was refused, as a bounded set.

    Every member is a decision this surface makes about a request's *shape*, never
    a description of its content, so none of these can carry anything a remote
    party wrote.
    """

    ADMISSION = "admission"
    METHOD = "method"
    UNKNOWN_ROUTE = "unknown_route"
    ROUTE_DISABLED = "route_disabled"
    BODY_PRESENT = "body_present"
    OVERSIZE = "oversize"


class ReadinessReason(StrEnum):
    """Why the process is or is not ready to work.

    A bounded enum rather than a sentence, because this value is published over
    HTTP and a free-text reason is how an exception message reaches a client. The
    set is deliberately about *classes* of unreadiness that GLOBIN can already
    distinguish; a later phase with exchange adapters adds members here rather than
    widening the type into prose.
    """

    READY = "ready"
    STARTING = "starting"
    STOPPING = "stopping"
    CONFIGURATION_INVALID = "configuration_invalid"
    DEPENDENCY_UNREADY = "dependency_unready"
    ENVIRONMENT_INCOMPATIBLE = "environment_incompatible"
    SECRETS_UNREADY = "secrets_unready"
    UNKNOWN = "unknown"


class ExpositionFormat(StrEnum):
    """Which metric exposition format a response is encoded in.

    Two members, and the absent ones are absent on purpose. PrometheusText1.0.0,
    OpenMetricsText0.0.1 and the protobuf protocol are all real and all things
    GLOBIN does not produce; declaring a member for one would let
    :func:`negotiate` agree to it, and answering a 1.0.0 request with 0.0.4 bytes
    under a 1.0.0 content type is worse than declining to support it.
    """

    PROMETHEUS_TEXT = "prometheus_text_0_0_4"
    OPENMETRICS_TEXT = "openmetrics_text_1_0_0"


def address_problems(text: str) -> tuple[str, ...]:
    """Judge whether a string is a literal loopback address.

    Args:
        text: The candidate.

    Returns:
        One sentence per reason it is not, empty when it is.

    Problems rather than an exception, so a caller checking a whole configuration
    reports every fault at once — the shape ``profile_problems`` and
    ``segment_problems`` already have.
    """
    if not text:
        return ("the bind address is empty",)
    try:
        parsed = ipaddress.ip_address(text)
    except ValueError:
        return (
            f"the bind address {text!r} is not an IP address; a hostname is refused "
            f"rather than resolved, because resolution is I/O and a name that "
            f"resolves to loopback today may not tomorrow",
        )
    if not parsed.is_loopback:
        return (
            f"the bind address {text!r} is not a loopback address, so binding it "
            f"could expose this process to another machine",
        )
    return ()


def policy_problems(
    *,
    port: int,
    request_timeout_seconds: int,
    shutdown_timeout_seconds: int,
    max_concurrent_requests: int,
    max_response_bytes: int,
) -> tuple[str, ...]:
    """Judge every numeric bound the surface would run under.

    Args:
        port: Which port it would bind.
        request_timeout_seconds: How long one request may occupy a worker.
        shutdown_timeout_seconds: How long in-flight requests get to finish.
        max_concurrent_requests: How many requests may be in flight at once.
        max_response_bytes: The largest body that will be sent.

    Returns:
        One sentence per unusable bound, empty when every one is fine.

    Every check is an inclusive range with both ends named in the message, so an
    operator who typed a number reads the accepted band rather than guessing at it.
    A ``bool`` is refused explicitly: it is an ``int`` to Python, and
    ``max_concurrent_requests = true`` meaning "one worker" is not a reading anybody
    intended.
    """
    checks: tuple[tuple[str, int, int, int], ...] = (
        ("port", port, MINIMUM_PORT, MAXIMUM_PORT),
        (
            "request_timeout_seconds",
            request_timeout_seconds,
            MINIMUM_TIMEOUT_SECONDS,
            MAXIMUM_TIMEOUT_SECONDS,
        ),
        (
            "shutdown_timeout_seconds",
            shutdown_timeout_seconds,
            MINIMUM_TIMEOUT_SECONDS,
            MAXIMUM_TIMEOUT_SECONDS,
        ),
        (
            "max_concurrent_requests",
            max_concurrent_requests,
            MINIMUM_CONCURRENT_REQUESTS,
            MAXIMUM_CONCURRENT_REQUESTS,
        ),
        (
            "max_response_bytes",
            max_response_bytes,
            MINIMUM_RESPONSE_BYTES,
            MAXIMUM_RESPONSE_BYTES,
        ),
    )
    problems: list[str] = []
    for name, value, low, high in checks:
        if isinstance(value, bool) or not isinstance(value, int):
            problems.append(f"{name} is {value!r}, which is not a plain int")
        elif not low <= value <= high:
            problems.append(f"{name} is {value}, which is outside {low}..{high}")
    return tuple(problems)


@dataclass(frozen=True, slots=True)
class LoopbackAddress:
    """An address this machine can reach and no other machine can.

    Args:
        text: The address as written.

    Raises:
        ValidationError: If it is not a literal loopback address.

    **The refusal is :mod:`ipaddress`'s judgement, never a string comparison.** A
    denylist of spellings has to be complete to be correct, and the spellings are
    not finite: an all-interfaces address can be written as four zeroes, as a bare
    zero, in hexadecimal, as a bare pair of colons, as an IPv4-mapped form, or as a
    single decimal integer. ``is_loopback`` is a property of the *parsed* address,
    so every one of those is refused by the same line — and ``127.0.0.2``, which is
    loopback and is not the one anybody means, is *accepted*, because it genuinely
    cannot leave this host.

    A hostname is refused rather than resolved. Resolution reaches a resolver, which
    is I/O the domain may not perform, and a name that resolves to loopback today
    can resolve elsewhere tomorrow. An address is a value; a name is a question.
    """

    text: str

    def __post_init__(self) -> None:
        """Refuse anything that is not a literal loopback address."""
        problems = address_problems(self.text)
        if problems:
            raise ValidationError("; ".join(problems))

    @property
    def is_ipv6(self) -> bool:
        """Whether this is an IPv6 address.

        Returns:
            ``True`` for ``::1`` and its relatives.

        The one thing a caller opening a socket needs that it cannot read off the
        string safely, since the address family decides which socket to create.
        """
        return ipaddress.ip_address(self.text).version == IPV6_VERSION


@dataclass(frozen=True, slots=True)
class DiagnosticsHttpPolicy:
    """Every bound the diagnostics surface operates inside.

    Args:
        address: Where it binds. A value type, so it cannot be widened.
        port: Which port it binds.
        request_timeout_seconds: How long one request may occupy a worker.
        shutdown_timeout_seconds: How long in-flight requests are given to finish.
        max_concurrent_requests: How many requests may be in flight at once, which
            is also exactly how many worker threads exist.
        max_response_bytes: The largest body that will be sent.

    Raises:
        ValidationError: If any bound is outside its permitted range.

    **A policy that could not be honoured cannot be constructed**, which is the rule
    ``RotationPolicy`` and ``WatchdogPolicy`` already follow. The reason it matters
    more here: every one of these numbers is the *only* thing standing between a
    remote caller and unbounded work, so "the limits are validated" has to be a
    property of the type rather than a step somebody remembers to run first.
    """

    address: LoopbackAddress
    port: int
    request_timeout_seconds: int
    shutdown_timeout_seconds: int
    max_concurrent_requests: int
    max_response_bytes: int

    def __post_init__(self) -> None:
        """Refuse a policy with a bound that is not usable."""
        problems = policy_problems(
            port=self.port,
            request_timeout_seconds=self.request_timeout_seconds,
            shutdown_timeout_seconds=self.shutdown_timeout_seconds,
            max_concurrent_requests=self.max_concurrent_requests,
            max_response_bytes=self.max_response_bytes,
        )
        if problems:
            raise ValidationError("; ".join(problems))


@dataclass(frozen=True, slots=True)
class MediaRange:
    """One entry from an ``Accept`` header, parsed.

    Args:
        media_type: The type and subtype, lowercased.
        version: The ``version`` parameter, lowercased, or an empty string.
        quality: The weight, in thousandths, so no float enters the comparison.
        position: Where it appeared, so ties break by client order.

    **Quality is an integer.** ADR-0068 already refuses floats in telemetry values
    for the reason that applies here too: ``q=0.9`` and ``q=0.90`` must compare
    equal and sort identically on every run, and thousandths is exactly the
    precision RFC 9110 permits a sender to express.
    """

    media_type: str
    version: str
    quality: int
    position: int


@dataclass(frozen=True, slots=True)
class DiagnosticsResponse:
    """One answer, complete, before anything has been written to a socket.

    Args:
        status: The HTTP status code.
        content_type: The exact content type the body is encoded in.
        body: The bytes a ``GET`` would receive. A ``HEAD`` sends none of them and
            still reports their length.
        route: Which route produced this, for logging and metrics.
        outcome: What happened, for logging and metrics.
        allow: The ``Allow`` header value, set only on a 405.

    **The whole body exists before the status line is sent**, which is what makes
    the size bound enforceable. A response streamed as it was rendered could only
    discover it was too large after committing to a status, and the only remaining
    move would be to truncate — producing invalid JSON, or an OpenMetrics document
    missing the terminator its specification requires.
    """

    status: int
    content_type: str
    body: bytes
    route: DiagnosticsRoute
    outcome: RequestOutcome
    allow: str = ""

    @property
    def length(self) -> int:
        """How many bytes the body is.

        Returns:
            The exact ``Content-Length`` to send, for ``GET`` and ``HEAD`` alike.
        """
        return len(self.body)

    @property
    def status_class(self) -> StatusClass:
        """This response's status class.

        Returns:
            The class, for the metric label.
        """
        return status_class(self.status)


def routes() -> tuple[DiagnosticsRoute, ...]:
    """Every route this surface can name.

    Returns:
        The six members, in serving order.

    A function rather than a constant because a layer package performs no call at
    import, so ``tuple(DiagnosticsRoute)`` is unavailable here.
    """
    return (
        DiagnosticsRoute.LIVENESS,
        DiagnosticsRoute.READY,
        DiagnosticsRoute.RUNTIME,
        DiagnosticsRoute.METRICS,
        DiagnosticsRoute.SNAPSHOT,
        DiagnosticsRoute.UNKNOWN,
    )


def route_values() -> tuple[str, ...]:
    """Every route's label value.

    Returns:
        The six values.

    The bounded value set ``globin.domain.metrics`` declares for its ``route``
    attribute. Derived from the enum rather than spelled beside it, so a seventh
    route cannot appear without the metric's declared series count changing in the
    same commit — which is what makes the cardinality arithmetic in that registry a
    computation rather than a claim.
    """
    return tuple(route.value for route in routes())


def status_class_values() -> tuple[str, ...]:
    """Every status class's label value.

    Returns:
        The three values.
    """
    return (
        StatusClass.SUCCESS.value,
        StatusClass.CLIENT_ERROR.value,
        StatusClass.SERVER_ERROR.value,
    )


def rejection_reason_values() -> tuple[str, ...]:
    """Every rejection reason's label value.

    Returns:
        The six values.
    """
    return (
        RejectionReason.ADMISSION.value,
        RejectionReason.METHOD.value,
        RejectionReason.UNKNOWN_ROUTE.value,
        RejectionReason.ROUTE_DISABLED.value,
        RejectionReason.BODY_PRESENT.value,
        RejectionReason.OVERSIZE.value,
    )


def route_paths() -> tuple[tuple[str, DiagnosticsRoute], ...]:
    """The declared mapping from request target to route.

    Returns:
        Pairs of exact path and the route it names, in serving order.

    **Exact strings, with no pattern anywhere.** There is no prefix match, no
    trailing-slash tolerance, no case folding and no normalisation, so this table is
    the complete list of targets that do anything. That is what makes directory
    traversal a non-question rather than a defended one: a target climbing out of
    the tree is not sanitised, it simply is not in the table.

    ``UNKNOWN`` has no path, which is the point of it.
    """
    return (
        ("/health/live", DiagnosticsRoute.LIVENESS),
        ("/health/ready", DiagnosticsRoute.READY),
        ("/health/runtime", DiagnosticsRoute.RUNTIME),
        ("/metrics", DiagnosticsRoute.METRICS),
        ("/diagnostics/snapshot", DiagnosticsRoute.SNAPSHOT),
    )


def normalise_path(target: str) -> DiagnosticsRoute:
    """Reduce a request target to the route it names.

    Args:
        target: The raw request target, query string and all.

    Returns:
        The route, or :attr:`DiagnosticsRoute.UNKNOWN` for anything not in the
        declared table.

    A query component is **discarded, not parsed**. Making one part of the contract
    would turn a fixed set of five documents into a query surface, and every filter
    a caller could express is work this process performs on a remote party's behalf.
    Dropping it keeps a scrape with a cache-busting parameter a scrape, without the
    parameter meaning anything.
    """
    if len(target) > MAXIMUM_TARGET_LENGTH:
        return DiagnosticsRoute.UNKNOWN
    path = target.split("?", 1)[0].split("#", 1)[0]
    for spelling, route in route_paths():
        if path == spelling:
            return route
    return DiagnosticsRoute.UNKNOWN


def method_of(raw: str) -> RouteMethod:
    """Reduce a request method to the three cases this surface distinguishes.

    Args:
        raw: The method as sent.

    Returns:
        ``GET``, ``HEAD``, or ``OTHER`` for everything else.

    Case-sensitive, because HTTP methods are. A lowercase spelling is not the
    method, and treating it as one would be this surface being more permissive than
    the protocol it implements.
    """
    if raw == RouteMethod.GET.value:
        return RouteMethod.GET
    if raw == RouteMethod.HEAD.value:
        return RouteMethod.HEAD
    return RouteMethod.OTHER


def status_class(status: int) -> StatusClass:
    """Which class a status code belongs to.

    Args:
        status: The code.

    Returns:
        The class. Anything below 400 counts as success, because this surface emits
        no 1xx and no 3xx and a code it never sends has no meaningful class.

    The two floors are :data:`STATUS_BAD_REQUEST` and :data:`STATUS_INTERNAL_ERROR`
    rather than any status this surface happens to send. Reaching for the *codes in
    use* is how a 400 gets filed as a success when it is added later, which is
    precisely what happened before this line was tested.
    """
    if status >= STATUS_INTERNAL_ERROR:
        return StatusClass.SERVER_ERROR
    if status >= STATUS_BAD_REQUEST:
        return StatusClass.CLIENT_ERROR
    return StatusClass.SUCCESS


def content_type_for(exposition: ExpositionFormat) -> str:
    """The exact content type one exposition format is served under.

    Args:
        exposition: The format.

    Returns:
        The content type string.

    Raises:
        ValidationError: If the format has no content type, which can only happen
            if :class:`ExpositionFormat` gained a member and this table did not.

    A lookup that can miss rather than a chain mypy proves exhaustive, for the
    reason ``ConfigLayout._spellings`` records: the "this was edited in half" branch
    has to stay reachable or ``warn_unreachable`` refuses the module.
    """
    declared = {
        ExpositionFormat.PROMETHEUS_TEXT: CONTENT_TYPE_PROMETHEUS,
        ExpositionFormat.OPENMETRICS_TEXT: CONTENT_TYPE_OPENMETRICS,
    }
    found = declared.get(exposition)
    if found is None:
        msg = f"exposition format {exposition!r} has no declared content type"
        raise ValidationError(msg)
    return found


def negotiate(accept: str) -> ExpositionFormat:
    """Choose the exposition format one ``Accept`` header asks for.

    Args:
        accept: The header value, which may be empty, malformed or hostile.

    Returns:
        The format to encode in. Never fails.

    **Total, and that is the specification's doing rather than a shortcut.** The
    scrape protocol's rule is *"If no fallback is specified, the target MUST use
    PrometheusText0.0.4 as a last resort"*, so there is no 406 to send and no error
    to report — an unusable header and an absent one both land on the same answer.
    Ledger entry S-01.

    Selection is *"the protocol in the Accept header with the highest weighting that
    is supported"*. Ties break on the order the client wrote them, so two ranges of
    equal weight resolve the way the client listed them rather than the way a
    dictionary happened to iterate.

    ``escaping=`` is read past and discarded. It is a parameter of the
    1.0.0-and-above formats, and GLOBIN produces neither, so honouring it would be
    agreeing to a protocol it does not speak.
    """
    if not accept or len(accept) > MAXIMUM_ACCEPT_LENGTH:
        return ExpositionFormat.PROMETHEUS_TEXT
    eligible: list[tuple[int, int, ExpositionFormat]] = []
    for entry in media_ranges(accept):
        matched = format_for(entry)
        if matched is not None:
            eligible.append((entry.quality, entry.position, matched))
    if not eligible:
        return ExpositionFormat.PROMETHEUS_TEXT
    best = min(eligible, key=lambda item: (-item[0], item[1]))
    return best[2]


def media_ranges(accept: str) -> tuple[MediaRange, ...]:
    """Parse an ``Accept`` header into weighted media ranges.

    Args:
        accept: The header value.

    Returns:
        Every range parsed, up to :data:`MAXIMUM_ACCEPT_ITEMS`, in client order.

    Never raises. A range this cannot make sense of is dropped rather than poisoning
    the header, because one unparseable entry among five is a client offering four
    things GLOBIN might be able to serve.
    """
    parsed: list[MediaRange] = []
    for position, chunk in enumerate(accept.split(",")):
        if position >= MAXIMUM_ACCEPT_ITEMS:
            break
        pieces = [piece.strip() for piece in chunk.split(";")]
        media_type = pieces[0].lower()
        if not media_type:
            continue
        version = ""
        quality = FULL_QUALITY
        for piece in pieces[1:]:
            name, separator, value = piece.partition("=")
            if not separator:
                continue
            lowered = name.strip().lower()
            if lowered == VERSION_PARAMETER:
                version = value.strip().lower()
            elif lowered == QUALITY_PARAMETER:
                quality = quality_of(value.strip())
        parsed.append(
            MediaRange(media_type=media_type, version=version, quality=quality, position=position)
        )
    return tuple(parsed)


def quality_of(value: str) -> int:
    """Read a q-value as thousandths.

    Args:
        value: The parameter's text.

    Returns:
        The weight in thousandths, or zero when it cannot be read.

    **Unreadable means zero, and zero means unacceptable.** RFC 9110 gives ``q=0``
    exactly that meaning, so treating a malformed weight as "not offered" reuses a
    reading the protocol already has rather than inventing a lenient one. The
    alternative — defaulting a broken weight to full — would let a mangled header
    outrank a well-formed one.

    ``1`` may only be followed by zeroes, which is the grammar rather than
    pedantry: ``q=1.5`` is not a stronger preference than ``q=1``, it is a sender
    that has misunderstood the range, and clamping it would reward the mistake.

    **:meth:`str.isdecimal` rather than :meth:`str.isdigit`.** ``isdigit`` is true
    for characters :func:`int` refuses — a superscript two among them — so the pair
    ``isdigit`` then ``int`` raises on input it had just declared acceptable. A
    property test over generated text found exactly that, in a function whose whole
    contract is that it never raises.
    """
    whole, separator, fraction = value.partition(".")
    if not whole.isdecimal():
        return 0
    units = int(whole)
    if units > 1:
        return 0
    if not separator:
        return units * FULL_QUALITY
    if fraction and not fraction.isdecimal():
        return 0
    if len(fraction) > QUALITY_DIGITS:
        return 0
    thousandths = int((fraction + "000")[:QUALITY_DIGITS]) if fraction else 0
    if units == 1 and thousandths:
        return 0
    return units * FULL_QUALITY + thousandths


def format_for(entry: MediaRange) -> ExpositionFormat | None:
    """Which format, if any, one media range asks for.

    Args:
        entry: The parsed range.

    Returns:
        The format, or ``None`` when GLOBIN produces nothing this range accepts.

    A version parameter naming something other than what GLOBIN produces is a
    **non-match**, not a near-match. ``text/plain`` at version 1.0.0 is
    PrometheusText1.0.0, which this repository does not encode; answering it with
    0.0.4 bytes would be a lie told in a header.
    """
    if entry.quality == 0:
        return None
    wildcards = {
        MEDIA_RANGE_ANY: ExpositionFormat.PROMETHEUS_TEXT,
        MEDIA_RANGE_TEXT: ExpositionFormat.PROMETHEUS_TEXT,
        MEDIA_RANGE_APPLICATION: ExpositionFormat.OPENMETRICS_TEXT,
    }
    wildcard = wildcards.get(entry.media_type)
    if wildcard is not None:
        return wildcard
    exact = {
        MEDIA_TYPE_PROMETHEUS: (VERSION_PROMETHEUS_TEXT, ExpositionFormat.PROMETHEUS_TEXT),
        MEDIA_TYPE_OPENMETRICS: (VERSION_OPENMETRICS_TEXT, ExpositionFormat.OPENMETRICS_TEXT),
    }
    found = exact.get(entry.media_type)
    if found is None:
        return None
    produced, matched = found
    return matched if entry.version in {"", produced} else None
