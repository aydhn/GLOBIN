"""Four words, and what happens to a fifth.

Two of the four subcommands reach the index and rewrite a committed file, so the
refusals here are load-bearing rather than pedantic: the cost of a
misunderstanding is a network call and a lock nobody asked for.
"""

import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.support import REPO_ROOT
from tools.quality.lock import cli
from tools.quality.lock.cli import (
    EXIT_USAGE,
    SUBCOMMANDS,
    USAGE,
    Invocation,
    UsageError,
    main,
    parse,
)
from tools.quality.lock.gate import CHECK, EXIT_UNMEASURED, INSTALLED, RELOCK, UPGRADE
from tools.quality.lock.plan import LockError


def test_no_argument_means_check() -> None:
    """The default is the one that reaches nothing and changes nothing."""
    assert parse([]) == Invocation(mode=CHECK, only=())


@pytest.mark.parametrize("word", sorted(SUBCOMMANDS - {UPGRADE}))
def test_each_subcommand_is_accepted_spelled_out(word: str) -> None:
    """Spelled out, because nothing here accepts an abbreviation."""
    assert parse([word]) == Invocation(mode=word, only=())


def test_upgrade_takes_one_name() -> None:
    """The only subcommand in this repository that takes a value."""
    assert parse([UPGRADE, "ruff"]) == Invocation(mode=UPGRADE, only=("ruff",))


def test_upgrade_takes_several_names() -> None:
    """A package whose upgrade needs a neighbour to move is named alongside it."""
    assert parse([UPGRADE, "ruff", "mypy"]).only == ("ruff", "mypy")


def test_upgrade_with_no_name_is_refused_rather_than_treated_as_relock() -> None:
    """The two do different things, and promoting one to the other is a surprise.

    `upgrade` moves what was named; `relock` moves everything with a newer
    release. Reading an empty `upgrade` as `relock` would hand somebody a diff
    they did not ask for, over the network.
    """
    with pytest.raises(UsageError, match="use relock"):
        parse([UPGRADE])


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["rel"], id="abbreviation"),
        pytest.param(["Check"], id="wrong-case"),
        pytest.param(["CHECK"], id="upper-case"),
        pytest.param(["--check"], id="flag-spelling"),
        pytest.param(["verify"], id="unknown-word"),
        pytest.param(["check", "installed"], id="two-subcommands"),
        pytest.param(["check", "check"], id="repeated"),
        pytest.param(["relock", "ruff"], id="relock-with-a-name"),
        pytest.param(["installed", "--quiet"], id="unknown-option"),
    ],
)
def test_a_command_line_this_parser_does_not_understand_is_refused(argv: list[str]) -> None:
    """No prefixes: `rel` meaning `relock` is a network call and a rewritten lock."""
    with pytest.raises(UsageError):
        parse(argv)


@pytest.mark.parametrize(
    "name",
    [pytest.param("--force", id="option"), pytest.param("", id="empty")],
)
def test_upgrade_refuses_something_that_is_not_a_distribution_name(name: str) -> None:
    """Caught before anything reaches the index."""
    with pytest.raises(UsageError):
        parse([UPGRADE, name])


def test_the_usage_is_ascii_and_documents_every_exit_code() -> None:
    """A Windows console encodes with the active code page.

    A character it cannot represent turns a usage message into a traceback, which
    is the least helpful moment for one.
    """
    assert USAGE.isascii()
    for code in ("0", "1", "2", "3"):
        assert f"  {code}  " in USAGE


def test_the_usage_says_which_subcommands_reach_the_index() -> None:
    """Somebody reading it must be able to tell which two are not free."""
    assert USAGE.count("REACHES THE INDEX") == 2
    for word in sorted(SUBCOMMANDS):
        assert word in USAGE


def test_the_usage_exit_code_is_distinct_from_every_verdict() -> None:
    """A misunderstood command line is not a failed check."""
    from tools.quality.lock.gate import EXIT_GATE_FAILED, EXIT_OK

    assert EXIT_USAGE not in {EXIT_OK, EXIT_GATE_FAILED, EXIT_UNMEASURED}


def test_relock_and_upgrade_are_the_two_that_reach_the_index() -> None:
    """Named here so a third could not be added without this test being read."""
    assert {RELOCK, UPGRADE} < SUBCOMMANDS
    assert {CHECK, INSTALLED} < SUBCOMMANDS
    assert len(SUBCOMMANDS) == 4


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


def test_a_bad_command_line_prints_the_usage_and_exits_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The usage is what a person reads after a typo, so it has to be printed."""
    assert main(["verify"]) == EXIT_USAGE
    printed = capsys.readouterr().out
    assert "unrecognised argument" in printed
    assert "Exit codes:" in printed


def test_an_upgrade_of_something_the_lock_does_not_carry_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checked against a closed set, so a typo is refused before anything is resolved.

    Without this, `upgrade ruf` would drop nothing from the constraints and quietly
    perform a wholesale relock over the network.
    """
    monkeypatch.setattr(cli, "_unknown", lambda only: tuple(sorted(only)))
    assert main([UPGRADE, "ruf"]) == EXIT_USAGE
    assert "no version to move: ruf" in capsys.readouterr().out


def test_an_upgrade_with_no_readable_lock_is_unmeasured(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """There is no closed set to check against, which is not the same as a typo."""

    def refuse(_only: object) -> tuple[str, ...]:
        msg = "pylock.dev.toml could not be read"
        raise LockError(msg)

    monkeypatch.setattr(cli, "_unknown", refuse)
    assert main([UPGRADE, "ruff"]) == EXIT_UNMEASURED
    assert "nothing to upgrade" in capsys.readouterr().out


def test_the_unknown_check_reads_the_committed_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Normalised on both sides, so `pip_audit` and `pip-audit` are one name."""
    monkeypatch.setattr(
        cli, "lock_of", lambda: SimpleNamespace(packages=(SimpleNamespace(normalised="pip-audit"),))
    )
    unknown = cli._unknown  # noqa: SLF001 -- the closed-set check is what is under test
    assert unknown(["pip_audit"]) == ()
    assert unknown(["ruff", "pip-audit"]) == ("ruff",)


def test_a_recognised_command_line_runs_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patched where the name is used, not where it is defined."""
    seen: list[tuple[str, tuple[str, ...]]] = []

    def record(*, mode: str, only: tuple[str, ...]) -> int:
        seen.append((mode, only))
        return 0

    monkeypatch.setattr(cli, "run_lock", record)
    assert main([INSTALLED]) == 0
    assert seen == [(INSTALLED, ())]


def test_a_gate_that_cannot_write_reports_unmeasured_rather_than_raising(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gate that could not record its answer has not given one."""

    def refuse(**_kwargs: object) -> int:
        msg = "read-only file system"
        raise OSError(msg)

    monkeypatch.setattr(cli, "run_lock", refuse)
    assert main([]) == EXIT_UNMEASURED
    assert "could not write its artefacts" in capsys.readouterr().out


@pytest.mark.slow
def test_the_module_starts_and_reports_its_usage() -> None:
    """`python -m tools.quality.lock` is how CI invokes this.

    Exercised through a real subprocess rather than excluded with a coverage
    pragma, on the reasoning `QUALITY_GATES.md` gives about the other module
    guards: a line excluded from measurement is a line nobody is measuring.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "tools.quality.lock", "nonsense"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert completed.returncode == EXIT_USAGE
    assert "usage: python -m tools.quality.lock" in completed.stdout
