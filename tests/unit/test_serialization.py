"""The cases someone thought of, for the serialization contracts.

``tests/property/test_serialization_properties.py`` searches for the laws that
must hold over every input. These are the boundaries and the refusals, where the
expected answer can be written down.

Two groups of refusal are worth naming, because both are the point of the phase
rather than defensive noise.

*Narrowing is refused, not performed.* An instant carrying microseconds, a
non-finite decimal, a float anywhere in a document — each would read back as
something other than what was written, and each raises instead.

*An unknown version is refused, not guessed.* A record written by a newer writer
cannot be understood by ignoring the parts this reader does not recognise, and
the tests below pin that it is not attempted.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from globin.adapters.serialization import JsonCodec
from globin.domain.clock import Duration, Instant, instant_from_epoch_millis
from globin.domain.identifiers import specifications
from globin.domain.precision import Rounding, increment
from globin.domain.serialization import (
    FIRST_VERSION,
    MAX_SCHEMA_NAME_LENGTH,
    RESERVED_KEYS,
    SCHEMA_KEY,
    VERSION_KEY,
    Compatibility,
    Field,
    Migration,
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
    decode_rounding,
    decode_side,
    decode_symbol,
    encode_currency,
    encode_decimal,
    encode_duration,
    encode_increment,
    encode_instant,
    encode_price,
    encode_quantity,
    encode_rounding,
    encode_side,
    encode_symbol,
    envelope,
    identifier_storage_width,
    migration_path,
    parse,
    upgrade,
)
from globin.domain.values import Side, currency, price, quantity, symbol
from globin.errors import ValidationError

SCHEMA_NAME = "globin.order.fill"


def _rename(payload: Mapping[str, object]) -> dict[str, object]:
    """A migration body: rename ``commission`` to ``fee``.

    Takes a :class:`~collections.abc.Mapping` rather than a :class:`dict`
    because a parameter type is contravariant: a step declared to need a ``dict``
    could not be handed the ``Mapping`` the chain actually carries, and mypy says
    so. The return may narrow, and does.
    """
    migrated = dict(payload)
    migrated["fee"] = migrated.pop("commission")
    return migrated


def _step(from_version: int, to_version: int, name: str = SCHEMA_NAME) -> Migration:
    """A migration that adds a marker naming the step it performed."""

    def apply(payload: Mapping[str, object]) -> dict[str, object]:
        migrated = dict(payload)
        migrated[f"at{to_version}"] = True
        return migrated

    return Migration(name, from_version, to_version, apply)


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------


def test_a_schema_renders_as_name_at_version() -> None:
    """The spelling a message uses, so a refusal names the exact revision."""
    assert str(Schema(SCHEMA_NAME, 3)) == "globin.order.fill@3"


@pytest.mark.parametrize(
    "name",
    ["Globin.Order", "globin order", "globin-order", "globin/order", "globin_order"],
)
def test_a_schema_name_outside_the_alphabet_is_refused(name: str) -> None:
    """Case, spaces and punctuation are refused: a name reaches filenames and columns."""
    with pytest.raises(ValidationError, match="outside the permitted alphabet"):
        Schema(name, FIRST_VERSION)


@pytest.mark.parametrize("name", [".globin.order", "globin.order."])
def test_a_schema_name_may_not_begin_or_end_with_a_dot(name: str) -> None:
    """Both spellings pass a character check and still name an empty segment."""
    with pytest.raises(ValidationError, match="empty segment"):
        Schema(name, FIRST_VERSION)


@pytest.mark.parametrize("name", ["ab", "x" * (MAX_SCHEMA_NAME_LENGTH + 1)])
def test_a_schema_name_outside_the_length_bounds_is_refused(name: str) -> None:
    """Too short to mean anything, or too long to sit beside the record."""
    with pytest.raises(ValidationError, match="characters"):
        Schema(name, FIRST_VERSION)


def test_a_schema_name_that_is_not_text_is_refused() -> None:
    """The guard for the call sites mypy cannot see."""
    with pytest.raises(ValidationError, match="must be a str"):
        Schema(object(), FIRST_VERSION)  # type: ignore[arg-type]


def test_version_zero_is_refused() -> None:
    """Zero reads as 'not yet versioned', which is what a version rules out."""
    with pytest.raises(ValidationError, match="at least 1"):
        Schema(SCHEMA_NAME, 0)


def test_a_boolean_version_is_refused() -> None:
    """``True`` is an ``int`` to :func:`isinstance`, and would pass as version one.

    No ``type: ignore`` here, and its absence is the point: :class:`bool`
    subclasses :class:`int`, so mypy sees nothing wrong with this call. The
    runtime guard is the only thing standing between ``True`` and version one.
    """
    with pytest.raises(ValidationError, match="a flag is not a version"):
        Schema(SCHEMA_NAME, True)


# --------------------------------------------------------------------------
# Field and compatibility
# --------------------------------------------------------------------------


def test_an_empty_field_name_is_refused() -> None:
    """A field with no key cannot be read back."""
    with pytest.raises(ValidationError, match="must not be empty"):
        Field("", required=True)


def test_a_non_boolean_requiredness_is_refused() -> None:
    """A field is either demanded by a reader or it is not; there is no third answer."""
    with pytest.raises(ValidationError, match="field required"):
        Field("amount", required="yes")  # type: ignore[arg-type]


def test_adding_an_optional_field_is_readable_both_ways() -> None:
    """The only change safe to deploy in any order."""
    before = [Field("a", required=True)]
    after = [Field("a", required=True), Field("b", required=False)]
    assert compatibility(before=before, after=after) is Compatibility.FULL


def test_adding_a_required_field_needs_the_data_migrated_first() -> None:
    """Old records lack the key, so new code cannot read them: forward only."""
    before = [Field("a", required=True)]
    after = [Field("a", required=True), Field("b", required=True)]
    assert compatibility(before=before, after=after) is Compatibility.FORWARD


def test_removing_a_required_field_needs_the_readers_deployed_first() -> None:
    """New records lack the key an old reader demands: backward only."""
    before = [Field("a", required=True), Field("b", required=True)]
    after = [Field("a", required=True)]
    assert compatibility(before=before, after=after) is Compatibility.BACKWARD


def test_replacing_a_required_field_is_readable_in_neither_direction() -> None:
    """A rename is a removal and an addition at once, and needs a migration."""
    before = [Field("commission", required=True)]
    after = [Field("fee", required=True)]
    assert compatibility(before=before, after=after) is Compatibility.NONE


def test_a_field_named_twice_in_one_version_is_refused() -> None:
    """A version has one answer per field about whether it is required."""
    with pytest.raises(ValidationError, match="twice"):
        compatibility(
            before=[Field("a", required=True), Field("a", required=False)],
            after=[],
        )


def test_compatibility_refuses_something_that_is_not_a_field() -> None:
    """Guard the checker with its failing case."""
    with pytest.raises(ValidationError, match="entry is str"):
        compatibility(before=["a"], after=[])  # type: ignore[list-item]


# --------------------------------------------------------------------------
# The envelope
# --------------------------------------------------------------------------


def test_an_envelope_carries_the_schema_and_the_payload_flat() -> None:
    """Flat rather than nested: the reserved keys are already refused."""
    document = envelope(Record(Schema(SCHEMA_NAME, 2), {"fee": "0.10"}))
    assert document == {SCHEMA_KEY: SCHEMA_NAME, VERSION_KEY: 2, "fee": "0.10"}


def test_an_envelope_is_a_fresh_mapping() -> None:
    """A caller may add to the result without reaching back into the record."""
    record = Record(Schema(SCHEMA_NAME, 1), {"fee": "0.10"})
    document = envelope(record)
    document["extra"] = True
    assert "extra" not in record.payload


@pytest.mark.parametrize("key", RESERVED_KEYS)
def test_a_payload_may_not_use_an_envelope_key(key: str) -> None:
    """A field of that name would overwrite the document's statement of what it is."""
    with pytest.raises(ValidationError, match="the envelope owns it"):
        Record(Schema(SCHEMA_NAME, 1), {key: "smuggled"})


def test_a_payload_key_that_is_not_text_is_refused() -> None:
    """JSON would render it as a string, so the document would not round-trip."""
    with pytest.raises(ValidationError, match="record payload key"):
        Record(Schema(SCHEMA_NAME, 1), {1: "a"})  # type: ignore[dict-item]


def test_parsing_returns_the_payload_without_the_envelope_keys() -> None:
    """A caller reasoning about contents never steps over the two describing them."""
    record = parse({SCHEMA_KEY: SCHEMA_NAME, VERSION_KEY: 4, "fee": "0.10"}, expecting=SCHEMA_NAME)
    assert record == Record(Schema(SCHEMA_NAME, 4), {"fee": "0.10"})


@pytest.mark.parametrize("missing", RESERVED_KEYS)
def test_a_document_missing_an_envelope_key_is_refused(missing: str) -> None:
    """Nothing in an unversioned record says what shape it is."""
    document: dict[str, object] = {SCHEMA_KEY: SCHEMA_NAME, VERSION_KEY: 1}
    del document[missing]
    with pytest.raises(ValidationError, match="is missing"):
        parse(document, expecting=SCHEMA_NAME)


def test_a_document_announcing_another_schema_is_refused() -> None:
    """Checked rather than trusted: the alternative reports a missing field later."""
    document = {SCHEMA_KEY: "globin.other.thing", VERSION_KEY: 1}
    with pytest.raises(ValidationError, match="announces schema"):
        parse(document, expecting=SCHEMA_NAME)


def test_parsing_does_not_compare_the_version_against_anything() -> None:
    """Reading the version is what lets a caller decide what to do about it."""
    assert parse({SCHEMA_KEY: SCHEMA_NAME, VERSION_KEY: 99}, expecting=SCHEMA_NAME).schema.version


# --------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------


def test_a_migration_that_skips_a_version_is_refused() -> None:
    """A skipped version stays claimed as readable and is never exercised."""
    with pytest.raises(ValidationError, match="exactly one version"):
        Migration(SCHEMA_NAME, 1, 3, _rename)


def test_a_migration_that_is_not_callable_is_refused() -> None:
    """Guard the checker with its failing case."""
    with pytest.raises(ValidationError, match="migration apply"):
        Migration(SCHEMA_NAME, 1, 2, "not a function")  # type: ignore[arg-type]


def test_an_empty_migration_set_is_a_valid_chain() -> None:
    """A schema that never changed has no migrations, and a placeholder would be a lie."""
    assert migration_path([]) == ()


def test_a_migration_chain_with_a_gap_is_refused() -> None:
    """Nothing reads version 2, so the path past it is broken."""
    with pytest.raises(ValidationError, match="has a gap"):
        migration_path([_step(1, 2), _step(3, 4)])


def test_two_migrations_reading_the_same_version_are_refused() -> None:
    """A fork has no rule saying which branch a record takes."""
    with pytest.raises(ValidationError, match="fork"):
        migration_path([_step(1, 2), _step(1, 2)])


def test_a_chain_spanning_two_schemas_is_refused() -> None:
    """Two schemas have no single version line to be contiguous along."""
    with pytest.raises(ValidationError, match="one schema"):
        migration_path([_step(1, 2), _step(2, 3, name="globin.other.thing")])


def test_migrations_are_returned_in_version_order() -> None:
    """Given in any order, read in the order a record travels."""
    ordered = migration_path([_step(3, 4), _step(1, 2), _step(2, 3)])
    assert [step.from_version for step in ordered] == [1, 2, 3]


def test_a_record_already_at_the_target_version_is_returned_unchanged() -> None:
    """No step runs, so no step can damage it."""
    record = Record(Schema(SCHEMA_NAME, 2), {"fee": "0.10"})
    assert upgrade(record, to=2, migrations=[]) is record


def test_an_older_record_is_migrated_one_step_at_a_time() -> None:
    """Every intermediate version is exercised on the way past it."""
    record = Record(Schema(SCHEMA_NAME, 1), {})
    upgraded = upgrade(record, to=4, migrations=[_step(1, 2), _step(2, 3), _step(3, 4)])
    assert upgraded.schema == Schema(SCHEMA_NAME, 4)
    assert upgraded.payload == {"at2": True, "at3": True, "at4": True}


def test_a_migration_actually_rewrites_the_payload() -> None:
    """The worked case the chain tests abstract over."""
    record = Record(Schema(SCHEMA_NAME, 1), {"commission": "0.10"})
    upgraded = upgrade(record, to=2, migrations=[Migration(SCHEMA_NAME, 1, 2, _rename)])
    assert upgraded.payload == {"fee": "0.10"}


def test_a_record_newer_than_the_reader_is_refused() -> None:
    """The plausible guess — ignore the unknown keys — drops the field that mattered."""
    record = Record(Schema(SCHEMA_NAME, 5), {})
    with pytest.raises(ValidationError, match="Upgrade the reader"):
        upgrade(record, to=2, migrations=[_step(1, 2)])


def test_an_older_record_with_no_path_forward_is_refused() -> None:
    """A missing step is reported against the version it was missing from."""
    record = Record(Schema(SCHEMA_NAME, 1), {})
    with pytest.raises(ValidationError, match="no migration takes"):
        upgrade(record, to=3, migrations=[_step(1, 2)])


def test_a_migration_for_another_schema_does_not_satisfy_the_path() -> None:
    """Steps are selected by schema name, not merely by version number."""
    record = Record(Schema(SCHEMA_NAME, 1), {})
    with pytest.raises(ValidationError, match="no migration takes"):
        upgrade(record, to=2, migrations=[_step(1, 2, name="globin.other.thing")])


def test_a_migration_returning_something_that_is_not_a_mapping_is_named() -> None:
    """Reported against itself, rather than against whichever step trips over it."""
    broken = Migration(SCHEMA_NAME, 1, 2, lambda _payload: "not a mapping")  # type: ignore[arg-type,return-value]
    record = Record(Schema(SCHEMA_NAME, 1), {})
    with pytest.raises(ValidationError, match=r"migration globin\.order\.fill 1 to 2 result"):
        upgrade(record, to=2, migrations=[broken])


# --------------------------------------------------------------------------
# Wire forms
# --------------------------------------------------------------------------


def test_a_decimal_keeps_its_trailing_zeros() -> None:
    """The exponent is information: it is the venue's statement of its precision."""
    assert encode_decimal(Decimal("0.10")) == "0.10"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_decimal_is_refused(value: str) -> None:
    """JSON has no spelling for it, so it could not be read back as what it is."""
    with pytest.raises(ValidationError, match="non-finite"):
        encode_decimal(Decimal(value))


@pytest.mark.parametrize("text", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_decimal_is_refused_on_the_way_in_too(text: str) -> None:
    """A document from somewhere else is exactly where a permissive reader hurts."""
    with pytest.raises(ValidationError, match="non-finite"):
        decode_decimal(text)


def test_text_that_is_not_a_decimal_is_refused() -> None:
    """:class:`~decimal.InvalidOperation` is translated, as ADR-0022 requires."""
    with pytest.raises(ValidationError, match="cannot read 'twelve' as a decimal"):
        decode_decimal("twelve")


def test_encoding_a_float_as_a_decimal_is_refused() -> None:
    """Guard the checker with its failing case."""
    with pytest.raises(ValidationError, match="encode_decimal"):
        encode_decimal(1.5)  # type: ignore[arg-type]


def test_an_instant_with_sub_millisecond_precision_is_refused() -> None:
    """The phase's central claim: a stored value reads back as what was written."""
    moment = Instant(datetime(2026, 8, 15, 12, 0, 0, 123_456, tzinfo=UTC))
    with pytest.raises(ValidationError, match="carries 123456 microseconds"):
        encode_instant(moment)


def test_the_refusal_names_the_projection_that_would_have_floored_it() -> None:
    """A caller who wanted the floor is told how to ask for it."""
    moment = Instant(datetime(2026, 8, 15, 12, 0, 0, 1, tzinfo=UTC))
    with pytest.raises(ValidationError, match="epoch_millis"):
        encode_instant(moment)


def test_a_whole_millisecond_instant_encodes_exactly() -> None:
    """No flooring happens, because there is nothing to floor."""
    assert encode_instant(instant_from_epoch_millis(1_700_000_000_123)) == 1_700_000_000_123


def test_an_instant_outside_the_representable_range_is_refused_on_the_way_back() -> None:
    """The bound belongs to :mod:`globin.domain.clock` and is not restated here."""
    with pytest.raises(ValidationError, match="outside the range"):
        decode_instant(253_402_300_800_000)


def test_a_duration_is_stored_in_the_unit_it_holds() -> None:
    """Nanoseconds, because converting to milliseconds would lose what it already has."""
    assert encode_duration(Duration(1_234_567)) == 1_234_567
    assert decode_duration(1_234_567) == Duration(1_234_567)


def test_a_symbol_is_stored_separated_rather_than_concatenated() -> None:
    """Nothing in ``BTCUSDT`` says where the base ends."""
    assert encode_symbol(symbol("BTC", "USDT")) == "BTC/USDT"


@pytest.mark.parametrize("text", ["BTCUSDT", "BTC/USDT/EUR", "BTC/"])
def test_a_symbol_without_exactly_one_separator_is_refused(text: str) -> None:
    """Zero, two, or one with nothing after it are all unreadable."""
    with pytest.raises(ValidationError):
        decode_symbol(text)


def test_a_quantity_is_stored_as_two_fields() -> None:
    """A denomination recovered by splitting text is one bad delimiter from confusion."""
    assert encode_quantity(quantity(Decimal("1.5"), "BTC")) == {
        "amount": "1.5",
        "currency": "BTC",
    }


def test_a_quantity_missing_a_field_names_what_is_missing() -> None:
    """Guard the checker with its failing case."""
    with pytest.raises(ValidationError, match="quantity is missing currency"):
        decode_quantity({"amount": "1.5"})


def test_a_price_missing_a_field_names_what_is_missing() -> None:
    """Guard the checker with its failing case."""
    with pytest.raises(ValidationError, match="price is missing symbol"):
        decode_price({"amount": "30000"})


def test_an_unknown_enumeration_member_lists_the_permitted_ones() -> None:
    """A reader needs to know which set it is comparing against."""
    with pytest.raises(ValidationError, match="expected one of BUY, SELL"):
        decode_side("HOLD")


def test_a_rounding_mode_round_trips() -> None:
    """A stored result is reproducible only alongside the mode that produced it."""
    assert decode_rounding(encode_rounding(Rounding.HALF_EVEN)) is Rounding.HALF_EVEN


def test_a_currency_round_trips() -> None:
    """The simplest wire form there is, and still worth pinning."""
    assert decode_currency(encode_currency(currency("USDT"))) == currency("USDT")


def test_an_increment_keeps_the_precision_the_venue_stated() -> None:
    """``0.10`` and ``0.1`` are the same number and different statements."""
    grid = increment(Decimal("0.010"))
    assert encode_increment(grid) == "0.010"
    assert decode_increment("0.010").step.as_tuple() == grid.step.as_tuple()


def test_a_side_round_trips() -> None:
    """The member value is stored, not the Python identifier naming it."""
    assert encode_side(Side.SELL) == "SELL"
    assert decode_side(encode_side(Side.BUY)) is Side.BUY


def test_a_price_round_trips_through_its_mapping() -> None:
    """The composite case, end to end."""
    original = price(Decimal("30000.00"), symbol("BTC", "USDT"))
    assert decode_price(encode_price(original)) == original


def test_encoders_refuse_a_value_of_the_wrong_type() -> None:
    """One representative of the guard every encoder carries."""
    with pytest.raises(ValidationError, match="encode_price\\(\\) value is str"):
        encode_price("not a price")  # type: ignore[arg-type]


def test_the_identifier_column_width_is_derived_from_the_registry() -> None:
    """Registering a longer kind moves this number; a literal would have to be remembered."""
    assert identifier_storage_width() == max(spec.max_length for spec in specifications())


# --------------------------------------------------------------------------
# The JSON codec
# --------------------------------------------------------------------------


def test_the_codec_sorts_keys_so_two_runs_produce_the_same_text() -> None:
    """Determinism is what lets a digest over the result mean anything."""
    assert JsonCodec().encode({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_the_codec_adds_no_trailing_newline() -> None:
    """Whoever writes the file decides the terminator."""
    assert not JsonCodec().encode({"a": 1}).endswith("\n")


def test_the_codec_refuses_a_float_anywhere_in_the_document() -> None:
    """JSON would take it happily, which is exactly why the walk exists."""
    with pytest.raises(ValidationError, match=r"document\.a\.b\[1\] holds the float"):
        JsonCodec().encode({"a": {"b": [1, 2.5]}})


def test_the_codec_refuses_a_key_that_is_not_text() -> None:
    """``json.dumps`` would coerce it silently and break the round trip."""
    with pytest.raises(ValidationError, match="would render it as a string"):
        JsonCodec().encode({"a": {1: "b"}})


def test_the_codec_refuses_a_value_it_cannot_render() -> None:
    """A type JSON has no form for is reported rather than escaping as TypeError."""
    with pytest.raises(ValidationError, match="cannot be rendered as JSON"):
        JsonCodec().encode({"a": object()})


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_the_codec_refuses_the_bare_words_python_would_have_accepted(literal: str) -> None:
    """RFC 8259 defines none of them, so the file would be readable by little else."""
    with pytest.raises(ValidationError, match="which is not JSON"):
        JsonCodec().decode(f'{{"a":{literal}}}')


def test_the_codec_refuses_a_fractional_number_on_the_way_in() -> None:
    """A float in a stored record means somebody bypassed ``encode_decimal``."""
    with pytest.raises(ValidationError, match=r"JSON number 1\.5"):
        JsonCodec().decode('{"a":1.5}')


def test_the_codec_reads_integers_unchanged() -> None:
    """A version, a count and an epoch millisecond are integers and are unaffected."""
    assert JsonCodec().decode('{"a":1700000000123}') == {"a": 1700000000123}


def test_the_codec_refuses_a_document_that_is_not_an_object() -> None:
    """Every GLOBIN record carries its schema and version at the top level."""
    with pytest.raises(ValidationError, match="must be a JSON object"):
        JsonCodec().decode("[1, 2]")


def test_the_codec_refuses_malformed_text() -> None:
    """Guard the checker with its failing case."""
    with pytest.raises(ValidationError, match="not valid JSON"):
        JsonCodec().decode("{oops")


def test_the_codec_refuses_bytes_rather_than_guessing_an_encoding() -> None:
    """Whoever opened the file knows which encoding it used."""
    with pytest.raises(ValidationError, match="decode\\(\\) needs a str"):
        JsonCodec().decode(b'{"a":1}')  # type: ignore[arg-type]


def test_the_codec_keeps_booleans_as_booleans() -> None:
    """A JSON literal that reads back as itself is not the float problem."""
    assert JsonCodec().decode(JsonCodec().encode({"a": True})) == {"a": True}
