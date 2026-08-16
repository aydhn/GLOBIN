"""The command line: what it accepts, what it refuses, and what it writes where.

The parser is exercised on its own, and ``main`` is exercised against the real
repository through an injected starting directory and captured streams. Nothing
here starts a process — the one test that does is at the bottom, marked ``slow``,
and it exists to prove the module guard runs rather than to test the parser
twice.
"""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from globin.domain.bootstrap import BootstrapOutcome, ExitCode
from globin.runtime.cli import (
    USAGE,
    Invocation,
    UsageError,
    main,
    parse,
    render_human,
    render_json,
)
from globin.runtime.composition import build_bootstrap
from tests.support import REPO_ROOT

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        pytest.param(["--help"], Invocation(command="--help"), id="long-help"),
        pytest.param(["-h"], Invocation(command="-h"), id="short-help"),
        pytest.param(["--version"], Invocation(command="--version"), id="version"),
        pytest.param(["doctor"], Invocation(command="doctor"), id="doctor"),
        pytest.param(
            ["doctor", "--json"], Invocation(command="doctor", as_json=True), id="doctor-json"
        ),
        pytest.param(
            ["bootstrap"], Invocation(command="bootstrap check"), id="bootstrap-defaults-to-check"
        ),
        pytest.param(
            ["bootstrap", "check"], Invocation(command="bootstrap check"), id="bootstrap-check"
        ),
        pytest.param(
            ["bootstrap", "check", "--json"],
            Invocation(command="bootstrap check", as_json=True),
            id="bootstrap-check-json",
        ),
        pytest.param(
            ["bootstrap", "evidence"],
            Invocation(command="bootstrap evidence"),
            id="bootstrap-evidence",
        ),
    ],
)
def test_a_command_line_this_parser_understands_is_read(
    argv: list[str], expected: Invocation
) -> None:
    """The default subcommand is the one that changes nothing."""
    assert parse(argv) == expected


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param([], id="nothing"),
        pytest.param(["doc"], id="abbreviation"),
        pytest.param(["Doctor"], id="wrong-case"),
        pytest.param(["--doctor"], id="flag-spelling"),
        pytest.param(["diagnose"], id="unknown-word"),
        pytest.param(["doctor", "check"], id="two-subcommands"),
        pytest.param(["doctor", "--quiet"], id="unknown-option"),
        pytest.param(["doctor", "--json", "--json"], id="repeated-option"),
        pytest.param(["bootstrap", "verify"], id="unknown-bootstrap-subcommand"),
        pytest.param(["bootstrap", "check", "extra"], id="trailing-word"),
        pytest.param(["--version", "--json"], id="version-with-an-option"),
        pytest.param(["--help", "doctor"], id="help-with-a-subcommand"),
        pytest.param(["bootstrap", "evidence", "--json"], id="json-with-evidence"),
    ],
)
def test_a_command_line_this_parser_does_not_understand_is_refused(argv: list[str]) -> None:
    """Refused rather than ignored: a flag that silently does nothing is worse."""
    with pytest.raises(UsageError):
        parse(argv)


def test_asking_for_json_from_evidence_says_what_to_use_instead() -> None:
    """A refusal that names the alternative costs one sentence and saves a search."""
    with pytest.raises(UsageError, match="bootstrap check --json"):
        parse(["bootstrap", "evidence", "--json"])


def test_the_usage_text_documents_every_exit_code_the_process_can_return() -> None:
    """The codes are a contract, and a contract nobody can read is not one."""
    for code in ExitCode:
        assert f"{int(code):>3}  " in USAGE or f"{int(code):>2}  " in USAGE, code


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def outcome_here() -> BootstrapOutcome:
    """One real run against this repository."""
    return build_bootstrap(REPO_ROOT).run(stop_at_first_refusal=False)


def test_the_human_rendering_names_every_check() -> None:
    """A table a person reads, aligned to the identifiers actually present."""
    text = render_human(outcome_here())
    for line in text.splitlines():
        assert len(line) < 200
    assert "bootstrap.ready" in text


def test_the_human_rendering_says_plainly_whether_globin_may_start() -> None:
    """The last line is the answer, so it does not have to be inferred."""
    text = render_human(outcome_here())
    assert text.rstrip().endswith(("GLOBIN is ready.", "GLOBIN will not start."))


def test_the_json_rendering_is_the_document_the_evidence_carries() -> None:
    """Reading the stream and reading the artefact cannot disagree."""
    document = json.loads(render_json(outcome_here()))
    assert document["schema"] == "globin.bootstrap.manifest"
    assert document["phase"] == 21
    assert "digest" in document


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def run(argv: list[str], *, start: Path | None = None) -> tuple[int, str, str]:
    """One command, with its streams captured."""
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, stdout=out, stderr=err, start=REPO_ROOT if start is None else start)
    return code, out.getvalue(), err.getvalue()


def test_help_is_written_to_standard_output_and_succeeds() -> None:
    """Asking for help is not an error."""
    code, out, _ = run(["--help"])
    assert code == ExitCode.OK
    assert "usage: globin" in out


def test_no_command_is_a_usage_error_rather_than_a_success() -> None:
    """A gate invoked wrongly must never look like a gate that passed."""
    code, out, err = run([])
    assert code == ExitCode.USAGE
    assert out == ""
    assert "usage: globin" in err


def test_an_unrecognised_command_is_a_usage_error() -> None:
    """And the usage text goes to standard error, where a failure belongs."""
    code, _, err = run(["diagnose"])
    assert code == ExitCode.USAGE
    assert "unrecognised argument" in err


def test_the_version_is_the_one_the_package_declares() -> None:
    """One source, which ADR-0049 requires and `pyproject.toml` points at."""
    import globin

    code, out, _ = run(["--version"])
    assert code == ExitCode.OK
    assert out.strip() == globin.__version__


def test_doctor_writes_its_table_to_standard_output() -> None:
    """The ordinary diagnostic, and its code is the pipeline's rather than a guess.

    Asserting a set of acceptable codes would be asserting something about the
    machine this happens to run on: from `.venv` the answer is 0, and from the
    interpreter continuous integration installs it is 12, because that interpreter
    is genuinely not the project's environment. What must hold either way is that
    the command reports what the pipeline concluded.
    """
    expected = build_bootstrap(REPO_ROOT).run(stop_at_first_refusal=False).exit_code
    code, out, _ = run(["doctor"])
    assert code == int(expected)
    assert "bootstrap.ready" in out


def test_under_json_standard_output_carries_only_json() -> None:
    """A caller piping this into a parser gets a document and nothing else."""
    _, out, err = run(["doctor", "--json"])
    assert json.loads(out)
    assert err, "the human text still goes somewhere"


def test_the_two_renderings_describe_one_run() -> None:
    """Two views of one report, not two reports."""
    _, out, err = run(["bootstrap", "check", "--json"])
    document = json.loads(out)
    for check in document["checks"]:
        assert check["id"] in err


def test_evidence_writes_the_manifest_and_says_where() -> None:
    """Into the declared evidence root, and nowhere else.

    Written whatever the verdict was: a gate that failed silently and left no
    artefact is indistinguishable from one that never ran.
    """
    expected = build_bootstrap(REPO_ROOT).run(stop_at_first_refusal=True).exit_code
    code, out, _ = run(["bootstrap", "evidence"])
    assert code == int(expected)
    assert "evidence: .globin/bootstrap/bootstrap-manifest.json" in out
    assert (REPO_ROOT / ".globin" / "bootstrap" / "bootstrap-manifest.json").is_file()


def test_a_tree_that_is_not_a_checkout_refuses_rather_than_guessing(tmp_path: Path) -> None:
    """The bounded search found nothing, and nothing is what it reports."""
    code, out, _ = run(["bootstrap", "check"], start=tmp_path)
    assert code == ExitCode.PATHS_UNUSABLE
    assert "no project root was found" in out
    assert "will not start" in out


def test_a_run_that_refuses_writes_no_evidence_outside_the_project(tmp_path: Path) -> None:
    """Nothing is written outside the project root, ever — including on failure."""
    code, _, err = run(["bootstrap", "evidence"], start=tmp_path)
    assert code == ExitCode.INTERNAL
    assert "nowhere to write evidence" in err
    assert not list(tmp_path.iterdir())


def test_running_the_same_command_twice_reports_the_same_thing() -> None:
    """Idempotent: a doctor run changes no configuration, secret or dependency."""
    first = json.loads(run(["doctor", "--json"])[1])
    second = json.loads(run(["doctor", "--json"])[1])
    assert first == second


def test_the_working_directory_does_not_decide_what_is_reported() -> None:
    """Run from a nested directory, the same project is found and described.

    The whole documents are deliberately *not* compared. ``project.root`` says
    where the search started, and that genuinely differs — it is diagnostic
    information rather than drift, and a test demanding it be identical would be
    demanding the report say less. What must not differ is everything the run
    concluded: the root, the facts, every verdict, and the fingerprint.
    """
    top = json.loads(run(["doctor", "--json"], start=REPO_ROOT)[1])
    nested = json.loads(run(["doctor", "--json"], start=REPO_ROOT / "src" / "globin")[1])

    assert top["observed"] == nested["observed"]
    assert top["observed"]["project"]["root"] == {"location": "repository", "path": "."}
    assert top["verdict"] == nested["verdict"]
    assert [(check["id"], check["status"]) for check in top["checks"]] == [
        (check["id"], check["status"]) for check in nested["checks"]
    ]


@pytest.mark.slow
def test_the_module_starts_as_a_process_and_reports_its_usage() -> None:
    """`python -m globin` is one of the two documented ways in.

    Exercised through a real subprocess rather than excluded with a coverage
    pragma, on the reasoning `docs/engineering/QUALITY_GATES.md` gives about the
    other module guards: a line excluded from measurement is a line nobody is
    measuring.

    `PYTHONPATH` is set because the child is a fresh interpreter and this test is
    about the module guard rather than about the install. Where GLOBIN is
    installed it changes nothing; where it is not — the continuous-integration
    `quality` job, and any checkout nobody has bootstrapped — it is the difference
    between measuring the guard and measuring the install.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "globin", "nonsense"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
    )
    assert completed.returncode == ExitCode.USAGE
    assert "usage: globin" in completed.stderr
