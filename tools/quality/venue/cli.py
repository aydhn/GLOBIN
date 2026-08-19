"""The two words this gate answers to.

Hand-written, as every command line in this repository is: ADR-0019 refused
``argparse`` and the consistency is worth keeping.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

CHECK: Final[str] = "check"
"""Read the committed registry and recompute it. Reaches nothing. The default."""

REFRESH: Final[str] = "refresh"
"""Everything check does, and then ask the venue. Reaches the network."""

SUBCOMMANDS: Final[tuple[str, ...]] = (CHECK, REFRESH)
"""Every word, and no third."""

USAGE: Final[str] = """usage: python -m tools.quality.venue [check|refresh]

  check    Read docs/engineering/binance-api-reality.toml, recompute every claim
           it makes, and write the manifest. Reaches nothing. The default.
  refresh  Everything check does, and then asks the official machine-readable
           sources whether the record is still true. Reaches the network, which
           is why it is a separate word and why neither is in `full`.

Writes .globin/api_reality/api-reality-manifest.json either way.

Exit codes:
  0  the registry recomputes, and nothing is wrong.
  1  something is wrong. Every finding is printed.
  2  the command line was not understood.
  3  there is no readable registry, so nothing was established.
"""


class UsageError(Exception):
    """The command line was not understood."""


def parse(argv: Sequence[str]) -> bool:
    """Read the command line.

    Args:
        argv: The arguments after the module name.

    Returns:
        Whether the venue should be asked as well as the document.

    Raises:
        UsageError: If a word is unrecognised or a second one follows.

    The offline word is the default and the networked word is opt-in, which is the
    shape every networked gate in this repository uses.
    """
    words = list(argv)
    if not words:
        return False
    head = words.pop(0)
    if head not in SUBCOMMANDS:
        msg = f"unrecognised argument: {head!r}"
        raise UsageError(msg)
    if words:
        msg = f"unexpected argument: {words[0]!r}"
        raise UsageError(msg)
    return head == REFRESH


def main(argv: Sequence[str]) -> int:
    """Run one invocation and report its exit code.

    Args:
        argv: The arguments after the module name.

    Returns:
        The gate's code, or ``2`` when the command line was not understood.

    Here rather than in ``__main__.py`` so that the wiring is one line and this is
    reachable from a test: a module body guarded by ``if __name__`` can only be
    exercised by starting a process.
    """
    from tools.quality.venue.gate import describe, run_api_reality

    try:
        refresh = parse(argv)
    except UsageError as fault:
        print(str(fault), file=sys.stderr)
        print(file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    outcome = run_api_reality(refresh=refresh)
    print(describe(outcome), end="")
    return outcome.code
