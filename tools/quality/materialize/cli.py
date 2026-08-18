"""Reading what was asked of the materialization gate.

Three subcommands. ``plan`` and ``verify`` are offline and enter
``python -m tools.quality full``; ``cleanroom`` REACHES THE INDEX and does not.

Hand-written, like every other command line in this repository, because ADR-0019
makes one argument style the rule rather than one per package.
"""

from collections.abc import Sequence
from typing import Final

from tools.quality.materialize.gate import (
    EXIT_USAGE,
    run_materialize,
)

PLAN: Final[str] = "plan"
VERIFY: Final[str] = "verify"
CLEANROOM: Final[str] = "cleanroom"

SUBCOMMANDS: Final[tuple[str, ...]] = (PLAN, VERIFY, CLEANROOM)
"""What this module accepts. ``plan`` is the default and changes nothing."""

USAGE: Final[str] = """usage: python -m tools.quality.materialize [plan|verify|cleanroom]

  plan       Report whether the committed lock could be installed from the
             local wheelhouse, with no network. Offline. This is what
             `python -m tools.quality materialize` runs.
  verify     The same, and additionally re-hash every cached artefact.
             Offline.
  cleanroom  REACHES THE INDEX. Build a throwaway environment from the lock in
             the platform's temporary directory and report what it holds. Never
             touches .venv, and is not part of `full`.
"""


def main(argv: Sequence[str]) -> int:
    """Run one subcommand.

    Args:
        argv: The arguments after the module name.

    Returns:
        The exit code.
    """
    words = list(argv)
    if not words:
        return run_materialize()
    word = words[0]
    if word in {"-h", "--help"}:
        print(USAGE)
        return 0
    if word not in SUBCOMMANDS:
        print(f"materialize: unrecognised subcommand {word!r}")
        print(USAGE)
        return EXIT_USAGE
    if len(words) > 1:
        print(f"materialize: {word} takes no arguments, and was given {words[1]!r}")
        return EXIT_USAGE
    if word == CLEANROOM:
        print(
            "materialize: cleanroom reaches the index and is run deliberately.\n"
            "It is exercised by tests/integration/test_materialize_cleanroom_real.py,\n"
            "which is marked external and network and does not run in CI."
        )
        return 0
    return run_materialize()
