"""The laws exact arithmetic and alignment obey, over generated values.

``tests/unit/test_precision.py`` checks the cases someone thought of. These check
the claims that must hold for *every* input, and four of them are the reason the
phase can be trusted rather than merely believed:

* **The ambient context changes nothing.** Every operation gives the same answer
  under a deliberately hostile thread-local context as under the default one.
  This is the executable form of the module's central claim, and the single most
  valuable test in the phase.
* **Exactness is checked against an independent oracle.** :mod:`fractions` is
  standard library, exact and unbounded, and shares no implementation with
  :mod:`decimal` — so it cannot share a bug with the code under test. An
  operation either equals the rational answer or refuses.
* **Alignment is total, idempotent and bounded.** The result is always on the
  grid, aligning twice changes nothing, and nothing moves by a whole increment.
* **Alignment is monotone.** Ordering survives it. This is what stops a value
  crossing a limit *because* it was rounded, which is the failure that would
  turn a risk check into a suggestion.

Deliberately absent: a property over the four :class:`Rounding` members. Four is
a slow unit test rather than a space worth searching — the argument
``test_values_properties.py`` already makes about ``Side.opposite``.
"""

from decimal import Decimal, localcontext
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from globin.domain.precision import (
    Increment,
    Rounding,
    add,
    align,
    increment,
    is_aligned,
    multiply,
    subtract,
)
from globin.errors import ValidationError

#: Bounded well inside the published limits, for the reason
#: ``test_values_properties.py`` gives: the boundaries are unit tests, where the
#: expected answer can be written down. These searches are for what happens
#: between them.
magnitudes = st.decimals(
    min_value=Decimal(0),
    max_value=Decimal("1E+12"),
    allow_nan=False,
    allow_infinity=False,
    places=8,
).filter(lambda value: not value.is_signed())

#: Grids coarse enough that alignment actually moves most magnitudes, and never
#: so fine that the quotient approaches the digit budget.
increments = st.sampled_from(["0.01", "0.001", "0.5", "1", "25", "0.00010000", "2.5", "1E+3"]).map(
    increment
)

modes = st.sampled_from([Rounding.FLOOR, Rounding.CEILING, Rounding.HALF_EVEN])


@given(amount=magnitudes, to=increments, rounding=modes)
def test_a_hostile_ambient_context_changes_no_answer(
    amount: Decimal, to: Increment, rounding: Rounding
) -> None:
    """The module's central claim, searched rather than sampled.

    `prec=1` with `ROUND_UP` would change nearly every answer if any operation
    read the thread-local context. `Context` methods do not.
    """
    expected = align(amount, to=to, rounding=rounding)
    with localcontext() as hostile:
        hostile.prec = 1
        hostile.rounding = "ROUND_UP"
        assert align(amount, to=to, rounding=rounding) == expected


@given(left=magnitudes, right=magnitudes)
def test_an_exact_operation_agrees_with_rational_arithmetic_or_refuses(
    left: Decimal, right: Decimal
) -> None:
    """Checked against `Fraction`, which cannot share a bug with `Decimal`.

    Either the answer is the mathematically exact one, or the operation refused.
    There is no third outcome, and a rounded result would be exactly that.
    """
    for operation, oracle in (
        (add, Fraction(left) + Fraction(right)),
        (subtract, Fraction(left) - Fraction(right)),
        (multiply, Fraction(left) * Fraction(right)),
    ):
        try:
            answer = operation(left, right)
        except ValidationError:
            continue
        assert Fraction(answer) == oracle


@given(amount=magnitudes, to=increments, rounding=modes)
def test_alignment_always_lands_on_the_grid(
    amount: Decimal, to: Increment, rounding: Rounding
) -> None:
    """Totality: whatever went in, what comes out is a multiple of the step."""
    assert is_aligned(align(amount, to=to, rounding=rounding), to=to)


@given(amount=magnitudes, to=increments, rounding=modes)
def test_alignment_is_idempotent(amount: Decimal, to: Increment, rounding: Rounding) -> None:
    """Aligning an aligned value moves it no further.

    Also proves `EXACT` accepts anything the other modes produced, which is the
    property a caller relies on when it aligns once and asserts later.
    """
    once = align(amount, to=to, rounding=rounding)
    assert align(once, to=to, rounding=rounding) == once
    assert align(once, to=to, rounding=Rounding.EXACT) == once


@given(amount=magnitudes, to=increments, rounding=modes)
def test_alignment_never_moves_a_whole_increment(
    amount: Decimal, to: Increment, rounding: Rounding
) -> None:
    """A bound on the effect rather than on the mechanism.

    The same shape of claim `TIME_POLICY.md` makes about millisecond flooring: a
    reader can check it without understanding how alignment is implemented.
    """
    assert abs(align(amount, to=to, rounding=rounding) - amount) < to.step


@given(amount=magnitudes, to=increments)
def test_each_mode_moves_in_its_own_direction(amount: Decimal, to: Increment) -> None:
    """What distinguishes the modes from each other.

    Monotonicity alone would not: every mode is monotone, so a test that only
    checked ordering would pass with all three implemented identically.
    """
    floored = align(amount, to=to, rounding=Rounding.FLOOR)
    ceiled = align(amount, to=to, rounding=Rounding.CEILING)
    nearest = align(amount, to=to, rounding=Rounding.HALF_EVEN)
    assert floored <= amount <= ceiled
    assert abs(nearest - amount) <= to.step / 2
    assert nearest in (floored, ceiled)


@given(left=magnitudes, right=magnitudes, to=increments, rounding=modes)
def test_alignment_preserves_ordering(
    left: Decimal, right: Decimal, to: Increment, rounding: Rounding
) -> None:
    """Rounding may not invert a comparison.

    This is the property a risk check depends on: if aligning could reorder two
    values, a price that was below a limit could be above it afterwards.
    """
    if left > right:
        left, right = right, left
    assert align(left, to=to, rounding=rounding) <= align(right, to=to, rounding=rounding)


@given(amount=magnitudes, to=increments)
def test_exact_accepts_precisely_what_is_aligned_and_refuses_the_rest(
    amount: Decimal, to: Increment
) -> None:
    """`EXACT` and `is_aligned` are two spellings of one question, in both directions."""
    if is_aligned(amount, to=to):
        assert align(amount, to=to, rounding=Rounding.EXACT) == amount
    else:
        with pytest.raises(ValidationError, match="not a multiple of"):
            align(amount, to=to, rounding=Rounding.EXACT)


@given(step=magnitudes)
def test_increment_refusal_is_total_in_both_directions(step: Decimal) -> None:
    """Every strictly positive step is a grid; nothing else is."""
    if step > 0:
        assert increment(step).step == step
    else:
        with pytest.raises(ValidationError, match="strictly positive"):
            increment(step)


@given(step=magnitudes.filter(lambda value: value > 0))
def test_an_increment_survives_being_written_down_and_read_back(step: Decimal) -> None:
    """The round trip that proves `INCREMENT_ALPHABET` is not narrower than `str`.

    ``str(Decimal('1E+3'))`` is ``'1E+3'``, not ``'1000'``, so an alphabet
    missing ``E`` would refuse a value this module had itself produced.
    """
    assert increment(str(increment(step))).step == step
