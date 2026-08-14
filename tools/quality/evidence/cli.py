"""The command line for the evidence gate.

Hand-written, like ``tools/quality/__main__.py`` and
``tools/quality/execution/cli.py``. There are two subcommands and no options, so
:mod:`argparse` would be more machinery than the problem has — and this
repository has no argparse anywhere, which is a consistency worth keeping until
something actually needs it.

Every unrecognised word is refused rather than ignored. A typo that silently ran
the default command would produce evidence somebody believed was verified.
"""

from collections.abc import Sequence
from typing import Final

from tools.quality.evidence.gate import (
    EXIT_USAGE,
    run_evidence,
    verify_evidence,
)

USAGE: Final[str] = """\
usage: python -m tools.quality.evidence [command]

  run       Run the suite and write the evidence. The default.
  verify    Re-read the evidence already written and check it.

Exit codes:
  0  every gate passed
  1  a gate failed: the suite, the coverage floor, or verification
  2  the command line was not understood
  3  the result could not be determined, which is never a pass
"""


class UsageError(Exception):
    """The command line was not understood."""


def parse(argv: Sequence[str]) -> str:
    """Read the subcommand.

    Args:
        argv: Arguments after the module name.

    Returns:
        ``"run"`` or ``"verify"``.

    Raises:
        UsageError: If more than one word was given, or the word is not a
            command.
    """
    if not argv:
        return "run"
    if len(argv) > 1:
        msg = f"expected one command, got {list(argv)}"
        raise UsageError(msg)
    command = argv[0]
    if command not in ("run", "verify"):
        msg = f"unknown command {command!r}; expected 'run' or 'verify'"
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
        command = parse(argv)
    except UsageError as fault:
        print(f"evidence: {fault}\n")
        print(USAGE, end="")
        return EXIT_USAGE
    return verify_evidence() if command == "verify" else run_evidence()
