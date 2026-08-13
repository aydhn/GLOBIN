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
    "docs/GIT_WORKFLOW.md",
    "docs/GLOSSARY.md",
    "docs/adr/README.md",
    "docs/research/phase_001_sources.md",
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
    "docs/GIT_WORKFLOW.md": ("master", "origin/master", "clean", "push"),
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
    """No TODO/TBD/FIXME spam. Unverified facts must name their owning phase."""
    offenders: list[str] = []
    for relative in REQUIRED_DOCS:
        text = _read(repo_root, relative)
        for marker in ("TODO", "TBD", "FIXME", "XXX", "Lorem ipsum"):
            if marker in text:
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
    assert len(adrs) >= 10, f"expected at least 10 ADRs, found {len(adrs)}"

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
# Research ledger
# --------------------------------------------------------------------------

SOURCE_HEADING_RE = re.compile(r"^### S-(\d{2}) — .+$", re.MULTILINE)


def test_research_ledger_has_structured_entries(repo_root: Path) -> None:
    text = _read(repo_root, "docs/research/phase_001_sources.md")
    headings = SOURCE_HEADING_RE.findall(text)
    assert len(headings) >= 12, f"expected at least 12 research sources, found {len(headings)}"
    assert len(set(headings)) == len(headings), "duplicate source identifiers in research ledger"

    for field in ("**Canonical location:**", "**Accessed:**", "**Authority:**", "**Implication"):
        assert text.count(field) >= len(headings), (
            f"every research entry must carry a {field} field"
        )
    assert text.count("https://") >= len(headings), "every research entry needs a canonical URL"


def test_research_ledger_records_access_dates(repo_root: Path) -> None:
    text = _read(repo_root, "docs/research/phase_001_sources.md")
    dates = re.findall(r"\*\*Accessed:\*\*\s*(\d{4}-\d{2}-\d{2})", text)
    assert len(dates) >= 12, f"expected at least 12 dated accesses, found {len(dates)}"
