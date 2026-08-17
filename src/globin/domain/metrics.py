"""Metric descriptors, the folds that advance them, and the snapshot they produce.

[`telemetry.py`](telemetry.py) owns the vocabulary — what a name may be, what a
dimension may be, which units exist. This owns what is built from it: the
descriptors GLOBIN declares, the three pure folds that advance a measurement, and
the document a snapshot renders to.

**Every fold here is a pure function of values.** No clock, no state, no lock. The
mutable store that accumulates them belongs to the application layer, which is
what lets the whole of this module be tested with literals — the shape
`domain/watchdog.py` used to make a stall testable without waiting for one.

**A descriptor that could exceed its own budget cannot be constructed.** Because
every attribute key must declare a bounded value set, the number of series a
family can produce is a product, and the product is checked when the descriptor is
built. The runtime budget check that still exists is therefore a guard against a
registry defect rather than the mechanism keeping cardinality bounded — and a
property test asserts it never fires for anything :func:`metrics` returns.
"""

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Final

from globin.domain.clock import Duration, Instant
from globin.domain.telemetry import (
    MAXIMUM_METRIC_VALUE,
    AttributeDomain,
    MetricAttributes,
    MetricKind,
    MetricUnit,
    name_problems,
    unit_specification,
)
from globin.errors import InternalError, ValidationError

#: The schema a telemetry snapshot is published under.
TELEMETRY_SCHEMA: Final[str] = "globin.telemetry.snapshot"

#: The version of that schema. An unknown version is refused, never read.
TELEMETRY_SCHEMA_VERSION: Final[int] = 1

#: The fewest bucket boundaries a histogram may declare.
MINIMUM_BUCKETS: Final[int] = 2

#: The most bucket boundaries a histogram may declare.
#:
#: A family costs ``budget * (len(boundaries) + 1)`` integers in the snapshot, so
#: at a budget of sixteen this is 272 numbers — a document a person can still
#: read. A histogram is the one place a metric silently multiplies.
MAXIMUM_BUCKETS: Final[int] = 16

#: The fewest unique attribute combinations a family may be allowed.
MINIMUM_SERIES_BUDGET: Final[int] = 1

#: The default ceiling on unique attribute combinations per family.
DEFAULT_SERIES_BUDGET: Final[int] = 16

#: The most unique attribute combinations any family may be allowed.
MAXIMUM_SERIES_BUDGET: Final[int] = 64

#: The name segment a counter must end with.
#:
#: Prometheus and OpenTelemetry both read it, so an exporter re-derives nothing.
#: Nothing else may end with it either: a gauge called `total` is the confusion
#: that makes a dashboard silently wrong rather than visibly broken.
COUNTER_SUFFIX: Final[str] = "total"

#: Default histogram boundaries for a duration, in nanoseconds.
#:
#: A tuple display of integer literals is not a call, so this is legal at module
#: scope where ``frozenset({...})`` would not be. 100 microseconds to 10 seconds,
#: which brackets everything GLOBIN measures about itself today.
DEFAULT_SECOND_BOUNDARIES: Final[tuple[int, ...]] = (
    100_000,
    250_000,
    500_000,
    1_000_000,
    2_500_000,
    5_000_000,
    10_000_000,
    25_000_000,
    50_000_000,
    100_000_000,
    250_000_000,
    500_000_000,
    1_000_000_000,
    2_500_000_000,
    5_000_000_000,
    10_000_000_000,
)


@dataclass(frozen=True, slots=True)
class MetricDescriptor:
    """One metric family: what it is called, what it measures, how it is bounded.

    Args:
        name: The canonical `globin.*` name.
        kind: Counter, gauge or histogram.
        unit: The base unit its values are denominated in.
        description: One sentence, for a human reading an exporter's output.
        attributes: The dimensions it carries, each with a bounded value set.
        boundaries: Histogram bucket boundaries, in the unit's stored scale.
        cardinality_budget: The most unique attribute combinations permitted.

    Raises:
        ValidationError: If anything about it is not constructible — a malformed
            name, a suffix that contradicts the kind or the unit, boundaries on a
            non-histogram or missing from a histogram, a repeated attribute key,
            or a declared series count above its own budget.
    """

    name: str
    kind: MetricKind
    unit: MetricUnit
    description: str
    attributes: tuple[AttributeDomain, ...] = ()
    boundaries: tuple[int, ...] = ()
    cardinality_budget: int = DEFAULT_SERIES_BUDGET

    def __post_init__(self) -> None:
        """Refuse a descriptor that could not be recorded or could not be bounded."""
        problems = list(name_problems(self.name))
        problems.extend(_suffix_problems(self.name, self.kind, self.unit))
        problems.extend(_histogram_problems(self.kind, self.boundaries, self.unit))
        keys = [domain.key for domain in self.attributes]
        if len(set(keys)) != len(keys):
            problems.append(f"{self.name} repeats an attribute key")
        if not self.description:
            problems.append(f"{self.name} has no description")
        if not MINIMUM_SERIES_BUDGET <= self.cardinality_budget <= MAXIMUM_SERIES_BUDGET:
            problems.append(
                f"{self.name} has a budget outside {MINIMUM_SERIES_BUDGET}..{MAXIMUM_SERIES_BUDGET}"
            )
        elif declared_series(self) > self.cardinality_budget:
            problems.append(
                f"{self.name} declares {declared_series(self)} series, above its "
                f"budget of {self.cardinality_budget}"
            )
        if problems:
            raise ValidationError("; ".join(problems))

    def keys(self) -> tuple[str, ...]:
        """Every attribute key this family declares.

        Returns:
            The keys, in declaration order.
        """
        return tuple(domain.key for domain in self.attributes)


def declared_series(descriptor: MetricDescriptor) -> int:
    """How many series this family can possibly produce.

    Args:
        descriptor: The family.

    Returns:
        The product of its attribute domains' sizes, or ``1`` for a family with no
        attributes.

    **This is the whole cardinality argument in one function.** Every declared key
    carries a bounded value set, so the maximum is arithmetic rather than
    observation, and :meth:`MetricDescriptor.__post_init__` refuses a descriptor
    whose product exceeds its own budget.
    """
    total = 1
    for domain in descriptor.attributes:
        total *= len(domain.permitted)
    return total


def _suffix_problems(name: str, kind: MetricKind, unit: MetricUnit) -> list[str]:
    """Judge a name's last segments against the kind and unit that own it.

    Args:
        name: The metric name.
        kind: Its kind.
        unit: Its unit.

    Returns:
        One sentence per problem.

    Joint facts about three things at once, which is why they are checked on the
    descriptor rather than by the name validator: a name alone cannot know whether
    it belongs to a counter.
    """
    problems: list[str] = []
    segments = name.split(".")
    last = segments[-1] if segments else ""
    if kind is MetricKind.COUNTER and last != COUNTER_SUFFIX:
        problems.append(f"the counter {name} does not end in {COUNTER_SUFFIX!r}")
    if kind is not MetricKind.COUNTER and last == COUNTER_SUFFIX:
        problems.append(
            f"the {kind.value} {name} ends in {COUNTER_SUFFIX!r}, which reads as a counter"
        )
    if unit is not MetricUnit.COUNT:
        suffix = unit_specification(unit).suffix
        carried = last == suffix or (
            last == COUNTER_SUFFIX and len(segments) > 1 and segments[-2] == suffix
        )
        if not carried:
            problems.append(f"{name} is denominated in {unit.value} but does not carry {suffix!r}")
    return problems


def _histogram_problems(
    kind: MetricKind, boundaries: tuple[int, ...], unit: MetricUnit
) -> list[str]:
    """Judge boundaries against the kind that may carry them.

    Args:
        kind: The metric kind.
        boundaries: The declared boundaries.
        unit: The unit they are denominated in.

    Returns:
        One sentence per problem.
    """
    if kind is MetricKind.HISTOGRAM:
        if not boundaries:
            return ["a histogram declares no bucket boundaries"]
        return list(boundary_problems(boundaries, unit=unit))
    if boundaries:
        return [f"a {kind.value} declares bucket boundaries, which only a histogram has"]
    return []


def boundary_problems(boundaries: Sequence[int], *, unit: MetricUnit) -> tuple[str, ...]:
    """Judge a histogram's bucket boundaries.

    Args:
        boundaries: The candidates, expected strictly increasing.
        unit: The unit they are denominated in.

    Returns:
        One sentence per reason they are unusable, empty when they are sound.

    Problems rather than an exception, so a contract test can hold every registry
    entry against the rules without catching anything.
    """
    problems: list[str] = []
    if not MINIMUM_BUCKETS <= len(boundaries) <= MAXIMUM_BUCKETS:
        problems.append(
            f"{len(boundaries)} boundaries is outside {MINIMUM_BUCKETS}..{MAXIMUM_BUCKETS}"
        )
    spec = unit_specification(unit)
    for boundary in boundaries:
        if isinstance(boundary, bool) or not isinstance(boundary, int):
            problems.append(f"the boundary {boundary!r} is not a plain int")
        elif boundary < spec.minimum or (spec.maximum is not None and boundary > spec.maximum):
            problems.append(f"the boundary {boundary} is outside what {unit.value} permits")
    ordered = all(earlier < later for earlier, later in pairwise(boundaries))
    if not ordered:
        problems.append("the boundaries are not strictly increasing, so a bucket cannot fill")
    return tuple(problems)


def bucket_index(value: int, boundaries: Sequence[int]) -> int:
    """Which bucket one observation falls in.

    Args:
        value: The observation.
        boundaries: Strictly increasing upper bounds.

    Returns:
        ``i`` where ``boundaries[i-1] < value <= boundaries[i]``, or
        ``len(boundaries)`` for the overflow bucket.

    Upper-inclusive and non-cumulative, which is OpenTelemetry's and Prometheus's
    ``le`` semantics — so an exporter re-derives nothing. Total: it never raises
    for any integer and any valid boundary sequence.
    """
    return bisect_left(boundaries, value)


@dataclass(frozen=True, slots=True)
class MetricPoint:
    """One series' current value, whatever kind it belongs to.

    Args:
        kind: Which kind this point belongs to.
        attributes: The dimensions identifying the series.
        value: A counter's or gauge's number.
        count: A histogram's observation count.
        total: A histogram's summed observations.
        bucket_counts: A histogram's per-bucket counts, overflow last.

    Raises:
        ValidationError: If the fields disagree with the kind, if a counter is
            negative, if any number exceeds the ceiling, or if the bucket counts
            do not sum to the count.

    One type with disagreement refused rather than three, which is what `Reading`
    does and for the same reason: the refusals *are* the type's contribution.
    """

    kind: MetricKind
    attributes: MetricAttributes
    value: int | None = None
    count: int | None = None
    total: int | None = None
    bucket_counts: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a point whose shape contradicts its kind."""
        problems = list(_shape_problems(self))
        for number in (self.value, self.count, self.total, *self.bucket_counts):
            if number is None:
                continue
            if isinstance(number, bool) or not isinstance(number, int):
                problems.append(f"{number!r} is not a plain int")
            elif number > MAXIMUM_METRIC_VALUE:
                problems.append(f"{number} exceeds {MAXIMUM_METRIC_VALUE}")
        if self.kind is MetricKind.COUNTER and self.value is not None and self.value < 0:
            problems.append("a counter is negative")
        if (
            self.kind is MetricKind.HISTOGRAM
            and self.count is not None
            and sum(self.bucket_counts) != self.count
        ):
            problems.append("the bucket counts do not sum to the observation count")
        if problems:
            raise ValidationError("; ".join(problems))


def _shape_problems(point: MetricPoint) -> tuple[str, ...]:
    """Judge which fields a point carries against the kind it claims.

    Args:
        point: The point.

    Returns:
        One sentence per problem.
    """
    problems: list[str] = []
    histogram_fields = (point.count, point.total)
    if point.kind is MetricKind.HISTOGRAM:
        if point.value is not None:
            problems.append("a histogram point carries a scalar value")
        if any(field is None for field in histogram_fields):
            problems.append("a histogram point is missing its count or total")
    else:
        if point.value is None:
            problems.append(f"a {point.kind.value} point carries no value")
        if any(field is not None for field in histogram_fields) or point.bucket_counts:
            problems.append(f"a {point.kind.value} point carries histogram fields")
    return tuple(problems)


def empty_point(kind: MetricKind, attributes: MetricAttributes, buckets: int) -> MetricPoint:
    """A series' starting value.

    Args:
        kind: Which kind.
        attributes: The dimensions identifying the series.
        buckets: How many buckets a histogram has, boundaries plus overflow.

    Returns:
        A zeroed point of that kind.
    """
    if kind is MetricKind.HISTOGRAM:
        return MetricPoint(
            kind=kind, attributes=attributes, count=0, total=0, bucket_counts=(0,) * buckets
        )
    return MetricPoint(kind=kind, attributes=attributes, value=0)


def increment_problems(increment: object) -> tuple[str, ...]:
    """Judge a counter increment without raising.

    Args:
        increment: The candidate.

    Returns:
        One sentence per problem, empty when it is usable.

    The screening twin of :func:`advanced`, so the recorder can drop and count
    rather than let a telemetry call raise into the code it is measuring — the
    split `member_problems` and `safe_member_name` already have.
    """
    if isinstance(increment, bool) or not isinstance(increment, int):
        return (f"the increment {increment!r} is not a plain int",)
    if increment < 0:
        return (f"the increment {increment} is negative, and a counter only rises",)
    if increment > MAXIMUM_METRIC_VALUE:
        return (f"the increment {increment} exceeds {MAXIMUM_METRIC_VALUE}",)
    return ()


def advanced(current: int, increment: int) -> int:
    """Advance a counter.

    Args:
        current: Its present value.
        increment: How much to add.

    Returns:
        The new value.

    Raises:
        ValidationError: If the increment is negative or not an int, or the result
            would exceed the ceiling.

    Raises rather than clamping: a negative increment is a GLOBIN defect, not
    untrusted input, and a counter that silently refused to move would be a
    dashboard reading zero for a reason nobody could find.
    """
    problems = increment_problems(increment)
    if problems:
        raise ValidationError("; ".join(problems))
    total = current + increment
    if total > MAXIMUM_METRIC_VALUE:
        msg = f"the counter would reach {total}, above {MAXIMUM_METRIC_VALUE}"
        raise ValidationError(msg)
    return total


def gauge_problems(current: int, delta: object, *, unit: MetricUnit) -> tuple[str, ...]:
    """Judge a gauge adjustment without raising.

    Args:
        current: Its present value.
        delta: The signed change.
        unit: The unit that bounds the result.

    Returns:
        One sentence per problem, empty when it is usable.
    """
    if isinstance(delta, bool) or not isinstance(delta, int):
        return (f"the delta {delta!r} is not a plain int",)
    spec = unit_specification(unit)
    result = current + delta
    if result < spec.minimum:
        return (f"the gauge would fall to {result}, below what {unit.value} permits",)
    if spec.maximum is not None and result > spec.maximum:
        return (f"the gauge would reach {result}, above what {unit.value} permits",)
    if result > MAXIMUM_METRIC_VALUE:
        return (f"the gauge would reach {result}, above {MAXIMUM_METRIC_VALUE}",)
    return ()


def gauge_adjusted(current: int, delta: int, *, unit: MetricUnit) -> int:
    """Move a gauge up or down.

    Args:
        current: Its present value.
        delta: The signed change.
        unit: The unit that bounds the result.

    Returns:
        The new value.

    Raises:
        ValidationError: If the result would leave the unit's range.

    Refuses rather than clamping. A byte gauge falling below zero means a decrement
    without a matching increment — an in-flight counter leaking in reverse — and
    clamping would hide it for ever.
    """
    problems = gauge_problems(current, delta, unit=unit)
    if problems:
        raise ValidationError("; ".join(problems))
    return current + delta


def observation_problems(value: object, *, unit: MetricUnit) -> tuple[str, ...]:
    """Judge a histogram observation without raising.

    Args:
        value: The candidate.
        unit: The unit that bounds it.

    Returns:
        One sentence per problem, empty when it is usable.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return (f"the observation {value!r} is not a plain int",)
    spec = unit_specification(unit)
    if value < spec.minimum:
        return (f"the observation {value} is below what {unit.value} permits",)
    if spec.maximum is not None and value > spec.maximum:
        return (f"the observation {value} is above what {unit.value} permits",)
    return ()


def observed(point: MetricPoint, value: int, boundaries: Sequence[int]) -> MetricPoint:
    """Fold one observation into a histogram point.

    Args:
        point: The present point.
        value: The observation.
        boundaries: The family's bucket boundaries.

    Returns:
        A new point with the count, total and one bucket advanced.

    Raises:
        ValidationError: If the point is not a histogram, or the total would
            exceed the ceiling.
    """
    if point.kind is not MetricKind.HISTOGRAM or point.count is None or point.total is None:
        msg = "only a histogram point can take an observation"
        raise ValidationError(msg)
    counts = list(point.bucket_counts)
    index = bucket_index(value, boundaries)
    counts[index] += 1
    return replace(
        point, count=point.count + 1, total=point.total + value, bucket_counts=tuple(counts)
    )


@dataclass(frozen=True, slots=True)
class DropCounts:
    """How many observations were refused, by the rule that refused them.

    Args:
        refused: Failed the attribute screen.
        over_budget: Would have created a series past the family's budget.
        malformed: Carried a value the fold would not accept.

    One integer per rule rather than one total, because each has a different fix
    and a single number would say something was refused without saying what to do.
    """

    refused: int = 0
    over_budget: int = 0
    malformed: int = 0

    def total(self) -> int:
        """Every drop, however caused.

        Returns:
            The sum.
        """
        return self.refused + self.over_budget + self.malformed

    def document(self) -> dict[str, object]:
        """This block, ready to publish.

        Returns:
            A JSON-safe mapping of integers.
        """
        return {
            "refused": self.refused,
            "over_budget": self.over_budget,
            "malformed": self.malformed,
            "total": self.total(),
        }


@dataclass(frozen=True, slots=True)
class MetricSnapshot:
    """One family's series at one moment.

    Args:
        name: The family's canonical name.
        kind: Its kind.
        unit: Its unit.
        boundaries: Its bucket boundaries, empty unless it is a histogram.
        points: Its series, ordered lexicographically by series key.

    Raises:
        ValidationError: If a point disagrees with the family, if the bucket count
            does not match the boundaries, or if the points are unordered or
            repeated.

    Deliberately does **not** require the name to be registered. A decoder reading
    a two-year-old document must be able to rebuild a family the current registry
    has dropped; requiring registration is :class:`TelemetrySnapshot`'s job,
    because that is the type a fresh construction goes through.
    """

    name: str
    kind: MetricKind
    unit: MetricUnit
    boundaries: tuple[int, ...] = ()
    points: tuple[MetricPoint, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a family whose points could not have come from it."""
        problems: list[str] = []
        for point in self.points:
            if point.kind is not self.kind:
                problems.append(f"{self.name} holds a {point.kind.value} point")
            elif (
                self.kind is MetricKind.HISTOGRAM
                and len(point.bucket_counts) != len(self.boundaries) + 1
            ):
                problems.append(f"{self.name} holds a point with the wrong bucket count")
        keys = [point.attributes.series_key() for point in self.points]
        if len(set(keys)) != len(keys):
            problems.append(f"{self.name} holds two points with one series key")
        if keys != sorted(keys):
            problems.append(f"{self.name} holds points out of series-key order")
        if problems:
            raise ValidationError("; ".join(problems))

    def document(self) -> dict[str, object]:
        """This family, ready to publish.

        Returns:
            A JSON-safe mapping, integers throughout.
        """
        return {
            "name": self.name,
            "kind": self.kind.value,
            "unit": self.unit.value,
            "boundaries": list(self.boundaries),
            "points": [_point_document(point) for point in self.points],
        }

    def shape(self) -> dict[str, object]:
        """The half of this family that does not move.

        Returns:
            Its identity, its boundaries and its series keys — no measurements.
        """
        return {
            "name": self.name,
            "kind": self.kind.value,
            "unit": self.unit.value,
            "boundaries": list(self.boundaries),
            "series": [point.attributes.series_key() for point in self.points],
        }


def _point_document(point: MetricPoint) -> dict[str, object]:
    """One point, ready to publish.

    Args:
        point: The point.

    Returns:
        A JSON-safe mapping.

    Hand-written rather than reflective, for `snapshot_document`'s reason: a
    generic serialiser would publish whatever field somebody added next.
    """
    document: dict[str, object] = {"series": point.attributes.series_key()}
    if point.kind is MetricKind.HISTOGRAM:
        document["count"] = point.count
        document["total"] = point.total
        document["buckets"] = list(point.bucket_counts)
    else:
        document["value"] = point.value
    return document


@dataclass(frozen=True, slots=True)
class TelemetrySnapshot:
    """Everything telemetry has measured, at one moment.

    Args:
        generated_at: When this was taken. **Millisecond-aligned**, because
            `encode_instant` refuses sub-millisecond precision.
        uptime: How long the process has been running.
        run_id: The run this belongs to.
        families: Every family, in registry order.
        drops: What was refused, by rule.
        schema_version: The version this document is written against.

    Raises:
        ValidationError: If a family is unregistered, disagrees with its
            descriptor, or is out of registry order.
    """

    generated_at: Instant
    uptime: Duration
    run_id: str
    families: tuple[MetricSnapshot, ...]
    drops: DropCounts
    schema_version: int = TELEMETRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Refuse a snapshot the current registry could not have produced."""
        problems: list[str] = []
        order = [descriptor.name for descriptor in metrics()]
        seen: list[str] = []
        for family in self.families:
            descriptor = _descriptor_or_none(family.name)
            if descriptor is None:
                problems.append(f"{family.name} is not a registered metric")
                continue
            if descriptor.kind is not family.kind or descriptor.unit is not family.unit:
                problems.append(f"{family.name} disagrees with its descriptor")
            seen.append(family.name)
        if len(set(seen)) != len(seen):
            problems.append("a family appears twice")
        if seen != [name for name in order if name in set(seen)]:
            problems.append("the families are out of registry order")
        if problems:
            raise ValidationError("; ".join(problems))

    def document(self) -> dict[str, object]:
        """The whole snapshot, ready to publish.

        Returns:
            A JSON-safe mapping with no float anywhere.
        """
        return {
            "schema": TELEMETRY_SCHEMA,
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.epoch_millis,
            "uptime_nanoseconds": self.uptime.nanoseconds,
            "run_id": self.run_id,
            "families": [family.document() for family in self.families],
            "drops": self.drops.document(),
        }

    def shape(self) -> dict[str, object]:
        """The half of this snapshot that two equivalent runs share.

        Returns:
            The family list, their identities and their series keys.

        **Determinism is claimed narrowly, and this method is the claim.** Two
        snapshots taken at different times differ, because a counter grows and a
        duration moves; promising otherwise would be a guarantee nobody could
        keep. What is guaranteed for the same logical work — and what a digest may
        therefore be taken over — is exactly this: the families, their order, their
        units, their boundaries and their series keys.
        """
        return {
            "schema": TELEMETRY_SCHEMA,
            "schema_version": self.schema_version,
            "families": [family.shape() for family in self.families],
        }


def metrics() -> tuple[MetricDescriptor, ...]:
    """Every metric GLOBIN declares.

    Returns:
        The descriptors, in the order a snapshot presents them.

    A function rather than a module-level tuple because constructing a dataclass
    is a call and a layer package performs none at import.

    **These describe telemetry itself and nothing else.** A descriptor named after
    a capability GLOBIN does not have would be a claim that somebody is working on
    it — `REPOSITORY_LAYOUT.md`'s rule about directories, applied to a registry.
    Market data, orders and strategies get theirs from the phases that build them.
    """
    return (
        MetricDescriptor(
            name="globin.telemetry.observations.total",
            kind=MetricKind.COUNTER,
            unit=MetricUnit.COUNT,
            description="Observations accepted, by component and outcome.",
            attributes=(
                AttributeDomain("component", ("health", "lifecycle", "telemetry", "watchdog")),
                AttributeDomain("result", ("error", "ok")),
            ),
        ),
        MetricDescriptor(
            name="globin.telemetry.dropped.total",
            kind=MetricKind.COUNTER,
            unit=MetricUnit.COUNT,
            description="Observations refused, by the rule that refused them.",
            attributes=(AttributeDomain("reason", ("malformed", "over_budget", "refused")),),
        ),
        MetricDescriptor(
            name="globin.telemetry.series.active",
            kind=MetricKind.GAUGE,
            unit=MetricUnit.COUNT,
            description="Series currently materialised across every family.",
        ),
        MetricDescriptor(
            name="globin.telemetry.snapshot.nanoseconds",
            kind=MetricKind.HISTOGRAM,
            unit=MetricUnit.SECONDS,
            description="How long producing a telemetry snapshot took.",
            boundaries=DEFAULT_SECOND_BOUNDARIES,
        ),
    )


def metric_names() -> tuple[str, ...]:
    """Every declared metric name.

    Returns:
        The names, in registry order.
    """
    return tuple(descriptor.name for descriptor in metrics())


def _descriptor_or_none(name: str) -> MetricDescriptor | None:
    """Look a descriptor up without raising.

    Args:
        name: The metric name.

    Returns:
        The descriptor, or ``None`` when nothing is registered under that name.
    """
    for descriptor in metrics():
        if descriptor.name == name:
            return descriptor
    return None


def descriptor_for(name: str) -> MetricDescriptor:
    """The descriptor registered under one name.

    Args:
        name: The metric name.

    Returns:
        Its descriptor.

    Raises:
        InternalError: If nothing is registered under it. A name reaching this
            function unregistered means a call site invented one, which is a
            GLOBIN defect rather than a caller's mistake —
            `identifiers.specification`'s rule and its wording.
    """
    descriptor = _descriptor_or_none(name)
    if descriptor is None:
        msg = (
            f"metric {name!r} is not registered; every metric must be declared in "
            f"metrics() before it can be recorded"
        )
        raise InternalError(msg)
    return descriptor


def maximum_series_footprint() -> int:
    """The most integers every family together can hold in a snapshot.

    Returns:
        The sum over families of budget times per-series integers.

    A function so a contract test can assert it stays under a declared ceiling,
    which makes adding a wide family a visible, arguable edit rather than a quiet
    one.
    """
    total = 0
    for descriptor in metrics():
        per_series = len(descriptor.boundaries) + 3 if descriptor.boundaries else 1
        total += descriptor.cardinality_budget * per_series
    return total


def screened(descriptor: MetricDescriptor, supplied: Mapping[str, object]) -> tuple[str, ...]:
    """Screen a supplied attribute set against one descriptor.

    Args:
        descriptor: The family being recorded.
        supplied: What the caller passed.

    Returns:
        Problem codes, empty when the observation may be recorded.

    A thin pairing of the descriptor with
    :func:`~globin.domain.telemetry.attribute_problems`, so a caller holding a
    descriptor never has to reach inside it for the domains.
    """
    from globin.domain.telemetry import attribute_problems

    return attribute_problems(descriptor.attributes, supplied)
