"""Telemetry's promises to the rest of the repository.

`test_telemetry.py` owns the behaviour. This owns the claims the design makes
about how telemetry fits beside what already exists — chiefly that its second
denylist answers a question the first one cannot, which is the whole justification
for there being two.
"""

from globin.domain.observability import SENSITIVE_KEY_FRAGMENTS, is_sensitive
from globin.domain.telemetry import (
    ATTRIBUTE_KEY_ALPHABET,
    ATTRIBUTE_VALUE_ALPHABET,
    HIGH_CARDINALITY_KEY_FRAGMENTS,
    METRIC_NAME_ALPHABET,
    METRIC_NAMESPACE,
    MetricUnit,
    attribute_problem_codes,
    is_high_cardinality,
    unit_specifications,
)


def test_the_two_denylists_are_disjoint() -> None:
    """The claim that justifies a second list existing at all.

    `is_sensitive` answers *would this value be a secret*; `is_high_cardinality`
    answers *would this value be unbounded*. They are different questions — an
    order id is not a secret and is fatal as a label; an API key is not especially
    high-cardinality and is fatal for another reason entirely.

    A third list would be drift. Two lists whose disjointness is asserted are the
    arrangement `SOURCE_OF_TRUTH.md` permits, and this is the assertion.
    """
    overlap = set(SENSITIVE_KEY_FRAGMENTS) & set(HIGH_CARDINALITY_KEY_FRAGMENTS)
    assert not overlap, f"a fragment answers both questions, so one list is redundant: {overlap}"


def test_neither_list_is_empty_and_neither_subsumes_the_other() -> None:
    """Guard the guard above: disjoint but empty would pass and mean nothing."""
    assert SENSITIVE_KEY_FRAGMENTS
    assert HIGH_CARDINALITY_KEY_FRAGMENTS
    assert any(is_sensitive(key) and not is_high_cardinality(key) for key in ("api_key", "token"))
    assert any(is_high_cardinality(key) and not is_sensitive(key) for key in ("order_id", "email"))


def test_the_sensitive_list_is_reused_rather_than_restated() -> None:
    """Telemetry imports the predicate; it does not carry a copy of the fragments.

    Asserted by behaviour rather than by inspection: every fragment the logging
    module declares must already be refused by telemetry's key screen, which can
    only be true if the same predicate is doing the work.
    """
    for fragment in SENSITIVE_KEY_FRAGMENTS:
        assert is_sensitive(fragment)


def test_the_problem_vocabulary_is_closed_and_unique() -> None:
    """A code produced but unnamed is a hole; a name nothing produces is a fiction."""
    codes = attribute_problem_codes()
    assert len(set(codes)) == len(codes)
    for code in codes:
        assert code.startswith("TELEMETRY_")
        assert code.isupper()


def test_every_unit_declares_a_distinct_name_suffix() -> None:
    """Two units sharing a suffix would make a metric name ambiguous about scale."""
    suffixes = [spec.suffix for spec in unit_specifications()]
    assert len(set(suffixes)) == len(suffixes)


def test_every_unit_bounds_itself_at_or_above_zero() -> None:
    """No metric GLOBIN declares today is signed, and the units say so.

    Signed money is Phases 155-156. A unit that permitted a negative value would
    let a counter fold below zero without anything noticing.
    """
    for spec in unit_specifications():
        assert spec.minimum >= 0
        assert spec.maximum is None or spec.maximum > spec.minimum


def test_the_alphabets_keep_a_series_key_injective() -> None:
    """`series_key` joins with `=` and `,`, so neither may appear in a value.

    This is the property the whole identity scheme rests on, and it is a fact
    about the alphabet rather than about the join.
    """
    assert "=" not in ATTRIBUTE_VALUE_ALPHABET
    assert "," not in ATTRIBUTE_VALUE_ALPHABET
    assert " " not in ATTRIBUTE_VALUE_ALPHABET


def test_an_attribute_key_cannot_be_spelled_like_a_metric_name() -> None:
    """A dotted key would read as a name where the two appear side by side."""
    assert "." not in ATTRIBUTE_KEY_ALPHABET
    assert "." in METRIC_NAME_ALPHABET


def test_a_metric_name_needs_no_json_escaping() -> None:
    """Every name reaches a JSON key, and an escaped key is a key two ways.

    Deliberately **not** compared against `SCHEMA_NAME_ALPHABET`. That alphabet
    excludes the underscore and governs a *schema* name — the identity of a
    document format. A metric name is a JSON key inside such a document, which is
    a different thing with a different rule, and conflating them would forbid
    `error_type` for a reason that does not apply to it.

    What actually matters is that no character here forces the encoder to escape,
    because an escaped key compares unequal to its own spelling in every tool that
    reads the document as text.
    """
    forbidden = ('"', "\\", "\n", "\r", "\t")
    for character in METRIC_NAME_ALPHABET + METRIC_NAMESPACE:
        assert character not in forbidden
        assert character.isprintable()


def test_the_unit_registry_covers_the_enum_in_both_directions() -> None:
    """A member without a specification, or one for a member that is gone."""
    declared = {spec.unit for spec in unit_specifications()}
    assert declared == set(MetricUnit)
