"""The ports a health snapshot is assembled through.

Five probes rather than one, and the split is by *what can fail independently*
rather than by subject matter. A host that cannot report its own memory can still
report its disks; a process whose handle count is refused can still report its
resident set. One wide probe would make each of those failures take the others
down with it, and the collector's whole job is that they should not.

**Every probe returns domain types, never library types.** A ``psutil.Process`` or
a ``threading.Thread`` crossing this boundary would put the outside world's
vocabulary into the application layer, and would make substituting a probe in a
test mean constructing the library's objects. What crosses is
:class:`~globin.domain.health.Reading` and the summaries beside it.

**No probe raises for an expected absence.** A missing library, an unsupported
counter and a refused read are all *answers*, and each has a
:class:`~globin.domain.health.Availability` to say which. An implementation that
raised would push the classification into every caller, which is where it would be
got wrong.
"""

from typing import Protocol

from globin.domain.health import (
    HostSummary,
    LifecycleSummary,
    LoggingSummary,
    MemorySummary,
    PathSummary,
    PlatformSummary,
    ProcessSummary,
    ThreadSummary,
)


class ProcessProbe(Protocol):
    """What this process is consuming."""

    def summary(self) -> ProcessSummary:
        """Read every process counter available on this host.

        Returns:
            The summary, with an availability per field.

        Implementations should read the whole set in one pass over the operating
        system's process table where the platform offers that. Reading it field by
        field is not merely slower: the fields would then describe the process at
        several different moments, and a resident set from one instant beside a
        thread count from another is not a snapshot of anything.
        """
        ...


class HostResourceProbe(Protocol):
    """What the machine has, and what is left of it."""

    def summary(self, anchors: tuple[str, ...]) -> HostSummary:
        """Read the host's processor, memory and filesystem figures.

        Args:
            anchors: The distinct filesystem roots to ask about, already
                deduplicated by the caller.

        Returns:
            The summary.
        """
        ...


class ThreadProbe(Protocol):
    """Which threads are alive in this interpreter."""

    def summary(self) -> ThreadSummary:
        """Take the thread inventory.

        Returns:
            The summary, ordered so two readings of one process serialise the
            same way.

        Never a stack. See
        :class:`~globin.domain.health.ThreadDescription` for why.
        """
        ...


class MemoryProbe(Protocol):
    """What the interpreter's allocator tracer knows, if it is running."""

    def summary(self, top: int) -> MemorySummary:
        """Read the tracer.

        Args:
            top: How many allocation sites to report, at most.

        Returns:
            The summary, with ``tracing`` false and no figures when the tracer is
            not running — which is the default state and is not a fault.
        """
        ...

    def start(self, frame_depth: int) -> None:
        """Begin tracing.

        Args:
            frame_depth: How many frames each traceback retains.

        Explicit because tracing costs the whole process on every allocation. A
        probe that started the tracer in order to read it would turn a diagnostic
        into a profiler, and would do it silently.
        """
        ...

    def stop(self) -> None:
        """End tracing and release what it was holding."""
        ...


class PlatformProbe(Protocol):
    """What is running this."""

    def summary(self) -> PlatformSummary:
        """Read the interpreter and operating-system facts.

        Returns:
            The summary, carrying nothing that identifies a person or a machine.
        """
        ...


class RuntimeTreeProbe(Protocol):
    """Whether the mutable runtime tree is in the shape the process needs."""

    def summary(self) -> PathSummary:
        """Check every declared area for presence, kind, writability and boundary.

        Returns:
            The summary.

        The boundary question is the one that cannot be skipped: a directory that
        resolves outside the approved root is a directory GLOBIN would write
        operational state into somewhere nobody declared, and on Windows a
        junction makes that possible without anything looking unusual.
        """
        ...


class LifecycleProbe(Protocol):
    """What is known about this run and the one before it."""

    def summary(self) -> LifecycleSummary:
        """Read the lifecycle records and probe the single-instance lock.

        Returns:
            The summary.

        Probing means *acquiring and releasing*, never looking for a file.
        ADR-0059 is explicit that a lock file's existence proves only that GLOBIN
        once ran, so a check that consulted it would report a crashed predecessor
        as a running instance.
        """
        ...


class LoggingStateProbe(Protocol):
    """What the diagnostics subsystem will say about itself."""

    def summary(self) -> LoggingSummary:
        """Read the subsystem's own state.

        Returns:
            The summary.

        A port rather than a direct read, because the alternative is a health
        check reaching into the adapter's attributes — which breaks on the first
        refactor and reports an implementation detail to somebody who cannot act
        on it.
        """
        ...
