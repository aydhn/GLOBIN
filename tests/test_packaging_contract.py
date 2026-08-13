"""Verify that `pyproject.toml` encodes the project's policies, not just metadata.

The zero-budget rule (ADR-0003) is easy to state and easy to erode: one
convenient paid client library added to `dependencies` and the runtime is no
longer free. Parsing the manifest and asserting the dependency list is empty
turns that policy into something CI can catch.
"""

import tomllib
from pathlib import Path
from typing import Any

import pytest

import globin


@pytest.fixture(scope="session")
def pyproject(repo_root: Path) -> dict[str, Any]:
    """Parsed `pyproject.toml` (stdlib `tomllib`; no third-party parser needed)."""
    with (repo_root / "pyproject.toml").open("rb") as handle:
        data: dict[str, Any] = tomllib.load(handle)
    return data


def test_distribution_name_matches_the_package(pyproject: dict[str, Any]) -> None:
    assert pyproject["project"]["name"] == globin.PACKAGE_NAME == "globin"


def test_there_are_no_runtime_dependencies(pyproject: dict[str, Any]) -> None:
    """Phase 1 runtime dependency count is zero, and that is an invariant.

    A later phase adding a runtime dependency must consciously update this
    test, at which point the zero-budget review (ADR-0003) is unavoidable.
    """
    assert pyproject["project"]["dependencies"] == []


def test_development_extra_is_a_free_toolchain(pyproject: dict[str, Any]) -> None:
    dev = pyproject["project"]["optional-dependencies"]["dev"]
    names = {entry.split(">")[0].split("=")[0].split("[")[0].strip() for entry in dev}
    assert names == {"pytest", "pytest-cov", "ruff", "mypy"}


def test_requires_python_floor_supports_the_planned_stack(pyproject: dict[str, Any]) -> None:
    """3.12 is the strictest known floor among libraries scheduled for later phases.

    See docs/research/phase_001_sources.md — XGBoost requires >=3.12 while
    PyTorch, Gymnasium and Stable-Baselines3 require >=3.10.
    """
    assert pyproject["project"]["requires-python"] == ">=3.12"


def test_version_is_dynamic_and_sourced_from_the_package(
    repo_root: Path, pyproject: dict[str, Any]
) -> None:
    assert pyproject["project"]["dynamic"] == ["version"]
    version_path = pyproject["tool"]["hatch"]["version"]["path"]
    assert version_path == "src/globin/__init__.py"
    assert (repo_root / version_path).is_file()
    assert f'__version__ = "{globin.__version__}"' in (repo_root / version_path).read_text(
        encoding="utf-8"
    )


def test_no_licence_is_asserted(pyproject: dict[str, Any]) -> None:
    """Licensing is deliberately undecided and must not be invented.

    The owner has not selected a licence. Declaring one here would be a legal
    assertion the project is not entitled to make, so its absence is checked.
    """
    project = pyproject["project"]
    assert "license" not in project
    assert "license-files" not in project


def test_src_layout_is_configured(repo_root: Path, pyproject: dict[str, Any]) -> None:
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/globin"]
    assert pyproject["tool"]["pytest"]["ini_options"]["pythonpath"] == ["src"]
    assert (repo_root / "src" / "globin" / "__init__.py").is_file()


def test_strict_typing_and_linting_are_enabled(pyproject: dict[str, Any]) -> None:
    assert pyproject["tool"]["mypy"]["strict"] is True
    assert pyproject["tool"]["ruff"]["line-length"] == 100
