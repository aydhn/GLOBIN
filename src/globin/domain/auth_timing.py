r"""The two timing values a signed request carries, and nothing that reads a clock.

Binance requires every ``SIGNED`` request to carry a ``timestamp``, and optionally
a ``recvWindow`` bounding how long it stays valid. This module holds both as types
and holds no clock at all: :class:`~globin.ports.clock.Clock` already exists, and
its own docstring says why nothing new is needed here —

    *"A clock that reports Binance's server time can honestly implement*
    :class:`~globin.ports.clock.Clock`\\ *."*

So Phase 040's synchronised clock is injected where the host clock is injected
today, with no signature in this phase changing. Inventing a second
``TimestampProvider`` protocol beside it would create two ports for one question
and give the later phase two places to plug into.

**What this phase deliberately does not do**, restated because a reader looking
for it should find the refusal rather than an absence: no server time is sampled,
no offset is estimated, no round trip is corrected for and no drift is measured.
The venue's own processing rule is quoted in
``docs/research/phase_035_sources.md`` S-02 and is **recorded rather than
implemented**, because it is written in terms of ``serverTime`` and GLOBIN does not
have one.

**:class:`RecvWindow` carries a** :class:`~decimal.Decimal`, which is the whole
reason it is a type. The venue documents *"up to three decimal places of
precision (e.g., 6000.346)"*, and three decimal places of a millisecond is a value
a binary float cannot hold exactly — ``6000.346`` is not representable, so a float
round-trip changes the number the venue is asked to honour.
``docs/VALUE_TYPES_POLICY.md`` already forbids a float near a quantity a venue
compares against a bound, and this is one.

**Nothing here lets an operator raise the window to fix a clock.** The ceiling is
the venue's own 60000 and it is enforced at construction, so a configuration
carrying a larger number fails before a request is built rather than being clamped
into something the operator did not write.
"""

from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

from globin.domain.clock import Instant
from globin.errors import ValidationError

RECV_WINDOW_PARAMETER: Final[str] = "recvWindow"
"""What the venue calls the validity window. Its exact documented spelling."""

TIMESTAMP_PARAMETER: Final[str] = "timestamp"
"""What the venue calls the request's moment. Its exact documented spelling."""

DEFAULT_RECV_WINDOW_MILLIS: Final[str] = "5000"
"""The window the venue applies when none is sent, as text rather than a number.

Quoted: *"If ``recvWindow`` is not sent, **it defaults to 5000 milliseconds**."*

A string because :class:`~decimal.Decimal` construction is a call and a layer
package performs none at import — the same constraint
:mod:`globin.domain.rest` records for ``field(default_factory=...)``. Callers reach
it through :func:`default_recv_window`.
"""

MAX_RECV_WINDOW_MILLIS: Final[str] = "60000"
"""The largest window the venue accepts, as text.

Quoted: *"Maximum ``recvWindow`` is 60000 milliseconds."* The documentation adds,
in bold, *"It is recommended to use a small recvWindow of 5000 or less! The max
cannot go beyond 60,000!"* — so this is a hard ceiling rather than guidance, and it
is enforced rather than warned about.
"""

MAX_RECV_WINDOW_DECIMALS: Final[int] = 3
"""How many decimal places the venue accepts on the window.

Quoted: *"``recvWindow`` supports up to three decimal places of precision (e.g.,
6000.346) so that microseconds may be specified."*

Enforced as a refusal rather than by rounding. A window of ``5000.1234`` is a
value the operator wrote and the venue does not accept; quietly truncating it to
``5000.123`` would send a bound nobody chose, and rounding it up would send one
larger than the operator asked for.
"""


class TimestampUnit(StrEnum):
    """Which unit a request's ``timestamp`` is expressed in.

    Two members, and both are documented: *"a ``timestamp`` parameter which should
    be the current timestamp either in milliseconds or microseconds."*

    Distinct from :class:`~globin.domain.rest.TimeUnitPreference`, which asks the
    venue what unit to answer **in** and has a third member for *ask for nothing*.
    This one says what GLOBIN **sends**, where there is no such thing as sending
    nothing — a signed request without a timestamp is refused by the venue. Two
    enums because they are two questions; merging them would give the request
    parameter a ``PROVIDER_DEFAULT`` member that could not be rendered.
    """

    MILLISECONDS = "milliseconds"
    """The documented default, and what every worked example in the venue's own
    documentation uses."""

    MICROSECONDS = "microseconds"
    """Documented and accepted. Chosen when a caller needs sub-millisecond
    resolution, which nothing in GLOBIN yet does."""


def default_recv_window() -> "RecvWindow":
    """The window the venue would apply if none were sent.

    Returns:
        Five thousand milliseconds.

    A function rather than a constant because constructing one is a call. GLOBIN
    sends this **explicitly** rather than relying on the venue's default: the
    parameter is part of the signature payload, so a window that is present in
    GLOBIN's record and absent from the request would be two different requests
    described by one diagnostic.
    """
    return RecvWindow(Decimal(DEFAULT_RECV_WINDOW_MILLIS))


def max_recv_window() -> "RecvWindow":
    """The largest window the venue accepts.

    Returns:
        Sixty thousand milliseconds.
    """
    return RecvWindow(Decimal(MAX_RECV_WINDOW_MILLIS))


def parse_recv_window(text: str) -> "RecvWindow":
    """Read a window from configuration text.

    Args:
        text: The window in milliseconds, as written by an operator.

    Returns:
        The window.

    Raises:
        ValidationError: If the text is not a decimal number, or if the number it
            names is not an acceptable window.

    **Text rather than a number, and that is the point.** A TOML float would have
    lost the third decimal place before this function ever saw it, and a TOML
    integer could not express one at all. Reading the operator's own characters and
    parsing them here means the value that reaches :class:`RecvWindow` is the value
    they wrote, and a value the venue would reject fails at the boundary with their
    text quoted back at them.
    """
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError, ArithmeticError) as fault:
        msg = (
            f"a recvWindow of {text!r} is not a decimal number of milliseconds; "
            "the venue accepts a number with at most three decimal places"
        )
        raise ValidationError(msg) from fault
    return RecvWindow(value)


class RecvWindow:
    """How long a signed request stays valid, in milliseconds.

    Args:
        millis: The window. Must be a :class:`~decimal.Decimal`.

    Raises:
        ValidationError: If ``millis`` is not a ``Decimal``, is not finite, is not
            positive, exceeds :data:`MAX_RECV_WINDOW_MILLIS`, or carries more than
            :data:`MAX_RECV_WINDOW_DECIMALS` decimal places.

    **A plain class rather than a frozen dataclass**, for the reason
    :mod:`globin.domain.rest` gives about ``QueryParameters``' optionality: the
    obvious ``@dataclass`` here would want a ``Decimal`` default, and a default is
    constructed in the class body, which is a call at import. Keeping the
    constructor explicit puts the arithmetic in a function body where it belongs
    and makes :func:`default_recv_window` the one place the default is spelled.

    **A ``float`` is refused rather than converted.** ``RecvWindow(6000.346)``
    would silently become ``6000.3459999999999...`` and then fail the decimal-place
    check with a message about a number the caller never wrote. Refusing the type
    outright gives them a message about the type they actually passed.
    """

    __slots__ = ("_millis",)

    def __init__(self, millis: object) -> None:
        """Build a window after checking the venue would accept it.

        Args:
            millis: The window in milliseconds. Typed as :class:`object` rather
                than :class:`~decimal.Decimal` so the type check below is a real
                one — :mod:`globin.domain.rest` draws the same distinction, for the
                same reason: an annotated parameter would make mypy prove the guard
                redundant and refuse to compile it, leaving the boundary unguarded
                for every caller mypy cannot see.

        Raises:
            ValidationError: As documented on the class.
        """
        if not isinstance(millis, Decimal):
            msg = (
                f"a recvWindow must be a Decimal and is {type(millis).__name__}; a float "
                "cannot hold the three decimal places the venue documents"
            )
            raise ValidationError(msg)
        if not millis.is_finite():
            msg = f"a recvWindow of {millis!r} is not a finite number of milliseconds"
            raise ValidationError(msg)
        if millis <= 0:
            msg = (
                f"a recvWindow of {millis} is not positive; a request must stay valid for "
                "some length of time"
            )
            raise ValidationError(msg)
        ceiling = Decimal(MAX_RECV_WINDOW_MILLIS)
        if millis > ceiling:
            msg = (
                f"a recvWindow of {millis} exceeds the documented maximum of {ceiling}; "
                "a wider window is not the remedy for a clock that disagrees with the venue"
            )
            raise ValidationError(msg)
        exponent = millis.as_tuple().exponent
        # `exponent` is `'n'`, `'N'` or `'F'` for a NaN or an infinity, which
        # `is_finite()` above has already refused. The check is repeated as a type
        # narrowing rather than trusted, because the alternative is a negation of a
        # string that mypy is right to refuse.
        if not isinstance(exponent, int) or -exponent > MAX_RECV_WINDOW_DECIMALS:
            msg = (
                f"a recvWindow of {millis} carries more than {MAX_RECV_WINDOW_DECIMALS} decimal "
                "places, which the venue does not accept"
            )
            raise ValidationError(msg)
        self._millis = millis

    @property
    def millis(self) -> Decimal:
        """The window, in milliseconds.

        Returns:
            The exact value this was built with, scale included.

        The scale survives because the venue sees the rendering: ``5000`` and
        ``5000.000`` are the same duration and two different strings, and the
        second is what gets signed if that is what the operator wrote.
        """
        return self._millis

    def __eq__(self, other: object) -> bool:
        """Compare two windows by value.

        Args:
            other: The object to compare against.

        Returns:
            ``True`` when both are windows of the same duration.

        Compared with ``==`` on the underlying ``Decimal``, so ``5000`` equals
        ``5000.000``. That is the right answer for *is this the same window* and
        the wrong one for *will these render identically*, which is why
        :meth:`__str__` exists separately and the rendering is what gets signed.
        """
        if not isinstance(other, RecvWindow):
            return NotImplemented
        return self._millis == other._millis

    def __hash__(self) -> int:
        """Hash by value, consistent with :meth:`__eq__`."""
        return hash(self._millis)

    def __str__(self) -> str:
        """Render as the venue will see it.

        Returns:
            Positional notation with the declared scale preserved — never
            scientific notation, matching
            :func:`globin.domain.rest.encode_value`'s rule for a ``Decimal``.
        """
        return format(self._millis, "f")

    def __repr__(self) -> str:
        """Render for a diagnostic."""
        return f"RecvWindow({self._millis})"

    def as_record(self) -> dict[str, object]:
        """This window as plain JSON-safe values.

        Returns:
            Its rendering and its decimal places. **A string rather than a
            number**, because a JSON reader would parse the number back into a
            float and undo the whole reason this is a ``Decimal``.
        """
        exponent = self._millis.as_tuple().exponent
        return {
            "millis": str(self),
            "decimal_places": -exponent if isinstance(exponent, int) else 0,
        }


def stamp(moment: Instant, unit: TimestampUnit) -> int:
    """A moment as the integer a request's ``timestamp`` parameter carries.

    Args:
        moment: When the request is being made, from a
            :class:`~globin.ports.clock.Clock`.
        unit: Which unit to express it in.

    Returns:
        The count since the Unix epoch, in the requested unit.

    Total over both members, so there is no branch in which a timestamp is
    absent. Both units come from :class:`~globin.domain.clock.Instant`'s own
    properties, which share one exact conversion — a timestamp computed two ways
    that disagreed by a rounding step would be a request signed for one moment and
    described as another.
    """
    if unit is TimestampUnit.MICROSECONDS:
        return moment.epoch_micros
    return moment.epoch_millis


__all__ = [
    "DEFAULT_RECV_WINDOW_MILLIS",
    "MAX_RECV_WINDOW_DECIMALS",
    "MAX_RECV_WINDOW_MILLIS",
    "RECV_WINDOW_PARAMETER",
    "TIMESTAMP_PARAMETER",
    "RecvWindow",
    "TimestampUnit",
    "default_recv_window",
    "max_recv_window",
    "parse_recv_window",
    "stamp",
]
