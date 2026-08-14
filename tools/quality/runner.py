"""Execution of quality steps, with failures that stay failures.

Three properties matter here, and each is a way a quality gate can look like it
is working while proving nothing:

* **A missing tool is a failure, not a pass.** If `ruff` is not installed, the
  honest outcome is "lint did not run", never a silent success. Modules are
  checked before anything is launched so the report names every missing tool at
  once instead of one per re-run.
* **Exit codes are propagated, not summarised.** The caller receives the child's
  own code. A wrapper that returns 1 for everything throws away the difference
  between "tests failed" and "the interpreter was not found".
* **Nothing is installed automatically.** Dependency bootstrap belongs to Phases
  017-032. A tool that quietly `pip install`s what it needs makes the
  environment un-reproducible in exactly the way that band exists to fix.
"""

import subprocess
import sys
from collections.abc import Iterable
from importlib.util import find_spec
from pathlib import Path
from typing import Final

from tools.quality.commands import Command, Step

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: Returned when a required tool is absent. 127 is the conventional
#: "command not found", and it is deliberately distinct from any exit code a
#: check itself produces, so "the gate failed" and "the gate never ran" are
#: never confused in a CI log.
EXIT_TOOL_MISSING: Final[int] = 127

#: Returned when the command name is not one this tool knows.
EXIT_USAGE: Final[int] = 2


def missing_modules(steps: Iterable[Step]) -> tuple[str, ...]:
    """Return the modules required by ``steps`` that are not importable."""
    required = {module for step in steps for module in step.modules}
    absent: set[str] = set()
    for module in required:
        try:
            if find_spec(module) is None:
                absent.add(module)
        except (ImportError, ValueError):
            absent.add(module)
    return tuple(sorted(absent))


def execute(step: Step) -> int:
    """Run one step and return its exit code.

    The executable is ``sys.executable`` and the arguments are a list, so no
    string is ever handed to a shell. ``shell=True`` would make every argument
    below a potential injection point for no benefit whatsoever.
    """
    argv = [sys.executable, *step.argv]
    # S603 fires on every `subprocess` call and asks for a human to confirm the
    # input is trusted. It is: `argv[0]` is this interpreter, and the remaining
    # arguments come from `COMMANDS`, a frozen module-level table of string
    # literals. Nothing here is derived from user input, the environment, or a
    # file. `shell` is left at its default of False, so no string is parsed by a
    # shell at any point.
    completed = subprocess.run(argv, cwd=REPO_ROOT, check=False)  # noqa: S603
    return completed.returncode


def run(command: Command, *, echo: bool = True) -> int:
    """Run every step of ``command``, stopping at the first failure.

    Returns:
        ``0`` if all steps succeeded, ``EXIT_TOOL_MISSING`` if a required tool is
        absent, otherwise the exit code of the first step that failed.
    """
    absent = missing_modules(command.steps)
    if absent:
        tools = ", ".join(absent)
        print(f"cannot run '{command.name}': missing quality tool(s): {tools}", file=sys.stderr)
        print(
            "Install the development toolchain, then re-run. GLOBIN does not "
            "install dependencies for you; see CONTRIBUTING.md.",
            file=sys.stderr,
        )
        return EXIT_TOOL_MISSING

    for step in command.steps:
        if echo:
            print(f"\n=== {command.name}: {step.name} ===", flush=True)
        code = execute(step)
        if code != 0:
            print(f"FAILED: {step.name} (exit {code})", file=sys.stderr)
            return code

    if echo:
        print(f"\n{command.name}: all steps passed", flush=True)
    return 0
