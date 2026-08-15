"""The governance command line: one subcommand, and every other word refused.

A typo that silently ran the default command would write a manifest somebody
believed had been asked for, which is why an unrecognised word is a usage error
rather than something to ignore.
"""

import pytest

from tools.quality.governance import cli, gate


@pytest.mark.parametrize("argv", [[], ["run"]])
def test_the_command_may_be_spelled_or_omitted(argv: list[str]) -> None:
    """Both spellings work, so a future second subcommand changes nothing for today's callers.

    ``parse`` returns nothing and communicates by raising, so acceptance is the
    absence of :class:`~tools.quality.governance.cli.UsageError` — asserting on
    its return value would assert that ``None is None``.
    """
    cli.parse(argv)


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["walk"], id="an unknown word"),
        pytest.param(["run", "run"], id="a repeated command"),
        pytest.param(["--offline"], id="a flag another gate has and this one does not"),
        pytest.param(["run", "--verbose"], id="an unknown flag"),
    ],
)
def test_anything_else_is_a_usage_error(argv: list[str]) -> None:
    with pytest.raises(cli.UsageError):
        cli.parse(argv)


def test_a_usage_error_exits_two_rather_than_a_verdict_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A mistyped command must never be mistaken for a repository in trouble."""
    assert cli.main(["nonsense"]) == cli.EXIT_USAGE
    printed = capsys.readouterr().out
    assert "unrecognised argument" in printed
    assert "usage:" in printed


def test_the_usage_text_states_every_exit_code_it_can_return() -> None:
    """An exit code nobody documented is an exit code nobody handles."""
    for code in ("0", "1", "2", "3"):
        assert f"  {code}  " in cli.USAGE


def test_a_gate_that_cannot_write_is_unmeasured_rather_than_passing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A gate that could not record its answer has not given one.

    Exit ``3``, not ``0``: doubt about what ran casts doubt on what passed, which
    is the rule every gate here shares.
    """

    def refuse(**_kwargs: object) -> int:
        msg = "read-only file system"
        raise OSError(msg)

    monkeypatch.setattr("tools.quality.governance.cli.run_governance", refuse)
    assert cli.main([]) == gate.EXIT_UNMEASURED
    assert "could not write its artefacts" in capsys.readouterr().out


def test_the_module_runs_as_a_process() -> None:
    """The ``__main__`` guard is exercised rather than excluded from measurement.

    ``docs/engineering/QUALITY_GATES.md`` names the three module guards that are
    covered this way; a line excluded from measurement is a line nobody is
    measuring.
    """
    import subprocess
    import sys

    from tools.quality.governance.gate import REPO_ROOT

    completed = subprocess.run(
        [sys.executable, "-m", "tools.quality.governance", "nonsense"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=REPO_ROOT,
    )
    assert completed.returncode == cli.EXIT_USAGE
    assert "unrecognised argument" in completed.stdout


def test_the_usage_text_points_at_the_gate_that_asks_the_platform() -> None:
    """The split between this gate and the capability probe is the thing most likely to confuse.

    Somebody looking here for "is private vulnerability reporting on" must be
    sent to the gate that actually asks, rather than concluding nothing does.
    """
    assert "supply" in cli.USAGE
