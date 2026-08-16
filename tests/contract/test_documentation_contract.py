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

from tests.support import REPO_ROOT, markdown_prose, markdown_section, parse_roadmap
from tools.quality.commands import command_names

#: Documents carrying a "what this does not cover" table of the form
#: ``| Question | Phase |``. Found by their header rather than listed by hand
#: would be neater, but a list that a test compares against the tree is how a new
#: policy document silently escapes the check below.
DEFERRAL_TABLES: tuple[str, ...] = (
    "docs/CONFIGURATION_POLICY.md",
    "docs/IDENTIFIER_POLICY.md",
    "docs/PRECISION_POLICY.md",
    "docs/VALUE_TYPES_POLICY.md",
    # Added in Phase 020. This one is not merely tidy: the secret store contract
    # constrains five phases that have not started, and almost nothing in it can
    # be checked by a gate until they do. The deferral table is what makes time
    # do the enforcing -- the day any of those phases ships, this fails and the
    # document has to be reconciled in the same commit.
    "docs/security/SECRET_STORE_CONTRACT.md",
)

#: A row of one of those tables: a question, then the phase or phases owning it.
DEFERRAL_ROW_RE: re.Pattern[str] = re.compile(
    r"^\|\s*(?P<question>[^|]+?)\s*\|\s*(?P<owner>[^|]+?)\s*\|\s*$", re.MULTILINE
)

#: A three-digit phase number inside an owner cell. Ranges such as ``021-032``
#: yield both ends, which is what should be checked: a range whose end has
#: delivered is as stale as a single number that has.
PHASE_IN_OWNER_RE: re.Pattern[str] = re.compile(r"\b(\d{3})\b")

#: What an owner cell says when the phase named has already delivered. The
#: convention already existed in two of these documents and was applied
#: inconsistently, which is the defect this check exists to stop recurring.
DELIVERED: str = "delivered"

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
    "docs/VALUE_TYPES_POLICY.md",
    "docs/TIME_POLICY.md",
    "docs/PRECISION_POLICY.md",
    "docs/IDENTIFIER_POLICY.md",
    "docs/SERIALIZATION_POLICY.md",
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
    "docs/engineering/CI_SECURITY.md",
    "docs/adr/README.md",
    "docs/adr/TEMPLATE.md",
    "docs/research/phase_001_sources.md",
    "docs/research/phase_002_sources.md",
    "docs/research/phase_003_sources.md",
    "docs/research/phase_004_sources.md",
    "docs/research/phase_005_sources.md",
    "docs/research/phase_006_sources.md",
    "docs/research/phase_007_sources.md",
    "docs/research/phase_008_sources.md",
    "docs/research/phase_009_sources.md",
    "docs/research/phase_010_sources.md",
    "docs/research/phase_011_sources.md",
    "docs/research/phase_012_sources.md",
    "docs/research/phase_013_sources.md",
    # Phase 014's ledger existed and was never added here, so nothing required
    # it. Added in Phase 015 alongside its own, which is the edit MEMORY.md
    # names as the third a phase adding a ledger must make.
    "docs/research/phase_014_sources.md",
    "docs/research/phase_015_sources.md",
    "docs/research/phase_016_sources.md",
    "docs/research/phase_017_sources.md",
    "docs/research/phase_018_sources.md",
    "docs/research/phase_019_sources.md",
    "docs/research/phase_020_sources.md",
    # Added in Phase 020 with the locking it describes and the store contract it
    # establishes the limits for.
    "docs/engineering/DEPENDENCY_LOCKING.md",
    "docs/security/SECRET_STORE_CONTRACT.md",
    # Added in Phase 016 with the release governance they carry. The changelog is
    # deliberately not here: it is required by the release gate, which checks the
    # version it announces rather than only that it exists.
    "docs/release/RELEASE_POLICY.md",
    "docs/release/FOUNDATION_ACCEPTANCE.md",
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
    "docs/engineering/DEPENDENCY_LOCKING.md": (
        "pylock",
        "pep 751",
        "hash",
        "relock",
        "upgrade",
        "--locked",
        "transitive",
    ),
    # Chosen so that dropping a *section* fails, rather than pinning prose. The
    # constant name rather than the number: 2560 is arithmetic somebody could
    # restate, and a number in prose would need a source to compare against that
    # this repository does not hold.
    "docs/security/SECRET_STORE_CONTRACT.md": (
        "reference",
        "builder",
        "fails closed",
        "rotation",
        "logon session",
        "cred_max_credential_blob_size",
        "echo",
        "canary",
        "zeroisation",
    ),
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
    "docs/VALUE_TYPES_POLICY.md": (
        "price",
        "quantity",
        "symbol",
        "side",
        "currency",
        "decimal",
        "refus",
    ),
    "docs/TIME_POLICY.md": (
        "utc",
        "instant",
        "monotonic",
        "millisecond",
        "inject",
        "floor",
        "naive",
    ),
    "docs/PRECISION_POLICY.md": (
        "exact",
        "rounding",
        "tick",
        "step",
        "increment",
        "context",
        "refus",
    ),
    "docs/IDENTIFIER_POLICY.md": (
        "canonical",
        "registry",
        "product",
        "environment",
        "run",
        "model",
        "order",
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
    "docs/engineering/CI_SECURITY.md": (
        "pin",
        "least privilege",
        "merge queue",
        "timeout",
        "concurrency",
        "fail-closed",
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


#: The README's count of decision records: `Architecture decision records (26)`.
README_ADR_COUNT_RE = re.compile(r"Architecture decision records \((?P<count>\d+)\)")


def test_the_readme_adr_count_matches_the_adr_set(repo_root: Path) -> None:
    """A hand-maintained number is a number that goes stale.

    The README tells a first-time reader how much decision history exists. That
    is worth stating and worth being true: a count that has drifted teaches the
    reader to distrust the rest of the table, and nothing else on that table is
    checkable by eye either.

    The regular expression failing to match is itself a failure rather than a
    silent pass, so removing the claim to avoid maintaining it is not available
    without editing this test.
    """
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    stated = README_ADR_COUNT_RE.search(readme)
    assert stated is not None, "README no longer states how many ADRs exist"
    assert int(stated.group("count")) == len(_adr_paths(repo_root))


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


# --------------------------------------------------------------------------
# The README's maturity table
#
# `README.md` is the one document a stranger reads before deciding whether to
# trust anything else here, and its capability table is the load-bearing claim:
# what exists, and what does not. Prose is not directly checkable, so the table
# is held to a structure that makes the claim falsifiable — every implemented row
# must point at the artefact that proves it, and the row admitting that
# everything else is unbuilt must survive.
# --------------------------------------------------------------------------

#: A two-column row of a Markdown table, with the cells stripped.
TABLE_ROW_RE = re.compile(r"^\|\s*(?P<left>[^|]+?)\s*\|\s*(?P<right>[^|]+?)\s*\|\s*$", re.MULTILINE)

#: A repository-relative Markdown link: `[text](path)`, excluding URLs and
#: in-page anchors.
RELATIVE_LINK_RE = re.compile(r"\[[^\]]+\]\((?!https?://|#)(?P<target>[^)]+)\)")

#: The states a capability row may claim. Deliberately two: a third such as
#: "Partial" or "In progress" is how a table stops distinguishing a thing that
#: works from a thing somebody started.
CAPABILITY_STATES: frozenset[str] = frozenset({"Implemented", "Not started"})

#: The row that stops the table reading as a complete inventory of the system.
CATCH_ALL_ROW: tuple[str, str] = ("Everything else", "Not started")

#: Capabilities `README.md` states do not exist, each paired with the fragment no
#: module under `src/globin/` may contain while that remains true. Phases 033
#: onwards will legitimately break these, and the point is that they cannot do so
#: without editing the README in the same commit.
ABSENT_CAPABILITIES: tuple[tuple[str, str], ...] = (
    ("Binance API integration", "binance"),
    ("request signing", "signing"),
    ("credential handling", "credential"),
    ("WebSocket", "websocket"),
    ("market data ingestion", "market"),
    ("order books", "order"),
    ("an execution engine", "execution"),
    ("backtesting", "backtest"),
    ("technical indicators", "indicator"),
    ("strategies", "strateg"),
    ("machine learning", "learning"),
    ("reinforcement learning", "reinforcement"),
    ("optimisation", "optimis"),
    ("portfolio and risk management", "portfolio"),
    ("the Telegram interface", "telegram"),
    ("the orchestrator", "orchestrat"),
)


def capability_rows(readme: str) -> tuple[tuple[str, str], ...]:
    """Return the component/state rows of the README's maturity table.

    Args:
        readme: The README source.

    Returns:
        One ``(component, state)`` pair per row, in document order, with the
        header and separator rows dropped.
    """
    section = markdown_section(readme, "### What exists right now")
    return tuple(
        (match.group("left"), match.group("right"))
        for match in TABLE_ROW_RE.finditer(section)
        if match.group("right") != "State" and not match.group("left").startswith("--")
    )


def test_the_capability_reader_finds_its_own_failing_case() -> None:
    """Guard the guard. A reader returning nothing would pass every check below."""
    readme = "\n".join(
        [
            "",
            "### What exists right now",
            "",
            "| Component | State |",
            "|---|---|",
            "| A | Implemented |",
            "",
            "## Next",
            "",
            "| B | C |",
            "",
        ]
    )
    assert capability_rows(readme) == (("A", "Implemented"),)


def test_the_capability_table_has_rows(repo_root: Path) -> None:
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    assert capability_rows(readme), "README states nothing about what exists"


def test_every_capability_claims_a_known_state(repo_root: Path) -> None:
    """Two states, so that a row cannot describe something half-built.

    `DEFINITION_OF_DONE.md` recognises no partial completion, and a table that
    offered one would let a phase report itself as nearly finished — the claim
    the whole programme is arranged to make impossible.
    """
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    unknown = [row for row in capability_rows(readme) if row[1] not in CAPABILITY_STATES]
    assert not unknown, f"capability rows with an unrecognised state: {unknown}"


def test_the_table_still_admits_that_everything_else_is_unbuilt(repo_root: Path) -> None:
    """Without the final row the table reads as a complete inventory.

    It is the only row permitted to say `Not started`, and it must come last:
    a catch-all in the middle would leave the rows beneath it looking like
    exceptions to it rather than entries above it.
    """
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    rows = capability_rows(readme)
    assert rows[-1] == CATCH_ALL_ROW, f"the last capability row is {rows[-1]}, not {CATCH_ALL_ROW}"

    unstarted = [row for row in rows if row[1] == "Not started"]
    assert unstarted == [CATCH_ALL_ROW], (
        "a capability that is not started needs no row of its own; the catch-all covers it"
    )


def test_every_implemented_capability_points_at_its_evidence(repo_root: Path) -> None:
    """A claim with nothing behind it is the failure this table could hide.

    Requiring a repository-relative link makes the claim checkable without this
    test knowing anything about what any row means: the link must exist, which
    `test_every_repository_relative_link_resolves` already enforces over every
    committable document, so a row naming a file that was never written fails
    there rather than here.
    """
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    unevidenced = [
        component
        for component, state in capability_rows(readme)
        if state == "Implemented" and RELATIVE_LINK_RE.search(component) is None
    ]
    assert not unevidenced, (
        f"implemented capabilities with no link to what proves them: {unevidenced}"
    )


def test_the_readme_names_every_capability_it_says_is_absent(repo_root: Path) -> None:
    """The list below is the other half of the maturity claim, and it goes stale.

    the moment a phase starts building one of these.
    """
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    # Whitespace is collapsed first: the document wraps at 100 columns, so a
    # two-word capability can be split across a line break and a naive substring
    # search would report it missing from a document that names it.
    section = " ".join(markdown_section(readme, "### What does not exist").split())
    missing = [name for name, _fragment in ABSENT_CAPABILITIES if name not in section]
    assert not missing, f"README no longer lists these as absent: {missing}"


def test_nothing_absent_from_the_readme_has_quietly_acquired_a_module(repo_root: Path) -> None:
    """The claim, checked against the tree rather than against itself.

    `test_import_surface.py` guards the exported names; this guards the file
    names, which is where a phase implemented early would show up first.
    """
    modules = [path.stem.lower() for path in (repo_root / "src" / "globin").rglob("*.py")]
    started = [
        f"{name} (module matching {fragment!r})"
        for name, fragment in ABSENT_CAPABILITIES
        if any(fragment in module for module in modules)
    ]
    assert not started, (
        f"README says these do not exist, but the package has modules for them: {started}"
    )


#: Verbs `docs/security/SECRET_STORE_CONTRACT.md` section 5 forbids: each would
#: return a secret to a terminal, a file or a log. Matched against module stems
#: and against the command table, which are the two places such a thing would
#: first appear.
FORBIDDEN_REVEAL_VERBS: tuple[str, ...] = ("reveal", "dump", "export")


def test_no_command_or_module_offers_to_reveal_a_secret(repo_root: Path) -> None:
    """A negative surface, guarded the only way a negative surface can be.

    This passes vacuously today, and saying so is honest rather than damning: it
    is a tripwire on the frontier, in the same way `test_drift_contract.py` pins
    a phase number that is correct now and will be wrong the moment somebody
    moves past it without looking.

    What it catches is the specific failure section 5 exists to prevent. Phase 029
    defines credential collection, and the obvious convenience to add while doing
    it -- a way to print the secret back so somebody can check it -- is the one
    thing that turns an operating-system vault into a value in a scrollback
    buffer. The day that command is added, this goes red and the contract has to
    be argued with rather than forgotten.

    `show` and `print` are deliberately absent from the list. Both are ordinary
    English that a legitimate command could carry -- `show` a manifest, `print` a
    report -- and a tripwire that fires on innocent names is one somebody deletes.
    The three kept are the ones whose only plausible object here is the material.
    """
    offenders: list[str] = []
    for path in (repo_root / "src" / "globin").rglob("*.py"):
        stem = path.stem.lower()
        offenders.extend(
            f"src/globin module {path.stem!r} (matches {verb!r})"
            for verb in FORBIDDEN_REVEAL_VERBS
            if verb in stem
        )
    for name in command_names():
        offenders.extend(
            f"quality command {name!r} (matches {verb!r})"
            for verb in FORBIDDEN_REVEAL_VERBS
            if verb in name
        )
    assert not offenders, (
        "docs/security/SECRET_STORE_CONTRACT.md section 5 says no verb returns a "
        f"secret to a terminal, and these have appeared: {offenders}"
    )


# ---------------------------------------------------------------------------
# A policy document may not defer a question to a phase that has already answered it
# ---------------------------------------------------------------------------


def _deferral_rows(text: str) -> list[tuple[str, str]]:
    """Return the question and owner of every deferral row in a document.

    Args:
        text: The document.

    Returns:
        One pair per row, excluding the header and the alignment rule.

    Found by walking from the table's own header rather than from a section
    heading, because the four documents carrying this table do not agree on what
    to call the section above it — and the table is the thing being checked.
    """
    rows: list[tuple[str, str]] = []
    inside = False
    for line in text.splitlines():
        if line.strip() == "| Question | Phase |":
            inside = True
            continue
        if not inside:
            continue
        if not line.startswith("|"):
            inside = False
            continue
        match = DEFERRAL_ROW_RE.match(line)
        if match is None:
            continue
        question = match.group("question")
        if set(question) <= set("-: "):
            continue
        rows.append((question, match.group("owner")))
    return rows


def test_the_deferral_row_parser_finds_rows(repo_root: Path) -> None:
    """Guard the guard.

    A parser that silently matched nothing would make every assertion below pass
    while comparing empty sets, which is the failure mode a tripwire has.
    """
    for relative in DEFERRAL_TABLES:
        rows = _deferral_rows((repo_root / relative).read_text(encoding="utf-8"))
        assert len(rows) >= 3, f"{relative}: parsed {len(rows)} deferral rows"


@pytest.mark.parametrize("relative", DEFERRAL_TABLES)
def test_no_document_defers_a_question_to_a_phase_that_has_delivered(
    repo_root: Path, relative: str
) -> None:
    """A deferral is a promise that the answer does not exist yet.

    Each of these tables sits under a heading whose own purpose is to stop a
    reader inferring a rule from the absence of one. Pointing at a phase that has
    already shipped does the opposite: the reader is told the question is open
    when it has been answered, and told where to look by a number that is wrong.

    Three of these rows were stale when Phase 019 looked, and the convention for
    fixing them — ``012, delivered - <document>`` — already existed in two of the
    same tables. It had simply not been applied when the phases delivered. Nothing
    compared them, which is why the disagreement survived.
    """
    statuses = {
        row.phase: row.status
        for row in parse_roadmap((repo_root / "ROADMAP.md").read_text(encoding="utf-8"))
    }
    stale: list[str] = []
    for question, owner in _deferral_rows((repo_root / relative).read_text(encoding="utf-8")):
        if DELIVERED in owner.lower():
            continue
        for number in PHASE_IN_OWNER_RE.findall(owner):
            status = statuses.get(int(number))
            if status is not None and status != "Planned":
                stale.append(f"{question!r} defers to phase {number}, which is {status}")
    assert not stale, f"{relative} defers to phases that have delivered: {stale}"
