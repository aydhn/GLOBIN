"""The coordinator lock, proved across real Windows processes.

Every other test of the lock runs in one interpreter, and one interpreter can
convince itself of almost anything. This is the test that establishes the
property the whole single-instance design rests on: **while one process holds the
lock, a different process cannot take it, and when the first exits the next
can** — including when the first exits without unwinding.

**The handshake is file-based, not time-based.** A test that slept and hoped
would be flaky on a loaded machine and would pass for the wrong reason on a fast
one. The child writes a file when it has the lock; the parent waits for that file
to appear, with a deadline. Every wait is bounded and every child is killed in a
`finally`, so a failure here leaves no orphan holding a lock the next test needs.

The children reach no network, so the offline guard — which does not cross a
process boundary — is not being evaded. They import GLOBIN, take a lock, and exit.
"""

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from globin.domain.bootstrap import ExitCode
from globin.domain.runtime_state import LOCK_FILE, RuntimeArea, RuntimeLayout
from tests.support import REPO_ROOT

LAYOUT = RuntimeLayout()

DEADLINE_SECONDS: float = 30.0
"""How long any wait here may take before the test fails.

Bounded rather than open-ended: a hung child would otherwise stall the suite
rather than report a broken lock.
"""

POLL_SECONDS: float = 0.02
"""How often a wait re-checks. Small enough not to dominate the test's runtime."""

HOLDER = """
import os, sys, time
from pathlib import Path
from globin.domain.runtime_state import LOCK_FILE, RuntimeLayout
from globin.adapters.runtime_state import ProjectRuntimeTree, WindowsInstanceLock

root, ready, release = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
layout = RuntimeLayout()
ProjectRuntimeTree(root=root, layout=layout).prepare(layout)
lock = WindowsInstanceLock(root=root, layout=layout, name=LOCK_FILE)
with lock.hold():
    ready.write_text(str(os.getpid()), encoding="utf-8")
    deadline = time.monotonic() + 60
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
sys.exit(0)
"""

CONTENDER = """
import sys
from pathlib import Path
from globin.domain.bootstrap import ExitCode
from globin.domain.runtime_state import (
    LOCK_FILE,
    InstanceAlreadyActiveError,
    RuntimeLayout,
)
from globin.adapters.runtime_state import ProjectRuntimeTree, WindowsInstanceLock

root = Path(sys.argv[1])
layout = RuntimeLayout()
ProjectRuntimeTree(root=root, layout=layout).prepare(layout)
lock = WindowsInstanceLock(root=root, layout=layout, name=LOCK_FILE)
try:
    with lock.hold():
        print("ACQUIRED")
except InstanceAlreadyActiveError as fault:
    print("REFUSED")
    sys.exit(int(ExitCode.INSTANCE_ALREADY_ACTIVE))
sys.exit(int(ExitCode.OK))
"""

CRASHER = """
import os, sys
from pathlib import Path
from globin.domain.runtime_state import LOCK_FILE, RuntimeLayout
from globin.adapters.runtime_state import ProjectRuntimeTree, WindowsInstanceLock

root, ready = Path(sys.argv[1]), Path(sys.argv[2])
layout = RuntimeLayout()
ProjectRuntimeTree(root=root, layout=layout).prepare(layout)
lock = WindowsInstanceLock(root=root, layout=layout, name=LOCK_FILE)
with lock.hold():
    ready.write_text(str(os.getpid()), encoding="utf-8")
    # Leave without unwinding: no `finally`, no `atexit`, no unlock. This is what
    # a killed process looks like from the outside, and the operating system is
    # what has to release the region.
    os._exit(9)
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A runtime root in a temporary directory, never a real user profile."""
    return tmp_path / "GLOBIN"


def _environment() -> dict[str, str]:
    """The child's environment: this interpreter's, with the source tree importable.

    `pythonpath = ["src"]` is a pytest setting and does not reach a child, so the
    child is told where the package is rather than left to guess.
    """
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH", "")
    source = str(REPO_ROOT / "src")
    environment["PYTHONPATH"] = f"{source}{os.pathsep}{existing}" if existing else source
    return environment


def _spawn(script: str, *arguments: str) -> subprocess.Popen[str]:
    """Start a child running one of the scripts above."""
    return subprocess.Popen(  # noqa: S603 - the interpreter and script are this file's own
        [sys.executable, "-c", script, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_environment(),
        cwd=REPO_ROOT,
    )


def _await_file(path: Path, *, what: str) -> None:
    """Wait for a file to appear, or fail the test.

    Args:
        path: What to wait for.
        what: What it means, for the failure message.

    Raises:
        AssertionError: If it does not appear before the deadline.
    """
    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(POLL_SECONDS)
    pytest.fail(f"{what} did not happen within {DEADLINE_SECONDS} seconds", pytrace=False)


@pytest.fixture
def reaper() -> Iterator[list[subprocess.Popen[str]]]:
    """Kill every child this test started, however the test ends.

    A leaked holder would keep the lock and make the *next* test fail, which is
    the worst way to learn about it.

    The pipes are closed as well as the process reaped. `Popen` opens two, and
    leaving them to the garbage collector raises a `ResourceWarning` that this
    suite's strict warning configuration turns into an error — in the *next* test,
    which is again the worst way to learn about it.
    """
    children: list[subprocess.Popen[str]] = []
    yield children
    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=DEADLINE_SECONDS)
        for pipe in (child.stdout, child.stderr, child.stdin):
            if pipe is not None:
                pipe.close()


@pytest.mark.windows
def test_one_coordinator_at_a_time_across_real_processes(
    root: Path, reaper: list[subprocess.Popen[str]]
) -> None:
    """The sequence the phase exists to guarantee.

    A holder takes the lock; a second process is refused with the exit code a
    launcher branches on; the holder exits; a third process takes it.
    """
    ready = root.parent / "ready"
    release = root.parent / "release"

    holder = _spawn(HOLDER, str(root), str(ready), str(release))
    reaper.append(holder)
    _await_file(ready, what="the first coordinator taking the lock")

    contender = subprocess.run(  # noqa: S603 - as `_spawn`
        [sys.executable, "-c", CONTENDER, str(root)],
        capture_output=True,
        text=True,
        timeout=DEADLINE_SECONDS,
        check=False,
        env=_environment(),
        cwd=REPO_ROOT,
    )
    assert contender.returncode == int(ExitCode.INSTANCE_ALREADY_ACTIVE), contender.stderr
    assert "REFUSED" in contender.stdout

    release.write_text("go", encoding="utf-8")
    assert holder.wait(timeout=DEADLINE_SECONDS) == 0

    third = subprocess.run(  # noqa: S603 - as `_spawn`
        [sys.executable, "-c", CONTENDER, str(root)],
        capture_output=True,
        text=True,
        timeout=DEADLINE_SECONDS,
        check=False,
        env=_environment(),
        cwd=REPO_ROOT,
    )
    assert third.returncode == int(ExitCode.OK), third.stderr
    assert "ACQUIRED" in third.stdout


@pytest.mark.windows
def test_a_process_that_dies_without_unwinding_still_releases_the_lock(
    root: Path, reaper: list[subprocess.Popen[str]]
) -> None:
    """The reason a stale lock file is harmless.

    The child leaves through `os._exit`, so no `finally` runs, no `atexit` runs
    and nothing unlocks anything. The operating system releases the region because
    the process holding it ended — which is what makes "delete the stale lock
    file" both unnecessary and wrong.
    """
    ready = root.parent / "crashed"

    crasher = _spawn(CRASHER, str(root), str(ready))
    reaper.append(crasher)
    _await_file(ready, what="the coordinator taking the lock before it dies")
    assert crasher.wait(timeout=DEADLINE_SECONDS) == 9

    lock_file = root / LAYOUT.segment_for(RuntimeArea.RUN) / LOCK_FILE
    assert lock_file.exists(), "the crashed process left its lock file, as expected"

    survivor = subprocess.run(  # noqa: S603 - as `_spawn`
        [sys.executable, "-c", CONTENDER, str(root)],
        capture_output=True,
        text=True,
        timeout=DEADLINE_SECONDS,
        check=False,
        env=_environment(),
        cwd=REPO_ROOT,
    )
    assert survivor.returncode == int(ExitCode.OK), survivor.stderr
    assert "ACQUIRED" in survivor.stdout


@pytest.mark.windows
def test_two_trees_do_not_contend(
    root: Path, tmp_path: Path, reaper: list[subprocess.Popen[str]]
) -> None:
    """The lock guards a tree, not the machine's idea of GLOBIN.

    Worth pinning because it is what makes the tests above safe to run beside a
    real GLOBIN: a temporary root contends with nothing.
    """
    ready = root.parent / "ready-a"
    release = root.parent / "release-a"
    other = tmp_path / "OTHER"

    holder = _spawn(HOLDER, str(root), str(ready), str(release))
    reaper.append(holder)
    _await_file(ready, what="the first coordinator taking the lock")

    elsewhere = subprocess.run(  # noqa: S603 - as `_spawn`
        [sys.executable, "-c", CONTENDER, str(other)],
        capture_output=True,
        text=True,
        timeout=DEADLINE_SECONDS,
        check=False,
        env=_environment(),
        cwd=REPO_ROOT,
    )
    release.write_text("go", encoding="utf-8")
    assert elsewhere.returncode == int(ExitCode.OK), elsewhere.stderr
