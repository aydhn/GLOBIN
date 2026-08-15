"""The aggregate gate composed with real files and a real environment.

``tests/unit/test_workflow.py`` checks the pure pieces. This runs the gate itself
against an evidence bundle on disk and a workflow context in the environment, and
checks the thing that actually matters: **which exit code comes out.**

The table below is the contract, and every row is a test:

===========================  ==================================  ====
This run                     What it means                       Exit
===========================  ==================================  ====
Everything passed            The tree is good                    0
A required job failed        A test or a tool said no            1
A required job was skipped   Nothing established anything        3
A required job was cancelled Nothing established anything        3
A required job never reported It was deleted or never ran        3
No context, but in CI        The gate was given nothing          3
Evidence absent              Nothing to check the run against    3
Evidence unreadable          As above, and worse                 3
Evidence missing a gate      The run stopped part way            3
An evidence gate failed      A gate said no                      1
===========================  ==================================  ====

Environment variables are set through ``monkeypatch`` rather than directly, so
the autouse isolation fixture in ``conftest.py`` does not report the test as
leaking process state.
"""

import json
from pathlib import Path

import pytest

from tools.quality.evidence.manifest import build as build_manifest
from tools.quality.evidence.manifest import render as render_manifest
from tools.quality.workflow.gate import (
    AGGREGATE_FILE,
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    expected_gates,
    read_aggregate,
    run_aggregate,
)
from tools.quality.workflow.plan import (
    CI_VARIABLE,
    DIGEST_VARIABLE,
    NEEDS_VARIABLE,
    WorkflowError,
    load_configuration,
)

REQUIRED_JOBS = load_configuration().required_jobs


def _manifest(**gates: bool | None) -> str:
    """A rendered evidence manifest recording a verdict for every expected gate.

    Args:
        gates: Overrides, by gate name. A gate given ``None`` is recorded as
            never having said, which is what a gate that did not run leaves.

    Returns:
        The manifest text.
    """
    recorded: dict[str, object] = {
        name: {"exit_code": 0, "passed": gates.get(name, True), "findings": 0}
        for name in expected_gates()
    }
    return render_manifest(build_manifest(run={}, gates=recorded, timing={}))


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    """An evidence directory holding a manifest in which every gate passed."""
    directory = tmp_path / "evidence"
    directory.mkdir()
    (directory / "evidence-manifest.json").write_text(_manifest(), encoding="utf-8")
    return directory


@pytest.fixture
def reports(tmp_path: Path) -> Path:
    """Where the aggregate is written."""
    return tmp_path / "workflow"


def _context(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    """Put a workflow context in the environment, defaulting every job to success."""
    results = {job: overrides.get(job, "success") for job in REQUIRED_JOBS}
    context = {job: {"result": result, "outputs": {}} for job, result in results.items()}
    monkeypatch.setenv(NEEDS_VARIABLE, json.dumps(context))


def _verdict(reports: Path) -> str:
    """The verdict the aggregate wrote."""
    return str(read_aggregate(reports / AGGREGATE_FILE)["verdict"])


# --------------------------------------------------------------------------
# The exit-code contract
# --------------------------------------------------------------------------


def test_a_run_in_which_everything_passed_exits_zero(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """The only path to a pass."""
    _context(monkeypatch)
    assert run_aggregate(reports=reports, evidence=evidence) == EXIT_OK
    assert _verdict(reports) == "passed"


def test_a_failed_required_job_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """A test or a tool said no, and the evidence agreeing does not rescue it."""
    _context(monkeypatch, shards="failure")
    assert run_aggregate(reports=reports, evidence=evidence) == EXIT_GATE_FAILED
    assert _verdict(reports) == "failed"


@pytest.mark.parametrize("result", ["skipped", "cancelled", "neutral", ""])
def test_a_required_job_that_established_nothing_is_never_a_pass(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path, result: str
) -> None:
    """The failure mode the package exists for.

    GitHub reports a skipped job's check as something other than a failure, so a
    rule trusting the check view alone would be satisfied here. This is the
    assertion that says it is not.
    """
    _context(monkeypatch, mutation=result)
    assert run_aggregate(reports=reports, evidence=evidence) == EXIT_UNMEASURED
    assert _verdict(reports) == "unmeasured"


def test_a_required_job_missing_from_the_context_is_never_a_pass(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """A job deleted from the workflow reports nothing at all."""
    present = {job: {"result": "success"} for job in REQUIRED_JOBS[:-1]}
    monkeypatch.setenv(NEEDS_VARIABLE, json.dumps(present))
    assert run_aggregate(reports=reports, evidence=evidence) == EXIT_UNMEASURED


def test_an_empty_context_in_ci_is_never_a_pass(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """Asked to aggregate, and given nothing to aggregate."""
    monkeypatch.delenv(NEEDS_VARIABLE, raising=False)
    monkeypatch.setenv(CI_VARIABLE, "true")
    assert run_aggregate(reports=reports, evidence=evidence) == EXIT_UNMEASURED


def test_a_malformed_context_is_never_a_pass(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """Guard the checker with its failing case."""
    monkeypatch.setenv(NEEDS_VARIABLE, "{not json")
    assert run_aggregate(reports=reports, evidence=evidence) == EXIT_UNMEASURED


def test_unmeasured_outranks_failed(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """A run with both reports the more alarming fact.

    A failed job says a test broke. A skipped one says this run cannot tell you
    whether one did, which casts doubt on the jobs that passed as well.
    """
    _context(monkeypatch, shards="failure", mutation="skipped")
    assert run_aggregate(reports=reports, evidence=evidence) == EXIT_UNMEASURED


# --------------------------------------------------------------------------
# The published evidence
# --------------------------------------------------------------------------


def test_a_failed_evidence_gate_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """Every job can pass and the evidence still say a gate did not."""
    (evidence / "evidence-manifest.json").write_text(_manifest(lint=False), encoding="utf-8")
    _context(monkeypatch)
    assert run_aggregate(reports=reports, evidence=evidence) == EXIT_GATE_FAILED


def test_an_evidence_gate_that_did_not_say_is_never_a_pass(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """ADR-0040's third state, carried through to the aggregate."""
    (evidence / "evidence-manifest.json").write_text(_manifest(typing=None), encoding="utf-8")
    _context(monkeypatch)
    assert run_aggregate(reports=reports, evidence=evidence) == EXIT_UNMEASURED


def test_absent_evidence_is_never_a_pass(
    monkeypatch: pytest.MonkeyPatch, reports: Path, tmp_path: Path
) -> None:
    """Evidence that was not found is never read as evidence that probably passed."""
    _context(monkeypatch)
    assert run_aggregate(reports=reports, evidence=tmp_path / "nothing") == EXIT_UNMEASURED


def test_an_unreadable_manifest_is_never_a_pass(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """Covers a wrong schema, an unsupported version and a broken digest at once."""
    (evidence / "evidence-manifest.json").write_text("{}", encoding="utf-8")
    _context(monkeypatch)
    assert run_aggregate(reports=reports, evidence=evidence) == EXIT_UNMEASURED


def test_a_tampered_manifest_is_never_a_pass(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """Editing a verdict without recomputing the digest does not go unnoticed."""
    path = evidence / "evidence-manifest.json"
    document = json.loads(_manifest(lint=False))
    document["gates"]["lint"]["passed"] = True
    path.write_text(json.dumps(document), encoding="utf-8")
    _context(monkeypatch)
    assert run_aggregate(reports=reports, evidence=evidence) == EXIT_UNMEASURED


def test_a_manifest_missing_a_gate_is_never_a_pass(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """What an evidence run that crashed part way through leaves behind.

    The manifest parses and its digest is correct. It simply describes fewer
    gates than the run is supposed to produce, and a reader checking only that
    everything present passed would call it a clean run.
    """
    partial: dict[str, object] = {name: {"passed": True} for name in expected_gates()[:2]}
    text = render_manifest(build_manifest(run={}, gates=partial, timing={}))
    (evidence / "evidence-manifest.json").write_text(text, encoding="utf-8")
    _context(monkeypatch)
    assert run_aggregate(reports=reports, evidence=evidence) == EXIT_UNMEASURED


# --------------------------------------------------------------------------
# What it writes
# --------------------------------------------------------------------------


def test_the_aggregate_is_written_even_when_the_run_failed(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """The document explaining a failure is exactly the one somebody needs."""
    _context(monkeypatch, quality="failure")
    run_aggregate(reports=reports, evidence=evidence)
    document = read_aggregate(reports / AGGREGATE_FILE)
    assert document["verdict"] == "failed"
    assert "required job 'quality' is failed" in str(document["problems"])


def test_no_half_written_file_is_left_behind(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """The staged name is moved into place, never left where a reader would find it."""
    _context(monkeypatch)
    run_aggregate(reports=reports, evidence=evidence)
    assert [path.name for path in reports.iterdir()] == [AGGREGATE_FILE]


def test_writing_twice_replaces_rather_than_appends(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """``os.replace`` overwrites on Windows, where ``Path.rename`` would raise."""
    _context(monkeypatch)
    run_aggregate(reports=reports, evidence=evidence)
    _context(monkeypatch, hygiene="failure")
    run_aggregate(reports=reports, evidence=evidence)
    assert _verdict(reports) == "failed"


def test_the_artifact_digest_is_recorded_when_ci_supplies_one(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """It is learned after the upload, so this is the only route it can take."""
    monkeypatch.setenv(DIGEST_VARIABLE, "sha256:" + "ab" * 32)
    _context(monkeypatch)
    run_aggregate(reports=reports, evidence=evidence)
    run = read_aggregate(reports / AGGREGATE_FILE)["run"]
    assert isinstance(run, dict)
    assert run["artifact_digest"] == "sha256:" + "ab" * 32


def test_a_missing_digest_is_recorded_as_missing_rather_than_blank(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """A blank field reads as one somebody forgot to look at."""
    monkeypatch.delenv(DIGEST_VARIABLE, raising=False)
    _context(monkeypatch)
    run_aggregate(reports=reports, evidence=evidence)
    run = read_aggregate(reports / AGGREGATE_FILE)["run"]
    assert isinstance(run, dict)
    assert run["artifact_digest"] == "not recorded"


def test_the_step_summary_is_appended_when_github_asks_for_one(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path, tmp_path: Path
) -> None:
    """The same code path writes nothing when the variable is unset."""
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    _context(monkeypatch, evidence="failure")
    run_aggregate(reports=reports, evidence=evidence)
    text = summary.read_text(encoding="utf-8")
    assert "## GLOBIN quality gate" in text
    assert "**FAILED**" in text
    assert "python -m tools.quality full" in text


def test_nothing_is_written_when_github_asks_for_no_summary(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path, tmp_path: Path
) -> None:
    """The local case, which must not require a variable to be set."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    _context(monkeypatch)
    run_aggregate(reports=reports, evidence=evidence)
    assert not (tmp_path / "summary.md").exists()


def test_the_written_document_names_no_absolute_path(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """A published document must carry neither a user name nor a runner's layout."""
    _context(monkeypatch)
    run_aggregate(reports=reports, evidence=evidence)
    text = (reports / AGGREGATE_FILE).read_text(encoding="utf-8")
    assert "C:\\" not in text
    assert str(evidence) not in text


def test_a_reader_refuses_an_aggregate_from_a_later_version(
    monkeypatch: pytest.MonkeyPatch, reports: Path, evidence: Path
) -> None:
    """The rule ADR-0041 states for everything GLOBIN persists, applied to this."""
    _context(monkeypatch)
    run_aggregate(reports=reports, evidence=evidence)
    path = reports / AGGREGATE_FILE
    document = json.loads(path.read_text(encoding="utf-8"))
    document["schema_version"] = 99
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(WorkflowError, match="will not guess"):
        read_aggregate(path)


def test_a_reader_refuses_a_document_announcing_another_schema(reports: Path) -> None:
    """An evidence manifest fed to the aggregate reader is refused by name."""
    reports.mkdir(parents=True)
    path = reports / AGGREGATE_FILE
    path.write_text(_manifest(), encoding="utf-8")
    with pytest.raises(WorkflowError, match="announces schema"):
        read_aggregate(path)
