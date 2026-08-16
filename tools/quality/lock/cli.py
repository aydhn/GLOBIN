"""The command line for the lock gate.

Hand-written rather than ``argparse``, matching every other gate here. Two of the
four subcommands **reach the index and rewrite a committed file**, which is
precisely why no abbreviation is accepted: a parser that resolved prefixes would
let ``rel`` mean ``relock`` on a day somebody meant something else, and the cost of
that mistake is a network call and a lock nobody asked for.

``upgrade`` is the only subcommand in this repository that takes a value. The
values are checked against a closed set — the distributions the committed lock
actually contains — so a misspelled name is a usage error rather than a silent
wholesale relock.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from tools.quality.lock.gate import (
    CHECK,
    EXIT_UNMEASURED,
    INSTALLED,
    RELOCK,
    UPGRADE,
    lock_of,
    run_lock,
)
from tools.quality.lock.plan import LockError, normalise

SUBCOMMANDS: Final[frozenset[str]] = frozenset({CHECK, INSTALLED, RELOCK, UPGRADE})
"""Every word this command accepts in first position."""

EXIT_USAGE: Final[int] = 2
"""The command line was not understood."""

USAGE: Final[str] = """usage: python -m tools.quality.lock
           [check|installed|relock|upgrade <name>...]

Whether the committed lock says what it claims to say, and whether this
environment matches it.

  check      Read pylock.dev.toml and docs/engineering/lock-policy.toml, and
             recompute every claim the lock makes from the evidence recorded in
             it: hashes, artefact hosts, wheel tags, and the versions the three
             declaration registers carry. Reaches nothing. The default.

  installed  Everything check does, and then compares this environment against
             the lock. Reaches nothing. Reports unmeasured when it is not run
             through the project environment's own interpreter.

  relock     Re-resolve every declared root from its bounds and rewrite
             pylock.dev.toml. REACHES THE INDEX. This is the wholesale upgrade,
             and it will move anything with a newer release.

  upgrade <name>...
             Re-resolve with every other locked package held at the version it
             already carries, so the diff is the named packages and nothing else.
             REACHES THE INDEX. Each <name> must be a distribution the committed
             lock contains.

Writes .globin/lock/lock-manifest.json in every mode. A regenerated lock is
checked before it is kept: one the gate refuses is left in .globin/lock/ and the
committed file is not touched.

Exit codes:
  0  every check passed
  1  a check failed
  2  the command line was not understood
  3  a check could not be measured, which is never a pass
"""


class UsageError(Exception):
    """The command line was not understood."""


@dataclass(frozen=True, slots=True)
class Invocation:
    """What the command line asked for.

    Args:
        mode: One of :data:`SUBCOMMANDS`.
        only: For ``upgrade``, the distributions allowed to move.
    """

    mode: str
    only: tuple[str, ...]


def parse(argv: Sequence[str]) -> Invocation:
    """Read the command line.

    Args:
        argv: The arguments after the module name.

    Returns:
        What was asked for.

    Raises:
        UsageError: If the first word is not a subcommand, if a subcommand other
            than ``upgrade`` is given arguments, or if ``upgrade`` is given none.

    ``upgrade`` with no name is refused rather than treated as ``relock``. The two
    do different things — one moves a named package, the other moves everything —
    and quietly promoting the narrower request to the wider one is how somebody
    gets a diff they did not ask for.
    """
    if not argv:
        return Invocation(mode=CHECK, only=())

    word, rest = argv[0], tuple(argv[1:])
    if word not in SUBCOMMANDS:
        msg = f"unrecognised argument: {word!r}"
        raise UsageError(msg)

    if word != UPGRADE:
        if rest:
            msg = f"{word} takes no arguments, and was given {rest[0]!r}"
            raise UsageError(msg)
        return Invocation(mode=word, only=())

    if not rest:
        msg = "upgrade needs at least one distribution name; to move everything, use relock"
        raise UsageError(msg)
    for name in rest:
        if not name or name.startswith("-"):
            msg = f"{name!r} is not a distribution name"
            raise UsageError(msg)
    return Invocation(mode=UPGRADE, only=rest)


def _unknown(only: Sequence[str]) -> tuple[str, ...]:
    """Which requested distributions the committed lock does not contain.

    Args:
        only: The names asked for.

    Returns:
        The unrecognised names, sorted.

    Raises:
        LockError: If the lock cannot be read, in which case there is no closed
            set to check against and the caller reports that instead.
    """
    locked = {package.normalised for package in lock_of().packages}
    return tuple(sorted({name for name in only if normalise(name) not in locked}))


def main(argv: Sequence[str]) -> int:
    """Run the gate.

    Args:
        argv: The arguments after the module name.

    Returns:
        The process exit code.
    """
    try:
        invocation = parse(argv)
    except UsageError as fault:
        print(f"lock: {fault}")
        print(USAGE)
        return EXIT_USAGE

    if invocation.mode == UPGRADE:
        try:
            unknown = _unknown(invocation.only)
        except LockError as fault:
            print("lock: the committed lock could not be read, so there is nothing to upgrade")
            print(f"lock: {fault}")
            return EXIT_UNMEASURED
        if unknown:
            print(f"lock: not locked, so there is no version to move: {', '.join(unknown)}")
            print(USAGE)
            return EXIT_USAGE

    try:
        return run_lock(mode=invocation.mode, only=invocation.only)
    except OSError as fault:
        print(f"lock: the gate could not write its artefacts: {fault}")
        return EXIT_UNMEASURED
