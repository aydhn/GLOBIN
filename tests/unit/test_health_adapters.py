"""The probes that read this host, and the failures each one classifies.

Every psutil failure is exercised through a hand-written double rather than by
arranging a real one: `AccessDenied` needs another user's process, `NoSuchProcess`
needs a race, and neither is reproducible in a test suite. The doubles satisfy the
same attribute surface the adapter reaches for, which is what
`docs/TESTING_STRATEGY.md` asks a double to do.

The real probes are also run once each against this interpreter, so the happy path
is not only exercised through a substitute.
"""

import threading
import tracemalloc
from pathlib import Path
from typing import Any

import pytest

from globin.adapters.health import (
    MAIN_THREAD_NAME,
    SANITISED,
    DiagnosticsStateProbe,
    FilesystemTreeProbe,
    PsutilProcessProbe,
    StateLifecycleProbe,
    SystemHostProbe,
    SystemPlatformProbe,
    SystemThreadProbe,
    TracemallocProbe,
    UnavailableProcessProbe,
    _sanitised_name,
    _seconds_to_nanoseconds,
    cpu_percent_reading,
    relative_location,
    snapshot_document,
    system_host_probe,
    system_process_probe,
)
from globin.domain.health import (
    REASON_CPU_NOT_SAMPLED,
    REASON_PSUTIL_ABSENT,
    Availability,
    LoggingState,
)
from globin.domain.runtime_state import RuntimeArea, RuntimeLayout


class Memory:
    """What `memory_info` returns."""

    rss = 1024
    vms = 2048


class Times:
    """What `cpu_times` returns."""

    user = 1.5
    system = 0.5


class FakeProcess:
    """A psutil process that answers, and can be told to refuse.

    Args:
        handles: What `num_handles` returns, or ``None`` to omit the attribute
            entirely — which is how a non-Windows platform presents.
        raises: An exception class to raise from every reader.
    """

    def __init__(self, handles: int | None = 179, raises: type[Exception] | None = None) -> None:
        """Record what this process will answer, and what it will refuse."""
        self._handles = handles
        self._raises = raises
        if handles is not None:
            self.num_handles = self._read_handles

    def oneshot(self) -> Any:
        """The caching context psutil documents."""

        class Context:
            """A no-op caching context."""

            def __enter__(self) -> None:
                """Enter, caching nothing."""
                return

            def __exit__(self, *_args: object) -> None:
                """Leave, propagating anything raised."""

        return Context()

    def memory_info(self) -> Memory:
        """Resident and virtual size."""
        if self._raises is not None:
            raise self._raises
        return Memory()

    def cpu_times(self) -> Times:
        """Cumulative user and system time."""
        return Times()

    def num_threads(self) -> int:
        """How many operating-system threads."""
        return 4

    def _read_handles(self) -> int:
        assert self._handles is not None
        return self._handles


class FakePsutil:
    """The psutil surface `PsutilProcessProbe` reaches for."""

    class AccessDenied(Exception):  # noqa: N818 -- psutil's own spelling, looked up by name
        """Raised when the operating system refuses."""

    class NoSuchProcess(Exception):  # noqa: N818 -- psutil's own spelling
        """Raised when the process disappeared."""

    class ZombieProcess(Exception):  # noqa: N818 -- psutil's own spelling
        """Raised for a process that has exited but not been reaped."""

    def __init__(self, process: FakeProcess | None = None) -> None:
        """Hold the process this module will hand out."""
        self._process = FakeProcess() if process is None else process

    def Process(self, _pid: int) -> FakeProcess:  # noqa: N802 -- psutil's own spelling
        """The one process this module knows about."""
        return self._process


# ---------------------------------------------------------------------------
# The process probe
# ---------------------------------------------------------------------------


def test_a_psutil_backed_probe_reads_every_counter() -> None:
    summary = PsutilProcessProbe(FakePsutil()).summary()
    assert summary.resident_bytes.value == 1024
    assert summary.virtual_bytes.value == 2048
    assert summary.cpu_user.value == 1_500_000_000
    assert summary.threads.value == 4
    assert summary.handles.value == 179


def test_a_platform_without_a_handle_count_records_unsupported_rather_than_zero() -> None:
    """Reporting `0` there would invent a measurement."""
    summary = PsutilProcessProbe(FakePsutil(FakeProcess(handles=None))).summary()
    assert summary.handles.availability is Availability.UNSUPPORTED
    assert summary.handles.value is None


def test_a_refused_read_is_denied_rather_than_raised() -> None:
    process = FakeProcess(raises=FakePsutil.AccessDenied)
    summary = PsutilProcessProbe(FakePsutil(process)).summary()
    assert summary.resident_bytes.availability is Availability.DENIED


def test_a_process_that_disappeared_is_reported_as_gone() -> None:
    process = FakeProcess(raises=FakePsutil.NoSuchProcess)
    summary = PsutilProcessProbe(FakePsutil(process)).summary()
    assert summary.resident_bytes.availability is Availability.UNAVAILABLE


def test_a_zombie_process_is_reported_the_same_way() -> None:
    process = FakeProcess(raises=FakePsutil.ZombieProcess)
    summary = PsutilProcessProbe(FakePsutil(process)).summary()
    assert summary.resident_bytes.availability is Availability.UNAVAILABLE


def test_an_operating_system_error_is_reported_as_denied() -> None:
    process = FakeProcess(raises=PermissionError)
    summary = PsutilProcessProbe(FakePsutil(process)).summary()
    assert summary.resident_bytes.availability is Availability.DENIED


def test_a_handle_reader_that_refuses_is_classified_rather_than_raised() -> None:
    class Refusing(FakeProcess):
        """A process whose handle reader refuses."""

        def _read_handles(self) -> int:
            raise FakePsutil.AccessDenied

    summary = PsutilProcessProbe(FakePsutil(Refusing())).summary()
    assert summary.handles.availability is Availability.DENIED


def test_a_handle_reader_that_is_not_implemented_is_unsupported() -> None:
    class Unimplemented(FakeProcess):
        """A process whose handle reader is not implemented here."""

        def _read_handles(self) -> int:
            raise NotImplementedError

    summary = PsutilProcessProbe(FakePsutil(Unimplemented())).summary()
    assert summary.handles.availability is Availability.UNSUPPORTED


def test_an_absent_library_still_reports_the_process_identifier() -> None:
    """The identifier needs no library and cannot fail.

    A snapshot withholding a fact it holds because a *different* reader was
    missing would be discarding information it had.
    """
    summary = UnavailableProcessProbe().summary()
    assert summary.pid > 0
    assert summary.resident_bytes.reason == REASON_PSUTIL_ABSENT


def test_the_factory_returns_a_probe_either_way() -> None:
    """Either branch produces a usable probe.

    On this host psutil is installed; the other branch is covered directly by
    `UnavailableProcessProbe` above.
    """
    probe = system_process_probe()
    assert probe.summary().pid > 0


def test_seconds_are_truncated_rather_than_rounded() -> None:
    """A CPU time only grows, and rounding up would report time nobody used."""
    assert _seconds_to_nanoseconds(1.9999999999) < 2_000_000_000


def test_no_instantaneous_cpu_percentage_is_offered() -> None:
    reading = cpu_percent_reading()
    assert not reading.measured
    assert reading.reason == REASON_CPU_NOT_SAMPLED


# ---------------------------------------------------------------------------
# The host probe
# ---------------------------------------------------------------------------


class Usage:
    """What `shutil.disk_usage` returns."""

    total = 1000
    free = 400


def test_the_host_probe_reports_processors_and_filesystems() -> None:
    summary = SystemHostProbe(usage=lambda _anchor: Usage()).summary(("C:", "C:"))
    assert summary.logical_cpus.value
    assert len(summary.filesystems) == 1, "duplicate anchors are collapsed"
    assert summary.filesystems[0].free_bytes.value == 400


def test_a_filesystem_query_that_fails_records_an_absence() -> None:
    def refuse(_anchor: str) -> Usage:
        raise OSError

    summary = SystemHostProbe(usage=refuse).summary(("C:",))
    assert not summary.filesystems[0].free_bytes.measured


def test_host_memory_is_unavailable_without_a_reader() -> None:
    summary = SystemHostProbe(usage=lambda _anchor: Usage()).summary(())
    assert summary.available_memory_bytes.reason == REASON_PSUTIL_ABSENT


def test_host_memory_is_read_where_a_reader_exists() -> None:
    class Virtual:
        """What `virtual_memory` returns."""

        total = 100
        available = 40

    probe = SystemHostProbe(usage=lambda _anchor: Usage(), memory=Virtual)
    summary = probe.summary(())
    assert summary.total_memory_bytes.value == 100
    assert summary.available_memory_bytes.value == 40


def test_a_memory_reader_that_fails_records_an_absence() -> None:
    def refuse() -> object:
        raise OSError

    summary = SystemHostProbe(usage=lambda _anchor: Usage(), memory=refuse).summary(())
    assert not summary.available_memory_bytes.measured


def test_a_memory_reader_missing_a_field_records_unsupported() -> None:
    class Partial:
        """A memory record missing the field the probe wants."""

        total = 100

    probe = SystemHostProbe(usage=lambda _anchor: Usage(), memory=Partial)
    assert probe.summary(()).available_memory_bytes.availability is Availability.UNSUPPORTED


def test_the_real_host_probe_answers_on_this_machine() -> None:
    summary = system_host_probe().summary(())
    assert summary.logical_cpus.value


# ---------------------------------------------------------------------------
# The thread probe
# ---------------------------------------------------------------------------


def test_the_thread_inventory_finds_the_main_thread() -> None:
    summary = SystemThreadProbe().summary()
    assert summary.count >= 1
    assert any(thread.main for thread in summary.threads)


def test_a_worker_thread_appears_and_its_daemon_flag_is_recorded() -> None:
    started = threading.Event()
    release = threading.Event()

    def wait() -> None:
        started.set()
        release.wait(timeout=5)

    worker = threading.Thread(target=wait, name="globin-test-worker", daemon=True)
    worker.start()
    try:
        started.wait(timeout=5)
        summary = SystemThreadProbe().summary()
        found = [thread for thread in summary.threads if thread.name == "globin-test-worker"]
        assert found
        assert found[0].daemon
        assert found[0].alive
    finally:
        release.set()
        worker.join(timeout=5)

    after = SystemThreadProbe().summary()
    assert not [thread for thread in after.threads if thread.name == "globin-test-worker"]


def test_the_inventory_is_ordered_so_two_readings_serialise_the_same() -> None:
    probe = SystemThreadProbe()
    assert [thread.name for thread in probe.summary().threads] == [
        thread.name for thread in probe.summary().threads
    ]


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        pytest.param("worker", "worker", id="ordinary"),
        pytest.param("  ", SANITISED, id="blank"),
        pytest.param("a\x01b", "ab", id="control-character"),
        pytest.param("x" * 200, "x" * 64, id="bounded"),
    ],
)
def test_a_thread_name_is_sanitised_and_bounded(given: str, expected: str) -> None:
    """A dependency is free to put anything in a thread name."""
    assert _sanitised_name(given) == expected


def test_the_main_thread_is_recognised_by_the_interpreters_own_name() -> None:
    assert threading.main_thread().name == MAIN_THREAD_NAME


# ---------------------------------------------------------------------------
# The memory probe
# ---------------------------------------------------------------------------


class FakeTracer:
    """A tracemalloc stand-in that records what it was asked to do."""

    def __init__(self, *, tracing: bool = False) -> None:
        """Start out tracing or not, and record what is asked of us."""
        self.tracing = tracing
        self.started_with: int | None = None
        self.stopped = False

    def is_tracing(self) -> bool:
        """Whether tracing is on."""
        return self.tracing

    def start(self, depth: int) -> None:
        """Begin tracing at the given frame depth."""
        self.tracing = True
        self.started_with = depth

    def stop(self) -> None:
        """End tracing."""
        self.tracing = False
        self.stopped = True

    def get_traced_memory(self) -> tuple[int, int]:
        """Current and peak traced size."""
        return (100, 200)

    def get_traceback_limit(self) -> int:
        """The configured frame depth."""
        return 8

    def get_tracemalloc_memory(self) -> int:
        """What the tracer itself costs."""
        return 900

    def take_snapshot(self) -> Any:
        """One allocation snapshot, with a single indexable traceback."""

        class Frame:
            """One traceback frame, as tracemalloc reports it."""

            filename = "somewhere/else/mod.py"
            lineno = 3

        class Statistic:
            """One allocation site."""

            size = 10
            count = 2
            traceback = (Frame(),)

        class Snapshot:
            """What `take_snapshot` returns."""

            @staticmethod
            def statistics(_key: str) -> list[Any]:
                """The sites, largest first."""
                return [Statistic()]

        return Snapshot()


def test_tracing_is_off_by_default_and_says_so_without_reporting_zeroes() -> None:
    summary = TracemallocProbe(FakeTracer()).summary(3)
    assert not summary.tracing
    assert not summary.current_bytes.measured


def test_tracing_reports_current_peak_and_its_own_overhead() -> None:
    summary = TracemallocProbe(FakeTracer(tracing=True)).summary(3)
    assert summary.tracing
    assert summary.current_bytes.value == 100
    assert summary.peak_bytes.value == 200
    assert summary.overhead_bytes.value == 900
    assert summary.frame_depth.value == 8


def test_the_configured_frame_depth_reaches_the_tracer() -> None:
    tracer = FakeTracer()
    TracemallocProbe(tracer).start(5)
    assert tracer.started_with == 5


def test_a_probe_never_stops_a_tracer_it_did_not_start() -> None:
    """Tracing is process-global state.

    Stopping it unconditionally would silently disable tracing an operator had
    enabled for their own reasons.
    """
    tracer = FakeTracer(tracing=True)
    probe = TracemallocProbe(tracer)
    probe.start(4)
    probe.stop()
    assert not tracer.stopped
    assert tracer.tracing


def test_a_probe_stops_a_tracer_it_did_start() -> None:
    tracer = FakeTracer()
    probe = TracemallocProbe(tracer)
    probe.start(4)
    probe.stop()
    assert tracer.stopped


def test_the_top_is_bounded_and_its_locations_name_no_person() -> None:
    summary = TracemallocProbe(FakeTracer(tracing=True)).summary(1)
    assert len(summary.top) == 1
    assert "\\Users\\" not in summary.top[0].location


def test_the_real_tracer_reports_a_sanitised_location() -> None:
    probe = TracemallocProbe(tracemalloc)
    probe.start(4)
    try:
        summary = probe.summary(3)
        assert summary.tracing
        assert all(":" in site.location for site in summary.top)
    finally:
        probe.stop()


def test_a_module_under_the_package_is_named_relative_to_it() -> None:
    here = str(Path(__file__).resolve().parents[2] / "src" / "globin" / "domain" / "health.py")
    assert relative_location(here).startswith("globin/")


def test_an_unattributable_path_is_reduced_to_its_filename() -> None:
    assert relative_location("Z:/somewhere/private/mod.py") == "mod.py"


# ---------------------------------------------------------------------------
# The platform, tree, lifecycle and logging probes
# ---------------------------------------------------------------------------


def test_the_platform_probe_carries_nothing_identifying_a_person() -> None:
    summary = SystemPlatformProbe().summary()
    assert summary.implementation
    assert summary.system
    assert not hasattr(summary, "node")


def test_the_tree_probe_reports_a_prepared_tree_as_usable(tmp_path: Path) -> None:
    layout = RuntimeLayout()
    for area in layout.areas():
        (tmp_path / layout.segment_for(area)).mkdir(parents=True)
    summary = FilesystemTreeProbe(root=tmp_path, layout=layout).summary()
    assert summary.root_present
    assert all(present and directory for _n, present, directory, _w, _i in summary.areas)
    assert all(inside for *_rest, inside in summary.areas)


def test_the_tree_probe_reports_a_missing_area(tmp_path: Path) -> None:
    layout = RuntimeLayout()
    summary = FilesystemTreeProbe(root=tmp_path, layout=layout).summary()
    assert not any(present for _n, present, *_rest in summary.areas)


def test_the_tree_probe_reports_an_unresolvable_root() -> None:
    summary = FilesystemTreeProbe(root=Path("\x00"), layout=RuntimeLayout()).summary()
    assert not summary.root_present


class FakeLock:
    """An instance lock that reports whatever it was told to."""

    def __init__(self, problem: str = "") -> None:
        """Record what the operating system will say."""
        self._problem = problem

    def probe(self) -> str:
        """Acquire and release, reporting the problem if there was one."""
        return self._problem


class FakeStore:
    """A state store holding documents in memory."""

    def __init__(self, documents: dict[str, object] | None = None) -> None:
        """Hold the documents this store will answer with."""
        self._documents = documents or {}

    def read(self, _area: RuntimeArea, name: str) -> object:
        """One document, or the exception it was told to raise."""
        value = self._documents.get(name)
        if isinstance(value, Exception):
            raise value
        return value


def lifecycle_probe(store: FakeStore, lock: FakeLock) -> StateLifecycleProbe:
    """A lifecycle probe over the given doubles."""
    return StateLifecycleProbe(
        store=store,
        lock=lock,
        area=RuntimeArea.STATE,
        lifecycle_file="lifecycle.json",
        instance_file="instance.json",
    )


def test_an_available_lock_is_reported_as_held() -> None:
    summary = lifecycle_probe(FakeStore(), FakeLock()).summary()
    assert summary.lock_held
    assert summary.previous_ended_cleanly is None


def test_a_lock_held_elsewhere_carries_the_operating_systems_words() -> None:
    summary = lifecycle_probe(FakeStore(), FakeLock("in use")).summary()
    assert not summary.lock_held
    assert summary.lock_problem == "in use"


def test_a_previous_run_that_finished_is_reported_as_clean() -> None:
    store = FakeStore(
        {
            "lifecycle.json": {"status": "stopped", "finished_at": "2026-01-01T00:00:00+00:00"},
            "instance.json": {"instance_id": "abc"},
        }
    )
    summary = lifecycle_probe(store, FakeLock()).summary()
    assert summary.previous_ended_cleanly is True
    assert summary.instance_id == "abc"
    assert summary.status == "stopped"


def test_a_previous_run_that_did_not_finish_is_reported_as_unclean() -> None:
    store = FakeStore({"lifecycle.json": {"status": "running"}})
    assert lifecycle_probe(store, FakeLock()).summary().previous_ended_cleanly is False


def test_a_corrupt_state_document_is_treated_as_absent_rather_than_raised() -> None:
    """Reported as absent rather than raised.

    A run whose predecessor left a truncated file is exactly the situation
    somebody is taking a snapshot to understand.
    """
    store = FakeStore({"lifecycle.json": ValueError("truncated")})
    assert lifecycle_probe(store, FakeLock()).summary().previous_ended_cleanly is None


def test_the_logging_probe_reports_not_configured_by_default() -> None:
    summary = DiagnosticsStateProbe().summary()
    assert summary.state is LoggingState.NOT_CONFIGURED
    assert not summary.rotation_max_bytes.measured


def test_the_logging_probe_reports_a_running_subsystem() -> None:
    summary = DiagnosticsStateProbe(
        state=LoggingState.RUNNING,
        minimum_severity="DEBUG",
        destination="logs/globin.log",
        rotation_max_bytes=4096,
        rotation_backup_count=2,
    ).summary()
    assert summary.state is LoggingState.RUNNING
    assert summary.rotation_max_bytes.value == 4096


def test_the_snapshot_document_refuses_anything_that_is_not_a_snapshot() -> None:
    with pytest.raises(TypeError, match="RuntimeHealthSnapshot"):
        snapshot_document(object())
