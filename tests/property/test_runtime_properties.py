"""Invariants of the runtime judgements, over generated input.

Two of these are the reason this file exists rather than more examples.

**A recorded path never carries an absolute path.** The example tests check the
cases somebody thought of. The property checks the shape of the answer for any
input at all, which is the right strength for a rule whose failure mode is
publishing an account holder's name in a public CI artifact.

**A directory outside the repository is never a deletion target.** The same
argument, for a rule whose failure mode is a recursive delete.
"""

import string
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from tools.quality.runtime import plan
from tools.quality.runtime.plan import Version

SEGMENT_ALPHABET = string.ascii_letters + string.digits + "-_. "

segments = st.text(alphabet=SEGMENT_ALPHABET, min_size=1, max_size=12).filter(
    lambda text: text.strip(" .") != "" and text == text.strip()
)
"""One path component. Windows refuses a trailing space or dot, and a component
that is only dots is a traversal rather than a name."""

relative_paths = st.lists(segments, min_size=1, max_size=4)

versions = st.builds(
    Version,
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=0, max_value=999),
)

ROOT = Path("C:/repo")

FORBIDDEN_FRAGMENTS = ("C:", "c:", "Users", "AppData", "/home/", "Program Files")


# ---------------------------------------------------------------------------
# Recording a path never publishes one
# ---------------------------------------------------------------------------


@given(relative_paths)
def test_a_path_inside_the_repository_is_recorded_relative_and_rejoins(
    parts: list[str],
) -> None:
    recorded = plan.recorded_path(ROOT.joinpath(*parts), root=ROOT)

    assert recorded["location"] == "repository"
    assert ROOT / recorded["path"] == ROOT.joinpath(*parts)
    assert "\\" not in recorded["path"], "recorded as POSIX, so two machines agree"


@given(relative_paths)
def test_a_path_outside_the_repository_never_appears_in_what_is_recorded(
    parts: list[str],
) -> None:
    """The privacy invariant. Whatever the path is, the record does not contain it."""
    outside = Path("C:/Users/Someone").joinpath(*parts)

    recorded = plan.recorded_path(outside, root=ROOT)

    assert recorded["location"] == "outside"
    assert "path" not in recorded
    rendered = str(recorded)
    assert str(outside) not in rendered
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in rendered


@given(st.one_of(st.none(), relative_paths))
def test_a_recorded_path_never_contains_a_drive_letter_or_a_home_directory(
    parts: list[str] | None,
) -> None:
    """Stated over both branches at once.

    That is because the rule is about the *output* rather than about which branch produced it.
    """
    path = None if parts is None else Path("C:/Users/Someone").joinpath(*parts)

    rendered = str(plan.recorded_path(path, root=ROOT))

    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in rendered


# ---------------------------------------------------------------------------
# Deletion refuses everything it has not been told to accept
# ---------------------------------------------------------------------------


@given(relative_paths)
def test_a_directory_outside_the_repository_is_never_a_deletion_target(
    parts: list[str],
) -> None:
    """No generated path outside the root is ever safe to remove."""
    target = Path("C:/elsewhere").joinpath(*parts)

    problems = plan.deletion_problems(
        target=target, root=ROOT, directory=".venv", is_reparse_point=False
    )

    assert problems


@given(relative_paths)
def test_only_the_declared_directory_is_ever_a_deletion_target(parts: list[str]) -> None:
    """Being inside the repository is not sufficient — `src` is inside it too."""
    target = ROOT.joinpath(*parts)

    problems = plan.deletion_problems(
        target=target, root=ROOT, directory=".venv", is_reparse_point=False
    )

    assert (problems == ()) == (target == ROOT / ".venv")


@given(relative_paths)
def test_a_reparse_point_is_never_a_deletion_target(parts: list[str]) -> None:
    """Deleting through a link can remove what it points at, and it may point anywhere at all."""
    problems = plan.deletion_problems(
        target=ROOT.joinpath(*parts), root=ROOT, directory=".venv", is_reparse_point=True
    )

    assert problems


@given(segments)
def test_a_name_with_a_separator_is_never_a_plain_directory_name(name: str) -> None:
    assert plan.is_plain_directory_name(name)
    assert not plan.is_plain_directory_name(f"{name}/child")
    assert not plan.is_plain_directory_name(f"{name}\\child")


# ---------------------------------------------------------------------------
# Versions order, and survive a round trip
# ---------------------------------------------------------------------------


@given(versions)
def test_a_version_survives_being_written_down_and_read_back(version: Version) -> None:
    assert plan.parse_version(version.text) == version


@given(versions, versions)
def test_version_ordering_is_antisymmetric(first: Version, second: Version) -> None:
    """No two versions can each be older than the other.

    A floor comparison that could report both would accept and refuse the same
    interpreter depending on which side of the ``<`` it was written.
    """
    assert not (first < second and second < first)
    assert (first < second) or (second < first) or (first == second)


@given(versions, versions, versions)
def test_version_ordering_is_transitive(first: Version, second: Version, third: Version) -> None:
    if first < second and second < third:
        assert first < third


@given(versions)
def test_a_version_is_never_below_itself_so_the_floor_accepts_the_baseline(
    version: Version,
) -> None:
    """The contract's ``minimum_patch`` must be an accepted value, not the first refused one."""
    assert not version < version


@given(versions)
def test_the_minor_line_is_the_first_two_components(version: Version) -> None:
    assert plan.parse_minor_line(version.line) == (version.major, version.minor)
