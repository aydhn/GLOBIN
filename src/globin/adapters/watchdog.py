"""The watchdog's I/O: one lock, one thread, one dump and one exit.

Everything the layers above could not touch. ``threading``, ``sys``,
``faulthandler``, ``traceback`` and ``os`` are all I/O-capable in
``docs/architecture/dependency-rules.toml``, so this is the only module in the
subsystem that may name any of them.

**This is the first thread GLOBIN starts.** Nothing under ``src/globin`` called
:class:`threading.Thread` before Phase 025 — the health adapter enumerates threads
the interpreter already has, which is a different thing entirely. Every convention
here is therefore being set rather than followed, and three are written down
because a later author will otherwise have to guess: the thread is **not** a
daemon, it waits on an :class:`threading.Event` rather than sleeping, and it is
disarmed before it is joined.

**The lock protects one increment and nothing else.** A dict store is atomic under
the interpreter's own lock; ``sequence + 1`` is a read-modify-write and is not.
Everything expensive — reading the clock, sorting, building the immutable snapshot
— happens outside it, and no disk, no logging and no callback ever happens inside
it. That is what makes a heartbeat cheap enough to put in a hot loop.
"""

import faulthandler
import os
import sys
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, replace
from types import FrameType
from typing import IO, NoReturn

from globin.adapters.health import relative_location
from globin.application.observability import Logger
from globin.application.watchdog import RuntimeWatchdog
from globin.domain.watchdog import (
    EVENT_WATCHDOG_LOOP_FAILED,
    MAXIMUM_COMPONENT_NAME,
    MAXIMUM_EVIDENCE_BYTES,
    MAXIMUM_EVIDENCE_FRAMES,
    MAXIMUM_EVIDENCE_THREADS,
    ComponentBeat,
    Criticality,
    FrameLine,
    HeartbeatSnapshot,
    StallEvidence,
    ThreadStack,
)
from globin.errors import ValidationError
from globin.ports.clock import MonotonicClock

THREAD_NAME: str = "globin-watchdog"
"""What the watchdog's own thread is called, so a stack dump names it."""

JOIN_SECONDS: float = 5.0
"""How long :meth:`WatchdogThread.stop` waits for the loop to notice.

Bounded rather than indefinite, and reported rather than ignored when it expires.
A join that could block for ever would make a hung watchdog hang the shutdown it
exists to guarantee.
"""

UNNAMED: str = "<unnamed>"
"""What a thread with no usable name is called in a dump."""


@dataclass(slots=True)
class SharedHeartbeatRegistry:
    """The heartbeat table, and the only shared mutable state in the subsystem.

    Args:
        monotonic: The clock a beat is stamped with.
        lock: Guards the increment. Supplied rather than defaulted, because
            constructing one in a class body is work performed at import.
        entries: Component name to its last beat. Supplied for the same reason.

    Satisfies both :class:`~globin.ports.watchdog.Heartbeat` and
    :class:`~globin.ports.watchdog.HeartbeatSource`, and is handed to callers as
    one or the other so that a monitored component cannot read the table and the
    watchdog loop cannot beat on somebody's behalf.
    """

    monotonic: MonotonicClock
    lock: threading.Lock
    entries: dict[str, ComponentBeat]

    def register(self, component: str, criticality: Criticality) -> None:
        """Begin monitoring a component.

        Args:
            component: What it calls itself.
            criticality: Whether its silence may end the process.

        Raises:
            ValidationError: If the name is unusable or already registered.

        **Registration seeds a beat rather than leaving a gap**, so "registered ten
        minutes ago and never beat" is measured by the same subtraction as
        everything else and no caller has a ``None`` timestamp to branch on.
        """
        if component in self.entries:
            msg = f"{component!r} is already monitored, and registering it twice hides one of them"
            raise ValidationError(msg)
        seeded = ComponentBeat(
            name=component,
            criticality=criticality,
            sequence=0,
            at=self.monotonic.reading(),
        )
        with self.lock:
            self.entries[component] = seeded

    def beat(self, component: str) -> None:
        """Report that a component has made progress.

        Args:
            component: Which one.

        Raises:
            ValidationError: If nothing is registered under that name.

        **A mistyped name raises rather than doing nothing.** A silent no-op would
        mean the component an operator believes is monitored is monitored by
        nothing, and the watchdog would report a healthy process for ever. It can
        only be a wiring mistake, and it fires on the first beat rather than under
        load.
        """
        at = self.monotonic.reading()
        with self.lock:
            previous = self.entries.get(component)
            if previous is None:
                msg = f"{component!r} is not monitored, so its progress is not being watched"
                raise ValidationError(msg)
            self.entries[component] = replace(previous, sequence=previous.sequence + 1, at=at)

    def snapshot(self) -> HeartbeatSnapshot:
        """Every monitored component, frozen at one reading.

        Returns:
            An immutable, name-ordered copy.

        **The reading is taken after the lock is released, and the order matters.**
        :meth:`~globin.domain.clock.MonotonicReading.since` refuses to subtract in
        the wrong direction, so a beat landing between the reading and the copy
        would carry a stamp later than the snapshot containing it and raise from
        inside the watchdog loop — intermittently, and only under load. Copying
        first makes that impossible, and :class:`HeartbeatSnapshot` refuses the case
        anyway.
        """
        with self.lock:
            captured = tuple(self.entries.values())
        return HeartbeatSnapshot(
            taken_at=self.monotonic.reading(),
            beats=tuple(sorted(captured, key=lambda beat: beat.name)),
        )


@dataclass(slots=True)
class WatchdogThread:
    """The loop that ticks the watchdog, and its start and stop.

    Args:
        cycle: What to tick.
        wake: Set to end the wait early. Supplied rather than defaulted.
        interval_seconds: How long each wait lasts.
        logger: Where a loop failure is reported.
        spawn: Builds the thread. Injected so a test can observe the arguments
            without starting anything.
        join_seconds: How long :meth:`stop` waits.
        thread: The running thread, once there is one.
    """

    cycle: RuntimeWatchdog
    wake: threading.Event
    interval_seconds: float
    logger: Logger
    spawn: Callable[..., threading.Thread] = threading.Thread
    join_seconds: float = JOIN_SECONDS
    thread: threading.Thread | None = None

    def start(self) -> None:
        """Arm the watchdog and begin looking.

        Starting a started thread does nothing, which is the guard
        ``globin.adapters.diagnostics.RuntimeDiagnostics.start`` uses and for the
        same reason: the caller that owns the process should not have to remember
        whether it already did this.

        **The thread is not a daemon, and that is a correctness decision.** The
        interpreter kills daemon threads at shutdown without unwinding them, and a
        daemon part-way through deciding to end the process during interpreter
        teardown is undefined behaviour. Non-daemon means a forgotten :meth:`stop`
        hangs the test suite loudly rather than being papered over — which is the
        only way "does not depend on daemon shutdown" becomes provable.
        """
        if self.thread is not None:
            return
        self.wake.clear()
        self.cycle.arm()
        self.cycle.running = True
        self.thread = self.spawn(target=self._loop, name=THREAD_NAME, daemon=False)
        self.thread.start()

    def stop(self) -> None:
        """Disarm, wake the loop, and wait a bounded time for it to finish.

        Raises:
            ShutdownIncompleteError: Never directly — a loop that will not stop is
                reported as a critical record and left, because raising here would
                replace a shutdown that is merely untidy with one that failed.

        **Disarming happens before the join, not after.** If the loop never notices
        the event, a disarmed cycle is a harmless one: it can no longer escalate.
        Ordering that before the wait matters more than the wait's bound does.
        """
        thread, self.thread = self.thread, None
        self.cycle.stand_down()
        self.cycle.running = False
        self.wake.set()
        if thread is None:
            return
        thread.join(self.join_seconds)
        if thread.is_alive():
            self.logger.critical(
                EVENT_WATCHDOG_LOOP_FAILED,
                joined=False,
                waited_seconds=self.join_seconds,
            )

    def _loop(self) -> None:
        """Tick until asked to stop, or until a tick cannot complete.

        **A failing tick stops the loop rather than retrying it.** A watchdog whose
        tick raises every interval writes a critical record every interval for ever;
        one that swallows the failure removes the protection with nothing saying so.
        The protection is already gone the moment a tick cannot complete, so this
        says so once, disarms, and returns.
        """
        while not self.wake.wait(self.interval_seconds):
            try:
                self.cycle.tick()
            except Exception as fault:
                self.logger.critical(
                    EVENT_WATCHDOG_LOOP_FAILED, fault=type(fault).__name__, joined=True
                )
                self.cycle.stand_down()
                self.cycle.running = False
                return


@dataclass(frozen=True, slots=True)
class ProcessStackEvidence:
    """Where every thread was parked when a stall was confirmed.

    Args:
        handle: An already-open text file the native dump is written to. Phase
            023's ``FaultFile`` owns it, and reusing it means this collector
            performs no ``open`` and no ``mkdir`` — which is the strongest
            available bound on how long it can block.
        current_frames: Reads the interpreter's live frames. Injected for tests.
        dump: Writes the native all-thread traceback. Injected for tests.
        enumerate_threads: Lists live threads, for their names.

    **No frame is retained and no local is read.**
    :func:`sys._current_frames` hands out live frame objects, and every one of them
    has an ``f_locals`` holding the values a credential-reading function was working
    with — not merely the name of the function reading them.
    :func:`traceback.extract_stack` is used without any capture-locals option, the
    summaries are copied out, and the mapping is dropped in the same call.
    """

    handle: IO[str] | None
    current_frames: Callable[[], dict[int, FrameType]] = sys._current_frames  # noqa: SLF001
    dump: Callable[..., None] = faulthandler.dump_traceback
    enumerate_threads: Callable[[], list[threading.Thread]] = threading.enumerate

    def capture(self, incident_id: str) -> StallEvidence:
        """Gather what can be gathered, and record what could not.

        Args:
            incident_id: What the incident is filed under.

        Returns:
            The evidence, with one sentence per collector that failed.

        Two independent collectors, each contained, because a stall is already a
        failure and the second source is most valuable exactly when the first one
        breaks.
        """
        problems: list[str] = []
        native = self._native(incident_id, problems)
        threads, truncated = self._threads(problems)
        return StallEvidence(
            threads=threads,
            native_dump=native,
            truncated=truncated,
            problems=tuple(problems),
        )

    def _native(self, incident_id: str, problems: list[str]) -> bool:
        """Ask ``faulthandler`` to write its own all-thread traceback.

        Args:
            incident_id: Written as a header line before the dump, because the
                fault file is append-only and shared with the process fault hooks —
                without a marker there is no way to tell which of several dumps
                belongs to which incident.
            problems: Collected failures, appended to.

        Returns:
            Whether it wrote.

        Native because it is written by C, which is exactly why it still works in
        the cases Python-level introspection does not. It cannot be time-bounded
        from this thread, and pretending otherwise with a timer would be building
        the supervisor Phase 263 owns.
        """
        if self.handle is None:
            problems.append("no fault file was open, so no native traceback was written")
            return False
        try:
            self.handle.write(f"--- globin watchdog stall {incident_id} ---\n")
            self.dump(file=self.handle, all_threads=True)
            self.handle.flush()
        except (OSError, ValueError, RuntimeError) as fault:
            problems.append(f"the native traceback failed: {type(fault).__name__}")
            return False
        return True

    def _threads(self, problems: list[str]) -> tuple[tuple[ThreadStack, ...], bool]:
        """Summarise where each thread is parked, bounded and sanitised.

        Args:
            problems: Collected failures, appended to.

        Returns:
            The stacks, and whether any bound was reached.
        """
        try:
            frames = self.current_frames()
        except RuntimeError as fault:
            problems.append(f"the interpreter's frames could not be read: {type(fault).__name__}")
            return (), False
        names = self._names()
        mine = threading.get_ident()
        described: list[ThreadStack] = []
        truncated = False
        spent = 0
        for identifier in sorted(frames):
            if identifier == mine:
                continue
            if len(described) >= MAXIMUM_EVIDENCE_THREADS:
                truncated = True
                break
            stack = self._describe(identifier, frames[identifier], names)
            spent += _weight(stack)
            if spent > MAXIMUM_EVIDENCE_BYTES:
                truncated = True
                break
            described.append(stack)
            truncated = truncated or stack.truncated
        return tuple(described), truncated

    def _names(self) -> dict[int, str]:
        """Thread identifiers to their names.

        Returns:
            The mapping, empty when the inventory could not be read.
        """
        try:
            live = self.enumerate_threads()
        except RuntimeError:
            return {}
        return {
            thread.ident: _sanitised(thread.name) for thread in live if thread.ident is not None
        }

    @staticmethod
    def _describe(identifier: int, frame: FrameType, names: dict[int, str]) -> ThreadStack:
        """One thread's innermost frames.

        Args:
            identifier: Which thread.
            frame: Its current frame.
            names: Identifiers to names.

        Returns:
            The stack, with every filename reduced to a publishable form.

        Innermost rather than outermost: a hang is described by where it is parked,
        not by how it got there. ``extract_stack`` returns outermost-first, so the
        tail is what is kept.
        """
        summary = traceback.extract_stack(frame)
        kept = summary[-MAXIMUM_EVIDENCE_FRAMES:]
        return ThreadStack(
            name=names.get(identifier, UNNAMED),
            identifier=identifier,
            frames=tuple(
                FrameLine(
                    location=relative_location(str(entry.filename)),
                    function=_sanitised(entry.name),
                    line=int(entry.lineno or 0),
                )
                for entry in kept
            ),
            truncated=len(summary) > len(kept),
        )


@dataclass(frozen=True, slots=True)
class ImmediateProcessExit:
    """Ending the process without running anything that could block.

    Args:
        exit_process: What actually ends it. Injected so that no test ever kills
            the runner.

    **``os._exit`` rather than ``sys.exit`` or ``os.abort``, and both alternatives
    are wrong in ways that matter here.** ``sys.exit`` raises ``SystemExit`` in the
    calling thread; raised from a background thread it ends that thread and leaves
    the wedged process running, which is a silent failure of the one mechanism that
    must not fail silently. ``os.abort`` goes through the C runtime and on Windows
    can raise the abort dialog and a crash dump — a modal dialog on an unattended
    host is the hang the watchdog exists to end, reintroduced by the thing ending
    it. ``os._exit`` runs no ``atexit`` handler, unwinds nothing, flushes nothing
    and waits on no lock, which is correct precisely because the reason this path
    was reached is that something is holding one.
    """

    exit_process: Callable[[int], NoReturn] = os._exit

    def terminate(self, code: int) -> None:
        """Stop this process now.

        Args:
            code: The exit status to leave behind.
        """
        self.exit_process(code)


def _sanitised(name: str) -> str:
    """A name reduced to something publishable.

    Args:
        name: What it called itself.

    Returns:
        The printable part, bounded, or a placeholder when nothing is left.
    """
    printable = "".join(character for character in name if character.isprintable())
    return printable[:MAXIMUM_COMPONENT_NAME] or UNNAMED


def _weight(stack: ThreadStack) -> int:
    """Roughly how many bytes one stack will occupy once rendered.

    Args:
        stack: The stack.

    Returns:
        An estimate, deliberately an over-count rather than an under-count.
    """
    return len(stack.name) + sum(
        len(frame.location) + len(frame.function) + 16 for frame in stack.frames
    )


def heartbeats(monotonic: MonotonicClock) -> SharedHeartbeatRegistry:
    """A registry with its lock and its table.

    Args:
        monotonic: The clock a beat is stamped with.

    Returns:
        The registry.

    A function rather than defaults on the dataclass, because ``threading.Lock()``
    and ``{}`` are both calls and a layer package performs no work at import.
    """
    return SharedHeartbeatRegistry(monotonic=monotonic, lock=threading.Lock(), entries={})
