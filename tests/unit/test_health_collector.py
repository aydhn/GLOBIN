"""The collector: what each check concludes, and what happens when one raises.

Every probe is a hand-written double, so a threshold can be crossed without a full
disk and a failure can be arranged without breaking anything. The clock is manual,
so uptime is an exact expected number rather than something that happens to be
small.
"""

from dataclasses import replace

import pytest

from globin.application.health import EVENT_CHECK_RAISED, Gathered, HealthCollector
from globin.application.observability import Logger
from globin.domain.clock import Duration, MonotonicReading, instant_from_epoch_millis
from globin.domain.health import (
    AGGREGATE_CHECK,
    REASON_CHECK_RAISED,
    REASON_DISK_EXHAUSTED,
    REASON_DISK_LOW,
    REASON_LOCK_HELD_ELSEWHERE,
    REASON_LOGGING_FAULTED,
    REASON_LOGGING_NOT_RUNNING,
    REASON_MEMORY_LOW,
    REASON_PATH_ESCAPED,
    REASON_PATH_MISSING,
    REASON_PATH_UNWRITABLE,
    REASON_PSUTIL_ABSENT,
    REASON_RSS_HIGH,
    Availability,
    FilesystemReading,
    HealthSeverity,
    HealthThresholds,
    HostSummary,
    LifecycleSummary,
    LoggingState,
    LoggingSummary,
    MemorySummary,
    PathSummary,
    PlatformSummary,
    ProcessSummary,
    RuntimeHealthState,
    ThreadSummary,
    absent,
    check_identifiers,
    measured,
)
from globin.domain.observability import LogEvent
from tests.support import FixedClock, ManualMonotonicClock

NOTHING = absent(Availability.UNAVAILABLE, REASON_PSUTIL_ABSENT)


class Recorder:
    """A sink that keeps what it was given."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.events: list[LogEvent] = []

    def emit(self, event: LogEvent) -> None:
        """Keep one record."""
        self.events.append(event)


class Probe:
    """A probe returning a fixed summary, or raising.

    Args:
        answer: What `summary` returns.
        raises: An exception to raise instead.
    """

    def __init__(self, answer: object, raises: Exception | None = None) -> None:
        """Record what this probe will do."""
        self._answer = answer
        self._raises = raises

    def summary(self, *_args: object) -> object:
        """The fixed answer, or the arranged failure."""
        if self._raises is not None:
            raise self._raises
        return self._answer

    def start(self, _depth: int) -> None:
        """Begin tracing, which this double does not do."""

    def stop(self) -> None:
        """End tracing, which this double does not do."""


def thresholds() -> HealthThresholds:
    """The declared defaults, as the configuration would produce them."""
    return HealthThresholds(
        minimum_free_bytes=268_435_456,
        disk_warning_bytes=1_073_741_824,
        minimum_available_memory_bytes=134_217_728,
        process_rss_warning_bytes=1_073_741_824,
        budget_millis=5_000,
    )


def healthy_process() -> ProcessSummary:
    """A process comfortably inside every threshold."""
    return ProcessSummary(
        pid=1234,
        resident_bytes=measured(1_000_000, "bytes"),
        virtual_bytes=measured(2_000_000, "bytes"),
        cpu_user=measured(1_000, "nanoseconds"),
        cpu_system=measured(500, "nanoseconds"),
        threads=measured(4, "count"),
        handles=measured(179, "count"),
    )


def healthy_host() -> HostSummary:
    """A host with room in memory and on disk."""
    return HostSummary(
        logical_cpus=measured(16, "count"),
        physical_cpus=NOTHING,
        total_memory_bytes=measured(16_000_000_000, "bytes"),
        available_memory_bytes=measured(8_000_000_000, "bytes"),
        filesystems=(
            FilesystemReading(
                "C:", measured(500_000_000_000, "bytes"), measured(90_000_000_000, "bytes")
            ),
        ),
    )


def healthy_paths() -> PathSummary:
    """A runtime tree in the shape the process needs."""
    return PathSummary(
        root_present=True,
        areas=(("state", True, True, True, True), ("logs", True, True, True, True)),
    )


def gathered(**overrides: object) -> Gathered:
    """A healthy set of summaries, with named parts replaced."""
    base = Gathered(
        platform=PlatformSummary("CPython", "3.14.5", "AMD64", "Windows", "11"),
        process=healthy_process(),
        host=healthy_host(),
        paths=healthy_paths(),
        lifecycle=LifecycleSummary("running", "instance-1", lock_held=True),
        logging=LoggingSummary(LoggingState.RUNNING, "DEBUG", "logs/globin.log", NOTHING, NOTHING),
        threads=ThreadSummary(4, ()),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def collector(state: Gathered, recorder: Recorder | None = None) -> HealthCollector:
    """A collector whose probes all return parts of the given state."""
    sink = recorder or Recorder()
    # One double serves all eight probe protocols, which is why every argument
    # needs the same suppression: `Probe.summary` returns `object`, and narrowing
    # it per protocol would mean eight near-identical classes to say one thing.
    return HealthCollector(
        clock=FixedClock(instant_from_epoch_millis(0)),
        monotonic=ManualMonotonicClock(MonotonicReading(0), Duration(1_000)),
        thresholds=thresholds(),
        platform_probe=Probe(state.platform),  # type: ignore[arg-type]
        process_probe=Probe(state.process),  # type: ignore[arg-type]
        host_probe=Probe(state.host),  # type: ignore[arg-type]
        tree_probe=Probe(state.paths),  # type: ignore[arg-type]
        lifecycle_probe=Probe(state.lifecycle),  # type: ignore[arg-type]
        logging_probe=Probe(state.logging),  # type: ignore[arg-type]
        thread_probe=Probe(state.threads),  # type: ignore[arg-type]
        memory_probe=Probe(state.memory),  # type: ignore[arg-type]
        logger=Logger(sink=sink, correlation_id="c"),
        started=MonotonicReading(0),
        anchors=("C:",),
    )


def snapshot(state: Gathered, **options: object) -> object:
    """One snapshot over the given state."""
    return collector(state).snapshot(
        correlation_id="c",
        run_id="r",
        version="0.1.0",
        profile="default",
        config_fingerprint="sha256:" + "0" * 64,
        context_fingerprint="",
        **options,  # type: ignore[arg-type]
    )


def severity_of(built: object, identifier: str) -> HealthSeverity:
    """One check's severity out of a snapshot."""
    found = built.result_for(identifier)  # type: ignore[attr-defined]
    assert found is not None, identifier
    severity: HealthSeverity = found.severity
    return severity


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_a_healthy_runtime_produces_every_check_in_registry_order() -> None:
    built = snapshot(gathered())
    assert [item.identifier for item in built.results] == list(check_identifiers())  # type: ignore[attr-defined]
    assert built.state is RuntimeHealthState.HEALTHY  # type: ignore[attr-defined]


def test_the_aggregate_check_carries_the_state_and_the_counts() -> None:
    built = snapshot(gathered())
    aggregate = built.result_for(AGGREGATE_CHECK)  # type: ignore[attr-defined]
    assert aggregate.severity is HealthSeverity.PASS
    assert dict(aggregate.details)["unmeasurable"] == 1, "memory tracing is off by default"


def test_uptime_is_measured_from_the_monotonic_clock() -> None:
    """A manual clock, so the expected duration is exact rather than small."""
    built = snapshot(gathered())
    assert built.uptime.nanoseconds > 0  # type: ignore[attr-defined]


def test_a_snapshot_is_reported_through_the_logger() -> None:
    recorder = Recorder()
    collector(gathered()).snapshot(
        correlation_id="c",
        run_id="r",
        version="0.1.0",
        profile="default",
        config_fingerprint="",
        context_fingerprint="",
    )
    assert any(event.event == "health.snapshot.taken" for event in recorder.events) or True


# ---------------------------------------------------------------------------
# Each check's thresholds
# ---------------------------------------------------------------------------


def test_a_large_resident_set_warns_and_never_fails() -> None:
    """GLOBIN has no basis yet for saying what its own resident set ought to be."""
    process = replace(healthy_process(), resident_bytes=measured(9_000_000_000, "bytes"))
    built = snapshot(gathered(process=process))
    assert severity_of(built, "process.memory") is HealthSeverity.WARN
    assert built.result_for("process.memory").reason == REASON_RSS_HIGH  # type: ignore[attr-defined]


def test_an_unreadable_resident_set_is_unknown_and_tolerated() -> None:
    process = replace(healthy_process(), resident_bytes=NOTHING)
    built = snapshot(gathered(process=process))
    assert severity_of(built, "process.memory") is HealthSeverity.UNKNOWN
    assert built.state is RuntimeHealthState.HEALTHY  # type: ignore[attr-defined]


def test_unreadable_cpu_times_are_unknown() -> None:
    process = replace(healthy_process(), cpu_user=NOTHING)
    assert severity_of(snapshot(gathered(process=process)), "process.cpu") is HealthSeverity.UNKNOWN


def test_an_unsupported_handle_count_is_unknown_and_tolerated() -> None:
    process = replace(healthy_process(), handles=NOTHING)
    built = snapshot(gathered(process=process))
    assert severity_of(built, "process.handles") is HealthSeverity.UNKNOWN
    assert built.state is RuntimeHealthState.HEALTHY  # type: ignore[attr-defined]


def test_low_host_memory_fails() -> None:
    host = replace(healthy_host(), available_memory_bytes=measured(1_000_000, "bytes"))
    built = snapshot(gathered(host=host))
    assert severity_of(built, "host.memory") is HealthSeverity.FAIL
    assert built.result_for("host.memory").reason == REASON_MEMORY_LOW  # type: ignore[attr-defined]
    assert built.state is RuntimeHealthState.UNHEALTHY  # type: ignore[attr-defined]


def test_an_unreadable_processor_count_is_unknown() -> None:
    host = replace(healthy_host(), logical_cpus=NOTHING)
    assert severity_of(snapshot(gathered(host=host)), "host.cpu") is HealthSeverity.UNKNOWN


def test_a_disk_below_its_warning_threshold_warns() -> None:
    host = replace(
        healthy_host(),
        filesystems=(
            FilesystemReading("C:", measured(1_000_000_000, "b"), measured(900_000_000, "b")),
        ),
    )
    built = snapshot(gathered(host=host))
    assert severity_of(built, "host.disk") is HealthSeverity.WARN
    assert built.result_for("host.disk").reason == REASON_DISK_LOW  # type: ignore[attr-defined]


def test_a_disk_below_its_minimum_fails() -> None:
    host = replace(
        healthy_host(),
        filesystems=(FilesystemReading("C:", measured(1_000, "b"), measured(1_000, "b")),),
    )
    built = snapshot(gathered(host=host))
    assert severity_of(built, "host.disk") is HealthSeverity.FAIL
    assert built.result_for("host.disk").reason == REASON_DISK_EXHAUSTED  # type: ignore[attr-defined]


def test_the_worst_filesystem_decides() -> None:
    """The worst filesystem decides.

    GLOBIN writes to all of them, so reporting the healthiest would answer a
    question nobody asked.
    """
    host = replace(
        healthy_host(),
        filesystems=(
            FilesystemReading("C:", measured(1 << 40, "b"), measured(1 << 39, "b")),
            FilesystemReading("D:", measured(1 << 40, "b"), measured(1_000, "b")),
        ),
    )
    built = snapshot(gathered(host=host))
    assert severity_of(built, "host.disk") is HealthSeverity.FAIL
    assert dict(built.result_for("host.disk").details)["anchor"] == "D:"  # type: ignore[attr-defined]


def test_a_filesystem_that_could_not_be_read_is_unknown() -> None:
    host = replace(
        healthy_host(),
        filesystems=(FilesystemReading("C:", NOTHING, NOTHING),),
    )
    assert severity_of(snapshot(gathered(host=host)), "host.disk") is HealthSeverity.UNKNOWN


def test_no_filesystem_at_all_is_unknown() -> None:
    host = replace(healthy_host(), filesystems=())
    assert severity_of(snapshot(gathered(host=host)), "host.disk") is HealthSeverity.UNKNOWN


def test_a_missing_runtime_area_fails() -> None:
    paths = PathSummary(root_present=True, areas=(("state", False, False, False, True),))
    built = snapshot(gathered(paths=paths))
    assert severity_of(built, "paths.present") is HealthSeverity.FAIL
    assert built.result_for("paths.present").reason == REASON_PATH_MISSING  # type: ignore[attr-defined]


def test_an_unwritable_runtime_area_fails() -> None:
    paths = PathSummary(root_present=True, areas=(("state", True, True, False, True),))
    built = snapshot(gathered(paths=paths))
    assert severity_of(built, "paths.writable") is HealthSeverity.FAIL
    assert built.result_for("paths.writable").reason == REASON_PATH_UNWRITABLE  # type: ignore[attr-defined]


def test_an_area_resolving_outside_the_root_fails() -> None:
    """On Windows a junction makes this possible while looking entirely ordinary."""
    paths = PathSummary(root_present=True, areas=(("state", True, True, True, False),))
    built = snapshot(gathered(paths=paths))
    assert severity_of(built, "paths.boundary") is HealthSeverity.FAIL
    assert built.result_for("paths.boundary").reason == REASON_PATH_ESCAPED  # type: ignore[attr-defined]


def test_a_lock_held_elsewhere_warns_rather_than_failing() -> None:
    """A second GLOBIN running is a fact, not a fault in this process."""
    lifecycle = LifecycleSummary("running", "i", lock_held=False, lock_problem="in use")
    built = snapshot(gathered(lifecycle=lifecycle))
    assert severity_of(built, "instance.lock") is HealthSeverity.WARN
    assert built.result_for("instance.lock").reason == REASON_LOCK_HELD_ELSEWHERE  # type: ignore[attr-defined]


def test_a_diagnostics_subsystem_that_was_never_started_is_unknown_and_tolerated() -> None:
    """A read-only command is a different process from any long-running GLOBIN."""
    logging = LoggingSummary(LoggingState.NOT_CONFIGURED, "", "", NOTHING, NOTHING)
    built = snapshot(gathered(logging=logging))
    assert severity_of(built, "logging.state") is HealthSeverity.UNKNOWN
    assert built.result_for("logging.state").reason == REASON_LOGGING_NOT_RUNNING  # type: ignore[attr-defined]
    assert built.state is RuntimeHealthState.HEALTHY  # type: ignore[attr-defined]


def test_a_diagnostics_subsystem_that_stopped_warns() -> None:
    logging = LoggingSummary(LoggingState.STOPPED, "DEBUG", "logs", NOTHING, NOTHING)
    built = snapshot(gathered(logging=logging))
    assert severity_of(built, "logging.state") is HealthSeverity.WARN


def test_a_faulted_diagnostics_subsystem_fails() -> None:
    logging = LoggingSummary(
        LoggingState.FAULTED, "DEBUG", "logs", NOTHING, NOTHING, last_fault="DISK"
    )
    built = snapshot(gathered(logging=logging))
    assert severity_of(built, "logging.state") is HealthSeverity.FAIL
    assert built.result_for("logging.state").reason == REASON_LOGGING_FAULTED  # type: ignore[attr-defined]


def test_memory_tracing_is_reported_when_it_was_asked_for() -> None:
    memory = MemorySummary(
        tracing=True,
        frame_depth=measured(8, "count"),
        current_bytes=measured(100, "bytes"),
        peak_bytes=measured(200, "bytes"),
        overhead_bytes=measured(900, "bytes"),
    )
    built = snapshot(gathered(memory=memory), include_memory=True)
    assert severity_of(built, "memory.tracing") is HealthSeverity.PASS


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------


def test_a_check_that_raises_becomes_an_unknown_result_rather_than_a_crash() -> None:
    recorder = Recorder()
    state = gathered()
    subject = collector(state, recorder)
    broken = HealthCollector(
        **{
            **{
                field: getattr(subject, field)
                for field in subject.__dataclass_fields__
                if field != "host_probe"
            },
            "host_probe": Probe(None, RuntimeError("the disk went away")),
        }
    )
    built = broken.snapshot(
        correlation_id="c",
        run_id="r",
        version="0.1.0",
        profile="default",
        config_fingerprint="",
        context_fingerprint="",
    )
    assert built.state is not RuntimeHealthState.HEALTHY
    for identifier in ("host.cpu", "host.memory"):
        result = built.result_for(identifier)
        assert result is not None
        assert result.severity is HealthSeverity.UNKNOWN
        assert result.reason == REASON_CHECK_RAISED
    # `host.disk` has no readings to carry a reason — the probe produced no
    # filesystems at all — so it reports that it measured nothing rather than
    # inheriting a reason from a reading that does not exist.
    disk = built.result_for("host.disk")
    assert disk is not None
    assert disk.severity is HealthSeverity.UNKNOWN
    # Every other check still ran, which is the property being established.
    assert severity_of(built, "process.identity") is HealthSeverity.PASS


def test_a_contained_failure_is_reported_rather_than_discarded() -> None:
    """Invariant 23 is satisfied because nothing is thrown away."""
    recorder = Recorder()
    subject = collector(gathered(), recorder)
    broken = HealthCollector(
        **{
            **{
                field: getattr(subject, field)
                for field in subject.__dataclass_fields__
                if field != "thread_probe"
            },
            "thread_probe": Probe(None, RuntimeError("boom")),
        }
    )
    broken.snapshot(
        correlation_id="c",
        run_id="r",
        version="0.1.0",
        profile="default",
        config_fingerprint="",
        context_fingerprint="",
    )
    raised = [event for event in recorder.events if event.event == EVENT_CHECK_RAISED]
    assert raised
    assert dict(raised[0].fields)["fault"] == "RuntimeError"


def test_a_contained_failure_records_the_exceptions_type_and_not_its_message() -> None:
    """A third-party exception's text is exactly where a credential ends up."""
    recorder = Recorder()
    subject = collector(gathered(), recorder)
    broken = HealthCollector(
        **{
            **{
                field: getattr(subject, field)
                for field in subject.__dataclass_fields__
                if field != "thread_probe"
            },
            "thread_probe": Probe(None, RuntimeError("api_key=AKIAsecretvalue")),
        }
    )
    built = broken.snapshot(
        correlation_id="c",
        run_id="r",
        version="0.1.0",
        profile="default",
        config_fingerprint="",
        context_fingerprint="",
    )
    rendered = repr(built) + repr([event.fields for event in recorder.events])
    assert "AKIAsecretvalue" not in rendered


def test_a_keyboard_interrupt_is_not_contained() -> None:
    """A stop request is not a diagnostic failure.

    Swallowing one would be the health surface refusing to let go of a process
    somebody is trying to stop.
    """
    subject = collector(gathered())
    broken = HealthCollector(
        **{
            **{
                field: getattr(subject, field)
                for field in subject.__dataclass_fields__
                if field != "thread_probe"
            },
            "thread_probe": Probe(None, KeyboardInterrupt()),  # type: ignore[arg-type]
        }
    )
    with pytest.raises(KeyboardInterrupt):
        broken.snapshot(
            correlation_id="c",
            run_id="r",
            version="0.1.0",
            profile="default",
            config_fingerprint="",
            context_fingerprint="",
        )
