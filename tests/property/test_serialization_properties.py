"""The laws serialization obeys, over generated values rather than examples.

``tests/unit/test_serialization.py`` checks the cases someone thought of. These
check the claims that must hold for *every* input, and four are the reason a
later phase can persist a value without re-deriving whether it is safe to:

* **Round-trip identity, for every wire form.** ``decode(encode(x)) == x`` is the
  whole contract, and it is the property that a narrowing encoder breaks. Testing
  it per type rather than once over a union is deliberate: a union would hide
  which member failed.
* **Rendering is order-independent.** The same document built by inserting its
  keys in a different order renders to the same text, which is what makes a
  digest over stored bytes mean anything — ``ENGINEERING_CONTRACT.md`` invariant 3.
* **Compatibility is a duality, not two unrelated answers.** A change that is
  backward compatible one way round is forward compatible the other way round,
  for every pair of field sets. That law is what stops the classification
  becoming two hand-written branches that drift apart.
* **A record newer than its reader is refused, always.** Not for the versions
  someone thought to write down — for every pair where the record leads.

Deliberately absent: a property over the four :class:`~globin.domain.precision.Rounding`
members or the two :class:`~globin.domain.values.Side` members. Those are spaces
of four and two, which ``test_values_properties.py`` and ADR-0023 both call a
slow unit test rather than a search.
"""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from globin.adapters.serialization import JsonCodec
from globin.domain.clock import (
    MAX_EPOCH_MILLIS,
    MIN_EPOCH_MILLIS,
    Duration,
    Instant,
    instant_from_epoch_millis,
)
from globin.domain.precision import Increment, increment
from globin.domain.serialization import (
    MAX_SCHEMA_NAME_LENGTH,
    MIN_SCHEMA_NAME_LENGTH,
    SCHEMA_NAME_ALPHABET,
    Compatibility,
    Field,
    Record,
    Schema,
    compatibility,
    decode_currency,
    decode_decimal,
    decode_duration,
    decode_increment,
    decode_instant,
    decode_price,
    decode_quantity,
    decode_symbol,
    encode_currency,
    encode_decimal,
    encode_duration,
    encode_increment,
    encode_instant,
    encode_price,
    encode_quantity,
    encode_symbol,
    envelope,
    parse,
    upgrade,
)
from globin.domain.values import (
    CURRENCY_ALPHABET,
    MAX_CURRENCY_CODE_LENGTH,
    MIN_CURRENCY_CODE_LENGTH,
    Symbol,
    currency,
    price,
    quantity,
    symbol,
)
from globin.errors import ValidationError

codes = st.text(
    alphabet=CURRENCY_ALPHABET, min_size=MIN_CURRENCY_CODE_LENGTH, max_size=MAX_CURRENCY_CODE_LENGTH
)

#: Bounded well inside the published limits, for the reason
#: ``test_values_properties.py`` gives: the boundaries are unit tests, where the
#: expected answer can be written down.
amounts = st.decimals(
    min_value=Decimal(0),
    max_value=Decimal("1E+12"),
    allow_nan=False,
    allow_infinity=False,
    places=8,
).filter(lambda value: not value.is_signed())

positive_amounts = amounts.filter(lambda value: value != 0)

#: The same set ``test_precision_properties.py`` samples: coarse enough to be
#: realistic, and including one step whose trailing zeros are load-bearing.
increments = st.sampled_from(["0.01", "0.001", "0.5", "1", "25", "0.00010000", "2.5", "1E+3"]).map(
    increment
)

#: An asset is not a market against itself, so the two halves must differ.
symbols = (
    st.tuples(codes, codes)
    .filter(lambda pair: pair[0] != pair[1])
    .map(lambda pair: symbol(pair[0], pair[1]))
)

#: Every instant the projection can carry, including both ends and the far side
#: of the epoch, where flooring changes direction under a naive implementation.
instants = st.integers(min_value=MIN_EPOCH_MILLIS, max_value=MAX_EPOCH_MILLIS).map(
    instant_from_epoch_millis
)

#: Any finite decimal, not merely the ones a magnitude admits. ``encode_decimal``
#: is the primitive every other wire form is built from, so its round trip has to
#: hold over more than the subset ``Price`` and ``Quantity`` accept.
finite_decimals = st.decimals(allow_nan=False, allow_infinity=False)

schema_names = st.text(
    alphabet=SCHEMA_NAME_ALPHABET,
    min_size=MIN_SCHEMA_NAME_LENGTH,
    max_size=MAX_SCHEMA_NAME_LENGTH,
).filter(lambda name: not name.startswith(".") and not name.endswith("."))

versions = st.integers(min_value=1, max_value=64)

#: Values a document may hold. No float: the codec refuses one in either
#: direction, which ``test_serialization.py`` pins as a unit case.
json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(), children, max_size=4)
    ),
    max_leaves=8,
)

documents = st.dictionaries(st.text(), json_values, max_size=6)

field_sets = st.lists(
    st.builds(Field, name=st.text(min_size=1, max_size=4), required=st.booleans()),
    max_size=5,
).filter(lambda fields: len({field.name for field in fields}) == len(fields))


@given(value=finite_decimals)
def test_every_finite_decimal_survives_being_written_down(value: Decimal) -> None:
    """The primitive every other magnitude wire form is built from.

    Equality is compared with ``compare_total`` rather than ``==`` because the
    two disagree on exactly the thing this phase cares about: ``Decimal('0.10')``
    equals ``Decimal('0.1')`` numerically and is a different statement of
    precision, and the exponent is what
    :class:`~globin.domain.precision.Increment` documents as the venue's own.
    """
    assert decode_decimal(encode_decimal(value)).compare_total(value) == 0


@given(moment=instants)
def test_every_representable_instant_survives_being_written_down(moment: Instant) -> None:
    """Total across the whole range, including before the epoch."""
    assert decode_instant(encode_instant(moment)) == moment


@given(nanoseconds=st.integers(min_value=0, max_value=2**63))
def test_every_duration_survives_being_written_down(nanoseconds: int) -> None:
    """Nanoseconds in, nanoseconds out, with no unit conversion to lose."""
    length = Duration(nanoseconds)
    assert decode_duration(encode_duration(length)) == length


@given(code=codes)
def test_every_currency_survives_being_written_down(code: str) -> None:
    """Every code the alphabet admits, not merely the ones a venue lists."""
    asset = currency(code)
    assert decode_currency(encode_currency(asset)) == asset


@given(market=symbols)
def test_every_symbol_survives_being_written_down(market: Symbol) -> None:
    """The separated spelling is unambiguous, which is why it is the stored one."""
    assert decode_symbol(encode_symbol(market)) == market


@given(amount=amounts, code=codes)
def test_every_quantity_survives_being_written_down(amount: Decimal, code: str) -> None:
    """Amount and denomination both, which is why they are two fields."""
    held = quantity(amount, code)
    assert decode_quantity(encode_quantity(held)) == held


@given(amount=positive_amounts, market=symbols)
def test_every_price_survives_being_written_down(amount: Decimal, market: Symbol) -> None:
    """A price refuses zero, so the strategy does too."""
    quoted = price(amount, market)
    assert decode_price(encode_price(quoted)) == quoted


@given(grid=increments)
def test_every_increment_survives_being_written_down(grid: Increment) -> None:
    """Including its trailing zeros, which are the precision the venue stated.

    ``0.00010000`` is in the sampled set for exactly that reason: it is the
    example where a renderer that normalised would still pass every other case
    here.
    """
    assert decode_increment(encode_increment(grid)) == grid


@given(name=schema_names, version=versions, payload=documents)
def test_every_record_survives_its_envelope(
    name: str, version: int, payload: dict[str, object]
) -> None:
    """Wrapping and unwrapping is the identity, for every schema and payload.

    Reserved keys are dropped from the generated payload rather than filtered
    out of the strategy: a payload carrying one is refused at construction, which
    ``test_serialization.py`` already pins, and filtering here would spend most
    examples regenerating the same thing.
    """
    clean = {
        key: value for key, value in payload.items() if key not in {"schema", "schema_version"}
    }
    record = Record(Schema(name, version), clean)
    assert parse(envelope(record), expecting=name) == record


@given(document=documents)
def test_every_document_survives_the_codec(document: dict[str, object]) -> None:
    """Text in, the same document out — including non-ASCII keys, which are escaped."""
    codec = JsonCodec()
    assert codec.decode(codec.encode(document)) == document


@given(document=documents)
def test_rendering_does_not_depend_on_the_order_the_keys_were_inserted(
    document: dict[str, object],
) -> None:
    """What makes a digest over stored bytes mean anything.

    The reversed copy holds the same pairs and was built by a different sequence
    of insertions, so a renderer that walked insertion order would disagree here
    and nowhere else.
    """
    codec = JsonCodec()
    reversed_copy = dict(reversed(list(document.items())))
    assert codec.encode(reversed_copy) == codec.encode(document)


@given(before=field_sets, after=field_sets)
def test_compatibility_is_a_duality(before: list[Field], after: list[Field]) -> None:
    """Backward one way round is forward the other way round, always.

    This is the law that keeps the classification honest. Two hand-written
    branches would satisfy the examples someone wrote and drift apart on the
    pairs nobody did.
    """
    forwards = compatibility(before=before, after=after)
    backwards = compatibility(before=after, after=before)
    mirrored = {
        Compatibility.FULL: Compatibility.FULL,
        Compatibility.NONE: Compatibility.NONE,
        Compatibility.BACKWARD: Compatibility.FORWARD,
        Compatibility.FORWARD: Compatibility.BACKWARD,
    }
    assert backwards is mirrored[forwards]


@given(fields=field_sets)
def test_a_schema_is_fully_compatible_with_itself(fields: list[Field]) -> None:
    """A version nobody changed is readable in both directions, by definition."""
    assert compatibility(before=fields, after=fields) is Compatibility.FULL


@given(name=schema_names, reader=versions, ahead=st.integers(min_value=1, max_value=16))
def test_a_record_ahead_of_its_reader_is_always_refused(name: str, reader: int, ahead: int) -> None:
    """For every pair where the record leads, not merely the ones written down.

    No migrations are offered, and none would help: the refusal is about the
    direction, and there is no such thing as a step backwards here.
    """
    record = Record(Schema(name, reader + ahead), {})
    with pytest.raises(ValidationError, match="Upgrade the reader"):
        upgrade(record, to=reader, migrations=[])


@given(name=schema_names, version=versions, payload=documents)
def test_upgrading_to_the_version_a_record_already_has_changes_nothing(
    name: str, version: int, payload: dict[str, object]
) -> None:
    """No step runs, so no step can damage it — whatever the payload holds."""
    clean = {
        key: value for key, value in payload.items() if key not in {"schema", "schema_version"}
    }
    record = Record(Schema(name, version), clean)
    assert upgrade(record, to=version, migrations=[]) is record
