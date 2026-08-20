"""What a venue timing rejection permits, and — mostly — what it does not.

Six of the nine cases below are refusals, which is the right ratio for a mechanism
whose whole safety argument is what it declines to do. The two that matter most:

* an **unknown** outcome never earns a retry, whatever the code says. ADR-0089's
  rule does not acquire an exception because the remedy happens to be obvious;
* a **mutating** request with no idempotency declaration never earns one either.
  Silence is not a declaration.

The classification is also checked against Phase 034's own ``classify()``, so the
claim that ``-1021`` arrives as a *confirmed* failure — which is what makes the
bounded retry reachable at all — is verified rather than assumed.
"""

import pytest

from globin.application.clock_sync import timing_recovery
from globin.domain.clock_sync import (
    INVALID_TIMESTAMP_CODE,
    MAX_TIMING_RETRIES,
    TimingRecovery,
    recovery_for,
)
from globin.domain.rest import (
    AMBIGUOUS_EXCHANGE_CODES,
    RequestOutcome,
    RestOutcomeInputs,
    SendState,
    SideEffect,
    classify,
)

# ---------------------------------------------------------------------------
# What Phase 034 makes of the code
# ---------------------------------------------------------------------------


def test_the_venue_code_is_the_one_the_documentation_publishes() -> None:
    """`-1021 INVALID_TIMESTAMP`, from `errors.md`."""
    assert INVALID_TIMESTAMP_CODE == -1021


def test_a_timing_rejection_is_a_confirmed_failure_even_for_a_write() -> None:
    """The property that makes a bounded retry reachable rather than universal.

    The venue rejects at the timing gate, before the Matching Engine, so nothing
    was at stake — the same reading that keeps 403, 418 and 429 out of the ambiguous
    status table. Marking it ambiguous would make the one timing failure that is
    always safe to re-send permanently unretryable.
    """
    outcome = classify(
        RestOutcomeInputs(
            side_effect=SideEffect.MUTATING,
            send_state=SendState.COMPLETED,
            status=400,
            exchange_code=INVALID_TIMESTAMP_CODE,
        )
    )
    assert outcome is RequestOutcome.FAILURE_CONFIRMED
    assert INVALID_TIMESTAMP_CODE not in AMBIGUOUS_EXCHANGE_CODES


def test_the_unexpected_response_code_is_ambiguous() -> None:
    """The defect Phase 036 found: `-1006` says "Execution status unknown"."""
    assert -1006 in AMBIGUOUS_EXCHANGE_CODES
    outcome = classify(
        RestOutcomeInputs(
            side_effect=SideEffect.MUTATING,
            send_state=SendState.COMPLETED,
            status=200,
            exchange_code=-1006,
        )
    )
    assert outcome is RequestOutcome.UNKNOWN


# ---------------------------------------------------------------------------
# The recovery table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "outcome", "effect", "idempotent", "attempt", "expected"),
    [
        pytest.param(
            -1022,
            RequestOutcome.FAILURE_CONFIRMED,
            SideEffect.READ_ONLY,
            False,
            0,
            TimingRecovery.NO_ACTION,
            id="another-code-is-not-our-business",
        ),
        pytest.param(
            0,
            RequestOutcome.SUCCESS_CONFIRMED,
            SideEffect.READ_ONLY,
            False,
            0,
            TimingRecovery.NO_ACTION,
            id="a-success-is-not-our-business",
        ),
        pytest.param(
            INVALID_TIMESTAMP_CODE,
            RequestOutcome.FAILURE_CONFIRMED,
            SideEffect.READ_ONLY,
            False,
            0,
            TimingRecovery.RESYNC_AND_RETRY_ONCE,
            id="a-read-may-be-sent-again",
        ),
        pytest.param(
            INVALID_TIMESTAMP_CODE,
            RequestOutcome.FAILURE_CONFIRMED,
            SideEffect.MUTATING,
            True,
            0,
            TimingRecovery.RESYNC_AND_RETRY_ONCE,
            id="a-declared-idempotent-write-may-be-sent-again",
        ),
        pytest.param(
            INVALID_TIMESTAMP_CODE,
            RequestOutcome.FAILURE_CONFIRMED,
            SideEffect.MUTATING,
            False,
            0,
            TimingRecovery.RESYNC_ONLY,
            id="silence-is-not-a-declaration",
        ),
        pytest.param(
            INVALID_TIMESTAMP_CODE,
            RequestOutcome.UNKNOWN,
            SideEffect.MUTATING,
            True,
            0,
            TimingRecovery.RESYNC_ONLY,
            id="an-unknown-outcome-is-never-replayed",
        ),
        pytest.param(
            INVALID_TIMESTAMP_CODE,
            RequestOutcome.UNKNOWN,
            SideEffect.READ_ONLY,
            True,
            0,
            TimingRecovery.RESYNC_ONLY,
            id="an-unknown-outcome-is-never-replayed-even-for-a-read",
        ),
        pytest.param(
            INVALID_TIMESTAMP_CODE,
            RequestOutcome.FAILURE_CONFIRMED,
            SideEffect.READ_ONLY,
            False,
            MAX_TIMING_RETRIES,
            TimingRecovery.RESYNC_ONLY,
            id="the-budget-is-one",
        ),
        pytest.param(
            INVALID_TIMESTAMP_CODE,
            RequestOutcome.REJECTED_BEFORE_SEND,
            SideEffect.READ_ONLY,
            False,
            0,
            TimingRecovery.RESYNC_ONLY,
            id="only-a-confirmed-failure-may-be-re-sent",
        ),
    ],
)
def test_the_recovery_table_recomputes(
    code: int,
    outcome: RequestOutcome,
    effect: SideEffect,
    idempotent: bool,
    attempt: int,
    expected: TimingRecovery,
) -> None:
    """Every row, including the six that refuse."""
    assert (
        recovery_for(
            exchange_code=code,
            outcome=outcome,
            side_effect=effect,
            idempotent=idempotent,
            attempt=attempt,
        )
        is expected
    )


def test_an_unsafe_write_is_not_retried_however_many_times_it_is_asked() -> None:
    """The one that would be most tempting to soften, asserted across the whole space."""
    for outcome in RequestOutcome:
        verdict = recovery_for(
            exchange_code=INVALID_TIMESTAMP_CODE,
            outcome=outcome,
            side_effect=SideEffect.MUTATING,
            idempotent=False,
        )
        assert verdict is not TimingRecovery.RESYNC_AND_RETRY_ONCE, outcome


def test_a_timing_rejection_always_requires_a_resynchronisation() -> None:
    """Even when the request may not be re-sent, the clock is still wrong."""
    for outcome in RequestOutcome:
        verdict = recovery_for(
            exchange_code=INVALID_TIMESTAMP_CODE,
            outcome=outcome,
            side_effect=SideEffect.MUTATING,
            idempotent=False,
        )
        assert verdict.resynchronises


def test_nothing_that_is_not_a_timing_rejection_resynchronises() -> None:
    """The clock layer stays out of every other failure's business."""
    for code in (0, -1000, -1007, -1022, -2010):
        verdict = recovery_for(
            exchange_code=code,
            outcome=RequestOutcome.FAILURE_CONFIRMED,
            side_effect=SideEffect.READ_ONLY,
        )
        assert verdict is TimingRecovery.NO_ACTION
        assert not verdict.resynchronises


def test_the_retry_budget_is_exactly_one() -> None:
    """Not configurable, because a raisable budget is a retry engine."""
    assert MAX_TIMING_RETRIES == 1


def test_the_application_seam_agrees_with_the_domain_rule() -> None:
    """Two entry points, one decision."""
    for attempt in (0, 1):
        assert timing_recovery(
            exchange_code=INVALID_TIMESTAMP_CODE,
            outcome=RequestOutcome.FAILURE_CONFIRMED,
            side_effect=SideEffect.READ_ONLY,
            attempt=attempt,
        ) is recovery_for(
            exchange_code=INVALID_TIMESTAMP_CODE,
            outcome=RequestOutcome.FAILURE_CONFIRMED,
            side_effect=SideEffect.READ_ONLY,
            attempt=attempt,
        )


def test_there_is_no_verdict_meaning_retry_freely() -> None:
    """The vocabulary cannot express an unbounded retry."""
    assert sorted(item.value for item in TimingRecovery) == [
        "no_action",
        "resync_and_retry_once",
        "resync_only",
    ]
