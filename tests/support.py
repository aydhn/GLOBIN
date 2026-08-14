"""Importable helpers shared across the GLOBIN suite.

These live here rather than in ``conftest.py`` for one structural reason. A
``conftest.py`` is loaded by pytest, not imported by name, and the only reason
``from conftest import ...`` ever worked was that pytest happened to place
``tests/`` on ``sys.path``. That accident stops being true the moment tests are
organised into subdirectories, so the helpers a test *imports* are separated
here from the fixtures pytest *injects*, which are still in ``conftest.py`` and
are still inherited by every subdirectory automatically.

The parser is intentionally tiny. ``ROADMAP.md`` is written in a fixed,
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

#: The taxonomy levels, one directory each under ``tests/``. Mutually exclusive:
#: a test has exactly one, decided by where it lives rather than by what someone
#: remembered to type. The orthogonal attribute markers (``slow``, ``network``,
#: ``external``, ``windows``) are applied by hand and are not listed here.
TAXONOMY_LEVELS: Final[tuple[str, ...]] = (
    "unit",
    "contract",
    "architecture",
    "integration",
    "smoke",
)


def taxonomy_level(path: Path) -> str | None:
    """Return the taxonomy level a test file belongs to, or ``None``.

    ``None`` means the file sits somewhere the taxonomy does not describe —
    directly in ``tests/``, or in a directory that is not a level. That is
    reported as a failure by ``tests/contract/test_quality_contract.py`` rather
    than raised here, because a collection-time exception would obscure which
    file caused it.
    """
    try:
        relative = path.resolve().relative_to(REPO_ROOT / "tests")
    except ValueError:
        return None
    if len(relative.parts) < 2:
        return None
    head = relative.parts[0]
    return head if head in TAXONOMY_LEVELS else None


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


def git_committable_files() -> tuple[str, ...]:
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
        # S607: `git` is resolved from PATH on purpose. Hard-coding an absolute
        # path would break on every machine whose Git lives somewhere else, and
        # the argument list is a fixed literal, so there is nothing to inject.
        completed = subprocess.run(
            ("git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"),  # noqa: S607
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
