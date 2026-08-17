"""Turning one diagnostics request into one response, with no socket in sight.

This is the whole behaviour of GLOBIN's diagnostics surface: which route a target
names, whether that route is switched on, what its body is, how large the body is
allowed to be, and what gets recorded about having answered. Every one of those is
decidable from values, so all of it is here and none of it is near a connection.

**That is what makes this feature testable offline.** The suite's autouse guard
turns an outbound connection into a failure, and almost every test of this surface
never wants one: a test calls :meth:`DiagnosticsService.handle` with a method, a
target and an ``Accept`` header, and reads back a status, a content type and a body.
`adapters/diagnostics_http.py` is then left with one question — does the socket
plumbing hand these three strings over and write these bytes back — which is what
the handful of integration tests over a real loopback socket exist to answer.

**The body is complete before a status exists.** Nothing is streamed. A response
rendered incrementally could only discover it had exceeded its size bound after
committing to a status line, and the only remaining move would be to truncate —
producing invalid JSON, or an OpenMetrics document missing the terminator its
specification requires. Rendering into a buffer first is what turns "bounded
responses" into a fact.

**The recording order is fixed and stated rather than left to reading.** Inflight is
the adapter's, because only the adapter knows when a request was admitted. Everything
else happens here, *after* the body exists and before it is returned: the request
counter, the duration, the bytes. That ordering is why a ``/metrics`` scrape cannot
recurse — the exposition is rendered from a snapshot taken before this request's own
counters move, so a scrape reports the state as of its own arrival rather than
chasing a number it is itself changing.
"""

import json
from dataclasses import dataclass

from globin.application.observability import Logger
from globin.domain.clock import MonotonicReading
from globin.domain.configuration import DiagnosticsHttpConfig
from globin.domain.diagnostics_http import (
    ALLOWED_METHODS,
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_TEXT,
    SCHEMA,
    SCHEMA_VERSION,
    STATUS_BAD_REQUEST,
    STATUS_INTERNAL_ERROR,
    STATUS_METHOD_NOT_ALLOWED,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    DiagnosticsResponse,
    DiagnosticsRoute,
    ReadinessReason,
    RejectionReason,
    RequestOutcome,
    RouteMethod,
    content_type_for,
    method_of,
    negotiate,
    normalise_path,
)
from globin.ports.clock import MonotonicClock
from globin.ports.diagnostics_http import (
    HealthProjection,
    LivenessProbe,
    MetricsExposition,
    ReadinessProbe,
    SnapshotProjection,
)
from globin.ports.telemetry import MetricRecorder

METRIC_REQUESTS: str = "globin.diagnostics.http.requests.total"
"""Requests answered, by route and status class."""

METRIC_DURATION: str = "globin.diagnostics.http.request.nanoseconds"
"""How long answering took, by route."""

METRIC_REJECTED: str = "globin.diagnostics.http.rejected.total"
"""Requests refused, by the rule that refused them."""

METRIC_RESPONSE_BYTES: str = "globin.diagnostics.http.response.bytes.total"
"""Bytes of body sent, by route."""

METRIC_INFLIGHT: str = "globin.diagnostics.http.inflight"
"""Requests in flight. Recorded by the adapter, which is what knows."""

EVENT_REQUEST: str = "diagnostics.http.request"
"""One answered request. Carries the normalised route, never the target."""

EVENT_REFUSED: str = "diagnostics.http.refused"
"""One refused request, with a bounded reason."""

EVENT_FAILED: str = "diagnostics.http.failed"
"""One request whose handler raised. The exception is recorded here and not sent."""

BODY_TOO_LARGE: bytes = b"the response exceeded its configured size bound\n"
"""What an oversized response says instead of a truncated document.

Small enough to fit inside any permitted bound, so the refusal itself can never
trigger the condition it reports.
"""

BODY_INTERNAL_ERROR: bytes = b"the diagnostic could not be produced\n"
"""What a failed handler says. Deliberately identical for every cause.

A client learns that something went wrong and nothing about what, because the
alternative is an exception message on a socket — and Phase 023 already records that
redaction is by field name, so a credential inside an exception message would be
written verbatim.
"""

BODY_NOT_FOUND: bytes = b"no such diagnostic\n"
"""What an unrecognised target gets. It does not echo the target."""

BODY_METHOD_NOT_ALLOWED: bytes = b"only GET and HEAD are served\n"
"""What an unsupported method gets. It does not echo the method."""

BODY_BAD_REQUEST: bytes = b"this surface reads no request body\n"
"""What a request carrying a body gets. It does not echo anything it carried."""

_REFUSAL_BODIES: dict[int, bytes] = {
    STATUS_BAD_REQUEST: BODY_BAD_REQUEST,
    STATUS_METHOD_NOT_ALLOWED: BODY_METHOD_NOT_ALLOWED,
    STATUS_NOT_FOUND: BODY_NOT_FOUND,
}
"""Which constant body each refusal status carries.

A table rather than a chain, so a status added without a body is a lookup that misses
and falls back to the safe one rather than a branch somebody forgot to extend.
"""


@dataclass(frozen=True, slots=True)
class DiagnosticsService:
    """Answers one diagnostics request, and records that it did.

    Args:
        surface: The resolved settings — which routes answer, and the size bound.
        liveness: Whether the process is live.
        readiness: Whether the process is ready.
        health: The runtime health document.
        snapshot: The fuller diagnostics document.
        exposition: The metric encoder.
        recorder: Where this surface's own measurements go.
        logger: Where a structured access record goes.
        monotonic: How a duration is measured.

    Frozen and holding no request state: everything about one request lives in the
    arguments to :meth:`handle` and in the value it returns. Two concurrent requests
    through one service are therefore independent, which is what lets the adapter's
    worker pool share a single instance.
    """

    surface: DiagnosticsHttpConfig
    liveness: LivenessProbe
    readiness: ReadinessProbe
    health: HealthProjection
    snapshot: SnapshotProjection
    exposition: MetricsExposition
    recorder: MetricRecorder
    logger: Logger
    monotonic: MonotonicClock

    def handle(
        self, method: str, target: str, accept: str = "", *, has_body: bool = False
    ) -> DiagnosticsResponse:
        """Answer one request.

        Args:
            method: The request method, as sent.
            target: The request target, query string and all.
            accept: The ``Accept`` header, or an empty string when absent.
            has_body: Whether the request carried a body or announced one.

        Returns:
            The complete response. **Never raises**: a handler that failed becomes a
            small 500, because an exception escaping here would reach a worker thread
            and the only thing a worker can do with one is die.

        The order of the checks is the order of the costs. Method and body are
        properties of the request line and headers, so they are settled before a route
        is even looked up; the route is settled before anything is rendered; and the
        size bound is checked before anything is returned. Nothing expensive happens
        for a request that was never going to be served.
        """
        started = self.monotonic.reading()
        route = normalise_path(target)
        verb = method_of(method)
        response = self._answer(verb, route, accept, has_body=has_body)
        self._record(response, started)
        return response

    def _answer(
        self, verb: RouteMethod, route: DiagnosticsRoute, accept: str, *, has_body: bool
    ) -> DiagnosticsResponse:
        """Produce the response, refusals first.

        Args:
            verb: The reduced method.
            route: The named route.
            accept: The ``Accept`` header.
            has_body: Whether a body was present or announced.

        Returns:
            The response.
        """
        if has_body:
            return self._refused(route, RejectionReason.BODY_PRESENT, STATUS_BAD_REQUEST)
        if verb is RouteMethod.OTHER:
            return self._refused(route, RejectionReason.METHOD, STATUS_METHOD_NOT_ALLOWED)
        if route is DiagnosticsRoute.UNKNOWN:
            return self._refused(route, RejectionReason.UNKNOWN_ROUTE, STATUS_NOT_FOUND)
        if not self._enabled(route):
            return self._refused(route, RejectionReason.ROUTE_DISABLED, STATUS_NOT_FOUND)
        try:
            return self._bounded(self._route_response(route, accept))
        except Exception as fault:
            # A handler exception may not leave this method. It is recorded through
            # Phase 023's logger, where redaction by field name applies, and answered
            # with a body that is the same for every cause. `except Exception` is the
            # honest spelling of "this is the outer boundary of a request": narrowing
            # it would leave some other exception type to reach a worker thread, and
            # the only thing a worker can do with one is stop being a worker.
            self.logger.error(  # noqa: TRY400 -- GLOBIN's Logger has no `exception`
                EVENT_FAILED, route=route.value, fault=type(fault).__name__
            )
            return DiagnosticsResponse(
                status=STATUS_INTERNAL_ERROR,
                content_type=CONTENT_TYPE_TEXT,
                body=BODY_INTERNAL_ERROR,
                route=route,
                outcome=RequestOutcome.ERROR,
            )

    def _route_response(self, route: DiagnosticsRoute, accept: str) -> DiagnosticsResponse:
        """The response one enabled route produces.

        Args:
            route: The route, already known to be enabled.
            accept: The ``Accept`` header.

        Returns:
            The response, before its size has been checked.

        Raises:
            InternalError: If the route has no handler, which can only happen if
                :class:`~globin.domain.diagnostics_http.DiagnosticsRoute` gained a
                member and this mapping did not.
        """
        if route is DiagnosticsRoute.LIVENESS:
            return self._liveness()
        if route is DiagnosticsRoute.READY:
            return self._ready()
        if route is DiagnosticsRoute.RUNTIME:
            return self._document(route, self.health.document())
        if route is DiagnosticsRoute.SNAPSHOT:
            return self._document(route, self.snapshot.document())
        return self._metrics(accept)

    def _liveness(self) -> DiagnosticsResponse:
        """The liveness answer, which depends on nothing outside this process.

        Returns:
            ``200`` while the process is live, ``503`` once it is stopping.

        **The payload is four fields and none of them is measured.** No path, no host
        name, no command line, no environment, and no instantaneous reading — because
        a supervisor polling this every second must not be able to make the process do
        work, and because every one of those fields is something Phase 023's redaction
        would have had to be trusted to catch.
        """
        alive = self.liveness.alive()
        return self._document(
            DiagnosticsRoute.LIVENESS,
            {"live": alive, "status": "live" if alive else "stopping"},
            status=STATUS_OK if alive else STATUS_UNAVAILABLE,
        )

    def _ready(self) -> DiagnosticsResponse:
        """The readiness answer.

        Returns:
            ``200`` when ready, ``503`` with a bounded reason when not.

        **A truthful 503 is a success**, which is why the outcome recorded is
        ``SUCCESS`` while the status class is ``5xx``. Conflating the two would make a
        healthy process that has not finished starting look broken on a dashboard.
        """
        reason = self.readiness.readiness()
        ready = reason is ReadinessReason.READY
        return self._document(
            DiagnosticsRoute.READY,
            {"ready": ready, "reason": reason.value},
            status=STATUS_OK if ready else STATUS_UNAVAILABLE,
        )

    def _metrics(self, accept: str) -> DiagnosticsResponse:
        """The scrape answer, in whichever format was negotiated.

        Args:
            accept: The ``Accept`` header.

        Returns:
            The exposition, under the content type that matches how it was encoded.

        The content type comes from the same enum the encoder was chosen by, so the
        header and the bytes cannot disagree about which format this is.
        """
        chosen = negotiate(accept)
        return DiagnosticsResponse(
            status=STATUS_OK,
            content_type=content_type_for(chosen),
            body=self.exposition.render(chosen).encode("utf-8"),
            route=DiagnosticsRoute.METRICS,
            outcome=RequestOutcome.SUCCESS,
        )

    def _document(
        self, route: DiagnosticsRoute, payload: dict[str, object], status: int = STATUS_OK
    ) -> DiagnosticsResponse:
        """One JSON response, rendered canonically.

        Args:
            route: Which route produced it.
            payload: The document's own fields.
            status: The status code.

        Returns:
            The response.

        Every document carries a schema and its version, so a consumer can tell what to
        parse a body as without guessing from the fields present.

        **A projection's own schema wins, and that is deliberate rather than an
        accident of ordering.** ``/health/runtime`` publishes the Phase 024 health
        snapshot, which already declares ``globin.health.snapshot``; stamping this
        surface's name over it would tell a consumer to parse a health document as an
        endpoint document. The endpoint's schema is therefore a *default* for the
        documents this surface invents — liveness, readiness, the combined snapshot —
        and a passthrough for the ones it merely carries.

        Sorted keys and no incidental whitespace, matching ``render_state_document``
        and ``render_snapshot_json``: two runs producing the same values produce the
        same bytes.
        """
        body = json.dumps(
            {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, **payload},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return DiagnosticsResponse(
            status=status,
            content_type=CONTENT_TYPE_JSON,
            body=body.encode("utf-8"),
            route=route,
            outcome=RequestOutcome.SUCCESS,
        )

    def _bounded(self, response: DiagnosticsResponse) -> DiagnosticsResponse:
        """Refuse a response that is larger than the configured bound.

        Args:
            response: The rendered response.

        Returns:
            It, or a small refusal in its place.

        A refusal rather than a truncation. Half a JSON document is not a smaller
        answer, and an OpenMetrics exposition without its terminator is refused by
        every conforming parser — so the failure mode of truncating is a consumer that
        errors on data it cannot tell apart from corruption.
        """
        if response.length <= self.surface.max_response_bytes:
            return response
        self.recorder.count(METRIC_REJECTED, reason=RejectionReason.OVERSIZE.value)
        self.logger.warning(
            EVENT_REFUSED,
            route=response.route.value,
            reason=RejectionReason.OVERSIZE.value,
            bytes_rendered=response.length,
            bytes_permitted=self.surface.max_response_bytes,
        )
        return DiagnosticsResponse(
            status=STATUS_INTERNAL_ERROR,
            content_type=CONTENT_TYPE_TEXT,
            body=BODY_TOO_LARGE,
            route=response.route,
            outcome=RequestOutcome.ERROR,
        )

    def _refused(
        self, route: DiagnosticsRoute, reason: RejectionReason, status: int
    ) -> DiagnosticsResponse:
        """One refusal, counted and logged with a bounded reason.

        Args:
            route: The route, which is ``unknown`` for an unrecognised target.
            reason: Why it was refused.
            status: The status code.

        Returns:
            The refusal.

        **A disabled route answers 404 rather than 403 or 503**, and that is
        deliberate: from outside, a route that is switched off is indistinguishable
        from one that does not exist, and telling a caller which diagnostics an
        operator chose to withhold is information they have no use for.
        """
        self.recorder.count(METRIC_REJECTED, reason=reason.value)
        self.logger.info(EVENT_REFUSED, route=route.value, reason=reason.value, status=status)
        body = _REFUSAL_BODIES.get(status, BODY_NOT_FOUND)
        return DiagnosticsResponse(
            status=status,
            content_type=CONTENT_TYPE_TEXT,
            body=body,
            route=route,
            outcome=RequestOutcome.REJECTED,
            allow=ALLOWED_METHODS if status == STATUS_METHOD_NOT_ALLOWED else "",
        )

    def _enabled(self, route: DiagnosticsRoute) -> bool:
        """Whether one route answers under the current settings.

        Args:
            route: The route.

        Returns:
            Whether it is switched on.
        """
        if route is DiagnosticsRoute.METRICS:
            return self.surface.metrics_enabled
        if route is DiagnosticsRoute.SNAPSHOT:
            return self.surface.diagnostics_snapshot_enabled
        return self.surface.health_enabled

    def _record(self, response: DiagnosticsResponse, started: MonotonicReading) -> None:
        """Record what answering one request cost and what it concluded.

        Args:
            response: What is about to be returned.
            started: The monotonic reading taken on arrival.

        Every dimension here is an enum value. The target, the query, the peer address
        and every header are absent by construction rather than by filtering, which is
        what keeps a remote party from choosing a label — ADR-0068's cardinality
        argument applied to the one surface a remote party can reach.

        The elapsed time is clamped at zero. ``MonotonicReading`` promises only that
        the *difference* between two readings is meaningful, and a platform clock that
        went backwards should record an implausible zero rather than a negative
        duration a histogram would refuse.
        """
        route = response.route.value
        self.recorder.count(METRIC_REQUESTS, route=route, status_class=response.status_class.value)
        self.recorder.count(METRIC_RESPONSE_BYTES, response.length, route=route)
        elapsed = self.monotonic.reading().nanoseconds - started.nanoseconds
        self.recorder.observe(METRIC_DURATION, max(elapsed, 0), route=route)
        self.logger.info(
            EVENT_REQUEST,
            route=route,
            status=response.status,
            status_class=response.status_class.value,
            outcome=response.outcome.value,
            bytes=response.length,
        )
