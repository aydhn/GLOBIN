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

JOURNAL: Final[str] = "journal"
"""Read back what previous runs recorded. Reaches nothing, and writes nothing.

Added in Phase 034 with the change journal itself. Separate from ``check``
because it answers a question about *history* rather than about the tree as it
stands, and folding it in would make every gate run print a log.
"""

SUBCOMMANDS: Final[tuple[str, ...]] = (CHECK, REFRESH, JOURNAL)
"""Every word, and no fourth."""

USAGE: Final[str] = """usage: python -m tools.quality.venue [check|refresh|journal]

  check    Read docs/engineering/binance-api-reality.toml, recompute every claim
           it makes, age every source against docs/engineering/ingestion-policy.toml,
           and write the manifest. Reaches nothing. The default.
  refresh  Everything check does, and then asks the official machine-readable
           sources whether the record is still true. Reaches the network, which
           is why it is a separate word and why neither is in `full`. A source
           whose digest moved must be acknowledged in
           docs/engineering/venue-acknowledgements.toml before this passes.
  journal  Print what previous refreshes recorded, oldest first. Reaches nothing
           and writes nothing. A run that found nothing appends nothing, so every
           line is a moment something moved.

Writes .globin/venue/api-reality-manifest.json for check and refresh.
A refresh that found something also appends .globin/venue/venue-journal.jsonl.

A source past its declared re-check interval is reported as a NOTE and does not
fail this gate. It does refuse a REST endpoint resolution inside GLOBIN, which is
where failing closed belongs -- a gate that reddened on a calendar, on a machine
that may have no network to clear it with, is one people re-run instead of read.

Exit codes:
  0  the registry recomputes, and nothing is wrong.
  1  something is wrong. Every finding is printed.
  2  the command line was not understood.
  3  there is no readable registry, so nothing was established.
"""


class UsageError(Exception):
    """The command line was not understood."""


def parse(argv: Sequence[str]) -> str:
    """Read the command line.

    Args:
        argv: The arguments after the module name.

    Returns:
        The subcommand, defaulting to the offline one.

    Raises:
        UsageError: If a word is unrecognised or a second one follows.

    The offline word is the default and the networked word is opt-in, which is the
    shape every networked gate in this repository uses.
    """
    words = list(argv)
    if not words:
        return CHECK
    head = words.pop(0)
    if head not in SUBCOMMANDS:
        msg = f"unrecognised argument: {head!r}"
        raise UsageError(msg)
    if words:
        msg = f"unexpected argument: {words[0]!r}"
        raise UsageError(msg)
    return head


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
    from tools.quality.venue.gate import describe, describe_journal, run_api_reality

    try:
        subcommand = parse(argv)
    except UsageError as fault:
        print(str(fault), file=sys.stderr)
        print(file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    if subcommand == JOURNAL:
        print(describe_journal(), end="")
        return 0
    outcome = run_api_reality(refresh=subcommand == REFRESH)
    print(describe(outcome), end="")
    return outcome.code
