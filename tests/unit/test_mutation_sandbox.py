"""The impure half of the mutation harness: the throwaway tree and the child process.

Everything here works inside ``tmp_path``. Nothing reads or writes the real
repository, and no test starts a real pytest — the child is a hand-written double
satisfying :class:`~tools.quality.mutation.sandbox.ProcessRunner`, which is how
the timeout path is exercised without a ``sleep``. ``docs/TESTING_STRATEGY.md``
forbids synchronising a test with the clock, and a suite whose duration depended
on a timeout would be a suite whose result depended on the machine.

The harness itself never calls :func:`os.chdir` and never assigns to
:data:`os.environ` — it passes ``cwd`` and ``env`` to the child, exactly as
``tools/quality/runner.py`` already does — so these tests need no ``monkeypatch``
and leave no process state behind for the isolation fixture to complain about.
"""

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import pytest

from tools.quality.mutation import sandbox

ARGV: Final[tuple[str, ...]] = ("python", "-m", "pytest")


class _FixedRunner:
    """A child that reports what it was told to, and records how it was called."""

    def __init__(self, exit_code: int = 0, output: bytes = b"") -> None:
        self.exit_code = exit_code
        self.output = output
        self.calls: list[tuple[Sequence[str], Path, Mapping[str, str], float]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        self.calls.append((argv, cwd, env, timeout))
        return self.exit_code, self.output


class _StoppedRunner:
    """A child that never returns, without taking any time to prove it."""

    def __init__(self) -> None:
        self.calls: list[tuple[Sequence[str], Path, Mapping[str, str], float]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        self.calls.append((argv, cwd, env, timeout))
        raise subprocess.TimeoutExpired(cmd=list(argv), timeout=timeout)


def _tree(root: Path) -> Path:
    """A miniature repository, with something that must not be copied."""
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    cache = root / "src" / "pkg" / "__pycache__"
    cache.mkdir()
    (cache / "module.cpython-314.pyc").write_bytes(b"stale")
    (root / "pyproject.toml").write_text("[tool.example]\n", encoding="utf-8")
    return root


# --------------------------------------------------------------------------
# Building the sandbox
# --------------------------------------------------------------------------


def test_the_declared_entries_are_copied(tmp_path: Path) -> None:
    source = _tree(tmp_path / "repo")
    destination = tmp_path / "sandbox"
    destination.mkdir()

    sandbox.build(source, ["pyproject.toml", "src"], destination)

    assert (destination / "pyproject.toml").is_file()
    assert (destination / "src" / "pkg" / "module.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_stale_bytecode_is_never_carried_into_the_sandbox(tmp_path: Path) -> None:
    """Correctness, not tidiness.

    CPython validates a cached `.pyc` against the source's whole-second timestamp
    and its byte count, and most mutations preserve length exactly. A `.pyc`
    copied in from the real tree could therefore be executed in place of a
    mutant, and the wrong verdict would look like nothing at all.
    """
    source = _tree(tmp_path / "repo")
    destination = tmp_path / "sandbox"
    destination.mkdir()

    sandbox.build(source, ["src"], destination)

    assert not list(destination.rglob("__pycache__"))
    assert not list(destination.rglob("*.pyc"))


def test_an_entry_that_does_not_exist_is_refused_by_name(tmp_path: Path) -> None:
    source = _tree(tmp_path / "repo")
    destination = tmp_path / "sandbox"
    destination.mkdir()

    with pytest.raises(FileNotFoundError, match="absent"):
        sandbox.build(source, ["absent"], destination)


def test_a_module_can_be_replaced_inside_the_sandbox(tmp_path: Path) -> None:
    source = _tree(tmp_path / "repo")
    destination = tmp_path / "sandbox"
    destination.mkdir()
    sandbox.build(source, ["src"], destination)

    sandbox.write_module(destination, "src/pkg/module.py", "VALUE = 2\n")

    assert (destination / "src" / "pkg" / "module.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert (source / "src" / "pkg" / "module.py").read_text(encoding="utf-8") == "VALUE = 1\n"


# --------------------------------------------------------------------------
# Running a subset
# --------------------------------------------------------------------------


@pytest.mark.parametrize("exit_code", [0, 1, 5])
def test_the_exit_code_is_reported_verbatim(tmp_path: Path, exit_code: int) -> None:
    """Unjudged. Deciding what a code *means* belongs to `plan.classify`."""
    runner = _FixedRunner(exit_code=exit_code)

    outcome = sandbox.run_subset(ARGV, sandbox=tmp_path, env={}, timeout=1.0, run_process=runner)

    assert outcome.exit_code == exit_code
    assert not outcome.timed_out


def test_the_child_runs_inside_the_sandbox(tmp_path: Path) -> None:
    """The working directory is what makes pytest's rootdir the sandbox, and.

    therefore its `src` the mutated one rather than the real package.
    """
    runner = _FixedRunner()

    sandbox.run_subset(ARGV, sandbox=tmp_path, env={"PATH": "p"}, timeout=2.0, run_process=runner)

    _argv, cwd, env, timeout = runner.calls[0]
    assert cwd == tmp_path
    assert env == {"PATH": "p"}
    assert timeout == 2.0


def test_the_output_is_kept_for_a_report(tmp_path: Path) -> None:
    runner = _FixedRunner(exit_code=1, output=b"a failure nobody can reproduce by eye")

    outcome = sandbox.run_subset(ARGV, sandbox=tmp_path, env={}, timeout=1.0, run_process=runner)

    assert b"nobody can reproduce" in outcome.output


def test_a_child_that_never_returns_is_reported_as_stopped(tmp_path: Path) -> None:
    """Driven by a double rather than by waiting, so this test takes no time at all."""
    outcome = sandbox.run_subset(
        ARGV, sandbox=tmp_path, env={}, timeout=1.0, run_process=_StoppedRunner()
    )

    assert outcome.timed_out
    assert outcome.exit_code is None


def test_the_real_runner_starts_a_real_child(tmp_path: Path) -> None:
    """A positive control for the default runner.

    Everything above substitutes the child, so without this the harness could be
    unable to start a process at all and every test here would still pass.
    """
    exit_code, output = sandbox.spawn(
        ["python", "-c", "print('alive')"], cwd=tmp_path, env={}, timeout=60.0
    )

    assert exit_code == 0
    assert b"alive" in output
