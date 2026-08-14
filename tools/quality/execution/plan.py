"""What a child is told, and what its exit code means.

Pure: every function here maps values to values. The module that actually starts
a process is :mod:`tools.quality.execution.workspace`, and keeping the judgement
out of it is what lets every decision below be tested from literals.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Final

from tools.quality.mutation.plan import INHERITED_ENVIRONMENT, interpreter

__all__ = ["interpreter"]

MIN_SEED: Final[int] = 0
MAX_SEED: Final[int] = 4_294_967_295
"""The range CPython documents for ``PYTHONHASHSEED``."""

DEFAULT_SEED: Final[int] = 0
"""The canonical seed.

Zero, and not a random-looking constant, for two reasons. The mutation harness
already pins ``PYTHONHASHSEED`` to ``"0"``, and a second harness in the same
repository choosing differently would create two answers to "what is the seed".
And CPython documents ``0`` as *disabling* hash randomisation, so it is also the
strongest determinism on offer — any non-zero seed is a deliberate weakening,
for the purpose of *finding* an order dependency rather than avoiding one.
"""

DEFAULT_SHARD_COUNT: Final[int] = 4
DEFAULT_ITERATIONS: Final[int] = 3
MAX_ITERATIONS: Final[int] = 50
"""A bound, so that a mistyped iteration count cannot start an hour-long run."""

PYTEST_OK: Final[int] = 0
PYTEST_TESTS_FAILED: Final[int] = 1
PYTEST_INTERRUPTED: Final[int] = 2
PYTEST_INTERNAL_ERROR: Final[int] = 3
PYTEST_USAGE_ERROR: Final[int] = 4
PYTEST_NO_TESTS_COLLECTED: Final[int] = 5


class Verdict(StrEnum):
    """What one child run established."""

    PASSED = "passed"
    FAILED = "failed"
    UNMEASURED = "unmeasured"


def classify(exit_code: int | None, *, timed_out: bool = False) -> Verdict:
    """Turn a child's exit code into a verdict.

    Args:
        exit_code: What the child returned, or ``None`` if it never did.
        timed_out: Whether the child was stopped rather than finishing.

    Returns:
        The verdict.

    Only ``0`` and ``1`` are verdicts about the tests. Everything else is
    :attr:`Verdict.UNMEASURED`, and the two that matter most are the ones a
    two-state design gets wrong:

    * ``5`` is "no tests collected". Reading it as success reports a shard that
      ran nothing as a shard that passed — which, in a partition, is precisely
      the failure that makes the union claim false.
    * ``4`` is a usage error, and it is what pytest returns when a node ID in
      the args file no longer exists. That is collection drift, observed rather
      than inferred.
    """
    if timed_out or exit_code is None:
        return Verdict.UNMEASURED
    if exit_code == PYTEST_OK:
        return Verdict.PASSED
    if exit_code == PYTEST_TESTS_FAILED:
        return Verdict.FAILED
    return Verdict.UNMEASURED


def combine(verdicts: Sequence[Verdict]) -> Verdict:
    """One verdict for a whole run.

    Args:
        verdicts: One per shard.

    Returns:
        The strongest concern present.

    **Unmeasured outranks failed, deliberately.** A failed shard says a test is
    broken. An unmeasured one says the partition itself is not describing what
    ran, which casts doubt on every other shard's result — including the ones
    that passed. The more alarming fact is the one to report.
    """
    if not verdicts or Verdict.UNMEASURED in verdicts:
        return Verdict.UNMEASURED
    if Verdict.FAILED in verdicts:
        return Verdict.FAILED
    return Verdict.PASSED


def parse_seed(text: str) -> int:
    """Read a seed from the command line.

    Args:
        text: What the caller typed.

    Returns:
        The seed.

    Raises:
        ValueError: If it is not a whole number in CPython's documented range.

    There is deliberately no ``--seed random``. A seed nobody recorded is not a
    seed, and a failure that cannot be replayed is the thing this whole package
    exists to avoid.
    """
    try:
        seed = int(text)
    except ValueError as fault:
        msg = f"a seed must be a whole number, got {text!r}"
        raise ValueError(msg) from fault
    if not MIN_SEED <= seed <= MAX_SEED:
        msg = f"a seed must be in {MIN_SEED}..{MAX_SEED}, got {seed}"
        raise ValueError(msg)
    return seed


def child_argv(args_file: str, *, coverage: bool) -> tuple[str, ...]:
    """The arguments a shard's pytest is given, after the interpreter.

    Args:
        args_file: Path to the file listing this shard's node IDs.
        coverage: Whether to measure coverage in this child.

    Returns:
        The argument tuple.

    Four of these are load bearing and none is decoration:

    ``-p no:cacheprovider`` keeps concurrent children out of one ``.pytest_cache``.

    ``--hypothesis-profile=ci`` is ``derandomize=True, database=None``, so shards
    examine the same inputs and cannot pollute each other through ``.hypothesis``.

    ``--cov-fail-under=0`` is **mandatory**, not tidiness. ``pytest-cov`` reads
    ``fail_under`` from ``[tool.coverage.report]`` when no flag overrides it, and
    this repository sets it to 95. A shard measures a fraction of the suite and
    can never reach a whole-suite floor — measured here, one quarter of the suite
    reaches 87.43% — so without this flag **every shard exits 1** and the gate
    reports a broken suite while nothing is broken.

    ``-x`` is deliberately **absent**, unlike the mutation harness's child. There,
    the only question is "did anything fail". Here, stopping at the first failure
    would both hide the rest and make the shard's coverage depend on where it
    stopped, which would poison the comparison against the serial control.
    """
    argv = ["-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]
    argv += ["--hypothesis-profile=ci"]
    if coverage:
        argv += [
            "--cov=globin",
            "--cov=tools",
            "--cov-branch",
            "--cov-report=",
            "--cov-fail-under=0",
        ]
    argv.append(f"@{args_file}")
    return tuple(argv)


def child_environment(
    parent: Mapping[str, str], *, seed: int, coverage_file: str | None = None
) -> dict[str, str]:
    """The environment a shard's pytest is given.

    Args:
        parent: This process's environment.
        seed: The value ``PYTHONHASHSEED`` is pinned to.
        coverage_file: Where this child writes its coverage data, if measuring.

    Returns:
        The child's environment.

    An **allowlist**, reusing the one the mutation harness already maintains
    rather than growing a second copy that drifts from it. What is dropped is
    the point: ``PYTHONPATH`` would shadow ``src``, ``PYTEST_ADDOPTS`` would
    inject flags this design never chose, and ``COVERAGE_PROCESS_START`` would
    start a second, differently configured ``Coverage`` in a child that already
    starts one explicitly through ``--cov``.

    ``PYTHONHASHSEED`` is set here and not in a fixture because CPython reads it
    during interpreter startup to seed the hashing of ``str`` and ``bytes``.
    Assigning it inside a running process changes nothing about that process.

    ``PYTHONNOUSERSITE`` is deliberately absent. This machine's toolchain is
    installed at user level, and setting it makes the child unable to find
    pytest at all.
    """
    child = {name: parent[name] for name in INHERITED_ENVIRONMENT if name in parent}
    child["PYTHONDONTWRITEBYTECODE"] = "1"
    child["PYTHONHASHSEED"] = str(seed)
    if coverage_file is not None:
        child["COVERAGE_FILE"] = coverage_file
    return child


def replay_command(*, shard_index: int, shard_count: int, seed: int) -> str:
    """The command that reproduces one shard exactly.

    Args:
        shard_index: Which shard failed.
        shard_count: How many there were.
        seed: The seed that produced the deal.

    Returns:
        A single command line.

    Printed on every failure. The manifest, the shard count and the seed are
    together sufficient to reproduce a run, and that sentence is the whole seed
    contract — so the command that carries all three is what a failure report
    leads with.
    """
    return (
        f"python -m tools.quality.execution shards "
        f"--shards {shard_count} --only {shard_index} --seed {seed}"
    )
