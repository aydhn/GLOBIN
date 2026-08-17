"""Verify that the quality system is configured the way it is documented.

Phase 004 put the same facts in several places on purpose — the taxonomy exists
as directories, as a marker registry and as documentation; the tool versions
exist in a pre-commit revision and in a CI pin. Each of those copies is only
safe while something fails when they disagree, which is what this module is
(`SOURCE_OF_TRUTH.md` on tripwires versus drift).

The workflow and the hook configuration are checked as text rather than parsed
as YAML. That is not laziness: adding a YAML parser would mean another entry in
the development toolchain that `test_packaging_contract.py` pins exactly, and the
properties worth asserting here — that an action reference is a forty-character
SHA, that no step is allowed to fail silently — are textual anyway.
"""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from tests.support import TAXONOMY_LEVELS, markdown_section, spelled_size
from tools.quality.commands import command_names

#: Attribute markers that are registered but not applied by directory. They
#: describe a property of a test, not its level, so a test may carry none of
#: them or several.
ATTRIBUTE_MARKERS: tuple[str, ...] = (
    "slow",
    "network",
    "external",
    "windows",
    "loopback",
)

#: A pinned GitHub Actions reference: `uses: owner/repo@<40 hex characters>`.
ACTION_USE_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>\S+)", re.MULTILINE)
SHA_PINNED_RE = re.compile(r"^[\w.\-]+/[\w.\-]+(?:/[\w.\-]+)*@[0-9a-f]{40}$")

#: A table row whose whole first cell is one lowercase backticked word. Used for
#: the command table in `QUALITY_GATES.md` and the marker table in
#: `TESTING_STRATEGY.md`. Requiring the closing backtick to be followed
#: immediately by the cell separator is what keeps it from also matching rows
#: such as ``| `if TYPE_CHECKING:` bodies |``.
BACKTICKED_FIRST_CELL_RE = re.compile(r"^\| `(?P<name>[a-z]+)` \|", re.MULTILINE)

#: A test-module row of the "What the suite enforces" table in
#: `TESTING_STRATEGY.md`.
STRATEGY_MODULE_ROW_RE = re.compile(r"^\| `(?P<module>test_[a-z0-9_]+\.py)` \|", re.MULTILINE)


@pytest.fixture(scope="module")
def pyproject(repo_root: Path) -> dict[str, Any]:
    with (repo_root / "pyproject.toml").open("rb") as handle:
        data: dict[str, Any] = tomllib.load(handle)
    return data


@pytest.fixture(scope="module")
def workflow(repo_root: Path) -> str:
    return (repo_root / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def precommit(repo_root: Path) -> str:
    return (repo_root / ".pre-commit-config.yaml").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The taxonomy is the directory layout
# --------------------------------------------------------------------------


def test_every_test_module_lives_in_a_taxonomy_directory(repo_root: Path) -> None:
    """A test outside the taxonomy gets no marker and silently escapes `-m` selection.

    That is the failure worth catching: the test still runs in a full sweep, so
    nothing looks wrong, while every filtered run quietly omits it.
    """
    tests_dir = repo_root / "tests"
    stray = [
        path.relative_to(repo_root).as_posix()
        for path in sorted(tests_dir.rglob("test_*.py"))
        if path.parent.name not in TAXONOMY_LEVELS
    ]
    assert not stray, f"test modules outside the taxonomy: {stray}"


@pytest.mark.parametrize("level", TAXONOMY_LEVELS)
def test_each_taxonomy_level_holds_real_tests(repo_root: Path, level: str) -> None:
    """An empty level is a claim that a kind of testing happens when it does not.

    `REPOSITORY_LAYOUT.md` prohibits directories that exist to look organised;
    this applies the same rule to the suite.
    """
    directory = repo_root / "tests" / level
    assert directory.is_dir(), f"missing taxonomy directory: tests/{level}"
    assert (directory / "__init__.py").is_file(), f"tests/{level} is not a package"
    modules = list(directory.glob("test_*.py"))
    assert modules, f"tests/{level}/ contains no tests, so the level is a label only"


def test_the_taxonomy_marker_is_applied_by_the_collection_hook(
    request: pytest.FixtureRequest,
) -> None:
    """This test must carry `contract`, and it never says so itself.

    If the hook in `tests/conftest.py` stopped working, every `-m` selection
    would silently return nothing while the full suite stayed green.
    """
    own_markers = {marker.name for marker in request.node.iter_markers()}
    assert "contract" in own_markers, (
        f"the directory-derived marker was not applied; markers seen: {sorted(own_markers)}"
    )
    levels = own_markers & set(TAXONOMY_LEVELS)
    assert levels == {"contract"}, f"expected exactly one taxonomy marker, got {sorted(levels)}"


# --------------------------------------------------------------------------
# pytest configuration
# --------------------------------------------------------------------------


def test_every_taxonomy_and_attribute_marker_is_registered(pyproject: dict[str, Any]) -> None:
    """`--strict-markers` turns an unregistered marker into an error, not a typo."""
    declared = {
        entry.split(":", 1)[0].strip()
        for entry in pyproject["tool"]["pytest"]["ini_options"]["markers"]
    }
    missing = [name for name in (*TAXONOMY_LEVELS, *ATTRIBUTE_MARKERS) if name not in declared]
    assert not missing, f"markers used or reserved but not registered: {missing}"


def test_every_registered_marker_carries_a_description(pyproject: dict[str, Any]) -> None:
    """A bare marker name teaches nobody when to apply it."""
    thin = [
        entry
        for entry in pyproject["tool"]["pytest"]["ini_options"]["markers"]
        if len(entry.split(":", 1)) < 2 or not entry.split(":", 1)[1].strip()
    ]
    assert not thin, f"markers registered without a description: {thin}"


def test_marker_and_config_strictness_stay_on(pyproject: dict[str, Any]) -> None:
    """Strictness must be declared as ini options, not as flags inside `addopts`.

    `--strict-markers` in `addopts` does not take effect: pytest 9 emits
    `PytestUnknownMarkWarning` and the run passes. Only the ini option is
    enforced at collection. The distinction is invisible in a passing suite,
    which is why it is pinned here as well as exercised end to end below.
    """
    options = pyproject["tool"]["pytest"]["ini_options"]
    assert options.get("strict_markers") is True, (
        "strict_markers must be an ini option; the addopts flag is silently ineffective"
    )
    assert options.get("strict_config") is True
    assert "--strict-markers" not in options["addopts"], (
        "the addopts form gives false confidence; keep the ini option as the only declaration"
    )
    assert options["xfail_strict"] is True, "an xpass must fail; a fixed bug should not stay xfail"
    assert options["filterwarnings"] == ["error"], "a warning must surface when it appears"


# --------------------------------------------------------------------------
# The marker contract can actually fail
#
# Asserting that `--strict-markers` appears in `addopts` proves the string is
# present, not that it does anything. These two tests run pytest against a
# throwaway project configured from THIS repository's marker settings, so what
# is exercised is the configuration rather than pytest's documentation.
#
# The pair matters more than either half. A negative case that passes because
# the temporary project was broken would look identical to one that passes for
# the right reason, so the registered-marker control runs the same tree with the
# single thing under test changed.
# --------------------------------------------------------------------------


def _mini_project(tmp_path: Path, options: dict[str, Any], marker: str) -> Path:
    """Write a one-test project using this repository's marker configuration.

    The strictness options are copied from ``options`` rather than hard-coded,
    so this exercises whatever GLOBIN actually declares. Copying them wrongly is
    what the registered-marker control catches.
    """
    addopts = ",\n".join(f"    {json.dumps(opt)}" for opt in options["addopts"])
    markers = ",\n".join(f"    {json.dumps(entry)}" for entry in options["markers"])
    flags = "".join(
        f"{key} = {str(options[key]).lower()}\n"
        for key in ("strict_markers", "strict_config", "xfail_strict")
        if key in options
    )
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.pytest.ini_options]\n{flags}"
        f"addopts = [\n{addopts},\n]\nmarkers = [\n{markers},\n]\n",
        encoding="utf-8",
    )
    (tmp_path / "test_sample.py").write_text(
        f"import pytest\n\n\n@pytest.mark.{marker}\ndef test_it() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    return tmp_path


def _run_pytest(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.slow
def test_an_unregistered_marker_is_rejected(tmp_path: Path, pyproject: dict[str, Any]) -> None:
    """A typo in a marker name must stop the run, not silently deselect the test."""
    options = pyproject["tool"]["pytest"]["ini_options"]
    project = _mini_project(tmp_path, options, "definitely_not_a_registered_marker")
    result = _run_pytest(project)
    assert result.returncode != 0, "an unknown marker was accepted; --strict-markers is not working"
    combined = result.stdout + result.stderr
    assert "definitely_not_a_registered_marker" in combined, (
        f"the failure did not name the offending marker:\n{combined}"
    )


@pytest.mark.slow
def test_a_registered_marker_is_accepted(tmp_path: Path, pyproject: dict[str, Any]) -> None:
    """The control for the test above: same tree, registered marker, must pass.

    Without this, a temporary project that failed to run at all would make the
    negative case look like a working guard.
    """
    options = pyproject["tool"]["pytest"]["ini_options"]
    project = _mini_project(tmp_path, options, "unit")
    result = _run_pytest(project)
    assert result.returncode == 0, (
        f"a registered marker was rejected, so the negative case proves nothing:\n"
        f"{result.stdout}{result.stderr}"
    )


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------


def test_coverage_is_branch_aware_and_gated(pyproject: dict[str, Any]) -> None:
    """Line coverage alone reports a half-tested conditional as fully tested."""
    coverage = pyproject["tool"]["coverage"]
    assert coverage["run"]["branch"] is True
    threshold = coverage["report"]["fail_under"]
    assert threshold >= 90, f"a floor of {threshold} is too low to catch a real regression"


def test_coverage_measures_the_tooling_as_well_as_the_package(pyproject: dict[str, Any]) -> None:
    """The quality runner decides whether a gate ran. Untested, it could lie."""
    sources = pyproject["tool"]["coverage"]["run"]["source"]
    assert "globin" in sources
    assert "tools" in sources


def test_coverage_exclusions_add_to_the_defaults(pyproject: dict[str, Any]) -> None:
    """`exclude_lines` would REPLACE coverage's defaults, dropping `pragma: no cover`."""
    report = pyproject["tool"]["coverage"]["report"]
    assert "exclude_also" in report
    assert "exclude_lines" not in report, "exclude_lines silently discards the built-in defaults"


# --------------------------------------------------------------------------
# Continuous integration: least privilege, pinned, and unable to pass quietly
# --------------------------------------------------------------------------


def test_the_workflow_declares_least_privilege(workflow: str) -> None:
    assert re.search(r"^permissions:", workflow, re.MULTILINE), (
        "no `permissions:` block; the workflow would inherit the repository default"
    )
    assert re.search(r"^\s*contents:\s*read\s*$", workflow, re.MULTILINE), (
        "the token should be able to read the repository and nothing else"
    )
    for scope in ("write-all", "contents: write", "packages: write"):
        assert scope not in workflow, f"the quality workflow must not request `{scope}`"
    # `id-token: write` is no longer forbidden outright — Phase 014's `attest`
    # job needs it to sign a provenance statement. What replaced the ban is a
    # narrower rule in `test_ci_security_contract.py`: the scope may appear only
    # in a job guarded by a condition restricting it to a push to master, so it
    # is unreachable from a fork's pull request.


def test_every_action_is_pinned_to_a_full_commit_sha(workflow: str) -> None:
    """A tag is mutable. Pinning to one lets its owner change what runs here."""
    references = ACTION_USE_RE.findall(workflow)
    assert references, "no `uses:` entries found; this check would be vacuous"
    unpinned = [ref for ref in references if not SHA_PINNED_RE.match(ref)]
    assert not unpinned, f"actions not pinned to a 40-character commit SHA: {unpinned}"


def test_no_step_is_permitted_to_fail_quietly(workflow: str) -> None:
    """A gate that cannot fail the build is decoration."""
    assert "continue-on-error: true" not in workflow
    assert "|| true" not in workflow
    assert "exit 0" not in workflow


def test_the_workflow_uses_no_secret_and_reaches_no_exchange(workflow: str) -> None:
    """Quality checks need no credential, and GLOBIN has none to give them."""
    assert "secrets." not in workflow, "the quality pipeline must not consume repository secrets"
    for forbidden in ("binance", "api_key", "apikey", "api-key", "testnet"):
        assert forbidden not in workflow.lower(), f"unexpected reference to {forbidden!r}"


def test_the_workflow_runs_the_canonical_gate(workflow: str) -> None:
    """CI must not keep its own idea of what the checks are."""
    assert "python -m tools.quality full" in workflow


def test_the_workflow_never_writes_back_to_the_repository(workflow: str) -> None:
    """CI verifies. A pipeline that commits its own fixes proves nothing about the commit."""
    for forbidden in ("git push", "git commit", "ruff format .", "--fix"):
        assert forbidden not in workflow, f"CI would modify the repository: {forbidden!r}"


# --------------------------------------------------------------------------
# pre-commit
# --------------------------------------------------------------------------


def test_every_hook_repository_is_pinned(precommit: str) -> None:
    """A branch name as a revision means the hook set can change under you."""
    revisions = re.findall(r"^\s*rev:\s*(?P<rev>\S+)", precommit, re.MULTILINE)
    assert revisions, "no hook revisions found; this check would be vacuous"
    floating = [rev for rev in revisions if rev in {"main", "master", "HEAD", "latest"}]
    assert not floating, f"hook repositories pinned to a moving reference: {floating}"


def test_the_hook_ruff_and_the_ci_ruff_are_the_same_version(precommit: str, workflow: str) -> None:
    """Two Ruffs is two verdicts.

    If the hook lints with one version and the gate with another, a file can
    pass locally and fail in CI with no change in between — the exact confusion
    a single quality entrypoint exists to remove.
    """
    hook = re.search(r"ruff-pre-commit\s*\n\s*rev:\s*v?(?P<version>[\d.]+)", precommit)
    assert hook is not None, "could not find the ruff-pre-commit revision"
    ci = re.search(r'"ruff==(?P<version>[\d.]+)"', workflow)
    assert ci is not None, "could not find the ruff version pinned in CI"
    assert hook.group("version") == ci.group("version"), (
        f"pre-commit uses ruff {hook.group('version')} but CI uses {ci.group('version')}"
    )


def test_the_lint_hook_does_not_rewrite_code(precommit: str) -> None:
    """A verification hook that edits makes the reviewed code differ from the committed code."""
    assert "--unsafe-fixes" not in precommit
    assert re.search(r"id:\s*ruff-check\s*\n(?:\s*#.*\n)*\s*args:.*--fix", precommit) is None, (
        "the ruff-check hook must not apply fixes"
    )


# --------------------------------------------------------------------------
# The documents that restate the machinery
#
# `QUALITY_GATES.md` and `TESTING_STRATEGY.md` each carry a table restating
# something the code already knows. Both were hand-maintained and unchecked
# until Phase 007, and both had already drifted: the strategy table was missing
# two property modules. A table that lists most of the truth is worse than no
# table, because a reader treats an absent row as evidence rather than as an
# omission.
# --------------------------------------------------------------------------


def test_the_quality_gates_document_lists_every_command(repo_root: Path) -> None:
    """The command table is defined once, in `tools/quality/commands.py`.

    `QUALITY_GATES.md` restates it for a reader who wants to know what to run
    without reading Python. Order is compared too: the document presents the
    commands as a progression from the inner edit loop outwards, and a new
    command appended to the wrong end of one list and not the other would be a
    silent disagreement about what that progression is.
    """
    document = (repo_root / "docs" / "engineering" / "QUALITY_GATES.md").read_text(encoding="utf-8")
    documented = tuple(match.group("name") for match in BACKTICKED_FIRST_CELL_RE.finditer(document))
    assert documented, "no command rows parsed from QUALITY_GATES.md"
    assert documented == command_names()


def test_the_testing_strategy_describes_every_test_module(repo_root: Path) -> None:
    """Every test module says, in one sentence, what it would catch.

    That table is the only place the suite is legible as a whole rather than as
    546 individual assertions, and its value depends entirely on being complete.
    A module with no row is a module nobody has had to justify.
    """
    document = (repo_root / "docs" / "TESTING_STRATEGY.md").read_text(encoding="utf-8")
    documented = {match.group("module") for match in STRATEGY_MODULE_ROW_RE.finditer(document)}
    present = {path.name for path in (repo_root / "tests").rglob("test_*.py")}

    assert not present - documented, (
        f"test modules with no row in TESTING_STRATEGY.md: {sorted(present - documented)}"
    )
    assert not documented - present, (
        f"TESTING_STRATEGY.md describes modules that do not exist: {sorted(documented - present)}"
    )


def test_the_section_reader_finds_its_own_failing_case() -> None:
    """Guard the guard, for the reader the marker check below depends on."""
    document = "\n## One\n\n| `alpha` | x |\n\n## Two\n\n| `beta` | y |\n"
    section = markdown_section(document, "## One")
    assert [m.group("name") for m in BACKTICKED_FIRST_CELL_RE.finditer(section)] == ["alpha"]
    with pytest.raises(AssertionError):
        markdown_section(document, "## Absent")


def test_the_testing_strategy_documents_every_attribute_marker(repo_root: Path) -> None:
    """The four hand-applied markers are registered in one place and explained in another.

    Registration without an explanation teaches nobody when to apply a marker,
    and an explanation for a marker that is no longer registered is worse: a
    contributor who follows it gets a collection error, because `strict_markers`
    turns an unregistered marker into a failure rather than a typo.
    """
    document = (repo_root / "docs" / "TESTING_STRATEGY.md").read_text(encoding="utf-8")
    section = markdown_section(document, "### Markers")

    documented = tuple(match.group("name") for match in BACKTICKED_FIRST_CELL_RE.finditer(section))
    assert documented == ATTRIBUTE_MARKERS

    spelled = spelled_size(len(ATTRIBUTE_MARKERS)).capitalize()
    assert f"{spelled} **attribute** markers" in section, (
        f"TESTING_STRATEGY.md must say '{spelled} **attribute** markers'"
    )
