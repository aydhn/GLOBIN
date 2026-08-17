"""Where telemetry meets the machine: a file, a thread, and a published snapshot.

Three things live here and nowhere else, each because it touches something the
inner layers may not: a local exporter that writes NDJSON into the runtime tree,
the thread that drives the pump, and the snapshot writer that publishes a document
atomically.

**The local exporter is the one that makes the state machine reachable.** Every
failure `domain/telemetry_delivery.py` models — a temporary failure, a permanent
one, backpressure — has a real cause here: a full disk, a closed handle, a
directory that vanished. The provider adapters are absent on every CI run, so
without this the whole delivery path would be exercised only by doubles.
"""

import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from globin.application.observability import Logger
from globin.application.telemetry_delivery import TelemetryPump
from globin.domain.clock import MonotonicReading
from globin.domain.telemetry_delivery import ExportOutcome

TELEMETRY_FILE: str = "telemetry.json"
"""The published snapshot, in the runtime tree's state area."""

TELEMETRY_STREAM_FILE: str = "telemetry.ndjson"
"""Where the local exporter appends. In the logs area, which is the only one bounded by rotation."""

JOIN_SECONDS: float = 5.0
"""How long a stop waits for the loop before reporting that it will not join."""

EVENT_LOOP_FAILED: str = "telemetry.loop.failed"
"""Emitted once when a tick raises, which stops the loop rather than flooding it."""

EVENT_LOOP_NOT_JOINED: str = "telemetry.loop.not_joined"
"""Emitted when the thread outlives its join, so the exporter is left open deliberately."""


@dataclass(slots=True)
class LocalFileExporter:
    """Appends batches to a file as JSON Lines.

    Args:
        open_stream: Opens the destination for appending. Injected so a test can
            supply a failure without a real filesystem.
        render: Turns one document into a line.
        stream: The open handle, or ``None`` before the first write.
        closed: Whether :meth:`close` has run.

    Every real failure mode is reachable: `OSError` becomes a temporary failure
    because a full disk may not be full a minute later, while writing to a closed
    exporter is permanent because nothing about it will change.
    """

    open_stream: Callable[[], TextIO]
    render: Callable[[Mapping[str, object]], str]
    stream: TextIO | None = None
    closed: bool = False

    def offer(self, batch: Sequence[dict[str, object]]) -> ExportOutcome:
        """Append a batch.

        Args:
            batch: The documents.

        Returns:
            What happened. Never raises, which is the port's first contract.
        """
        if self.closed:
            return ExportOutcome.PERMANENT_FAILURE
        try:
            if self.stream is None:
                self.stream = self.open_stream()
            for document in batch:
                self.stream.write(self.render(document))
            self.stream.flush()
        except OSError:
            return ExportOutcome.TEMPORARY_FAILURE
        except ValueError:
            return ExportOutcome.PERMANENT_FAILURE
        return ExportOutcome.DELIVERED

    def close(self) -> None:
        """Release the handle. Idempotent, and never raises."""
        self.closed = True
        if self.stream is None:
            return
        try:
            self.stream.close()
        except OSError:
            return
        finally:
            self.stream = None


def render_line(document: Mapping[str, object]) -> str:
    """One document as a JSON Lines record.

    Args:
        document: What to write.

    Returns:
        One line, ASCII-escaped and newline-terminated.

    Raises:
        ValueError: If the document holds a value JSON cannot represent exactly,
            which `allow_nan=False` turns from a silent `NaN` into a refusal.
    """
    return (
        json.dumps(
            document, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        )
        + "\n"
    )


def append_stream(path: Path, makedirs: Callable[[Path], None]) -> Callable[[], TextIO]:
    """A factory that opens one path for appending.

    Args:
        path: Where to append.
        makedirs: Creates the parent directory.

    Returns:
        A callable opening the file, deferred so building the graph opens nothing.
    """

    def _open() -> TextIO:
        makedirs(path.parent)
        return path.open("a", encoding="utf-8", newline="\n")

    return _open


@dataclass(slots=True)
class DisabledExporter:
    """What stands in when no exporter is configured.

    Deliberately **not** what runs by default. With telemetry export off, no
    exporter, queue, pump or thread is constructed at all, so this exists for the
    narrower case of a configured exporter whose library is absent — an
    unavailability that is recorded rather than pretended away.
    """

    reason: str

    def offer(self, batch: Sequence[dict[str, object]]) -> ExportOutcome:
        """Refuse permanently, since an absent library will not appear.

        Args:
            batch: Ignored.

        Returns:
            Always a permanent failure.
        """
        del batch
        return ExportOutcome.PERMANENT_FAILURE

    def close(self) -> None:
        """Release nothing."""


@dataclass(slots=True)
class TelemetryThread:
    """Drives the pump on an interval until asked to stop.

    Args:
        pump: What to tick.
        wake: Set to end a wait early. Supplied rather than defaulted, since
            `threading.Event()` is a call.
        interval_seconds: How long one wait lasts.
        monotonic: Reads the clock the pump is ticked with.
        logger: Where a loop failure is announced.
        spawn: Builds the thread. Injected so a test can observe the arguments
            without starting anything.
        join_seconds: How long a stop waits.
        thread: The running thread, or ``None``.

    **Non-daemon**, for `WatchdogThread`'s reason: the interpreter kills a daemon
    thread without unwinding, and a daemon part-way through an export during
    teardown is undefined behaviour. Non-daemon means a forgotten stop hangs the
    suite loudly rather than corrupting a file quietly.
    """

    pump: TelemetryPump
    wake: threading.Event
    interval_seconds: float
    monotonic: Callable[[], MonotonicReading]
    logger: Logger
    spawn: Callable[..., threading.Thread] = threading.Thread
    join_seconds: float = JOIN_SECONDS
    thread: threading.Thread | None = None

    def start(self) -> None:
        """Begin ticking. Starting twice starts one thread."""
        if self.thread is not None:
            return
        self.pump.arm()
        self.wake.clear()
        self.thread = self.spawn(target=self._loop, name="globin-telemetry", daemon=False)
        self.thread.start()

    def stop(self) -> bool:
        """Disarm, wake, and wait a bounded time for the loop to end.

        Returns:
            Whether the thread joined.

        **Disarm before waking**, which is `WatchdogThread.stop`'s ordering rule: a
        loop that never notices the event is harmless once the pump is disarmed,
        and that matters more than the wait's bound does.
        """
        self.pump.stand_down()
        self.wake.set()
        thread = self.thread
        if thread is None:
            return True
        thread.join(self.join_seconds)
        joined = not thread.is_alive()
        if not joined:
            self.logger.error(EVENT_LOOP_NOT_JOINED, seconds=int(self.join_seconds))
        self.thread = None
        return joined

    def _loop(self) -> None:
        """Tick until woken with the pump disarmed."""
        while not self.wake.is_set():
            try:
                self.pump.tick(self.monotonic())
            except Exception:
                self.logger.critical(EVENT_LOOP_FAILED)
                return
            self.wake.wait(self.interval_seconds)


def telemetry_thread(
    *,
    pump: TelemetryPump,
    interval_seconds: float,
    monotonic: Callable[[], MonotonicReading],
    logger: Logger,
) -> TelemetryThread:
    """A thread that has not started.

    Args:
        pump: What to tick.
        interval_seconds: How long one wait lasts.
        monotonic: Reads the clock.
        logger: Where a loop failure is announced.

    Returns:
        The thread wrapper, not started — the convention `build_diagnostics`
        already follows, because starting one is a decision for whoever owns the
        process rather than a side effect of asking for the object.
    """
    return TelemetryThread(
        pump=pump,
        wake=threading.Event(),
        interval_seconds=interval_seconds,
        monotonic=monotonic,
        logger=logger,
    )
