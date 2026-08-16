"""The runtime-state adapter: resolving a root, publishing a document, taking a lock.

Every test here builds its tree in `tmp_path`, so nothing touches a real user
profile and nothing depends on what a previous run left behind.

**The failure-injection tests are the reason `FileOperations` exists.** Proving
that a failed `fsync` leaves the previous document intact needs a disk that fails
`fsync`, and nobody has one to hand. Substituting exactly one stage is how each
guarantee is checked separately, and the assertion after each is always the same
one: *the destination still holds what it held before*.
"""

import errno
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from globin.adapters.runtime_state import (
    LOCAL_APPLICATION_DATA,
    AtomicStateStore,
    FileOperations,
    PlatformShutdownSignals,
    ProjectRuntimeTree,
    WindowsInstanceLock,
    record_root,
    render,
    resolve_root,
    system_environment,
)
from globin.domain.identifiers import RunId
from globin.domain.runtime_state import (
    LOCK_FILE,
    InstanceAlreadyActiveError,
    RuntimeArea,
    RuntimeLayout,
    RuntimePersistenceError,
)
from globin.errors import ValidationError

if TYPE_CHECKING:
    from types import FrameType

LAYOUT = RuntimeLayout()
RUN = RunId(text="c" * 32)
OTHER_RUN = RunId(text="d" * 32)
DOCUMENT: dict[str, object] = {"schema_version": 1, "status": "running"}
LATER: dict[str, object] = {"schema_version": 1, "status": "stopped"}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A prepared runtime tree in a temporary directory."""
    base = tmp_path / "GLOBIN"
    assert ProjectRuntimeTree(root=base, layout=LAYOUT).prepare(LAYOUT) == ()
    return base


def store(root: Path, **broken: Callable[..., object]) -> AtomicStateStore:
    """A store whose filesystem operations are the real ones except those named."""
    return AtomicStateStore(
        root=root,
        layout=LAYOUT,
        operations=FileOperations(**broken),  # type: ignore[arg-type]
    )


def refuse(*_args: object, **_kwargs: object) -> None:
    """Fail the way a full or read-only disk does."""
    raise OSError(errno.EACCES, "access is denied")


# ---------------------------------------------------------------------------
# Finding the root
# ---------------------------------------------------------------------------


def test_the_root_is_the_namespace_under_the_platforms_per_user_area() -> None:
    resolved = resolve_root({LOCAL_APPLICATION_DATA: "C:/Users/Someone/AppData/Local"}, LAYOUT)
    assert resolved.name == "GLOBIN"


@pytest.mark.parametrize(
    "environment",
    [
        pytest.param({}, id="the variable is absent"),
        pytest.param({LOCAL_APPLICATION_DATA: ""}, id="the variable is empty"),
        pytest.param({LOCAL_APPLICATION_DATA: "   "}, id="the variable is blank"),
    ],
)
def test_a_platform_that_will_not_say_where_per_user_data_goes_is_refused(
    environment: dict[str, str],
) -> None:
    """Refusing is the whole point.

    Falling back to the home directory or the working directory would put a
    machine-wide coordinator lock somewhere that depends on how GLOBIN was
    started, which would make it guard nothing.
    """
    with pytest.raises(RuntimePersistenceError, match="will not guess"):
        resolve_root(environment, LAYOUT)


def test_the_root_is_never_published_as_a_path() -> None:
    """A path under a user profile carries the account holder's name."""
    recorded = record_root(Path("C:/Users/Someone/AppData/Local/GLOBIN"))
    assert recorded.path is None
    assert recorded.fingerprint
    assert "Someone" not in str(recorded.as_record())


def test_the_environment_reader_is_the_one_place_that_reads_one() -> None:
    """It exists so `resolve_root` can take a mapping rather than reach for one."""
    assert system_environment() is os.environ


# ---------------------------------------------------------------------------
# Preparing the tree
# ---------------------------------------------------------------------------


def test_preparing_creates_every_area(root: Path) -> None:
    for area in LAYOUT.areas():
        assert (root / LAYOUT.segment_for(area)).is_dir()


def test_preparing_twice_changes_nothing(root: Path) -> None:
    assert ProjectRuntimeTree(root=root, layout=LAYOUT).prepare(LAYOUT) == ()


def test_an_area_that_exists_as_a_file_is_reported_rather_than_overwritten(
    tmp_path: Path,
) -> None:
    base = tmp_path / "GLOBIN"
    base.mkdir()
    (base / "cache").write_text("not a directory", encoding="utf-8")
    problems = ProjectRuntimeTree(root=base, layout=LAYOUT).prepare(LAYOUT)
    assert any("cache area exists and is not a directory" in problem for problem in problems)
    assert (base / "cache").read_text(encoding="utf-8") == "not a directory"


def test_a_root_that_exists_as_a_file_is_refused_before_anything_is_created(
    tmp_path: Path,
) -> None:
    base = tmp_path / "GLOBIN"
    base.write_text("not a directory", encoding="utf-8")
    problems = ProjectRuntimeTree(root=base, layout=LAYOUT).prepare(LAYOUT)
    assert problems
    assert base.is_file()


def test_the_root_is_resolved_after_it_exists(tmp_path: Path) -> None:
    """The ordering bug this caught, pinned so it cannot come back.

    `Path.resolve` leaves a non-existent tail alone, so a root resolved before it
    exists and an area resolved after it can disagree whenever anything on the way
    is a junction — which is the normal state of a per-user data directory inside
    a Windows application container. Both sides are resolved after creation.
    """
    base = tmp_path / "nested" / "deeper" / "GLOBIN"
    assert ProjectRuntimeTree(root=base, layout=LAYOUT).prepare(LAYOUT) == ()


def test_the_description_names_no_path(root: Path) -> None:
    described = ProjectRuntimeTree(root=root, layout=LAYOUT).describe()
    assert str(root) not in described
    assert "per-user application data" in described


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_a_document_renders_to_one_sorted_ascii_line() -> None:
    rendered = render({"b": 2, "a": 1})
    assert rendered == '{"a":1,"b":2}\n'


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        pytest.param(float("nan"), "not-a-number", id="nan"),
        pytest.param(float("inf"), "infinity", id="infinity"),
        pytest.param(-float("inf"), "negative infinity", id="negative infinity"),
    ],
)
def test_a_value_json_cannot_express_is_refused(value: float, reason: str) -> None:
    """`NaN` and `Infinity` are not JSON, and every standard reader refuses them.

    Writing one would produce a file only Python could read back, turning a
    numeric mistake into a corrupt document.
    """
    with pytest.raises(ValidationError, match="cannot be written as JSON"):
        render({"x": value})
    assert reason


def test_an_unserialisable_value_is_refused() -> None:
    with pytest.raises(ValidationError, match="cannot be written as JSON"):
        render({"x": object()})


# ---------------------------------------------------------------------------
# Publishing, and the guarantee under each failure
# ---------------------------------------------------------------------------


def published(root: Path, name: str = "lifecycle.json") -> dict[str, object]:
    """Read back what is actually on disk."""
    text = (root / LAYOUT.segment_for(RuntimeArea.STATE) / name).read_text(encoding="utf-8")
    document = json.loads(text)
    assert isinstance(document, dict)
    return document


def test_a_document_is_published_and_reads_back(root: Path) -> None:
    store(root).publish(RuntimeArea.STATE, "lifecycle.json", DOCUMENT)
    assert published(root) == DOCUMENT
    assert store(root).read(RuntimeArea.STATE, "lifecycle.json") == DOCUMENT


def test_republishing_replaces_the_previous_document(root: Path) -> None:
    """`os.replace` overwrites; `Path.rename` would refuse on Windows."""
    store(root).publish(RuntimeArea.STATE, "lifecycle.json", DOCUMENT)
    store(root).publish(RuntimeArea.STATE, "lifecycle.json", LATER)
    assert published(root) == LATER


def test_a_publication_leaves_no_temporary_artefact_behind(root: Path) -> None:
    store(root).publish(RuntimeArea.STATE, "lifecycle.json", DOCUMENT)
    directory = root / LAYOUT.segment_for(RuntimeArea.STATE)
    assert [entry.name for entry in directory.iterdir()] == ["lifecycle.json"]


def test_the_temporary_file_is_written_beside_the_destination(root: Path) -> None:
    """A rename is only atomic within one filesystem.

    A temporary file in the platform temporary directory would silently turn the
    atomic step into a copy, which is exactly the guarantee being bought.
    """
    seen: list[tuple[Path, Path]] = []

    def observe(source: Path, target: Path) -> None:
        seen.append((source, target))
        os.replace(source, target)  # noqa: PTH105 - the real operation, which is the subject

    store(root, replace=observe).publish(RuntimeArea.STATE, "lifecycle.json", DOCUMENT)
    source, target = seen[0]
    assert source.parent == target.parent


@pytest.mark.parametrize(
    "stage",
    ["makedirs", "flush", "fsync", "replace"],
)
def test_a_failure_at_any_stage_leaves_the_previous_document_intact(root: Path, stage: str) -> None:
    """The guarantee the whole mechanism exists for, checked one stage at a time.

    A reader must never observe a truncated document, so a publication that could
    not complete must not have touched the destination at all.
    """
    store(root).publish(RuntimeArea.STATE, "lifecycle.json", DOCUMENT)
    with pytest.raises(RuntimePersistenceError):
        store(root, **{stage: refuse}).publish(RuntimeArea.STATE, "lifecycle.json", LATER)
    assert published(root) == DOCUMENT


@pytest.mark.parametrize("stage", ["flush", "fsync", "replace"])
def test_a_failed_publication_cleans_up_its_temporary_artefact(root: Path, stage: str) -> None:
    store(root).publish(RuntimeArea.STATE, "lifecycle.json", DOCUMENT)
    with pytest.raises(RuntimePersistenceError):
        store(root, **{stage: refuse}).publish(RuntimeArea.STATE, "lifecycle.json", LATER)
    directory = root / LAYOUT.segment_for(RuntimeArea.STATE)
    assert [entry.name for entry in directory.iterdir()] == ["lifecycle.json"]


def test_a_cleanup_that_also_fails_does_not_replace_the_fault_worth_reporting(
    root: Path,
) -> None:
    """The operator has to act on the write failure, not on the tidying failure."""
    with pytest.raises(RuntimePersistenceError, match="could not be published"):
        store(root, replace=refuse, unlink=refuse).publish(
            RuntimeArea.STATE, "lifecycle.json", DOCUMENT
        )


def test_an_unrepresentable_document_never_reaches_the_destination(root: Path) -> None:
    """The encoding happens before anything is opened.

    So a document that cannot be written does not truncate what was there.
    """
    store(root).publish(RuntimeArea.STATE, "lifecycle.json", DOCUMENT)
    with pytest.raises(ValidationError):
        store(root).publish(RuntimeArea.STATE, "lifecycle.json", {"x": float("nan")})
    assert published(root) == DOCUMENT


@pytest.mark.parametrize("name", ["../escape.json", "a/b.json", "C:/absolute.json", ".."])
def test_a_name_that_could_leave_the_area_is_refused_by_every_method(root: Path, name: str) -> None:
    calls: tuple[Callable[[], object], ...] = (
        lambda: store(root).publish(RuntimeArea.STATE, name, DOCUMENT),
        lambda: store(root).read(RuntimeArea.STATE, name),
        lambda: store(root).discard(RuntimeArea.STATE, name),
    )
    for call in calls:
        with pytest.raises(ValidationError):
            call()


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------


def test_a_document_that_is_not_there_reads_as_none(root: Path) -> None:
    assert store(root).read(RuntimeArea.STATE, "absent.json") is None


def test_a_corrupt_document_is_refused_rather_than_treated_as_absent(root: Path) -> None:
    """Corrupt and absent mean opposite things, and one is worth reporting."""
    target = root / LAYOUT.segment_for(RuntimeArea.STATE) / "lifecycle.json"
    target.write_text("{ truncated", encoding="utf-8")
    with pytest.raises(ValidationError, match="not valid JSON"):
        store(root).read(RuntimeArea.STATE, "lifecycle.json")


def test_a_document_that_is_not_an_object_is_refused(root: Path) -> None:
    target = root / LAYOUT.segment_for(RuntimeArea.STATE) / "lifecycle.json"
    target.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValidationError, match="state document is an object"):
        store(root).read(RuntimeArea.STATE, "lifecycle.json")


def test_discarding_something_that_is_not_there_is_not_an_error(root: Path) -> None:
    """Absence is not a failure here.

    This runs on the shutdown path, where the alternative is a teardown that fails
    because its work was already done.
    """
    store(root).discard(RuntimeArea.STATE, "absent.json")


def test_discarding_removes_the_document(root: Path) -> None:
    store(root).publish(RuntimeArea.STATE, "lifecycle.json", DOCUMENT)
    store(root).discard(RuntimeArea.STATE, "lifecycle.json")
    assert store(root).read(RuntimeArea.STATE, "lifecycle.json") is None


# ---------------------------------------------------------------------------
# The temporary tree
# ---------------------------------------------------------------------------


def test_a_run_claims_and_releases_only_its_own_directory(root: Path) -> None:
    tree = ProjectRuntimeTree(root=root, layout=LAYOUT)
    tree.claim_temporary(RUN)
    tree.claim_temporary(OTHER_RUN)
    (root / LAYOUT.segment_for(RuntimeArea.TMP) / str(RUN) / "scratch").write_text(
        "work", encoding="utf-8"
    )

    tree.release_temporary(RUN)

    assert not (root / LAYOUT.segment_for(RuntimeArea.TMP) / str(RUN)).exists()
    assert (root / LAYOUT.segment_for(RuntimeArea.TMP) / str(OTHER_RUN)).is_dir()


def test_releasing_a_directory_that_is_already_gone_is_not_an_error(root: Path) -> None:
    ProjectRuntimeTree(root=root, layout=LAYOUT).release_temporary(RUN)


def test_the_other_areas_survive_a_release(root: Path) -> None:
    """The recursive delete may reach beneath `tmp` and nowhere else."""
    tree = ProjectRuntimeTree(root=root, layout=LAYOUT)
    store(root).publish(RuntimeArea.STATE, "lifecycle.json", DOCUMENT)
    tree.claim_temporary(RUN)
    tree.release_temporary(RUN)
    assert published(root) == DOCUMENT
    for area in LAYOUT.areas():
        assert (root / LAYOUT.segment_for(area)).is_dir()


# ---------------------------------------------------------------------------
# The lock
# ---------------------------------------------------------------------------


def a_lock(root: Path) -> WindowsInstanceLock:
    """The coordinator lock for a tree."""
    return WindowsInstanceLock(root=root, layout=LAYOUT, name=LOCK_FILE)


def test_the_lock_can_be_taken_and_taken_again_after_release(root: Path) -> None:
    with a_lock(root).hold():
        pass
    with a_lock(root).hold():
        pass


def test_a_probe_reports_availability_without_keeping_the_lock(root: Path) -> None:
    """A probe is not ownership.

    A diagnostic that held the real lock would refuse to run beside a running
    GLOBIN, which is exactly when somebody wants to run it.
    """
    assert a_lock(root).probe() == ""
    with a_lock(root).hold():
        pass


def test_the_lock_file_is_left_behind_and_that_proves_nothing(root: Path) -> None:
    """The rule the whole design turns on.

    A crashed process leaves its lock file. The file being present must not stop
    the next start-up, and nothing deletes it on a guess.
    """
    with a_lock(root).hold():
        pass
    assert a_lock(root).path.exists()
    assert a_lock(root).probe() == ""


def test_the_lock_is_released_even_when_the_block_raises(root: Path) -> None:
    with pytest.raises(RuntimeError), a_lock(root).hold():  # noqa: PT012 - the block is a context manager plus the statement that must raise inside it
        msg = "the application failed"
        raise RuntimeError(msg)
    assert a_lock(root).probe() == ""


def test_a_lock_file_that_cannot_be_opened_is_a_broken_tree_not_a_busy_one(
    tmp_path: Path,
) -> None:
    """A broken tree is not a busy one.

    Reporting this as an active instance would send an operator hunting for a
    process that does not exist.
    """
    base = tmp_path / "GLOBIN"
    (base / LAYOUT.segment_for(RuntimeArea.RUN)).mkdir(parents=True)
    (base / LAYOUT.segment_for(RuntimeArea.RUN) / LOCK_FILE).mkdir()
    with pytest.raises(RuntimePersistenceError, match="could not be opened"), a_lock(base).hold():
        pass


def test_a_refused_acquisition_is_named_as_an_active_instance(root: Path) -> None:
    """`EACCES` is the documented refusal and what the target host produces."""
    lock = a_lock(root)
    descriptor = os.open(lock.path.parent.joinpath(LOCK_FILE), os.O_RDWR | os.O_CREAT)
    try:
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        try:
            with pytest.raises(InstanceAlreadyActiveError, match="another GLOBIN"), lock.hold():
                pass
            assert "another GLOBIN" in lock.probe()
        finally:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(descriptor)


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


def test_only_signals_this_platform_has_are_registered() -> None:
    """`signal.signal` raises `ValueError` for anything Windows does not accept.

    A start-up that fell over while installing its own shutdown path would be
    failing for the least useful possible reason.
    """
    registered: list[int] = []
    signals = PlatformShutdownSignals(
        registrar=lambda number, _handler: registered.append(number), installed=[]
    )
    signals.install()
    assert signals.installed
    assert set(signals.installed) <= {"SIGINT", "SIGTERM", "SIGBREAK"}
    assert len(registered) == len(signals.installed)


def test_a_handler_sets_a_flag_and_nothing_else() -> None:
    """The handler does the least it can.

    Python runs one on the main thread at a bytecode boundary, and its
    documentation warns against synchronisation primitives inside one.
    """
    captured: list[Callable[[int, FrameType | None], None]] = []
    signals = PlatformShutdownSignals(
        registrar=lambda _number, handler: captured.append(handler), installed=[]
    )
    signals.install()

    assert signals.requested() is False
    captured[0](2, None)
    assert signals.requested() is True
