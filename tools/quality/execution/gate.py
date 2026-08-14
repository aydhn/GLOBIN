"""Collect once, partition, run each shard as its own process, compare.

**Everything this module prints is ASCII.** GLOBIN's host is Windows, where a
console stream is frequently not UTF-8: an em dash written here arrives in a CI
log as a replacement character. ``docs/LOGGING_POLICY.md`` reached the same
conclusion for log records and escapes non-ASCII for it; this is the same
constraint reached from the other direction, and it was found by reading the
first CI log this gate produced.

Four exit states, never two, matching the mutation gate: passed, failed, asked
for something impossible, and *ran but measured nothing*. The fourth is the one
a boolean design loses, and it is the one that matters most in a partition — a
shard that collected nothing has not passed, it has made the union claim false.

What this buys is **evidence, not speed**. It runs the suite once as a control
and again in N pieces, so it is slower than ``coverage``, not faster. What it
establishes is that no test depends on sharing a process with another, and that
coverage survives being measured in N processes and combined.
"""

import os
import platform
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from tools.quality.execution import manifest as manifest_module
from tools.quality.execution import plan, shard
from tools.quality.execution.workspace import (
    ProcessRunner,
    prepare,
    run_child,
    spawn,
    write_args_file,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
REPORTS: Final[Path] = REPO_ROOT / ".globin" / "execution"

EXIT_OK: Final[int] = 0
EXIT_GATE_FAILED: Final[int] = 1
EXIT_USAGE: Final[int] = 2
EXIT_UNMEASURED: Final[int] = 3

SELECTION: Final[str] = "not external"
"""The marker expression the manifest is collected under.

The same exclusion every command in the table carries. It is recorded *inside*
the digest, so a manifest of one selection can never be mistaken for another.
"""

COLLECT_TIMEOUT_SECONDS: Final[float] = 300.0
SHARD_TIMEOUT_SECONDS: Final[float] = 1800.0


def _collect(run_process: ProcessRunner) -> tuple[str, ...]:
    """Ask pytest what tests exist."""
    argv = (
        plan.interpreter(),
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
        "-m",
        SELECTION,
    )
    code, output = run_child(
        argv,
        cwd=REPO_ROOT,
        env=plan.child_environment(os.environ, seed=plan.DEFAULT_SEED),
        timeout=COLLECT_TIMEOUT_SECONDS,
        run_process=run_process,
    )
    if code != 0:
        msg = f"collection failed with exit {code}:\n{output}"
        raise manifest_module.ManifestError(msg)
    return manifest_module.parse_collection(output)


def _meta(count: int) -> dict[str, object]:
    """Context that is recorded and never digested."""
    return {
        "platform": sys.platform,
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "test_count": count,
    }


def run_shards(
    *,
    shard_count: int = plan.DEFAULT_SHARD_COUNT,
    seed: int = plan.DEFAULT_SEED,
    only: int | None = None,
    run_process: ProcessRunner = spawn,
) -> int:
    """Partition the suite and run every shard as its own process.

    Args:
        shard_count: How many shards.
        seed: Varies the deal, and pins ``PYTHONHASHSEED`` in every child.
        only: Run just this shard, for replaying a failure.
        run_process: How a child is started. Injected for testability.

    Returns:
        One of the four exit constants.
    """
    try:
        node_ids = _collect(run_process)
        shard.validate(total=len(node_ids), shard_count=shard_count, shard_index=only)
    except (manifest_module.ManifestError, shard.ShardError) as fault:
        print(f"execution: {fault}", file=sys.stderr)
        return EXIT_USAGE

    document = manifest_module.build(node_ids, selection=SELECTION, meta=_meta(len(node_ids)))
    prepare(REPORTS)
    (REPORTS / "manifest.json").write_text(
        manifest_module.render(document), encoding="utf-8", newline="\n"
    )
    print(f"execution: {len(node_ids)} tests, digest {document['digest']}")

    shards = shard.partition(node_ids, shard_count=shard_count, seed=seed)
    covered = _verify_partition(node_ids, shards)
    if covered is not None:
        print(f"execution: {covered}", file=sys.stderr)
        return EXIT_UNMEASURED

    chosen = range(shard_count) if only is None else [only]
    verdicts: list[plan.Verdict] = []
    for index in chosen:
        verdicts.append(
            _run_one(
                index, shards[index], shard_count=shard_count, seed=seed, run_process=run_process
            )
        )

    overall = plan.combine(verdicts)
    if overall is plan.Verdict.PASSED:
        print(f"execution: {len(chosen)} shard(s) passed, {len(node_ids)} tests accounted for.")
        return EXIT_OK
    if overall is plan.Verdict.FAILED:
        return EXIT_GATE_FAILED
    return EXIT_UNMEASURED


def _verify_partition(node_ids: Sequence[str], shards: Sequence[Sequence[str]]) -> str | None:
    """Check the mathematical contract before spending a single subprocess.

    Args:
        node_ids: The manifest.
        shards: The partition.

    Returns:
        ``None`` when the contract holds, or a message naming what broke.

    Cheap, and it fails in milliseconds rather than after N suite runs. The
    partition is arithmetic, so an error here is a defect in this package and
    checking for it costs nothing.
    """
    seen: list[str] = [name for group in shards for name in group]
    if len(seen) != len(set(seen)):
        return "a test was dealt into more than one shard, so the partition is not disjoint"
    if set(seen) != set(node_ids):
        missing = sorted(set(node_ids) - set(seen))
        return f"{len(missing)} test(s) reached no shard, starting with {missing[:3]}"
    return None


def _run_one(
    index: int,
    node_ids: Sequence[str],
    *,
    shard_count: int,
    seed: int,
    run_process: ProcessRunner,
) -> plan.Verdict:
    """Run one shard and report what it established."""
    args_file = REPORTS / f"shard-{index:03d}.args"
    write_args_file(args_file, node_ids)

    code, output = run_child(
        (plan.interpreter(), *plan.child_argv(str(args_file), coverage=True)),
        cwd=REPO_ROOT,
        env=plan.child_environment(
            os.environ, seed=seed, coverage_file=str(REPORTS / f"shard-{index:03d}.coverage")
        ),
        timeout=SHARD_TIMEOUT_SECONDS,
        run_process=run_process,
    )
    verdict = plan.classify(code)
    print(f"execution: shard {index} of {shard_count}, {len(node_ids)} tests: {verdict}")

    if verdict is not plan.Verdict.PASSED:
        _report_failure(
            index, output, code=code, shard_count=shard_count, seed=seed, size=len(node_ids)
        )
    return verdict


def _report_failure(
    index: int, output: str, *, code: int | None, shard_count: int, seed: int, size: int
) -> None:
    """Print everything needed to reproduce a failure, and nothing else."""
    print(f"\n--- shard {index} of {shard_count} (exit {code}) ---", file=sys.stderr)
    if code == plan.PYTEST_NO_TESTS_COLLECTED:
        print(
            f"the shard collected nothing although the manifest assigned it {size} tests. "
            "The manifest is stale relative to the tree; regenerate it.",
            file=sys.stderr,
        )
    if code == plan.PYTEST_USAGE_ERROR:
        print(
            "pytest refused an argument. A node ID in the args file no longer exists, "
            "which is collection drift; regenerate the manifest.",
            file=sys.stderr,
        )
    print(output, file=sys.stderr)
    print(f"seed: {seed}", file=sys.stderr)
    print(
        f"replay: {plan.replay_command(shard_index=index, shard_count=shard_count, seed=seed)}\n",
        file=sys.stderr,
    )
