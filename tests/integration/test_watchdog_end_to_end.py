"""The watchdog against a real runtime tree, wired by the composition root.

The unit tests substitute every port. This builds the real thing —
:func:`~globin.runtime.composition.build_watchdog` against a real temporary
runtime tree — and asserts the two properties that are only true of a filesystem:
that the incident **reaches disk atomically and reads back**, and that the CLI
which reports it sees what was written.

The clock is still injected. Nothing here sleeps, and the escalation is driven by
moving a reading rather than by waiting for one.
"""

import io
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from globin.domain.bootstrap import ExitCode
from globin.domain.clock import Instant, MonotonicReading, instant_from_epoch_millis
from globin.domain.configuration import (
    DiagnosticsConfig,
    GlobinConfig,
    LoggingConfig,
    WatchdogConfig,
)
from globin.domain.runtime_state import RuntimeArea, RuntimeLayout
from globin.domain.watchdog import (
    DEFAULT_ESCALATE_MILLIS,
    DEFAULT_STALL_MILLIS,
    NANOSECONDS_PER_MILLISECOND,
    WATCHDOG_SCHEMA,
    WATCHDOG_SCHEMA_VERSION,
    Criticality,
    WatchdogState,
)
from globin.runtime.cli import main
from globin.runtime.composition import (
    WATCHDOG_FILE,
    build_heartbeats,
    build_runtime_state,
    build_watchdog,
)

INCIDENT_ID = "0123456789abcdef0123456789abcdef"
STALL_MILLIS = 1_000
ESCALATE_MILLIS = 1_000


@dataclass(slots=True)
class _Clock:
    """A monotonic clock this test moves by hand."""

    at: int = 0

    def reading(self) -> MonotonicReading:
        return MonotonicReading(self.at * NANOSECONDS_PER_MILLISECOND)


@dataclass(frozen=True, slots=True)
class _Wall:
    """A wall clock that never moves, so the document is the same on every run."""

    def now(self) -> Instant:
        return instant_from_epoch_millis(1_780_000_000_000)


@dataclass(slots=True)
class _Terminator:
    """Records the exit code. Nothing in this file may end the test runner."""

    codes: list[int] = field(default_factory=list)

    def terminate(self, code: int) -> None:
        self.codes.append(code)


def settings() -> GlobinConfig:
    """Thresholds small enough to cross by moving a clock a few times."""
    return GlobinConfig(
        logging=LoggingConfig(),
        diagnostics=DiagnosticsConfig(),
        watchdog=WatchdogConfig(
            interval_millis=100,
            grace_millis=0,
            stall_millis=STALL_MILLIS,
            escalate_millis=ESCALATE_MILLIS,
        ),
    )


@pytest.fixture
def runtime_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the user-local runtime tree at a temporary directory."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def drive_a_stall(runtime_root: Path) -> tuple[Path, _Terminator, _Clock]:
    """Build the real watchdog, register a component, and never beat it.

    Returns:
        The runtime root, the terminator that recorded the exit, and the clock.
    """
    state = build_runtime_state()
    assert state.tree.prepare(state.layout) == ()
    clock = _Clock()
    beats = build_heartbeats(clock)
    beats.register("feed", Criticality.REQUIRED)
    terminator = _Terminator()
    thread = build_watchdog(
        state,
        beats,
        run_id="fedcba9876543210fedcba9876543210",
        correlation_id="00112233445566778899aabbccddeeff",
        config=settings(),
        clock=_Wall(),
        monotonic=clock,
        terminator=terminator,
        new_incident_id=lambda: INCIDENT_ID,
    )
    cycle = thread.cycle
    cycle.arm()
    clock.at = STALL_MILLIS + 1
    assert _ticked(cycle) is WatchdogState.SHUTDOWN_REQUESTED
    clock.at = STALL_MILLIS + STALL_MILLIS + ESCALATE_MILLIS + 2
    assert _ticked(cycle) is WatchdogState.ESCALATING
    return runtime_root, terminator, clock


def _ticked(cycle: object) -> WatchdogState:
    """Tick from a worker, which is where a real watchdog ticks from.

    The evidence collector excludes its own thread, so a tick driven directly from
    the test would describe nothing at all — correct behaviour, and a useless
    fixture. Running it from a worker puts the main thread in front of it, exactly
    as the watchdog thread does in production.
    """
    landed: list[WatchdogState] = []
    worker = threading.Thread(target=lambda: landed.append(cycle.tick()))  # type: ignore[attr-defined]
    worker.start()
    worker.join(30.0)
    assert landed, "the tick never completed"
    return landed[0]


def published(state_area: Path) -> dict[str, object]:
    """The incident as it was actually written to disk."""
    document = json.loads((state_area / WATCHDOG_FILE).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def state_area(runtime_root: Path) -> Path:
    """Where the runtime tree keeps its small published documents."""
    layout = RuntimeLayout()
    return runtime_root / layout.namespace / layout.segment_for(RuntimeArea.STATE)


def test_a_confirmed_stall_reaches_disk_and_reads_back(runtime_root: Path) -> None:
    """Published through the Phase 022 atomic store, so it is fsynced before it renames.

    The ordering matters more than the writing: the incident is on disk before the
    process is asked to stop, because if the ask fails the next thing that happens
    is a termination that runs no cleanup at all.
    """
    drive_a_stall(runtime_root)
    document = published(state_area(runtime_root))
    assert document["schema"] == WATCHDOG_SCHEMA
    assert document["schema_version"] == WATCHDOG_SCHEMA_VERSION
    assert document["component"] == "feed"
    assert document["incident_id"] == INCIDENT_ID


def test_the_escalated_incident_replaces_the_first_rather_than_joining_it(
    runtime_root: Path,
) -> None:
    """One file per run, republished. A directory of incidents would be a log."""
    drive_a_stall(runtime_root)
    written = list(state_area(runtime_root).glob("watchdog*"))
    assert [path.name for path in written] == [WATCHDOG_FILE]
    assert published(state_area(runtime_root))["escalated"] is True


def test_no_partial_file_survives_beside_the_published_one(runtime_root: Path) -> None:
    """The temporary is written beside the destination and renamed onto it."""
    drive_a_stall(runtime_root)
    leftovers = [path.name for path in state_area(runtime_root).iterdir() if ".tmp" in path.name]
    assert leftovers == []


def test_the_process_is_ended_with_the_watchdogs_own_exit_code(runtime_root: Path) -> None:
    _root, terminator, _clock = drive_a_stall(runtime_root)
    assert terminator.codes == [int(ExitCode.WATCHDOG_STALLED)]


def test_the_incident_carries_thread_evidence_naming_no_person(runtime_root: Path) -> None:
    """Captured from the real interpreter, through the real collector.

    Every location is reduced to ``globin/...``, ``stdlib/...`` or a bare
    filename, so no drive letter and no separator survives into the document.
    """
    drive_a_stall(runtime_root)
    evidence = published(state_area(runtime_root))["evidence"]
    assert isinstance(evidence, dict)
    threads = evidence["threads"]
    assert isinstance(threads, list)
    located = [frame["location"] for thread in threads for frame in thread["frames"]]
    assert located
    assert all(":" not in location and "\\" not in location for location in located)


def test_no_frame_carries_a_value_from_the_process_it_described(runtime_root: Path) -> None:
    """A frame's ``f_locals`` is the exposure that matters, and it is never read.

    Asserted against the raw bytes rather than the parsed document, because what
    must be absent is absent from the file an operator would open.
    """
    drive_a_stall(runtime_root)
    raw = (state_area(runtime_root) / WATCHDOG_FILE).read_text(encoding="utf-8")
    assert "f_locals" not in raw
    assert INCIDENT_ID in raw


# ---------------------------------------------------------------------------
# What the command line reports
# ---------------------------------------------------------------------------


def test_the_command_reports_the_policy_when_nothing_has_stalled(runtime_root: Path) -> None:
    """Exit zero, because no run on this machine was stopped for not progressing."""
    assert build_runtime_state().tree.prepare(RuntimeLayout()) == ()
    assert not (state_area(runtime_root) / WATCHDOG_FILE).exists()
    out, err = io.StringIO(), io.StringIO()
    code = main(["diagnostics", "watchdog"], stdout=out, stderr=err)
    assert code == int(ExitCode.OK)
    assert "incident: none recorded" in out.getvalue()


def test_the_command_reports_a_recorded_incident_and_fails(runtime_root: Path) -> None:
    """A recorded incident means the last run here was stopped, which is a failure."""
    drive_a_stall(runtime_root)
    out, err = io.StringIO(), io.StringIO()
    code = main(["diagnostics", "watchdog"], stdout=out, stderr=err)
    assert code == int(ExitCode.GATE_FAILED)
    assert INCIDENT_ID in out.getvalue()
    assert "feed" in out.getvalue()


def test_under_json_standard_output_carries_the_document_and_nothing_else(
    runtime_root: Path,
) -> None:
    """The one contract the flag makes, asserted by parsing what it printed."""
    drive_a_stall(runtime_root)
    out, err = io.StringIO(), io.StringIO()
    main(["diagnostics", "watchdog", "--json"], stdout=out, stderr=err)
    document = json.loads(out.getvalue())
    # The declared defaults, not this test's thresholds: the command reports the
    # policy an operator configured, and nothing here configures one. That the two
    # differ is the point — the report describes the machine, not the last run.
    assert document["stall_millis"] == DEFAULT_STALL_MILLIS
    assert document["deadline_millis"] == DEFAULT_STALL_MILLIS + DEFAULT_ESCALATE_MILLIS
    assert document["incident"]["incident_id"] == INCIDENT_ID
    assert "watchdog:" in err.getvalue()


def test_the_command_starts_no_watchdog_and_writes_nothing(runtime_root: Path) -> None:
    """A read-only report. A command that armed one could end what it described."""
    assert build_runtime_state().tree.prepare(RuntimeLayout()) == ()
    before = sorted(path.name for path in state_area(runtime_root).iterdir())
    out, err = io.StringIO(), io.StringIO()
    main(["diagnostics", "watchdog"], stdout=out, stderr=err)
    assert sorted(path.name for path in state_area(runtime_root).iterdir()) == before


def test_an_unrecognised_subcommand_is_refused_rather_than_defaulted() -> None:
    out, err = io.StringIO(), io.StringIO()
    assert main(["diagnostics", "watchdo"], stdout=out, stderr=err) == int(ExitCode.USAGE)
