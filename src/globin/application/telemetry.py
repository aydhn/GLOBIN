"""The store that accumulates measurements, and the rules it enforces at runtime.

[`domain/metrics.py`](../domain/metrics.py) holds the folds; this holds the state
they fold into. It is the only mutable object in the telemetry chain, and it is
deliberately the *simplest* one: a dictionary of dictionaries, no lock, no clock,
no thread. That is `RuntimeWatchdog`'s shape, and it is what lets every rule below
be tested in microseconds without concurrency.

**Nothing here raises.** A telemetry call sits inside the code it is measuring, so
a refused observation is dropped and counted rather than propagated. Every refusal
therefore goes through a screen first and the raising fold second, which is why
`domain/metrics.py` publishes both halves of each.

**A rejected series key is never stored, never logged and never published.** The
whole point of a cardinality budget is that an unbounded set of values cannot grow
anything, and a drop path that recorded what it rejected would grow a table
instead of a series — the cardinality bug in the one place nobody would look for
it.

**Drop logging is itself bounded.** A drop that logged every occurrence would turn
a cardinality explosion into a log explosion. The first drop per
``(metric, problem code)`` is logged and the rest are counted, which bounds the
announcement table at ``len(metrics()) * len(attribute_problem_codes())``.
"""

from dataclasses import dataclass, replace

from globin.application.observability import Logger
from globin.domain.clock import Duration, Instant
from globin.domain.metrics import (
    DropCounts,
    MetricPoint,
    MetricSnapshot,
    TelemetrySnapshot,
    advanced,
    descriptor_for,
    empty_point,
    gauge_problems,
    increment_problems,
    metrics,
    observation_problems,
    observed,
    screened,
)
from globin.domain.telemetry import MetricAttributes, MetricKind

EVENT_OBSERVATION_DROPPED: str = "telemetry.observation.dropped"
"""Emitted once per metric and reason, never once per drop."""

EVENT_SERIES_BUDGET_SPENT: str = "telemetry.series.budget.spent"
"""Emitted once per metric when its budget first refuses a new series."""

REASON_REFUSED: str = "refused"
"""The attribute set did not satisfy what the family declares."""

REASON_OVER_BUDGET: str = "over_budget"
"""A new series would have exceeded the family's cardinality budget."""

REASON_MALFORMED: str = "malformed"
"""The value itself was not one the fold would accept."""


@dataclass(slots=True)
class MetricStore:
    """Every materialised series, and what was refused on the way in.

    Args:
        logger: Where a first-of-its-kind drop is announced.
        series: Metric name to series key to point.
        announced: Which ``(metric, reason)`` pairs have already been logged.
        drops: How many observations were refused, by rule.

    Not frozen, and it holds no lock: only one object owns a store, and writing a
    lock here would persuade a future reader there is a race. When a thread
    arrives, the lock goes in the adapter that owns it — the arrangement
    `SharedHeartbeatRegistry` already uses.

    None of the three recording methods has a default for `series` or `announced`,
    because ``{}`` and ``set()`` are calls and a layer package performs none at
    import. :func:`metric_store` is the factory that supplies them.
    """

    logger: Logger
    series: dict[str, dict[str, MetricPoint]]
    announced: set[tuple[str, str]]
    drops: DropCounts

    def count(self, name: str, increment: int = 1, **attributes: str) -> None:
        """Advance a counter, or drop and count the attempt.

        Args:
            name: The declared metric name.
            increment: How much to add, never negative.
            attributes: Every attribute key the family declares.
        """
        point = self._point_for(name, MetricKind.COUNTER, attributes)
        if point is None:
            return
        if self._malformed(name, increment_problems(increment)):
            return
        current = point.value if point.value is not None else 0
        self._store(name, replace(point, value=advanced(current, increment)))

    def set_gauge(self, name: str, value: int, **attributes: str) -> None:
        """Set a gauge to an absolute value, or drop and count the attempt.

        Args:
            name: The declared metric name.
            value: The new value.
            attributes: Every attribute key the family declares.

        Absolute rather than a delta, because a gauge read from a real quantity —
        how many series exist, how deep a queue is — is always known outright, and
        a delta interface would invite a caller to compute one and get it wrong.
        """
        point = self._point_for(name, MetricKind.GAUGE, attributes)
        if point is None:
            return
        unit = descriptor_for(name).unit
        if self._malformed(name, gauge_problems(0, value, unit=unit)):
            return
        self._store(name, replace(point, value=value))

    def observe(self, name: str, value: int, **attributes: str) -> None:
        """Record one histogram observation, or drop and count the attempt.

        Args:
            name: The declared metric name.
            value: The observation, in the family's stored scale.
            attributes: Every attribute key the family declares.
        """
        point = self._point_for(name, MetricKind.HISTOGRAM, attributes)
        if point is None:
            return
        descriptor = descriptor_for(name)
        if self._malformed(name, observation_problems(value, unit=descriptor.unit)):
            return
        self._store(name, observed(point, value, descriptor.boundaries))

    def families(self) -> tuple[MetricSnapshot, ...]:
        """Every family holding at least one series.

        Returns:
            The families in registry order, each with its points in series-key
            order — the two orderings :class:`TelemetrySnapshot` refuses to repair.
        """
        built: list[MetricSnapshot] = []
        for descriptor in metrics():
            points = self.series.get(descriptor.name)
            if not points:
                continue
            built.append(
                MetricSnapshot(
                    name=descriptor.name,
                    kind=descriptor.kind,
                    unit=descriptor.unit,
                    boundaries=descriptor.boundaries,
                    points=tuple(points[key] for key in sorted(points)),
                )
            )
        return tuple(built)

    def drop_counts(self) -> DropCounts:
        """How many observations were refused, by rule.

        Returns:
            The counts.
        """
        return self.drops

    def snapshot(
        self, *, generated_at: Instant, uptime: Duration, run_id: str
    ) -> TelemetrySnapshot:
        """Everything measured so far, as a document-ready value.

        Args:
            generated_at: When this was taken. Must be millisecond-aligned, since
                `encode_instant` refuses sub-millisecond precision rather than
                truncating it.
            uptime: How long the process has been running.
            run_id: The run this belongs to.

        Returns:
            The snapshot.
        """
        return TelemetrySnapshot(
            generated_at=generated_at,
            uptime=uptime,
            run_id=run_id,
            families=self.families(),
            drops=self.drops,
        )

    def _point_for(
        self, name: str, kind: MetricKind, attributes: dict[str, str]
    ) -> MetricPoint | None:
        """Find or create the series one observation belongs to.

        Args:
            name: The declared metric name.
            kind: The kind the caller believes it is recording.
            attributes: What the caller supplied.

        Returns:
            The series' present point, or ``None`` when the observation was
            dropped — in which case the drop has already been counted.

        The one place the cardinality budget is enforced at runtime, and it should
        be unreachable: a descriptor whose declared product exceeds its budget
        cannot be constructed. It exists so a registry defect degrades into a drop
        rather than into unbounded memory.
        """
        descriptor = descriptor_for(name)
        if descriptor.kind is not kind:
            self._drop(name, REASON_MALFORMED, f"{name} is a {descriptor.kind.value}")
            return None
        problems = screened(descriptor, attributes)
        if problems:
            self._drop(name, REASON_REFUSED, problems[0])
            return None
        identity = MetricAttributes(tuple(sorted(attributes.items())))
        key = identity.series_key()
        existing = self.series.setdefault(name, {})
        found = existing.get(key)
        if found is not None:
            return found
        if len(existing) >= descriptor.cardinality_budget:
            self.drops = replace(self.drops, over_budget=self.drops.over_budget + 1)
            self._announce(name, REASON_OVER_BUDGET, EVENT_SERIES_BUDGET_SPENT, "")
            return None
        buckets = len(descriptor.boundaries) + 1 if descriptor.boundaries else 0
        return empty_point(descriptor.kind, identity, buckets)

    def _store(self, name: str, point: MetricPoint) -> None:
        """Put a folded point back.

        Args:
            name: The declared metric name.
            point: The new point.
        """
        self.series.setdefault(name, {})[point.attributes.series_key()] = point

    def _malformed(self, name: str, problems: tuple[str, ...]) -> bool:
        """Count and announce a value the fold would have refused.

        Args:
            name: The declared metric name.
            problems: What the screen said, empty when the value is usable.

        Returns:
            Whether the observation was dropped.
        """
        if not problems:
            return False
        self._drop(name, REASON_MALFORMED, problems[0])
        return True

    def _drop(self, name: str, reason: str, detail: str) -> None:
        """Record one refused observation.

        Args:
            name: The declared metric name.
            reason: Which rule refused it.
            detail: What the screen said. **Never a supplied value** — the screens
                return codes and sentences GLOBIN wrote, precisely so that this is
                safe to log.
        """
        if reason == REASON_REFUSED:
            self.drops = replace(self.drops, refused=self.drops.refused + 1)
        else:
            self.drops = replace(self.drops, malformed=self.drops.malformed + 1)
        self._announce(name, reason, EVENT_OBSERVATION_DROPPED, detail)

    def _announce(self, name: str, reason: str, event: str, detail: str) -> None:
        """Log a drop the first time this metric and reason produce one.

        Args:
            name: The declared metric name.
            reason: Which rule refused it.
            event: The event name to emit under.
            detail: What the screen said.

        A record per drop would turn a cardinality explosion into a log explosion,
        and the rotation policy would then discard the record that mattered. The
        announcement table is bounded by the registry times the problem vocabulary.
        """
        marker = (name, reason)
        if marker in self.announced:
            return
        self.announced.add(marker)
        self.logger.warning(event, metric=name, reason=reason, detail=detail)


def metric_store(logger: Logger) -> MetricStore:
    """A store with nothing recorded yet.

    Args:
        logger: Where a first-of-its-kind drop is announced.

    Returns:
        The store.

    A function rather than field defaults because ``{}``, ``set()`` and
    ``DropCounts()`` are all calls, and a layer package performs none at import —
    the same reason `adapters/watchdog.py::heartbeats` exists.
    """
    return MetricStore(logger=logger, series={}, announced=set(), drops=DropCounts())
