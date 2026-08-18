"""What GLOBIN may run without, and what it must refuse to start without.

Phase 031's titled scope. ADR-0076 states the residue precisely: "what a running
GLOBIN does when an optional component is missing, how it reports a partial
capability, and what it refuses to start without." That is *behaviour*, not a
verdict about a tree — ``tools/quality/materialize/`` already answers whether the
committed lock could be installed from local bytes, and asking it again from
another entrypoint would be the failure that gate's own record predicted.

**The gap this closes is small and real.** Five factories in
:mod:`globin.adapters` each choose between a working implementation and a
recording stand-in — ``psutil``, ``opentelemetry``, ``prometheus_client``,
``advapi32`` and ``kernel32``, now six with ``crypt32``. Which arm each took was
thrown away everywhere except one untyped dictionary built inside one command.
This module gives that fact a type, a necessity and a rule.

**Almost nothing here is new, and that is the design.**
:class:`~globin.domain.environment.CapabilityStatus` already spells the five
answers, :class:`~globin.domain.environment.CapabilityReason` already bounds the
why, and :class:`~globin.domain.environment.EnvironmentCompatibility` already has
exactly the three words a posture needs. Inventing a parallel posture enumeration
would have produced two vocabularies for one idea. What is genuinely new is
:class:`ComponentNecessity`, because nothing existing says *whether GLOBIN may run
without this*.

**The inherited rule from Phase 030 lives in** :func:`degrades`. A capability the
registry *predicted* absent must not make a host amber: the CI ``quality`` job
installs neither ``psutil`` nor either telemetry library on any run, and under the
obvious rule this posture would be ``DEGRADED`` for ever — a signal that is always
amber is a signal nobody reads.

**No fingerprint, and the refusal is deliberate.**
:func:`~globin.domain.environment.compatibility_fingerprint` exists because
environment compatibility is stable, and a stable identifier for a stable thing is
meaningful. A degradation posture is perishable — a library can be installed into
a running environment — so a fingerprint over it would be a stable name for an
unstable thing, and somebody would compare two of them.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.domain.bootstrap import CheckOutcome, CheckStatus
from globin.domain.environment import (
    CapabilityReason,
    CapabilityStatus,
    EnvironmentCompatibility,
)
from globin.errors import ValidationError

COMPONENT_PREFIX: Final[str] = "component."
"""What every component identifier begins with.

So that an identifier is recognisable wherever it is published, and so that a
check name and a component name cannot be confused for one another.
"""

MAX_DETAIL_LENGTH: Final[int] = 120
"""The longest phrase an observation may carry.

A phrase, never a sentence and never a path. The bound is what stops a platform
message being pasted in whole, which is how a path or a user name reaches a
published record.
"""

MAX_WITHDRAWN: Final[int] = 8
"""The most capabilities one component may be said to withdraw.

Bounded for the reason every list in a published record is: an unbounded one is a
document whose size depends on something nobody is watching.
"""

DEGRADATION_CHECK: Final[str] = "runtime.degradation"
"""Which registered check this module judges.

Spelled once here and registered once in :func:`~globin.domain.bootstrap.checks`,
so the two cannot drift into naming different things.
"""

MAX_COMPONENTS: Final[int] = 32
"""The most components a report may carry.

Well above the six that exist. It exists so that a malformed contract cannot
produce an unbounded document.
"""


class ComponentNecessity(StrEnum):
    """Whether GLOBIN may run without a component, and what its absence costs.

    Three members where :class:`~globin.domain.environment.CapabilitySeverity`
    has two, and the third is **not** the "recommended" tier that enum's own
    docstring refuses. That rejected tier was a third answer on the *blocking*
    axis — one that neither blocked nor was ignorable, so every caller had to
    decide what it meant. These three produce three distinct, testable behaviours
    and no caller decides anything.
    """

    REQUIRED = "required"
    """Absent means the process refuses to start.

    Reserved for a component whose absence makes a declared GLOBIN capability
    both unperformable **and** unreportable. A component whose stand-in still
    produces a truthful record degrades instead — all six of them do.
    """

    OPTIONAL = "optional"
    """Absent means the process starts, says so, and names what stopped working.

    The posture becomes :attr:`~globin.domain.environment.EnvironmentCompatibility.DEGRADED`
    and ``withdraws`` says which capabilities went with it. An amber that named
    nothing would be an amber nobody could act on.
    """

    OPPORTUNISTIC = "opportunistic"
    """Absent changes nothing, and the posture stays ready.

    **This is Phase 030's inherited rule promoted from a per-check boolean to a
    declared property of a component.**
    :attr:`~globin.domain.health.HealthCheckSpec.tolerates_unknown` says the same
    thing about one health check; this says it once, about the component that
    made the check unmeasurable, in the place a reader looks.

    The observable signal that this tier was drawn wrongly is every row declaring
    it — at which point :attr:`OPTIONAL` means nothing and should go.
    """


class ComponentKind(StrEnum):
    """What sort of thing a component is.

    Grouping only. **Nothing branches on it**, because a kind that changed
    behaviour would be a necessity wearing a different name — the rule
    :class:`~globin.domain.environment.CapabilityCategory` already states about
    itself.
    """

    LIBRARY = "library"
    NATIVE = "native"
    DEVICE = "device"
    NETWORK = "network"


@dataclass(frozen=True, slots=True, order=True)
class ComponentSpec:
    """One thing GLOBIN reaches for, and what its absence means.

    Args:
        identifier: Stable and dotted, beginning with :data:`COMPONENT_PREFIX`.
        kind: What sort of thing this is.
        necessity: Whether a start survives its absence.
        withdraws: The GLOBIN capabilities that stop working, as bounded tokens.
        reached_through: The dotted path of the one factory that decides. Empty
            only for a component nothing reaches yet.
        absence_means: One published sentence. The field name is taken from
            ``gpu-contract.toml`` deliberately: this is that bargain generalised.
        owner_phase: Which phase owes an answer for the absence. Zero means
            nobody does, because the stand-in *is* the answer.

    Raises:
        ValidationError: On an unprefixed or empty identifier; on
            :attr:`ComponentNecessity.OPPORTUNISTIC` with a non-empty
            ``withdraws``; on either other necessity with an empty one; or on
            more than :data:`MAX_WITHDRAWN` tokens.

    **The withdraws invariant is the one worth having.** "Refuse to start" and
    "amber" are both unexplainable without saying what was lost, and an
    opportunistic component that claimed to withdraw something would be
    contradicting its own tier.
    """

    identifier: str
    kind: ComponentKind
    necessity: ComponentNecessity
    withdraws: tuple[str, ...] = ()
    reached_through: str = ""
    absence_means: str = ""
    owner_phase: int = 0

    def __post_init__(self) -> None:
        """Refuse a component declaration that could not be acted on."""
        if not self.identifier.startswith(COMPONENT_PREFIX):
            msg = (
                f"{self.identifier!r} does not begin with {COMPONENT_PREFIX!r}, so it "
                f"could be confused with a check name wherever it is published"
            )
            raise ValidationError(msg)
        if len(self.identifier) <= len(COMPONENT_PREFIX):
            msg = "a component identifier is more than its prefix"
            raise ValidationError(msg)
        if len(self.withdraws) > MAX_WITHDRAWN:
            msg = (
                f"a component may withdraw at most {MAX_WITHDRAWN} capabilities, "
                f"and {self.identifier} names {len(self.withdraws)}"
            )
            raise ValidationError(msg)
        opportunistic = self.necessity is ComponentNecessity.OPPORTUNISTIC
        if opportunistic and self.withdraws:
            msg = (
                f"{self.identifier} is opportunistic and names capabilities it "
                f"withdraws; an absence that changes nothing withdraws nothing"
            )
            raise ValidationError(msg)
        if not opportunistic and not self.withdraws:
            msg = (
                f"{self.identifier} is {self.necessity.value} and names nothing it "
                f"withdraws; a refusal or an amber nobody can act on is not worth raising"
            )
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This declaration as a publishable record.

        Returns:
            Every declared field, with lists rendered in the order declared.
        """
        return {
            "identifier": self.identifier,
            "kind": self.kind.value,
            "necessity": self.necessity.value,
            "withdraws": list(self.withdraws),
            "reached_through": self.reached_through,
            "absence_means": self.absence_means,
            "owner_phase": self.owner_phase,
        }


@dataclass(frozen=True, slots=True, order=True)
class ComponentObservation:
    """What was found when the factory was called.

    Args:
        identifier: Which component.
        status: What was found.
        reason: Why, bounded.
        detail: A phrase, already safe to publish and bounded by
            :data:`MAX_DETAIL_LENGTH`.

    Raises:
        ValidationError: If the detail is longer than the bound.

    **Carries no necessity.** A second copy of a declared field is drift, so
    :func:`blocks` and :func:`degrades` take the specification and the
    observation as two arguments rather than reading one object that holds both.
    """

    identifier: str
    status: CapabilityStatus
    reason: CapabilityReason = CapabilityReason.SATISFIED
    detail: str = ""

    def __post_init__(self) -> None:
        """Refuse an observation carrying more than a phrase."""
        if len(self.detail) > MAX_DETAIL_LENGTH:
            msg = (
                f"an observation detail may be at most {MAX_DETAIL_LENGTH} characters, "
                f"and {self.identifier}'s is {len(self.detail)}"
            )
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This observation as a publishable record.

        Returns:
            The identifier, the status, the reason and the phrase.
        """
        return {
            "identifier": self.identifier,
            "status": self.status.value,
            "reason": self.reason.value,
            "detail": self.detail,
        }


def blocks(spec: ComponentSpec, observation: ComponentObservation) -> bool:
    """Whether this component on its own prevents a start.

    Args:
        spec: What was declared.
        observation: What was found.

    Returns:
        Whether the process must refuse.

    Only a :attr:`ComponentNecessity.REQUIRED` component that was **measured**
    and found absent. :attr:`~globin.domain.environment.CapabilityStatus.UNKNOWN`
    never blocks — a component that could not be measured has not been shown to
    be absent, which is ADR-0045's rule and the reason a host that cannot answer
    a question is still allowed to run.
    """
    return (
        spec.necessity is ComponentNecessity.REQUIRED
        and observation.status is CapabilityStatus.UNSUPPORTED
    )


def degrades(spec: ComponentSpec, observation: ComponentObservation) -> bool:
    """Whether this component makes the process worse than intended.

    Args:
        spec: What was declared.
        observation: What was found.

    Returns:
        Whether the posture should be amber on this component's account.

    **The opportunistic branch is the whole of Phase 030's inheritance**, and it
    is the one place this differs from
    :meth:`~globin.domain.environment.CapabilityCheck.degrading`. There, every
    unknown degrades. Here, an opportunistic component's absence or silence does
    not — because the registry *predicted* it. The CI ``quality`` job installs
    neither ``psutil`` nor either telemetry library on any run; under the other
    rule this posture would be amber for ever, and a signal that is always amber
    is a signal nobody reads.

    :attr:`~globin.domain.environment.CapabilityStatus.NOT_APPLICABLE` never
    degrades either, and that is what carries the network and the device: the
    question does not arise, which is a different thing from an answer nobody
    could get.
    """
    if observation.status is CapabilityStatus.NOT_APPLICABLE:
        return False
    if spec.necessity is ComponentNecessity.OPPORTUNISTIC:
        return False
    return observation.status in {
        CapabilityStatus.DEGRADED,
        CapabilityStatus.UNKNOWN,
        CapabilityStatus.UNSUPPORTED,
    }


@dataclass(frozen=True, slots=True)
class DegradationReport:
    """Every declared component and what was observed of it.

    Args:
        components: The declared registry, as parsed.
        observations: One per component, no more and no fewer.

    Raises:
        ValidationError: If an observation names an undeclared component, if one
            is observed twice, if a declared component has no observation, or if
            there are more than :data:`MAX_COMPONENTS`.

    The third refusal is the one worth having: **a survey that quietly skipped a
    component would report ready for a reason nobody could see.**

    The registry is *carried* rather than imported from a module-level function,
    because it lives in a committed TOML document and a report that reached for a
    global could not be built from literals in a test.
    """

    components: tuple[ComponentSpec, ...]
    observations: tuple[ComponentObservation, ...]

    def __post_init__(self) -> None:
        """Refuse a report that does not cover what it declares."""
        if len(self.components) > MAX_COMPONENTS:
            msg = (
                f"a degradation report may carry at most {MAX_COMPONENTS} components, "
                f"and this one carries {len(self.components)}"
            )
            raise ValidationError(msg)
        declared = [spec.identifier for spec in self.components]
        if len(set(declared)) != len(declared):
            msg = "a component is declared twice; an identifier addresses one component"
            raise ValidationError(msg)
        observed = [observation.identifier for observation in self.observations]
        if len(set(observed)) != len(observed):
            msg = "a component is observed twice, so its posture would depend on order"
            raise ValidationError(msg)
        undeclared = sorted(set(observed) - set(declared))
        if undeclared:
            msg = f"observed but not declared: {', '.join(undeclared)}"
            raise ValidationError(msg)
        unobserved = sorted(set(declared) - set(observed))
        if unobserved:
            msg = (
                f"declared but not observed: {', '.join(unobserved)}; a survey that "
                f"skipped a component would report a posture nobody could account for"
            )
            raise ValidationError(msg)

    def _paired(self) -> tuple[tuple[ComponentSpec, ComponentObservation], ...]:
        """Every component beside what was observed of it.

        Returns:
            The pairs, in declared order.
        """
        found = {observation.identifier: observation for observation in self.observations}
        return tuple((spec, found[spec.identifier]) for spec in self.components)

    def blocking(self) -> tuple[str, ...]:
        """Which components prevent a start.

        Returns:
            Their identifiers, sorted.
        """
        return tuple(
            sorted(spec.identifier for spec, found in self._paired() if blocks(spec, found))
        )

    def withdrawn(self) -> tuple[str, ...]:
        """Which GLOBIN capabilities are not available.

        Returns:
            The union of what every unhappy component withdraws, de-duplicated
            and sorted.

        **This is the phase's headline sentence as data**: *GLOBIN started, and
        these named capabilities are not available*. That is "how it reports a
        partial capability" from ADR-0076, in a form a machine can read.
        """
        lost: set[str] = set()
        for spec, found in self._paired():
            if blocks(spec, found) or degrades(spec, found):
                lost.update(spec.withdraws)
        return tuple(sorted(lost))

    def unmeasured(self) -> tuple[str, ...]:
        """Which components could not be measured at all.

        Returns:
            Their identifiers, sorted, **including the ones whose absence was
            forgiven**.

        Mirrors :meth:`~globin.domain.health.RuntimeHealthSnapshot.unmeasurable`
        deliberately: forgiving an absence in the verdict must never mean hiding
        it in the document.
        """
        return tuple(
            sorted(
                observation.identifier
                for observation in self.observations
                if observation.status is CapabilityStatus.UNKNOWN
            )
        )

    def posture(self) -> EnvironmentCompatibility:
        """The whole-process verdict.

        Returns:
            :attr:`~globin.domain.environment.EnvironmentCompatibility.BLOCKED`
            where anything blocks,
            :attr:`~globin.domain.environment.EnvironmentCompatibility.DEGRADED`
            where anything degrades, and
            :attr:`~globin.domain.environment.EnvironmentCompatibility.READY`
            otherwise.

        Order matters and blocked wins, because a process that must refuse is not
        usefully described as merely worse than intended.
        """
        paired = self._paired()
        if any(blocks(spec, found) for spec, found in paired):
            return EnvironmentCompatibility.BLOCKED
        if any(degrades(spec, found) for spec, found in paired):
            return EnvironmentCompatibility.DEGRADED
        return EnvironmentCompatibility.READY

    def as_record(self) -> dict[str, object]:
        """This report as a publishable record.

        Returns:
            The posture, what is blocked, what is withdrawn, what is unmeasured,
            and one entry per component.
        """
        return {
            "posture": self.posture().value,
            "blocking": list(self.blocking()),
            "withdrawn": list(self.withdrawn()),
            "unmeasured": list(self.unmeasured()),
            "components": [
                {**spec.as_record(), **found.as_record()} for spec, found in self._paired()
            ],
        }


def degradation_outcome(report: DegradationReport | None) -> CheckOutcome:
    """Judge the survey.

    Args:
        report: What was surveyed, or ``None`` where the contract could not be
            read.

    Returns:
        The outcome of the ``runtime.degradation`` check.

    ``None`` is the **only** route to
    :attr:`~globin.domain.bootstrap.CheckStatus.UNMEASURED` here, and it means
    the declaration itself was unreadable — the same treatment an unreadable
    ``runtime-contract.toml`` already gets. A survey that ran has an answer for
    every component, because every factory was called and every one answered.

    A degraded posture is a :attr:`~globin.domain.bootstrap.CheckStatus.WARN`,
    which the exit-code decision ignores. That is the same collapse
    :func:`~globin.domain.bootstrap.capability_outcome` performs and for the same
    reason: starting worse than intended is not a refusal.
    """
    if report is None:
        return CheckOutcome(
            identifier=DEGRADATION_CHECK,
            status=CheckStatus.UNMEASURED,
            summary="the degradation contract could not be read",
            remediation=(
                "restore docs/engineering/degradation-contract.toml; without it GLOBIN "
                "cannot say what it may run without"
            ),
        )
    posture = report.posture()
    if posture is EnvironmentCompatibility.BLOCKED:
        missing = ", ".join(report.blocking())
        return CheckOutcome(
            identifier=DEGRADATION_CHECK,
            status=CheckStatus.FAIL,
            summary=f"required component(s) absent: {missing}",
            remediation=(
                "install or repair the named component; GLOBIN declares it required "
                "and will not start without it"
            ),
        )
    if posture is EnvironmentCompatibility.DEGRADED:
        lost = ", ".join(report.withdrawn())
        return CheckOutcome(
            identifier=DEGRADATION_CHECK,
            status=CheckStatus.WARN,
            summary=f"started without: {lost}",
            remediation=(
                "install the absent optional component to regain the named capabilities; "
                "GLOBIN starts without them"
            ),
        )
    return CheckOutcome(
        identifier=DEGRADATION_CHECK,
        status=CheckStatus.PASS,
        summary="every declared component is present or accounted for",
    )
