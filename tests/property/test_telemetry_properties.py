"""Telemetry's invariants over generated input.

The unit tests pin the refusals somebody thought of. These assert the properties
that must hold for every attribute set a caller could construct, which is where a
screening function that must never raise is actually attacked.
"""

from hypothesis import given
from hypothesis import strategies as st

from globin.domain.observability import SENSITIVE_KEY_FRAGMENTS
from globin.domain.telemetry import (
    ATTRIBUTE_KEY_ALPHABET,
    ATTRIBUTE_VALUE_ALPHABET,
    MAXIMUM_ATTRIBUTE_KEYS,
    PARTS_PER_MILLION,
    AttributeDomain,
    MetricAttributes,
    attribute_problem_codes,
    attribute_problems,
    is_high_cardinality,
    name_problems,
    ratio_parts_per_million,
)
from globin.errors import ValidationError

keys = st.text(alphabet=ATTRIBUTE_KEY_ALPHABET, min_size=2, max_size=24)
"""Keys valid by construction, so the search stays on behaviour not the constructor."""

values = st.text(alphabet=ATTRIBUTE_VALUE_ALPHABET, min_size=1, max_size=32)
"""Likewise for values."""

anything = st.text(max_size=40)
"""Everything a caller could actually pass, including what it should not."""

DOMAINS: tuple[AttributeDomain, ...] = (
    AttributeDomain("component", ("telemetry", "watchdog")),
    AttributeDomain("result", ("error", "ok")),
)
"""A fixed pair of bounded dimensions to screen against."""


@given(st.dictionaries(anything, anything, max_size=8))
def test_screening_is_total_and_never_raises(supplied: dict[str, str]) -> None:
    """A telemetry call must never take down the code it is measuring.

    The single most important property here: whatever a caller passes, screening
    returns rather than raising, so the recorder can drop and count.
    """
    for code in attribute_problems(DOMAINS, supplied):
        assert code in attribute_problem_codes()


@given(st.dictionaries(anything, anything, max_size=8))
def test_no_supplied_value_ever_reaches_a_problem_code(supplied: dict[str, str]) -> None:
    """The offending token is arbitrary caller data and could be a credential.

    Asserted over generated input rather than one planted secret, because the
    guarantee is about the return *type* — codes — and not about one string.
    """
    problems = attribute_problems(DOMAINS, supplied)
    for value in supplied.values():
        if len(value) < 4:
            continue
        for problem in problems:
            assert value not in problem


@given(st.dictionaries(anything, anything, max_size=8))
def test_problems_are_deduplicated_and_ordered(supplied: dict[str, str]) -> None:
    """Deterministic output, so one diagnostic reads the same on two runs."""
    problems = attribute_problems(DOMAINS, supplied)
    assert len(problems) == len(set(problems))
    declared = attribute_problem_codes()
    positions = [declared.index(code) for code in problems]
    assert positions == sorted(positions)


@given(st.lists(st.tuples(keys, values), max_size=MAXIMUM_ATTRIBUTE_KEYS))
def test_attribute_order_never_changes_identity(pairs: list[tuple[str, str]]) -> None:
    """Two callers supplying the same dimensions must produce one series.

    The order-independence property `test_health_properties.py` asserts for the
    health reduction, applied to the thing that becomes a series key.
    """
    unique = dict(pairs)
    try:
        forwards = MetricAttributes(tuple(unique.items()))
        backwards = MetricAttributes(tuple(reversed(list(unique.items()))))
    except ValidationError:
        return
    assert forwards == backwards
    assert forwards.series_key() == backwards.series_key()


@given(st.lists(st.tuples(keys, values), min_size=1, max_size=MAXIMUM_ATTRIBUTE_KEYS))
def test_a_series_key_round_trips_to_its_own_pairs(pairs: list[tuple[str, str]]) -> None:
    """Injectivity, asserted by reconstruction rather than by inspection.

    The alphabet excludes `=` and `,`, so splitting on them recovers exactly what
    was joined. If that ever stops being true, two dimension sets collapse onto
    one series and nothing else would notice.
    """
    unique = dict(pairs)
    try:
        attributes = MetricAttributes(tuple(unique.items()))
    except ValidationError:
        return
    recovered = dict(part.split("=", 1) for part in attributes.series_key().split(","))
    assert recovered == unique


@given(anything)
def test_a_credential_shaped_key_can_never_be_constructed(key: str) -> None:
    """Refusal rather than substitution, for every spelling rather than a list.

    An attribute is a dimension; substituting it merges two series under a name
    that means nothing, which is worse than refusing the observation.
    """
    if not any(fragment in key.casefold() for fragment in SENSITIVE_KEY_FRAGMENTS):
        return
    try:
        MetricAttributes(((key, "ok"),))
    except ValidationError:
        return
    msg = f"a credential-shaped key was accepted: {key!r}"
    raise AssertionError(msg)


@given(keys, st.lists(values, min_size=1, max_size=6, unique=True))
def test_a_declared_domain_is_bounded_and_canonical(key: str, permitted: list[str]) -> None:
    """Every constructible domain bounds its dimension and sorts its values."""
    if is_high_cardinality(key) or any(
        fragment in key.casefold() for fragment in SENSITIVE_KEY_FRAGMENTS
    ):
        return
    domain = AttributeDomain(key, tuple(permitted))
    assert domain.permitted == tuple(sorted(permitted))
    assert len(domain.permitted) == len(set(domain.permitted))


@given(st.integers(min_value=0, max_value=10_000), st.integers(min_value=1, max_value=10_000))
def test_a_ratio_is_always_inside_its_declared_bound(numerator: int, denominator: int) -> None:
    """A ratio above one is a defect, and the type must make it unreachable."""
    if numerator > denominator:
        return
    parts = ratio_parts_per_million(numerator, denominator)
    assert 0 <= parts <= PARTS_PER_MILLION


@given(st.integers(min_value=0, max_value=10_000), st.integers(min_value=1, max_value=10_000))
def test_flooring_never_overstates(numerator: int, denominator: int) -> None:
    """The direction the name promises, asserted rather than assumed.

    A floored ratio must never exceed the exact one, which is what makes it safe
    for a success rate: the reported figure is never better than the measurement.
    """
    if numerator > denominator:
        return
    parts = ratio_parts_per_million(numerator, denominator)
    assert parts * denominator <= numerator * PARTS_PER_MILLION


@given(anything)
def test_name_screening_is_total(name: str) -> None:
    """Every string either is a canonical name or is reported, and nothing raises."""
    problems = name_problems(name)
    assert isinstance(problems, tuple)
    if not problems:
        assert name.startswith("globin.")
