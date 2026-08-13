"""Shared fixtures and the ROADMAP parser for the GLOBIN contract suite.

The parser here is intentionally tiny. ``ROADMAP.md`` is written in a fixed,
machine-checkable table shape precisely so that verifying it needs a regex and
nothing more — see ``docs/TESTING_STRATEGY.md`` on why the suite tests
*invariants* rather than snapshotting Markdown.
"""

import re
from pathlib import Path
from typing import Final, NamedTuple

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: Matches one phase row of a ROADMAP.md band table:
#: ``| 001 | Title | Purpose | Status |``
#: Phase numbers are zero-padded to three digits so the pattern is unambiguous
#: and cannot accidentally match an unrelated table elsewhere in the document.
ROADMAP_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\|\s*(?P<phase>\d{3})\s*"
    r"\|(?P<title>[^|]*)"
    r"\|(?P<purpose>[^|]*)"
    r"\|(?P<status>[^|]*)\|\s*$"
)


class RoadmapRow(NamedTuple):
    """One parsed phase row from ``ROADMAP.md``."""

    phase: int
    title: str
    purpose: str
    status: str


def parse_roadmap(text: str) -> list[RoadmapRow]:
    """Extract every phase row from ``ROADMAP.md`` text, in document order."""
    rows: list[RoadmapRow] = []
    for line in text.splitlines():
        match = ROADMAP_ROW_RE.match(line)
        if match is None:
            continue
        rows.append(
            RoadmapRow(
                phase=int(match.group("phase")),
                title=match.group("title").strip(),
                purpose=match.group("purpose").strip(),
                status=match.group("status").strip(),
            )
        )
    return rows


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
