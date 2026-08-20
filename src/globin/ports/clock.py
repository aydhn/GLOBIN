"""The two ports time reaches GLOBIN through.

Two, not one, and the split is the decision this module exists to record.

A wall clock answers "what moment is this", against the civil calendar. It can
be stepped — by an operator, or by an NTP correction landing mid-operation — and
:func:`time.time` documents exactly that: it "can return a lower value than a
previous call if the system clock has been set back".

A monotonic clock answers "how much time has passed". It "cannot go backwards"
and is "not affected by system clock updates", and in exchange it will not tell
you what time it is at all: its reference point is undefined.

A single port carrying both methods would force every consumer to depend on
both, and — the reason that actually matters — would make a future server-time
clock lie. ``docs/architecture/SYSTEM_CONTEXT.md`` already names two independent
time sources, the host's and the venue's, and Phase 040 owns reconciling them --
row 040 is *Server Time Synchronization and Drift Control*, which is the phase that
measures skew and decides what to do about it.
A clock that reports Binance's server time can honestly implement :class:`Clock`.
It has no monotonic reading to offer, and a combined port would oblige it to
invent one.

Neither protocol is :func:`~typing.runtime_checkable`, matching
:class:`globin.ports.observability.LogSink`. Conformance is checked by mypy at
the point an implementation is assigned to the port's type, which is a stronger
guarantee than an ``isinstance`` call that would only compare method names.
"""

from typing import Protocol

from globin.domain.clock import Instant, MonotonicReading


class Clock(Protocol):
    """A source of the current moment."""

    def now(self) -> Instant:
        """The moment this is called.

        Returns:
            The current moment, in UTC.

        An implementation reads something outside the process — the host clock,
        or eventually a venue's published time — which is why this is a port and
        why no inner layer may call one of those directly.
        """
        ...


class MonotonicClock(Protocol):
    """A source of readings that never go backwards."""

    def reading(self) -> MonotonicReading:
        """A reading of the monotonic clock.

        Returns:
            The reading, which is meaningful only against another reading from
            the same clock.

        Deliberately not called ``now``. A name suggesting the present moment
        would invite a caller to log the value or compare it against a
        timestamp, and it denotes neither — see
        :class:`globin.domain.clock.MonotonicReading`.
        """
        ...
