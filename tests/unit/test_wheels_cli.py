"""The wheel-survey command line: what it accepts, and what it refuses.

A parser is worth testing because its failure mode is silence. A word this command
did not understand must be an error, not a run that quietly did the default thing
and reported success — the caller believed they had asked for something else.
"""

from collections.abc import Sequence

import pytest

from tools.quality.wheels import cli, gate


def test_no_argument_runs_the_offline_check() -> None:
    """The default is the one that reaches nothing.

    A default that opened a socket would put the network in every casual
    invocation, including the ones inside a pre-commit hook.
    """
    assert cli.parse([]) is False


def test_check_is_the_offline_run_named_explicitly() -> None:
    assert cli.parse(["check"]) is False


def test_probe_asks_the_index() -> None:
    assert cli.parse(["probe"]) is True


@pytest.mark.parametrize(
    "argv",
    [
        ["--probe"],
        ["Probe"],
        ["pro"],
        ["check", "probe"],
        ["check", "check"],
        ["probe", "extra"],
        ["--help"],
        [""],
    ],
)
def test_anything_else_is_a_usage_error(argv: Sequence[str]) -> None:
    """No abbreviations and no prefixes.

    ``pro`` meaning ``probe`` is convenient until the day somebody means something
    else by it, and then it is a network call nobody asked for.
    """
    with pytest.raises(cli.UsageError):
        cli.parse(argv)


def test_a_usage_error_exits_two_and_prints_the_usage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--probe"]) == cli.EXIT_USAGE
    printed = capsys.readouterr().out
    assert "unrecognised argument" in printed
    assert "usage:" in printed


def test_the_usage_text_states_every_exit_code() -> None:
    """The same four lines every gate here ends its usage with.

    A caller reading one gate's exit codes has read them all.
    """
    for code in ("0  every check passed", "1  a check failed", "2  the command line", "3  a check"):
        assert code in cli.USAGE


def test_the_usage_text_is_ascii() -> None:
    """A Windows console encodes with the active code page.

    A character it cannot represent turns the help text into a traceback.
    """
    assert cli.USAGE.isascii()


def test_the_usage_text_says_which_run_reaches_the_network() -> None:
    """The distinction the whole two-command split exists for."""
    assert "Reaches nothing" in cli.USAGE
    assert "Reaches the network" in cli.USAGE


def test_the_subcommands_are_exactly_the_two_documented() -> None:
    assert {"check", "probe"} == cli.SUBCOMMANDS


def test_a_gate_that_cannot_write_reports_unmeasured_rather_than_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A gate that could not record its answer has not given one.

    Reporting that as a failure would say the survey found something wrong, which
    is a different claim from "the survey could not be written down".
    """

    def refuse(**_kwargs: object) -> int:
        message = "read-only file system"
        raise OSError(message)

    monkeypatch.setattr(cli, "run_wheels", refuse)
    assert cli.main([]) == gate.EXIT_UNMEASURED
    assert "could not write its artefacts" in capsys.readouterr().out
