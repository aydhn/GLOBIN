"""The runtime-state paths a healthy machine never reaches.

Every branch here is an error path, and none of them fires on a working host —
which is exactly why they need tests. A `RuntimePersistenceError` raised with the
wrong message, or an `OSError` escaping where a named refusal was intended, would
first be discovered by an operator on a broken machine, reading a traceback
instead of a sentence.

They are separated from `test_runtime_state_adapters.py` because that file is
about behaviour somebody uses and this one is about behaviour nobody wants. Both
matter; keeping them apart stops the failure paths from being read as the normal
ones.
"""

import atexit
import errno
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from globin.adapters.runtime_state import (
    AtomicStateStore,
    FileOperations,
    PlatformShutdownSignals,
    ProjectRuntimeTree,
    WindowsInstanceLock,
    register_last_resort,
)
from globin.domain.identifiers import RunId
from globin.domain.runtime_state import (
    LOCK_FILE,
    RuntimeArea,
    RuntimeLayout,
    RuntimePersistenceError,
)
from globin.errors import ValidationError

LAYOUT = RuntimeLayout()
RUN = RunId(text="1" * 32)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A prepared runtime tree in a temporary directory."""
    base = tmp_path / "GLOBIN"
    assert ProjectRuntimeTree(root=base, layout=LAYOUT).prepare(LAYOUT) == ()
    return base


def denied(*_args: object, **_kwargs: object) -> None:
    """Fail the way a read-only or locked filesystem does."""
    raise OSError(errno.EACCES, "access is denied")


def tree(root: Path) -> ProjectRuntimeTree:
    """The tree adapter for a root."""
    return ProjectRuntimeTree(root=root, layout=LAYOUT)


def store(root: Path, **broken: Callable[..., object]) -> AtomicStateStore:
    """A store whose filesystem operations are real except those named."""
    return AtomicStateStore(
        root=root,
        layout=LAYOUT,
        operations=FileOperations(**broken),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Preparing a tree that cannot be prepared
# ---------------------------------------------------------------------------


def test_a_root_that_cannot_be_created_is_reported_rather_than_raised(tmp_path: Path) -> None:
    """A refusal an operator can read beats an exception they cannot.

    The whole point of `prepare` returning sentences is that `paths.boundary`
    turns them into a named check failure with a remediation.
    """
    blocked = tmp_path / "file" / "GLOBIN"
    (tmp_path / "file").write_text("not a directory", encoding="utf-8")
    problems = tree(blocked).prepare(LAYOUT)
    assert problems
    assert "runtime root could not be created" in problems[0]


def test_an_area_that_cannot_be_created_is_reported_per_area(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each area is named, so the message says which one to look at."""
    real = Path.mkdir

    def selective(self: Path, *args: object, **kwargs: object) -> None:
        if self.name == "cache":
            denied()
        real(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "mkdir", selective)
    problems = tree(root).prepare(LAYOUT)
    assert any("cache area could not be created" in problem for problem in problems)
    assert not any("state area" in problem for problem in problems)


def test_an_area_resolving_outside_its_root_is_refused_before_it_is_created(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The branch a valid `RuntimeLayout` cannot reach today.

    `RuntimeLayout` validates its own segments, so nothing can currently escape —
    which is exactly when a boundary check is cheap to add and worth having,
    because the day it can happen is the day nobody is looking. Reached here by
    making one area resolve elsewhere.
    """
    escape = root.parent / "elsewhere"
    real = Path.resolve

    def wander(self: Path, *args: object, **kwargs: object) -> Path:
        if self.name == "tmp":
            return escape
        return real(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "resolve", wander)
    problems = tree(root).prepare(LAYOUT)
    assert any("tmp area resolves outside the runtime root" in problem for problem in problems)
    assert not escape.exists()


# ---------------------------------------------------------------------------
# The temporary tree
# ---------------------------------------------------------------------------


def test_a_run_identifier_that_could_leave_the_temporary_area_is_refused() -> None:
    """`RunId` will not hold a traversal, so this is checked where the delete is.

    A value that reaches a recursive delete is verified where the delete happens,
    not only where the name was chosen.
    """

    class _Hostile:
        def __str__(self) -> str:
            return ".."

    with pytest.raises(ValidationError):
        ProjectRuntimeTree(root=Path("C:/nowhere"), layout=LAYOUT).claim_temporary(
            _Hostile()  # type: ignore[arg-type]
        )


def test_a_temporary_directory_that_cannot_be_created_is_named(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "mkdir", lambda *_args, **_kwargs: denied())
    with pytest.raises(RuntimePersistenceError, match="temporary directory could not be created"):
        tree(root).claim_temporary(RUN)


def test_a_temporary_directory_that_cannot_be_removed_is_named(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree(root).claim_temporary(RUN)
    monkeypatch.setattr("globin.adapters.runtime_state.shutil.rmtree", lambda *_a, **_k: denied())
    with pytest.raises(RuntimePersistenceError, match="temporary directory could not be removed"):
        tree(root).release_temporary(RUN)


# ---------------------------------------------------------------------------
# Reading and discarding
# ---------------------------------------------------------------------------


def test_a_document_that_exists_but_cannot_be_read_is_a_persistence_fault(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A third outcome, distinct from the other two.

    Absent reads as `None`; corrupt is a validation fault; unreadable is a
    persistence fault. Three outcomes, three answers.
    """
    store(root).publish(RuntimeArea.STATE, "lifecycle.json", {"a": 1})
    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: denied())
    with pytest.raises(RuntimePersistenceError, match="could not be read"):
        store(root).read(RuntimeArea.STATE, "lifecycle.json")


def test_a_document_that_cannot_be_removed_is_a_persistence_fault(root: Path) -> None:
    store(root).publish(RuntimeArea.STATE, "lifecycle.json", {"a": 1})
    with pytest.raises(RuntimePersistenceError, match="could not be removed"):
        store(root, unlink=denied).discard(RuntimeArea.STATE, "lifecycle.json")


def test_a_directory_that_cannot_be_created_names_the_area(root: Path) -> None:
    with pytest.raises(RuntimePersistenceError, match="state could not be created"):
        store(root, makedirs=denied).publish(RuntimeArea.STATE, "lifecycle.json", {"a": 1})


# ---------------------------------------------------------------------------
# The lock
# ---------------------------------------------------------------------------


def test_a_lock_failure_that_is_not_contention_is_not_reported_as_contention(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`EACCES` means another holder; anything else means a broken filesystem.

    Reporting the second as the first would send an operator hunting for a
    process that does not exist.
    """

    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "there is no space left")

    monkeypatch.setattr("globin.adapters.runtime_state.msvcrt.locking", broken)
    lock = WindowsInstanceLock(root=root, layout=LAYOUT, name=LOCK_FILE)
    with pytest.raises(RuntimePersistenceError, match="could not be taken"), lock.hold():
        pass


def test_a_probe_reports_a_broken_tree_as_well_as_a_busy_one(root: Path) -> None:
    """Both refusals reach the caller as a sentence rather than an exception.

    `instance.lock` turns whatever comes back into a check outcome, so a probe
    that raised would replace a named failure with a traceback.
    """
    (root / LAYOUT.segment_for(RuntimeArea.RUN) / LOCK_FILE).mkdir()
    lock = WindowsInstanceLock(root=root, layout=LAYOUT, name=LOCK_FILE)
    assert "could not be opened" in lock.probe()


# ---------------------------------------------------------------------------
# Signals and the last-resort net
# ---------------------------------------------------------------------------


def test_a_signal_this_platform_lacks_is_skipped_rather_than_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`signal.signal` raises `ValueError` for anything Windows does not accept.

    Reached by removing one that does exist, since the branch cannot otherwise be
    taken on a host where all three are present.
    """
    monkeypatch.delattr("signal.SIGBREAK", raising=False)
    signals = PlatformShutdownSignals(registrar=lambda *_a: None, installed=[])
    signals.install()
    assert "SIGBREAK" not in signals.installed
    assert "SIGINT" in signals.installed


def test_the_last_resort_hook_is_handed_to_atexit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The net is `atexit` and nothing cleverer, and it is not invoked here.

    Observed by substituting `atexit.register` rather than by counting what the
    real registry holds. **That count is global and shared**: coverage, pytest
    plugins and the interpreter itself register handlers, so a count taken twice
    around one call can legitimately differ — which is a flaky test rather than a
    property of GLOBIN, and is how the first version of this failed in CI and
    nowhere else.

    Substituting also means nothing is left registered. A real registration would
    run a test's callback at interpreter exit, long after the test that made it
    finished, and surface in whatever happened to run last.
    """
    handed: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", handed.append)

    def note() -> None:
        raise AssertionError

    register_last_resort(note)
    assert handed == [note]


def test_the_environment_reader_returns_the_real_environment() -> None:
    from globin.adapters.runtime_state import system_environment

    assert system_environment() is os.environ
