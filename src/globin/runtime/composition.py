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

import sys
from pathlib import Path
from typing import Final, TextIO

from globin.adapters.architecture import AstModuleImportSource, TomlArchitectureContractSource
from globin.adapters.observability import StreamLogSink, new_correlation_id
from globin.application.architecture_review import ArchitectureReview
from globin.application.observability import Logger

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


def build_logger(stream: TextIO | None = None, correlation_id: str | None = None) -> Logger:
    """Wire a logger writing JSON Lines to a stream.

    Args:
        stream: Where records go. Defaults to :data:`sys.stderr`, so that log
            output does not contaminate whatever a program writes to standard
            output.
        correlation_id: Ties every record this logger produces to one unit of
            work. Defaults to a fresh one. A test passes its own, and so does a
            caller continuing work that already has an id.

    Returns:
        A :class:`~globin.application.observability.Logger`.

    Both arguments default to ``None`` rather than to the value they resolve to.
    ``sys.stderr`` as a default argument would be captured when this module is
    imported, which is both work at import time and the wrong stream if anything
    later replaces it — and reading it here keeps this function the only place
    that knows which stream GLOBIN logs to.
    """
    return Logger(
        sink=StreamLogSink(sys.stderr if stream is None else stream),
        correlation_id=new_correlation_id() if correlation_id is None else correlation_id,
    )
