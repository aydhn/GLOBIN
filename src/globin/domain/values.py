"""The vocabulary GLOBIN counts in: sides, currencies, symbols, prices and quantities.

A number on its own carries no unit. ``60000`` could be a price in USDT, a
quantity of a token, or a millisecond offset, and nothing stops one being passed
where another is expected. This module gives each of them a type, so that the
mistake is refused rather than traded on.

The five types are *denominated*, not merely distinct. A :class:`Quantity` knows
which asset it counts and a :class:`Price` knows which pair it prices, because
the confusion this phase exists to prevent is not only "a price where a quantity
belongs" but "a price in USDT compared against a price in EUR". A bare magnitude
in a wrapper would catch the first and miss the second.

*Arithmetic is exact, or it is refused.* An operator spelled ``a + b`` reads the
caller's thread-local context and may round without saying so —
``Decimal('1E+30') + Decimal('1E-30')`` returns ``1E+30`` under the default
context, silently discarding the addend, which is the loss
``ENGINEERING_CONTRACT.md`` invariant 22 forbids. Phase 008 answered by defining
no operators at all and deferring to Phase 010.

Phase 010's answer is :mod:`globin.domain.precision`, and the methods of an
explicitly built :class:`decimal.Context`. A ``Context`` method takes its
precision and its traps from the object it is called on and touches no
thread-local state at all — measured, and recorded in
``docs/research/phase_010_sources.md``. That is what makes exact arithmetic
possible here without the ambient-state problem ADR-0031 raised against it: this
module never calls :func:`decimal.getcontext` or :func:`decimal.localcontext`,
and an architecture test refuses either anywhere under ``src/globin``.

:meth:`Quantity.__add__` and :meth:`Quantity.__sub__` are therefore exact or they
raise, and neither takes a rounding mode because neither rounds. Rounding is a
separate step with a name and a required argument (ADR-0037).

Three things remain deliberately absent.

*There is no arithmetic on a price.* A :class:`Price` is strictly positive, so
the difference of two is not one; and the sum of two prices is not a price
either — what a caller wants from ``(a + b) / 2`` is an average, which is a
division and therefore needs a rounding mode. Signed money arrives with the
portfolio accounting of **Phases 155-156**. Valuing a quantity at a price is
:func:`notional`, named rather than spelled ``*`` because the result changes
denomination and an operator cannot show that.

*There is no registry.* :class:`Currency` validates the *shape* of a code and
nothing else. ``Currency("ZZZQ")`` succeeds, because whether a venue lists an
asset is a capability question answered against the venue (ADR-0006), never a
constant compiled into the domain layer. Canonical identifiers are **Phase 011**.

*There is no wire format.* A :class:`Symbol` is a pair of currencies. It is not
``"BTCUSDT"``, and it deliberately cannot become one here: that spelling is not
decodable without knowing which assets a venue quotes in — ``BTCUSDT`` could
split as ``BTC``/``USDT`` or ``BTCU``/``SDT`` — so it is an encoding requiring a
registry rather than a value. Venue formats arrive with **Phases 033-048**.

This module imports nothing outside :mod:`globin.errors` and :mod:`decimal`,
performs no I/O and holds no module-level call. ``decimal`` is absent from the
I/O-capable list in ``docs/architecture/dependency-rules.toml``, which is what
permits the import at all.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

from globin.domain import precision
from globin.domain.precision import Increment, Rounding
from globin.errors import ValidationError

CURRENCY_ALPHABET: Final[str] = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
"""The characters a currency code may contain.

Digits are permitted because real tickers contain them. Lowercase is not: one
spelling means one thing to search a log for, which is the same argument
``globin.domain.configuration`` makes for refusing ``"debug"`` where ``"DEBUG"``
is meant.

Written out rather than compiled as a regular expression because a module-level
:func:`re.compile` is a call, and ``tests/architecture/test_architecture_contract.py``
holds every layer package to performing no work at import.
"""

MIN_CURRENCY_CODE_LENGTH: Final[int] = 2
"""The shortest a currency code may be.

Two, not one: a single character is far more often a slicing bug than a ticker,
and refusing it costs nothing GLOBIN can name.
"""

MAX_CURRENCY_CODE_LENGTH: Final[int] = 16
"""The longest a currency code may be.

A generous ceiling stated as a bound on *shape*. It is not a claim about which
codes exist — that is Phase 011's register, not this module's business.
"""

DECIMAL_ALPHABET: Final[str] = "0123456789+-.eE"
"""The characters a decimal string may contain.

Narrower than what :class:`decimal.Decimal` itself accepts, and deliberately so.
``Decimal`` reads ``" 1 "`` as one, ``"1_000"`` as a thousand, and ``"NaN"`` and
``"Infinity"`` as values that compare in ways no price should. None of those
characters appear here, so all four are refused before ``Decimal`` ever sees
them. Everything ``Decimal.__str__`` emits for a finite value is spelled from
this alphabet, which a property test asserts by round trip.
"""

MAX_SIGNIFICANT_DIGITS: Final[int] = 28
"""How many significant digits a value may carry.

This is the guard that catches a value derived from binary floating point:
``Decimal(1.1)`` is exactly ``1.100000000000000088817841970012523233890533447265625``,
fifty-one digits, and it arrives already typed as a ``Decimal`` where the float
refusal below cannot see it.

Stated as a constant rather than read from :func:`decimal.getcontext`, because
refusal that depends on ambient thread-local state is the hidden global state
``ENGINEERING_CONTRACT.md`` invariant 5 forbids. It is a fail-closed bound, not
a rounding policy: a value too long to be held exactly is one whose first
arithmetic operation would silently round it. What to *do* about precision is
:mod:`globin.domain.precision`, which derives :data:`~globin.domain.precision.EXACT_PRECISION`
from this bound and refuses any result that would exceed it.
"""

MAX_ADJUSTED_EXPONENT: Final[int] = 30
"""How far from one a value's magnitude may sit, in powers of ten.

Without this bound ``Decimal('1E+999999999')`` is finite, positive and one
significant digit long, so every other rule here admits it — and then
``format(value, 'f')`` renders it as a billion characters. That is not a
cosmetic problem: the refusal messages below interpolate the value, so two such
amounts compared against each other would build the enormous string on the
*error* path. Measured: ``1E+100000`` renders to 100 001 characters.

The bound is symmetric, so ``1E-30`` is the smallest magnitude admitted and
:meth:`decimal.Decimal.is_subnormal` becomes unreachable — which is the point.
Subnormality is defined against the ambient context's ``Emin``, and a refusal
that moves when a caller changes a thread-local setting is the hidden global
state invariant 5 forbids. :meth:`decimal.Decimal.adjusted` is documented as
unaffected by context, so this rule means the same thing everywhere.

Thirty is a judgement, and a deliberately loose one: it is roughly eighteen
orders of magnitude beyond the largest quantity of any asset a venue quotes.
It is a bound on what can be *represented*, not a limit on what may be traded —
risk ceilings remain Phase 242, and rounding is
:mod:`globin.domain.precision`. A later phase that finds it too tight should
widen it with the case that showed why, not delete it — and must check
:data:`~globin.domain.precision.EXACT_PRECISION`, which is derived from this
number and from :data:`MAX_SIGNIFICANT_DIGITS`.
"""

SYMBOL_SEPARATOR: Final[str] = "/"
"""What separates the two halves of a rendered symbol.

The separator is what keeps :meth:`Symbol.__str__` from being mistaken for a
venue format. ``"BTC/USDT"`` is not something Binance would accept, so a later
phase cannot reach for :func:`str` and have it appear to work.
"""


class Side(StrEnum):
    """Which way round a piece of work goes.

    Direction lives here and never in the sign of a number. That is what allows
    :class:`Quantity` to refuse a negative amount: an amount says how much, and
    a side says which way, and collapsing the two into one signed number is how
    a sell becomes a buy under a stray negation.

    The uppercase spelling is chosen to match :class:`Currency`, not because any
    venue spells it this way. No wire format is decided here — see the module
    docstring.
    """

    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "Side":
        """The other side.

        Returns:
            :attr:`SELL` for :attr:`BUY` and :attr:`BUY` for :attr:`SELL`.
        """
        return Side.SELL if self is Side.BUY else Side.BUY


@dataclass(frozen=True, slots=True)
class Currency:
    """An asset code, validated for shape and nothing else.

    Args:
        code: The ticker, in uppercase, such as ``"BTC"`` or ``"USDT"``.

    Raises:
        ValidationError: If ``code`` is outside the length bounds or contains a
            character outside :data:`CURRENCY_ALPHABET`.

    Not a subclass of :class:`str`, for the reason ADR-0022 gives about
    exceptions and builtins: ``Currency("BTC") == "BTC"`` would let one pass
    anywhere a string is wanted and reintroduce exactly the confusion this
    module exists to prevent.

    There is no ordering. Assets have no meaningful order, and defining an
    alphabetical one invites a report sorted by it and called canonical, which
    is Phase 011's question rather than this module's.
    """

    code: str

    def __post_init__(self) -> None:
        """Validate the code's length and alphabet."""
        if not MIN_CURRENCY_CODE_LENGTH <= len(self.code) <= MAX_CURRENCY_CODE_LENGTH:
            msg = (
                f"currency code {self.code!r} is {len(self.code)} characters; "
                f"expected between {MIN_CURRENCY_CODE_LENGTH} and {MAX_CURRENCY_CODE_LENGTH}"
            )
            raise ValidationError(msg)
        stray = sorted(set(self.code) - set(CURRENCY_ALPHABET))
        if stray:
            msg = (
                f"currency code {self.code!r} contains {stray}; "
                f"codes are uppercase letters and digits"
            )
            raise ValidationError(msg)

    def __str__(self) -> str:
        """Return the code itself."""
        return self.code


@dataclass(frozen=True, slots=True)
class Symbol:
    """A market: one asset priced in another.

    Args:
        base: The asset being bought or sold.
        quote: The asset it is priced in.

    Raises:
        ValidationError: If either argument is not a :class:`Currency`, or if
            ``base`` and ``quote`` are the same asset.

    There is no ordering and no ``from_string``. See the module docstring for
    why the concatenated venue spelling is not a value type.
    """

    base: Currency
    quote: Currency

    def __post_init__(self) -> None:
        """Validate that both halves are currencies and that they differ."""
        _require(self.base, Currency, label="symbol base", remedy="pass a Currency")
        _require(self.quote, Currency, label="symbol quote", remedy="pass a Currency")
        if self.base == self.quote:
            msg = f"symbol has {self.base} on both sides; an asset is not a market against itself"
            raise ValidationError(msg)

    def __str__(self) -> str:
        """Render the pair for a human or a log, never for a venue."""
        return f"{self.base}{SYMBOL_SEPARATOR}{self.quote}"


@dataclass(frozen=True, slots=True)
class Quantity:
    """An amount of one asset.

    Args:
        amount: How much, as an exact :class:`decimal.Decimal`. Zero is
            permitted — a zero balance is a real answer.
        currency: Which asset is being counted.

    Raises:
        ValidationError: If ``amount`` is not a finite, non-negative
            :class:`~decimal.Decimal` within :data:`MAX_SIGNIFICANT_DIGITS`, or
            if ``currency`` is not a :class:`Currency`.

    Because every balance, fee and order size in GLOBIN is an amount of an
    asset, this is also the money type. There is deliberately no separate
    ``Money``: a second type carrying the same pair of fields would need a rule
    for when each applies, and that rule is the thing that drifts.

    Comparison against a :class:`Quantity` of a different asset raises rather
    than answering. See :meth:`__lt__`.
    """

    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        """Validate the amount and the currency."""
        _validate_amount(self.amount, label="quantity amount", allow_zero=True)
        _require(
            self.currency,
            Currency,
            label="quantity currency",
            remedy="pass a Currency, not the code on its own",
        )

    def __str__(self) -> str:
        """Render the amount and its asset."""
        return f"{format(self.amount, 'f')} {self.currency}"

    def _comparable(self, other: object, operator: str, verb: str = "compare") -> Decimal | None:
        """The other amount when the operation is meaningful.

        Args:
            other: Whatever appeared on the right of the operator.
            operator: The operator's spelling, for the message.
            verb: What the caller was attempting, for the message. Comparison and
                arithmetic admit exactly the same pairs for exactly the same
                reason, and differ only in how the refusal should read.

        Returns:
            ``other``'s amount, or ``None`` when ``other`` is not a
            :class:`Quantity` at all — in which case the caller returns
            ``NotImplemented`` and Python raises a :class:`TypeError` naming
            both types.

        Raises:
            ValidationError: If both are quantities but of different assets.
                That case is not ``NotImplemented``: the types match, so mypy
                could not have refused it and Python's own message would say
                only that ``<`` is unsupported between two ``Quantity``
                instances, which tells the caller nothing.
        """
        if not isinstance(other, Quantity):
            return None
        if other.currency != self.currency:
            msg = (
                f"cannot {verb} {self} with {other} using {operator!r}: they count different assets"
            )
            raise ValidationError(msg)
        return other.amount

    def __lt__(self, other: object) -> bool:
        """Whether this is less than another quantity of the same asset."""
        amount = self._comparable(other, "<")
        return NotImplemented if amount is None else self.amount < amount

    def __le__(self, other: object) -> bool:
        """Whether this is at most another quantity of the same asset."""
        amount = self._comparable(other, "<=")
        return NotImplemented if amount is None else self.amount <= amount

    def __gt__(self, other: object) -> bool:
        """Whether this is greater than another quantity of the same asset."""
        amount = self._comparable(other, ">")
        return NotImplemented if amount is None else self.amount > amount

    def __ge__(self, other: object) -> bool:
        """Whether this is at least another quantity of the same asset."""
        amount = self._comparable(other, ">=")
        return NotImplemented if amount is None else self.amount >= amount

    def __add__(self, other: object) -> "Quantity":
        """The total of two quantities of the same asset.

        Args:
            other: The quantity to add.

        Returns:
            A new :class:`Quantity`, of the same asset.

        Raises:
            ValidationError: If ``other`` counts a different asset, or if the
                exact total is outside the bounds a quantity may carry.

        Balances add, fills add and fees add, which is why this is the one
        arithmetic operator the system genuinely needs. It rounds nothing: the
        sum is computed exactly by :func:`globin.domain.precision.add` and then
        admitted by :meth:`__post_init__` on the same terms as the operands, so a
        total too long to hold exactly is refused rather than truncated.
        """
        amount = self._comparable(other, "+", verb="add")
        if amount is None:
            return NotImplemented
        return Quantity(amount=precision.add(self.amount, amount), currency=self.currency)

    def __sub__(self, other: object) -> "Quantity":
        """What remains after taking one quantity from another of the same asset.

        Args:
            other: The quantity to take away.

        Returns:
            A new :class:`Quantity`, of the same asset.

        Raises:
            ValidationError: If ``other`` counts a different asset, or if the
                difference is negative.

        A negative result is not a quantity — direction is a :class:`Side`, which
        is ADR-0030's decision and not this operator's to revisit — so
        :meth:`__post_init__` refuses it. "You cannot spend more than you hold"
        is therefore a fact about the type rather than a check somebody has to
        remember to write.
        """
        amount = self._comparable(other, "-", verb="subtract")
        if amount is None:
            return NotImplemented
        return Quantity(amount=precision.subtract(self.amount, amount), currency=self.currency)


@dataclass(frozen=True, slots=True)
class Price:
    """What one unit of an asset costs, in the asset it is quoted against.

    Args:
        amount: How much, as an exact :class:`decimal.Decimal`. Strictly
            positive — zero is a sentinel rather than a price, and a caller who
            means "no price" should say so with absence.
        symbol: The market being priced.

    Raises:
        ValidationError: If ``amount`` is not a finite, strictly positive
            :class:`~decimal.Decimal` within :data:`MAX_SIGNIFICANT_DIGITS`, or
            if ``symbol`` is not a :class:`Symbol`.

    The denomination is the whole pair, not just the quote currency. ``60000
    USDT`` does not say what costs that much; ``60000 USDT per BTC`` does, and
    comparing a BTC price against an ETH price is then refused rather than
    answered.
    """

    amount: Decimal
    symbol: Symbol

    def __post_init__(self) -> None:
        """Validate the amount and the symbol."""
        _validate_amount(self.amount, label="price amount", allow_zero=False)
        _require(
            self.symbol,
            Symbol,
            label="price symbol",
            remedy="pass a Symbol, so that the price says what it prices",
        )

    @property
    def quote(self) -> Currency:
        """The currency the amount is denominated in."""
        return self.symbol.quote

    def __str__(self) -> str:
        """Render the amount, the currency it is in, and what it prices."""
        return f"{format(self.amount, 'f')} {self.symbol.quote} per {self.symbol.base}"

    def _comparable(self, other: object, operator: str) -> Decimal | None:
        """The other amount when the comparison is meaningful.

        Args:
            other: Whatever appeared on the right of the operator.
            operator: The operator's spelling, for the message.

        Returns:
            ``other``'s amount, or ``None`` when ``other`` is not a
            :class:`Price`.

        Raises:
            ValidationError: If both are prices but of different markets. See
                :meth:`Quantity._comparable` for why this is not
                ``NotImplemented``.
        """
        if not isinstance(other, Price):
            return None
        if other.symbol != self.symbol:
            msg = (
                f"cannot compare {self} with {other} using {operator!r}: "
                f"they price different markets"
            )
            raise ValidationError(msg)
        return other.amount

    def __lt__(self, other: object) -> bool:
        """Whether this is less than another price of the same market."""
        amount = self._comparable(other, "<")
        return NotImplemented if amount is None else self.amount < amount

    def __le__(self, other: object) -> bool:
        """Whether this is at most another price of the same market."""
        amount = self._comparable(other, "<=")
        return NotImplemented if amount is None else self.amount <= amount

    def __gt__(self, other: object) -> bool:
        """Whether this is greater than another price of the same market."""
        amount = self._comparable(other, ">")
        return NotImplemented if amount is None else self.amount > amount

    def __ge__(self, other: object) -> bool:
        """Whether this is at least another price of the same market."""
        amount = self._comparable(other, ">=")
        return NotImplemented if amount is None else self.amount >= amount


def _require(value: object, expected: type, *, label: str, remedy: str) -> None:
    """Refuse a field whose type is wrong, however it was constructed.

    Args:
        value: What was supplied. Typed as :class:`object` so that the check is
            a real one: a parameter typed as the expected class would make the
            test redundant to mypy, and mypy is configured to say so.
        expected: The class the field must hold.
        label: How to name the field in a message.
        remedy: What the caller should do instead.

    Raises:
        ValidationError: If ``value`` is not an instance of ``expected``.

    The dataclasses here annotate their fields, so mypy already refuses the
    wrong type at every call site it can see. This exists for the call sites it
    cannot: a value read from a document, or a test constructing the class
    directly to prove the refusal happens.
    """
    if not isinstance(value, expected):
        msg = f"{label} is {type(value).__name__}; {remedy}"
        raise ValidationError(msg)


def _validate_amount(amount: object, *, label: str, allow_zero: bool) -> None:
    """Refuse any amount that is not an exact, representable, non-negative decimal.

    Args:
        amount: The value stored on the field. Typed as :class:`object` because
            a caller constructing the dataclass directly can pass anything.
        label: How to name the field in a message.
        allow_zero: Whether zero is a legitimate value.

    Raises:
        ValidationError: On the first rule the value breaks.

    The order of the checks matters. ``is_signed`` is tested rather than
    ``< 0`` because ``Decimal('-0')`` is signed *and* equal to zero, so a
    comparison would admit a value that renders as ``-0``.
    """
    if not isinstance(amount, Decimal):
        msg = (
            f"{label} is {type(amount).__name__}; construct it through the "
            f"matching factory, which converts and refuses in one place"
        )
        raise ValidationError(msg)
    if not amount.is_finite():
        msg = (
            f"{label} is {amount}; a non-finite value compares in ways no "
            f"amount should — NaN is unequal to itself and ordering it raises"
        )
        raise ValidationError(msg)
    if amount.is_signed():
        msg = f"{label} is {amount}; amounts are never negative, because direction is a Side"
        raise ValidationError(msg)
    if not allow_zero and amount == 0:
        msg = f"{label} is zero; a zero price is a sentinel, so say absence instead"
        raise ValidationError(msg)
    magnitude = amount.adjusted()
    if abs(magnitude) > MAX_ADJUSTED_EXPONENT:
        msg = (
            f"{label} has magnitude 1E{magnitude:+}, beyond "
            f"1E+{MAX_ADJUSTED_EXPONENT}; no venue quotes a number that size, and "
            f"rendering one would produce a string nobody asked for"
        )
        raise ValidationError(msg)
    digits = len(amount.as_tuple().digits)
    if digits > MAX_SIGNIFICANT_DIGITS:
        msg = (
            f"{label} carries {digits} significant digits, more than "
            f"{MAX_SIGNIFICANT_DIGITS}; a value this long cannot be held exactly, "
            f"and one that long usually came from a float"
        )
        raise ValidationError(msg)


def _decimal(value: object, label: str) -> Decimal:
    """Convert what a caller supplied into an exact decimal, or refuse it.

    Args:
        value: A :class:`~decimal.Decimal`, an :class:`int`, or a string spelled
            from :data:`DECIMAL_ALPHABET`.
        label: How to name the field in a message.

    Returns:
        The value as a :class:`~decimal.Decimal`. Not yet checked for sign,
        finiteness or length — :func:`_validate_amount` does that, so that
        direct construction is refused on the same terms.

    Raises:
        ValidationError: If ``value`` is of a type that cannot be exact, or is
            a string this module will not read.

    :class:`bool` is refused explicitly and before :class:`int`, because
    ``isinstance(True, int)`` is true and ``Decimal(True)`` is one.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        return _decimal_from_text(value, label)
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    remedy = (
        f" Pass the exact text instead: Decimal({value!r}) is {Decimal(value)}."
        if isinstance(value, float)
        else ""
    )
    msg = (
        f"{label} is {type(value).__name__}; expected a Decimal, an int, or a "
        f"decimal string.{remedy}"
    )
    raise ValidationError(msg)


def _decimal_from_text(text: str, label: str) -> Decimal:
    """Read a decimal from text, refusing anything this module will not spell.

    Args:
        text: The candidate.
        label: How to name the field in a message.

    Returns:
        The value it denotes.

    Raises:
        ValidationError: If ``text`` contains a character outside
            :data:`DECIMAL_ALPHABET`, or is spelled from that alphabet but is
            still not a number.
    """
    stray = sorted(set(text) - set(DECIMAL_ALPHABET))
    if stray:
        msg = (
            f"{label} {text!r} contains {stray}; write digits, an optional sign, "
            f"a point and an optional exponent, and nothing else"
        )
        raise ValidationError(msg)
    try:
        return Decimal(text)
    except InvalidOperation:
        msg = f"{label} {text!r} is not a number"
        raise ValidationError(msg) from None


def currency(code: str) -> Currency:
    """Build a :class:`Currency` from its code.

    Args:
        code: The ticker, in uppercase.

    Returns:
        The currency.

    Raises:
        ValidationError: As :class:`Currency`.
    """
    return Currency(code=code)


def symbol(base: str | Currency, quote: str | Currency) -> Symbol:
    """Build a :class:`Symbol` from two codes or two currencies.

    Args:
        base: The asset being traded, or its code.
        quote: The asset it is priced in, or its code.

    Returns:
        The market.

    Raises:
        ValidationError: As :class:`Currency` and :class:`Symbol`.
    """
    return Symbol(
        base=base if isinstance(base, Currency) else Currency(code=base),
        quote=quote if isinstance(quote, Currency) else Currency(code=quote),
    )


def quantity(amount: Decimal | int | str, asset: str | Currency) -> Quantity:
    """Build a :class:`Quantity`, converting the amount and the asset.

    Args:
        amount: How much. A string is read exactly; a float is refused.
        asset: What is being counted, or its code.

    Returns:
        The quantity.

    Raises:
        ValidationError: As :func:`_decimal`, :func:`_validate_amount` and
            :class:`Currency`.
    """
    return Quantity(
        amount=_decimal(amount, "quantity amount"),
        currency=asset if isinstance(asset, Currency) else Currency(code=asset),
    )


def price(amount: Decimal | int | str, market: Symbol) -> Price:
    """Build a :class:`Price`, converting the amount.

    Args:
        amount: How much one unit of the base asset costs. A string is read
            exactly; a float is refused.
        market: The pair being priced. A :class:`Symbol`, never a string —
            there is no single-string spelling of a market, by design.

    Returns:
        The price.

    Raises:
        ValidationError: As :func:`_decimal` and :func:`_validate_amount`.
    """
    return Price(amount=_decimal(amount, "price amount"), symbol=market)


def notional(unit_price: Price, amount: Quantity) -> Quantity:
    """What a quantity of an asset is worth at a price.

    Args:
        unit_price: What one unit of the base asset costs.
        amount: How much of that asset is being valued.

    Returns:
        A :class:`Quantity` denominated in the price's **quote** asset:
        ``60000 USDT per BTC`` and ``2 BTC`` give ``120000 USDT``.

    Raises:
        ValidationError: If either argument is of the wrong type, if ``amount``
            counts an asset this price does not price, or if the exact product is
            outside the bounds a quantity may carry.

    Named rather than spelled ``*``, because the result changes denomination and
    an operator cannot show that. A reader of ``a * b`` has no way to see that
    the answer is in a third currency, and a reader of ``notional(p, q)`` can be
    told.

    This is also the operation that vindicates ADR-0030. The check below — that
    the quantity counts the asset this price actually prices — is expressible
    only because both values carry their denomination. Without that it would be a
    comment, and comments do not raise.
    """
    _require(unit_price, Price, label="notional price", remedy="pass a Price")
    _require(amount, Quantity, label="notional quantity", remedy="pass a Quantity")
    if amount.currency != unit_price.symbol.base:
        msg = (
            f"cannot value {amount} at {unit_price}: this price prices "
            f"{unit_price.symbol.base}, not {amount.currency}"
        )
        raise ValidationError(msg)
    return Quantity(
        amount=precision.multiply(unit_price.amount, amount.amount),
        currency=unit_price.symbol.quote,
    )


def align_price(held: Price, *, tick: Increment, rounding: Rounding) -> Price:
    """Put a price onto its market's tick grid.

    Args:
        held: The price to align.
        tick: The market's tick size.
        rounding: Which way to move it. Required and keyword-only.

    Returns:
        A :class:`Price` on the grid, for the same market.

    Raises:
        ValidationError: If ``held`` is not a :class:`Price`, if ``rounding`` is
            not a :class:`~globin.domain.precision.Rounding` member, if the
            rounding is ``EXACT`` and the price is not already aligned, or if the
            aligned value is not a price — flooring a price below one tick gives
            zero, and zero is a sentinel rather than a price.

    The tick is not checked against the market, because nothing here knows which
    tick belongs to which market. That pairing is venue data, and the instrument
    registry that owns it is **Phases 049-050**.
    """
    _require(held, Price, label="aligned price", remedy="pass a Price")
    return Price(
        amount=precision.align(held.amount, to=tick, rounding=rounding),
        symbol=held.symbol,
    )


def align_quantity(held: Quantity, *, step: Increment, rounding: Rounding) -> Quantity:
    """Put a quantity onto its asset's step grid.

    Args:
        held: The quantity to align.
        step: The step size the quantity must be a multiple of.
        rounding: Which way to move it. Required and keyword-only.

    Returns:
        A :class:`Quantity` on the grid, of the same asset.

    Raises:
        ValidationError: If ``held`` is not a :class:`Quantity`, if ``rounding``
            is not a :class:`~globin.domain.precision.Rounding` member, or if the
            rounding is ``EXACT`` and the quantity is not already aligned.

    Unlike :func:`align_price`, flooring to zero is admissible here: a zero
    quantity is a real answer, and "your order rounds down to nothing" is
    precisely what a caller needs to be told rather than shielded from.
    """
    _require(held, Quantity, label="aligned quantity", remedy="pass a Quantity")
    return Quantity(
        amount=precision.align(held.amount, to=step, rounding=rounding),
        currency=held.currency,
    )
