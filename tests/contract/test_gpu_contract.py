"""This repository's GPU contract, held against the tree it describes.

The unit tests prove the judgements are right about literals. These prove they are
right about **this** repository: that the target matches the runtime contract, that
every forbidden field is one the interface does not ask for, that the reason codes
the gate can emit are exactly the ones it declares, and that the gate is registered
in the one command table.

ADR-0032's six conditions are asserted here too, because a gate added outside a
phase's declared scope has to be able to state all six — and this one is inside its
phase's scope, which makes conditions 1 and 2 trivially true and the other four
worth checking.
"""

import tomllib
from pathlib import Path
from typing import Final

import pytest

from tools.quality.commands import COMMANDS, MUTATING_COMMANDS, command_names
from tools.quality.gpu.gate import (
    DELIVERED_PHASE,
    OUTPUT_DIRECTORY,
    ROADMAP_TOTAL_PHASES,
    RUNTIME_CONTRACT,
    declaration_of,
)
from tools.quality.gpu.manifest import PHASE, REASONS
from tools.quality.gpu.plan import (
    CONFIGURATION_FILE,
    POLICIES,
    duplicate_capabilities,
    forbidden_field_problems,
    phase_problems,
    target_problems,
)
from tools.quality.runtime.plan import parse_declaration as parse_runtime_contract

GATE_NAME: Final[str] = "gpu"
"""What the command is called in the one command table."""


@pytest.fixture(scope="module")
def contract(repo_root: Path) -> object:
    """This repository's GPU contract."""
    return declaration_of(repo_root)


def test_the_contract_parses(contract: object) -> None:
    """The file this repository ships is one the gate can actually read."""
    assert contract.capabilities  # type: ignore[attr-defined]


def test_the_declared_target_matches_the_runtime_contract(
    repo_root: Path, contract: object
) -> None:
    """The tripwire's whole job.

    A permitted copy under `SOURCE_OF_TRUTH.md` is one a test compares against its
    source. Somebody changing the runtime contract and forgetting that this survey
    was conducted against the old one is exactly what this catches.
    """
    runtime = parse_runtime_contract((repo_root / RUNTIME_CONTRACT).read_text(encoding="utf-8"))
    assert not target_problems(
        contract.target,  # type: ignore[attr-defined]
        system=runtime.host.system,
        architecture=runtime.interpreter.architecture,
    )


def test_no_capability_is_declared_twice(contract: object) -> None:
    assert not duplicate_capabilities(contract.capabilities)  # type: ignore[attr-defined]


def test_every_gap_is_owned_by_a_phase_that_can_still_close_it(contract: object) -> None:
    """An absence owned by a shipped phase is one nobody will ever close."""
    assert not phase_problems(
        contract.capabilities,  # type: ignore[attr-defined]
        delivered=DELIVERED_PHASE,
        total=ROADMAP_TOTAL_PHASES,
    )


def test_the_contract_does_not_contradict_itself(contract: object) -> None:
    """A field both permitted and forbidden is a rule with an exception underneath it."""
    assert not forbidden_field_problems(
        contract.interface,  # type: ignore[attr-defined]
        contract.forbidden,  # type: ignore[attr-defined]
    )


def test_every_policy_is_one_of_the_two_words(contract: object) -> None:
    for capability in contract.capabilities:  # type: ignore[attr-defined]
        assert capability.policy in POLICIES


def test_nothing_is_required_yet_and_that_is_a_claim_about_globin(contract: object) -> None:
    """Nothing in GLOBIN depends on a GPU, so nothing here may be `required`.

    This is not a rule about the gate; it is a statement about the product that
    stops being true in the phase that makes something depend on a device. That
    phase edits this test in its own diff, where the decision is visible.
    """
    assert {capability.policy for capability in contract.capabilities} == {"optional"}  # type: ignore[attr-defined]


def test_the_forbidden_table_names_the_traps_the_ledger_records(contract: object) -> None:
    """Each entry was measured; see `docs/research/phase_023_sources.md` S-02 to S-04.

    Asserting the *names* rather than the count, because the value of the table is
    which labels it stops being read, and a count would be satisfied by padding.
    """
    names = {entry.name for entry in contract.forbidden}  # type: ignore[attr-defined]
    assert names == {"cuda_version", "DRIVER version", "CUDA version"}


def test_every_forbidden_entry_explains_what_reading_it_would_produce(contract: object) -> None:
    """A rule without its reason is one the next author deletes."""
    for entry in contract.forbidden:  # type: ignore[attr-defined]
        assert entry.reason.strip()
        assert entry.where.strip()


def test_the_manifest_records_the_phase_that_introduced_the_gate() -> None:
    assert PHASE == 23


def test_the_gate_is_registered_exactly_once_in_the_one_command_table() -> None:
    """ADR-0019: one table defines the checks, and every caller reads it."""
    assert command_names().count(GATE_NAME) == 1


def test_the_gate_only_reports_and_is_in_neither_fast_nor_full() -> None:
    """ADR-0032 condition 5.

    Sharper here than the artefact it writes: this gate reports on the *machine*
    rather than on the tree, so its verdict can change without a commit and a
    commit cannot change it. A gate in `full` should fail for something the commit
    did.
    """
    assert GATE_NAME not in MUTATING_COMMANDS
    bundled = {
        step.name
        for command in COMMANDS
        if command.name in {"fast", "full"}
        for step in command.steps
    }
    assert GATE_NAME not in bundled


def test_the_gate_writes_only_inside_the_ignored_evidence_root() -> None:
    """Nothing this produces is committed."""
    assert OUTPUT_DIRECTORY.startswith(".globin/")


def test_the_evidence_directory_is_ignored_by_git(repo_root: Path) -> None:
    """A manifest that could be committed is a manifest that will be."""
    assert ".globin/" in (repo_root / ".gitignore").read_text(encoding="utf-8")


def test_the_reason_codes_are_a_closed_set_and_all_are_prefixed() -> None:
    """A reason the gate can produce that this set does not name is a hole."""
    assert REASONS
    assert all(reason.startswith("GPU_") for reason in REASONS)


def test_every_declared_reason_is_reachable_from_the_gate(repo_root: Path) -> None:
    """A name nothing can produce is a claim about a check that does not exist."""
    source = (repo_root / "tools" / "quality" / "gpu" / "gate.py").read_text(encoding="utf-8")
    unreachable = [reason for reason in REASONS if reason.removeprefix("GPU_") not in source]
    assert not unreachable, f"declared but never emitted: {sorted(unreachable)}"


def test_the_contract_declares_the_schema_the_reader_implements(repo_root: Path) -> None:
    """A future schema is refused rather than read, per `SERIALIZATION_POLICY.md`."""
    document = tomllib.loads((repo_root / CONFIGURATION_FILE).read_text(encoding="utf-8"))
    assert document["schema"] == 1


def test_the_contract_declares_no_observed_value_as_a_setting(repo_root: Path) -> None:
    """It declares an interface, not a baseline.

    A pinned driver version would go red on a Tuesday for a reason nobody in this
    programme decided, and the bump would then be applied without being read. The
    observed values belong in the regenerated manifest, not here.

    Asserted over the **parsed values**, not the file's text. The prose above the
    tables names `610.88` while explaining why no table may — a text search would
    fail on the document that argues for the rule, which is the wrong reading of
    it. Comments are reasoning; only the values are the contract.
    """
    document = tomllib.loads((repo_root / CONFIGURATION_FILE).read_text(encoding="utf-8"))

    def strings(node: object) -> list[str]:
        if isinstance(node, str):
            return [node]
        if isinstance(node, dict):
            return [found for value in node.values() for found in strings(value)]
        if isinstance(node, list):
            return [found for value in node for found in strings(value)]
        return []

    versionish = [
        value for value in strings(document) if value.replace(".", "").isdigit() and "." in value
    ]
    assert not versionish, f"the contract declares an observed value: {versionish}"
