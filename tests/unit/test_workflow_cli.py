"""The aggregate gate's entry point, and the branches a happy path never reaches.

Two subjects that share a reason for existing: both are code a passing run never
executes, and both decide what happens when something is wrong.

The command line matters because a typo that silently ran the default would
produce a verdict somebody believed was about what they typed. The error branches
matter because each of them is the difference between "this run could not say"
and a green check.
"""

import json
from pathlib import Path

import pytest

from tools.quality.workflow import cli, gate, plan
from tools.quality.workflow.cli import COMMANDS, UsageError, main, parse
from tools.quality.workflow.gate import (
    AGGREGATE_FILE,
    EXIT_UNMEASURED,
    EXIT_USAGE,
    read_aggregate,
    run_aggregate,
)
from tools.quality.workflow.plan import WorkflowError, load_configuration

# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------


def test_no_argument_runs_the_default_command() -> None:
    """One subcommand, so typing it is optional and typing nothing is not an error."""
    assert parse([]) == COMMANDS[0]


def test_the_command_may_be_named_explicitly() -> None:
    """A script that spells it out keeps working when a second command arrives."""
    assert parse(["aggregate"]) == "aggregate"


def test_an_unknown_command_is_refused() -> None:
    """Refused rather than ignored: a typo must not run the default."""
    with pytest.raises(UsageError, match="unknown command"):
        parse(["agregate"])


def test_more_than_one_command_is_refused() -> None:
    """Two words is a caller who believes this takes arguments. It does not."""
    with pytest.raises(UsageError, match="expected one command"):
        parse(["aggregate", "--now"])


def test_help_prints_the_usage_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    """Asking for help is not a failure, so it exits zero."""
    assert main(["-h"]) == 0
    printed = capsys.readouterr().out
    assert "usage: python -m tools.quality.workflow" in printed
    assert "GLOBIN_WORKFLOW_NEEDS" in printed


def test_the_usage_documents_every_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    """The four codes are the contract; a caller reading `--help` gets all of them."""
    main(["--help"])
    printed = capsys.readouterr().out
    for code in ("0  ", "1  ", "2  ", "3  "):
        assert code in printed


def test_a_bad_command_line_exits_with_the_usage_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Distinct from every code a check itself produces.

    A gate invoked wrongly must never look like a gate that passed, and must not
    look like one that failed either — the two need different responses.
    """
    assert main(["nonsense"]) == EXIT_USAGE
    assert "unknown command" in capsys.readouterr().out


def test_the_default_invocation_runs_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wiring between the entry point and the gate, without running one.

    Substituted rather than executed: the gate reads the repository's real
    evidence directory, so a unit test that let it run would depend on whatever
    the last local run happened to leave there.
    """
    calls: list[int] = []

    def fake() -> int:
        calls.append(1)
        return 0

    monkeypatch.setattr(cli, "run_aggregate", fake)
    assert main([]) == 0
    assert calls == [1]


@pytest.mark.slow
def test_the_module_can_be_started_as_a_process(repo_root: Path) -> None:
    """Exercises ``__main__.py``, which no in-process test reaches.

    ``QUALITY_GATES.md`` records the ``if __name__`` guards as knowingly
    uncovered rather than annotating them with a pragma, because a pragma asserts
    coverage this repository does not have. ``--help`` is used so the test costs
    a process start and nothing else.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "tools.quality.workflow", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0
    assert "usage: python -m tools.quality.workflow" in result.stdout


# --------------------------------------------------------------------------
# The branches a passing run never reaches
# --------------------------------------------------------------------------


def test_an_unreadable_configuration_is_never_a_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A gate that cannot read what it requires has established nothing."""

    def broken() -> plan.Configuration:
        msg = "cannot read pyproject.toml: OSError (no such file)"
        raise WorkflowError(msg)

    monkeypatch.setattr(gate, "load_configuration", broken)
    assert run_aggregate(reports=tmp_path / "w", evidence=tmp_path / "e") == EXIT_UNMEASURED
    assert "[quality] configuration:" in capsys.readouterr().out


def test_a_settings_file_that_will_not_parse_is_refused(tmp_path: Path) -> None:
    """Guard the checker with its failing case."""
    (tmp_path / "pyproject.toml").write_text("[tool.globin", encoding="utf-8")
    with pytest.raises(WorkflowError, match=r"cannot read pyproject\.toml"):
        load_configuration(tmp_path)


def test_a_missing_settings_file_is_refused(tmp_path: Path) -> None:
    """Not defaulted. There is no sensible guess at what a run required."""
    with pytest.raises(WorkflowError, match=r"cannot read pyproject\.toml"):
        load_configuration(tmp_path / "nowhere")


def test_the_repository_configuration_is_readable() -> None:
    """The real settings file parses, which every other test assumes."""
    assert load_configuration().required_jobs


def test_a_manifest_with_no_gates_section_is_never_a_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """It parses and its digest is right; it simply concluded nothing."""
    from tools.quality.evidence.manifest import build, render

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    document = build(run={}, gates={}, timing={})
    document["gates"] = "not a mapping"
    text = render(document)
    (evidence / "evidence-manifest.json").write_text(text, encoding="utf-8")
    monkeypatch.setenv(plan.NEEDS_VARIABLE, json.dumps({}))
    assert run_aggregate(reports=tmp_path / "w", evidence=evidence) == EXIT_UNMEASURED


def test_a_gate_entry_that_is_not_a_mapping_is_unmeasured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A manifest can be well-formed and still record nonsense for one gate."""
    from tools.quality.evidence.manifest import build, render

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    gates: dict[str, object] = dict.fromkeys(gate.expected_gates(), "not a mapping")
    text = render(build(run={}, gates=gates, timing={}))
    (evidence / "evidence-manifest.json").write_text(text, encoding="utf-8")
    monkeypatch.setenv(plan.NEEDS_VARIABLE, json.dumps({}))
    assert run_aggregate(reports=tmp_path / "w", evidence=evidence) == EXIT_UNMEASURED


def test_a_summary_that_cannot_be_written_does_not_change_the_verdict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Losing the cover page is not a reason to call a good tree bad.

    Nor a way to make a bad one look good: the verdict is decided before the
    summary is written, so this can only ever remove information.
    """
    from tools.quality.evidence.manifest import build, render

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    gates: dict[str, object] = {
        name: {"passed": True, "findings": 0} for name in gate.expected_gates()
    }
    (evidence / "evidence-manifest.json").write_text(
        render(build(run={}, gates=gates, timing={})), encoding="utf-8"
    )
    # A directory cannot be opened for appending, so the write raises OSError.
    unwritable = tmp_path / "summary-directory"
    unwritable.mkdir()
    monkeypatch.setenv(gate.SUMMARY_VARIABLE, str(unwritable))
    monkeypatch.delenv(plan.NEEDS_VARIABLE, raising=False)
    monkeypatch.delenv(plan.CI_VARIABLE, raising=False)

    assert run_aggregate(reports=tmp_path / "w", evidence=evidence) == 0
    assert "[quality] summary: could not write it" in capsys.readouterr().out


def test_a_local_run_with_no_context_reports_no_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The developer's case: there are no jobs, so the evidence decides alone."""
    from tools.quality.evidence.manifest import build, render

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    gates: dict[str, object] = {
        name: {"passed": True, "findings": 0} for name in gate.expected_gates()
    }
    (evidence / "evidence-manifest.json").write_text(
        render(build(run={}, gates=gates, timing={})), encoding="utf-8"
    )
    monkeypatch.delenv(plan.NEEDS_VARIABLE, raising=False)
    monkeypatch.delenv(plan.CI_VARIABLE, raising=False)
    reports = tmp_path / "w"

    assert run_aggregate(reports=reports, evidence=evidence) == 0
    assert read_aggregate(reports / AGGREGATE_FILE)["jobs"] == {}


def test_an_aggregate_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    """Guard the checker with its failing case."""
    path = tmp_path / AGGREGATE_FILE
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(WorkflowError, match="must be a JSON object"):
        read_aggregate(path)


def test_an_aggregate_that_will_not_parse_is_refused(tmp_path: Path) -> None:
    """A truncated file is a detectable fault, and stays one."""
    path = tmp_path / AGGREGATE_FILE
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(WorkflowError, match="cannot read the aggregate"):
        read_aggregate(path)


def test_a_missing_aggregate_is_refused(tmp_path: Path) -> None:
    """Absence is reported as such, not as an empty result."""
    with pytest.raises(WorkflowError, match="cannot read the aggregate"):
        read_aggregate(tmp_path / "nothing.json")
