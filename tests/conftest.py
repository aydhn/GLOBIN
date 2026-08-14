"""Session fixtures for the GLOBIN suite.

This file holds **only** fixtures. The helpers a test imports by name live in
``tests/support.py``; see that module for why the two are separated.

Scope discipline matters here more than it looks. A ``conftest.py`` at the root
of ``tests/`` applies to every test in every subdirectory, so anything added
here is paid for by the whole suite. Fixtures belong at the narrowest scope that
serves them: a fixture used by one module is declared in that module, a fixture
used across one taxonomy level belongs in that level's ``conftest.py``, and only
genuinely repository-wide facts belong here.

Every fixture below is ``scope="session"`` because each reads immutable
repository state. Re-reading ``ROADMAP.md`` once per test would be slower and
could not produce a different answer.
"""

from pathlib import Path

import pytest

from tests.support import (
    REPO_ROOT,
    RoadmapRow,
    git_committable_files,
    parse_roadmap,
    taxonomy_level,
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply each test's taxonomy marker from the directory it lives in.

    Deriving the marker rather than writing it means ``pytest -m unit`` cannot
    disagree with the directory layout, and a moved file cannot keep a stale
    label. The alternative — a decorator on every test — is 187 opportunities to
    forget, and nothing would notice a mistake.

    A file the taxonomy does not describe is left unmarked on purpose. The
    contract suite fails on it by name, which is a better diagnosis than an
    exception thrown during collection.
    """
    for item in items:
        level = taxonomy_level(item.path)
        if level is not None:
            item.add_marker(level)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the repository root."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def roadmap_text() -> str:
    """Raw text of ``ROADMAP.md``."""
    return (REPO_ROOT / "ROADMAP.md").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def roadmap_rows(roadmap_text: str) -> list[RoadmapRow]:
    """Every phase row parsed from ``ROADMAP.md``."""
    return parse_roadmap(roadmap_text)


@pytest.fixture(scope="session")
def committable_files() -> tuple[str, ...]:
    """Repository-relative, POSIX-separated paths Git would commit from this tree."""
    return git_committable_files()


@pytest.fixture(scope="session")
def committable_markdown(committable_files: tuple[str, ...]) -> tuple[str, ...]:
    """Repository-relative paths of every committable Markdown document."""
    return tuple(path for path in committable_files if path.endswith(".md"))
