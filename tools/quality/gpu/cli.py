"""The command line for the GPU capability gate.

Hand-written rather than ``argparse``, matching every other gate here: the surface
is one optional word, and a parser that accepts abbreviations and prefixes would
make ``ch`` mean ``check`` on a day somebody meant something else.

There is no networked subcommand, unlike ``wheels`` and ``supply``. Everything
this gate asks is answerable from this machine, so there is no second question to
put behind a second word.
"""

from collections.abc import Sequence
from typing import Final

from tools.quality.gpu.gate import EXIT_UNMEASURED, run_gpu

CHECK: Final[str] = "check"
"""Probe this host and recompute the contract against it. The default."""

SUBCOMMANDS: Final[frozenset[str]] = frozenset({CHECK})
"""Every word this command accepts."""

EXIT_USAGE: Final[int] = 2
"""The command line was not understood."""

USAGE: Final[str] = """usage: python -m tools.quality.gpu [check]

Whether this host has an NVIDIA device, which driver, which compute capability
and which CUDA runtime -- measured rather than assumed.

  check   Read docs/engineering/gpu-contract.toml, compare its target against
          the runtime contract, ask nvidia-smi the fields the contract permits,
          and record a state for every declared capability. The default.

Reaches no network. Writes .globin/gpu/gpu-manifest.json.

A host with no NVIDIA device is not a failure: every capability is recorded
ABSENT and the gate exits 0. What fails is a contract that contradicts itself,
a gap owned by nobody, or a probe that errored.

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
        print(f"gpu: {fault}")
        print(USAGE)
        return EXIT_USAGE
    try:
        return run_gpu()
    except OSError as fault:
        print(f"gpu: the gate could not write its artefacts: {fault}")
        return EXIT_UNMEASURED
