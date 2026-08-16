"""The two functions that start a child, driven by an injected runner.

``audit.run`` and ``capability.probe`` are the only places in the supply package
that leave the process, and until they were injectable the offline suite could
not reach them at all. Injection is the pattern ``tools/quality/evidence``
already established — ``test_evidence_end_to_end.py`` describes itself as "the
gate composed with an injected process runner" — and it is used here for the same
reason: a gate that can only be exercised with a network is a gate the suite
cannot cover.

The runners below are hand-written callables rather than mocks. `TESTING_STRATEGY.md`
makes a hand-written double the default and `create_autospec(..., spec_set=True)`
the exception, and nothing here needs the exception: what is being substituted is
one function with a known signature.

Every failure path checked here ends in something that is **not**
:attr:`~tools.quality.supply.audit.Outcome.CLEAN` and not
:attr:`~tools.quality.supply.capability.State.PASS`. That is the property worth
the machinery.
"""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.quality.supply import audit, capability
from tools.quality.supply.capability import State

PROJECT = Path()
"""Where `pip-audit --locked` is pointed.

Since Phase 020 the audit reads the locks in a project directory rather than a
requirements file synthesised from the inventory's pins. Every runner below is
injected, so nothing is actually read from here -- what is under test is how the
gate classifies what came back.
"""

CLEAN_PAYLOAD = json.dumps({"dependencies": [{"name": "ruff", "version": "0.15.14", "vulns": []}]})

VULNERABLE_PAYLOAD = json.dumps(
    {
        "dependencies": [
            {
                "name": "ruff",
                "version": "0.15.14",
                "vulns": [{"id": "GHSA-aaaa-bbbb-cccc", "fix_versions": ["0.15.15"]}],
            }
        ]
    }
)


def _runner(
    *, returncode: int = 0, stdout: str = "", stderr: str = "", raises: Exception | None = None
) -> audit.Runner:
    """A stand-in for :func:`subprocess.run` that returns what a test needs.

    Args:
        returncode: What the child should appear to have returned.
        stdout: What it printed.
        stderr: What it complained about.
        raises: An exception to raise instead of returning, for the paths where
            the child could not be started at all.

    Returns:
        The callable, accepting and ignoring the real signature's arguments.
    """

    def run(argv: Sequence[str], **_: object) -> subprocess.CompletedProcess[str]:
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(list(argv), returncode, stdout, stderr)

    return run


# ---------------------------------------------------------------------------
# The audit
# ---------------------------------------------------------------------------


def test_a_clean_child_produces_a_clean_report() -> None:
    """Exit 0 with a parseable payload and no advisories."""
    report = audit.run(PROJECT, (), runner=_runner(stdout=CLEAN_PAYLOAD))
    assert report.outcome is audit.Outcome.CLEAN
    assert report.measured
    assert report.audited == 1
    assert report.open_count == 0


def test_a_finding_produces_a_vulnerable_report() -> None:
    """Exit 1 with a payload naming an advisory."""
    report = audit.run(PROJECT, (), runner=_runner(returncode=1, stdout=VULNERABLE_PAYLOAD))
    assert report.outcome is audit.Outcome.VULNERABLE
    assert report.measured
    assert report.open_count == 1


def test_exit_one_with_no_payload_is_a_collection_failure_not_a_finding() -> None:
    """The conflation `--strict` creates, and the reason it is handled explicitly.

    Exit 1 means "vulnerabilities found" *or*, under ``--strict``, "a dependency
    could not be audited" — and the second prints nothing to stdout. Reading an
    unparseable result as a finding count would report zero vulnerabilities from
    a run that never examined anything. This is the case that failed in practice
    against a local package on no index.
    """
    report = audit.run(
        PROJECT,
        (),
        runner=_runner(returncode=1, stdout="", stderr="binokx: Dependency not found on PyPI"),
    )
    assert report.outcome is audit.Outcome.COLLECTION_FAILED
    assert not report.measured
    assert "NOT a clean audit" in report.detail


def test_an_unexpected_exit_code_is_classified_rather_than_believed() -> None:
    """Only 0 and 1 are documented; anything else is a fault, not a verdict."""
    report = audit.run(PROJECT, (), runner=_runner(returncode=2, stderr="Connection refused"))
    assert report.outcome is audit.Outcome.SERVICE_UNREACHABLE
    assert not report.measured


def test_a_child_that_never_returns_is_not_a_clean_audit() -> None:
    """A timeout is the failure the bound exists for, and it is not silence."""
    report = audit.run(
        PROJECT,
        (),
        runner=_runner(raises=subprocess.TimeoutExpired(cmd="pip-audit", timeout=1)),
    )
    assert report.outcome is audit.Outcome.SERVICE_UNREACHABLE
    assert not report.measured


def test_a_child_that_cannot_be_started_is_not_a_clean_audit() -> None:
    """A missing interpreter or a permission error, reported as itself."""
    report = audit.run(PROJECT, (), runner=_runner(raises=OSError("no such file")))
    assert report.outcome is audit.Outcome.TOOL_MISSING
    assert not report.measured


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("<html>502 Bad Gateway</html>", id="not json"),
        pytest.param('{"results": []}', id="json of the wrong shape"),
    ],
)
def test_output_that_cannot_be_read_is_not_a_clean_audit(payload: str) -> None:
    """Guessing between "clean" and "vulnerable" with no evidence is not an option."""
    report = audit.run(PROJECT, (), runner=_runner(stdout=payload, stderr="something went wrong"))
    assert report.outcome is not audit.Outcome.CLEAN
    assert not report.measured


# ---------------------------------------------------------------------------
# The capability probe
# ---------------------------------------------------------------------------


def _response(status: int, body: str) -> str:
    """A ``gh api -i`` response: a status line, headers, a blank line, the body.

    Args:
        status: The HTTP status.
        body: The response body.

    Returns:
        The text ``gh`` would print.
    """
    return f"HTTP/2.0 {status}\r\nContent-Type: application/json\n\n{body}"


def test_every_control_is_asked_and_recorded() -> None:
    """One entry per control, with the evidence that established each."""
    states = capability.probe("aydhn/GLOBIN", runner=_runner(stdout=_response(204, "")))
    assert set(states) == {control.name for control in capability.CONTROLS}
    assert all(state is State.PASS for state, _ in states.values())


def test_a_plan_refusal_is_recorded_as_one_rather_than_as_a_failure() -> None:
    """The response that made this repository public."""
    body = json.dumps(
        {"message": "Upgrade to GitHub Pro or make this repository public to enable this feature."}
    )
    states = capability.probe("aydhn/GLOBIN", runner=_runner(stdout=_response(403, body)))
    assert all(state is State.UNAVAILABLE_BY_PLAN for state, _ in states.values())
    assert not capability.judge(states), "a plan ceiling is nobody's to fix from a commit"


def test_a_probe_that_cannot_run_is_an_error_rather_than_a_pass() -> None:
    """Not knowing why is a different fact from knowing why."""
    states = capability.probe("aydhn/GLOBIN", runner=_runner(raises=OSError("gh missing")))
    assert all(state is State.ERROR for state, _ in states.values())
    assert all(state is not State.PASS for state, _ in states.values())


def test_a_response_with_no_status_line_is_an_error() -> None:
    """``gh`` printing nothing recognisable is not a repository with a setting off."""
    states = capability.probe("aydhn/GLOBIN", runner=_runner(stdout="", stderr="boom"))
    assert all(state is State.ERROR for state, _ in states.values())


def test_the_probe_reports_not_probed_when_the_cli_is_absent() -> None:
    """Recorded rather than omitted, and never a pass.

    Reached without a runner, which is the one path where the real
    :func:`~tools.quality.supply.capability.available` decides — so this is
    skipped rather than faked when the CLI happens to be installed.
    """
    if capability.available():
        pytest.skip("the GitHub CLI is installed on this machine")
    states = capability.probe("aydhn/GLOBIN")
    assert all(state is State.NOT_PROBED for state, _ in states.values())
