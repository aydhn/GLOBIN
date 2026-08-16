"""The contracts through which GLOBIN reaches its own mutable state.

Four protocols, one per thing the application cannot do for itself: find and
prepare a directory tree, publish a small document without ever being seen
half-written, take an exclusive lock the operating system will release if this
process dies, and notice that somebody has asked it to stop.

Each exists because the answer comes from outside the process, and
:mod:`globin.application.lifecycle` may touch none of it. Substituting one is how
a test proves that a failed ``fsync`` is reported correctly without owning a disk
that fails.

**The seams are where the failures are.** :class:`StateStore` is one method rather
than several deliberately — a caller that could open a handle itself would be able
to publish a document non-atomically, and the whole point is that it cannot. The
stages *inside* that method are what
``tests/unit/test_runtime_state_adapters.py`` breaks one at a time, and they are
reachable because the adapter takes its filesystem operations as substitutable
callables rather than reaching for :mod:`os` directly.

**No port here returns a secret**, and none accepts one. Everything that crosses
these boundaries is small, non-secret operational metadata — ADR-0059 names what
may never go into the tree, and the types in :mod:`globin.domain.runtime_state`
carry nothing else.
"""

from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Protocol

from globin.domain.bootstrap import RecordedPath
from globin.domain.identifiers import RunId
from globin.domain.runtime_state import RuntimeArea, RuntimeLayout


class RuntimeTreeSource(Protocol):
    """Resolves the user-local runtime root and prepares the tree beneath it."""

    def prepare(self, layout: RuntimeLayout) -> tuple[str, ...]:
        """Create the declared areas and report what cannot be used.

        Args:
            layout: The declared tree.

        Returns:
            One sentence per area that cannot be used. Empty when the tree is fit
            to write into.

        The root is resolved once and canonicalised, and every area is checked to
        resolve inside it before anything is created. An implementation that
        created a directory first and checked afterwards would have already made
        the mess it was asked to prevent.
        """
        ...

    def describe(self) -> str:
        """Describe where the tree is, in terms that are safe to publish.

        Returns:
            A phrase naming the root without spelling it out. The tree lives under
            a user profile, and a user profile directory names its owner.
        """
        ...

    def recorded_root(self) -> RecordedPath:
        """The runtime root in the one form that may be written down.

        Returns:
            A :class:`~globin.domain.bootstrap.RecordedPath`, which for this tree
            is always a fingerprint: it is deliberately outside the repository, so
            there is no relative spelling to give, and the absolute one names the
            account holder.
        """
        ...

    def claim_temporary(self, run_id: RunId) -> None:
        """Create the temporary directory this run owns.

        Args:
            run_id: The run's identifier, which names the directory.

        Raises:
            RuntimePersistenceError: If it could not be created.

        One directory per run, named after the run. That is what makes
        :meth:`release_temporary` safe to be recursive: it removes something whose
        name this process chose, rather than everything it finds.
        """
        ...

    def release_temporary(self, run_id: RunId) -> None:
        """Remove the temporary directory this run owns, and nothing else.

        Args:
            run_id: The run's identifier.

        Raises:
            ValidationError: If the identifier could not name a directory inside
                the temporary area.
            RuntimePersistenceError: If it could not be removed.

        **The target is re-verified before anything recursive happens.** A
        recursive delete is the most damaging operation in this phase, and the
        guarantee that must hold is that it can only ever reach strictly beneath
        the temporary area — never the runtime root, never `state`, never `cache`.
        Removing a directory that is already gone is not an error: this runs on
        the shutdown path, where the alternative is a teardown that fails because
        its work was already done.
        """
        ...


class StateStore(Protocol):
    """Publishes and reads back the small documents GLOBIN keeps between runs."""

    def publish(self, area: RuntimeArea, name: str, document: Mapping[str, object]) -> None:
        """Write one document so that no reader can observe it half-written.

        Args:
            area: Which area it belongs in.
            name: Its filename, which must be a plain name.
            document: What to write. Must be JSON-representable and must contain
                no secret.

        Raises:
            ValidationError: If the name could leave the area.
            RuntimePersistenceError: If the document could not be published. The
                previous document, if there was one, is left intact.

        One method rather than "open, write, close" precisely so that a caller
        cannot publish non-atomically. Everything between the temporary file and
        the replace is the implementation's business.
        """
        ...

    def read(self, area: RuntimeArea, name: str) -> Mapping[str, object] | None:
        """Read one document back.

        Args:
            area: Which area it lives in.
            name: Its filename.

        Returns:
            The parsed document, or ``None`` when there is no such file.

        Raises:
            ValidationError: If the name could leave the area, or the file exists
                and is not a JSON object. A corrupt document is refused rather
                than treated as absent: the two mean opposite things, and one of
                them is worth telling an operator about.
        """
        ...

    def discard(self, area: RuntimeArea, name: str) -> None:
        """Remove one document, if it is there.

        Args:
            area: Which area it lives in.
            name: Its filename.

        Raises:
            ValidationError: If the name could leave the area.

        Removing something that is not there is not an error. This runs on the
        shutdown path, where the alternative is a teardown that fails because a
        file it was going to delete had already gone.
        """
        ...


class InstanceLock(Protocol):
    """Decides whether this process is the machine's one GLOBIN coordinator."""

    def hold(self) -> AbstractContextManager[None]:
        """Take the lock for the duration of a block.

        Returns:
            A context manager holding the lock, releasing it on exit whether the
            block succeeded or raised.

        Raises:
            InstanceAlreadyActiveError: If another process holds it. Non-blocking:
                a second coordinator fails closed immediately rather than waiting
                for a first that may never finish.

        The lock is held for the whole life of the application, so this is entered
        once, high up, and the `finally` that releases it is the operating
        system's as much as Python's — a process that dies without unwinding still
        releases it.
        """
        ...

    def probe(self) -> str:
        """Ask whether the lock could be taken, without keeping it.

        Returns:
            The empty string when it is available, otherwise what the operating
            system said.

        **This is what a diagnostic uses.** A read-only command that took the real
        lock would refuse to run beside a running GLOBIN, which is the moment
        somebody most wants to run it. The window between acquiring and releasing
        is as short as an acquisition, and nothing is written inside it.
        """
        ...


class ShutdownSignals(Protocol):
    """Notices that something has asked this process to stop.

    Note the name: *something*, not *a signal*. Only :meth:`install` was ever
    signal-specific, and Phase 025 added :meth:`request` so that a stop asked for
    from inside the process reaches the same latch a stop asked for from outside
    does. One latch with two writers is what keeps
    :meth:`~globin.application.lifecycle.Session.stop_requested` able to see both;
    a second port with a second flag would have let one of them go unnoticed.
    """

    def install(self) -> None:
        """Register handlers for whichever signals this platform has.

        Only signals the running Python actually exposes are registered:
        :func:`signal.signal` raises :exc:`ValueError` for anything else on
        Windows, and a start-up that fell over while installing its own shutdown
        path would be failing for the least useful possible reason.
        """
        ...

    def request(self) -> None:
        """Ask this process to stop, from inside it.

        Idempotent by construction rather than by a guard: the latch only ever goes
        from unset to set, so calling this twice is calling it once.

        **Safe from any thread, and safe for a reason worth writing down.** The
        implementation must be a plain attribute store, exactly as the signal
        handler is — an :class:`threading.Event` would take a lock, and the same
        latch is written from a signal handler where CPython warns against
        synchronisation primitives. There is no read-modify-write here, so there is
        nothing for a lock to protect and no lock is permitted.
        """
        ...

    def requested(self) -> bool:
        """Whether a stop has been asked for.

        Returns:
            ``True`` once a handled signal has arrived, or :meth:`request` was
            called.

        A handler sets a flag and returns; this is how the ordinary control flow
        learns about it. Nothing waits, blocks or does I/O inside a handler.
        """
        ...
