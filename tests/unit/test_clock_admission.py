"""The seven gates, the timing context they produce, and the venue rule they satisfy.

Two properties are asserted here that nothing else in the suite can assert.

The first is that **a refusal offers nothing to stamp with**. Every gate is driven
to fire and the resulting admission is checked for a context — not because the
implementation looks like it might carry one, but because the whole safety argument
is that a caller which ignored the outcome would find nothing to misuse.

The second is that **an admitted timestamp survives the venue's own published
rule**. That check runs the pseudo-code from ``rest-api.md`` against GLOBIN's
output, at both extremes of the error bound GLOBIN claimed and after the whole
network budget has been spent. It is the one assertion in this file whose expected
answer this repository did not choose.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from globin.application.clock_sync import admit_request
from globin.domain.api_reality import EnvironmentName, ProductFamily, ProtocolKind
from globin.domain.auth_timing import RecvWindow, TimestampUnit, default_recv_window
from globin.domain.clock import (
    MICROSECONDS_PER_MILLISECOND,
    Duration,
    Instant,
    MonotonicReading,
)
from globin.domain.clock_sync import (
    FUTURE_TOLERANCE_MILLIS,
    MAX_TIMING_RETRIES,
    AdmissionStatus,
    CalibrationSample,
    ClockDiscipline,
    ClockDomain,
    ClockStatus,
    JumpDirection,
    JumpVerdict,
    RecvWindowPolicy,
    SyncState,
    TimingAdmission,
    TimingContext,
    admit,
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


def _sample(*, offset_millis: int = 200, round_trip_millis: int = 40) -> CalibrationSample:
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


def _healthy(**kwargs: object) -> ClockStatus:
    """A synchronized status over one good sample.

    Args:
        **kwargs: Passed through to :func:`_sample`.

    Returns:
        The status.
    """
    return evaluate(
        DOMAIN,
        samples=(_sample(**kwargs),),  # type: ignore[arg-type]
        age=Duration(0),
        discipline=default_discipline(),
    )


def _admit(status: ClockStatus, **kwargs: object) -> TimingAdmission:
    """Admit against a status, with sensible defaults.

    Args:
        status: What is known about the clock.
        **kwargs: Overrides for the admission.

    Returns:
        The admission.
    """
    arguments: dict[str, object] = {
        "moment": MOMENT,
        "unit": TimestampUnit.MILLISECONDS,
        "policy": RecvWindowPolicy(window=default_recv_window()),
        "discipline": default_discipline(),
    }
    arguments.update(kwargs)
    return admit(status, **arguments)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_a_synchronized_clock_admits_and_carries_a_corrected_timestamp() -> None:
    """The offset is applied, so the stamp is the venue's time rather than the host's."""
    admission = _admit(_healthy())
    assert admission.admitted
    assert admission.context is not None
    assert admission.context.timestamp == MOMENT.epoch_millis + 200
    assert admission.context.recv_window == default_recv_window()
    assert admission.context.attempt == 0


def test_the_microsecond_unit_is_carried_through_to_the_stamp() -> None:
    """The unit is decided once, at admission, and travels on the context."""
    admission = _admit(_healthy(), unit=TimestampUnit.MICROSECONDS)
    assert admission.context is not None
    assert admission.context.unit is TimestampUnit.MICROSECONDS
    assert admission.context.timestamp == MOMENT.epoch_micros + 200_000


def test_the_context_carries_the_provenance_of_its_own_correction() -> None:
    """A timestamp with no error bound beside it is a claim rather than a measurement."""
    admission = _admit(_healthy(round_trip_millis=80))
    assert admission.context is not None
    assert admission.context.offset_micros == 200 * MICROSECONDS_PER_MILLISECOND
    assert admission.context.uncertainty_micros == 40 * MICROSECONDS_PER_MILLISECOND
    assert admission.context.round_trip_micros == 80 * MICROSECONDS_PER_MILLISECOND


# ---------------------------------------------------------------------------
# Every gate, driven to fire
# ---------------------------------------------------------------------------


def test_gate_1_refuses_a_domain_with_no_declared_source() -> None:
    """The state every non-Spot family is in: named, and never guessed at."""
    admission = _admit(_healthy(), source_available=False)
    assert admission.outcome is AdmissionStatus.CLOCK_SOURCE_UNAVAILABLE
    assert "never guessed" in admission.detail


def test_gate_2_refuses_a_clock_that_has_never_been_calibrated() -> None:
    """A fresh process signs nothing."""
    empty = evaluate(DOMAIN, samples=(), age=None, discipline=default_discipline())
    admission = _admit(empty)
    assert admission.outcome is AdmissionStatus.CLOCK_NOT_SYNCHRONIZED


def test_gate_3_refuses_after_a_wall_clock_jump() -> None:
    """A stepped host clock invalidates the estimate that was taken before it."""
    discipline = default_discipline()
    threshold = discipline.max_wall_divergence.microseconds
    jumped = evaluate(
        DOMAIN,
        samples=(_sample(),),
        age=Duration(0),
        discipline=discipline,
        jump=JumpVerdict(
            direction=JumpDirection.BACKWARD,
            divergence_micros=-threshold * 4,
            threshold_micros=threshold,
        ),
    )
    admission = _admit(jumped)
    assert admission.outcome is AdmissionStatus.CLOCK_JUMP_DETECTED


def test_an_invalidation_without_a_jump_refuses_as_not_synchronized() -> None:
    """`-1021` disbelieves the estimate without any wall-clock evidence."""
    invalidated = evaluate(
        DOMAIN,
        samples=(_sample(),),
        age=Duration(0),
        discipline=default_discipline(),
        invalidated=True,
    )
    admission = _admit(invalidated)
    assert admission.outcome is AdmissionStatus.CLOCK_NOT_SYNCHRONIZED


def test_gate_4_refuses_a_stale_calibration() -> None:
    """Freshness is a gate, not a hint."""
    discipline = default_discipline()
    stale = evaluate(
        DOMAIN,
        samples=(_sample(),),
        age=Duration(discipline.freshness_ttl.nanoseconds * 2),
        discipline=discipline,
    )
    admission = _admit(stale)
    assert admission.outcome is AdmissionStatus.CLOCK_CALIBRATION_STALE


def test_a_degraded_clock_refuses_as_stale() -> None:
    """A surviving sample nobody is refreshing does not admit."""
    degraded = evaluate(
        DOMAIN,
        samples=(_sample(),),
        age=Duration(0),
        discipline=default_discipline(),
        last_probe_failed=True,
    )
    admission = _admit(degraded)
    assert admission.outcome is AdmissionStatus.CLOCK_CALIBRATION_STALE


def test_gate_7_refuses_a_window_narrower_than_the_budget() -> None:
    """A configured window that cannot cover the measured uncertainty."""
    admission = _admit(_healthy(), policy=RecvWindowPolicy(window=RecvWindow(Decimal(500))))
    assert admission.outcome is AdmissionStatus.RECV_WINDOW_POLICY_VIOLATION
    assert "refuses rather than widening" in admission.detail


def test_the_window_refusal_names_widening_as_something_globin_will_not_do() -> None:
    """The sentence `auth_timing.py` has carried since Phase 035, now enforced."""
    admission = _admit(_healthy(), policy=RecvWindowPolicy(window=RecvWindow(Decimal(500))))
    assert "matching engine" in admission.detail


def test_the_budget_gate_fires_when_no_window_could_cover_the_requirement() -> None:
    """A different remedy from a narrow window: widening cannot help here."""
    base = default_discipline()
    discipline = ClockDiscipline(
        sample_count=base.sample_count,
        freshness_ttl=base.freshness_ttl,
        degraded_grace=base.degraded_grace,
        max_round_trip=base.max_round_trip,
        max_uncertainty=base.max_uncertainty,
        max_offset_jump=base.max_offset_jump,
        max_wall_divergence=base.max_wall_divergence,
        network_budget=Duration(70_000 * NANOS_PER_MILLI),
    )
    status = evaluate(DOMAIN, samples=(_sample(),), age=Duration(0), discipline=discipline)
    admission = _admit(
        status,
        discipline=discipline,
        policy=RecvWindowPolicy(window=RecvWindow(Decimal(60_000))),
    )
    assert admission.outcome is AdmissionStatus.TIMING_BUDGET_EXCEEDED
    assert "no configuration could cover this" in admission.detail


def test_gates_5_and_6_are_defence_in_depth_and_still_fire() -> None:
    """Unreachable through `evaluate`, and checked anyway.

    `evaluate` already degrades a sample whose round trip or uncertainty is out of
    bounds, so a status built by it can never reach gates 5 and 6. They exist for
    the same reason
    :attr:`~globin.domain.rest_endpoint.ResolutionStatus.ENVIRONMENT_MISMATCH` does:
    this is the function that actually hands a timestamp to a signer, and the cost
    of the check is one comparison. A hand-built status is what reaches them.
    """
    discipline = default_discipline()
    slow = _sample(round_trip_millis=discipline.max_round_trip.milliseconds + 500)
    hand_built = ClockStatus(
        domain=DOMAIN, state=SyncState.SYNCHRONIZED, sample=slow, age=Duration(0)
    )
    admission = _admit(hand_built)
    assert admission.outcome is AdmissionStatus.CLOCK_UNCERTAINTY_EXCEEDED
    assert admission.context is None


def test_a_synchronized_status_offering_no_sample_is_refused_rather_than_trusted() -> None:
    """The last defensive branch, reachable only by constructing the contradiction.

    `ClockStatus` refuses a synchronized status with no sample, so this needs the
    guard to be bypassed -- which is the point: `admit` does not rely on a type
    invariant it did not enforce itself.
    """
    admission = _admit(_hollowed(_healthy(), "sample", None))
    assert admission.outcome is AdmissionStatus.CLOCK_NOT_SYNCHRONIZED
    assert "offers no sample" in admission.detail


def test_a_refusal_with_no_detail_falls_back_to_naming_the_state() -> None:
    """A refusal must explain something, so the builder supplies a floor."""
    empty = ClockStatus(domain=DOMAIN, state=SyncState.UNINITIALIZED, detail="x")
    admission = _admit(_hollowed(empty, "detail", ""))
    assert admission.detail


def _hollowed(status: ClockStatus, field: str, value: object) -> ClockStatus:
    """A status with one field replaced, bypassing the type's own refusal.

    Args:
        status: The status to hollow out.
        field: Which field to replace.
        value: What to replace it with.

    Returns:
        The hollowed status.

    Built with ``object.__setattr__`` rather than ``dataclasses.replace``, which
    re-runs ``__post_init__`` and would refuse both of these combinations. That
    refusal is the invariant; these two tests are the evidence that :func:`admit`
    does not *depend* on it holding, which is what makes its own guards defence in
    depth rather than decoration.
    """
    import copy

    hollow = copy.copy(status)
    object.__setattr__(hollow, field, value)
    return hollow


def test_every_refusal_carries_no_timing_context() -> None:
    """The property the whole gate rests on, asserted across every refusal at once."""
    discipline = default_discipline()
    refusals = [
        _admit(_healthy(), source_available=False),
        _admit(evaluate(DOMAIN, samples=(), age=None, discipline=discipline)),
        _admit(
            evaluate(
                DOMAIN,
                samples=(_sample(),),
                age=Duration(discipline.freshness_ttl.nanoseconds * 2),
                discipline=discipline,
            )
        ),
        _admit(_healthy(), policy=RecvWindowPolicy(window=RecvWindow(Decimal(1)))),
    ]
    for admission in refusals:
        assert not admission.admitted, admission.outcome
        assert admission.context is None, admission.outcome
        assert admission.detail, admission.outcome


# ---------------------------------------------------------------------------
# The venue's own rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skew", [-1, 0, 1], ids=["venue-early", "venue-exact", "venue-late"])
def test_an_admitted_timestamp_satisfies_both_of_the_venues_checks(skew: int) -> None:
    """The venue's published pseudo-code, run against GLOBIN's output.

    Quoted from ``rest-api.md``::

        if (timestamp < (serverTime + 1 second) && (serverTime - timestamp) <= recvWindow) {
          serverTime = getCurrentTime()
          if (serverTime - timestamp) <= recvWindow {

    The second evaluation carries **no** future tolerance, so it is checked after
    the whole network budget has been spent — which is the worst case GLOBIN can
    describe.
    """
    discipline = default_discipline()
    sample = _sample(offset_millis=200, round_trip_millis=80)
    status = evaluate(DOMAIN, samples=(sample,), age=Duration(0), discipline=discipline)
    window = default_recv_window()
    admission = _admit(status, policy=RecvWindowPolicy(window=window))
    assert admission.context is not None

    stamp = admission.context.timestamp * MICROSECONDS_PER_MILLISECOND
    truth = MOMENT.epoch_micros + sample.offset_micros
    first = truth + skew * sample.uncertainty_micros
    window_micros = int(window.millis * MICROSECONDS_PER_MILLISECOND)
    tolerance = FUTURE_TOLERANCE_MILLIS * MICROSECONDS_PER_MILLISECOND

    assert stamp < first + tolerance
    assert first - stamp <= window_micros
    second = first + discipline.network_budget.microseconds
    assert second - stamp <= window_micros


# ---------------------------------------------------------------------------
# The timing context itself
# ---------------------------------------------------------------------------


def test_a_context_refuses_an_attempt_past_the_bound() -> None:
    """One retry, and the type is what enforces it."""
    with pytest.raises(ValidationError, match="timing retry is permitted"):
        TimingContext(
            domain=DOMAIN,
            timestamp=1,
            unit=TimestampUnit.MILLISECONDS,
            recv_window=default_recv_window(),
            offset_micros=0,
            uncertainty_micros=0,
            round_trip_micros=0,
            attempt=MAX_TIMING_RETRIES + 1,
        )


@pytest.mark.parametrize("stamp", [0, -1], ids=["zero", "negative"])
def test_a_context_refuses_a_timestamp_that_is_not_a_moment(stamp: int) -> None:
    """A zero timestamp is the shape of an unset field."""
    with pytest.raises(ValidationError, match="not a moment"):
        TimingContext(
            domain=DOMAIN,
            timestamp=stamp,
            unit=TimestampUnit.MILLISECONDS,
            recv_window=default_recv_window(),
            offset_micros=0,
            uncertainty_micros=0,
            round_trip_micros=0,
        )


def test_a_context_record_publishes_no_timestamp() -> None:
    """Per-request values are unbounded in cardinality, so none is published."""
    admission = _admit(_healthy())
    assert admission.context is not None
    record = admission.context.as_record()
    assert "timestamp" not in record
    assert record["offset_bucket"] == "+<=500ms"
    assert record["uncertainty_bucket"] == "<=25ms"


def test_an_admission_that_permits_must_carry_a_context() -> None:
    """The type refuses the combination a caller would misread."""
    with pytest.raises(ValidationError, match="carries no timing context"):
        TimingAdmission(
            outcome=AdmissionStatus.ADMITTED, domain=DOMAIN, state=SyncState.SYNCHRONIZED
        )


def test_a_refusal_may_not_carry_a_context() -> None:
    """A refusal must offer nothing to stamp with."""
    with pytest.raises(ValidationError, match="must offer nothing"):
        TimingAdmission(
            outcome=AdmissionStatus.CLOCK_CALIBRATION_STALE,
            domain=DOMAIN,
            state=SyncState.STALE,
            context=TimingContext(
                domain=DOMAIN,
                timestamp=1,
                unit=TimestampUnit.MILLISECONDS,
                recv_window=default_recv_window(),
                offset_micros=0,
                uncertainty_micros=0,
                round_trip_micros=0,
            ),
            detail="x",
        )


# ---------------------------------------------------------------------------
# The window policy
# ---------------------------------------------------------------------------


def test_the_window_policy_is_exact_in_microseconds() -> None:
    """Three decimal places of a millisecond, with nothing to round."""
    assert RecvWindowPolicy(window=RecvWindow(Decimal("6000.346"))).micros == 6_000_346


def test_a_window_covers_exactly_its_own_width_and_not_a_microsecond_more() -> None:
    """The boundary, because an off-by-one here is an off-by-one against the venue."""
    policy = RecvWindowPolicy(window=RecvWindow(Decimal(5_000)))
    assert policy.covers(5_000_000)
    assert not policy.covers(5_000_001)


def test_the_window_policy_reports_that_it_does_not_adapt() -> None:
    """An absence stated as a value, so a diagnostic can carry it."""
    assert RecvWindowPolicy(window=default_recv_window()).as_record()["adaptive"] is False


def test_the_venue_ceiling_is_refused_by_the_value_type_rather_than_the_policy() -> None:
    """A policy holding an over-large window cannot exist to be checked."""
    with pytest.raises(ValidationError, match="exceeds the documented maximum"):
        RecvWindowPolicy(window=RecvWindow(Decimal("60000.001")))


def test_a_policy_must_hold_a_window() -> None:
    """A bare number would lose the three decimal places the venue documents."""
    with pytest.raises(ValidationError, match="must be a RecvWindow"):
        RecvWindowPolicy(window=5000)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The application seam
# ---------------------------------------------------------------------------


def test_the_application_seam_builds_the_policy_from_a_plain_window() -> None:
    """A caller passes what an operator configured, not an assembled policy."""
    admission = admit_request(
        _healthy(),
        moment=MOMENT,
        unit=TimestampUnit.MILLISECONDS,
        window=default_recv_window(),
        discipline=default_discipline(),
    )
    assert admission.admitted
    assert admission.context is not None
    assert admission.context.recv_window == default_recv_window()
