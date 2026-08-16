"""The runtime gate's observation and failure paths, which a passing run never reaches.

:mod:`tools.quality.runtime.plan` is judgement and is tested from literals.
:mod:`tools.quality.runtime.gate` is the part that reads a real machine, and most
of what can go wrong there is a thing that did not happen on the machine running
this suite: no Git directory, no pip metadata, a launcher that refuses, a registry
that cannot be read, a child that fails to start.

Every one of those decides whether a finding says *failed* or *unmeasured*, and
the two are not interchangeable — ``docs/engineering/QUALITY_GATES.md`` is explicit
that unmeasured is never a pass. So they are exercised here rather than left to a
machine that happens to hit them.

**The gate's internals are imported by name rather than reached through the
module.** Both spellings mean the same thing, and this one says plainly that these
tests are about the inside of one module. It also keeps the file free of
thirty-odd ``noqa`` comments, which would be the only other way to say it.
"""

import importlib.metadata
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.quality.execution.plan import Verdict
from tools.quality.runtime import gate
from tools.quality.runtime.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    _create,
    _exit_code,
    _finding,
    _install_toolchain,
    _interpreter_is_environment,
    _joined,
    _launcher_output,
    _pip_configuration_sources,
    _pip_origin,
    _pip_version,
    _read,
    _remove,
    _report,
    _resolve,
    _sha,
    _tail,
    _verdict_of,
    observe_discovery,
    observe_environment,
    observe_host,
    observe_interpreter,
    observe_long_paths,
    observe_pip,
)
from tools.quality.runtime.plan import Environment

SHA = "a" * 40


def completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> "subprocess.CompletedProcess[str]":
    """A finished child process."""
    return subprocess.CompletedProcess(["child"], returncode, stdout, stderr)


def workflow_at(root: Path, body: str) -> None:
    """Write a workflow the toolchain register can be read from."""
    path = root / ".github" / "workflows" / "quality.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# The commit, read without starting Git
# ---------------------------------------------------------------------------


def test_a_tree_without_git_records_the_commit_as_unknown(tmp_path: Path) -> None:
    """Unknown is recorded rather than invented.

    A manifest can then be produced in a tree Git has never seen, which is every
    tree in this suite.
    """
    assert _sha(tmp_path) == "unknown"


def test_a_detached_head_is_read_directly(tmp_path: Path) -> None:
    """A detached HEAD holds the SHA itself."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text(SHA, encoding="utf-8")
    assert _sha(tmp_path) == SHA


def test_a_head_that_is_neither_a_reference_nor_a_sha_is_unknown(tmp_path: Path) -> None:
    """A truncated or corrupt HEAD is not a commit."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("garbage", encoding="utf-8")
    assert _sha(tmp_path) == "unknown"


def test_a_symbolic_head_is_followed_to_its_reference(tmp_path: Path) -> None:
    """The ordinary case: HEAD names a branch and the branch names a commit."""
    reference = tmp_path / ".git" / "refs" / "heads"
    reference.mkdir(parents=True)
    (reference / "master").write_text(f"{SHA}\n", encoding="utf-8")
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
    assert _sha(tmp_path) == SHA


def test_a_symbolic_head_pointing_at_nothing_is_unknown(tmp_path: Path) -> None:
    """A branch with no commits yet is not a commit either."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/gone\n", encoding="utf-8")
    assert _sha(tmp_path) == "unknown"


def test_a_file_that_cannot_be_read_is_reported_as_absent(tmp_path: Path) -> None:
    """Absence and unreadability are the same answer to the caller."""
    assert _read(tmp_path, "nothing.toml") is None


# ---------------------------------------------------------------------------
# Findings carry their own verdict
# ---------------------------------------------------------------------------


def test_a_check_that_found_nothing_passed() -> None:
    """The ordinary case."""
    assert _finding(()) == {"verdict": "passed", "problems": []}


def test_a_check_that_found_something_failed() -> None:
    """A problem is a failure, and the problem is kept."""
    assert _finding(("wrong",))["verdict"] == "failed"


def test_an_unmeasured_check_that_found_nothing_is_still_unmeasured() -> None:
    """The order matters.

    Getting it the other way round would turn every check that could not run into
    a pass, which is the one outcome that must never be inferred.
    """
    assert _finding((), measured=False)["verdict"] == "unmeasured"


def test_an_unrecognised_finding_reads_back_as_unmeasured() -> None:
    """A manifest section this gate did not write is never counted as a pass."""
    assert _verdict_of("not a finding") is Verdict.UNMEASURED
    assert _verdict_of({"verdict": "invented"}) is Verdict.UNMEASURED


@pytest.mark.parametrize(
    ("verdict", "code"),
    [
        (Verdict.PASSED, EXIT_OK),
        (Verdict.FAILED, EXIT_GATE_FAILED),
        (Verdict.UNMEASURED, EXIT_UNMEASURED),
    ],
)
def test_each_verdict_has_its_own_exit_code(verdict: Verdict, code: int) -> None:
    """Three verdicts, three codes, and no collapsing of two into one."""
    assert _exit_code(verdict) == code


# ---------------------------------------------------------------------------
# pip, when it is not where it should be
# ---------------------------------------------------------------------------


def test_pip_that_cannot_be_located_is_reported_rather_than_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken import path is an absent pip, not an assumed one."""

    def refuse(_name: str) -> None:
        msg = "no pip here"
        raise ImportError(msg)

    monkeypatch.setattr(importlib.util, "find_spec", refuse)
    assert _pip_origin() is None


def test_pip_with_no_module_origin_is_reported_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A namespace package has a spec and no file to point at."""

    class _Spec:
        origin = None

    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: _Spec())
    assert _pip_origin() is None


def test_pip_without_installed_metadata_reports_an_unknown_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vendored pip has no distribution metadata."""

    def refuse(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", refuse)
    assert _pip_version() == "unknown"


def test_pip_configuration_sources_are_recorded_by_scope_and_never_by_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An index URL is the likeliest credential in this document.

    The way to keep one out is not to read it, so only the scope and whether the
    file exists are recorded — never the path, which on a user scope carries the
    account name.
    """
    monkeypatch.setenv("PROGRAMDATA", "C:\\ProgramData")
    monkeypatch.setenv("APPDATA", "C:\\Users\\Someone\\AppData\\Roaming")
    monkeypatch.delenv("HOME", raising=False)

    sources = _pip_configuration_sources()

    assert [entry["scope"] for entry in sources] == ["global", "user", "user-legacy", "site"]
    assert all(set(entry) == {"scope", "exists"} for entry in sources)
    assert "Someone" not in str(sources)


def test_a_configuration_scope_whose_variable_is_unset_is_recorded_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset variable is not a path, and joining onto it would invent one."""
    monkeypatch.delenv("PROGRAMDATA", raising=False)

    assert _joined(None, "pip", "pip.ini") is None
    scope = next(entry for entry in _pip_configuration_sources() if entry["scope"] == "global")
    assert scope["exists"] is False


def test_pip_overrides_are_recorded_by_name_and_never_by_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The name says an override is in force; the value says what it is.

    The first is worth having and the second is worth not publishing, so only the
    names are recorded.
    """
    monkeypatch.setenv("PIP_INDEX_URL", "https://user:secret@example.invalid/simple")

    observed = observe_pip(tmp_path)

    overrides = observed["environment_overrides"]
    assert isinstance(overrides, list)
    assert "PIP_INDEX_URL" in overrides
    assert "secret" not in str(observed)


# ---------------------------------------------------------------------------
# The launcher, and hosts that do not have one
# ---------------------------------------------------------------------------


def test_a_host_with_the_install_manager_counts_its_runtimes_without_naming_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manager's JSON schema has never been read on a host that has it.

    Inventing one would be the guess ``AGENTS.md`` forbids, so the documented
    ``--format=exe`` is used instead and only the count is kept.
    """
    monkeypatch.setattr(shutil, "which", lambda name: "somewhere" if name else None)

    observed = observe_discovery(
        lambda *_a, **_k: completed(stdout="C:\\A\\python.exe\nC:\\B\\python.exe\n")
    )

    assert observed["launcher"] == "python-install-manager"
    assert observed["count"] == 2
    assert observed["runtimes"] == []
    assert "C:\\A" not in str(observed)


def test_a_host_with_no_python_at_all_is_recorded_as_such(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent is a state, and the fourth one this classification has."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert observe_discovery(None)["launcher"] == "absent"


def test_a_launcher_that_refuses_leaves_the_runtime_list_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-zero exit is not a listing.

    Treating its output as one would record whatever the error message happened to
    look like as though it were a runtime.
    """
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "pymanager" else "py")

    observed = observe_discovery(lambda *_a, **_k: completed(returncode=1, stdout="nope"))

    assert observed["launcher"] == "legacy-launcher"
    assert observed["count"] == 0


def test_a_launcher_that_cannot_be_started_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing executable is a host without a launcher, not a broken gate."""
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "pymanager" else "py")

    def refuse(*_args: object, **_kwargs: object) -> "subprocess.CompletedProcess[str]":
        msg = "not executable"
        raise OSError(msg)

    assert observe_discovery(refuse)["count"] == 0


def test_the_launcher_output_helper_reports_a_refusal_as_no_output() -> None:
    """Output from a failed command is not output."""
    assert _launcher_output(("py",), lambda *_a, **_k: completed(returncode=2)) is None


# ---------------------------------------------------------------------------
# Long paths, which are recorded rather than fixed
# ---------------------------------------------------------------------------


def test_an_unreadable_long_path_setting_is_unmeasured_rather_than_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0045: an absence is recorded as an absence.

    "We could not read it" and "it is switched off" are different facts with
    different remedies, and rounding the first to the second would send somebody
    to change a setting that may already be right.
    """
    import winreg

    def refuse(*_args: object, **_kwargs: object) -> None:
        msg = "access denied"
        raise OSError(msg)

    monkeypatch.setattr(winreg, "OpenKey", refuse)
    assert observe_long_paths()["state"] == "unmeasured"


def test_a_host_with_no_registry_records_the_long_path_setting_as_unmeasured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The branch a non-Windows host takes.

    GLOBIN declares one platform, so this is the only way the code path is ever
    reached — and leaving it untested would leave the gate's behaviour on a host it
    might one day meet entirely unknown.
    """
    monkeypatch.setitem(sys.modules, "winreg", None)
    assert observe_long_paths() == {
        "state": "unmeasured",
        "reason": "this host has no Windows registry",
    }


def test_the_long_path_setting_is_read_as_a_state() -> None:
    """Whatever this host says, it is one of three words and never a bare pass."""
    assert observe_long_paths()["state"] in {"enabled", "disabled", "unmeasured"}


# ---------------------------------------------------------------------------
# Children that fail
# ---------------------------------------------------------------------------


def test_a_venv_that_cannot_be_started_is_reported(tmp_path: Path) -> None:
    """A missing interpreter is a finding, not a traceback."""

    def refuse(*_args: object, **_kwargs: object) -> "subprocess.CompletedProcess[str]":
        msg = "no interpreter"
        raise OSError(msg)

    problems = _create(tmp_path / ".venv", refuse)
    assert any("could not be created" in problem for problem in problems)


def lock_at(root: Path, text: str = 'lock-version = "1.0"\ncreated-by = "pip"\n') -> Path:
    """Write a development lock into a synthetic tree.

    Args:
        root: The tree.
        text: What to write. The default is enough for `_install_toolchain`,
            which checks that the file exists and hands it to pip rather than
            reading it — parsing a lock is `tools/quality/lock`'s job.

    Returns:
        The path written.
    """
    path = root / gate.DEVELOPMENT_LOCK
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def test_the_toolchain_is_installed_from_the_lock_by_default(tmp_path: Path) -> None:
    """Since Phase 020 the lock is what bootstrap installs, not the workflow pins.

    The pins cover the seven direct tools; the lock covers all forty-nine, each
    with a digest. Asserted through the argv rather than through the outcome,
    because the outcome of a faked `pip install` is whatever the fake returns.
    """
    lock_at(tmp_path)
    workflow_at(tmp_path, 'jobs:\n  a:\n    steps:\n      - run: pip install "ruff==0.15.14"\n')
    seen: list[list[str]] = []

    def record(argv: list[str], **_kwargs: object) -> "subprocess.CompletedProcess[str]":
        seen.append(argv)
        return completed()

    assert _install_toolchain(tmp_path, tmp_path / ".venv", record) == ()
    assert seen, "pip was never started"
    assert "--requirement" in seen[0]
    assert any(argument.endswith(gate.DEVELOPMENT_LOCK) for argument in seen[0])
    assert not any("ruff==" in argument for argument in seen[0])


def test_a_missing_lock_is_refused_rather_than_falling_back_to_the_pins(tmp_path: Path) -> None:
    """The fallback would be taken on exactly the day the lock is wrong.

    The workflow register is present and perfectly usable here, and is still not
    used: a silent substitution is what ADR-0054 refuses, and the message names
    the deliberate alternative instead of quietly being it.
    """
    workflow_at(tmp_path, 'jobs:\n  a:\n    steps:\n      - run: pip install "ruff==0.15.14"\n')

    def refuse(*_args: object, **_kwargs: object) -> "subprocess.CompletedProcess[str]":
        message = "pip must not be started when the lock is missing"
        raise AssertionError(message)

    problems = _install_toolchain(tmp_path, tmp_path / ".venv", refuse)
    assert any(gate.DEVELOPMENT_LOCK in problem for problem in problems)
    assert any("--from-pins" in problem for problem in problems)


def test_a_toolchain_install_that_cannot_be_started_is_reported(tmp_path: Path) -> None:
    """The environment's own interpreter may not exist yet."""
    lock_at(tmp_path)

    def refuse(*_args: object, **_kwargs: object) -> "subprocess.CompletedProcess[str]":
        msg = "no interpreter"
        raise OSError(msg)

    problems = _install_toolchain(tmp_path, tmp_path / ".venv", refuse)
    assert any("could not be installed" in problem for problem in problems)


def test_a_toolchain_install_that_exits_non_zero_is_reported(tmp_path: Path) -> None:
    """A recorded digest that does not match what was served is the case here now."""
    lock_at(tmp_path)

    problems = _install_toolchain(
        tmp_path,
        tmp_path / ".venv",
        lambda *_a, **_k: completed(returncode=1, stderr="THESE PACKAGES DO NOT MATCH"),
    )
    assert any("pip install exited 1" in problem for problem in problems)


def test_a_tree_with_no_workflow_register_cannot_install_from_pins(tmp_path: Path) -> None:
    """Under `--from-pins` the versions still come from the workflow register.

    A tree without one therefore has no toolchain to install, rather than a
    default one this function would have had to invent.
    """
    problems = _install_toolchain(
        tmp_path, tmp_path / ".venv", lambda *_a, **_k: completed(), from_pins=True
    )
    assert any("no pinned toolchain" in problem for problem in problems)


def test_a_workflow_register_that_contradicts_itself_is_reported(tmp_path: Path) -> None:
    """Two jobs pinning one package to two versions is a finding, not a merge."""
    workflow_at(
        tmp_path,
        "jobs:\n"
        '  a:\n    steps:\n      - run: pip install "ruff==0.15.14"\n'
        '  b:\n    steps:\n      - run: pip install "ruff==0.16.0"\n',
    )

    problems = _install_toolchain(
        tmp_path, tmp_path / ".venv", lambda *_a, **_k: completed(), from_pins=True
    )
    assert problems
    assert any("ruff" in problem for problem in problems)


def test_an_environment_that_cannot_be_removed_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file held open by another process is the usual cause on Windows."""
    location = tmp_path / ".venv"
    location.mkdir()

    def refuse(*_args: object, **_kwargs: object) -> None:
        msg = "in use by another process"
        raise OSError(msg)

    monkeypatch.setattr(shutil, "rmtree", refuse)
    problems = _remove(tmp_path, location, ".venv")
    assert any("could not be removed" in problem for problem in problems)


def test_removal_refuses_a_directory_that_is_not_the_declared_one(tmp_path: Path) -> None:
    """The gate consults the pure judgement before it calls ``rmtree``.

    This is the assertion that it actually does, rather than that the judgement
    would have said no if anyone had asked it.
    """
    other = tmp_path / "src"
    other.mkdir()

    problems = _remove(tmp_path, other, ".venv")

    assert problems
    assert other.is_dir(), "a refused removal must not have removed anything"


def test_an_environment_that_cannot_be_resolved_is_not_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unresolvable path is refused rather than removed on its unresolved form."""
    monkeypatch.setattr(gate, "_resolve", lambda _path: None)
    problems = _remove(tmp_path, tmp_path / ".venv", ".venv")
    assert any("could not be resolved" in problem for problem in problems)


def test_a_path_that_cannot_be_resolved_is_reported_as_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unresolved path might be relative to a working directory nobody recorded."""

    def refuse(_self: Path, **_kwargs: object) -> Path:
        msg = "the name is too long"
        raise OSError(msg)

    monkeypatch.setattr(Path, "resolve", refuse)
    assert _resolve(tmp_path) is None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"), [(None, "no output"), ("", "no output"), ("  a\n  b  ", "a b")]
)
def test_child_output_is_flattened_for_a_finding(text: str | None, expected: str) -> None:
    """A finding is one line, so the child's newlines are collapsed."""
    assert _tail(text) == expected


def test_child_output_is_truncated_to_its_end() -> None:
    """The end of a traceback names the failure; the beginning names the caller."""
    assert _tail("x" * 900, limit=10) == "x" * 10


def test_a_report_skips_a_section_that_is_not_a_finding(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A malformed section is skipped rather than printed as an empty check."""
    _report({"real": _finding(("wrong",)), "odd": "not a dict"}, Verdict.FAILED, ["R"])

    printed = capsys.readouterr().out
    assert "runtime: real: failed" in printed
    assert "  - wrong" in printed
    assert "runtime: reasons R" in printed
    assert "odd" not in printed


def test_a_passing_report_names_no_reasons(capsys: pytest.CaptureFixture[str]) -> None:
    """There is nothing to explain when nothing failed."""
    _report({"real": _finding(())}, Verdict.PASSED, [])
    assert "reasons" not in capsys.readouterr().out


def test_a_report_with_no_findings_still_names_the_verdict(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A run that measured nothing still says so."""
    _report({}, Verdict.UNMEASURED, [])
    assert "runtime: verdict unmeasured" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Observation of the machine this suite is running on
# ---------------------------------------------------------------------------


def test_the_running_interpreter_describes_itself_consistently() -> None:
    """The shape of the answer, not which interpreter it is.

    Asserting the version would only ever assert what this machine happens to be,
    and would fail on the other job of the CI matrix for no useful reason.
    """
    observed = observe_interpreter()

    assert observed.implementation
    assert observed.pointer_bits in {32, 64}
    assert observed.release_level in {"alpha", "beta", "candidate", "final"}
    assert observed.version.line.count(".") == 1


def test_the_host_describes_itself_consistently() -> None:
    """As above, for the operating system."""
    observed = observe_host()

    assert observed.system
    assert isinstance(observed.kernel, str)


def test_an_absent_environment_is_observed_as_absent(tmp_path: Path) -> None:
    """Nothing is inferred about an environment that is not there."""
    observed = observe_environment(tmp_path, ".venv")

    assert observed.present is False
    assert observed.location is None
    assert observed.config == {}


def test_an_interpreter_outside_any_environment_is_not_the_project_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A base interpreter whose prefix equals the environment directory is still not one.

    The ``sys.prefix != sys.base_prefix`` test is what separates a virtual
    environment from a coincidence of paths.
    """
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path))

    observed = Environment(present=True, location=tmp_path.resolve())

    assert _interpreter_is_environment(observed) is False
