"""Composition root for the architecture review.

The single worked example of GLOBIN's wiring convention: a plain function that
takes what it cannot know — here, where the repository is — and returns a fully
constructed use case. Nothing is cached, nothing is global, and nothing runs
until the function is called.

The ``repo_root`` argument is not decoration. This service reviews *this*
repository's source tree, so it needs a location, and guessing one by walking
up from ``__file__`` would make the result depend on where the package happens
to be installed. Passing it in keeps the dependency visible and lets a test
point the review at a fixture tree instead.
"""

from pathlib import Path
from typing import Final

from globin.adapters.architecture import AstModuleImportSource, TomlArchitectureContractSource
from globin.application.architecture_review import ArchitectureReview

CONTRACT_RELATIVE_PATH: Final[str] = "docs/architecture/dependency-rules.toml"
"""Where the declared contract lives, relative to the repository root."""

PACKAGE_RELATIVE_PATH: Final[str] = "src/globin"
"""Where the package source lives, relative to the repository root."""

ROOT_PACKAGE: Final[str] = "globin"
"""The import namespace the review is scoped to."""


def build_architecture_review(repo_root: Path) -> ArchitectureReview:
    """Wire the architecture review against a repository checkout.

    Args:
        repo_root: Absolute path to the repository root — the directory holding
            ``pyproject.toml``.

    Returns:
        An :class:`~globin.application.architecture_review.ArchitectureReview`
        reading the declared contract and this repository's own source tree.

    No file is opened here. Both adapters record their paths and read them when
    the review runs, so constructing the graph stays free of I/O even though
    the objects it contains will perform some.
    """
    return ArchitectureReview(
        contract_source=TomlArchitectureContractSource(repo_root / CONTRACT_RELATIVE_PATH),
        module_source=AstModuleImportSource(repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE),
    )
