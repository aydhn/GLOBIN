"""The drift command line: three words, and what happens to a fourth.

One of the three writes to the environment and one records a baseline, so the
difference between them is not cosmetic. A parser that quietly degraded `repair`
into `check` would report a repair somebody believes happened, which is worse than
refusing outright.
"""

import pytest

from tools.quality.drift import cli, gate


def test_no_argument_means_check() -> None:
    """The default is the one that changes nothing, which is the safe direction."""
    assert cli.parse([]) == gate.CHECK


@pytest.mark.parametrize("word", [gate.CHECK, gate.ACCEPT, gate.REPAIR])
def test_each_subcommand_is_recognised(word: str) -> None:
    """All three, so a rename cannot silently drop one."""
    assert cli.parse([word]) == word


def test_an_unrecognised_argument_is_refused_rather_than_ignored() -> None:
    """Ignoring it is how a typo becomes a repair that never ran."""
    with pytest.raises(cli.UsageError, match="unrecognised argument"):
        cli.parse(["--recreate"])


def test_two_subcommands_are_refused_rather_than_resolved_by_position() -> None:
    """`accept repair` could mean either order, and they do different things."""
    with pytest.raises(cli.UsageError, match="only one subcommand"):
        cli.parse([gate.ACCEPT, gate.REPAIR])


def test_a_usage_error_prints_the_usage_and_returns_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The exit code the whole tool family uses for a command line it did not understand."""
    assert cli.main(["--help"]) == cli.EXIT_USAGE
    printed = capsys.readouterr().out
    assert "usage: python -m tools.quality.drift" in printed


def test_the_usage_text_names_every_subcommand() -> None:
    """A subcommand nobody documents is one nobody finds."""
    for word in (gate.CHECK, gate.ACCEPT, gate.REPAIR):
        assert word in cli.USAGE


def test_the_usage_text_says_what_an_absent_baseline_means() -> None:
    """It is the one result a reader is most likely to misread as success."""
    assert "unmeasured one" in cli.USAGE


def test_the_usage_text_is_ascii() -> None:
    """A Windows console encodes with the active code page, so a stray dash raises."""
    assert cli.USAGE.isascii()


def test_a_gate_that_cannot_write_reports_unmeasured_rather_than_crashing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A full disk is not a clean tree, and a traceback is not a verdict."""

    def refuse(**_keywords: object) -> int:
        message = "no space left on device"
        raise OSError(message)

    monkeypatch.setattr(cli, "run_drift", refuse)
    assert cli.main([]) == gate.EXIT_UNMEASURED
    assert "could not write its artefacts" in capsys.readouterr().out


def test_the_parser_and_the_gate_agree_on_the_subcommand_names() -> None:
    """Two spellings of one word is a thing that drifts, in a package named for it."""
    assert set(cli.SUBCOMMANDS) == {gate.CHECK, gate.ACCEPT, gate.REPAIR}
