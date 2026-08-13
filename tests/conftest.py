"""Shared fixtures and the ROADMAP parser for the GLOBIN contract suite.

The parser here is intentionally tiny. ``ROADMAP.md`` is written in a fixed,
machine-checkable table shape precisely so that verifying it needs a regex and
nothing more — see ``docs/TESTING_STRATEGY.md`` on why the suite tests
*invariants* rather than snapshotting Markdown.
"""

import re
import subprocess
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


#: A fenced code block, including its fences.
MARKDOWN_FENCE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<fence>```+|~~~+).*?(?:^(?P=fence)\s*$|\Z)", re.MULTILINE | re.DOTALL
)

#: An inline code span, not crossing a line break.
MARKDOWN_INLINE_CODE_RE: Final[re.Pattern[str]] = re.compile(r"`[^`\n]*`")


def markdown_prose(text: str) -> str:
    """Return ``text`` with fenced blocks and inline code spans removed.

    What survives is what the document *asserts*; what is stripped is what it
    *quotes* — an example command, a tree diagram, or the literal name of a
    thing under discussion.

    Without this distinction a document that forbids ``TODO`` markers fails the
    check that looks for them, which is the same trap as a ``*secret*`` glob
    matching a document about secret handling.
    """
    return MARKDOWN_INLINE_CODE_RE.sub("", MARKDOWN_FENCE_RE.sub("", text))


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


def _git_committable_files() -> tuple[str, ...]:
    """Return every path Git would include in a commit of the whole tree.

    That is: tracked files, plus untracked files that ``.gitignore`` does not
    exclude. Deliberately *not* ``git ls-files`` alone, which lists only what is
    already staged or committed.

    The distinction is load-bearing. ``DEFINITION_OF_DONE.md`` requires the
    verification gate to run **before** staging, so a check restricted to
    already-tracked files would be blind to exactly the files the current phase
    just wrote — a new document would first be link-checked one commit after it
    could still be fixed cheaply.

    Ignored files stay excluded, so a developer's local ``.env`` or
    ``.pytest_cache/`` never fails the suite.

    ``-z`` avoids Git's quoting of unusual filenames, so paths are taken
    verbatim.

    Failure is reported, never skipped: a skipped check reads as a passing one,
    and GLOBIN's contract is that a check either ran or is reported as not run
    (``AGENTS.md``).
    """
    try:
        completed = subprocess.run(
            ("git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"),
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
    except OSError as exc:  # git absent or not executable
        pytest.fail(f"cannot run `git ls-files`: {exc}")

    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        pytest.fail(f"`git ls-files` failed in {REPO_ROOT}: {detail or '(no stderr)'}")

    entries = completed.stdout.decode("utf-8").split("\0")
    return tuple(sorted({entry for entry in entries if entry}))


@pytest.fixture(scope="session")
def committable_files() -> tuple[str, ...]:
    """Repository-relative, POSIX-separated paths Git would commit from this tree."""
    return _git_committable_files()


@pytest.fixture(scope="session")
def committable_markdown(committable_files: tuple[str, ...]) -> tuple[str, ...]:
    """Repository-relative paths of every committable Markdown document."""
    return tuple(path for path in committable_files if path.endswith(".md"))
