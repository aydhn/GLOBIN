"""The five synchronisation states, and which conditions reach each one.

The state machine is where a wrong answer is most expensive, because every other
gate trusts it: :func:`~globin.domain.clock_sync.admit` refuses on the state alone
before it looks at a sample. So each state is reached here by constructing the
condition that should produce it, and the states that must **not** be reached by
that condition are asserted too — a machine that answered ``SYNCHRONIZED`` for
everything would pass a test that only ever checked the happy path.
"""

from datetime import UTC, datetime

import pytest

from globin.domain.api_reality import EnvironmentName, ProductFamily, ProtocolKind
from globin.domain.auth_timing import TimestampUnit
from globin.domain.clock import (
    MICROSECONDS_PER_MILLISECOND,
    Duration,
    Instant,
    MonotonicReading,
)
from globin.domain.clock_sync import (
    CalibrationSample,
    ClockDiscipline,
    ClockDomain,
    JumpDirection,
    JumpVerdict,
    SyncState,
    default_discipline,
    evaluate,
)
from globin.errors import ValidationError

NANOS_PER_MILLI = 1_000_000

DOMAIN = ClockDomain(
    family=ProductFamily("spot"),
    environment=EnvironmentName("testnet"),
    protocol=ProtocolKind.REST,
)

MOMENT = Instant(datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC))


def _sample(*, offset_millis: int = 1, round_trip_millis: int = 40) -> CalibrationSample:
    """A sample with a chosen offset and round trip.

    Args:
        offset_millis: How far ahead the venue is.
        round_trip_millis: How long the exchange took.

    Returns:
        The sample.
    """
    return CalibrationSample(
        domain=DOMAIN,
        offset_micros=offset_millis * MICROSECONDS_PER_MILLISECOND,
        round_trip=Duration(round_trip_millis * NANOS_PER_MILLI),
        taken_at=MonotonicReading(round_trip_millis * NANOS_PER_MILLI),
        wall_anchor_micros=MOMENT.epoch_micros,
        reported_unit=TimestampUnit.MILLISECONDS,
    )


def _jump(discipline: ClockDiscipline) -> JumpVerdict:
    """A verdict reporting a forward jump well past the threshold.

    Args:
        discipline: Whose threshold to exceed.

    Returns:
        The verdict.
    """
    threshold = discipline.max_wall_divergence.microseconds
    return JumpVerdict(
        direction=JumpDirection.FORWARD,
        divergence_micros=threshold * 5,
        threshold_micros=threshold,
    )


# ---------------------------------------------------------------------------
# Reaching each state
# ---------------------------------------------------------------------------


def test_a_domain_with_no_sample_is_uninitialized() -> None:
    """A fresh process has asked nothing, and says so rather than guessing."""
    status = evaluate(DOMAIN, samples=(), age=None, discipline=default_discipline())
    assert status.state is SyncState.UNINITIALIZED
    assert not status.synchronized
    assert status.sample is None
    assert "never been calibrated" in status.detail or "no calibration" in status.detail


def test_a_fresh_sample_inside_every_bound_is_synchronized() -> None:
    """The only state that admits a signature."""
    status = evaluate(
        DOMAIN, samples=(_sample(),), age=Duration(0), discipline=default_discipline()
    )
    assert status.state is SyncState.SYNCHRONIZED
    assert status.synchronized


def test_a_sample_past_the_freshness_interval_is_stale() -> None:
    """Nothing went wrong; nothing has been checked recently either."""
    discipline = default_discipline()
    status = evaluate(
        DOMAIN,
        samples=(_sample(),),
        age=Duration(discipline.freshness_ttl.nanoseconds + 1),
        discipline=discipline,
    )
    assert status.state is SyncState.STALE
    assert not status.synchronized
    assert str(discipline.freshness_ttl.milliseconds) in status.detail


def test_a_failed_probe_with_a_recent_sample_is_degraded() -> None:
    """Describable, not usable — and distinct from having never known."""
    status = evaluate(
        DOMAIN,
        samples=(_sample(),),
        age=Duration(0),
        discipline=default_discipline(),
        last_probe_failed=True,
    )
    assert status.state is SyncState.DEGRADED
    assert not status.synchronized
    assert status.sample is not None


def test_a_failed_probe_past_the_grace_period_is_stale_rather_than_degraded() -> None:
    """A sample nobody has refreshed for that long is old, not merely unrefreshed."""
    discipline = default_discipline()
    status = evaluate(
        DOMAIN,
        samples=(_sample(),),
        age=Duration(discipline.degraded_grace.nanoseconds + 1),
        discipline=discipline,
        last_probe_failed=True,
    )
    assert status.state is SyncState.STALE


def test_a_detected_jump_is_unsynchronized() -> None:
    """Being told the estimate is wrong outranks the estimate looking fine."""
    discipline = default_discipline()
    status = evaluate(
        DOMAIN,
        samples=(_sample(),),
        age=Duration(0),
        discipline=discipline,
        jump=_jump(discipline),
    )
    assert status.state is SyncState.UNSYNCHRONIZED
    assert "wall clock moved forward" in status.detail


def test_an_explicit_invalidation_is_unsynchronized() -> None:
    """What a venue `-1021` produces, with no jump having been observed."""
    status = evaluate(
        DOMAIN,
        samples=(_sample(),),
        age=Duration(0),
        discipline=default_discipline(),
        invalidated=True,
    )
    assert status.state is SyncState.UNSYNCHRONIZED
    assert "invalidated" in status.detail


def test_a_jump_outranks_a_fresh_sample_and_a_failed_probe_alike() -> None:
    """Ordering, asserted rather than assumed.

    A jump arriving together with a failed probe must still report
    `UNSYNCHRONIZED`: the failed probe is the lesser fact, and reporting `DEGRADED`
    would let a stepped clock look like a slow network.
    """
    discipline = default_discipline()
    status = evaluate(
        DOMAIN,
        samples=(_sample(),),
        age=Duration(0),
        discipline=discipline,
        last_probe_failed=True,
        jump=_jump(discipline),
    )
    assert status.state is SyncState.UNSYNCHRONIZED


def test_a_slow_sample_is_degraded_rather_than_synchronized() -> None:
    """A real measurement GLOBIN will not sign with."""
    discipline = default_discipline()
    slow = _sample(round_trip_millis=discipline.max_round_trip.milliseconds + 1)
    status = evaluate(DOMAIN, samples=(slow,), age=Duration(0), discipline=discipline)
    assert status.state is SyncState.DEGRADED
    assert "limit is" in status.detail


def test_an_uncertain_sample_is_degraded() -> None:
    """Uncertainty is half the round trip, so this needs a discipline that separates them."""
    base = default_discipline()
    discipline = ClockDiscipline(
        sample_count=base.sample_count,
        freshness_ttl=base.freshness_ttl,
        degraded_grace=base.degraded_grace,
        max_round_trip=Duration(2_000 * NANOS_PER_MILLI),
        max_uncertainty=Duration(10 * NANOS_PER_MILLI),
        max_offset_jump=base.max_offset_jump,
        max_wall_divergence=base.max_wall_divergence,
        network_budget=base.network_budget,
    )
    status = evaluate(
        DOMAIN, samples=(_sample(round_trip_millis=100),), age=Duration(0), discipline=discipline
    )
    assert status.state is SyncState.DEGRADED
    assert "could be wrong by" in status.detail


def test_recovery_after_a_transient_failure_returns_to_synchronized() -> None:
    """The whole point of `DEGRADED` being a state rather than a terminal one."""
    discipline = default_discipline()
    window = (_sample(),)
    degraded = evaluate(
        DOMAIN, samples=window, age=Duration(0), discipline=discipline, last_probe_failed=True
    )
    assert degraded.state is SyncState.DEGRADED
    recovered = evaluate(DOMAIN, samples=window, age=Duration(0), discipline=discipline)
    assert recovered.state is SyncState.SYNCHRONIZED


# ---------------------------------------------------------------------------
# The invariants the type enforces
# ---------------------------------------------------------------------------


def test_exactly_one_state_admits_a_signature() -> None:
    """Counted rather than named, so a sixth state cannot quietly become admitting."""
    assert [state for state in SyncState if state.admits] == [SyncState.SYNCHRONIZED]


def test_a_status_reporting_uninitialized_cannot_carry_a_sample() -> None:
    """A domain that has never calibrated has nothing to offer."""
    from globin.domain.clock_sync import ClockStatus

    with pytest.raises(ValidationError, match="nothing to offer"):
        ClockStatus(
            domain=DOMAIN,
            state=SyncState.UNINITIALIZED,
            sample=_sample(),
            detail="x",
        )


def test_a_status_reporting_synchronized_must_carry_a_sample() -> None:
    """The type refuses the combination the caller would misread."""
    from globin.domain.clock_sync import ClockStatus

    with pytest.raises(ValidationError, match="carries no calibration sample"):
        ClockStatus(domain=DOMAIN, state=SyncState.SYNCHRONIZED)


def test_a_refusing_status_must_explain_itself() -> None:
    """An operator reading a refusal needs to know what to change."""
    from globin.domain.clock_sync import ClockStatus

    with pytest.raises(ValidationError, match="explains nothing"):
        ClockStatus(domain=DOMAIN, state=SyncState.STALE, sample=_sample(), age=Duration(0))


# ---------------------------------------------------------------------------
# The discipline refuses a set that contradicts itself
# ---------------------------------------------------------------------------


def _discipline(**overrides: Duration | int) -> ClockDiscipline:
    """A discipline with one or more thresholds replaced.

    Args:
        **overrides: Fields to replace.

    Returns:
        The discipline.
    """
    base = default_discipline()
    fields: dict[str, Duration | int] = {
        "sample_count": base.sample_count,
        "freshness_ttl": base.freshness_ttl,
        "degraded_grace": base.degraded_grace,
        "max_round_trip": base.max_round_trip,
        "max_uncertainty": base.max_uncertainty,
        "max_offset_jump": base.max_offset_jump,
        "max_wall_divergence": base.max_wall_divergence,
        "network_budget": base.network_budget,
    }
    fields.update(overrides)
    return ClockDiscipline(**fields)  # type: ignore[arg-type]


def test_a_grace_shorter_than_the_freshness_interval_is_refused() -> None:
    """It would make the degraded state unreachable."""
    with pytest.raises(ValidationError, match="degraded state unreachable"):
        _discipline(degraded_grace=Duration(NANOS_PER_MILLI))


def test_an_uncertainty_limit_above_half_the_round_trip_limit_is_refused() -> None:
    """The uncertainty gate could never fire, because it is half the round trip."""
    with pytest.raises(ValidationError, match="could never fire"):
        _discipline(
            max_round_trip=Duration(100 * NANOS_PER_MILLI),
            max_uncertainty=Duration(90 * NANOS_PER_MILLI),
        )


def test_an_uncertainty_limit_at_the_venues_future_tolerance_is_refused() -> None:
    """The construction rule that makes the future half of the venue's check structural."""
    with pytest.raises(ValidationError, match="future tolerance"):
        _discipline(
            max_round_trip=Duration(4_000 * NANOS_PER_MILLI),
            max_uncertainty=Duration(1_000 * NANOS_PER_MILLI),
        )


@pytest.mark.parametrize("count", [0, 17, -1], ids=["none", "too-many", "negative"])
def test_a_sample_count_outside_the_bounds_is_refused(count: int) -> None:
    """An unbounded window is an unbounded allocation."""
    with pytest.raises(ValidationError, match="between 1 and"):
        _discipline(sample_count=count)


def test_a_threshold_of_zero_is_refused() -> None:
    """Zero would disable a gate by arithmetic rather than by a decision."""
    with pytest.raises(ValidationError, match="not a usable interval"):
        _discipline(max_wall_divergence=Duration(0))


def test_a_threshold_that_is_not_a_duration_is_refused() -> None:
    """Milliseconds as a bare integer would be off by a factor of a million."""
    with pytest.raises(ValidationError, match="must be a Duration"):
        _discipline(freshness_ttl=1_000)


def test_the_required_window_is_the_uncertainty_plus_the_budget() -> None:
    """The floor a configured window has to clear, stated once."""
    discipline = default_discipline()
    assert discipline.required_window_micros == (
        discipline.max_uncertainty.microseconds + discipline.network_budget.microseconds
    )
