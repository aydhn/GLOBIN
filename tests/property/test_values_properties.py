"""The laws the value types obey, over generated values rather than examples.

``tests/unit/test_values.py`` checks the cases someone thought of. These check
the claims that must hold for *every* input, and four are worth stating plainly
because later phases will build on them:

* **Refusal is total in both directions.** Every code spelled from the published
  alphabet within the published bounds is accepted; every code outside either is
  refused. A hand-rolled alphabet check is exactly the kind of thing that widens
  by one character without anyone noticing.
* **An amount survives being written down and read back.** This is what proves
  :data:`~globin.domain.values.DECIMAL_ALPHABET` is not accidentally narrower
  than what :meth:`decimal.Decimal.__str__` emits — a real bug class, since
  ``str(Decimal('1E+3'))`` is ``'1E+3'`` and not ``'1000'``.
* **Ordering is a total order within one denomination, and refuses across two.**
  Trichotomy and transitivity are what break first when somebody derives one
  comparison operator from another.
* **Equality never raises, for any pair of any of the five types.** That is the
  guarantee keeping these usable in a ``set`` or as a ``dict`` key, and it is one
  ``if`` away from being lost.

Deliberately absent: any property about :attr:`~globin.domain.values.Side.opposite`.
Its domain has two members, so a generated test over it is a slow unit test —
``docs/TESTING_STRATEGY.md`` and ADR-0023 both say to write the invariant only
where one exists over a space worth searching.
"""

from decimal import Decimal
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from globin.domain.values import (
    CURRENCY_ALPHABET,
    DECIMAL_ALPHABET,
    MAX_ADJUSTED_EXPONENT,
    MAX_CURRENCY_CODE_LENGTH,
    MAX_SIGNIFICANT_DIGITS,
    MIN_CURRENCY_CODE_LENGTH,
    Currency,
    Price,
    Quantity,
    Side,
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

#: Bounded well inside the published limits on purpose. The boundaries themselves
#: are unit tests, where the expected answer can be written down; these searches
#: are for the behaviour in between.
amounts = st.decimals(
    min_value=Decimal(0),
    max_value=Decimal("1E+12"),
    allow_nan=False,
    allow_infinity=False,
    places=8,
).filter(lambda value: not value.is_signed())

positive_amounts = amounts.filter(lambda value: value != 0)

quantities = st.builds(quantity, amount=amounts, asset=codes)

#: One shared pair, because a property about ordering needs two values of the
#: *same* denomination and generating the denomination twice would rarely agree.
BTC_USDT: Final[Symbol] = Symbol(base=Currency(code="BTC"), quote=Currency(code="USDT"))
ETH_USDT: Final[Symbol] = Symbol(base=Currency(code="ETH"), quote=Currency(code="USDT"))

btc_prices = st.builds(price, amount=positive_amounts, market=st.just(BTC_USDT))
btc_quantities = st.builds(quantity, amount=amounts, asset=st.just("BTC"))

#: At least one of each type, so a property about "any pair of values" searches
#: across types rather than within one.
any_value = st.one_of(
    st.builds(currency, codes),
    st.just(BTC_USDT),
    btc_prices,
    btc_quantities,
    st.sampled_from(list(Side)),
)


# --------------------------------------------------------------------------
# Refusal is total, in both directions
# --------------------------------------------------------------------------


@given(code=codes)
def test_every_code_the_rule_describes_is_accepted(code: str) -> None:
    assert currency(code).code == code


@given(code=st.text(max_size=20).filter(lambda text: set(text) - set(CURRENCY_ALPHABET)))
def test_every_code_spelled_outside_the_alphabet_is_refused(code: str) -> None:
    with pytest.raises(ValidationError):
        currency(code)


@given(
    code=st.text(alphabet=CURRENCY_ALPHABET).filter(
        lambda text: not MIN_CURRENCY_CODE_LENGTH <= len(text) <= MAX_CURRENCY_CODE_LENGTH
    )
)
def test_every_code_outside_the_length_bounds_is_refused(code: str) -> None:
    with pytest.raises(ValidationError, match="expected between"):
        currency(code)


@given(value=st.floats())
def test_no_float_is_ever_accepted_as_an_amount(value: float) -> None:
    """Invariant 17 has no exceptions, so neither does this."""
    with pytest.raises(ValidationError):
        quantity(value, "BTC")  # type: ignore[arg-type]


@given(text=st.text(max_size=20).filter(lambda text: set(text) - set(DECIMAL_ALPHABET)))
def test_every_amount_spelled_outside_the_decimal_alphabet_is_refused(text: str) -> None:
    with pytest.raises(ValidationError):
        quantity(text, "BTC")


@given(base=codes, quote=codes)
def test_a_symbol_is_refused_exactly_when_both_halves_are_the_same_asset(
    base: str, quote: str
) -> None:
    if base == quote:
        with pytest.raises(ValidationError, match="not a market against itself"):
            symbol(base, quote)
    else:
        assert symbol(base, quote).base == currency(base)


# --------------------------------------------------------------------------
# Writing a value down and reading it back
# --------------------------------------------------------------------------


@given(held=quantities)
def test_an_amount_survives_being_written_down_and_read_back(held: Quantity) -> None:
    """The alphabet must admit everything `Decimal.__str__` produces."""
    assert quantity(str(held.amount), held.currency) == held


@given(held=quantities)
def test_reading_an_amount_back_is_idempotent(held: Quantity) -> None:
    once = quantity(str(held.amount), held.currency)
    twice = quantity(str(once.amount), once.currency)
    assert once == twice


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


@given(left=btc_prices, right=btc_prices)
def test_exactly_one_of_less_equal_or_greater_holds(left: Price, right: Price) -> None:
    assert [left < right, left == right, left > right].count(True) == 1


@given(left=btc_prices, right=btc_prices)
def test_ordering_agrees_when_read_from_either_end(left: Price, right: Price) -> None:
    assert (left < right) == (right > left)
    assert (left <= right) == (right >= left)


@given(left=btc_prices, middle=btc_prices, right=btc_prices)
def test_ordering_is_transitive(left: Price, middle: Price, right: Price) -> None:
    if left < middle and middle < right:
        assert left < right


@given(held=btc_quantities)
def test_a_value_is_neither_less_nor_greater_than_itself(held: Quantity) -> None:
    assert not held < held
    assert not held > held
    assert held <= held
    assert held >= held


@given(amount=positive_amounts, other=positive_amounts)
def test_ordering_across_denominations_always_refuses(amount: Decimal, other: Decimal) -> None:
    """No pair of amounts makes a BTC price comparable with an ETH one."""
    left = price(amount, BTC_USDT)
    right = price(other, ETH_USDT)
    with pytest.raises(ValidationError, match="different markets"):
        _ = left < right


# --------------------------------------------------------------------------
# Equality, hashing, and immutability
# --------------------------------------------------------------------------


@given(left=any_value, right=any_value)
def test_equality_never_raises_for_any_pair_of_values(left: object, right: object) -> None:
    """`__eq__` is called by `in`, by `dict` and by every assertion in the suite."""
    assert isinstance(left == right, bool)
    assert (left == right) is not (left != right)


@given(left=btc_quantities, right=btc_quantities)
def test_equal_values_hash_alike(left: Quantity, right: Quantity) -> None:
    if left == right:
        assert hash(left) == hash(right)


@given(value=any_value)
def test_every_value_can_be_a_set_member(value: object) -> None:
    """Hashable, and equal to itself — which is what a set collapsing two copies proves."""
    assert len({value, value}) == 1


# --------------------------------------------------------------------------
# What construction guarantees about what it stores
# --------------------------------------------------------------------------


@given(held=quantities)
def test_a_stored_amount_is_always_finite_unsigned_and_representable(held: Quantity) -> None:
    """The four rules, read back off the constructed value rather than the input."""
    assert held.amount.is_finite()
    assert not held.amount.is_signed()
    assert abs(held.amount.adjusted()) <= MAX_ADJUSTED_EXPONENT
    assert len(held.amount.as_tuple().digits) <= MAX_SIGNIFICANT_DIGITS


@given(amount=positive_amounts)
def test_a_price_always_knows_the_currency_it_is_quoted_in(amount: Decimal) -> None:
    assert price(amount, BTC_USDT).quote == BTC_USDT.quote
