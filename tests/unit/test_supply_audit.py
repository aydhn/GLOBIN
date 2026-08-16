"""The vulnerability audit's judgement, tested without running the audit.

``run`` starts a process and reaches an advisory service, so it is never called
here — ADR-0024 makes the suite offline. Everything that decides anything is
:func:`parse`, :func:`classify_failure` and :func:`requirements`, and all three
map values to values.

The property worth asserting most is negative: **no path through this module
turns a failed audit into a clean one.**
"""

import json
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from tools.quality.supply import audit
from tools.quality.supply.waivers import OPEN, WAIVED, Waiver

CLEAN = json.dumps({"dependencies": [{"name": "ruff", "version": "0.15.14", "vulns": []}]})

VULNERABLE = json.dumps(
    {
        "dependencies": [
            {
                "name": "example",
                "version": "1.2.3",
                "vulns": [
                    {"id": "GHSA-aaaa-bbbb-cccc", "fix_versions": ["1.2.4"]},
                ],
            },
            {"name": "ruff", "version": "0.15.14", "vulns": []},
        ]
    }
)

WAIVER = Waiver(
    vulnerability="GHSA-aaaa-bbbb-cccc",
    package="example",
    ecosystem="pypi",
    affected="==1.2.3",
    reason="No reachable code path.",
    owner="aydhn",
    created=date(2026, 8, 15),
    expires=date(2026, 11, 15),
    compensating_control="Development-only, never runs in CI.",
    reference="https://github.com/advisories/GHSA-aaaa-bbbb-cccc",
)


def test_a_clean_result_produces_no_findings() -> None:
    """The baseline, so the negatives below mean something."""
    assert audit.parse(CLEAN, ()) == ()


def test_a_finding_is_read_with_its_fix_versions() -> None:
    """What was found, against which version, and what resolves it."""
    (found,) = audit.parse(VULNERABLE, ())
    assert found.package == "example"
    assert found.version == "1.2.3"
    assert found.identifier == "GHSA-aaaa-bbbb-cccc"
    assert found.fix_versions == ("1.2.4",)
    assert found.disposition == OPEN


def test_a_waiver_marks_a_finding_without_removing_it() -> None:
    """The point of a register is to read later what was accepted and by whom.

    A waiver that deleted the finding would make that impossible, so the
    disposition changes and everything else survives.
    """
    (found,) = audit.parse(VULNERABLE, (WAIVER,))
    assert found.disposition == WAIVED
    assert found.waiver_owner == "aydhn"
    assert found.identifier == "GHSA-aaaa-bbbb-cccc"


def test_a_waiver_for_another_package_does_not_cover_this_finding() -> None:
    """Both the advisory and the package must match, or a waiver would over-reach."""
    (found,) = audit.parse(VULNERABLE, (replace(WAIVER, package="different"),))
    assert found.disposition == OPEN

    (found,) = audit.parse(VULNERABLE, (replace(WAIVER, vulnerability="CVE-2026-0001"),))
    assert found.disposition == OPEN


def test_unparseable_output_raises_rather_than_reporting_nothing() -> None:
    """No findings and unparseable output must not produce the same value.

    Returning an empty tuple for output that could not be read would report a run
    that examined nothing as a run that found nothing.
    """
    with pytest.raises(ValueError, match="not JSON"):
        audit.parse("<html>503</html>", ())
    with pytest.raises(ValueError, match="without a 'dependencies' array"):
        audit.parse('{"results": []}', ())


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        pytest.param("Connection refused", audit.Outcome.SERVICE_UNREACHABLE, id="connection"),
        pytest.param("Read timed out", audit.Outcome.SERVICE_UNREACHABLE, id="timeout"),
        pytest.param(
            "Max retries exceeded with url", audit.Outcome.SERVICE_UNREACHABLE, id="retries"
        ),
        pytest.param(
            "certificate verify failed", audit.Outcome.SERVICE_UNREACHABLE, id="certificate"
        ),
        pytest.param(
            "Dependency not found on PyPI", audit.Outcome.COLLECTION_FAILED, id="collection"
        ),
        pytest.param("something else entirely", audit.Outcome.COLLECTION_FAILED, id="unknown"),
    ],
)
def test_no_failure_is_ever_classified_as_clean(stderr: str, expected: audit.Outcome) -> None:
    """The property the module exists for.

    A scanner has three possible results and two of them look alike from a
    distance. Every branch here returns something that is not
    :attr:`Outcome.CLEAN`, and the message says so in words as well.
    """
    outcome, detail = audit.classify_failure(1, stderr)
    assert outcome is expected
    assert outcome is not audit.Outcome.CLEAN
    assert "NOT a clean audit" in detail


@pytest.mark.parametrize(
    ("outcome", "measured"),
    [
        pytest.param(audit.Outcome.CLEAN, True, id="clean"),
        pytest.param(audit.Outcome.VULNERABLE, True, id="vulnerable"),
        pytest.param(audit.Outcome.TOOL_MISSING, False, id="tool missing"),
        pytest.param(audit.Outcome.COLLECTION_FAILED, False, id="collection failed"),
        pytest.param(audit.Outcome.SERVICE_UNREACHABLE, False, id="service unreachable"),
        pytest.param(audit.Outcome.UNREADABLE, False, id="unreadable"),
    ],
)
def test_only_a_completed_audit_counts_as_measured(outcome: audit.Outcome, measured: bool) -> None:
    """Four of the six outcomes mean the question was never answered.

    The gate reads an unmeasured audit as a failure rather than as an absence of
    findings, which is what makes the distinction load-bearing rather than
    decorative.
    """
    assert audit.Report(outcome=outcome).measured is measured


def test_the_open_count_excludes_waived_findings_but_the_report_does_not() -> None:
    """A waived finding has been decided about; an open one has not.

    Only the open count fails the gate. Both appear in the report.
    """
    report = audit.Report(
        outcome=audit.Outcome.VULNERABLE, vulnerabilities=audit.parse(VULNERABLE, (WAIVER,))
    )
    assert report.open_count == 0
    assert len(report.vulnerabilities) == 1


def test_the_audit_reads_the_lock_and_resolves_nothing(tmp_path: Path) -> None:
    """Since Phase 020 the audited set is the locked set.

    Before it, this module wrote a requirements file from the inventory's exact
    pins and let `pip-audit` resolve it against a live index *at audit time* — so
    the report described a resolution nobody had installed, and two runs on one
    commit could disagree. `--locked` resolves nothing, so the audited set and the
    set `scripts/bootstrap.ps1` installs are the same set.

    Asserted through the argv, because that is where the change lives. `--strict`
    is checked here too: without it a package whose version cannot be determined
    is skipped, and skipped is counted as fine.
    """
    seen: list[list[str]] = []

    def record(argv: list[str], **_kwargs: object) -> "subprocess.CompletedProcess[str]":
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=CLEAN, stderr="")

    audit.run(tmp_path, (), runner=record)
    assert seen, "pip-audit was never started"
    assert "--locked" in seen[0]
    assert str(tmp_path) in seen[0]
    assert "--strict" in seen[0]
    assert "--fix" not in seen[0]
    assert not any(argument.endswith("requirements.txt") for argument in seen[0])
