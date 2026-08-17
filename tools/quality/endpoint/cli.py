"""The command line for the diagnostics endpoint gate.

Hand-written rather than ``argparse``, matching every other gate here: the surface is
one optional word, and a parser that accepted abbreviations would make ``ch`` mean
``check`` on a day somebody meant something else.

There is no networked subcommand, and unlike ``gpu`` there is not even a local probe:
everything this gate asks is answerable from two files in the repository, so there is
no second question to put behind a second word.
"""

from collections.abc import Sequence
from typing import Final

from tools.quality.endpoint.gate import EXIT_UNMEASURED, run_endpoint

CHECK: Final[str] = "check"
"""Recompute the contract against the source. The default, and the only word."""

SUBCOMMANDS: Final[frozenset[str]] = frozenset({CHECK})
"""Every word this command accepts."""

EXIT_USAGE: Final[int] = 2
"""The command line was not understood."""

USAGE: Final[str] = """usage: python -m tools.quality.endpoint [check]

Whether the diagnostics endpoint's declared contract is the one the source
implements -- recomputed rather than believed.

  check   Read docs/engineering/endpoint-contract.toml and hold every claim in it
          against src/globin: the route table, the loopback addresses, the absence
          of any address literal in the module that binds, the absence of a
          wildcard anywhere in the package, every bound and default, every route's
          switch, both content types, each attribute vocabulary, and the
          cardinality arithmetic behind all five metric budgets. The default.

Binds nothing and reaches nothing. No socket is opened, no server started and no
question asked of this host, so this is safe to run on a machine where the
surface has never been enabled. Writes .globin/endpoint/endpoint-manifest.json.

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
        UsageError: If a word is unrecognised, or a subcommand is given twice.
    """
    chosen: str | None = None
    for word in argv:
        if word in SUBCOMMANDS and chosen is None:
            chosen = word
        else:
            msg = f"unrecognised argument: {word!r}"
            raise UsageError(msg)


def main(argv: Sequence[str]) -> int:
    """Run the gate.

    Args:
        argv: The arguments after the module name.

    Returns:
        The process exit code.
    """
    try:
        parse(argv)
    except UsageError as fault:
        print(f"endpoint: {fault}")
        print(USAGE)
        return EXIT_USAGE
    try:
        return run_endpoint()
    except OSError as fault:
        print(f"endpoint: the gate could not write its artefacts: {fault}")
        return EXIT_UNMEASURED
