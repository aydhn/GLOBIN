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
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final, NamedTuple

import pytest

from globin.domain.architecture import LAYER_ORDER, ArchitectureContract, Layer, LayerPolicy
from globin.domain.configuration import ResolvedConfig, config_layer, default_layer, resolve

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
    "property",
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


def process_state_drift(
    *,
    environment_before: Mapping[str, str],
    environment_after: Mapping[str, str],
    directory_before: Path,
    directory_after: Path | None,
) -> tuple[str, ...]:
    """Describe every way process-global state changed, or return ``()``.

    Separated from the fixture that calls it so that it can be tested with its
    own failing case. A detector nobody has ever seen report anything is
    indistinguishable from one that cannot report at all, and this one runs in
    teardown where a silent failure would be especially easy to miss.

    Args:
        environment_before: Environment as the test found it.
        environment_after: Environment as the test left it.
        directory_before: Working directory as the test found it.
        directory_after: Working directory as the test left it, or ``None`` if
            it can no longer be read — which happens when a test deletes the
            directory it was standing in.

    Returns:
        One human-readable line per kind of drift, empty when nothing moved.
    """
    drift: list[str] = []

    if environment_after != environment_before:
        added = sorted(set(environment_after) - set(environment_before))
        removed = sorted(set(environment_before) - set(environment_after))
        altered = sorted(
            name
            for name in set(environment_after) & set(environment_before)
            if environment_after[name] != environment_before[name]
        )
        changed = [
            *(f"+{name}" for name in added),
            *(f"-{name}" for name in removed),
            *(f"~{name}" for name in altered),
        ]
        drift.append(f"environment variables: {', '.join(changed)}")

    if directory_after != directory_before:
        left_in = (
            "a directory that no longer exists" if directory_after is None else str(directory_after)
        )
        drift.append(f"working directory: {left_in} (expected {directory_before})")

    return tuple(drift)


def layer_policy(
    layer: Layer,
    *,
    may_import: Iterable[Layer] = (),
    may_perform_io: bool = False,
) -> LayerPolicy:
    """Build one layer's policy, with the package name derived from the layer.

    Defaults are the strictest available — imports nothing, performs no I/O — so
    a test that permits something has to say so, and a reader can tell what the
    test is actually about from the arguments it passes.
    """
    return LayerPolicy(
        layer=layer,
        package=f"globin.{layer.value}",
        responsibility=f"Synthetic {layer.value} policy for tests.",
        may_import=frozenset(may_import),
        may_perform_io=may_perform_io,
    )


def architecture_contract(
    *,
    policies: Iterable[LayerPolicy] | None = None,
    shared_modules: Iterable[str] = (),
    io_capable_modules: Iterable[str] = (),
) -> ArchitectureContract:
    """Build a contract governing all five layers, permitting nothing by default.

    This is a *synthetic* contract, not a copy of
    ``docs/architecture/dependency-rules.toml``. Restating the real matrix here
    would be the duplication ``docs/engineering/SOURCE_OF_TRUTH.md`` forbids, and
    a test asserting a rule against a copy of that rule asserts nothing. Tests
    that need the real contract load it from disk.
    """
    return ArchitectureContract(
        root_package="globin",
        policies=tuple(policies) if policies is not None else tuple(map(layer_policy, LAYER_ORDER)),
        shared_modules=frozenset(shared_modules),
        io_capable_modules=frozenset(io_capable_modules),
    )


def resolved_configuration(origin: str = "test", /, **settings: object) -> ResolvedConfig:
    """Resolve the declared defaults with one override layer on top.

    Args:
        origin: What the override layer calls itself. Worth setting when a test
            asserts that a refusal names the document at fault. Positional-only,
            so that a caller forwarding ``**settings`` cannot bind it by accident
            with a setting that happens to be called ``origin``.
        settings: Dotted keys and the values to override them with. Keys are not
            Python identifiers, so callers pass them as ``**{KEY: value}``.

    Returns:
        The resolved settings, ready for
        :func:`~globin.domain.configuration.as_config`.

    Defaults underneath is the arrangement every real resolution uses, so a test
    that assembled the sequence by hand would be testing a shape no caller
    produces — and would get an ``InternalError`` about a setting it never
    touched if it forgot them.
    """
    return resolve((default_layer(), config_layer(origin, settings)))


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
