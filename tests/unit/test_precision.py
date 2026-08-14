"""The precision module: exact arithmetic, and alignment onto a grid.

Every refusal is asserted by the message it produces, because a
`ValidationError` that says the wrong thing is a `ValidationError` nobody can
act on. Every rounding mode is asserted on both sides of its boundary, since a
mode that is right in one direction and wrong in the other passes any test that
only checks one.

The whole module is pure, so nothing here needs a temporary directory, a double
or a clock.
"""

from decimal import Decimal, localcontext
from typing import Any

import pytest

from globin.domain import values
from globin.domain.precision import (
    EXACT_PRECISION,
    INCREMENT_ALPHABET,
    MAX_INCREMENT_DIGITS,
    MAX_INCREMENT_EXPONENT,
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

# --------------------------------------------------------------------------
# Increment
# --------------------------------------------------------------------------


def test_an_increment_carries_its_step() -> None:
    """The one field, read back unchanged."""
    assert increment("0.01").step == Decimal("0.01")


def test_an_increment_keeps_the_trailing_zeros_it_was_given() -> None:
    """A venue that says `0.00010000` is stating its precision, not padding.

    ADR-0030 refused a scaled integer representation for exactly this reason, so
    an increment that quietly normalised to `0.0001` would reintroduce the loss
    that decision exists to prevent.
    """
    assert str(increment("0.00010000")) == "0.00010000"


def test_an_increment_is_frozen() -> None:
    """A grid that could be edited after construction is not a grid."""
    with pytest.raises(AttributeError):
        increment("0.01").step = Decimal("0.02")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        pytest.param(0, "strictly positive", id="zero"),
        pytest.param(-1, "strictly positive", id="negative"),
        pytest.param(Decimal("NaN"), "finite", id="not a number"),
        pytest.param(Decimal("Infinity"), "finite", id="infinite"),
        pytest.param("1E+31", "beyond", id="magnitude too large"),
        pytest.param("1E-31", "beyond", id="magnitude too small"),
        pytest.param("1." + "1" * MAX_INCREMENT_DIGITS, "significant digits", id="too long"),
    ],
)
def test_an_increment_refuses_a_step_that_describes_no_usable_grid(
    step: object, expected: str
) -> None:
    """Each rule, named in the message it produces."""
    with pytest.raises(ValidationError, match=expected):
        increment(step)  # type: ignore[arg-type]


def test_an_increment_refuses_a_float_and_says_what_it_would_have_meant() -> None:
    """The remedy matters more than the refusal.

    `0.01` is not a hundredth, and a message that only said "no float" would
    leave the caller believing it was.
    """
    with pytest.raises(ValidationError, match="Pass the exact text instead"):
        increment(0.01)  # type: ignore[arg-type]


def test_an_increment_refuses_a_bool_before_it_refuses_an_int() -> None:
    """`isinstance(True, int)` is true, and `Decimal(True)` is one.

    No `type: ignore` here, and that is the point: `bool` *is* an `int` to the
    type checker, so this call passes mypy. Only the runtime guard catches it.
    """
    with pytest.raises(ValidationError, match="bool"):
        increment(True)


def test_an_increment_accepts_a_whole_number_of_units() -> None:
    """A step of one is a real grid — a venue quoting whole tokens."""
    assert increment(1).step == Decimal(1)


@pytest.mark.parametrize(
    "step",
    [
        pytest.param(f"1E+{MAX_INCREMENT_EXPONENT}", id="largest permitted magnitude"),
        pytest.param(f"1E-{MAX_INCREMENT_EXPONENT}", id="smallest permitted magnitude"),
        pytest.param("1." + "1" * (MAX_INCREMENT_DIGITS - 1), id="longest permitted step"),
    ],
)
def test_an_increment_accepts_a_step_exactly_on_its_bounds(step: str) -> None:
    """The bounds are inclusive, and that has to be asserted rather than assumed.

    The refusal tests above sit one step outside each bound, which proves the
    rule exists but not where it falls. Without these, changing `>` to `>=` in
    the guards would pass the whole suite — and would quietly refuse a venue
    quoting at exactly the limit.
    """
    assert increment(step).step == Decimal(step)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(" 1 ", "contains", id="padded"),
        pytest.param("1_000", "contains", id="underscored"),
        pytest.param("NaN", "contains", id="not a number by name"),
        pytest.param("+-", "is not a number", id="spelled from the alphabet but meaningless"),
    ],
)
def test_an_increment_refuses_text_it_will_not_spell(text: str, expected: str) -> None:
    """`Decimal` reads all four; this module reads none of them.

    The first three are refused by the alphabet and the fourth by `Decimal`
    itself, which is why both branches need a case.
    """
    with pytest.raises(ValidationError, match=expected):
        increment(text)


def test_an_increment_refuses_a_step_built_around_the_dataclass() -> None:
    """The factory is the front door, not the only door.

    Constructing the dataclass directly with a non-`Decimal` must refuse on the
    same terms, or the validation is advice rather than a rule.
    """
    with pytest.raises(ValidationError, match="build it through"):
        Increment(step="0.01")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Exact arithmetic
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("operation", "left", "right", "expected"),
    [
        pytest.param(add, "1.11", "2.222", "3.332", id="sum"),
        pytest.param(subtract, "3.332", "1.11", "2.222", id="difference"),
        pytest.param(multiply, "1.5", "2.5", "3.75", id="product"),
        pytest.param(subtract, "1", "3", "-2", id="difference below zero"),
    ],
)
def test_an_exact_operation_answers_exactly(
    operation: Any, left: str, right: str, expected: str
) -> None:
    """The ordinary case, including a difference that goes negative.

    `subtract` returns a magnitude and passes no judgement on its sign; whether
    a negative result is an admissible *amount* is the question the type built
    from it answers.
    """
    assert operation(Decimal(left), Decimal(right)) == Decimal(expected)


def test_a_sum_that_cannot_be_held_exactly_is_refused_rather_than_rounded() -> None:
    """The failure this module exists to prevent, made to happen.

    Under the default context this expression returns `1E+30` and discards the
    addend without a word. Here it is refused, and the refusal names the digit
    budget so the reader learns why.
    """
    with pytest.raises(ValidationError, match="refused rather than rounded"):
        add(Decimal("1E+200000"), Decimal("1E-200000"))


def test_the_sum_the_default_context_would_discard_is_computed_in_full() -> None:
    """Refusal is the fallback, not the behaviour.

    `1E+30 + 1E-30` needs 61 digits, which is well inside the budget, so the
    answer is the exact one rather than either a rounded value or an error.
    """
    total = add(Decimal("1E+30"), Decimal("1E-30"))
    assert len(total.as_tuple().digits) == 61
    assert total != Decimal("1E+30")


def test_the_digit_budget_covers_the_worst_case_the_value_bounds_permit() -> None:
    """`EXACT_PRECISION` is derived, so the derivation is checked rather than trusted.

    An amount `values` admits spans from `1E+30` down to `1E-57`, so the widest
    exact sum of two occupies 88 places plus one for a carry. If a later phase
    widens either bound without revisiting the budget, this fails.
    """
    largest_place = values.MAX_ADJUSTED_EXPONENT
    smallest_place = -values.MAX_ADJUSTED_EXPONENT - (values.MAX_SIGNIFICANT_DIGITS - 1)
    widest_sum = largest_place - smallest_place + 1 + 1
    widest_product = 2 * values.MAX_SIGNIFICANT_DIGITS
    assert max(widest_sum, widest_product) <= EXACT_PRECISION


# --------------------------------------------------------------------------
# Alignment
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "rounding", "expected"),
    [
        pytest.param("1.239", Rounding.FLOOR, "1.23", id="floor moves down"),
        pytest.param("1.239", Rounding.CEILING, "1.24", id="ceiling moves up"),
        pytest.param("1.231", Rounding.HALF_EVEN, "1.23", id="half-even below the midpoint"),
        pytest.param("1.239", Rounding.HALF_EVEN, "1.24", id="half-even above the midpoint"),
        pytest.param("1.005", Rounding.HALF_EVEN, "1.00", id="half-even tie to the even below"),
        pytest.param("1.015", Rounding.HALF_EVEN, "1.02", id="half-even tie to the even above"),
        pytest.param("1.23", Rounding.EXACT, "1.23", id="exact when already aligned"),
        pytest.param("1.23", Rounding.FLOOR, "1.23", id="already aligned is left alone"),
        pytest.param("0", Rounding.FLOOR, "0.00", id="zero is on every grid"),
        pytest.param("0.001", Rounding.FLOOR, "0.00", id="flooring below one step gives zero"),
    ],
)
def test_alignment_moves_a_magnitude_in_the_direction_asked_for(
    amount: str, rounding: Rounding, expected: str
) -> None:
    """Every mode, on both sides of its boundary, including both tie directions.

    The two tie cases are the ones that distinguish half-even from half-up:
    `1.005` and `1.015` are both exactly on a midpoint, and they must move in
    opposite directions.
    """
    assert align(Decimal(amount), to=increment("0.01"), rounding=rounding) == Decimal(expected)


def test_alignment_carries_the_grids_own_exponent() -> None:
    """The venue's stated precision survives, rather than being narrowed.

    Aligning onto `0.00010000` yields a value spelled to eight places even
    though only one of them is non-zero.
    """
    aligned = align(Decimal("1.2"), to=increment("0.00010000"), rounding=Rounding.FLOOR)
    assert str(aligned) == "1.20000000"


def test_exact_refuses_a_value_that_is_not_already_on_the_grid() -> None:
    """The mode that asserts rather than rounds."""
    with pytest.raises(ValidationError, match="is not a multiple of"):
        align(Decimal("1.239"), to=increment("0.01"), rounding=Rounding.EXACT)


@pytest.mark.parametrize(
    "rounding",
    [
        pytest.param("FLOOR", id="the member's own value as a string"),
        pytest.param("ROUND_HALF_UP", id="a decimal.ROUND_* constant"),
        pytest.param(None, id="nothing at all"),
    ],
)
def test_alignment_refuses_a_rounding_mode_that_is_not_a_member(rounding: object) -> None:
    """A `StrEnum` member equals its value, and a string still is not one.

    `Rounding.FLOOR == "FLOOR"` is true, which is what makes the enum pleasant
    to read; `isinstance("FLOOR", Rounding)` is false, which is what makes this
    refusal possible. `ROUND_HALF_UP` is in the list because it is the mode a
    caller reaching past this module would most plausibly want.
    """
    with pytest.raises(ValidationError, match="pass a Rounding member"):
        align(Decimal("1.23"), to=increment("0.01"), rounding=rounding)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        pytest.param("-1", "signed", id="negative"),
        pytest.param("NaN", "non-finite", id="not a number"),
        pytest.param("Infinity", "non-finite", id="infinite"),
    ],
)
def test_alignment_refuses_a_magnitude_it_has_no_rule_for(amount: str, expected: str) -> None:
    """A signed value is Phase 155's question; a non-finite one sits on no grid."""
    with pytest.raises(ValidationError, match=expected):
        align(Decimal(amount), to=increment("0.01"), rounding=Rounding.FLOOR)


def test_alignment_refuses_a_magnitude_that_is_not_a_decimal() -> None:
    """The guard for the call sites mypy cannot see."""
    with pytest.raises(ValidationError, match="alignment works on a Decimal"):
        align("1.23", to=increment("0.01"), rounding=Rounding.FLOOR)  # type: ignore[arg-type]


def test_alignment_refuses_a_quotient_too_long_to_compute_exactly() -> None:
    """`divmod` refuses rather than rounding, and the refusal is translated.

    A magnitude beyond what `values` would admit is still a `Decimal`, and
    placing `1E+200000` on a hundredths grid needs two hundred thousand digits
    of quotient. `decimal` signals `DivisionImpossible`; the caller sees a
    GLOBIN error naming the digit budget.
    """
    with pytest.raises(ValidationError, match="quotient needs more than"):
        align(Decimal("1E+200000"), to=increment("0.01"), rounding=Rounding.FLOOR)


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        pytest.param("1.23", True, id="on the grid"),
        pytest.param("1.239", False, id="off the grid"),
        pytest.param("0", True, id="zero"),
    ],
)
def test_is_aligned_answers_what_exact_would_have_raised_about(amount: str, expected: bool) -> None:
    """The question form, for a caller who would rather branch than catch."""
    assert is_aligned(Decimal(amount), to=increment("0.01")) is expected


def test_is_aligned_refuses_a_magnitude_it_has_no_rule_for() -> None:
    """The same guard as alignment, because the same quotient is computed."""
    with pytest.raises(ValidationError, match="signed"):
        is_aligned(Decimal(-1), to=increment("0.01"))


# --------------------------------------------------------------------------
# The ambient context
# --------------------------------------------------------------------------


def test_a_hostile_ambient_context_changes_nothing() -> None:
    """The claim the whole module rests on, made to fail if it were false.

    `prec=1` with `ROUND_UP` would turn every answer below into something else
    if any operation here read the thread-local context. `Context` methods do
    not, which is why these assertions are the same ones as above.

    `localcontext` is used as a context manager so that a failure inside it
    still restores the caller's context — a test that leaked a `prec=1` context
    would corrupt every later test sharing the process.
    """
    tick = increment("0.01")
    with localcontext() as hostile:
        hostile.prec = 1
        hostile.rounding = "ROUND_UP"
        assert add(Decimal("1.11"), Decimal("2.222")) == Decimal("3.332")
        assert multiply(Decimal("1.5"), Decimal("2.5")) == Decimal("3.75")
        assert align(Decimal("1.239"), to=tick, rounding=Rounding.FLOOR) == Decimal("1.23")
        assert is_aligned(Decimal("1.23"), to=tick) is True


def test_the_module_leaves_the_callers_context_alone() -> None:
    """The other direction: GLOBIN must not disturb the caller either.

    A module that fixed its own results by calling `setcontext` would pass the
    test above and still be wrong, because the next thing the caller computed
    would be affected.
    """
    with localcontext() as before:
        before.prec = 7
        # `localcontext` copies the caller's flags, and an earlier test in this
        # process may have set some. Clearing first is what makes the assertion
        # below about this module rather than about the whole session.
        before.clear_flags()
        align(Decimal("1.239"), to=increment("0.01"), rounding=Rounding.CEILING)
        add(Decimal("1.11"), Decimal("2.222"))
        assert before.prec == 7
        assert not any(before.flags.values())


# --------------------------------------------------------------------------
# The tripwires
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("here", "there", "name"),
    [
        pytest.param(
            MAX_INCREMENT_DIGITS, values.MAX_SIGNIFICANT_DIGITS, "digits", id="digit bound"
        ),
        pytest.param(
            MAX_INCREMENT_EXPONENT, values.MAX_ADJUSTED_EXPONENT, "exponent", id="magnitude bound"
        ),
        pytest.param(INCREMENT_ALPHABET, values.DECIMAL_ALPHABET, "alphabet", id="alphabet"),
    ],
)
def test_the_copied_bounds_still_agree_with_the_ones_they_copy(
    here: object, there: object, name: str
) -> None:
    """Three deliberate copies, each licensed only by this comparison.

    `precision` is the inner module and must not import `values`, so it restates
    three of that module's bounds. `SOURCE_OF_TRUTH.md` permits a copy only when
    a test fails on divergence, and this is that test.
    """
    assert here == there, f"the {name} bound has drifted between precision and values"
