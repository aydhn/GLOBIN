"""The command line for the scientific-stack gate.

Hand-written rather than ``argparse``, matching every other gate here: the surface
is one optional word, and a parser that accepts abbreviations would make ``c``
mean ``check`` on a day somebody meant something else.

**There is no subcommand that reaches the network, and that is the point.** The
sibling gates split ``check`` from ``probe`` because one of them consults an
index. This one never does: what it asks is entirely answerable from the files and
the libraries already on this machine.
"""

from collections.abc import Sequence
from typing import Final

from tools.quality.stack.gate import EXIT_UNMEASURED, run_stack

CHECK: Final[str] = "check"
"""Recompute the contract against this environment. The default, and the only one."""

EXIT_USAGE: Final[int] = 2
"""The command line was not understood."""

USAGE: Final[str] = """usage: python -m tools.quality.stack [check]

Whether the installed numerical and dataframe stack satisfies the behaviour
GLOBIN's written assumptions depend on.

  check   Read docs/engineering/stack-contract.toml, compare its target against
          the runtime contract, compare every declared version against
          pyproject.toml, pylock.toml and what is installed, check each
          artefact's own record of the wheel it came from, and run every declared
          behaviour probe. Reaches nothing. The default, and the only subcommand.

Writes .globin/stack/stack-manifest.json.

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
        UsageError: If a word is unrecognised, or ``check`` is given twice.

    Returns nothing, because there is nothing to choose. It exists so that an
    unrecognised word is refused rather than ignored — a gate that silently
    accepted ``python -m tools.quality.stack probe`` would let a caller believe it
    had asked for something.
    """
    seen = False
    for word in argv:
        if word == CHECK and not seen:
            seen = True
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
        print(f"stack: {fault}")
        print(USAGE)
        return EXIT_USAGE
    try:
        return run_stack()
    except OSError as fault:
        print(f"stack: the manifest could not be written: {fault}")
        return EXIT_UNMEASURED
