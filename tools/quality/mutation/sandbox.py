"""The throwaway copy of the tree, and the child process run against it.

This is the only module in the package that touches a disk or a process.
Everything it decides is handed to :mod:`tools.quality.mutation.plan` as data, so
that the judgements are testable without a subprocess and this file stays small
enough to read in one sitting.

**Why a copy of the whole tree, and not just the mutated file.** ``pyproject.toml``
sets ``pythonpath = ["src", "."]``, and pytest inserts those at ``sys.path[0]``
resolved against its rootdir — after the interpreter has already processed
``PYTHONPATH``. A harness that wrote the mutant to a temporary directory and put
it on ``PYTHONPATH`` would therefore import the *real* module every time, every
mutant would survive, and the score would be a lie that looks like a finding. The
sandbox owns a copy of ``pyproject.toml``, so its rootdir is the sandbox and its
``src`` is the mutated one. :func:`tools.quality.mutation.__main__` proves this
with a canary before trusting a single verdict.

Nothing is written inside the repository. The sandbox lives under the system
temporary directory, the child writes no bytecode and no cache, and the report
goes to standard output.
"""

import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

#: Never copied. `__pycache__` is excluded for correctness rather than tidiness:
#: a stale `.pyc` carried in from the real tree could be executed in place of a
#: mutant, since CPython validates the cache against a whole-second timestamp and
#: a byte count that most mutations preserve exactly.
IGNORED: Final[tuple[str, ...]] = (
    "__pycache__",
    "*.py[cod]",
    ".pytest_cache",
    ".hypothesis",
    ".mypy_cache",
    ".ruff_cache",
)


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one child process did.

    Args:
        exit_code: What pytest returned, or ``None`` when it was stopped.
        timed_out: Whether the harness stopped it.
        seconds: How long it took. Reported, never asserted on — a test that
            compared this against a number would be a test about the machine.
        output: Everything the child wrote, for a report that has to explain a
            failure nobody can reproduce by eye.
    """

    exit_code: int | None
    timed_out: bool
    seconds: float
    output: bytes


class ProcessRunner(Protocol):
    """How the harness starts a child.

    Injectable so that the timeout path can be driven by a double that raises
    :exc:`subprocess.TimeoutExpired` immediately, rather than by a test that
    sleeps — which ``docs/TESTING_STRATEGY.md`` forbids, and which would make the
    suite's duration depend on the machine.
    """

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        """Run ``argv`` and return its exit code and combined output."""
        ...


def spawn(
    argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout: float
) -> tuple[int, bytes]:
    """Start a real child process. The default :class:`ProcessRunner`."""
    completed = subprocess.run(  # noqa: S603
        list(argv),
        cwd=cwd,
        env=dict(env),
        timeout=timeout,
        capture_output=True,
        check=False,
    )
    return completed.returncode, completed.stdout + completed.stderr


def build(repo_root: Path, entries: Sequence[str], into: Path) -> None:
    """Copy the declared entries into an empty directory.

    Args:
        repo_root: Where to copy from.
        entries: Repository-relative files and directories, from configuration.
        into: The sandbox root, which must already exist.

    Raises:
        FileNotFoundError: If a declared entry does not exist.

    Done once per run rather than once per mutant. The tree is small enough that
    the copy costs milliseconds, and per-mutant only the one mutated file is
    rewritten.
    """
    for entry in entries:
        source = repo_root / entry
        destination = into / entry
        if source.is_dir():
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*IGNORED))
        elif source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        else:
            msg = f"declared in the mutation sandbox but not found: {entry}"
            raise FileNotFoundError(msg)


def write_module(sandbox: Path, relative: str, source: str) -> None:
    """Replace one module inside the sandbox.

    Args:
        sandbox: The sandbox root.
        relative: Repository-relative path of the module.
        source: What to write.

    Written with an explicit encoding and newline so that the child reads the
    same bytes on every platform. Nothing here ever writes into the repository.
    """
    (sandbox / relative).write_text(source, encoding="utf-8", newline="\n")


def run_subset(
    argv: Sequence[str],
    *,
    sandbox: Path,
    env: Mapping[str, str],
    timeout: float,
    run_process: ProcessRunner = spawn,
) -> Outcome:
    """Run one test subset inside the sandbox.

    Args:
        argv: The full command, interpreter first.
        sandbox: The working directory, which is what makes pytest's rootdir the
            sandbox and therefore its ``src`` the mutated one.
        env: The child's environment, already reduced to an allowlist.
        timeout: How long to wait.
        run_process: How to start the child.

    Returns:
        What happened, unjudged. Deciding what an exit code *means* belongs to
        :func:`tools.quality.mutation.plan.classify`.
    """
    started = time.perf_counter()
    try:
        exit_code, output = run_process(argv, cwd=sandbox, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Outcome(
            exit_code=None, timed_out=True, seconds=time.perf_counter() - started, output=b""
        )
    return Outcome(
        exit_code=exit_code,
        timed_out=False,
        seconds=time.perf_counter() - started,
        output=output,
    )
