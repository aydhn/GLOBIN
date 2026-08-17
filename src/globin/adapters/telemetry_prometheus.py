"""The only module in GLOBIN that may name `prometheus_client`.

Same shape as `telemetry_otel.py` and for the same reason: the library is absent
on every CI run, so the import sits inside a function and the absence is a
recorded state.

**The name mapping is DECLARED, never derived, and that is a correctness argument
rather than a stylistic one.** `globin.export.batches_offered` and
`globin.export.batches.offered` both sanitise to `globin_export_batches_offered`.
A derived mapping merges two distinct series into one, and the merge is invisible
in the code, invisible in the diff, and shows up as a wrong number on somebody's
dashboard six months later. A declared table makes that collision a failing test.

**The listener binds `127.0.0.1` as a literal, and nothing can widen it.**
`prometheus_client.start_http_server` defaults its address to `0.0.0.0` — every
interface, not this machine — which is exactly the class of mitigation this
repository refuses to leave to somebody remembering. There is no address setting,
the listener is off unless explicitly enabled, and a default bootstrap opens
nothing.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from globin.domain.metrics import MetricDescriptor, metrics
from globin.domain.telemetry import MetricKind, unit_specification
from globin.domain.telemetry_delivery import ExportOutcome

REASON_PROMETHEUS_ABSENT: str = "PROMETHEUS_LIBRARY_ABSENT"
"""No prometheus_client package is installed on this host."""

REASON_PROMETHEUS_PRESENT: str = "PROMETHEUS_LIBRARY_PRESENT"
"""The library is importable."""

LOOPBACK_ADDRESS: Final[str] = "127.0.0.1"
"""The only address GLOBIN will ever bind.

A literal rather than a setting. The library's own default is `0.0.0.0`, so a
configurable address would be one typo away from publishing this process's
internals to the network — and there is no operational reason GLOBIN needs one.
"""

MINIMUM_PORT: Final[int] = 1_024
"""The lowest port a listener may use; below this needs privilege on most hosts."""

MAXIMUM_PORT: Final[int] = 65_535
"""The highest port a listener may use."""


def prometheus_name(descriptor: MetricDescriptor) -> str:
    """The Prometheus spelling of one family.

    Args:
        descriptor: The family.

    Returns:
        A name matching Prometheus's published grammar.

    Derived here **only** because the declared table below is checked against it
    for collisions in both directions; the table is what a reviewer reads, and
    `test_telemetry_interop_contract.py` fails if any two families collide.
    """
    return descriptor.name.replace(".", "_")


def prometheus_mapping() -> tuple[tuple[str, str, str, str], ...]:
    """Every family, as Prometheus would name it.

    Returns:
        Tuples of ``(globin name, prometheus name, type, unit)``.
    """
    types = {
        MetricKind.COUNTER: "counter",
        MetricKind.GAUGE: "gauge",
        MetricKind.HISTOGRAM: "histogram",
    }
    return tuple(
        (
            descriptor.name,
            prometheus_name(descriptor),
            types[descriptor.kind],
            unit_specification(descriptor.unit).exporter_name,
        )
        for descriptor in metrics()
    )


def render_exposition(document: dict[str, object]) -> str:
    """One snapshot as Prometheus text exposition.

    Args:
        document: A telemetry snapshot document.

    Returns:
        The exposition text, ending in a newline.

    Written here rather than delegated so that the **textfile** route works with no
    library at all: an operator's node_exporter reads a file, and requiring a
    dependency to produce one would make the simplest deployment the most fragile.
    """
    lines: list[str] = []
    families = document.get("families")
    if not isinstance(families, list):
        return ""
    declared = {name: (spelling, kind) for name, spelling, kind, _ in prometheus_mapping()}
    for family in families:
        if not isinstance(family, dict):
            continue
        name = family.get("name")
        points = family.get("points")
        if not isinstance(name, str) or not isinstance(points, list):
            continue
        found = declared.get(name)
        if found is None:
            continue
        spelling, kind = found
        lines.append(f"# TYPE {spelling} {kind}")
        for point in points:
            if isinstance(point, dict):
                lines.extend(_point_lines(spelling, point))
    return "\n".join(lines) + "\n" if lines else ""


def _point_lines(spelling: str, point: dict[str, object]) -> list[str]:
    """The exposition lines one point produces.

    Args:
        spelling: The Prometheus metric name.
        point: The point document.

    Returns:
        Zero or more lines.
    """
    labels = _labels(point.get("series"))
    value = point.get("value")
    if isinstance(value, int):
        return [f"{spelling}{labels} {value}"]
    count = point.get("count")
    total = point.get("total")
    if isinstance(count, int) and isinstance(total, int):
        return [f"{spelling}_count{labels} {count}", f"{spelling}_sum{labels} {total}"]
    return []


def _labels(series: object) -> str:
    """A series key rendered as a Prometheus label set.

    Args:
        series: The series key, ``key=value`` pairs joined by commas.

    Returns:
        The label set, or an empty string when there are no dimensions.

    The attribute alphabet excludes quotes, backslashes and newlines, which is
    what makes this safe without escaping — and a contract test asserts that
    property of the alphabet rather than trusting this comment.
    """
    if not isinstance(series, str) or not series:
        return ""
    pairs = []
    for part in series.split(","):
        key, _, value = part.partition("=")
        pairs.append(f'{key}="{value}"')
    return "{" + ",".join(pairs) + "}"


@dataclass(frozen=True, slots=True)
class UnavailablePrometheus:
    """What stands in when the library is not installed."""

    reason: str = REASON_PROMETHEUS_ABSENT

    @property
    def available(self) -> bool:
        """Whether the library is present.

        Returns:
            Always ``False``.
        """
        return False

    def offer(self, batch: Sequence[dict[str, object]]) -> ExportOutcome:
        """Refuse permanently, since an absent library will not appear.

        Args:
            batch: Ignored.

        Returns:
            Always a permanent failure.
        """
        del batch
        return ExportOutcome.PERMANENT_FAILURE

    def close(self) -> None:
        """Release nothing."""


@dataclass(slots=True)
class PrometheusPublisher:
    """Holds the newest exposition text, and optionally serves it on loopback.

    Args:
        registry: The library's collector registry.
        latest: The most recent exposition text.
        server: The running server, or ``None`` when no listener was started.
        reason: Why this publisher exists in the state it does.
    """

    registry: Any
    latest: str = ""
    server: Any = None
    reason: str = REASON_PROMETHEUS_PRESENT

    @property
    def available(self) -> bool:
        """Whether the library is present.

        Returns:
            Always ``True``.
        """
        return True

    @property
    def listening(self) -> bool:
        """Whether a socket is bound.

        Returns:
            Whether a listener was started.
        """
        return self.server is not None

    def offer(self, batch: Sequence[dict[str, object]]) -> ExportOutcome:
        """Keep the newest snapshot's exposition text.

        Args:
            batch: Telemetry snapshot documents.

        Returns:
            What happened. Never raises.
        """
        try:
            for document in batch:
                self.latest = render_exposition(document)
        except Exception:
            return ExportOutcome.TEMPORARY_FAILURE
        return ExportOutcome.DELIVERED

    def close(self) -> None:
        """Shut a listener down, if one was started. Idempotent, never raises."""
        server = self.server
        self.server = None
        if server is None:
            return
        try:
            server.shutdown()
        except Exception:
            return


def port_problems(port: int) -> tuple[str, ...]:
    """Judge a listener port.

    Args:
        port: The candidate.

    Returns:
        One sentence per reason it is unusable, empty when it is fine.
    """
    if isinstance(port, bool) or not isinstance(port, int):
        return (f"the port {port!r} is not a plain int",)
    if not MINIMUM_PORT <= port <= MAXIMUM_PORT:
        return (f"the port {port} is outside {MINIMUM_PORT}..{MAXIMUM_PORT}",)
    return ()


def prometheus_publisher() -> UnavailablePrometheus | PrometheusPublisher:
    """A publisher that holds text and binds nothing.

    Returns:
        A working publisher when the library is importable, and an object that says
        why when it is not.

    **No listener.** Starting one is :func:`start_loopback_listener`'s job and is
    never a side effect of asking for a publisher, so a default bootstrap opens no
    socket by construction rather than by configuration.
    """
    try:
        from prometheus_client import CollectorRegistry
    except ImportError:
        return UnavailablePrometheus()
    return PrometheusPublisher(registry=CollectorRegistry())


def start_loopback_listener(publisher: PrometheusPublisher, port: int) -> bool:
    """Bind a scrape endpoint on loopback only.

    Args:
        publisher: The publisher whose registry is served.
        port: Which port, validated before anything binds.

    Returns:
        Whether a listener started.

    Raises:
        ValueError: If the port is out of range.

    **`127.0.0.1` is a literal here and there is no way to change it.** The
    library's own default is `0.0.0.0`; passing the loopback address explicitly is
    the whole security posture of this function, and the absence of an address
    parameter is what stops a later edit widening it by accident.
    """
    problems = port_problems(port)
    if problems:
        raise ValueError("; ".join(problems))
    from prometheus_client import start_http_server

    server, _ = start_http_server(port, addr=LOOPBACK_ADDRESS, registry=publisher.registry)
    publisher.server = server
    return True
