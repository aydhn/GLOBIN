"""The command line for the governance gate.

Hand-written, like every other sub-command here. There is one subcommand and no
option, so :mod:`argparse` would be more machinery than the problem has — and
this repository has no argparse anywhere, which is a consistency worth keeping
until something actually needs it.

Every unrecognised word is refused rather than ignored. A typo that silently ran
the default command would write a manifest somebody believed had been asked for.
"""

from collections.abc import Sequence
from typing import Final

from tools.quality.governance.gate import EXIT_UNMEASURED, run_governance

EXIT_USAGE: Final[int] = 2
"""Distinct from every verdict code, so that "you typed it wrong" is never
mistaken for "the repository is in trouble"."""

USAGE: Final[str] = """\
usage: python -m tools.quality.governance [run]

  run   Check the declared governance arrangement against the tree and write
        the manifest. The default.

The whole gate is offline. Whether the platform's controls are switched on is a
different question, asked by `python -m tools.quality supply`, which already has
the network and the credential for it.

Exit codes:
  0  every check passed
  1  a check failed
  2  the command line was not understood
  3  a check could not be measured, which is never a pass
"""


class UsageError(Exception):
    """The command line was not understood."""


def parse(argv: Sequence[str]) -> None:
    """Read the command line.

    Args:
        argv: The arguments after the module name.

    Raises:
        UsageError: If a word is not recognised, or ``run`` is repeated.

    ``run`` is accepted as well as omitted, so that the explicit spelling works
    for anybody who prefers it, and so that a future second subcommand does not
    change what today's callers must type.
    """
    seen = False
    for word in argv:
        if word == "run" and not seen:
            seen = True
        else:
            msg = f"unrecognised argument: {word!r}"
            raise UsageError(msg)


def main(argv: Sequence[str]) -> int:
    """Run the gate.

    Args:
        argv: The arguments after the module name.

    Returns:
        The gate's exit code, or :data:`EXIT_USAGE` when the command line was not
        understood.
    """
    try:
        parse(argv)
    except UsageError as fault:
        print(f"governance: {fault}")
        print(USAGE)
        return EXIT_USAGE
    try:
        return run_governance()
    except OSError as fault:
        print(f"governance: the gate could not write its artefacts: {fault}")
        return EXIT_UNMEASURED
