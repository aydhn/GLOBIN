"""Where configuration documents sit, and what shape a profile name has.

What the four profiles actually *are* is not asserted here — that is the
composition root's data and `test_configuration_layout_contract.py`'s comparison
against `ROADMAP.md`. This module owns the kind: the layout's segments, the
spellings it computes, and the refusals that keep a caller-supplied name from
becoming a path.
"""

import pytest

from globin.domain.config_layout import (
    DOCUMENT_SUFFIX,
    MAXIMUM_PROFILE_LENGTH,
    MINIMUM_PROFILE_LENGTH,
    PATH_SEPARATOR,
    PROFILE_ALPHABET,
    ConfigLayout,
    ConfigRole,
    profile_problems,
    resolve_profile,
    roles,
)
from globin.errors import ConfigurationError, ValidationError

DECLARED: tuple[str, ...] = ("paper", "demo", "testnet", "live")
"""A stand-in for what the composition root declares.

Written out rather than imported from `globin.runtime.composition`, so that a unit
test of the domain does not reach into the runtime layer to find its fixture.
"""


# ---------------------------------------------------------------------------
# The layout: segments in, spellings out
# ---------------------------------------------------------------------------


def test_the_declared_layout_computes_the_four_documents() -> None:
    """The whole point of the type: a profile plus a role is one spelling."""
    layout = ConfigLayout()
    assert layout.documents_for("live") == {
        ConfigRole.BASE: "config/globin.toml",
        ConfigRole.PROFILE: "config/profiles/live.toml",
        ConfigRole.LOCAL_BASE: "config/local/globin.toml",
        ConfigRole.LOCAL_PROFILE: "config/local/profiles/live.toml",
    }


def test_documents_are_returned_as_a_mapping_rather_than_a_sequence() -> None:
    """A tuple has an order, and a reader would read that order as precedence.

    Which documents are consulted and in what order is Phase 027's question. The
    return type is where that boundary is held, so this asserts the type rather
    than merely the contents.
    """
    assert isinstance(ConfigLayout().documents_for("paper"), dict)


def test_every_spelling_is_posix_and_relative() -> None:
    """These strings are compared, published and read by people.

    A backslash would make one document spell two ways depending on the host that
    wrote it down, which is the defect `RecordedPath` exists to avoid.
    """
    for spelling in ConfigLayout().documents_for("demo").values():
        assert "\\" not in spelling
        assert not spelling.startswith(PATH_SEPARATOR)
        assert spelling.endswith(DOCUMENT_SUFFIX)


def test_the_base_document_ignores_the_profile() -> None:
    """It applies whatever profile is selected, so it cannot depend on one."""
    layout = ConfigLayout()
    paper = layout.document_for(ConfigRole.BASE, "paper")
    live = layout.document_for(ConfigRole.BASE, "live")
    assert paper == live


def test_the_local_prefix_is_the_directory_gitignore_names() -> None:
    """One spelling, so `.gitignore` and its contract test cannot disagree."""
    assert ConfigLayout().local_prefix() == "config/local"


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"directory": ".."}, id="traversal"),
        pytest.param({"directory": "a/b"}, id="separator"),
        pytest.param({"local_directory": "C:"}, id="drive-letter"),
        pytest.param({"profiles_directory": ""}, id="empty"),
        pytest.param({"base_name": "globin"}, id="no-suffix"),
    ],
)
def test_a_layout_that_could_leave_its_directory_cannot_be_built(
    overrides: dict[str, str],
) -> None:
    """Refused at construction, so no caller ever holds a layout it must check."""
    with pytest.raises(ValidationError):
        ConfigLayout(**overrides)


def test_every_role_has_a_spelling() -> None:
    """Guard the dispatch: a member added to the enum must be routed.

    `document_for` raises rather than returning a default for an unrouted role,
    and this is what would notice.
    """
    layout = ConfigLayout()
    for role in roles():
        assert layout.document_for(role, "paper")


def test_the_role_listing_matches_the_enum() -> None:
    """`roles()` is a function because a layer performs no call at import.

    That makes it a second place the member list is written, so it is compared
    against the first.
    """
    assert set(roles()) == set(ConfigRole)
    assert len(roles()) == len(ConfigRole)


# ---------------------------------------------------------------------------
# The profile name: a kind, not a register
# ---------------------------------------------------------------------------


def test_a_canonical_profile_name_has_no_problems() -> None:
    """The positive case, so the refusals below are not vacuously satisfied."""
    for name in DECLARED:
        assert profile_problems(name) == ()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        pytest.param("", "empty", id="empty"),
        pytest.param("ab", "shorter than", id="too-short"),
        pytest.param("a" * (MAXIMUM_PROFILE_LENGTH + 1), "longer than", id="too-long"),
        pytest.param("Paper", "outside the profile alphabet", id="uppercase"),
        pytest.param("pa per", "outside the profile alphabet", id="space"),
        pytest.param("live/../x", "outside the profile alphabet", id="traversal"),
        pytest.param("live.toml", "outside the profile alphabet", id="suffix-included"),
        pytest.param("paper-1", "outside the profile alphabet", id="digit-and-dash"),
    ],
)
def test_a_non_canonical_profile_name_is_reported(name: str, expected: str) -> None:
    """Each row is a real way a name reaches a filename and should not.

    Uppercase is not pedantry: a profile name becomes a filename, and Windows
    compares filenames case-insensitively, so `Paper` and `paper` would name one
    document while comparing unequal everywhere else.
    """
    problems = profile_problems(name)
    assert problems
    assert any(expected in problem for problem in problems)


def test_a_non_canonical_name_never_becomes_a_path() -> None:
    """The refusal that matters: validation happens where the path is built."""
    with pytest.raises(ValidationError):
        ConfigLayout().document_for(ConfigRole.PROFILE, "../../etc/passwd")


def test_the_shortest_and_longest_permitted_names_are_accepted() -> None:
    """The bounds are inclusive, and a test says so rather than a comment."""
    assert profile_problems("a" * MINIMUM_PROFILE_LENGTH) == ()
    assert profile_problems("a" * MAXIMUM_PROFILE_LENGTH) == ()


def test_the_alphabet_is_lowercase_letters_and_nothing_else() -> None:
    """Pinned, because widening it later would widen every filename rule at once."""
    assert PROFILE_ALPHABET == "abcdefghijklmnopqrstuvwxyz"


# ---------------------------------------------------------------------------
# Resolution: refusal, never a nearest match
# ---------------------------------------------------------------------------


def test_a_declared_profile_resolves_to_itself() -> None:
    """The positive case."""
    assert resolve_profile("testnet", DECLARED) == "testnet"


@pytest.mark.parametrize(
    "supplied",
    [
        pytest.param("  live  ", id="surrounding-whitespace"),
        pytest.param("LIVE", id="uppercase"),
        pytest.param(" Live\t", id="both"),
    ],
)
def test_transport_accidents_are_forgiven(supplied: str) -> None:
    """A name arrives from a launcher argument or an environment variable.

    Case and surrounding whitespace are accidents of that transport rather than of
    intent. Nothing else is.
    """
    assert resolve_profile(supplied, DECLARED) == "live"


@pytest.mark.parametrize(
    "supplied",
    [
        pytest.param("prod", id="plausible-synonym"),
        pytest.param("liv", id="prefix"),
        pytest.param("livee", id="typo"),
        pytest.param("mainnet", id="venue-word-we-do-not-use"),
        pytest.param("", id="empty"),
    ],
)
def test_an_undeclared_profile_is_refused_rather_than_matched(supplied: str) -> None:
    """A name that is nearly `live` is not `live`.

    A selection that silently became something else because it was misspelled
    would be a configuration error reported as a successful start — ADR-0006's
    "never downgraded" rule read at the level of a filename.
    """
    with pytest.raises(ConfigurationError, match="is not a profile"):
        resolve_profile(supplied, DECLARED)


def test_the_refusal_names_every_accepted_spelling() -> None:
    """The reader should be one line from the fix, which is what `_severity` does."""
    with pytest.raises(ConfigurationError) as caught:
        resolve_profile("prod", DECLARED)
    for name in DECLARED:
        assert name in str(caught.value)


def test_resolving_against_no_declared_profile_is_refused() -> None:
    """An empty register would otherwise refuse every name with a confusing message."""
    with pytest.raises(ConfigurationError, match="no profile is declared"):
        resolve_profile("paper", ())
