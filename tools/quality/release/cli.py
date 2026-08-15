"""The command line for the release gate.

Hand-written, like every other sub-command here. There are two subcommands and no
option, so :mod:`argparse` would be more machinery than the problem has — and
this repository has no argparse anywhere, which is a consistency worth keeping
until something actually needs it.

Every unrecognised word is refused rather than ignored. A typo that silently ran
the default command would write a manifest somebody believed had been asked for —
and here that manifest is a release asset.
"""

from collections.abc import Sequence
from typing import Final

from tools.quality.release.gate import EXIT_UNMEASURED, run_release

EXIT_USAGE: Final[int] = 2
"""Distinct from every verdict code, so that "you typed it wrong" is never
mistaken for "the repository is in trouble"."""

CHECK: Final[str] = "check"
READY: Final[str] = "ready"

SUBCOMMANDS: Final[frozenset[str]] = frozenset({CHECK, READY})

USAGE: Final[str] = """\
usage: python -m tools.quality.release [check|ready]

  check   Check the release contract against the tree and write the manifest:
          the foundation matrix, the version, the tag it implies, the changelog,
          the release documents and the notes configuration. The default.

  ready   Everything `check` does, and the release preconditions as well: that
          the branch is master, the working tree is clean, and HEAD agrees with
          origin/master.

`check` is deterministic over a commit and is what continuous integration runs.
`ready` asks about the working tree rather than about the commit, so two runs of
it can legitimately disagree; it is the question to ask immediately before
cutting a release, not on every push.

Neither reaches the network. Whether the platform has immutable releases switched
on, and whether the tag ruleset exists, are asked by
`python -m tools.quality supply`, which already has the credential for it.

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
        Whether the release preconditions were asked for.

    Raises:
        UsageError: If a word is not recognised, or a subcommand is repeated.

    ``check`` is accepted as well as omitted, so that the explicit spelling works
    for anybody who prefers it, and so that adding ``ready`` did not change what
    existing callers must type.
    """
    chosen: str | None = None
    for word in argv:
        if word in SUBCOMMANDS and chosen is None:
            chosen = word
        else:
            msg = f"unrecognised argument: {word!r}"
            raise UsageError(msg)
    return chosen == READY


def main(argv: Sequence[str]) -> int:
    """Run the gate.

    Args:
        argv: The arguments after the module name.

    Returns:
        The gate's exit code, or :data:`EXIT_USAGE` when the command line was not
        understood.
    """
    try:
        preconditions = parse(argv)
    except UsageError as fault:
        print(f"release: {fault}")
        print(USAGE)
        return EXIT_USAGE
    try:
        return run_release(check_repository=preconditions)
    except OSError as fault:
        print(f"release: the gate could not write its artefacts: {fault}")
        return EXIT_UNMEASURED
