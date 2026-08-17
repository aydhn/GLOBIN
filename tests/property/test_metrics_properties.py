"""Invariants of the metric folds over generated observations.

The unit tests pin the folds somebody reasoned about. These assert what must hold
for every sequence a running process could produce — which is where an
accumulator that must never disagree with itself is actually attacked.
"""

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from globin.adapters.serialization import JsonCodec
from globin.domain.clock import Duration, Instant
from globin.domain.metrics import (
    DEFAULT_SECOND_BOUNDARIES,
    DropCounts,
    MetricPoint,
    MetricSnapshot,
    TelemetrySnapshot,
    advanced,
    bucket_index,
    declared_series,
    descriptor_for,
    empty_point,
    increment_problems,
    metric_names,
    metrics,
    observed,
    screened,
)
from globin.domain.telemetry import (
    MAXIMUM_METRIC_VALUE,
    MetricAttributes,
    MetricKind,
    MetricUnit,
)
from globin.errors import ValidationError

BUCKETS: int = len(DEFAULT_SECOND_BOUNDARIES) + 1
"""Boundaries plus overflow."""

observations = st.integers(min_value=0, max_value=20_000_000_000)
"""Durations spanning below the first boundary and past the last."""

increments = st.integers(min_value=0, max_value=10_000)
"""Counter increments valid by construction."""


def _folded(values: list[int]) -> MetricPoint:
    """Fold a sequence of observations into one histogram point.

    Args:
        values: The observations, in order.

    Returns:
        The resulting point.
    """
    point = empty_point(MetricKind.HISTOGRAM, MetricAttributes(), BUCKETS)
    for value in values:
        point = observed(point, value, DEFAULT_SECOND_BOUNDARIES)
    return point


@given(st.lists(observations, max_size=40))
def test_the_bucket_counts_always_sum_to_the_count(values: list[int]) -> None:
    """The histogram invariant, over any sequence rather than one hand-picked.

    A fold that dropped an observation into no bucket would still advance the
    count, and nothing but this would notice.
    """
    point = _folded(values)
    assert sum(point.bucket_counts) == point.count == len(values)


@given(st.lists(observations, max_size=40))
def test_the_total_is_the_sum_of_the_observations(values: list[int]) -> None:
    """A total that drifted from its inputs would misreport every average."""
    assert _folded(values).total == sum(values)


@given(st.lists(observations, max_size=24))
def test_folding_does_not_depend_on_order(values: list[int]) -> None:
    """Two collectors finishing in different orders must produce one point.

    The order-independence property `test_health_properties.py` asserts for the
    health reduction, applied to an accumulator.
    """
    assert _folded(values) == _folded(list(reversed(values)))


@given(observations)
def test_a_bucket_index_is_always_addressable(value: int) -> None:
    """Total, and always inside the array it will index."""
    index = bucket_index(value, DEFAULT_SECOND_BOUNDARIES)
    assert 0 <= index <= len(DEFAULT_SECOND_BOUNDARIES)


@given(observations, observations)
def test_bucket_placement_is_monotone(smaller: int, larger: int) -> None:
    """A larger observation never lands in an earlier bucket."""
    low, high = sorted((smaller, larger))
    assert bucket_index(low, DEFAULT_SECOND_BOUNDARIES) <= bucket_index(
        high, DEFAULT_SECOND_BOUNDARIES
    )


@given(observations)
def test_the_first_and_last_buckets_mean_what_they_say(value: int) -> None:
    """Upper-inclusive at the bottom, overflow at the top."""
    index = bucket_index(value, DEFAULT_SECOND_BOUNDARIES)
    assert (index == 0) == (value <= DEFAULT_SECOND_BOUNDARIES[0])
    assert (index == len(DEFAULT_SECOND_BOUNDARIES)) == (value > DEFAULT_SECOND_BOUNDARIES[-1])


@given(increments, increments, increments)
def test_a_counter_is_monotone_and_associative(start: int, first: int, second: int) -> None:
    """Two increments must equal one of their sum.

    An implementation that clamped, saturated or reset would break this while
    still passing every single-step test.
    """
    once = advanced(advanced(start, first), second)
    assert once == advanced(start, first + second)
    assert once >= start


@given(st.integers(min_value=-10_000, max_value=10_000))
def test_the_increment_screen_and_the_fold_agree(increment: int) -> None:
    """The screen empty must mean the fold succeeds, and conversely.

    A disagreement would mean either an increment that passes review and then
    raises inside the code being measured, or one refused that was safe.
    """
    if increment_problems(increment):
        try:
            advanced(0, increment)
        except ValidationError:
            return
        msg = f"{increment} was screened out but folded anyway"
        raise AssertionError(msg)
    assert advanced(0, increment) == increment


@given(st.integers(min_value=0, max_value=MAXIMUM_METRIC_VALUE))
def test_a_counter_never_silently_passes_the_ceiling(current: int) -> None:
    """Refused and countable, never wrapped — the 2**53 rule at the fold."""
    try:
        result = advanced(current, 1)
    except ValidationError:
        assert current + 1 > MAXIMUM_METRIC_VALUE
        return
    assert result <= MAXIMUM_METRIC_VALUE


@given(st.sampled_from(metric_names()), st.dictionaries(st.text(max_size=12), st.text(max_size=12)))
def test_screening_a_registered_family_is_total(name: str, supplied: dict[str, str]) -> None:
    """Whatever a caller passes, screening returns rather than raising."""
    assert isinstance(screened(descriptor_for(name), supplied), tuple)


@given(st.sampled_from(metric_names()))
def test_every_registered_family_is_bounded_by_arithmetic(name: str) -> None:
    """The runtime budget check should be unreachable for anything declared.

    Asserted over the registry rather than over one entry, so a family added
    later is covered without anybody remembering this test.
    """
    descriptor = descriptor_for(name)
    assert declared_series(descriptor) <= descriptor.cardinality_budget


@given(st.integers(min_value=0, max_value=64), st.lists(observations, max_size=8))
def test_a_snapshot_always_survives_the_codec(value: int, durations: list[int]) -> None:
    """No float ever reaches a persisted telemetry document.

    Asserted by encoding through the real codec, which refuses a float at any
    depth — so this proves the property rather than restating the intention.
    """
    counter_family = MetricSnapshot(
        name="globin.telemetry.observations.total",
        kind=MetricKind.COUNTER,
        unit=MetricUnit.COUNT,
        points=(
            MetricPoint(
                kind=MetricKind.COUNTER,
                attributes=MetricAttributes((("component", "telemetry"), ("result", "ok"))),
                value=value,
            ),
        ),
    )
    histogram_family = MetricSnapshot(
        name="globin.telemetry.snapshot.nanoseconds",
        kind=MetricKind.HISTOGRAM,
        unit=MetricUnit.SECONDS,
        boundaries=DEFAULT_SECOND_BOUNDARIES,
        points=(_folded(durations),),
    )
    snapshot = TelemetrySnapshot(
        generated_at=Instant(datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)),
        uptime=Duration(value),
        run_id="abc",
        families=(counter_family, histogram_family),
        drops=DropCounts(refused=value),
    )
    codec = JsonCodec()
    encoded = codec.encode(snapshot.document())
    assert codec.decode(encoded) == snapshot.document()
    assert codec.encode(snapshot.shape())


@given(st.lists(observations, max_size=12), st.lists(observations, max_size=12))
def test_the_shape_ignores_every_measurement(first: list[int], second: list[int]) -> None:
    """Two runs doing the same logical work share a shape whatever they measured.

    This is the exact property a digest over `shape()` is entitled to rely on, and
    it is asserted rather than asserted-about.
    """

    def _snapshot(durations: list[int], moment: int) -> TelemetrySnapshot:
        family = MetricSnapshot(
            name="globin.telemetry.snapshot.nanoseconds",
            kind=MetricKind.HISTOGRAM,
            unit=MetricUnit.SECONDS,
            boundaries=DEFAULT_SECOND_BOUNDARIES,
            points=(_folded(durations),),
        )
        return TelemetrySnapshot(
            generated_at=Instant(datetime(2026, 8, 17, 12, 0, moment, tzinfo=UTC)),
            uptime=Duration(moment),
            run_id="abc",
            families=(family,),
            drops=DropCounts(malformed=moment),
        )

    assert _snapshot(first, 0).shape() == _snapshot(second, 30).shape()


def test_the_registry_is_stable_across_calls() -> None:
    """`metrics()` is a function, so two calls must not disagree."""
    assert metrics() == metrics()
