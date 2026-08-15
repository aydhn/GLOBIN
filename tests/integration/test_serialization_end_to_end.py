"""A record from domain values to stored text and back, through the real wiring.

``tests/unit`` checks each piece and ``tests/property`` checks the laws. This
checks that the pieces compose: the codec the composition root builds, the
envelope the domain defines, and the wire forms in between, exercised as a caller
in a later phase would exercise them.

Nothing here writes a file. Storage belongs to the phases that own somewhere to
put a record — 159 for backtest results, 190 for models, 266 for orchestration
state — and this level is "several components together, still entirely local"
rather than "several components and a disk".
"""

from decimal import Decimal

import pytest

from globin.domain.clock import instant_from_epoch_millis
from globin.domain.precision import Rounding, increment
from globin.domain.serialization import (
    Migration,
    Record,
    Schema,
    decode_increment,
    decode_instant,
    decode_price,
    decode_quantity,
    decode_rounding,
    decode_side,
    encode_increment,
    encode_instant,
    encode_price,
    encode_quantity,
    encode_rounding,
    encode_side,
    envelope,
    parse,
    upgrade,
)
from globin.domain.values import Side, price, quantity, symbol
from globin.errors import ValidationError
from globin.runtime.composition import build_codec

SCHEMA_NAME = "globin.order.fill"


def _fill() -> Record:
    """A plausible record, using every wire form a fill would need.

    Returns:
        The record at version 1.

    Deliberately not a fixture. It is used by one test as data and by another as
    the *input* to a migration, and a fixture would hide that the second test
    starts from the same shape the first proved.
    """
    market = symbol("BTC", "USDT")
    return Record(
        Schema(SCHEMA_NAME, 1),
        {
            "at": encode_instant(instant_from_epoch_millis(1_700_000_000_123)),
            "side": encode_side(Side.BUY),
            "price": encode_price(price(Decimal("30000.00"), market)),
            "filled": encode_quantity(quantity(Decimal("0.50000000"), "BTC")),
            "tick": encode_increment(increment(Decimal("0.01"))),
            "rounding": encode_rounding(Rounding.FLOOR),
        },
    )


def test_a_record_survives_the_whole_round_trip() -> None:
    """Domain values out, stored text, and the same domain values back."""
    codec = build_codec()
    original = _fill()

    text = codec.encode(envelope(original))
    restored = parse(codec.decode(text), expecting=SCHEMA_NAME)

    assert restored == original
    assert decode_instant(restored.payload["at"]) == instant_from_epoch_millis(1_700_000_000_123)  # type: ignore[arg-type]
    assert decode_side(restored.payload["side"]) is Side.BUY  # type: ignore[arg-type]
    assert decode_price(restored.payload["price"]) == price(  # type: ignore[arg-type]
        Decimal("30000.00"), symbol("BTC", "USDT")
    )
    assert decode_quantity(restored.payload["filled"]) == quantity(  # type: ignore[arg-type]
        Decimal("0.50000000"), "BTC"
    )
    assert decode_rounding(restored.payload["rounding"]) is Rounding.FLOOR  # type: ignore[arg-type]


def test_the_stored_text_carries_the_precision_the_venue_stated() -> None:
    """The trailing zeros reach the bytes, not merely the objects in memory.

    ``0.50000000`` and ``0.5`` are the same quantity and different statements
    about how finely it was measured. A renderer that normalised would pass every
    equality assertion above and still lose this.
    """
    text = build_codec().encode(envelope(_fill()))
    assert '"0.50000000"' in text
    assert '"30000.00"' in text
    assert decode_increment("0.01").step == increment(Decimal("0.01")).step


def test_the_same_record_renders_to_the_same_text_every_time() -> None:
    """Determinism across separately built codecs, which is what a digest needs."""
    document = envelope(_fill())
    assert build_codec().encode(document) == build_codec().encode(document)


def test_a_stored_record_can_be_migrated_after_it_was_written() -> None:
    """The case the phase exists for: code moved on, the record did not.

    Version 1 spelled the field ``filled``; version 2 spells it ``quantity``. The
    record on disk is untouched, and the reader brings it forward on the way in.
    """

    def rename(payload: object) -> dict[str, object]:
        assert isinstance(payload, dict)
        migrated = dict(payload)
        migrated["quantity"] = migrated.pop("filled")
        return migrated

    codec = build_codec()
    stored = codec.encode(envelope(_fill()))

    read = parse(codec.decode(stored), expecting=SCHEMA_NAME)
    current = upgrade(read, to=2, migrations=[Migration(SCHEMA_NAME, 1, 2, rename)])

    assert current.schema == Schema(SCHEMA_NAME, 2)
    assert "filled" not in current.payload
    assert decode_quantity(current.payload["quantity"]) == quantity(  # type: ignore[arg-type]
        Decimal("0.50000000"), "BTC"
    )


def test_a_record_written_by_a_newer_writer_is_refused_at_the_boundary() -> None:
    """The whole point of the version, exercised where a reader would meet it.

    A reader implementing version 1 is handed a version 2 record. It refuses
    rather than reading the fields it happens to recognise, because the field it
    does not recognise is the one the newer writer added on purpose.
    """
    codec = build_codec()
    ahead = Record(Schema(SCHEMA_NAME, 2), {"quantity": {"amount": "0.5", "currency": "BTC"}})
    stored = codec.encode(envelope(ahead))

    read = parse(codec.decode(stored), expecting=SCHEMA_NAME)
    with pytest.raises(ValidationError, match="Upgrade the reader"):
        upgrade(read, to=1, migrations=[])


def test_a_corrupted_record_is_refused_rather_than_half_read() -> None:
    """A truncated file is a detectable fault, and stays one."""
    codec = build_codec()
    stored = codec.encode(envelope(_fill()))
    with pytest.raises(ValidationError, match="not valid JSON"):
        codec.decode(stored[: len(stored) // 2])
