"""The command line for the aggregate gate.

Hand-written, like every other entry point here. There is one subcommand and no
options, because the two things the gate needs from CI arrive as environment
variables rather than arguments — a JSON document threaded through a ``run:``
line survives neither shell intact.

Every unrecognised word is refused rather than ignored, for the reason
``tools/quality/evidence/cli.py`` gives: a typo that silently ran the default
would produce a verdict somebody believed was about what they typed.
"""

from collections.abc import Sequence
from typing import Final

from tools.quality.workflow.gate import EXIT_USAGE, run_aggregate

USAGE: Final[str] = """\
usage: python -m tools.quality.workflow [command]

  aggregate    Reduce this run's jobs and its published evidence to one verdict.
               The default.

Reads, when they are set:
  GLOBIN_WORKFLOW_NEEDS             toJSON(needs), the result of every job
  GLOBIN_WORKFLOW_ARTIFACT_DIGEST   the SHA-256 GitHub gave the uploaded artifact
  GITHUB_STEP_SUMMARY               where to append the human-readable summary

With no needs context it aggregates the evidence the local run wrote, which is
the developer's case and uses the same evaluator CI does.

Exit codes:
  0  every required job passed and the published evidence agreed
  1  something required failed
  2  the command line was not understood
  3  the result could not be determined, which is never a pass
"""

COMMANDS: Final[tuple[str, ...]] = ("aggregate",)
"""The words this entry point accepts."""


class UsageError(Exception):
    """The command line was not understood."""


def parse(argv: Sequence[str]) -> str:
    """Read the subcommand.

    Args:
        argv: Arguments after the module name.

    Returns:
        The command, defaulting to ``"aggregate"``.

    Raises:
        UsageError: If more than one word was given, or the word is not a
            command.
    """
    if not argv:
        return COMMANDS[0]
    if len(argv) > 1:
        msg = f"expected one command, got {list(argv)}"
        raise UsageError(msg)
    command = argv[0]
    if command not in COMMANDS:
        msg = f"unknown command {command!r}; expected {' or '.join(repr(c) for c in COMMANDS)}"
        raise UsageError(msg)
    return command


def main(argv: Sequence[str]) -> int:
    """Run the gate.

    Args:
        argv: Arguments after the module name.

    Returns:
        The exit code.
    """
    if any(argument in ("-h", "--help") for argument in argv):
        print(USAGE, end="")
        return 0
    try:
        parse(argv)
    except UsageError as fault:
        print(f"workflow: {fault}\n")
        print(USAGE, end="")
        return EXIT_USAGE
    return run_aggregate()
