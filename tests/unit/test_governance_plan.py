"""Judging a governance arrangement, from literals.

Every function in :mod:`tools.quality.governance.plan` takes text or values and
returns findings, so the whole of the reasoning is testable offline with no
repository, no network and no temporary tree.

**Each checker is exercised twice: once against something correct, and once
against something deliberately broken.** A checker only ever seen to pass is a
checker nobody has established can fail, and ``docs/engineering/QUALITY_GATES.md``
is explicit that a gate that cannot fail is decoration.
"""

import pytest

from tools.quality.governance import plan
from tools.quality.governance.plan import GovernanceError, Rule, SensitivePath

CODEOWNERS = """\
# A comment, and a blank line follow.

*                          @aydhn
/.github/workflows/        @aydhn
/pyproject.toml            @aydhn @second
/docs/adr/                 @aydhn   # trailing comment
"""


def rules() -> tuple[Rule, ...]:
    """The parsed sample, for tests that need rules rather than text."""
    return plan.parse_codeowners(CODEOWNERS)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_comments_and_blank_lines_are_skipped_and_owners_are_kept() -> None:
    parsed = rules()
    assert [rule.pattern for rule in parsed] == [
        "*",
        "/.github/workflows/",
        "/pyproject.toml",
        "/docs/adr/",
    ]
    assert parsed[2].owners == ("@aydhn", "@second")
    assert parsed[3].owners == ("@aydhn",), "a trailing comment is not an owner"
    assert parsed[1].line == 4, "a finding must be able to point at the line"


def test_a_pattern_with_no_owner_is_refused_rather_than_ignored() -> None:
    """GitHub reads an ownerless line as *removing* ownership.

    That is a legitimate thing to write and a catastrophic thing to write by
    accident, because it looks exactly like a line that grants ownership until
    the owner column is noticed to be empty.
    """
    with pytest.raises(GovernanceError, match="no owner"):
        plan.parse_codeowners("/tools/\n")


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pattern", ["*", "**", "/*", "/**"])
def test_every_spelling_of_everything_is_recognised_as_a_catch_all(pattern: str) -> None:
    """One spelling missed would make the coverage check vacuous for that file."""
    assert plan.is_catch_all(pattern)
    assert plan.matches(pattern, "anything/at/all.py")


@pytest.mark.parametrize("pattern", ["!/docs/", "/docs/[ab]/", "/docs/**/deep/"])
def test_syntax_this_module_does_not_implement_is_reported_rather_than_guessed(
    pattern: str,
) -> None:
    """Guessing would either overstate or understate coverage.

    Reporting asks a person to simplify the pattern or extend the module, which
    is the only outcome that leaves the answer trustworthy.
    """
    assert not plan.supported(pattern)
    assert not plan.matches(pattern, "docs/adr/0001.md")


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        pytest.param("/.github/workflows/", ".github/workflows/", True, id="the directory"),
        pytest.param(
            "/.github/workflows/", ".github/workflows/quality.yml", True, id="a file under it"
        ),
        pytest.param("/.github/workflows/", ".github/dependabot.yml", False, id="a sibling"),
        pytest.param("/pyproject.toml", "pyproject.toml", True, id="an anchored file"),
        pytest.param("/pyproject.toml", "tools/pyproject.toml", False, id="not a nested copy"),
        pytest.param("/tools/", "tools/quality/commands.py", True, id="nested under a directory"),
        pytest.param("*.md", "docs/GLOSSARY.md", True, id="by extension anywhere"),
        pytest.param("*.md", "docs/GLOSSARY.txt", False, id="a different extension"),
    ],
)
def test_the_supported_pattern_forms_match_what_github_would_match(
    pattern: str, path: str, expected: bool
) -> None:
    assert plan.matches(pattern, path) is expected


def test_paths_are_posix_and_a_windows_spelling_does_not_match() -> None:
    """The gate is developed on Windows and must not accept a backslash path.

    Accepting both would let coverage depend on which separator happened to
    reach the checker, which is the sort of difference that passes locally and
    fails in continuous integration.
    """
    assert plan.matches("/.github/workflows/", ".github/workflows/quality.yml")
    assert not plan.matches("/.github/workflows/", ".github\\workflows\\quality.yml")


def test_a_catch_all_is_excluded_when_specific_coverage_is_asked_for() -> None:
    """The distinction the whole coverage check rests on."""
    parsed = rules()
    assert plan.covering_rules("README.md", parsed)
    assert not plan.covering_rules("README.md", parsed, specific=True)


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


def test_a_second_code_owners_file_is_a_failure_rather_than_a_duplicate() -> None:
    """GitHub reads one and ignores the other, so the maintained copy may be the ignored one."""
    problems = plan.duplicate_codeowners(
        [".github/CODEOWNERS", "CODEOWNERS"], authoritative=".github/CODEOWNERS"
    )
    assert len(problems) == 1
    assert "CODEOWNERS" in problems[0]


def test_the_authoritative_file_being_absent_is_reported() -> None:
    problems = plan.duplicate_codeowners([], authoritative=".github/CODEOWNERS")
    assert problems
    assert "does not exist" in problems[0]


def test_the_correct_arrangement_reports_nothing() -> None:
    assert not plan.duplicate_codeowners([".github/CODEOWNERS"], authoritative=".github/CODEOWNERS")


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def test_a_sensitive_path_owned_only_by_the_catch_all_is_uncovered() -> None:
    """Otherwise the check would be satisfied on any repository with a catch-all line.

    The specific entry is what survives the day a second maintainer makes the
    catch-all the wrong answer.
    """
    uncovered = plan.uncovered_sensitive_paths(
        [SensitivePath(path="src/globin/", category="runtime", reason="why")], rules()
    )
    assert len(uncovered) == 1
    assert "catch-all" in uncovered[0]


def test_a_sensitive_path_with_its_own_pattern_is_covered() -> None:
    assert not plan.uncovered_sensitive_paths(
        [SensitivePath(path=".github/workflows/", category="ci", reason="why")], rules()
    )


def test_a_pattern_matching_nothing_is_reported() -> None:
    """It reads as coverage while providing none, and survives a directory rename."""
    problems = plan.unmatched_patterns(rules(), ["README.md"])
    assert any("matches nothing" in problem for problem in problems)


def test_a_pattern_matching_something_is_not_reported() -> None:
    tree = [".github/workflows/", ".github/workflows/quality.yml", "pyproject.toml", "docs/adr/"]
    assert not plan.unmatched_patterns(rules(), tree)


def test_an_unowned_workflow_is_reported() -> None:
    """Adding a workflow is the most security-relevant change anybody makes here."""
    assert plan.ownerless([".elsewhere/rogue.yml"], rules())
    assert not plan.ownerless([".github/workflows/quality.yml"], rules())


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def test_a_missing_heading_is_reported_and_a_present_one_is_not() -> None:
    """Headings rather than prose, so editorial improvement is free and deletion is not."""
    text = "# Policy\n\n## How to report\n\nUse the form.\n"
    assert plan.missing_sections(text, ["## How to report"]) == ()
    assert plan.missing_sections(text, ["## Scope"]) == ("## Scope",)


def test_a_template_soliciting_exploit_detail_is_refused() -> None:
    """The check the whole issue-template arrangement exists for.

    A public form collecting exploit detail publishes the vulnerability at the
    moment it is reported, which is worse than having no channel at all.
    """
    template = "## Report\n\nPlease provide a proof of concept and the affected versions.\n"
    problems = plan.solicits_vulnerability_detail("security.md", template)
    assert problems
    assert all("security.md" in problem for problem in problems)


def test_a_template_warning_against_disclosure_is_not_mistaken_for_one() -> None:
    """A rule that flagged its own remedy would be a rule people switch off.

    ``bug_report.md`` warns, at length and inside an HTML comment, against
    reporting a vulnerability publicly. Flagging it for containing the words
    would make the check unusable on exactly the file that does this correctly.
    """
    template = (
        "<!--\nDo not describe a vulnerability, an exploit or a proof of concept here.\n"
        "Report it privately instead.\n-->\n\n## Expected behaviour\n\nWhat should happen:\n"
    )
    assert plan.solicits_vulnerability_detail("bug_report.md", template) == ()


def test_an_unclosed_comment_does_not_swallow_the_rest_of_the_check() -> None:
    """An unterminated comment runs to the end, which is what a Markdown renderer does."""
    assert plan.solicits_vulnerability_detail("x.md", "<!-- proof of concept") == ()
    assert plan.solicits_vulnerability_detail("x.md", "proof of concept <!-- note") != ()


# ---------------------------------------------------------------------------
# Reading the declaration
# ---------------------------------------------------------------------------

MINIMAL = """\
schema = 1

[locations]
codeowners = ".github/CODEOWNERS"
security_policy = "SECURITY.md"
governance_policy = "docs/security/GOVERNANCE.md"
security_baseline = "docs/security/SECURITY_BASELINE.md"
vulnerability_runbook = "docs/security/VULNERABILITY_RESPONSE.md"
pull_request_template = ".github/pull_request_template.md"
issue_template_config = ".github/ISSUE_TEMPLATE/config.yml"
issue_templates = ".github/ISSUE_TEMPLATE/"
codeowners_candidates = ["CODEOWNERS", ".github/CODEOWNERS"]

[security_policy]
required_sections = ["## How to report"]
reporting_url = "https://example.invalid/advisories/new"

[pull_request_template]
required_sections = ["## Security impact"]

[[sensitive_path]]
path = ".github/workflows/"
category = "continuous-integration"
reason = "It executes code."
"""


def test_a_well_formed_declaration_is_read() -> None:
    declaration = plan.parse_declaration(MINIMAL)
    assert declaration.locations.codeowners == ".github/CODEOWNERS"
    assert declaration.sensitive_paths[0].category == "continuous-integration"
    assert declaration.reporting_url.startswith("https://")
    assert declaration.extension_points == (), "an absent optional array is empty, not an error"


def test_an_unknown_schema_is_refused_rather_than_read_anyway() -> None:
    """A format this tool has not been taught is a format it cannot judge."""
    with pytest.raises(GovernanceError, match="schema"):
        plan.parse_declaration(MINIMAL.replace("schema = 1", "schema = 99"))


def test_an_empty_sensitive_path_list_is_refused() -> None:
    """A gate with nothing to require passes everything.

    The same reasoning ``read_configuration`` applies to an empty
    ``required_jobs``: there would be nothing left to be unhappy about.
    """
    without = MINIMAL.split("[[sensitive_path]]")[0]
    with pytest.raises(GovernanceError, match="sensitive_path is empty"):
        plan.parse_declaration(without)


@pytest.mark.parametrize(
    ("broken", "expected"),
    [
        pytest.param("[locations]", "[locations]", id="a missing table"),
        pytest.param('codeowners = ".github/CODEOWNERS"', "codeowners", id="a missing key"),
        pytest.param(
            'reporting_url = "https://example.invalid/advisories/new"',
            "reporting_url",
            id="a missing url",
        ),
    ],
)
def test_a_malformed_declaration_names_what_is_wrong(broken: str, expected: str) -> None:
    with pytest.raises(GovernanceError, match=expected):
        plan.parse_declaration(MINIMAL.replace(broken, ""))


def test_a_key_of_the_wrong_type_is_refused() -> None:
    with pytest.raises(GovernanceError, match="non-empty list"):
        plan.parse_declaration(
            MINIMAL.replace('required_sections = ["## Security impact"]', "required_sections = []")
        )


def test_text_that_is_not_toml_is_refused_with_the_reason() -> None:
    with pytest.raises(GovernanceError, match="not valid TOML"):
        plan.parse_declaration("schema = = 1")


@pytest.mark.parametrize(
    ("broken", "replacement", "expected"),
    [
        pytest.param(
            'codeowners_candidates = ["CODEOWNERS", ".github/CODEOWNERS"]',
            "codeowners_candidates = [1, 2]",
            "expected a string",
            id="a list holding something that is not a string",
        ),
        pytest.param(
            "schema = 1",
            'schema = 1\nextension_point = "not a table"',
            "array of tables",
            id="an array of tables that is not one",
        ),
        pytest.param(
            "schema = 1",
            "schema = 1\nextension_point = [42]",
            "expected a table",
            id="an array of tables holding something else",
        ),
        pytest.param(
            'required_sections = ["## How to report"]',
            'required_sections = "## How to report"',
            "non-empty list",
            id="a bare string where a list belongs",
        ),
    ],
)
def test_the_declaration_is_read_strictly_rather_than_coerced(
    broken: str, replacement: str, expected: str
) -> None:
    """Every one of these has a plausible "just make it work" reading.

    Coercing a string into a one-item list, or skipping an entry that is not a
    table, would each leave the gate checking less than the file appears to ask
    for — which is the failure a governance gate can least afford.
    """
    with pytest.raises(GovernanceError, match=expected):
        plan.parse_declaration(MINIMAL.replace(broken, replacement))


def test_an_extension_points_phase_must_be_a_positive_integer() -> None:
    """A phase of ``0``, ``true`` or ``"28"`` each names nothing in the programme."""
    for value in ("0", "true", '"28"'):
        entry = f'\n[[extension_point]]\npattern = "x"\nphase = {value}\nreason = "y"\n'
        with pytest.raises(GovernanceError, match="positive integer"):
            plan.parse_declaration(MINIMAL + entry)


def test_an_unsupported_pattern_is_reported_as_unreachable_rather_than_unmatched() -> None:
    """The two findings read differently and must not be conflated.

    "This pattern owns nothing" tells somebody to delete a line. "This gate
    cannot reason about this pattern" tells them to simplify it or extend the
    module — and only one of those is true here.
    """
    rules = plan.parse_codeowners("/docs/[ab]/  @aydhn\n")
    problems = plan.unmatched_patterns(rules, ["docs/a/x.md"])
    assert len(problems) == 1
    assert "does not implement" in problems[0]
