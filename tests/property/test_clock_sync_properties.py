"""Invariants of the clock layer over generated input.

Four real invariants, not four restatements of the implementation:

* the two timestamp units name the **same moment** at every resolution;
* the estimator's answer is **exactly** the offset a symmetric path implies, for
  every offset and every round trip — which is the claim a handful of hand-computed
  vectors can only sample;
* the chosen sample is always the **minimum** round trip in the window;
* nothing in the path produces a value a binary float could not have held, because
  nothing in the path is a float.

The last one is worth stating as a property rather than a spot check. Float drift is
not a bug that shows up on round numbers; it shows up on the values nobody chose,
which is exactly what Hypothesis supplies.
"""

from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from globin.domain.api_reality import EnvironmentName, ProductFamily, ProtocolKind
from globin.domain.auth_timing import TimestampUnit
from globin.domain.clock import (
    MICROSECONDS_PER_MILLISECOND,
    Duration,
    Instant,
    MonotonicReading,
    instant,
)
from globin.domain.clock_sync import (
    CalibrationSample,
    ClockDomain,
    ServerTimeReading,
    bound_window,
    choose_sample,
    corrected_stamp,
    offset_bucket,
    round_trip_bucket,
    sample_offset,
)

NANOS_PER_MILLI = 1_000_000

DOMAIN = ClockDomain(
    family=ProductFamily("spot"),
    environment=EnvironmentName("testnet"),
    protocol=ProtocolKind.REST,
)

BASE = Instant(datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC))

offsets = st.integers(min_value=-86_400_000_000, max_value=86_400_000_000)
round_trips = st.integers(min_value=0, max_value=600_000)
microseconds = st.integers(min_value=0, max_value=999_999)


def _moment(micros: int) -> Instant:
    """A moment with a chosen sub-second part.

    Args:
        micros: How many microseconds past the whole second.

    Returns:
        The instant.
    """
    return instant(BASE.moment + timedelta(microseconds=micros))


@given(micros=microseconds, offset=offsets)
def test_the_two_units_name_the_same_moment(micros: int, offset: int) -> None:
    """A millisecond stamp is the microsecond stamp floored, always.

    Not *approximately* — the same integer grid, projected. A conversion that ever
    disagreed would mean one of the two units was computed by a different route.
    """
    moment = _moment(micros)
    micro_stamp = corrected_stamp(moment, offset, TimestampUnit.MICROSECONDS)
    milli_stamp = corrected_stamp(moment, offset, TimestampUnit.MILLISECONDS)
    assert milli_stamp == micro_stamp // MICROSECONDS_PER_MILLISECOND


@given(micros=microseconds, offset=offsets)
def test_a_millisecond_stamp_never_names_a_moment_that_has_not_happened(
    micros: int, offset: int
) -> None:
    """Flooring towards the past, over the whole generated range.

    The venue's second timing check carries no future tolerance at all, so a
    projection that ever rounded *up* would spend an allowance that check does not
    grant. This is that guarantee, stated as an inequality.
    """
    moment = _moment(micros)
    micro_stamp = corrected_stamp(moment, offset, TimestampUnit.MICROSECONDS)
    milli_stamp = corrected_stamp(moment, offset, TimestampUnit.MILLISECONDS)
    assert milli_stamp * MICROSECONDS_PER_MILLISECOND <= micro_stamp
    assert micro_stamp - milli_stamp * MICROSECONDS_PER_MILLISECOND < MICROSECONDS_PER_MILLISECOND


@given(offset=offsets)
def test_a_correction_is_exactly_reversible(offset: int) -> None:
    """Microsecond arithmetic loses nothing, so the correction can be undone.

    The millisecond projection is lossy by design; the microsecond one is not, and
    that asymmetry is what lets the offset be applied before the flooring rather
    than after it.
    """
    stamped = corrected_stamp(BASE, offset, TimestampUnit.MICROSECONDS)
    assert stamped - offset == BASE.epoch_micros


@given(ahead=st.integers(min_value=-3_600_000, max_value=3_600_000), trip=round_trips)
def test_the_estimator_recovers_a_symmetric_offset_exactly(ahead: int, trip: int) -> None:
    """Every offset and every round trip, not the four that were worked out by hand.

    The venue's answer is placed at the true midpoint plus ``ahead``; a correct
    estimator returns ``ahead`` and nothing else. Both are in microseconds, so the
    halving is exact whenever the round trip is even and floored consistently on
    both sides when it is not — which is why the assertion allows a single
    microsecond of floor rather than pretending odd trips divide evenly.
    """
    started = MonotonicReading(0)
    finished = MonotonicReading(trip * 1_000)
    half = (trip * 1_000 // 1_000) // 2
    reading = ServerTimeReading(
        epoch_micros=BASE.epoch_micros + half + ahead + 10**12,
        unit=TimestampUnit.MICROSECONDS,
    )
    sample = sample_offset(
        DOMAIN, reading=reading, wall_anchor=BASE, started=started, finished=finished
    )
    assert sample.offset_micros == ahead + 10**12


@given(trip=round_trips)
def test_the_uncertainty_is_never_more_than_half_the_round_trip(trip: int) -> None:
    """The bound the whole estimator rests on, over every generated trip."""
    started = MonotonicReading(0)
    finished = MonotonicReading(trip * 1_000)
    reading = ServerTimeReading(epoch_micros=BASE.epoch_micros + 1, unit=TimestampUnit.MICROSECONDS)
    sample = sample_offset(
        DOMAIN, reading=reading, wall_anchor=BASE, started=started, finished=finished
    )
    assert sample.uncertainty_micros * 2 <= sample.round_trip.microseconds + 1


@given(
    trips=st.lists(st.integers(min_value=0, max_value=5_000), min_size=1, max_size=16),
)
def test_the_chosen_sample_is_always_the_fastest_in_the_window(trips: list[int]) -> None:
    """The selection rule, over every window shape.

    Stated as *the chosen round trip equals the minimum* rather than by re-running
    the selection, so the assertion is about the property rather than about the
    code that implements it.
    """
    window = tuple(
        CalibrationSample(
            domain=DOMAIN,
            offset_micros=index,
            round_trip=Duration(trip * NANOS_PER_MILLI),
            taken_at=MonotonicReading(index * 10**9),
            wall_anchor_micros=BASE.epoch_micros,
            reported_unit=TimestampUnit.MILLISECONDS,
        )
        for index, trip in enumerate(trips)
    )
    chosen = choose_sample(window)
    assert chosen is not None
    assert chosen.round_trip.milliseconds == min(trips)


@given(
    trips=st.lists(st.integers(min_value=0, max_value=5_000), min_size=0, max_size=40),
    keep=st.integers(min_value=1, max_value=16),
)
def test_the_window_never_exceeds_what_it_keeps(trips: list[int], keep: int) -> None:
    """Bounded memory, over every sequence of calibrations."""
    window: tuple[CalibrationSample, ...] = ()
    for index, trip in enumerate(trips):
        window = bound_window(
            window,
            CalibrationSample(
                domain=DOMAIN,
                offset_micros=index,
                round_trip=Duration(trip * NANOS_PER_MILLI),
                taken_at=MonotonicReading(index * 10**9),
                wall_anchor_micros=BASE.epoch_micros,
                reported_unit=TimestampUnit.MILLISECONDS,
            ),
            keep,
        )
        assert len(window) <= keep


@given(micros=st.integers(min_value=-(10**12), max_value=10**12))
def test_every_offset_falls_in_a_declared_bucket(micros: int) -> None:
    """Cardinality is bounded for every input, not merely for the ones tried."""
    bucket = offset_bucket(micros)
    assert bucket[0] in {"+", "-"}
    assert bucket.endswith(("ms", "over"))


@given(micros=st.integers(min_value=0, max_value=10**12))
def test_every_duration_falls_in_a_declared_bucket(micros: int) -> None:
    """The round-trip dimension, over its whole domain."""
    assert round_trip_bucket(micros).endswith(("ms", "over"))


@given(micros=microseconds, offset=offsets)
def test_no_value_in_the_stamping_path_is_a_float(micros: int, offset: int) -> None:
    """Integer arithmetic end to end, asserted on the types rather than on the values.

    A float that happened to be exact for the generated input would pass a value
    comparison and still be the defect this phase avoids. Checking the *type*
    catches it whatever the value.
    """
    moment = _moment(micros)
    for unit in TimestampUnit:
        stamp = corrected_stamp(moment, offset, unit)
        assert isinstance(stamp, int)
        assert not isinstance(stamp, bool)
