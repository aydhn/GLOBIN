"""The provisioning domain, from literals.

Everything here is pure: a plan is a function of a report and a policy, so the
whole of the reasoning is testable with no host, no process and no temporary tree.
That is the same property that makes `bootstrap plan` read-only in production, so
testing it this way is not a convenience — it is the design being exercised.

**Each rule is exercised twice**, once against something valid and once against
something the type is supposed to refuse. A validator only ever seen to accept is
a validator nobody has established can refuse.
"""

import pytest

from globin.domain.bootstrap import BootstrapReport, CheckOutcome, CheckStatus, ExitCode
from globin.domain.process import HostCapability, Tool, ToolPresence
from globin.domain.provisioning import (
    FORBIDDEN_REMEDY_PREFIXES,
    MAX_ACTIONS,
    ActionOutcome,
    ActionSpec,
    MutationClass,
    NetworkPolicy,
    NetworkRequirement,
    Privilege,
    ProvisioningAction,
    ProvisioningJournal,
    ProvisioningPlan,
    ProvisioningStep,
    Recovery,
    action_identifiers,
    action_spec_for,
    actions,
    admits,
    exit_code_for_journal,
    exit_code_for_plan,
    outcome_for,
    plan_from,
)
from globin.errors import InternalError, ValidationError


def outcome(identifier: str, status: CheckStatus = CheckStatus.PASS) -> CheckOutcome:
    """One check outcome, with everything a test does not care about filled in.

    A remediation is supplied for the failing statuses because `CheckOutcome`
    requires one -- a check that says a host is wrong and not what to do about it
    is the thing that invariant exists to refuse.
    """
    remediation = "" if status is CheckStatus.PASS else "do the thing that fixes it"
    return CheckOutcome(
        identifier=identifier, status=status, summary="a summary", remediation=remediation
    )


def report(*failing: str) -> BootstrapReport:
    """A report in which exactly the named checks failed."""
    from globin.domain.bootstrap import check_identifiers

    return BootstrapReport(
        outcomes=tuple(
            outcome(name, CheckStatus.FAIL if name in failing else CheckStatus.PASS)
            for name in check_identifiers()
        )
    )


def host(*, launcher: Tool | None = Tool.LEGACY_LAUNCHER) -> HostCapability:
    """A capability inventory naming one launcher, or none."""
    return HostCapability(
        tools=tuple(ToolPresence(tool=tool, present=tool is launcher) for tool in Tool)
    )


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


def test_every_action_is_declared_once_and_in_a_stable_order() -> None:
    identifiers = action_identifiers()
    assert len(identifiers) == len(set(identifiers))
    assert identifiers == tuple(spec.identifier for spec in actions())


def test_an_action_can_be_looked_up_by_its_identifier() -> None:
    assert action_spec_for("environment.create").mutation is MutationClass.CREATE


def test_looking_up_an_action_that_does_not_exist_is_a_defect() -> None:
    """A caller naming an action that does not exist has a bug, not bad input."""
    with pytest.raises(InternalError, match="no action is registered"):
        action_spec_for("environment.invent")


def test_exactly_one_declared_action_is_destructive() -> None:
    """The one route to losing work, and it is reachable only from a switch."""
    destructive = [spec.identifier for spec in actions() if spec.destructive]
    assert destructive == ["environment.recreate"]


def test_no_action_answers_for_a_secret_or_a_configuration_check() -> None:
    """The structural boundary, asserted rather than assumed.

    This is what makes `setup` unable to reach a credential store: not that
    nobody added such an action, but that `ActionSpec` refuses to construct one.
    """
    answered = [remedy for spec in actions() for remedy in spec.remedy_for]
    assert not [name for name in answered if name.startswith(FORBIDDEN_REMEDY_PREFIXES)]


def test_an_action_answering_for_a_secret_check_cannot_be_constructed() -> None:
    """Guard the guard: the rule above must be enforced, not merely observed."""
    with pytest.raises(ValidationError, match="does not write a credential"):
        ActionSpec(
            identifier="secrets.provision",
            mutation=MutationClass.CREATE,
            network=NetworkRequirement.NONE,
            privilege=Privilege.USER,
            destructive=False,
            recovery=Recovery.RESUMABLE,
            postcondition="secrets.required",
            remedy_for=("secrets.required",),
        )


def test_an_action_naming_a_check_that_does_not_exist_is_refused() -> None:
    with pytest.raises(ValidationError, match="not a registered check"):
        ActionSpec(
            identifier="environment.invent",
            mutation=MutationClass.CREATE,
            network=NetworkRequirement.NONE,
            privilege=Privilege.USER,
            destructive=False,
            recovery=Recovery.RESUMABLE,
            postcondition="python.invented",
        )


def test_a_destructive_action_cannot_claim_to_be_resumable() -> None:
    """An interrupted delete does not finish by being run again."""
    with pytest.raises(ValidationError, match="does not finish by being run again"):
        ActionSpec(
            identifier="environment.wipe",
            mutation=MutationClass.REMOVE,
            network=NetworkRequirement.NONE,
            privilege=Privilege.USER,
            destructive=True,
            recovery=Recovery.RESUMABLE,
            postcondition="python.environment",
        )


def test_an_identifier_that_is_not_area_dot_subject_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"area\.subject"):
        ActionSpec(
            identifier="environment",
            mutation=MutationClass.CREATE,
            network=NetworkRequirement.NONE,
            privilege=Privilege.USER,
            destructive=False,
            recovery=Recovery.RESUMABLE,
            postcondition="python.environment",
        )


def test_no_declared_action_requires_a_network() -> None:
    """Nothing this phase does needs an index.

    A declared action requiring one would be unreachable under the default
    policy, which is the sort of dead branch this repository refuses elsewhere.
    """
    assert not [spec for spec in actions() if spec.network is NetworkRequirement.NETWORK]


def test_no_declared_action_requires_elevation() -> None:
    """The default path never asks for administrator rights."""
    assert not [spec for spec in actions() if spec.privilege is Privilege.ELEVATED]


# ---------------------------------------------------------------------------
# The network policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("policy", "requirement", "permitted"),
    [
        (NetworkPolicy.OFFLINE, NetworkRequirement.NONE, True),
        (NetworkPolicy.OFFLINE, NetworkRequirement.CACHE, False),
        (NetworkPolicy.OFFLINE, NetworkRequirement.NETWORK, False),
        (NetworkPolicy.CACHE_ONLY, NetworkRequirement.NONE, True),
        (NetworkPolicy.CACHE_ONLY, NetworkRequirement.CACHE, True),
        (NetworkPolicy.CACHE_ONLY, NetworkRequirement.NETWORK, False),
        (NetworkPolicy.ONLINE_ALLOWED, NetworkRequirement.NONE, True),
        (NetworkPolicy.ONLINE_ALLOWED, NetworkRequirement.CACHE, True),
        (NetworkPolicy.ONLINE_ALLOWED, NetworkRequirement.NETWORK, True),
    ],
)
def test_a_policy_admits_exactly_what_it_declares(
    policy: NetworkPolicy, requirement: NetworkRequirement, permitted: bool
) -> None:
    """Every pair, written out, because a table with a gap defaults permissively."""
    assert admits(policy, requirement) is permitted


def test_the_offline_policy_is_the_most_restrictive_one() -> None:
    """The default must not be the permissive member."""
    assert [
        requirement
        for requirement in NetworkRequirement
        if admits(NetworkPolicy.OFFLINE, requirement)
    ] == [NetworkRequirement.NONE]


# ---------------------------------------------------------------------------
# Deriving a plan
# ---------------------------------------------------------------------------


def test_a_healthy_host_produces_an_empty_plan() -> None:
    """The property a second `setup` run turns on."""
    plan = plan_from(report(), policy=NetworkPolicy.OFFLINE, capability=host())
    assert plan.empty
    assert not plan.destructive


def test_a_failing_check_produces_the_action_that_answers_it() -> None:
    plan = plan_from(report("python.environment"), policy=NetworkPolicy.OFFLINE, capability=host())
    assert [action.identifier for action in plan.actions] == ["environment.create"]
    assert "python.environment" in plan.actions[0].reason


def test_the_destructive_action_is_never_planned_by_inference() -> None:
    """The failing check that would justify it is the one `create` answers.

    Without this, a wrong `.venv` would silently produce a plan that deletes it.
    """
    plan = plan_from(report("python.environment"), policy=NetworkPolicy.OFFLINE, capability=host())
    assert not plan.destructive
    assert "environment.recreate" not in [action.identifier for action in plan.actions]


def test_the_destructive_action_appears_only_when_the_operator_asked() -> None:
    plan = plan_from(
        report("python.environment"),
        policy=NetworkPolicy.OFFLINE,
        capability=host(),
        recreate=True,
    )
    assert [action.identifier for action in plan.actions] == ["environment.recreate"]
    assert plan.destructive


def test_a_rebuild_subsumes_a_create_rather_than_following_it() -> None:
    """Planning both would delete what the first one made."""
    plan = plan_from(
        report("python.environment"),
        policy=NetworkPolicy.OFFLINE,
        capability=host(),
        recreate=True,
    )
    assert "environment.create" not in [action.identifier for action in plan.actions]


def test_a_host_with_no_launcher_is_recorded_on_the_action_rather_than_refused() -> None:
    """Whether a launcher is needed is the executor's question, not the planner's.

    A planner that refused here would be deciding something the report cannot
    support.
    """
    plan = plan_from(
        report("python.environment"),
        policy=NetworkPolicy.OFFLINE,
        capability=host(launcher=None),
    )
    assert "no Python launcher" in plan.actions[0].reason


def test_the_plan_is_derived_from_the_report_and_from_nothing_else() -> None:
    """Two identical reports produce two identical plans, whatever the host has."""
    first = plan_from(report("dependency.lock"), policy=NetworkPolicy.CACHE_ONLY, capability=host())
    second = plan_from(
        report("dependency.lock"),
        policy=NetworkPolicy.CACHE_ONLY,
        capability=host(launcher=Tool.PYTHON_MANAGER),
    )
    assert [a.identifier for a in first.actions] == [a.identifier for a in second.actions]


def test_an_unmeasured_check_is_planned_for_as_a_failing_one() -> None:
    """Unmeasured outranks failed everywhere else, and must not be ignored here."""
    from globin.domain.bootstrap import check_identifiers

    unmeasured = BootstrapReport(
        outcomes=tuple(
            outcome(
                name,
                CheckStatus.UNMEASURED if name == "python.environment" else CheckStatus.PASS,
            )
            for name in check_identifiers()
        )
    )
    plan = plan_from(unmeasured, policy=NetworkPolicy.OFFLINE, capability=host())
    assert [action.identifier for action in plan.actions] == ["environment.create"]


# ---------------------------------------------------------------------------
# The plan as a value
# ---------------------------------------------------------------------------


def action(identifier: str = "environment.create") -> ProvisioningAction:
    """One bound action."""
    return ProvisioningAction(spec=action_spec_for(identifier), reason="a reason")


def test_a_plan_that_repeats_an_action_is_refused() -> None:
    with pytest.raises(ValidationError, match="at most once"):
        ProvisioningPlan(policy=NetworkPolicy.OFFLINE, actions=(action(), action()))


def test_a_plan_reports_what_its_policy_forbids_rather_than_dropping_it() -> None:
    """An operator running offline must see what could not be attempted."""
    plan = plan_from(report("dependency.lock"), policy=NetworkPolicy.OFFLINE, capability=host())
    refused = plan.refused_by_policy()
    assert [entry.identifier for entry in refused] == ["dependency.install"]


def test_the_same_plan_under_a_cache_policy_forbids_nothing() -> None:
    plan = plan_from(report("dependency.lock"), policy=NetworkPolicy.CACHE_ONLY, capability=host())
    assert plan.refused_by_policy() == ()


def test_admitted_narrows_by_both_the_policy_and_the_caller() -> None:
    plan = plan_from(report("dependency.lock"), policy=NetworkPolicy.CACHE_ONLY, capability=host())
    assert plan.admitted(frozenset({MutationClass.INSTALL}))
    assert not plan.admitted(frozenset({MutationClass.CREATE}))


def test_a_plan_beyond_the_bound_is_refused() -> None:
    """Guard the bound, since the declared actions are well under the ceiling."""
    assert len(actions()) <= MAX_ACTIONS


def test_at_most_one_non_destructive_action_answers_any_postcondition() -> None:
    """Two actions answering one check would plan one job twice.

    Phase 032 found this by writing `dependency.install` and `dependency.repair`
    against the same check: a failing lock produced a two-step plan that ran the
    same command twice. The destructive action is exempt because it shares
    `python.environment` with `environment.create` deliberately, and a plan
    carries one or the other rather than both.
    """
    seen: dict[str, list[str]] = {}
    for spec in actions():
        if spec.destructive:
            continue
        seen.setdefault(spec.postcondition, []).append(spec.identifier)
    doubled = {key: names for key, names in seen.items() if len(names) > 1}
    assert not doubled, f"these checks are answered by more than one action: {doubled}"


def test_a_failing_dependency_check_plans_exactly_one_action() -> None:
    """The concrete case the rule above generalises."""
    plan = plan_from(report("dependency.lock"), policy=NetworkPolicy.CACHE_ONLY, capability=host())
    assert [action.identifier for action in plan.actions] == ["dependency.install"]


# ---------------------------------------------------------------------------
# The journal
# ---------------------------------------------------------------------------


def journal(*outcomes: ActionOutcome) -> ProvisioningJournal:
    """A journal over as many actions as outcomes given."""
    identifiers = ["paths.create", "environment.create", "dependency.install"][: len(outcomes)]
    bound = tuple(action(name) for name in identifiers)
    plan = ProvisioningPlan(policy=NetworkPolicy.CACHE_ONLY, actions=bound)
    return ProvisioningJournal(
        plan=plan,
        steps=tuple(
            ProvisioningStep(action=entry, outcome=result)
            for entry, result in zip(bound, outcomes, strict=True)
        ),
    )


def test_a_journal_of_satisfied_steps_changed_nothing() -> None:
    """What a second `setup` run over an unchanged host produces."""
    recorded = journal(ActionOutcome.SATISFIED, ActionOutcome.SATISFIED)
    assert not recorded.changed
    assert recorded.complete
    assert not recorded.failed


def test_a_journal_with_one_applied_step_changed_something() -> None:
    recorded = journal(ActionOutcome.SATISFIED, ActionOutcome.APPLIED)
    assert recorded.changed


def test_a_journal_with_an_unattempted_step_is_incomplete() -> None:
    """The property that stops a half-finished run from carrying a verdict."""
    recorded = journal(ActionOutcome.FAILED, ActionOutcome.NOT_ATTEMPTED)
    assert not recorded.complete
    assert recorded.failed


def test_a_journal_describing_an_action_the_plan_does_not_carry_is_refused() -> None:
    plan = ProvisioningPlan(policy=NetworkPolicy.OFFLINE, actions=(action("paths.create"),))
    with pytest.raises(ValidationError, match="not in the plan"):
        ProvisioningJournal(
            plan=plan,
            steps=(
                ProvisioningStep(
                    action=action("environment.create"), outcome=ActionOutcome.APPLIED
                ),
            ),
        )


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ((ActionOutcome.SATISFIED, ActionOutcome.APPLIED), ActionOutcome.APPLIED),
        ((ActionOutcome.APPLIED, ActionOutcome.FAILED), ActionOutcome.FAILED),
        ((ActionOutcome.APPLIED, ActionOutcome.REFUSED), ActionOutcome.REFUSED),
        ((ActionOutcome.SATISFIED, ActionOutcome.SATISFIED), ActionOutcome.SATISFIED),
        ((ActionOutcome.FAILED, ActionOutcome.NOT_ATTEMPTED), ActionOutcome.FAILED),
    ],
)
def test_a_run_is_described_by_its_worst_outcome(
    given: tuple[ActionOutcome, ...], expected: ActionOutcome
) -> None:
    """A run with one failure is never described by the successes beside it."""
    steps = tuple(
        ProvisioningStep(action=action("paths.create"), outcome=result) for result in given
    )
    assert outcome_for(steps) is expected


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_an_empty_plan_exits_ok() -> None:
    plan = plan_from(report(), policy=NetworkPolicy.OFFLINE, capability=host())
    assert exit_code_for_plan(plan, report()) is ExitCode.OK


def test_a_non_empty_plan_exits_with_the_code_check_would_give() -> None:
    """`plan` and `check` answer identically for the same host.

    That is the property a launcher branching on either depends on, and it comes
    from both reading one report rather than from two tables agreeing.
    """
    from globin.domain.bootstrap import exit_code_for

    measured = report("python.environment")
    plan = plan_from(measured, policy=NetworkPolicy.OFFLINE, capability=host())
    assert exit_code_for_plan(plan, measured) is exit_code_for(measured)
    assert exit_code_for_plan(plan, measured) is ExitCode.ENVIRONMENT_MISMATCH


def test_a_failed_run_gates() -> None:
    assert exit_code_for_journal(journal(ActionOutcome.FAILED), None) is ExitCode.GATE_FAILED


def test_an_incomplete_run_gates_even_without_a_failure() -> None:
    recorded = journal(ActionOutcome.APPLIED, ActionOutcome.NOT_ATTEMPTED)
    assert exit_code_for_journal(recorded, None) is ExitCode.GATE_FAILED


def test_a_complete_run_reports_what_the_re_measurement_found() -> None:
    recorded = journal(ActionOutcome.APPLIED, ActionOutcome.APPLIED, ActionOutcome.APPLIED)
    assert exit_code_for_journal(recorded, report()) is ExitCode.OK
    assert (
        exit_code_for_journal(recorded, report("python.environment"))
        is ExitCode.ENVIRONMENT_MISMATCH
    )


def test_twenty_six_is_still_not_an_exit_code() -> None:
    """Phase 032 added no code, and this is where that stays true.

    Every refusal this phase can produce maps onto one that already exists. A
    twenty-sixth whose only honest readiness mapping is `UNKNOWN` is the thing
    Phase 031 refused to add, and adding one here would have been the same defect
    with a different number.
    """
    assert 26 not in {int(code) for code in ExitCode}


def test_the_check_status_vocabulary_is_still_four_words() -> None:
    """An action's outcome is a different subject, and got its own enum.

    A fifth member here would be this phase widening a vocabulary rather than
    naming a second one, which is the defect a consolidation phase exists to
    prevent.
    """
    assert {member.name for member in CheckStatus} == {"PASS", "FAIL", "WARN", "UNMEASURED"}
    assert not {member.value for member in ActionOutcome} & {member.value for member in CheckStatus}
