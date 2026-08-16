"""The watchdog's I/O: the lock, the thread, the stack capture and the exit.

The three things that could not be tested in the layers above, and each is tested
for the property that made it live down here.

**No test kills the runner and no test waits on a clock.** The terminator's exit is
injected; the loop is stopped by making its own snapshot set the wake event, so
exactly one tick runs and the test finishes as fast as a function call rather than
as fast as an interval.
"""

import io
import threading
from dataclasses import dataclass, field

import pytest

from globin.adapters.watchdog import (
    JOIN_SECONDS,
    THREAD_NAME,
    UNNAMED,
    ImmediateProcessExit,
    ProcessStackEvidence,
    SharedHeartbeatRegistry,
    WatchdogThread,
    heartbeats,
)
from globin.application.observability import Logger
from globin.application.watchdog import RuntimeWatchdog
from globin.domain.clock import Instant, MonotonicReading, instant_from_epoch_millis
from globin.domain.observability import LogEvent
from globin.domain.watchdog import (
    EVENT_WATCHDOG_LOOP_FAILED,
    MAXIMUM_EVIDENCE_FRAMES,
    NANOSECONDS_PER_MILLISECOND,
    Criticality,
    HeartbeatSnapshot,
    StallEvidence,
    WatchdogEpisode,
    WatchdogPolicy,
    WatchdogState,
)
from globin.errors import ValidationError

CORRELATION_ID = "00112233445566778899aabbccddeeff"


@dataclass(slots=True)
class _Ticking:
    """A monotonic clock that advances by a fixed step on every read."""

    at: int = 0
    step: int = 1

    def reading(self) -> MonotonicReading:
        self.at += self.step
        return MonotonicReading(self.at * NANOSECONDS_PER_MILLISECOND)


@dataclass(frozen=True, slots=True)
class _Wall:
    def now(self) -> Instant:
        return instant_from_epoch_millis(1_780_000_000_000)


@dataclass(slots=True)
class _Sink:
    events: list[LogEvent] = field(default_factory=list)

    def emit(self, event: LogEvent) -> None:
        self.events.append(event)


@dataclass(slots=True)
class _StoppingBeats:
    """A source that ends the loop it is read from, so exactly one tick runs."""

    wake: threading.Event
    reads: int = 0
    explodes: bool = False

    def snapshot(self) -> HeartbeatSnapshot:
        self.reads += 1
        self.wake.set()
        if self.explodes:
            msg = "the registry could not be read"
            raise RuntimeError(msg)
        return HeartbeatSnapshot(taken_at=MonotonicReading(0))


@dataclass(slots=True)
class _Quiet:
    """A collector with nothing to say, for the loop tests that do not need one."""

    def capture(self, _incident_id: str) -> StallEvidence:
        return StallEvidence()


@dataclass(slots=True)
class _Signals:
    stopped: bool = False

    def install(self) -> None:
        return

    def request(self) -> None:
        self.stopped = True

    def requested(self) -> bool:
        return self.stopped


@dataclass(slots=True)
class _Terminator:
    codes: list[int] = field(default_factory=list)

    def terminate(self, code: int) -> None:
        self.codes.append(code)


@dataclass(slots=True)
class _FakeThread:
    """A thread that records how it was built and never actually runs."""

    target: object = None
    name: str = ""
    daemon: bool = True
    started: int = 0
    joins: list[float | None] = field(default_factory=list)
    alive: bool = False

    def start(self) -> None:
        self.started += 1

    def join(self, timeout: float | None = None) -> None:
        self.joins.append(timeout)

    def is_alive(self) -> bool:
        return self.alive


# ---------------------------------------------------------------------------
# The heartbeat registry
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> SharedHeartbeatRegistry:
    """A registry on a clock that advances one millisecond per read."""
    return heartbeats(_Ticking())


def test_registration_seeds_a_beat_so_never_beaten_needs_no_special_case(
    registry: SharedHeartbeatRegistry,
) -> None:
    registry.register("feed", Criticality.REQUIRED)
    taken = registry.snapshot()
    assert taken.beats[0].sequence == 0
    assert taken.silence_of(taken.beats[0]).nanoseconds > 0


def test_registering_one_component_twice_is_refused(
    registry: SharedHeartbeatRegistry,
) -> None:
    """Two registrations would hide one of them, whichever won."""
    registry.register("feed", Criticality.REQUIRED)
    with pytest.raises(ValidationError, match="already monitored"):
        registry.register("feed", Criticality.ADVISORY)


def test_beating_an_unregistered_component_is_refused_rather_than_ignored(
    registry: SharedHeartbeatRegistry,
) -> None:
    """A silent no-op means a typo is monitored by nothing and nothing says so."""
    with pytest.raises(ValidationError, match="not monitored"):
        registry.beat("fed")


def test_a_beat_advances_the_sequence_rather_than_only_the_timestamp(
    registry: SharedHeartbeatRegistry,
) -> None:
    registry.register("feed", Criticality.REQUIRED)
    registry.beat("feed")
    registry.beat("feed")
    assert registry.snapshot().beats[0].sequence == 2


def test_a_snapshot_is_ordered_by_name_whatever_order_registration_happened(
    registry: SharedHeartbeatRegistry,
) -> None:
    for name in ("zulu", "alpha", "mike"):
        registry.register(name, Criticality.REQUIRED)
    assert [entry.name for entry in registry.snapshot().beats] == ["alpha", "mike", "zulu"]


def test_a_snapshot_does_not_change_when_the_registry_does(
    registry: SharedHeartbeatRegistry,
) -> None:
    """It is an immutable copy, which is what lets evidence run without a lock."""
    registry.register("feed", Criticality.REQUIRED)
    taken = registry.snapshot()
    registry.beat("feed")
    assert taken.beats[0].sequence == 0


def test_concurrent_beats_lose_none_of_their_increments(
    registry: SharedHeartbeatRegistry,
) -> None:
    """The one thing the lock is for: ``sequence + 1`` is a read-modify-write.

    A plain dict store would be atomic under the interpreter's own lock and an
    increment is not, so without the lock two threads reading the same value would
    write the same successor and one beat would vanish.
    """
    registry.register("feed", Criticality.REQUIRED)

    def hammer() -> None:
        for _ in range(200):
            registry.beat("feed")

    workers = [threading.Thread(target=hammer) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(JOIN_SECONDS)
    assert registry.snapshot().beats[0].sequence == 800


def test_a_snapshot_is_never_dated_before_the_beats_it_contains(
    registry: SharedHeartbeatRegistry,
) -> None:
    """Reading the clock after the copy is what makes this impossible.

    The reverse order would let a beat land between the reading and the copy,
    producing a snapshot ``MonotonicReading.since`` refuses to subtract — from
    inside the watchdog loop, intermittently, and only under load.
    """
    for index in range(20):
        registry.register(f"component-{index:02d}", Criticality.REQUIRED)
    taken = registry.snapshot()
    assert all(entry.at <= taken.taken_at for entry in taken.beats)


# ---------------------------------------------------------------------------
# The thread
# ---------------------------------------------------------------------------


def build_thread(
    *, spawn: object = None, wake: threading.Event | None = None
) -> tuple[WatchdogThread, _StoppingBeats, _Sink]:
    """A watchdog thread whose single tick ends its own loop."""
    event = threading.Event() if wake is None else wake
    beats = _StoppingBeats(wake=event)
    sink = _Sink()
    logger = Logger(sink=sink, correlation_id=CORRELATION_ID)
    cycle = RuntimeWatchdog(
        monotonic=_Ticking(),
        clock=_Wall(),
        beats=beats,
        policy=WatchdogPolicy(),
        evidence=_Quiet(),
        signals=_Signals(),
        terminator=_Terminator(),
        logger=logger,
        run_id="fedcba9876543210fedcba9876543210",
        correlation_id=CORRELATION_ID,
        new_incident_id=lambda: "0123456789abcdef0123456789abcdef",
        episode=WatchdogEpisode(),
    )
    thread = WatchdogThread(
        cycle=cycle,
        wake=event,
        interval_seconds=0.001,
        logger=logger,
        join_seconds=JOIN_SECONDS,
    )
    if spawn is not None:
        thread.spawn = spawn  # type: ignore[assignment]
    return thread, beats, sink


def test_the_thread_is_named_and_is_not_a_daemon() -> None:
    """A daemon is killed at interpreter shutdown without unwinding.

    One part-way through deciding to end the process during teardown is undefined
    behaviour, and a forgotten stop would be papered over rather than noticed.
    """
    built = _FakeThread()
    thread, _beats, _sink = build_thread(spawn=lambda **kwargs: _record(built, kwargs))
    thread.start()
    assert built.name == THREAD_NAME
    assert built.daemon is False
    assert built.started == 1
    thread.stop()


def _record(built: _FakeThread, kwargs: dict[str, object]) -> _FakeThread:
    """Capture the arguments a spawn was called with."""
    built.target = kwargs.get("target")
    built.name = str(kwargs.get("name", ""))
    built.daemon = bool(kwargs.get("daemon"))
    return built


def test_starting_a_started_thread_does_nothing() -> None:
    built = _FakeThread()
    thread, _beats, _sink = build_thread(spawn=lambda **kwargs: _record(built, kwargs))
    thread.start()
    thread.start()
    assert built.started == 1
    thread.stop()


def test_starting_arms_the_cycle_and_stopping_disarms_it() -> None:
    built = _FakeThread()
    thread, _beats, _sink = build_thread(spawn=lambda **kwargs: _record(built, kwargs))
    thread.start()
    armed = thread.cycle.episode.state
    running = thread.cycle.running
    thread.stop()
    assert armed is WatchdogState.STARTING
    assert running
    assert thread.cycle.episode.state is WatchdogState.DISABLED
    assert not thread.cycle.running


def test_stopping_a_stopped_thread_does_nothing_and_joins_nothing() -> None:
    built = _FakeThread()
    thread, _beats, _sink = build_thread(spawn=lambda **kwargs: _record(built, kwargs))
    thread.start()
    thread.stop()
    thread.stop()
    assert built.joins == [JOIN_SECONDS]


def test_a_thread_that_will_not_join_is_reported_rather_than_waited_on_for_ever() -> None:
    """A hung watchdog must not hang the shutdown it exists to guarantee."""
    built = _FakeThread(alive=True)
    thread, _beats, sink = build_thread(spawn=lambda **kwargs: _record(built, kwargs))
    thread.start()
    thread.stop()
    failures = [event for event in sink.events if event.event == EVENT_WATCHDOG_LOOP_FAILED]
    assert failures
    assert failures[0].as_mapping()["joined"] is False


def test_the_loop_runs_a_tick_and_stops_when_woken() -> None:
    """A real thread, ended by its own first read rather than by a timeout."""
    thread, beats, _sink = build_thread()
    thread.start()
    assert thread.thread is not None
    thread.thread.join(JOIN_SECONDS)
    assert beats.reads == 1
    thread.stop()


def test_a_tick_that_raises_stops_the_loop_once_and_disarms_it() -> None:
    """Retrying would flood the log for ever; swallowing would remove the guard."""
    thread, beats, sink = build_thread()
    beats.explodes = True
    thread.start()
    assert thread.thread is not None
    thread.thread.join(JOIN_SECONDS)
    failures = [event for event in sink.events if event.event == EVENT_WATCHDOG_LOOP_FAILED]
    assert len(failures) == 1
    assert failures[0].as_mapping()["fault"] == "RuntimeError"
    assert thread.cycle.episode.state is WatchdogState.DISABLED
    assert not thread.cycle.running
    thread.stop()


# ---------------------------------------------------------------------------
# The stack capture
# ---------------------------------------------------------------------------


def capture_off_the_main_thread(collector: ProcessStackEvidence) -> StallEvidence:
    """Capture from a worker, which is where the watchdog really captures from.

    The collector excludes its own thread, so a capture invoked directly from a
    single-threaded test describes nothing at all — which is correct behaviour and
    a useless fixture. Running it from a worker puts the main thread in front of
    it, exactly as the watchdog thread does in production.
    """
    gathered: list[StallEvidence] = []
    worker = threading.Thread(target=lambda: gathered.append(collector.capture("abc123")))
    worker.start()
    worker.join(JOIN_SECONDS)
    return gathered[0]


def test_the_native_dump_is_written_with_a_marker_naming_its_incident() -> None:
    """The fault file is append-only and shared with the process fault hooks."""
    handle = io.StringIO()
    written: list[dict[str, object]] = []
    collector = ProcessStackEvidence(
        handle=handle,
        dump=lambda **kwargs: written.append(kwargs),
    )
    gathered = collector.capture("abc123")
    assert gathered.native_dump
    assert "--- globin watchdog stall abc123 ---" in handle.getvalue()
    assert written[0]["all_threads"] is True


def test_no_open_fault_file_is_a_recorded_problem_rather_than_a_failure() -> None:
    collector = ProcessStackEvidence(handle=None)
    gathered = capture_off_the_main_thread(collector)
    assert not gathered.native_dump
    assert any("no fault file" in problem for problem in gathered.problems)
    assert gathered.threads


def test_a_dump_that_fails_is_recorded_and_the_frames_are_still_gathered() -> None:
    """One collector failing must not stop the other."""

    def explode(**_kwargs: object) -> None:
        msg = "the descriptor went away"
        raise OSError(msg)

    collector = ProcessStackEvidence(handle=io.StringIO(), dump=explode)
    gathered = capture_off_the_main_thread(collector)
    assert not gathered.native_dump
    assert gathered.problems
    assert gathered.threads


def test_frames_that_cannot_be_read_are_a_problem_rather_than_a_crash() -> None:
    def explode() -> dict[int, object]:
        msg = "the interpreter refused"
        raise RuntimeError(msg)

    collector = ProcessStackEvidence(
        handle=io.StringIO(),
        dump=lambda **_kwargs: None,
        current_frames=explode,  # type: ignore[arg-type]
    )
    gathered = collector.capture("abc123")
    assert gathered.threads == ()
    assert any("frames could not be read" in problem for problem in gathered.problems)


def test_the_capturing_thread_never_describes_itself() -> None:
    """Otherwise the evidence is dominated by the collector's own stack.

    The identity that must be absent is the *worker's*, not this test's, because
    the worker is what ran the capture — which is the whole reason the exclusion is
    ``threading.get_ident()`` inside the collector rather than a name comparison.
    """
    collector = ProcessStackEvidence(handle=io.StringIO(), dump=lambda **_kwargs: None)
    gathered: list[StallEvidence] = []
    identities: list[int] = []

    def run() -> None:
        identities.append(threading.get_ident())
        gathered.append(collector.capture("abc123"))

    worker = threading.Thread(target=run)
    worker.start()
    worker.join(JOIN_SECONDS)
    described = {stack.identifier for stack in gathered[0].threads}
    assert identities[0] not in described
    assert threading.main_thread().ident in described


def test_every_frame_location_is_reduced_to_something_naming_no_person() -> None:
    """A path outside the tree carries the account holder's name.

    ``relative_location`` is the reduction Phase 024 already blessed for allocation
    sites, which are the same class of data: a source location out of a traceback.
    """
    collector = ProcessStackEvidence(handle=io.StringIO(), dump=lambda **_kwargs: None)
    gathered = capture_off_the_main_thread(collector)
    located = [frame.location for stack in gathered.threads for frame in stack.frames]
    assert located
    assert all(":" not in location and "\\" not in location for location in located)


def test_no_thread_reports_more_frames_than_the_declared_bound() -> None:
    collector = ProcessStackEvidence(handle=io.StringIO(), dump=lambda **_kwargs: None)
    gathered = capture_off_the_main_thread(collector)
    assert all(len(stack.frames) <= MAXIMUM_EVIDENCE_FRAMES for stack in gathered.threads)


def test_a_thread_with_an_unprintable_name_is_described_anyway() -> None:
    """A dependency is free to name its threads whatever it likes."""
    collector = ProcessStackEvidence(
        handle=io.StringIO(),
        dump=lambda **_kwargs: None,
        enumerate_threads=list,
    )
    gathered = capture_off_the_main_thread(collector)
    assert all(stack.name == UNNAMED for stack in gathered.threads)


# ---------------------------------------------------------------------------
# The exit
# ---------------------------------------------------------------------------


def test_the_terminator_calls_what_it_was_given_with_the_code() -> None:
    """The real default is ``os._exit``; no test may ever reach it."""
    codes: list[int] = []
    ImmediateProcessExit(exit_process=codes.append).terminate(23)  # type: ignore[arg-type]
    assert codes == [23]
