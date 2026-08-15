"""The aggregate gate's conditions, asserted against the tree.

Three groups.

*ADR-0032's six conditions*, for the mechanically checkable ones. The aggregate
gate is tooling added in a phase that does not name it, and that record's
permission is conditional; conditions nobody checks are conditions somebody will
argue around.

*Drift between what is declared and what exists.* The required-job list, the
required-check name, the artifact name and the retention are each written in two
places — ``[tool.globin.workflow]`` and the workflow file — and two copies of a
rule are drift rather than a tripwire unless something compares them.

*The circular-digest guard.* An artifact cannot contain its own digest. The
design that avoids it is invisible once it works, so it is asserted here rather
than left as a thing somebody remembers.

The workflow is read as text and never parsed as YAML, for the reason
``test_quality_contract.py`` gives: a YAML parser would be a seventh entry in a
toolchain three tests pin at six, and the properties worth asserting are textual.
"""

import ast
import re
import tomllib
from pathlib import Path
from typing import Final

import pytest

from tools.quality.commands import COMMANDS, MUTATING_COMMANDS, command_names, find
from tools.quality.evidence.gate import REPORTS as EVIDENCE_REPORTS
from tools.quality.evidence.gate import evidence_files
from tools.quality.workflow.gate import AGGREGATE_FILE, REPORTS, expected_gates
from tools.quality.workflow.plan import read_configuration
from tools.quality.workflow.report import REPRODUCTION

WORKFLOW_RELATIVE_PATH: Final[str] = ".github/workflows/quality.yml"

AGGREGATE_JOB: Final[str] = "aggregate"
"""The job key the aggregate check is declared under."""

#: A job key: two spaces, a name, a colon, nothing else on the line. Only applied
#: to the region after `jobs:`, because `on:` has keys at the same indentation.
JOB_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^  ([a-z][\w-]*):$", re.MULTILINE)

#: A job's display name, which is what becomes a status check. Four spaces, so
#: this cannot match a step's `- name:`, which is indented further and dashed.
JOB_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^    name: (.+)$", re.MULTILINE)


@pytest.fixture(scope="module")
def workflow(repo_root: Path) -> str:
    """The CI workflow, read once."""
    return (repo_root / WORKFLOW_RELATIVE_PATH).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def jobs_block(workflow: str) -> str:
    """Everything after the top-level ``jobs:`` key."""
    return workflow.split("\njobs:\n", maxsplit=1)[-1]


@pytest.fixture(scope="module")
def pyproject(repo_root: Path) -> dict[str, object]:
    """The project configuration, read once."""
    return tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def package_sources(repo_root: Path) -> dict[str, str]:
    """Every module of the workflow package, by name."""
    directory = repo_root / "tools" / "quality" / "workflow"
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.py"))}


# --------------------------------------------------------------------------
# ADR-0032's conditions
# --------------------------------------------------------------------------


def test_the_tooling_added_no_dependency(pyproject: dict[str, object]) -> None:
    """Condition 3, which rules out most tools worth wanting.

    The aggregate reads two files and some environment variables. A reporting
    action or a YAML library would each have needed Phase 014's review process,
    which does not exist yet.
    """
    project = pyproject["project"]
    assert isinstance(project, dict)
    extras = project["optional-dependencies"]
    assert isinstance(extras, dict)
    declared = {re.split(r"[<>=!\[]", name, maxsplit=1)[0].strip() for name in extras["dev"]}
    assert len(declared) == 6


def test_the_package_imports_only_the_standard_library_and_this_repository(
    package_sources: dict[str, str],
) -> None:
    """The same condition, against the code rather than the manifest.

    A dependency can arrive without touching ``pyproject.toml`` — it only has to
    be installed on the machine that runs the gate.
    """
    permitted = {
        "collections",
        "dataclasses",
        "json",
        "os",
        "pathlib",
        "sys",
        "tomllib",
        "typing",
        "tools",
    }
    found: dict[str, set[str]] = {}
    for name, source in package_sources.items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = {node.module.split(".")[0]}
            else:
                continue
            outside = roots - permitted
            if outside:
                found.setdefault(name, set()).update(outside)
    assert not found, f"imports outside the standard library and this repository: {found}"


def test_the_package_does_not_import_globin(package_sources: dict[str, str]) -> None:
    """Condition 4. Tooling verifies; it does not participate.

    A verifier that imported the thing it verifies would fail to notice the day
    the thing stopped importing.
    """
    for name, source in package_sources.items():
        assert "globin" not in {
            node.module.split(".")[0]
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom) and node.module
        }, f"{name} imports globin"


def test_the_aggregate_is_in_neither_fast_nor_full() -> None:
    """Condition 5. No existing gate changes what it does because this exists."""
    for name in ("fast", "full"):
        command = find(name)
        assert command is not None
        assert "aggregate" not in {step.name for step in command.steps}


def test_the_aggregate_does_not_claim_to_modify_the_tree() -> None:
    """Condition 5 again. Only ``fix`` and ``reformat`` write anything."""
    assert "aggregate" not in MUTATING_COMMANDS


def test_the_aggregate_writes_only_inside_the_ignored_run_directory() -> None:
    """Nothing it produces can be committed by accident."""
    assert REPORTS.parent.name == ".globin"


def test_the_aggregate_is_reachable_only_through_the_one_command_table() -> None:
    """ADR-0019: every caller reads the table rather than keeping its own list."""
    assert "aggregate" in command_names()


def test_the_aggregate_sits_after_the_evidence_it_reads() -> None:
    """Ordering is documentation: a reader meets the gates in the order they run."""
    order = command_names()
    assert order.index("evidence") < order.index("aggregate") < order.index("fix")


def test_everything_the_package_prints_is_ascii(package_sources: dict[str, str]) -> None:
    """A Windows console codepage that cannot render a character raises rather than prints.

    Walks the arguments of every ``print`` call, which is where the gate's output
    comes from, rather than the whole file — a docstring may contain anything.
    """
    for name, source in package_sources.items():
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print"):
                continue
            for literal in ast.walk(node):
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                    assert literal.value.isascii(), f"{name} prints non-ASCII: {literal.value!r}"


# --------------------------------------------------------------------------
# Drift between what is declared and what exists
# --------------------------------------------------------------------------


def test_every_required_job_exists_in_the_workflow(
    pyproject: dict[str, object], jobs_block: str
) -> None:
    """A requirement naming a job nobody declares can never be satisfied."""
    declared = set(read_configuration(pyproject).required_jobs)
    present = set(JOB_KEY_RE.findall(jobs_block))
    assert declared <= present, (
        f"required but absent from the workflow: {sorted(declared - present)}"
    )


def test_every_workflow_job_is_either_required_or_the_aggregate_itself(
    pyproject: dict[str, object], jobs_block: str
) -> None:
    """The other direction, and the one that rots quietly.

    A job added to the workflow without being considered here would run, could
    fail, and would not affect the check anybody requires. Adding one is now a
    decision with a place to record it rather than an omission.
    """
    declared = set(read_configuration(pyproject).required_jobs)
    present = set(JOB_KEY_RE.findall(jobs_block))
    unaccounted = present - declared - {AGGREGATE_JOB}
    assert not unaccounted, f"jobs neither required nor the aggregate: {sorted(unaccounted)}"


def test_the_aggregate_does_not_require_itself(pyproject: dict[str, object]) -> None:
    """A job listed among its own dependencies is a cycle GitHub would refuse."""
    assert AGGREGATE_JOB not in read_configuration(pyproject).required_jobs


def test_the_declared_check_name_is_the_aggregate_job_name(
    pyproject: dict[str, object], jobs_block: str
) -> None:
    """The name in the documentation is the name a rule would have to match.

    A status check is identified by a job's display name, so renaming the job
    detaches every branch protection rule pointing at it. This is what makes that
    a test failure rather than a silent loss of enforcement.
    """
    block = jobs_block.split(f"\n  {AGGREGATE_JOB}:\n", maxsplit=1)[-1]
    name = JOB_NAME_RE.search(block)
    assert name is not None, "the aggregate job declares no name"
    assert name.group(1).strip() == read_configuration(pyproject).required_check


def test_no_two_jobs_share_a_check_name(workflow: str) -> None:
    """A required check name that matched two jobs would be ambiguous.

    The matrix job is excluded from the comparison by its own expression: its
    name carries ``matrix.python-version``, so it expands to one distinct check
    per interpreter rather than colliding with anything.
    """
    names = [name.strip() for name in JOB_NAME_RE.findall(workflow)]
    assert len(names) == len(set(names)), f"duplicate job names: {names}"


def test_the_declared_artifact_is_the_one_the_workflow_uploads(
    pyproject: dict[str, object], workflow: str
) -> None:
    """The summary names an artifact, and it has to be the one that exists."""
    assert f"name: {read_configuration(pyproject).artifact}" in workflow


def test_the_declared_retention_is_the_one_the_workflow_requests(
    pyproject: dict[str, object], workflow: str
) -> None:
    """``QUALITY_GATES.md`` states a number, and it is read from this setting."""
    retention = read_configuration(pyproject).retention_days
    assert f"retention-days: {retention}" in workflow
    assert "retention-days:" in workflow
    assert workflow.count("retention-days:") == workflow.count(f"retention-days: {retention}")


def test_the_aggregate_job_depends_on_every_required_job(
    pyproject: dict[str, object], jobs_block: str
) -> None:
    """Declared requirements it does not wait for would be read before they finished."""
    block = jobs_block.split(f"\n  {AGGREGATE_JOB}:\n", maxsplit=1)[-1]
    needs = re.search(r"^    needs: \[(.+)\]$", block, re.MULTILINE)
    assert needs is not None, "the aggregate job declares no needs"
    waited = {name.strip() for name in needs.group(1).split(",")}
    assert waited == set(read_configuration(pyproject).required_jobs)


def test_the_aggregate_job_runs_after_a_dependency_failed(jobs_block: str) -> None:
    """The hole this whole package exists to close.

    Without a condition, GitHub skips a job whose dependency failed — and a
    skipped required check is not a failing one. ``!cancelled()`` rather than
    ``always()``, so a run superseded by the next push does not spend a runner
    reporting on code nobody will merge.
    """
    block = jobs_block.split(f"\n  {AGGREGATE_JOB}:\n", maxsplit=1)[-1]
    assert "if: ${{ !cancelled() }}" in block.split("\n    steps:", maxsplit=1)[0]


def test_the_aggregate_job_runs_the_canonical_command(jobs_block: str) -> None:
    """ADR-0019 again: CI runs the table's command, not its own spelling of one."""
    assert "python -m tools.quality aggregate" in jobs_block


def test_the_aggregate_job_reverifies_the_published_evidence(jobs_block: str) -> None:
    """Different bytes: these have been through an upload and a download."""
    block = jobs_block.split(f"\n  {AGGREGATE_JOB}:\n", maxsplit=1)[-1]
    assert "actions/download-artifact@" in block
    assert "python -m tools.quality.evidence verify" in block


def test_the_evidence_job_publishes_the_artifact_digest(jobs_block: str) -> None:
    """It cannot be known before the upload, so it has to leave by this route."""
    assert "artifact-digest: ${{ steps.upload.outputs.artifact-digest }}" in jobs_block
    assert "GLOBIN_WORKFLOW_ARTIFACT_DIGEST: ${{ needs.evidence.outputs.artifact-digest }}" in (
        jobs_block
    )


# --------------------------------------------------------------------------
# The circular-digest guard
# --------------------------------------------------------------------------


def test_the_aggregate_is_not_part_of_the_evidence_bundle() -> None:
    """The impossible design, ruled out structurally.

    The aggregate records the evidence artifact's SHA-256, which GitHub computes
    from the finished artifact. Putting the aggregate inside that artifact would
    make the artifact's digest depend on a value derived from the artifact. It is
    a separate file in a separate directory, uploaded separately.
    """
    assert AGGREGATE_FILE not in evidence_files()
    assert REPORTS != EVIDENCE_REPORTS
    assert EVIDENCE_REPORTS not in REPORTS.parents


def test_the_evidence_bundle_carries_its_own_file_checksums() -> None:
    """The other integrity layer, which *can* live inside because it is computed first."""
    assert "checksums.sha256" in evidence_files()


def test_the_aggregate_requires_every_gate_the_evidence_run_produces() -> None:
    """Derived from the evidence gate, so a sixth tool becomes required by itself."""
    assert set(expected_gates()) >= {"tests", "coverage", "lint", "format", "typing"}


# --------------------------------------------------------------------------
# Condition 6 — documented to the same standard
# --------------------------------------------------------------------------


def test_the_quality_gates_document_names_the_check_to_require(
    repo_root: Path, pyproject: dict[str, object]
) -> None:
    """A check nobody can find the name of is a check nobody will require."""
    text = (repo_root / "docs" / "engineering" / "QUALITY_GATES.md").read_text(encoding="utf-8")
    assert read_configuration(pyproject).required_check in text


def test_the_quality_gates_document_says_branch_protection_is_not_configured_here(
    repo_root: Path,
) -> None:
    """Claiming the rule exists would describe a guarantee the code cannot give."""
    text = (repo_root / "docs" / "engineering" / "QUALITY_GATES.md").read_text(encoding="utf-8")
    assert "Branch protection is not configured here" in text


def test_every_reproduction_command_is_one_that_exists(repo_root: Path) -> None:
    """A troubleshooting section naming a command that does not exist costs the
    reader the time to find out.

    Each entry is either a quality command in the table or the verification
    script, checked by resolving it rather than by matching text.
    """
    names = set(command_names())
    for _label, command in REPRODUCTION:
        if command.startswith("powershell"):
            assert (repo_root / "scripts" / "verify.ps1").is_file()
            continue
        if command.startswith("python -m tools.quality.evidence"):
            assert (repo_root / "tools" / "quality" / "evidence" / "__main__.py").is_file()
            continue
        assert command.split()[-1] in names, f"not a command: {command}"


def test_every_command_in_the_table_is_documented() -> None:
    """The table and the document agree, which `test_quality_contract.py` also
    asserts — repeated here only as the guard for this package's own row."""
    assert len({command.name for command in COMMANDS}) == len(COMMANDS)
