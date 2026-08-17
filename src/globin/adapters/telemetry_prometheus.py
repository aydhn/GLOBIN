"""The only module in GLOBIN that may name `prometheus_client`, and both encoders.

Same shape as `telemetry_otel.py` and for the same reason: the library is absent
on every CI run, so the import sits inside a function and the absence is a
recorded state.

**The name mapping is DECLARED, never derived, and that is a correctness argument
rather than a stylistic one.** `globin.export.batches_offered` and
`globin.export.batches.offered` both sanitise to `globin_export_batches_offered`.
A derived mapping merges two distinct series into one, and the merge is invisible
in the code, invisible in the diff, and shows up as a wrong number on somebody's
dashboard six months later. A declared table makes that collision a failing test.

**Both encoders are written here and neither needs the library.** That is what lets
every route work with nothing installed: the textfile route writes a file an
operator's node_exporter reads, and Phase 027's `/metrics` serves the same bytes
over loopback. Requiring a dependency to produce either would make the simplest
deployment the most fragile.

**The two formats differ in more than a header, and the differences are the
specification's rather than this module's.** Under OpenMetrics 1.0 a counter's
MetricFamily is named without `_total` while *"the MetricPoint's Total Value Sample
MetricName MUST have the suffix `_total`"*, a histogram MUST expose cumulative
`_bucket` samples including `le="+Inf"`, and *"Expositions MUST end with EOF"*.
Prometheus text 0.0.4 has none of those rules. Ledger entry S-02.

**No `# UNIT` line is emitted, and that is a decision rather than an omission.**
The specification's unit rule is conditional — *"If a unit is specified it MUST be
provided in a UNIT metadata line. In addition, an underscore and the unit MUST be
the suffix of the MetricFamily name."* GLOBIN's durations are integer nanoseconds
by ADR-0068, so a family named `..._nanoseconds` carrying a UNIT line of `s` would
be a false claim about its own numbers, and the alternatives — renaming or
rescaling — reopen a Phase 026 decision to satisfy an optional line. Omitting it is
conformant; stating a unit the values are not in would not be.

**Phase 026's listener is gone.** `start_loopback_listener` bound a socket through
`prometheus_client.start_http_server` and served a `CollectorRegistry` that GLOBIN
never populated, so it would have answered a scrape with an empty exposition. It had
no production caller. Phase 027 built the endpoint properly, in
`adapters/diagnostics_http.py`, and two routes to a socket — one working, one
dormant — is the second independent source of truth this repository refuses.
`tests/architecture/test_library_discipline.py` now forbids `start_http_server`
along with every other route. ADR-0072 records it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from globin.domain.diagnostics_http import OPENMETRICS_TERMINATOR
from globin.domain.metrics import COUNTER_SUFFIX, MetricDescriptor, metrics
from globin.domain.telemetry import MetricKind, unit_specification
from globin.domain.telemetry_delivery import ExportOutcome

BUCKET_LABEL: Final[str] = "le"
"""The label naming a histogram bucket's upper bound, inclusive."""

POSITIVE_INFINITY: Final[str] = "+Inf"
"""The upper bound of the bucket that catches everything.

Spelled exactly as the specification requires. A histogram whose samples omit this
bucket is not a histogram with one fewer bucket — it is one whose total is missing.
"""

REASON_PROMETHEUS_ABSENT: str = "PROMETHEUS_LIBRARY_ABSENT"
"""No prometheus_client package is installed on this host."""

REASON_PROMETHEUS_PRESENT: str = "PROMETHEUS_LIBRARY_PRESENT"
"""The library is importable."""


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


def _labels(series: object, extra: tuple[tuple[str, str], ...] = ()) -> str:
    """A series key rendered as a Prometheus label set.

    Args:
        series: The series key, ``key=value`` pairs joined by commas.
        extra: Further label pairs to append, for the ``le`` a bucket carries.

    Returns:
        The label set, or an empty string when there are no dimensions at all.

    The attribute alphabet excludes quotes, backslashes and newlines, which is
    what makes this safe without escaping — and a contract test asserts that
    property of the alphabet rather than trusting this comment. ``extra`` is only
    ever supplied from this module's own bucket rendering, so it carries the same
    guarantee for the same reason: nothing a caller wrote reaches it.
    """
    pairs = []
    if isinstance(series, str) and series:
        for part in series.split(","):
            key, _, value = part.partition("=")
            pairs.append(f'{key}="{value}"')
    pairs.extend(f'{key}="{value}"' for key, value in extra)
    if not pairs:
        return ""
    return "{" + ",".join(pairs) + "}"


def openmetrics_name(descriptor: MetricDescriptor) -> str:
    """The OpenMetrics MetricFamily name for one family.

    Args:
        descriptor: The family.

    Returns:
        The family name, which for a counter is the Prometheus spelling with the
        ``_total`` suffix removed.

    **The suffix moves from the family to the sample, and that is the specification
    rather than a preference.** Under OpenMetrics a counter family named
    ``x`` exposes a sample named ``x_total``; GLOBIN's registry already requires every
    counter's *own* name to end in ``total``, so leaving it on the family would
    produce ``x_total_total`` on the sample. The samples the two encoders emit are
    therefore identical for a counter — it is only the metadata lines that differ.
    """
    spelling = prometheus_name(descriptor)
    if descriptor.kind is MetricKind.COUNTER:
        return spelling.removesuffix(f"_{COUNTER_SUFFIX}")
    return spelling


def openmetrics_mapping() -> tuple[tuple[str, str, str, str], ...]:
    """Every family, as OpenMetrics would name and describe it.

    Returns:
        Tuples of ``(globin name, family name, type, description)``.

    The description is here and absent from :func:`prometheus_mapping` because only
    this encoder emits a ``# HELP`` line. Phase 026's exposition carried types alone,
    and a reader of a scrape had to know what a family meant from somewhere else.
    """
    types = {
        MetricKind.COUNTER: "counter",
        MetricKind.GAUGE: "gauge",
        MetricKind.HISTOGRAM: "histogram",
    }
    return tuple(
        (
            descriptor.name,
            openmetrics_name(descriptor),
            types[descriptor.kind],
            descriptor.description,
        )
        for descriptor in metrics()
    )


def render_openmetrics(document: dict[str, object]) -> str:
    """One snapshot as an OpenMetrics 1.0 exposition.

    Args:
        document: A telemetry snapshot document.

    Returns:
        The exposition text, always ending in ``# EOF`` and a newline — including
        when there is nothing to report, because an empty document is still a valid
        exposition and a *missing terminator* is not.

    Written without the library for the reason the module docstring gives. What it
    adds over :func:`render_exposition`: a ``# HELP`` line per family, the counter
    family/sample split, cumulative bucket samples, and the terminator.
    """
    lines: list[str] = []
    families = document.get("families")
    declared = {
        name: (family, kind, description)
        for name, family, kind, description in openmetrics_mapping()
    }
    if isinstance(families, list):
        for family in families:
            if isinstance(family, dict):
                lines.extend(_openmetrics_family(family, declared))
    return "\n".join(lines) + ("\n" if lines else "") + OPENMETRICS_TERMINATOR


def _openmetrics_family(
    family: dict[str, object], declared: dict[str, tuple[str, str, str]]
) -> list[str]:
    """The OpenMetrics lines one family produces.

    Args:
        family: The family document.
        declared: The mapping from GLOBIN name to family name, type and description.

    Returns:
        Zero or more lines. A family the registry does not declare produces none,
        which is the same refusal :func:`render_exposition` makes: an exposition is
        rendered from the declared table, never from whatever a document happened to
        contain.
    """
    name = family.get("name")
    points = family.get("points")
    if not isinstance(name, str) or not isinstance(points, list):
        return []
    found = declared.get(name)
    if found is None:
        return []
    spelling, kind, description = found
    lines = [f"# TYPE {spelling} {kind}", f"# HELP {spelling} {_help_text(description)}"]
    boundaries = family.get("boundaries")
    for point in points:
        if isinstance(point, dict):
            lines.extend(_openmetrics_point(spelling, kind, point, boundaries))
    return lines


def _openmetrics_point(
    spelling: str, kind: str, point: dict[str, object], boundaries: object
) -> list[str]:
    """The OpenMetrics sample lines one point produces.

    Args:
        spelling: The MetricFamily name.
        kind: Its OpenMetrics type.
        point: The point document.
        boundaries: The family's bucket boundaries, for a histogram.

    Returns:
        Zero or more sample lines.
    """
    labels = _labels(point.get("series"))
    value = point.get("value")
    if isinstance(value, int):
        suffix = f"_{COUNTER_SUFFIX}" if kind == "counter" else ""
        return [f"{spelling}{suffix}{labels} {value}"]
    count = point.get("count")
    total = point.get("total")
    if not isinstance(count, int) or not isinstance(total, int):
        return []
    lines = _bucket_lines(spelling, point.get("series"), point.get("buckets"), boundaries)
    lines.append(f"{spelling}_count{labels} {count}")
    lines.append(f"{spelling}_sum{labels} {total}")
    return lines


def _bucket_lines(spelling: str, series: object, buckets: object, boundaries: object) -> list[str]:
    """A histogram point's cumulative bucket samples.

    Args:
        spelling: The MetricFamily name.
        series: The point's series key.
        buckets: The per-bucket counts, one more than there are boundaries.
        boundaries: The declared boundaries.

    Returns:
        One line per boundary plus the ``+Inf`` line, or none when the two lists do
        not agree about how many buckets there are.

    **The stored counts are per-bucket and the exposition's are cumulative**, which
    is the one arithmetic difference between GLOBIN's snapshot and the wire format.
    ``le="+Inf"`` is not optional: it is the sample that makes the last bucket the
    total, and a histogram without it is not a histogram.
    """
    if not isinstance(buckets, list) or not isinstance(boundaries, list):
        return []
    if len(buckets) != len(boundaries) + 1:
        return []
    lines: list[str] = []
    running = 0
    for boundary, count in zip(boundaries, buckets, strict=False):
        if not isinstance(count, int):
            return []
        running += count
        edge = _labels(series, ((BUCKET_LABEL, str(boundary)),))
        lines.append(f"{spelling}_bucket{edge} {running}")
    overflow = buckets[-1]
    if not isinstance(overflow, int):
        return []
    running += overflow
    edge = _labels(series, ((BUCKET_LABEL, POSITIVE_INFINITY),))
    lines.append(f"{spelling}_bucket{edge} {running}")
    return lines


def _help_text(description: str) -> str:
    """One description, escaped for a ``# HELP`` line.

    Args:
        description: The registry's own sentence.

    Returns:
        The escaped text.

    Every description is a literal in `domain/metrics.py` and none contains either
    character today. The escaping is applied anyway, because "no current description
    needs it" is a property of the registry rather than of this function, and the
    failure it would otherwise permit is a malformed exposition rather than an
    obviously wrong number.
    """
    return description.replace("\\", "\\\\").replace("\n", "\\n")


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
    """Holds the newest exposition text. Binds nothing, and cannot.

    Args:
        registry: The library's collector registry.
        latest: The most recent exposition text.
        reason: Why this publisher exists in the state it does.

    **The registry is held as proof the library is importable, and for nothing
    else.** GLOBIN encodes both exposition formats itself, so nothing is ever
    registered into it and nothing reads it. That is worth saying plainly rather
    than leaving a reader to infer a use: the field's job is that constructing it
    is what distinguishes this class from :class:`UnavailablePrometheus`, which is
    the state `diagnostics telemetry` reports.
    """

    registry: Any
    latest: str = ""
    reason: str = REASON_PROMETHEUS_PRESENT

    @property
    def available(self) -> bool:
        """Whether the library is present.

        Returns:
            Always ``True``.
        """
        return True

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
        """Release nothing.

        Present because the exporter port declares it, and a no-op because this
        publisher holds a string and a registry it never wrote to. Phase 026's
        version shut a listener down; there is no listener here to shut down, and
        `adapters/diagnostics_http.py` owns the one that exists.
        """


def prometheus_publisher() -> UnavailablePrometheus | PrometheusPublisher:
    """A publisher that holds text and binds nothing.

    Returns:
        A working publisher when the library is importable, and an object that says
        why when it is not.

    **Nothing in this module can open a socket**, which is stronger than Phase 026's
    "no listener unless you ask": there is no function to ask.
    """
    try:
        from prometheus_client import CollectorRegistry
    except ImportError:
        return UnavailablePrometheus()
    return PrometheusPublisher(registry=CollectorRegistry())
