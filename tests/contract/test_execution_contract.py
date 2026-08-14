"""The execution harness is reachable one way, changes no gate, and adds nothing.

ADR-0032 permits verification tooling outside phase scope under six conditions.
Three of them are checkable rather than merely stated, and this module checks
them: it adds no dependency, it only reports, and it is documented like
everything else. Writing them as tests is the difference between a permission
that was granted and one that is still being honoured.
"""

from pathlib import Path
from typing import Final

import pytest

from tools.quality.commands import COMMANDS, MUTATING_COMMANDS, command_names, find

EXECUTION_COMMANDS: Final[tuple[str, ...]] = ("shards",)

TOOLCHAIN: Final[frozenset[str]] = frozenset(
    {"pytest", "pytest-cov", "ruff", "mypy", "pre-commit", "hypothesis"}
)
"""The six names ADR-0032 condition 3 pins. Restated here on purpose.

`test_packaging_contract.py` already asserts this set against `pyproject.toml`.
The copy is legitimate because this test asks a different question: not "is the
extra what it was" but "did *this* tooling change it". A future contributor
adding `pytest-xdist` has to edit two tests whose docstrings both say why not.
"""


@pytest.mark.parametrize("name", EXECUTION_COMMANDS)
def test_the_command_is_reachable_through_the_one_command_table(name: str) -> None:
    """ADR-0019: three consumers, one definition."""
    assert find(name) is not None


@pytest.mark.parametrize("name", EXECUTION_COMMANDS)
def test_the_command_runs_the_package_as_a_module(name: str) -> None:
    command = find(name)
    assert command is not None
    assert command.steps[0].argv[:2] == ("-m", "tools.quality.execution")


@pytest.mark.parametrize("name", EXECUTION_COMMANDS)
def test_the_command_is_not_part_of_the_pre_commit_path(name: str) -> None:
    """ADR-0032 condition 5: no existing gate changes what it does.

    `fast` promises seconds. `full` already ends in a coverage-measured pytest
    run, and nesting a pytest-spawning step inside one is the re-entrancy the
    mutation harness exists to avoid.
    """
    for gate in ("fast", "full"):
        command = find(gate)
        assert command is not None
        assert name not in {step.name for step in command.steps}


@pytest.mark.parametrize("name", EXECUTION_COMMANDS)
def test_the_command_does_not_claim_to_modify_the_tree(name: str) -> None:
    assert name not in MUTATING_COMMANDS


def test_the_reporting_commands_stay_in_order() -> None:
    """`coverage < shards < mutation < fix` — the checks that only report, last.

    The ordering is pinned by `test_mutation_contract.py` too, whose test is
    *named* for the gate sitting last among them. Appending after `mutation`
    would leave that assertion passing while its name became false.
    """
    names = command_names()
    assert names.index("coverage") < names.index("shards") < names.index("mutation")
    assert names.index("mutation") < names.index("fix")


def test_the_tooling_added_no_dependency(repo_root: Path) -> None:
    """ADR-0032 condition 3, asserted rather than promised.

    This is the condition that rules out `pytest-xdist`, and the one a future
    proposal will try to argue around. The dependency review it would need is
    Phase 014, which does not exist yet.
    """
    import tomllib

    with (repo_root / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    dev = pyproject["project"]["optional-dependencies"]["dev"]
    names = {entry.split(">")[0].split("=")[0].split("[")[0].strip() for entry in dev}
    assert names == TOOLCHAIN


@pytest.mark.parametrize("forbidden", ["xdist", "pytest_xdist", "pytest_rerunfailures"])
def test_no_command_declares_a_plugin_this_repository_refused(forbidden: str) -> None:
    """`xdist` is ADR-0032 condition 3; a rerun plugin is `TESTING_STRATEGY.md`."""
    declared = {module for command in COMMANDS for step in command.steps for module in step.modules}
    assert forbidden not in declared


@pytest.mark.parametrize("forbidden", ["--reruns", "--only-rerun", "rerun"])
def test_no_command_retries_a_failing_test(forbidden: str) -> None:
    """The executable form of `TESTING_STRATEGY.md`: diagnosed, never retried.

    A rerun turns a real defect into an intermittent green build, which is worse
    than a red one because it stops anybody looking.
    """
    for command in COMMANDS:
        for step in command.steps:
            assert forbidden not in step.argv, f"{command.name}/{step.name}"


def test_the_run_directory_is_ignored_by_git(
    repo_root: Path, committable_files: tuple[str, ...]
) -> None:
    """Generated artefacts must not reach a commit.

    `REPOSITORY_LAYOUT.md` insists the ignore rule exists *before* the first byte
    is written, because a mistake there is permanent in Git history.
    """
    ignored = (repo_root / ".gitignore").read_text(encoding="utf-8")
    assert ".globin/" in ignored
    assert not [path for path in committable_files if path.startswith(".globin/")]


def test_the_quality_gates_document_explains_the_command(repo_root: Path) -> None:
    """ADR-0032 condition 6: documented to the same standard as everything else."""
    document = (repo_root / "docs" / "engineering" / "QUALITY_GATES.md").read_text(encoding="utf-8")
    for name in EXECUTION_COMMANDS:
        assert f"| `{name}` |" in document


def test_the_document_records_what_was_deliberately_not_built(repo_root: Path) -> None:
    """An absence with no owner is a gap; one with an owner is a decision.

    `pytest-xdist`'s concurrency, dynamic balancing and worker-scoped fixtures
    are genuinely not delivered here, and the deferral register is where that
    belongs rather than in a commit message nobody will find.
    """
    document = (repo_root / "docs" / "engineering" / "QUALITY_GATES.md").read_text(encoding="utf-8")
    section = document.split("## Deliberately deferred", 1)[-1]
    assert "xdist" in section
    assert "014" in section


@pytest.mark.slow
def test_the_entry_point_works_as_a_process() -> None:
    """The one statement no in-process test executes.

    ``tools/quality/execution/__main__.py`` guards on ``__name__``, which is
    never true when the module is imported. The mutation harness makes the same
    trade for the same reason: a ``pragma`` would claim coverage the repository
    does not have, so the guard is exercised by actually running it.
    """
    import subprocess
    import sys

    from tools.quality.execution.gate import EXIT_USAGE, REPO_ROOT

    completed = subprocess.run(
        [sys.executable, "-m", "tools.quality.execution", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert b"--shards" in completed.stdout

    refused = subprocess.run(
        [sys.executable, "-m", "tools.quality.execution", "not-a-mode"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert refused.returncode == EXIT_USAGE


def test_everything_the_gate_prints_is_ascii() -> None:
    """A Windows console is frequently not UTF-8, and a CI log proved it.

    The first CI log this gate produced rendered its em dashes as replacement
    characters. `docs/LOGGING_POLICY.md` reached the same conclusion for log
    records and escapes non-ASCII for exactly this reason; this is the same
    constraint arrived at from the other direction, so it is checked rather than
    remembered.

    Only strings that actually reach a stream are examined — the arguments of a
    `print` call and anything bound to `msg` before being raised. Docstrings and
    comments are read in an editor and may say what they like.
    """
    import ast

    from tools.quality.execution.gate import REPO_ROOT

    offenders: list[str] = []
    for module in sorted((REPO_ROOT / "tools" / "quality" / "execution").glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            emitted: list[ast.AST] = []
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
                emitted = list(node.args)
            elif isinstance(node, ast.Assign) and any(
                getattr(target, "id", None) == "msg" for target in node.targets
            ):
                emitted = [node.value]
            offenders += [
                f"{module.name}:{piece.lineno}"
                for part in emitted
                for piece in ast.walk(part)
                if isinstance(piece, ast.Constant)
                and isinstance(piece.value, str)
                and not piece.value.isascii()
            ]
    assert not offenders, f"non-ASCII in a string a Windows console must render: {offenders}"
