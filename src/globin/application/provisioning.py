"""Producing a plan, and applying one.

**Two use cases, and one of them is read-only by construction.**
:class:`ProvisioningPlanRun` composes the existing bootstrap pipeline and the
pure planner, and touches nothing else --- a plan is a function of a report, so
producing one cannot change a host. :class:`ProvisioningApply` adds an executor,
a claim and a lock, and is the only thing here that mutates.

**``setup`` and ``repair`` are one code path and two admitted-mutation sets.**
Not two pipelines: the difference between them is which
:class:`globin.domain.provisioning.MutationClass` members are permitted, which is
an argument rather than a branch. That is the shape
:class:`globin.application.preflight.PreflightRun` already uses --- a third
combination of switches that already existed.

**The order inside :meth:`ProvisioningApply.run` is the whole safety argument.**
The claim is written before the first mutation and released only after the last
one completes, so a process ended between them leaves it behind; and the report
that decides the exit code is taken *after* the work, so the postconditions are
proved rather than trusted.
"""

from dataclasses import dataclass

from globin.application.bootstrap import BootstrapPipeline
from globin.domain.bootstrap import BootstrapOutcome, BootstrapReport, ExitCode
from globin.domain.process import HostCapability
from globin.domain.provisioning import (
    ActionOutcome,
    MutationClass,
    NetworkPolicy,
    ProvisioningAction,
    ProvisioningJournal,
    ProvisioningPlan,
    ProvisioningStep,
    admits,
    exit_code_for_journal,
    exit_code_for_plan,
    plan_from,
)
from globin.errors import ValidationError
from globin.ports.provisioning import CapabilityProbe, EnvironmentClaim, ProvisioningExecutor
from globin.ports.runtime_state import InstanceLock


def setup_mutations() -> frozenset[MutationClass]:
    """What ``bootstrap setup`` may do: bring things into existence, and record.

    Returns:
        The admitted mutation classes.

    A function rather than a constant because building a ``frozenset`` is a call,
    and ``tests/architecture/test_architecture_contract.py`` refuses one at import
    in a layer package --- the rule
    :func:`globin.domain.bootstrap.checks` states about itself.

    Deliberately excludes :attr:`globin.domain.provisioning.MutationClass.REMOVE`,
    which is the whole difference between this and ``repair --recreate``.
    """
    return frozenset({MutationClass.CREATE, MutationClass.INSTALL, MutationClass.RECORD})


def recreate_mutations() -> frozenset[MutationClass]:
    """What ``bootstrap repair --recreate`` may do.

    Returns:
        The admitted mutation classes.

    The only set containing :attr:`globin.domain.provisioning.MutationClass.REMOVE`,
    and it is reachable only from a switch an operator typed.

    **Without ``--recreate``, ``repair`` admits exactly what ``setup`` does**, and
    that is honest rather than a gap. The only repair GLOBIN can perform today is
    on its own runtime tree; rebuilding an environment is the operator's, and the
    plan names the command.
    """
    return setup_mutations() | {MutationClass.REMOVE}


@dataclass(frozen=True, slots=True)
class ProvisioningProposal:
    """What was measured, what the host has, and what would change.

    Args:
        outcome: What the bootstrap pipeline concluded.
        capability: Which tools were found.
        plan: What would be changed.
    """

    outcome: BootstrapOutcome
    capability: HostCapability
    plan: ProvisioningPlan

    @property
    def report(self) -> BootstrapReport:
        """The report the plan was derived from."""
        return self.outcome.report

    @property
    def exit_code(self) -> ExitCode:
        """What ``bootstrap plan`` returns for this proposal."""
        return exit_code_for_plan(self.plan, self.report)

    def as_record(self) -> dict[str, object]:
        """This proposal as the mapping evidence carries.

        Returns:
            The capability inventory, the plan, and the verdict it implies.
        """
        return {
            "capability": self.capability.as_record(),
            "plan": self.plan.as_record(),
            "ready": self.report.ready,
            "exit_code": int(self.exit_code),
        }


@dataclass(frozen=True, slots=True)
class ProvisioningPlanRun:
    """Measure the host, and say what would change. Changes nothing.

    Args:
        pipeline: The existing bootstrap pipeline, composed rather than rebuilt.
        capabilities: How to discover the host's tools.
        policy: What the operator permitted this run to reach.
        recreate: Whether the operator asked for a destructive rebuild.
    """

    pipeline: BootstrapPipeline
    capabilities: CapabilityProbe
    policy: NetworkPolicy
    recreate: bool = False

    def run(self) -> ProvisioningProposal:
        """Take every measurement, then derive the plan from it.

        Returns:
            The proposal.

        ``stop_at_first_refusal=False`` for the reason
        :class:`globin.application.preflight.PreflightRun` gives: a plan built
        from a report that stopped at the first failure would name one action and
        hide the rest, so an operator would have to run this once per problem.
        """
        outcome = self.pipeline.run(stop_at_first_refusal=False)
        capability = self.capabilities.capabilities()
        plan = plan_from(
            outcome.report,
            policy=self.policy,
            capability=capability,
            recreate=self.recreate,
        )
        return ProvisioningProposal(outcome=outcome, capability=capability, plan=plan)


@dataclass(frozen=True, slots=True)
class ProvisioningOutcome:
    """What a provisioning run intended, did, and left behind.

    Args:
        before: What was measured before anything changed.
        journal: What was done.
        after: What a re-measurement concluded, or ``None`` when the run did not
            reach one.

    Raises:
        ValidationError: If an ``after`` report is carried on an incomplete
            journal.

    **The invariant is the same one
    :class:`globin.domain.bootstrap.BootstrapOutcome` enforces**, for the same
    reason: a caller must not be able to obtain a clean verdict from a run that
    did not finish, by ignoring the part that says it did not.
    """

    before: ProvisioningProposal
    journal: ProvisioningJournal
    after: BootstrapOutcome | None = None

    def __post_init__(self) -> None:
        """Refuse a re-measurement a half-finished run cannot support."""
        if self.after is not None and not self.journal.complete:
            msg = (
                "a provisioning run that did not complete carries no re-measurement; "
                "the host was left part-way and a report over it would read as a verdict"
            )
            raise ValidationError(msg)

    @property
    def changed(self) -> bool:
        """Whether anything was actually done."""
        return self.journal.changed

    @property
    def exit_code(self) -> ExitCode:
        """What ``bootstrap setup`` or ``bootstrap repair`` returns."""
        return exit_code_for_journal(
            self.journal, None if self.after is None else self.after.report
        )

    def as_record(self) -> dict[str, object]:
        """This run as the mapping evidence carries.

        Returns:
            The proposal, the journal, whether a re-measurement was reached and
            what it concluded.
        """
        return {
            "before": self.before.as_record(),
            "journal": self.journal.as_record(),
            "after": None if self.after is None else {"ready": self.after.report.ready},
            "changed": self.changed,
            "exit_code": int(self.exit_code),
        }


@dataclass(frozen=True, slots=True)
class ProvisioningApply:
    """Apply a plan, under a lock, behind a claim.

    Args:
        proposal: How to measure the host and derive a plan.
        executor: How to perform one action.
        claim: How to mark a half-built environment.
        lock: The provisioning lock. A *second* instance of the Phase 022 lock
            with its own name, never the coordinator's.

    **The lock is not the coordinator's, and that matters.** That one is a
    whole-application mutex; holding it here would make this run's own
    ``instance.lock`` check fail against itself.
    """

    proposal: ProvisioningPlanRun
    executor: ProvisioningExecutor
    claim: EnvironmentClaim
    lock: InstanceLock

    def setup(self) -> ProvisioningOutcome:
        """Bring missing pieces into existence.

        Returns:
            What was done.
        """
        return self.run(admitted=setup_mutations())

    def repair(self, *, recreate: bool = False) -> ProvisioningOutcome:
        """Correct what exists and is wrong.

        Args:
            recreate: Whether the destructive rebuild is permitted.

        Returns:
            What was done.
        """
        return self.run(admitted=recreate_mutations() if recreate else setup_mutations())

    def run(self, *, admitted: frozenset[MutationClass]) -> ProvisioningOutcome:
        """Measure, plan, apply what is permitted, then measure again.

        Args:
            admitted: Which mutation classes this invocation may perform.

        Returns:
            What was intended and what happened.

        The sequence, and why each step is where it is:

        1. Take the provisioning lock, so two mutating runs cannot interleave.
        2. Measure and plan.
        3. Write the claim **before** the first mutation.
        4. Apply, stopping at the first failure and recording the rest as
           not-attempted rather than silently omitting them.
        5. Release the claim **only** if every step completed.
        6. Re-measure, so the postconditions are proved rather than trusted.
        """
        with self.lock.hold():
            before = self.proposal.run()
            steps = self._steps(before.plan, admitted)
            journal = ProvisioningJournal(plan=before.plan, steps=steps)
            after: BootstrapOutcome | None = None
            if journal.complete and not journal.failed:
                self.claim.release()
                after = self.proposal.pipeline.run(stop_at_first_refusal=False)
            return ProvisioningOutcome(before=before, journal=journal, after=after)

    def _steps(
        self, plan: ProvisioningPlan, admitted: frozenset[MutationClass]
    ) -> tuple[ProvisioningStep, ...]:
        """Apply every action the caller and the policy permit, in order.

        Args:
            plan: What would be changed.
            admitted: Which mutation classes this invocation may perform.

        Returns:
            One step per planned action, in plan order.

        The claim is written here rather than in :meth:`run`, and only when there
        is something to write it for: a plan with nothing to apply must not leave
        a marker behind, or a check over an untouched host would read as
        interrupted.
        """
        applicable = [
            action for action in plan.actions if self._refusal(action, plan, admitted) is None
        ]
        if applicable:
            self.claim.claim(plan)

        steps: list[ProvisioningStep] = []
        stopped = False
        for action in plan.actions:
            refusal = self._refusal(action, plan, admitted)
            if refusal is not None:
                steps.append(
                    ProvisioningStep(action=action, outcome=ActionOutcome.REFUSED, detail=refusal)
                )
                continue
            if stopped:
                steps.append(
                    ProvisioningStep(
                        action=action,
                        outcome=ActionOutcome.NOT_ATTEMPTED,
                        detail="an earlier action failed, so this one was not reached",
                    )
                )
                continue
            step = self.executor.apply(action)
            steps.append(step)
            if step.outcome is ActionOutcome.FAILED:
                stopped = True
        return tuple(steps)

    @staticmethod
    def _refusal(
        action: ProvisioningAction,
        plan: ProvisioningPlan,
        admitted: frozenset[MutationClass],
    ) -> str | None:
        """Why this action may not run, or ``None`` if it may.

        Args:
            action: The action.
            plan: The plan it belongs to, for the network policy.
            admitted: Which mutation classes this invocation may perform.

        Returns:
            One sentence naming the refusal, or ``None``.
        """
        if not admits(plan.policy, action.spec.network):
            return (
                f"this action needs {action.spec.network.value} and the run is {plan.policy.value}"
            )
        if action.spec.mutation not in admitted:
            if action.spec.mutation is MutationClass.REMOVE:
                return (
                    "this action destroys the environment; `bootstrap repair --recreate` "
                    "is the one command that performs it"
                )
            return f"this command does not perform {action.spec.mutation.value} actions"
        return None
