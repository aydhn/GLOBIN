"""The suite: which checks a long-running process must take again, and how often.

Phase 021 built a *registry* — eighteen specifications in
:func:`~globin.domain.bootstrap.checks`, performed in order, reduced to one exit
code. That is everything a command which reports and exits needs, because the
instant its answers describe and the instant it stops are the same one.

A process that keeps running breaks that identity, and this module is what the
break costs. A check is a measurement; a measurement is taken at an instant; and
a start-up gate that passed an hour ago is a claim about an hour ago. The suite
adds the one fact the registry cannot hold —
:class:`~globin.domain.bootstrap.Durability`, which says whether an answer
survives the run — and the one policy that follows from it, which is how often
the answers that do not survive are taken again.

**Nothing here executes a re-take, and that is the deliberate half.** GLOBIN has
no long-running process yet: the phase that starts one honours this policy, and
until then a scheduler would be a mechanism with no caller, tested only against
itself. What is delivered instead is a policy that **cannot be constructed if it
could not be honoured**, which is the treatment
:class:`~globin.domain.observability.RotationPolicy` and
:class:`~globin.domain.watchdog.WatchdogPolicy` already receive.

**The suite is derived from the registry, never restated beside it.** A second
table listing which checks decay would describe checks the registry no longer has
the moment one is renamed, and ``docs/engineering/SOURCE_OF_TRUTH.md`` refuses
exactly that. Every accessor below reads
:func:`~globin.domain.bootstrap.checks`.
"""

from dataclasses import dataclass
from typing import Final

from globin.domain.bootstrap import (
    BootstrapReport,
    CheckSpec,
    CheckStatus,
    Durability,
    ExitCode,
    checks,
    exit_code_for,
)
from globin.errors import ValidationError

MINIMUM_RECHECK_INTERVAL_MILLIS: Final[int] = 1_000
"""The shortest interval a re-take may be scheduled at.

A second. Below it the probes stop being cheap: ``paths.runtime`` asks the
filesystem for free space and ``instance.lock`` attempts an exclusive
acquisition, and doing either hundreds of times a minute costs more than the
staleness it removes. The floor is not a performance guess about one host — it is
the point below which the measurement is measuring the measuring.
"""

MAXIMUM_RECHECK_INTERVAL_MILLIS: Final[int] = 3_600_000
"""The longest interval a re-take may be scheduled at.

An hour. Beyond it the schedule stops being a schedule: a verdict refreshed less
often than that is, for any operational purpose, the start-up verdict with extra
machinery. An operator who wants that switches the re-take off rather than
setting it to a day, and the ceiling is what makes them say so.
"""

DEFAULT_RECHECK_INTERVAL_MILLIS: Final[int] = 60_000
"""How often a perishable check is taken again, by default.

A minute, and it is deliberately far slower than the watchdog's second. The two
answer different questions: the watchdog asks whether a component is still
moving, where a sub-second answer is the entire value, and this asks whether the
host is still fit, where nothing an operator can act on changes that fast. A disk
does not fill in the time it takes to notice it filling.
"""


@dataclass(frozen=True, slots=True)
class RecheckPolicy:
    """How often a perishable check is taken again.

    Args:
        interval_millis: The gap between re-takes, between
            :data:`MINIMUM_RECHECK_INTERVAL_MILLIS` and
            :data:`MAXIMUM_RECHECK_INTERVAL_MILLIS` inclusive.

    Raises:
        ValidationError: If the interval is outside those bounds, or is a
            ``bool``.

    A policy that could not be honoured must not exist, which is why the bounds
    are checked here rather than where a scheduler would read them. The failure an
    operator would otherwise get is a schedule that silently never fires, or one
    that fires so often the process spends its life probing.

    ``bool`` is refused even though Python makes it an ``int``, for the reason
    ``docs/CONFIGURATION_POLICY.md`` gives about the same trap: ``True`` resolving
    to an interval of one millisecond is the kind of accident that looks like it
    worked.
    """

    interval_millis: int

    def __post_init__(self) -> None:
        """Refuse an interval no scheduler could honour."""
        if isinstance(self.interval_millis, bool):
            msg = "the recheck interval is a boolean; it must be a count of milliseconds"
            raise ValidationError(msg)
        low = MINIMUM_RECHECK_INTERVAL_MILLIS
        high = MAXIMUM_RECHECK_INTERVAL_MILLIS
        if not low <= self.interval_millis <= high:
            msg = (
                f"the recheck interval {self.interval_millis} is outside {low}..{high} milliseconds"
            )
            raise ValidationError(msg)

    def applies_to(self, spec: CheckSpec) -> bool:
        """Whether this policy schedules re-takes of one check.

        Args:
            spec: The check to ask about.

        Returns:
            ``True`` when the check's answer decays.

        A stable answer is never re-taken. Re-measuring the interpreter's version
        every minute would burn the schedule on the one class of question whose
        answer is guaranteed not to have moved.
        """
        return spec.durability is Durability.PERISHABLE

    def due(self, elapsed_millis: int) -> bool:
        """Whether a re-take is owed after some time has passed.

        Args:
            elapsed_millis: Milliseconds since the check was last taken. Measured
                by the caller from a monotonic source, because a wall clock can
                move backwards and would then make a re-take permanently overdue
                or permanently not.

        Returns:
            ``True`` once at least :attr:`interval_millis` has elapsed.

        Raises:
            ValidationError: If the elapsed time is negative. Time not having
                passed is a caller's defect rather than a schedule's.
        """
        if elapsed_millis < 0:
            msg = f"elapsed time {elapsed_millis} is negative; a re-take cannot be owed in the past"
            raise ValidationError(msg)
        return elapsed_millis >= self.interval_millis


def default_recheck_policy() -> RecheckPolicy:
    """The declared re-take schedule.

    Returns:
        A :class:`RecheckPolicy` at :data:`DEFAULT_RECHECK_INTERVAL_MILLIS`.

    A function rather than a constant because building one is a call, and a layer
    package may perform none at import — the same reason
    :func:`~globin.domain.bootstrap.checks` is a function.

    **The interval is a constant here rather than a row in the settings
    register.** ``docs/CONFIGURATION_POLICY.md`` asks a proposed setting to have a
    call site in the phase that adds it, and this one has none: nothing runs long
    enough to re-take anything. A setting whose only reader is its own test is the
    speculative field that document exists to keep out.
    """
    return RecheckPolicy(interval_millis=DEFAULT_RECHECK_INTERVAL_MILLIS)


@dataclass(frozen=True, slots=True)
class PreflightSuite:
    """The registered checks, classified, with the schedule their answers imply.

    Args:
        policy: How often the perishable ones are taken again.

    Holds no checks of its own. Every accessor reads
    :func:`~globin.domain.bootstrap.checks`, so a check added, renamed or removed
    there is added, renamed or removed here in the same edit and there is no
    second list to forget.
    """

    policy: RecheckPolicy

    def specifications(self) -> tuple[CheckSpec, ...]:
        """Every registered check, in pipeline order.

        Returns:
            The registry, unchanged.
        """
        return checks()

    def identifiers(self) -> tuple[str, ...]:
        """Every registered check identifier, in pipeline order.

        Returns:
            The identifiers.
        """
        return tuple(spec.identifier for spec in self.specifications())

    def _with_durability(self, durability: Durability) -> tuple[str, ...]:
        """Identifiers of the checks carrying one durability.

        Args:
            durability: Which classification to select.

        Returns:
            The identifiers, in pipeline order.
        """
        return tuple(
            spec.identifier for spec in self.specifications() if spec.durability is durability
        )

    def stable(self) -> tuple[str, ...]:
        """Checks whose answer survives the run.

        Returns:
            The identifiers, in pipeline order.
        """
        return self._with_durability(Durability.STABLE)

    def perishable(self) -> tuple[str, ...]:
        """Checks whose answer was true only when taken.

        Returns:
            The identifiers, in pipeline order.
        """
        return self._with_durability(Durability.PERISHABLE)

    def scheduled(self) -> tuple[str, ...]:
        """Checks this suite's policy would take again.

        Returns:
            The identifiers, in pipeline order.

        Today this is exactly :meth:`perishable`. It is a separate method because
        the two answer different questions — one is a property of the check, the
        other of the policy — and a policy that scheduled a subset would make them
        differ without either definition changing.
        """
        return tuple(
            spec.identifier for spec in self.specifications() if self.policy.applies_to(spec)
        )

    def as_record(self) -> dict[str, object]:
        """This suite as the mapping the evidence carries.

        Returns:
            The interval, and the identifiers in each classification.
        """
        return {
            "interval_millis": self.policy.interval_millis,
            "stable": list(self.stable()),
            "perishable": list(self.perishable()),
            "scheduled": list(self.scheduled()),
        }


def build_suite(policy: RecheckPolicy | None = None) -> PreflightSuite:
    """The declared suite.

    Args:
        policy: The re-take schedule, defaulting to
            :func:`default_recheck_policy`.

    Returns:
        A :class:`PreflightSuite`.
    """
    return PreflightSuite(policy=default_recheck_policy() if policy is None else policy)


@dataclass(frozen=True, slots=True)
class PreflightOutcome:
    """A preflight verdict, and how long it is good for.

    Args:
        report: What the checks concluded.
        suite: The classification and schedule they were judged under.
    """

    report: BootstrapReport
    suite: PreflightSuite

    @property
    def exit_code(self) -> ExitCode:
        """What the process returns.

        **Deliberately the registry's answer rather than a second one.**
        :func:`~globin.domain.bootstrap.exit_code_for` already reduces a report to
        the earliest refusal's declared code, and a suite that computed its own
        would be the second answer for one failure that
        :class:`~globin.domain.bootstrap.CheckSpec` exists to prevent.
        """
        return exit_code_for(self.report)

    @property
    def may_start(self) -> bool:
        """Whether a long-running process may start.

        Delegates to :attr:`~globin.domain.bootstrap.BootstrapReport.ready`, which
        already refuses a report that stopped early as well as one that refused.
        The suite neither weakens nor widens that question; what it adds is
        :meth:`shelf_life_millis`, which says how long the answer stays true.
        """
        return self.report.ready

    def decaying(self) -> tuple[str, ...]:
        """Checks that passed, and whose passing was true only when taken.

        Returns:
            The identifiers, in the order they were performed.

        This is the sentence a start-up gate cannot say and a suite must: these
        answers are not wrong, and they are not durable either.
        """
        scheduled = set(self.suite.scheduled())
        keeping = {CheckStatus.PASS, CheckStatus.WARN}
        return tuple(
            outcome.identifier
            for outcome in self.report.outcomes
            if outcome.identifier in scheduled and outcome.status in keeping
        )

    def shelf_life_millis(self) -> int | None:
        """How long this verdict stays good.

        Returns:
            The re-take interval when anything in the verdict decays, and ``None``
            when nothing does.

        ``None`` is not "for ever" hedged — it is the accurate answer for a report
        built entirely from stable checks, and it is distinguishable from an
        interval precisely so that a caller cannot treat the two the same way.
        """
        if not self.decaying():
            return None
        return self.suite.policy.interval_millis

    def as_record(self) -> dict[str, object]:
        """This outcome as the mapping the evidence carries.

        Returns:
            The verdict, the suite, what decays, and every check that ran.

        The checks are carried here rather than added by whichever caller renders
        them, so that the human report and the machine document describe one run
        — the property :func:`~globin.runtime.cli.render_json` already holds by
        calling the same builder the evidence file uses.
        """
        return {
            "may_start": self.may_start,
            "exit_code": int(self.exit_code),
            "decaying": list(self.decaying()),
            "shelf_life_millis": self.shelf_life_millis(),
            "suite": self.suite.as_record(),
            "checks": [outcome.as_record() for outcome in self.report.outcomes],
        }
