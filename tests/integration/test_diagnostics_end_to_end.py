"""Diagnostics wired by the composition root, against a real runtime tree.

The unit tests exercise each adapter alone. These prove the assembled thing works:
a logger writing to a console *and* a bounded file in the Phase 022 runtime tree,
fault hooks installed and removed in the right order, and nothing left behind.

**The runtime tree is a temporary one.** `build_runtime_state` is handed an
environment whose `LOCALAPPDATA` points at `tmp_path`, which is the seam that
parameter's docstring exists for. No test here touches a real user profile.

**No test here installs a real process hook.** Every one passes a hook registry
backed by a dictionary. The suite's process-state guard watches the environment and
the working directory; it does not watch `sys.excepthook`, so a test that leaked one
would break a later test rather than itself.
"""

import io
import json
from pathlib import Path

import pytest

from globin.adapters.diagnostics import (
    DIAGNOSTICS_FILE,
    DIAGNOSTICS_SCHEMA,
    DIAGNOSTICS_SCHEMA_VERSION,
    FAULT_FILE_NAME,
    LOG_FILE_NAME,
    SYS_EXCEPTHOOK,
    SYS_UNRAISABLEHOOK,
    THREADING_EXCEPTHOOK,
    HookRegistry,
    RuntimeDiagnostics,
)
from globin.domain.configuration import DiagnosticsConfig, GlobinConfig, LoggingConfig
from globin.domain.observability import Severity
from globin.domain.runtime_state import RuntimeArea, RuntimeLayout
from globin.runtime.composition import build_diagnostics, build_runtime_state


def _explode(message: str) -> None:
    """Raise, so a caller can obtain an exception carrying a real traceback."""
    raise ValueError(message)


def caught(message: str) -> ValueError:
    """An exception with a genuine traceback attached.

    Args:
        message: What it says.

    Returns:
        The caught exception.
    """
    try:
        _explode(message)
    except ValueError as fault:
        return fault
    msg = "the helper did not raise"
    raise AssertionError(msg)


SENTINEL = "SENTINEL-VALUE-4f2a"
"""An obviously synthetic value, per `docs/TESTING_STRATEGY.md`."""


@pytest.fixture
def hooks() -> tuple[HookRegistry, dict[str, object]]:
    """A hook registry backed by a dictionary, and the dictionary."""
    store: dict[str, object] = {
        SYS_EXCEPTHOOK: "original-excepthook",
        SYS_UNRAISABLEHOOK: "original-unraisablehook",
        THREADING_EXCEPTHOOK: "original-threading-excepthook",
    }
    return HookRegistry(read=store.__getitem__, write=store.__setitem__), store


@pytest.fixture
def wired(
    tmp_path: Path, hooks: tuple[HookRegistry, dict[str, object]]
) -> tuple[RuntimeDiagnostics, Path, io.StringIO, dict[str, object]]:
    """Diagnostics wired against a prepared temporary runtime tree.

    Returns:
        The subsystem, the logs directory, the console stream, and the hook store.
    """
    registry, store = hooks
    state = build_runtime_state(environment={"LOCALAPPDATA": str(tmp_path)}, layout=RuntimeLayout())
    assert state.tree.prepare(state.layout) == ()
    console = io.StringIO()
    subject = build_diagnostics(
        state, correlation_id="corr-integration", stream=console, hooks=registry
    )
    logs = state.root / state.layout.segment_for(RuntimeArea.LOGS)
    return subject, logs, console, store


def records(logs: Path) -> list[dict[str, object]]:
    """Every record written to the live log file."""
    text = (logs / LOG_FILE_NAME).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_the_logs_area_is_created_by_preparing_the_tree(tmp_path: Path) -> None:
    """The fifth area exists for the same reason the other four do: something writes there."""
    state = build_runtime_state(environment={"LOCALAPPDATA": str(tmp_path)}, layout=RuntimeLayout())
    assert state.tree.prepare(state.layout) == ()
    assert (state.root / state.layout.segment_for(RuntimeArea.LOGS)).is_dir()


def test_a_record_reaches_both_the_console_and_the_file(
    wired: tuple[RuntimeDiagnostics, Path, io.StringIO, dict[str, object]],
) -> None:
    """One logger, one correlation id, two destinations."""
    subject, logs, console, _store = wired
    subject.start()
    subject.logger.info("bootstrap.started", phase=23)
    subject.stop()

    on_file = records(logs)
    assert [record["event"] for record in on_file] == ["bootstrap.started"]
    assert json.loads(console.getvalue().splitlines()[0])["event"] == "bootstrap.started"
    assert on_file[0]["correlation_id"] == "corr-integration"


def test_console_output_goes_nowhere_near_standard_output(
    wired: tuple[RuntimeDiagnostics, Path, io.StringIO, dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--json` promises standard output carries JSON and nothing else.

    A sink defaulting to standard output would break `render_json` for every
    machine consumer, which is why `build_diagnostics` resolves `sys.stderr`.
    """
    subject, _logs, _console, _store = wired
    subject.start()
    subject.logger.info("bootstrap.started")
    subject.stop()
    assert capsys.readouterr().out == ""


def test_a_credential_shaped_field_is_redacted_in_every_destination(
    wired: tuple[RuntimeDiagnostics, Path, io.StringIO, dict[str, object]],
) -> None:
    """The security property, asserted across the console, the file and a nested value.

    Redaction happens while the record is constructed, so no sink can leak by
    forgetting to call something — this proves the guarantee survives being fanned
    out to two of them.
    """
    subject, logs, console, _store = wired
    subject.start()
    subject.logger.info(
        "configuration.loaded",
        api_key=SENTINEL,
        detail={"authorization": SENTINEL, "safe": [{"secret": SENTINEL}]},
    )
    subject.stop()

    written = (logs / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert SENTINEL not in written
    assert SENTINEL not in console.getvalue()
    assert "[redacted]" in written


def test_starting_installs_the_hooks_and_stopping_puts_them_back(
    wired: tuple[RuntimeDiagnostics, Path, io.StringIO, dict[str, object]],
) -> None:
    """The mirror-image property the whole lifecycle rests on."""
    subject, _logs, _console, store = wired
    original = dict(store)
    subject.start()
    assert all(store[name] is not original[name] for name in original)
    subject.stop()
    assert store == original


def test_starting_twice_installs_one_set_of_hooks(
    wired: tuple[RuntimeDiagnostics, Path, io.StringIO, dict[str, object]],
) -> None:
    """A repeated initialisation must not lose the original hooks."""
    subject, _logs, _console, store = wired
    original = dict(store)
    subject.start()
    subject.start()
    subject.stop()
    assert store == original


def test_stopping_twice_is_safe(
    wired: tuple[RuntimeDiagnostics, Path, io.StringIO, dict[str, object]],
) -> None:
    """Shutdown runs every cleanup even when an earlier one raised."""
    subject, _logs, _console, _store = wired
    subject.start()
    subject.stop()
    subject.stop()


def test_an_uncaught_exception_is_written_to_the_file_before_shutdown(
    wired: tuple[RuntimeDiagnostics, Path, io.StringIO, dict[str, object]],
) -> None:
    """The reason this sink flushes every record.

    A process that dies badly must leave an explanation behind, and an explanation
    still sitting in a buffer when the interpreter is killed is not one. The file
    is read here *while the subsystem is still running*, which is what proves the
    record was flushed rather than merely queued.
    """
    subject, logs, _console, store = wired
    subject.start()
    fault = caught("something broke")
    store[SYS_EXCEPTHOOK](type(fault), fault, fault.__traceback__)  # type: ignore[operator]

    written = records(logs)
    subject.stop()
    assert written[-1]["event"] == "exception.uncaught"
    assert written[-1]["severity"] == "CRITICAL"


def test_the_fault_file_is_opened_and_removed_with_the_subsystem(
    wired: tuple[RuntimeDiagnostics, Path, io.StringIO, dict[str, object]],
) -> None:
    """`faulthandler` writes from a signal context, so the handle outlives the enabling."""
    subject, logs, _console, _store = wired
    subject.start()
    assert (logs / FAULT_FILE_NAME).exists()
    assert subject.faults.handle is not None
    subject.stop()
    assert subject.faults.handle is None


def test_the_file_rotates_inside_the_runtime_tree_and_stays_bounded(
    tmp_path: Path, hooks: tuple[HookRegistry, dict[str, object]]
) -> None:
    """The bound is what makes an appending area safe to add to the runtime tree.

    ADR-0059 named "a later phase writing something large" as the characteristic
    failure of adding a directory. This is the assertion that it did not happen.
    """
    registry, _store = hooks
    state = build_runtime_state(environment={"LOCALAPPDATA": str(tmp_path)}, layout=RuntimeLayout())
    assert state.tree.prepare(state.layout) == ()
    config = GlobinConfig(
        logging=LoggingConfig(
            min_severity=Severity.DEBUG, rotation_max_bytes=4096, rotation_backup_count=2
        ),
        diagnostics=DiagnosticsConfig(),
    )
    subject = build_diagnostics(
        state, correlation_id="corr-rotate", config=config, stream=io.StringIO(), hooks=registry
    )
    subject.start()
    for index in range(400):
        subject.logger.info("bootstrap.started", index=index, padding="x" * 200)
    subject.stop()

    logs = state.root / state.layout.segment_for(RuntimeArea.LOGS)
    written = sorted(path.name for path in logs.glob(f"{LOG_FILE_NAME}*"))
    assert written == [LOG_FILE_NAME, f"{LOG_FILE_NAME}.1", f"{LOG_FILE_NAME}.2"]
    total = sum(path.stat().st_size for path in logs.glob(f"{LOG_FILE_NAME}*"))
    assert total <= config.logging.rotation().ceiling_bytes()


def test_the_severity_threshold_is_honoured_by_both_destinations(
    tmp_path: Path, hooks: tuple[HookRegistry, dict[str, object]]
) -> None:
    """Filtering lives in a decorating sink, so a fan-out inherits it per destination."""
    registry, _store = hooks
    state = build_runtime_state(environment={"LOCALAPPDATA": str(tmp_path)}, layout=RuntimeLayout())
    assert state.tree.prepare(state.layout) == ()
    console = io.StringIO()
    subject = build_diagnostics(
        state,
        correlation_id="corr-threshold",
        config=GlobinConfig(
            logging=LoggingConfig(min_severity=Severity.ERROR),
            diagnostics=DiagnosticsConfig(),
        ),
        stream=console,
        hooks=registry,
    )
    subject.start()
    subject.logger.info("bootstrap.started")
    subject.logger.error("exception.uncaught")
    subject.stop()

    logs = state.root / state.layout.segment_for(RuntimeArea.LOGS)
    assert [record["event"] for record in records(logs)] == ["exception.uncaught"]
    assert "bootstrap.started" not in console.getvalue()


def test_the_evidence_record_describes_what_is_installed_and_carries_no_path(
    wired: tuple[RuntimeDiagnostics, Path, io.StringIO, dict[str, object]],
) -> None:
    """Evidence is published, so it names files rather than locating them.

    Every absolute path on a development host carries the account holder's name,
    which is the rule `tools/quality/runtime` follows about its own manifest.
    """
    subject, _logs, _console, _store = wired
    subject.start()
    record = subject.record()
    subject.stop()

    assert record["file_logging"] is True
    assert record["log_file"] == LOG_FILE_NAME
    assert record["standard_library_captured"] is True
    installed = record["hooks_installed"]
    assert isinstance(installed, list)
    assert sorted(installed) == [SYS_EXCEPTHOOK, SYS_UNRAISABLEHOOK, THREADING_EXCEPTHOOK]
    rendered = json.dumps(record)
    assert "C:\\" not in rendered
    assert "/Users/" not in rendered


def test_starting_publishes_the_evidence_atomically_into_the_state_area(
    tmp_path: Path, hooks: tuple[HookRegistry, dict[str, object]]
) -> None:
    """The record is written through the Phase 022 store, so it is never truncated.

    Published *after* the hooks are installed rather than before, so that what it
    describes is what is actually in place. A record written first would claim
    hooks that a failure between the two calls left uninstalled.
    """
    registry, _store = hooks
    state = build_runtime_state(environment={"LOCALAPPDATA": str(tmp_path)}, layout=RuntimeLayout())
    assert state.tree.prepare(state.layout) == ()
    subject = build_diagnostics(
        state, correlation_id="corr-evidence", stream=io.StringIO(), hooks=registry
    )
    subject.start()
    subject.stop()

    published = state.store.read(RuntimeArea.STATE, DIAGNOSTICS_FILE)
    assert published is not None
    assert published["schema"] == DIAGNOSTICS_SCHEMA
    assert published["schema_version"] == DIAGNOSTICS_SCHEMA_VERSION
    assert published["standard_library_captured"] is True
    assert published["faulthandler_enabled"] is True
    recorded = published["hooks_installed"]
    assert isinstance(recorded, list)
    assert sorted(recorded) == [SYS_EXCEPTHOOK, SYS_UNRAISABLEHOOK, THREADING_EXCEPTHOOK]


def test_the_published_evidence_carries_no_path_from_outside_the_repository(
    tmp_path: Path, hooks: tuple[HookRegistry, dict[str, object]]
) -> None:
    """It names files rather than locating them.

    Every absolute path on a development host carries the account holder's name,
    which is the rule `tools/quality/runtime` follows about its own manifest.
    """
    registry, _store = hooks
    state = build_runtime_state(environment={"LOCALAPPDATA": str(tmp_path)}, layout=RuntimeLayout())
    assert state.tree.prepare(state.layout) == ()
    subject = build_diagnostics(
        state, correlation_id="corr-evidence", stream=io.StringIO(), hooks=registry
    )
    subject.start()
    subject.stop()

    raw = (state.root / state.layout.segment_for(RuntimeArea.STATE) / DIAGNOSTICS_FILE).read_text(
        encoding="utf-8"
    )
    assert str(tmp_path) not in raw
    assert raw.endswith("\n")
    assert "\r" not in raw
