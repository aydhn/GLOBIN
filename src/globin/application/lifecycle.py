"""One run of GLOBIN, from taking the lock to putting it down.

The use case that turns a `RuntimeContext` into a running process: it takes the
coordinator lock, records that a run started, hands control to the caller, and —
whether that caller returned, raised, or was asked to stop — records how the run
ended and releases everything it took.

**Cleanup is `try`/`finally`, and `atexit` is a net.** Python's documentation is
explicit that `atexit` functions are not called when a process is killed by a
signal it does not handle, when a fatal internal error occurs, or when
:func:`os._exit` is called — which are exactly the cases crash safety is about.
So nothing here depends on it. What makes a crash survivable is that every
document was published atomically: whatever was last written is complete and
readable, whether or not anything got to run afterwards.

**The teardown order is fixed, and each step is reached even if the one before it
failed.** ADR-0059 states it: stop accepting work, run the application's own
cleanup, publish the closing record, remove this run's temporary tree, clear the
instance metadata, release the lock. A shutdown that abandoned the rest because
one step raised would leave exactly the debris it exists to remove, so the
failures are collected and reported together at the end.

**A signal handler sets a flag and returns.** :meth:`Session.stop_requested` is
how ordinary control flow learns about it. Nothing waits, locks or writes inside a
handler — Python runs one on the main thread at a bytecode boundary, and its
documentation warns against synchronisation primitives there.

What this deliberately is not: a supervisor (Phase 263), a subsystem lifecycle
(Phase 262), a drain of work in flight (Phase 268), or any kind of recovery
(Phase 267). It starts one process, records that it did, and stops it.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from globin.domain.bootstrap import ExitCode, RecordedPath
from globin.domain.clock import Instant
from globin.domain.identifiers import RunId
from globin.domain.runtime_state import (
    INSTANCE_FILE,
    LIFECYCLE_FILE,
    InstanceMetadata,
    LifecycleRecord,
    LifecycleStatus,
    RuntimeArea,
    RuntimeLayout,
    ShutdownReason,
)
from globin.errors import ConfigurationError
from globin.ports.clock import Clock
from globin.ports.runtime_state import (
    InstanceLock,
    RuntimeTreeSource,
    ShutdownSignals,
    StateStore,
)


class ShutdownIncompleteError(ConfigurationError):
    """A run finished, and something it was releasing did not release.

    The application's work is over by the time this can be raised, so it never
    invalidates what a run produced. What it says is that this machine now holds
    debris — a temporary tree, a stale instance record — that the next run will
    have to live with, and that is worth an operator's attention rather than a
    silent pass.

    A :class:`~globin.errors.ConfigurationError`, matching the two faults in
    :mod:`globin.domain.runtime_state` and chosen on the taxonomy's own axis of
    *who must act*: the usual cause is another process holding a file open, so
    the operator acts on the environment and no retry helps. It is specifically
    not an :class:`~globin.errors.InternalError`, which would claim GLOBIN broke
    its own invariant, and it may not be a direct subclass of
    :class:`~globin.errors.GlobinError` — ``FaultDomain`` has one member per
    direct subclass and a sixth category is a decision ADR-0022 reserves.
    """


@dataclass(slots=True)
class Session:
    """One run in progress: who it is, and whether it has been asked to stop.

    Args:
        run_id: This run's identifier, from Phase 011's registry.
        started_at: When it started.
        signals: Where a stop request arrives.
        cleanups: Callbacks the application registers, run newest first on the way
            out. It has **no default**, for the reason
            :class:`~globin.application.bootstrap._RunState` gives about its own
            fields: a default of ``[]`` would have to be constructed, and
            constructing one in a class body is work performed at import, which
            every layer package is forbidden. :meth:`Lifecycle.run` builds it,
            where a call is just a call.

    Mutable and handed to the caller, unlike almost everything else in this
    repository, because registering a cleanup is the one thing an application must
    be able to do *during* a run.
    """

    run_id: RunId
    started_at: Instant
    signals: ShutdownSignals
    cleanups: list[Callable[[], None]]

    def stop_requested(self) -> bool:
        """Whether something has asked this process to stop.

        Returns:
            ``True`` once a handled signal has arrived.

        Polled by the application at a point of its choosing. That is the whole
        design: the handler marked an intention, and the work of acting on it
        happens where it is safe to do it.
        """
        return self.signals.requested()

    def on_close(self, cleanup: Callable[[], None]) -> None:
        """Register a callback to run during an orderly shutdown.

        Args:
            cleanup: What to run. It should not raise; if it does, the failure is
                collected and the remaining teardown still happens.

        Run in reverse registration order, matching `atexit`'s own convention and
        the ordinary expectation that a thing set up later is torn down earlier.
        """
        self.cleanups.append(cleanup)


@dataclass(frozen=True, slots=True)
class Lifecycle:
    """Runs one GLOBIN session against a prepared runtime tree.

    Args:
        tree: Owns this run's temporary directory.
        state: Publishes the two records.
        lock: Guards single-instance ownership.
        signals: Notices a stop request.
        clock: Stamps the records.
        layout: The declared tree.
        version: The GLOBIN version, for the instance metadata.
        profile: The resolved configuration profile's name.
        pid: This process's identifier. A **value**, not a call: the application
            layer may import no I/O-capable module and :mod:`os` is one, so the
            composition root reads it and passes it down — the same treatment the
            clock gets, and for the same reason.
        runtime_root: Where the tree is, recorded.
        register_fallback: Registers the best-effort `atexit` net. Substitutable
            so a test can observe that one was registered without actually
            registering anything at interpreter exit — which would then run after
            the test that made it.

    Frozen, and holding no state about the run: everything that changes lives in
    the :class:`Session` handed to the caller. Two runs of one `Lifecycle` are
    therefore independent, which is what makes it safe for the composition root to
    build a single one.
    """

    tree: RuntimeTreeSource
    state: StateStore
    lock: InstanceLock
    signals: ShutdownSignals
    clock: Clock
    layout: RuntimeLayout
    version: str
    profile: str
    pid: int
    runtime_root: RecordedPath
    register_fallback: Callable[[Callable[[], None]], None]

    @contextmanager
    def run(self, run_id: RunId) -> Iterator[Session]:
        """Hold the coordinator lock for one run, and record what happened.

        Args:
            run_id: This run's identifier. Passed in rather than generated here so
                that the identifier is the caller's, which is what lets a test
                assert about exact records and what ADR-0026 requires of anything
                correlating work.

        Yields:
            The :class:`Session`, for the duration of the block.

        Raises:
            InstanceAlreadyActiveError: If another coordinator holds the lock.
                Raised before anything is written, so a refused second instance
                changes nothing the first one owns.
            RuntimePersistenceError: If the opening records could not be written.
            ShutdownIncompleteError: If the block finished and the teardown could not.

        The lock is taken **first**, before any record is written. A second
        coordinator that wrote its instance metadata and then discovered it could
        not have the lock would have already overwritten the first one's.
        """
        with self.lock.hold():
            started_at = self.clock.now()
            session = Session(
                run_id=run_id, started_at=started_at, signals=self.signals, cleanups=[]
            )
            self.signals.install()
            self.register_fallback(lambda: self._last_resort(session))

            self._open(session)
            reason = ShutdownReason.COMPLETED
            code = ExitCode.OK
            try:
                yield session
            except KeyboardInterrupt:
                reason, code = ShutdownReason.INTERRUPTED, ExitCode.GATE_FAILED
                raise
            except BaseException:
                reason, code = ShutdownReason.FAILED, ExitCode.INTERNAL
                raise
            else:
                if session.stop_requested():
                    reason = ShutdownReason.SIGNALLED
            finally:
                self._close(session, reason=reason, code=code)

    def _open(self, session: Session) -> None:
        """Claim this run's temporary directory and publish the opening records.

        Args:
            session: The run.

        Raises:
            RuntimePersistenceError: If either record could not be written.

        The lifecycle record is written **last**. Until it exists there is nothing
        claiming a run is in progress, so a failure part-way through leaves no
        record suggesting an unclean shutdown that never happened.
        """
        self.tree.claim_temporary(session.run_id)
        self.state.publish(
            RuntimeArea.RUN,
            INSTANCE_FILE,
            InstanceMetadata(
                version=self.version,
                pid=self._pid(),
                instance_id=str(session.run_id),
                started_at=str(session.started_at),
                profile=self.profile,
                root=self.runtime_root,
            ).as_record(),
        )
        self._record(session, LifecycleStatus.RUNNING)

    def _close(self, session: Session, *, reason: ShutdownReason, code: ExitCode) -> None:
        """Run the teardown, in order, reaching every step.

        Args:
            session: The run.
            reason: Why it ended.
            code: What it is returning.

        Raises:
            ShutdownIncompleteError: If any step failed. Collected rather than raised
                at the first, because abandoning the rest would leave the debris
                this exists to remove.

        The order is ADR-0059's, and the first step is the application's own
        cleanup: everything after it assumes the application has stopped touching
        the tree.
        """
        problems: list[str] = []
        problems.extend(self._run_cleanups(session))
        problems.extend(
            self._attempt("record the shutdown", lambda: self._finish(session, reason, code))
        )
        problems.extend(
            self._attempt(
                "remove this run's temporary tree",
                lambda: self.tree.release_temporary(session.run_id),
            )
        )
        problems.extend(
            self._attempt(
                "clear the instance metadata",
                lambda: self.state.discard(RuntimeArea.RUN, INSTANCE_FILE),
            )
        )
        if problems:
            raise ShutdownIncompleteError("; ".join(problems))

    def _run_cleanups(self, session: Session) -> list[str]:
        """Run the application's callbacks, newest first.

        Args:
            session: The run.

        Returns:
            One sentence per callback that raised.

        Every callback runs even if an earlier one failed. A cleanup list that
        stopped at the first exception would make the reliability of the last
        callback depend on the first, which is the opposite of what a caller
        registering one expects.
        """
        problems: list[str] = []
        for cleanup in reversed(session.cleanups):
            problems.extend(self._attempt("run an application cleanup", cleanup))
        return problems

    @staticmethod
    def _attempt(what: str, action: Callable[[], object]) -> list[str]:
        """Perform one teardown step, turning a failure into a sentence.

        Args:
            what: What was being attempted, for the message.
            action: The step.

        Returns:
            Empty when it succeeded, otherwise one sentence.

        :class:`Exception` rather than :class:`BaseException`: a
        :exc:`KeyboardInterrupt` arriving *during* shutdown should still stop the
        process rather than being collected into a report nobody will read.
        """
        try:
            action()
        except Exception as fault:
            return [f"could not {what}: {fault}"]
        return []

    def _finish(self, session: Session, reason: ShutdownReason, code: ExitCode) -> None:
        """Publish the closing lifecycle record.

        Args:
            session: The run.
            reason: Why it ended.
            code: What it is returning.
        """
        self.state.publish(
            RuntimeArea.STATE,
            LIFECYCLE_FILE,
            LifecycleRecord(
                status=LifecycleStatus.STOPPED,
                instance_id=str(session.run_id),
                pid=self._pid(),
                started_at=str(session.started_at),
                finished_at=str(self.clock.now()),
                reason=reason,
                exit_code=int(code),
            ).as_record(),
        )

    def _record(self, session: Session, status: LifecycleStatus) -> None:
        """Publish an open lifecycle record.

        Args:
            session: The run.
            status: What the run is doing.
        """
        self.state.publish(
            RuntimeArea.STATE,
            LIFECYCLE_FILE,
            LifecycleRecord(
                status=status,
                instance_id=str(session.run_id),
                pid=self._pid(),
                started_at=str(session.started_at),
            ).as_record(),
        )

    def _last_resort(self, session: Session) -> None:
        """The `atexit` net: close an open record if `finally` never ran.

        Args:
            session: The run.

        **Best effort, and nothing rests on it.** It does not run on a hard kill or
        a power loss, which are the cases that matter, and any failure here is
        swallowed because the interpreter is already leaving and a traceback at
        exit would be noise attached to the wrong cause.

        It reads the record before writing one, so a run that shut down properly
        is not overwritten by its own safety net.
        """
        try:
            document = self.state.read(RuntimeArea.STATE, LIFECYCLE_FILE)
            if document is None or document.get("instance_id") != str(session.run_id):
                return
            if document.get("status") == LifecycleStatus.STOPPED.value:
                return
            self._finish(session, ShutdownReason.FAILED, ExitCode.INTERNAL)
        except Exception:
            return

    def _pid(self) -> int:
        """The process identifier the records carry.

        Returns:
            What the composition root was told at wiring time.
        """
        return self.pid
