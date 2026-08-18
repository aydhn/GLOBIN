"""Finding the runtime tree, publishing state into it, and locking it.

The only module in this phase that touches the world. Everything above it is
handed facts; this is where :mod:`os`, :mod:`pathlib`, :mod:`tempfile`,
:mod:`msvcrt`, :mod:`signal` and :mod:`atexit` live, which is what lets every
judgement in :mod:`globin.domain.runtime_state` be tested from literals.

**The root is a platform lookup, not a configuration source.**
``docs/CONFIGURATION_POLICY.md`` defers environment-variable *resolution* to Phase
027, and nothing here reads the process environment on its own: the mapping is
handed in. Microsoft's Known Folder reference gives ``%LOCALAPPDATA%`` as the
documented default path of ``FOLDERID_LocalAppData``, which is what makes reading
that name a way of asking the platform where per-user application data goes rather
than a second configuration system. When it is absent this **refuses**; it does
not fall back to the home directory, the working directory or a guess.

**Every filesystem step of a publication is substitutable, and that is the
design.** Proving that a failed ``fsync`` leaves the previous document intact
requires a disk that fails ``fsync``. :class:`FileOperations` is how a test
supplies one, and the default is the real thing, so nothing outside a test ever
passes another.

**A lock file's existence is never consulted.** ``msvcrt.locking`` with
``LK_NBLCK`` raises :exc:`OSError` when the region is held, and the operating
system releases it when the holder exits — so a file left by a crashed process is
harmless and is never deleted on a guess. That was measured on the target host
before it was relied on; see ``docs/research/phase_022_sources.md`` S-02.

**No absolute path leaves this module.** A path becomes a
:class:`~globin.domain.bootstrap.RecordedPath` at the moment it is observed, so
the layers above cannot publish one — and this tree lives under a user profile,
which names its owner.
"""

import atexit
import errno
import json
import msvcrt
import os
import shutil
import signal
import types
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Final

from globin.domain.bootstrap import RecordedPath, fingerprint_of, recorded_outside
from globin.domain.identifiers import RunId
from globin.domain.runtime_state import (
    InstanceAlreadyActiveError,
    RuntimeArea,
    RuntimeLayout,
    RuntimePersistenceError,
    child_problems,
)
from globin.errors import ValidationError

LOCAL_APPLICATION_DATA: Final[str] = "LOCALAPPDATA"
"""The environment name Windows documents for ``FOLDERID_LocalAppData``.

Microsoft's Known Folder reference gives its default path as ``%LOCALAPPDATA%``
(``%USERPROFILE%\\AppData\\Local``), which is why reading this is a platform
lookup. It is never read from :data:`os.environ` here — see the module docstring.
"""

LOCK_REGION_BYTES: Final[int] = 1
"""How much of the lock file is locked.

One byte at position zero. The region is measured from the *current file
position*, so the lock and the matching unlock must agree about both, and the
descriptor is never seeked between them.
"""

TEMPORARY_PREFIX: Final[str] = ".globin-"
"""What a half-written document is called before it is published.

A leading dot and a project prefix, so an artefact left behind by an interrupted
write is recognisable as GLOBIN's and is obviously not the document itself.
"""

TEMPORARY_SUFFIX: Final[str] = ".tmp"
"""The other half of that name."""

HANDLED_SIGNALS: Final[tuple[str, ...]] = ("SIGINT", "SIGTERM", "SIGBREAK")
"""The signals GLOBIN handles, by name rather than by number.

Named so that :func:`hasattr` decides what exists on this platform.
:func:`signal.signal` raises :exc:`ValueError` for anything Windows does not
accept, and a start-up that fell over while installing its own shutdown path
would be failing for the least useful possible reason. ``SIGBREAK`` is
Windows-only and ``SIGINT`` and ``SIGTERM`` are everywhere; a tuple rather than a
:class:`frozenset` because a layer package performs no call at import.
"""


def resolve_root(environment: Mapping[str, str], layout: RuntimeLayout) -> Path:
    """Find the directory GLOBIN owns under the platform's per-user data area.

    Args:
        environment: The process environment, handed in rather than read.
        layout: The declared tree, for its namespace.

    Returns:
        The canonical runtime root. Not created; that is :meth:`ProjectRuntimeTree.prepare`.

    Raises:
        ConfigurationError: If the platform does not say where per-user
            application data goes. Refusing is the whole point — falling back to
            the home directory or the working directory would put a machine-wide
            coordinator lock somewhere that depends on how GLOBIN was started.

    Nothing here contains a user name, a repository path or a working directory.
    """
    base = environment.get(LOCAL_APPLICATION_DATA, "").strip()
    if not base:
        msg = (
            f"{LOCAL_APPLICATION_DATA} is not set, so there is nowhere per-user to put "
            "GLOBIN's runtime state. It is the documented default path of "
            "FOLDERID_LocalAppData; GLOBIN will not guess a substitute."
        )
        raise RuntimePersistenceError(msg)
    return (Path(base) / layout.namespace).resolve()


def record_root(root: Path) -> RecordedPath:
    """Describe the runtime root in a form that is safe to publish.

    Args:
        root: The canonical root.

    Returns:
        A fingerprint rather than a spelling, always.

    Unlike :func:`globin.adapters.bootstrap.record`, there is no "inside the
    project" case to consider: this tree is deliberately outside it, and a path
    under a user profile carries the account holder's name. The fingerprint still
    answers the question a reader has, which is whether this is the *same* root as
    last time.
    """
    return recorded_outside(str(root))


def make_directory(directory: Path) -> None:
    """Create a directory and its parents.

    Args:
        directory: What to create.
    """
    directory.mkdir(parents=True, exist_ok=True)


def flush_writer(handle: IO[str]) -> None:
    """Empty a writer's buffer into the operating system.

    Args:
        handle: The open writer.
    """
    handle.flush()


def remove_file(path: Path) -> None:
    """Remove a file, tolerating one that is not there.

    Args:
        path: What to remove.
    """
    path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class FileOperations:
    """The filesystem steps a publication is made of, each substitutable.

    Args:
        makedirs: Creates a directory and its parents.
        flush: Empties a writer's buffer into the operating system.
        fsync: Forces the operating system's buffer onto the disk.
        replace: Publishes the temporary file over the destination.
        unlink: Removes a file.

    Every field defaults to the real operation, so production code constructs this
    with no arguments and a test replaces exactly one. That is what makes "a failed
    ``fsync`` leaves the previous document intact" an assertion rather than a hope:
    each stage can be broken alone, and the stages after it must then not have run.

    :func:`os.replace` is used rather than :meth:`pathlib.Path.rename` because it
    overwrites an existing destination, which every republication needs and which
    ``rename`` refuses on Windows.

    **The defaults are named functions rather than lambdas, and are assigned
    rather than wrapped in** :func:`~dataclasses.field`. Both spellings would be a
    *call* in a class body, which
    ``tests/architecture/test_architecture_contract.py`` forbids every layer
    package: a lambda body containing ``directory.mkdir(...)`` reads to that
    checker exactly like work performed at import, and being right about the
    difference is not a distinction worth teaching it.
    """

    makedirs: Callable[[Path], None] = make_directory
    flush: Callable[[IO[str]], None] = flush_writer
    fsync: Callable[[int], None] = os.fsync
    replace: Callable[[Path, Path], None] = os.replace
    unlink: Callable[[Path], None] = remove_file


def render(document: Mapping[str, object]) -> str:
    """Encode a state document so two writers cannot disagree about bytes.

    Args:
        document: What to write.

    Returns:
        One line of JSON followed by a newline — sorted keys, no incidental
        whitespace, ASCII only, exactly as every manifest under ``.globin`` does it.

    Raises:
        ValidationError: If the document is not representable, which includes
            ``NaN`` and ``Infinity``. Those are not JSON, and every standard reader
            refuses them; writing one would produce a file only Python could read
            back and would turn a numeric mistake into a corrupt document.
    """
    try:
        encoded = json.dumps(
            dict(document),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as fault:
        msg = f"this document cannot be written as JSON: {fault}"
        raise ValidationError(msg) from fault
    return encoded + "\n"


@dataclass(frozen=True, slots=True)
class ProjectRuntimeTree:
    """Creates the five areas beneath the resolved root, and refuses what escapes.

    Args:
        root: The canonical runtime root.
        layout: The declared tree. Held as well as passed to :meth:`prepare`
            because the temporary-directory methods need it and their callers —
            the lifecycle, on a shutdown path — have no business supplying a
            layout that could differ from the one the tree was prepared with.
    """

    root: Path
    layout: RuntimeLayout

    def prepare(self, layout: RuntimeLayout) -> tuple[str, ...]:
        """Create every area and report what cannot be used.

        Args:
            layout: The declared tree.

        Returns:
            One sentence per area that cannot be used, empty when all four are fit
            to write into.

        Each area's boundary is checked **before** that area is created. An
        implementation that created a directory and then noticed it was outside the
        root would have already made the mess it was asked to prevent.
        :class:`~globin.domain.runtime_state.RuntimeLayout` has validated its own
        segments, so this cannot fail today for that reason — which is exactly when
        a boundary check is cheap to add and worth having.

        **The root is created first, and re-resolved afterwards.** That ordering is
        not cosmetic: :meth:`~pathlib.Path.resolve` leaves a non-existent tail
        alone, so a root resolved before it exists and an area resolved after it
        does can disagree whenever anything on the way is a junction or a symbolic
        link — which is the normal state of a per-user data directory inside a
        Windows application container. Resolving both sides of the comparison after
        the root exists is what makes containment mean one thing.
        """
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as fault:
            return (f"the runtime root could not be created: {fault.strerror or fault}",)
        if not self.root.is_dir():
            return ("the runtime root exists and is not a directory",)

        base = self.root.resolve()
        problems: list[str] = []
        for area in layout.areas():
            target = (base / layout.segment_for(area)).resolve()
            if not target.is_relative_to(base):
                problems.append(f"the {area.value} area resolves outside the runtime root")
                continue
            if target.exists() and not target.is_dir():
                problems.append(f"the {area.value} area exists and is not a directory")
                continue
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as fault:
                problems.append(
                    f"the {area.value} area could not be created: {fault.strerror or fault}"
                )
        return tuple(problems)

    def describe(self) -> str:
        """Describe where the tree is without spelling it out.

        Returns:
            A phrase naming the platform area and this root's fingerprint.
        """
        return (
            f"the per-user application data area, GLOBIN namespace "
            f"(fingerprint {fingerprint_of(str(self.root))})"
        )

    def recorded_root(self) -> RecordedPath:
        """The runtime root in the one form that may be written down.

        Returns:
            A fingerprint, always. See :func:`record_root`.
        """
        return record_root(self.root)

    def _temporary(self, run_id: RunId, layout: RuntimeLayout) -> Path:
        """Where one run's temporary directory is, checked to be inside the area.

        Args:
            run_id: The run's identifier.
            layout: The declared tree.

        Returns:
            The directory.

        Raises:
            ValidationError: If the identifier could not name a directory inside
                the temporary area, or the result would escape it.

        Two checks, not one. The name is validated as a plain segment, and the
        joined result is then checked to be strictly beneath the temporary root —
        because the value that reaches a recursive delete must be verified where
        the delete happens, not only where the name was chosen.
        """
        name = str(run_id)
        problems = child_problems(name, area=RuntimeArea.TMP)
        if problems:
            raise ValidationError("; ".join(problems))
        area = (self.root / layout.segment_for(RuntimeArea.TMP)).resolve()
        target = (area / name).resolve()
        if not target.is_relative_to(area) or target == area:
            msg = f"the temporary directory for {name} does not lie inside the temporary area"
            raise ValidationError(msg)
        return target

    def claim_temporary(self, run_id: RunId) -> None:
        """Create the temporary directory this run owns.

        Args:
            run_id: The run's identifier.

        Raises:
            ValidationError: If the identifier could not name a directory here.
            RuntimePersistenceError: If it could not be created.
        """
        target = self._temporary(run_id, self.layout)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as fault:
            msg = f"this run's temporary directory could not be created: {fault.strerror or fault}"
            raise RuntimePersistenceError(msg) from fault

    def release_temporary(self, run_id: RunId) -> None:
        """Remove the temporary directory this run owns, and nothing else.

        Args:
            run_id: The run's identifier.

        Raises:
            ValidationError: If the identifier could not name a directory here.
            RuntimePersistenceError: If it could not be removed.

        The boundary is re-verified by :meth:`_temporary` before anything
        recursive happens, and a directory that is already gone is not an error —
        this runs on the shutdown path, where the alternative is a teardown that
        fails because its work was already done.
        """
        target = self._temporary(run_id, self.layout)
        try:
            shutil.rmtree(target)
        except FileNotFoundError:
            return
        except OSError as fault:
            msg = f"this run's temporary directory could not be removed: {fault.strerror or fault}"
            raise RuntimePersistenceError(msg) from fault


@dataclass(frozen=True, slots=True)
class AtomicDocumentWriter:
    """The publication sequence, addressed by path rather than by area.

    Args:
        operations: The filesystem steps, substitutable one at a time.

    The sequence is fixed and is not negotiable: a uniquely-named temporary file
    **in the destination's own directory**, the encoded document, ``flush``,
    ``fsync`` on the descriptor, close, then ``replace``. Python's own
    documentation gives that order for ``fsync``, and the temporary file may not
    live in the platform temporary directory because a rename is only atomic
    within one filesystem — putting it elsewhere would silently turn the atomic
    step into a copy.

    **Extracted in Phase 031 so that one writer serves two addressing schemes.**
    :class:`AtomicStateStore` addresses a document by
    :class:`~globin.domain.runtime_state.RuntimeArea`; the secret vault is
    deliberately *not* an area — its answer to the question that enumeration
    poses, *may this be deleted*, is **no** — and it needs exactly this sequence.
    A second copy of it is the drift ``docs/engineering/SOURCE_OF_TRUTH.md``
    exists to prevent, and the sequence is the one thing here that must not be
    got subtly differently twice.

    The caller supplies an already-resolved target, because the two schemes
    validate a name differently and neither validation belongs to the writing.
    """

    operations: FileOperations

    def publish(self, target: Path, document: Mapping[str, object], *, label: str) -> None:
        """Write one document atomically.

        Args:
            target: Where it goes, already validated by the caller.
            document: What to write.
            label: What to call the parent directory in a failure message.

        Raises:
            ValidationError: If the document is not representable as JSON.
            RuntimePersistenceError: If it could not be published. The previous
                document, if any, is left intact.

        The encoding happens **before** anything is opened, so a document that
        cannot be written does not leave a temporary file behind — and, more
        importantly, does not truncate anything.
        """
        encoded = render(document)
        try:
            self.operations.makedirs(target.parent)
        except OSError as fault:
            msg = f"{label} could not be created: {fault.strerror or fault}"
            raise RuntimePersistenceError(msg) from fault

        stem = f"{TEMPORARY_PREFIX}{os.getpid()}-{target.name}{TEMPORARY_SUFFIX}"
        temporary = target.parent / stem
        try:
            self._write(temporary, encoded)
            self.operations.replace(temporary, target)
        except OSError as fault:
            self._discard_quietly(temporary)
            msg = f"{target.name} could not be published: {fault.strerror or fault}"
            raise RuntimePersistenceError(msg) from fault

    def read(self, target: Path) -> Mapping[str, object] | None:
        """Read one document back.

        Args:
            target: Where it lives, already validated by the caller.

        Returns:
            The parsed document, or ``None`` when there is no such file.

        Raises:
            ValidationError: If the file is not a JSON object.
            RuntimePersistenceError: If it exists and could not be read.

        Corrupt and absent are refused differently on purpose: they mean opposite
        things, and only one of them is worth telling an operator about.
        """
        try:
            text = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as fault:
            msg = f"{target.name} could not be read: {fault.strerror or fault}"
            raise RuntimePersistenceError(msg) from fault
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as fault:
            msg = f"{target.name} is not valid JSON: {fault}"
            raise ValidationError(msg) from fault
        if not isinstance(parsed, dict):
            held = type(parsed).__name__
            msg = f"{target.name} holds a {held}, and a state document is an object"
            raise ValidationError(msg)
        return parsed

    def discard(self, target: Path) -> None:
        """Remove one document, if it is there.

        Args:
            target: Where it lives, already validated by the caller.

        Raises:
            RuntimePersistenceError: If it exists and could not be removed.
        """
        try:
            self.operations.unlink(target)
        except OSError as fault:
            msg = f"{target.name} could not be removed: {fault.strerror or fault}"
            raise RuntimePersistenceError(msg) from fault

    def _write(self, temporary: Path, encoded: str) -> None:
        r"""Write and durably flush the temporary file.

        Args:
            temporary: Where to write.
            encoded: The rendered document.

        Raises:
            OSError: If any stage fails. Left to :meth:`publish`, which is where
                the temporary artefact is cleaned up and the fault is renamed.

        ``newline=""`` rather than ``"\\n"``: the document already ends in one, and
        letting the platform translate it would make the bytes differ between
        hosts for a document whose whole point is to be comparable.
        """
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(encoded)
            self.operations.flush(handle)
            self.operations.fsync(handle.fileno())

    def _discard_quietly(self, path: Path) -> None:
        """Remove a temporary artefact, never masking the fault that caused it.

        Args:
            path: The temporary file.

        A failure to clean up is deliberately swallowed. The caller is already
        raising about something more important, and replacing that message with
        "and also the temporary file could not be removed" would bury the fault
        an operator has to act on.
        """
        with suppress(OSError):
            self.operations.unlink(path)


@dataclass(frozen=True, slots=True)
class AtomicStateStore:
    """Publishes small JSON documents so no reader sees one half-written.

    Args:
        root: The canonical runtime root.
        layout: The declared tree.
        operations: The filesystem steps, substitutable one at a time.

    The publication sequence lives in :class:`AtomicDocumentWriter` and is shared
    with the secret vault. What this class adds is the *addressing*: a
    :class:`~globin.domain.runtime_state.RuntimeArea` and a filename, with the
    name refused where it could leave the area.
    """

    root: Path
    layout: RuntimeLayout
    operations: FileOperations

    def _writer(self) -> AtomicDocumentWriter:
        """The publication sequence, bound to this store's operations.

        Returns:
            The writer.

        A method rather than a field, so this class's constructor keeps the three
        arguments every caller and every test already passes. Constructing it here
        is a call in a method body, which is ordinary; a default in the class body
        would be a call at import and
        ``tests/architecture/test_architecture_contract.py`` forbids one.
        """
        return AtomicDocumentWriter(operations=self.operations)

    def _directory(self, area: RuntimeArea) -> Path:
        """Where one area is.

        Args:
            area: Which area.

        Returns:
            Its resolved directory.
        """
        return self.root / self.layout.segment_for(area)

    def _target(self, area: RuntimeArea, name: str) -> Path:
        """Where one document goes, refusing a name that could leave the area.

        Args:
            area: Which area.
            name: The filename.

        Returns:
            The destination.

        Raises:
            ValidationError: If the name is not a plain filename.
        """
        problems = child_problems(name, area=area)
        if problems:
            raise ValidationError("; ".join(problems))
        return self._directory(area) / name

    def publish(self, area: RuntimeArea, name: str, document: Mapping[str, object]) -> None:
        """Write one document atomically.

        Args:
            area: Which area it belongs in.
            name: Its filename.
            document: What to write.

        Raises:
            ValidationError: If the name could leave the area, or the document is
                not representable as JSON.
            RuntimePersistenceError: If it could not be published. The previous
                document, if any, is left intact.

        The encoding happens **before** anything is opened, so a document that
        cannot be written does not leave a temporary file behind — and, more
        importantly, does not truncate anything.
        """
        target = self._target(area, name)
        self._writer().publish(target, document, label=area.value)

    def read(self, area: RuntimeArea, name: str) -> Mapping[str, object] | None:
        """Read one document back.

        Args:
            area: Which area it lives in.
            name: Its filename.

        Returns:
            The parsed document, or ``None`` when there is no such file.

        Raises:
            ValidationError: If the name could leave the area, or the file is not
                a JSON object. Corrupt and absent are refused differently on
                purpose: they mean opposite things, and only one of them is worth
                telling an operator about.
        """
        return self._writer().read(self._target(area, name))

    def discard(self, area: RuntimeArea, name: str) -> None:
        """Remove one document, if it is there.

        Args:
            area: Which area it lives in.
            name: Its filename.

        Raises:
            ValidationError: If the name could leave the area.
            RuntimePersistenceError: If it exists and could not be removed.
        """
        self._writer().discard(self._target(area, name))


@dataclass(frozen=True, slots=True)
class WindowsInstanceLock:
    """One coordinator per machine, decided by the operating system.

    Args:
        root: The canonical runtime root.
        layout: The declared tree.
        name: The lock file's name.

    ``msvcrt.locking`` with ``LK_NBLCK`` is documented to raise :exc:`OSError`
    when the bytes cannot be locked, and it was measured on the target host to be
    genuinely cross-process: while one process holds the region a second receives
    ``PermissionError`` with ``errno.EACCES``, and after the first unlocks and
    closes, a third acquires immediately.

    **This is a whole-application mutex, not a resource lock.** It guards one
    top-level coordinator against being started twice. Phases 257 onwards need
    something broader for workers and child processes, and this cannot correctly
    become it.
    """

    root: Path
    layout: RuntimeLayout
    name: str

    @property
    def path(self) -> Path:
        """Where the lock file is."""
        return self.root / self.layout.segment_for(RuntimeArea.RUN) / self.name

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Take the lock for the duration of a block.

        Yields:
            Nothing. The lock is held for the body.

        Raises:
            InstanceAlreadyActiveError: If another process holds it.
            RuntimePersistenceError: If the lock file could not be opened at all,
                which is a broken runtime tree rather than a busy one.

        The unlock and the close are both in ``finally``, and the unlock names the
        same one-byte region the acquisition did. Seeking between the two would
        unlock a region nobody locked; nothing here seeks.
        """
        descriptor = self._open()
        try:
            self._acquire(descriptor)
        except BaseException:
            os.close(descriptor)
            raise
        try:
            yield
        finally:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, LOCK_REGION_BYTES)
            finally:
                os.close(descriptor)

    def probe(self) -> str:
        """Ask whether the lock could be taken, without keeping it.

        Returns:
            The empty string when it is available, otherwise what the operating
            system said.

        Acquired and released immediately. A diagnostic that held the real lock
        would refuse to run beside a running GLOBIN, which is exactly when
        somebody wants to run it.
        """
        try:
            with self.hold():
                return ""
        except InstanceAlreadyActiveError as fault:
            return str(fault)
        except RuntimePersistenceError as fault:
            return str(fault)

    def _open(self) -> int:
        """Open the lock file, creating it if it is not there.

        Returns:
            The file descriptor.

        Raises:
            RuntimePersistenceError: If it could not be opened.

        Opened rather than checked for existence. The file being present says
        nothing about whether anything holds it, and this module never asks.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as fault:
            msg = f"the instance lock could not be opened: {fault.strerror or fault}"
            raise RuntimePersistenceError(msg) from fault

    def _acquire(self, descriptor: int) -> None:
        """Take the one-byte region, without waiting.

        Args:
            descriptor: The open lock file.

        Raises:
            InstanceAlreadyActiveError: If another process holds it.
            RuntimePersistenceError: If the acquisition failed for another reason.

        ``EACCES`` is the documented refusal and is what the target host produces;
        anything else is a broken filesystem rather than a busy one, and reporting
        it as "another instance is running" would send an operator hunting for a
        process that does not exist.
        """
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, LOCK_REGION_BYTES)
        except OSError as fault:
            if fault.errno in {errno.EACCES, errno.EDEADLK}:
                msg = (
                    "another GLOBIN coordinator is running on this machine and holds "
                    "the instance lock"
                )
                raise InstanceAlreadyActiveError(msg) from fault
            msg = f"the instance lock could not be taken: {fault.strerror or fault}"
            raise RuntimePersistenceError(msg) from fault


@dataclass(slots=True)
class PlatformShutdownSignals:
    """Notices a stop request, and does nothing else inside the handler.

    Args:
        registrar: Installs a handler for one signal. Substitutable so a test can
            observe which signals were registered without altering this process's
            own dispositions, which are global and would leak into every test that
            ran afterwards.
        installed: Which signal names were registered, filled in by
            :meth:`install`. It has **no default**, for the reason
            ``globin.application.bootstrap._RunState`` gives about its own fields:
            a default of ``[]`` would have to be constructed, and constructing one
            in a class body is work performed at import, which every layer package
            is forbidden.
        stopped: Whether a stop has been requested.

    A handler sets :attr:`stopped` and returns. Python runs a signal handler on the
    main thread at the next bytecode boundary, and its documentation warns
    explicitly against synchronisation primitives inside one — so there is no lock
    here, no I/O, and no cleanup. The ordinary control flow reads
    :meth:`requested` and does the work.
    """

    registrar: Callable[[int, Callable[[int, types.FrameType | None], None]], None]
    installed: list[str]
    stopped: bool = False

    def install(self) -> None:
        """Register a handler for every signal this platform actually has.

        Guarded by :func:`hasattr` rather than by a platform string.
        :func:`signal.signal` raises :exc:`ValueError` on Windows for anything
        outside its seven accepted signals, and a start-up that fell over while
        installing its own shutdown path would be failing for the least useful
        possible reason.
        """
        for name in HANDLED_SIGNALS:
            number = getattr(signal, name, None)
            if number is None:
                continue
            self.registrar(int(number), self._handle)
            self.installed.append(name)

    def _handle(self, _number: int, _frame: types.FrameType | None) -> None:
        """Record that a stop was requested.

        Args:
            _number: Which signal arrived. Unused: every handled signal means the
                same thing to GLOBIN, and the *reason* an operator reads comes
                from the lifecycle record rather than from here.
            _frame: The interrupted frame. Unused.
        """
        self.stopped = True

    def request(self) -> None:
        """Ask this process to stop, from inside it.

        Deliberately the same single line as :meth:`_handle`, and the sameness is
        the design rather than a coincidence. One latch, written two ways, read
        once — so :meth:`~globin.application.lifecycle.Session.stop_requested` sees
        a watchdog's request exactly as it sees an operator's ``Ctrl+C``.

        **A plain attribute store, and it must stay one.** Making :attr:`stopped`
        an :class:`threading.Event` would put a lock acquisition on this line and
        on :meth:`_handle`, and the class docstring above records why a lock inside
        a signal handler is the one thing this type may not do. There is no
        read-modify-write to protect, so nothing is lost by having no lock: the
        store is a single bytecode and the value only ever moves one way.
        """
        self.stopped = True

    def requested(self) -> bool:
        """Whether a stop has been asked for.

        Returns:
            ``True`` once a handled signal has arrived, or :meth:`request` was
            called.
        """
        return self.stopped


def register_last_resort(callback: Callable[[], None]) -> None:
    """Register a best-effort cleanup for normal interpreter termination.

    Args:
        callback: What to run.

    **This is a net, not a guarantee, and nothing rests on it.** Python's own
    documentation is explicit that ``atexit`` functions "are not called when the
    program is killed by a signal not handled by Python, when a Python fatal
    internal error is detected, or when ``os._exit()`` is called" — which are
    exactly the cases crash safety is about.

    Crash safety comes from atomic publication instead: whatever was last written
    is complete and readable, whether or not anything got to run afterwards.
    Presenting this as crash protection would be a claim the mechanism cannot
    support.
    """
    atexit.register(callback)


def system_environment() -> MutableMapping[str, str]:
    """The process environment, read in the one place that may read it.

    Returns:
        :data:`os.environ`.

    Exists so that :func:`resolve_root` can take a mapping rather than reach for
    one, which is what keeps the Phase 027 seam open: when configuration sources
    arrive, the composition root passes a different mapping and nothing below
    changes.
    """
    return os.environ
