"""The runtime gate's command line, including everything it refuses.

Every unrecognised word is refused rather than ignored. That matters more here
than on the reporting-only gates: this command line can be asked to remove a
directory, and a typo that silently ran the default would be the difference
between a diagnosis and a deletion.
"""

import pytest

from tools.quality.runtime import cli
from tools.quality.runtime.cli import BOOTSTRAP, CHECK, Invocation, UsageError


def test_no_argument_means_check_and_changes_nothing() -> None:
    assert cli.parse([]) == Invocation(bootstrap=False, recreate=False, install_python=False)


def test_check_may_be_spelled_explicitly() -> None:
    """So that the explicit spelling works for anybody who prefers it.

    So that adding ``bootstrap`` did not change what existing callers must type.
    """
    assert cli.parse([CHECK]) == cli.parse([])


def test_bootstrap_is_recognised() -> None:
    assert cli.parse([BOOTSTRAP]).bootstrap is True


def test_the_options_are_recognised_with_bootstrap() -> None:
    invocation = cli.parse([BOOTSTRAP, "--recreate", "--install-python"])
    assert invocation == Invocation(bootstrap=True, recreate=True, install_python=True)


def test_the_order_of_the_words_does_not_matter() -> None:
    assert cli.parse(["--recreate", BOOTSTRAP]) == cli.parse([BOOTSTRAP, "--recreate"])


@pytest.mark.parametrize("option", ["--recreate", "--install-python"])
def test_an_option_without_bootstrap_is_refused_rather_than_ignored(option: str) -> None:
    """``check --recreate`` reads like a request to rebuild something.

    Accepting it while doing nothing of the sort would be worse than refusing it.
    """
    with pytest.raises(UsageError, match="only means something with"):
        cli.parse([option])


def test_an_unknown_word_is_refused() -> None:
    with pytest.raises(UsageError, match="unrecognised argument"):
        cli.parse(["--force"])


def test_a_repeated_subcommand_is_refused() -> None:
    with pytest.raises(UsageError, match="unrecognised argument"):
        cli.parse([CHECK, CHECK])


def test_two_different_subcommands_are_refused() -> None:
    with pytest.raises(UsageError, match="unrecognised argument"):
        cli.parse([CHECK, BOOTSTRAP])


def test_a_repeated_option_is_refused() -> None:
    with pytest.raises(UsageError, match="unrecognised argument"):
        cli.parse([BOOTSTRAP, "--recreate", "--recreate"])


def test_a_usage_error_prints_the_usage_and_returns_the_usage_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--nonsense"]) == cli.EXIT_USAGE
    printed = capsys.readouterr().out
    assert "unrecognised argument" in printed
    assert "usage: python -m tools.quality.runtime" in printed


def test_the_usage_code_is_not_a_verdict_code() -> None:
    """So that "you typed it wrong" is never mistaken for "the host is in trouble"."""
    from tools.quality.runtime.gate import EXIT_GATE_FAILED, EXIT_OK, EXIT_UNMEASURED

    assert cli.EXIT_USAGE not in {EXIT_OK, EXIT_GATE_FAILED, EXIT_UNMEASURED}


def test_the_usage_text_documents_every_exit_code() -> None:
    for code in ("0", "1", "2", "3"):
        assert f"\n  {code}  " in cli.USAGE, f"exit code {code} is not documented"


def test_the_usage_text_names_the_environment_interpreter() -> None:
    """The commonest way to get a wrong answer here is the wrong Python.

    So the usage names the interpreter to run it with, rather than leaving that to
    be worked out from a failing finding.
    """
    assert ".venv\\Scripts\\python.exe" in cli.USAGE


def test_a_gate_that_cannot_write_reports_unmeasured_rather_than_passing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unmeasured is never a pass.

    A read-only evidence directory is the way this actually happens.
    """
    from tools.quality.runtime import gate

    def refuse(**_kwargs: object) -> int:
        msg = "read-only file system"
        raise OSError(msg)

    monkeypatch.setattr("tools.quality.runtime.cli.run_runtime", refuse)
    assert cli.main([]) == gate.EXIT_UNMEASURED
    assert "could not write its artefacts" in capsys.readouterr().out


def test_the_module_runs_as_a_process() -> None:
    """The ``__main__`` guard is exercised rather than excluded from measurement.

    ``docs/engineering/QUALITY_GATES.md`` is explicit that a line excluded from
    measurement is a line nobody is measuring. The usage path is chosen because it
    reaches the guard without writing an artefact.
    """
    import subprocess
    import sys

    from tools.quality.runtime.gate import REPO_ROOT

    completed = subprocess.run(
        [sys.executable, "-m", "tools.quality.runtime", "nonsense"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=REPO_ROOT,
    )
    assert completed.returncode == cli.EXIT_USAGE
    assert "unrecognised argument" in completed.stdout
