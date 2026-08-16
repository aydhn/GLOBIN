"""What GLOBIN can report about its own run, expressed as pure domain types.

Three things live here, and none of them writes anything.

**The lifecycle event vocabulary.** ``LOGGING_POLICY.md`` requires that event names
be constants, "so that the set of things GLOBIN can report is enumerable rather
than discovered by reading log output". Until this phase nothing in the product
logged at all, so there was nothing to enumerate. These are the names a start-up
and a shutdown produce, and a machine consumer may rely on them.

**The rule about which endings are faults.** A process that exits because it was
asked to has not crashed, and recording it as one would make the only signal that
means *something went wrong* fire every time somebody pressed Ctrl-C. Phase 022
already made this distinction for :class:`~globin.domain.runtime_state.ShutdownReason`;
this states it once more for the exception hooks, which see the same endings
through a different door.

**The bound on the logs area.** :attr:`~globin.domain.runtime_state.RuntimeArea.LOGS`
is the only part of the runtime tree that is appended to rather than published
whole, which makes it the one directory that can grow without anybody deciding it
should. ADR-0059 named exactly that as the failure mode of adding a directory, so
the size is a validated value type rather than a number passed around: a policy
that could not be honoured cannot be constructed.

Nothing here imports :mod:`logging`, :mod:`sys`, :mod:`faulthandler` or anything
else that touches the process. The domain may import none of them, and the
judgements below are the half of diagnostics that has no reason to.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.errors import ValidationError

EVENT_BOOTSTRAP_STARTED: Final[str] = "bootstrap.started"
"""A start-up began. The first thing GLOBIN ever writes in a run."""

EVENT_CONFIGURATION_LOADED: Final[str] = "configuration.loaded"
"""Configuration resolved and validated. Nothing before this had a threshold."""

EVENT_RUNTIME_PATHS_PREPARED: Final[str] = "runtime.paths.prepared"
"""The mutable tree exists and is writable."""

EVENT_INSTANCE_LOCK_ACQUIRED: Final[str] = "instance.lock.acquired"
"""This process is the machine's one coordinator."""

EVENT_DIAGNOSTICS_INITIALISED: Final[str] = "diagnostics.initialised"
"""Sinks are open and the fault hooks are installed."""

EVENT_DIAGNOSTICS_STOPPED: Final[str] = "diagnostics.stopped"
"""Hooks restored and sinks closed. The last thing GLOBIN writes in a run."""

EVENT_BOOTSTRAP_COMPLETED: Final[str] = "bootstrap.completed"
"""Every start-up gate was measured, whatever they concluded."""

EVENT_APPLICATION_READY: Final[str] = "application.ready"
"""Start-up passed and work may begin."""

EVENT_SHUTDOWN_REQUESTED: Final[str] = "shutdown.requested"
"""A signal asked this process to stop. Not itself the stopping."""

EVENT_SHUTDOWN_STARTED: Final[str] = "shutdown.started"
"""Teardown began."""

EVENT_SHUTDOWN_COMPLETED: Final[str] = "shutdown.completed"
"""Teardown finished, and every cleanup ran."""

EVENT_EXCEPTION_UNCAUGHT: Final[str] = "exception.uncaught"
"""An exception reached the top of the main thread."""

EVENT_EXCEPTION_THREAD_UNCAUGHT: Final[str] = "exception.thread_uncaught"
"""An exception reached the top of a background thread."""

EVENT_EXCEPTION_UNRAISABLE: Final[str] = "exception.unraisable"
"""The interpreter could not propagate an exception at all."""

EVENT_EXCEPTION_ASYNCIO: Final[str] = "exception.asyncio_uncaught"
"""An event loop reported an exception nothing awaited."""

EVENT_RUNTIME_WARNING: Final[str] = "runtime.warning"
"""A Python warning was issued, routed here rather than to standard error."""

EVENT_FAULTHANDLER_ENABLED: Final[str] = "faulthandler.enabled"
"""Native-fault tracebacks will be written to a file if the interpreter dies."""

EVENT_DEPENDENCY_RECORD: Final[str] = "dependency.record"
"""A library emitted a standard-library log record, bridged into GLOBIN's own.

One event name for every such record rather than one derived from the emitting
logger, because a logger name is chosen by somebody else and
:data:`~globin.domain.observability.EVENT_NAME_ALPHABET` does not admit most of
them. The originating logger travels as a field, where it is searchable and where
redaction still applies.
"""

LIFECYCLE_EVENTS: Final[tuple[str, ...]] = (
    EVENT_BOOTSTRAP_STARTED,
    EVENT_CONFIGURATION_LOADED,
    EVENT_RUNTIME_PATHS_PREPARED,
    EVENT_INSTANCE_LOCK_ACQUIRED,
    EVENT_DIAGNOSTICS_INITIALISED,
    EVENT_DIAGNOSTICS_STOPPED,
    EVENT_BOOTSTRAP_COMPLETED,
    EVENT_APPLICATION_READY,
    EVENT_SHUTDOWN_REQUESTED,
    EVENT_SHUTDOWN_STARTED,
    EVENT_SHUTDOWN_COMPLETED,
    EVENT_EXCEPTION_UNCAUGHT,
    EVENT_EXCEPTION_THREAD_UNCAUGHT,
    EVENT_EXCEPTION_UNRAISABLE,
    EVENT_EXCEPTION_ASYNCIO,
    EVENT_RUNTIME_WARNING,
    EVENT_FAULTHANDLER_ENABLED,
    EVENT_DEPENDENCY_RECORD,
)
"""Every event this phase can emit, as a closed set.

A tuple rather than a :class:`frozenset` because ``frozenset(...)`` is a call, and
``tests/architecture/test_architecture_contract.py`` holds every layer package to
performing no work at import — the same reason
:data:`globin.domain.bootstrap.CREATED_PATHS` is a tuple.

Closed so that a contract test can compare it against
``docs/engineering/RUNTIME_DIAGNOSTICS.md`` in both directions: an event the
product can emit and the document does not name is undocumented, and a name in
the document nothing emits is a claim about a capability that does not exist.
"""

ORDERLY_EXIT_TYPES: Final[tuple[str, ...]] = ("SystemExit", "KeyboardInterrupt")
"""Exception types that mean the process was asked to stop, not that it broke.

Both inherit :class:`BaseException` rather than :class:`Exception` precisely
because the standard library considers them control flow, and GLOBIN agrees. A
diagnostic layer that logged either at ``CRITICAL`` would make the severity that
is supposed to mean *GLOBIN cannot do its job* fire on every Ctrl-C, and an
operator who sees that twice stops reading it.

Names rather than the classes themselves, because the domain answers this from a
record as well as from a live exception, and a record has only ever carried the
name. The adapter installing the hook still uses :func:`issubclass` against the
real types, so a subclass is classified correctly there; this is the same rule
stated where a reader of a written record can apply it.
"""

MINIMUM_ROTATION_BYTES: Final[int] = 4096
"""The smallest file size worth rotating at.

Below this a single record can exceed the limit, so every write would rotate and
the backup set would hold one line each. That is not a bound on disk use, it is a
bound expressed so tightly it stops being one.
"""

MAXIMUM_ROTATION_BYTES: Final[int] = 67_108_864
"""The largest single log file, at 64 MiB.

A ceiling rather than a preference. ``RUNTIME_FILESYSTEM.md`` says the runtime
tree holds nothing large, and without an upper bound the one appending area could
be pointed at a number that quietly makes that false.
"""

MAXIMUM_BACKUP_COUNT: Final[int] = 32
"""How many rotated files may be kept."""


class FaultSource(StrEnum):
    """Which door a fault report came through.

    Recorded because the four are not interchangeable and the remedy differs. A
    thread fault means work continued elsewhere; an unraisable fault means the
    interpreter could not even propagate it, which is usually a finaliser; an
    asyncio fault means nothing awaited a task that failed.
    """

    MAIN = "main"
    """The main thread's :data:`sys.excepthook`."""

    THREAD = "thread"
    """:data:`threading.excepthook`, for a background thread."""

    UNRAISABLE = "unraisable"
    """:data:`sys.unraisablehook`, for what could not be propagated at all."""

    ASYNCIO = "asyncio"
    """An event loop's exception handler."""


def is_orderly_exit(exception_type: str) -> bool:
    """Whether an ending named by this exception type is a stop rather than a fault.

    Args:
        exception_type: The exception class's name.

    Returns:
        Whether GLOBIN was asked to stop.

    Used to decide severity, not to decide whether to record. An orderly exit is
    still written down — a run that ended on a signal is exactly the kind of thing
    an operator later wants to confirm — it is simply not written down as a
    catastrophe.
    """
    return exception_type in ORDERLY_EXIT_TYPES


@dataclass(frozen=True, slots=True)
class RotationPolicy:
    """How much disk the logs area may ever consume.

    Args:
        max_bytes: The size at which one file is rotated.
        backup_count: How many rotated files are kept beside the live one.

    Raises:
        ValidationError: If either value is outside its declared bound.

    Validated on construction, so a policy that could not be honoured cannot be
    built and no sink has to refuse one it was handed. That is the same reason
    :class:`~globin.domain.runtime_state.RuntimeLayout` validates its segments
    rather than leaving the adapter to.

    ``backup_count`` of zero is legitimate and means *rotate and discard*: the
    live file is truncated when it fills and nothing is kept. It is a real choice
    for a machine short of disk, not a disabled state.
    """

    max_bytes: int
    backup_count: int

    def __post_init__(self) -> None:
        """Refuse a policy outside the declared bounds."""
        problems: list[str] = []
        if not MINIMUM_ROTATION_BYTES <= self.max_bytes <= MAXIMUM_ROTATION_BYTES:
            problems.append(
                f"max_bytes is {self.max_bytes}, and must be between "
                f"{MINIMUM_ROTATION_BYTES} and {MAXIMUM_ROTATION_BYTES}"
            )
        if not 0 <= self.backup_count <= MAXIMUM_BACKUP_COUNT:
            problems.append(
                f"backup_count is {self.backup_count}, and must be between "
                f"0 and {MAXIMUM_BACKUP_COUNT}"
            )
        if problems:
            raise ValidationError("; ".join(problems))

    def ceiling_bytes(self) -> int:
        """The most disk this policy can ever occupy.

        Returns:
            The live file plus every backup, at their maximum size.

        Exists so that the bound is a number somebody can read rather than a
        multiplication they have to perform. A reviewer asking "how large can this
        get" should not have to derive it.
        """
        return self.max_bytes * (self.backup_count + 1)
