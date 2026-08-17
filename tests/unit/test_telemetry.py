"""The pure telemetry vocabulary: names, units, dimensions and refusals.

Everything here runs without a clock, a registry or a provider. What a descriptor
does with these, and what an exporter makes of them, belong to the modules that
own those; this owns the values themselves and the rules that make a dimension
recordable.
"""

from typing import TYPE_CHECKING

import pytest

from globin.domain.telemetry import (
    MAXIMUM_ATTRIBUTE_KEYS,
    MAXIMUM_ATTRIBUTE_VALUE_LENGTH,
    MAXIMUM_METRIC_VALUE,
    MAXIMUM_PERMITTED_VALUES,
    METRIC_NAMESPACE,
    PARTS_PER_MILLION,
    AttributeDomain,
    MetricAttributes,
    MetricKind,
    MetricUnit,
    attribute_problem_codes,
    attribute_problems,
    is_high_cardinality,
    name_problems,
    ratio_parts_per_million,
    unit_specification,
    unit_specifications,
)
from globin.errors import InternalError, ValidationError

if TYPE_CHECKING:
    from collections.abc import Mapping

SENTINEL = "SENTINEL-VALUE-9c1e"
"""An obviously synthetic value, per `docs/TESTING_STRATEGY.md`."""

DOMAINS: tuple[AttributeDomain, ...] = (
    AttributeDomain("component", ("telemetry", "watchdog")),
    AttributeDomain("result", ("error", "ok")),
)
"""Two bounded dimensions, which is what a real descriptor declares."""


def supplied(**overrides: str) -> dict[str, str]:
    """A complete, valid attribute set, with fields replaced.

    Args:
        overrides: Values to replace or add.

    Returns:
        The attribute mapping.
    """
    return {"component": "telemetry", "result": "ok", **overrides}


# ---------------------------------------------------------------------------
# Names: the namespace is the whole of "provider-neutral"
# ---------------------------------------------------------------------------


def test_a_canonical_name_has_no_problems() -> None:
    """The positive case, so the refusals are not vacuously satisfied."""
    assert name_problems("globin.telemetry.observations.total") == ()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        pytest.param("", "empty", id="empty"),
        pytest.param("otel.foo.bar", "does not begin with", id="foreign-namespace"),
        pytest.param("globin.a", "segments", id="too-few-segments"),
        pytest.param("globin." + "a.b.c.d.e.f.g", "segments", id="too-many-segments"),
        pytest.param("globin.Telemetry.total", "outside the metric name", id="uppercase"),
        pytest.param("globin.tele metry.total", "outside the metric name", id="space"),
        pytest.param("globin..total", "empty segment", id="empty-segment"),
        pytest.param("globin.1st.total", "begin with a letter", id="leading-digit"),
        pytest.param("globin.a__b.total", "doubled underscore", id="doubled-underscore"),
        pytest.param("globin.ab_.total", "trailing or doubled", id="trailing-underscore"),
    ],
)
def test_a_non_canonical_name_is_reported(name: str, expected: str) -> None:
    """Each row is a real way a name stops being comparable across exporters."""
    problems = name_problems(name)
    assert problems
    assert any(expected in problem for problem in problems)


def test_the_namespace_is_what_makes_the_boundary_concrete() -> None:
    """An exporter maps `globin.*`; nothing else may claim it."""
    assert METRIC_NAMESPACE == "globin."
    assert name_problems("globin.telemetry.batches.total") == ()


# ---------------------------------------------------------------------------
# Units: base units declared, integers stored
# ---------------------------------------------------------------------------


def test_every_unit_has_exactly_one_specification() -> None:
    """A member without one means the module was edited in half."""
    specs = unit_specifications()
    assert {spec.unit for spec in specs} == set(MetricUnit)
    assert len(specs) == len(MetricUnit)


def test_a_second_lookup_of_the_same_unit_agrees() -> None:
    """The registry is a function, so it is worth proving it is stable."""
    assert unit_specification(MetricUnit.BYTES) == unit_specification(MetricUnit.BYTES)


def test_a_duration_is_stored_in_nanoseconds() -> None:
    """The choice that removes arithmetic from the recording path entirely.

    `MonotonicReading.since` already returns integer nanoseconds, so an
    observation is stored exactly as it was measured.
    """
    spec = unit_specification(MetricUnit.SECONDS)
    assert spec.scale_exponent == -9
    assert spec.exporter_name == "s"


def test_a_ratio_is_bounded_at_one() -> None:
    """A ratio above one is a defect, not a value."""
    spec = unit_specification(MetricUnit.RATIO)
    assert spec.maximum == PARTS_PER_MILLION


def test_an_unregistered_unit_is_an_internal_error() -> None:
    """Guard the guard: the failure path of the registry lookup is exercised."""

    class Fake:
        """A stand-in for a member that has no entry."""

    with pytest.raises(InternalError, match="has no specification"):
        unit_specification(Fake())  # type: ignore[arg-type]


def test_the_metric_ceiling_is_the_double_precision_limit() -> None:
    """Not Python's limit — every other JSON reader's.

    GLOBIN stores and reads an integer exactly at any width. A consumer holding
    numbers as IEEE-754 doubles silently drops low bits past 2**53, which is the
    corruption the float ban exists to prevent arriving through the integer door.
    """
    assert MAXIMUM_METRIC_VALUE == 2**53 - 1


# ---------------------------------------------------------------------------
# Cardinality: the two questions, and why they need two lists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("id", id="bare-id"),
        pytest.param("order_id", id="order-id"),
        pytest.param("request_id", id="request-id"),
        pytest.param("span_id", id="span-id"),
        pytest.param("started_at", id="instant-at"),
        pytest.param("elapsed_ms", id="instant-ms"),
        pytest.param("elapsed_ns", id="instant-ns"),
        pytest.param("wall_time", id="instant-time"),
        pytest.param("user", id="fragment-user"),
        pytest.param("email", id="fragment-email"),
        pytest.param("symbol", id="fragment-symbol"),
        pytest.param("full_path", id="fragment-path"),
        pytest.param("error_message", id="fragment-message"),
    ],
)
def test_an_unbounded_key_is_recognised(key: str) -> None:
    """Three rules rather than an enumeration, so a new spelling is covered too.

    `_id` catches every identifier suffix at once, which is what makes four
    separate cases a single rule.
    """
    assert is_high_cardinality(key)


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("component", id="component"),
        pytest.param("result", id="result"),
        pytest.param("status", id="status"),
        pytest.param("mode", id="mode"),
        pytest.param("error_type", id="error-type"),
    ],
)
def test_a_bounded_key_is_spared(key: str) -> None:
    """The other direction, so the rule is not simply refusing everything."""
    assert not is_high_cardinality(key)


def test_a_credential_shaped_key_cannot_be_declared() -> None:
    """`is_sensitive` is reused rather than restated, so the two cannot drift."""
    with pytest.raises(ValidationError, match="names a credential"):
        AttributeDomain("api_key", ("a", "b"))


def test_an_unbounded_key_cannot_be_declared() -> None:
    """A dimension whose values are unbounded is refused where it is written."""
    with pytest.raises(ValidationError, match="names an unbounded value"):
        AttributeDomain("order_id", ("a", "b"))


@pytest.mark.parametrize(
    ("key", "permitted", "expected"),
    [
        pytest.param("component", (), "declares no permitted value", id="empty-domain"),
        pytest.param("component", ("a",) * 1, "", id="single-is-fine"),
        pytest.param(
            "component",
            tuple(f"v{index}" for index in range(MAXIMUM_PERMITTED_VALUES + 1)),
            "more than",
            id="too-many-values",
        ),
        pytest.param("component", ("a", "a"), "repeats", id="repeated-value"),
        pytest.param("component", ("A",), "contains", id="uppercase-value"),
        pytest.param("c", ("a",), "outside", id="key-too-short"),
        pytest.param("comp onent", ("a",), "contains", id="key-with-space"),
        pytest.param("comp.onent", ("a",), "contains", id="dotted-key"),
    ],
)
def test_a_malformed_domain_is_refused(key: str, permitted: tuple[str, ...], expected: str) -> None:
    """A dotted key is refused because it would read as a metric name."""
    if not expected:
        assert AttributeDomain(key, permitted).permitted == permitted
        return
    with pytest.raises(ValidationError, match=expected):
        AttributeDomain(key, permitted)


def test_a_domain_canonicalises_its_permitted_values() -> None:
    """Two domains declaring the same set compare equal whatever order was typed."""
    assert AttributeDomain("result", ("ok", "error")) == AttributeDomain("result", ("error", "ok"))


# ---------------------------------------------------------------------------
# Attributes: refusal where a log field would substitute
# ---------------------------------------------------------------------------


def test_attributes_canonicalise_their_order() -> None:
    """A dimension set must serialise identically whatever order it was built in."""
    one = MetricAttributes((("result", "ok"), ("component", "telemetry")))
    two = MetricAttributes((("component", "telemetry"), ("result", "ok")))
    assert one == two
    assert one.series_key() == "component=telemetry,result=ok"


def test_a_series_key_is_injective() -> None:
    """The value alphabet excludes both separators, which is what buys this."""
    one = MetricAttributes((("component", "a-b"), ("result", "c")))
    two = MetricAttributes((("component", "a"), ("result", "b-c")))
    assert one.series_key() != two.series_key()


def test_a_credential_shaped_attribute_is_refused_rather_than_redacted() -> None:
    """The deliberate divergence from `LogEvent`, and the reason it is deliberate.

    A log field is a leaf, so substituting loses one datum. An attribute is a
    *dimension*, so substituting merges two series under a meaningless name — a
    real series with a fake identity, which is worse than no series at all.
    """
    with pytest.raises(ValidationError, match="names a credential"):
        MetricAttributes((("session_id", "abc"),))


@pytest.mark.parametrize(
    ("pairs", "expected"),
    [
        pytest.param((("a", "b"),), "outside", id="key-too-short"),
        pytest.param((("component", ""),), "empty or longer", id="empty-value"),
        pytest.param(
            (("component", "x" * (MAXIMUM_ATTRIBUTE_VALUE_LENGTH + 1)),),
            "empty or longer",
            id="value-too-long",
        ),
        pytest.param((("component", "a,b"),), "contains", id="value-with-comma"),
        pytest.param((("component", "a=b"),), "contains", id="value-with-equals"),
        pytest.param((("component", "a"), ("component", "b")), "repeated", id="repeated-key"),
        pytest.param(
            tuple((f"key{index}", "v") for index in range(MAXIMUM_ATTRIBUTE_KEYS + 1)),
            "more than",
            id="too-many-keys",
        ),
    ],
)
def test_malformed_attributes_are_refused(
    pairs: tuple[tuple[str, str], ...], expected: str
) -> None:
    """A comma or an equals sign would break `series_key`'s injectivity."""
    with pytest.raises(ValidationError, match=expected):
        MetricAttributes(pairs)


# ---------------------------------------------------------------------------
# Screening: codes, never the value
# ---------------------------------------------------------------------------


def test_a_complete_declared_attribute_set_has_no_problems() -> None:
    """The positive case."""
    assert attribute_problems(DOMAINS, supplied()) == ()


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        pytest.param(supplied(extra="x"), "TELEMETRY_KEY_NOT_DECLARED", id="undeclared"),
        pytest.param({"component": "telemetry"}, "TELEMETRY_KEY_MISSING", id="missing"),
        pytest.param(supplied(api_key="s"), "TELEMETRY_KEY_SENSITIVE", id="credential"),
        pytest.param(supplied(order_id="1"), "TELEMETRY_KEY_UNBOUNDED", id="unbounded"),
        pytest.param(supplied(result="NOPE"), "TELEMETRY_VALUE_MALFORMED", id="malformed-value"),
        pytest.param(
            supplied(result="maybe"), "TELEMETRY_VALUE_NOT_PERMITTED", id="undeclared-value"
        ),
        pytest.param({"a": "b"}, "TELEMETRY_KEY_MALFORMED", id="malformed-key"),
    ],
)
def test_each_refusal_earns_its_own_code(given: dict[str, object], expected: str) -> None:
    """Fail-closed: an unknown key is never recorded, and the reason is specific."""
    assert expected in attribute_problems(DOMAINS, given)


def test_the_screen_never_names_a_supplied_value() -> None:
    """The offending token is caller data and could be a credential.

    `member_problems` quotes the offending member because GLOBIN chose that
    filename. Here it did not, so nothing supplied ever reaches the return value.
    """
    problems = attribute_problems(DOMAINS, supplied(result=SENTINEL, api_key=SENTINEL))
    assert problems
    for problem in problems:
        assert SENTINEL not in problem


def test_every_code_the_screen_emits_is_declared() -> None:
    """The closed vocabulary, checked from the emitting side."""
    cases: tuple[Mapping[str, object], ...] = (
        supplied(),
        supplied(extra="x"),
        {"component": "telemetry"},
        supplied(api_key="s"),
        supplied(order_id="1"),
        supplied(result="NOPE"),
        supplied(result="maybe"),
        {"a": "b"},
    )
    for case in cases:
        for code in attribute_problems(DOMAINS, case):
            assert code in attribute_problem_codes()


def test_the_screen_is_total_for_input_of_any_type() -> None:
    """A caller can pass anything, and screening must still return rather than raise."""
    assert attribute_problems(DOMAINS, {1: "a", "component": 2}) != ()  # type: ignore[dict-item]


def test_problems_are_reported_in_declaration_order_without_repeats() -> None:
    """Deterministic output, so a diagnostic reads the same on two runs."""
    problems = attribute_problems(DOMAINS, {"api_key": "s", "order_id": "1"})
    assert list(problems) == [code for code in attribute_problem_codes() if code in problems]
    assert len(problems) == len(set(problems))


# ---------------------------------------------------------------------------
# Ratios: integer, floored, and discouraged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("numerator", "denominator", "expected"),
    [
        pytest.param(0, 1, 0, id="zero"),
        pytest.param(1, 1, PARTS_PER_MILLION, id="one"),
        pytest.param(1, 2, 500_000, id="half"),
        pytest.param(1, 3, 333_333, id="floored-third"),
        pytest.param(2, 3, 666_666, id="floored-two-thirds"),
    ],
)
def test_a_ratio_is_an_integer_in_parts_per_million(
    numerator: int, denominator: int, expected: int
) -> None:
    """Floored, and named so, because GLOBIN has no default rounding mode."""
    assert ratio_parts_per_million(numerator, denominator) == expected


@pytest.mark.parametrize(
    ("numerator", "denominator"),
    [
        pytest.param(1, 0, id="zero-denominator"),
        pytest.param(1, -1, id="negative-denominator"),
        pytest.param(-1, 2, id="negative-numerator"),
        pytest.param(3, 2, id="above-one"),
        pytest.param(True, 2, id="bool-numerator"),
    ],
)
def test_an_impossible_ratio_is_refused(numerator: int, denominator: int) -> None:
    """A ratio above one is a defect, and `isinstance(True, int)` is why bools are checked."""
    with pytest.raises(ValidationError):
        ratio_parts_per_million(numerator, denominator)


def test_the_three_kinds_are_closed() -> None:
    """No summary, because provider-computed quantiles do not aggregate."""
    assert set(MetricKind) == {MetricKind.COUNTER, MetricKind.GAUGE, MetricKind.HISTOGRAM}
