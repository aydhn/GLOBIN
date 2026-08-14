"""The host's clocks, behind the ports.

This module and this module alone reads the machine's idea of the time. Every
other layer is handed a :class:`~globin.ports.clock.Clock` or a
:class:`~globin.ports.clock.MonotonicClock` and asks it, which is what makes a
test able to say what time it is instead of having to freeze something.

``tests/architecture/test_clock_discipline.py`` enforces that rather than
trusting it: the ambient clock calls are refused everywhere except here.
"""

import time
from dataclasses import dataclass
from datetime import UTC, datetime

from globin.domain.clock import Instant, MonotonicReading


@dataclass(frozen=True, slots=True)
class SystemClock:
    """The host's wall clock.

    Carries no state, and is a frozen dataclass anyway so that two of them
    compare equal — which keeps a component holding one comparable, the same
    property :class:`globin.adapters.observability.StreamLogSink` has.

    **What this clock does not promise.** It is the operating system's idea of
    the civil time, and it can be stepped. Measured on the declared host
    (Windows, CPython 3.14.5), :func:`time.get_clock_info` reports
    ``adjustable=True`` for this source. An interval measured by subtracting two
    of its readings is therefore not reliably an elapsed time, which is why
    :class:`~globin.domain.clock.Instant` defines no subtraction and why
    :class:`SystemMonotonicClock` exists.

    Reconciling this clock against the venue's server time, and deciding what to
    do when they disagree, is **Phase 040**.
    """

    def now(self) -> Instant:
        """The current moment, in UTC.

        Returns:
            The moment this was called.

        ``datetime.now(UTC)`` rather than the deprecated ``datetime.utcnow()``:
        the latter returns a *naive* datetime holding UTC, which is the exact
        shape ``ENGINEERING_CONTRACT.md`` invariant 25 forbids from crossing a
        boundary. It has been deprecated since Python 3.12, and because
        ``pyproject.toml`` sets ``filterwarnings = ["error"]``, reaching for it
        anywhere in this repository would fail the suite rather than warn.
        """
        return Instant(datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class SystemMonotonicClock:
    """The host's monotonic clock.

    **Why :func:`time.monotonic_ns` and not :func:`time.perf_counter_ns`.** The
    guarantee GLOBIN needs is the one in ``monotonic``'s own definition — a
    clock that "cannot go backwards" and is "not affected by system clock
    updates". ``perf_counter`` is documented as the highest available
    resolution, which is a different promise and not the one being relied upon.

    On the declared host the two are the *same source*: measured with
    :func:`time.get_clock_info`, both report
    ``implementation='QueryPerformanceCounter()'`` at ``1e-07`` resolution. So
    the choice costs nothing measurable here and is made purely on the contract
    — which is the right basis, because the host is not the only machine this
    will ever run on.

    The ``_ns`` variant rather than the float one, because the standard library
    says to prefer it "to avoid the precision loss caused by the float type".
    """

    def reading(self) -> MonotonicReading:
        """A reading of the monotonic clock.

        Returns:
            The reading, in nanoseconds from a reference point the platform does
            not define.
        """
        return MonotonicReading(time.monotonic_ns())
