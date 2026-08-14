"""The value types: what each refuses, and what the operators do.

Three things are checked here, and the split matters. *Construction* is tested
for every way it refuses, because a value type that admits a bad value has
already failed. *Comparison* is tested for the three outcomes it can have —
answer, ``ValidationError``, ``TypeError`` — since the whole point of the phase
is that the third and second are different situations. *Absence* is tested too:
there are assertions that arithmetic does **not** work, because the operators
this module declines to define are as much a part of its contract as the ones it
defines, and nothing else would notice them appearing.

Whether the laws hold over generated values rather than examples is
``tests/property/test_values_properties.py``; whether the policy document still
describes this code is ``tests/contract/test_values_contract.py``.
"""

import operator
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any, Final

import pytest

from globin.domain.values import (
    CURRENCY_ALPHABET,
    MAX_ADJUSTED_EXPONENT,
    MAX_CURRENCY_CODE_LENGTH,
    MAX_SIGNIFICANT_DIGITS,
    MIN_CURRENCY_CODE_LENGTH,
    SYMBOL_SEPARATOR,
    Currency,
    Quantity,
    Side,
    Symbol,
    currency,
    price,
    quantity,
    symbol,
)
from globin.errors import ValidationError

#: The four comparison operators, as callables, so that a test asserting
#: something about "ordering" does not have to be written four times.
ORDERINGS: Final[tuple[Callable[[Any, Any], Any], ...]] = (
    operator.lt,
    operator.le,
    operator.gt,
    operator.ge,
)

BTC_USDT: Final[Symbol] = Symbol(base=Currency(code="BTC"), quote=Currency(code="USDT"))
ETH_USDT: Final[Symbol] = Symbol(base=Currency(code="ETH"), quote=Currency(code="USDT"))


# --------------------------------------------------------------------------
# Side
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("side", "expected"), [(Side.BUY, Side.SELL), (Side.SELL, Side.BUY)])
def test_every_side_has_the_other_as_its_opposite(side: Side, expected: Side) -> None:
    assert side.opposite is expected


def test_the_opposite_of_the_opposite_is_the_original() -> None:
    """Written as a unit test rather than a property: the domain has two members."""
    for side in Side:
        assert side.opposite.opposite is side


# --------------------------------------------------------------------------
# Currency
# --------------------------------------------------------------------------


def test_a_currency_keeps_the_code_it_was_given() -> None:
    assert currency("USDT").code == "USDT"
    assert str(currency("USDT")) == "USDT"


@pytest.mark.parametrize("code", ["", "B", "X" * (MAX_CURRENCY_CODE_LENGTH + 1)])
def test_a_currency_code_outside_the_length_bounds_is_refused(code: str) -> None:
    with pytest.raises(ValidationError, match="characters; expected between"):
        currency(code)


@pytest.mark.parametrize("code", ["btc", "BT-C", "BT C", "BTC.", "BTÇ"])
def test_a_currency_code_spelled_outside_the_alphabet_is_refused(code: str) -> None:
    with pytest.raises(ValidationError, match="uppercase letters and digits"):
        currency(code)


def test_a_currency_code_may_contain_digits() -> None:
    """Real tickers do — refusing them would be a rule about spelling, not shape."""
    assert currency("1INCH").code == "1INCH"


def test_a_well_formed_code_no_venue_lists_is_still_a_currency() -> None:
    """The absence of a registry, asserted as behaviour.

    Phase 011 owns canonical identifiers and Phases 033-048 own what a venue
    actually lists. If somebody adds a set of known codes to the domain layer,
    this fails — which is the only way the absence of a thing can be enforced.
    """
    assert currency("ZZZQ").code == "ZZZQ"


def test_the_length_bounds_are_the_ones_the_module_publishes() -> None:
    assert currency("X" * MIN_CURRENCY_CODE_LENGTH).code == "X" * MIN_CURRENCY_CODE_LENGTH
    assert currency("X" * MAX_CURRENCY_CODE_LENGTH).code == "X" * MAX_CURRENCY_CODE_LENGTH


def test_a_currency_is_not_a_string() -> None:
    """A `str` subclass would pass anywhere a string is wanted, which is the bug.

    The comparison goes through an `object` because mypy otherwise reports it as a
    check that can never succeed — which is the guarantee, stated by the type
    checker instead of by the test. This asserts it also holds at runtime.
    """
    held: object = currency("BTC")
    assert not isinstance(held, str)
    assert held != "BTC"


# --------------------------------------------------------------------------
# Symbol
# --------------------------------------------------------------------------


def test_a_symbol_is_built_from_codes_or_from_currencies() -> None:
    assert symbol("BTC", "USDT") == symbol(Currency(code="BTC"), Currency(code="USDT"))


def test_a_symbol_renders_with_a_separator_no_venue_would_accept() -> None:
    """The separator is what stops `str` being mistaken for a wire format."""
    assert str(symbol("BTC", "USDT")) == f"BTC{SYMBOL_SEPARATOR}USDT"


def test_a_symbol_of_one_asset_against_itself_is_refused() -> None:
    with pytest.raises(ValidationError, match="not a market against itself"):
        symbol("BTC", "BTC")


@pytest.mark.parametrize("half", ["base", "quote"])
def test_a_symbol_half_that_is_not_a_currency_is_refused(half: str) -> None:
    """Constructed directly, because the factory converts a string rather than refusing."""
    halves: dict[str, object] = {"base": Currency(code="BTC"), "quote": Currency(code="USDT")}
    halves[half] = "USDT"
    with pytest.raises(ValidationError, match=f"symbol {half} is str"):
        Symbol(**halves)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Reading an amount
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("1.5", Decimal("1.5")),
        ("1E+3", Decimal("1E+3")),
        ("+2", Decimal(2)),
        (7, Decimal(7)),
        (Decimal("0.125"), Decimal("0.125")),
    ],
)
def test_an_amount_is_read_exactly_from_what_the_caller_wrote(
    given: Decimal | int | str, expected: Decimal
) -> None:
    assert quantity(given, "BTC").amount == expected


def test_an_amount_given_as_a_float_is_refused_and_says_what_to_write_instead() -> None:
    """Invariant 17 enforced rather than stated.

    The message carries the exact expansion, because `Decimal(1.1)` being fifty-two
    digits long is the fact that makes the refusal obviously right rather than
    obviously pedantic.
    """
    with pytest.raises(ValidationError, match="is float; expected"):
        quantity(1.1, "BTC")  # type: ignore[arg-type]


def test_an_amount_given_as_a_bool_is_refused() -> None:
    """`isinstance(True, int)` is true, so the bool guard has to come first.

    No `type: ignore` here, and that is the point: `bool` *is* an `int` to the type
    checker, so this call passes mypy. Only the runtime guard catches it.
    """
    with pytest.raises(ValidationError, match="is bool; expected"):
        quantity(True, "BTC")


def test_an_amount_of_an_unreadable_type_is_refused() -> None:
    with pytest.raises(ValidationError, match="is NoneType; expected"):
        quantity(None, "BTC")  # type: ignore[arg-type]


@pytest.mark.parametrize("text", ["NaN", "Infinity", "-Inf", " 1 ", "1_000", "0x10", "1,5"])
def test_an_amount_spelled_outside_the_decimal_alphabet_is_refused(text: str) -> None:
    """`Decimal` would read four of these. That it would is the reason for the guard."""
    with pytest.raises(ValidationError, match="write digits, an optional sign"):
        quantity(text, "BTC")


def test_an_amount_spelled_from_the_alphabet_but_still_not_a_number_is_refused() -> None:
    with pytest.raises(ValidationError, match="is not a number"):
        quantity("1.2.3", "BTC")


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity")])
def test_a_non_finite_decimal_handed_in_directly_is_refused(value: Decimal) -> None:
    """The alphabet cannot see this one: the caller already had a `Decimal`.

    It matters more than it looks. `Decimal('NaN') == Decimal('NaN')` is false and
    ordering one raises `InvalidOperation` — a `decimal` exception escaping from a
    comparison, which ADR-0022 does not permit.
    """
    with pytest.raises(ValidationError, match="non-finite value compares"):
        quantity(value, "BTC")


@pytest.mark.parametrize("text", ["-1", "-0", "-0.0000"])
def test_a_negative_amount_is_refused_including_negative_zero(text: str) -> None:
    """`-0` is why the check is `is_signed()` and not `< 0`: it is signed and equal to zero."""
    with pytest.raises(ValidationError, match="never negative, because direction is a Side"):
        quantity(text, "BTC")


def test_an_amount_carrying_more_digits_than_can_be_held_exactly_is_refused() -> None:
    with pytest.raises(ValidationError, match="significant digits, more than"):
        quantity("1." + "1" * MAX_SIGNIFICANT_DIGITS, "BTC")


def test_an_amount_at_the_digit_limit_is_accepted() -> None:
    at_the_limit = "1." + "1" * (MAX_SIGNIFICANT_DIGITS - 1)
    assert quantity(at_the_limit, "BTC").amount == Decimal(at_the_limit)


def test_a_decimal_derived_from_a_float_is_caught_by_the_digit_bound() -> None:
    """The float refusal cannot see this one — it arrives already typed."""
    with pytest.raises(ValidationError, match="usually came from a float"):
        # RUF032 exists to stop exactly this construction reaching production. Here
        # the float literal *is* the subject: `Decimal(1.1)` is fifty-two digits, and
        # catching it is what the digit bound is for.
        quantity(Decimal(1.1), "BTC")  # noqa: RUF032


@pytest.mark.parametrize("text", ["1E+31", "1E-31", "1E+999999999", "1E-1000000"])
def test_an_amount_of_absurd_magnitude_is_refused(text: str) -> None:
    """Without this, `format(value, 'f')` renders `1E+100000` as 100 001 characters."""
    with pytest.raises(ValidationError, match="beyond 1E"):
        quantity(text, "BTC")


@pytest.mark.parametrize("text", ["1E+30", "1E-30"])
def test_an_amount_at_the_magnitude_limit_is_accepted(text: str) -> None:
    assert quantity(text, "BTC").amount == Decimal(text)


def test_an_amount_that_is_not_a_decimal_at_all_is_refused_on_direct_construction() -> None:
    """The factory converts; the dataclass does not, so it has to refuse."""
    with pytest.raises(ValidationError, match="quantity amount is str"):
        Quantity(amount="1", currency=Currency(code="BTC"))  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Quantity
# --------------------------------------------------------------------------


def test_a_quantity_may_be_zero() -> None:
    """A zero balance is a real answer, unlike a zero price."""
    assert quantity(0, "BTC").amount == 0


def test_a_quantity_renders_its_amount_and_its_asset() -> None:
    assert str(quantity("0.5", "BTC")) == "0.5 BTC"


def test_a_quantity_renders_without_an_exponent() -> None:
    """`str(Decimal('1E+3'))` is `'1E+3'`, which is not how anyone reads a balance."""
    assert str(quantity("1E+3", "BTC")) == "1000 BTC"


def test_a_quantity_takes_its_asset_as_a_code_or_a_currency() -> None:
    assert quantity(1, "BTC") == quantity(1, Currency(code="BTC"))


def test_a_quantity_whose_currency_is_not_a_currency_is_refused() -> None:
    with pytest.raises(ValidationError, match="quantity currency is str"):
        Quantity(amount=Decimal(1), currency="BTC")  # type: ignore[arg-type]


def test_a_quantity_is_frozen() -> None:
    held = quantity(1, "BTC")
    with pytest.raises(FrozenInstanceError):
        held.amount = Decimal(2)  # type: ignore[misc]


# --------------------------------------------------------------------------
# Price
# --------------------------------------------------------------------------


def test_a_price_says_what_it_prices_and_what_in() -> None:
    assert str(price("60000.50", BTC_USDT)) == "60000.50 USDT per BTC"


def test_a_price_exposes_the_currency_it_is_denominated_in() -> None:
    assert price(1, BTC_USDT).quote == Currency(code="USDT")


def test_a_price_of_zero_is_refused() -> None:
    with pytest.raises(ValidationError, match="say absence instead"):
        price(0, BTC_USDT)


def test_a_price_needs_a_symbol_not_a_string() -> None:
    """There is no single-string spelling of a market. See the module docstring."""
    with pytest.raises(ValidationError, match="price symbol is str"):
        price(1, "BTCUSDT")  # type: ignore[arg-type]


def test_a_price_is_frozen() -> None:
    held = price(1, BTC_USDT)
    with pytest.raises(FrozenInstanceError):
        held.amount = Decimal(2)  # type: ignore[misc]


# --------------------------------------------------------------------------
# Comparison: the three outcomes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("compare", ORDERINGS)
def test_two_prices_of_the_same_market_compare(compare: Callable[[object, object], object]) -> None:
    low = price("1", BTC_USDT)
    high = price("2", BTC_USDT)
    assert compare(low, high) is compare(Decimal(1), Decimal(2))


@pytest.mark.parametrize("compare", ORDERINGS)
def test_two_quantities_of_the_same_asset_compare(
    compare: Callable[[object, object], object],
) -> None:
    small = quantity("1", "BTC")
    large = quantity("2", "BTC")
    assert compare(small, large) is compare(Decimal(1), Decimal(2))


@pytest.mark.parametrize("compare", ORDERINGS)
def test_ordering_two_prices_of_different_markets_is_refused(
    compare: Callable[[object, object], object],
) -> None:
    """Right type, wrong unit. mypy could not have caught this one."""
    with pytest.raises(ValidationError, match="they price different markets"):
        compare(price("1", BTC_USDT), price("1", ETH_USDT))


@pytest.mark.parametrize("compare", ORDERINGS)
def test_ordering_two_quantities_of_different_assets_is_refused(
    compare: Callable[[object, object], object],
) -> None:
    with pytest.raises(ValidationError, match="they count different assets"):
        compare(quantity("1", "BTC"), quantity("1", "ETH"))


@pytest.mark.parametrize("compare", ORDERINGS)
@pytest.mark.parametrize(
    ("left", "right"),
    [
        (price("1", BTC_USDT), quantity("1", "BTC")),
        (quantity("1", "BTC"), price("1", BTC_USDT)),
        (price("1", BTC_USDT), Decimal(1)),
        (quantity("1", "BTC"), 1),
    ],
)
def test_ordering_across_types_raises_a_type_error_naming_both(
    compare: Callable[[Any, Any], Any], left: object, right: object
) -> None:
    """Wrong type, not wrong unit: `NotImplemented`, so Python writes the message.

    The assertion names both classes rather than matching "not supported between
    instances", and the difference is not pedantry. Returning `NotImplemented`
    exists precisely so that the interpreter can name both operands; a comparison
    that instead reached the amount and compared it against `None` would raise a
    `TypeError` too, with the same opening words and a message about `Decimal`
    and `NoneType` that tells the caller nothing. Mutation testing found the
    looser form of this test accepting exactly that.
    """
    with pytest.raises(TypeError) as raised:
        compare(left, right)

    message = str(raised.value)
    assert type(left).__name__ in message, message
    assert type(right).__name__ in message, message


def test_equality_across_types_answers_rather_than_raising() -> None:
    """`__eq__` is called by `in`, by `dict` and by every assertion.

    An `__eq__` that raised would make these unusable as dictionary keys and turn a
    membership test into an exception. Ordering carries no such obligation, which
    is why the two behave differently on a mismatch.

    Through `object` again, because mypy already refuses to compare the two types
    and reporting that is its job rather than this test's.
    """
    held: object = price("1", BTC_USDT)
    counted: object = quantity("1", "BTC")
    assert held != counted
    assert counted != Decimal(1)


def test_equality_across_units_is_false_rather_than_refused() -> None:
    assert price("1", BTC_USDT) != price("1", ETH_USDT)
    assert quantity("1", "BTC") != quantity("1", "ETH")


def test_values_differing_only_in_trailing_zeros_are_the_same_value() -> None:
    """`Decimal` equality is numeric, and hashing agrees, so a set collapses them."""
    assert quantity("1.10", "BTC") == quantity("1.1", "BTC")
    assert len({quantity("1.10", "BTC"), quantity("1.1", "BTC")}) == 1


def test_a_value_can_be_a_dictionary_key() -> None:
    holdings = {currency("BTC"): quantity("1", "BTC")}
    assert holdings[currency("BTC")] == quantity("1", "BTC")


# --------------------------------------------------------------------------
# What these types deliberately cannot do
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attempt",
    [
        pytest.param(lambda p: p + p, id="price + price"),
        pytest.param(lambda p: p - p, id="price - price"),
        pytest.param(lambda p: -p, id="negate a price"),
        pytest.param(lambda p: float(p), id="float()"),
        pytest.param(lambda p: round(p), id="round()"),
        pytest.param(lambda p: sum([p, p]), id="sum()"),
        pytest.param(lambda p: p * quantity("2", "BTC"), id="price * quantity"),
    ],
)
def test_no_arithmetic_is_defined_on_a_price(attempt: Callable[[Any], object]) -> None:
    """Absence, asserted twice over.

    `Decimal` arithmetic runs under a thread-local context and rounds without
    saying so — `Decimal('1E+30') + Decimal('1E-30')` discards the addend.
    Invariant 22 forbids silent data loss and invariant 17 gives the precision
    policy to Phase 010, so these operators wait for the phase that owns the
    rounding rule.

    Half of that guarantee is already mypy's: every expression below is a static
    error at any call site the type checker can see, which is why the operand
    arrives here through an untyped parameter. This covers the other half — the
    call sites it cannot see, where a value arrived as `object` from a document.
    If an operator appears, this is what notices.
    """
    with pytest.raises(TypeError):
        attempt(price("1", BTC_USDT))


@pytest.mark.parametrize(
    "attempt",
    [
        pytest.param(lambda q: q + q, id="quantity + quantity"),
        pytest.param(lambda q: q - q, id="quantity - quantity"),
        pytest.param(lambda q: abs(q), id="absolute value"),
        pytest.param(lambda q: int(q), id="int()"),
        pytest.param(lambda q: q / 2, id="divide by a number"),
    ],
)
def test_no_arithmetic_is_defined_on_a_quantity(attempt: Callable[[Any], object]) -> None:
    """As for a price. Halving a position is a rounding decision, and Phase 010 owns it."""
    with pytest.raises(TypeError):
        attempt(quantity("1", "BTC"))


@pytest.mark.parametrize("compare", ORDERINGS)
@pytest.mark.parametrize(
    ("left", "right"),
    [
        (currency("BTC"), currency("ETH")),
        (BTC_USDT, ETH_USDT),
        (Side.BUY, 1),
    ],
)
def test_types_with_no_meaningful_order_do_not_have_one(
    compare: Callable[[object, object], object], left: object, right: object
) -> None:
    """Assets have no order, and inventing an alphabetical one is Phase 011's question."""
    with pytest.raises(TypeError, match="not supported between instances"):
        compare(left, right)


def test_the_published_alphabet_is_what_is_actually_enforced() -> None:
    """A constant nothing reads is a comment. This makes it load-bearing."""
    for character in CURRENCY_ALPHABET:
        assert currency(f"X{character}").code == f"X{character}"


def test_the_published_magnitude_bound_is_what_is_actually_enforced() -> None:
    assert quantity(f"1E+{MAX_ADJUSTED_EXPONENT}", "BTC").amount == Decimal(
        f"1E+{MAX_ADJUSTED_EXPONENT}"
    )
    with pytest.raises(ValidationError, match="beyond 1E"):
        quantity(f"1E+{MAX_ADJUSTED_EXPONENT + 1}", "BTC")
