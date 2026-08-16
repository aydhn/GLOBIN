"""The wheel survey, asserted against this repository rather than a fixture.

``tests/integration/test_wheels_end_to_end.py`` establishes that the gate reaches
the right verdict about *a* tree. This asserts the facts about *this* one, and it
lives at the contract level so that it runs inside the ordinary suite — which
means every ``full`` run and every pre-commit run gates on it, without anybody
remembering to invoke a separate command.

**Offline and read-only.** Nothing here starts a process except the one deliberate
subprocess that checks the module can be started at all, and nothing reaches an
index. Whether the record still matches what PyPI publishes is a different
question, asked by ``python -m tools.quality.wheels probe``; asserting it here
would make the suite fail on a day an upstream project cut a release, which is a
fact about the world rather than about this tree.

**The survey's target is a tripwire and so is the delivered-phase bound.** Both
are copies, in the sense ``docs/engineering/SOURCE_OF_TRUTH.md`` permits: compared
here against the thing they copy, so that a change touching only one of them
fails.
"""

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from tests.contract.test_roadmap_contract import LAST_COMPLETED_PHASE
from tools.quality.commands import COMMANDS, find
from tools.quality.runtime import plan as runtime_plan
from tools.quality.wheels import gate, manifest, plan

RUNTIME_CONTRACT = "docs/engineering/runtime-contract.toml"


@pytest.fixture(scope="module")
def declaration(repo_root: Path) -> plan.Declaration:
    """The survey this repository actually carries."""
    text = (repo_root / plan.CONFIGURATION_FILE).read_text(encoding="utf-8")
    return plan.parse_declaration(text)


@pytest.fixture(scope="module")
def contract(repo_root: Path) -> runtime_plan.Contract:
    """The interpreter contract the survey is conducted against."""
    return runtime_plan.parse_declaration(
        (repo_root / RUNTIME_CONTRACT).read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# The declaration exists, parses, and is the shape the reader expects
# ---------------------------------------------------------------------------


def test_the_survey_exists_and_parses(declaration: plan.Declaration) -> None:
    assert declaration.libraries


def test_the_contract_file_is_named_as_a_machine_readable_contract() -> None:
    """A file tools parse is not a document.

    Naming it like one invites a reader to edit it as prose, and the difference
    matters: a document may be improved freely, while a contract file changes what
    the tests enforce.
    """
    name = Path(plan.CONFIGURATION_FILE).name
    assert name.endswith(".toml")
    assert name.islower()
    assert name == "wheel-survey.toml"


def test_the_survey_lives_beside_the_document_that_explains_it(repo_root: Path) -> None:
    assert (repo_root / plan.CONFIGURATION_FILE).is_file()
    assert (repo_root / "docs" / "engineering" / "WHEEL_AVAILABILITY.md").is_file()


def test_nothing_in_the_tooling_writes_the_survey(repo_root: Path) -> None:
    """It is a declaration, not a snapshot.

    A file generated from the index could only ever agree with the index, which is
    a mirror rather than a check — the argument ``action-pins.toml`` makes about
    itself. ``tomllib`` reads TOML and the standard library ships no writer, so
    this is close to structurally guaranteed; asserting it keeps a future
    contributor from adding one.
    """
    package = repo_root / "tools" / "quality" / "wheels"
    for module in sorted(package.glob("*.py")):
        source = module.read_text(encoding="utf-8")
        assert "tomli_w" not in source
        assert "toml.dump" not in source

    writes = [
        line.strip()
        for line in (package / "gate.py").read_text(encoding="utf-8").splitlines()
        if ".write_text(" in line
    ]
    assert writes, "the gate writes nothing, which cannot be right"
    for line in writes:
        assert "MANIFEST_NAME" in line, f"the gate writes something other than its manifest: {line}"


# ---------------------------------------------------------------------------
# The target, against the runtime contract
# ---------------------------------------------------------------------------


def test_the_survey_target_matches_the_runtime_contract(
    declaration: plan.Declaration, contract: runtime_plan.Contract
) -> None:
    """The tripwire.

    A survey conducted against an interpreter the project does not run is not
    merely stale; it reports availability for a line nothing uses while the pinned
    line goes unexamined.
    """
    interpreter = contract.interpreter
    assert (
        plan.target_problems(
            declaration.target,
            implementation=interpreter.implementation,
            minor_line=interpreter.minor_line,
            architecture=interpreter.architecture,
            free_threaded=interpreter.free_threaded,
        )
        == ()
    )


def test_the_platform_tag_follows_from_the_architecture(declaration: plan.Declaration) -> None:
    assert declaration.target.platform_tag == plan.platform_tag_for(declaration.target.architecture)


def test_the_survey_is_conducted_against_the_default_build(
    declaration: plan.Declaration,
) -> None:
    """ADR-0050 refused the free-threaded build.

    The survey targets what the project runs; what adopting the other build would
    cost is computed beside it rather than declared.
    """
    assert declaration.target.free_threaded is False


def test_the_index_surveyed_is_the_public_one_and_carries_no_credential(
    declaration: plan.Declaration,
) -> None:
    """No private index, and nothing that could carry a token into the manifest."""
    assert declaration.target.index.startswith("https://pypi.org/")
    assert "@" not in declaration.target.index


# ---------------------------------------------------------------------------
# Every entry, recomputed
# ---------------------------------------------------------------------------


def test_every_recorded_verdict_follows_from_its_own_evidence(
    declaration: plan.Declaration,
) -> None:
    """What stops the declaration being a transcription.

    Each entry records the filenames it was judged from, and the judgement is made
    again here from those filenames rather than believed.
    """
    problems = [
        problem
        for library in declaration.libraries
        for problem in plan.verdict_problems(library, declaration.target)
    ]
    assert problems == []


def test_every_scheduled_library_has_a_wheel_for_the_pinned_interpreter(
    declaration: plan.Declaration,
) -> None:
    """The question Phase 018 exists to answer, asserted rather than described.

    If this ever fails, ADR-0051 states what follows: the contract Phase 017 wrote
    is what changes.
    """
    without = [
        library.name
        for library in declaration.libraries
        if not plan.serving_wheels(library.wheels, declaration.target)
    ]
    assert without == []


def test_every_entry_names_a_phase_that_has_not_shipped(declaration: plan.Declaration) -> None:
    assert (
        plan.phase_problems(
            declaration.libraries,
            delivered=gate.DELIVERED_PHASE,
            total=gate.ROADMAP_TOTAL_PHASES,
        )
        == ()
    )


def test_every_gap_is_owned(declaration: plan.Declaration) -> None:
    assert (
        plan.gap_problems(
            declaration.libraries,
            delivered=gate.DELIVERED_PHASE,
            total=gate.ROADMAP_TOTAL_PHASES,
        )
        == ()
    )


def test_no_distribution_is_surveyed_twice(declaration: plan.Declaration) -> None:
    assert plan.duplicate_libraries(declaration.libraries) == ()


def test_every_entry_records_where_its_evidence_was_read(
    declaration: plan.Declaration,
) -> None:
    """A claim about an external system names its source.

    ``docs/SOURCE_POLICY.md``'s rule, applied to a machine-readable file rather
    than to prose.
    """
    for library in declaration.libraries:
        assert library.source.startswith("https://pypi.org/pypi/")
        assert library.source.endswith("/json")
        assert library.name in library.source


def test_every_entry_states_why_it_is_in_the_survey(declaration: plan.Declaration) -> None:
    """An entry nobody justified is an entry nobody can argue with when it needs removing."""
    for library in declaration.libraries:
        assert len(library.reason) > 30
        assert library.reason.strip().endswith((".", '"'))


def test_the_survey_covers_the_libraries_the_phase_001_ledger_names(
    declaration: plan.Declaration,
) -> None:
    """The set is the roadmap's, not the author's.

    Phase 001 recorded distribution metadata for each of these against a named
    source; a survey that quietly dropped one would leave the interpreter pinned
    on evidence about a smaller stack than the programme actually schedules.

    Three of the ledger's names are deliberately absent from this set rather than
    from the programme. ``numpy`` and ``pandas`` left in Phase 022 and ``ta-lib``
    in Phase 025, each on adoption: once a library is installed the answerable
    question stops being whether a wheel exists and becomes whether the thing
    inside it computes, which ``docs/engineering/stack-contract.toml`` measures.
    Dropping a name here is only safe because that file picks it up, which
    ``test_stack_contract.py`` asserts from the other side.
    """
    surveyed = {library.name for library in declaration.libraries}
    named = {
        "torch",
        "xgboost",
        "lightgbm",
        "optuna",
        "gymnasium",
        "stable-baselines3",
        "binance-sdk-spot",
        "binance-sdk-margin-trading",
        "binance-sdk-derivatives-trading-usds-futures",
        "binance-sdk-derivatives-trading-coin-futures",
        "binance-sdk-derivatives-trading-options",
        "binance-sdk-derivatives-trading-portfolio-margin",
        "binance-sdk-derivatives-trading-portfolio-margin-pro",
        "binance-sdk-wallet",
        "binance-sdk-algo",
    }
    assert named <= surveyed


def test_the_binance_family_still_caps_below_the_next_interpreter_line(
    declaration: plan.Declaration,
) -> None:
    """The sharpest finding in the survey, pinned so that it cannot quietly change.

    Every ``binance-sdk-*`` distribution publishes an upper bound. The pinned line
    satisfies it and the next one would not, which is why ADR-0050 named an exact
    minor line rather than a floor.
    """
    family = [
        library
        for library in declaration.libraries
        if library.name.startswith(("binance-sdk-", "binance-common"))
    ]
    assert family
    for library in family:
        assert "<3.15" in library.requires_python
        assert plan.admits(library.requires_python, declaration.target)


def test_no_surveyed_library_would_block_a_free_threaded_build(
    declaration: plan.Declaration,
) -> None:
    """The list this survey tracks has emptied, and that does not reopen ADR-0050.

    Until Phase 025 the answer here was ``("ta-lib",)``, and the older test said
    that when the list emptied the refusal would be worth revisiting. It has
    emptied, and it is not — because the blocker did not go away, it was adopted.
    ``ta-lib`` publishes ``cp314-cp314`` and no ``cp314t``, which is as true of the
    installed distribution as it was of the surveyed one; what changed is which
    file is answerable for it.

    So this asserts emptiness of *the survey*, and the assertion is worth keeping
    for the case it still catches: a library scheduled but not yet adopted that
    would block the build. Read together with the survey's own note, the pair says
    what is true — nothing unadopted blocks it, and one adopted thing does.
    """
    assert plan.free_threaded_gaps(declaration.libraries, declaration.target) == ()


# ---------------------------------------------------------------------------
# Registration in the one command table
# ---------------------------------------------------------------------------


def test_the_gate_is_registered_in_the_one_command_table() -> None:
    """Every check is a name in ``tools/quality/commands.py`` and nowhere else."""
    command = find("wheels")
    assert command is not None
    assert [step.argv for step in command.steps] == [("-m", "tools.quality.wheels")]


def test_the_gate_is_absent_from_fast_and_full() -> None:
    """It writes an artefact, and ``full`` reports rather than produces.

    The assertions that must gate a commit are in this module, which the coverage
    step already runs.
    """
    for name in ("fast", "full"):
        command = find(name)
        assert command is not None
        assert all(step.name != "wheels" for step in command.steps)


def test_the_registered_step_never_reaches_the_index() -> None:
    """``probe`` can. The registered step must not ask for it.

    Otherwise ``python -m tools.quality wheels`` acquires a network dependency
    that nothing in its name suggests.
    """
    command = find("wheels")
    assert command is not None
    for step in command.steps:
        assert "probe" not in step.argv


def test_the_command_summary_is_ascii_like_every_other() -> None:
    command = find("wheels")
    assert command is not None
    assert command.summary.isascii()


def test_the_command_name_appears_once_in_the_table() -> None:
    assert [command.name for command in COMMANDS].count("wheels") == 1


def test_the_module_can_be_started_and_reports_its_usage() -> None:
    """A pragma asserts a line does not need testing.

    Starting the module is the only way to find out whether it works.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "tools.quality.wheels", "--help"],
        capture_output=True,
        cwd=gate.REPO_ROOT,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 2
    assert b"usage: python -m tools.quality.wheels" in completed.stdout


# ---------------------------------------------------------------------------
# The gate's own shape
# ---------------------------------------------------------------------------


def test_the_manifest_records_the_phase_that_introduced_it() -> None:
    assert manifest.PHASE == 18


def test_the_exit_codes_are_the_three_every_other_gate_uses() -> None:
    assert (gate.EXIT_OK, gate.EXIT_GATE_FAILED, gate.EXIT_UNMEASURED) == (0, 1, 3)


def test_the_gate_writes_under_the_ignored_evidence_directory(repo_root: Path) -> None:
    assert gate.OUTPUT_DIRECTORY.startswith(".globin/")
    ignored = (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".globin/" in ignored


def test_the_delivered_phase_bound_never_claims_more_than_has_shipped() -> None:
    """The second tripwire, and deliberately an inequality.

    ``DELIVERED_PHASE`` is a constant in the gate so that its verdict does not
    depend on parsing ``ROADMAP.md``. Requiring it to *equal* the frontier would
    oblige every remaining phase to edit an unrelated file to keep this suite
    green, and a constant bumped to silence a test is a constant nobody reads.

    Erring low only makes the gate more permissive. Erring high would make it
    reject a legitimate entry, which is the failure worth preventing.
    """
    assert gate.DELIVERED_PHASE <= LAST_COMPLETED_PHASE


def test_every_reason_the_gate_can_emit_is_declared() -> None:
    source = (Path(gate.__file__)).read_text(encoding="utf-8")
    used = {name for name in dir(manifest) if name.startswith("REASON_") and name in source}
    emitted = {getattr(manifest, name) for name in used}
    assert emitted <= manifest.REASONS


def test_no_declared_reason_is_unreachable() -> None:
    """A name here that nothing can produce is a claim about a check that does not exist."""
    source = (Path(gate.__file__)).read_text(encoding="utf-8")
    for name in dir(manifest):
        if name.startswith("REASON_"):
            assert name in source, f"{name} is declared but the gate never emits it"


# ---------------------------------------------------------------------------
# How CI runs it
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow(repo_root: Path) -> str:
    """The quality workflow, read once."""
    return (repo_root / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")


def test_continuous_integration_runs_both_halves(workflow: str) -> None:
    assert "python -m tools.quality wheels" in workflow
    assert "python -m tools.quality.wheels probe" in workflow


def test_the_probe_runs_in_the_job_that_already_reaches_the_network(workflow: str) -> None:
    """One job declares the network dependency, rather than two.

    ``supply`` is described in that file as the only job that reaches anything
    outside the runner, and that sentence should stay true.
    """
    supply = workflow.split("  supply:", 1)[1].split("\n  evidence:", 1)[0]
    assert "python -m tools.quality.wheels probe" in supply
    assert "python -m tools.quality wheels" in supply


def test_the_probe_result_is_never_softened(workflow: str) -> None:
    """``continue-on-error: true``, ``|| true`` and ``exit 0`` are prohibited by name.

    A scanner that cannot fail is a scanner nobody has to fix. Spelled exactly as
    ``test_supply_contract.py`` spells them, so that the prohibition reads the same
    wherever it is asserted — and so that a comment *naming* the prohibition is not
    mistaken for an instance of it.
    """
    supply = workflow.split("  supply:", 1)[1].split("\n  evidence:", 1)[0]
    for mask in ("continue-on-error: true", "|| true", "exit 0"):
        assert mask not in supply


def test_the_survey_evidence_is_uploaded_from_exactly_one_path(workflow: str) -> None:
    """Two paths re-root the archive at their least common ancestor.

    Phase 015 broke the ``attest`` job that way, which is why this is asserted
    rather than remembered.
    """
    block = workflow.split("name: wheel-survey-evidence", 1)[1].split("- name:", 1)[0]
    assert block.count("path:") == 1
    assert ".globin/wheels/" in block


# ---------------------------------------------------------------------------
# The document that explains it
# ---------------------------------------------------------------------------


def test_the_document_names_every_surveyed_library(
    repo_root: Path, declaration: plan.Declaration
) -> None:
    """A reader should be able to find out why a library is in the survey.

    Not by reading the TOML, which is the machine's copy.
    """
    document = (repo_root / "docs" / "engineering" / "WHEEL_AVAILABILITY.md").read_text(
        encoding="utf-8"
    )
    for library in declaration.libraries:
        assert library.name in document


def test_the_survey_declares_the_schema_the_reader_implements(repo_root: Path) -> None:
    document = tomllib.loads((repo_root / plan.CONFIGURATION_FILE).read_text(encoding="utf-8"))
    assert document["schema"] == plan.SCHEMA
