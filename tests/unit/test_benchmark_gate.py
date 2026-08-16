"""The benchmark gate's sequencing, its manifest, its measurement and its CLI.

The pure judgements are `test_benchmark_plan.py`'s. What this establishes is that
the gate wires them to the right inputs, records what it did even when it could not
finish, and — the property no pure test can see — that the *derivation* of verdicts
from measurements is a function of its inputs even though the measurements are not.

Measurements are injected throughout, so nothing here waits for a clock or depends
on what this machine happened to be doing.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from tools.quality.benchmark import gate
from tools.quality.benchmark.cli import EXIT_USAGE, USAGE, UsageError, parse
from tools.quality.benchmark.cli import main as cli_main
from tools.quality.benchmark.gate import (
    DELIVERED_PHASE,
    EXIT_GATE_FAILED,
    EXIT_OK,
    ROADMAP_TOTAL_PHASES,
    declaration_of,
    digest_of,
    run_benchmark,
)
from tools.quality.benchmark.manifest import (
    PHASE,
    REASON_DECLARATION_UNREADABLE,
    REASON_TARGET_DIVERGED,
    REASON_WORKLOAD_ERRORED,
    REASONS,
    SCHEMA,
    SCHEMA_VERSION,
    BenchmarkManifestError,
    build,
    load,
    render,
)
from tools.quality.benchmark.plan import CPU, Measurement, State, Workload
from tools.quality.benchmark.probes import measure

CONTRACT = """\
schema = 1

[target]
system = "Windows"
architecture = "AMD64"

[method]
warmup = 0
repeats = 1
reduction = "minimum"
clock = "time.perf_counter_ns"

[[workload]]
id = "matmul.cpu"
question = "What does it cost here?"
backend = "cpu"
library = "numpy"
phase = 22
speedup_threshold = 1.0
size = 4

[[workload]]
id = "matmul.cuda"
question = "Does the device pay?"
backend = "cuda"
library = "torch"
phase = 183
speedup_threshold = 2.0
size = 4
"""

RUNTIME_CONTRACT = """\
schema = 1

[interpreter]
implementation = "CPython"
minor_line = "3.14"
minimum_patch = "3.14.0"
architecture = "AMD64"
pointer_bits = 64
free_threaded = false
allow_prerelease = true

[host]
system = "Windows"
minimum_release = "10"

[environment]
directory = ".venv"
system_site_packages = false
"""

TAKEN = (
    Measurement("matmul.cpu", State.MEASURED, 1000, "numpy"),
    Measurement("matmul.cuda", State.UNAVAILABLE, detail="torch is not installed"),
)


def build_tree(root: Path, *, contract: str | None = CONTRACT) -> None:
    """Write a tree the benchmark gate can judge."""
    engineering = root / "docs" / "engineering"
    engineering.mkdir(parents=True, exist_ok=True)
    (engineering / "runtime-contract.toml").write_text(
        RUNTIME_CONTRACT, encoding="utf-8", newline="\n"
    )
    if contract is not None:
        (engineering / "benchmark-contract.toml").write_text(
            contract, encoding="utf-8", newline="\n"
        )


def run(root: Path, **options: object) -> int:
    """Run the gate over a prepared tree, writing its evidence inside it."""
    return run_benchmark(root=root, reports=root / "out", **options)  # type: ignore[arg-type]


def manifest_of(root: Path) -> dict[str, object]:
    """The manifest the run wrote, verified against its own digest."""
    return load((root / "out" / gate.MANIFEST_NAME).read_text(encoding="utf-8"))


def reasons_of(document: dict[str, object]) -> list[str]:
    """The reason codes the manifest records."""
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    return list(verdict["reasons"])


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_a_coherent_tree_passes_and_records_what_it_measured(tmp_path: Path) -> None:
    build_tree(tmp_path)
    assert run(tmp_path, measurements=TAKEN) == EXIT_OK
    document = manifest_of(tmp_path)
    assert document["schema"] == SCHEMA
    assert document["phase"] == PHASE
    run_section = document["run"]
    assert isinstance(run_section, dict)
    assert run_section["declaration"] == "docs/engineering/benchmark-contract.toml"
    observed = run_section["observed"]
    assert isinstance(observed, dict)
    assert observed["measured"] == 1


def test_an_unadopted_backend_is_a_state_rather_than_a_failure(tmp_path: Path) -> None:
    """The whole point of the state model.

    Every CUDA workload is `unavailable` today, and the gate still exits zero.
    """
    build_tree(tmp_path)
    assert run(tmp_path, measurements=TAKEN) == EXIT_OK
    findings = manifest_of(tmp_path)["findings"]
    assert isinstance(findings, dict)
    workloads = findings["workloads"]
    assert isinstance(workloads, dict)
    records = workloads["workloads"]
    assert isinstance(records, list)
    states = {item["id"]: item["state"] for item in records}
    assert states["matmul.cuda"] == "unavailable"


def test_a_workload_that_errored_fails_the_gate(tmp_path: Path) -> None:
    """Not knowing why something did not run differs from knowing why."""
    build_tree(tmp_path)
    errored = (
        Measurement("matmul.cpu", State.MEASURED, 1000, "numpy"),
        Measurement("matmul.cuda", State.ERROR, detail="RuntimeError"),
    )
    assert run(tmp_path, measurements=errored) == EXIT_GATE_FAILED
    assert REASON_WORKLOAD_ERRORED in reasons_of(manifest_of(tmp_path))


def test_the_derivation_is_a_function_of_its_inputs(tmp_path: Path) -> None:
    """Two runs over the same measurements produce the same findings.

    The timings themselves are expected to move; what must not is the verdict
    derived from them.
    """
    build_tree(tmp_path)
    run(tmp_path, measurements=TAKEN)
    first = manifest_of(tmp_path)["findings"]
    run(tmp_path, measurements=TAKEN)
    assert manifest_of(tmp_path)["findings"] == first


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_a_missing_contract_is_reported_and_still_writes_evidence(tmp_path: Path) -> None:
    """A refusal still writes evidence.

    A gate that failed silently and left no artefact is indistinguishable, to
    anything reading afterwards, from a gate that never ran.
    """
    build_tree(tmp_path, contract=None)
    assert run(tmp_path, measurements=TAKEN) == EXIT_GATE_FAILED
    assert REASON_DECLARATION_UNREADABLE in reasons_of(manifest_of(tmp_path))


def test_an_unparsable_contract_is_reported(tmp_path: Path) -> None:
    build_tree(tmp_path, contract="not toml = = =")
    assert run(tmp_path, measurements=TAKEN) == EXIT_GATE_FAILED
    assert REASON_DECLARATION_UNREADABLE in reasons_of(manifest_of(tmp_path))


def test_a_missing_runtime_contract_is_reported(tmp_path: Path) -> None:
    build_tree(tmp_path)
    (tmp_path / "docs" / "engineering" / "runtime-contract.toml").unlink()
    assert run(tmp_path, measurements=TAKEN) == EXIT_GATE_FAILED
    assert REASON_TARGET_DIVERGED in reasons_of(manifest_of(tmp_path))


def test_a_contract_written_for_another_host_fails(tmp_path: Path) -> None:
    build_tree(tmp_path, contract=CONTRACT.replace('system = "Windows"', 'system = "Linux"'))
    assert run(tmp_path, measurements=TAKEN) == EXIT_GATE_FAILED
    assert REASON_TARGET_DIVERGED in reasons_of(manifest_of(tmp_path))


def test_the_commit_is_read_from_git_without_starting_a_process(tmp_path: Path) -> None:
    """Read from `.git` directly.

    Every other gate does the same, so a manifest can be produced in a tree with
    no Git on the path.
    """
    build_tree(tmp_path)
    run(tmp_path, measurements=TAKEN)
    run_section = manifest_of(tmp_path)["run"]
    assert isinstance(run_section, dict)
    assert run_section["commit"] == "unknown"


def test_the_commit_is_read_through_a_reference(tmp_path: Path) -> None:
    build_tree(tmp_path)
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
    (git / "refs" / "heads" / "master").write_text("a" * 40, encoding="utf-8")
    run(tmp_path, measurements=TAKEN)
    run_section = manifest_of(tmp_path)["run"]
    assert isinstance(run_section, dict)
    assert run_section["commit"] == "a" * 40


def test_a_detached_head_is_read_directly(tmp_path: Path) -> None:
    build_tree(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("b" * 40, encoding="utf-8")
    run(tmp_path, measurements=TAKEN)
    run_section = manifest_of(tmp_path)["run"]
    assert isinstance(run_section, dict)
    assert run_section["commit"] == "b" * 40


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


def document() -> dict[str, object]:
    """A manifest with everything a reader needs."""
    return build(run={"commit": "x"}, findings={"a": {"verdict": "passed"}}, verdict={"v": "p"})


def test_a_manifest_verifies_against_its_own_digest() -> None:
    assert load(render(document()))["schema_version"] == SCHEMA_VERSION


def test_a_manifest_that_is_not_json_is_refused() -> None:
    with pytest.raises(BenchmarkManifestError, match="not valid JSON"):
        load("{")


def test_a_manifest_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(BenchmarkManifestError, match="expected an object"):
        load("[]")


def test_another_schema_is_refused() -> None:
    text = render({**document(), "schema": "something.else"})
    with pytest.raises(BenchmarkManifestError, match="declares schema"):
        load(text)


def test_another_version_is_refused() -> None:
    built = document()
    built["schema_version"] = 99
    with pytest.raises(BenchmarkManifestError, match="declares version"):
        load(render(built))


def test_a_tampered_manifest_is_refused() -> None:
    built = document()
    built["phase"] = 999
    with pytest.raises(BenchmarkManifestError, match="content digests to"):
        load(render(built))


def test_every_declared_reason_is_prefixed_and_the_set_is_closed() -> None:
    assert REASONS
    assert all(reason.startswith("BENCHMARK_") for reason in REASONS)


def test_the_digest_helper_is_a_plain_content_hash() -> None:
    assert digest_of(b"x") == digest_of(b"x")
    assert digest_of(b"x") != digest_of(b"y")


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def workload(identifier: str, backend: str = CPU, family_size: int = 4) -> Workload:
    """One workload to measure."""
    return Workload(identifier, "why", backend, "numpy", 22, 1.0, family_size)


def test_a_cpu_workload_is_measured_with_an_injected_clock() -> None:
    """The clock is injected so the expected figure is exact."""
    ticks = iter([0, 5, 10, 25])
    taken = measure(workload("elementwise.cpu"), 0, 2, "minimum", clock=lambda: next(ticks))
    assert taken.state is State.MEASURED
    assert taken.nanoseconds == 5


def test_every_declared_family_has_a_runner() -> None:
    for family in ("elementwise", "matmul", "reduction"):
        taken = measure(workload(f"{family}.cpu"), 0, 1, "minimum")
        assert taken.state is State.MEASURED, family


def test_an_unadopted_backend_records_the_library_it_needed() -> None:
    taken = measure(workload("matmul.cuda", backend="cuda"), 0, 1, "minimum")
    assert taken.state is State.UNAVAILABLE
    assert "torch" in taken.detail


def test_a_backend_with_no_runner_is_an_error() -> None:
    taken = measure(workload("matmul.quantum", backend="quantum"), 0, 1, "minimum")
    assert taken.state is State.ERROR


def test_a_workload_that_raises_becomes_an_error_rather_than_a_crash() -> None:
    """A reduction the harness does not implement fails inside the timed block."""
    taken = measure(workload("matmul.cpu"), 0, 1, "mean")
    assert taken.state is State.ERROR


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def test_no_argument_means_check() -> None:
    parse([])


def test_the_one_subcommand_is_accepted() -> None:
    parse(["check"])


def test_an_unrecognised_word_is_refused_rather_than_ignored() -> None:
    with pytest.raises(UsageError, match="unrecognised"):
        parse(["measure"])


def test_a_trailing_word_is_refused() -> None:
    with pytest.raises(UsageError, match="unrecognised"):
        parse(["check", "--verbose"])


def test_a_usage_error_prints_the_usage_and_returns_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli_main(["nonsense"]) == EXIT_USAGE
    assert "usage:" in capsys.readouterr().out


def test_the_usage_text_documents_every_exit_code() -> None:
    for code in ("0", "1", "2", "3"):
        assert f"  {code}  " in USAGE


def test_the_module_entry_point_runs() -> None:
    """Exercised by a subprocess rather than a coverage pragma."""
    completed = subprocess.run(
        [sys.executable, "-m", "tools.quality.benchmark", "nonsense"],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[2],
        timeout=120,
    )
    assert completed.returncode == EXIT_USAGE


# ---------------------------------------------------------------------------
# This repository's own contract
# ---------------------------------------------------------------------------


def test_the_repositorys_contract_reads_and_every_phase_is_plausible() -> None:
    declared = declaration_of()
    assert declared.workloads
    assert DELIVERED_PHASE <= ROADMAP_TOTAL_PHASES


def test_reading_a_contract_from_a_tree_without_one_is_refused(tmp_path: Path) -> None:
    from tools.quality.benchmark.plan import BenchmarkContractError as ContractError

    with pytest.raises(ContractError, match="could not be read"):
        declaration_of(tmp_path)
