"""The clock self-test's failing half, and every refusal the types make.

`tests/contract/test_clock_sync_contract.py` asserts the committed defaults pass
all eight checks. This module drives each one against a **drifted** input, because
a check that could not fail is a check nobody should read — the argument
`test_rest_application.py` makes about Phase 034's self-test, applied here.

Driving a self-test to fail needs the thing it checks to be wrong, and most of what
it checks is pure functions that cannot be swapped. So the failures are produced by
monkeypatching the collaborator each finding calls, which is honest about what is
being exercised: the *reporting* path, not a second implementation of the rule.

The second half of the module is the refusals — the branches a type takes when a
caller hands it a combination it must not accept. Those are reached directly,
because a type that refuses is easier to test than one that computes.
"""

import pytest

from globin.application import clock_sync as application
from globin.application.clock_sync import (
    CHECK_ADMISSION,
    CHECK_BUCKETS,
    CHECK_ESTIMATOR,
    CHECK_RECOVERY,
    CHECK_RECV_WINDOW,
    CHECK_STATE_MACHINE,
    CHECK_UNITS,
    CHECK_VENUE_RULE,
    CalibrationOutcome,
    ClockFinding,
    ClockSelfTest,
    declared_domains,
    self_test,
)
from globin.domain.api_reality import EnvironmentName, ProductFamily, ProtocolKind
from globin.domain.auth_timing import TimestampUnit
from globin.domain.clock import Duration, Instant, MonotonicReading
from globin.domain.clock_sync import (
    AdmissionStatus,
    CalibrationSample,
    ClockDomain,
    ClockStatus,
    JumpDirection,
    JumpVerdict,
    ServerTimeReading,
    SyncState,
    TimingAdmission,
    TimingRecovery,
    default_discipline,
    offset_bucket,
    round_trip_bucket,
)
from globin.errors import ValidationError

DOMAIN = ClockDomain(
    family=ProductFamily("spot"),
    environment=EnvironmentName("testnet"),
    protocol=ProtocolKind.REST,
)


def _finding(report: ClockSelfTest, check: str) -> ClockFinding:
    """One finding out of a report.

    Args:
        report: The report.
        check: Which check.

    Returns:
        The finding.
    """
    matches = [item for item in report.findings if item.check == check]
    assert len(matches) == 1, check
    return matches[0]


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
        offset_micros=offset_millis * 1_000,
        round_trip=Duration(round_trip_millis * 1_000_000),
        taken_at=MonotonicReading(round_trip_millis * 1_000_000),
        wall_anchor_micros=1_800_000_000_000_000,
        reported_unit=TimestampUnit.MILLISECONDS,
    )


# ---------------------------------------------------------------------------
# Each check, driven to fail
# ---------------------------------------------------------------------------


def test_a_broken_estimator_fails_its_own_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """An estimator that folds half the round trip into the offset is caught.

    This is the naive `serverTime - now` mistake, injected. The check exists to
    notice it, so the check is shown noticing it.
    """

    def wrong(
        domain: ClockDomain,
        *,
        reading: ServerTimeReading,
        wall_anchor: Instant,
        started: MonotonicReading,
        finished: MonotonicReading,
    ) -> CalibrationSample:
        del domain
        return CalibrationSample(
            domain=DOMAIN,
            offset_micros=reading.epoch_micros - wall_anchor.epoch_micros,
            round_trip=finished.since(started),
            taken_at=finished,
            wall_anchor_micros=wall_anchor.epoch_micros,
            reported_unit=reading.unit,
        )

    monkeypatch.setattr(application, "sample_offset", wrong)
    finding = _finding(self_test(default_discipline()), CHECK_ESTIMATOR)
    assert not finding.passed
    assert "estimated" in finding.detail


def test_a_stamp_that_rounds_forward_fails_the_unit_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rounding a timestamp up spends an allowance the venue's second check does not grant."""

    def rounding(moment: Instant, offset_micros: int, unit: TimestampUnit) -> int:
        exact = moment.epoch_micros + offset_micros
        if unit is TimestampUnit.MICROSECONDS:
            return exact
        return -(-exact // 1_000)

    monkeypatch.setattr(application, "corrected_stamp", rounding)
    finding = _finding(self_test(default_discipline()), CHECK_UNITS)
    assert not finding.passed
    # The detail names whichever of the four unit properties broke first. Which one
    # is not the assertion -- the assertion is that a stamp which rounds forward
    # cannot pass this check at all.
    assert finding.detail


def test_a_state_machine_that_cannot_reach_a_state_fails_its_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A machine that answers `SYNCHRONIZED` for everything reaches four states fewer."""

    def always_synchronized(domain: ClockDomain, **kwargs: object) -> ClockStatus:
        del kwargs
        return ClockStatus(domain=domain, state=SyncState.SYNCHRONIZED, sample=_sample())

    monkeypatch.setattr(application, "evaluate", always_synchronized)
    finding = _finding(self_test(default_discipline()), CHECK_STATE_MACHINE)
    assert not finding.passed
    assert "unreachable states" in finding.detail


def test_an_admission_that_permits_everything_fails_its_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check that would matter most if the gate were ever loosened."""
    from globin.domain.auth_timing import default_recv_window
    from globin.domain.clock_sync import TimingContext

    def always_admit(status: ClockStatus, **kwargs: object) -> TimingAdmission:
        del kwargs
        return TimingAdmission(
            outcome=AdmissionStatus.ADMITTED,
            domain=status.domain,
            state=status.state,
            context=TimingContext(
                domain=status.domain,
                timestamp=1,
                unit=TimestampUnit.MILLISECONDS,
                recv_window=default_recv_window(),
                offset_micros=0,
                uncertainty_micros=0,
                round_trip_micros=0,
            ),
        )

    monkeypatch.setattr(application, "admit", always_admit)
    finding = _finding(self_test(default_discipline()), CHECK_ADMISSION)
    assert not finding.passed
    assert "expected" in finding.detail


def test_a_window_that_accepts_an_over_large_value_fails_its_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The venue's ceiling, and what a self-test says when it stops being enforced."""

    class _Permissive:
        """A window type that accepts anything and renders wrongly."""

        def __init__(self, millis: object) -> None:
            """Accept whatever was passed.

            Args:
                millis: Whatever.
            """
            self.millis = millis

        def __str__(self) -> str:
            """Render as something the venue would not accept."""
            return "whatever"

        def as_record(self) -> dict[str, object]:
            """A record shaped like the real one and carrying the wrong value."""
            return {"millis": "whatever", "decimal_places": 0}

    class _PermissivePolicy:
        """A policy that holds anything and covers nothing."""

        def __init__(self, window: object) -> None:
            """Hold whatever was passed.

            Args:
                window: Whatever.
            """
            self.window = window

        @property
        def micros(self) -> int:
            """A width that is always wrong."""
            return 0

        def covers(self, required_micros: int) -> bool:
            """Never cover anything.

            Args:
                required_micros: What must fit.

            Returns:
                ``False``, always.
            """
            del required_micros
            return False

        def as_record(self) -> dict[str, object]:
            """A record claiming the policy adapts, which the real one never does."""
            return {"adaptive": True}

    # BOTH are replaced, and that is the finding rather than an inconvenience. The
    # venue's ceiling is enforced by `RecvWindow` at construction and `RecvWindowPolicy`
    # additionally refuses to hold anything that is not one -- so loosening the check
    # takes two separate deliberate acts, which is what "the type refuses the value and
    # the policy above it never has to" means in practice.
    monkeypatch.setattr(application, "RecvWindow", _Permissive)
    monkeypatch.setattr(application, "RecvWindowPolicy", _PermissivePolicy)
    finding = _finding(self_test(default_discipline()), CHECK_RECV_WINDOW)
    assert not finding.passed
    assert finding.detail


def test_a_recovery_table_that_retries_an_unknown_outcome_fails_its_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single most dangerous loosening this layer could suffer."""

    def always_retry(**kwargs: object) -> TimingRecovery:
        """Permit a re-send whatever was asked.

        Args:
            **kwargs: Ignored.

        Returns:
            The most permissive verdict there is.
        """
        del kwargs
        return TimingRecovery.RESYNC_AND_RETRY_ONCE

    monkeypatch.setattr(application, "recovery_for", always_retry)
    finding = _finding(self_test(default_discipline()), CHECK_RECOVERY)
    assert not finding.passed
    assert "expected" in finding.detail


def test_a_stamp_that_lands_outside_the_venues_rule_fails_the_venue_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The strongest check, shown failing.

    A timestamp shifted a full minute into the venue's future breaks the first of
    the venue's two conditions, which is exactly what this check is for.
    """
    import dataclasses
    from typing import Any

    # The *domain's* function, not the application module's reference to it. Reading
    # `application.admit` would be reading a name that module re-exports without
    # declaring, and the two are the same object anyway.
    from globin.domain.clock_sync import admit as real

    def ahead(status: ClockStatus, **kwargs: Any) -> TimingAdmission:
        """Admit as usual, then push the timestamp a minute into the venue's future.

        Args:
            status: What is known about the clock.
            **kwargs: The rest of the admission's arguments.

        Returns:
            The admission, with a shifted context.

        **Patched at `admit` rather than at `corrected_stamp`, and the first draft
        got that wrong.** `admit()` calls the *domain's* `corrected_stamp` directly,
        so replacing the application module's reference to it changes nothing the
        gate does. That is a real property worth knowing: the domain's arithmetic is
        not reachable through the application layer's namespace.
        """
        admission: TimingAdmission = real(status, **kwargs)
        if admission.context is None:
            return admission
        shifted = dataclasses.replace(
            admission.context, timestamp=admission.context.timestamp + 60_000
        )
        return dataclasses.replace(admission, context=shifted)

    monkeypatch.setattr(application, "admit", ahead)
    finding = _finding(self_test(default_discipline()), CHECK_VENUE_RULE)
    assert not finding.passed
    assert "reject" in finding.detail


def test_an_admission_that_refuses_a_healthy_clock_fails_the_venue_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other way that check can fail: nothing was admitted to check."""

    def always_refuse(status: ClockStatus, **kwargs: object) -> TimingAdmission:
        del kwargs
        return TimingAdmission(
            outcome=AdmissionStatus.CLOCK_NOT_SYNCHRONIZED,
            domain=status.domain,
            state=status.state,
            detail="no",
        )

    monkeypatch.setattr(application, "admit", always_refuse)
    finding = _finding(self_test(default_discipline()), CHECK_VENUE_RULE)
    assert not finding.passed
    assert "did not admit" in finding.detail


def test_an_unbounded_bucket_fails_the_cardinality_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dimension that published raw values would give every observation its own series."""
    monkeypatch.setattr(application, "round_trip_bucket", lambda micros: f"{micros}us")
    finding = _finding(self_test(default_discipline()), CHECK_BUCKETS)
    assert not finding.passed
    assert "distinct values" in finding.detail


def test_an_unbounded_offset_bucket_fails_the_same_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both dimensions, because one bounded and one not is still unbounded."""
    monkeypatch.setattr(application, "offset_bucket", lambda micros: f"{micros}us")
    finding = _finding(self_test(default_discipline()), CHECK_BUCKETS)
    assert not finding.passed
    assert "offset buckets" in finding.detail


def test_a_report_with_a_failure_reports_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """The aggregate, so a caller reading `passed` gets the right answer."""

    def never_act(**kwargs: object) -> TimingRecovery:
        """Do nothing whatever was asked.

        Args:
            **kwargs: Ignored.

        Returns:
            The verdict that acts on nothing.
        """
        del kwargs
        return TimingRecovery.NO_ACTION

    monkeypatch.setattr(application, "recovery_for", never_act)
    report = self_test(default_discipline())
    assert not report.passed
    assert len(report.failures) >= 1
    assert report.as_record()["failed"] == len(report.failures)


# ---------------------------------------------------------------------------
# A family with no declared probe
# ---------------------------------------------------------------------------


def test_a_resolvable_family_with_no_declared_probe_is_unavailable() -> None:
    """The second gate in `declared_domains`, which the committed documents never reach.

    Spot resolves *and* declares a `spot.time` probe, so this branch is unreachable
    from the committed pair. It is the branch that keeps *a path is never guessed*
    structural, so it is reached here with a contract whose probe table is empty.
    """
    from pathlib import Path

    from globin.adapters.api_reality import read_registry
    from globin.adapters.rest import read_contract

    root = Path(__file__).resolve().parents[2]
    snapshot = read_registry(root / "docs" / "engineering" / "binance-api-reality.toml")
    contract = read_contract(root / "docs" / "engineering" / "rest-transport.toml")
    assert snapshot is not None
    assert contract is not None

    class _NoProbes:
        """A contract that declares no probe for anything."""

        def probe(self, family: object, operation: str) -> None:
            """Answer that nothing is declared.

            Args:
                family: Which family.
                operation: Which operation.

            Returns:
                ``None``, always.
            """
            del family, operation
            return

    results = declared_domains(snapshot, _NoProbes())  # type: ignore[arg-type]
    spot = [item for item in results if item.domain.family.slug == "spot"]
    assert spot
    for item in spot:
        assert not item.available
        assert "never guessed" in item.detail


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------


def test_a_calibration_outcome_may_not_report_failure_and_carry_a_sample() -> None:
    """A caller reading the sample would be reading one that was not obtained."""
    with pytest.raises(ValidationError, match="failure and still carries a sample"):
        CalibrationOutcome(domain=DOMAIN, sample=_sample(), failed=True)


def test_a_calibration_outcome_may_not_report_success_and_carry_nothing() -> None:
    """The other direction, so neither combination can be constructed."""
    with pytest.raises(ValidationError, match="success and carries no sample"):
        CalibrationOutcome(domain=DOMAIN, failed=False)


@pytest.mark.parametrize(
    ("direction", "divergence", "match"),
    [
        pytest.param(JumpDirection.NONE, 9_000, "reports no jump", id="none-with-a-divergence"),
        pytest.param(JumpDirection.FORWARD, -9_000, "forward jump", id="forward-going-back"),
        pytest.param(JumpDirection.BACKWARD, 9_000, "backward jump", id="backward-going-forward"),
    ],
)
def test_a_jump_verdict_whose_direction_contradicts_its_divergence_is_refused(
    direction: JumpDirection, divergence: int, match: str
) -> None:
    """The verdict carries both, so the two are checked against each other."""
    with pytest.raises(ValidationError, match=match):
        JumpVerdict(direction=direction, divergence_micros=divergence, threshold_micros=500)


def test_a_verdict_reporting_no_jump_inside_the_threshold_is_accepted() -> None:
    """The guard's own negative case, so it cannot refuse the ordinary answer."""
    verdict = JumpVerdict(direction=JumpDirection.NONE, divergence_micros=100, threshold_micros=500)
    assert not verdict.detected


def test_a_calibration_sample_refuses_a_round_trip_that_is_not_a_duration() -> None:
    """Nanoseconds as a bare integer would be off by a factor of a million."""
    with pytest.raises(ValidationError, match="round trip must be a Duration"):
        CalibrationSample(
            domain=DOMAIN,
            offset_micros=0,
            round_trip=40,  # type: ignore[arg-type]
            taken_at=MonotonicReading(0),
            wall_anchor_micros=1,
            reported_unit=TimestampUnit.MILLISECONDS,
        )


def test_a_calibration_sample_refuses_an_anchor_that_is_not_a_reading() -> None:
    """An `Instant` here would make the age a wall-clock difference."""
    from datetime import UTC, datetime

    from globin.domain.clock import Instant

    with pytest.raises(ValidationError, match="anchor must be a MonotonicReading"):
        CalibrationSample(
            domain=DOMAIN,
            offset_micros=0,
            round_trip=Duration(0),
            taken_at=Instant(datetime(2026, 8, 20, tzinfo=UTC)),  # type: ignore[arg-type]
            wall_anchor_micros=1,
            reported_unit=TimestampUnit.MILLISECONDS,
        )


def test_a_calibration_sample_refuses_a_non_integer_offset() -> None:
    """A float offset would reintroduce the drift the whole module avoids."""
    with pytest.raises(ValidationError, match="offset in microseconds"):
        CalibrationSample(
            domain=DOMAIN,
            offset_micros=1.5,  # type: ignore[arg-type]
            round_trip=Duration(0),
            taken_at=MonotonicReading(0),
            wall_anchor_micros=1,
            reported_unit=TimestampUnit.MILLISECONDS,
        )


def test_a_server_time_reading_refuses_a_non_integer() -> None:
    """The reading is normalised on arrival, so its type is checked on arrival."""
    with pytest.raises(ValidationError, match="must be an int"):
        ServerTimeReading(epoch_micros="1499827319559", unit=TimestampUnit.MILLISECONDS)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def test_every_record_this_layer_publishes_survives_json() -> None:
    """Each one goes into the evidence manifest, so each is round-tripped."""
    import json

    verdict = JumpVerdict(direction=JumpDirection.NONE, divergence_micros=0, threshold_micros=500)
    outcome = CalibrationOutcome(domain=DOMAIN, sample=_sample())
    records = [
        DOMAIN.as_record(),
        _sample().as_record(),
        verdict.as_record(),
        outcome.as_record(),
        default_discipline().as_record(),
        ServerTimeReading(epoch_micros=1, unit=TimestampUnit.MILLISECONDS).as_record(),
    ]
    for record in records:
        assert json.loads(json.dumps(record)) == record


def test_a_domain_renders_as_its_label() -> None:
    """One stable string, used as a mapping key and printed to an operator."""
    assert str(DOMAIN) == "spot/testnet/rest"
    assert DOMAIN.as_record()["label"] == "spot/testnet/rest"


def test_the_bucket_helpers_agree_with_their_own_records() -> None:
    """The record is what a dashboard reads, so it is compared to the helper."""
    sample = _sample(offset_millis=-7, round_trip_millis=120)
    record = sample.as_record()
    assert record["offset_bucket"] == offset_bucket(sample.offset_micros)
    assert record["round_trip_bucket"] == round_trip_bucket(sample.round_trip.microseconds)
