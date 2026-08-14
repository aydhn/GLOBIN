"""Argument parsing, hand-written and pure.

Hand-written for the same reason ``tools/quality/__main__.py`` is: the surface
is a mode and three integers, and :mod:`argparse` would be more configuration
than logic. Pure, so that every refusal below is tested from literals rather
than by starting a process and reading stderr.

Unknown arguments are **refused**, never ignored. A mistyped flag that silently
does nothing is how a run reports on a configuration nobody chose.
"""

from collections.abc import Sequence
from typing import Final

from tools.quality.execution import gate, plan

MODES: Final[tuple[str, ...]] = ("shards",)

USAGE: Final[str] = f"""\
usage: python -m tools.quality.execution shards [options]

  --shards N   how many shards to split the suite into (default {plan.DEFAULT_SHARD_COUNT})
  --only I     run only shard I, for replaying a failure
  --seed S     vary the deal; the same seed reproduces the run (default {plan.DEFAULT_SEED})

The manifest, the shard count and the seed together reproduce a run exactly.
"""


class UsageError(Exception):
    """The command line asked for something that cannot be honoured."""


def parse(argv: Sequence[str]) -> dict[str, int | None]:
    """Turn a command line into settings.

    Args:
        argv: Arguments after the module name.

    Returns:
        ``shard_count``, ``seed`` and ``only``.

    Raises:
        UsageError: On an unknown mode, an unknown flag, a flag with no value,
            or a value that is not a whole number in range.
    """
    if not argv or argv[0] not in MODES:
        given = argv[0] if argv else "(nothing)"
        msg = f"expected one of {', '.join(MODES)}, got {given!r}"
        raise UsageError(msg)

    settings: dict[str, int | None] = {
        "shard_count": plan.DEFAULT_SHARD_COUNT,
        "seed": plan.DEFAULT_SEED,
        "only": None,
    }
    flags = {"--shards": "shard_count", "--seed": "seed", "--only": "only"}

    rest = list(argv[1:])
    while rest:
        flag = rest.pop(0)
        if flag not in flags:
            msg = f"unknown argument {flag!r}"
            raise UsageError(msg)
        if not rest:
            msg = f"{flag} needs a value"
            raise UsageError(msg)
        raw = rest.pop(0)
        if flag == "--seed":
            try:
                settings["seed"] = plan.parse_seed(raw)
            except ValueError as fault:
                raise UsageError(str(fault)) from fault
        else:
            try:
                settings[flags[flag]] = int(raw)
            except ValueError as fault:
                msg = f"{flag} needs a whole number, got {raw!r}"
                raise UsageError(msg) from fault
    return settings


def main(argv: Sequence[str]) -> int:
    """Run the gate.

    Args:
        argv: Arguments after the module name.

    Returns:
        One of the gate's four exit constants.
    """
    if argv and argv[0] in {"-h", "--help"}:
        print(USAGE)
        return gate.EXIT_OK
    try:
        settings = parse(argv)
    except UsageError as fault:
        print(f"execution: {fault}\n\n{USAGE}", file=__import__("sys").stderr)
        return gate.EXIT_USAGE
    return gate.run_shards(
        shard_count=int(settings["shard_count"] or plan.DEFAULT_SHARD_COUNT),
        seed=int(settings["seed"] or 0),
        only=settings["only"],
    )
