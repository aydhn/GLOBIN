"""The clean-room harness, in two layers, and the invariant that guards both.

**Layer A always runs.** It builds nothing and installs nothing: the environment
is a directory, the installer is an injected double, and the whole sequence --
create, install, probe, reconcile, clean up -- is exercised end to end without a
network or a real interpreter. That is what makes the failure paths cheap enough
to have all of them.

**Layer B is opt-in and does not run in CI.** It is marked `external`, `network`
and `slow`; every selection in `tools/quality/commands.py` composes
`and not external` into its `-m` expression, so `fast`, `full`, the matrix jobs
and the shards job all exclude it. It reaches the index in a child process, so
the autouse offline guard -- which patches sockets in this interpreter only --
does not need an exemption. That is a property of the existing design rather
than a change to it.

The test that matters most is neither: it puts a decoy `.venv` beside a scratch
root and proves it survives byte for byte, in the success path and in the
failure path. Every mechanism in `cleanroom.py` exists to make that true, and
this is the assertion that would notice if one of them stopped working.
"""

import ast
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.quality.materialize.cleanroom import (
    SCRATCH_PREFIX,
    CleanRoom,
    CleanRoomFault,
    cleanroom_problems,
    installed_from,
)

pytestmark = pytest.mark.integration


class _Installer:
    """A double that answers the way a real installer would, without being one."""

    def __init__(self, *, transcript: str = "", fail_at: str = "") -> None:
        self.transcript = transcript
        self.fail_at = fail_at
        self.calls: list[Sequence[str]] = []

    def __call__(self, argv: Sequence[str], *, cwd: Path, timeout: float) -> tuple[int, str]:
        del cwd, timeout
        self.calls.append(argv)
        joined = " ".join(argv)
        if self.fail_at and self.fail_at in joined:
            return (1, "")
        if "list" in argv:
            return (0, self.transcript)
        return (0, "")


def decoy(root: Path) -> Path:
    """A `.venv` that must be exactly as it was afterwards."""
    venv = root / ".venv"
    (venv / "Scripts").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = C:/Python314\n", encoding="utf-8")
    (venv / "Scripts" / "python.exe").write_bytes(b"not really an interpreter")
    return venv


def fingerprint(venv: Path) -> list[tuple[str, bytes]]:
    """Every file under a tree, with its bytes."""
    return sorted(
        (str(path.relative_to(venv)), path.read_bytes())
        for path in venv.rglob("*")
        if path.is_file()
    )


# ---------------------------------------------------------------------------
# Layer A -- always runs
# ---------------------------------------------------------------------------


def test_a_room_is_created_installed_probed_and_removed(tmp_path: Path) -> None:
    """The whole sequence, with every child injected."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    installer = _Installer(transcript="numpy==2.5.2\npandas==3.0.5\n")

    with tempfile.TemporaryDirectory(
        prefix=SCRATCH_PREFIX, dir=scratch, ignore_cleanup_errors=True
    ) as made:
        room = CleanRoom(root=Path(made), runner=installer)
        assert room.create(Path("python.exe")).ok is True
        assert room.install(tmp_path / "pylock.toml", tmp_path / "house").ok is True
        outcome, transcript = room.probe()
        assert outcome.ok is True
        assert installed_from(transcript) == {"numpy": "2.5.2", "pandas": "3.0.5"}
        assert (
            cleanroom_problems(
                target=Path(made),
                repo_root=tmp_path / "repo",
                scratch_root=scratch,
                is_reparse_point=False,
            )
            == ()
        )
        room_path = Path(made)

    assert not room_path.exists()


def test_the_users_environment_survives_a_successful_run(tmp_path: Path) -> None:
    """The invariant every mechanism in cleanroom.py exists to make true."""
    venv = decoy(tmp_path)
    before = fingerprint(venv)

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with tempfile.TemporaryDirectory(prefix=SCRATCH_PREFIX, dir=scratch) as made:
        room = CleanRoom(root=Path(made), runner=_Installer())
        room.create(Path("python.exe"))
        room.install(tmp_path / "pylock.toml", None)

    assert venv.is_dir()
    assert fingerprint(venv) == before


def test_the_users_environment_survives_a_failing_run(tmp_path: Path) -> None:
    """The failure path touches it no more than the success path does."""
    venv = decoy(tmp_path)
    before = fingerprint(venv)

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with tempfile.TemporaryDirectory(prefix=SCRATCH_PREFIX, dir=scratch) as made:
        room = CleanRoom(root=Path(made), runner=_Installer(fail_at="install"))
        assert room.create(Path("python.exe")).ok is True
        outcome = room.install(tmp_path / "pylock.toml", None)
        assert outcome.fault is CleanRoomFault.INSTALL_FAILED

    assert venv.is_dir()
    assert fingerprint(venv) == before


def executable_strings(source: str) -> list[str]:
    """Every string literal a module would actually evaluate.

    Args:
        source: The module text.

    Returns:
        The literals, with docstrings excluded.

    Docstrings are stripped for the reason Phase 026 discovered the hard way in
    `test_library_discipline.py`: a substring scan cannot tell a module that
    *calls* a forbidden thing from one that *explains why it does not*, and
    `cleanroom.py` is three paragraphs of the latter. Reading the syntax tree
    distinguishes them; reading the bytes cannot.
    """
    tree = ast.parse(source)
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    ]


@pytest.mark.parametrize(
    "forbidden",
    [
        pytest.param("bootstrap.ps1", id="the-bootstrap-script"),
        pytest.param("-Recreate", id="the-recreate-switch"),
    ],
)
def test_the_harness_never_names_the_one_script_that_builds_a_venv(
    repo_root: Path, forbidden: str
) -> None:
    """`scripts/bootstrap.ps1` stays the one way to build `.venv`.

    Two commands that could produce it are two commands that can disagree about
    what it contains, so this asserts the absence rather than trusting it.
    Docstrings are excluded, because this package explains the refusal at length
    and a scan that could not tell explanation from execution would forbid
    documenting the rule.

    **The string `.venv` is deliberately not forbidden**, and that was learned by
    trying it. The usage text promises that the clean-room never touches `.venv`,
    which is a true and useful thing for a command to say; a rule that banned the
    spelling would ban making the promise. What is forbidden is *invoking* the
    one script that builds an environment, which is the behaviour that matters.
    The location checks in `cleanroom_problems` are what stop a real `.venv`
    being reached, and they are tested directly.
    """
    for path in sorted((repo_root / "tools" / "quality" / "materialize").rglob("*.py")):
        literals = executable_strings(path.read_text(encoding="utf-8"))
        assert not [text for text in literals if forbidden in text], (
            f"{path.name} evaluates a string naming {forbidden!r}"
        )


# ---------------------------------------------------------------------------
# Layer B -- opt-in, reaches the index, never runs in CI
# ---------------------------------------------------------------------------


@pytest.mark.external
@pytest.mark.network
@pytest.mark.slow
def test_a_real_environment_can_be_built_from_the_committed_lock(
    repo_root: Path, tmp_path: Path
) -> None:
    """The genuine article: a throwaway interpreter, installed from the real lock.

    Excluded from every command in the quality table by its `external` marker,
    so this runs when somebody asks for it and at no other time. It is the only
    test in the repository that starts a real installer.
    """
    import sys

    scratch = tmp_path / "scratch"
    scratch.mkdir()

    def spawn(argv: Sequence[str], *, cwd: Path, timeout: float) -> tuple[int, str]:
        completed = subprocess.run(  # noqa: S603 -- a list, never a shell string
            list(argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return (completed.returncode, f"{completed.stdout}{completed.stderr}")

    with tempfile.TemporaryDirectory(
        prefix=SCRATCH_PREFIX, dir=scratch, ignore_cleanup_errors=True
    ) as made:
        room = CleanRoom(root=Path(made), runner=spawn, timeout_seconds=900.0)
        created = room.create(Path(sys.executable))
        assert created.ok, created.detail

        installed = room.install(repo_root / "pylock.toml", None)
        assert installed.ok, installed.detail

        outcome, transcript = room.probe()
        assert outcome.ok, outcome.detail
        found = installed_from(transcript)

    assert "numpy" in found
    assert "packaging" in found
