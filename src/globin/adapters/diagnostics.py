"""Where GLOBIN's diagnostics touch the process: files, hooks and the standard library.

Everything in this module changes something the whole interpreter shares — a file
on disk, an attribute on :mod:`sys`, the root logger's handler list. That is why it
is here and nowhere else: ``dependency-rules.toml`` lists :mod:`logging`,
:mod:`faulthandler`, :mod:`os`, :mod:`sys` and :mod:`threading` among the
I/O-capable modules, and the inner layers may import none of them.

**Nothing installs itself at import.** Every hook below is installed by an explicit
call from the composition root and removed by an explicit call on the way out.
``ENGINEERING_CONTRACT.md`` invariant 5 forbids import-time work, and
``tests/architecture/test_architecture_contract.py`` checks it rather than trusting
it — but the stronger reason is that a module which grabbed :data:`sys.excepthook`
on import would change the behaviour of any program that imported GLOBIN for any
reason, including a test collecting it.

**The registry is injected, and that is the house pattern rather than a flourish.**
:class:`~globin.adapters.runtime_state.PlatformShutdownSignals` takes its
``registrar``; :class:`Lifecycle` takes its ``register_fallback``. The same
reasoning applies with more force here, because a test that installed a real
:data:`sys.excepthook` and then failed before restoring it would break every test
that ran afterwards, and the symptom would appear in the victim rather than in the
culprit.

**GLOBIN's own call sites do not use :mod:`logging`, and this does not change
that.** ADR-0026 and ``adapters/observability.py`` record why: module-level handler
state is the global configuration invariant 5 exists to keep out. What is added
here is the bridge that module already anticipated — *"when a dependency first
emits standard-library records, a second ``LogSink`` implementation bridges them;
the port is what makes that an addition rather than a rewrite"*. Phase 021 adopted
``numpy`` and ``pandas``, so that dependency now exists, and Python's own warnings
arrive by the same road.
"""

import faulthandler
import json
import logging
import sys
import threading
import traceback as traceback_module
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import IO, Final

from globin.adapters.observability import as_record
from globin.application.observability import Logger
from globin.domain.diagnostics import (
    EVENT_DEPENDENCY_RECORD,
    EVENT_EXCEPTION_ASYNCIO,
    EVENT_EXCEPTION_THREAD_UNCAUGHT,
    EVENT_EXCEPTION_UNCAUGHT,
    EVENT_EXCEPTION_UNRAISABLE,
    EVENT_RUNTIME_WARNING,
    FaultSource,
    RotationPolicy,
    is_orderly_exit,
)
from globin.domain.observability import LogEvent, Severity, log_event
from globin.ports.clock import Clock
from globin.ports.observability import LogSink

LOG_FILE_NAME: Final[str] = "globin.log"
"""The live log file's name inside the logs area."""

FAULT_FILE_NAME: Final[str] = "faults.txt"
"""Where native-fault tracebacks are written.

**Deliberately not JSON, and deliberately not the log file.** ``faulthandler``
writes a plain traceback with no encoder involved, precisely so that it can work
when the interpreter is too broken to run one. Pointing it at the NDJSON log would
put non-JSON lines in a file everything else is entitled to parse.
"""

SYS_EXCEPTHOOK: Final[str] = "sys.excepthook"
"""The main thread's uncaught-exception hook."""

SYS_UNRAISABLEHOOK: Final[str] = "sys.unraisablehook"
"""The hook for exceptions the interpreter could not propagate."""

THREADING_EXCEPTHOOK: Final[str] = "threading.excepthook"
"""A background thread's uncaught-exception hook."""

DIAGNOSTICS_FILE: Final[str] = "diagnostics.json"
"""Where the diagnostics record is published inside the state area.

Beside ``lifecycle.json`` rather than under ``.globin/``, because it describes
*this run on this machine* rather than this repository — the distinction
``RUNTIME_FILESYSTEM.md`` draws between the two roots.
"""

DIAGNOSTICS_SCHEMA: Final[str] = "globin.diagnostics.record"
"""What kind of document the published record is."""

DIAGNOSTICS_SCHEMA_VERSION: Final[int] = 1
"""The version of that document's shape.

Carried because ``SERIALIZATION_POLICY.md`` requires every persisted document to
name its schema and version, so that a reader which knows less than the writer
refuses rather than reading the parts it recognises.
"""

WARNINGS_LOGGER: Final[str] = "py.warnings"
"""The logger :func:`logging.captureWarnings` routes warnings through."""

TRACEBACK_LIMIT: Final[int] = 40
"""How many frames of a traceback are recorded.

Bounded because a runaway recursion produces a traceback that is thousands of
frames long and identical in all but the last few, and a log record that large
costs more than it explains.
"""


@dataclass(frozen=True, slots=True)
class HookRegistry:
    """Where the process-global fault hooks live.

    Args:
        read: Reads one hook by its qualified name.
        write: Replaces one hook by its qualified name.

    Injected so that a test never touches the real :mod:`sys` attributes. A test
    that installed a real hook and then failed before restoring it would break
    every test afterwards, and ``tests/conftest.py``'s process-state guard watches
    the environment and the working directory rather than these.
    """

    read: Callable[[str], object]
    write: Callable[[str, object], None]


def system_hooks() -> HookRegistry:
    """The real process hooks.

    Returns:
        A registry backed by :mod:`sys` and :mod:`threading`.

    A function rather than a module-level constant, because building it is a call
    and every layer package here performs no work at import. It is also the single
    place that knows which attribute each qualified name refers to.
    """
    holders: dict[str, tuple[object, str]] = {
        SYS_EXCEPTHOOK: (sys, "excepthook"),
        SYS_UNRAISABLEHOOK: (sys, "unraisablehook"),
        THREADING_EXCEPTHOOK: (threading, "excepthook"),
    }

    def read(name: str) -> object:
        module, attribute = holders[name]
        return getattr(module, attribute)

    def write(name: str, value: object) -> None:
        module, attribute = holders[name]
        setattr(module, attribute, value)

    return HookRegistry(read=read, write=write)


def _describe(
    exception_type: type[BaseException] | None,
    value: BaseException | None,
    traceback: TracebackType | None,
) -> dict[str, object]:
    """Summarise an exception for a log record, without letting it leak a secret.

    Args:
        exception_type: The class, when there is one.
        value: The instance, when there is one.
        traceback: The traceback, when there is one.

    Returns:
        Fields describing the fault.

    The message goes in as a field named ``exception_message`` rather than being
    interpolated into the event name, which is what makes redaction possible at
    all: :class:`~globin.domain.observability.LogEvent` redacts by field *name*,
    and a value interpolated into a message is past every rule about names.

    Formatting is bounded and defensive. A ``__str__`` that raises is a real thing
    — it is how a half-constructed object behaves — and a diagnostic layer that
    died formatting a fault would replace the report with a second fault.
    """
    fields: dict[str, object] = {
        "exception_type": "unknown" if exception_type is None else exception_type.__name__,
    }
    try:
        fields["exception_message"] = "" if value is None else str(value)
    except Exception:  # a broken __str__ must not replace the report
        fields["exception_message"] = "<unprintable>"
    if traceback is not None:
        try:
            frames = traceback_module.format_tb(traceback, limit=TRACEBACK_LIMIT)
        except Exception:  # same reason; a traceback may reference broken objects
            frames = ["<unformattable>"]
        fields["traceback"] = "".join(frames)
    return fields


@dataclass(slots=True)
class RotatingFileLogSink:
    """Writes each record to a bounded file in the runtime tree, as one line of JSON.

    Args:
        path: The live log file.
        clock: Where the timestamp comes from, read once per record.
        policy: The size at which to rotate and how many files to keep.

    **Every record is flushed, and this sink is the reason that is worth the cost.**
    :class:`~globin.adapters.observability.StreamLogSink` deliberately does not
    flush, because its stream is line-buffered and flushed at exit. This one exists
    so that a process which dies badly leaves an explanation behind, and an
    explanation still sitting in a buffer when the interpreter is killed is not one.

    **Rotation is a rename, and on Windows a rename needs the handle closed.** The
    live file is closed, the backups are shifted from oldest to newest so that no
    shift overwrites a file still needed by the next, and a new live file is
    opened. Doing it in the other order loses the newest backup, which is the one
    anybody would actually want.

    **A write failure propagates**, exactly as ``LOGGING_POLICY.md`` requires of the
    stream sink: invariant 23 forbids swallowing an exception silently, and a sink
    that quietly discarded records would be indistinguishable from a working one
    right up until somebody needed the log. The composition root decides what to do
    about that; this sink does not decide for it.
    """

    path: Path
    clock: Clock
    policy: RotationPolicy
    handle: IO[str] | None = None
    written: int = 0

    def open(self) -> None:
        """Open the live file for appending, creating the area if it is not there.

        Appending rather than truncating, so that a second run in the same tree
        adds to the record instead of destroying the first run's explanation of why
        it needed a second.
        """
        if self.handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.written = self.path.stat().st_size if self.path.exists() else 0
        self.handle = self.path.open("a", encoding="utf-8", newline="\n")

    def close(self) -> None:
        """Flush and close the live file.

        Safe to call twice. Shutdown runs cleanups newest-first and every one of
        them runs even if an earlier raised, so a cleanup that assumed it was the
        only caller would be the wrong shape for the lifecycle it is registered
        against.
        """
        handle, self.handle = self.handle, None
        if handle is None:
            return
        handle.flush()
        handle.close()

    def emit(self, event: LogEvent) -> None:
        """Write one record, rotating first if this record would exceed the bound.

        Args:
            event: The record, already redacted.

        Raises:
            RuntimeError: If the sink was never opened. A silent no-op here would
                mean every record in a run went nowhere and nothing said so.

        The size is tracked rather than queried. Calling :func:`os.stat` per record
        would be a system call on a path a later phase may take often, and the two
        can only disagree if something outside GLOBIN is writing to this file, which
        is not a case worth paying for on every line.
        """
        if self.handle is None:
            msg = "the log sink was not opened, so this record would have gone nowhere"
            raise RuntimeError(msg)
        line = _render(event, str(self.clock.now()))
        encoded = len(line.encode("utf-8"))
        if self.written and self.written + encoded > self.policy.max_bytes:
            self._rotate()
        self.handle.write(line)
        self.handle.flush()
        self.written += encoded

    def _rotate(self) -> None:
        """Close the live file, shift the backups, and open a new one."""
        self.close()
        _shift_backups(self.path, self.policy.backup_count)
        self.written = 0
        self.handle = self.path.open("a", encoding="utf-8", newline="\n")


def _render(event: LogEvent, timestamp: str) -> str:
    """Render one record as a line of JSON.

    Args:
        event: The record, already redacted.
        timestamp: When it happened.

    Returns:
        One line, newline included.

    Delegates the record shape to
    :func:`globin.adapters.observability.as_record` rather than rebuilding it, so
    that a file and a stream cannot disagree about what a GLOBIN log record is.
    """
    record = as_record(event, timestamp)
    return json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n"


def _shift_backups(path: Path, backup_count: int) -> None:
    """Move each backup one place older, discarding the oldest.

    Args:
        path: The live log file.
        backup_count: How many backups to keep.

    With a count of zero the live file is simply removed, which is the documented
    meaning of *rotate and discard* rather than an accident of the loop bounds.
    """
    if backup_count == 0:
        path.unlink(missing_ok=True)
        return
    oldest = path.with_name(f"{path.name}.{backup_count}")
    oldest.unlink(missing_ok=True)
    for index in range(backup_count - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        if source.exists():
            source.replace(path.with_name(f"{path.name}.{index + 1}"))
    if path.exists():
        path.replace(path.with_name(f"{path.name}.1"))


@dataclass(slots=True)
class ProcessFaultHooks:
    """GLOBIN's reporters for the three faults that never reach a ``try`` block.

    Args:
        logger: Where reports go.
        registry: How the hooks are read and replaced.
        previous: What was installed before. Supplied empty by the caller rather
            than defaulted, because ``field(default_factory=dict)`` is a call in a
            class body and every layer package here performs no work at import.
            :class:`~globin.adapters.runtime_state.PlatformShutdownSignals` takes
            its ``installed`` list for exactly the same reason.

    **Each hook replaces the previous one and puts it back.** Not chaining to it:
    the default :data:`sys.excepthook` prints a traceback to standard error, and
    calling it as well would double every report — once as JSON and once as prose,
    with the prose landing in the stream that ``--json`` mode promises carries
    nothing but JSON.

    **An orderly exit is recorded, not mourned.** :class:`SystemExit` and
    :class:`KeyboardInterrupt` are severity ``INFO``, because
    ``LOGGING_POLICY.md`` says ``CRITICAL`` means GLOBIN cannot do its job, and
    being asked to stop is not that.
    """

    logger: Logger
    registry: HookRegistry
    previous: dict[str, object]

    def install(self) -> None:
        """Take over the three hooks, remembering what was there.

        Installing twice is a no-op rather than an error: the second call would
        otherwise record GLOBIN's own hook as the thing to restore, and the
        original would be lost for the rest of the process.
        """
        if self.previous:
            return
        for name in (SYS_EXCEPTHOOK, SYS_UNRAISABLEHOOK, THREADING_EXCEPTHOOK):
            self.previous[name] = self.registry.read(name)
        self.registry.write(SYS_EXCEPTHOOK, self._on_uncaught)
        self.registry.write(SYS_UNRAISABLEHOOK, self._on_unraisable)
        self.registry.write(THREADING_EXCEPTHOOK, self._on_thread_uncaught)

    def restore(self) -> None:
        """Put back whatever was installed before, and forget it.

        Safe to call twice, and safe to call when ``install`` never ran. Shutdown
        runs every cleanup even when an earlier one raised, so a teardown that
        assumed it ran exactly once would be the wrong shape for the lifecycle it
        is registered against.
        """
        for name, hook in self.previous.items():
            self.registry.write(name, hook)
        self.previous.clear()

    def _on_uncaught(
        self,
        exception_type: type[BaseException],
        value: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        """Report an exception that reached the top of the main thread.

        Args:
            exception_type: The class.
            value: The instance.
            traceback: Where it came from.
        """
        orderly = issubclass(exception_type, (SystemExit, KeyboardInterrupt))
        fields = _describe(exception_type, value, traceback)
        fields["source"] = str(FaultSource.MAIN)
        fields["orderly"] = orderly
        self._report(EVENT_EXCEPTION_UNCAUGHT, orderly=orderly, fields=fields)

    def _on_thread_uncaught(self, args: object) -> None:
        """Report an exception that reached the top of a background thread.

        Args:
            args: The interpreter's hook argument, carrying the exception and the
                thread. Typed loosely because :class:`threading.ExceptHookArgs` is
                a named tuple the standard library builds and a test supplies a
                double of.

        The thread object is read for its name and then not retained. Holding a
        reference to a dead thread or to its exception in an attribute would keep
        every frame of the traceback alive for as long as this object lives, which
        is the whole run.
        """
        exception_type = getattr(args, "exc_type", None)
        value = getattr(args, "exc_value", None)
        traceback = getattr(args, "exc_traceback", None)
        thread = getattr(args, "thread", None)
        fields = _describe(exception_type, value, traceback)
        fields["source"] = str(FaultSource.THREAD)
        fields["thread_name"] = "unknown" if thread is None else str(getattr(thread, "name", ""))
        name = "unknown" if exception_type is None else exception_type.__name__
        self._report(EVENT_EXCEPTION_THREAD_UNCAUGHT, orderly=is_orderly_exit(name), fields=fields)

    def _on_unraisable(self, args: object) -> None:
        """Report an exception the interpreter could not propagate at all.

        Args:
            args: The interpreter's hook argument.

        The offending object is summarised with :func:`repr` inside a guard. That
        is not defensive programming for its own sake: an unraisable exception
        very often comes from a ``__del__``, so the object being described is
        part-destroyed and its ``__repr__`` is exactly the code most likely to
        raise a second time.
        """
        exception_type = getattr(args, "exc_type", None)
        value = getattr(args, "exc_value", None)
        traceback = getattr(args, "exc_traceback", None)
        fields = _describe(exception_type, value, traceback)
        fields["source"] = str(FaultSource.UNRAISABLE)
        try:
            fields["object"] = repr(getattr(args, "object", None))
        except Exception:  # a half-destroyed object's repr may raise
            fields["object"] = "<unreprable>"
        self._report(EVENT_EXCEPTION_UNRAISABLE, orderly=False, fields=fields)

    def _report(self, event: str, *, orderly: bool, fields: dict[str, object]) -> None:
        """Write one fault report, and never fail because of it.

        Args:
            event: The stable event name.
            orderly: Whether this was a stop rather than a fault.
            fields: What to record.

        **This is the one place in GLOBIN that swallows an exception**, and the
        reason is narrow enough to state. A hook runs when the process is already
        failing; an exception raised inside :data:`sys.excepthook` is printed by
        the interpreter and discarded, so it cannot propagate anywhere useful and
        can only replace the report with a less informative one. Invariant 23
        forbids swallowing silently, so it is not silent: the fallback writes to
        standard error, which is the last channel still guaranteed to exist.
        """
        try:
            if orderly:
                self.logger.info(event, **fields)
            else:
                self.logger.critical(event, **fields)
        except Exception as fault:  # the reporter must not become the fault
            print(f"globin: {event} could not be logged: {fault!r}", file=sys.stderr)


def asyncio_exception_handler(logger: Logger) -> Callable[[object, Mapping[str, object]], None]:
    """Build a handler an event loop can be given for exceptions nothing awaited.

    Args:
        logger: Where reports go.

    Returns:
        A callable matching :meth:`asyncio.AbstractEventLoop.set_exception_handler`.

    **Nothing installs this, and that is deliberate.** GLOBIN starts no event loop
    yet — Phases 033-048 bring the first one — so installing a handler here would
    mean reaching for a running loop that does not exist. What this phase owes the
    later ones is the reporting shape, ready to be handed to a loop by whoever
    creates it, rather than a loop created early so that something could be
    attached to it.

    The default handler is not called afterwards, for the reason
    :class:`ProcessFaultHooks` gives: it writes prose to standard error, and one
    fault should produce one report.
    """

    def handle(_loop: object, context: Mapping[str, object]) -> None:
        exception = context.get("exception")
        fields: dict[str, object] = {"source": str(FaultSource.ASYNCIO)}
        if isinstance(exception, BaseException):
            fields.update(_describe(type(exception), exception, exception.__traceback__))
        fields["asyncio_message"] = str(context.get("message", ""))
        future = context.get("future", context.get("task"))
        if future is not None:
            try:
                fields["task"] = repr(future)
            except Exception:  # a task's repr can raise while it is tearing down
                fields["task"] = "<unreprable>"
        try:
            logger.error(EVENT_EXCEPTION_ASYNCIO, **fields)
        except Exception as fault:  # reporting must not break the loop
            print(f"globin: asyncio fault could not be logged: {fault!r}", file=sys.stderr)

    return handle


def severity_for(levelno: int) -> Severity:
    """Map a standard-library level number to the nearest GLOBIN severity at or below it.

    Args:
        levelno: The value from a :class:`logging.LogRecord`.

    Returns:
        The severity.

    ``Severity(levelno)`` would be exact and would raise on the levels libraries
    actually invent — ``25`` for a "notice", ``15`` for a "verbose". Rounding down
    keeps such a record and files it conservatively, which is better than losing it
    to a :class:`ValueError` raised inside the logging system.
    """
    chosen = Severity.DEBUG
    for severity in (
        Severity.DEBUG,
        Severity.INFO,
        Severity.WARNING,
        Severity.ERROR,
        Severity.CRITICAL,
    ):
        if levelno >= severity.value:
            chosen = severity
    return chosen


class StandardLibraryBridge(logging.Handler):
    """Routes another library's :mod:`logging` records into a GLOBIN sink.

    This is the addition ``adapters/observability.py`` anticipated when it
    explained why GLOBIN does not use :mod:`logging` itself: *"when a dependency
    first emits standard-library records, a second ``LogSink`` implementation
    bridges them; the port is what makes that an addition rather than a rewrite"*.
    Phase 021 adopted ``numpy`` and ``pandas``, so that dependency now exists.

    **GLOBIN's own code still does not call :mod:`logging`**, and
    ``tests/architecture/test_logging_discipline.py`` fails if it starts. What
    arrives here comes from a library or from :func:`warnings.warn`.

    **The message is rendered here and travels as a field.** A standard-library
    record carries a format string and its arguments, which is the interpolation
    ``LOGGING_POLICY.md`` forbids GLOBIN from doing — but the library already did
    it, so the choice is between recording the result and discarding the record.
    It goes into a field so that redaction by field name still applies to it.
    """

    def __init__(self, sink: LogSink, correlation_id: str) -> None:
        """Build the bridge.

        Args:
            sink: Where the translated records go.
            correlation_id: Ties them to the run that installed this handler.
        """
        super().__init__()
        self.sink = sink
        self.correlation_id = correlation_id

    def emit(self, record: logging.LogRecord) -> None:
        """Translate one standard-library record and hand it to the sink.

        Args:
            record: What the library emitted.

        Failure is reported through :meth:`logging.Handler.handleError`, which is
        the standard library's own channel for a handler that could not handle.
        Raising instead would push an exception back into whichever library was
        merely trying to log something.
        """
        try:
            fields: dict[str, object] = {
                "logger": record.name,
                "message": record.getMessage(),
                "level": record.levelname,
            }
            if record.exc_info is not None:
                exception_type, value, traceback = record.exc_info
                fields.update(_describe(exception_type, value, traceback))
            event = (
                EVENT_RUNTIME_WARNING if record.name == WARNINGS_LOGGER else EVENT_DEPENDENCY_RECORD
            )
            self.sink.emit(
                log_event(
                    severity=severity_for(record.levelno),
                    event=event,
                    correlation_id=self.correlation_id,
                    fields=fields,
                )
            )
        except Exception:  # a logging handler must not raise into its caller
            self.handleError(record)


@dataclass(slots=True)
class StandardLibraryCapture:
    """Owns the root logger's handler for as long as GLOBIN is running.

    Args:
        bridge: The handler to install.
        installed: Whether it currently is. Supplied by the caller rather than
            defaulted for the reason :class:`ProcessFaultHooks` gives.

    **Warnings arrive through the same door.**
    :func:`logging.captureWarnings` routes :func:`warnings.warn` into the
    ``py.warnings`` logger, which this handler then receives. That is why no
    separate warnings mechanism exists here: one bridge, one place to remove.

    **The warning *filters* are not touched.** Deciding which warnings are
    produced is a different question from deciding where they go, and the test
    suite sets ``filterwarnings = ["error"]`` deliberately. A phase that changed
    the filters to make its own output tidier would silently disarm that.
    """

    bridge: StandardLibraryBridge
    installed: bool

    def install(self) -> None:
        """Attach the bridge to the root logger and start capturing warnings."""
        if self.installed:
            return
        logging.getLogger().addHandler(self.bridge)
        logging.captureWarnings(capture=True)
        self.installed = True

    def remove(self) -> None:
        """Detach the bridge and stop capturing warnings.

        Safe to call twice. Removing the handler matters more than it looks: the
        root logger is process-global, so a bridge left attached would keep
        forwarding records into a sink whose file has been closed.
        """
        if not self.installed:
            return
        logging.captureWarnings(capture=False)
        logging.getLogger().removeHandler(self.bridge)
        self.installed = False


@dataclass(slots=True)
class FaultFile:
    """Keeps a file open for :mod:`faulthandler` to write a native traceback into.

    Args:
        path: Where tracebacks go.
        handle: The open file, or ``None`` when disabled.

    **The handle must outlive the enabling.** :func:`faulthandler.enable` records
    the file descriptor and writes to it from a signal context; closing the file
    while it is enabled leaves the interpreter writing to a closed descriptor at
    the exact moment it is already crashing. So the order is fixed: enable then
    hold, disable then close, and never the other way round.

    **No signal registration.** :func:`faulthandler.register` is POSIX-only and
    this host is Windows. ``faulthandler.enable`` covers the faults that matter
    here — a segmentation fault or an abort from native code in a wheel — without
    assuming a signal set the platform does not have.

    **The output is not JSON, and that is documented rather than fixed.** A
    faulthandler traceback is written by C code with no encoder involved, which is
    the entire reason it still works when the interpreter cannot run Python. It
    goes to its own file so that nothing parsing the NDJSON log meets a line that
    is not a record.
    """

    path: Path
    handle: IO[str] | None

    def enable(self) -> None:
        """Open the fault file and point :mod:`faulthandler` at it."""
        if self.handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a", encoding="utf-8", newline="\n")
        faulthandler.enable(file=self.handle, all_threads=True)

    def disable(self) -> None:
        """Stop :mod:`faulthandler`, then flush and close the file.

        Safe to call twice, and deliberately in this order.
        """
        handle, self.handle = self.handle, None
        if handle is None:
            return
        faulthandler.disable()
        handle.flush()
        handle.close()


@dataclass(frozen=True, slots=True)
class FanOutLogSink:
    """Hands each record to several sinks in turn.

    Args:
        sinks: Where records go, in order.

    Exists so that a console and a file can hold different thresholds over the
    same events — the arrangement ``LOGGING_POLICY.md`` describes when it explains
    why filtering lives in a decorating sink rather than in the logger. Each
    element is typically a
    :class:`~globin.adapters.observability.ThresholdLogSink` wrapping its own
    destination.

    **A failure in one sink stops the rest**, and that is the same choice
    :class:`~globin.adapters.observability.StreamLogSink` makes about a failed
    write: invariant 23 forbids swallowing, and a fan-out that quietly continued
    would make "the log is complete" true of some destinations and not others with
    nothing recording which.
    """

    sinks: tuple[LogSink, ...]

    def emit(self, event: LogEvent) -> None:
        """Write one record to every sink.

        Args:
            event: The record, already redacted.
        """
        for sink in self.sinks:
            sink.emit(event)


@dataclass(slots=True)
class RuntimeDiagnostics:
    """Everything Phase 023 installs, and the order it is installed and removed in.

    Args:
        logger: The logger the rest of GLOBIN is handed.
        file_sink: The rotating file, or ``None`` when file logging is off.
        hooks: The three process fault hooks.
        capture: The standard-library bridge and warning capture.
        faults: The native-fault file.
        started: Whether :meth:`start` has run.

    **Start and stop are mirror images, and the order is the argument.** Files open
    before hooks are installed, because a hook that fired between the two would
    have nowhere to write. Hooks are removed before files close, for the same
    reason read backwards: a hook still installed after its sink closed would raise
    inside the interpreter's own error path.

    **Stopping never raises.** It is registered through
    :meth:`~globin.application.lifecycle.Session.on_close`, which runs every
    cleanup even when an earlier one raised — so each step here is independently
    safe and idempotent rather than relying on the ones before it having worked.
    """

    logger: Logger
    file_sink: RotatingFileLogSink | None
    hooks: ProcessFaultHooks
    capture: StandardLibraryCapture
    faults: FaultFile
    started: bool
    publish: Callable[[Mapping[str, object]], None] | None

    def start(self) -> None:
        """Open the files, install the hooks, then record what was installed.

        The evidence is published **last**, so that what it describes is what is
        actually in place rather than what was about to be. A record written first
        would claim hooks that a failure between the two calls left uninstalled.
        """
        if self.started:
            return
        if self.file_sink is not None:
            self.file_sink.open()
        self.faults.enable()
        self.hooks.install()
        self.capture.install()
        self.started = True
        if self.publish is not None:
            self.publish(self.record())

    def stop(self) -> None:
        """Remove the hooks, then close the files. Safe to call twice."""
        if not self.started:
            return
        self.capture.remove()
        self.hooks.restore()
        self.faults.disable()
        if self.file_sink is not None:
            self.file_sink.close()
        self.started = False

    def record(self) -> dict[str, object]:
        """Describe what is installed, for the diagnostics evidence.

        Returns:
            A mapping carrying no secret, no environment dump and no absolute path
            from outside the runtime tree.

        The log path is recorded as a **name** rather than a full path. The
        manifest is published as evidence, and every absolute path on a development
        host carries the account holder's name in it — the rule
        ``tools/quality/runtime`` follows about its own manifest.
        """
        return {
            "schema": DIAGNOSTICS_SCHEMA,
            "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
            "file_logging": self.file_sink is not None,
            "log_file": None if self.file_sink is None else self.file_sink.path.name,
            "rotation": None
            if self.file_sink is None
            else {
                "max_bytes": self.file_sink.policy.max_bytes,
                "backup_count": self.file_sink.policy.backup_count,
                "ceiling_bytes": self.file_sink.policy.ceiling_bytes(),
            },
            "fault_file": self.faults.path.name,
            "faulthandler_enabled": self.faults.handle is not None,
            "hooks_installed": sorted(self.hooks.previous),
            "standard_library_captured": self.capture.installed,
            "warnings_captured": self.capture.installed,
            "asyncio_handler_available": True,
            "started": self.started,
        }
