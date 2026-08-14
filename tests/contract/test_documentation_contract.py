"""Verify that the living documentation exists, is substantive, and is consistent.

Deliberately *not* snapshot tests. Snapshotting Markdown makes every editorial
improvement a test failure, which trains contributors to update expectations
without reading them. These tests assert that each document exists, carries
real content, and states the policies it is responsible for — while leaving
authors free to improve the prose.
"""

import re
from pathlib import Path

import pytest

from tests.support import REPO_ROOT, markdown_prose

#: Documents that must exist for the engineering contract to be coherent.
REQUIRED_DOCS: tuple[str, ...] = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "MEMORY.md",
    "ROADMAP.md",
    "CONTRIBUTING.md",
    "docs/PROJECT_CHARTER.md",
    "docs/ARCHITECTURE_PRINCIPLES.md",
    "docs/SOURCE_POLICY.md",
    "docs/TESTING_STRATEGY.md",
    "docs/LOGGING_POLICY.md",
    "docs/CONFIGURATION_POLICY.md",
    "docs/GIT_WORKFLOW.md",
    "docs/GLOSSARY.md",
    "docs/architecture/README.md",
    "docs/architecture/SYSTEM_CONTEXT.md",
    "docs/architecture/CONTAINER.md",
    "docs/engineering/ENGINEERING_CONTRACT.md",
    "docs/engineering/DEFINITION_OF_DONE.md",
    "docs/engineering/SOURCE_OF_TRUTH.md",
    "docs/engineering/REPOSITORY_LAYOUT.md",
    "docs/engineering/DOCUMENTATION_STANDARD.md",
    "docs/engineering/QUALITY_GATES.md",
    "docs/engineering/STATIC_ANALYSIS.md",
    "docs/adr/README.md",
    "docs/adr/TEMPLATE.md",
    "docs/research/phase_001_sources.md",
    "docs/research/phase_002_sources.md",
    "docs/research/phase_003_sources.md",
    "docs/research/phase_004_sources.md",
    "docs/research/phase_005_sources.md",
    "docs/research/phase_006_sources.md",
    "docs/research/phase_007_sources.md",
)

#: Minimum byte length for a document to count as substantive rather than a
#: filename created to satisfy a checklist.
MIN_DOC_BYTES = 800

#: Concepts each document is responsible for stating. Case-insensitive
#: substring checks: robust to rewording, but they fail if a policy is dropped.
REQUIRED_CONCEPTS: dict[str, tuple[str, ...]] = {
    "README.md": ("GLOBIN", "Binance", "320", "not implemented", "master"),
    "AGENTS.md": ("master", "scrap", "credential", "test", "push"),
    "CLAUDE.md": ("AGENTS.md", "master", "phase"),
    "MEMORY.md": ("GLOBIN", "master", "320", "Binance", "zero-budget"),
    "CONTRIBUTING.md": ("master", "pytest", "ruff", "mypy"),
    "docs/PROJECT_CHARTER.md": ("Binance", "zero-budget", "non-goal", "320"),
    "docs/ARCHITECTURE_PRINCIPLES.md": (
        "capability",
        "environment",
        "rate limit",
        "reconcil",
        "risk",
        "probabilistic",
        "GPU",
    ),
    "docs/SOURCE_POLICY.md": ("scrap", "official", "Binance", "authoritative"),
    "docs/TESTING_STRATEGY.md": ("pytest", "invariant", "leakage"),
    "docs/LOGGING_POLICY.md": (
        "correlation",
        "redact",
        "severity",
        "structured",
        "JSON",
    ),
    "docs/CONFIGURATION_POLICY.md": (
        "setting",
        "precedence",
        "default",
        "origin",
        "refus",
    ),
    "docs/GIT_WORKFLOW.md": ("master", "origin/master", "clean", "push"),
    "docs/engineering/ENGINEERING_CONTRACT.md": (
        "fail closed",
        "determinism",
        "idempot",
        "leakage",
        "timezone",
        "secret",
    ),
    "docs/engineering/DEFINITION_OF_DONE.md": (
        "master",
        "origin/master",
        "porcelain",
        "credential",
        "placeholder",
    ),
    "docs/engineering/SOURCE_OF_TRUTH.md": (
        "authority",
        "conflict",
        "pyproject.toml",
        "adr",
    ),
    "docs/engineering/REPOSITORY_LAYOUT.md": (
        "src/globin",
        "docs/adr",
        "docs/research",
        ".gitignore",
    ),
    "docs/engineering/DOCUMENTATION_STANDARD.md": (
        "review",
        "british",
        "guarantee",
        "adr",
        "relative link",
    ),
    "docs/engineering/QUALITY_GATES.md": (
        "exit code",
        "coverage",
        "branch",
        "least privilege",
        "pre-commit",
        "deferred",
    ),
    "docs/engineering/STATIC_ANALYSIS.md": (
        "ruff",
        "mypy",
        "noqa",
        "type: ignore",
        "exception",
    ),
    "docs/adr/TEMPLATE.md": (
        "## status",
        "## context",
        "## decision",
        "## consequences",
        "## alternatives considered",
        "## risks and trade-offs",
        "## references",
        "## supersedes",
        "## superseded by",
        "rejected",
    ),
    "docs/architecture/README.md": (
        "domain",
        "ports",
        "adapters",
        "runtime",
        "composition root",
        "inward",
        "import",
        "secret",
    ),
    "docs/architecture/SYSTEM_CONTEXT.md": (
        "operator",
        "binance",
        "telegram",
        "trust boundar",
        "windows",
    ),
    "docs/architecture/CONTAINER.md": (
        "container",
        "docker",
        "python",
        "monolith",
    ),
}

#: Command-shaped references to a branch that would contradict the master-only
#: rule. Matching on the bare word "main" would be useless (it appears inside
#: "maintain", "domain", "remaining"), so only command forms are forbidden.
FORBIDDEN_BRANCH_PATTERNS: tuple[str, ...] = (
    r"origin/main\b",
    r"upstream/main\b",
    r"git\s+checkout\s+main\b",
    r"git\s+switch\s+main\b",
    r"git\s+merge\s+main\b",
    r"git\s+rebase\s+main\b",
    r"git\s+pull\s+\S+\s+main\b",
    r"git\s+push\s+\S+\s+main\b",
    r"git\s+branch\s+main\b",
    r"--branch[= ]main\b",
    r"-b\s+main\b",
)

#: Documents that carry Git authority and must never contain the above.
GIT_AUTHORITATIVE_DOCS: tuple[str, ...] = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "MEMORY.md",
    "CONTRIBUTING.md",
    "docs/GIT_WORKFLOW.md",
    "docs/adr/0005-master-only-git-workflow.md",
)


def _read(repo_root: Path, relative: str) -> str:
    return (repo_root / relative).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Existence and substance
# --------------------------------------------------------------------------


@pytest.mark.parametrize("relative", REQUIRED_DOCS)
def test_required_document_exists(repo_root: Path, relative: str) -> None:
    assert (repo_root / relative).is_file(), f"missing required document: {relative}"


@pytest.mark.parametrize("relative", REQUIRED_DOCS)
def test_required_document_is_substantive(repo_root: Path, relative: str) -> None:
    """Guard against empty files created only to satisfy a filename checklist."""
    text = _read(repo_root, relative)
    assert len(text.encode("utf-8")) >= MIN_DOC_BYTES, (
        f"{relative} is only {len(text.encode('utf-8'))} bytes; expected at least {MIN_DOC_BYTES}"
    )
    assert text.lstrip().startswith("# "), f"{relative} must open with a level-1 heading"


@pytest.mark.parametrize(("relative", "concepts"), list(REQUIRED_CONCEPTS.items()))
def test_document_states_its_required_concepts(
    repo_root: Path, relative: str, concepts: tuple[str, ...]
) -> None:
    text = _read(repo_root, relative).lower()
    missing = [concept for concept in concepts if concept.lower() not in text]
    assert not missing, f"{relative} does not mention: {missing}"


def test_no_placeholder_debt_in_required_docs(repo_root: Path) -> None:
    """No TODO/TBD/FIXME spam. Unverified facts must name their owning phase.

    Prose only. Several of these documents *prohibit* placeholder markers and
    therefore have to name them; a marker quoted in backticks is the opposite of
    one left behind.
    """
    offenders: list[str] = []
    for relative in REQUIRED_DOCS:
        prose = markdown_prose(_read(repo_root, relative))
        for marker in ("TODO", "TBD", "FIXME", "XXX", "Lorem ipsum"):
            if marker in prose:
                offenders.append(f"{relative}: {marker}")
    assert not offenders, f"placeholder debt found: {offenders}"


# --------------------------------------------------------------------------
# Branch policy consistency
# --------------------------------------------------------------------------


@pytest.mark.parametrize("relative", GIT_AUTHORITATIVE_DOCS)
def test_no_conflicting_branch_instruction(repo_root: Path, relative: str) -> None:
    """Authoritative Git docs must not carry an instruction contradicting master-only."""
    text = _read(repo_root, relative)
    hits = [
        pattern
        for pattern in FORBIDDEN_BRANCH_PATTERNS
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    assert not hits, f"{relative} contains branch instructions conflicting with master-only: {hits}"


def test_git_workflow_positively_requires_master(repo_root: Path) -> None:
    text = _read(repo_root, "docs/GIT_WORKFLOW.md")
    assert "origin/master" in text
    assert re.search(r"git\s+push\s+origin\s+master", text), (
        "GIT_WORKFLOW.md must show the canonical push command"
    )


# --------------------------------------------------------------------------
# Architecture Decision Records
# --------------------------------------------------------------------------


def test_adr_set_is_complete_and_well_formed(repo_root: Path) -> None:
    adr_dir = repo_root / "docs" / "adr"
    adrs = sorted(p for p in adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert len(adrs) >= 15, f"expected at least 15 ADRs, found {len(adrs)}"

    numbers = [int(p.name[:4]) for p in adrs]
    assert len(set(numbers)) == len(numbers), f"duplicate ADR numbers: {numbers}"
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"ADR numbering must be contiguous from 0001, found {numbers}"
    )

    for adr in adrs:
        text = adr.read_text(encoding="utf-8")
        for section in ("## Status", "## Context", "## Decision", "## Consequences"):
            assert section in text, f"{adr.name} is missing section {section}"


def test_adr_index_references_every_adr(repo_root: Path) -> None:
    adr_dir = repo_root / "docs" / "adr"
    index = (adr_dir / "README.md").read_text(encoding="utf-8")
    for adr in sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md")):
        assert adr.name in index, f"ADR index does not reference {adr.name}"


# --------------------------------------------------------------------------
# ADR lifecycle
#
# An ADR set is only worth consulting if its states are trustworthy. A record
# claiming to be Accepted while a later one has replaced it is worse than no
# record, because it is confidently wrong. These checks are what let the
# supersession procedure in `docs/adr/README.md` be a rule rather than a hope.
# --------------------------------------------------------------------------

#: Permitted `## Status` openings. `Superseded` is matched by prefix because the
#: full form names the replacing record, as in `Superseded by ADR-0020`.
ADR_STATUS_VALUES: tuple[str, ...] = (
    "Proposed",
    "Accepted",
    "Rejected",
    "Deprecated",
    "Superseded",
)

#: First ADR written against the extended template. Records below this predate
#: the lifecycle sections, are Accepted, and are therefore immutable — see
#: ADR-0012 and `docs/adr/README.md`. Retrofitting them would rewrite decision
#: history to satisfy a test, which is the wrong way round.
ADR_LIFECYCLE_FLOOR = 12

ADR_LIFECYCLE_SECTIONS: tuple[str, ...] = (
    "## Alternatives Considered",
    "## Risks and Trade-offs",
    "## References",
    "## Supersedes",
    "## Superseded By",
)

#: One row of the index table: `| [0011](0011-....md) | Title | Accepted |`.
ADR_INDEX_ROW_RE = re.compile(
    r"^\|\s*\[(?P<number>\d{4})\]\([^)]+\)\s*\|[^|]*\|\s*(?P<status>[^|]+?)\s*\|\s*$",
    re.MULTILINE,
)


def _adr_paths(repo_root: Path) -> list[Path]:
    return sorted((repo_root / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md"))


def _adr_section(text: str, heading: str) -> str:
    """Return the body under ``heading``, stopping at the next level-2 heading."""
    _, _, after = text.partition(f"{heading}\n")
    body, _, _ = after.partition("\n## ")
    return body.strip()


def _adr_status(text: str) -> str:
    """Return the first non-empty line of the `## Status` section."""
    section = _adr_section(text, "## Status")
    for line in section.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _referenced_adr_numbers(section: str) -> set[int]:
    """Return every ADR number a section names, by `ADR-NNNN` or by file link."""
    return {int(number) for number in re.findall(r"ADR-(\d{4})", section)} | {
        int(number) for number in re.findall(r"\((\d{4})-[a-z0-9-]+\.md\)", section)
    }


def test_adr_section_parsing_reads_only_the_section_asked_for() -> None:
    """Guard the helpers below: a parser that silently matches nothing passes everything."""
    text = "# T\n\n## Status\n\nAccepted — Phase 002.\n\n## Supersedes\n\nADR-0007\n\n## X\n\nno\n"
    assert _adr_status(text) == "Accepted — Phase 002."
    assert _adr_section(text, "## Supersedes") == "ADR-0007"
    assert _referenced_adr_numbers("ADR-0007") == {7}
    assert _referenced_adr_numbers("[0009](0009-windows-bat-launchers.md)") == {9}
    assert _referenced_adr_numbers("None") == set()


def test_every_adr_states_a_status_from_the_known_vocabulary(repo_root: Path) -> None:
    offenders = [
        f"{adr.name}: {_adr_status(adr.read_text(encoding='utf-8'))!r}"
        for adr in _adr_paths(repo_root)
        if not _adr_status(adr.read_text(encoding="utf-8")).startswith(ADR_STATUS_VALUES)
    ]
    assert not offenders, f"ADRs with an unrecognised status: {offenders}"


def test_adrs_written_against_the_current_template_carry_every_section(
    repo_root: Path,
) -> None:
    recent = [adr for adr in _adr_paths(repo_root) if int(adr.name[:4]) >= ADR_LIFECYCLE_FLOOR]
    assert recent, f"no ADR at or above {ADR_LIFECYCLE_FLOOR:04d}; this check would be vacuous"

    missing = [
        f"{adr.name}: {section}"
        for adr in recent
        for section in ADR_LIFECYCLE_SECTIONS
        if section not in adr.read_text(encoding="utf-8")
    ]
    assert not missing, f"ADRs missing required sections: {missing}"


def test_superseding_adrs_and_their_predecessors_agree(repo_root: Path) -> None:
    """Supersession must be recorded on both records, or the log is inconsistent.

    Currently no record supersedes another, so this asserts nothing about the
    present set. It exists so that the first supersession cannot be delivered
    half-finished, which is exactly when the mistake is easy to make.
    """
    texts = {int(adr.name[:4]): adr.read_text(encoding="utf-8") for adr in _adr_paths(repo_root)}
    problems: list[str] = []
    for number, text in texts.items():
        for replaced in _referenced_adr_numbers(_adr_section(text, "## Supersedes")):
            if replaced not in texts:
                problems.append(
                    f"ADR-{number:04d} supersedes ADR-{replaced:04d}, which does not exist"
                )
                continue
            older = texts[replaced]
            if not _adr_status(older).startswith("Superseded"):
                problems.append(
                    f"ADR-{replaced:04d} is superseded by ADR-{number:04d} "
                    f"but its status is {_adr_status(older)!r}"
                )
            if number not in _referenced_adr_numbers(_adr_section(older, "## Superseded By")):
                problems.append(
                    f"ADR-{replaced:04d} does not name ADR-{number:04d} under `Superseded By`"
                )
    assert not problems, "inconsistent supersession:\n  " + "\n  ".join(problems)


def test_the_adr_index_status_matches_each_record(repo_root: Path) -> None:
    """A stale status in the index is the copy a reader is most likely to trust."""
    index = (repo_root / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
    listed = {
        int(match.group("number")): match.group("status")
        for match in ADR_INDEX_ROW_RE.finditer(index)
    }
    assert listed, "no ADR rows parsed from the index table"

    mismatched: list[str] = []
    for adr in _adr_paths(repo_root):
        number = int(adr.name[:4])
        status = _adr_status(adr.read_text(encoding="utf-8"))
        if number not in listed:
            mismatched.append(f"ADR-{number:04d} has no index row")
        elif not status.startswith(listed[number]):
            mismatched.append(
                f"ADR-{number:04d}: index says {listed[number]!r}, record says {status!r}"
            )
    assert not mismatched, f"index and records disagree: {mismatched}"


# --------------------------------------------------------------------------
# Research ledger
# --------------------------------------------------------------------------

SOURCE_HEADING_RE = re.compile(r"^### S-(\d{2}) — .+$", re.MULTILINE)

#: Every per-phase ledger present in the repository, discovered rather than
#: listed, so a new phase's ledger is checked the moment it is written.
RESEARCH_LEDGERS: tuple[str, ...] = tuple(
    sorted(f"docs/research/{path.name}" for path in (REPO_ROOT / "docs" / "research").glob("*.md"))
)


def test_research_ledgers_are_discovered() -> None:
    """Guard the discovery above: an empty glob would make the checks below vacuous."""
    assert len(RESEARCH_LEDGERS) >= 2, (
        f"expected a ledger per completed phase, found {RESEARCH_LEDGERS}"
    )


@pytest.mark.parametrize("relative", RESEARCH_LEDGERS)
def test_research_ledger_entries_are_well_formed(repo_root: Path, relative: str) -> None:
    """Every source entry carries a location, an access date and an authority assessment.

    Structure is asserted per entry; the *number* of entries is not. A
    governance phase legitimately relies on fewer external facts than an
    integration phase, and a minimum count would be satisfied by padding —
    which turns the ledger into decoration.
    """
    text = _read(repo_root, relative)
    headings = SOURCE_HEADING_RE.findall(text)
    assert headings, f"{relative} contains no `### S-NN — ...` entries"
    assert len(set(headings)) == len(headings), f"duplicate source identifiers in {relative}"

    for field in ("**Canonical location:**", "**Accessed:**", "**Authority:**", "**Implication"):
        assert text.count(field) >= len(headings), (
            f"every entry in {relative} must carry a {field} field"
        )
    assert text.count("https://") >= len(headings), f"every entry in {relative} needs a URL"

    dates = re.findall(r"\*\*Accessed:\*\*\s*(\d{4}-\d{2}-\d{2})", text)
    assert len(dates) >= len(headings), (
        f"{relative} has {len(headings)} entries but {len(dates)} ISO access dates"
    )


def test_phase_001_ledger_remains_comprehensive(repo_root: Path) -> None:
    """Phase 001 established the architecture from twelve primary sources.

    Specific to that ledger, not a general rule: it is the evidence base the
    charter and the ADR set rest on, and thinning it would quietly weaken them.
    """
    text = _read(repo_root, "docs/research/phase_001_sources.md")
    headings = SOURCE_HEADING_RE.findall(text)
    assert len(headings) >= 12, f"expected at least 12 research sources, found {len(headings)}"
