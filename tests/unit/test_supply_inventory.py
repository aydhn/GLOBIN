"""The dependency inventory, and the drift it exists to catch.

The inventory reads three registers that describe one toolchain from three
angles: lower bounds in ``pyproject.toml``, exact versions in the workflows, and
a pinned revision in ``.pre-commit-config.yaml``. Nothing compared them before
Phase 014. These tests are mostly about the comparison.
"""

from pathlib import Path

import pytest

from tools.quality.supply import inventory
from tools.quality.supply.inventory import Dependency, SupplyChainError

FULL_SHA = "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"


def _pinned(name: str, version: str, scope: str = inventory.CONTINUOUS_INTEGRATION) -> Dependency:
    """A pinned PyPI dependency, for building drift scenarios.

    Args:
        name: The distribution.
        version: The exact version.
        scope: What it is for.

    Returns:
        The dependency.
    """
    return Dependency(
        ecosystem=inventory.PYPI,
        name=name,
        version=version,
        scope=scope,
        resolution=inventory.PINNED,
        source=".github/workflows/quality.yml",
    )


def _declared(name: str, specifier: str) -> Dependency:
    """A ranged dependency as ``pyproject.toml`` declares one.

    Args:
        name: The distribution.
        specifier: The bound, such as ``>=8.0``.

    Returns:
        The dependency.
    """
    return Dependency(
        ecosystem=inventory.PYPI,
        name=name,
        version=specifier,
        scope=inventory.DEVELOPMENT,
        resolution=inventory.RANGED,
        source=inventory.PYPROJECT,
    )


def _hook(repository: str, revision: str) -> Dependency:
    """A pre-commit hook repository at a pinned revision.

    Args:
        repository: The ``owner/name``.
        revision: The ``rev:`` value.

    Returns:
        The dependency.
    """
    return Dependency(
        ecosystem=inventory.PRE_COMMIT,
        name=repository,
        version=revision,
        scope=inventory.HOOK,
        resolution=inventory.PINNED,
        source=inventory.PRE_COMMIT_CONFIG,
    )


# ---------------------------------------------------------------------------
# The real tree
# ---------------------------------------------------------------------------


def test_the_repository_inventory_is_collected_and_ordered(repo_root: Path) -> None:
    """Sorting is total and comes from the dataclass, not from a caller's key."""
    found = inventory.collect(repo_root)
    assert found
    assert list(found) == sorted(found)
    assert {entry.ecosystem for entry in found} <= {
        inventory.PYPI,
        inventory.GITHUB_ACTIONS,
        inventory.PRE_COMMIT,
    }


def test_the_repository_has_no_runtime_dependency(repo_root: Path) -> None:
    """``dependencies = []`` is an invariant, and the inventory must show it as one."""
    found = inventory.collect(repo_root)
    assert not [entry for entry in found if entry.scope == inventory.RUNTIME]


def test_the_three_registers_agree_in_this_repository(repo_root: Path) -> None:
    """The gate's own subject: if this fails, the toolchain has drifted."""
    assert not inventory.drift(inventory.collect(repo_root))


def test_collection_is_reproducible(repo_root: Path) -> None:
    """Two reads of one tree produce identical bytes, which the SBOM depends on."""
    assert inventory.render(inventory.collect(repo_root)) == inventory.render(
        inventory.collect(repo_root)
    )


def test_a_missing_manifest_is_refused_rather_than_read_as_empty(tmp_path: Path) -> None:
    """An empty inventory is indistinguishable from a repository with no dependencies.

    Returning one for an unreadable tree would report that tree as clean.
    """
    with pytest.raises(SupplyChainError, match=r"pyproject\.toml is missing"):
        inventory.from_pyproject(tmp_path)


def test_malformed_toml_is_refused(tmp_path: Path) -> None:
    """Same reasoning, one layer down."""
    (tmp_path / "pyproject.toml").write_text("[project\n", encoding="utf-8")
    with pytest.raises(SupplyChainError, match="not valid TOML"):
        inventory.from_pyproject(tmp_path)


# ---------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------


def test_a_tool_ci_installs_but_pyproject_does_not_declare_is_reported() -> None:
    """CI would then measure with something a developer's install does not contain."""
    problems = inventory.drift((_pinned("bandit", "1.9.0"),))
    assert problems
    assert "does not declare" in problems[0]


def test_a_pin_that_violates_its_own_lower_bound_is_reported() -> None:
    """The two files would describe toolchains that cannot both be right."""
    problems = inventory.drift((_pinned("pytest", "7.0.0"), _declared("pytest", ">=8.0")))
    assert problems
    assert "does not satisfy" in problems[0]


def test_a_pin_that_satisfies_its_lower_bound_is_accepted() -> None:
    """The ordinary case, asserted so the check above is not vacuous."""
    assert not inventory.drift((_pinned("pytest", "9.0.3"), _declared("pytest", ">=8.0")))


def test_a_hook_revision_disagreeing_with_the_ci_pin_is_reported() -> None:
    """The drift that bites hardest, because both halves pass on their own.

    ``.pre-commit-config.yaml`` states in prose that the hook is pinned to the
    same version the gate runs "so the hook and the gate cannot disagree about
    whether a file is clean". Until this check existed nothing enforced it, and a
    developer would commit through a hook calling the file clean and watch CI
    call it dirty, with no diff between them to explain why.
    """
    problems = inventory.drift(
        (
            _pinned("ruff", "0.15.14"),
            _declared("ruff", ">=0.6"),
            _hook("astral-sh/ruff-pre-commit", "v0.14.0"),
        )
    )
    assert problems
    assert "would disagree about whether a file is clean" in problems[0]


def test_a_matching_hook_revision_is_accepted() -> None:
    """The ``v`` prefix is a pre-commit convention, not a version difference."""
    assert not inventory.drift(
        (
            _pinned("ruff", "0.15.14"),
            _declared("ruff", ">=0.6"),
            _hook("astral-sh/ruff-pre-commit", "v0.15.14"),
        )
    )


def test_a_hook_that_mirrors_no_installed_tool_is_left_alone() -> None:
    """``pre-commit-hooks`` wraps no PyPI distribution this repository installs."""
    assert not inventory.drift((_hook("pre-commit/pre-commit-hooks", "v6.0.0"),))


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        pytest.param(_pinned("ruff", "0.15.14"), "pkg:pypi/ruff@0.15.14", id="pypi"),
        pytest.param(
            Dependency(
                inventory.GITHUB_ACTIONS,
                "actions/checkout",
                FULL_SHA,
                inventory.CONTINUOUS_INTEGRATION,
                inventory.PINNED,
                ".github/workflows/quality.yml",
            ),
            f"pkg:github/actions/checkout@{FULL_SHA}",
            id="action",
        ),
        pytest.param(
            _hook("astral-sh/ruff-pre-commit", "v0.15.14"),
            "pkg:github/astral-sh/ruff-pre-commit@v0.15.14",
            id="hook is a github package, not a pypi one",
        ),
    ],
)
def test_a_package_url_names_the_right_ecosystem(entry: Dependency, expected: str) -> None:
    """A pre-commit hook lives on GitHub, so its identifier says so.

    It is nonetheless a distinct ecosystem from ``github-actions``, because
    Dependabot's ``github-actions`` updater does not touch a
    ``.pre-commit-config.yaml`` revision — reporting a hook as an action would
    promise coverage that does not exist.
    """
    assert entry.purl == expected
