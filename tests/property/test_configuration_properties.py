"""The laws the configuration fold obeys, over generated layers rather than examples.

``tests/unit/test_configuration.py`` checks the cases someone thought of. These
check the claims that must hold for *every* input, and there are three worth
stating plainly because Phase 027 will build its source ordering on top of them:

* :func:`~globin.domain.configuration.resolve` is **total** — no sequence of
  layers, however malformed the values inside them, makes it raise. That is what
  lets every refusal live in one place where the origin is known, and it is the
  property that breaks the moment somebody sneaks a schema check into the fold.
* **The strongest layer wins, and silence is not a value.** A layer can replace a
  setting; nothing can delete one.
* **Refusal is total in the other direction.** Every value that is not a severity
  name, and every key that is not a setting, is refused — never quietly ignored,
  which is how a typo disables a setting an operator believes they have set.

Deliberately absent: any property asserting that ``resolve`` equals some other
way of writing the same fold. ``docs/TESTING_STRATEGY.md`` warns against a test
that would have to change if the implementation were rewritten correctly, and a
restatement of the loop is exactly that.
"""

from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from globin.adapters.observability import ThresholdLogSink
from globin.domain.configuration import (
    MIN_SEVERITY,
    ConfigLayer,
    GlobinConfig,
    as_config,
    config_layer,
    known_keys,
    resolve,
)
from globin.domain.observability import LogEvent, Severity, log_event
from globin.errors import ConfigurationError
from tests.support import resolved_configuration

SEVERITY_NAMES: Final[frozenset[str]] = frozenset(member.name for member in Severity)

#: A small key space on purpose. Keys drawn from a wide alphabet would almost
#: never collide, and every interesting property here is about what happens when
#: two layers set the same thing.
keys = st.sampled_from(["a.one", "a.two", "b.one", "b.two", "c.one"])

values = st.one_of(
    st.integers(min_value=-100, max_value=100),
    st.text(max_size=6),
    st.booleans(),
    st.none(),
)

origins = st.from_regex(r"[a-z][a-z0-9_-]{0,9}", fullmatch=True)

#: Built from a mapping, so a layer never arrives with a duplicate key — that
#: refusal is a unit test, and generating it here would only re-find it.
layers = st.builds(
    config_layer,
    origin=origins,
    values=st.dictionaries(keys, values, max_size=4),
)

layer_lists = st.lists(layers, max_size=4)

severities = st.sampled_from(list(Severity))

#: Strings that are not the name of a severity. The filter is legitimate
#: narrowing rather than hiding a failure: the valid names are a genuinely
#: different case, tested exhaustively by parametrisation next door.
not_severity_names = st.text(max_size=10).filter(lambda value: value not in SEVERITY_NAMES)

#: Values that are not severities at all. Integers are included deliberately —
#: `Severity` is an `IntEnum`, and `30` being refused is a decision.
non_severity_values = st.one_of(
    st.integers(min_value=0, max_value=60),
    st.booleans(),
    st.none(),
    st.floats(allow_nan=False, allow_infinity=False, width=16),
    st.lists(st.integers(), max_size=2),
)

unknown_keys = st.from_regex(r"[a-z]{1,6}\.[a-z_]{1,8}", fullmatch=True).filter(
    lambda key: key not in known_keys()
)


class _RecordingSink:
    """A sink that keeps what it was given, satisfying the port structurally."""

    def __init__(self) -> None:
        self.records: list[LogEvent] = []

    def emit(self, event: LogEvent) -> None:
        self.records.append(event)


def _bound(**settings: object) -> GlobinConfig:
    """Resolve the defaults with one named override layer, then validate."""
    return as_config(resolved_configuration("generated.toml", **settings))


# --------------------------------------------------------------------------
# The fold
# --------------------------------------------------------------------------


@given(given_layers=layer_lists)
def test_resolving_never_raises_whatever_the_layers_hold(
    given_layers: list[ConfigLayer],
) -> None:
    """Totality is what lets every refusal live in one place."""
    resolve(given_layers)


@given(given_layers=layer_lists)
def test_no_key_is_lost_and_none_is_invented(given_layers: list[ConfigLayer]) -> None:
    mentioned = {key for layer in given_layers for key, _value in layer.values}
    assert set(resolve(given_layers).keys()) == mentioned


@given(earlier=layer_lists, last=layers)
def test_the_strongest_layer_wins_whatever_came_before(
    earlier: list[ConfigLayer], last: ConfigLayer
) -> None:
    resolved = resolve([*earlier, last])
    for key, value in last.values:
        won = resolved.setting(key)
        assert won.value == value
        assert won.origin == last.origin


@given(earlier=layer_lists, last=layers)
def test_a_key_the_last_layer_is_silent_about_keeps_the_answer_it_had(
    earlier: list[ConfigLayer], last: ConfigLayer
) -> None:
    """Silence is not a value: no layer can delete a setting."""
    before = resolve(earlier)
    after = resolve([*earlier, last])
    untouched = set(before.keys()) - {key for key, _value in last.values}
    for key in untouched:
        assert after.setting(key) == before.setting(key)


@given(earlier=layer_lists, repeated=layers)
def test_applying_the_same_layer_twice_changes_nothing(
    earlier: list[ConfigLayer], repeated: ConfigLayer
) -> None:
    assert resolve([*earlier, repeated, repeated]) == resolve([*earlier, repeated])


@given(given_layers=layer_lists, position=st.integers(min_value=0, max_value=4))
def test_an_empty_layer_is_the_identity_wherever_it_is_inserted(
    given_layers: list[ConfigLayer], position: int
) -> None:
    at = min(position, len(given_layers))
    with_empty = [*given_layers[:at], config_layer("empty", {}), *given_layers[at:]]
    assert resolve(with_empty) == resolve(given_layers)


@given(origin=origins, pairs=st.dictionaries(keys, values, max_size=4))
def test_the_order_pairs_arrive_in_cannot_reach_the_result(
    origin: str, pairs: dict[str, object]
) -> None:
    forwards = ConfigLayer(origin=origin, values=tuple(pairs.items()))
    backwards = ConfigLayer(origin=origin, values=tuple(reversed(list(pairs.items()))))
    assert forwards == backwards
    assert resolve([forwards]) == resolve([backwards])


# --------------------------------------------------------------------------
# Binding, in both directions
# --------------------------------------------------------------------------


@given(severity=severities)
def test_every_severity_survives_the_spelling_the_document_uses(severity: Severity) -> None:
    assert _bound(**{MIN_SEVERITY: severity.name}).logging.min_severity is severity


@given(spelling=not_severity_names)
def test_a_string_that_is_not_a_severity_name_is_refused(spelling: str) -> None:
    with pytest.raises(ConfigurationError) as refused:
        _bound(**{MIN_SEVERITY: spelling})
    assert "generated.toml" in str(refused.value)


@given(value=non_severity_values)
def test_a_value_that_is_not_a_string_is_refused(value: object) -> None:
    with pytest.raises(ConfigurationError):
        _bound(**{MIN_SEVERITY: value})


@given(key=unknown_keys, value=values)
def test_any_key_that_is_not_a_setting_is_refused_by_name(key: str, value: object) -> None:
    with pytest.raises(ConfigurationError) as refused:
        _bound(**{key: value})
    assert key in str(refused.value)


def test_the_refusal_harness_accepts_a_value_that_ought_to_pass() -> None:
    """Guard the guard.

    The three refusal properties above all resolve through :func:`_bound`, and
    each asserts only that something was raised. They would pass just as well if
    that construction failed for a reason having nothing to do with the value
    under test — a malformed origin, say. This is the positive control that says
    it does not.
    """
    assert _bound(**{MIN_SEVERITY: "WARNING"}).logging.min_severity is Severity.WARNING
    assert "WARNING" in SEVERITY_NAMES


# --------------------------------------------------------------------------
# The threshold sink
# --------------------------------------------------------------------------


@given(severity=severities, minimum=severities)
def test_a_record_is_forwarded_exactly_when_it_clears_the_threshold(
    severity: Severity, minimum: Severity
) -> None:
    """Both directions. A sink that forwarded everything would pass a test that.

    only checked the records it expected to see.
    """
    inner = _RecordingSink()
    ThresholdLogSink(inner=inner, minimum=minimum).emit(log_event(severity, "a.b", "corr-1"))
    assert bool(inner.records) is (severity >= minimum)


@given(severity=severities)
def test_the_record_that_arrives_is_the_record_that_was_sent(severity: Severity) -> None:
    """So no future 'helpful' enrichment can slip into the decorator."""
    inner = _RecordingSink()
    event = log_event(severity, "a.b", "corr-1", {"n": 1})
    ThresholdLogSink(inner=inner, minimum=Severity.DEBUG).emit(event)
    assert inner.records == [event]
    assert inner.records[0] is event


@given(severity=severities, first=severities, second=severities)
def test_stacking_two_thresholds_is_the_stricter_of_the_two(
    severity: Severity, first: Severity, second: Severity
) -> None:
    nested_inner = _RecordingSink()
    nested = ThresholdLogSink(
        inner=ThresholdLogSink(inner=nested_inner, minimum=first), minimum=second
    )
    flat_inner = _RecordingSink()
    flat = ThresholdLogSink(inner=flat_inner, minimum=max(first, second))

    event = log_event(severity, "a.b", "corr-1")
    nested.emit(event)
    flat.emit(event)

    assert nested_inner.records == flat_inner.records
