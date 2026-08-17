"""Invariants of the configuration layout over generated input.

The unit tests pin the four documents and the refusals somebody thought of. These
assert the properties that must hold for every name a caller could supply, which
is where a path-building function is actually attacked.
"""

from hypothesis import given
from hypothesis import strategies as st

from globin.domain.config_layout import (
    MAXIMUM_PROFILE_LENGTH,
    PATH_SEPARATOR,
    PROFILE_ALPHABET,
    ConfigLayout,
    ConfigRole,
    profile_problems,
    resolve_profile,
    roles,
)
from globin.errors import ConfigurationError, ValidationError

canonical_names = st.text(alphabet=PROFILE_ALPHABET, min_size=3, max_size=MAXIMUM_PROFILE_LENGTH)
"""Names drawn so that they are valid by construction.

Building valid input rather than filtering it keeps the search on the behaviour
instead of on the constructor — the rule `test_watchdog_properties.py` states.
"""

arbitrary_names = st.text(max_size=40)
"""Anything at all, including the spellings a caller should never send."""


@given(canonical_names)
def test_a_canonical_name_always_produces_a_contained_spelling(name: str) -> None:
    """The property that matters: a validated name cannot address anything else.

    No traversal, no absolute prefix, no backslash, and always inside the
    configuration directory — for every name the validator accepts, not only the
    four the programme declares.
    """
    layout = ConfigLayout()
    for spelling in layout.documents_for(name).values():
        assert not spelling.startswith(PATH_SEPARATOR)
        assert "\\" not in spelling
        assert ".." not in spelling.split(PATH_SEPARATOR)
        assert spelling.startswith(f"{layout.directory}{PATH_SEPARATOR}")


@given(canonical_names)
def test_every_role_is_present_and_distinct(name: str) -> None:
    """A mapping keyed by role, complete, with no two roles sharing a document.

    Two roles resolving to one file would make a precedence Phase 027 has not yet
    chosen silently unobservable.
    """
    documents = ConfigLayout().documents_for(name)
    assert set(documents) == set(roles())
    profile_documents = {
        documents[ConfigRole.PROFILE],
        documents[ConfigRole.LOCAL_PROFILE],
        documents[ConfigRole.BASE],
        documents[ConfigRole.LOCAL_BASE],
    }
    assert len(profile_documents) == len(roles())


@given(arbitrary_names)
def test_the_screen_and_the_builder_agree(name: str) -> None:
    """`profile_problems` empty must mean `document_for` succeeds, and conversely.

    The same screen/constructor agreement `member_problems` and `safe_member_name`
    have. A disagreement would mean either a name that passes review and then
    raises, or one that is refused by review and would have been safe.
    """
    layout = ConfigLayout()
    if profile_problems(name):
        try:
            layout.document_for(ConfigRole.PROFILE, name)
        except ValidationError:
            return
        msg = f"{name!r} has problems but still built a path"
        raise AssertionError(msg)
    assert layout.document_for(ConfigRole.PROFILE, name)


@given(arbitrary_names)
def test_problems_never_quote_the_candidate_into_a_path(name: str) -> None:
    """A rejected name is reported, and the report is prose rather than a path.

    Worth pinning because the message quotes the candidate: a reader must never be
    able to mistake the refusal for a location GLOBIN consulted.
    """
    for problem in profile_problems(name):
        assert not problem.startswith(PATH_SEPARATOR)


@given(canonical_names, st.lists(canonical_names, max_size=8))
def test_resolution_is_refusal_or_an_element_of_the_register(
    name: str, declared: list[str]
) -> None:
    """Total: every input either returns something declared or raises.

    There is no third outcome — no nearest match, no default, no empty string.
    """
    if not declared:
        return
    try:
        resolved = resolve_profile(name, tuple(declared))
    except ConfigurationError:
        assert name not in declared
        return
    assert resolved in declared


@given(canonical_names, st.lists(canonical_names, min_size=1, max_size=8))
def test_resolution_is_idempotent(name: str, declared: list[str]) -> None:
    """Resolving a resolved name changes nothing.

    A resolver that normalised on the way through would break this, and a
    normalisation nobody declared is how two spellings of one profile appear.
    """
    try:
        once = resolve_profile(name, tuple(declared))
    except ConfigurationError:
        return
    assert resolve_profile(once, tuple(declared)) == once
