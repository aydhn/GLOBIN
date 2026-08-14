"""How a magnitude is computed, and how it is put onto a grid.

``ROADMAP.md`` gives Phase 010 one job: decide where exact arithmetic is
mandatory rather than optional, and define rounding and tick-size behaviour.
Three earlier phases deferred to it by name — ADR-0030, ADR-0031 and ADR-0035 —
and this module is the answer they were waiting for.

**The problem, stated once.** Every :class:`decimal.Decimal` *operator* reads a
thread-local context. ``Decimal('1E+30') + Decimal('1E-30')`` returns ``1E+30``
under the default context, discarding the addend without a word, and a caller who
has set ``prec=5`` changes what every other module computes. That is the silent
data loss ``ENGINEERING_CONTRACT.md`` invariant 22 forbids and the hidden global
state invariant 5 forbids, in one expression.

**The answer.** Nothing here uses an operator, and nothing here reads the
thread-local context. Every operation is a method on a :class:`decimal.Context`
this module builds for the call. A ``Context`` method takes its precision, its
exponent range and its traps from the object it is called on, and touches no
thread-local state at all — measured, and recorded as S-03 in
``docs/research/phase_010_sources.md``. ADR-0031 raised ambient-state mutation as
its reason for refusing exact arithmetic in the domain; that objection is about
:func:`decimal.localcontext`, and it does not apply to a ``Context`` method.

**The two rules a reader needs.**

*Exact or refused.* :func:`add`, :func:`subtract` and :func:`multiply` return the
mathematically exact result or raise :class:`~globin.errors.ValidationError`.
They take no rounding mode, because they never round.

*Rounding is always asked for.* :func:`align` and anything else that can discard
information takes a required, keyword-only :class:`Rounding`. There is no default
anywhere in GLOBIN, because a default is what makes a rounding decision invisible
at the call site.

**What lives here rather than in :mod:`globin.domain.values`.** A grid spacing
and a rounding mode are facts about magnitudes. They do not need to know what a
market is, which is why this module imports nothing from ``values`` and ``values``
imports this one. A later phase aligning something that is neither a price nor a
quantity — a funding rate, an interest accrual — reaches for this module and not
for the value types.

This module imports nothing outside :mod:`globin.errors` and :mod:`decimal`,
performs no I/O and holds no module-level call. ``decimal`` is absent from the
I/O-capable list in ``docs/architecture/dependency-rules.toml``, which is what
permits the import at all.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import (
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Underflow,
)
from enum import StrEnum
from typing import Final

from globin.errors import ValidationError

EXACT_PRECISION: Final[int] = 128
"""How many digits the exact operations are given to work in.

Derived from the bounds :mod:`globin.domain.values` publishes, not chosen. An
amount that module admits carries at most 28 significant digits with an adjusted
exponent within ±30, so its largest place value is ``1E+30`` and its smallest is
``1E-57``. From that:

* the exact **sum** of two such amounts spans 88 decimal places, and one more for
  a carry makes 89;
* the exact **product** needs at most 56 digits;
* the exact integer **quotient** of an amount by an increment needs at most 61.

One hundred and twenty-eight clears all three with margin, and the margin costs
nothing: :class:`~decimal.Decimal` is arbitrary-precision, so a wide context is
not a slow one until the digits are actually used.

The trap matters more than the width. :class:`decimal.Inexact` is armed in every
context built here, so if a later phase widens those bounds and this number stops
being sufficient, the arithmetic **raises** rather than quietly rounding. A unit
test derives the worst case from the published bounds and asserts this value
covers it, so the derivation above is checked rather than merely written down.
"""

EXACT_MIN_EXPONENT: Final[int] = -999_999
"""The smallest exponent the exact context permits.

Stated rather than inherited. :data:`decimal.DefaultContext` happens to use this
value, but "happens to" is not a guarantee, and a refusal that moves when CPython
changes a default is not a refusal. Wide enough that no amount this project
admits can reach it, so :class:`decimal.Underflow` and subnormal results are
unreachable — which is the point, because subnormality is defined against the
context's ``Emin`` and would otherwise make an answer depend on a setting.
"""

EXACT_MAX_EXPONENT: Final[int] = 999_999
"""The largest exponent the exact context permits.

The mirror of :data:`EXACT_MIN_EXPONENT`, for the same reason. Overflow is
trapped rather than returning infinity, so a product that escapes this range
raises instead of producing a value that compares in ways no amount should.
"""

MAX_INCREMENT_DIGITS: Final[int] = 28
"""How many significant digits an increment may carry.

Deliberately equal to ``values.MAX_SIGNIFICANT_DIGITS``. It is written out again
rather than imported because this module is the inner one and must not depend on
``values``; ``docs/engineering/SOURCE_OF_TRUTH.md`` permits a copy only as a
tripwire, so ``tests/contract/test_precision_contract.py`` compares the two and
fails when they diverge.

It is also what catches an increment derived from binary floating point:
``Decimal(0.01)`` is fifty-five digits long and arrives already typed as a
``Decimal``, where a ``float`` refusal cannot see it.
"""

MAX_INCREMENT_EXPONENT: Final[int] = 30
"""How far from one an increment's magnitude may sit, in powers of ten.

Deliberately equal to ``values.MAX_ADJUSTED_EXPONENT``, and compared against it
by the same tripwire test. Without it ``Decimal('1E-999999999')`` is finite and
positive, so every other rule here admits it, and the quotient of any amount by
it would need a billion digits.
"""

INCREMENT_ALPHABET: Final[str] = "0123456789+-.eE"
"""The characters an increment written as text may contain.

Deliberately equal to ``values.DECIMAL_ALPHABET``, under the same tripwire.
Narrower than what :class:`decimal.Decimal` accepts: ``Decimal`` reads ``" 1 "``
as one and ``"1_000"`` as a thousand, and neither spelling should silently mean
what it appears to mean.
"""


class Rounding(StrEnum):
    """What to do with a magnitude that does not sit on the grid.

    Four members, where :mod:`decimal` offers eight. ``ROUND_UP``,
    ``ROUND_HALF_UP``, ``ROUND_HALF_DOWN`` and ``ROUND_05UP`` each have a
    defensible use somewhere and none of them here, and admitting a mode nobody
    argued for is how a rounding decision gets made by accident.

    A member is required at every call site, so a reader of the call can see
    which way the value moved without opening this file.
    """

    FLOOR = "FLOOR"
    """Toward negative infinity: never ask for more than exists.

    The mode for making a value acceptable to a venue — a quantity onto its step,
    a bid onto its tick. ``ROUND_FLOOR`` rather than ``ROUND_DOWN`` even though
    the two are identical for every value this project currently admits, because
    they stop being identical the moment Phases 155-156 introduce signed money,
    and a mode that silently changes meaning is worse than one that was always
    explicit. ADR-0035 chose flooring on both sides of the epoch for the same
    reason.
    """

    CEILING = "CEILING"
    """Toward positive infinity: never reserve less than is owed.

    The mode for a charge rather than a holding — a fee, a margin requirement, a
    minimum notional. The counterpart to :attr:`FLOOR`, and named as its
    direction for the same reason.
    """

    HALF_EVEN = "HALF_EVEN"
    """To the nearest, with ties going to the even multiple.

    The mode for reporting and for statistics over many values, where a
    directional bias accumulates into a number somebody will quote. Ties go to
    even rather than away from zero because that is the choice with no long-run
    drift.
    """

    EXACT = "EXACT"
    """Not a rounding mode: the assertion that no rounding is needed.

    Refuses a value that is not already on the grid. It is a member rather than a
    separate function so that **every** call site names a mode, and there is no
    second spelling of "do not round" for a reader to learn. A caller who wants to
    ask rather than to insist uses :func:`is_aligned`.
    """


@dataclass(frozen=True, slots=True)
class Increment:
    """The spacing of the grid a magnitude must sit on.

    Args:
        step: How far apart two adjacent admissible values are. Strictly
            positive — a zero step describes no grid, and a negative one
            describes the same grid as its magnitude while inviting a sign error.

    Raises:
        ValidationError: If ``step`` is not a finite, strictly positive
            :class:`~decimal.Decimal` within :data:`MAX_INCREMENT_DIGITS` and
            :data:`MAX_INCREMENT_EXPONENT`.

    **A tick size and a step size are the same type.** One denominates a price and
    the other a quantity, but the object is identical and the arithmetic is
    identical. Two types carrying one :class:`~decimal.Decimal` each would need a
    rule saying which applies where, and that rule is the thing that drifts —
    ADR-0030's argument for having no separate ``Money`` type, which holds here
    for the same reason. Which one an ``Increment`` *is* depends on what it is
    applied to, and :func:`~globin.domain.values.align_price` and
    :func:`~globin.domain.values.align_quantity` are separately named so the call
    site says so.

    **It carries no denomination.** A :class:`~globin.domain.values.Symbol` or
    :class:`~globin.domain.values.Currency` field would be this phase guessing the
    shape of the instrument registry that Phases 049-050 own. ADR-0030 already set
    that split: shape is validated here, membership is answered against the venue.

    The step's own exponent is preserved through alignment, so an increment of
    ``0.00010000`` yields aligned values spelled to eight places. That is
    deliberate: the trailing zeros are the venue's statement of its precision, and
    ADR-0030 refused a scaled integer precisely because it would discard them.
    """

    step: Decimal

    def __post_init__(self) -> None:
        """Validate the step."""
        _validate_step(self.step)

    def __str__(self) -> str:
        """Render the step in positional notation, keeping its trailing zeros."""
        return format(self.step, "f")


def increment(step: Decimal | int | str) -> Increment:
    """Build an :class:`Increment`, converting the step.

    Args:
        step: The grid spacing. A string is read exactly, so that
            ``increment("0.00010000")`` keeps the venue's stated precision; a
            :class:`float` is refused, because ``0.1`` is not a tenth.

    Returns:
        The increment.

    Raises:
        ValidationError: If ``step`` is of a type that cannot be exact, is a
            string this module will not read, or breaks any rule
            :class:`Increment` states.
    """
    return Increment(step=_decimal(step))


def add(left: Decimal, right: Decimal) -> Decimal:
    """The exact sum, or a refusal.

    Args:
        left: One addend.
        right: The other.

    Returns:
        The mathematically exact sum.

    Raises:
        ValidationError: If the exact sum cannot be held in
            :data:`EXACT_PRECISION` digits. It is refused rather than rounded,
            because rounding without being asked is what this module exists to
            prevent.
    """
    return _operate(_exact_context().add, left, right, "sum")


def subtract(left: Decimal, right: Decimal) -> Decimal:
    """The exact difference, or a refusal.

    Args:
        left: The value subtracted from.
        right: The value subtracted.

    Returns:
        The mathematically exact difference. It may be negative; whether that is
        an admissible *amount* is a question for the type being built from it,
        not for this function.

    Raises:
        ValidationError: If the exact difference cannot be held in
            :data:`EXACT_PRECISION` digits.
    """
    return _operate(_exact_context().subtract, left, right, "difference")


def multiply(left: Decimal, right: Decimal) -> Decimal:
    """The exact product, or a refusal.

    Args:
        left: One factor.
        right: The other.

    Returns:
        The mathematically exact product.

    Raises:
        ValidationError: If the exact product cannot be held in
            :data:`EXACT_PRECISION` digits, or escapes the context's exponent
            range.
    """
    return _operate(_exact_context().multiply, left, right, "product")


def is_aligned(amount: Decimal, *, to: Increment) -> bool:
    """Whether a magnitude already sits on a grid.

    Args:
        amount: The magnitude to test. Must be finite and non-negative.
        to: The grid.

    Returns:
        Whether ``amount`` is an exact multiple of the increment's step.

    Raises:
        ValidationError: If ``amount`` is not a finite, non-negative
            :class:`~decimal.Decimal`, or if the quotient is too long to compute
            exactly.

    The question :class:`Rounding.EXACT` answers by raising, for a caller who
    would rather branch than catch.
    """
    _require_magnitude(amount)
    return _remainder(amount, to) == 0


def align(amount: Decimal, *, to: Increment, rounding: Rounding) -> Decimal:
    """Put a magnitude onto a grid, in a named direction.

    Args:
        amount: The magnitude to align. Must be finite and non-negative.
        to: The grid to put it on.
        rounding: Which way to move it. Required and keyword-only: there is no
            default rounding mode anywhere in GLOBIN.

    Returns:
        The nearest admissible value in the requested direction, carrying the
        increment's own exponent so the venue's stated precision survives.

    Raises:
        ValidationError: If ``amount`` is not a finite, non-negative
            :class:`~decimal.Decimal`; if ``rounding`` is not a :class:`Rounding`
            member; if ``rounding`` is :attr:`Rounding.EXACT` and the value is not
            already on the grid; or if the quotient is too long to compute
            exactly.

    **No division is performed.** The implementation is
    :meth:`decimal.Context.divmod`, which is exact for every admissible pair and
    yields an integer quotient with exponent zero, so multiplying it back by the
    step reproduces the step's exponent rather than inventing one.

    A negative ``amount`` is refused rather than handled. ``Decimal``'s
    ``divmod`` truncates toward zero, so :attr:`Rounding.FLOOR` and
    :attr:`Rounding.CEILING` would each need a second implementation below zero —
    a decision that belongs to the phase that introduces signed money, which is
    **155**, not to this one.
    """
    mode = _require_rounding(rounding)
    _require_magnitude(amount)
    context = _exact_context()
    steps, remainder = _divide(amount, to, context)
    if remainder == 0:
        return _operate(context.multiply, steps, to.step, "aligned value")
    if mode is Rounding.EXACT:
        msg = (
            f"{amount} is not a multiple of {to}; it was required to be already "
            f"aligned, so it is refused rather than moved"
        )
        raise ValidationError(msg)
    upward = mode is Rounding.CEILING or (
        mode is Rounding.HALF_EVEN and _rounds_up(steps, remainder, to)
    )
    if upward:
        steps = _operate(context.add, steps, Decimal(1), "step count")
    return _operate(context.multiply, steps, to.step, "aligned value")


def _rounds_up(steps: Decimal, remainder: Decimal, to: Increment) -> bool:
    """Whether a half-even alignment moves away from zero.

    Args:
        steps: How many whole increments fit below the value.
        remainder: What is left over, strictly between zero and the step.
        to: The grid.

    Returns:
        Whether the value is past the midpoint, or exactly on it with an odd
        number of steps below.

    The midpoint is tested as ``2 * remainder`` against the step rather than as
    ``remainder`` against ``step / 2``, because doubling is exact and halving an
    odd step is not.
    """
    context = _exact_context()
    doubled = _operate(context.multiply, remainder, Decimal(2), "midpoint test")
    if doubled != to.step:
        return bool(doubled > to.step)
    return context.remainder(steps, Decimal(2)) != 0


def _divide(amount: Decimal, to: Increment, context: Context) -> tuple[Decimal, Decimal]:
    """How many whole increments fit below a magnitude, and what is left over.

    Args:
        amount: The magnitude.
        to: The grid.
        context: The exact context to compute in.

    Returns:
        The integer quotient and the remainder, both exact.

    Raises:
        ValidationError: If the quotient would need more than
            :data:`EXACT_PRECISION` digits. :mod:`decimal` signals that as
            ``DivisionImpossible`` and refuses rather than rounding, which is the
            behaviour this module wants; it is translated so the caller sees a
            GLOBIN error with the operands in it.
    """
    try:
        steps, remainder = context.divmod(amount, to.step)
    except DecimalException as fault:
        msg = (
            f"cannot place {amount} on a grid of {to} exactly: the quotient needs "
            f"more than {EXACT_PRECISION} digits"
        )
        raise ValidationError(msg) from fault
    return steps, remainder


def _remainder(amount: Decimal, to: Increment) -> Decimal:
    """What is left of a magnitude after removing whole increments.

    Args:
        amount: The magnitude.
        to: The grid.

    Returns:
        The exact remainder.
    """
    return _divide(amount, to, _exact_context())[1]


def _operate(
    operation: Callable[[Decimal, Decimal], Decimal],
    left: Decimal,
    right: Decimal,
    label: str,
) -> Decimal:
    """Run one exact operation, translating every decimal signal into a refusal.

    Args:
        operation: A bound method of the context to compute in.
        left: The left operand.
        right: The right operand.
        label: What the result is, for the message.

    Returns:
        Whatever the operation returned, which is exact because inexactness is
        trapped.

    Raises:
        ValidationError: If the exact result cannot be represented. Every
            :class:`decimal.DecimalException` is caught, not only
            :class:`decimal.Inexact`, because ``Overflow`` and ``InvalidOperation``
            describe the same failure from the caller's side: the answer cannot be
            given exactly, so it is not given at all.
    """
    try:
        return operation(left, right)
    except DecimalException as fault:
        msg = (
            f"the exact {label} of {left} and {right} cannot be represented in "
            f"{EXACT_PRECISION} digits, so it is refused rather than rounded"
        )
        raise ValidationError(msg) from fault


def _validate_step(step: object) -> None:
    """Refuse any step that does not describe a usable grid.

    Args:
        step: The value stored on the field. Typed as :class:`object` because a
            caller constructing the dataclass directly can pass anything, and
            because a narrower annotation would let mypy prove the first guard
            unreachable — the same reason ``values._validate_amount`` does it.

    Raises:
        ValidationError: On the first rule the value breaks.
    """
    if not isinstance(step, Decimal):
        msg = (
            f"increment step is {type(step).__name__}; build it through "
            f"increment(), which converts and refuses in one place"
        )
        raise ValidationError(msg)
    if not step.is_finite():
        msg = f"increment step is {step}; a grid spacing must be a finite number"
        raise ValidationError(msg)
    if step <= 0:
        msg = (
            f"increment step is {step}; a step must be strictly positive, "
            f"because zero describes no grid and a sign belongs to a Side"
        )
        raise ValidationError(msg)
    magnitude = step.adjusted()
    if abs(magnitude) > MAX_INCREMENT_EXPONENT:
        msg = (
            f"increment step has magnitude 1E{magnitude:+}, beyond "
            f"1E+{MAX_INCREMENT_EXPONENT}; no venue quotes a grid that size"
        )
        raise ValidationError(msg)
    digits = len(step.as_tuple().digits)
    if digits > MAX_INCREMENT_DIGITS:
        msg = (
            f"increment step carries {digits} significant digits, more than "
            f"{MAX_INCREMENT_DIGITS}; one that long usually came from a float"
        )
        raise ValidationError(msg)


def _exact_context() -> Context:
    """A decimal context in which rounding raises instead of happening.

    Returns:
        A fresh :class:`decimal.Context` at :data:`EXACT_PRECISION` digits, with
        every signal that would mean a lost or invented digit trapped.

    Built fresh on every call, for two independent reasons. A ``Context``
    accumulates flags as it is used, so a shared module-level one would be mutable
    global state — the thing ``ENGINEERING_CONTRACT.md`` invariant 5 forbids and
    the reason ``values.py`` refuses to read :func:`decimal.getcontext`. And
    constructing one is a call, which no layer module may perform at import
    (``tests/architecture/test_architecture_contract.py``), so it has to be a
    function whatever else were true. Measured at roughly 625 nanoseconds, which
    buys the guarantee cheaply.

    Constructed from explicit arguments rather than copied from
    :data:`decimal.DefaultContext`, so that the traps are the ones written here
    and not the ones CPython currently happens to arm.
    """
    return Context(
        prec=EXACT_PRECISION,
        Emin=EXACT_MIN_EXPONENT,
        Emax=EXACT_MAX_EXPONENT,
        traps=[Inexact, InvalidOperation, DivisionByZero, Overflow, Underflow],
    )


def _require_rounding(rounding: object) -> Rounding:
    """Refuse anything that is not one of the four modes.

    Args:
        rounding: What the caller passed. Typed as :class:`object` so the check
            is a real one rather than something mypy proves unreachable.

    Returns:
        The mode.

    Raises:
        ValidationError: If ``rounding`` is not a :class:`Rounding` member.

    A :class:`enum.StrEnum` member equals its own value, so
    ``Rounding.FLOOR == "FLOOR"`` is true — but ``isinstance("FLOOR", Rounding)``
    is false, which is what lets this refuse the string while the comparison
    still reads naturally. It is also what refuses ``decimal.ROUND_HALF_UP``: a
    mode this project did not choose arrives as a plain string and is turned away
    by name.
    """
    if not isinstance(rounding, Rounding):
        permitted = ", ".join(member.value for member in Rounding)
        msg = (
            f"rounding is {rounding!r}; pass a Rounding member, one of "
            f"{permitted}. A decimal.ROUND_* string is not one of them"
        )
        raise ValidationError(msg)
    return rounding


def _require_magnitude(amount: object) -> None:
    """Refuse anything that is not a finite, non-negative decimal.

    Args:
        amount: What the caller passed.

    Raises:
        ValidationError: If ``amount`` is not a :class:`~decimal.Decimal`, is not
            finite, or is negative.

    ``is_signed`` is tested rather than ``< 0`` because ``Decimal('-0')`` is
    signed *and* equal to zero, so a comparison would admit a value that renders
    as ``-0`` — the same reasoning ``values.py`` gives for the same test.
    """
    if not isinstance(amount, Decimal):
        msg = f"amount is {type(amount).__name__}; alignment works on a Decimal"
        raise ValidationError(msg)
    if not amount.is_finite():
        msg = f"amount is {amount}; a non-finite value sits on no grid"
        raise ValidationError(msg)
    if amount.is_signed():
        msg = (
            f"amount is {amount}; alignment is defined for magnitudes, and a "
            f"signed one is Phase 155's question rather than this module's"
        )
        raise ValidationError(msg)


def _decimal(value: object) -> Decimal:
    """Convert what a caller supplied into an exact decimal, or refuse it.

    Args:
        value: A :class:`~decimal.Decimal`, an :class:`int`, or a string spelled
            from :data:`INCREMENT_ALPHABET`.

    Returns:
        The value as a :class:`~decimal.Decimal`, not yet checked for sign or
        length — :meth:`Increment.__post_init__` does that, so that direct
        construction is refused on the same terms.

    Raises:
        ValidationError: If ``value`` is of a type that cannot be exact, or is a
            string this module will not read.

    :class:`bool` is refused explicitly and before :class:`int`, because
    ``isinstance(True, int)`` is true and ``Decimal(True)`` is one.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        return _decimal_from_text(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    remedy = (
        f" Pass the exact text instead: Decimal({value!r}) is {Decimal(value)}."
        if isinstance(value, float)
        else ""
    )
    msg = (
        f"increment step is {type(value).__name__}; expected a Decimal, an int, "
        f"or a decimal string.{remedy}"
    )
    raise ValidationError(msg)


def _decimal_from_text(text: str) -> Decimal:
    """Read an increment from text, refusing anything this module will not spell.

    Args:
        text: The candidate.

    Returns:
        The value it denotes.

    Raises:
        ValidationError: If ``text`` contains a character outside
            :data:`INCREMENT_ALPHABET`, or is spelled from that alphabet but is
            still not a number.
    """
    stray = sorted(set(text) - set(INCREMENT_ALPHABET))
    if stray:
        msg = (
            f"increment step {text!r} contains {stray}; write digits, an optional "
            f"sign, a point and an optional exponent, and nothing else"
        )
        raise ValidationError(msg)
    try:
        return Decimal(text)
    except InvalidOperation:
        msg = f"increment step {text!r} is not a number"
        raise ValidationError(msg) from None
