"""The command line for the supply-chain gate.

Hand-written, like ``tools/quality/evidence/cli.py`` and
``tools/quality/execution/cli.py``. There are two subcommands and one option, so
:mod:`argparse` would be more machinery than the problem has — and this
repository has no argparse anywhere, which is a consistency worth keeping until
something actually needs it.

Every unrecognised word is refused rather than ignored. A typo that silently ran
the default command would write a manifest somebody believed had been asked for.
"""

from collections.abc import Sequence
from typing import Final

from tools.quality.supply.gate import EXIT_UNMEASURED, run_supply

EXIT_USAGE: Final[int] = 2
"""Distinct from every verdict code, so that "you typed it wrong" is never
mistaken for "the repository is in trouble"."""

OFFLINE_FLAG: Final[str] = "--offline"

USAGE: Final[str] = """\
usage: python -m tools.quality.supply [command] [--offline]

  run       Run every supply-chain check and write the manifest. The default.

  --offline Make no network call at all: neither the vulnerability audit nor
            the platform probe runs, and both are recorded as unmeasured.
            An offline run therefore never exits 0.

Exit codes:
  0  every check passed
  1  a check failed
  2  the command line was not understood
  3  a check could not be measured, which is never a pass
"""


class UsageError(Exception):
    """The command line was not understood."""


def parse(argv: Sequence[str]) -> bool:
    """Read the command line.

    Args:
        argv: The arguments after the module name.

    Returns:
        Whether the gate may reach the network.

    Raises:
        UsageError: If a word is not recognised, or a command is repeated.

    ``run`` is accepted as well as omitted, so that the explicit spelling works
    for anybody who prefers it, and so that a future second subcommand does not
    change what today's callers must type.
    """
    online = True
    seen_command = False
    for word in argv:
        if word == OFFLINE_FLAG:
            online = False
        elif word == "run" and not seen_command:
            seen_command = True
        else:
            msg = f"unrecognised argument: {word!r}"
            raise UsageError(msg)
    return online


def main(argv: Sequence[str]) -> int:
    """Run the gate.

    Args:
        argv: The arguments after the module name.

    Returns:
        The gate's exit code, or :data:`EXIT_USAGE` when the command line was not
        understood.
    """
    try:
        online = parse(argv)
    except UsageError as fault:
        print(f"supply: {fault}")
        print(USAGE)
        return EXIT_USAGE
    try:
        return run_supply(online=online)
    except OSError as fault:
        print(f"supply: the gate could not write its artefacts: {fault}")
        return EXIT_UNMEASURED
