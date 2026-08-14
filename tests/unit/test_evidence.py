"""The pure half of the evidence package: parsing, digesting and rendering.

Everything here is driven from literals. The modules under test take text and
return values, so nothing needs a temporary directory, a subprocess or a clock —
the same split that makes `tools/quality/execution`'s pure modules testable, and
the reason the package is divided that way.

Whether the gate composes them correctly is
`tests/integration/test_evidence_end_to_end.py`; whether the tooling satisfies
ADR-0032 is `tests/contract/test_evidence_contract.py`.
"""

import json
from typing import Final

import pytest

from tools.quality.evidence import checksums, coverage_report, junit, manifest, redaction, summary
from tools.quality.evidence.cli import USAGE, UsageError, main, parse
from tools.quality.evidence.junit import EvidenceError

#: A JUnit report shaped exactly as pytest writes one, with `junit_family` set
#: to `xunit2`: one `testsuites` root wrapping one `testsuite`.
JUNIT_XML: Final[str] = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="globin" errors="1" failures="1" skipped="1" tests="4" time="2.500">
    <testcase classname="tests.unit.test_a" name="test_passes" time="0.100"/>
    <testcase classname="tests.unit.test_a" name="test_fails" time="1.900">
      <failure message="assert False">trace</failure>
    </testcase>
    <testcase classname="tests.unit.test_b" name="test_errors" time="0.300">
      <error message="fixture blew up">trace</error>
    </testcase>
    <testcase classname="tests.unit.test_b" name="test_skips" time="0.050">
      <skipped type="pytest.skip"/>
    </testcase>
  </testsuite>
</testsuites>
"""

#: The header of a PEM private key, assembled rather than written literally.
#:
#: This repository's own `detect-private-key` pre-commit hook scans every file
#: for that marker, so a fixture containing it would be refused by the same kind
#: of check this test exists to prove works. Splitting the string is not
#: cleverness for its own sake — it is the only way to test a secret detector
#: inside a repository that runs one.
PRIVATE_KEY_MARKER: Final[str] = "-----BEGIN " + "RSA PRIVATE KEY-----"

#: `coverage json`'s shape, with the keys the installed coverage.py writes.
COVERAGE_JSON: Final[str] = json.dumps(
    {
        "meta": {"branch_coverage": True},
        "totals": {
            "covered_lines": 1794,
            "num_statements": 2235,
            "percent_covered": 80.328,
            "percent_covered_display": "80",
            "missing_lines": 441,
            "excluded_lines": 12,
            "num_branches": 576,
            "num_partial_branches": 4,
            "covered_branches": 464,
            "missing_branches": 108,
        },
    }
)


# --------------------------------------------------------------------------
# JUnit
# --------------------------------------------------------------------------


def test_a_report_is_read_into_counts_that_add_up() -> None:
    """One of each outcome, so no counter can be conflated with another."""
    outcome, _ = junit.parse(JUNIT_XML)
    assert (outcome.collected, outcome.passed, outcome.failed) == (4, 1, 1)
    assert (outcome.errors, outcome.skipped) == (1, 1)
    assert outcome.passed + outcome.failed + outcome.errors + outcome.skipped == outcome.collected


def test_the_suite_duration_comes_from_the_header_and_not_the_sum() -> None:
    """A suite total includes time no individual test is charged for.

    The four cases below sum to 2.35s while the suite reports 2.5s, so a
    implementation that added the cases up would produce a different number and
    this would catch it.
    """
    outcome, durations = junit.parse(JUNIT_XML)
    assert outcome.duration_seconds == pytest.approx(2.5)
    assert sum(item.seconds for item in durations) == pytest.approx(2.35)


def test_a_report_whose_root_is_the_suite_itself_is_read() -> None:
    """`junit_family` and pytest version decide whether there is a wrapper.

    Reading only the wrapped form would break silently on a configuration
    change, and the fix would be found by nobody until the evidence was empty.
    """
    outcome, _ = junit.parse('<testsuite name="globin" tests="0" time="0.0"></testsuite>')
    assert outcome.collected == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("<testsuite", "not well-formed", id="truncated"),
        pytest.param("", "not well-formed", id="empty"),
        pytest.param("<html><body>oops</body></html>", "no <testsuite>", id="not a report"),
    ],
)
def test_an_unreadable_report_is_refused_by_name(text: str, expected: str) -> None:
    """A corrupt report must not be read as a run in which nothing failed."""
    with pytest.raises(EvidenceError, match=expected):
        junit.parse(text)


def test_a_case_with_no_usable_time_is_counted_but_charged_nothing() -> None:
    """A missing duration must not discard the outcome counts.

    The counts decide the verdict and the durations are diagnostic, so losing
    the second is a much smaller loss than refusing the first.
    """
    outcome, durations = junit.parse(
        '<testsuite tests="2" time="x">'
        '<testcase classname="c" name="a"/>'
        '<testcase classname="c" name="b" time="not-a-number"/>'
        "</testsuite>"
    )
    assert outcome.collected == 2
    assert outcome.duration_seconds == 0.0
    assert [item.seconds for item in durations] == [0.0, 0.0]


def test_a_case_without_a_classname_still_has_a_name() -> None:
    """The node ID is for reading, so it degrades rather than raising."""
    _, durations = junit.parse('<testsuite tests="1" time="0"><testcase name="bare"/></testsuite>')
    assert durations[0].node_id == "bare"


def test_the_slowest_tests_are_ordered_and_ties_broken_by_name() -> None:
    """Determinism: two tests of equal duration must not swap between runs."""
    durations = (
        junit.TestDuration(node_id="z", seconds=1.0),
        junit.TestDuration(node_id="a", seconds=1.0),
        junit.TestDuration(node_id="m", seconds=9.0),
    )
    assert [item.node_id for item in junit.slowest(durations, limit=3)] == ["m", "a", "z"]


@pytest.mark.parametrize("limit", [0, -1])
def test_asking_for_no_slow_tests_returns_none(limit: int) -> None:
    """The boundary, so the limit cannot become "all of them" by accident."""
    assert junit.slowest((junit.TestDuration(node_id="a", seconds=1.0),), limit=limit) == ()


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------


def test_a_coverage_report_is_read_without_recomputing_anything() -> None:
    """Every figure comes from the file, including the one the gate compares."""
    measured = coverage_report.parse(COVERAGE_JSON)
    assert measured.percent_covered == pytest.approx(80.328)
    assert (measured.covered_lines, measured.num_statements) == (1794, 2235)
    assert (measured.covered_branches, measured.num_branches) == (464, 576)
    assert measured.branch_enabled is True


def test_a_report_without_branch_figures_says_so_rather_than_guessing() -> None:
    """Branch coverage off is a configuration answer, not a parse failure."""
    measured = coverage_report.parse(
        json.dumps({"totals": {"covered_lines": 1, "num_statements": 2, "percent_covered": 50.0}})
    )
    assert measured.branch_enabled is False
    assert measured.num_branches is None
    assert measured.covered_branches is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("{", "not valid JSON", id="truncated"),
        pytest.param("[]", "must be a JSON object", id="not an object"),
        pytest.param("{}", "carries no 'totals'", id="no totals"),
        pytest.param('{"totals": []}', "carries no 'totals'", id="totals is not an object"),
        pytest.param('{"totals": {"covered_lines": 1}}', "omit", id="truncated totals"),
    ],
)
def test_an_unreadable_coverage_report_is_refused_by_name(text: str, expected: str) -> None:
    """Unmeasured coverage must never be reported as zero coverage.

    `QUALITY_GATES.md`: a gate is passed, failed, or not run, and "not run"
    never reports as "passed". Defaulting a missing total to zero would collapse
    the third state into the second.
    """
    with pytest.raises(EvidenceError, match=expected):
        coverage_report.parse(text)


# --------------------------------------------------------------------------
# Checksums
# --------------------------------------------------------------------------


def test_a_checksum_manifest_is_sorted_and_self_excluding() -> None:
    """Two runs over the same files must produce the same bytes."""
    rendered = checksums.render({"b.json": b"two", "a.xml": b"one"})
    names = [line.split("  ", 1)[1] for line in rendered.splitlines()]
    assert names == ["a.xml", "b.json"]
    assert "checksums.sha256" not in rendered


def test_an_empty_manifest_renders_as_nothing_rather_than_a_blank_line() -> None:
    """The edge case a `join` on an empty list gets wrong."""
    assert checksums.render({}) == ""


def test_a_manifest_round_trips() -> None:
    """What is written is what is read, which is what makes verification mean anything."""
    entries = {"a.xml": b"one", "b.json": b"two"}
    assert checksums.load(checksums.render(entries)) == {
        name: checksums.digest(payload) for name, payload in entries.items()
    }


def test_verification_passes_when_nothing_changed() -> None:
    """The success path, so the failure paths below mean something."""
    entries = {"a.xml": b"one", "b.json": b"two"}
    assert checksums.verify(checksums.load(checksums.render(entries)), entries) == ()


def test_a_tampered_file_fails_verification_and_names_both_digests() -> None:
    """The whole reason the checksum file exists.

    A reader who is told only "something changed" has to diff by hand; one who
    is given both digests can tell corruption from an edit.
    """
    recorded = checksums.load(checksums.render({"a.xml": b"one"}))
    problems = checksums.verify(recorded, {"a.xml": b"tampered"})
    assert len(problems) == 1
    assert "contents changed" in problems[0]


@pytest.mark.parametrize(
    ("recorded", "present", "expected"),
    [
        pytest.param({"a": b"x"}, {}, "recorded but missing", id="file gone"),
        pytest.param({}, {"a": b"x"}, "present but not recorded", id="file appeared"),
    ],
)
def test_verification_reports_a_file_on_only_one_side(
    recorded: dict[str, bytes], present: dict[str, bytes], expected: str
) -> None:
    """An unrecorded file matters as much as a missing one.

    An artifact containing something nobody listed is an artifact nobody has
    checked, so it is reported rather than ignored.
    """
    manifest_text = checksums.render(recorded)
    problems = checksums.verify(checksums.load(manifest_text), present)
    assert any(expected in line for line in problems)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("nonsense", "malformed", id="no separator"),
        pytest.param("abc  a.xml", "malformed", id="digest too short"),
        pytest.param(f"{'0' * 64}  a\n{'1' * 64}  a", "more than once", id="duplicate name"),
    ],
)
def test_a_malformed_checksum_manifest_is_refused(text: str, expected: str) -> None:
    """A duplicate is refused rather than resolved by last-wins.

    Two digests for one path describes something that cannot be true, and
    picking one would be inventing an answer.
    """
    with pytest.raises(EvidenceError, match=expected):
        checksums.load(text)


def test_blank_lines_in_a_checksum_manifest_are_ignored() -> None:
    """Trailing newlines are how text files end; they are not entries."""
    assert checksums.load(f"{'0' * 64}  a.xml\n\n") == {"a.xml": "0" * 64}


def test_a_relative_name_uses_forward_slashes_whatever_produced_it() -> None:
    """A manifest written on Windows must verify on POSIX and compare equal."""
    from pathlib import PureWindowsPath

    root = PureWindowsPath(r"C:\work\evidence")
    assert checksums.relative_name(root / "sub" / "a.xml", root=root) == "sub/a.xml"


def test_a_path_outside_the_evidence_directory_is_refused() -> None:
    """An absolute path would carry a user name into a published file."""
    from pathlib import PurePosixPath

    with pytest.raises(EvidenceError, match="not inside"):
        checksums.relative_name(PurePosixPath("/etc/passwd"), root=PurePosixPath("/work"))


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("api_key = NOT-A-REAL-SECRET-0000", id="an assignment"),
        pytest.param('"token": "NOT-A-REAL-TOKEN-0000"', id="a JSON field"),
        pytest.param("Authorization: Bearer NOT-A-REAL-BEARER-0000", id="a bearer token"),
        pytest.param(PRIVATE_KEY_MARKER, id="a private key"),
        pytest.param("https://user:NOT-A-REAL-PASSWORD@example.com/x", id="credentials in a URL"),
        pytest.param("PASSWORD=NOT-A-REAL-PASSWORD", id="an environment variable"),
    ],
)
def test_secret_shaped_content_is_found(line: str) -> None:
    """Each shape the check claims to catch, caught."""
    assert redaction.scan("a.xml", line)


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("token = ''", id="an empty value"),
        pytest.param("secret: null", id="a null value"),
        pytest.param("the api_key is never written here", id="prose"),
        pytest.param('"collected": 1203', id="an ordinary manifest field"),
    ],
)
def test_ordinary_content_is_not_reported(line: str) -> None:
    """The other half of the guard.

    A check that flagged `token = ''` would be turned off within a week, which
    would be worse than not having it.
    """
    assert redaction.scan("a.xml", line) == ()


def test_a_finding_names_the_field_without_reproducing_the_value() -> None:
    """Printing the suspected secret would be the whole failure, committed by
    the check meant to prevent it."""
    findings = redaction.scan("evidence-manifest.json", "\n\napi_key = NOT-A-REAL-SECRET-0000")
    assert findings[0].line == 3
    assert "NOT-A-REAL-SECRET-0000" not in redaction.describe(findings)
    assert "api_key" in redaction.describe(findings)


def test_findings_are_described_in_a_stable_order() -> None:
    """Two runs over the same files must report identically."""
    findings = (
        redaction.Finding(source="b", line=2, description="second"),
        redaction.Finding(source="a", line=1, description="first"),
    )
    assert redaction.describe(findings).splitlines() == ["  a:1: first", "  b:2: second"]


# --------------------------------------------------------------------------
# The manifest
# --------------------------------------------------------------------------


def _document() -> dict[str, object]:
    """A minimal, internally consistent manifest."""
    return manifest.build(
        run={"collected": 2, "passed": 2, "failed": 0, "errors": 0, "skipped": 0},
        timing={"duration_seconds": 1.5, "slow_tests": []},
    )


def test_a_manifest_round_trips_through_its_own_rendering() -> None:
    """Building, rendering and loading agree, or none of the rest matters."""
    document = _document()
    assert manifest.load(manifest.render(document)) == document


def test_rendering_is_byte_stable_regardless_of_key_order() -> None:
    """Two writers must not disagree about bytes, or the digest is meaningless."""
    first = manifest.render({"b": 1, "a": 2})
    second = manifest.render({"a": 2, "b": 1})
    assert first == second
    assert first.endswith("\n")
    assert first.isascii()


def test_an_edited_manifest_fails_its_own_digest() -> None:
    """Tamper detection, which is what makes this evidence rather than a note."""
    document = _document()
    run = document["run"]
    assert isinstance(run, dict)
    run["passed"] = 99
    with pytest.raises(EvidenceError, match="has been edited or truncated"):
        manifest.load(manifest.render(document))


def test_a_manifest_from_a_future_schema_version_is_refused() -> None:
    """Reading a document written by a newer tool would be guessing at its shape."""
    document = _document()
    document["schema_version"] = manifest.SCHEMA_VERSION + 1
    document["digest"] = manifest.digest(document)
    with pytest.raises(EvidenceError, match="Regenerate it rather than reading"):
        manifest.load(manifest.render(document))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("{", "not valid JSON", id="truncated"),
        pytest.param("[]", "must be a JSON object", id="not an object"),
        pytest.param('{"schema": "other"}', "not a globin.evidence", id="another document"),
    ],
)
def test_something_that_is_not_a_manifest_is_refused_by_name(text: str, expected: str) -> None:
    """A shard manifest fed to this reader is refused by name, not by a key error."""
    with pytest.raises(EvidenceError, match=expected):
        manifest.load(text)


def test_consistent_counts_report_nothing() -> None:
    """The success path for the arithmetic check."""
    run = {"collected": 4, "passed": 1, "failed": 1, "errors": 1, "skipped": 1}
    assert manifest.counts_are_consistent(run) == ()


@pytest.mark.parametrize(
    ("run", "expected"),
    [
        pytest.param(
            {"collected": 9, "passed": 1, "failed": 0, "errors": 0, "skipped": 0},
            "one of them is wrong",
            id="outcomes do not sum",
        ),
        pytest.param(
            {"collected": 0, "passed": -1, "failed": 0, "errors": 0, "skipped": 1},
            "is negative",
            id="a negative count",
        ),
        pytest.param(
            {"collected": 1, "passed": "1", "failed": 0, "errors": 0, "skipped": 0},
            "not an integer",
            id="a count that is text",
        ),
        pytest.param(
            {"collected": 1, "passed": True, "failed": 0, "errors": 0, "skipped": 0},
            "not an integer",
            id="a boolean where a count belongs",
        ),
    ],
)
def test_inconsistent_counts_are_reported(run: dict[str, object], expected: str) -> None:
    """`bool` is refused explicitly, because `isinstance(True, int)` is true."""
    problems = manifest.counts_are_consistent(run)
    assert any(expected in line for line in problems)


# --------------------------------------------------------------------------
# The step summary
# --------------------------------------------------------------------------


def test_a_summary_reports_the_verdict_and_the_numbers() -> None:
    """What somebody reads on a phone before deciding whether to care."""
    document = manifest.build(
        run={
            "collected": 1203,
            "passed": 1203,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "profile": "full",
            "platform": "Windows",
            "python_version": "3.14.5",
            "git_sha": "abc123",
            "percent_covered": 99.47,
            "coverage_threshold": 95.0,
            "coverage_gate_passed": True,
            "test_gate_passed": True,
            "artifacts": ["a.xml"],
        },
        timing={
            "duration_seconds": 31.7,
            "slow_tests": [{"node_id": "tests.unit.test_a::test_slow", "seconds": 1.4}],
        },
    )
    rendered = summary.render(document)
    assert "**PASSED**" in rendered
    assert "| Collected | 1203 |" in rendered
    assert "99.47% (floor 95.0%)" in rendered
    assert "test_slow" in rendered
    assert rendered.isascii(), "a Windows console codepage must be able to print this"


def test_a_failing_run_is_reported_as_failing() -> None:
    """The verdict has to be visible without reading the table."""
    document = manifest.build(
        run={"test_gate_passed": False, "coverage_gate_passed": True},
        timing={"duration_seconds": 1.0},
    )
    assert "**FAILED**" in summary.render(document)


def test_an_unmeasured_gate_renders_as_not_run() -> None:
    """`QUALITY_GATES.md` allows three states, and this is the third."""
    document = manifest.build(
        run={"test_gate_passed": True, "coverage_gate_passed": None},
        timing={"duration_seconds": 1.0},
    )
    rendered = summary.render(document)
    assert "not run" in rendered
    assert "not measured" in rendered


def test_a_summary_survives_a_manifest_missing_its_sections() -> None:
    """A summary that crashed would take the diagnostics with it.

    The manifest is validated where it is loaded; rendering degrades instead of
    adding a second place the evidence can be lost.
    """
    rendered = summary.render({"schema": manifest.SCHEMA})
    assert "**FAILED**" in rendered
    assert "?" in rendered


# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------


def test_no_argument_means_run() -> None:
    """The common case is the default, so the usual invocation is the short one."""
    assert parse([]) == "run"


@pytest.mark.parametrize("command", ["run", "verify"])
def test_each_command_is_recognised(command: str) -> None:
    assert parse([command]) == command


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["run", "verify"], id="two commands"),
        pytest.param(["verfiy"], id="a typo"),
        pytest.param(["--reports=x"], id="an option this CLI does not have"),
    ],
)
def test_anything_else_is_refused_rather_than_ignored(argv: list[str]) -> None:
    """A typo that silently ran the default would produce evidence nobody verified."""
    with pytest.raises(UsageError):
        parse(argv)


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_prints_usage_and_succeeds(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    """Asking for help is not an error."""
    assert main([flag]) == 0
    assert "usage: python -m tools.quality.evidence" in capsys.readouterr().out


def test_an_unusable_command_line_exits_two_and_says_why(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exit 2 is `EXIT_USAGE`, matching `tools/quality`'s own convention."""
    from tools.quality.evidence.gate import EXIT_USAGE

    assert main(["nonsense"]) == EXIT_USAGE
    printed = capsys.readouterr().out
    assert "unknown command" in printed
    assert USAGE in printed
