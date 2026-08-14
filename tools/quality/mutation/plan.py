"""What to mutate, how to launch a test subset, and what an exit code means.

Everything here is a pure function over configuration or over an exit code. The
filesystem and the subprocess live in :mod:`tools.quality.mutation.sandbox`, and
the split is not tidiness: the judgements below are the ones worth testing
exhaustively, and a judgement entangled with a subprocess is a judgement tested
once and hoped about.

The rule this module exists to enforce is that **an exit code is never guessed
at**. pytest has seven of them, and only two are verdicts. Reading "not zero" as
"the mutant was killed" would score a run in which pytest never collected a
single test as a perfect one.
"""

import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

#: pytest's documented exit codes. Only `TESTS_FAILED` and `OK` are verdicts;
#: everything else means the run did not measure what it was asked to.
PYTEST_OK: Final[int] = 0
PYTEST_TESTS_FAILED: Final[int] = 1
PYTEST_NO_TESTS_COLLECTED: Final[int] = 5

#: What the harness copies into the throwaway tree. Declared rather than
#: discovered, so it needs neither git nor a helper from the test suite.
DEFAULT_SANDBOX: Final[tuple[str, ...]] = ("pyproject.toml", "src", "tests", "tools")

DEFAULT_TIMEOUT_FACTOR: Final[int] = 8
DEFAULT_TIMEOUT_FLOOR_SECONDS: Final[int] = 30
DEFAULT_BASELINE: Final[str] = "docs/engineering/mutation-baseline.toml"

#: Environment names the child inherits. An allowlist rather than a denylist,
#: because the failure mode of a missing name is loud — the unmutated control run
#: fails and the whole run stops — while the failure mode of an unnoticed
#: inherited name is a silently wrong verdict.
INHERITED_ENVIRONMENT: Final[tuple[str, ...]] = (
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "PATH",
    "PATHEXT",
    "COMSPEC",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "OS",
    "HOME",
    "LANG",
)

#: What the child is told regardless of what the parent had.
#:
#: `PYTHONDONTWRITEBYTECODE` is a correctness measure, not a speed one. CPython
#: validates a cached `.pyc` against the source's modification time **in whole
#: seconds** and its size in bytes, and most mutations here preserve length
#: exactly — `>=` to `>`, `and` to `or`, `True` to `False` in a keyword. Two such
#: mutants written inside the same second could therefore run the first one's
#: bytecode, and the wrong verdict would look like nothing at all.
#: `PYTHONHASHSEED` is pinned so that a verdict cannot change between two runs of
#: the same mutant. That is a knowing trade: an unpinned seed might expose a
#: mutation that introduces a dependency on hash ordering, but the suite already
#: asserts order-independence directly in `tests/property/`, and a gate whose
#: answer moves between runs is worth less than the check it would duplicate.
#:
#: `PYTHONNOUSERSITE` is deliberately **absent**. Setting it would make the child
#: hermetic and was in the first draft; it also made the child unable to find
#: pytest, because this project's toolchain is installed at user level and not in
#: a virtual environment (MEMORY.md). The unmutated control run caught it
#: immediately, which is the whole reason that control exists.
FORCED_ENVIRONMENT: Final[Mapping[str, str]] = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
}


class MutationConfigurationError(Exception):
    """A mutation configuration or baseline that cannot be read.

    Deliberately **not** :class:`globin.errors.ConfigurationError`, and the reason
    is worth stating: ``tools`` is the machinery that reports whether ``globin``
    is healthy, and a verifier importing the package it verifies cannot report on
    one too broken to import. ``tools/quality/runner.py`` avoids the same
    coupling by asking :func:`importlib.util.find_spec` whether a module exists
    rather than importing it.

    It is also what lets every refusal below name one fault. A malformed table
    and a missing key are the same situation — the file is wrong — and splitting
    them into :exc:`TypeError` and :exc:`ValueError` would make a caller catch
    two things to handle one, which is the argument
    :mod:`globin.adapters.architecture` already makes for its own TOML readers.
    """


class Verdict(StrEnum):
    """What happened to one mutant."""

    KILLED = "killed"
    SURVIVED = "survived"
    NO_TESTS = "no-tests"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Target:
    """One module to mutate, and the tests that must notice.

    Args:
        module: Repository-relative path of the module.
        tests: Repository-relative paths of the tests to run against each mutant.

    Test *paths*, never a ``-k`` expression or a marker. A mistyped path is
    caught by :func:`validate` before anything launches; a mistyped ``-k`` or
    marker makes pytest exit 5 having collected nothing, which a careless reader
    scores as a flawless run.
    """

    module: str
    tests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Configuration:
    """Everything a run needs, read from ``pyproject.toml``."""

    targets: tuple[Target, ...]
    sandbox: tuple[str, ...]
    baseline: str
    timeout_factor: int
    timeout_floor_seconds: int


def read_configuration(document: Mapping[str, object]) -> Configuration:
    """Read the ``[tool.globin.mutation]`` table.

    Args:
        document: A parsed ``pyproject.toml``.

    Returns:
        The configuration, with defaults filled in.

    Raises:
        MutationConfigurationError: If the table is missing, declares no target,
            or a target is missing its module or its tests.
    """
    table = _table(_table(_table(document, "tool"), "globin"), "mutation")
    raw_targets = table.get("target")
    if not isinstance(raw_targets, list) or not raw_targets:
        msg = "[tool.globin.mutation] declares no [[tool.globin.mutation.target]]"
        raise MutationConfigurationError(msg)

    targets = tuple(_target(entry, position) for position, entry in enumerate(raw_targets))
    return Configuration(
        targets=targets,
        sandbox=_strings(table, "sandbox", DEFAULT_SANDBOX),
        baseline=_text(table, "baseline", DEFAULT_BASELINE),
        timeout_factor=_integer(table, "timeout_factor", DEFAULT_TIMEOUT_FACTOR),
        timeout_floor_seconds=_integer(
            table, "timeout_floor_seconds", DEFAULT_TIMEOUT_FLOOR_SECONDS
        ),
    )


def _table(document: Mapping[str, object], key: str) -> Mapping[str, object]:
    """Return a nested table, or refuse naming the one that is missing."""
    value = document.get(key)
    if not isinstance(value, Mapping):
        msg = f"expected a table called {key!r} in the mutation configuration"
        raise MutationConfigurationError(msg)
    return value


def _strings(table: Mapping[str, object], key: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    """Return a list of strings from a table, or the fallback when absent."""
    value = table.get(key)
    if value is None:
        return fallback
    if not isinstance(value, list):
        msg = f"{key} must be a list of strings"
        raise MutationConfigurationError(msg)
    return tuple(str(item) for item in value)


def _text(table: Mapping[str, object], key: str, fallback: str) -> str:
    """Return a string from a table, or the fallback when absent."""
    value = table.get(key)
    if value is None:
        return fallback
    if not isinstance(value, str):
        msg = f"{key} must be a string"
        raise MutationConfigurationError(msg)
    return value


def _integer(table: Mapping[str, object], key: str, fallback: int) -> int:
    """Return a whole number from a table, or the fallback when absent."""
    value = table.get(key)
    if value is None:
        return fallback
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"{key} must be a whole number"
        raise MutationConfigurationError(msg)
    return value


def _target(entry: object, position: int) -> Target:
    """Read one target table."""
    if not isinstance(entry, Mapping):
        msg = f"target {position} is not a table"
        raise MutationConfigurationError(msg)
    module = entry.get("module")
    if not isinstance(module, str):
        msg = f"target {position} declares no module"
        raise MutationConfigurationError(msg)
    tests = entry.get("tests")
    if not isinstance(tests, list) or not tests:
        msg = f"target {module!r} declares no tests; a target nothing runs measures nothing"
        raise MutationConfigurationError(msg)
    return Target(module=module, tests=tuple(str(item) for item in tests))


def validate(configuration: Configuration, repo_root: Path) -> tuple[str, ...]:
    """Return every declared path that does not exist.

    Args:
        configuration: What was read from ``pyproject.toml``.
        repo_root: Where the paths are relative to.

    Returns:
        A message per missing path, empty when everything resolves. Checked in
        the parent, before a sandbox is built, because this is the one class of
        mistake that would otherwise reach pytest and come back as exit 5.
    """
    missing: list[str] = []
    for target in configuration.targets:
        if not (repo_root / target.module).is_file():
            missing.append(f"target module does not exist: {target.module}")
        missing.extend(
            f"test path does not exist: {path} (for {target.module})"
            for path in target.tests
            if not (repo_root / path).exists()
        )
    return tuple(missing)


def classify(exit_code: int | None, *, timed_out: bool) -> Verdict:
    """Say what a child process's outcome means.

    Args:
        exit_code: What pytest returned, or ``None`` when it was killed.
        timed_out: Whether the harness stopped it.

    Returns:
        The verdict. Only ``0`` and ``1`` are verdicts about the mutant; every
        other code means the run did not measure it, and says so rather than
        guessing.
    """
    if timed_out:
        return Verdict.TIMEOUT
    if exit_code == PYTEST_OK:
        return Verdict.SURVIVED
    if exit_code == PYTEST_TESTS_FAILED:
        return Verdict.KILLED
    if exit_code == PYTEST_NO_TESTS_COLLECTED:
        return Verdict.NO_TESTS
    return Verdict.ERROR


def child_argv(tests: Sequence[str]) -> tuple[str, ...]:
    """The command line for one subset run, after the interpreter.

    Args:
        tests: Sandbox-relative test paths.

    Returns:
        The arguments.

    ``--hypothesis-profile=ci`` is not optional. ``tests/conftest.py`` loads the
    ``dev`` profile, which keeps an example database; a database surviving inside
    a sandbox reused across mutants would let one mutant's verdict depend on the
    failures of the mutant before it. The ``ci`` profile sets ``database=None``
    and ``derandomize=True``.
    """
    return (
        "-m",
        "pytest",
        "-x",
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
        "--hypothesis-profile=ci",
        *tests,
    )


def child_environment(parent: Mapping[str, str]) -> dict[str, str]:
    """Build the child's environment from an allowlist.

    Args:
        parent: The environment the harness itself is running under.

    Returns:
        Only the names in :data:`INHERITED_ENVIRONMENT` that were present, plus
        :data:`FORCED_ENVIRONMENT`.

    What is dropped matters more than what is kept. ``COVERAGE_PROCESS_START``
    would make the child start measuring coverage; ``PYTHONPATH`` could point at
    the real source tree instead of the sandbox; ``PYTEST_ADDOPTS`` would inject
    flags this design never chose.
    """
    child = {name: parent[name] for name in INHERITED_ENVIRONMENT if name in parent}
    child.update(FORCED_ENVIRONMENT)
    return child


def timeout_seconds(control_seconds: float, configuration: Configuration) -> float:
    """How long one mutant may run before the harness stops it.

    Args:
        control_seconds: How long the unmutated subset took **on this machine**.
        configuration: The factor and the floor.

    Returns:
        The budget, in seconds.

    Derived from a measurement rather than fixed, so that a slow machine gets a
    proportionally longer budget and the verdict does not become a report about
    the hardware. A timeout that is not declared in the baseline stops the run
    rather than scoring, so this number decides how long to wait, never who wins.
    """
    return max(
        float(configuration.timeout_floor_seconds),
        math.ceil(control_seconds * configuration.timeout_factor),
    )


def interpreter() -> str:
    """The interpreter to launch children with: this one."""
    return sys.executable
