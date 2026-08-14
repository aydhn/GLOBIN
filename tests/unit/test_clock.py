"""The clock units: instants, durations, monotonic readings and the adapters.

Every refusal is tested by name, so a failure line is already the diagnosis
rather than the start of one. What is deliberately *not* here: whether the
composition root wires a clock into the logger, which is
``tests/integration/test_logging_end_to_end.py``; whether the laws hold over
generated input, which is ``tests/property/test_clock_properties.py``; and
whether an inner layer reads a clock, which is
``tests/architecture/test_clock_discipline.py``.

**One rule governs every test that touches a real clock here: no test asserts
that two readings differ.** On the declared host :func:`time.get_clock_info`
reports a 1e-07 resolution, but that is a property of this machine and this
CPython build, not a guarantee. On a host where the wall clock falls back to
``GetSystemTimeAsFileTime()`` the granularity is about 15.6 ms, and two
consecutive reads return the same value. A test asserting ``b > a`` would pass
here and flake in CI. Distinctness comes from :class:`~tests.support.ManualClock`
instead, which is what a double is for.
"""

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from typing import Final

import pytest

from globin.adapters.clock import SystemClock, SystemMonotonicClock
from globin.domain.clock import (
    MAX_EPOCH_MILLIS,
    MICROSECONDS_PER_MILLISECOND,
    MIN_EPOCH_MILLIS,
    NANOSECONDS_PER_MILLISECOND,
    Duration,
    Instant,
    MonotonicReading,
    duration_from_millis,
    instant,
    instant_from_epoch_millis,
)
from globin.errors import ValidationError
from globin.runtime.composition import build_clock, build_monotonic_clock
from tests.support import FixedClock, ManualClock, ManualMonotonicClock

EPOCH: Final[datetime] = datetime(1970, 1, 1, tzinfo=UTC)
"""The Unix epoch, spelled out so the millisecond cases below can be read."""


class _UnhelpfulTimezone(tzinfo):
    """A tzinfo whose ``utcoffset`` returns something that is not a timedelta.

    The standard library raises :class:`TypeError` for this. It exists to reach
    the branch that translates that into a :class:`ValidationError` — a branch
    no realistic input reaches, and therefore one that would otherwise be
    uncovered while looking tested.
    """

    def utcoffset(self, dt: datetime | None) -> timedelta | None:  # noqa: ARG002
        """Return the wrong type on purpose."""
        return "not a timedelta"  # type: ignore[return-value]

    def dst(self, dt: datetime | None) -> timedelta | None:  # noqa: ARG002
        """No daylight saving; present because `tzinfo` declares it abstract."""
        return None

    def tzname(self, dt: datetime | None) -> str | None:  # noqa: ARG002
        """A name, present for the same reason."""
        return "unhelpful"


class _ImpossibleTimezone(tzinfo):
    """A tzinfo whose offset exceeds the day the standard library permits."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:  # noqa: ARG002
        """Return an offset outside the documented range."""
        return timedelta(days=2)

    def dst(self, dt: datetime | None) -> timedelta | None:  # noqa: ARG002
        """No daylight saving; present because `tzinfo` declares it abstract."""
        return None

    def tzname(self, dt: datetime | None) -> str | None:  # noqa: ARG002
        """A name, present for the same reason."""
        return "impossible"


# --------------------------------------------------------------------------
# Instant: what it refuses
# --------------------------------------------------------------------------


def test_a_naive_moment_is_refused() -> None:
    """Invariant 25: a naive datetime does not say which moment it means."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        Instant(datetime(2026, 8, 14, 12))  # noqa: DTZ001


def test_an_aware_moment_at_another_offset_is_refused_by_the_constructor() -> None:
    """Direct construction stays strict; converting is `instant()`'s job.

    The same split as :class:`~globin.domain.values.Quantity` and
    :func:`~globin.domain.values.quantity`: the constructor states the invariant,
    the factory does the accommodating.
    """
    with pytest.raises(ValidationError, match="must be UTC"):
        Instant(datetime(2026, 8, 14, 12, tzinfo=timezone(timedelta(hours=3))))


def test_a_date_is_not_a_datetime() -> None:
    """`datetime` subclasses `date`, so the check must be for the narrower type.

    A check written against ``date`` would admit a ``datetime`` silently, and a
    bare ``date`` has no time of day to be an instant of.
    """
    with pytest.raises(ValidationError, match="must be a datetime"):
        Instant(date(2026, 8, 14))  # type: ignore[arg-type]


def test_something_that_is_not_a_datetime_at_all_is_refused() -> None:
    with pytest.raises(ValidationError, match="must be a datetime"):
        Instant("2026-08-14T12:00:00+00:00")  # type: ignore[arg-type]


def test_a_timezone_that_cannot_report_an_offset_is_refused_as_validation() -> None:
    """A hostile `tzinfo` raises `TypeError`; ADR-0022 requires ours instead."""
    with pytest.raises(ValidationError, match="cannot report an offset"):
        Instant(datetime(2026, 8, 14, 12, tzinfo=_UnhelpfulTimezone()))


def test_a_timezone_whose_offset_is_out_of_range_is_refused_as_validation() -> None:
    """The same branch, reached through `ValueError` rather than `TypeError`."""
    with pytest.raises(ValidationError, match="cannot report an offset"):
        Instant(datetime(2026, 8, 14, 12, tzinfo=_ImpossibleTimezone()))


def test_an_instant_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        Instant(EPOCH).moment = EPOCH  # type: ignore[misc]


# --------------------------------------------------------------------------
# instant(): what it converts
# --------------------------------------------------------------------------


def test_an_aware_moment_at_another_offset_is_converted_not_refused() -> None:
    """An aware datetime names one moment, so converting it is arithmetic."""
    converted = instant(datetime(2026, 8, 14, 12, tzinfo=timezone(timedelta(hours=3))))
    assert str(converted) == "2026-08-14T09:00:00+00:00"


def test_conversion_preserves_the_moment() -> None:
    at_three = datetime(2026, 8, 14, 12, tzinfo=timezone(timedelta(hours=3)))
    assert instant(at_three).moment == at_three


def test_a_naive_moment_is_refused_by_the_factory_too() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        instant(datetime(2026, 8, 14, 12))  # noqa: DTZ001


def test_a_conversion_that_leaves_the_calendar_is_refused() -> None:
    """Year 1 at +14:00 shifts off the front of the representable range.

    The standard library raises :class:`OverflowError` here, which is not a
    ``globin.errors`` type and would cross a domain boundary as a foreign
    exception.
    """
    with pytest.raises(ValidationError, match="leaves the range"):
        instant(datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14))))


# --------------------------------------------------------------------------
# Milliseconds: the floor rule
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("microseconds", "expected"),
    [
        (0, 0),
        (1, 0),
        (999, 0),
        (1_000, 1),
        (1_999, 1),
        (2_000, 2),
    ],
)
def test_milliseconds_floor_rather_than_round(microseconds: int, expected: int) -> None:
    """Truncation never claims an event happened later than it did."""
    moment = Instant(EPOCH + timedelta(microseconds=microseconds))
    assert moment.epoch_millis == expected


@pytest.mark.parametrize(
    ("microseconds", "expected"),
    [
        (-1, -1),
        (-999, -1),
        (-1_000, -1),
        (-1_500, -2),
    ],
)
def test_milliseconds_floor_towards_the_past_before_the_epoch_too(
    microseconds: int, expected: int
) -> None:
    """`//` floors rather than truncating towards zero, and that is wanted.

    A conversion that changed direction at the epoch would be a latent surprise.
    Instants before 1970 are not something GLOBIN trades on; a rule that means
    one thing everywhere is still worth more than one that means two.
    """
    moment = Instant(EPOCH + timedelta(microseconds=microseconds))
    assert moment.epoch_millis == expected


def test_a_whole_millisecond_round_trips_exactly() -> None:
    assert instant_from_epoch_millis(1_755_172_800_123).epoch_millis == 1_755_172_800_123


def test_the_documented_bounds_are_the_calendars_bounds() -> None:
    """The literals are derived here, so they cannot drift from what they claim.

    They are literals in the module because building a datetime at module level
    is a call, and the architecture suite refuses one in a layer package.
    """
    earliest_representable = datetime.min.replace(tzinfo=UTC)
    latest_representable = datetime.max.replace(tzinfo=UTC)

    lowest = EPOCH + timedelta(microseconds=MIN_EPOCH_MILLIS * MICROSECONDS_PER_MILLISECOND)
    highest = EPOCH + timedelta(microseconds=MAX_EPOCH_MILLIS * MICROSECONDS_PER_MILLISECOND)
    assert lowest == earliest_representable
    assert highest.replace(microsecond=999_999) == latest_representable


@pytest.mark.parametrize("millis", [MIN_EPOCH_MILLIS, MAX_EPOCH_MILLIS])
def test_the_bounds_themselves_are_admitted(millis: int) -> None:
    assert instant_from_epoch_millis(millis).epoch_millis == millis


@pytest.mark.parametrize("millis", [MIN_EPOCH_MILLIS - 1, MAX_EPOCH_MILLIS + 1])
def test_a_value_outside_the_calendar_is_refused_by_name(millis: int) -> None:
    """Checked before construction, so the message names the value and the limit.

    Catching the standard library's :class:`OverflowError` would report that an
    internal conversion failed, which tells the caller nothing about what to fix.
    """
    with pytest.raises(ValidationError, match="outside the range"):
        instant_from_epoch_millis(millis)


def test_a_bool_is_not_a_count_of_milliseconds() -> None:
    """`isinstance(True, int)` is `True`, so the bool guard must come first."""
    with pytest.raises(ValidationError, match="got the bool"):
        instant_from_epoch_millis(True)


def test_a_float_is_not_a_count_of_milliseconds() -> None:
    with pytest.raises(ValidationError, match="must be an int"):
        instant_from_epoch_millis(1_755_172_800_123.0)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def test_instants_order_and_never_refuse() -> None:
    """There is one denomination for wall time, which is the whole phase.

    The contrast with :class:`~globin.domain.values.Price` is deliberate: two
    prices can share a type and still be incomparable, so ordering them can
    raise. Two instants never can.
    """
    earlier = instant_from_epoch_millis(1_000)
    later = instant_from_epoch_millis(2_000)
    assert earlier < later
    assert later > earlier
    assert earlier != later


def test_comparing_an_instant_with_a_foreign_type_raises_type_error() -> None:
    """`NotImplemented` reaches Python, which names both types."""
    with pytest.raises(TypeError):
        _ = instant_from_epoch_millis(0) < 0  # type: ignore[operator]


def test_an_instant_defines_no_subtraction() -> None:
    """Elapsed time is the monotonic clock's job, not the wall clock's.

    The host's wall clock reports ``adjustable=True``. The difference between
    two of its readings is not reliably an elapsed time, and an operator that
    silently returned one would make the wrong measurement easy to write and
    impossible to notice.
    """
    with pytest.raises(TypeError):
        _ = instant_from_epoch_millis(2_000) - instant_from_epoch_millis(1_000)  # type: ignore[operator]


# --------------------------------------------------------------------------
# Duration
# --------------------------------------------------------------------------


def test_a_negative_duration_is_refused() -> None:
    with pytest.raises(ValidationError, match="must not be negative"):
        Duration(-1)


def test_a_zero_duration_is_admitted() -> None:
    """Two readings can be equal within the clock's resolution."""
    assert Duration(0).milliseconds == 0


def test_a_bool_is_not_a_count_of_nanoseconds() -> None:
    with pytest.raises(ValidationError, match="got the bool"):
        Duration(True)


@pytest.mark.parametrize(
    ("nanoseconds", "expected"),
    [(0, 0), (999_999, 0), (1_000_000, 1), (1_999_999, 1), (2_000_000, 2)],
)
def test_a_duration_floors_to_milliseconds_like_an_instant_does(
    nanoseconds: int, expected: int
) -> None:
    """One millisecond convention in the phase, not two."""
    assert Duration(nanoseconds).milliseconds == expected


def test_a_duration_can_be_built_from_milliseconds() -> None:
    assert duration_from_millis(250).nanoseconds == 250 * NANOSECONDS_PER_MILLISECOND


def test_a_negative_count_of_milliseconds_is_refused() -> None:
    with pytest.raises(ValidationError, match="must not be negative"):
        duration_from_millis(-1)


# --------------------------------------------------------------------------
# MonotonicReading
# --------------------------------------------------------------------------


def test_a_negative_reading_is_admitted_because_the_origin_is_undefined() -> None:
    """Asserted as a permission, so nobody adds a sign check later.

    :func:`time.monotonic` documents its reference point as undefined. A rule
    that refused a negative reading would be a claim the source does not make.
    """
    assert MonotonicReading(-5).nanoseconds == -5


def test_a_bool_is_not_a_reading() -> None:
    with pytest.raises(ValidationError, match="got the bool"):
        MonotonicReading(True)


def test_elapsed_time_between_two_readings_is_exact() -> None:
    elapsed = MonotonicReading(5_000_000).since(MonotonicReading(1_000_000))
    assert elapsed == Duration(4_000_000)
    assert elapsed.milliseconds == 4


def test_readings_subtracted_in_the_wrong_order_are_refused_by_name() -> None:
    """The message names both explanations, because they are different faults."""
    with pytest.raises(ValidationError, match="the earlier reading is the larger one"):
        MonotonicReading(1_000).since(MonotonicReading(5_000))


def test_elapsed_time_against_a_foreign_type_is_refused() -> None:
    with pytest.raises(ValidationError, match="another MonotonicReading"):
        MonotonicReading(5).since(instant_from_epoch_millis(0))


def test_a_reading_cannot_be_turned_into_a_moment() -> None:
    """The absence is the type doing its job.

    A reading denotes no calendar moment, so offering a conversion would claim a
    correspondence the platform does not promise.
    """
    assert not hasattr(MonotonicReading(0), "epoch_millis")


# --------------------------------------------------------------------------
# The adapters
# --------------------------------------------------------------------------


def test_the_system_clock_answers_in_utc() -> None:
    """The value is never asserted — only that it is aware and at UTC."""
    now = SystemClock().now()
    assert now.moment.utcoffset() == timedelta(0)


def test_two_system_clocks_compare_equal() -> None:
    """Frozen and stateless, so holding one does not make a component unequal."""
    assert SystemClock() == SystemClock()
    assert SystemMonotonicClock() == SystemMonotonicClock()


def test_the_monotonic_clock_never_goes_backwards() -> None:
    """`>=`, never `>`.

    Two consecutive reads may land in the same tick on a host whose monotonic
    source is coarse. Asserting they differ would be asserting the resolution of
    whatever machine happens to run the suite.
    """
    first = SystemMonotonicClock().reading()
    second = SystemMonotonicClock().reading()
    assert second.nanoseconds >= first.nanoseconds


def test_a_real_elapsed_measurement_is_a_duration() -> None:
    clock = SystemMonotonicClock()
    first = clock.reading()
    second = clock.reading()
    assert second.since(first).nanoseconds >= 0


# --------------------------------------------------------------------------
# The composition root
# --------------------------------------------------------------------------


def test_the_composition_root_is_where_the_concrete_clocks_are_named() -> None:
    """Both builders return the adapter, declared as the port.

    The return *annotations* are the ports, so no caller learns which adapter it
    got — that is ADR-0014 and ADR-0015 made concrete. The assertions here are
    about the runtime value, which is the half a type checker cannot see.

    `build_monotonic_clock` has no caller in GLOBIN yet, so without this test the
    only new line in the composition root would be unexecuted. An untested
    factory is how a phase ships a port that does not work.
    """
    assert build_clock() == SystemClock()
    assert build_monotonic_clock() == SystemMonotonicClock()


# --------------------------------------------------------------------------
# The doubles
# --------------------------------------------------------------------------


def test_the_fixed_clock_repeats_itself() -> None:
    clock = FixedClock(instant_from_epoch_millis(1_000))
    assert clock.now() == clock.now()


def test_the_manual_clock_advances_by_its_step() -> None:
    clock = ManualClock(current=instant_from_epoch_millis(0), step=duration_from_millis(500))
    assert [clock.now().epoch_millis for _ in range(3)] == [0, 500, 1_000]


def test_the_manual_monotonic_clock_advances_by_its_step() -> None:
    clock = ManualMonotonicClock(
        current=MonotonicReading(0),
        step=duration_from_millis(1),
    )
    first = clock.reading()
    second = clock.reading()
    assert second.since(first) == Duration(NANOSECONDS_PER_MILLISECOND)
