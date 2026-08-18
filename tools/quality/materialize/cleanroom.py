"""Building a throwaway environment, and never touching the one you are using.

**The user's `.venv` is never deleted, recreated or written to by anything in
this module.** Three independent mechanisms hold that, and any one of them alone
would be sufficient:

1. **Location.** The environment is created under the platform's own temporary
   directory with a distinctive prefix, which is neither the repository nor the
   user-local runtime tree. ``scripts/bootstrap.ps1`` is never called, and
   ``-Recreate`` is never invoked from here: this builds a *new* environment and
   removes nothing that existed before it ran.
2. **A refusal that names the danger.** :func:`cleanroom_problems` refuses to
   remove anything that is not strictly beneath the scratch root, is the scratch
   root itself, is reachable inside the repository, or does not carry the
   prefix. Four checks, deliberately redundant, in the shape
   ``tools/quality/runtime/plan.py`` uses so that no recursive delete is ever
   decided anywhere but in a pure function with tests.
3. **Cleanup on every ordinary exit.** The caller owns a context manager, so the
   tree goes on return, on exception and on ``KeyboardInterrupt``.

What none of that covers, stated rather than implied: ``os._exit``, a kill
signal, and power loss. Nothing in Python cleans up after those. What bounds the
damage is that the residue is a prefixed directory under the system temporary
root, which the platform reclaims and a person can identify at a glance.

**Every process is injected.** :class:`ProcessRunner` is a seam, and the whole
failure vocabulary below is driven from literals in the unit tests -- a timeout
by a double that raises immediately rather than by a test that sleeps, which
``docs/TESTING_STRATEGY.md`` forbids.
"""

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol

SCRATCH_PREFIX: Final[str] = "globin-cleanroom-"
"""What every throwaway environment's directory is called.

Checked before any removal, so that a path which is somehow beneath the scratch
root but was not created here is still refused.
"""

DEFAULT_TIMEOUT: Final[float] = 900.0
"""How long a child may run. Fifteen minutes, matching the lock gate's relock."""


class CleanRoomFault(StrEnum):
    """Why a clean-room run did not finish."""

    ENVIRONMENT_REFUSED = "environment_refused"
    """The interpreter would not create a virtual environment."""

    INSTALL_FAILED = "install_failed"
    """The installer exited non-zero."""

    INSTALL_TIMED_OUT = "install_timed_out"
    """The installer did not finish inside the declared bound."""

    INSTALL_INTERRUPTED = "install_interrupted"
    """The installer was stopped part-way, so the environment is half-built."""

    PROBE_DISAGREED = "probe_disagreed"
    """What was installed is not what the lock names."""

    SCRATCH_REFUSED = "scratch_refused"
    """The scratch directory failed the safety checks and nothing was run."""


class ProcessRunner(Protocol):
    """How a child process is started.

    Injected rather than called directly, and that is not a convenience. The
    autouse offline guard patches sockets **in this interpreter only**, so a test
    that started a real child would sail straight past it. A double also drives
    the timeout path immediately instead of by sleeping.
    """

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout: float,
    ) -> tuple[int, str]:
        """Run one child and return its status and combined output.

        Args:
            argv: The command, as a list. **Never a shell string**, so there is
                no quoting surface and no injection surface.
            cwd: Where to run it.
            timeout: How long it may take.

        Returns:
            The exit status and what it printed.

        Raises:
            subprocess.TimeoutExpired: If it outlived the bound.
        """
        ...


@dataclass(frozen=True, slots=True)
class CleanRoomOutcome:
    """What one clean-room step concluded.

    Args:
        ok: Whether it did what was asked.
        fault: Why not, when it did not.
        detail: A bounded sentence. Never a raw child transcript, which can be
            megabytes and can carry a path.
    """

    ok: bool
    fault: CleanRoomFault | None = None
    detail: str = ""

    def as_record(self) -> dict[str, object]:
        """Render as ordinary data."""
        return {
            "ok": self.ok,
            "fault": None if self.fault is None else self.fault.value,
            "detail": self.detail,
        }


def cleanroom_problems(
    *,
    target: Path,
    repo_root: Path,
    scratch_root: Path,
    is_reparse_point: bool,
) -> tuple[str, ...]:
    """Every reason a directory must not be removed as a clean room.

    Args:
        target: What is about to be removed.
        repo_root: The repository, which must never contain the target.
        scratch_root: The temporary root the target must be strictly beneath.
        is_reparse_point: Whether the target is a link, junction or mount point.

    Returns:
        One sentence per problem, empty when removal is safe.

    Four checks that would all have to fail together, in the shape
    ``tools/quality/runtime/plan.py:deletion_problems`` uses -- which exists, in
    its own words, so that no recursive delete is ever decided in PowerShell.
    Pure, so every refusal is testable without creating anything.
    """
    problems: list[str] = []
    if target == scratch_root:
        problems.append("the target is the scratch root itself, not a room inside it")
    if not _beneath(target, scratch_root):
        problems.append("the target is not beneath the scratch root")
    if _beneath(target, repo_root):
        problems.append("the target is inside the repository")
    if is_reparse_point:
        problems.append("the target is a link, so removing it could reach elsewhere")
    if not target.name.startswith(SCRATCH_PREFIX):
        problems.append(f"the target is not named {SCRATCH_PREFIX}...")
    return tuple(problems)


def _beneath(target: Path, root: Path) -> bool:
    """Whether one path is inside another.

    Args:
        target: The path to test.
        root: The directory it might be inside.

    Returns:
        Whether it is, strictly.

    Compared with :meth:`~pathlib.PurePath.relative_to` rather than by string
    prefix, so that ``/tmp/globin-cleanroom-x`` is not treated as being inside
    ``/tmp/globin``.
    """
    try:
        relative = target.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return relative != Path()


@dataclass(frozen=True, slots=True)
class CleanRoom:
    """A throwaway environment built from a lock.

    Args:
        root: Where the environment goes. Already created by the caller, and
            already checked by :func:`cleanroom_problems`.
        runner: How to start a child.
        timeout_seconds: How long each child may run.
    """

    root: Path
    runner: ProcessRunner
    timeout_seconds: float = DEFAULT_TIMEOUT

    def create(self, interpreter: Path) -> CleanRoomOutcome:
        """Build a virtual environment inside the room.

        Args:
            interpreter: Which Python to build it with.

        Returns:
            What happened.
        """
        argv = [str(interpreter), "-m", "venv", str(self.root / "venv")]
        return self._run(argv, fault=CleanRoomFault.ENVIRONMENT_REFUSED)

    def install(self, lock: Path, wheelhouse: Path | None) -> CleanRoomOutcome:
        """Install from a lock, offline when a wheelhouse is given.

        Args:
            lock: The PEP 751 lock to install from.
            wheelhouse: Local artefacts, or ``None`` to permit the index.

        Returns:
            What happened.

        ``--no-index`` and ``--find-links`` are passed together when a wheelhouse
        is given, so that an artefact missing from it fails rather than being
        fetched. That is the offline guarantee at the process level, matching the
        one :mod:`tools.quality.materialize.plan` makes structurally.
        """
        argv = [
            str(self.root / "venv" / "Scripts" / "python.exe"),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--requirement",
            str(lock),
        ]
        if wheelhouse is not None:
            argv += ["--no-index", "--find-links", str(wheelhouse)]
        return self._run(argv, fault=CleanRoomFault.INSTALL_FAILED)

    def probe(self) -> tuple[CleanRoomOutcome, str]:
        """Ask the built environment what it holds.

        Returns:
            What happened, and the child's output for the caller to compare
            against the lock.
        """
        argv = [
            str(self.root / "venv" / "Scripts" / "python.exe"),
            "-m",
            "pip",
            "list",
            "--format",
            "freeze",
            "--disable-pip-version-check",
        ]
        try:
            status, output = self.runner(argv, cwd=self.root, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            return (
                CleanRoomOutcome(
                    ok=False,
                    fault=CleanRoomFault.INSTALL_TIMED_OUT,
                    detail="the probe did not finish inside its bound",
                ),
                "",
            )
        if status != 0:
            return (
                CleanRoomOutcome(
                    ok=False,
                    fault=CleanRoomFault.PROBE_DISAGREED,
                    detail=f"the probe exited {status}",
                ),
                "",
            )
        return (CleanRoomOutcome(ok=True), output)

    def _run(self, argv: Sequence[str], *, fault: CleanRoomFault) -> CleanRoomOutcome:
        """Start one child and classify what it did.

        Args:
            argv: The command, as a list.
            fault: Which fault a non-zero status means here.

        Returns:
            What happened.

        A ``KeyboardInterrupt`` is caught and reported as
        :attr:`CleanRoomFault.INSTALL_INTERRUPTED` rather than propagating,
        because a half-built environment is a state an operator should be told
        about explicitly -- the alternative leaves a partial install and a
        traceback, and no statement that the two are connected.
        """
        try:
            status, output = self.runner(argv, cwd=self.root, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            return CleanRoomOutcome(
                ok=False,
                fault=CleanRoomFault.INSTALL_TIMED_OUT,
                detail=f"no answer inside {self.timeout_seconds:.0f}s",
            )
        except KeyboardInterrupt:
            return CleanRoomOutcome(
                ok=False,
                fault=CleanRoomFault.INSTALL_INTERRUPTED,
                detail="stopped part-way, so the environment is half-built",
            )
        if status != 0:
            return CleanRoomOutcome(ok=False, fault=fault, detail=f"the child exited {status}")
        del output
        return CleanRoomOutcome(ok=True)


def installed_from(output: str) -> Mapping[str, str]:
    """Read a ``pip list --format freeze`` transcript.

    Args:
        output: What the child printed.

    Returns:
        Distribution name to version, lowercased.

    Lines that are not ``name==version`` are skipped rather than raised on: pip
    emits editable and direct-reference lines in other shapes, and a probe that
    crashed on one would report a clean-room failure that is really a parsing
    failure.
    """
    found: dict[str, str] = {}
    for line in output.splitlines():
        name, separator, version = line.strip().partition("==")
        if separator and name and version:
            found[name.strip().lower().replace("_", "-")] = version.strip()
    return found


def spawn(argv: Sequence[str], *, cwd: Path, timeout: float) -> tuple[int, str]:
    """Start a real child process.

    Args:
        argv: The command, as a list.
        cwd: Where to run it.
        timeout: How long it may take.

    Returns:
        Its status and combined output.

    The default :class:`ProcessRunner`, and the only genuinely uncoverable body
    in this package -- which is why it is this short and why every decision above
    it is behind the seam.
    """
    completed = subprocess.run(  # noqa: S603 -- a list, never a shell string
        list(argv),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    return (completed.returncode, f"{completed.stdout}{completed.stderr}")
