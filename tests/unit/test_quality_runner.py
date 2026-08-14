"""Verify that the quality entrypoint reports failure honestly.

This is the test that matters most in Phase 004, because the runner is the one
component whose bug would be invisible. Everything else in the repository fails
loudly when it breaks; a gate that swallows an exit code fails *quietly*, and
every subsequent phase inherits a green build that proves nothing.

So the assertions here are almost entirely about the unhappy paths: a step that
fails, a tool that is not installed, a command that does not exist. The
happy-path assertion — that a passing command returns zero — is the least
interesting one in the file.

Steps are synthesised rather than taken from the real table. Running the actual
lint or coverage step from inside the suite would be slow, recursive, and would
couple this test to whether the repository happens to be clean right now.
"""

import sys

import pytest

from tools import quality
from tools.quality.__main__ import main, usage
from tools.quality.commands import COMMANDS, MUTATING_COMMANDS, Command, Step, command_names, find
from tools.quality.runner import EXIT_TOOL_MISSING, EXIT_USAGE, execute, missing_modules, run

#: A step that always succeeds, using only the interpreter already running.
_OK = Step("ok", "sys", ("-c", "raise SystemExit(0)"))


def _exits(code: int) -> Step:
    """Return a step whose subprocess exits with ``code``."""
    return Step(f"exit-{code}", "sys", ("-c", f"raise SystemExit({code})"))


# --------------------------------------------------------------------------
# The command table
# --------------------------------------------------------------------------


def test_every_command_name_is_unique() -> None:
    names = command_names()
    assert len(set(names)) == len(names), f"duplicate command names: {names}"


def test_every_command_has_at_least_one_step() -> None:
    empty = [command.name for command in COMMANDS if not command.steps]
    assert not empty, f"commands that would pass without running anything: {empty}"


def test_every_command_has_a_summary() -> None:
    """A command nobody can describe is a command nobody will run correctly."""
    for command in COMMANDS:
        assert command.summary.strip(), f"{command.name} has no summary"


@pytest.mark.parametrize("required", ["fast", "full", "lint", "format", "typecheck", "coverage"])
def test_the_mandatory_commands_exist(required: str) -> None:
    """These names are referenced by CI, pre-commit and the documentation.

    Renaming one without updating its callers would leave a gate that silently
    stops running, so the names are pinned here.
    """
    assert find(required) is not None, f"missing quality command: {required}"


def test_find_returns_none_for_an_unknown_command() -> None:
    """A missing command must not fall back to something that looks like success."""
    assert find("no-such-command") is None


def test_the_full_command_covers_lint_format_type_and_coverage() -> None:
    """`full` is what CI runs. If a check leaves it, CI stops checking it."""
    full = find("full")
    assert full is not None
    modules = {step.module for step in full.steps}
    assert {"ruff", "mypy", "pytest"} <= modules
    names = {step.name for step in full.steps}
    assert {"lint", "format", "typecheck", "coverage"} <= names


def test_only_the_declared_commands_modify_the_tree() -> None:
    """Verification must never rewrite the code it is verifying.

    A gate that reformats on the way past makes its own result meaningless: the
    thing that passed is not the thing that was committed.
    """
    assert set(MUTATING_COMMANDS) == {"fix", "reformat"}
    for command in COMMANDS:
        if command.name in MUTATING_COMMANDS:
            continue
        for step in command.steps:
            assert "--fix" not in step.argv, f"{command.name} would modify the tree"
            reformats = step.argv[:3] == ("-m", "ruff", "format") and "--check" not in step.argv
            assert not reformats, f"{command.name} would rewrite formatting"


def test_no_command_applies_unsafe_fixes() -> None:
    """Ruff's unsafe fixes can change behaviour, so no command may apply them."""
    for command in COMMANDS:
        for step in command.steps:
            assert "--unsafe-fixes" not in step.argv, f"{command.name} applies unsafe fixes"


# --------------------------------------------------------------------------
# Missing tools are a failure, never a pass
# --------------------------------------------------------------------------


def test_missing_modules_reports_an_absent_tool() -> None:
    step = Step("phantom", "globin_tool_that_does_not_exist", ("-c", "pass"))
    assert missing_modules([step]) == ("globin_tool_that_does_not_exist",)


def test_missing_modules_is_quiet_when_everything_is_present() -> None:
    """Guard the check above: one that always reported something would be useless."""
    assert missing_modules([_OK]) == ()


def test_a_command_needing_an_absent_tool_fails_without_running_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The distinctive exit code matters: 'did not run' must not read as 'passed'."""
    command = Command(
        "phantom",
        "Not a real command.",
        (Step("phantom", "globin_tool_that_does_not_exist", ("-c", "raise SystemExit(0)")),),
    )
    assert run(command, echo=False) == EXIT_TOOL_MISSING
    message = capsys.readouterr().err
    assert "globin_tool_that_does_not_exist" in message, "the error must name the missing tool"
    assert "install" in message.lower(), "the error must say what to do about it"


def test_a_missing_tool_is_not_installed_automatically(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dependency bootstrap belongs to Phases 017-032, not to a quality gate.

    A tool that installs what it needs makes the environment depend on the order
    things were run in, which is the opposite of reproducible.
    """
    command = Command(
        "phantom",
        "Not a real command.",
        (Step("phantom", "globin_tool_that_does_not_exist", ("-c", "raise SystemExit(0)")),),
    )
    run(command, echo=False)
    assert "pip install" not in capsys.readouterr().err


# --------------------------------------------------------------------------
# Exit codes survive
# --------------------------------------------------------------------------


@pytest.mark.parametrize("code", [1, 2, 5, 42])
def test_execute_returns_the_child_exit_code(code: int) -> None:
    """Not a boolean. The specific code distinguishes the kind of failure."""
    assert execute(_exits(code)) == code


def test_a_passing_command_returns_zero() -> None:
    assert run(Command("ok", "Always passes.", (_OK, _OK)), echo=False) == 0


def test_run_propagates_the_first_failing_step_code() -> None:
    command = Command("mixed", "Fails in the middle.", (_OK, _exits(3), _OK))
    assert run(command, echo=False) == 3


def test_run_stops_at_the_first_failure() -> None:
    """Later steps must not run, or a failure could be masked by what follows it."""
    command = Command("mixed", "Fails early.", (_exits(4), _exits(9)))
    assert run(command, echo=False) == 4, "the second step's code leaked past the first failure"


def test_run_names_the_step_that_failed(capsys: pytest.CaptureFixture[str]) -> None:
    run(Command("mixed", "Fails.", (_exits(6),)), echo=False)
    assert "exit-6" in capsys.readouterr().err


def test_execute_uses_the_running_interpreter() -> None:
    """A step must not silently run under a different Python from its caller."""
    step = Step("which", "sys", ("-c", "import sys; raise SystemExit(0 if sys.executable else 1)"))
    assert execute(step) == 0
    assert sys.executable, "the interpreter path is what execute() builds argv from"


# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------


def test_no_arguments_is_a_usage_error() -> None:
    """Invoking the gate wrongly must not look like invoking it successfully."""
    assert main([]) == EXIT_USAGE


def test_explicit_help_succeeds() -> None:
    """Asking for help is not an error, unlike forgetting to say what to run."""
    assert main(["--help"]) == 0


def test_an_unknown_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["definitely-not-a-command"]) == EXIT_USAGE
    assert "unknown command" in capsys.readouterr().err


def test_extra_arguments_are_refused(capsys: pytest.CaptureFixture[str]) -> None:
    """Silently ignoring an argument is how someone runs a different check than they meant."""
    assert main(["lint", "--with-feeling"]) == EXIT_USAGE
    assert "unexpected extra arguments" in capsys.readouterr().err


def test_main_dispatches_to_the_named_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """The command name must actually reach the runner, and its code come back.

    Substituting the runner keeps this a unit test: dispatching correctly and
    lint passing are different questions, and only the first one is asked here.
    """
    seen: list[tuple[str, bool]] = []

    def fake_run(command: Command, *, echo: bool = True) -> int:
        seen.append((command.name, echo))
        return 17

    monkeypatch.setattr("tools.quality.__main__.run", fake_run)
    assert main(["lint"]) == 17, "main() must return the runner's exit code unchanged"
    assert [name for name, _ in seen] == ["lint"], f"main() dispatched to {seen}"
    assert all(echo for _, echo in seen), "the command line should show progress by default"


def test_run_reports_progress_when_echoing(capsys: pytest.CaptureFixture[str]) -> None:
    """The default run is not silent: a gate nobody can watch is hard to trust."""
    assert run(Command("noisy", "Passes loudly.", (_OK,)), echo=True) == 0
    out = capsys.readouterr().out
    assert "noisy" in out
    assert "ok" in out


def test_usage_lists_every_command() -> None:
    text = usage()
    missing = [name for name in command_names() if name not in text]
    assert not missing, f"commands absent from the help text: {missing}"


def test_the_package_exports_everything_it_declares() -> None:
    """`__all__` must describe the package, not aspire to it.

    A name listed but absent breaks `from tools.quality import *` and, more
    importantly, means the documented interface and the real one disagree.
    """
    missing = [name for name in quality.__all__ if not hasattr(quality, name)]
    assert not missing, f"declared in __all__ but not present: {missing}"
