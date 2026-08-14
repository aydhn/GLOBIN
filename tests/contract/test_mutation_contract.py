"""The mutation configuration, its baseline and the command table agree with each other.

Three documents describe one gate: ``[tool.globin.mutation]`` says what to
measure, ``docs/engineering/mutation-baseline.toml`` says what the answer should
be, and ``tools/quality/commands.py`` says how to run it. Any two of them can
drift apart, and the drift is quiet — a baseline naming a module nobody mutates
looks exactly like a baseline that is up to date.

The rule with the most weight here is the one about **reasons**. A survivor
recorded without an argument is a test gap nobody has defended, and the block the
harness prints on failure deliberately fills every reason with a placeholder. So
a contributor who pastes it unread fails this file rather than passing the gate,
which is the only way "deliberate reviewable change" is structural rather than
aspirational.
"""

import importlib
import tomllib
from pathlib import Path
from typing import Final

import pytest

from tools.quality.commands import MUTATING_COMMANDS, command_names, find
from tools.quality.mutation import baseline as baseline_module
from tools.quality.mutation import plan

CONFIGURATION_PATH: Final[str] = "pyproject.toml"


@pytest.fixture(scope="module")
def configuration(repo_root: Path) -> plan.Configuration:
    """The mutation configuration as the harness reads it."""
    document = tomllib.loads((repo_root / CONFIGURATION_PATH).read_text(encoding="utf-8"))
    return plan.read_configuration(document)


@pytest.fixture(scope="module")
def expectations(
    repo_root: Path, configuration: plan.Configuration
) -> dict[str, baseline_module.Expectation]:
    """The committed baseline as the harness reads it."""
    document = tomllib.loads((repo_root / configuration.baseline).read_text(encoding="utf-8"))
    return baseline_module.load(document)


# --------------------------------------------------------------------------
# The configuration describes things that exist
# --------------------------------------------------------------------------


def test_the_configuration_declares_at_least_one_target(
    configuration: plan.Configuration,
) -> None:
    """An empty target list would make every comparison below vacuous."""
    assert configuration.targets


def test_every_declared_path_resolves(repo_root: Path, configuration: plan.Configuration) -> None:
    """The check the harness itself makes before building anything.

    A mistyped test path is the one mistake that would otherwise reach pytest and
    come back as exit 5 — nothing collected, which a careless reading scores as a
    flawless run.
    """
    assert plan.validate(configuration, repo_root) == ()


def test_every_sandbox_entry_exists(repo_root: Path, configuration: plan.Configuration) -> None:
    missing = [entry for entry in configuration.sandbox if not (repo_root / entry).exists()]
    assert not missing, f"declared in the sandbox but absent: {missing}"


def test_the_sandbox_carries_the_file_that_makes_it_the_one_imported(
    configuration: plan.Configuration,
) -> None:
    """`pyproject.toml` is load-bearing, not incidental.

    pytest resolves `pythonpath = ["src", "."]` against its rootdir and inserts
    the result at `sys.path[0]`. Without the sandbox owning a copy of this file,
    the child would import the real package and report every mutant as surviving.
    """
    assert "pyproject.toml" in configuration.sandbox


def test_the_sandbox_carries_whatever_the_declared_tests_read(
    configuration: plan.Configuration,
) -> None:
    """A contract test in a subset reads a document, and the document has to be there."""
    for target in configuration.targets:
        for path in target.tests:
            if "contract" in path:
                assert "docs" in configuration.sandbox, path


# --------------------------------------------------------------------------
# The baseline describes the same things
# --------------------------------------------------------------------------


def test_the_baseline_and_the_configuration_name_the_same_modules(
    configuration: plan.Configuration, expectations: dict[str, baseline_module.Expectation]
) -> None:
    """Both directions. A baseline entry for a module nobody mutates is folklore."""
    assert set(expectations) == {target.module for target in configuration.targets}


def test_every_recorded_survivor_is_named_the_way_the_harness_names_one(
    expectations: dict[str, baseline_module.Expectation],
) -> None:
    for expectation in expectations.values():
        for identity in expectation.survivors:
            parts = identity.split("::")
            assert len(parts) == 4, identity
            assert parts[3].isdigit(), identity


def test_every_recorded_survivor_names_an_operator_that_exists(
    expectations: dict[str, baseline_module.Expectation],
) -> None:
    """An exemption for a retired operator is a stale exemption nobody would notice."""
    known = {
        "comparison",
        "boolean",
        "arithmetic",
        "not-removal",
        "integer",
        "boolean-constant",
    }
    for expectation in expectations.values():
        for identity in expectation.survivors:
            assert identity.split("::")[1] in known, identity


def test_every_recorded_survivor_carries_a_real_argument(
    expectations: dict[str, baseline_module.Expectation],
) -> None:
    """The rule that stops the suggested block being pasted without being read.

    The harness fills every reason it prints with a placeholder, so this is what
    turns "edit the baseline deliberately" from advice into a gate.
    """
    for expectation in expectations.values():
        for identity, reason in expectation.survivors.items():
            assert baseline_module.REASON_PLACEHOLDER not in reason, identity
            assert len(reason) >= baseline_module.MIN_REASON_LENGTH, identity


# --------------------------------------------------------------------------
# The command table
# --------------------------------------------------------------------------


def test_the_gate_is_reachable_through_the_one_command_table() -> None:
    """ADR-0019: a check that is not a name in that table is a check nobody runs."""
    command = find("mutation")
    assert command is not None
    assert command.steps


def test_the_gate_runs_the_package_as_a_module() -> None:
    command = find("mutation")
    assert command is not None
    assert command.steps[0].argv == ("-m", "tools.quality.mutation")


def test_the_gate_does_not_claim_to_modify_the_tree() -> None:
    """Two senses of "mutate" sit one screen apart in `commands.py`.

    `MUTATING_COMMANDS` means "writes to the working tree". The mutation gate
    writes only into a temporary directory, so its absence there is deliberate
    rather than an oversight, and this says so where somebody would look.
    """
    assert "mutation" not in MUTATING_COMMANDS


def test_the_gate_is_not_part_of_the_pre_commit_path() -> None:
    """`fast` promises seconds and `full` runs before every commit.

    A run that spawns one pytest per mutant belongs in neither, and `full` ending
    in a coverage-measured pytest run is also exactly the re-entrancy the harness
    works to avoid.
    """
    for name in ("fast", "full"):
        command = find(name)
        assert command is not None
        assert "mutation" not in {step.name for step in command.steps}


def test_the_gate_sits_last_among_the_checks_that_only_report() -> None:
    names = command_names()
    assert names.index("coverage") < names.index("mutation") < names.index("fix")


def test_the_entry_point_is_wired_to_the_gate() -> None:
    """`python -m tools.quality.mutation` has to reach something.

    Imported rather than run, because running it would start a full mutation run.
    The `if __name__` guard itself is the one statement in the package no test
    executes — the same trade `tools/quality/__main__.py` already makes.
    """
    entry = importlib.import_module("tools.quality.mutation.__main__")

    assert callable(entry.run)
    assert (Path(entry.REPO_ROOT) / "pyproject.toml").is_file()
