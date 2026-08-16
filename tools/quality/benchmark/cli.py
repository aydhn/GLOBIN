"""The benchmark gate's argument surface.

Hand-written, like every other command line in this repository. ADR-0019 rejected
``argparse`` as disproportionate for the quality entrypoint, and the same argument
holds here.
"""

from collections.abc import Sequence
from typing import Final

from tools.quality.benchmark.gate import run_benchmark

CHECK: Final[str] = "check"
"""The one subcommand, and the default."""

SUBCOMMANDS: Final[frozenset[str]] = frozenset({CHECK})
"""What may follow the module name."""

EXIT_USAGE: Final[int] = 2
"""The command line was not understood."""

USAGE: Final[str] = """usage: python -m tools.quality.benchmark [check]

Measure the workloads docs/engineering/benchmark-contract.toml declares and
recompute every verdict from the numbers. Reaches no network.

Subcommands:
  check   Measure and write .globin/benchmark/benchmark-manifest.json. The default.

Exit codes:
  0  every workload was measured or recorded a state
  1  something the contract asserts is not true of this tree
  2  the command line was not understood
  3  the gate could not establish what it was asked to establish
"""


class UsageError(Exception):
    """The command line was not understood."""


def parse(argv: Sequence[str]) -> None:
    """Read a command line.

    Args:
        argv: The arguments after the module name.

    Raises:
        UsageError: If a word is unrecognised or repeated.
    """
    words = list(argv)
    if not words:
        return
    if len(words) > 1:
        msg = f"unrecognised argument: {words[1]!r}"
        raise UsageError(msg)
    if words[0] not in SUBCOMMANDS:
        msg = f"unrecognised argument: {words[0]!r}"
        raise UsageError(msg)


def main(argv: Sequence[str]) -> int:
    """Run the gate.

    Args:
        argv: The arguments after the module name.

    Returns:
        The exit code.
    """
    try:
        parse(argv)
    except UsageError as fault:
        print(f"benchmark: {fault}")
        print(USAGE)
        return EXIT_USAGE
    return run_benchmark()
