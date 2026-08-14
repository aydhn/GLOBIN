"""One order-shaped calculation, from raw quotes to a charge.

The unit tests check each operation alone and the property tests check the laws.
This checks that they compose: an unaligned price and an unaligned size arrive,
both are put onto their venue's grids, a notional is computed, a fee is reserved,
and the balance is reduced — with every intermediate exact and every rounding
named.

Nothing here reaches a venue. The tick, the step and the fee rate are written
down as literals because Phases 049-050 own where they really come from, and this
phase owns only what is done with them once they arrive.
"""

from decimal import Decimal, localcontext

import pytest

from globin.domain.precision import Rounding, increment, is_aligned, multiply
from globin.domain.values import (
    Currency,
    Symbol,
    align_price,
    align_quantity,
    notional,
    price,
    quantity,
)
from globin.errors import ValidationError

BTC_USDT = Symbol(base=Currency(code="BTC"), quote=Currency(code="USDT"))

#: Shaped like a venue's filters, and deliberately not read from one. A real tick
#: size arrives with the instrument registry in Phases 049-050.
TICK = increment("0.01")
STEP = increment("0.00001000")
FEE_RATE = Decimal("0.001")


def test_an_order_is_priced_sized_and_charged_without_a_single_silent_rounding() -> None:
    """The whole phase, exercised as one calculation.

    Each step names its own rounding direction, and the directions differ on
    purpose: the price and the size floor, so the order never asks for more than
    the venue allows, while the fee ceilings, so the reservation is never short.
    That asymmetry is the reason a single default rounding mode would be wrong.
    """
    quoted = price("60123.4567", BTC_USDT)
    wanted = quantity("0.123456789", "BTC")

    tradable_price = align_price(quoted, tick=TICK, rounding=Rounding.FLOOR)
    tradable_size = align_quantity(wanted, step=STEP, rounding=Rounding.FLOOR)

    assert tradable_price == price("60123.45", BTC_USDT)
    assert tradable_size == quantity("0.12345000", "BTC")

    value = notional(tradable_price, tradable_size)
    assert value == quantity("7422.2399025000", "USDT")

    # `multiply`, not `*`. A raw operator here would read the thread-local
    # context and could round the fee — in the one test whose subject is that
    # nothing rounds silently.
    fee = align_quantity(
        quantity(multiply(value.amount, FEE_RATE), "USDT"),
        step=increment("0.01"),
        rounding=Rounding.CEILING,
    )
    assert fee == quantity("7.43", "USDT")

    reserved = value + fee
    assert reserved == quantity("7429.6699025000", "USDT")


def test_the_aligned_values_are_the_ones_a_venue_would_accept() -> None:
    """Alignment is checked by the question form as well as by the value.

    A venue rejects an order whose price is off-tick, so "did this land on the
    grid" is the property that matters operationally, not "did it equal the
    number I expected".
    """
    tradable = align_price(price("60123.4567", BTC_USDT), tick=TICK, rounding=Rounding.FLOOR)
    size = align_quantity(quantity("0.123456789", "BTC"), step=STEP, rounding=Rounding.FLOOR)
    assert is_aligned(tradable.amount, to=TICK)
    assert is_aligned(size.amount, to=STEP)


def test_the_whole_calculation_is_unchanged_by_a_hostile_ambient_context() -> None:
    """The composed path inherits the guarantee each step gives individually.

    A single operation reading the thread-local context would show up here as a
    different final answer, which is the failure mode that would otherwise only
    appear in production on a thread somebody else configured.
    """

    def calculate() -> object:
        tradable = align_price(price("60123.4567", BTC_USDT), tick=TICK, rounding=Rounding.FLOOR)
        size = align_quantity(quantity("0.123456789", "BTC"), step=STEP, rounding=Rounding.FLOOR)
        return notional(tradable, size)

    expected = calculate()
    with localcontext() as hostile:
        hostile.prec = 3
        hostile.rounding = "ROUND_UP"
        assert calculate() == expected


def test_a_size_that_rounds_away_to_nothing_says_so_rather_than_trading() -> None:
    """The end of the calculation a caller most needs told about.

    Flooring a size below one step gives zero, which is a legitimate quantity and
    a useless order. It is reported as a value rather than an exception, because
    the caller — not this layer — decides whether zero is an error.
    """
    dust = align_quantity(quantity("0.000001", "BTC"), step=STEP, rounding=Rounding.FLOOR)
    assert dust == quantity("0", "BTC")
    assert notional(price("60000", BTC_USDT), dust) == quantity("0", "USDT")


def test_spending_more_than_is_held_is_refused_by_the_types() -> None:
    """The balance check that needs no separate balance check."""
    held = quantity("100", "USDT")
    cost = notional(price("60000", BTC_USDT), quantity("0.01", "BTC"))
    with pytest.raises(ValidationError, match="never negative"):
        held - cost
