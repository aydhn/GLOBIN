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
both, and — the reason that actually matters — would make a server-time clock lie.
``docs/architecture/SYSTEM_CONTEXT.md`` names two independent time sources, the
host's and the venue's, and Phase 036 reconciles them.

**Phase 036 answered the question this docstring used to leave open, and answered
it differently from the way it was predicted.** The prediction was that a clock
reporting Binance's server time would implement :class:`Clock`. It does not, and
the reason is worth keeping: a venue's server time is not something GLOBIN *has*,
it is something GLOBIN **estimates**, and an estimate has an error bound. A
:class:`Clock` returning a corrected :class:`~globin.domain.clock.Instant` would
have thrown that bound away at the boundary, leaving every caller unable to ask
*how sure are you* — which is precisely the question
:func:`globin.domain.clock_sync.admit` exists to answer. So the third protocol
below reports a **reading plus its provenance**, and the correction is applied by
the domain layer where the uncertainty travels with it.

None of these protocols is :func:`~typing.runtime_checkable`, matching
:class:`globin.ports.observability.LogSink`. Conformance is checked by mypy at
the point an implementation is assigned to the port's type, which is a stronger
guarantee than an ``isinstance`` call that would only compare method names.
"""

from typing import Protocol

from globin.domain.clock import Instant, MonotonicReading
from globin.domain.clock_sync import ClockDomain, ServerTimeReading


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


class ServerTimeSource(Protocol):
    """Something that can ask a venue what time it thinks it is.

    Added in Phase 036. Implemented over REST by
    :class:`globin.adapters.clock_sync.RestServerTimeSource`, and by hand-written
    doubles in the tests.

    **Protocol-shaped rather than transport-shaped, and deliberately so.** The
    venue publishes the same fact over three surfaces — ``GET /api/v3/time``, the
    WebSocket API's ``time`` method, and the FIX session's own timestamps — and all
    three answer with the field
    :data:`~globin.domain.clock_sync.SERVER_TIME_FIELD`. A port naming HTTP would
    have to be replaced when the second surface arrives; this one does not, which
    is what lets Phase 036 declare a WebSocket clock domain without building a
    WebSocket engine for it.

    **Every implementation is credential-free and read-only.** Server time is a
    public endpoint on every product the venue documents, so an implementation that
    needed a secret would be doing something other than what this port is for.
    """

    def sample(self, domain: ClockDomain) -> ServerTimeReading | None:
        """Ask one clock domain for its current time.

        Args:
            domain: Which venue clock to ask.

        Returns:
            The reading, or ``None`` when the venue could not be asked or did not
            answer usably.

        **``None`` rather than an exception**, matching
        :class:`globin.ports.rest.RestTransport`'s rule and for a related reason: a
        failed calibration is an ordinary, expected state that the caller records as
        :attr:`~globin.domain.clock_sync.SyncState.DEGRADED`, not a fault that
        should unwind a stack. Raising would also make every caller responsible for
        distinguishing *the venue did not answer* from *GLOBIN is broken*, which is
        a distinction the return type makes for free.

        An implementation must not retry. One call is one exchange, so the round
        trip the caller measures around it is the round trip of exactly one request
        — a retry hidden inside here would silently inflate every uncertainty
        estimate GLOBIN publishes.
        """
        ...
