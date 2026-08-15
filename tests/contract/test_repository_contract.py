"""Verify the repository's structural contracts: layout, links and hygiene.

Where ``test_documentation_contract.py`` asks whether each document says what it
is responsible for saying, this module asks whether the repository *holds
together*: that the engineering contracts exist, that every cross-reference
between documents actually resolves, that the change templates are present, and
that no credential-shaped file has been committed.

Two deliberate limits are worth stating, because both are easy to get wrong in
a way that produces false confidence:

* The link checker resolves **repository-relative links only**. External URLs
  are not fetched — a test that reaches the network is not deterministic, and
  ``docs/TESTING_STRATEGY.md`` forbids it below the External level. Link *rot*
  on third-party sites is handled by the research ledger's access dates.
* The credential check matches **filenames**, never file contents. A regular
  expression hunting for secrets inside files would miss anything unusual while
  looking authoritative, and false authority is worse here than no check. Real
  secret handling is Phase 015; this is a tripwire for the obvious accident.
"""

import fnmatch
import re
from pathlib import Path

import pytest

from tests.support import markdown_prose

# --------------------------------------------------------------------------
# What must exist
# --------------------------------------------------------------------------

#: The engineering contracts introduced in Phase 002. Separate from the
#: ``REQUIRED_DOCS`` list in ``test_documentation_contract.py``: that list is
#: about documents stating their policies, this one is about the process
#: contracts existing at their canonical location (ADR-0011).
ENGINEERING_DOCS: tuple[str, ...] = (
    "docs/engineering/ENGINEERING_CONTRACT.md",
    "docs/engineering/DEFINITION_OF_DONE.md",
    "docs/engineering/SOURCE_OF_TRUTH.md",
    "docs/engineering/REPOSITORY_LAYOUT.md",
    "docs/engineering/DOCUMENTATION_STANDARD.md",
    # Added in Phase 004 with the quality gates they describe.
    "docs/engineering/QUALITY_GATES.md",
    "docs/engineering/STATIC_ANALYSIS.md",
    # Added in Phase 013 with the CI hardening it describes (ADR-0043).
    "docs/engineering/CI_SECURITY.md",
)

#: Change templates. Paths are fixed by GitHub, not chosen — see
#: ``docs/research/phase_002_sources.md`` entries S-01 and S-02.
GITHUB_TEMPLATES: tuple[str, ...] = (
    ".github/pull_request_template.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/engineering_task.md",
)

ADR_TEMPLATE = "docs/adr/TEMPLATE.md"

#: Sections a new ADR must offer. The first four are also asserted on every
#: numbered ADR by ``test_documentation_contract.py``; the rest are asserted
#: only from ADR-0012 onwards, because earlier records predate them and are
#: immutable. The template must offer all of them regardless, since it is what
#: the next record is copied from.
ADR_TEMPLATE_SECTIONS: tuple[str, ...] = (
    "## Status",
    "## Context",
    "## Decision",
    "## Consequences",
    "## Alternatives Considered",
    "## Risks and Trade-offs",
    "## References",
    "## Supersedes",
    "## Superseded By",
)


def _read(repo_root: Path, relative: str) -> str:
    return (repo_root / relative).read_text(encoding="utf-8")


@pytest.mark.parametrize("relative", ENGINEERING_DOCS)
def test_engineering_document_exists_and_is_substantive(repo_root: Path, relative: str) -> None:
    path = repo_root / relative
    assert path.is_file(), f"missing engineering contract: {relative}"
    text = path.read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) >= 800, f"{relative} is too thin to be a contract"
    assert text.lstrip().startswith("# "), f"{relative} must open with a level-1 heading"


def test_engineering_documents_are_committable(committable_files: tuple[str, ...]) -> None:
    """A contract Git would not commit is invisible to every other contributor.

    Catches the specific accident of a document written into a path that
    ``.gitignore`` swallows, which leaves the repository asserting a rule that
    no other clone can read.
    """
    missing = [doc for doc in ENGINEERING_DOCS if doc not in committable_files]
    assert not missing, f"engineering contracts are ignored by Git: {missing}"


# --------------------------------------------------------------------------
# Cross-references
# --------------------------------------------------------------------------

#: An inline Markdown link. The target group stops at the first ``)``, which is
#: correct for every link style used here; parenthesised targets are not used
#: and would need angle-bracket form anyway.
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(\s*(?P<target>[^)\s]+)")

#: Schemes that leave the repository. Not fetched — see the module docstring.
EXTERNAL_PREFIXES: tuple[str, ...] = ("http://", "https://", "mailto:", "ftp://", "//")


def _repo_relative_targets(text: str) -> list[str]:
    """Return the repository-relative link targets in ``text``.

    Code is removed first, then external schemes and pure in-page anchors are
    discarded and any trailing ``#anchor`` is trimmed. Anchors are not
    validated: heading slugs are a renderer concern, and asserting them would
    make every heading rename a test failure — precisely the brittleness
    ``docs/TESTING_STRATEGY.md`` warns against.

    Stripping inline code leaves ``[`README.md`](README.md)`` as
    ``[](README.md)``, whose target still matches.
    """
    targets: list[str] = []
    for match in MARKDOWN_LINK_RE.finditer(markdown_prose(text)):
        target = match.group("target").strip()
        if not target or target.startswith("#"):
            continue
        if target.lower().startswith(EXTERNAL_PREFIXES):
            continue
        targets.append(target.split("#", 1)[0])
    return targets


def test_every_repository_relative_link_resolves(
    repo_root: Path, committable_markdown: tuple[str, ...]
) -> None:
    """Cross-references between documents must point at something real.

    Phase 002 made links load-bearing: the engineering contracts deliberately
    link instead of restating (ADR-0011), so a broken link now silently removes
    a rule rather than merely inconveniencing a reader.
    """
    broken: list[str] = []
    for relative in committable_markdown:
        source = repo_root / relative
        for target in _repo_relative_targets(source.read_text(encoding="utf-8")):
            if not (source.parent / target).resolve().exists():
                broken.append(f"{relative} -> {target}")
    assert not broken, "unresolved repository-relative links:\n  " + "\n  ".join(broken)


def test_link_checker_detects_a_broken_link() -> None:
    """The checker must be able to fail, or it proves nothing.

    A validator whose negative case is never exercised tends to quietly stop
    matching anything at all — a regex refactor is enough to do it.
    """
    assert _repo_relative_targets("[gone](docs/does_not_exist.md)") == ["docs/does_not_exist.md"]
    assert _repo_relative_targets("[ok](../adr/README.md#index)") == ["../adr/README.md"]
    assert _repo_relative_targets("[out](https://example.invalid/x.md)") == []
    assert _repo_relative_targets("[here](#section)") == []
    assert _repo_relative_targets("```\n[fenced](nope.md)\n```\n") == []
    # Backticked link text is the repository's house style and must survive.
    assert _repo_relative_targets("[`README.md`](README.md)") == ["README.md"]


def test_prose_extraction_ignores_quoted_material() -> None:
    """``markdown_prose`` strips what is being *named* while keeping what is *said*."""
    assert "TODO" not in markdown_prose("Never write `TODO` in a document.")
    assert "TODO" not in markdown_prose("```python\n# TODO: later\n```\n")
    assert "TODO" in markdown_prose("TODO: this one is real debt.")


# --------------------------------------------------------------------------
# Change templates
# --------------------------------------------------------------------------


@pytest.mark.parametrize("relative", GITHUB_TEMPLATES)
def test_github_template_exists(repo_root: Path, relative: str) -> None:
    assert (repo_root / relative).is_file(), f"missing change template: {relative}"


def test_pull_request_template_asks_for_the_things_that_matter(repo_root: Path) -> None:
    text = _read(repo_root, ".github/pull_request_template.md").lower()
    for prompt in ("phase", "scope", "test", "documentation", "risk", "secret", "verification"):
        assert prompt in text, f"pull request template does not ask about: {prompt}"
    assert "definition_of_done" in text, "PR template must point at the canonical DoD"


def test_issue_templates_carry_github_frontmatter(repo_root: Path) -> None:
    """Markdown issue templates need ``name`` and ``about`` to appear in the chooser.

    Frontmatter keys per ``docs/research/phase_002_sources.md`` entry S-03.
    """
    for relative in GITHUB_TEMPLATES:
        if "ISSUE_TEMPLATE" not in relative:
            continue
        text = _read(repo_root, relative)
        assert text.startswith("---\n"), f"{relative} must open with YAML frontmatter"
        header = text.split("---", 2)[1]
        assert "name:" in header, f"{relative} frontmatter has no `name`"
        assert "about:" in header, f"{relative} frontmatter has no `about`"


def test_bug_report_requires_redaction_and_reproduction(repo_root: Path) -> None:
    text = _read(repo_root, ".github/ISSUE_TEMPLATE/bug_report.md").lower()
    for prompt in ("expected", "actual", "reproduc", "environment", "redact", "regression"):
        assert prompt in text, f"bug report template does not ask about: {prompt}"


def test_engineering_task_template_binds_work_to_a_phase(repo_root: Path) -> None:
    text = _read(repo_root, ".github/ISSUE_TEMPLATE/engineering_task.md").lower()
    for prompt in ("phase", "acceptance criteria", "out of scope"):
        assert prompt in text, f"engineering task template does not ask about: {prompt}"


def test_adr_template_offers_every_required_section(repo_root: Path) -> None:
    text = _read(repo_root, ADR_TEMPLATE)
    missing = [section for section in ADR_TEMPLATE_SECTIONS if section not in text]
    assert not missing, f"{ADR_TEMPLATE} is missing sections: {missing}"


def test_adr_template_is_excluded_from_numbered_records(repo_root: Path) -> None:
    """The template must not be picked up as ADR-0000 by the numbering checks."""
    adr_dir = repo_root / "docs" / "adr"
    numbered = {path.name for path in adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md")}
    assert "TEMPLATE.md" not in numbered


# --------------------------------------------------------------------------
# Hygiene
# --------------------------------------------------------------------------

#: Filenames that are credential artefacts by convention. Precise patterns
#: only: a broad glob such as ``*secret*`` would also match documentation about
#: secret handling, and a check that cries wolf gets disabled.
CREDENTIAL_FILENAME_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "*.secret",
    "*.token",
    "credentials.json",
    "api_keys.json",
    "secrets.json",
    "secrets.toml",
    "secrets.yaml",
    "secrets.yml",
    "telegram_token.txt",
)

#: Suffixes marking a file as a committed sample rather than a live secret.
#: ``.gitignore`` already re-includes ``.env.example`` for the same reason:
#: template configuration must stay committable.
SAMPLE_SUFFIXES: tuple[str, ...] = (".example", ".template", ".sample", ".dist")

#: Directories whose whole contents are credential material by convention.
CREDENTIAL_DIRECTORIES: frozenset[str] = frozenset({"secrets", "credentials"})


def test_no_credential_shaped_file_is_committable(committable_files: tuple[str, ...]) -> None:
    offenders: list[str] = []
    for relative in committable_files:
        parts = relative.split("/")
        if CREDENTIAL_DIRECTORIES.intersection(parts[:-1]):
            offenders.append(relative)
            continue
        name = parts[-1]
        if name.endswith(SAMPLE_SUFFIXES):
            continue
        if any(fnmatch.fnmatch(name, pattern) for pattern in CREDENTIAL_FILENAME_PATTERNS):
            offenders.append(relative)
    assert not offenders, f"credential-shaped files would be committed: {offenders}"


@pytest.mark.parametrize("relative", ENGINEERING_DOCS)
def test_engineering_documents_carry_no_placeholder_debt(repo_root: Path, relative: str) -> None:
    """A contract containing unfinished thinking is a contract not yet agreed.

    Checked against prose only. These documents *prohibit* placeholder markers
    and therefore have to name them; quoting a marker in backticks is the
    opposite of leaving one behind.
    """
    prose = markdown_prose(_read(repo_root, relative))
    found = [marker for marker in ("TODO", "TBD", "FIXME", "XXX") if marker in prose]
    assert not found, f"{relative} contains placeholder markers: {found}"


def test_tool_configuration_is_not_duplicated_outside_pyproject(
    committable_files: tuple[str, ...],
) -> None:
    """One machine-readable configuration file, per ADR-0011 and REPOSITORY_LAYOUT.

    Each name below configures a tool already configured in ``pyproject.toml``.
    A second home for the same settings is the drift this repository's
    source-of-truth order exists to prevent.
    """
    competing = {"setup.cfg", "tox.ini", "pytest.ini", "mypy.ini", ".flake8", "ruff.toml"}
    found = sorted(path for path in committable_files if path.split("/")[-1] in competing)
    assert not found, f"tool configuration duplicated outside pyproject.toml: {found}"
