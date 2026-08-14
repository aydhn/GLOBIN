"""The execution gate as it actually runs, with the child scripted.

The unit tests prove each decision from literals; none of them proves the gate
strings those decisions together correctly. This level runs the real
orchestration and substitutes only the thing that would otherwise take minutes
and touch the network of processes: the child.

``_ScriptedRunner`` hands back exit codes in a fixed order and **runs out**
rather than defaulting. A double that keeps answering after its script ends
turns "the gate called the child more times than expected" into a passing test.

No test here sleeps. The timeout path is driven by a double that raises
:class:`subprocess.TimeoutExpired` immediately —
``docs/TESTING_STRATEGY.md`` forbids synchronising a test with the clock.
"""

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from tools.quality.execution import cli, gate, plan

COLLECTION = "\n".join(f"tests/unit/test_{n % 3}.py::test_{n}" for n in range(12))
COLLECTED = f"{COLLECTION}\n\n12 tests collected in 0.10s\n"


class _ScriptedRunner:
    """Hands back a fixed sequence of exit codes, then refuses."""

    def __init__(self, *codes: int, collection: str = COLLECTED) -> None:
        self.codes = list(codes)
        self.collection = collection
        self.calls: list[tuple[tuple[str, ...], Mapping[str, str]]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,  # noqa: ARG002
        env: Mapping[str, str],
        timeout: float,  # noqa: ARG002
    ) -> tuple[int, bytes]:
        self.calls.append((tuple(argv), dict(env)))
        if "--collect-only" in argv:
            return 0, self.collection.encode("utf-8")
        if not self.codes:
            msg = f"the gate started more children than the script allowed: {argv}"
            raise AssertionError(msg)
        return self.codes.pop(0), b"scripted child output\n"


class _StoppedRunner:
    """A child that never returns."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,  # noqa: ARG002
        env: Mapping[str, str],  # noqa: ARG002
        timeout: float,
    ) -> tuple[int, bytes]:
        if "--collect-only" in argv:
            return 0, COLLECTED.encode("utf-8")
        raise subprocess.TimeoutExpired(cmd=list(argv), timeout=timeout)


@pytest.fixture(autouse=True)
def _reports_under_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Send every artefact to `tmp_path`, so no test writes into the repository."""
    monkeypatch.setattr(gate, "REPORTS", tmp_path / "execution")


def test_a_run_in_which_every_shard_passes_passes() -> None:
    runner = _ScriptedRunner(0, 0, 0)
    assert gate.run_shards(shard_count=3, run_process=runner) == gate.EXIT_OK


def test_a_failing_shard_fails_the_run() -> None:
    assert gate.run_shards(shard_count=3, run_process=_ScriptedRunner(0, 1, 0)) == (
        gate.EXIT_GATE_FAILED
    )


def test_a_shard_that_collected_nothing_stops_the_run() -> None:
    """Exit 5 is unmeasured, and it outranks the two shards that passed."""
    assert gate.run_shards(shard_count=3, run_process=_ScriptedRunner(0, 5, 0)) == (
        gate.EXIT_UNMEASURED
    )


def test_a_usage_error_from_a_shard_is_unmeasured() -> None:
    """Exit 4 is what pytest gives for a node ID that no longer exists."""
    assert gate.run_shards(shard_count=3, run_process=_ScriptedRunner(0, 4, 0)) == (
        gate.EXIT_UNMEASURED
    )


def test_an_unmeasured_shard_outranks_a_failed_one() -> None:
    assert gate.run_shards(shard_count=3, run_process=_ScriptedRunner(1, 5, 0)) == (
        gate.EXIT_UNMEASURED
    )


def test_a_child_that_never_returns_is_reported_rather_than_waited_for() -> None:
    assert gate.run_shards(shard_count=2, run_process=_StoppedRunner()) == gate.EXIT_UNMEASURED


def test_every_shard_is_started_exactly_once() -> None:
    runner = _ScriptedRunner(0, 0, 0, 0)
    gate.run_shards(shard_count=4, run_process=runner)
    shard_calls = [call for call in runner.calls if "--collect-only" not in call[0]]
    assert len(shard_calls) == 4
    args_files = {call[0][-1] for call in shard_calls}
    assert len(args_files) == 4, "two shards were given the same args file"


def test_only_runs_one_shard_and_no_others() -> None:
    """The replay path: reproduce one failure without paying for the rest."""
    runner = _ScriptedRunner(0)
    assert gate.run_shards(shard_count=4, only=2, run_process=runner) == gate.EXIT_OK
    assert len([call for call in runner.calls if "--collect-only" not in call[0]]) == 1


def test_every_child_carries_the_seed_it_was_given() -> None:
    runner = _ScriptedRunner(0, 0)
    gate.run_shards(shard_count=2, seed=4242, run_process=runner)
    shard_calls = [call for call in runner.calls if "--collect-only" not in call[0]]
    assert all(env["PYTHONHASHSEED"] == "4242" for _, env in shard_calls)


def test_every_child_writes_its_own_coverage_data() -> None:
    """Sharing one data file would make the children erase each other's work."""
    runner = _ScriptedRunner(0, 0, 0)
    gate.run_shards(shard_count=3, run_process=runner)
    shard_calls = [call for call in runner.calls if "--collect-only" not in call[0]]
    files = {env["COVERAGE_FILE"] for _, env in shard_calls}
    assert len(files) == 3


def test_the_args_files_together_account_for_every_test(tmp_path: Path) -> None:
    """The union claim, checked against what was actually written to disk."""
    gate.run_shards(shard_count=3, run_process=_ScriptedRunner(0, 0, 0))
    written: list[str] = []
    for args_file in sorted((tmp_path / "execution").glob("shard-*.args")):
        written += args_file.read_text(encoding="utf-8").splitlines()
    assert sorted(written) == sorted(COLLECTION.splitlines())
    assert len(written) == len(set(written))


def test_no_args_file_contains_a_blank_line(tmp_path: Path) -> None:
    """A blank line becomes an empty positional argument, which pytest refuses."""
    gate.run_shards(shard_count=3, run_process=_ScriptedRunner(0, 0, 0))
    for args_file in (tmp_path / "execution").glob("shard-*.args"):
        assert "" not in args_file.read_text(encoding="utf-8").splitlines()


def test_a_stale_args_file_from_a_wider_run_is_removed(tmp_path: Path) -> None:
    """A four-shard run's leftovers must not survive into a three-shard run."""
    reports = tmp_path / "execution"
    reports.mkdir(parents=True)
    (reports / "shard-009.args").write_text("stale\n", encoding="utf-8")
    gate.run_shards(shard_count=3, run_process=_ScriptedRunner(0, 0, 0))
    assert not (reports / "shard-009.args").exists()


def test_the_manifest_is_written_and_reads_back(tmp_path: Path) -> None:
    from tools.quality.execution import manifest

    gate.run_shards(shard_count=3, run_process=_ScriptedRunner(0, 0, 0))
    document = manifest.load((tmp_path / "execution" / "manifest.json").read_text(encoding="utf-8"))
    assert document["count"] == 12
    assert document["selection"] == gate.SELECTION


def test_a_collection_that_cannot_be_parsed_is_a_usage_error() -> None:
    runner = _ScriptedRunner(0, collection="nothing useful here\n")
    assert gate.run_shards(shard_count=2, run_process=runner) == gate.EXIT_USAGE


def test_more_shards_than_tests_is_refused_before_any_child_starts() -> None:
    runner = _ScriptedRunner()
    assert gate.run_shards(shard_count=99, run_process=runner) == gate.EXIT_USAGE
    assert len([call for call in runner.calls if "--collect-only" not in call[0]]) == 0


def test_a_shard_index_outside_the_range_is_refused() -> None:
    assert gate.run_shards(shard_count=3, only=9, run_process=_ScriptedRunner()) == gate.EXIT_USAGE


def test_a_failure_prints_the_seed_and_a_replay_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate.run_shards(shard_count=2, seed=77, run_process=_ScriptedRunner(1, 0))
    captured = capsys.readouterr()
    assert "seed: 77" in captured.err
    assert "--seed 77" in captured.err


# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------


def test_the_defaults_are_the_documented_ones() -> None:
    assert cli.parse(["shards"]) == {
        "shard_count": plan.DEFAULT_SHARD_COUNT,
        "seed": plan.DEFAULT_SEED,
        "only": None,
    }


def test_every_flag_is_read() -> None:
    assert cli.parse(["shards", "--shards", "6", "--seed", "9", "--only", "2"]) == {
        "shard_count": 6,
        "seed": 9,
        "only": 2,
    }


@pytest.mark.parametrize(
    "argv",
    [[], ["soak"], ["shards", "--wat", "1"], ["shards", "--shards"], ["shards", "--shards", "x"]],
)
def test_an_argument_that_cannot_be_honoured_is_refused_never_ignored(argv: list[str]) -> None:
    """A mistyped flag that silently does nothing reports on a run nobody chose."""
    with pytest.raises(cli.UsageError):
        cli.parse(argv)


def test_a_bad_command_line_exits_two_rather_than_running_anything() -> None:
    assert cli.main(["shards", "--seed", "banana"]) == gate.EXIT_USAGE


def test_help_exits_zero() -> None:
    assert cli.main(["--help"]) == gate.EXIT_OK


def test_a_collection_run_that_fails_is_a_usage_error() -> None:
    """pytest itself refusing to collect is not a suite failure to report."""

    class _BrokenCollector:
        def __call__(
            self,
            argv: Sequence[str],  # noqa: ARG002
            *,
            cwd: Path,  # noqa: ARG002
            env: Mapping[str, str],  # noqa: ARG002
            timeout: float,  # noqa: ARG002
        ) -> tuple[int, bytes]:
            return 4, b"pytest: error: unrecognized arguments\n"

    assert gate.run_shards(shard_count=2, run_process=_BrokenCollector()) == gate.EXIT_USAGE


def test_a_partition_that_lost_a_test_is_caught_before_any_child_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The union claim is arithmetic, so checking it costs nothing.

    Substituting a deliberately lossy partition proves the guard fires rather
    than merely existing — the same shape as the architecture suite's
    guard-the-guard tests.
    """
    from tools.quality.execution import shard

    monkeypatch.setattr(
        shard,
        "partition",
        lambda ids, *, shard_count, seed: ((ids[0],), (ids[1],)),  # noqa: ARG005
    )
    runner = _ScriptedRunner()
    assert gate.run_shards(shard_count=2, run_process=runner) == gate.EXIT_UNMEASURED
    assert len([call for call in runner.calls if "--collect-only" not in call[0]]) == 0


def test_a_stale_directory_in_the_run_folder_is_removed(tmp_path: Path) -> None:
    """`--basetemp` leaves directories, not just files, if one is ever added."""
    reports = tmp_path / "execution"
    (reports / "shard-000.coverage.d").mkdir(parents=True)
    gate.run_shards(shard_count=2, run_process=_ScriptedRunner(0, 0))
    assert not (reports / "shard-000.coverage.d").exists()
