"""This repository's own benchmark contract, held against the tree.

`test_benchmark_plan.py` establishes that the reader is correct. This establishes
that the contract *this repository ships* says something true, which is a different
question and the one that would go stale.
"""

from pathlib import Path
from typing import Final

import pytest

from tools.quality.benchmark import gate
from tools.quality.benchmark.gate import (
    DELIVERED_PHASE,
    OUTPUT_DIRECTORY,
    ROADMAP_TOTAL_PHASES,
    declaration_of,
)
from tools.quality.benchmark.manifest import PHASE, REASONS
from tools.quality.benchmark.plan import (
    BACKENDS,
    CONFIGURATION_FILE,
    CPU,
    REDUCTIONS,
    Declaration,
    duplicate_workloads,
    phase_problems,
    shape_problems,
    target_problems,
)
from tools.quality.commands import COMMANDS, command_names, find
from tools.quality.runtime.plan import parse_declaration as parse_runtime_contract

GATE_NAME: Final[str] = "benchmark"
"""The command this gate is registered under."""


@pytest.fixture(scope="module")
def contract(repo_root: Path) -> Declaration:
    """This repository's benchmark contract."""
    return declaration_of(repo_root)


def test_the_contract_parses(contract: Declaration) -> None:
    assert contract.workloads


def test_the_declared_target_matches_the_runtime_contract(
    contract: Declaration, repo_root: Path
) -> None:
    """A tripwire: the two must not disagree about which machine this is."""
    runtime = parse_runtime_contract(
        (repo_root / "docs/engineering/runtime-contract.toml").read_text(encoding="utf-8")
    )
    assert (
        target_problems(
            contract.target,
            system=runtime.host.system,
            architecture=runtime.interpreter.architecture,
        )
        == ()
    )


def test_no_workload_is_declared_twice(contract: Declaration) -> None:
    assert duplicate_workloads(contract.workloads) == ()


def test_the_contract_is_one_this_harness_can_act_on(contract: Declaration) -> None:
    assert shape_problems(contract) == ()


def test_every_workload_is_owned_by_a_phase_that_can_still_answer_for_it(
    contract: Declaration,
) -> None:
    assert (
        phase_problems(contract.workloads, delivered=DELIVERED_PHASE, total=ROADMAP_TOTAL_PHASES)
        == ()
    )


def test_every_backend_is_one_of_the_declared_words(contract: Declaration) -> None:
    assert all(workload.backend in BACKENDS for workload in contract.workloads)


def test_the_declared_reduction_is_one_this_harness_implements(contract: Declaration) -> None:
    assert contract.method.reduction in REDUCTIONS


def test_every_device_workload_has_a_baseline_to_be_divided_by(contract: Declaration) -> None:
    """A speedup against a baseline that does not exist is not a number."""
    baselines = {item.family for item in contract.workloads if item.backend == CPU}
    for workload in contract.workloads:
        if workload.backend != CPU:
            assert workload.family in baselines, workload.identifier


def test_no_device_workload_is_measurable_yet_and_the_contract_says_which_phase(
    contract: Declaration,
) -> None:
    """The honest state of this repository today.

    `wheel-survey.toml` files no library under phase 24 and `torch` is Phase 183,
    so nothing installed here can reach a device. Each device workload therefore
    names the phase that would change that, which is what makes the absence a
    recorded gap rather than a hole.
    """
    device = [item for item in contract.workloads if item.backend != CPU]
    assert device, "a contract with no device workload would not be asking the question"
    assert all(item.phase > DELIVERED_PHASE for item in device)


def test_a_device_threshold_pays_for_the_round_trip(contract: Declaration) -> None:
    """A workload 1.1x faster on the device is slower once transfer is paid for."""
    for workload in contract.workloads:
        if workload.backend != CPU:
            assert workload.speedup_threshold > 1.0, workload.identifier


def test_the_manifest_records_the_phase_that_introduced_the_gate() -> None:
    assert PHASE == 24


def test_the_gate_is_registered_exactly_once_in_the_one_command_table() -> None:
    assert command_names().count(GATE_NAME) == 1


def test_the_gate_is_in_neither_fast_nor_full() -> None:
    """A gate inside `full` should fail for something the commit did.

    This one reports on the MACHINE rather than on the tree, so its verdict can
    change without a commit and a commit cannot change it. ADR-0032 condition 5.
    """
    for aggregate in ("fast", "full"):
        command = find(aggregate)
        assert command is not None
        assert GATE_NAME not in {step.name for step in command.steps}


def test_the_gate_sits_after_gpu_and_before_the_mutating_commands() -> None:
    names = command_names()
    assert names.index("gpu") < names.index(GATE_NAME) < names.index("fix")


def test_the_gate_declares_the_library_its_baselines_need() -> None:
    """One library is declared and the other deliberately is not.

    `numpy` is declared so a run without it refuses rather than recording three
    unavailable workloads and calling that a pass. `torch` is not, because its
    absence is the expected state rather than a reason to refuse to start.
    """
    command = find(GATE_NAME)
    assert command is not None
    modules = {module for step in command.steps for module in step.modules}
    assert "numpy" in modules
    assert "torch" not in modules


def test_the_gate_writes_only_inside_the_ignored_evidence_root() -> None:
    assert OUTPUT_DIRECTORY.startswith(".globin/")


def test_the_evidence_directory_is_ignored_by_git(repo_root: Path) -> None:
    assert ".globin/" in (repo_root / ".gitignore").read_text(encoding="utf-8")


def test_the_reason_codes_are_a_closed_set_and_all_are_prefixed() -> None:
    assert REASONS
    assert all(reason.startswith("BENCHMARK_") for reason in REASONS)


def test_every_declared_reason_is_reachable_from_the_gate(repo_root: Path) -> None:
    """A name nothing can produce is a claim about a check that does not exist."""
    source = (repo_root / "tools" / "quality" / "benchmark" / "gate.py").read_text(encoding="utf-8")
    for reason in REASONS:
        assert reason.removeprefix("BENCHMARK_") in source, reason


def test_the_contract_declares_the_schema_the_reader_implements(repo_root: Path) -> None:
    assert "schema = 1" in (repo_root / CONFIGURATION_FILE).read_text(encoding="utf-8")


def test_the_gate_summary_is_ascii() -> None:
    command = find(GATE_NAME)
    assert command is not None
    command.summary.encode("ascii")


def test_the_command_table_still_holds_every_gate() -> None:
    assert len(COMMANDS) == len(command_names())


def test_the_manifest_name_is_the_one_the_gate_writes() -> None:
    assert gate.MANIFEST_NAME.endswith(".json")
