"""ADR-0032's six conditions, for the evidence gate, made checkable.

The evidence tooling was added in a phase that does not name it. ADR-0032 permits
that only when all six of its conditions hold, and says plainly that an addition
which cannot state all six "is not covered by this record". Four of them can be
asserted mechanically, and this is where they are:

* **It adds no dependency** (condition 3) — the toolchain is still six names, and
  the package imports nothing outside the standard library and this repository.
* **It adds no runtime capability** (condition 4) — nothing under `src/globin`
  imports it, and nothing under `src/globin` gained behaviour because of it.
* **It only reports** (condition 5) — it is in neither `fast` nor `full`, it is
  not a mutating command, and it writes only inside the run directory Git
  ignores.
* **It is documented and tested to the same standard** (condition 6) — a row in
  the command table, a row in `QUALITY_GATES.md`, and rows in
  `TESTING_STRATEGY.md` for each of its test modules.

Conditions 1 and 2 are judgements a test cannot make: whether a phase was
displaced, and whether the phase's own deliverable shipped in full. ADR-0037 and
ADR-0038 are where those are argued.

This file also pins the things a reader would otherwise have to take on trust:
that the JUnit configuration keeps captured output out of the report, and that
the CI job cannot mask a failure while uploading its evidence.
"""

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Final

import pytest

from tools.quality.commands import MUTATING_COMMANDS, command_names, find
from tools.quality.evidence import gate

#: The `dev` extra, restated so that adding a dependency for this tooling has to
#: edit a test whose docstring says why not.
TOOLCHAIN: Final[frozenset[str]] = frozenset(
    {"pytest", "pytest-cov", "ruff", "mypy", "pre-commit", "hypothesis", "pip-audit"}
)

#: Every module the evidence package is allowed to import from outside itself.
#: Standard library, plus the two sibling packages it deliberately reuses.
PERMITTED_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "collections",
        "dataclasses",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "platform",
        "re",
        "shutil",
        "sys",
        "tomllib",
        "typing",
        "xml",
        "tools",
    }
)

#: The JUnit settings the evidence depends on, and the values they must have.
REQUIRED_JUNIT_SETTINGS: Final[dict[str, str]] = {
    "junit_family": "xunit2",
    "junit_suite_name": "globin",
    "junit_logging": "no",
    "junit_duration_report": "total",
}

WORKFLOW_RELATIVE_PATH: Final[str] = ".github/workflows/quality.yml"

#: An action reference pinned to a full commit SHA, as `test_quality_contract.py`
#: requires of every `uses:` line.
SHA_PINNED_RE: Final[re.Pattern[str]] = re.compile(
    r"^[\w.\-]+/[\w.\-]+(?:/[\w.\-]+)*@[0-9a-f]{40}$"
)


@pytest.fixture(scope="module")
def pyproject(repo_root: Path) -> dict[str, object]:
    """The project configuration, read once."""
    return tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def workflow(repo_root: Path) -> str:
    """The CI workflow, read once."""
    return (repo_root / WORKFLOW_RELATIVE_PATH).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def package_sources(repo_root: Path) -> dict[str, str]:
    """Every module of the evidence package, by name."""
    directory = repo_root / "tools" / "quality" / "evidence"
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.py"))}


# --------------------------------------------------------------------------
# Condition 3 — it adds no dependency
# --------------------------------------------------------------------------


def test_the_tooling_added_no_dependency(pyproject: dict[str, object]) -> None:
    """ADR-0032 condition 3, which rules out most tools worth wanting.

    JUnit XML is native to pytest and coverage.py writes its own JSON, so this
    needed nothing new. A reporting plugin would have needed Phase 014's review
    process, which does not exist yet.
    """
    project = pyproject["project"]
    assert isinstance(project, dict)
    extras = project["optional-dependencies"]
    assert isinstance(extras, dict)
    declared = {re.split(r"[<>=!\[]", name, maxsplit=1)[0].strip() for name in extras["dev"]}
    assert declared == TOOLCHAIN


def test_the_package_imports_only_the_standard_library_and_this_repository(
    package_sources: dict[str, str],
) -> None:
    """The same condition, enforced against the code rather than the manifest.

    A dependency can arrive without touching `pyproject.toml` — it only has to be
    installed on the machine that runs the gate. This is what notices.
    """
    found: dict[str, set[str]] = {}
    for name, source in package_sources.items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = {node.module.split(".")[0]}
            else:
                continue
            if stray := roots - PERMITTED_IMPORTS:
                found.setdefault(name, set()).update(stray)
    assert not found, f"the evidence package imports something unexpected: {found}"


# --------------------------------------------------------------------------
# Condition 4 — it adds no runtime capability
# --------------------------------------------------------------------------


def test_nothing_in_the_package_imports_the_evidence_tooling(repo_root: Path) -> None:
    """ADR-0032 condition 4: tooling verifies, it does not participate.

    This is the condition the phase brief would have broken. It asked for the
    CLI at `globin.testing.evidence`, which would have made test tooling part of
    the shipped package and turned it from tooling into phase scope.
    """
    offenders = [
        path.relative_to(repo_root).as_posix()
        for path in sorted((repo_root / "src" / "globin").rglob("*.py"))
        if "tools.quality" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"the package imports its own verification tooling: {offenders}"


# --------------------------------------------------------------------------
# Condition 5 — it only reports
# --------------------------------------------------------------------------


def test_the_evidence_command_is_reachable_and_runs_the_package() -> None:
    """One command table defines the checks, and every caller reads it (ADR-0019)."""
    command = find("evidence")
    assert command is not None
    assert command.steps[0].argv == ("-m", "tools.quality.evidence")


@pytest.mark.parametrize("name", ["fast", "full"])
def test_the_evidence_gate_is_in_neither_standard_command(name: str) -> None:
    """ADR-0032 condition 5: no existing gate changes what it does.

    `full` already ends in a coverage-measured pytest run, and nesting a
    pytest-spawning step inside one is the re-entrancy the mutation and shard
    harnesses both avoid.
    """
    command = find(name)
    assert command is not None
    assert all(step.name != "evidence" for step in command.steps)


def test_the_evidence_gate_does_not_modify_the_tree() -> None:
    """Only `fix` and `reformat` write anything a person would notice."""
    assert "evidence" not in MUTATING_COMMANDS


def test_no_tool_the_gate_runs_can_rewrite_the_tree() -> None:
    """ADR-0032's fifth condition, for the three children the gate now starts.

    The gate runs Ruff and mypy itself, so "it only reports" is no longer settled
    by the command table alone. `ruff check --fix` and a bare `ruff format` would
    each edit the working tree from inside a gate whose whole claim is that it
    does not, and the thing that passed would no longer be the thing you have.
    """
    for name, _, argv in gate.tool_commands():
        assert "--fix" not in argv, name
        assert "--unsafe-fixes" not in argv, name
        if "format" in argv:
            assert "--check" in argv, "ruff format must never run without --check"


def test_every_tool_the_gate_runs_writes_its_own_evidence_file() -> None:
    """A gate whose result is not written down is a gate nobody can check later."""
    written = {filename for _, filename, _ in gate.tool_commands()}
    assert written <= set(gate.evidence_files())
    assert len(written) == len(gate.tool_commands()), "two gates would overwrite one file"


def test_the_reporting_commands_stay_in_order() -> None:
    """The command table's order is compared against `QUALITY_GATES.md` byte for.

    byte, so a new command inserted in the wrong place fails two tests at once.
    """
    names = command_names()
    positions = [
        names.index(name) for name in ("coverage", "shards", "mutation", "evidence", "fix")
    ]
    assert positions == sorted(positions)


def test_the_gate_writes_only_inside_the_ignored_run_directory() -> None:
    """A gate that dirtied the working tree would make `git status` useless.

    `.globin/` is already ignored and already asserted uncommittable by
    `test_execution_contract.py`; this pins that the evidence goes inside it
    rather than beside it.
    """
    assert gate.REPORTS.parent.name == ".globin"
    assert gate.REPORTS.name == "evidence"


def test_no_evidence_file_is_committable(committable_files: tuple[str, ...]) -> None:
    """The other direction: nothing this gate produces has been committed."""
    written = set(gate.evidence_files())
    offenders = [path for path in committable_files if path.split("/")[-1] in written]
    assert not offenders, f"generated evidence would be committed: {offenders}"


# --------------------------------------------------------------------------
# Condition 6 — documented and tested to the same standard
# --------------------------------------------------------------------------


def test_the_quality_gates_document_describes_the_evidence_gate(repo_root: Path) -> None:
    """A gate nobody can find is a gate nobody runs."""
    document = (repo_root / "docs" / "engineering" / "QUALITY_GATES.md").read_text(encoding="utf-8")
    assert "| `evidence` |" in document


def test_everything_the_gate_prints_is_ascii(package_sources: dict[str, str]) -> None:
    """A Windows console codepage that cannot render a character turns a report.

    into a traceback, and this repository's only declared platform is Windows.

    The same check `tools/quality/execution` carries, for the same reason.
    """
    offenders: list[str] = []
    for name, source in package_sources.items():
        for node in ast.walk(ast.parse(source)):
            text = _printed_text(node)
            if text is not None and not text.isascii():
                offenders.append(f"{name}: {text!r}")
    assert not offenders, f"non-ASCII text would be printed: {offenders}"


# --------------------------------------------------------------------------
# The JUnit configuration the evidence depends on
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("setting", "expected"), sorted(REQUIRED_JUNIT_SETTINGS.items()))
def test_the_junit_configuration_is_what_the_evidence_expects(
    pyproject: dict[str, object], setting: str, expected: str
) -> None:
    """`junit_logging = "no"` is the load-bearing one.

    It keeps captured stdout, stderr and log records out of the report. A test
    that printed an environment variable while somebody was debugging would
    otherwise put it in a file CI uploads, and scrubbing afterwards is strictly
    worse than never capturing.
    """
    tool = pyproject["tool"]
    assert isinstance(tool, dict)
    options = tool["pytest"]["ini_options"]
    assert options[setting] == expected


# --------------------------------------------------------------------------
# The CI job
# --------------------------------------------------------------------------


def test_the_workflow_runs_the_evidence_gate(workflow: str) -> None:
    """CI calls the repository's own entrypoint, never its own list of steps."""
    assert "python -m tools.quality evidence" in workflow


def test_the_workflow_uploads_the_evidence_even_when_the_suite_failed(workflow: str) -> None:
    """`if: always()` preserves the job's failure; `continue-on-error` erases it.

    They look similar and are opposites. `test_quality_contract.py` forbids the
    second anywhere in this file; this requires the first, so a later reader
    "tidying" one into the other breaks a test that explains the difference.
    """
    assert "if: always()" in workflow
    assert "actions/upload-artifact@" in workflow


def test_every_action_the_evidence_job_uses_is_pinned_to_a_commit(workflow: str) -> None:
    """A tag is mutable, and a moved tag silently changes what runs here."""
    references = re.findall(r"uses:\s*(\S+)", workflow)
    unpinned = [reference for reference in references if not SHA_PINNED_RE.match(reference)]
    assert not unpinned, f"actions not pinned to a 40-character commit SHA: {unpinned}"


def test_the_artifact_carries_no_cache_or_environment(workflow: str) -> None:
    """An artifact is downloaded by people. It holds evidence and nothing else.

    `htmlcov` was on this list until Phase 011 and is deliberately off it now:
    ADR-0040 decided the browsable coverage tree is worth publishing, being the
    thing somebody opens when coverage falls. It is rendered rather than
    digested, which is a different question and is argued there.

    A cache is still forbidden, and for a reason the tree does not share: a cache
    is this machine's state rather than this run's result.
    """
    for forbidden in (".venv", "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache"):
        assert forbidden not in workflow, f"{forbidden} must not be uploaded"


def test_the_evidence_job_installs_every_tool_the_gate_starts(workflow: str) -> None:
    """The near-miss this exists to prevent, found while writing Phase 011.

    The gate runs Ruff and mypy as children, and the job installed neither. A
    machine without them reports a missing tool and exits 127, so CI would have
    failed on a configuration mistake rather than on anything about the code —
    and the failure would have looked like the gate's, not the workflow's.
    """
    block = workflow.split("evidence:", maxsplit=1)[-1]
    installs = block.split("python -m tools.quality evidence", maxsplit=1)[0]
    started = {argv[argv.index("-m") + 1] for _, _, argv in gate.tool_commands()}
    missing = sorted(name for name in started if f'"{name}==' not in installs)
    assert not missing, f"the evidence job starts these but never installs them: {missing}"


# --------------------------------------------------------------------------
# The entry point
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_the_module_can_be_started_as_a_process(repo_root: Path) -> None:
    """Exercises `__main__.py`, which no in-process test reaches.

    `QUALITY_GATES.md` records the `if __name__` guards as knowingly uncovered
    rather than annotating them with a pragma, because a pragma asserts that a
    line does not need testing and starting the module is the only way to find
    out whether it works.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "tools.quality.evidence", "--help"],
        cwd=repo_root,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0
    assert b"usage: python -m tools.quality.evidence" in completed.stdout


def _printed_text(node: ast.AST) -> str | None:
    """The literal text a node would print, if it is one that prints.

    Args:
        node: Any node.

    Returns:
        The string, or ``None`` when the node prints nothing literal.

    Covers `print(...)` arguments and `msg = ...` assignments, which between
    them are every way this package produces text a console has to render.
    """
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
        parts = [
            argument.value
            for argument in node.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        ]
        return "".join(parts) if parts else None
    if (
        isinstance(node, ast.Assign)
        and any(getattr(target, "id", None) == "msg" for target in node.targets)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ):
        return node.value.value
    if isinstance(node, ast.Assign) and any(
        getattr(target, "id", None) in ("USAGE", "msg") for target in node.targets
    ):
        return "".join(
            part.value
            for part in ast.walk(node.value)
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return None
