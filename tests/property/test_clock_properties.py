"""Laws the clock types obey over generated input.

These are the invariants an example cannot establish. Two of them are load
bearing in a way worth naming:

*Monotonicity alone does not pin the rounding mode.* Rounding half-even is
monotone too, so a test that only checked ordering would pass against a
conversion that moves an instant *forward*. The property that actually
distinguishes flooring is
:func:`test_the_millisecond_projection_never_moves_an_instant_forward`, and it
is the reason this module exists rather than a handful more unit tests.

*Ordering is total.* Phase 008's value types refuse a comparison across
denominations, so their ordering law has an exception. Wall time has exactly one
denomination, which is the phase, so this one has none — and asserting the
absence is what stops a later contributor adding a refusal that looks
symmetrical with :class:`~globin.domain.values.Price` and is not.

**Timezone strategies are built from fixed offsets, not from
:func:`hypothesis.strategies.timezones`.** That strategy reads a timezone
database. One is present on the developer host, but ``dependencies = []`` is a
contract test and a bare CI runner is not obliged to carry one. A generated
:class:`~datetime.timezone` covers the same ground with nothing to install.
"""

from datetime import UTC, datetime, timedelta, timezone
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from globin.domain.clock import (
    MAX_EPOCH_MILLIS,
    MIN_EPOCH_MILLIS,
    NANOSECONDS_PER_MILLISECOND,
    Duration,
    Instant,
    MonotonicReading,
    instant,
    instant_from_epoch_millis,
)
from globin.errors import ValidationError

MAX_UTC_OFFSET_MINUTES: Final[int] = 1439
"""One minute short of a day, which is the range `tzinfo` documents."""

offsets = st.integers(min_value=-MAX_UTC_OFFSET_MINUTES, max_value=MAX_UTC_OFFSET_MINUTES).map(
    lambda minutes: timezone(timedelta(minutes=minutes))
)

#: Datetimes with a clear day at each end of the calendar, so that shifting one
#: by its offset cannot leave the representable range. That overflow is real and
#: is refused deliberately — it has its own unit test rather than being generated
#: into every property here.
naive_moments = st.datetimes(
    min_value=datetime(2, 1, 1),  # noqa: DTZ001
    max_value=datetime(9998, 12, 31),  # noqa: DTZ001
)

aware_moments = st.builds(
    lambda moment, zone: moment.replace(tzinfo=zone),
    naive_moments,
    offsets,
)

utc_moments = st.builds(lambda moment: moment.replace(tzinfo=UTC), naive_moments)
instants = st.builds(Instant, utc_moments)

epoch_millis = st.integers(min_value=MIN_EPOCH_MILLIS, max_value=MAX_EPOCH_MILLIS)
readings = st.builds(MonotonicReading, st.integers(min_value=-(2**62), max_value=2**62))
durations = st.builds(Duration, st.integers(min_value=0, max_value=2**62))


@given(moment=aware_moments)
def test_converting_an_offset_never_moves_the_point(moment: datetime) -> None:
    """`instant()` re-expresses a moment; it does not change which one it is."""
    converted = instant(moment)
    assert converted.moment == moment
    assert converted.moment.utcoffset() == timedelta(0)


@given(moment=naive_moments)
def test_every_naive_moment_is_refused(moment: datetime) -> None:
    """No offset, no exceptions."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        instant(moment)


@given(earlier=instants, later=instants)
def test_the_millisecond_projection_is_monotone(earlier: Instant, later: Instant) -> None:
    """Ordering by milliseconds agrees with ordering by instants.

    This is what makes it safe to sort records by their wire timestamp.
    """
    if earlier <= later:
        assert earlier.epoch_millis <= later.epoch_millis


@given(moment=instants)
def test_the_millisecond_projection_never_moves_an_instant_forward(moment: Instant) -> None:
    """The property that distinguishes flooring from every rounding mode.

    Round-half-even is monotone too, so the monotonicity law above would accept
    it. Only this one refuses it: the projected moment is never later than the
    moment it came from, and it is less than one millisecond earlier.
    """
    projected = instant_from_epoch_millis(moment.epoch_millis)
    assert projected <= moment
    assert moment.moment - projected.moment < timedelta(milliseconds=1)


@given(millis=epoch_millis)
def test_a_whole_millisecond_round_trips_exactly(millis: int) -> None:
    """The reverse projection loses nothing, because there is nothing to lose."""
    assert instant_from_epoch_millis(millis).epoch_millis == millis


@given(left=instants, right=instants)
def test_ordering_is_total_and_never_refuses(left: Instant, right: Instant) -> None:
    """Exactly one of `<`, `==`, `>` holds, and none of them raises."""
    assert [left < right, left == right, left > right].count(True) == 1


@given(left=instants, right=st.one_of(instants, readings, durations, st.integers(), st.text()))
def test_equality_never_raises_for_any_pair(left: Instant, right: object) -> None:
    """`__eq__` is called by `in`, by `dict` and by every assertion in the suite."""
    assert isinstance(left == right, bool)
    assert (left == right) is not (left != right)


@given(earlier=readings, later=readings)
def test_elapsed_time_is_exact_or_refused(
    earlier: MonotonicReading, later: MonotonicReading
) -> None:
    """Integer subtraction throughout: no float ever enters the path."""
    if later.nanoseconds >= earlier.nanoseconds:
        assert later.since(earlier).nanoseconds == later.nanoseconds - earlier.nanoseconds
    else:
        with pytest.raises(ValidationError, match="the earlier reading is the larger one"):
            later.since(earlier)


@given(length=durations)
def test_a_duration_floors_to_milliseconds_by_the_same_law(length: Duration) -> None:
    """One convention, two call sites, one law.

    Stated as a bound rather than as a formula, so that reimplementing the
    conversion cannot make the test agree with it by construction.
    """
    millis = length.milliseconds
    assert millis * NANOSECONDS_PER_MILLISECOND <= length.nanoseconds
    assert length.nanoseconds < (millis + 1) * NANOSECONDS_PER_MILLISECOND
