"""Descriptors, the three folds, and the snapshot they build.

Every case here is literals in and values out — no clock, no store, no provider —
which is what `domain/watchdog.py` achieved for a subject that is even harder to
test that way.
"""

from datetime import UTC, datetime

import pytest

from globin.domain.clock import Duration, Instant
from globin.domain.metrics import (
    DEFAULT_SECOND_BOUNDARIES,
    MAXIMUM_BUCKETS,
    MAXIMUM_SERIES_BUDGET,
    DropCounts,
    MetricDescriptor,
    MetricPoint,
    MetricSnapshot,
    TelemetrySnapshot,
    advanced,
    boundary_problems,
    bucket_index,
    declared_series,
    descriptor_for,
    empty_point,
    gauge_adjusted,
    gauge_problems,
    increment_problems,
    maximum_series_footprint,
    metric_names,
    metrics,
    observation_problems,
    observed,
    screened,
)
from globin.domain.telemetry import (
    MAXIMUM_METRIC_VALUE,
    AttributeDomain,
    MetricAttributes,
    MetricKind,
    MetricUnit,
)
from globin.errors import InternalError, ValidationError

ATTRIBUTES = MetricAttributes((("component", "telemetry"), ("result", "ok")))
"""One valid dimension set, matching the first registered family."""

BUCKETS: int = len(DEFAULT_SECOND_BOUNDARIES) + 1
"""Boundaries plus the overflow bucket."""


def counter(**overrides: object) -> MetricDescriptor:
    """A minimal valid counter descriptor, with fields replaced.

    Args:
        overrides: Fields to replace.

    Returns:
        The descriptor.
    """
    fields: dict[str, object] = {
        "name": "globin.testing.things.total",
        "kind": MetricKind.COUNTER,
        "unit": MetricUnit.COUNT,
        "description": "A counter used only by tests.",
    }
    fields.update(overrides)
    return MetricDescriptor(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Descriptors: the suffix rules, and the budget proved at construction
# ---------------------------------------------------------------------------


def test_a_minimal_counter_is_constructible() -> None:
    """The positive case, so every refusal below means something."""
    assert counter().kind is MetricKind.COUNTER


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({"name": "globin.testing.things"}, "does not end in", id="counter-no-total"),
        pytest.param(
            {"name": "globin.testing.things.total", "kind": MetricKind.GAUGE},
            "reads as a counter",
            id="gauge-named-total",
        ),
        pytest.param(
            {"unit": MetricUnit.BYTES},
            "does not carry",
            id="bytes-without-suffix",
        ),
        pytest.param({"description": ""}, "no description", id="no-description"),
        pytest.param({"boundaries": (1, 2)}, "only a histogram", id="counter-with-boundaries"),
        pytest.param({"cardinality_budget": 0}, "budget outside", id="budget-too-small"),
        pytest.param(
            {"cardinality_budget": MAXIMUM_SERIES_BUDGET + 1}, "budget outside", id="budget-too-big"
        ),
    ],
)
def test_a_contradictory_descriptor_is_refused(overrides: dict[str, object], expected: str) -> None:
    """A suffix that contradicts the kind is the failure that silently misleads.

    A gauge called `total` reads as a counter to every dashboard that sees it, and
    the resulting chart is wrong rather than broken.
    """
    with pytest.raises(ValidationError, match=expected):
        counter(**overrides)


def test_a_unit_suffix_may_sit_before_the_counter_suffix() -> None:
    """`...bytes.total` is a counter of bytes, and both rules hold at once."""
    descriptor = counter(name="globin.testing.written.bytes.total", unit=MetricUnit.BYTES)
    assert descriptor.unit is MetricUnit.BYTES


def test_a_histogram_must_declare_boundaries() -> None:
    """A histogram with no buckets cannot record anything."""
    with pytest.raises(ValidationError, match="no bucket boundaries"):
        counter(
            name="globin.testing.took.nanoseconds",
            kind=MetricKind.HISTOGRAM,
            unit=MetricUnit.SECONDS,
        )


def test_the_declared_series_count_is_the_product_of_the_domains() -> None:
    """The arithmetic the whole cardinality argument rests on."""
    descriptor = counter(
        attributes=(
            AttributeDomain("component", ("a", "b", "c")),
            AttributeDomain("result", ("ok", "error")),
        )
    )
    assert declared_series(descriptor) == 6


def test_a_descriptor_that_could_exceed_its_own_budget_cannot_be_built() -> None:
    """Cardinality is refused where it is declared, not policed where it happens.

    This is what turns "we hope this stays bounded" into an arithmetic fact.
    """
    with pytest.raises(ValidationError, match="above its budget"):
        counter(
            cardinality_budget=4,
            attributes=(
                AttributeDomain("component", ("a", "b", "c")),
                AttributeDomain("result", ("ok", "error")),
            ),
        )


def test_a_family_with_no_attributes_declares_one_series() -> None:
    """The empty product, which is what an unlabelled metric actually is."""
    assert declared_series(counter()) == 1


# ---------------------------------------------------------------------------
# Buckets: upper-inclusive, non-cumulative, total
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(0, 0, id="below-first"),
        pytest.param(10, 0, id="inside-first"),
        pytest.param(10, 0, id="at-first-boundary"),
        pytest.param(11, 1, id="just-above-first"),
        pytest.param(20, 1, id="at-second-boundary"),
        pytest.param(21, 2, id="overflow"),
        pytest.param(10**12, 2, id="far-overflow"),
    ],
)
def test_a_value_lands_in_the_upper_inclusive_bucket(value: int, expected: int) -> None:
    """`le` semantics, so an exporter re-derives nothing."""
    assert bucket_index(value, (10, 20)) == expected


@pytest.mark.parametrize(
    ("boundaries", "expected"),
    [
        pytest.param((1,), "outside", id="too-few"),
        pytest.param(tuple(range(1, MAXIMUM_BUCKETS + 3)), "outside", id="too-many"),
        pytest.param((10, 10), "strictly increasing", id="repeated"),
        pytest.param((20, 10), "strictly increasing", id="descending"),
        pytest.param((-1, 10), "outside what", id="negative"),
    ],
)
def test_unusable_boundaries_are_reported(boundaries: tuple[int, ...], expected: str) -> None:
    """A repeated boundary makes a bucket that can never be non-empty."""
    problems = boundary_problems(boundaries, unit=MetricUnit.SECONDS)
    assert problems
    assert any(expected in problem for problem in problems)


def test_the_declared_duration_boundaries_are_sound() -> None:
    """The registry's own defaults, held against the same rule."""
    assert boundary_problems(DEFAULT_SECOND_BOUNDARIES, unit=MetricUnit.SECONDS) == ()


# ---------------------------------------------------------------------------
# The three folds, and their non-raising twins
# ---------------------------------------------------------------------------


def test_a_counter_only_rises() -> None:
    """Monotonic, and the increment is what is checked rather than the result."""
    assert advanced(0, 5) == 5
    assert advanced(5, 0) == 5


@pytest.mark.parametrize(
    "increment",
    [
        pytest.param(-1, id="negative"),
        pytest.param(True, id="bool"),
        pytest.param(MAXIMUM_METRIC_VALUE + 1, id="above-ceiling"),
    ],
)
def test_a_bad_increment_is_refused_and_screened_alike(increment: object) -> None:
    """The screen and the fold must agree, or a drop path becomes a raise path.

    `isinstance(True, int)` is why the bool case exists: without an explicit
    guard, `advanced(0, True)` would silently add one.
    """
    assert increment_problems(increment)
    with pytest.raises(ValidationError):
        advanced(0, increment)  # type: ignore[arg-type]


def test_a_counter_refuses_to_pass_the_ceiling() -> None:
    """Refused and countable, never wrapped."""
    with pytest.raises(ValidationError, match="above"):
        advanced(MAXIMUM_METRIC_VALUE, 1)


def test_a_gauge_moves_both_ways() -> None:
    """The whole difference between a gauge and a counter."""
    assert gauge_adjusted(5, 3, unit=MetricUnit.COUNT) == 8
    assert gauge_adjusted(5, -3, unit=MetricUnit.COUNT) == 2


def test_a_gauge_refuses_to_fall_below_its_unit() -> None:
    """Refused rather than clamped, because clamping hides a real leak.

    A byte gauge below zero means a decrement without a matching increment — an
    in-flight counter leaking in reverse — and a clamp would conceal it for ever.
    """
    assert gauge_problems(0, -1, unit=MetricUnit.BYTES)
    with pytest.raises(ValidationError, match="below what"):
        gauge_adjusted(0, -1, unit=MetricUnit.BYTES)


def test_a_ratio_gauge_refuses_to_pass_one() -> None:
    """The unit's own ceiling, enforced by the fold rather than by a caller."""
    with pytest.raises(ValidationError, match="above what"):
        gauge_adjusted(1_000_000, 1, unit=MetricUnit.RATIO)


def test_an_observation_advances_count_total_and_one_bucket() -> None:
    """The histogram invariant, asserted on a concrete fold."""
    point = empty_point(MetricKind.HISTOGRAM, MetricAttributes(), 3)
    point = observed(point, 5, (10, 20))
    point = observed(point, 15, (10, 20))
    assert point.count == 2
    assert point.total == 20
    assert point.bucket_counts == (1, 1, 0)


def test_a_negative_observation_is_refused_and_screened_alike() -> None:
    """A duration cannot be negative, and the screen says so without raising."""
    assert observation_problems(-1, unit=MetricUnit.SECONDS)


def test_only_a_histogram_takes_an_observation() -> None:
    """A counter handed an observation is a call site confusion, not a value."""
    point = empty_point(MetricKind.COUNTER, MetricAttributes(), 0)
    with pytest.raises(ValidationError, match="only a histogram"):
        observed(point, 1, (10,))


# ---------------------------------------------------------------------------
# Points: one type, disagreement refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        pytest.param({"kind": MetricKind.COUNTER}, "carries no value", id="counter-no-value"),
        pytest.param(
            {"kind": MetricKind.COUNTER, "value": 1, "count": 1},
            "histogram fields",
            id="counter-with-count",
        ),
        pytest.param(
            {"kind": MetricKind.HISTOGRAM, "value": 1, "count": 0, "total": 0},
            "scalar value",
            id="histogram-with-value",
        ),
        pytest.param({"kind": MetricKind.HISTOGRAM}, "missing its count", id="histogram-empty"),
        pytest.param({"kind": MetricKind.COUNTER, "value": -1}, "negative", id="negative-counter"),
        pytest.param(
            {"kind": MetricKind.COUNTER, "value": MAXIMUM_METRIC_VALUE + 1},
            "exceeds",
            id="above-ceiling",
        ),
        pytest.param(
            {"kind": MetricKind.HISTOGRAM, "count": 2, "total": 5, "bucket_counts": (1, 0)},
            "do not sum",
            id="buckets-disagree",
        ),
    ],
)
def test_a_point_whose_shape_contradicts_its_kind_is_refused(
    fields: dict[str, object], expected: str
) -> None:
    """The refusals are the type's contribution, exactly as they are for `Reading`."""
    with pytest.raises(ValidationError, match=expected):
        MetricPoint(attributes=MetricAttributes(), **fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The registry, and the snapshot it validates
# ---------------------------------------------------------------------------


def test_every_registered_descriptor_is_within_its_budget() -> None:
    """The runtime budget check should be unreachable for anything declared here."""
    for descriptor in metrics():
        assert declared_series(descriptor) <= descriptor.cardinality_budget


def test_registered_names_are_unique() -> None:
    """Two families under one name would make a lookup ambiguous."""
    names = metric_names()
    assert len(set(names)) == len(names)


def test_an_unregistered_name_is_an_internal_error() -> None:
    """A name reaching the registry unregistered means a call site invented one."""
    with pytest.raises(InternalError, match="is not registered"):
        descriptor_for("globin.telemetry.invented.total")


def test_the_footprint_is_bounded_and_small() -> None:
    """Adding a wide family should be a visible edit rather than a quiet one."""
    assert 0 < maximum_series_footprint() < 2_000


def test_screening_pairs_a_descriptor_with_its_domains() -> None:
    """A caller holding a descriptor never reaches inside it for the domains."""
    descriptor = descriptor_for("globin.telemetry.observations.total")
    assert screened(descriptor, {"component": "telemetry", "result": "ok"}) == ()
    assert screened(descriptor, {"component": "nope", "result": "ok"})


def snapshot(**overrides: object) -> TelemetrySnapshot:
    """A minimal valid snapshot, with fields replaced.

    Args:
        overrides: Fields to replace.

    Returns:
        The snapshot.
    """
    family = MetricSnapshot(
        name="globin.telemetry.observations.total",
        kind=MetricKind.COUNTER,
        unit=MetricUnit.COUNT,
        points=(MetricPoint(kind=MetricKind.COUNTER, attributes=ATTRIBUTES, value=7),),
    )
    fields: dict[str, object] = {
        "generated_at": Instant(datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)),
        "uptime": Duration(123_456_789),
        "run_id": "abc",
        "families": (family,),
        "drops": DropCounts(refused=2),
    }
    fields.update(overrides)
    return TelemetrySnapshot(**fields)  # type: ignore[arg-type]


def test_a_snapshot_publishes_integers_throughout() -> None:
    """Every number in the document must survive a codec that refuses floats."""
    document = snapshot().document()
    assert document["uptime_nanoseconds"] == 123_456_789
    assert isinstance(document["generated_at"], int)


def test_a_snapshot_naming_an_unregistered_family_is_refused() -> None:
    """A fresh construction must agree with the registry it was built from."""
    stray = MetricSnapshot(
        name="globin.telemetry.invented.total", kind=MetricKind.COUNTER, unit=MetricUnit.COUNT
    )
    with pytest.raises(ValidationError, match="not a registered metric"):
        snapshot(families=(stray,))


def test_a_snapshot_with_families_out_of_registry_order_is_refused() -> None:
    """Order is enforced rather than repaired, so a digest means something.

    A document whose order depended on which recording finished first would give
    two different digests for identical work.
    """
    first = MetricSnapshot(
        name="globin.telemetry.observations.total", kind=MetricKind.COUNTER, unit=MetricUnit.COUNT
    )
    second = MetricSnapshot(
        name="globin.telemetry.dropped.total", kind=MetricKind.COUNTER, unit=MetricUnit.COUNT
    )
    assert len(snapshot(families=(first, second)).families) == 2
    with pytest.raises(ValidationError, match="out of registry order"):
        snapshot(families=(second, first))


def test_a_family_holding_points_out_of_series_order_is_refused() -> None:
    """There is no registry of series, so lexicographic is the only stable rule."""
    one = MetricPoint(
        kind=MetricKind.COUNTER,
        attributes=MetricAttributes((("component", "telemetry"), ("result", "ok"))),
        value=1,
    )
    two = MetricPoint(
        kind=MetricKind.COUNTER,
        attributes=MetricAttributes((("component", "watchdog"), ("result", "ok"))),
        value=1,
    )
    ordered = MetricSnapshot(
        name="globin.telemetry.observations.total",
        kind=MetricKind.COUNTER,
        unit=MetricUnit.COUNT,
        points=(one, two),
    )
    assert len(ordered.points) == 2
    with pytest.raises(ValidationError, match="out of series-key order"):
        MetricSnapshot(
            name="globin.telemetry.observations.total",
            kind=MetricKind.COUNTER,
            unit=MetricUnit.COUNT,
            points=(two, one),
        )


def test_the_shape_holds_no_measurement() -> None:
    """Determinism is claimed over this half and nothing else.

    Two snapshots of the same logical work share their families, order, units,
    boundaries and series keys. They do not share their numbers, and promising
    that would be a guarantee nobody could keep.
    """
    shape = snapshot().shape()
    rendered = repr(shape)
    assert "7" not in rendered
    assert "component=telemetry,result=ok" in rendered


def test_two_snapshots_of_the_same_work_share_a_shape() -> None:
    """The property a digest is taken over, asserted directly."""
    early = snapshot()
    late = snapshot(
        generated_at=Instant(datetime(2026, 8, 17, 13, 0, 0, tzinfo=UTC)),
        uptime=Duration(999_000_000),
        drops=DropCounts(refused=99),
    )
    assert early.shape() == late.shape()
    assert early.document() != late.document()


def test_drop_counts_report_every_rule_separately() -> None:
    """One integer per rule, because each has a different fix."""
    document = DropCounts(refused=1, over_budget=2, malformed=3).document()
    assert document["total"] == 6
