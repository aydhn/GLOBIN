"""The command line for the wheel-survey gate.

Hand-written rather than ``argparse``, matching every other gate here: the surface
is one optional word, and a parser that accepts abbreviations and prefixes would
make ``pro`` mean ``probe`` on a day somebody meant something else.
"""

from collections.abc import Sequence
from typing import Final

from tools.quality.wheels.gate import EXIT_UNMEASURED, run_wheels

CHECK: Final[str] = "check"
"""Recompute the survey offline. The default."""

PROBE: Final[str] = "probe"
"""Recompute it, then compare the record against the index."""

SUBCOMMANDS: Final[frozenset[str]] = frozenset({CHECK, PROBE})
"""Every word this command accepts."""

EXIT_USAGE: Final[int] = 2
"""The command line was not understood."""

USAGE: Final[str] = """usage: python -m tools.quality.wheels [check|probe]

Whether every library the roadmap schedules has a wheel for the pinned
interpreter, on the pinned platform.

  check   Read docs/engineering/wheel-survey.toml, compare its target against
          the runtime contract, and recompute every recorded verdict from the
          filenames recorded beside it. Reaches nothing. The default.

  probe   Everything check does, and then asks the index whether the record is
          still true. Reaches the network, which is why it is not in `full`.

Writes .globin/wheels/wheel-manifest.json either way.

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
        Whether the index should be consulted.

    Raises:
        UsageError: If a word is unrecognised, or a subcommand is given twice.
    """
    chosen: str | None = None
    for word in argv:
        if word in SUBCOMMANDS and chosen is None:
            chosen = word
        else:
            msg = f"unrecognised argument: {word!r}"
            raise UsageError(msg)
    return chosen == PROBE


def main(argv: Sequence[str]) -> int:
    """Run the gate.

    Args:
        argv: The arguments after the module name.

    Returns:
        The process exit code.
    """
    try:
        probe = parse(argv)
    except UsageError as fault:
        print(f"wheels: {fault}")
        print(USAGE)
        return EXIT_USAGE
    try:
        return run_wheels(probe=probe)
    except OSError as fault:
        print(f"wheels: the gate could not write its artefacts: {fault}")
        return EXIT_UNMEASURED
