"""The mutation gate, wired together, against a repository built for the occasion.

``tests/unit/test_mutation.py`` checks each judgement on its own. This checks the
order they happen in, which is where the design actually lives: two control runs
precede every verdict, and each exists to make one silent failure impossible.

Everything happens inside ``tmp_path``, against a four-file repository, with a
scripted stand-in for the child process. No real pytest runs, so these tests take
milliseconds and their result cannot depend on the machine — which matters more
than usual here, because the thing under test is a harness whose whole purpose is
to produce a verdict that does not.

The two failures worth reading the file for:

* **the control run** — if the unmutated subset does not pass, every mutant would
  be "killed" by a test that was already failing;
* **the canary** — if a module replaced by ``raise ImportError`` still leaves the
  subset passing, the sandbox is not being imported and every mutant would be
  reported as surviving. That one is not hypothetical: it is what happens if the
  sandbox stops owning a copy of ``pyproject.toml``.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import pytest

from tools.quality.mutation import gate

#: A module with exactly two mutation sites: the comparison and the literal.
MODULE: Final[str] = "def over(value):\n    return value > 1\n"

BASELINE: Final[str] = 'schema = 1\n\n[[target]]\nmodule = "src/pkg/thing.py"\n'

CONFIGURATION: Final[str] = """\
[tool.globin.mutation]
baseline = "baseline.toml"
sandbox = ["pyproject.toml", "src", "tests"]
timeout_factor = 2
timeout_floor_seconds = 5

[[tool.globin.mutation.target]]
module = "src/pkg/thing.py"
tests = ["tests/test_thing.py"]
"""


class _ScriptedRunner:
    """A child whose exit codes were decided in advance.

    Args:
        codes: One per call, in order: the control run, the canary, then one per
            mutant. Running out is an error rather than a default, because a
            script shorter than the run would silently test something else.
    """

    def __init__(self, *codes: int) -> None:
        self.remaining = list(codes)
        self.seen: list[str] = []
        self.calls: list[tuple[Sequence[str], Mapping[str, str], float]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        self.calls.append((argv, env, timeout))
        self.seen.append((cwd / "src" / "pkg" / "thing.py").read_text(encoding="utf-8"))
        if not self.remaining:
            msg = "the scripted child ran out of exit codes"
            raise AssertionError(msg)
        return self.remaining.pop(0), b"scripted"


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """A four-file repository the gate can be pointed at."""
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "thing.py").write_text(MODULE, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_thing.py").write_text("def test_over(): pass\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(CONFIGURATION, encoding="utf-8")
    (tmp_path / "baseline.toml").write_text(BASELINE, encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------


def test_a_run_that_kills_everything_passes(repository: Path) -> None:
    runner = _ScriptedRunner(0, 1, 1, 1)

    assert gate.run(repository, run_process=runner) == gate.EXIT_OK


def test_the_control_run_sees_the_module_unmutated(repository: Path) -> None:
    """The first thing the child is shown must be the real source."""
    runner = _ScriptedRunner(0, 1, 1, 1)

    gate.run(repository, run_process=runner)

    assert runner.seen[0] == MODULE


def test_the_canary_replaces_the_module_with_something_that_cannot_import(
    repository: Path,
) -> None:
    runner = _ScriptedRunner(0, 1, 1, 1)

    gate.run(repository, run_process=runner)

    assert "raise ImportError" in runner.seen[1]


def test_every_mutant_reaches_the_child_exactly_once(repository: Path) -> None:
    runner = _ScriptedRunner(0, 1, 1, 1)

    gate.run(repository, run_process=runner)

    mutants = runner.seen[2:]
    assert len(mutants) == 2
    assert len(set(mutants)) == 2
    assert MODULE not in mutants


def test_a_recorded_survivor_is_accepted(repository: Path) -> None:
    (repository / "baseline.toml").write_text(
        'schema = 1\n\n[[target]]\nmodule = "src/pkg/thing.py"\n\n'
        "  [[target.survivor]]\n"
        '  id = "over::comparison::Gt->GtE::0"\n'
        '  reason = "An argument long enough to be an argument rather than a shrug."\n',
        encoding="utf-8",
    )
    runner = _ScriptedRunner(0, 1, 0, 1)

    assert gate.run(repository, run_process=runner) == gate.EXIT_OK


# --------------------------------------------------------------------------
# The gate failing
# --------------------------------------------------------------------------


def test_an_unrecorded_survivor_fails_the_gate(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _ScriptedRunner(0, 1, 0, 1)

    assert gate.run(repository, run_process=runner) == gate.EXIT_GATE_FAILED

    reported = capsys.readouterr().err
    assert "survived, unrecorded" in reported
    assert "no --update" in reported


def test_a_failing_gate_prints_the_block_a_person_would_paste(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """And the block refuses to pass review unread: every reason is a placeholder."""
    gate.run(repository, run_process=_ScriptedRunner(0, 1, 0, 1))

    reported = capsys.readouterr().err
    assert "[[target.survivor]]" in reported
    assert "REPLACE THIS" in reported


# --------------------------------------------------------------------------
# The two controls, and everything that is not a verdict
# --------------------------------------------------------------------------


def test_a_subset_that_already_fails_stops_the_run(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Otherwise every mutant would be killed by a test that was broken beforehand."""
    assert gate.run(repository, run_process=_ScriptedRunner(1)) == gate.EXIT_UNMEASURED
    assert "nothing to measure" in capsys.readouterr().err


def test_a_canary_that_survives_stops_the_run(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The failure this whole design is shaped around, asserted rather than assumed.

    A module replaced by `raise ImportError` that still leaves the subset passing
    means the real package is being imported, not the sandbox.
    """
    assert gate.run(repository, run_process=_ScriptedRunner(0, 0)) == gate.EXIT_UNMEASURED
    assert "not being imported" in capsys.readouterr().err


@pytest.mark.parametrize(("code", "described"), [(5, "no-tests"), (4, "error"), (3, "error")])
def test_a_mutant_that_was_not_measured_stops_the_run(
    repository: Path, capsys: pytest.CaptureFixture[str], code: int, described: str
) -> None:
    """Exit 5 is the one that matters: nothing was collected, so nothing was proved."""
    runner = _ScriptedRunner(0, 1, code, 1)

    assert gate.run(repository, run_process=runner) == gate.EXIT_UNMEASURED

    reported = capsys.readouterr().err
    assert "was not measured" in reported
    assert described in reported


def test_the_module_is_put_back_before_the_run_ends(repository: Path) -> None:
    """The sandbox is thrown away, but the real tree must be untouched throughout."""
    gate.run(repository, run_process=_ScriptedRunner(0, 1, 1, 1))

    assert (repository / "src" / "pkg" / "thing.py").read_text(encoding="utf-8") == MODULE


# --------------------------------------------------------------------------
# Refusing to start
# --------------------------------------------------------------------------


def test_a_configuration_that_cannot_be_read_is_a_usage_error(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repository / "pyproject.toml").write_text("[tool.globin.mutation]\n", encoding="utf-8")

    assert gate.run(repository, run_process=_ScriptedRunner()) == gate.EXIT_USAGE
    assert "declares no" in capsys.readouterr().err


def test_a_declared_path_that_does_not_exist_is_a_usage_error(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Caught in the parent, before a sandbox exists — the alternative is exit 5."""
    (repository / "tests" / "test_thing.py").unlink()

    assert gate.run(repository, run_process=_ScriptedRunner()) == gate.EXIT_USAGE
    assert "test path does not exist" in capsys.readouterr().err


def test_a_baseline_that_cannot_be_read_is_a_usage_error(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repository / "baseline.toml").write_text(
        '[[target]]\nmodule = "src/pkg/thing.py"\n\n[[target.survivor]]\nid = "a"\n',
        encoding="utf-8",
    )

    assert gate.run(repository, run_process=_ScriptedRunner()) == gate.EXIT_USAGE
    assert "declares no reason" in capsys.readouterr().err


def test_a_missing_baseline_file_is_a_usage_error(repository: Path) -> None:
    (repository / "baseline.toml").unlink()

    assert gate.run(repository, run_process=_ScriptedRunner()) == gate.EXIT_USAGE
