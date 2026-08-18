"""The suite: what it classifies, what it schedules, and how long a verdict lasts.

``test_bootstrap.py`` owns the checks themselves — what each one concludes and
which exit code it declares. This owns the layer above: the classification the
registry gained in Phase 030, the schedule that follows from it, and the one
sentence a start-up gate cannot say.

Nothing here runs a check. Every test builds a report by hand, because what is
under test is how a report is *read* rather than how one is produced.
"""

import pytest

from globin.domain.bootstrap import (
    BootstrapReport,
    CheckOutcome,
    CheckSpec,
    CheckStatus,
    Durability,
    ExitCode,
    checks,
)
from globin.domain.preflight import (
    DEFAULT_RECHECK_INTERVAL_MILLIS,
    MAXIMUM_RECHECK_INTERVAL_MILLIS,
    MINIMUM_RECHECK_INTERVAL_MILLIS,
    PreflightOutcome,
    PreflightSuite,
    RecheckPolicy,
    build_suite,
    default_recheck_policy,
)
from globin.errors import ValidationError

# ---------------------------------------------------------------------------
# The classification
# ---------------------------------------------------------------------------


def test_every_registered_check_declares_a_durability() -> None:
    """A check with no classification would be scheduled by accident, either way."""
    assert all(isinstance(spec.durability, Durability) for spec in checks())


def test_a_check_built_without_one_is_treated_as_decaying() -> None:
    """The conservative default: an unconsidered check costs a re-measurement, not trust."""
    spec = CheckSpec("project.root", "project", ExitCode.PATHS_UNUSABLE)
    assert spec.durability is Durability.PERISHABLE


def test_the_two_classifications_partition_the_registry() -> None:
    """Every check is in exactly one class, so no schedule can miss or double one."""
    suite = build_suite()
    stable = set(suite.stable())
    perishable = set(suite.perishable())
    assert stable | perishable == set(suite.identifiers())
    assert not stable & perishable


@pytest.mark.parametrize(
    "identifier",
    [
        pytest.param("runtime.host", id="an-operating-system-does-not-change-under-a-run"),
        pytest.param("python.version", id="nor-does-an-interpreter"),
        pytest.param("config.valid", id="the-snapshot-is-immutable-so-the-values-are-fixed"),
        pytest.param("state.previous_run", id="history-cannot-change-and-re-asking-shifts-it"),
    ],
)
def test_these_answers_survive_the_run(identifier: str) -> None:
    """The four calls the registry's docstring argues for by name."""
    assert identifier in build_suite().stable()


@pytest.mark.parametrize(
    "identifier",
    [
        pytest.param("paths.runtime", id="free-space-moves"),
        pytest.param("instance.lock", id="another-process-may-take-it"),
        pytest.param("state.persistence", id="a-tree-may-stop-being-writable"),
        pytest.param("bootstrap.ready", id="an-aggregate-is-no-stronger-than-its-inputs"),
    ],
)
def test_these_answers_were_true_only_when_taken(identifier: str) -> None:
    """The instantaneous half, which is what makes a schedule mean anything."""
    assert identifier in build_suite().perishable()


def test_the_suite_holds_no_checks_of_its_own() -> None:
    """Derived from the registry, so a renamed check cannot leave a stale entry."""
    assert build_suite().identifiers() == tuple(spec.identifier for spec in checks())


# ---------------------------------------------------------------------------
# The schedule
# ---------------------------------------------------------------------------


def test_the_declared_interval_is_inside_its_own_bounds() -> None:
    """A default outside the bounds would make the bounds decoration."""
    assert MINIMUM_RECHECK_INTERVAL_MILLIS <= DEFAULT_RECHECK_INTERVAL_MILLIS
    assert DEFAULT_RECHECK_INTERVAL_MILLIS <= MAXIMUM_RECHECK_INTERVAL_MILLIS
    assert default_recheck_policy().interval_millis == DEFAULT_RECHECK_INTERVAL_MILLIS


@pytest.mark.parametrize(
    "interval",
    [
        pytest.param(MINIMUM_RECHECK_INTERVAL_MILLIS, id="the-floor-is-inclusive"),
        pytest.param(MAXIMUM_RECHECK_INTERVAL_MILLIS, id="and-so-is-the-ceiling"),
    ],
)
def test_a_bound_is_accepted_rather_than_merely_approached(interval: int) -> None:
    """Inclusive bounds asserted, not left to a comment."""
    assert RecheckPolicy(interval_millis=interval).interval_millis == interval


@pytest.mark.parametrize(
    "interval",
    [
        pytest.param(MINIMUM_RECHECK_INTERVAL_MILLIS - 1, id="below-the-floor"),
        pytest.param(MAXIMUM_RECHECK_INTERVAL_MILLIS + 1, id="above-the-ceiling"),
        pytest.param(0, id="never"),
        pytest.param(-1, id="in-the-past"),
    ],
)
def test_a_policy_no_scheduler_could_honour_cannot_be_constructed(interval: int) -> None:
    """The bound is refused where it is declared, not where it would be read."""
    with pytest.raises(ValidationError, match="recheck interval"):
        RecheckPolicy(interval_millis=interval)


def test_a_boolean_interval_is_refused_even_though_python_makes_it_an_integer() -> None:
    """``True`` is one millisecond, and that is the accident that looks like it worked."""
    with pytest.raises(ValidationError, match="boolean"):
        RecheckPolicy(interval_millis=True)


def test_a_stable_check_is_never_scheduled() -> None:
    """Re-measuring an interpreter every minute would spend the schedule on nothing."""
    policy = default_recheck_policy()
    stable = [spec for spec in checks() if spec.durability is Durability.STABLE]
    assert not any(policy.applies_to(spec) for spec in stable)


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        pytest.param(0, False, id="no-time-has-passed"),
        pytest.param(DEFAULT_RECHECK_INTERVAL_MILLIS - 1, False, id="not-quite"),
        pytest.param(DEFAULT_RECHECK_INTERVAL_MILLIS, True, id="exactly-due"),
        pytest.param(DEFAULT_RECHECK_INTERVAL_MILLIS * 3, True, id="long-overdue"),
    ],
)
def test_a_retake_falls_due_at_the_interval(elapsed: int, expected: bool) -> None:
    """Inclusive at the boundary, so a schedule cannot drift a tick later each time."""
    assert default_recheck_policy().due(elapsed) is expected


def test_negative_elapsed_time_is_a_caller_defect_rather_than_a_verdict() -> None:
    """Time not having passed says nothing about whether a re-take is owed."""
    with pytest.raises(ValidationError, match="negative"):
        default_recheck_policy().due(-1)


# ---------------------------------------------------------------------------
# The verdict, and its shelf life
# ---------------------------------------------------------------------------


def _report(suite: PreflightSuite, status: CheckStatus = CheckStatus.PASS) -> BootstrapReport:
    """Every registered check, concluding the same thing."""
    return BootstrapReport(
        outcomes=tuple(
            CheckOutcome(
                identifier=identifier,
                status=status,
                summary="measured",
                remediation="" if status is CheckStatus.PASS else "do the thing",
            )
            for identifier in suite.identifiers()
        )
    )


def test_a_complete_passing_run_may_start() -> None:
    """The verdict the whole command exists to produce."""
    suite = build_suite()
    outcome = PreflightOutcome(report=_report(suite), suite=suite)
    assert outcome.may_start
    assert outcome.exit_code is ExitCode.OK


def test_a_partial_report_may_not_start_even_when_nothing_refused() -> None:
    """Stopping early and everything passing must never reduce to one answer."""
    suite = build_suite()
    partial = BootstrapReport(
        outcomes=(CheckOutcome("project.root", CheckStatus.PASS, "found"),),
    )
    assert not PreflightOutcome(report=partial, suite=suite).may_start


def test_the_exit_code_is_the_registry_answer_rather_than_a_second_one() -> None:
    """A suite that computed its own would be the duplicate ``CheckSpec`` prevents."""
    suite = build_suite()
    refused = BootstrapReport(
        outcomes=tuple(
            CheckOutcome(
                identifier=identifier,
                status=CheckStatus.FAIL if identifier == "config.valid" else CheckStatus.PASS,
                summary="measured",
                remediation="fix the document" if identifier == "config.valid" else "",
            )
            for identifier in suite.identifiers()
        )
    )
    assert PreflightOutcome(report=refused, suite=suite).exit_code is ExitCode.CONFIGURATION_INVALID


def test_a_full_verdict_names_every_answer_that_decays() -> None:
    """The sentence a start-up gate cannot say."""
    suite = build_suite()
    outcome = PreflightOutcome(report=_report(suite), suite=suite)
    assert set(outcome.decaying()) == set(suite.perishable())


def test_a_verdict_with_nothing_perishable_in_it_does_not_expire() -> None:
    """``None`` is the accurate answer, distinguishable from an interval by type."""
    suite = build_suite()
    stable_only = BootstrapReport(
        outcomes=tuple(
            CheckOutcome(identifier, CheckStatus.PASS, "measured") for identifier in suite.stable()
        )
    )
    assert PreflightOutcome(report=stable_only, suite=suite).shelf_life_millis() is None


def test_a_verdict_carrying_a_perishable_pass_expires_at_the_interval() -> None:
    """The shelf life is the schedule's, not a second number."""
    suite = build_suite()
    outcome = PreflightOutcome(report=_report(suite), suite=suite)
    assert outcome.shelf_life_millis() == suite.policy.interval_millis


def test_a_refused_perishable_check_is_not_reported_as_decaying() -> None:
    """A failure is already reported; calling it perishable as well would say nothing."""
    suite = build_suite()
    outcome = PreflightOutcome(report=_report(suite, CheckStatus.FAIL), suite=suite)
    assert outcome.decaying() == ()


def test_a_warning_counts_as_an_answer_that_can_decay() -> None:
    """``WARN`` is a real answer, so its perishability is the same question."""
    suite = build_suite()
    outcome = PreflightOutcome(report=_report(suite, CheckStatus.WARN), suite=suite)
    assert set(outcome.decaying()) == set(suite.perishable())


def test_the_record_carries_the_checks_so_stream_and_artefact_cannot_disagree() -> None:
    """One builder, so a renderer cannot describe a different run from an evidence file."""
    suite = build_suite()
    record = PreflightOutcome(report=_report(suite), suite=suite).as_record()
    recorded_checks = record["checks"]
    recorded_suite = record["suite"]
    assert isinstance(recorded_checks, list)
    assert isinstance(recorded_suite, dict)
    assert [entry["id"] for entry in recorded_checks] == list(suite.identifiers())
    assert recorded_suite["interval_millis"] == suite.policy.interval_millis
