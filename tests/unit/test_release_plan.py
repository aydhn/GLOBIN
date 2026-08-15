"""Judging a release contract, from literals.

Every function in :mod:`tools.quality.release.plan` takes text or values and
returns findings, so the whole of the reasoning is testable offline with no
repository, no network and no temporary tree.

**Each checker is exercised twice: once against something correct, and once
against something deliberately broken.** A checker only ever seen to pass is a
checker nobody has established can fail, and ``docs/engineering/QUALITY_GATES.md``
is explicit that a gate that cannot fail is decoration.
"""

import pytest

from tools.quality.release import plan
from tools.quality.release.plan import Criterion, ReleaseError, Status

DECLARATION = """\
schema = 1

[release]
version_source = "src/globin/__init__.py"
changelog = "CHANGELOG.md"
release_notes = ".github/release.yml"
policy = "docs/release/RELEASE_POLICY.md"
acceptance = "docs/release/FOUNDATION_ACCEPTANCE.md"

[[criterion]]
id = "FND-A-01"
category = "repository-foundation"
requirement = "Identity is executable."
evidence = ["src/globin/project_contract.py"]
blocking = true
status = "PASS"
reason = "Asserted by a contract test."
"""

RELEASE_NOTES = """\
changelog:
  categories:
    - title: Features
      labels:
        - enhancement
    - title: Other Changes
      labels:
        - "*"
"""


def criterion(
    identifier: str = "FND-A-01",
    *,
    category: str = "repository-foundation",
    blocking: bool = True,
    status: Status = Status.PASS,
    evidence: tuple[str, ...] = ("pyproject.toml",),
    command: str = "",
) -> Criterion:
    """One criterion, with everything a test does not care about filled in."""
    return Criterion(
        identifier=identifier,
        category=category,
        requirement="A requirement.",
        blocking=blocking,
        status=status,
        reason="A reason.",
        evidence=evidence,
        command=command,
    )


# ---------------------------------------------------------------------------
# Reading a version
# ---------------------------------------------------------------------------


def test_the_version_is_read_from_an_assignment() -> None:
    assert plan.read_version('__version__ = "0.1.0"\n') == "0.1.0"
    assert plan.read_version("x = 1\n__version__ = '2.3.4'\ny = 2\n") == "2.3.4"
    assert plan.read_version('__version__: Final[str] = "9.8.7"\n') == "9.8.7"


def test_a_source_without_a_version_is_refused_rather_than_defaulted() -> None:
    """The alternative is a gate that tags 'unknown' and reports success."""
    with pytest.raises(ReleaseError, match="no __version__ assignment"):
        plan.read_version("VERSION = '1.0.0'\n")


@pytest.mark.parametrize("version", ["0.1.0", "1.0.0", "10.20.30", "0.0.1"])
def test_a_final_release_version_is_accepted(version: str) -> None:
    assert plan.valid_version(version)


@pytest.mark.parametrize(
    "version",
    [
        "0.1",  # two components; the pattern wants three
        "0.1.0.1",  # four
        "01.1.0",  # a leading zero
        "1.0.0a1",  # a pre-release, which PEP 440 allows and this project does not
        "1.0.0.dev1",
        "1!1.0.0",  # an epoch
        "1.0.0+local",
        "v1.0.0",  # the tag, not the version
        "",
        "one.two.three",
    ],
)
def test_a_version_this_project_cannot_tag_is_refused(version: str) -> None:
    """PEP 440 is wider than this project.

    A shape the release procedure has no answer for must not be accepted merely because a
    specification permits it.
    """
    assert not plan.valid_version(version)


# ---------------------------------------------------------------------------
# Tag parity
# ---------------------------------------------------------------------------


def test_a_tag_names_its_version_and_back_again() -> None:
    assert plan.tag_for("0.1.0") == "v0.1.0"
    assert plan.version_for("v0.1.0") == "0.1.0"


@pytest.mark.parametrize("version", ["0.1.0", "1.2.3", "10.0.99"])
def test_tag_and_version_are_inverses(version: str) -> None:
    """The property the gate's parity check exists to hold to account."""
    assert plan.version_for(plan.tag_for(version)) == version


@pytest.mark.parametrize("tag", ["0.1.0", "release-0.1.0", "v0.1", "v1.0.0a1", "v", ""])
def test_something_that_is_not_a_release_tag_names_no_version(tag: str) -> None:
    assert plan.version_for(tag) is None


# ---------------------------------------------------------------------------
# The changelog
# ---------------------------------------------------------------------------


def test_the_announced_versions_are_read_in_order() -> None:
    text = "# Changelog\n\n## [Unreleased]\n\n## [0.2.0] - x\n\n## 0.1.0\n"
    assert plan.changelog_versions(text) == ("0.2.0", "0.1.0")


def test_a_changelog_announcing_the_version_once_is_accepted() -> None:
    text = "## [Unreleased]\n\n## [0.1.0] - 2026-08-15\n"
    assert plan.changelog_problems(text, "0.1.0") == ()


def test_a_changelog_that_does_not_announce_the_version_is_a_problem() -> None:
    text = "## [Unreleased]\n\n## [0.2.0] - x\n"
    assert any(
        "does not announce 0.1.0" in problem for problem in plan.changelog_problems(text, "0.1.0")
    )


def test_a_version_announced_twice_is_a_problem() -> None:
    """What a careless re-run produces: a section appended, not edited."""
    text = "## [Unreleased]\n\n## [0.1.0] - x\n\n## [0.1.0] - y\n"
    assert any("more than once" in problem for problem in plan.changelog_problems(text, "0.1.0"))


def test_a_changelog_without_an_unreleased_heading_is_a_problem() -> None:
    text = "## [0.1.0] - 2026-08-15\n"
    assert any("Unreleased" in problem for problem in plan.changelog_problems(text, "0.1.0"))


# ---------------------------------------------------------------------------
# Release notes configuration
# ---------------------------------------------------------------------------


def test_a_well_formed_release_notes_configuration_is_accepted() -> None:
    assert plan.release_notes_problems(RELEASE_NOTES) == ()


def test_a_configuration_without_a_catch_all_is_a_problem() -> None:
    """Without it, an uncategorised pull request is dropped from the notes."""
    text = (
        "changelog:\n  categories:\n    - title: Features\n      labels:\n        - enhancement\n"
    )
    assert any("catch-all" in problem for problem in plan.release_notes_problems(text))


def test_a_configuration_with_no_changelog_root_is_a_problem() -> None:
    text = "categories:\n  - title: Features\n"
    assert any("changelog:" in problem for problem in plan.release_notes_problems(text))


def test_a_configuration_with_no_categories_is_a_problem() -> None:
    text = "changelog:\n  exclude:\n    labels:\n      - ignore\n"
    problems = plan.release_notes_problems(text)
    assert any("categories:" in problem for problem in problems)


def test_an_empty_configuration_is_refused_on_every_count() -> None:
    """Guard the guard. A reader returning nothing would pass every check above."""
    problems = plan.release_notes_problems("")
    assert len(problems) == 4


# ---------------------------------------------------------------------------
# The criteria
# ---------------------------------------------------------------------------


def test_a_repeated_identifier_is_reported() -> None:
    criteria = (criterion("FND-A-01"), criterion("FND-A-01"), criterion("FND-A-02"))
    assert plan.duplicate_identifiers(criteria) == ("FND-A-01",)


def test_identifiers_used_once_each_are_not_reported() -> None:
    criteria = (criterion("FND-A-01"), criterion("FND-A-02"))
    assert plan.duplicate_identifiers(criteria) == ()


@pytest.mark.parametrize("identifier", ["FND-A-1", "FND-Q-01", "fnd-a-01", "A-01", "FND-A-001"])
def test_an_identifier_outside_the_declared_shape_is_reported(identifier: str) -> None:
    assert plan.malformed_identifiers((criterion(identifier),)) == (identifier,)


def test_a_well_formed_identifier_is_not_reported() -> None:
    assert plan.malformed_identifiers((criterion("FND-P-05"),)) == ()


def test_a_category_letter_follows_the_declared_order() -> None:
    assert plan.category_letter("repository-foundation") == "A"
    assert plan.category_letter("release-readiness") == "P"
    assert plan.category_letter("invented") == ""


def test_an_identifier_filed_under_the_wrong_category_is_reported() -> None:
    """The identifier and the category say the same thing twice on purpose.

    Two spellings of one fact need a check that they agree.
    """
    misfiled = criterion("FND-A-01", category="release-readiness")
    assert plan.misfiled_identifiers((misfiled,)) == (
        "FND-A-01 is filed under 'release-readiness', whose criteria are numbered FND-P-NN",
    )


def test_an_identifier_matching_its_category_is_not_reported() -> None:
    assert plan.misfiled_identifiers((criterion("FND-A-01"),)) == ()


def test_an_unknown_category_is_reported() -> None:
    assert plan.unknown_categories((criterion(category="invented"),)) == ("invented",)


def test_every_declared_category_absent_from_the_criteria_is_reported() -> None:
    """A category with no criteria claims coverage the matrix does not have."""
    empty = plan.empty_categories((criterion(),))
    assert "repository-foundation" not in empty
    assert len(empty) == len(plan.CATEGORIES) - 1


def test_a_populated_matrix_leaves_no_category_empty() -> None:
    criteria = tuple(
        criterion(f"FND-{plan.category_letter(name)}-01", category=name) for name in plan.CATEGORIES
    )
    assert plan.empty_categories(criteria) == ()
    assert plan.misfiled_identifiers(criteria) == ()


@pytest.mark.parametrize("status", [Status.FAIL, Status.BLOCKED, Status.NOT_APPLICABLE])
def test_a_blocking_criterion_that_did_not_pass_is_reported(status: Status) -> None:
    """BLOCKED and NOT_APPLICABLE are reported alongside FAIL deliberately.

    Neither is a pass, and a blocking criterion is one a release may not proceed without.
    """
    reported = plan.blocking_failures((criterion(blocking=True, status=status),))
    assert len(reported) == 1
    assert str(status) in reported[0]


def test_a_non_blocking_criterion_that_did_not_pass_is_not_reported() -> None:
    assert plan.blocking_failures((criterion(blocking=False, status=Status.BLOCKED),)) == ()


def test_a_blocking_criterion_that_passed_is_not_reported() -> None:
    assert plan.blocking_failures((criterion(blocking=True, status=Status.PASS),)) == ()


def test_a_criterion_answered_by_nothing_is_reported() -> None:
    assert plan.unjustified((criterion(evidence=(), command="  "),)) == ("FND-A-01",)


def test_a_criterion_answered_by_a_command_alone_is_accepted() -> None:
    """Not every requirement has a file. One answered by a gate is answered."""
    assert plan.unjustified((criterion(evidence=(), command="python -m tools.quality full"),)) == ()


# ---------------------------------------------------------------------------
# Reading the declaration
# ---------------------------------------------------------------------------


def test_a_well_formed_declaration_is_read() -> None:
    contract = plan.parse_declaration(DECLARATION)
    assert contract.version_source == "src/globin/__init__.py"
    assert contract.changelog == "CHANGELOG.md"
    assert len(contract.criteria) == 1
    assert contract.criteria[0].status is Status.PASS
    assert contract.criteria[0].blocking is True


def test_the_documents_a_release_requires_are_listed_in_a_stable_order() -> None:
    contract = plan.parse_declaration(DECLARATION)
    assert contract.documents() == (
        "CHANGELOG.md",
        ".github/release.yml",
        "docs/release/RELEASE_POLICY.md",
        "docs/release/FOUNDATION_ACCEPTANCE.md",
    )


def test_text_that_is_not_toml_is_refused_with_the_file_named() -> None:
    with pytest.raises(ReleaseError, match="not valid TOML"):
        plan.parse_declaration("schema = = 1")


def test_a_declaration_of_another_schema_version_is_refused() -> None:
    """Refused rather than read anyway.

    A reader that guessed at an unknown version would be inventing the meaning of fields it has
    never seen.
    """
    with pytest.raises(ReleaseError, match="schema"):
        plan.parse_declaration(DECLARATION.replace("schema = 1", "schema = 2"))


def test_a_declaration_with_no_criteria_is_refused() -> None:
    """An empty matrix certifies nothing while looking like certification."""
    text = DECLARATION.split("[[criterion]]")[0]
    with pytest.raises(ReleaseError, match="no criteria"):
        plan.parse_declaration(text)


def test_a_declaration_with_no_release_table_is_refused() -> None:
    with pytest.raises(ReleaseError, match=r"\[release\]"):
        plan.parse_declaration(DECLARATION.replace("[release]", "[unrelated]"))


def test_a_status_outside_the_vocabulary_is_refused_and_the_permitted_set_is_named() -> None:
    text = DECLARATION.replace('status = "PASS"', 'status = "WARN"')
    with pytest.raises(ReleaseError, match="permitted: BLOCKED, FAIL, NOT_APPLICABLE, PASS"):
        plan.parse_declaration(text)


def test_a_missing_blocking_flag_is_refused_rather_than_defaulted() -> None:
    """Neither default is right.

    False would make the safe-looking omission the dangerous one; true would file every new
    criterion as release-stopping without anybody deciding that.
    """
    text = DECLARATION.replace("blocking = true\n", "")
    with pytest.raises(ReleaseError, match="blocking must be true or false"):
        plan.parse_declaration(text)


def test_a_blocking_flag_that_is_not_a_boolean_is_refused() -> None:
    text = DECLARATION.replace("blocking = true", 'blocking = "yes"')
    with pytest.raises(ReleaseError, match="must be true or false"):
        plan.parse_declaration(text)


@pytest.mark.parametrize("field", ["id", "category", "requirement", "reason"])
def test_a_criterion_missing_a_required_string_is_refused(field: str) -> None:
    text = "\n".join(
        line for line in DECLARATION.splitlines() if not line.startswith(f"{field} = ")
    )
    with pytest.raises(ReleaseError, match=field):
        plan.parse_declaration(text)


def test_an_empty_reason_is_refused() -> None:
    """A PASS nobody justified cannot be argued with when it stops holding."""
    text = DECLARATION.replace('reason = "Asserted by a contract test."', 'reason = "  "')
    with pytest.raises(ReleaseError, match="reason"):
        plan.parse_declaration(text)


def test_evidence_holding_something_that_is_not_a_string_is_refused() -> None:
    text = DECLARATION.replace('evidence = ["src/globin/project_contract.py"]', "evidence = [7]")
    with pytest.raises(ReleaseError, match="expected a string"):
        plan.parse_declaration(text)


def test_a_criterion_array_that_is_not_an_array_of_tables_is_refused() -> None:
    with pytest.raises(ReleaseError, match="array of tables"):
        plan.read_declaration({"schema": 1, "release": {}, "criterion": "not a list"})
