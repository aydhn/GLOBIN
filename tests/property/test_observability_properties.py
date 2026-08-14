"""Redaction and serialisation invariants, over generated input rather than examples.

``tests/unit/test_observability.py`` checks that redaction handles the cases
someone thought of. These check the two claims that have to hold for *every*
input, because both are claims a chosen example cannot establish:

* a value filed under a sensitive name never reaches the output, at any depth;
* no field value whatsoever can make the sink emit something that is not JSON.

The second is the property that justifies coercion being total. If a value
existed that :func:`~globin.adapters.observability.as_record` could not render,
a logging call would be able to raise, and Phases 081-096 will log from an order
loop where that matters more than the diagnostic being pretty.
"""

import json
from decimal import Decimal
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from globin.adapters.observability import as_record
from globin.application.observability import Logger
from globin.domain.observability import (
    REDACTED,
    SENSITIVE_KEY_FRAGMENTS,
    LogEvent,
    Severity,
    is_sensitive,
    log_event,
    redact,
)

SENTINEL: Final[str] = "SENTINEL-VALUE-4f2a"
"""Distinctive enough that finding it anywhere in a rendered structure is proof."""

#: Ordinary field names. ASCII only and lowercase-seeded, because the
#: case-insensitivity property below compares `upper()` against `lower()`, and
#: Unicode case mapping is not length-preserving — Turkish dotted capital I
#: lowercases to two code points. Restricting the alphabet keeps the property
#: about the redaction rule rather than about Unicode.
plain_names = st.from_regex(r"[a-z][a-z0-9_]{0,11}", fullmatch=True)

#: Names built to trip the rule, since a random identifier almost never contains
#: "secret" and a generator that never produces one proves nothing.
sensitive_names = st.tuples(
    st.sampled_from(["", "binance_", "client_", "x_"]),
    st.sampled_from(SENSITIVE_KEY_FRAGMENTS),
    st.sampled_from(["", "s", "_value"]),
).map(lambda parts: "".join(parts))

field_names = st.one_of(plain_names, sensitive_names)

#: Arbitrarily shaped payloads whose every leaf is the sentinel.
payloads = st.recursive(
    st.just(SENTINEL),
    lambda children: (
        st.dictionaries(plain_names, children, max_size=3) | st.lists(children, max_size=3)
    ),
    max_leaves=6,
)

#: Values chosen to include several JSON cannot represent: `Decimal` and
#: `bytes` reach the `repr` fallback, and `float` covers NaN and both infinities.
values = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(),
    st.text(max_size=20),
    st.binary(max_size=8),
    st.decimals(allow_nan=True, allow_infinity=True),
)


@given(fields=st.dictionaries(field_names, st.just(SENTINEL), max_size=8))
def test_a_value_survives_exactly_when_its_name_is_not_sensitive(
    fields: dict[str, str],
) -> None:
    """The rule and its consequence, stated over every generated name.

    Both directions matter. Under-redaction leaks a credential; over-redaction
    applied to everything would satisfy a one-directional test while making the
    log useless.
    """
    result = redact(fields)

    for name, value in result.items():
        expected = REDACTED if is_sensitive(name) else SENTINEL
        assert value == expected, f"{name!r} rendered as {value!r}"


@given(payload=payloads)
def test_a_sensitive_name_hides_everything_beneath_it(payload: object) -> None:
    """Redaction stops at the name; it does not walk into what the name covered."""
    assert SENTINEL not in str(redact({"api_secret": payload}))


@given(payload=payloads)
def test_a_sensitive_name_nested_under_an_innocent_one_still_redacts(payload: object) -> None:
    """The failure this rules out: a secret one level below a name nobody flagged."""
    assert SENTINEL not in str(redact({"request": {"headers": {"authorization": payload}}}))


@given(fields=st.dictionaries(field_names, payloads, max_size=5))
def test_redaction_is_idempotent(fields: dict[str, object]) -> None:
    """Re-redacting an event's fields must not change them.

    A rule that kept finding new things to redact on each pass would mean the
    first pass had not finished, and events are redacted exactly once.
    """
    once = redact(fields)

    assert redact(once) == once


@given(name=field_names)
def test_sensitivity_ignores_case(name: str) -> None:
    """A caller writing ``apiKey`` must be treated the same as one writing ``api_key``."""
    assert is_sensitive(name) == is_sensitive(name.upper()) == is_sensitive(name.lower())


@given(fields=st.dictionaries(plain_names, values, max_size=6))
def test_no_field_value_can_produce_something_that_is_not_json(
    fields: dict[str, object],
) -> None:
    """The property that lets a logging call be unable to raise.

    ``Decimal``, ``bytes``, NaN and both infinities are all in the generated set
    and none of them is representable in JSON, so this fails the moment coercion
    stops being total.
    """
    rendered = json.dumps(as_record(log_event(Severity.INFO, "a.b", "corr-1", fields), "T"))

    assert json.loads(rendered)["fields"] is not None


@given(fields=st.dictionaries(plain_names, values, max_size=6))
def test_fields_are_stored_in_one_canonical_order(fields: dict[str, object]) -> None:
    """Two events carrying the same detail must compare equal and serialise alike."""
    event = log_event(Severity.INFO, "a.b", "corr-1", fields)
    names = [name for name, _ in event.fields]

    assert names == sorted(names)
    assert len(names) == len(set(names))


@given(
    first=st.dictionaries(plain_names, st.integers(), max_size=4),
    second=st.dictionaries(plain_names, st.integers(), max_size=4),
)
def test_binding_twice_is_the_same_as_binding_the_merge(
    first: dict[str, int], second: dict[str, int]
) -> None:
    """Binding composes, and the later binding wins on a collision.

    If this did not hold, the context a record carried would depend on how many
    times a logger had been passed along rather than on what was bound to it.
    """
    base = Logger(sink=_NullSink(), correlation_id="corr-1")

    assert base.bind(**first).bind(**second).context == base.bind(**{**first, **second}).context


@given(fields=st.dictionaries(field_names, values, max_size=6))
def test_every_generated_event_round_trips_through_its_own_mapping(
    fields: dict[str, object],
) -> None:
    """``as_mapping`` and ``fields`` are two views of one thing, never two things."""
    event = log_event(Severity.INFO, "a.b", "corr-1", fields)

    assert tuple(sorted(event.as_mapping().items())) == event.fields


@given(value=st.decimals(allow_nan=False, allow_infinity=False))
def test_a_decimal_is_rendered_rather_than_refused(value: Decimal) -> None:
    """Prices are decimals from Phase 008; logging one must never raise."""
    record = as_record(log_event(Severity.INFO, "a.b", "corr-1", {"price": value}), "T")
    rendered = record["fields"]

    assert isinstance(rendered, dict)
    assert rendered["price"] == repr(value)


class _NullSink:
    """Satisfies the port and does nothing; these properties never inspect output."""

    def emit(self, event: LogEvent) -> None:
        """Discard the record."""


def test_the_sentinel_would_actually_be_found_if_it_leaked() -> None:
    """Guard the guards.

    Three properties above assert the sentinel is *absent* from a rendered
    structure. Absence is only evidence if presence would have been detected, and
    a rendering that silently dropped nested values would make all three pass
    while checking nothing.
    """
    assert SENTINEL in str(redact({"visible": {"nested": [SENTINEL]}}))


@pytest.mark.parametrize("fragment", SENSITIVE_KEY_FRAGMENTS)
def test_every_declared_fragment_actually_triggers_the_rule(fragment: str) -> None:
    """A fragment in the list that matched nothing would be documentation, not a rule."""
    assert is_sensitive(f"binance_{fragment}_value")
