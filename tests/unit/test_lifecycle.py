"""One run's lifecycle: what it records, in what order, and what it releases.

Every port is a hand-written double, which is what lets these tests assert about
a shutdown after a crash, after a signal and after a failed cleanup without any of
those actually happening. The clock is manual, so the timestamps written are exact
values rather than something that has to be matched with a pattern.

**The property under almost every test here is the same:** the lock is released
and the records are closed whatever the block did. A teardown that only ran on the
happy path would be a teardown nobody could rely on.
"""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest

from globin.application.lifecycle import Lifecycle, Session, ShutdownIncompleteError
from globin.domain.bootstrap import ExitCode, recorded_outside
from globin.domain.clock import duration_from_millis, instant_from_epoch_millis
from globin.domain.identifiers import RunId
from globin.domain.runtime_state import (
    INSTANCE_FILE,
    LIFECYCLE_FILE,
    LifecycleStatus,
    RuntimeArea,
    RuntimeLayout,
    RuntimePersistenceError,
    ShutdownReason,
    read_lifecycle,
)
from tests.support import ManualClock

RUN = RunId(text="e" * 32)
ROOT = recorded_outside("C:/somewhere/GLOBIN")


def a_clock() -> ManualClock:
    """A clock that advances one second per reading.

    Manual rather than the host's, so the timestamps written are exact values a
    test can assert about, and so the opening and closing records provably come
    from two separate readings.
    """
    return ManualClock(
        current=instant_from_epoch_millis(1_786_000_000_000),
        step=duration_from_millis(1_000),
    )


@dataclass(slots=True)
class _Tree:
    """Records which temporary directories were claimed and released."""

    claimed: list[str]
    released: list[str]
    refuse_release: bool = False

    def prepare(self, layout: RuntimeLayout) -> tuple[str, ...]:
        assert layout is not None
        return ()

    def describe(self) -> str:
        return "a temporary runtime root"

    def recorded_root(self) -> object:
        return ROOT

    def claim_temporary(self, run_id: RunId) -> None:
        self.claimed.append(str(run_id))

    def release_temporary(self, run_id: RunId) -> None:
        if self.refuse_release:
            msg = "the temporary tree is held open by something else"
            raise RuntimePersistenceError(msg)
        self.released.append(str(run_id))


@dataclass(slots=True)
class _State:
    """Holds documents in memory, recording the order they were published in."""

    documents: dict[tuple[str, str], Mapping[str, object]]
    order: list[str]
    refuse: set[str] = field(default_factory=set)

    def publish(self, area: RuntimeArea, name: str, document: Mapping[str, object]) -> None:
        if name in self.refuse:
            msg = f"{name} could not be published"
            raise RuntimePersistenceError(msg)
        self.documents[(area.value, name)] = document
        self.order.append(f"publish {name}")

    def read(self, area: RuntimeArea, name: str) -> Mapping[str, object] | None:
        return self.documents.get((area.value, name))

    def discard(self, area: RuntimeArea, name: str) -> None:
        self.documents.pop((area.value, name), None)
        self.order.append(f"discard {name}")


@dataclass(slots=True)
class _Lock:
    """Records that the lock was taken and released, or refuses to give it."""

    events: list[str]
    refuse: bool = False

    @contextmanager
    def hold(self) -> Iterator[None]:
        if self.refuse:
            msg = "another GLOBIN coordinator is running on this machine"
            raise RuntimePersistenceError(msg)
        self.events.append("acquired")
        try:
            yield
        finally:
            self.events.append("released")

    def probe(self) -> str:
        return "another GLOBIN coordinator is running" if self.refuse else ""


@dataclass(slots=True)
class _Signals:
    """Reports whether a stop was requested, and whether handlers were installed."""

    stopped: bool = False
    installed: bool = False
    asked: int = 0

    def install(self) -> None:
        self.installed = True

    def request(self) -> None:
        self.asked += 1
        self.stopped = True

    def requested(self) -> bool:
        return self.stopped


@dataclass(slots=True)
class _Harness:
    """A wired lifecycle and every double it was built from."""

    lifecycle: Lifecycle
    tree: _Tree
    state: _State
    lock: _Lock
    signals: _Signals
    registered: list[Callable[[], None]]


@pytest.fixture
def harness() -> _Harness:
    """A lifecycle whose every port is satisfied."""
    tree = _Tree(claimed=[], released=[])
    state = _State(documents={}, order=[])
    lock = _Lock(events=[])
    signals = _Signals()
    registered: list[Callable[[], None]] = []
    return _Harness(
        lifecycle=Lifecycle(
            tree=tree,  # type: ignore[arg-type]
            state=state,
            lock=lock,
            signals=signals,
            clock=a_clock(),
            layout=RuntimeLayout(),
            version="0.1.0",
            profile="default",
            pid=4321,
            runtime_root=ROOT,
            register_fallback=registered.append,
        ),
        tree=tree,
        state=state,
        lock=lock,
        signals=signals,
        registered=registered,
    )


def lifecycle_of(harness: _Harness) -> Mapping[str, object]:
    """The lifecycle document as it stands."""
    document = harness.state.documents[(RuntimeArea.STATE.value, LIFECYCLE_FILE)]
    assert document is not None
    return document


# ---------------------------------------------------------------------------
# A run that completes
# ---------------------------------------------------------------------------


def test_a_completed_run_records_a_clean_shutdown(harness: _Harness) -> None:
    with harness.lifecycle.run(RUN) as session:
        assert session.run_id == RUN
        assert lifecycle_of(harness)["status"] == LifecycleStatus.RUNNING.value

    record = read_lifecycle(dict(lifecycle_of(harness)))
    assert record.ended_cleanly
    assert record.reason is ShutdownReason.COMPLETED
    assert record.exit_code == int(ExitCode.OK)


def test_the_lock_is_taken_before_anything_is_written(harness: _Harness) -> None:
    """The lock comes first, before a single byte is written.

    A second coordinator that wrote its metadata and then found it could not have
    the lock would already have overwritten the first one's.
    """
    harness.lock.refuse = True
    with pytest.raises(RuntimePersistenceError), harness.lifecycle.run(RUN):
        pass
    assert harness.state.documents == {}
    assert harness.tree.claimed == []


def test_the_instance_metadata_is_published_and_then_cleared(harness: _Harness) -> None:
    with harness.lifecycle.run(RUN):
        published = harness.state.documents[(RuntimeArea.RUN.value, INSTANCE_FILE)]
        assert published["instance_id"] == str(RUN)
        assert published["pid"] == 4321
    assert (RuntimeArea.RUN.value, INSTANCE_FILE) not in harness.state.documents


def test_the_run_claims_and_releases_its_own_temporary_directory(harness: _Harness) -> None:
    with harness.lifecycle.run(RUN):
        assert harness.tree.claimed == [str(RUN)]
    assert harness.tree.released == [str(RUN)]


def test_signal_handlers_are_installed_and_a_fallback_is_registered(harness: _Harness) -> None:
    """`atexit` is registered, and nothing rests on it."""
    with harness.lifecycle.run(RUN):
        assert harness.signals.installed
    assert len(harness.registered) == 1


def test_the_teardown_happens_in_the_declared_order(harness: _Harness) -> None:
    """The teardown order ADR-0059 fixes.

    Publish the closing record, remove the temporary tree, clear the instance
    metadata, release the lock.
    """
    with harness.lifecycle.run(RUN):
        pass
    closing = harness.state.order.index(f"publish {LIFECYCLE_FILE}")
    clearing = harness.state.order.index(f"discard {INSTANCE_FILE}")
    assert closing < clearing
    assert harness.lock.events == ["acquired", "released"]


def test_the_records_carry_no_absolute_path(harness: _Harness) -> None:
    with harness.lifecycle.run(RUN):
        pass
    assert "C:/somewhere" not in str(harness.state.documents)


# ---------------------------------------------------------------------------
# A run that does not complete
# ---------------------------------------------------------------------------


def test_a_keyboard_interrupt_is_recorded_as_an_interruption(harness: _Harness) -> None:
    with pytest.raises(KeyboardInterrupt), harness.lifecycle.run(RUN):
        raise KeyboardInterrupt

    record = read_lifecycle(dict(lifecycle_of(harness)))
    assert record.reason is ShutdownReason.INTERRUPTED
    assert harness.lock.events == ["acquired", "released"]


def test_a_signal_is_recorded_separately_from_an_interruption(harness: _Harness) -> None:
    """An operator reading the record wants to know which route the stop took."""
    with harness.lifecycle.run(RUN) as session:
        harness.signals.stopped = True
        assert session.stop_requested()

    record = read_lifecycle(dict(lifecycle_of(harness)))
    assert record.reason is ShutdownReason.SIGNALLED


def test_a_failing_application_is_recorded_as_a_failure_and_still_releases(
    harness: _Harness,
) -> None:
    with pytest.raises(RuntimeError), harness.lifecycle.run(RUN):  # noqa: PT012 - the block is a context manager plus the statement that must raise inside it
        msg = "the application broke"
        raise RuntimeError(msg)

    record = read_lifecycle(dict(lifecycle_of(harness)))
    assert record.reason is ShutdownReason.FAILED
    assert record.exit_code == int(ExitCode.INTERNAL)
    assert harness.lock.events == ["acquired", "released"]
    assert harness.tree.released == [str(RUN)]


def test_the_original_failure_is_what_propagates(harness: _Harness) -> None:
    """A shutdown report must not replace the fault the caller has to act on."""

    def fail() -> None:
        msg = "the application broke"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="the application broke"), harness.lifecycle.run(RUN):
        fail()


# ---------------------------------------------------------------------------
# Application cleanups
# ---------------------------------------------------------------------------


def test_cleanups_run_newest_first(harness: _Harness) -> None:
    order: list[str] = []
    with harness.lifecycle.run(RUN) as session:
        session.on_close(lambda: order.append("first"))
        session.on_close(lambda: order.append("second"))
    assert order == ["second", "first"]


def test_every_cleanup_runs_even_when_an_earlier_one_raises(harness: _Harness) -> None:
    """Every callback runs, however the ones before it went.

    A list that stopped at the first exception would make the reliability of the
    last callback depend on the first.
    """
    order: list[str] = []

    def explode() -> None:
        msg = "this cleanup is broken"
        raise RuntimeError(msg)

    with pytest.raises(ShutdownIncompleteError), harness.lifecycle.run(RUN) as session:  # noqa: PT012 - the block is a context manager plus the statement that must raise inside it
        session.on_close(lambda: order.append("first"))
        session.on_close(explode)

    assert order == ["first"]


def test_a_failed_cleanup_does_not_stop_the_rest_of_the_teardown(harness: _Harness) -> None:
    """The debris this exists to remove would otherwise be left behind."""

    def explode() -> None:
        msg = "this cleanup is broken"
        raise RuntimeError(msg)

    with pytest.raises(ShutdownIncompleteError), harness.lifecycle.run(RUN) as session:
        session.on_close(explode)

    assert harness.tree.released == [str(RUN)]
    assert harness.lock.events == ["acquired", "released"]
    assert read_lifecycle(dict(lifecycle_of(harness))).ended_cleanly


# ---------------------------------------------------------------------------
# A teardown that cannot finish
# ---------------------------------------------------------------------------


def test_every_teardown_failure_is_collected_rather_than_only_the_first(
    harness: _Harness,
) -> None:
    with pytest.raises(ShutdownIncompleteError) as caught, harness.lifecycle.run(RUN):  # noqa: PT012 - the block is a context manager plus the statement that must raise inside it
        # Broken *inside* the block, so the opening records still succeed and only
        # the teardown fails. Refusing from the start would fail `_open` instead,
        # which is a different test two below.
        harness.tree.refuse_release = True
        harness.state.refuse = {LIFECYCLE_FILE}

    message = str(caught.value)
    assert "record the shutdown" in message
    assert "remove this run's temporary tree" in message


def test_the_lock_is_released_even_when_the_teardown_fails(harness: _Harness) -> None:
    """The one thing that must always happen, or the next run cannot start."""
    harness.tree.refuse_release = True
    with pytest.raises(ShutdownIncompleteError), harness.lifecycle.run(RUN):
        pass
    assert harness.lock.events == ["acquired", "released"]


def test_a_failure_opening_the_run_is_raised_before_the_block_is_entered(
    harness: _Harness,
) -> None:
    harness.state.refuse = {INSTANCE_FILE}
    entered = False
    with pytest.raises(RuntimePersistenceError), harness.lifecycle.run(RUN):
        entered = True
    assert not entered
    assert harness.lock.events == ["acquired", "released"]


# ---------------------------------------------------------------------------
# The `atexit` net
# ---------------------------------------------------------------------------


def test_the_fallback_closes_an_open_record(harness: _Harness) -> None:
    """What the net is for: a run whose `finally` never ran.

    Simulated by publishing an open record and then invoking the registered
    callback directly, which is the only way to observe it without ending the
    interpreter.
    """
    with harness.lifecycle.run(RUN):
        fallback = harness.registered[0]
        harness.state.documents.pop((RuntimeArea.STATE.value, LIFECYCLE_FILE), None)
        harness.lifecycle._record(  # noqa: SLF001 - reaching the open state the net exists for
            _session_of(harness), LifecycleStatus.RUNNING
        )
        fallback()
        assert read_lifecycle(dict(lifecycle_of(harness))).ended_cleanly


def test_the_fallback_does_not_overwrite_a_run_that_shut_down_properly(
    harness: _Harness,
) -> None:
    """The net reads before it writes.

    A safety net that rewrote a good record would turn every clean run into a
    failed one at interpreter exit.
    """
    with harness.lifecycle.run(RUN):
        pass
    before = dict(lifecycle_of(harness))
    harness.registered[0]()
    assert dict(lifecycle_of(harness)) == before


def test_the_fallback_ignores_a_record_belonging_to_another_run(harness: _Harness) -> None:
    with harness.lifecycle.run(RUN):
        pass
    harness.state.documents[(RuntimeArea.STATE.value, LIFECYCLE_FILE)] = {
        "schema_version": 1,
        "status": "running",
        "instance_id": "f" * 32,
        "pid": 999,
        "started_at": "2026-08-16T12:00:00Z",
        "finished_at": None,
        "reason": None,
        "exit_code": None,
    }
    harness.registered[0]()
    assert lifecycle_of(harness)["instance_id"] == "f" * 32


def test_the_fallback_swallows_its_own_failure(harness: _Harness) -> None:
    """A failing net stays quiet.

    The interpreter is already leaving, and a traceback at exit would be noise
    attached to the wrong cause.
    """
    with harness.lifecycle.run(RUN):
        pass
    harness.state.refuse = {LIFECYCLE_FILE}
    harness.state.documents[(RuntimeArea.STATE.value, LIFECYCLE_FILE)] = {
        "schema_version": 1,
        "status": "running",
        "instance_id": str(RUN),
        "pid": 4321,
        "started_at": "2026-08-16T12:00:00Z",
        "finished_at": None,
        "reason": None,
        "exit_code": None,
    }
    harness.registered[0]()


def _session_of(harness: _Harness) -> Session:
    """A session standing in for the one the fallback closed over.

    The fallback closes over the session `Lifecycle.run` built, which a test
    cannot reach. This is the same run, which is all the fallback compares.
    """
    return Session(run_id=RUN, started_at=a_clock().now(), signals=harness.signals, cleanups=[])
