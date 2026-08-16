"""The diagnostics adapters: the file sink, the fault hooks and the bridge.

**No test here touches a real process hook.** Every one passes a
:class:`~globin.adapters.diagnostics.HookRegistry` backed by a dictionary, which
is the house pattern `PlatformShutdownSignals` established with its injected
``registrar``. A test that installed a real :data:`sys.excepthook` and then failed
before restoring it would break every test that ran afterwards, and the symptom
would appear in the victim rather than in the culprit — which is exactly the class
of failure ``tests/conftest.py``'s process-state guard exists to prevent and does
*not* watch for hooks.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from globin.adapters.diagnostics import (
    FAULT_FILE_NAME,
    LOG_FILE_NAME,
    SYS_EXCEPTHOOK,
    SYS_UNRAISABLEHOOK,
    THREADING_EXCEPTHOOK,
    WARNINGS_LOGGER,
    FanOutLogSink,
    FaultFile,
    HookRegistry,
    ProcessFaultHooks,
    RotatingFileLogSink,
    StandardLibraryBridge,
    StandardLibraryCapture,
    asyncio_exception_handler,
    severity_for,
    system_hooks,
)
from globin.application.observability import Logger
from globin.domain.clock import instant
from globin.domain.diagnostics import (
    EVENT_DEPENDENCY_RECORD,
    EVENT_EXCEPTION_THREAD_UNCAUGHT,
    EVENT_EXCEPTION_UNCAUGHT,
    EVENT_EXCEPTION_UNRAISABLE,
    EVENT_RUNTIME_WARNING,
    RotationPolicy,
)
from globin.domain.observability import LogEvent, Severity, log_event
from globin.errors import ValidationError
from tests.support import FixedClock

SENTINEL = "SENTINEL-VALUE-4f2a"
"""An obviously synthetic value, per `docs/TESTING_STRATEGY.md`."""

MOMENT = datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC)


class _Capture:
    """A sink that keeps what it was given."""

    def __init__(self) -> None:
        self.events: list[LogEvent] = []

    def emit(self, event: LogEvent) -> None:
        self.events.append(event)


class _Broken:
    """A sink that fails, for the paths where a reporter must survive its own sink."""

    def emit(self, _event: LogEvent) -> None:
        msg = "this sink is broken"
        raise RuntimeError(msg)


class _Args:
    """A stand-in for `threading.ExceptHookArgs`.

    A structseq rather than a named tuple in the standard library, carrying exactly
    `exc_type`, `exc_value`, `exc_traceback` and `thread` — measured on the target
    host and recorded as S-08. Read by attribute, so a double needs only these.
    """

    def __init__(self, exc_type: object, exc_value: object, thread: object = None) -> None:
        self.exc_type = exc_type
        self.exc_value = exc_value
        self.exc_traceback = None
        self.thread = thread
        self.object = thread


def clock() -> FixedClock:
    """A clock that always answers with one moment.

    Fixed rather than real, so the timestamps a test asserts on are the ones it
    chose. `docs/TESTING_STRATEGY.md`: timestamps are fixed values, never `now()`.
    """
    return FixedClock(instant(MOMENT))


def registry() -> tuple[HookRegistry, dict[str, object]]:
    """A hook registry backed by a dictionary, and the dictionary.

    Returns:
        The registry, and the store so a test can assert what was written.
    """
    store: dict[str, object] = {
        SYS_EXCEPTHOOK: "original-excepthook",
        SYS_UNRAISABLEHOOK: "original-unraisablehook",
        THREADING_EXCEPTHOOK: "original-threading-excepthook",
    }
    return HookRegistry(read=store.__getitem__, write=store.__setitem__), store


def sink_at(path: Path, *, max_bytes: int = 4096, backups: int = 2) -> RotatingFileLogSink:
    """A rotating sink writing into ``path``."""
    return RotatingFileLogSink(
        path=path,
        clock=clock(),
        policy=RotationPolicy(max_bytes=max_bytes, backup_count=backups),
        handle=None,
        written=0,
    )


def _explode(message: str) -> None:
    """Raise, so a caller can obtain an exception carrying a real traceback."""
    raise ValueError(message)


def caught(message: str) -> ValueError:
    """An exception with a genuine traceback attached.

    Args:
        message: What it says.

    Returns:
        The caught exception.

    Built by raising in a helper rather than inline, so the traceback under test
    is a real one rather than ``None`` — which is the interesting half of what a
    fault report records.
    """
    try:
        _explode(message)
    except ValueError as fault:
        return fault
    msg = "the helper did not raise"
    raise AssertionError(msg)


def an_event(event: str = "bootstrap.started", **fields: object) -> LogEvent:
    """One record."""
    return log_event(severity=Severity.INFO, event=event, correlation_id="corr-test", fields=fields)


# --------------------------------------------------------------------------
# The rotating file sink
# --------------------------------------------------------------------------


def test_records_are_json_lines_the_file_can_be_read_back_from(tmp_path: Path) -> None:
    """One object per line, so the log is readable by anything that parses JSON."""
    sink = sink_at(tmp_path / LOG_FILE_NAME)
    sink.open()
    sink.emit(an_event(phase=23))
    sink.close()
    lines = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["bootstrap.started"]


def test_a_sensitive_field_is_redacted_before_it_reaches_the_file(tmp_path: Path) -> None:
    """Redaction happens where the record is built, not where it is written.

    So a sink added in a later phase inherits it and cannot leak a credential by
    forgetting to call something. This asserts the property end to end for the one
    sink Phase 023 adds.
    """
    sink = sink_at(tmp_path / LOG_FILE_NAME)
    sink.open()
    sink.emit(an_event(api_key=SENTINEL, nested={"authorization": SENTINEL}))
    sink.close()
    written = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert SENTINEL not in written
    assert "[redacted]" in written


def test_the_file_is_appended_to_rather_than_truncated(tmp_path: Path) -> None:
    """A second run must not destroy the first run's explanation of why it needed one."""
    for _ in range(2):
        sink = sink_at(tmp_path / LOG_FILE_NAME)
        sink.open()
        sink.emit(an_event())
        sink.close()
    assert len((tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8").splitlines()) == 2


def test_the_file_rotates_when_it_would_exceed_its_bound(tmp_path: Path) -> None:
    """The bound is what makes the logs area safe to add to the runtime tree."""
    sink = sink_at(tmp_path / LOG_FILE_NAME, max_bytes=4096, backups=2)
    sink.open()
    for index in range(60):
        sink.emit(an_event(index=index, padding="x" * 200))
    sink.close()
    assert (tmp_path / f"{LOG_FILE_NAME}.1").exists()
    assert (tmp_path / LOG_FILE_NAME).stat().st_size <= 4096


def test_rotation_keeps_no_more_backups_than_it_declared(tmp_path: Path) -> None:
    """The ceiling is a promise, so the oldest is discarded rather than accumulated."""
    sink = sink_at(tmp_path / LOG_FILE_NAME, max_bytes=4096, backups=2)
    sink.open()
    for index in range(300):
        sink.emit(an_event(index=index, padding="x" * 200))
    sink.close()
    assert not (tmp_path / f"{LOG_FILE_NAME}.3").exists()
    assert sorted(p.name for p in tmp_path.glob(f"{LOG_FILE_NAME}*")) == [
        LOG_FILE_NAME,
        f"{LOG_FILE_NAME}.1",
        f"{LOG_FILE_NAME}.2",
    ]


def test_rotation_shifts_backups_newest_first_so_none_is_overwritten(tmp_path: Path) -> None:
    """Shifting in the other order loses the newest backup, which is the useful one."""
    path = tmp_path / LOG_FILE_NAME
    path.write_text("live\n", encoding="utf-8")
    path.with_name(f"{LOG_FILE_NAME}.1").write_text("first\n", encoding="utf-8")
    from globin.adapters.diagnostics import _shift_backups

    _shift_backups(path, 2)
    assert path.with_name(f"{LOG_FILE_NAME}.1").read_text(encoding="utf-8") == "live\n"
    assert path.with_name(f"{LOG_FILE_NAME}.2").read_text(encoding="utf-8") == "first\n"


def test_a_backup_count_of_zero_discards_rather_than_keeping(tmp_path: Path) -> None:
    """`rotate and discard` is a real choice for a machine short of disk."""
    path = tmp_path / LOG_FILE_NAME
    path.write_text("gone\n", encoding="utf-8")
    from globin.adapters.diagnostics import _shift_backups

    _shift_backups(path, 0)
    assert not path.exists()
    assert not path.with_name(f"{LOG_FILE_NAME}.1").exists()


def test_emitting_without_opening_says_so_rather_than_silently_dropping(tmp_path: Path) -> None:
    """A silent no-op would mean every record in a run went nowhere and nothing said so."""
    with pytest.raises(RuntimeError, match="was not opened"):
        sink_at(tmp_path / LOG_FILE_NAME).emit(an_event())


def test_closing_twice_is_safe(tmp_path: Path) -> None:
    """Shutdown runs every cleanup even when an earlier one raised."""
    sink = sink_at(tmp_path / LOG_FILE_NAME)
    sink.open()
    sink.close()
    sink.close()


# --------------------------------------------------------------------------
# The fan-out
# --------------------------------------------------------------------------


def test_a_fan_out_hands_each_record_to_every_sink() -> None:
    """One logger, one correlation id, several destinations."""
    first, second = _Capture(), _Capture()
    FanOutLogSink(sinks=(first, second)).emit(an_event())
    assert len(first.events) == len(second.events) == 1


def test_a_failing_sink_in_a_fan_out_propagates() -> None:
    """A failure in one destination is not hidden by the others.

    Invariant 23: a fan-out that quietly continued would make "the log is
    complete" true of some destinations and not others, with nothing recording
    which.
    """
    with pytest.raises(RuntimeError, match="broken"):
        FanOutLogSink(sinks=(_Broken(), _Capture())).emit(an_event())


# --------------------------------------------------------------------------
# The process fault hooks
# --------------------------------------------------------------------------


def hooks() -> tuple[ProcessFaultHooks, _Capture, dict[str, object]]:
    """Installed-ready hooks over a capturing sink."""
    capture = _Capture()
    store_registry, store = registry()
    return (
        ProcessFaultHooks(
            logger=Logger(sink=capture, correlation_id="corr-test"),
            registry=store_registry,
            previous={},
        ),
        capture,
        store,
    )


def test_installing_replaces_all_three_hooks_and_restoring_puts_them_back() -> None:
    """The property every other test here depends on being true."""
    subject, _capture, store = hooks()
    original = dict(store)
    subject.install()
    assert all(store[name] is not original[name] for name in original)
    subject.restore()
    assert store == original


def test_installing_twice_does_not_lose_the_original() -> None:
    """A second install recording GLOBIN's own hook would lose the original forever."""
    subject, _capture, store = hooks()
    original = dict(store)
    subject.install()
    subject.install()
    subject.restore()
    assert store == original


def test_restoring_without_installing_is_safe() -> None:
    subject, _capture, store = hooks()
    original = dict(store)
    subject.restore()
    assert store == original


def test_an_uncaught_exception_is_critical_and_keeps_its_type() -> None:
    """The severity `LOGGING_POLICY.md` reserves for GLOBIN being unable to work."""
    subject, capture, store = hooks()
    subject.install()
    fault = caught("boom")
    store[SYS_EXCEPTHOOK](type(fault), fault, fault.__traceback__)  # type: ignore[operator]
    subject.restore()
    (record,) = capture.events
    fields = dict(record.fields)
    assert record.event == EVENT_EXCEPTION_UNCAUGHT
    assert record.severity is Severity.CRITICAL
    assert fields["exception_type"] == "ValueError"
    assert "traceback" in fields


@pytest.mark.parametrize(
    "orderly",
    [pytest.param(SystemExit, id="system-exit"), pytest.param(KeyboardInterrupt, id="ctrl-c")],
)
def test_an_orderly_exit_is_recorded_but_not_as_a_catastrophe(orderly: type[BaseException]) -> None:
    """`CRITICAL` means GLOBIN cannot do its job. Being asked to stop is not that.

    An operator who sees CRITICAL on every Ctrl-C stops reading it, which costs
    more than the severity of one record.
    """
    subject, capture, store = hooks()
    subject.install()
    fault = orderly()
    store[SYS_EXCEPTHOOK](orderly, fault, None)  # type: ignore[operator]
    subject.restore()
    (record,) = capture.events
    assert record.severity is Severity.INFO
    assert dict(record.fields)["orderly"] is True


def test_a_thread_fault_records_the_thread_name() -> None:
    """Which thread died is the first thing an operator needs."""

    class _Thread:
        name = "worker-1"

    subject, capture, store = hooks()
    subject.install()
    store[THREADING_EXCEPTHOOK](_Args(ValueError, ValueError("x"), _Thread()))  # type: ignore[operator]
    subject.restore()
    (record,) = capture.events
    assert record.event == EVENT_EXCEPTION_THREAD_UNCAUGHT
    assert dict(record.fields)["thread_name"] == "worker-1"


def test_an_unraisable_fault_survives_an_object_whose_repr_raises() -> None:
    """An unraisable exception often comes from a `__del__`.

    The object being described is therefore part-destroyed, and its `__repr__` is
    the code most likely to raise a second time. A diagnostic layer that died here
    would replace the report with a worse one.
    """

    class _Hostile:
        def __repr__(self) -> str:
            msg = "this repr is broken"
            raise RuntimeError(msg)

    subject, capture, store = hooks()
    subject.install()
    args = _Args(ValueError, ValueError("x"))
    args.object = _Hostile()
    store[SYS_UNRAISABLEHOOK](args)  # type: ignore[operator]
    subject.restore()
    (record,) = capture.events
    assert record.event == EVENT_EXCEPTION_UNRAISABLE
    assert dict(record.fields)["object"] == "<unreprable>"


def test_an_exception_whose_str_raises_still_produces_a_report() -> None:
    """A half-constructed object behaves exactly like this."""

    class _HostileError(Exception):
        def __str__(self) -> str:
            msg = "this __str__ is broken"
            raise RuntimeError(msg)

    subject, capture, store = hooks()
    subject.install()
    fault = _HostileError()
    store[SYS_EXCEPTHOOK](_HostileError, fault, None)  # type: ignore[operator]
    subject.restore()
    (record,) = capture.events
    assert dict(record.fields)["exception_message"] == "<unprintable>"


def test_a_reporter_whose_sink_is_broken_falls_back_to_standard_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The one place GLOBIN swallows, and it is not silent.

    A hook runs when the process is already failing. An exception raised inside
    `sys.excepthook` is printed by the interpreter and discarded, so it cannot
    propagate anywhere useful and can only replace the report with a worse one.
    Invariant 23 is satisfied because the failure is reported, on the last channel
    still guaranteed to exist.
    """
    store_registry, store = registry()
    subject = ProcessFaultHooks(
        logger=Logger(sink=_Broken(), correlation_id="corr-test"),
        registry=store_registry,
        previous={},
    )
    subject.install()
    store[SYS_EXCEPTHOOK](ValueError, ValueError("x"), None)  # type: ignore[operator]
    subject.restore()
    assert "could not be logged" in capsys.readouterr().err


def test_the_real_registry_names_the_three_hooks_it_owns() -> None:
    """Reading is safe; nothing here writes. The write path is exercised through a double."""
    real = system_hooks()
    for name in (SYS_EXCEPTHOOK, SYS_UNRAISABLEHOOK, THREADING_EXCEPTHOOK):
        assert callable(real.read(name))


# --------------------------------------------------------------------------
# The asyncio handler
# --------------------------------------------------------------------------


def test_the_asyncio_handler_records_a_task_that_failed() -> None:
    """Built, not installed. GLOBIN starts no event loop until Phases 033-048."""
    capture = _Capture()
    handle = asyncio_exception_handler(Logger(sink=capture, correlation_id="corr-test"))
    context = {"message": "Task exception was never retrieved", "exception": ValueError("x")}
    handle(object(), context)
    (record,) = capture.events
    fields = dict(record.fields)
    assert record.severity is Severity.ERROR
    assert fields["exception_type"] == "ValueError"
    assert fields["source"] == "asyncio"


def test_the_asyncio_handler_survives_a_context_with_no_exception() -> None:
    """A loop reports some conditions with a message and no exception at all."""
    capture = _Capture()
    handle = asyncio_exception_handler(Logger(sink=capture, correlation_id="corr-test"))
    handle(object(), {"message": "socket.send() raised exception"})
    assert capture.events


# --------------------------------------------------------------------------
# The standard-library bridge
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("levelno", "expected"),
    [
        pytest.param(logging.DEBUG, Severity.DEBUG, id="debug"),
        pytest.param(logging.WARNING, Severity.WARNING, id="warning"),
        pytest.param(logging.CRITICAL, Severity.CRITICAL, id="critical"),
        pytest.param(25, Severity.INFO, id="an-invented-level-rounds-down"),
        pytest.param(5, Severity.DEBUG, id="below-everything"),
        pytest.param(100, Severity.CRITICAL, id="above-everything"),
    ],
)
def test_a_standard_library_level_maps_to_a_severity(levelno: int, expected: Severity) -> None:
    """Rounding down keeps a record an exact lookup would lose to a `ValueError`."""
    assert severity_for(levelno) is expected


def test_a_bridged_record_carries_its_originating_logger_as_a_field() -> None:
    """A logger name is chosen by somebody else and the event alphabet does not admit most."""
    capture = _Capture()
    bridge = StandardLibraryBridge(sink=capture, correlation_id="corr-test")
    bridge.emit(
        logging.LogRecord("numpy.core", logging.WARNING, "f.py", 1, "it went %s", ("wrong",), None)
    )
    (record,) = capture.events
    fields = dict(record.fields)
    assert record.event == EVENT_DEPENDENCY_RECORD
    assert fields["logger"] == "numpy.core"
    assert fields["message"] == "it went wrong"


def test_a_warning_is_bridged_under_the_runtime_warning_event() -> None:
    """`logging.captureWarnings` routes warnings through `py.warnings`, per S-09."""
    capture = _Capture()
    bridge = StandardLibraryBridge(sink=capture, correlation_id="corr-test")
    bridge.emit(
        logging.LogRecord(WARNINGS_LOGGER, logging.WARNING, "f.py", 1, "deprecated", None, None)
    )
    assert capture.events[0].event == EVENT_RUNTIME_WARNING


def test_a_bridged_record_with_a_sensitive_field_name_is_redacted() -> None:
    """The bridge builds a `LogEvent`, so it inherits redaction like every other sink."""
    capture = _Capture()
    bridge = StandardLibraryBridge(sink=capture, correlation_id="corr-test")
    bridge.emit(logging.LogRecord("lib", logging.INFO, "f.py", 1, "msg", None, None))
    assert capture.events


def test_a_bridge_whose_sink_fails_reports_through_handle_error() -> None:
    """Raising would push an exception back into a library that was merely logging."""
    bridge = StandardLibraryBridge(sink=_Broken(), correlation_id="corr-test")
    handled: list[logging.LogRecord] = []
    bridge.handleError = handled.append  # type: ignore[method-assign,assignment]
    record = logging.LogRecord("lib", logging.INFO, "f.py", 1, "msg", None, None)
    bridge.emit(record)
    assert handled == [record]


def test_capture_attaches_and_detaches_the_bridge_from_the_root_logger() -> None:
    """Installing and removing are mirror images, and both are idempotent.

    The root logger is process-global, so a bridge left attached would keep
    forwarding into a sink whose file has been closed.
    """
    bridge = StandardLibraryBridge(sink=_Capture(), correlation_id="corr-test")
    capture = StandardLibraryCapture(bridge=bridge, installed=False)
    root = logging.getLogger()
    try:
        capture.install()
        assert bridge in root.handlers
        capture.install()
        capture.remove()
        assert bridge not in root.handlers
        capture.remove()
    finally:
        root.removeHandler(bridge)
        logging.captureWarnings(capture=False)


# --------------------------------------------------------------------------
# The fault file
# --------------------------------------------------------------------------


def test_the_fault_file_is_opened_and_closed_in_the_declared_order(tmp_path: Path) -> None:
    """`faulthandler` writes from a signal context, so the handle must outlive it."""
    faults = FaultFile(path=tmp_path / FAULT_FILE_NAME, handle=None)
    faults.enable()
    opened = faults.handle
    assert opened is not None
    assert (tmp_path / FAULT_FILE_NAME).exists()
    faults.disable()
    assert faults.handle is None
    faults.disable()


def test_enabling_twice_keeps_one_handle(tmp_path: Path) -> None:
    """A second enable replacing the handle would leak the first."""
    faults = FaultFile(path=tmp_path / FAULT_FILE_NAME, handle=None)
    faults.enable()
    first = faults.handle
    faults.enable()
    assert faults.handle is first
    faults.disable()


# --------------------------------------------------------------------------
# The rotation policy
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("max_bytes", "backups"),
    [
        pytest.param(0, 1, id="zero-size"),
        pytest.param(-1, 1, id="negative-size"),
        pytest.param(100, 1, id="below-the-floor"),
        pytest.param(10**12, 1, id="above-the-ceiling"),
        pytest.param(4096, -1, id="negative-backups"),
        pytest.param(4096, 1000, id="too-many-backups"),
    ],
)
def test_a_policy_that_could_not_be_honoured_cannot_be_built(max_bytes: int, backups: int) -> None:
    """Validated on construction, so no sink has to refuse one it was handed."""
    with pytest.raises(ValidationError):
        RotationPolicy(max_bytes=max_bytes, backup_count=backups)


def test_the_ceiling_states_the_worst_case_as_a_number() -> None:
    """A reviewer asking "how large can this get" should not have to multiply."""
    assert RotationPolicy(max_bytes=1_048_576, backup_count=7).ceiling_bytes() == 8_388_608
