"""What would be changed to make this host ready, and what changing it costs.

**A plan is derived from a bootstrap report and from nothing else.** :func:`plan_from`
takes a :class:`globin.domain.bootstrap.BootstrapReport` and a policy, and has no
probes of its own. Two consequences follow, and both are the reason it is written
this way. ``plan`` and ``check`` cannot disagree about the host, because they read
one report. And ``plan`` is read-only *by the architecture contract* rather than by
promise: this module is in ``globin.domain``, which
``docs/architecture/dependency-rules.toml`` gives ``may_perform_io = false``, so
the planner could not write even if somebody asked it to.

**The status vocabulary is not widened.** :class:`globin.domain.bootstrap.CheckStatus`
stays at four members. What an *action* concluded is a different subject from what a
*measurement* concluded, so it gets :class:`ActionOutcome` --- a disjoint enum ---
rather than two more members on the first. The distinction that forced this is
``SATISFIED``: "the postcondition already held" and "no measurement was taken" are
the two answers a second ``setup`` run most needs kept apart, and one word for both
would make an idempotent run indistinguishable from an unreadable disk.

**Nothing here provisions a credential or writes configuration.** No
:class:`ActionSpec` may name a ``secrets.*`` or ``config.*`` check in
``remedy_for``, and ``tests/contract/test_provisioning_contract.py`` fails if one
does. That is what makes ``setup`` structurally unable to reach a credential store,
rather than merely unlikely to.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.domain.bootstrap import (
    BootstrapReport,
    CheckStatus,
    ExitCode,
    RecordedPath,
    check_identifiers,
    exit_code_for,
    recorded_absent,
)
from globin.domain.process import HostCapability
from globin.errors import InternalError, ValidationError

IDENTIFIER_SEGMENTS: Final[int] = 2
"""An action identifier is ``area.subject``, like a check identifier."""

MAX_ACTIONS: Final[int] = 16
"""How many actions one plan may carry.

A bound rather than a limit anybody is near --- six are declared. It exists so a
plan is a thing an operator can read before approving, which is the whole reason
a plan is produced separately from applying one.
"""

FORBIDDEN_REMEDY_PREFIXES: Final[tuple[str, ...]] = ("secrets.", "config.")
"""Check areas no action may answer for.

A failing ``secrets.required`` is fixed by an operator running ``globin secrets
set`` at a console, and a failing ``config.valid`` by editing a document. Both are
deliberate human acts with their own commands, and an action that performed either
would be this phase quietly acquiring the ability to write a credential store.
"""


class MutationClass(StrEnum):
    """What kind of change an action makes.

    Grouped by what a reader needs to decide whether to approve it, not by which
    subsystem performs it.
    """

    CREATE = "create"
    """Something that did not exist comes into existence."""

    INSTALL = "install"
    """Artefacts are placed into an environment that already exists."""

    REMOVE = "remove"
    """Something is deleted. The only class that can lose work."""

    RECORD = "record"
    """Evidence is written. Changes nothing a later run depends on."""


class NetworkPolicy(StrEnum):
    """What an operator has permitted this run to reach.

    **Declared, never probed.** This is a value an operator supplies, and nothing
    in GLOBIN tests connectivity to derive it. A probe would be a mechanism with
    no caller *and* would add an outbound connect to a package that has none,
    removing a guarantee ``tests/architecture/test_library_discipline.py``
    currently proves --- the same reasoning ``degradation-contract.toml`` gives
    for its own network row.

    The default is :attr:`OFFLINE`, and that is a decision worth defending: the
    one command that mutates a host must not also be the one that reaches the
    network without being asked.
    """

    OFFLINE = "offline"
    """Nothing may leave this machine, and no cache may be consulted either."""

    CACHE_ONLY = "cache-only"
    """A local wheelhouse may be read. Still nothing leaves the machine."""

    ONLINE_ALLOWED = "online-allowed"
    """An index may be reached. Never the default."""


class NetworkRequirement(StrEnum):
    """What an action needs in order to run."""

    NONE = "none"
    """Nothing outside this machine, and no cache."""

    CACHE = "cache"
    """A populated local wheelhouse."""

    NETWORK = "network"
    """An index. No declared action requires this today."""


class Performer(StrEnum):
    """Who carries an action out.

    **The distinction the packaging forced.** GLOBIN's wheel contains the package
    and its metadata and nothing else --- no ``tools/``, no ``scripts/`` --- so an
    installed GLOBIN cannot invoke the gate that builds an environment. An
    executor that tried would work from a source checkout and fail everywhere
    else, which is the worst of the two.

    A plan shows both kinds, because an operator needs to see everything standing
    between them and a working host. The executor performs only :attr:`GLOBIN`
    actions and reports the others with the command to run.
    """

    GLOBIN = "globin"
    """GLOBIN does it, inside its own runtime tree."""

    OPERATOR = "operator"
    """An operator runs a named command. GLOBIN reports it and does not attempt
    it."""


class Privilege(StrEnum):
    """What an action must be run as.

    Every declared action is :attr:`USER`. The member exists so that an action
    needing elevation would have to say so in its declaration and appear in a
    plan before anything ran, rather than discovering it at the point of failure.
    """

    USER = "user"
    ELEVATED = "elevated"


class Recovery(StrEnum):
    """What happens if an action is interrupted part-way."""

    RESUMABLE = "resumable"
    """Running it again finishes the job. Nothing is lost."""

    RESTART_REQUIRED = "restart-required"
    """The target is left unusable and must be rebuilt from the start."""

    IRREVERSIBLE = "irreversible"
    """Something is gone. No action declares this, and one that did would need a
    reason written down beside it."""


class ActionOutcome(StrEnum):
    """What one action concluded.

    Disjoint from :class:`globin.domain.bootstrap.CheckStatus` because it answers
    a different question. A check says what was *measured*; an action says what
    was *done*.

    :attr:`SATISFIED` rather than a word like "skipped" is load-bearing. Skipped
    is a statement about the scheduler and proves nothing about the host;
    satisfied asserts the postcondition holds, which is the sentence an
    idempotency test needs.
    """

    APPLIED = "applied"
    """The mutation was made and its postcondition now holds."""

    SATISFIED = "satisfied"
    """The postcondition already held, so nothing was done."""

    REFUSED = "refused"
    """Policy or privilege forbade it. Nothing was attempted."""

    FAILED = "failed"
    """It was attempted and the postcondition was not reached."""

    NOT_ATTEMPTED = "not_attempted"
    """An earlier action failed, so this one was never reached."""


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """One change this phase knows how to make.

    Args:
        identifier: Stable and machine-readable, in ``area.subject`` form.
        mutation: What kind of change it is.
        network: What it needs in order to run.
        privilege: What it must run as.
        destructive: Whether it can lose work. Requires explicit operator intent.
        recovery: What an interruption leaves behind.
        postcondition: The check identifier that is true once this has worked.
        remedy_for: The check identifiers whose failure this action answers.
        performer: Who carries it out.
        command: What an operator runs, when the operator is the performer.

    Raises:
        ValidationError: If the identifier is malformed, the postcondition or a
            remedy names a check that does not exist, a remedy names a forbidden
            area, or a destructive action claims to be resumable.

    The relationship to :class:`globin.domain.bootstrap.CheckSpec` is deliberate
    and exact: a check declares what is measured and what its failure costs; a
    spec here declares what would fix it and what fixing it costs.
    """

    identifier: str
    mutation: MutationClass
    network: NetworkRequirement
    privilege: Privilege
    destructive: bool
    recovery: Recovery
    postcondition: str
    remedy_for: tuple[str, ...] = ()
    performer: Performer = Performer.GLOBIN
    command: str = ""

    def __post_init__(self) -> None:
        """Refuse a declaration this phase cannot honour."""
        if len(self.identifier.split(".")) != IDENTIFIER_SEGMENTS:
            msg = f"{self.identifier!r} is not an action identifier in area.subject form"
            raise ValidationError(msg)
        known = set(check_identifiers())
        if self.postcondition not in known:
            msg = (
                f"{self.identifier} claims the postcondition {self.postcondition!r}, "
                f"which is not a registered check"
            )
            raise ValidationError(msg)
        for remedy in self.remedy_for:
            if remedy not in known:
                msg = f"{self.identifier} answers for {remedy!r}, which is not a registered check"
                raise ValidationError(msg)
            if remedy.startswith(FORBIDDEN_REMEDY_PREFIXES):
                msg = (
                    f"{self.identifier} answers for {remedy!r}. Provisioning does not "
                    f"write a credential or a configuration document; those are "
                    f"operator acts with their own commands"
                )
                raise ValidationError(msg)
        if self.performer is Performer.OPERATOR and not self.command:
            msg = (
                f"{self.identifier} is the operator's to perform and names no command. "
                f"Reporting that something must be done without saying what is worse "
                f"than not reporting it"
            )
            raise ValidationError(msg)
        if self.performer is Performer.GLOBIN and self.command:
            msg = (
                f"{self.identifier} is GLOBIN's to perform and names a command an "
                f"operator would run, which is two answers to one question"
            )
            raise ValidationError(msg)
        if self.destructive and self.recovery is Recovery.RESUMABLE:
            msg = (
                f"{self.identifier} is destructive and claims to be resumable. "
                f"An interrupted delete does not finish by being run again"
            )
            raise ValidationError(msg)

    @property
    def area(self) -> str:
        """The identifier's first segment."""
        return self.identifier.split(".", 1)[0]

    def as_record(self) -> dict[str, object]:
        """This declaration as the mapping evidence carries.

        Returns:
            Every declared field, with enums as their values.
        """
        return {
            "id": self.identifier,
            "mutation": self.mutation.value,
            "network": self.network.value,
            "privilege": self.privilege.value,
            "destructive": self.destructive,
            "recovery": self.recovery.value,
            "postcondition": self.postcondition,
            "remedy_for": list(self.remedy_for),
            "performer": self.performer.value,
            "command": self.command,
        }


def actions() -> tuple[ActionSpec, ...]:
    """Return every action this phase can perform, in the order it performs them.

    Returns:
        One specification per action.

    A function rather than a constant, for the reason
    :func:`globin.domain.bootstrap.checks` gives about itself: building an
    :class:`ActionSpec` is a call, and a layer package performs none at import.

    The order is the dependency order. An environment must exist before anything
    can be installed into it, and evidence is recorded last because it describes
    everything before it.

    **Three absences are decisions, and each is asserted by a test.**

    **Two actions share the ``python.environment`` postcondition, and exactly
    two may.** ``environment.create`` and ``environment.recreate`` answer the same
    failing check, and a plan carries one or the other because the destructive one
    is reachable only from a switch an operator typed. Any other pair sharing a
    postcondition would be a plan that did one job twice, which is what
    ``tests/unit/test_provisioning.py`` refuses.

    - **No ``runtime.install``.** ``tools/quality/runtime`` already carries an
      opt-in for installing a Python through the install manager, and reports
      that this host's launcher cannot: it has the legacy one. A member nothing
      can emit is vocabulary rather than a capability --- the criticism
      :func:`globin.domain.bootstrap.readiness_for` makes of its own defaults.
    - **No ``secrets.*`` and no ``config.*``.** Enforced structurally by
      :data:`FORBIDDEN_REMEDY_PREFIXES` rather than by nobody having added one.
    - **``environment.recreate`` is the only destructive action**, matching the
      one opt-in ``tools/quality/runtime`` already exposes, whose recursive
      delete is guarded by a function that refuses anything but the declared
      environment directory.
    """
    return (
        ActionSpec(
            identifier="paths.create",
            mutation=MutationClass.CREATE,
            network=NetworkRequirement.NONE,
            privilege=Privilege.USER,
            destructive=False,
            recovery=Recovery.RESUMABLE,
            postcondition="paths.runtime",
            remedy_for=("paths.runtime", "paths.boundary"),
        ),
        ActionSpec(
            identifier="environment.create",
            mutation=MutationClass.CREATE,
            network=NetworkRequirement.NONE,
            privilege=Privilege.USER,
            destructive=False,
            recovery=Recovery.RESUMABLE,
            postcondition="python.environment",
            remedy_for=("python.environment",),
            performer=Performer.OPERATOR,
            command="powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1",
        ),
        ActionSpec(
            identifier="environment.recreate",
            mutation=MutationClass.REMOVE,
            network=NetworkRequirement.NONE,
            privilege=Privilege.USER,
            destructive=True,
            recovery=Recovery.RESTART_REQUIRED,
            postcondition="python.environment",
            remedy_for=("python.environment",),
            performer=Performer.OPERATOR,
            command="powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 -Recreate",
        ),
        ActionSpec(
            identifier="dependency.install",
            mutation=MutationClass.INSTALL,
            network=NetworkRequirement.CACHE,
            privilege=Privilege.USER,
            destructive=False,
            recovery=Recovery.RESUMABLE,
            postcondition="dependency.lock",
            remedy_for=("dependency.lock",),
            performer=Performer.OPERATOR,
            command="powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1",
        ),
        ActionSpec(
            identifier="evidence.record",
            mutation=MutationClass.RECORD,
            network=NetworkRequirement.NONE,
            privilege=Privilege.USER,
            destructive=False,
            recovery=Recovery.RESUMABLE,
            postcondition="bootstrap.ready",
        ),
    )


def action_identifiers() -> tuple[str, ...]:
    """Every action identifier, in plan order.

    Returns:
        The identifiers.
    """
    return tuple(spec.identifier for spec in actions())


def action_spec_for(identifier: str) -> ActionSpec:
    """Look up an action by its identifier.

    Args:
        identifier: The action identifier.

    Returns:
        Its declaration.

    Raises:
        InternalError: If no action has that identifier. A caller naming one that
            does not exist has a bug rather than bad input.
    """
    for spec in actions():
        if spec.identifier == identifier:
            return spec
    msg = f"no action is registered as {identifier!r}"
    raise InternalError(msg)


def admits(policy: NetworkPolicy, requirement: NetworkRequirement) -> bool:
    """Whether a policy permits an action with a given requirement.

    Args:
        policy: What the operator permitted.
        requirement: What the action needs.

    Returns:
        ``True`` if the action may run.

    Total by construction rather than by a fallback: every pair of members is
    covered, so a seventh policy would fail to typecheck rather than fall through
    to a permissive default.
    """
    permitted = {
        NetworkPolicy.OFFLINE: {NetworkRequirement.NONE},
        NetworkPolicy.CACHE_ONLY: {NetworkRequirement.NONE, NetworkRequirement.CACHE},
        NetworkPolicy.ONLINE_ALLOWED: set(NetworkRequirement),
    }
    return requirement in permitted[policy]


@dataclass(frozen=True, slots=True)
class ProvisioningAction:
    """A declared action, bound to this host and this run.

    Args:
        spec: What kind of action it is.
        reason: Which failing check made it necessary, or why it is included.
        target: What it would change, recorded rather than spelled.
    """

    spec: ActionSpec
    reason: str
    target: RecordedPath | None = None

    @property
    def identifier(self) -> str:
        """The action's identifier."""
        return self.spec.identifier

    def as_record(self) -> dict[str, object]:
        """This action as the mapping evidence carries.

        Returns:
            The declaration, the reason, and the recorded target.
        """
        target = recorded_absent() if self.target is None else self.target
        return {**self.spec.as_record(), "reason": self.reason, "target": target.as_record()}


@dataclass(frozen=True, slots=True)
class ProvisioningPlan:
    """Everything that would be changed, in the order it would be changed.

    Args:
        policy: What the operator permitted this run to reach.
        actions: The actions, in plan order.

    Raises:
        ValidationError: If an action appears twice, or there are too many.
    """

    policy: NetworkPolicy
    actions: tuple[ProvisioningAction, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a plan that repeats itself or exceeds its bound."""
        identifiers = [action.identifier for action in self.actions]
        if len(identifiers) != len(set(identifiers)):
            msg = "a plan performs each action at most once, and this one repeats"
            raise ValidationError(msg)
        if len(self.actions) > MAX_ACTIONS:
            msg = (
                f"a plan carries at most {MAX_ACTIONS} actions, and this one carries "
                f"{len(identifiers)}"
            )
            raise ValidationError(msg)

    @property
    def empty(self) -> bool:
        """Whether there is nothing to do.

        Returns:
            ``True`` when the plan carries no actions --- which is what a second
            ``setup`` run over an unchanged host produces.
        """
        return not self.actions

    @property
    def destructive(self) -> bool:
        """Whether any action can lose work."""
        return any(action.spec.destructive for action in self.actions)

    @property
    def requires_elevation(self) -> bool:
        """Whether any action must run as an administrator."""
        return any(action.spec.privilege is Privilege.ELEVATED for action in self.actions)

    def refused_by_policy(self) -> tuple[ProvisioningAction, ...]:
        """Every action this run's network policy forbids.

        Returns:
            The refused actions, in plan order.

        Reported rather than silently dropped: an operator running offline needs
        to see that the plan *would* have installed dependencies and could not,
        because the alternative is a plan that looks complete and is not.
        """
        return tuple(
            action for action in self.actions if not admits(self.policy, action.spec.network)
        )

    def admitted(self, classes: frozenset[MutationClass]) -> tuple[ProvisioningAction, ...]:
        """Every action both the policy and the caller permit.

        Args:
            classes: The mutation classes this invocation may perform.

        Returns:
            The permitted actions, in plan order.
        """
        return tuple(
            action
            for action in self.actions
            if action.spec.mutation in classes and admits(self.policy, action.spec.network)
        )

    def as_record(self) -> dict[str, object]:
        """This plan as the mapping evidence carries.

        Returns:
            The policy, the actions, and the two properties an approver needs.
        """
        return {
            "policy": self.policy.value,
            "destructive": self.destructive,
            "requires_elevation": self.requires_elevation,
            "actions": [action.as_record() for action in self.actions],
            "refused_by_policy": [action.identifier for action in self.refused_by_policy()],
        }


@dataclass(frozen=True, slots=True)
class ProvisioningStep:
    """What happened when one action was reached.

    Args:
        action: Which action.
        outcome: What it concluded.
        detail: One line of explanation, already redacted by whatever produced it.
    """

    action: ProvisioningAction
    outcome: ActionOutcome
    detail: str = ""

    def as_record(self) -> dict[str, object]:
        """This step as the mapping evidence carries.

        Returns:
            The action identifier, the outcome and the detail.
        """
        return {
            "id": self.action.identifier,
            "outcome": self.outcome.value,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ProvisioningJournal:
    """What a plan actually did.

    Args:
        plan: What was intended.
        steps: What happened, in the order it happened.

    Raises:
        ValidationError: If a step names an action the plan does not carry.
    """

    plan: ProvisioningPlan
    steps: tuple[ProvisioningStep, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a journal describing something the plan did not contain."""
        planned = {action.identifier for action in self.plan.actions}
        for step in self.steps:
            if step.action.identifier not in planned:
                msg = (
                    f"the journal records {step.action.identifier!r}, which is not in the plan "
                    f"it claims to describe"
                )
                raise ValidationError(msg)

    @property
    def changed(self) -> bool:
        """Whether anything was actually done.

        Returns:
            ``True`` if any step applied. The property an idempotency test
            asserts is ``False`` on a second run.
        """
        return any(step.outcome is ActionOutcome.APPLIED for step in self.steps)

    @property
    def failed(self) -> bool:
        """Whether any step was attempted and did not reach its postcondition."""
        return any(step.outcome is ActionOutcome.FAILED for step in self.steps)

    @property
    def complete(self) -> bool:
        """Whether every planned action was reached.

        Returns:
            ``True`` when there is one step per planned action and none was left
            unattempted.
        """
        reached = {
            step.action.identifier
            for step in self.steps
            if step.outcome is not ActionOutcome.NOT_ATTEMPTED
        }
        return reached == {action.identifier for action in self.plan.actions}

    def as_record(self) -> dict[str, object]:
        """This journal as the mapping evidence carries.

        Returns:
            The plan, the steps, and the three properties a reader needs.
        """
        return {
            "plan": self.plan.as_record(),
            "steps": [step.as_record() for step in self.steps],
            "changed": self.changed,
            "failed": self.failed,
            "complete": self.complete,
        }


def plan_from(
    report: BootstrapReport,
    *,
    policy: NetworkPolicy,
    capability: HostCapability,
    recreate: bool = False,
) -> ProvisioningPlan:
    """Derive what would have to change from what was measured.

    Args:
        report: What ``bootstrap check`` concluded. The only source of facts.
        policy: What the operator permitted this run to reach.
        capability: What tools the host has. Recorded in the plan's reasoning
            rather than consulted for a decision today --- no declared action
            needs a launcher, and one that did would read it here.
        recreate: Whether the operator asked for a destructive rebuild. Without
            it, ``environment.recreate`` is never planned.

    Returns:
        The plan, in action order.

    **This function performs no measurement**, which is what makes ``plan`` a
    read-only command by construction rather than by discipline. Everything it
    knows comes from ``report``.
    """
    failing = {
        outcome.identifier
        for outcome in report.outcomes
        if outcome.status is CheckStatus.FAIL or outcome.status is CheckStatus.UNMEASURED
    }
    planned: list[ProvisioningAction] = []
    for spec in actions():
        if spec.identifier == "environment.recreate":
            # Never planned by inference. A destructive action requires the
            # operator to have said so, because the failing check that would
            # justify it is the same one `environment.create` answers.
            if recreate and spec.remedy_for and set(spec.remedy_for) & failing:
                planned.append(
                    ProvisioningAction(
                        spec=spec,
                        reason=(
                            "the operator asked for a rebuild, and the environment does not match"
                        ),
                    )
                )
            continue
        if spec.identifier == "environment.create" and recreate:
            # A rebuild subsumes a create; planning both would delete what the
            # first one made.
            continue
        if spec.identifier == "evidence.record":
            continue
        answered = sorted(set(spec.remedy_for) & failing)
        if answered:
            planned.append(
                ProvisioningAction(
                    spec=spec,
                    reason=f"{', '.join(answered)} did not pass",
                )
            )
    if capability.launcher() is None and any(
        action.identifier in {"environment.create", "environment.recreate"} for action in planned
    ):
        # Recorded on the action rather than refused here: whether a launcher is
        # needed is the executor's question, and a planner that refused would be
        # making a decision the report cannot support.
        planned = [
            ProvisioningAction(
                spec=action.spec,
                reason=f"{action.reason}; no Python launcher was found on this host",
                target=action.target,
            )
            if action.identifier in {"environment.create", "environment.recreate"}
            else action
            for action in planned
        ]
    return ProvisioningPlan(policy=policy, actions=tuple(planned))


def exit_code_for_plan(plan: ProvisioningPlan, report: BootstrapReport) -> ExitCode:
    """What ``bootstrap plan`` returns.

    Args:
        plan: What would be changed.
        report: What was measured.

    Returns:
        :attr:`globin.domain.bootstrap.ExitCode.OK` when there is nothing to do,
        and otherwise the code the same host's ``bootstrap check`` returns.

    **A non-empty plan is not a new answer.** The plan is derived from the report,
    and :func:`globin.domain.bootstrap.exit_code_for` already reduces that report
    to the earliest failing check's declared code. Returning it is strictly more
    informative than a generic "work is required", and it makes ``plan`` and
    ``check`` answer identically for the same host --- the property that lets a
    launcher branch on either.
    """
    if plan.empty:
        return ExitCode.OK
    return exit_code_for(report)


def exit_code_for_journal(journal: ProvisioningJournal, after: BootstrapReport | None) -> ExitCode:
    """What ``bootstrap setup`` or ``bootstrap repair`` returns.

    Args:
        journal: What was done.
        after: What a re-measurement concluded, or ``None`` when the run did not
            reach one.

    Returns:
        :attr:`globin.domain.bootstrap.ExitCode.GATE_FAILED` when a step failed
        or the journal is incomplete, :attr:`globin.domain.bootstrap.ExitCode.OK`
        when the re-measurement is ready, and otherwise that measurement's own
        code.

    **No twenty-sixth exit code.** Every refusal this phase can produce maps
    honestly onto a code that already exists, and one whose only honest readiness
    mapping is ``UNKNOWN`` is the thing Phase 031 refused to add. An interrupted
    environment is :attr:`globin.domain.bootstrap.ExitCode.ENVIRONMENT_MISMATCH`,
    whose published sentence --- this is not the project's own environment --- is
    exactly true of a half-built one. ``26`` stays free.
    """
    if journal.failed or not journal.complete:
        return ExitCode.GATE_FAILED
    if after is None:
        return ExitCode.GATE_FAILED
    return exit_code_for(after)


def outcome_for(steps: Sequence[ProvisioningStep]) -> ActionOutcome:
    """The single word that describes a whole run.

    Args:
        steps: What happened.

    Returns:
        The worst outcome present, in the order failure, not-attempted, refused,
        applied, satisfied.

    Ordered worst-first so that a run with one failure is never described by the
    five successes beside it.
    """
    present = {step.outcome for step in steps}
    for outcome in (
        ActionOutcome.FAILED,
        ActionOutcome.NOT_ATTEMPTED,
        ActionOutcome.REFUSED,
        ActionOutcome.APPLIED,
    ):
        if outcome in present:
            return outcome
    return ActionOutcome.SATISFIED
