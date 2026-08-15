"""The release arrangement, asserted against this repository.

Where ``tests/integration/test_release_end_to_end.py`` runs the gate over trees
built for the occasion, this module asserts facts about **this** repository: that
the declaration parses, that the prose matrix and the machine-readable one agree
in both directions, and that the gate stayed the kind of thing it was added as.

**ADR-0032 is deliberately not invoked here.** That record governs verification
tooling added in a phase that does not name it, and release governance is Phase
016's own scope — so the six conditions do not apply as a licence. Four of them
are still worth holding as invariants, and are asserted below on their own
merits: no dependency added, no runtime capability added, the gate only reports,
and it is documented and tested to the same standard as everything else.
"""

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from globin.project_contract import REQUIRED_GIT_BRANCH
from tools.quality.commands import COMMANDS, MUTATING_COMMANDS, find
from tools.quality.release import assets, gate, manifest
from tools.quality.release.plan import CATEGORIES, CONFIGURATION_FILE, Status, parse_declaration
from tools.quality.release.plan import category_letter as letter_for

#: A criterion row in the prose matrix:
#: ``| `FND-A-01` | A requirement. | yes | `PASS` |``
CRITERION_ROW_RE = re.compile(
    r"^\|\s*`(?P<id>FND-[A-P]-\d{2})`\s*\|\s*(?P<requirement>[^|]+?)\s*\|"
    r"\s*(?P<blocking>yes|no)\s*\|\s*`(?P<status>[A-Z_]+)`\s*\|",
    re.MULTILINE,
)

#: The headline counts: ``| `PASS` | 53 |``
COUNT_ROW_RE = re.compile(r"^\|\s*`(?P<status>[A-Z_]+)`\s*\|\s*(?P<count>\d+)\s*\|", re.MULTILINE)

#: The sentence stating the size of the matrix.
TOTAL_RE = re.compile(
    r"\*\*(?P<total>\d+) criteria across sixteen categories\. (?P<blocking>\d+) are blocking\.\*\*"
)

ACCEPTANCE_DOCUMENT = "docs/release/FOUNDATION_ACCEPTANCE.md"
POLICY_DOCUMENT = "docs/release/RELEASE_POLICY.md"


@pytest.fixture(scope="module")
def declaration(repo_root: Path) -> Any:
    """The real acceptance declaration, parsed."""
    return parse_declaration((repo_root / CONFIGURATION_FILE).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def acceptance(repo_root: Path) -> str:
    """The prose matrix."""
    return (repo_root / ACCEPTANCE_DOCUMENT).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pyproject(repo_root: Path) -> dict[str, Any]:
    """The project's configuration."""
    with (repo_root / "pyproject.toml").open("rb") as handle:
        data: dict[str, Any] = tomllib.load(handle)
    return data


# ---------------------------------------------------------------------------
# Guard the guard
# ---------------------------------------------------------------------------


def test_the_criterion_row_reader_finds_its_own_failing_case() -> None:
    """A reader returning nothing would pass every comparison below."""
    document = "\n".join(
        [
            "| ID | Requirement | Blocking | Status |",
            "|---|---|---|---|",
            "| `FND-A-01` | Identity is executable. | yes | `PASS` |",
            "| `FND-P-05` | Signing is recorded. | no | `BLOCKED` |",
            "| not a row | x | y | z |",
        ]
    )
    rows = [match.groupdict() for match in CRITERION_ROW_RE.finditer(document)]
    assert [row["id"] for row in rows] == ["FND-A-01", "FND-P-05"]
    assert rows[0]["blocking"] == "yes"
    assert rows[1]["status"] == "BLOCKED"
    assert CRITERION_ROW_RE.search("| `FND-Z-01` | x | yes | `PASS` |") is None


def test_the_count_reader_finds_its_own_failing_case() -> None:
    assert COUNT_ROW_RE.search("| `PASS` | 53 |").group("count") == "53"  # type: ignore[union-attr]
    assert COUNT_ROW_RE.search("| PASS | 53 |") is None


# ---------------------------------------------------------------------------
# The declaration itself
# ---------------------------------------------------------------------------


def test_the_declaration_parses(declaration: Any) -> None:
    assert declaration.criteria


def test_every_category_carries_at_least_one_criterion(declaration: Any) -> None:
    """A category with no criteria claims coverage the matrix does not have."""
    used = {criterion.category for criterion in declaration.criteria}
    assert used == set(CATEGORIES), f"categories with no criteria: {sorted(set(CATEGORIES) - used)}"


def test_every_identifier_is_unique_and_matches_its_category(declaration: Any) -> None:
    identifiers = [criterion.identifier for criterion in declaration.criteria]
    assert len(identifiers) == len(set(identifiers))
    for criterion in declaration.criteria:
        expected = f"FND-{letter_for(criterion.category)}-"
        assert criterion.identifier.startswith(expected), (
            f"{criterion.identifier} is filed under {criterion.category!r}"
        )


def test_every_criterion_names_evidence_that_exists(repo_root: Path, declaration: Any) -> None:
    """The half of the matrix a machine can hold to account.

    The statuses are a human judgement; that each names something real is checkable, and
    checked.
    """
    missing = [
        f"{criterion.identifier} -> {relative}"
        for criterion in declaration.criteria
        for relative in criterion.evidence
        if not (repo_root / relative).exists()
    ]
    assert not missing, f"criteria naming evidence that does not exist: {missing}"


def test_every_criterion_is_answered_by_evidence_or_a_command(declaration: Any) -> None:
    unbacked = [
        criterion.identifier
        for criterion in declaration.criteria
        if not criterion.evidence and not criterion.command.strip()
    ]
    assert not unbacked, f"criteria answered by nothing: {unbacked}"


def test_every_blocking_criterion_passes(declaration: Any) -> None:
    """The assertion the whole phase turns on.

    A blocking criterion that is not PASS means the foundation is not certified, whatever the
    documents say.
    """
    unmet = [
        f"{criterion.identifier} is {criterion.status}"
        for criterion in declaration.criteria
        if criterion.blocking and criterion.status is not Status.PASS
    ]
    assert not unmet, f"blocking criteria that did not pass: {unmet}"


def test_the_declared_version_source_is_the_one_hatchling_reads(
    declaration: Any, pyproject: dict[str, Any]
) -> None:
    """Two declarations of one fact, compared.

    Otherwise the gate could check a version the build backend never reads.
    """
    assert declaration.version_source == pyproject["tool"]["hatch"]["version"]["path"]


def test_the_declared_documents_exist(repo_root: Path, declaration: Any) -> None:
    for relative in declaration.documents():
        assert (repo_root / relative).is_file(), f"{relative} is declared and absent"


# ---------------------------------------------------------------------------
# The prose matrix and the declaration agree
# ---------------------------------------------------------------------------


def test_the_document_lists_every_declared_criterion(acceptance: str, declaration: Any) -> None:
    documented = {match.group("id") for match in CRITERION_ROW_RE.finditer(acceptance)}
    declared = {criterion.identifier for criterion in declaration.criteria}
    assert declared - documented == set(), (
        f"declared but absent from {ACCEPTANCE_DOCUMENT}: {sorted(declared - documented)}"
    )


def test_the_document_invents_no_criterion(acceptance: str, declaration: Any) -> None:
    """A row the reader sees and the gate never reads enforces nothing."""
    documented = {match.group("id") for match in CRITERION_ROW_RE.finditer(acceptance)}
    declared = {criterion.identifier for criterion in declaration.criteria}
    assert documented - declared == set(), (
        f"documented but not declared: {sorted(documented - declared)}"
    )


def test_each_documented_row_states_the_declared_status_and_blocking_flag(
    acceptance: str, declaration: Any
) -> None:
    by_id = {criterion.identifier: criterion for criterion in declaration.criteria}
    for match in CRITERION_ROW_RE.finditer(acceptance):
        criterion = by_id[match.group("id")]
        assert match.group("status") == criterion.status.value, (
            f"{criterion.identifier}: document says {match.group('status')}, "
            f"declaration says {criterion.status.value}"
        )
        documented = match.group("blocking") == "yes"
        assert documented == criterion.blocking, (
            f"{criterion.identifier}: document says blocking={documented}, "
            f"declaration says {criterion.blocking}"
        )


def test_each_documented_row_states_the_declared_requirement(
    acceptance: str, declaration: Any
) -> None:
    by_id = {criterion.identifier: criterion for criterion in declaration.criteria}
    for match in CRITERION_ROW_RE.finditer(acceptance):
        criterion = by_id[match.group("id")]
        assert match.group("requirement") == criterion.requirement.strip(), (
            f"{criterion.identifier}: the document and the declaration word the "
            f"requirement differently"
        )


def test_the_headline_totals_match_the_declaration(acceptance: str, declaration: Any) -> None:
    """A hand-maintained number is a number that goes stale.

    The regular expression failing to match is itself a failure, so removing the claim to avoid
    maintaining it is not available without editing this test.
    """
    stated = TOTAL_RE.search(acceptance)
    assert stated is not None, f"{ACCEPTANCE_DOCUMENT} no longer states how many criteria exist"
    assert int(stated.group("total")) == len(declaration.criteria)
    assert int(stated.group("blocking")) == sum(
        1 for criterion in declaration.criteria if criterion.blocking
    )


def test_the_status_counts_match_the_declaration(acceptance: str, declaration: Any) -> None:
    section = acceptance[acceptance.index("## Result") : acceptance.index("## The matrix")]
    documented = {
        match.group("status"): int(match.group("count")) for match in COUNT_ROW_RE.finditer(section)
    }
    actual = {status.value: 0 for status in Status}
    for criterion in declaration.criteria:
        actual[criterion.status.value] += 1
    assert documented == actual


def test_the_document_names_every_category_the_code_declares(acceptance: str) -> None:
    """Sixteen categories, and the document is where a reader learns what they are.

    One missing would be a group nobody reviewing the matrix looks for.
    """
    for category in CATEGORIES:
        expected = f"### {letter_for(category)} — "
        assert expected in acceptance, f"{ACCEPTANCE_DOCUMENT} has no section for {category!r}"


# ---------------------------------------------------------------------------
# The gate stayed the kind of thing it was added as
# ---------------------------------------------------------------------------


def test_the_release_gate_is_reachable_exactly_one_way() -> None:
    command = find("release")
    assert command is not None, "the release gate is not in the command table"
    assert len(command.steps) == 1
    assert command.steps[0].argv == ("-m", "tools.quality.release")


def test_the_release_gate_adds_no_dependency(pyproject: dict[str, Any]) -> None:
    """The toolchain three contract tests pin stays the size it was.

    The gate uses the standard library and this repository's own modules.
    """
    command = find("release")
    assert command is not None
    assert command.steps[0].modules == ()
    assert len(pyproject["project"]["optional-dependencies"]["dev"]) == 7


def test_the_release_gate_adds_no_runtime_capability(repo_root: Path) -> None:
    """Tooling verifies; it does not participate.

    Nothing under src/globin/ may import it, and the layer contract would not catch this because
    tools/ is outside the layer stack entirely.
    """
    offenders = [
        str(path.relative_to(repo_root))
        for path in (repo_root / "src" / "globin").rglob("*.py")
        if "tools.quality" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"the package imports the tooling: {offenders}"


def test_the_release_gate_only_reports() -> None:
    """Absent from `fast` and `full`, and not a mutating command."""
    assert "release" not in MUTATING_COMMANDS
    for name in ("fast", "full"):
        command = find(name)
        assert command is not None
        assert "release" not in {step.name for step in command.steps}


def test_the_release_gate_writes_only_under_the_ignored_root(repo_root: Path) -> None:
    """Its artefacts are regenerable, so none is committed.

    What is published is a copy attached to a release.
    """
    assert gate.OUTPUT_DIRECTORY.startswith(".globin/")
    ignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
    assert ".globin/" in ignore.splitlines()


def test_the_release_command_appears_once_in_the_table() -> None:
    assert [command.name for command in COMMANDS].count("release") == 1


# ---------------------------------------------------------------------------
# Vocabularies, and the constants that must not drift
# ---------------------------------------------------------------------------


def test_the_release_branch_is_the_project_contract_branch() -> None:
    """Two spellings of one fact.

    The contract is the authority; this constant exists so the gate does not import the package,
    and must not drift from it.
    """
    assert gate.RELEASE_BRANCH == REQUIRED_GIT_BRANCH


def test_every_reason_the_gate_can_emit_is_declared() -> None:
    """The closed set.

    A new failure mode must not arrive with an undeclared name, because a reason code is what a
    machine reads.
    """
    source = Path(gate.__file__).read_text(encoding="utf-8")
    emitted = set(re.findall(r"REASON_[A-Z_]+", source))
    declared = {name for name in dir(manifest) if name.startswith("REASON_")}
    assert emitted <= declared, (
        f"the gate names reasons the manifest does not declare: {sorted(emitted - declared)}"
    )
    for name in emitted:
        assert getattr(manifest, name) in manifest.REASONS


def test_the_signing_vocabulary_is_closed_and_never_claims_a_signature() -> None:
    """The gate reads a configuration file.

    That can say a host could sign; only a verification says a tag was signed, so the verified
    state is never set here.
    """
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "return SIGNING_SIGNED" not in source
    assert manifest.SIGNING_SIGNED in manifest.SIGNING_STATES


def test_the_published_assets_are_named_in_the_policy(repo_root: Path) -> None:
    """A release's contents must be learnable from the policy, not the code."""
    policy = (repo_root / POLICY_DOCUMENT).read_text(encoding="utf-8")
    for name in assets.published_names():
        assert name in policy, f"{POLICY_DOCUMENT} does not name the asset {name!r}"


def test_the_policy_keeps_the_release_mechanisms_distinct(repo_root: Path) -> None:
    """Annotation, signature, immutability and attestation must not blur."""
    policy = (repo_root / POLICY_DOCUMENT).read_text(encoding="utf-8")
    for claim in (
        "Tag annotation",
        "Tag signature",
        "Release immutability",
        "Release attestation",
    ):
        assert claim in policy, f"{POLICY_DOCUMENT} no longer distinguishes {claim!r}"
    assert "not safety" in policy or "not prove safety" in policy
