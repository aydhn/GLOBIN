"""The release gate's command line, and the branches a passing run never reaches.

Two subcommands and no options, so most of what is worth testing here is what the
parser **refuses**. A typo that silently ran the default would write a manifest
somebody believed had been asked for — and here that manifest is published as a
release asset.
"""

import subprocess
import sys

import pytest

from tools.quality.release import cli, gate


def test_the_default_is_the_contract_check() -> None:
    """Omitting the subcommand asks the deterministic question."""
    assert cli.parse([]) is False
    assert cli.parse(["check"]) is False


def test_the_preconditions_are_asked_for_by_name() -> None:
    assert cli.parse(["ready"]) is True


@pytest.mark.parametrize(
    "argv",
    [
        ["nonsense"],
        ["--check"],
        ["check", "check"],
        ["ready", "ready"],
        ["check", "ready"],
        ["", "check"],
        ["Check"],
        ["release"],
    ],
)
def test_an_argument_the_parser_does_not_know_is_refused(argv: list[str]) -> None:
    """Refused rather than ignored, including a repeat and a misspelling."""
    with pytest.raises(cli.UsageError):
        cli.parse(argv)


def test_a_bad_command_line_exits_distinctly_from_every_verdict(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A typing mistake is never mistaken for a broken repository."""
    assert cli.main(["nonsense"]) == cli.EXIT_USAGE
    assert cli.EXIT_USAGE not in {gate.EXIT_OK, gate.EXIT_GATE_FAILED, gate.EXIT_UNMEASURED}
    printed = capsys.readouterr().out
    assert "unrecognised argument" in printed
    assert "usage:" in printed


def test_a_gate_that_cannot_write_reports_unmeasured_rather_than_passing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A gate that produced no evidence has established nothing."""

    def refuse(**_kwargs: object) -> int:
        msg = "read-only file system"
        raise OSError(msg)

    monkeypatch.setattr("tools.quality.release.cli.run_release", refuse)
    assert cli.main([]) == gate.EXIT_UNMEASURED
    assert "could not write its artefacts" in capsys.readouterr().out


def test_the_subcommand_reaches_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ready` must actually turn the preconditions on.

    A parser that returned the right answer and a caller that ignored it would both pass every
    test above.
    """
    asked: list[bool] = []

    def record(*, check_repository: bool) -> int:
        asked.append(check_repository)
        return gate.EXIT_OK

    monkeypatch.setattr("tools.quality.release.cli.run_release", record)
    cli.main([])
    cli.main(["ready"])
    assert asked == [False, True]


def test_the_usage_documents_every_exit_code() -> None:
    """Including `3`, the code a reader is likeliest to meet uncomprehending."""
    for code in ("0", "1", "2", "3"):
        assert f"  {code}  " in cli.USAGE


def test_the_usage_points_at_the_gate_that_asks_the_platform() -> None:
    """A reader asking "are immutable releases on" must be sent to `supply`."""
    assert "supply" in cli.USAGE


def test_the_usage_explains_why_there_are_two_subcommands() -> None:
    """A question about a commit and one about a working tree differ."""
    assert "deterministic" in cli.USAGE
    assert "working tree" in cli.USAGE


def test_the_module_runs_as_a_process() -> None:
    """The ``__main__`` guard is exercised rather than excluded from measurement.

    ``docs/engineering/QUALITY_GATES.md`` names the module guards covered this
    way; a line excluded from measurement is a line nobody is measuring.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "tools.quality.release", "nonsense"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=gate.REPO_ROOT,
    )
    assert completed.returncode == cli.EXIT_USAGE
    assert "unrecognised argument" in completed.stdout
