"""The stack gate's command line.

Short, because the surface is: one optional word. The tests that matter are the
refusals — a flag that silently does nothing is how a caller ends up believing it
asked for something.
"""

import pytest

from tools.quality.stack.cli import EXIT_USAGE, USAGE, UsageError, main, parse


def test_no_argument_is_the_default_and_is_accepted() -> None:
    parse([])


def test_the_only_subcommand_is_accepted() -> None:
    parse(["check"])


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["probe"], id="a subcommand this gate deliberately does not have"),
        pytest.param(["--json"], id="a flag from another command"),
        pytest.param(["che"], id="an abbreviation"),
        pytest.param(["check", "check"], id="the subcommand twice"),
        pytest.param(["check", "extra"], id="a trailing word"),
    ],
)
def test_anything_else_is_refused(argv: list[str]) -> None:
    """`probe` is the interesting row.

    Every sibling gate has one, and this one deliberately does not, because
    nothing it asks needs a network. Accepting it silently would let a caller
    believe they had asked for a check against an index.
    """
    with pytest.raises(UsageError, match="unrecognised argument"):
        parse(argv)


def test_a_usage_error_prints_the_usage_and_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["probe"]) == EXIT_USAGE
    printed = capsys.readouterr().out
    assert "unrecognised argument" in printed
    assert "usage: python -m tools.quality.stack" in printed


def test_the_usage_states_every_exit_code_the_gate_can_return() -> None:
    """An exit code a caller cannot look up is a code nobody branches on."""
    for code in ("0", "1", "2", "3"):
        assert f"  {code}  " in USAGE


def test_the_usage_says_it_reaches_nothing() -> None:
    """The property that decides where this command may run.

    A reader has to be able to learn, without opening the source, that this is
    safe on an aeroplane and needs no index.
    """
    assert "Reaches nothing" in USAGE
