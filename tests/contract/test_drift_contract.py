"""The drift policy and gate, asserted against this repository rather than a fixture.

``tests/integration/test_drift_end_to_end.py`` establishes that the gate reaches
the right verdict about *this* machine. ``tests/unit/test_drift_gate.py``
establishes that it reaches the right verdict about *a* tree. This asserts the
facts about *this repository* — that the declaration says what it should, that the
gate is registered where it should be, and that the documents describing it exist
— and it lives at the contract level so that it runs inside the ordinary suite.
Every ``full`` run and every pre-commit run therefore gates on it, without anybody
remembering to invoke a separate command.

**Offline and read-only.** Nothing here starts a process and nothing reaches a
network; the one subprocess that checks the module can be started at all lives in
the integration module beside its other end-to-end claims.

**The boundary is asserted, not intended.** ADR-0050 states that this tooling
edits no registry key, no ``PATH``, no execution policy and no interpreter outside
the environment. A rule that only exists in prose is a rule that lasts until
somebody is in a hurry, so the tests below read the package's own source and fail
on the constructs that would cross it.
"""

import re
from pathlib import Path

import pytest

from tools.quality.commands import find
from tools.quality.drift import gate, manifest, plan

PACKAGE = ("tools", "quality", "drift")
"""Where the gate lives, as path components."""

DOCUMENT = "docs/engineering/ENVIRONMENT_DRIFT.md"
"""The document that explains what the declaration only states."""

FORBIDDEN_CONSTRUCTS = (
    "winreg",
    "setx",
    "Set-ExecutionPolicy",
    "HKEY_",
    "os.putenv",
    "shutil.rmtree",
)
"""Constructs that would take this package outside the boundary ADR-0050 draws.

Matched as constructs rather than as words. A test asserting a forbidden *word*
matches the comment that explains why the word is forbidden, which is how a
tripwire becomes a thing people delete.
"""


@pytest.fixture(scope="module")
def policy(repo_root: Path) -> plan.Policy:
    """The classification this repository actually carries."""
    return plan.parse_declaration((repo_root / plan.CONFIGURATION_FILE).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sources(repo_root: Path) -> dict[str, str]:
    """Every module in the package, read once."""
    directory = repo_root.joinpath(*PACKAGE)
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.py"))}


@pytest.fixture(scope="module")
def workflow(repo_root: Path) -> str:
    """The quality workflow, read once."""
    return (repo_root / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The declaration exists, parses, and is the shape the reader expects
# ---------------------------------------------------------------------------


def test_the_declaration_exists_and_parses(policy: plan.Policy) -> None:
    """A policy that classifies nothing would let every difference through undeclared."""
    assert policy.classes


def test_the_declaration_is_named_as_a_machine_readable_contract() -> None:
    """The naming convention `REPOSITORY_LAYOUT.md` sets for a file a tool reads."""
    name = Path(plan.CONFIGURATION_FILE).name
    assert name.endswith(".toml")
    assert name.islower()


def test_every_recorded_verdict_recomputes(policy: plan.Policy) -> None:
    """The claim this file makes about itself, checked rather than believed.

    An entry declaring a fault repairable in place whose own declaration does not
    support that fails here, offline, without a host — ADR-0052's pattern applied
    to repair rather than to wheels.
    """
    assert plan.policy_problems(policy) == ()


def test_no_key_is_classified_twice(policy: plan.Policy) -> None:
    """Two verdicts about one fact, resolved by whichever line happens to come first."""
    assert plan.duplicate_classes(policy) == ()


def test_every_implemented_rule_is_used(policy: plan.Policy) -> None:
    """A rule with no caller is where a defect hides until somebody finally calls it."""
    assert plan.unreachable_rules(policy) == ()


def test_every_class_carries_a_reason(policy: plan.Policy) -> None:
    """A classification with no argument is an assertion, and this repository writes arguments."""
    for entry in policy.classes:
        assert len(entry.reason.strip()) > 40, f"{entry.key} has no argument for its verdict"


def test_exactly_one_class_is_repairable_in_place(policy: plan.Policy) -> None:
    """The phase's whole claim, pinned.

    `RUNTIME_BASELINE.md` answers five distinct environment faults with "rebuild".
    Phase 019 says one of them does not deserve it. If this number grows, the
    growth is a decision somebody made and should have to edit this line to make.
    """
    repairable = [entry.key for entry in policy.classes if entry.repair == plan.REPAIR_IN_PLACE]
    assert repairable == ["environment.system_site_packages"]


def test_no_class_declares_a_write_outside_the_environment(policy: plan.Policy) -> None:
    """`WRITES` has no member for "outside the repository", and this is why."""
    for entry in policy.classes:
        assert entry.writes in plan.WRITES


# ---------------------------------------------------------------------------
# The policy and the repairs the tool implements agree, in both directions
# ---------------------------------------------------------------------------


def test_every_repair_the_policy_promises_is_implemented(policy: plan.Policy) -> None:
    """A promise the tool cannot keep is worse than a refusal, because it reads as done."""
    promised = {entry.key for entry in policy.classes if entry.repair == plan.REPAIR_IN_PLACE}
    assert promised <= set(gate.REPAIRS)


def test_every_implemented_repair_is_promised_by_the_policy(policy: plan.Policy) -> None:
    """The other direction: an implementation nothing reaches is code that never runs."""
    promised = {entry.key for entry in policy.classes if entry.repair == plan.REPAIR_IN_PLACE}
    assert set(gate.REPAIRS) <= promised


# ---------------------------------------------------------------------------
# Registration in the one command table
# ---------------------------------------------------------------------------


def test_the_gate_is_registered_in_the_one_command_table() -> None:
    """`commands.py` is the only place a check is defined, and every caller reads it."""
    command = find("drift")
    assert command is not None
    assert [step.argv for step in command.steps] == [("-m", "tools.quality.drift")]


def test_the_gate_is_absent_from_fast_and_full() -> None:
    """It writes an artefact, and it is unmeasured on a tree that has accepted nothing.

    Either alone would keep it out of `full`. Together they make it a gate that
    would be red on every fresh clone, which is how a gate gets switched off.
    """
    for name in ("fast", "full"):
        command = find(name)
        assert command is not None
        assert all(step.name != "drift" for step in command.steps)


def test_the_command_summary_is_ascii_like_every_other() -> None:
    """A Windows console encodes with the active code page, and `--help` prints this."""
    command = find("drift")
    assert command is not None
    assert command.summary.isascii()


def test_the_command_name_appears_once_in_the_table() -> None:
    """`find` is a linear scan, so a second entry would be unreachable and untested."""
    command = find("drift")
    assert command is not None
    assert command.name == "drift"


# ---------------------------------------------------------------------------
# Reason codes are a closed set, checked in both directions
# ---------------------------------------------------------------------------


def test_every_reason_the_gate_can_emit_is_declared(sources: dict[str, str]) -> None:
    """A reason the gate produces that the set does not name is a hole in the contract."""
    emitted = set(re.findall(r"REASON_[A-Z_]+", sources["gate.py"]))
    declared = set(re.findall(r"REASON_[A-Z_]+", sources["manifest.py"]))
    assert emitted <= declared


def test_no_declared_reason_is_unreachable(sources: dict[str, str]) -> None:
    """A name nothing can produce is a claim about a check that does not exist."""
    emitted = set(re.findall(r"REASON_[A-Z_]+", sources["gate.py"]))
    declared = set(re.findall(r"^(REASON_[A-Z_]+): Final", sources["manifest.py"], re.MULTILINE))
    assert declared <= emitted


def test_every_declared_reason_is_in_the_closed_set() -> None:
    """The frozenset and the constants cannot disagree about what the vocabulary is."""
    declared = {
        value
        for name, value in vars(manifest).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }
    assert declared == set(manifest.REASONS)


def test_every_reason_is_prefixed_with_the_gate_it_belongs_to() -> None:
    """A code read out of context should say which gate produced it."""
    for reason in manifest.REASONS:
        assert reason.startswith("DRIFT_")


# ---------------------------------------------------------------------------
# The gate's own shape
# ---------------------------------------------------------------------------


def test_the_manifest_records_the_phase_that_introduced_it() -> None:
    """A tripwire on the frontier, in the sense `SOURCE_OF_TRUTH.md` permits a copy."""
    assert manifest.PHASE == 19


def test_the_exit_codes_are_the_three_every_other_gate_uses() -> None:
    """A fourth would be a vocabulary the aggregate gate has to learn."""
    assert (gate.EXIT_OK, gate.EXIT_GATE_FAILED, gate.EXIT_UNMEASURED) == (0, 1, 3)


def test_the_gate_writes_under_the_ignored_evidence_directory(repo_root: Path) -> None:
    """Evidence is generated, and generated files are not committed."""
    assert gate.OUTPUT_DIRECTORY.startswith(".globin/")
    ignored = (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".globin/" in ignored


def test_the_package_is_committable(committable_files: tuple[str, ...], repo_root: Path) -> None:
    """A `.gitignore` pattern without a leading slash matches at every depth.

    Phase 018 lost a whole package to a bare `wheels/` and `git add -A` reported
    nothing. `env/`, `venv/` and `runs/` are still unanchored, so a package under
    `tools/quality/` needs a name none of them swallows — and that needs checking
    rather than remembering.
    """
    directory = repo_root.joinpath(*PACKAGE)
    for path in sorted(directory.glob("*.py")):
        relative = path.relative_to(repo_root).as_posix()
        assert relative in committable_files, f"Git would not commit {relative}"


def test_nothing_in_the_tooling_writes_the_declaration(sources: dict[str, str]) -> None:
    """`tomllib` reads TOML and the standard library ships no writer.

    The policy is what a person decided. A tool that could refresh it would turn a
    judgement into a mirror of whatever the host happened to be doing.
    """
    for name, source in sources.items():
        assert "tomli_w" not in source, name
        assert "toml.dump" not in source, name


@pytest.mark.parametrize("construct", FORBIDDEN_CONSTRUCTS)
def test_the_package_stays_inside_the_boundary(sources: dict[str, str], construct: str) -> None:
    """ADR-0050's boundary, asserted against the source rather than trusted.

    `shutil.rmtree` is on the list because this phase is the one that must not
    reach for it: repair short of recreation means the recursive delete stays in
    `tools/quality/runtime/`, where Phase 017 put it behind its own guard.
    """
    for name, source in sources.items():
        assert construct not in source, f"{name} carries {construct!r}"


def test_the_gate_scans_what_it_writes(sources: dict[str, str]) -> None:
    """Both documents this package writes land in a directory CI uploads."""
    assert sources["gate.py"].count("scan_for_secrets(") >= 3


# ---------------------------------------------------------------------------
# How CI runs it
# ---------------------------------------------------------------------------


def test_continuous_integration_runs_the_gate(workflow: str) -> None:
    """A gate nothing runs is a gate that stops working without anybody noticing."""
    assert "python -m tools.quality drift" in workflow


def test_continuous_integration_accepts_a_baseline_before_checking(workflow: str) -> None:
    """A fresh runner has no prior state, so a check alone would only ever be unmeasured.

    Accepting and then checking on a machine that has never seen this repository is
    a real claim rather than a tautology: it fails if any recorded value is
    unstable across two processes.
    """
    assert "python -m tools.quality.drift accept" in workflow
    accept = workflow.index("python -m tools.quality.drift accept")
    check = workflow.index("python -m tools.quality drift")
    assert accept < check, "the baseline must be accepted before it is compared against"


def test_the_drift_result_is_never_softened(workflow: str) -> None:
    """`continue-on-error`, `|| true` and `exit 0` turn a gate into a decoration."""
    block = workflow.split("Run the environment-drift gate", 1)[1].split("- name:", 1)[0]
    for mask in ("continue-on-error: true", "|| true", "exit 0"):
        assert mask not in block


def test_the_drift_evidence_is_uploaded_from_exactly_one_path(workflow: str) -> None:
    """Two paths re-root the archive at their least common ancestor.

    Phase 015 broke the `attest` job that way, which is why this is asserted rather
    than remembered.
    """
    block = workflow.split("name: drift-evidence", 1)[1].split("- name:", 1)[0]
    assert block.count("path:") == 1


# ---------------------------------------------------------------------------
# The document that explains it
# ---------------------------------------------------------------------------


def test_the_document_exists_and_opens_with_a_heading(repo_root: Path) -> None:
    """`DOCUMENTATION_STANDARD.md` requires it, and a contract test enforces it."""
    text = (repo_root / DOCUMENT).read_text(encoding="utf-8")
    assert text.lstrip().startswith("# ")


def test_the_document_names_every_repair_verdict(repo_root: Path) -> None:
    """A verdict a reader meets in output and cannot look up is a verdict with no meaning."""
    text = (repo_root / DOCUMENT).read_text(encoding="utf-8")
    for verdict in plan.REPAIRS:
        assert verdict in text, f"{verdict} is undocumented"


def test_the_document_states_what_is_deferred(repo_root: Path) -> None:
    """Naming the owning phase is what stops a reader inferring a rule from its absence."""
    text = (repo_root / DOCUMENT).read_text(encoding="utf-8")
    assert "020" in text
