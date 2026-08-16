"""The probes that actually read this host, and the one library boundary.

Everything in this module is the outside world: a process table, a filesystem, an
interpreter's thread list, an allocator tracer. The domain describes what those
answers mean and this decides what they are.

**psutil is reached through one factory and nowhere else.**
:func:`system_process_probe` returns a psutil-backed probe when the library is
importable and :class:`UnavailableProcessProbe` when it is not, and no other module
in the package names psutil at all —
``tests/architecture/test_probe_discipline.py`` enforces that on the real import
graph. This is not defensive programming for its own sake. The CI ``quality`` job
installs the development toolchain with plain ``pip`` and never builds ``.venv``,
so psutil is genuinely absent there on every run; a module-level ``import psutil``
would make the smoke test and mypy fail in CI while passing on every developer's
machine, which is the worst shape a dependency can have. ADR-0045 made absence a
recorded state rather than a failure for a *device*; this is the same rule applied
to a *library*.

**Nothing here raises for an expected absence.** A missing library, a counter this
platform does not have and a read the operating system refused are three answers,
and each gets an :class:`~globin.domain.health.Availability` rather than an
exception. Raising would push the classification out to every caller, which is
exactly where it would be got wrong.
"""

import os
import platform
import shutil
import sys
import threading
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from globin.domain.health import (
    REASON_ACCESS_DENIED,
    REASON_COUNTER_UNSUPPORTED,
    REASON_CPU_NOT_SAMPLED,
    REASON_PROCESS_GONE,
    REASON_PSUTIL_ABSENT,
    REASON_TRACING_DISABLED,
    AllocationSite,
    Availability,
    FilesystemReading,
    HostSummary,
    LifecycleSummary,
    LoggingState,
    LoggingSummary,
    MemorySummary,
    PathSummary,
    PlatformSummary,
    ProcessSummary,
    Reading,
    ThreadDescription,
    ThreadSummary,
    absent,
    measured,
)
from globin.domain.watchdog import WatchdogSummary

BYTES: Final[str] = "bytes"
"""The unit label for a byte count."""

NANOSECONDS: Final[str] = "nanoseconds"
"""The unit label for a duration.

CPU times arrive from psutil as floating-point seconds and are converted here.
``docs/TIME_POLICY.md`` requires an integer nanosecond count at every GLOBIN
boundary, and converting at the edge means no float reaches the domain.
"""

COUNT: Final[str] = "count"
"""The unit label for a plain quantity."""

MAIN_THREAD_NAME: Final[str] = "MainThread"
"""What CPython names the thread the interpreter started on."""

SANITISED: Final[str] = "<unnamed>"
"""What a thread with an unusable name is called instead.

A thread name is set by whoever created the thread, and a dependency is free to put
anything in one. Names are therefore bounded and stripped of control characters
before they are published, for the same reason a bundle member name is.
"""

MAXIMUM_THREAD_NAME: Final[int] = 64
"""How long a published thread name may be."""


def _sanitised_name(name: str) -> str:
    """Bound a thread name and strip anything that is not printable.

    Args:
        name: The name as the interpreter reports it.

    Returns:
        A safe, bounded name.
    """
    cleaned = "".join(character for character in name if character.isprintable())
    cleaned = cleaned.strip()
    if not cleaned:
        return SANITISED
    return cleaned[:MAXIMUM_THREAD_NAME]


@dataclass(frozen=True, slots=True)
class UnavailableProcessProbe:
    """A process probe for a host that cannot answer, which records why.

    Args:
        reason: The declared code explaining the absence.
        availability: Which kind of absence it is.

    Returns readings rather than raising, so a snapshot taken where psutil is
    absent is still a snapshot: every other check ran, and the four process fields
    say plainly that nothing could read them.
    """

    reason: str = REASON_PSUTIL_ABSENT
    availability: Availability = Availability.UNAVAILABLE

    def summary(self) -> ProcessSummary:
        """Report the process identity and nothing else.

        Returns:
            A summary whose every counter is an absence.

        The process identifier is still real. ``os.getpid`` needs no library and
        cannot fail, and a snapshot that withheld it because a *different* reader
        was missing would be discarding a fact it holds.
        """
        return ProcessSummary(
            pid=os.getpid(),
            resident_bytes=absent(self.availability, self.reason, BYTES),
            virtual_bytes=absent(self.availability, self.reason, BYTES),
            cpu_user=absent(self.availability, self.reason, NANOSECONDS),
            cpu_system=absent(self.availability, self.reason, NANOSECONDS),
            threads=absent(self.availability, self.reason, COUNT),
            handles=absent(self.availability, self.reason, COUNT),
        )


@dataclass(frozen=True, slots=True)
class PsutilProcessProbe:
    """A process probe backed by psutil.

    Args:
        module: The psutil module, injected so a test can substitute a double
            without installing anything and without patching an import.

    **Every counter is read inside one ``oneshot()`` block.** psutil documents that
    as a caching context in which several fields are satisfied from one read of the
    operating system's process table. The performance is a side benefit; the reason
    it is required here is correctness. Read field by field, a resident set from one
    instant would sit beside a thread count from another, and the result would be a
    description of no single moment.
    """

    module: Any

    def summary(self) -> ProcessSummary:
        """Read every counter psutil offers for this process on this platform.

        Returns:
            The summary, with an availability per field.

        Three psutil failures are classified rather than propagated:
        ``AccessDenied`` becomes :attr:`~globin.domain.health.Availability.DENIED`,
        ``NoSuchProcess`` and ``ZombieProcess`` become
        :attr:`~globin.domain.health.Availability.UNAVAILABLE` with a reason saying
        the process went away, and an ``AttributeError`` from a counter this
        platform does not expose becomes
        :attr:`~globin.domain.health.Availability.UNSUPPORTED`.

        ``num_handles`` is the platform-specific one: it exists on Windows and not
        elsewhere, and asking for it on another platform raises ``AttributeError``
        rather than returning zero. Reporting ``0`` there would be inventing a
        measurement, which is the failure this whole module is shaped to avoid.
        """
        pid = os.getpid()
        try:
            process = self.module.Process(pid)
            with process.oneshot():
                memory = process.memory_info()
                times = process.cpu_times()
                threads = process.num_threads()
                handles = self._handles(process)
        except self.module.AccessDenied:
            return UnavailableProcessProbe(REASON_ACCESS_DENIED, Availability.DENIED).summary()
        except (self.module.NoSuchProcess, self.module.ZombieProcess):
            return UnavailableProcessProbe(REASON_PROCESS_GONE, Availability.UNAVAILABLE).summary()
        except OSError:
            return UnavailableProcessProbe(REASON_ACCESS_DENIED, Availability.DENIED).summary()

        return ProcessSummary(
            pid=pid,
            resident_bytes=measured(int(memory.rss), BYTES),
            virtual_bytes=self._optional(memory, "vms", BYTES),
            cpu_user=measured(_seconds_to_nanoseconds(times.user), NANOSECONDS),
            cpu_system=measured(_seconds_to_nanoseconds(times.system), NANOSECONDS),
            threads=measured(int(threads), COUNT),
            handles=handles,
        )

    def _handles(self, process: Any) -> Reading:
        """Read the Windows handle count, or say why there is none.

        Args:
            process: The psutil process object.

        Returns:
            The reading.
        """
        reader = getattr(process, "num_handles", None)
        if reader is None:
            return absent(Availability.UNSUPPORTED, REASON_COUNTER_UNSUPPORTED, COUNT)
        try:
            return measured(int(reader()), COUNT)
        except self.module.AccessDenied:
            return absent(Availability.DENIED, REASON_ACCESS_DENIED, COUNT)
        except (AttributeError, NotImplementedError, OSError):
            return absent(Availability.UNSUPPORTED, REASON_COUNTER_UNSUPPORTED, COUNT)

    @staticmethod
    def _optional(record: Any, name: str, unit: str) -> Reading:
        """Read a named field where the platform provides one.

        Args:
            record: The psutil named tuple.
            name: The field.
            unit: What it counts.

        Returns:
            The reading.
        """
        value = getattr(record, name, None)
        if value is None:
            return absent(Availability.UNSUPPORTED, REASON_COUNTER_UNSUPPORTED, unit)
        return measured(int(value), unit)


def _seconds_to_nanoseconds(seconds: float) -> int:
    """Convert psutil's floating-point seconds to whole nanoseconds.

    Args:
        seconds: The CPU time.

    Returns:
        The same duration in nanoseconds, truncated.

    Truncated rather than rounded, because a CPU time is a total that only ever
    grows and rounding up would let two successive readings of an idle process
    report that it had used time it had not.
    """
    return int(seconds * 1_000_000_000)


def system_process_probe() -> UnavailableProcessProbe | PsutilProcessProbe:
    """The process probe this environment can support.

    Returns:
        A psutil-backed probe, or one that records the library's absence.

    The import is inside the function deliberately, and it is the only ``import
    psutil`` in the package. At module scope it would run when ``globin.adapters``
    is imported, which the smoke test does on a host where the library is not
    installed. Here the cost is one cached module lookup per snapshot and the
    failure is a recorded state.
    """
    try:
        import psutil
    except ImportError:
        return UnavailableProcessProbe()
    return PsutilProcessProbe(psutil)


@dataclass(frozen=True, slots=True)
class SystemHostProbe:
    """The host's processor, memory and filesystem figures.

    Args:
        usage: How to ask for a filesystem's capacity, injected so a test can make
            one fail without needing a broken disk.
        memory: How to ask for the host's memory, or ``None`` when nothing can.
    """

    usage: Callable[[str], Any] = shutil.disk_usage
    memory: Callable[[], Any] | None = None

    def summary(self, anchors: tuple[str, ...]) -> HostSummary:
        """Read what the machine has.

        Args:
            anchors: The distinct filesystem roots to ask about.

        Returns:
            The summary.

        ``os.process_cpu_count`` rather than ``os.cpu_count``: the first reports how
        many processors this process may actually use, which is what a resource
        question is about, and the two differ wherever an affinity mask or a
        container limit is in force. The second is the fallback for an interpreter
        that has no such call.
        """
        logical = getattr(os, "process_cpu_count", os.cpu_count)()
        return HostSummary(
            logical_cpus=(
                measured(int(logical), COUNT)
                if logical
                else absent(Availability.UNSUPPORTED, REASON_COUNTER_UNSUPPORTED, COUNT)
            ),
            physical_cpus=self._physical(),
            total_memory_bytes=self._memory("total"),
            available_memory_bytes=self._memory("available"),
            filesystems=tuple(self._filesystem(anchor) for anchor in sorted(set(anchors))),
        )

    def _filesystem(self, anchor: str) -> FilesystemReading:
        """Read one filesystem's capacity.

        Args:
            anchor: The filesystem root.

        Returns:
            The reading, with both figures absent when the query failed.
        """
        try:
            usage = self.usage(anchor)
        except OSError:
            return FilesystemReading(
                anchor=anchor,
                total_bytes=absent(Availability.UNAVAILABLE, REASON_ACCESS_DENIED, BYTES),
                free_bytes=absent(Availability.UNAVAILABLE, REASON_ACCESS_DENIED, BYTES),
            )
        return FilesystemReading(
            anchor=anchor,
            total_bytes=measured(int(usage.total), BYTES),
            free_bytes=measured(int(usage.free), BYTES),
        )

    def _physical(self) -> Reading:
        """Read the physical core count where anything can.

        Returns:
            The reading.
        """
        source = self.memory
        if source is None:
            return absent(Availability.UNAVAILABLE, REASON_PSUTIL_ABSENT, COUNT)
        return absent(Availability.UNSUPPORTED, REASON_COUNTER_UNSUPPORTED, COUNT)

    def _memory(self, field_name: str) -> Reading:
        """Read one host memory figure.

        Args:
            field_name: ``total`` or ``available``.

        Returns:
            The reading.
        """
        source = self.memory
        if source is None:
            return absent(Availability.UNAVAILABLE, REASON_PSUTIL_ABSENT, BYTES)
        try:
            record = source()
        except OSError:
            return absent(Availability.UNAVAILABLE, REASON_ACCESS_DENIED, BYTES)
        value = getattr(record, field_name, None)
        if value is None:
            return absent(Availability.UNSUPPORTED, REASON_COUNTER_UNSUPPORTED, BYTES)
        return measured(int(value), BYTES)


def system_host_probe() -> SystemHostProbe:
    """The host probe this environment can support.

    Returns:
        A probe reading host memory through psutil where it is installed, and
        recording the absence where it is not.

    Disk figures never depend on psutil: :func:`shutil.disk_usage` is in the
    standard library, so a host with no psutil still reports every filesystem. That
    split is why the disk check is a mandatory one and the memory check tolerates
    being unmeasurable.
    """
    try:
        import psutil
    except ImportError:
        return SystemHostProbe()
    return SystemHostProbe(memory=psutil.virtual_memory)


@dataclass(frozen=True, slots=True)
class SystemThreadProbe:
    """The interpreter's live thread inventory.

    Args:
        enumerate_threads: How to list them, injected for tests.
    """

    enumerate_threads: Callable[[], list[threading.Thread]] = threading.enumerate

    def summary(self) -> ThreadSummary:
        """Take the inventory.

        Returns:
            The summary, ordered by name and then by identity so that two readings
            of an unchanged process serialise identically.

        ``threading.enumerate`` already excludes threads that have terminated and
        those that were never started, so nothing here filters for liveness — the
        ``alive`` field records what each thread reported at the moment it was
        asked, which can differ from the enumeration for a thread finishing during
        the walk.
        """
        described = [self._describe(thread) for thread in self.enumerate_threads()]
        described.sort(key=lambda item: (item.name, item.identifier or 0))
        return ThreadSummary(count=len(described), threads=tuple(described))

    @staticmethod
    def _describe(thread: threading.Thread) -> ThreadDescription:
        """Describe one thread without exposing what it is doing.

        Args:
            thread: The thread.

        Returns:
            The description.
        """
        return ThreadDescription(
            name=_sanitised_name(thread.name),
            identifier=thread.ident,
            native_identifier=thread.native_id,
            alive=thread.is_alive(),
            daemon=thread.daemon,
            main=thread.name == MAIN_THREAD_NAME,
        )


@dataclass(slots=True)
class TracemallocProbe:
    """The interpreter's allocator tracer.

    Args:
        tracer: The :mod:`tracemalloc` module, injected for tests.
        started_here: Whether this probe was the one that turned tracing on, so
            that :meth:`stop` never stops a tracer somebody else started.

    **The last field is a real hazard rather than bookkeeping.** ``tracemalloc`` is
    process-global state, and a probe that called ``stop()`` unconditionally would
    silently disable tracing an operator had enabled for their own reasons the
    moment a health snapshot was taken.
    """

    tracer: Any = tracemalloc
    started_here: bool = False

    def start(self, frame_depth: int) -> None:
        """Begin tracing, if it is not already running.

        Args:
            frame_depth: How many frames each traceback retains.
        """
        if self.tracer.is_tracing():
            return
        self.tracer.start(frame_depth)
        self.started_here = True

    def stop(self) -> None:
        """End tracing, but only if this probe started it."""
        if self.started_here and self.tracer.is_tracing():
            self.tracer.stop()
            self.started_here = False

    def summary(self, top: int) -> MemorySummary:
        """Read the tracer.

        Args:
            top: How many allocation sites to report, at most.

        Returns:
            The summary, with ``tracing`` false and every figure absent when the
            tracer is not running.

        Not running is the default and is not a fault, which is why the reason is
        :data:`~globin.domain.health.REASON_TRACING_DISABLED` rather than anything
        that sounds like a problem.
        """
        if not self.tracer.is_tracing():
            return MemorySummary(
                tracing=False,
                frame_depth=absent(Availability.UNAVAILABLE, REASON_TRACING_DISABLED, COUNT),
                current_bytes=absent(Availability.UNAVAILABLE, REASON_TRACING_DISABLED, BYTES),
                peak_bytes=absent(Availability.UNAVAILABLE, REASON_TRACING_DISABLED, BYTES),
                overhead_bytes=absent(Availability.UNAVAILABLE, REASON_TRACING_DISABLED, BYTES),
            )
        current, peak = self.tracer.get_traced_memory()
        return MemorySummary(
            tracing=True,
            frame_depth=measured(int(self.tracer.get_traceback_limit()), COUNT),
            current_bytes=measured(int(current), BYTES),
            peak_bytes=measured(int(peak), BYTES),
            overhead_bytes=measured(int(self.tracer.get_tracemalloc_memory()), BYTES),
            top=self._top(top),
        )

    def _top(self, limit: int) -> tuple[AllocationSite, ...]:
        """The largest allocation sites, bounded and sanitised.

        Args:
            limit: How many to report.

        Returns:
            The sites, largest first and then by location so that two equal sizes
            do not swap places between runs.

        **Locations are made relative before they are published.** A traceback
        names absolute paths, and on this host every one of them begins with a user
        profile directory — which names a person. What a reader needs is which
        *module* is allocating, and that survives the conversion intact.
        """
        snapshot = self.tracer.take_snapshot()
        statistics = snapshot.statistics("lineno")[: max(limit, 0)]
        sites = [
            AllocationSite(
                location=relative_location(str(statistic.traceback[0].filename))
                + f":{statistic.traceback[0].lineno}",
                size_bytes=int(statistic.size),
                count=int(statistic.count),
            )
            for statistic in statistics
        ]
        sites.sort(key=lambda site: (-site.size_bytes, site.location))
        return tuple(sites)


def _watchdog_document(watchdog: WatchdogSummary | None) -> dict[str, object] | None:
    """The watchdog's summary, as the snapshot carries it.

    Args:
        watchdog: What the watchdog said about itself, or ``None`` when this
            process has none.

    Returns:
        The mapping, or ``None``.

    **Counts and names only.** This document travels into a support bundle, which
    is why the stall evidence — paths, functions, line numbers — is not here. That
    stays in ``state/watchdog.json``, which is not a bundle candidate.
    """
    if watchdog is None:
        return None
    silent = watchdog.quietest_silent
    return {
        "enabled": watchdog.enabled,
        "running": watchdog.running,
        "state": str(watchdog.state),
        "monitored": watchdog.monitored,
        "required": watchdog.required,
        "suspects": list(watchdog.suspects),
        "quietest": watchdog.quietest,
        "quietest_silent_nanoseconds": None if silent is None else silent.nanoseconds,
        "incident_id": watchdog.incident_id,
        "escalated": watchdog.escalated,
    }


def relative_location(filename: str) -> str:
    """Reduce an absolute source path to something that names no person.

    Public since Phase 025, which is when it acquired a second caller.
    ``globin.adapters.watchdog`` reduces stack-frame filenames through it for
    exactly the reason the allocation sites below do — a traceback names files, and
    a file outside the tree names the account holder. One reduction shared by both
    is what keeps them from disagreeing about what is safe to publish.

    Args:
        filename: The path a traceback recorded.

    Returns:
        A path relative to the package or the standard library, or the bare
        filename when it belongs to neither.

    Three cases, tried in order. A path under GLOBIN's own package becomes
    ``globin/...``; one under the standard library becomes ``stdlib/...``; anything
    else is reduced to its final component, because a path that could not be
    attributed is a path whose directories are somebody's private business.
    """
    candidate = Path(filename)
    for anchor, label in ((Path(__file__).resolve().parents[1], "globin"), _stdlib()):
        try:
            relative = candidate.resolve().relative_to(anchor)
        except (ValueError, OSError):
            continue
        return f"{label}/{relative.as_posix()}"
    return candidate.name


def _stdlib() -> tuple[Path, str]:
    """Where the standard library lives on this interpreter.

    Returns:
        The path and the label to publish it under.
    """
    return Path(sys.prefix) / "Lib", "stdlib"


@dataclass(frozen=True, slots=True)
class SystemPlatformProbe:
    """What is running this, in the terms the runtime contract uses."""

    def summary(self) -> PlatformSummary:
        """Read the interpreter and operating-system facts.

        Returns:
            The summary.

        **``platform.release()`` and not ``platform.uname()``.** The second carries
        the node name, which is the machine's hostname and therefore an identifier
        an operator did not agree to publish when they generated a support bundle.
        Reading the narrower call means the wider value never enters the process.
        """
        return PlatformSummary(
            implementation=platform.python_implementation(),
            python_version=platform.python_version(),
            architecture=platform.machine(),
            system=platform.system(),
            release=platform.release(),
        )


@dataclass(frozen=True, slots=True)
class DiagnosticsStateProbe:
    """What the Phase 023 diagnostics subsystem will say about itself.

    Args:
        state: Where the subsystem is in its lifecycle.
        minimum_severity: The threshold below which records are discarded.
        destination: Where the log is written, as a runtime-relative label.
        rotation_max_bytes: The size at which the file rotates.
        rotation_backup_count: How many rotated files are kept.
        last_fault: A declared code for the last fault, empty when there was none.

    A plain record rather than a reader that reaches into
    :class:`~globin.adapters.diagnostics.RuntimeDiagnostics`. The composition root
    knows what it built and hands the answer over; a probe that inspected private
    attributes would break on the first refactor of the thing it reports on.
    """

    state: LoggingState = LoggingState.NOT_CONFIGURED
    minimum_severity: str = ""
    destination: str = ""
    rotation_max_bytes: int = 0
    rotation_backup_count: int = 0
    last_fault: str = ""

    def summary(self) -> LoggingSummary:
        """Report the subsystem's state.

        Returns:
            The summary.
        """
        configured = self.state is not LoggingState.NOT_CONFIGURED
        return LoggingSummary(
            state=self.state,
            minimum_severity=self.minimum_severity,
            destination=self.destination,
            rotation_max_bytes=(
                measured(self.rotation_max_bytes, BYTES)
                if configured
                else absent(Availability.UNAVAILABLE, REASON_TRACING_DISABLED, BYTES)
            ),
            rotation_backup_count=(
                measured(self.rotation_backup_count, COUNT)
                if configured
                else absent(Availability.UNAVAILABLE, REASON_TRACING_DISABLED, COUNT)
            ),
            last_fault=self.last_fault,
        )


def cpu_percent_reading() -> Reading:
    """The instantaneous CPU percentage a one-shot snapshot cannot honestly give.

    Returns:
        An absence carrying :data:`~globin.domain.health.REASON_CPU_NOT_SAMPLED`.

    A function rather than a constant so that the reason travels with the value
    wherever it is used. psutil documents that the first ``cpu_percent`` call on a
    process returns a meaningless ``0.0``: a percentage is a ratio over an
    interval, and the first call has no earlier reading to form one with. A command
    that takes one measurement and exits has no interval, so there is no number to
    report — and reporting ``0.0`` would say the process is idle, which is a
    conclusion nobody drew.
    """
    return absent(Availability.UNAVAILABLE, REASON_CPU_NOT_SAMPLED, COUNT)


@dataclass(frozen=True, slots=True)
class FilesystemTreeProbe:
    """Whether the mutable runtime tree is in the shape the process needs.

    Args:
        root: The resolved runtime root.
        layout: What areas are declared.

    **The boundary check resolves symbolic links before comparing.** On Windows a
    directory junction points somewhere else while looking entirely ordinary in a
    listing, so a comparison of the declared string against the root would pass
    while the process wrote its operational state onto a different volume.
    ``Path.resolve`` follows the link and ``is_relative_to`` then answers about
    where the writes actually land.
    """

    root: Path
    layout: Any

    def summary(self) -> PathSummary:
        """Check every declared area.

        Returns:
            The summary, one row per area.
        """
        try:
            anchor = self.root.resolve()
        except (OSError, ValueError):
            return PathSummary(root_present=False)
        rows = tuple(
            self._area(anchor, str(area), self.root / self.layout.segment_for(area))
            for area in self.layout.areas()
        )
        return PathSummary(root_present=anchor.is_dir(), areas=rows)

    @staticmethod
    def _area(anchor: Path, name: str, path: Path) -> tuple[str, bool, bool, bool, bool]:
        """Describe one area.

        Args:
            anchor: The resolved runtime root.
            name: The area's name.
            path: Where it should be.

        Returns:
            Name, present, is a directory, writable, inside the root.

        **``ValueError`` is caught beside ``OSError``, and the difference between
        interpreter versions is why.** A path carrying an embedded NUL raises
        ``ValueError`` from ``pathlib`` on CPython 3.12 and is handled without
        raising at all on 3.14 — so a probe catching only ``OSError`` reports
        correctly on one supported interpreter and crashes on another. This is a
        diagnostic: it reports what it could not determine rather than raising,
        whichever version it happens to be running under.

        Writability is tested with ``os.access`` rather than by creating a file.
        A probe that wrote a marker into every area on every snapshot would be a
        diagnostic that changes the thing it measures, and on a full disk it would
        fail for the reason it was trying to report.
        """
        try:
            present = path.exists()
            directory = path.is_dir()
            writable = directory and os.access(path, os.W_OK)
            inside = path.resolve().is_relative_to(anchor)
        except (OSError, ValueError):
            return (name, False, False, False, False)
        return (name, present, directory, writable, inside)


@dataclass(frozen=True, slots=True)
class StateLifecycleProbe:
    """What is known about this run and the one before it.

    Args:
        store: Where small state documents are read from.
        lock: The single-instance lock, probed rather than inspected.
        area: Which runtime area the documents live in.
        lifecycle_file: The lifecycle record's filename.
        instance_file: The instance record's filename.
    """

    store: Any
    lock: Any
    area: Any
    lifecycle_file: str
    instance_file: str

    def summary(self) -> LifecycleSummary:
        """Read the records and probe the lock.

        Returns:
            The summary.

        **Probing acquires and releases.** ADR-0059 is explicit that a lock file's
        existence proves only that GLOBIN once ran, so a check that looked for the
        file would report a crashed predecessor as a live instance — and a check
        that *held* the lock would make a read-only diagnostic refuse to run beside
        a running GLOBIN, which is the trap ADR-0057 already declined for `doctor`.
        """
        problem = self.lock.probe()
        instance = self._document(self.instance_file)
        lifecycle = self._document(self.lifecycle_file)
        status = str(lifecycle.get("status", "")) if lifecycle else ""
        ended = lifecycle.get("finished_at") if lifecycle else None
        return LifecycleSummary(
            status=status,
            instance_id=str(instance.get("instance_id", "")) if instance else "",
            lock_held=problem == "",
            lock_problem=problem,
            previous_ended_cleanly=None if lifecycle is None else ended is not None,
        )

    def _document(self, name: str) -> dict[str, object] | None:
        """Read one state document, treating a corrupt one as absent.

        Args:
            name: The filename.

        Returns:
            The document, or ``None``.

        A corrupt record is reported as absent rather than raised, because this is
        a diagnostic: a run whose predecessor left a truncated file is exactly the
        situation somebody is taking a snapshot to understand, and refusing to
        produce one would withhold the other seventeen answers.
        """
        try:
            document = self.store.read(self.area, name)
        except (OSError, ValueError):
            return None
        if document is None:
            return None
        return dict(document)


SNAPSHOT_SCHEMA: Final[str] = "globin.health.snapshot"
"""The schema name the snapshot document announces."""


def _reading(reading: Reading) -> dict[str, object]:
    """One reading as a document.

    Args:
        reading: The reading.

    Returns:
        The document.

    The availability is always present and the value only when there is one, so a
    consumer cannot read a missing key as a zero. That asymmetry is the whole
    point of the type surviving into the serialised form.
    """
    document: dict[str, object] = {"availability": str(reading.availability), "unit": reading.unit}
    if reading.value is not None:
        document["value"] = reading.value
    if reading.reason:
        document["reason"] = reading.reason
    return document


def snapshot_document(snapshot: object) -> dict[str, object]:
    """A health snapshot as a canonical, machine-readable document.

    Args:
        snapshot: The :class:`~globin.domain.health.RuntimeHealthSnapshot`.

    Returns:
        A document of plain types, ready for the canonical JSON renderer.

    Every container is built here rather than by reflection over the dataclasses.
    A generic serialiser would publish whatever field somebody added next, which
    is precisely how a diagnostic acquires a field nobody decided to publish —
    and this document travels into a support bundle.
    """
    from globin.domain.health import RuntimeHealthSnapshot

    if not isinstance(snapshot, RuntimeHealthSnapshot):  # pragma: no cover - defensive
        msg = "snapshot_document takes a RuntimeHealthSnapshot"
        raise TypeError(msg)
    return {
        "schema": SNAPSHOT_SCHEMA,
        "schema_version": snapshot.schema_version,
        "evidence_version": snapshot.evidence_version,
        "generated_at": str(snapshot.generated_at),
        "generated_at_epoch_millis": snapshot.generated_at.epoch_millis,
        "identity": {
            "correlation_id": snapshot.correlation_id,
            "run_id": snapshot.run_id,
            "version": snapshot.version,
            "profile": snapshot.profile,
            "config_fingerprint": snapshot.config_fingerprint,
            "context_fingerprint": snapshot.context_fingerprint,
        },
        "uptime_nanoseconds": snapshot.uptime.nanoseconds,
        "platform": {
            "implementation": snapshot.platform.implementation,
            "python_version": snapshot.platform.python_version,
            "architecture": snapshot.platform.architecture,
            "system": snapshot.platform.system,
            "release": snapshot.platform.release,
        },
        "process": {
            "pid": snapshot.process.pid,
            "resident_bytes": _reading(snapshot.process.resident_bytes),
            "virtual_bytes": _reading(snapshot.process.virtual_bytes),
            "cpu_user": _reading(snapshot.process.cpu_user),
            "cpu_system": _reading(snapshot.process.cpu_system),
            "cpu_percent": _reading(cpu_percent_reading()),
            "threads": _reading(snapshot.process.threads),
            "handles": _reading(snapshot.process.handles),
        },
        "host": {
            "logical_cpus": _reading(snapshot.host.logical_cpus),
            "physical_cpus": _reading(snapshot.host.physical_cpus),
            "total_memory_bytes": _reading(snapshot.host.total_memory_bytes),
            "available_memory_bytes": _reading(snapshot.host.available_memory_bytes),
            "filesystems": [
                {
                    "anchor": entry.anchor,
                    "total_bytes": _reading(entry.total_bytes),
                    "free_bytes": _reading(entry.free_bytes),
                }
                for entry in snapshot.host.filesystems
            ],
        },
        "paths": {
            "root_present": snapshot.paths.root_present,
            "areas": [
                {
                    "area": name,
                    "present": present,
                    "directory": directory,
                    "writable": writable,
                    "inside_root": inside,
                }
                for name, present, directory, writable, inside in snapshot.paths.areas
            ],
        },
        "lifecycle": {
            "status": snapshot.lifecycle.status,
            "instance_id": snapshot.lifecycle.instance_id,
            "lock_held": snapshot.lifecycle.lock_held,
            "lock_problem": snapshot.lifecycle.lock_problem,
            "previous_ended_cleanly": snapshot.lifecycle.previous_ended_cleanly,
        },
        "logging": {
            "state": str(snapshot.logging.state),
            "minimum_severity": snapshot.logging.minimum_severity,
            "destination": snapshot.logging.destination,
            "rotation_max_bytes": _reading(snapshot.logging.rotation_max_bytes),
            "rotation_backup_count": _reading(snapshot.logging.rotation_backup_count),
            "last_fault": snapshot.logging.last_fault,
        },
        "threads": {
            "count": snapshot.threads.count,
            "threads": [
                {
                    "name": thread.name,
                    "identifier": thread.identifier,
                    "native_identifier": thread.native_identifier,
                    "alive": thread.alive,
                    "daemon": thread.daemon,
                    "main": thread.main,
                }
                for thread in snapshot.threads.threads
            ],
        },
        "memory": _memory_document(snapshot.memory),
        "watchdog": _watchdog_document(snapshot.watchdog),
        "checks": [
            {
                "id": result.identifier,
                "severity": str(result.severity),
                "summary": result.summary,
                "reason": result.reason,
                "details": {key: _plain(value) for key, value in result.details},
                "took_nanoseconds": result.took.nanoseconds if result.took else None,
                "remediation": result.remediation,
            }
            for result in snapshot.results
        ],
        "state": str(snapshot.state),
        "unmeasurable": list(snapshot.unmeasurable()),
    }


def _plain(value: object) -> object:
    """Reduce a detail value to something the canonical renderer accepts.

    Args:
        value: The detail.

    Returns:
        A string, integer, boolean or list of strings.

    The canonical codec refuses a float anywhere, and a tuple is not a JSON type.
    Reducing here rather than at the codec means the refusal happens where the
    value was produced.
    """
    if isinstance(value, tuple | list):
        return [str(item) for item in value]
    if isinstance(value, bool | int | str) or value is None:
        return value
    return str(value)


def _memory_document(memory: MemorySummary | None) -> dict[str, object] | None:
    """The memory summary as a document, or ``None`` when tracing was not read.

    Args:
        memory: The summary.

    Returns:
        The document.
    """
    if memory is None:
        return None
    return {
        "tracing": memory.tracing,
        "frame_depth": _reading(memory.frame_depth),
        "current_bytes": _reading(memory.current_bytes),
        "peak_bytes": _reading(memory.peak_bytes),
        "overhead_bytes": _reading(memory.overhead_bytes),
        "top": [
            {"location": site.location, "size_bytes": site.size_bytes, "count": site.count}
            for site in memory.top
        ],
    }
