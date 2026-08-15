"""The governance arrangement, asserted against this repository rather than a fixture.

``tests/integration/test_governance_end_to_end.py`` establishes that the gate
reaches the right verdict about *a* tree. This asserts the facts about *this*
one, and it lives at the contract level so that it runs inside the ordinary
suite — which means every ``full`` run and every pre-commit run gates on it,
without anybody remembering to invoke a separate command.

**Offline and read-only.** Nothing here starts a process or reaches the network.
Whether the platform's controls are actually switched on is a different question,
asked by the capability probe inside ``python -m tools.quality supply``.
"""

import tomllib
from pathlib import Path

import pytest

from tools.quality.commands import COMMANDS, find
from tools.quality.governance import plan
from tools.quality.governance.gate import with_directories
from tools.quality.supply.capability import CONTROLS, REQUIRED, State
from tools.quality.workflow.plan import load_configuration

REPOSITORY_OWNER = "@aydhn"
"""The only owner GitHub can resolve for this repository.

``aydhn`` owns it as a personal account rather than an organisation, so
``@org/team`` syntax cannot resolve and none is written. An owner GitHub cannot
resolve is ignored without an error, which turns a governance file into
decoration — so the spelling is asserted rather than trusted.
"""

SECURITY_DOCS: tuple[str, ...] = (
    "SECURITY.md",
    "docs/security/GOVERNANCE.md",
    "docs/security/SECURITY_BASELINE.md",
    "docs/security/VULNERABILITY_RESPONSE.md",
)

WORKFLOW_DIRECTORY = ".github/workflows"


@pytest.fixture(scope="module")
def declaration(repo_root: Path) -> plan.Declaration:
    """The declaration this repository actually carries."""
    return plan.parse_declaration((repo_root / plan.CONFIGURATION_FILE).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rules(repo_root: Path, declaration: plan.Declaration) -> tuple[plan.Rule, ...]:
    """The code-owner rules this repository actually carries."""
    return plan.parse_codeowners(
        (repo_root / declaration.locations.codeowners).read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# The files exist, and exactly one of them is the code-owners file
# ---------------------------------------------------------------------------


def test_every_declared_governing_file_exists(
    repo_root: Path, declaration: plan.Declaration
) -> None:
    missing = [
        relative
        for relative in declaration.locations.required_files()
        if not (repo_root / relative).is_file()
    ]
    assert not missing, f"declared in {plan.CONFIGURATION_FILE} and absent: {missing}"


def test_exactly_one_code_owners_file_exists_and_it_is_the_declared_one(
    repo_root: Path, declaration: plan.Declaration
) -> None:
    """GitHub reads the first candidate it finds rather than merging them.

    A second copy therefore silently overrides the first, and the file being
    ignored is the one somebody is maintaining.
    """
    present = [
        candidate
        for candidate in declaration.locations.codeowners_candidates
        if (repo_root / candidate).is_file()
    ]
    assert present == [declaration.locations.codeowners]


@pytest.mark.parametrize("relative", SECURITY_DOCS)
def test_each_security_document_is_substantive_and_committable(
    repo_root: Path, committable_files: tuple[str, ...], relative: str
) -> None:
    """A contract Git would not commit is invisible to every other contributor."""
    path = repo_root / relative
    assert path.is_file(), f"missing: {relative}"
    text = path.read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) >= 800, f"{relative} is too thin to be a policy"
    assert text.lstrip().startswith("# "), f"{relative} must open with a level-1 heading"
    assert relative in committable_files, f"{relative} is ignored by Git"


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------


def test_no_owner_is_invented(rules: tuple[plan.Rule, ...]) -> None:
    """A fabricated team reads as institutional rigour and resolves to nobody."""
    owners = {owner for rule in rules for owner in rule.owners}
    assert owners == {REPOSITORY_OWNER}
    assert not any("/" in owner for owner in owners), "a personal account has no teams"


def test_every_security_sensitive_path_is_specifically_owned(
    declaration: plan.Declaration, rules: tuple[plan.Rule, ...]
) -> None:
    """The catch-all already names the same owner, so matching only it asserts nothing.

    The specific entry is what survives the day a second maintainer makes the
    catch-all the wrong answer.
    """
    uncovered = plan.uncovered_sensitive_paths(declaration.sensitive_paths, rules)
    assert not uncovered, "\n  ".join(("uncovered sensitive paths:", *uncovered))


def test_every_workflow_is_specifically_owned(
    committable_files: tuple[str, ...], rules: tuple[plan.Rule, ...]
) -> None:
    """Adding a workflow is the most security-relevant change anybody makes here."""
    workflows = [path for path in committable_files if path.startswith(f"{WORKFLOW_DIRECTORY}/")]
    assert workflows, "the workflow directory is not empty, so finding nothing means the glob broke"
    assert not plan.ownerless(workflows, rules)


def test_no_code_owners_pattern_matches_nothing(
    committable_files: tuple[str, ...], rules: tuple[plan.Rule, ...]
) -> None:
    """A pattern owning nothing reads as coverage while providing none.

    It is how a CODEOWNERS file survives a directory rename looking correct.
    """
    problems = plan.unmatched_patterns(rules, with_directories(committable_files))
    assert not problems, "\n  ".join(("unreachable CODEOWNERS patterns:", *problems))


def test_every_declared_sensitive_path_still_exists(
    repo_root: Path, declaration: plan.Declaration
) -> None:
    """The drift that decays most quietly: an entry describing a tree that has moved on."""
    absent = [
        entry.path
        for entry in declaration.sensitive_paths
        if not (
            (repo_root / entry.path.rstrip("/")).is_dir()
            if entry.path.endswith("/")
            else (repo_root / entry.path).is_file()
        )
    ]
    assert not absent, f"declared security-sensitive and absent: {absent}"


def test_every_sensitive_path_states_why_it_is_sensitive(
    declaration: plan.Declaration,
) -> None:
    """An entry nobody justified is an entry nobody can argue with when it needs removing."""
    for entry in declaration.sensitive_paths:
        assert len(entry.reason) > 30, f"{entry.path} carries no real reason"
        assert entry.reason.endswith("."), f"{entry.path}'s reason is not a sentence"


def test_the_extension_points_deliberately_do_not_exist(
    repo_root: Path, declaration: plan.Declaration
) -> None:
    """Creating the directory early settles a later phase's design question by accident.

    Declaring the shape costs nothing; creating the path is the premature
    implementation ``AGENTS.md`` treats as a defect.
    """
    for entry in declaration.extension_points:
        assert entry.phase > 15, f"{entry.pattern} names a phase that is not later"
        found = list(repo_root.glob(entry.pattern))
        assert not found, f"{entry.pattern} already exists: {found}"


# ---------------------------------------------------------------------------
# The reporting channel
# ---------------------------------------------------------------------------


def test_the_security_policy_carries_every_required_section(
    repo_root: Path, declaration: plan.Declaration
) -> None:
    text = (repo_root / declaration.locations.security_policy).read_text(encoding="utf-8")
    missing = plan.missing_sections(text, declaration.security_policy_sections)
    assert not missing, f"{declaration.locations.security_policy} is missing: {list(missing)}"


def test_the_policy_and_the_issue_chooser_name_the_same_channel(
    repo_root: Path, declaration: plan.Declaration
) -> None:
    """Two of three files agreeing is the failure worth catching.

    A policy pointing one way and a chooser pointing another sends half the
    reports somewhere public, and neither file looks wrong on its own.
    """
    for relative in (
        declaration.locations.security_policy,
        declaration.locations.issue_template_config,
    ):
        text = (repo_root / relative).read_text(encoding="utf-8")
        assert declaration.reporting_url in text, f"{relative} does not name the declared channel"


def test_the_issue_chooser_forces_the_choice(
    repo_root: Path, declaration: plan.Declaration
) -> None:
    """With blank issues enabled the chooser is bypassable and the security link never shown."""
    text = (repo_root / declaration.locations.issue_template_config).read_text(encoding="utf-8")
    assert "blank_issues_enabled: false" in text


def test_no_public_issue_template_solicits_vulnerability_detail(
    repo_root: Path, declaration: plan.Declaration
) -> None:
    """The check the whole issue-template arrangement exists for.

    A public form collecting exploit detail publishes the vulnerability at the
    moment it is reported, which is worse than having no channel at all: a
    reporter with no channel writes privately, whereas one given a form uses it.
    """
    directory = repo_root / declaration.locations.issue_templates.rstrip("/")
    config = Path(declaration.locations.issue_template_config).name
    problems: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.name != config:
            problems.extend(
                plan.solicits_vulnerability_detail(path.name, path.read_text(encoding="utf-8"))
            )
    assert not problems, "\n  ".join(("public templates soliciting detail:", *problems))


def test_the_change_template_asks_about_security_impact(
    repo_root: Path, declaration: plan.Declaration
) -> None:
    text = (repo_root / declaration.locations.pull_request_template).read_text(encoding="utf-8")
    assert not plan.missing_sections(text, declaration.pull_request_sections)


# ---------------------------------------------------------------------------
# The controls decided by argument, and the ones decided by a setting
# ---------------------------------------------------------------------------


def test_every_declared_capability_uses_the_recorded_state_vocabulary(
    declaration: plan.Declaration,
) -> None:
    """A state outside ADR-0045's seven would be a vocabulary nobody agreed."""
    known = {state.value for state in State}
    for entry in declaration.declared_capabilities:
        assert entry.state in known, f"{entry.name} is {entry.state!r}"
        assert entry.reason, f"{entry.name} records no reason"
        assert entry.authority, f"{entry.name} names no deciding document"


def test_a_control_decided_by_argument_is_not_also_probed(
    declaration: plan.Declaration,
) -> None:
    """Two answers to one question is how they come to disagree.

    A control GitHub can answer belongs to the capability probe; one decided by
    an ADR belongs here. Nothing may be in both.
    """
    probed = {control.name for control in CONTROLS}
    declared = {entry.name for entry in declaration.declared_capabilities}
    assert not (probed & declared), f"asked twice: {sorted(probed & declared)}"


def test_the_reporting_channel_is_a_required_platform_control() -> None:
    """The policy names it, so a switched-off form must fail the gate rather than be recorded.

    Unlike the plan ceilings ADR-0045 was written for, this is a switch the
    repository's owner controls — which is exactly what makes ``FAIL`` the right
    reading if it is ever turned off again.
    """
    control = next(
        control for control in CONTROLS if control.name == "private_vulnerability_reporting"
    )
    assert control.policy == REQUIRED


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


def test_the_gate_is_registered_in_the_one_command_table() -> None:
    """Every check GLOBIN runs is a name in ``tools/quality/commands.py``, and only there."""
    command = find("governance")
    assert command is not None
    assert command.steps[0].argv == ("-m", "tools.quality.governance")


def test_the_gate_is_absent_from_fast_and_full() -> None:
    """It writes an artefact, and ``full`` reports rather than produces.

    What must gate a commit is this module, which the coverage step already runs.
    """
    for name in ("fast", "full"):
        command = find(name)
        assert command is not None
        assert all(step.name != "governance" for step in command.steps)


def test_the_gate_declares_no_module_because_it_launches_none() -> None:
    """Like ``aggregate``, its judgement starts no child, so no absent tool can hide a gate."""
    command = find("governance")
    assert command is not None
    assert command.steps[0].modules == ()


def test_the_command_table_and_this_repository_agree_on_the_required_check(
    repo_root: Path,
) -> None:
    """The name is read from ``pyproject.toml`` rather than copied into the declaration.

    A second copy is how a rename leaves a stale name behind in a file nobody
    thought to look at, so this asserts the declaration does *not* carry one.
    """
    required = load_configuration(repo_root).required_check
    assert required
    declared = tomllib.loads((repo_root / plan.CONFIGURATION_FILE).read_text(encoding="utf-8"))
    assert required not in repr(declared), (
        f"{plan.CONFIGURATION_FILE} carries a copy of the required check name; "
        f"it must be read from [tool.globin.workflow] instead"
    )


def test_the_command_summary_is_ascii_like_every_other() -> None:
    """Everything a gate prints must be ASCII — a Windows console cannot always do otherwise."""
    for command in COMMANDS:
        assert command.summary.isascii(), command.name
