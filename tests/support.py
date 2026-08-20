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
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NamedTuple

import pytest

from globin.domain.architecture import LAYER_ORDER, ArchitectureContract, Layer, LayerPolicy
from globin.domain.clock import Duration, Instant, MonotonicReading, instant_from_epoch_millis
from globin.domain.configuration import ResolvedConfig, config_layer, default_layer, resolve

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

ENVIRONMENT_DIRECTORY: Final[str] = ".venv"
"""The project's own virtual environment, as `runtime-contract.toml` declares it.

Spelled here as well as there for the reason `verify.ps1` spells it twice: this
module may not read TOML at import, and the duplication is a tripwire rather than
a second source — `tests/contract/test_runtime_contract.py` compares them.
"""


def running_from_the_project_environment() -> bool:
    """Whether this interpreter is the one `scripts/bootstrap.ps1` built.

    Returns:
        ``True`` when :data:`sys.prefix` is the project's own ``.venv``.

    A handful of assertions are about *this development host* rather than about
    GLOBIN — that the project is installed, that the console entry point exists,
    that the repository bootstraps end to end. None of them can hold in the
    continuous-integration `quality` job, which installs the toolchain with plain
    `pip` and never builds an environment; the `runtime` job is the one that does,
    and it exercises the command line directly.

    Guarding on the real condition rather than on a CI variable is deliberate: a
    developer who has not run the bootstrap gets the same skip and the same
    reason, which is a true statement about their machine rather than a guess
    about where the code is running.
    """
    return Path(sys.prefix).resolve() == (REPO_ROOT / ENVIRONMENT_DIRECTORY).resolve()


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


def markdown_section(text: str, heading: str) -> str:
    """Return the body under ``heading``, stopping at the next heading of any level.

    Args:
        text: The Markdown source.
        heading: The exact heading line, including its leading hashes.

    Returns:
        Everything between that heading and the next one.

    Raises:
        AssertionError: If the heading does not appear exactly once. Several
            documents carry more than one table, and a reader that silently
            returned nothing would make its caller compare two empty sets and
            pass — which is the failure mode the checks built on this exist to
            avoid in the documents themselves.
    """
    occurrences = text.count(f"\n{heading}\n")
    assert occurrences == 1, f"expected one {heading!r} heading, found {occurrences}"
    body = text.split(f"\n{heading}\n", 1)[1]
    return re.split(r"^#{1,6} ", body, maxsplit=1, flags=re.MULTILINE)[0]


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


#: How a small count is written out in prose. Bounded deliberately: a list long
#: enough to fall off this map is one worth arguing about rather than spelling.
SPELLED_SIZES: Final[dict[int, str]] = {
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
}


def spelled_size(count: int) -> str:
    """Return how ``count`` is written out in this repository's prose.

    Args:
        count: How many things there are.

    Returns:
        The English word for it.

    Raises:
        AssertionError: If no spelling is recorded. A test asking for one is
            asserting that a document's count is right, so a missing spelling
            must fail rather than quietly skip the comparison.

    Documents say "all six are free and open source" and "four attribute
    markers", and both had drifted at least once before anything compared them.
    Spelling the number is the half a reader believes without counting.
    """
    spelled = SPELLED_SIZES.get(count)
    assert spelled is not None, f"no spelling recorded for {count}; extend SPELLED_SIZES"
    return spelled


#: How this repository writes a *position* out, as against a quantity.
#:
#: Separate from :data:`SPELLED_SIZES` because prose uses both about the same
#: subject and they are not interchangeable: there are *seven* absent-safe
#: factories, and the discipline test fires when an *eighth* appears. A test that
#: reached for the cardinal where the document correctly used the ordinal is what
#: prompted this table.
SPELLED_ORDINALS: dict[int, str] = {
    1: "first",
    2: "second",
    3: "third",
    4: "fourth",
    5: "fifth",
    6: "sixth",
    7: "seventh",
    8: "eighth",
    9: "ninth",
    10: "tenth",
}


def spelled_ordinal(position: int) -> str:
    """Return how ``position`` is written out in this repository's prose.

    Args:
        position: Which one in the sequence.

    Returns:
        The English ordinal for it.

    Raises:
        AssertionError: If no spelling is recorded, for the same reason
            :func:`spelled_size` raises -- a comparison that quietly stops
            comparing is worse than one that fails.
    """
    spelled = SPELLED_ORDINALS.get(position)
    assert spelled is not None, f"no ordinal recorded for {position}; extend SPELLED_ORDINALS"
    return spelled


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


@dataclass(frozen=True, slots=True)
class FixedClock:
    """A :class:`~globin.ports.clock.Clock` that always answers with one moment.

    Args:
        fixed: The moment every call returns.

    The default double for anything that needs a timestamp but does not care
    which. Because it is frozen, a test can also assert on the sink holding it.
    """

    fixed: Instant

    def now(self) -> Instant:
        """The moment this clock was built with."""
        return self.fixed


@dataclass(slots=True)
class ManualClock:
    """A :class:`~globin.ports.clock.Clock` a test advances by hand.

    Args:
        current: The moment the next call returns.
        step: How far the clock moves after each call.

    Mutable on purpose, and the one double in the suite that is. It exists to
    prove a specific invariant that :class:`FixedClock` cannot:
    :class:`~globin.adapters.observability.StreamLogSink` reads its clock once
    *per record* rather than caching a reading when it was built. Against a
    fixed clock those two implementations are indistinguishable.
    """

    current: Instant
    step: Duration

    def now(self) -> Instant:
        """The current moment, then advance by :attr:`step`."""
        answer = self.current
        self.current = instant_from_epoch_millis(
            answer.epoch_millis + self.step.milliseconds,
        )
        return answer


@dataclass(slots=True)
class ManualMonotonicClock:
    """A :class:`~globin.ports.clock.MonotonicClock` a test advances by hand.

    Args:
        current: The reading the next call returns.
        step: How far the reading advances after each call.

    A real monotonic clock cannot be asked for a specific elapsed interval, and
    on Windows two consecutive readings can be identical. A test that needs a
    known duration uses this instead of measuring one.
    """

    current: MonotonicReading
    step: Duration

    def reading(self) -> MonotonicReading:
        """The current reading, then advance by :attr:`step`."""
        answer = self.current
        self.current = MonotonicReading(answer.nanoseconds + self.step.nanoseconds)
        return answer


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
