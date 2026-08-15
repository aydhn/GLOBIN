"""The pure half of the aggregate gate, from literals.

Reading a job result, reading the declared configuration, assembling the document
and rendering the summary — none of which needs a workflow, a runner or a file.

The cases worth stating plainly are the ones where a permissive reading would
produce a green check for a run that established nothing:

* a required job **absent** from the context, which a mapping built from what
  reported would simply not mention;
* a result GitHub has not documented, which a lookup with a fallback would read
  as whatever the fallback was;
* a declared requirement that is absent, empty or the wrong type, which a reader
  with defaults would replace with an opinion nobody wrote down.

Reading a persisted aggregate back — including the refusal of a schema version
this code does not implement — is in
``tests/integration/test_workflow_end_to_end.py``, because it needs a file.
"""

import json

import pytest

from tools.quality.evidence.manifest import digest
from tools.quality.execution.plan import Verdict
from tools.quality.workflow.plan import (
    Configuration,
    WorkflowError,
    classify,
    job_verdicts,
    read_configuration,
    read_needs,
)
from tools.quality.workflow.report import (
    SCHEMA,
    SCHEMA_VERSION,
    build,
    render_document,
    render_summary,
)

REQUIRED = ("quality", "evidence")


def _settings(**overrides: object) -> dict[str, object]:
    """A well-formed ``[tool.globin.workflow]`` table, with overrides applied."""
    table: dict[str, object] = {
        "required_jobs": ["quality", "evidence"],
        "required_check": "Quality gate",
        "artifact": "test-evidence-windows-py314",
        "retention_days": 30,
        "timeouts": {"quality": 15, "evidence": 15},
    }
    table.update(overrides)
    return {"tool": {"globin": {"workflow": table}}}


def _context(**results: str) -> str:
    """A ``toJSON(needs)`` document naming each job's result."""
    return json.dumps({job: {"result": result, "outputs": {}} for job, result in results.items()})


def _document(verdict: Verdict = Verdict.PASSED, **overrides: object) -> dict[str, object]:
    """An aggregate document with one job and one gate."""
    document = build(
        run={"commit": "abc1234", "artifact": "bundle", "artifact_digest": "sha256:dead"},
        jobs={"quality": Verdict.PASSED},
        gates={"tests": {"passed": True, "findings": 0}},
        verdict=verdict,
    )
    document.update(overrides)
    return document


# --------------------------------------------------------------------------
# Reading a job result
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ("success", Verdict.PASSED),
        ("failure", Verdict.FAILED),
        ("cancelled", Verdict.UNMEASURED),
        ("skipped", Verdict.UNMEASURED),
    ],
)
def test_every_documented_job_result_is_read(result: str, expected: Verdict) -> None:
    """The four GitHub documents, and nothing is left to a default by accident."""
    assert classify(result) is expected


@pytest.mark.parametrize("result", ["neutral", "", None, 0, True, "SUCCESS"])
def test_an_undocumented_job_result_is_unmeasured(result: object) -> None:
    """The default is the decision.

    ``"SUCCESS"`` is in the list on purpose: a case-insensitive comparison would
    be a friendly-looking change that quietly widens what counts as a pass.
    """
    assert classify(result) is Verdict.UNMEASURED


def test_a_required_job_absent_from_the_context_is_unmeasured() -> None:
    """The case that motivates the package.

    A job deleted from the workflow reports nothing at all. A mapping built from
    what reported would not mention it, leaving every entry present and passing.
    """
    verdicts = job_verdicts({"quality": "success"}, required=REQUIRED)
    assert verdicts == {"quality": Verdict.PASSED, "evidence": Verdict.UNMEASURED}


def test_a_job_that_is_not_required_does_not_become_one() -> None:
    """Adding a job to the workflow must not silently add a requirement."""
    verdicts = job_verdicts(
        {"quality": "success", "evidence": "success", "extra": "failure"}, required=REQUIRED
    )
    assert set(verdicts) == set(REQUIRED)


def test_the_verdicts_follow_the_declared_order() -> None:
    """So a report reads in the order somebody wrote the requirements down."""
    assert list(job_verdicts({}, required=("b", "a"))) == ["b", "a"]


def test_the_context_is_read_into_results() -> None:
    """Only ``result`` is taken; a job's outputs are never copied."""
    assert read_needs(_context(quality="success", evidence="failure")) == {
        "quality": "success",
        "evidence": "failure",
    }


def test_a_job_entry_with_no_readable_result_reads_as_unmeasured() -> None:
    """A malformed entry is not a reason to believe the job passed."""
    results = read_needs('{"quality": {"outputs": {}}, "evidence": 7}')
    assert classify(results["quality"]) is Verdict.UNMEASURED
    assert classify(results["evidence"]) is Verdict.UNMEASURED


def test_a_context_that_is_not_json_is_refused() -> None:
    """Guard the checker with its failing case."""
    with pytest.raises(WorkflowError, match="not valid JSON"):
        read_needs("{oops")


def test_a_context_that_is_not_an_object_is_refused() -> None:
    """An array carries no job names, so nothing could be looked up in it."""
    with pytest.raises(WorkflowError, match="must be a JSON object"):
        read_needs("[1, 2]")


# --------------------------------------------------------------------------
# The declared configuration
# --------------------------------------------------------------------------


def test_the_configuration_is_read() -> None:
    """The shape every other test in this module assumes."""
    assert read_configuration(_settings()) == Configuration(
        required_jobs=("quality", "evidence"),
        required_check="Quality gate",
        artifact="test-evidence-windows-py314",
        retention_days=30,
        timeouts=(("quality", 15), ("evidence", 15)),
    )


def test_a_missing_table_is_refused() -> None:
    """Not defaulted. A gate with no configuration is a gate with no opinion."""
    with pytest.raises(WorkflowError, match=r"no \[tool.globin.workflow\] table"):
        read_configuration({"tool": {"globin": {}}})


def test_an_empty_required_list_is_refused() -> None:
    """An aggregate with nothing to require passes everything."""
    with pytest.raises(WorkflowError, match="passes everything"):
        read_configuration(_settings(required_jobs=[]))


@pytest.mark.parametrize("value", [["quality", 7], "quality", None])
def test_a_required_list_that_is_not_strings_is_refused(value: object) -> None:
    """Guard the checker with its failing case."""
    with pytest.raises(WorkflowError, match="required_jobs"):
        read_configuration(_settings(required_jobs=value))


@pytest.mark.parametrize("value", ["", None, 7])
def test_a_missing_or_empty_check_name_is_refused(value: object) -> None:
    """The check name reaches documentation and a branch protection rule."""
    with pytest.raises(WorkflowError, match="required_check"):
        read_configuration(_settings(required_check=value))


@pytest.mark.parametrize("value", [0, -1, True, "30", None])
def test_a_retention_that_is_not_a_positive_integer_is_refused(value: object) -> None:
    """``True`` is an ``int`` to :func:`isinstance` and would pass as one day."""
    with pytest.raises(WorkflowError, match="retention_days"):
        read_configuration(_settings(retention_days=value))


@pytest.mark.parametrize("value", [{}, None, [], "15", 15])
def test_a_missing_or_empty_timeout_table_is_refused(value: object) -> None:
    """Empty is not "no opinion"; it is every job left on GitHub's six-hour default."""
    with pytest.raises(WorkflowError, match="timeouts"):
        read_configuration(_settings(timeouts=value))


@pytest.mark.parametrize("value", [0, -1, True, "15", None, 1.5])
def test_a_timeout_that_is_not_a_positive_integer_is_refused(value: object) -> None:
    """Guard the checker with its failing case, ``True`` included for the reason above."""
    with pytest.raises(WorkflowError, match=r"timeouts\.quality"):
        read_configuration(_settings(timeouts={"quality": value}))


# --------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------


def test_the_document_announces_its_schema_and_version() -> None:
    """A consumer can tell an aggregate from an evidence manifest by reading it."""
    document = _document()
    assert document["schema"] == SCHEMA
    assert document["schema_version"] == SCHEMA_VERSION


def test_the_document_records_the_verdict_rather_than_leaving_it_derivable() -> None:
    """A consumer re-deriving it would be a second implementation of the rule."""
    assert _document(Verdict.FAILED)["verdict"] == "failed"


def test_the_document_is_sealed_against_editing() -> None:
    """Changing a section without changing the digest must not go unnoticed."""
    document = _document()
    sealed = document["digest"]
    document["verdict"] = "passed"
    document["jobs"] = {"quality": "passed", "evidence": "passed"}
    assert digest(document) != sealed


def test_the_same_values_render_to_the_same_bytes() -> None:
    """Determinism is what lets two runs of one tree be compared at all."""
    assert render_document(_document()) == render_document(_document())


def test_the_rendering_carries_no_absolute_path() -> None:
    """A published document must not name this machine's directories."""
    assert "C:\\" not in render_document(_document())
    assert "/Users/" not in render_document(_document())


# --------------------------------------------------------------------------
# The summary
# --------------------------------------------------------------------------


def test_the_summary_leads_with_the_verdict() -> None:
    """Read on a phone by somebody deciding whether to care."""
    assert "**PASSED**" in render_summary(_document())
    assert "**FAILED**" in render_summary(_document(Verdict.FAILED))


def test_the_summary_names_the_artifact_and_its_digest() -> None:
    """The digest is the artifact's identity, and it exists nowhere inside it."""
    summary = render_summary(_document())
    assert "bundle" in summary
    assert "sha256:dead" in summary


def test_the_summary_carries_the_commands_to_reproduce_it() -> None:
    """A failure page that does not say what to run next has done half its job."""
    summary = render_summary(_document(Verdict.FAILED))
    assert "python -m tools.quality full" in summary
    assert "python -m tools.quality aggregate" in summary


def test_the_summary_lists_the_problems_when_there_are_any() -> None:
    """The diagnosis, not merely the verdict."""
    summary = render_summary(
        _document(Verdict.FAILED, problems=["required job 'shards' is failed"])
    )
    assert "### What went wrong" in summary
    assert "required job 'shards' is failed" in summary


def test_the_summary_omits_the_problem_section_when_there_are_none() -> None:
    """An empty heading reads as a section somebody forgot to fill in."""
    assert "### What went wrong" not in render_summary(_document())


def test_a_gate_that_did_not_say_renders_as_not_run() -> None:
    """Never blank: "not run" reporting as anything else is what fails closed."""
    document = build(
        run={},
        jobs={"quality": Verdict.UNMEASURED},
        gates={"tests": {"exit_code": None}},
        verdict=Verdict.UNMEASURED,
    )
    summary = render_summary(document)
    assert summary.count("NOT RUN") == 2


def test_the_summary_is_ascii() -> None:
    """A console codepage that cannot render a character turns a report into a traceback."""
    render_summary(_document(Verdict.FAILED, problems=["x"])).encode("ascii")


def test_the_summary_is_deterministic() -> None:
    """Two renderings of one document are the same text, tables included."""
    assert render_summary(_document()) == render_summary(_document())


def test_a_malformed_section_renders_as_blanks_rather_than_raising() -> None:
    """A summary that crashed would take the diagnostics with it."""
    assert "unknown" in render_summary({"run": "not a mapping", "jobs": None})
