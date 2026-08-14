"""The quality command table: the one place a check is defined.

Every gate GLOBIN runs — locally, in a pre-commit hook, and in CI — is a name in
this table. That is the whole point of the module. When the developer's command
and the CI command are written out separately they drift, and the drift is
discovered at the worst possible moment: CI fails on something that passes on
the machine that produced it.

Steps carry the module they need so the runner can say *which* tool is missing
rather than surfacing a bare ``No module named ...`` from a subprocess.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class Step:
    """One tool invocation.

    Args:
        name: Human-facing label, shown as the step executes.
        module: The importable module this step runs, checked before launching
            anything so a missing tool is reported once and by name.
        argv: Arguments after the interpreter. The executable is always the
            running interpreter, so a step cannot accidentally use a different
            Python from the one invoking it.
    """

    name: str
    module: str
    argv: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Command:
    """A named sequence of steps, run in order and stopping at the first failure.

    Args:
        name: The name typed on the command line.
        summary: One line, shown by ``--help``.
        steps: Executed in order. Order is deliberate: cheap checks come first
            so an obvious mistake fails in a second rather than a minute.
    """

    name: str
    summary: str
    steps: tuple[Step, ...]


_LINT = Step("lint", "ruff", ("-m", "ruff", "check", "."))
_FORMAT = Step("format", "ruff", ("-m", "ruff", "format", "--check", "."))
_TYPECHECK = Step("typecheck", "mypy", ("-m", "mypy", "src/globin", "tests", "tools"))
_SMOKE = Step("smoke", "pytest", ("-m", "pytest", "-q", "-m", "smoke"))
_UNIT = Step("unit", "pytest", ("-m", "pytest", "-q", "-m", "unit"))
_ARCHITECTURE = Step(
    "architecture",
    "pytest",
    ("-m", "pytest", "-q", "-m", "contract or architecture"),
)
_COVERAGE = Step(
    "coverage",
    "pytest",
    (
        "-m",
        "pytest",
        "-q",
        "--cov=globin",
        "--cov=tools",
        "--cov-branch",
        "--cov-report=term-missing",
    ),
)

# Writing commands. Kept separate from every verification command above so that
# no gate can modify the tree as a side effect of being run. `ruff check --fix`
# applies safe fixes only; `--unsafe-fixes` is never passed by this tool,
# because a fix that changes behaviour is a change someone should be making
# consciously.
_FIX = Step("fix", "ruff", ("-m", "ruff", "check", ".", "--fix"))
_REFORMAT = Step("reformat", "ruff", ("-m", "ruff", "format", "."))


COMMANDS: Final[tuple[Command, ...]] = (
    Command(
        "fast",
        "Smoke tests, lint and format check. Seconds, not minutes.",
        (_SMOKE, _LINT, _FORMAT),
    ),
    Command(
        "full",
        "Every mandatory gate, in the order the cheapest fails first.",
        (_LINT, _FORMAT, _TYPECHECK, _COVERAGE),
    ),
    Command("lint", "Ruff lint check. Reports, never modifies.", (_LINT,)),
    Command("format", "Ruff format check. Reports, never modifies.", (_FORMAT,)),
    Command("typecheck", "mypy over the package, the suite and the tooling.", (_TYPECHECK,)),
    Command("smoke", "The smallest set of checks that would catch a broken tree.", (_SMOKE,)),
    Command("unit", "Unit tests only.", (_UNIT,)),
    Command("architecture", "Contract and architecture tests.", (_ARCHITECTURE,)),
    Command("coverage", "The full suite with branch coverage and its threshold.", (_COVERAGE,)),
    Command("fix", "Apply Ruff's SAFE fixes. Modifies the tree.", (_FIX,)),
    Command("reformat", "Apply Ruff formatting. Modifies the tree.", (_REFORMAT,)),
)

#: Commands that write to the working tree. Named so that documentation, the
#: pre-commit configuration and CI can all refer to one list instead of three
#: people remembering the same thing.
MUTATING_COMMANDS: Final[frozenset[str]] = frozenset({"fix", "reformat"})


def command_names() -> tuple[str, ...]:
    """Every command name, in declaration order."""
    return tuple(command.name for command in COMMANDS)


def find(name: str) -> Command | None:
    """Return the command called ``name``, or ``None`` if there is no such command."""
    for command in COMMANDS:
        if command.name == name:
            return command
    return None
