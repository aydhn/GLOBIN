"""The command line for the drift gate.

Hand-written rather than :mod:`argparse`, for the reason
``tools/quality/__main__.py`` gives about its own: the whole grammar is three
words and no options, and a parser generated for that would be more code than the
thing it parses, with error messages nobody chose.

**One of the three words writes to the environment**, and the difference between
them is the difference between a report and a change. The parser refuses anything
it does not recognise rather than ignoring it, because a typo that silently
degrades ``repair`` into ``check`` is a repair somebody believes happened.
"""

from collections.abc import Sequence
from typing import Final

from tools.quality.drift.gate import (
    ACCEPT,
    CHECK,
    EXIT_UNMEASURED,
    REPAIR,
    run_drift,
)

SUBCOMMANDS: Final[frozenset[str]] = frozenset({CHECK, ACCEPT, REPAIR})
"""Every word this command accepts."""

EXIT_USAGE: Final[int] = 2
"""The command line was not understood."""

USAGE: Final[str] = """\
usage: python -m tools.quality.drift [check|accept|repair]

  check    Compare this host against the accepted baseline. The default.
           Reads the host and writes only its own evidence.
  accept   Record this host as the baseline to be held to from now on.
           Run it when you have decided a change was intended.
  repair   Perform the repairs the policy marks in-place, then measure again.
           Writes only inside the project environment.

Exit codes:
  0  every check passed
  1  a check failed
  2  the command line was not understood
  3  a check could not be measured, which is never a pass

With no accepted baseline there is nothing to compare against, and the run
reports 3 rather than 0. That is not a clean tree; it is an unmeasured one.

What may be repaired, and what may not, is declared in
docs/engineering/drift-policy.toml and explained in
docs/engineering/ENVIRONMENT_DRIFT.md.
"""


class UsageError(Exception):
    """The command line was not understood."""


def parse(argv: Sequence[str]) -> str:
    """Read the subcommand from a command line.

    Args:
        argv: The arguments after the module name.

    Returns:
        The chosen subcommand, defaulting to :data:`~tools.quality.drift.gate.CHECK`.

    Raises:
        UsageError: If a word is not a subcommand, or two are given. Two
            subcommands have no defensible reading — ``accept repair`` could mean
            either order and they do different things — so it is refused rather
            than resolved by position.
    """
    chosen: str | None = None
    for word in argv:
        if word in SUBCOMMANDS and chosen is None:
            chosen = word
        elif word in SUBCOMMANDS:
            msg = f"only one subcommand at a time, and {chosen!r} was already given"
            raise UsageError(msg)
        else:
            msg = f"unrecognised argument: {word!r}"
            raise UsageError(msg)
    return chosen or CHECK


def main(argv: Sequence[str]) -> int:
    """Run the gate from a command line.

    Args:
        argv: The arguments after the module name.

    Returns:
        The gate's exit code, or :data:`EXIT_USAGE` when the command line was not
        understood.
    """
    try:
        mode = parse(argv)
    except UsageError as fault:
        print(f"drift: {fault}")
        print(USAGE)
        return EXIT_USAGE
    try:
        return run_drift(mode=mode)
    except OSError as fault:
        print(f"drift: the gate could not write its artefacts: {fault}")
        return EXIT_UNMEASURED
