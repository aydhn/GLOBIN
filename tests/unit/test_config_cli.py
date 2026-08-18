"""The two command surfaces Phase 030 added, and the four options they share.

``test_bootstrap_cli.py`` owns the parser's older half. This owns what Phase 030
put on top: the ``config`` group, ``bootstrap preflight``, and the two options
every configuration-resolving command now accepts.

The parser is exercised on its own; ``main`` is exercised against the real
repository through an injected starting directory and captured streams. Nothing
here starts a process and nothing here writes outside ``tmp_path``.
"""

import io
import json
from pathlib import Path

import pytest

from globin.domain.bootstrap import ExitCode, checks
from globin.domain.configuration import MIN_SEVERITY
from globin.runtime.cli import USAGE, Invocation, UsageError, main, parse
from tests.support import REPO_ROOT, running_from_the_project_environment


def run(argv: list[str], *, start: Path | None = None) -> tuple[int, str, str]:
    """One command, with its streams captured."""
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, stdout=out, stderr=err, start=REPO_ROOT if start is None else start)
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        pytest.param(["config"], Invocation(command="config validate"), id="defaults-to-validate"),
        pytest.param(["config", "explain"], Invocation(command="config explain"), id="explain-all"),
        pytest.param(
            ["config", "explain", MIN_SEVERITY],
            Invocation(command="config explain", field=MIN_SEVERITY),
            id="explain-one",
        ),
        pytest.param(["config", "dump"], Invocation(command="config dump"), id="dump"),
        pytest.param(
            ["config", "fingerprint"], Invocation(command="config fingerprint"), id="fingerprint"
        ),
        pytest.param(["config", "evidence"], Invocation(command="config evidence"), id="evidence"),
        pytest.param(
            ["bootstrap", "preflight"], Invocation(command="bootstrap preflight"), id="preflight"
        ),
        pytest.param(
            ["config", "--set", "a=b"],
            Invocation(command="config validate", overrides=("a=b",)),
            id="set-before-a-default-subcommand",
        ),
        pytest.param(
            ["config", "validate", "--set", "a=b", "--set", "c=d"],
            Invocation(command="config validate", overrides=("a=b", "c=d")),
            id="set-repeats-in-order",
        ),
        pytest.param(
            ["doctor", "--config", "x.toml"],
            Invocation(command="doctor", config="x.toml"),
            id="config-on-doctor",
        ),
    ],
)
def test_the_parser_reads_what_was_asked_for(argv: list[str], expected: Invocation) -> None:
    """Every accepted shape, compared whole rather than field by field."""
    assert parse(argv) == expected


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["config", "explane"], id="a-mistyped-verb"),
        pytest.param(["config", "dump", MIN_SEVERITY], id="a-field-given-to-a-verb-taking-none"),
        pytest.param(["config", "explain", "a", "b"], id="two-fields-at-once"),
        pytest.param(["config", "--nope"], id="an-unknown-flag"),
        pytest.param(["config", "--set"], id="set-with-no-assignment"),
        pytest.param(["config", "--config"], id="config-with-no-path"),
        pytest.param(["config", "--config", "--json"], id="config-swallowing-the-next-flag"),
        pytest.param(["config", "--config", "a", "--config", "b"], id="config-given-twice"),
        pytest.param(["config", "evidence", "--json"], id="json-asked-of-a-verb-writing-a-file"),
        pytest.param(["bootstrap", "preflght"], id="a-mistyped-subcommand"),
    ],
)
def test_a_command_line_that_means_nothing_is_refused(argv: list[str]) -> None:
    """Refused rather than ignored: a flag that silently does nothing is the failure."""
    with pytest.raises(UsageError):
        parse(argv)


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["config", "--jso"], id="json"),
        pytest.param(["config", "--prof", "paper"], id="profile"),
        pytest.param(["config", "--conf", "x.toml"], id="config"),
        pytest.param(["config", "--se", "a=b"], id="set"),
        pytest.param(["bootstrap", "--prefli"], id="a-subcommand-is-not-abbreviated-either"),
    ],
)
def test_no_long_option_is_accepted_in_an_abbreviated_form(argv: list[str]) -> None:
    """Every word is compared for equality, so there is no prefix logic to disable."""
    with pytest.raises(UsageError):
        parse(argv)


def test_an_option_that_was_not_given_is_absent_rather_than_defaulted() -> None:
    """A parser default reaching the config chain would overwrite every lower source."""
    invocation = parse(["config", "validate"])
    assert invocation.overrides == ()
    assert invocation.config == ""
    assert invocation.profile == ""


def test_the_usage_text_names_the_new_command_and_its_options() -> None:
    """A command a reader cannot discover is a command that does not exist."""
    for word in ("config validate", "config explain", "--set KEY=VALUE", "--config PATH"):
        assert word in USAGE


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------


def test_the_committed_tree_validates() -> None:
    """The repository's own documents bind, which is the baseline every other test moves from."""
    code, out, _ = run(["config", "validate"])
    assert code == ExitCode.OK
    assert "The configuration is valid." in out


def test_an_override_wins_and_the_account_says_which_source_did() -> None:
    """The whole point of provenance, exercised through the command an operator runs."""
    code, out, _ = run(["config", "explain", MIN_SEVERITY, "--set", f"{MIN_SEVERITY}=WARNING"])
    assert code == ExitCode.OK
    assert "command line" in out
    assert "WARNING" in out


def test_an_override_naming_no_setting_is_refused_before_its_value_is_read() -> None:
    """The typed field registry is ``known_keys``; an arbitrary path is not accepted."""
    code, _, err = run(["config", "validate", "--set", "logging.nope=1"])
    assert code == ExitCode.CONFIGURATION_INVALID
    assert "names no setting" in err


def test_a_credential_shaped_override_is_refused_and_its_value_never_printed() -> None:
    """Refusing on the name means the value is never read, so it cannot leak."""
    code, out, err = run(["config", "validate", "--set", "api_key=sk-live-secret"])
    assert code == ExitCode.CONFIGURATION_INVALID
    assert "looks like a credential" in err
    assert "sk-live-secret" not in out + err


def test_an_explicit_document_that_is_not_there_refuses() -> None:
    """Unlike the four computed documents, a named one must exist."""
    code, _, err = run(["config", "validate", "--config", "nowhere-at-all.toml"])
    assert code == ExitCode.CONFIGURATION_INVALID
    assert "is not there" in err


def test_an_explicit_document_is_read_and_wins_over_the_committed_ones(tmp_path: Path) -> None:
    """The layer ``--config`` adds sits above the tree and below the environment."""
    document = tmp_path / "explicit.toml"
    document.write_text('[logging]\nmin_severity = "ERROR"\n', encoding="utf-8")
    code, out, _ = run(["config", "explain", MIN_SEVERITY, "--config", str(document)])
    assert code == ExitCode.OK
    assert "ERROR" in out


def test_a_document_written_for_a_later_contract_is_refused(tmp_path: Path) -> None:
    """Fail closed: this GLOBIN does not know what a future document's keys mean."""
    document = tmp_path / "future.toml"
    document.write_text("config_schema_version = 99\n", encoding="utf-8")
    code, _, err = run(["config", "validate", "--config", str(document)])
    assert code == ExitCode.CONFIGURATION_INVALID
    assert "config_schema_version" in err


def test_a_document_declaring_this_contract_is_read(tmp_path: Path) -> None:
    """The reserved key is extracted rather than treated as an unknown setting."""
    document = tmp_path / "declared.toml"
    document.write_text('config_schema_version = 1\n[logging]\nmin_severity = "INFO"\n', "utf-8")
    code, out, _ = run(["config", "explain", MIN_SEVERITY, "--config", str(document)])
    assert code == ExitCode.OK
    assert "INFO" in out


def test_malformed_toml_stops_the_command(tmp_path: Path) -> None:
    """A file that is not TOML is reported where it sits, not skipped."""
    document = tmp_path / "broken.toml"
    document.write_text("[logging\n", encoding="utf-8")
    code, _, _ = run(["config", "validate", "--config", str(document)])
    assert code != ExitCode.OK


def test_a_dump_is_redacted_and_byte_stable() -> None:
    """Two runs on one configuration produce the same bytes, or comparison means nothing."""
    first = run(["config", "dump"])
    second = run(["config", "dump"])
    assert first[1] == second[1]
    assert first[0] == ExitCode.OK


def test_a_dump_refuses_a_configuration_that_would_not_bind() -> None:
    """It describes the validated model, and there is none to describe."""
    code, out, _ = run(["config", "dump", "--set", f"{MIN_SEVERITY}=NOTALEVEL"])
    assert code == ExitCode.CONFIGURATION_INVALID
    assert out == ""


def test_explain_still_answers_when_the_configuration_will_not_bind() -> None:
    """The operator whose configuration is broken is the one who needs the account."""
    code, out, _ = run(["config", "explain", MIN_SEVERITY, "--set", f"{MIN_SEVERITY}=NOTALEVEL"])
    assert code == ExitCode.OK
    assert "command line" in out


def test_a_fingerprint_changes_when_a_semantic_value_does() -> None:
    """The property the whole digest exists for."""
    _, plain, _ = run(["config", "fingerprint", "--json"])
    _, changed, _ = run(["config", "fingerprint", "--json", "--set", f"{MIN_SEVERITY}=WARNING"])
    assert json.loads(plain)["semantic_fingerprint"] != json.loads(changed)["semantic_fingerprint"]


def test_under_json_standard_output_carries_the_document_and_nothing_else() -> None:
    """The one contract the flag makes, asserted by parsing the whole stream."""
    code, out, err = run(["config", "explain", MIN_SEVERITY, "--json"])
    assert code == ExitCode.OK
    assert json.loads(out)["fields"][0]["key"] == MIN_SEVERITY
    assert err != ""


def test_preflight_reports_every_check_and_says_how_long_the_verdict_lasts() -> None:
    """The sentence a start-up gate cannot say, through the command that says it.

    The verdict itself is asserted only when this interpreter *is* the project's
    environment, because CI's quality job has no `.venv` and `python.environment`
    refuses there. What is asserted unconditionally is the shape: preflight runs
    every check rather than stopping, and always says whether its answer expires.
    """
    code, out, _ = run(["bootstrap", "preflight"])
    assert "true when taken" in out or "does not expire" in out
    if running_from_the_project_environment():
        assert code == ExitCode.OK
        assert "true when taken" in out


def test_preflight_under_json_carries_the_suite_and_every_check() -> None:
    """One builder, so the stream and any artefact describe one run."""
    _, out, _ = run(["bootstrap", "preflight", "--json"])
    document = json.loads(out)
    assert len(document["checks"]) == len(checks())
    assert document["suite"]["scheduled"]
    assert document["may_start"] is running_from_the_project_environment()
