"""The contracts provisioning talks to the outside world through.

Five protocols, and the split between them is the design. Starting a process,
asking what a host has, making a change, holding a claim over a half-built
environment and publishing evidence are five different capabilities, and a single
"provisioner" interface carrying all of them would make every test double
implement four methods it does not care about.

Only :mod:`globin.adapters.provisioning` implements the first three, and it is the
one module in the package permitted to start a process --- asserted by
``tests/architecture/test_process_discipline.py``, which fails if a second one
imports ``subprocess`` and fails again if that one stops.
"""

from typing import Protocol

from globin.domain.bootstrap import RecordedPath
from globin.domain.process import CommandRequest, CommandResult, HostCapability
from globin.domain.provisioning import (
    ProvisioningAction,
    ProvisioningJournal,
    ProvisioningPlan,
    ProvisioningStep,
)
from globin.domain.runtime_state import RuntimeLayout


class ProcessRunner(Protocol):
    """How a child process is started.

    Injected everywhere rather than called directly, for the reason the suite's
    offline guard makes necessary: it patches sockets in one interpreter, and a
    child has its own view of the world, so a function that starts one must be
    substitutable to be testable.
    """

    def run(self, request: CommandRequest) -> CommandResult:
        """Start a child, wait for it, and report what it did.

        Args:
            request: What to run, already bounded and shell-free.

        Returns:
            What happened. **A timeout is a result rather than an exception**, so
            a caller handles a hung child and a failed one the same way.
        """
        ...


class CapabilityProbe(Protocol):
    """How the host's tools are discovered."""

    def capabilities(self) -> HostCapability:
        """Ask which of the declared tools this host has.

        Returns:
            One entry per tool. A probe that could not run records
            ``measured=False`` rather than absence.
        """
        ...


class RuntimeTreePreparer(Protocol):
    """How the runtime tree is brought into existence.

    Narrower than :class:`globin.ports.runtime_state.RuntimeTreeSource` on
    purpose. That protocol carries five methods because a lifecycle needs all
    five; the provisioning executor needs one, and asking for the other four
    would make every test double implement things it does not use. The real
    adapter satisfies both.
    """

    def prepare(self, layout: RuntimeLayout) -> tuple[str, ...]:
        """Create the declared areas and report what cannot be used.

        Args:
            layout: The declared tree.

        Returns:
            One sentence per area that cannot be used, empty when the tree is fit
            to write into. **Reported rather than raised**, so a caller that
            discards the result leaves a step claiming success over a tree that
            is not writable.
        """
        ...


class ProvisioningExecutor(Protocol):
    """How one change is actually made."""

    def apply(self, action: ProvisioningAction) -> ProvisioningStep:
        """Perform one action and report what happened.

        Args:
            action: What to do.

        Returns:
            The step. An executor that could not reach the postcondition returns
            :attr:`globin.domain.provisioning.ActionOutcome.FAILED` rather than
            raising, because the caller must record every step either way.
        """
        ...


class EnvironmentClaim(Protocol):
    """How a half-built environment is marked as half-built.

    The mechanism that makes a false ``READY`` unreachable rather than unlikely.
    The claim is written **before** the first mutation and released **only** once
    every step has completed, so a process ended between the two leaves it behind
    --- and the next ``bootstrap check`` sees it.
    """

    def claim(self, plan: ProvisioningPlan) -> None:
        """Record that a plan is being applied.

        Args:
            plan: What is about to be attempted.
        """
        ...

    def release(self) -> None:
        """Record that the plan finished.

        Idempotent: releasing a claim that was never made is not an error, so a
        caller does not have to track whether it got as far as making one.
        """
        ...

    def outstanding(self) -> ProvisioningPlan | None:
        """What a previous run left unfinished.

        Returns:
            The plan it was applying, or ``None`` when nothing is outstanding.
        """
        ...


class ProvisioningRecord(Protocol):
    """How a run's evidence is published."""

    def publish(self, journal: ProvisioningJournal) -> RecordedPath:
        """Write the manifest for one provisioning run.

        Args:
            journal: What was done.

        Returns:
            Where it was written, recorded rather than spelled.
        """
        ...
