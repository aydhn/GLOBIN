"""How GLOBIN says *when*: instants, durations and monotonic readings.

``ENGINEERING_CONTRACT.md`` invariant 25 states the rule this module makes
enforceable — timezone-naive datetimes must not cross a domain boundary,
internal time is UTC, and wall-clock time is injected rather than read. Phase 006
committed the logging half of it and left the general statement here by name
([ADR-0026](../../../docs/adr/0026-correlation-is-bound-explicitly-not-ambiently.md)).

Three types, because *when* is three different questions.

:class:`Instant` answers "at what moment", against the civil calendar. It is the
only type that can be written into a record, compared against an exchange
timestamp, or read by a person.

:class:`Duration` answers "for how long". It is a length, not a position, and it
cannot be negative: a negative length is a subtraction performed in the wrong
order rather than a value.

:class:`MonotonicReading` answers neither on its own. The standard library
documents the monotonic clock's reference point as undefined, "so that only the
difference between the results of two calls is valid" — so a reading is useful
only against another reading, and :meth:`MonotonicReading.since` is the one
operation that turns two of them into something meaningful. Giving it a type is
the same argument :mod:`globin.domain.values` makes for prices: a bare integer
of nanoseconds is exactly the unit confusion that module exists to refuse.

**Wall time and monotonic time are not interchangeable.** :func:`time.time` "can
return a lower value than a previous call if the system clock has been set back",
while :func:`time.monotonic` "cannot go backwards" and is "not affected by system
clock updates". Code that measures an elapsed interval with a wall clock is
correct until an NTP correction lands mid-measurement. That is why
``globin.ports.clock`` declares two protocols rather than one with two methods:
a component that needs elapsed time is handed something that cannot jump.

**Milliseconds are the wire convention, microseconds are the representation.**
Binance publishes every timestamp field in milliseconds by default, while
:class:`~datetime.datetime` carries microsecond resolution. The conversion
therefore discards information, and :data:`MICROSECONDS_PER_MILLISECOND` names
the direction: it floors. See :meth:`Instant.epoch_millis`.

This module imports nothing outside :mod:`globin.errors`, :mod:`dataclasses` and
:mod:`datetime`, performs no I/O and holds no module-level call. ``datetime`` is
absent from the I/O-capable list in ``docs/architecture/dependency-rules.toml``,
which is what permits the import — and is also why
``tests/architecture/test_architecture_contract.py`` grew a separate guard
against *reading* a clock in an inner layer. Importing the module is legitimate
here; calling :meth:`datetime.datetime.now` would not be.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from globin.errors import ValidationError

MICROSECONDS_PER_MILLISECOND: Final[int] = 1_000
"""How many microseconds make a millisecond.

Named rather than written inline because it is the *lossy* step. A
:class:`~datetime.datetime` holds microseconds and Binance speaks milliseconds,
so every conversion to the wire divides by this number and discards a remainder.
:meth:`Instant.epoch_millis` floors that division deliberately — see its
docstring for why truncation rather than rounding.
"""

MICROSECONDS_PER_SECOND: Final[int] = 1_000_000
"""How many microseconds make a second."""

MICROSECONDS_PER_DAY: Final[int] = 86_400_000_000
"""How many microseconds make a day.

:class:`~datetime.timedelta` normalises itself into days, seconds and
microseconds, so converting one to a single integer needs all three factors.
The alternative — :meth:`datetime.datetime.timestamp` — returns a
:class:`float`, and at the far end of the representable range that is not exact.
Measured on CPython 3.14.5: ``datetime(9999, 12, 31, 23, 59, 59, 999999)`` in UTC
is ``253402300799999999`` microseconds after the epoch, while the same value
routed through ``timestamp()`` yields ``253402300800000000`` — one microsecond
into a moment that does not exist. Integer arithmetic over a ``timedelta`` has no
such failure, so that is the route this module takes.
"""

NANOSECONDS_PER_MILLISECOND: Final[int] = 1_000_000
"""How many nanoseconds make a millisecond.

Durations are counted in nanoseconds because :func:`time.monotonic_ns` reports
them, and the standard library says plainly to prefer it "to avoid the precision
loss caused by the float type".
"""

MIN_EPOCH_MILLIS: Final[int] = -62135596800000
"""The earliest instant :class:`~datetime.datetime` can represent, in epoch milliseconds.

``0001-01-01T00:00:00+00:00``. Stated as a literal because deriving it would mean
constructing a :class:`~datetime.datetime` at module level, and
``tests/architecture/test_architecture_contract.py`` holds every layer package to
performing no work at import. A contract test derives it and compares, so the
literal cannot drift from the thing it describes.
"""

MAX_EPOCH_MILLIS: Final[int] = 253402300799999
"""The latest instant :class:`~datetime.datetime` can represent, in epoch milliseconds.

``9999-12-31T23:59:59.999+00:00``. The underlying maximum carries 999999
microseconds; flooring to milliseconds gives the value above, which is what makes
the round trip in :func:`instant_from_epoch_millis` total over this range.
"""


@dataclass(frozen=True, slots=True, order=True)
class Instant:
    """A moment in time, always timezone-aware and always UTC.

    Args:
        moment: The moment, as a timezone-aware :class:`~datetime.datetime`
            whose offset is UTC.

    Raises:
        ValidationError: If ``moment`` is not a :class:`~datetime.datetime`, is
            timezone-naive, or carries an offset other than UTC.

    Construct one with :func:`instant`, which converts an aware datetime in any
    zone to UTC rather than refusing it. This class is the stricter inner
    boundary: by the time a value is an ``Instant``, it is UTC, and nothing
    downstream needs to ask.

    Ordering is generated rather than hand-written. Every ``Instant`` is
    comparable with every other one — there is no denomination to disagree
    about, which is exactly what distinguishes this from
    :class:`globin.domain.values.Price`, where two values can share a type and
    still be incomparable.
    """

    moment: datetime

    def __post_init__(self) -> None:
        """Validate that the moment is an aware UTC datetime."""
        offset = _offset_of(self.moment, label="instant moment")
        if offset is None:
            msg = (
                f"instant moment must be timezone-aware, got the naive {self.moment.isoformat()}: "
                f"a naive datetime does not say which moment it means"
            )
            raise ValidationError(msg)
        if offset != timedelta(0):
            msg = (
                f"instant moment must be UTC, got offset {offset} on "
                f"{self.moment.isoformat()}: use instant() to convert"
            )
            raise ValidationError(msg)

    def __str__(self) -> str:
        """Render the moment in ISO 8601, with its UTC offset."""
        return self.moment.isoformat()

    @property
    def epoch_millis(self) -> int:
        """This moment as whole milliseconds since the Unix epoch.

        Returns:
            The count, **floored** towards the past.

        A :class:`~datetime.datetime` carries microseconds and the wire carries
        milliseconds, so the last three digits have nowhere to go. Flooring is
        chosen over rounding because it is the direction that cannot invent
        time: a truncated timestamp never claims an event happened later than it
        did, which matters for a value that will eventually be compared against
        an exchange's ``recvWindow``. Rounding half-up would move an event
        forward by up to half a millisecond, and a timestamp that has drifted
        into the future is the one an exchange rejects.

        Note that flooring is towards the past for negative values too, because
        Python's ``//`` floors rather than truncating towards zero. Instants
        before 1970 are not a case GLOBIN trades on, but a conversion that
        changed direction at the epoch would be a latent surprise rather than a
        decision.

        This is not the rounding policy `globin.domain.precision` holds. That
        module decides where
        exact decimal arithmetic is mandatory for *prices and quantities*, and
        how tick and step sizes round. This is a lossy encoding of a timestamp
        into the unit a venue publishes, and the two do not constrain each other.
        """
        return _microseconds_since_epoch(self.moment) // MICROSECONDS_PER_MILLISECOND


@dataclass(frozen=True, slots=True, order=True)
class Duration:
    """A length of time, counted in whole nanoseconds.

    Args:
        nanoseconds: How long, as a non-negative :class:`int`.

    Raises:
        ValidationError: If ``nanoseconds`` is not an :class:`int`, is a
            :class:`bool`, or is negative.

    A length, never a position. The monotonic clock cannot go backwards, so a
    negative duration means two readings were subtracted in the wrong order —
    a bug worth refusing at the point it is made rather than one to propagate
    into a timeout calculation.

    Integers, not floats. :func:`time.monotonic_ns` already reports exact
    nanoseconds and the standard library recommends it precisely to avoid float
    precision loss, so there is nothing to gain by widening and a rounding
    question to lose.
    """

    nanoseconds: int

    def __post_init__(self) -> None:
        """Validate that the count is a non-negative integer."""
        _require_count(self.nanoseconds, label="duration nanoseconds")
        if self.nanoseconds < 0:
            msg = (
                f"duration must not be negative, got {self.nanoseconds} nanoseconds: "
                f"a monotonic clock cannot go backwards, so this is a subtraction "
                f"performed in the wrong order"
            )
            raise ValidationError(msg)

    def __str__(self) -> str:
        """Render the length in nanoseconds."""
        return f"{self.nanoseconds}ns"

    @property
    def milliseconds(self) -> int:
        """This length as whole milliseconds, floored.

        Returns:
            The count, rounded towards zero — which for a non-negative value is
            the same as flooring, and this type admits no negative value.
        """
        return self.nanoseconds // NANOSECONDS_PER_MILLISECOND


@dataclass(frozen=True, slots=True, order=True)
class MonotonicReading:
    """One reading of a monotonic clock, in nanoseconds from an undefined origin.

    Args:
        nanoseconds: The reading, as an :class:`int`. Any value is admitted,
            including a negative one: the origin is undefined, so no sign is
            wrong.

    Raises:
        ValidationError: If ``nanoseconds`` is not an :class:`int`, or is a
            :class:`bool`.

    A reading means nothing by itself. The standard library documents the
    reference point as undefined "so that only the difference between the
    results of two calls is valid", which is why this type carries exactly one
    operation — :meth:`since` — and no conversion to a calendar moment. There is
    deliberately no way to turn a ``MonotonicReading`` into an :class:`Instant`;
    a type that offered one would be claiming a correspondence the platform does
    not promise.

    Two readings from *different* clock instances, or from different processes,
    are not comparable either. Nothing here can detect that, which is stated in
    ``docs/TIME_POLICY.md`` rather than pretended away.
    """

    nanoseconds: int

    def __post_init__(self) -> None:
        """Validate that the reading is an integer."""
        _require_count(self.nanoseconds, label="monotonic reading nanoseconds")

    def __str__(self) -> str:
        """Render the reading in nanoseconds."""
        return f"{self.nanoseconds}ns (monotonic)"

    def since(self, earlier: object) -> Duration:
        """How long elapsed between an earlier reading and this one.

        Args:
            earlier: A reading taken before this one, from the same clock.

        Returns:
            The elapsed :class:`Duration`.

        Raises:
            ValidationError: If ``earlier`` is not a :class:`MonotonicReading`,
                or if it is later than this reading.

        The second refusal names both readings and both explanations, because
        the two are genuinely different faults and the caller cannot tell them
        apart from a bare negative number. Overwhelmingly the cause is a
        subtraction written the wrong way round; the remaining possibility is
        that the platform broke the guarantee :func:`time.monotonic` makes. It
        is a :class:`~globin.errors.ValidationError` rather than an
        :class:`~globin.errors.InternalError` because the likely cause is the
        argument, and ``errors.py`` reserves ``InternalError`` for a defect in
        GLOBIN rather than for bad input.

        **``earlier`` is annotated ``object``, and that is deliberate.** Typed as
        :class:`MonotonicReading` it would be better at the call site — but mypy
        then proves the type check below unreachable and refuses the module,
        because a guard that cannot fire is dead code. The guard has to stay:
        without it, passing an :class:`Instant` raises :class:`AttributeError`
        out of a domain boundary, and
        [ADR-0022](../../../docs/adr/0022-error-taxonomy-rooted-in-one-type.md)
        requires a ``globin.errors`` type there. ``docs/TIME_POLICY.md`` records
        the refusal as part of the operation matrix and a contract test runs it.
        This is the same trade :mod:`globin.domain.values` makes when its
        comparison helpers take ``object``.
        """
        if not isinstance(earlier, MonotonicReading):
            msg = (
                f"can only measure elapsed time against another MonotonicReading, "
                f"got {type(earlier).__name__}"
            )
            raise ValidationError(msg)
        if earlier.nanoseconds > self.nanoseconds:
            msg = (
                f"cannot measure elapsed time from {earlier} to {self}: the earlier "
                f"reading is the larger one. Either the two were subtracted in the "
                f"wrong order, or the platform's monotonic guarantee was broken"
            )
            raise ValidationError(msg)
        return Duration(self.nanoseconds - earlier.nanoseconds)


def instant(moment: datetime) -> Instant:
    """Build an :class:`Instant`, converting any aware datetime to UTC.

    Args:
        moment: A timezone-aware :class:`~datetime.datetime`, in any zone.

    Returns:
        The same moment, expressed in UTC.

    Raises:
        ValidationError: If ``moment`` is not a :class:`~datetime.datetime` or
            is timezone-naive.

    An aware datetime in another zone is *converted*, not refused, because it
    names an unambiguous moment — converting it is arithmetic, not a guess. A
    naive one is refused for exactly the opposite reason: nothing in the value
    says whether it means UTC, the host's local zone, or the zone of whoever
    wrote it down, and picking one would be inventing information.
    """
    if _offset_of(moment, label="instant()") is None:
        msg = (
            f"instant() needs a timezone-aware datetime, got the naive "
            f"{moment.isoformat()}: attach a timezone at the boundary that read it"
        )
        raise ValidationError(msg)
    try:
        shifted = moment.astimezone(UTC)
    except OverflowError:
        msg = (
            f"converting {moment.isoformat()} to UTC leaves the range a datetime can "
            f"represent: an instant within a day of year 1 or year 9999 cannot be "
            f"shifted by its offset"
        )
        raise ValidationError(msg) from None
    return Instant(shifted)


def instant_from_epoch_millis(millis: int) -> Instant:
    """Build an :class:`Instant` from whole milliseconds since the Unix epoch.

    Args:
        millis: The count, as an :class:`int` between :data:`MIN_EPOCH_MILLIS`
            and :data:`MAX_EPOCH_MILLIS`.

    Returns:
        The corresponding UTC instant.

    Raises:
        ValidationError: If ``millis`` is not an :class:`int`, is a
            :class:`bool`, or lies outside the range
            :class:`~datetime.datetime` can represent.

    The bound is checked before construction rather than by catching the
    :class:`OverflowError` the standard library would raise, so the message
    names the value and the limit instead of reporting that an internal
    conversion failed.
    """
    _require_count(millis, label="epoch milliseconds")
    if not MIN_EPOCH_MILLIS <= millis <= MAX_EPOCH_MILLIS:
        msg = (
            f"epoch milliseconds must be between {MIN_EPOCH_MILLIS} and "
            f"{MAX_EPOCH_MILLIS}, got {millis}: that is outside the range a "
            f"datetime can represent"
        )
        raise ValidationError(msg)
    moment = _epoch() + timedelta(microseconds=millis * MICROSECONDS_PER_MILLISECOND)
    return Instant(moment)


def duration_from_millis(millis: int) -> Duration:
    """Build a :class:`Duration` from whole milliseconds.

    Args:
        millis: How long, as a non-negative :class:`int`.

    Returns:
        The same length, held in nanoseconds.

    Raises:
        ValidationError: If ``millis`` is not a non-negative :class:`int`, or is
            a :class:`bool`.
    """
    _require_count(millis, label="duration milliseconds")
    return Duration(millis * NANOSECONDS_PER_MILLISECOND)


def _epoch() -> datetime:
    """The Unix epoch, as an aware UTC datetime.

    Returns:
        ``1970-01-01T00:00:00+00:00``.

    A function rather than a module constant because building it is a call, and
    ``tests/architecture/test_architecture_contract.py`` refuses any call
    executed when a layer module is imported.
    """
    return datetime(1970, 1, 1, tzinfo=UTC)


def _microseconds_since_epoch(moment: datetime) -> int:
    """How many microseconds separate the epoch from an aware UTC datetime.

    Args:
        moment: An aware UTC datetime.

    Returns:
        The exact count, positive after the epoch and negative before it.

    Computed from the :class:`~datetime.timedelta`'s three normalised fields
    rather than from :meth:`datetime.datetime.timestamp`, which returns a float
    and is not exact at the extremes — see :data:`MICROSECONDS_PER_DAY`.
    """
    delta = moment - _epoch()
    return (
        delta.days * MICROSECONDS_PER_DAY
        + delta.seconds * MICROSECONDS_PER_SECOND
        + delta.microseconds
    )


def _offset_of(moment: object, *, label: str) -> timedelta | None:
    """The UTC offset of a datetime, or ``None`` when it is naive.

    Args:
        moment: Whatever was passed.
        label: What the value was meant to be, for the message.

    Returns:
        The offset, or ``None`` if the value carries no timezone.

    Raises:
        ValidationError: If ``moment`` is not a :class:`~datetime.datetime`, or
            if asking it for its offset fails.

    The type check is for :class:`~datetime.datetime` rather than
    :class:`~datetime.date`, and the direction matters: ``datetime`` is a
    *subclass* of ``date``, so a check for ``date`` would silently admit a
    ``datetime`` — and, worse, a bare ``date`` has no time of day at all.

    :meth:`datetime.datetime.utcoffset` is a call into caller-supplied code, not
    a field read. A :class:`~datetime.tzinfo` is an arbitrary object, and the
    standard library raises :class:`TypeError` if its ``utcoffset`` returns
    something other than a :class:`~datetime.timedelta` and :class:`ValueError`
    if the offset is not strictly within a day. Neither is a
    :class:`globin.errors.GlobinError`, and
    [ADR-0022](../../../docs/adr/0022-error-taxonomy-rooted-in-one-type.md)
    requires that a fault leaving this boundary is one. Both are therefore
    translated here, naming the offending ``tzinfo`` — the same move
    :mod:`globin.domain.values` makes with :class:`decimal.InvalidOperation`.
    """
    if not isinstance(moment, datetime):
        msg = (
            f"{label} must be a datetime, got {type(moment).__name__}: "
            f"pass datetime.now(UTC), or use instant_from_epoch_millis for a wire value"
        )
        raise ValidationError(msg)
    try:
        return moment.utcoffset()
    except (TypeError, ValueError) as fault:
        msg = (
            f"{label} carries a tzinfo that cannot report an offset: "
            f"{type(moment.tzinfo).__name__} raised {type(fault).__name__} ({fault})"
        )
        raise ValidationError(msg) from fault


def _require_count(value: object, *, label: str) -> None:
    """Refuse anything that is not a plain integer.

    Args:
        value: Whatever was passed.
        label: What the value was meant to be, for the message.

    Raises:
        ValidationError: If ``value`` is a :class:`bool` or is not an
            :class:`int`.

    ``bool`` is checked first and separately because :func:`isinstance` reports
    ``True`` as an ``int``, so an ordinary type check would silently accept
    ``True`` as one nanosecond. This is the same ordering
    :mod:`globin.domain.values` uses, and for the same reason.
    """
    if isinstance(value, bool):
        msg = f"{label} must be an int, got the bool {value!r}: a flag is not a count"
        raise ValidationError(msg)
    if not isinstance(value, int):
        msg = f"{label} must be an int, got {type(value).__name__}"
        raise ValidationError(msg)
