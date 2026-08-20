r"""What GLOBIN believes the venue's clock says, and when that belief may be signed with.

Phase 035 recorded the venue's timing rule and did not implement it, saying so in
its own source ledger: *"it names ``serverTime``, which GLOBIN does not have."* This
module is where GLOBIN gets one — as an **estimate with a stated error bound**,
never as a fact.

**The rule this module makes executable**, quoted from the venue's own
``Timing security`` pseudo-code:

.. code-block:: javascript

    serverTime = getCurrentTime()
    if (timestamp < (serverTime + 1 second) && (serverTime - timestamp) <= recvWindow) {
      // begin processing request
      serverTime = getCurrentTime()
      if (serverTime - timestamp) <= recvWindow {
        // forward request to Matching Engine

**Read the second ``if`` carefully, because it is the one that shapes this phase.**
The window is evaluated **twice**, and the second evaluation — the one immediately
before the request reaches the Matching Engine — carries **no ``+ 1 second``
clause**. So the future tolerance is an admission-time allowance only, while the
*past* half of the window must survive the venue's own internal queueing: a delay
that happens after GLOBIN's request has arrived and that GLOBIN therefore cannot
measure at all. Every threshold here leaves headroom for it, and
:func:`admit` refuses rather than widening — which is the same sentence
:mod:`globin.domain.auth_timing` already carries and this module finally enforces:

    *"a wider window is not the remedy for a clock that disagrees with the venue"*

**A calibration is per clock domain, never global.** A round trip to a testnet host
says nothing about the offset of a production one, and an estimate borrowed across
that boundary would be a fabricated measurement. :class:`ClockDomain` is a
``(family, environment, protocol)`` triple built from Phase 033's own identifier
types, so this module enumerates no product and names no environment — which is
what ``tests/architecture/test_identifier_discipline.py`` requires of a domain
module.

**Everything here is integer arithmetic in microseconds.** Not floats, and not
:class:`~decimal.Decimal`: an offset is a coordinate difference on an exact integer
grid, which is the case ``docs/TIME_POLICY.md`` distinguishes from the *magnitude*
rounding ``docs/PRECISION_POLICY.md`` owns. Microseconds because
:attr:`~globin.domain.clock.Instant.epoch_micros` reports them exactly, and there
is therefore **one** flooring step in the whole path — :func:`corrected_stamp`,
when a millisecond timestamp is asked for.

**This module reads no clock and reaches nothing.** Every moment and every
monotonic reading arrives as an argument, which is what lets the whole state
machine be tested without a sleep anywhere.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.domain.api_reality import EnvironmentName, ProductFamily, ProtocolKind
from globin.domain.auth_timing import MAX_RECV_WINDOW_MILLIS, RecvWindow, TimestampUnit
from globin.domain.clock import MICROSECONDS_PER_MILLISECOND, Duration, Instant, MonotonicReading
from globin.domain.rest import RequestOutcome, SideEffect
from globin.errors import ValidationError

SERVER_TIME_FIELD: Final[str] = "serverTime"
"""What the venue calls the moment in its answer. Its exact documented spelling.

The response to ``GET /api/v3/time`` is documented as ``{"serverTime":
1499827319559}``, and the WebSocket API's ``time`` method answers with the same
field. One spelling serves both, which is why :func:`server_time_from` takes a
decoded payload rather than a protocol.
"""

FUTURE_TOLERANCE_MILLIS: Final[int] = 1_000
"""How far into the venue's future a timestamp may be, at admission only.

The ``+ 1 second`` of the venue's first check. ``errors.md`` states the same bound
from the other side: ``-1021`` is documented as *"Timestamp for this request was
1000ms ahead of the server's time."*

**It is a ceiling GLOBIN stays well inside, never a budget it spends.** The second
check has no such clause, so a request that scraped past the first one on future
tolerance would have no protection at all in the second.
"""

INVALID_TIMESTAMP_CODE: Final[int] = -1021
"""The venue's ``INVALID_TIMESTAMP``. Documented with two distinct meanings.

Quoted in full: *"Timestamp for this request is outside of the recvWindow."* and
*"Timestamp for this request was 1000ms ahead of the server's time."* Both are
refusals at the timing gate before the Matching Engine, which is why
``rest-transport.toml`` declares it **unambiguous** and why :func:`recovery_for`
may permit one bounded re-send.
"""

MAX_TIMING_RETRIES: Final[int] = 1
"""How many times one request may be re-sent after a timing rejection. Exactly one.

Not configurable, and deliberately not. A retry budget an operator can raise is a
retry engine, and Phase 043 owns those. What this phase owns is a seam narrow
enough to be obviously safe: resynchronise, re-stamp, send once more, and never
again.
"""

MAX_SAMPLE_COUNT: Final[int] = 16
"""The largest calibration window :class:`ClockDiscipline` will accept.

A bound rather than a preference. The window is held in memory for the life of the
process and never trimmed by anything else, so an unbounded count is an unbounded
allocation — and past a handful of samples the estimator gains nothing, because it
selects the single lowest round trip rather than combining them.
"""

DEFAULT_SAMPLE_COUNT: Final[int] = 5
"""How many samples a calibration keeps unless configured otherwise."""

DEFAULT_FRESHNESS_TTL_MILLIS: Final[int] = 300_000
"""How long a calibration stays fresh: five minutes.

Chosen against the quantity that actually decays, which is not the offset but the
*confidence* in it. A quartz oscillator specified at 20 parts per million drifts
about 1.2 milliseconds per minute in the worst case, so five minutes bounds the
accumulated drift at roughly six milliseconds — comfortably inside
:data:`DEFAULT_MAX_UNCERTAINTY_MILLIS` and an order of magnitude inside the
default window.
"""

DEFAULT_DEGRADED_GRACE_MILLIS: Final[int] = 900_000
"""How long a surviving sample keeps a domain describable after a probe fails.

Fifteen minutes, three times the freshness interval. It never admits a signature —
only :attr:`SyncState.SYNCHRONIZED` does — so this is the interval over which
GLOBIN can still say *what it last knew* rather than the interval over which it
still trusts it.
"""

DEFAULT_MAX_ROUND_TRIP_MILLIS: Final[int] = 2_000
"""The slowest round trip a sample may have and still be usable."""

DEFAULT_MAX_UNCERTAINTY_MILLIS: Final[int] = 250
"""The widest error bound an admitted timestamp may carry.

Half of :data:`DEFAULT_MAX_ROUND_TRIP_MILLIS` would be 1000, which is exactly
:data:`FUTURE_TOLERANCE_MILLIS` and therefore no margin at all. A quarter of it
leaves the future check three quarters of its allowance unspent.
"""

DEFAULT_MAX_OFFSET_JUMP_MILLIS: Final[int] = 1_000
"""How far the estimated offset may move between calibrations before it is disbelieved.

A venue's clock does not step; a host's does. An offset that moved by more than this
between two samples is evidence about **this machine**, so the domain is marked
:attr:`SyncState.UNSYNCHRONIZED` rather than quietly re-anchored.
"""

DEFAULT_MAX_WALL_DIVERGENCE_MILLIS: Final[int] = 500
"""How far the wall clock may diverge from the monotonic clock before a jump is declared.

Both clocks measure the same interval. Any difference between them is the wall
clock being adjusted, because the monotonic one is documented as *"not affected by
system clock updates"*. The threshold is not zero because the two are read at
slightly different instants and neither is infinitely precise.
"""

DEFAULT_NETWORK_BUDGET_MILLIS: Final[int] = 1_000
"""How long a signed request is assumed to take to reach the venue and be routed.

Deliberately larger than any healthy round trip. It stands in for the one interval
GLOBIN cannot observe — the venue's internal queueing between its first timing check
and its second — and it is spent against the window in :func:`admit` rather than
being hoped for.
"""

ROUND_TRIP_BUCKET_BOUNDS_MILLIS: Final[tuple[int, ...]] = (5, 10, 25, 50, 100, 250, 500, 1_000)
"""Upper bounds of the round-trip buckets a diagnostic may publish.

Eight bounds and therefore **nine** buckets, which is the whole cardinality this
dimension can contribute. ``docs/TELEMETRY_POLICY.md`` requires that a value set be
bounded when it is written rather than hoped to be small, and a raw nanosecond count
is the opposite of that: every observation is its own series.

A tuple rather than a frozenset, for the reason
:data:`globin.domain.rest.AMBIGUOUS_STATUSES` gives — a layer package performs no
call at import, and ``frozenset({...})`` is a call.
"""

OFFSET_BUCKET_BOUNDS_MILLIS: Final[tuple[int, ...]] = (1, 5, 25, 100, 500, 1_000)
"""Upper bounds of the offset-magnitude buckets a diagnostic may publish.

Six bounds, seven buckets, and a sign — fourteen values, computable here rather than
discovered in a dashboard.
"""

OVERFLOW_BUCKET: Final[str] = "over"
"""What a value above the largest declared bound is published as."""


def default_discipline() -> "ClockDiscipline":
    """The thresholds GLOBIN applies when an operator configures none.

    Returns:
        A discipline built from the ``DEFAULT_`` constants above.

    A function rather than a module constant because constructing one is a call, and
    ``tests/architecture/test_architecture_contract.py`` refuses any call performed
    when a layer package is imported. The same reason
    :func:`globin.domain.auth_timing.default_recv_window` is a function.
    """
    return ClockDiscipline(
        sample_count=DEFAULT_SAMPLE_COUNT,
        freshness_ttl=_millis(DEFAULT_FRESHNESS_TTL_MILLIS),
        degraded_grace=_millis(DEFAULT_DEGRADED_GRACE_MILLIS),
        max_round_trip=_millis(DEFAULT_MAX_ROUND_TRIP_MILLIS),
        max_uncertainty=_millis(DEFAULT_MAX_UNCERTAINTY_MILLIS),
        max_offset_jump=_millis(DEFAULT_MAX_OFFSET_JUMP_MILLIS),
        max_wall_divergence=_millis(DEFAULT_MAX_WALL_DIVERGENCE_MILLIS),
        network_budget=_millis(DEFAULT_NETWORK_BUDGET_MILLIS),
    )


def max_window_micros() -> int:
    """The widest window the venue accepts, in microseconds.

    Returns:
        Sixty thousand milliseconds, expressed in microseconds.

    Derived from :data:`globin.domain.auth_timing.MAX_RECV_WINDOW_MILLIS` rather
    than written again, so the venue's ceiling is spelled in exactly one place. A
    function rather than a constant because ``int("60000")`` is a call, and a layer
    package performs none at import.
    """
    return int(MAX_RECV_WINDOW_MILLIS) * MICROSECONDS_PER_MILLISECOND


def _require_int(value: object, *, label: str) -> int:
    """Refuse anything that is not a plain integer, and hand it back typed.

    Args:
        value: Whatever was passed.
        label: What the value was meant to be, for the message.

    Returns:
        The same value, as an :class:`int`.

    Raises:
        ValidationError: If ``value`` is a :class:`bool` or is not an :class:`int`.

    **Typed ``object`` deliberately**, which is the trade
    :meth:`globin.domain.clock.MonotonicReading.since` documents and
    :func:`globin.domain.clock._require_count` already makes. Annotated as
    :class:`int` the guard is provably dead and mypy refuses the module, leaving the
    boundary unchecked for every caller mypy cannot see. ``bool`` is tested first
    and separately because :func:`isinstance` reports ``True`` as an ``int``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{label} must be an int and is {type(value).__name__}"
        raise ValidationError(msg)
    return value


def _require_kind(value: object, expected: type, *, label: str) -> None:
    """Refuse anything that is not an instance of one type.

    Args:
        value: Whatever was passed.
        expected: What it must be.
        label: What the value was meant to be, for the message.

    Raises:
        ValidationError: If ``value`` is not an instance of ``expected``.

    ``object`` for the same reason :func:`_require_int` takes one.
    """
    if not isinstance(value, expected):
        msg = f"{label} must be a {expected.__name__} and is {type(value).__name__}"
        raise ValidationError(msg)


def _millis(count: int) -> Duration:
    """A whole number of milliseconds as a :class:`~globin.domain.clock.Duration`.

    Args:
        count: How many milliseconds.

    Returns:
        The duration.
    """
    return Duration(count * MICROSECONDS_PER_MILLISECOND * 1_000)


class SyncState(StrEnum):
    """How much GLOBIN trusts its estimate of one clock domain's server time.

    Five members, and exactly one of them admits a signature. The other four are
    kept apart because an operator reading a refusal needs to know whether to wait,
    to fix a network, or to fix a clock — a single ``unsynchronised`` would send all
    three to the same place, which is the same argument
    :class:`~globin.domain.rest_endpoint.ResolutionStatus` makes for having nine
    refusals rather than one.
    """

    UNINITIALIZED = "uninitialized"
    """No calibration has ever succeeded for this domain.

    The state every domain is in at start-up, and the reason a fresh process signs
    nothing until it has asked the venue what time it is. Nothing persists an offset
    across a restart, so this state cannot be skipped by reading a file.
    """

    SYNCHRONIZED = "synchronized"
    """A fresh sample exists, within every declared bound. The only admitting state."""

    STALE = "stale"
    """A sample exists and is older than the freshness interval.

    Not a failure — nothing went wrong, and nothing has been checked recently
    either. A calibration clears it.
    """

    DEGRADED = "degraded"
    """The most recent probe failed and a recent sample survives.

    Describable, not usable. It exists so that a diagnostic can say *the venue
    stopped answering and here is what it last said* rather than collapsing that
    into :attr:`UNINITIALIZED`, which would claim GLOBIN had never known.
    """

    UNSYNCHRONIZED = "unsynchronized"
    """The estimate has been actively disbelieved.

    Reached by a wall-clock jump, by an offset that moved further than the declared
    bound, or by the venue answering ``-1021``. Distinct from :attr:`UNINITIALIZED`
    because *we were told we are wrong* is a different fact from *we never asked*,
    and a supervisor should treat them differently.
    """

    @property
    def admits(self) -> bool:
        """Whether a signature may be produced against this state."""
        return self is SyncState.SYNCHRONIZED


class JumpDirection(StrEnum):
    """Which way the host's wall clock moved relative to the monotonic clock."""

    NONE = "none"
    """The two clocks agree within the declared tolerance."""

    FORWARD = "forward"
    """The wall clock advanced further than the elapsed interval. It was set ahead."""

    BACKWARD = "backward"
    """The wall clock advanced less than the elapsed interval, or went backwards."""


class AdmissionStatus(StrEnum):
    """Whether a signed request may be stamped, and if not, precisely why.

    Seven refusals rather than one. Every member here is a **timing** verdict and
    none of them is a transport failure: they share no type with
    :class:`~globin.domain.rest.TransportFailureKind`, which is what stops a caller
    retrying a clock problem as though it were a dropped connection.
    """

    ADMITTED = "admitted"
    """Every gate passed. A timing context was produced."""

    CLOCK_SOURCE_UNAVAILABLE = "clock_source_unavailable"
    """No server-time source is declared for this clock domain.

    The state every non-Spot family is in today: Phase 033 records their REST
    surface as ``unknown`` and the registry carries no endpoint, so there is nowhere
    to ask. A path is never guessed.
    """

    CLOCK_NOT_SYNCHRONIZED = "clock_not_synchronized"
    """No calibration has succeeded, or the estimate has been disbelieved."""

    CLOCK_CALIBRATION_STALE = "clock_calibration_stale"
    """A calibration exists and is no longer fresh enough to sign with."""

    CLOCK_JUMP_DETECTED = "clock_jump_detected"
    """The host's wall clock was adjusted since the calibration was taken."""

    CLOCK_UNCERTAINTY_EXCEEDED = "clock_uncertainty_exceeded"
    """The best available sample carries an error bound wider than the declared limit."""

    RECV_WINDOW_POLICY_VIOLATION = "recv_window_policy_violation"
    """The configured validity window is not one this policy permits to be sent."""

    TIMING_BUDGET_EXCEEDED = "timing_budget_exceeded"
    """The required allowance is wider than any window the venue would accept.

    Distinct from :attr:`RECV_WINDOW_POLICY_VIOLATION` because the remedies are
    different: that one an operator can fix by widening a setting, and this one they
    cannot fix at all without repairing the network or the host clock. Telling them
    to widen a window already at the ceiling would be advice that cannot work.
    """

    @property
    def permits(self) -> bool:
        """Whether a timestamp may be produced."""
        return self is AdmissionStatus.ADMITTED


class TimingRecovery(StrEnum):
    """What may be done after the venue rejects a request's timing.

    Three members, and the middle one is the default. There is deliberately no
    member meaning *retry freely*: the only re-send this vocabulary can express is
    bounded at :data:`MAX_TIMING_RETRIES`.
    """

    NO_ACTION = "no_action"
    """Nothing about this outcome concerns the clock."""

    RESYNC_ONLY = "resync_only"
    """Recalibrate and do not re-send.

    What an ambiguous outcome always gets. ADR-0089's rule is that a request whose
    fate is unknown is never replayed, and a timing rejection does not become an
    exception to it merely because the remedy is obvious.
    """

    RESYNC_AND_RETRY_ONCE = "resync_and_retry_once"
    """Recalibrate, re-stamp, and send exactly once more.

    Permitted only when the venue **confirmed** the rejection and the request is one
    whose repetition cannot create a second effect.
    """

    @property
    def resynchronises(self) -> bool:
        """Whether this verdict requires a fresh calibration before anything else."""
        return self is not TimingRecovery.NO_ACTION


@dataclass(frozen=True, slots=True)
class ClockDomain:
    """One venue clock GLOBIN calibrates against, identified by three facts.

    Args:
        family: Which product family.
        environment: Which environment.
        protocol: Which surface the time is read from.

    **Three axes rather than one, because a clock is not global.** Production and
    testnet are different machines; a REST answer and a WebSocket answer may be
    served by different front ends. Borrowing an offset across any of those
    boundaries would be reporting a measurement that was never taken.

    Built from Phase 033's own identifier types rather than from an enumeration
    here. Which products a venue offers changes without GLOBIN being redeployed,
    which is why ``tests/architecture/test_identifier_discipline.py`` refuses a
    register of instances in this layer.
    """

    family: ProductFamily
    environment: EnvironmentName
    protocol: ProtocolKind

    @property
    def label(self) -> str:
        """This domain as one stable string, for a diagnostic or a mapping key.

        Returns:
            ``family/environment/protocol``.
        """
        return f"{self.family.slug}/{self.environment.slug}/{self.protocol.value}"

    def __str__(self) -> str:
        """Render as the label."""
        return self.label

    def as_record(self) -> dict[str, object]:
        """This domain as plain JSON-safe values."""
        return {
            "family": self.family.slug,
            "environment": self.environment.slug,
            "protocol": self.protocol.value,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class ServerTimeReading:
    """One moment the venue reported, normalised to microseconds.

    Args:
        epoch_micros: The moment, in microseconds since the Unix epoch.
        unit: The unit the venue expressed it in before normalisation.

    Raises:
        ValidationError: If the count is not a positive :class:`int`, or is a
            :class:`bool`.

    **Normalised on arrival, and the original unit is kept beside it.** The venue
    answers in milliseconds by default and in microseconds when
    ``X-MBX-TIME-UNIT`` asks it to, so a reading that carried its own unit would
    push a multiplication out to every consumer. Carrying the unit as a *record* of
    what arrived keeps the diagnostic honest without making the arithmetic
    conditional.

    A non-positive count is refused rather than admitted. Every real answer is a
    moment after 1970, so zero is the shape of a missing field that survived
    parsing — which is exactly the value a permissive type would let through into
    an offset of minus fifty-six years.
    """

    epoch_micros: int
    unit: TimestampUnit

    def __post_init__(self) -> None:
        """Refuse a reading that cannot be a venue's answer."""
        _require_int(self.epoch_micros, label="a server time in microseconds")
        if self.epoch_micros <= 0:
            msg = (
                f"a server time of {self.epoch_micros} microseconds is not a moment the venue "
                "could have reported; a missing or zero field is not a timestamp"
            )
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This reading as plain JSON-safe values."""
        return {"epoch_micros": self.epoch_micros, "reported_unit": self.unit.value}


def server_time_from(payload: object, unit: TimestampUnit) -> ServerTimeReading:
    """Read the venue's answer out of a decoded response body.

    Args:
        payload: The decoded JSON body, as the transport produced it.
        unit: Which unit the request negotiated, and therefore which unit the
            number is in.

    Returns:
        The reading, normalised to microseconds.

    Raises:
        ValidationError: If the payload is not a mapping, carries no
            :data:`SERVER_TIME_FIELD`, or carries something that is not a whole
            number.

    **Pure, and therefore here rather than in the adapter.** Parsing a decoded
    value is a rule about the venue's documented shape, not an act of I/O — the
    adapter's job is to obtain the bytes, and this module's job is to say what
    counts as an answer. That split is what lets every malformed-response case be
    tested without a socket.

    ``float`` is refused rather than converted. The field is documented as an
    integer count, and a JSON number that arrived as a float means either the venue
    changed its documented shape or something re-encoded the body — both of which an
    operator needs told, and neither of which is fixed by rounding.
    """
    if not isinstance(payload, dict):
        msg = (
            f"a server-time response decoded to {type(payload).__name__} and the venue "
            f"documents an object carrying {SERVER_TIME_FIELD!r}"
        )
        raise ValidationError(msg)
    if SERVER_TIME_FIELD not in payload:
        present = ", ".join(sorted(str(key) for key in payload)) or "nothing"
        msg = f"a server-time response carries no {SERVER_TIME_FIELD!r} field; it carries {present}"
        raise ValidationError(msg)
    raw = payload[SERVER_TIME_FIELD]
    if isinstance(raw, bool) or not isinstance(raw, int):
        msg = (
            f"a server-time response carries {SERVER_TIME_FIELD}={type(raw).__name__}; the venue "
            "documents a whole number of milliseconds or microseconds"
        )
        raise ValidationError(msg)
    micros = raw if unit is TimestampUnit.MICROSECONDS else raw * MICROSECONDS_PER_MILLISECOND
    return ServerTimeReading(epoch_micros=micros, unit=unit)


@dataclass(frozen=True, slots=True)
class ClockDiscipline:
    """Every threshold the clock layer applies, validated as a set rather than singly.

    Args:
        sample_count: How many samples the calibration window keeps.
        freshness_ttl: How long a sample stays fresh enough to sign with.
        degraded_grace: How long a sample keeps a domain describable after a
            failure.
        max_round_trip: The slowest usable round trip.
        max_uncertainty: The widest admissible error bound.
        max_offset_jump: How far the offset may move between calibrations.
        max_wall_divergence: How far the two host clocks may disagree.
        network_budget: The unobservable delay a signed request is assumed to meet.

    Raises:
        ValidationError: If any threshold is unusable, or if two of them combine
            into a gate that could never fire.

    **The combinations are the reason this is a type.** Three of the checks below
    are not about one field at all:

    * ``degraded_grace`` shorter than ``freshness_ttl`` makes
      :attr:`SyncState.DEGRADED` unreachable — a sample would expire out of the
      grace period before it stopped being fresh.
    * ``max_uncertainty`` above half of ``max_round_trip`` makes the uncertainty
      gate unreachable, because uncertainty *is* half the round trip and the
      round-trip gate would always refuse first.
    * ``max_uncertainty`` at or above :data:`FUTURE_TOLERANCE_MILLIS` describes a
      host whose admitted timestamps could land beyond the venue's own future
      tolerance.

    **That third rule is what makes the future half of the venue's check
    structural rather than a runtime gate**, and the direction is worth stating
    because it is easy to get backwards. Network delay pushes a timestamp further
    into the venue's *past*, never its future: while the request is in flight the
    venue's own clock advances, so transit time is spent against ``recvWindow`` and
    never against the ``+ 1 second`` allowance. The only thing that can put a
    GLOBIN timestamp *ahead* of the venue is the estimate being wrong, which is
    exactly ``max_uncertainty``. Bounding it here means :func:`admit` needs no
    future-side gate at all — and a gate that could never fire is one this
    repository refuses to write.

    A discipline that could not be honoured cannot be constructed — the same rule
    ``RUNTIME_DIAGNOSTICS.md`` states about a rotation policy.
    """

    sample_count: int
    freshness_ttl: Duration
    degraded_grace: Duration
    max_round_trip: Duration
    max_uncertainty: Duration
    max_offset_jump: Duration
    max_wall_divergence: Duration
    network_budget: Duration

    def __post_init__(self) -> None:
        """Refuse a set of thresholds that contradicts itself."""
        _require_int(self.sample_count, label="a calibration sample count")
        if not 1 <= self.sample_count <= MAX_SAMPLE_COUNT:
            msg = (
                f"a calibration keeps between 1 and {MAX_SAMPLE_COUNT} samples and "
                f"{self.sample_count} was configured"
            )
            raise ValidationError(msg)
        for name, value in (
            ("freshness_ttl", self.freshness_ttl),
            ("degraded_grace", self.degraded_grace),
            ("max_round_trip", self.max_round_trip),
            ("max_uncertainty", self.max_uncertainty),
            ("max_offset_jump", self.max_offset_jump),
            ("max_wall_divergence", self.max_wall_divergence),
            ("network_budget", self.network_budget),
        ):
            _require_kind(value, Duration, label=f"clock discipline {name}")
            if value.nanoseconds <= 0:
                msg = f"clock discipline {name} is {value}, which is not a usable interval"
                raise ValidationError(msg)
        if self.degraded_grace < self.freshness_ttl:
            msg = (
                f"a degraded grace of {self.degraded_grace} is shorter than the freshness "
                f"interval of {self.freshness_ttl}, which makes the degraded state unreachable"
            )
            raise ValidationError(msg)
        if self.max_uncertainty.microseconds * 2 > self.max_round_trip.microseconds:
            msg = (
                f"a maximum uncertainty of {self.max_uncertainty} is more than half the maximum "
                f"round trip of {self.max_round_trip}; uncertainty is half a round trip, so the "
                "round-trip gate would always refuse first and this threshold could never fire"
            )
            raise ValidationError(msg)
        ceiling = FUTURE_TOLERANCE_MILLIS * MICROSECONDS_PER_MILLISECOND
        if self.max_uncertainty.microseconds >= ceiling:
            msg = (
                f"a maximum uncertainty of {self.max_uncertainty} reaches the venue's "
                f"{FUTURE_TOLERANCE_MILLIS}ms future tolerance; a timestamp that could be that "
                "far ahead of the venue would be rejected before it was processed"
            )
            raise ValidationError(msg)

    @property
    def required_window_micros(self) -> int:
        """The narrowest window that could survive this discipline's own worst case.

        Returns:
            The uncertainty plus the network budget, in microseconds.

        What :func:`admit` compares a configured ``recvWindow`` against. It is the
        *floor* a window has to clear, never a value GLOBIN would widen a window to
        reach.
        """
        return self.max_uncertainty.microseconds + self.network_budget.microseconds

    def as_record(self) -> dict[str, object]:
        """This discipline as plain JSON-safe values, in milliseconds."""
        return {
            "sample_count": self.sample_count,
            "freshness_ttl_millis": self.freshness_ttl.milliseconds,
            "degraded_grace_millis": self.degraded_grace.milliseconds,
            "max_round_trip_millis": self.max_round_trip.milliseconds,
            "max_uncertainty_millis": self.max_uncertainty.milliseconds,
            "max_offset_jump_millis": self.max_offset_jump.milliseconds,
            "max_wall_divergence_millis": self.max_wall_divergence.milliseconds,
            "network_budget_millis": self.network_budget.milliseconds,
            "future_tolerance_millis": FUTURE_TOLERANCE_MILLIS,
        }


@dataclass(frozen=True, slots=True)
class CalibrationSample:
    """One completed exchange with a venue clock, and what it implies.

    Args:
        domain: Which clock this measures.
        offset_micros: How far ahead of GLOBIN's host the venue's clock is. Signed:
            negative means the host is ahead.
        round_trip: How long the exchange took, measured on the **monotonic** clock.
        taken_at: The monotonic reading when the exchange finished.
        wall_anchor_micros: The host's wall clock when the exchange began.
        reported_unit: Which unit the venue answered in.

    Raises:
        ValidationError: If the round trip is not a :class:`Duration`, or the
            counts are not integers.

    **The round trip is monotonic and the anchor is wall — and that pairing is the
    whole point.** :func:`sample_offset` computes the midpoint by taking the wall
    anchor *once* and extending it by a monotonic span, so an NTP correction landing
    mid-flight cannot corrupt the sample. Computing the midpoint from two wall
    readings would have folded the correction straight into the offset.
    """

    domain: ClockDomain
    offset_micros: int
    round_trip: Duration
    taken_at: MonotonicReading
    wall_anchor_micros: int
    reported_unit: TimestampUnit

    def __post_init__(self) -> None:
        """Refuse a sample whose fields are not the measurements they claim."""
        for name, value in (
            ("offset", self.offset_micros),
            ("wall anchor", self.wall_anchor_micros),
        ):
            _require_int(value, label=f"a calibration {name} in microseconds")
        _require_kind(self.round_trip, Duration, label="a calibration round trip")
        _require_kind(self.taken_at, MonotonicReading, label="a calibration anchor")

    @property
    def uncertainty_micros(self) -> int:
        """How far this sample's offset could be wrong, at most.

        Returns:
            Half the round trip, floored.

        The classical bound, and the reason :func:`choose_sample` prefers the
        fastest exchange: the error in a midpoint estimate cannot exceed half the
        round trip, so the shortest round trip is simply the tightest bound
        available. Nothing computed from several samples improves it.
        """
        return self.round_trip.microseconds // 2

    def as_record(self) -> dict[str, object]:
        """This sample as plain JSON-safe values, bucketed rather than raw.

        Returns:
            The domain, the reported unit, and **buckets** for the round trip and
            the offset magnitude.

        The exact microsecond counts are deliberately absent. They are not secret —
        a clock offset protects nothing — but they are unbounded in cardinality, and
        ``docs/TELEMETRY_POLICY.md`` requires a published dimension to have a value
        set that can be counted when it is written. The signed offset in whole
        milliseconds is published beside the bucket, because an operator diagnosing
        a clock needs the number and a dashboard does not.
        """
        return {
            "domain": self.domain.label,
            "reported_unit": self.reported_unit.value,
            "offset_millis": self.offset_micros // MICROSECONDS_PER_MILLISECOND,
            "offset_bucket": offset_bucket(self.offset_micros),
            "round_trip_bucket": round_trip_bucket(self.round_trip.microseconds),
            "uncertainty_bucket": round_trip_bucket(self.uncertainty_micros),
        }


def sample_offset(
    domain: ClockDomain,
    *,
    reading: ServerTimeReading,
    wall_anchor: Instant,
    started: MonotonicReading,
    finished: MonotonicReading,
) -> CalibrationSample:
    """Turn one completed server-time exchange into a sample.

    Args:
        domain: Which clock was asked.
        reading: What it answered.
        wall_anchor: The host's wall clock, read immediately **before** the request.
        started: The monotonic reading taken at the same moment as ``wall_anchor``.
        finished: The monotonic reading taken when the answer arrived.

    Returns:
        The sample.

    Raises:
        ValidationError: If ``finished`` is earlier than ``started``, which
            :meth:`~globin.domain.clock.MonotonicReading.since` refuses.

    The estimator, in three lines and with the reasoning that makes each one
    necessary:

    .. code-block:: text

        round_trip     = finished - started                 monotonic; cannot jump
        local_midpoint = wall_anchor + round_trip / 2       one wall read, extended
        offset         = server_time - local_midpoint

    **Why a midpoint at all.** The venue stamps its answer at some unknown moment
    between GLOBIN's send and GLOBIN's receive. Assuming it stamped at *receive*
    time — the naive ``server_time - now`` — attributes the entire round trip to the
    offset, so a host with a perfect clock on a 200-millisecond link would measure
    itself 200 milliseconds fast and correct itself into being 200 milliseconds
    wrong. The midpoint assumes the path is symmetric, which is not always true, and
    is wrong by at most half the round trip when it is not. That bound is
    :attr:`CalibrationSample.uncertainty_micros`, and it is carried rather than
    forgotten.
    """
    round_trip = finished.since(started)
    local_midpoint = wall_anchor.epoch_micros + round_trip.microseconds // 2
    return CalibrationSample(
        domain=domain,
        offset_micros=reading.epoch_micros - local_midpoint,
        round_trip=round_trip,
        taken_at=finished,
        wall_anchor_micros=wall_anchor.epoch_micros,
        reported_unit=reading.unit,
    )


def choose_sample(samples: tuple[CalibrationSample, ...]) -> CalibrationSample | None:
    """Pick the sample whose offset estimate is most tightly bounded.

    Args:
        samples: The calibration window, in the order the samples were taken.

    Returns:
        The sample with the **lowest round trip**, the later one winning a tie, or
        ``None`` when the window is empty.

    **Lowest round trip, not an average, and there are two independent reasons.**

    The first is the bound. A midpoint estimate is wrong by at most half the round
    trip, so the fastest exchange is by definition the tightest estimate in the
    window. Averaging several samples does not narrow that bound — it produces a
    number whose error is governed by the *slowest* sample included.

    The second is specific to this transport, and is the reason the choice is not
    merely conventional. :class:`~globin.adapters.rest_transport.HttpRestTransport`
    pools connections, so the **first** exchange on a fresh pool pays a TCP and TLS
    handshake before any request is written. Its elapsed time is not a round trip at
    all, and the venue stamps its answer nowhere near the midpoint of it. An
    averaging estimator would fold that handshake into the offset; selecting the
    minimum discards it structurally, without needing to know which sample was
    first.

    A median over a low-round-trip subset was considered and declined in ADR-0093:
    it costs a sort and a tie rule and improves no bound.

    The later sample wins a tie because it is the fresher measurement of the same
    quality — a deterministic rule, so two runs over one window always agree.
    """
    chosen: CalibrationSample | None = None
    for sample in samples:
        if chosen is None or sample.round_trip <= chosen.round_trip:
            chosen = sample
    return chosen


def bound_window(
    samples: tuple[CalibrationSample, ...], sample: CalibrationSample, keep: int
) -> tuple[CalibrationSample, ...]:
    """Append a sample and drop whatever no longer fits.

    Args:
        samples: The window as it stands.
        sample: The sample to add.
        keep: How many to retain.

    Returns:
        The new window, oldest first, never longer than ``keep``.

    Raises:
        ValidationError: If ``keep`` is not positive.

    A function rather than a method on a collection type, because the window is held
    by a stateful adapter and everything that *decides* about it belongs here where
    it can be tested without one.
    """
    if _require_int(keep, label="a calibration window size") < 1:
        msg = f"a calibration window keeps at least one sample and {keep!r} was asked for"
        raise ValidationError(msg)
    return (*samples, sample)[-keep:]


@dataclass(frozen=True, slots=True)
class JumpVerdict:
    """Whether the host's wall clock was adjusted, and by how much.

    Args:
        direction: Which way it moved, or :attr:`JumpDirection.NONE`.
        divergence_micros: The signed difference between the wall-clock interval
            and the monotonic interval over the same span.
        threshold_micros: The bound that was applied.

    Raises:
        ValidationError: If the direction contradicts the divergence.

    **The measurement is a difference of two intervals, not of two clocks.** Both
    clocks measure the same span; the monotonic one is documented as *"not affected
    by system clock updates"*, so any disagreement between the intervals is the wall
    clock being moved. That is why this works with no reference to the venue at all
    and why it catches an adjustment that happens between calibrations.
    """

    direction: JumpDirection
    divergence_micros: int
    threshold_micros: int

    def __post_init__(self) -> None:
        """Refuse a verdict whose direction and divergence disagree."""
        if self.direction is JumpDirection.NONE and abs(self.divergence_micros) > (
            self.threshold_micros
        ):
            msg = (
                f"a jump verdict reports no jump and a divergence of "
                f"{self.divergence_micros} microseconds beyond a threshold of "
                f"{self.threshold_micros}"
            )
            raise ValidationError(msg)
        if self.direction is JumpDirection.FORWARD and self.divergence_micros <= 0:
            msg = f"a forward jump reports a divergence of {self.divergence_micros}"
            raise ValidationError(msg)
        if self.direction is JumpDirection.BACKWARD and self.divergence_micros >= 0:
            msg = f"a backward jump reports a divergence of {self.divergence_micros}"
            raise ValidationError(msg)

    @property
    def detected(self) -> bool:
        """Whether a jump was found."""
        return self.direction is not JumpDirection.NONE

    def as_record(self) -> dict[str, object]:
        """This verdict as plain JSON-safe values."""
        return {
            "detected": self.detected,
            "direction": self.direction.value,
            "divergence_millis": self.divergence_micros // MICROSECONDS_PER_MILLISECOND,
            "divergence_bucket": offset_bucket(self.divergence_micros),
            "threshold_millis": self.threshold_micros // MICROSECONDS_PER_MILLISECOND,
        }


@dataclass(frozen=True, slots=True)
class ClockAnchor:
    """Both host clocks, read at one moment, so a later pair can be compared to them.

    Args:
        wall: What the host's wall clock said.
        monotonic: What the host's monotonic clock said, adjacently.

    Raises:
        ValidationError: If either reading is not of its own type.

    **The pair is the unit, which is why it is a type rather than two arguments.**
    A jump is detected by comparing two *intervals* over the same span, so a wall
    reading is only ever useful beside the monotonic reading taken with it. Passing
    them separately made it possible to compare a wall reading from one moment
    against a monotonic reading from another — a silent, unfalsifiable error that
    this type removes by construction.
    """

    wall: Instant
    monotonic: MonotonicReading

    def __post_init__(self) -> None:
        """Refuse a pair that is not two clock readings."""
        _require_kind(self.wall, Instant, label="a clock anchor wall reading")
        _require_kind(self.monotonic, MonotonicReading, label="a clock anchor monotonic reading")


def detect_jump(
    *,
    earlier: ClockAnchor,
    later: ClockAnchor,
    discipline: ClockDiscipline,
) -> JumpVerdict:
    """Compare a wall-clock interval against a monotonic one over the same span.

    Args:
        earlier: Both clocks, read at the start of the span.
        later: Both clocks, read at the end of it.
        discipline: Whose ``max_wall_divergence`` is the threshold.

    Returns:
        The verdict.

    Raises:
        ValidationError: If ``later``'s monotonic reading precedes ``earlier``'s.

    The wall difference is computed as a subtraction of two
    :attr:`~globin.domain.clock.Instant.epoch_micros` values rather than through a
    :class:`~globin.domain.clock.Duration`, and that is required rather than
    convenient: ``Duration`` refuses a negative count, and a wall clock that was set
    **backwards** produces exactly that. ``docs/TIME_POLICY.md`` already names this
    as the case where an explicit epoch subtraction is the right tool — *"a caller
    that genuinely wants a wall-clock difference"* — and this is that caller.
    """
    elapsed = later.monotonic.since(earlier.monotonic)
    wall_delta = later.wall.epoch_micros - earlier.wall.epoch_micros
    divergence = wall_delta - elapsed.microseconds
    threshold = discipline.max_wall_divergence.microseconds
    if abs(divergence) <= threshold:
        direction = JumpDirection.NONE
    elif divergence > 0:
        direction = JumpDirection.FORWARD
    else:
        direction = JumpDirection.BACKWARD
    return JumpVerdict(
        direction=direction, divergence_micros=divergence, threshold_micros=threshold
    )


@dataclass(frozen=True, slots=True)
class ClockStatus:
    """Everything known about one clock domain right now.

    Args:
        domain: Which clock.
        state: How much it is trusted.
        sample: The chosen sample, when there is one.
        age: How long since that sample was taken.
        jump: The most recent jump verdict, when one has been taken.
        detail: What an operator should read.

    Raises:
        ValidationError: If a synchronized status carries no sample, or an
            uninitialized one carries a sample, or a non-admitting status explains
            nothing.

    **The refusal is the type doing the work**, exactly as
    :class:`~globin.domain.rest_endpoint.EndpointResolution` describes: a status
    that admits nothing but still offered a usable sample would invite a caller to
    read past the state.
    """

    domain: ClockDomain
    state: SyncState
    sample: CalibrationSample | None = None
    age: Duration | None = None
    jump: JumpVerdict | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        """Refuse a status that says one thing and carries another."""
        if self.state.admits and self.sample is None:
            msg = "a clock status reports synchronized and carries no calibration sample"
            raise ValidationError(msg)
        if self.state is SyncState.UNINITIALIZED and self.sample is not None:
            msg = (
                "a clock status reports uninitialized and carries a calibration sample; "
                "a domain that has never calibrated has nothing to offer"
            )
            raise ValidationError(msg)
        if not self.state.admits and not self.detail:
            msg = f"a clock status reports {self.state.value} and explains nothing"
            raise ValidationError(msg)

    @property
    def synchronized(self) -> bool:
        """Whether a signature may be produced against this status."""
        return self.state.admits

    def as_record(self) -> dict[str, object]:
        """This status as plain JSON-safe values, with every unbounded value bucketed."""
        return {
            "domain": self.domain.as_record(),
            "state": self.state.value,
            "synchronized": self.synchronized,
            "sample": self.sample.as_record() if self.sample else None,
            "age_millis": self.age.milliseconds if self.age else None,
            "age_bucket": round_trip_bucket(self.age.microseconds) if self.age else None,
            "jump": self.jump.as_record() if self.jump else None,
            "detail": self.detail,
        }


def evaluate(
    domain: ClockDomain,
    *,
    samples: tuple[CalibrationSample, ...],
    age: Duration | None,
    discipline: ClockDiscipline,
    last_probe_failed: bool = False,
    jump: JumpVerdict | None = None,
    invalidated: bool = False,
) -> ClockStatus:
    """Fold what is known about a domain into one state.

    Args:
        domain: Which clock.
        samples: The calibration window.
        age: How long since the chosen sample was taken, or ``None`` when there is
            no sample.
        discipline: The thresholds to apply.
        last_probe_failed: Whether the most recent calibration attempt failed.
        jump: The most recent jump verdict, when one has been taken.
        invalidated: Whether something has actively disbelieved the estimate — a
            venue ``-1021``, or an offset that moved further than the bound.

    Returns:
        The status.

    The order below is the state machine, and each branch refuses before the next is
    reached — the shape :func:`globin.domain.rest_endpoint.resolve` and
    :func:`globin.application.auth.resolve_auth` already use:

    1. a jump, or an explicit invalidation, wins over everything. Being *told* the
       estimate is wrong outranks the estimate looking fine;
    2. no sample at all is :attr:`SyncState.UNINITIALIZED`;
    3. a failed probe with a sample inside the grace period is
       :attr:`SyncState.DEGRADED`; past the grace period it is
       :attr:`SyncState.STALE`, because a sample nobody has refreshed for that long
       is old rather than merely unrefreshed;
    4. an aged sample is :attr:`SyncState.STALE`;
    5. a sample outside the round-trip or uncertainty bounds is
       :attr:`SyncState.DEGRADED` — it is a real measurement and it is not one
       GLOBIN will sign with;
    6. anything left is :attr:`SyncState.SYNCHRONIZED`.
    """
    chosen = choose_sample(samples)
    if jump is not None and jump.detected:
        return ClockStatus(
            domain=domain,
            state=SyncState.UNSYNCHRONIZED,
            sample=chosen,
            age=age,
            jump=jump,
            detail=(
                f"the host wall clock moved {jump.direction.value} by "
                f"{jump.divergence_micros // MICROSECONDS_PER_MILLISECOND}ms relative to the "
                "monotonic clock; the calibration is disbelieved until one is taken again"
            ),
        )
    if invalidated:
        return ClockStatus(
            domain=domain,
            state=SyncState.UNSYNCHRONIZED,
            sample=chosen,
            age=age,
            jump=jump,
            detail=(
                "the calibration for this domain was invalidated; recalibrate before signing "
                "anything against it"
            ),
        )
    if chosen is None:
        return ClockStatus(
            domain=domain,
            state=SyncState.UNINITIALIZED,
            age=None,
            jump=jump,
            detail=(
                f"no calibration has succeeded for {domain.label}; GLOBIN signs nothing against "
                "a clock it has never checked"
            ),
        )
    elapsed = age or Duration(0)
    if last_probe_failed:
        state = SyncState.DEGRADED if elapsed <= discipline.degraded_grace else SyncState.STALE
        return ClockStatus(
            domain=domain,
            state=state,
            sample=chosen,
            age=elapsed,
            jump=jump,
            detail=(
                f"the most recent server-time probe for {domain.label} failed and the surviving "
                f"sample is {elapsed.milliseconds}ms old"
            ),
        )
    if elapsed > discipline.freshness_ttl:
        return ClockStatus(
            domain=domain,
            state=SyncState.STALE,
            sample=chosen,
            age=elapsed,
            jump=jump,
            detail=(
                f"the calibration for {domain.label} is {elapsed.milliseconds}ms old and the "
                f"freshness interval is {discipline.freshness_ttl.milliseconds}ms"
            ),
        )
    if chosen.round_trip > discipline.max_round_trip:
        return ClockStatus(
            domain=domain,
            state=SyncState.DEGRADED,
            sample=chosen,
            age=elapsed,
            jump=jump,
            detail=(
                f"the fastest sample for {domain.label} took {chosen.round_trip.milliseconds}ms "
                f"and the limit is {discipline.max_round_trip.milliseconds}ms"
            ),
        )
    if chosen.uncertainty_micros > discipline.max_uncertainty.microseconds:
        return ClockStatus(
            domain=domain,
            state=SyncState.DEGRADED,
            sample=chosen,
            age=elapsed,
            jump=jump,
            detail=(
                f"the best estimate for {domain.label} could be wrong by "
                f"{chosen.uncertainty_micros // MICROSECONDS_PER_MILLISECOND}ms and the limit is "
                f"{discipline.max_uncertainty.milliseconds}ms"
            ),
        )
    return ClockStatus(domain=domain, state=SyncState.SYNCHRONIZED, sample=chosen, age=elapsed)


def offset_moved_too_far(
    previous: CalibrationSample | None, current: CalibrationSample, discipline: ClockDiscipline
) -> bool:
    """Whether the estimated offset moved further than a venue clock plausibly could.

    Args:
        previous: The sample the domain was previously anchored on, if any.
        current: The sample just taken.
        discipline: Whose ``max_offset_jump`` is the bound.

    Returns:
        ``True`` when the two offsets differ by more than the bound.

    **The asymmetry is the argument.** Venue clocks are disciplined and do not step;
    host clocks are stepped by operators and by time services. So a large movement in
    the *difference* between them is evidence about this machine, and re-anchoring
    silently on the new value would be GLOBIN adopting a fault as a fact.
    """
    if previous is None:
        return False
    return abs(current.offset_micros - previous.offset_micros) > (
        discipline.max_offset_jump.microseconds
    )


@dataclass(frozen=True, slots=True)
class RecvWindowPolicy:
    """The one place a validity window is decided, and the one place it cannot grow.

    Args:
        window: The window GLOBIN will send.

    **There is no adaptive branch here, and its absence is the deliverable.** The
    obvious "helpful" behaviour — widen the window when the clock looks uncertain —
    is precisely the behaviour that converts a clock fault into an accepted stale
    request, and the venue's second timing check means a wide window buys nothing
    against the delay GLOBIN actually cannot see. When the window does not cover the
    budget, :func:`admit` **refuses**.

    The venue's ceiling is not enforced here because it cannot be reached here:
    :class:`~globin.domain.auth_timing.RecvWindow` refuses anything above 60000 at
    construction, so a policy holding an over-large window cannot exist. That is the
    same division of labour ``LoopbackAddress`` has with the diagnostics surface —
    the type refuses the value, and the policy above it never has to.
    """

    window: RecvWindow

    def __post_init__(self) -> None:
        """Refuse anything that is not a window."""
        _require_kind(self.window, RecvWindow, label="a recvWindow policy window")

    @property
    def micros(self) -> int:
        """The window in whole microseconds.

        Returns:
            The exact count.

        Exact because the window is a :class:`~decimal.Decimal` with at most three
        decimal places of a millisecond, so multiplying by a thousand lands on an
        integer with nothing to round. A ``float`` here would reintroduce the error
        :class:`~globin.domain.auth_timing.RecvWindow` exists to prevent.
        """
        return int(self.window.millis * MICROSECONDS_PER_MILLISECOND)

    def covers(self, required_micros: int) -> bool:
        """Whether this window leaves room for a required allowance.

        Args:
            required_micros: What must fit inside it.

        Returns:
            ``True`` when the window is at least as wide.
        """
        return self.micros >= required_micros

    def as_record(self) -> dict[str, object]:
        """This policy as plain JSON-safe values."""
        return {
            "window": self.window.as_record(),
            "window_micros": self.micros,
            "adaptive": False,
            "ceiling_enforced_by": "RecvWindow",
        }


@dataclass(frozen=True, slots=True)
class TimingContext:
    """The timing half of one signed request, fixed before any byte is signed.

    Args:
        domain: Which clock produced it.
        timestamp: The value the ``timestamp`` parameter will carry.
        unit: Which unit that value is in.
        recv_window: The window the request will carry.
        offset_micros: The correction applied to the host clock.
        uncertainty_micros: How far that correction could be wrong.
        round_trip_micros: The round trip of the sample it came from.
        attempt: Which attempt this is, counting from zero.

    Raises:
        ValidationError: If the timestamp is not a positive integer, or the attempt
            exceeds :data:`MAX_TIMING_RETRIES`.

    **This type is the answer to "one timing context per signature operation."** It
    is produced only by a successful :func:`admit`, and
    :func:`globin.application.auth.sign_request` receives it instead of a clock. So
    there is no object in scope during canonicalisation that could produce a second
    timestamp — the guarantee is a property of the object graph rather than a rule
    somebody has to keep following, which is the same move
    :class:`~globin.domain.rest_endpoint.EndpointResolution` makes by giving a
    refusal no endpoint to read.
    """

    domain: ClockDomain
    timestamp: int
    unit: TimestampUnit
    recv_window: RecvWindow
    offset_micros: int
    uncertainty_micros: int
    round_trip_micros: int
    attempt: int = 0

    def __post_init__(self) -> None:
        """Refuse a context that could not have come from an admission."""
        _require_int(self.timestamp, label="a timing context timestamp")
        if self.timestamp <= 0:
            msg = f"a timing context carries a timestamp of {self.timestamp}, which is not a moment"
            raise ValidationError(msg)
        _require_int(self.attempt, label="a timing context attempt")
        if not 0 <= self.attempt <= MAX_TIMING_RETRIES:
            msg = (
                f"a timing context reports attempt {self.attempt} and at most "
                f"{MAX_TIMING_RETRIES} timing retry is permitted"
            )
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This context as plain JSON-safe values.

        Returns:
            Everything except the timestamp itself, which is published as its
            bucketed provenance instead.

        **The timestamp is deliberately absent**, and not because it is a secret. It
        is a per-request value, so publishing it into a diagnostic dimension would
        make every request its own series — the unbounded cardinality
        ``docs/TELEMETRY_POLICY.md`` refuses. An operator who needs the exact value
        has it in the request itself.
        """
        return {
            "domain": self.domain.label,
            "unit": self.unit.value,
            "recv_window": self.recv_window.as_record(),
            "offset_bucket": offset_bucket(self.offset_micros),
            "uncertainty_bucket": round_trip_bucket(self.uncertainty_micros),
            "round_trip_bucket": round_trip_bucket(self.round_trip_micros),
            "attempt": self.attempt,
        }


@dataclass(frozen=True, slots=True)
class TimingAdmission:
    """Whether a request may be stamped, and with what.

    Args:
        outcome: The verdict.
        domain: Which clock was consulted.
        state: What that clock's state was.
        context: The timing context, on an admission only.
        detail: What an operator should read, on a refusal only.

    Raises:
        ValidationError: If an admission carries no context, a refusal carries one,
            or a refusal explains nothing.

    **Returned, never raised.** A timing refusal is a value a caller records and
    reports, and raising would push the classification back out to every call site —
    the argument :class:`~globin.domain.rest.RestExchange` makes at length. It is
    also emphatically *not* a transport failure: nothing here shares a type with
    :class:`~globin.domain.rest.TransportFailureKind`, so a caller cannot retry a
    clock problem by mistaking it for a dropped connection.
    """

    outcome: AdmissionStatus
    domain: ClockDomain
    state: SyncState
    context: TimingContext | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        """Refuse an admission that says one thing and carries another."""
        if self.outcome.permits and self.context is None:
            msg = "a timing admission permits signing and carries no timing context"
            raise ValidationError(msg)
        if not self.outcome.permits and self.context is not None:
            msg = (
                f"a timing admission reports {self.outcome.value} and still carries a timing "
                "context; a refusal must offer nothing to stamp with"
            )
            raise ValidationError(msg)
        if not self.outcome.permits and not self.detail:
            msg = f"a timing admission reports {self.outcome.value} and explains nothing"
            raise ValidationError(msg)

    @property
    def admitted(self) -> bool:
        """Whether a timestamp was produced."""
        return self.outcome.permits

    def as_record(self) -> dict[str, object]:
        """This admission as plain JSON-safe values."""
        return {
            "outcome": self.outcome.value,
            "admitted": self.admitted,
            "domain": self.domain.as_record(),
            "state": self.state.value,
            "context": self.context.as_record() if self.context else None,
            "detail": self.detail,
        }


def corrected_stamp(moment: Instant, offset_micros: int, unit: TimestampUnit) -> int:
    """The host's idea of now, corrected to the venue's clock, in the requested unit.

    Args:
        moment: The host's wall clock, from a :class:`~globin.ports.clock.Clock`.
        offset_micros: How far ahead of the host the venue is. Signed.
        unit: Which unit the ``timestamp`` parameter should carry.

    Returns:
        The count since the Unix epoch, corrected.

    Raises:
        ValidationError: If the offset is not an :class:`int`.

    **Exactly one flooring step, and it happens last.** The correction is applied in
    microseconds — the unit :attr:`~globin.domain.clock.Instant.epoch_micros`
    reports exactly — and only then is a millisecond request floored. Correcting a
    value that had already been floored would throw the sub-millisecond part away
    and *then* add a correction derived from it, which is the shape of error a unit
    conversion exists to prevent.

    Flooring towards the past is ``docs/TIME_POLICY.md``'s existing rule, and here it
    is load-bearing rather than merely consistent: the venue's second timing check
    has no future tolerance at all, so a timestamp that rounded *up* would spend an
    allowance that check does not grant.
    """
    corrected = moment.epoch_micros + _require_int(
        offset_micros, label="a clock offset in microseconds"
    )
    if unit is TimestampUnit.MICROSECONDS:
        return corrected
    return corrected // MICROSECONDS_PER_MILLISECOND


def admit(
    status: ClockStatus,
    *,
    moment: Instant,
    unit: TimestampUnit,
    policy: RecvWindowPolicy,
    discipline: ClockDiscipline,
    source_available: bool = True,
    attempt: int = 0,
) -> TimingAdmission:
    """Decide whether a signed request may be stamped, and produce the stamp.

    Args:
        status: What is known about the clock domain.
        moment: The host's wall clock, read once by the caller.
        unit: Which unit the ``timestamp`` parameter should carry.
        policy: The validity window that would be sent.
        discipline: The thresholds to apply.
        source_available: Whether a server-time source is declared for this domain
            at all.
        attempt: Which attempt this is. Non-zero only on a bounded timing retry.

    Returns:
        An admission carrying a :class:`TimingContext`, or a refusal naming why.

    Seven gates, each refusing before the next is reached and ordered cheapest and
    broadest first, so an operator reads the outermost thing that is wrong:

    1. a server-time source is declared for this domain;
    2. a calibration has succeeded;
    3. the estimate has not been disbelieved;
    4. it is fresh;
    5. its error bound is inside the declared limit;
    6. the round trip it came from is inside the declared limit;
    7. the window covers the uncertainty and the network budget.

    **Gate 7 splits into two refusals because they have different remedies.** When
    the required allowance is wider than the largest window the venue accepts, no
    configuration could cover it and the answer is
    :attr:`AdmissionStatus.TIMING_BUDGET_EXCEEDED` - fix the network or the clock.
    When it merely exceeds the *configured* window, the answer is
    :attr:`AdmissionStatus.RECV_WINDOW_POLICY_VIOLATION` - an operator may widen it,
    within the ceiling. Collapsing them would tell half of the operators to do
    something that cannot work.

    **There is no future-side gate, and its absence is the design.** The venue's
    ``+ 1 second`` allowance can only be breached by the estimate being wrong, and
    :class:`ClockDiscipline` refuses at construction to admit a ``max_uncertainty``
    that reaches it. Gate 5 then bounds every sample by that limit, so a runtime
    check here could never fire - and this repository does not write a threshold
    that cannot fire. Transit time cannot breach it either: it advances the venue's
    clock while the request is in flight, so it is spent against the window instead.
    """
    if not source_available:
        return _refuse(
            AdmissionStatus.CLOCK_SOURCE_UNAVAILABLE,
            status,
            detail=(
                f"no server-time source is declared for {status.domain.label}; the registry "
                "records no endpoint for it and a path is never guessed"
            ),
        )
    if status.state is SyncState.UNINITIALIZED:
        return _refuse(
            AdmissionStatus.CLOCK_NOT_SYNCHRONIZED,
            status,
            detail=status.detail or f"{status.domain.label} has never been calibrated",
        )
    if status.state is SyncState.UNSYNCHRONIZED:
        jumped = status.jump is not None and status.jump.detected
        return _refuse(
            AdmissionStatus.CLOCK_JUMP_DETECTED
            if jumped
            else AdmissionStatus.CLOCK_NOT_SYNCHRONIZED,
            status,
            detail=status.detail,
        )
    if status.state in {SyncState.STALE, SyncState.DEGRADED}:
        return _refuse(AdmissionStatus.CLOCK_CALIBRATION_STALE, status, detail=status.detail)
    sample = status.sample
    if sample is None:
        return _refuse(
            AdmissionStatus.CLOCK_NOT_SYNCHRONIZED,
            status,
            detail=f"{status.domain.label} reports synchronized and offers no sample",
        )
    if sample.uncertainty_micros > discipline.max_uncertainty.microseconds:
        return _refuse(
            AdmissionStatus.CLOCK_UNCERTAINTY_EXCEEDED,
            status,
            detail=(
                f"the estimate for {status.domain.label} could be wrong by "
                f"{sample.uncertainty_micros // MICROSECONDS_PER_MILLISECOND}ms and the limit is "
                f"{discipline.max_uncertainty.milliseconds}ms"
            ),
        )
    if sample.round_trip > discipline.max_round_trip:
        return _refuse(
            AdmissionStatus.CLOCK_UNCERTAINTY_EXCEEDED,
            status,
            detail=(
                f"the sample for {status.domain.label} took {sample.round_trip.milliseconds}ms "
                f"and the limit is {discipline.max_round_trip.milliseconds}ms"
            ),
        )
    required = sample.uncertainty_micros + discipline.network_budget.microseconds
    if required > max_window_micros():
        return _refuse(
            AdmissionStatus.TIMING_BUDGET_EXCEEDED,
            status,
            detail=(
                f"{required // MICROSECONDS_PER_MILLISECOND}ms of clock uncertainty and network "
                f"budget exceeds {MAX_RECV_WINDOW_MILLIS}ms, which is the widest window the venue "
                "accepts; no configuration could cover this, so the remedy is the network or the "
                "clock rather than the window"
            ),
        )
    if not policy.covers(required):
        return _refuse(
            AdmissionStatus.RECV_WINDOW_POLICY_VIOLATION,
            status,
            detail=(
                f"a recvWindow of {policy.window} does not cover "
                f"{required // MICROSECONDS_PER_MILLISECOND}ms of clock uncertainty and network "
                "budget; GLOBIN refuses rather than widening it here, because the venue re-checks "
                "the window again before the matching engine and a window widened by GLOBIN would "
                "not be one the operator chose"
            ),
        )
    return TimingAdmission(
        outcome=AdmissionStatus.ADMITTED,
        domain=status.domain,
        state=status.state,
        context=TimingContext(
            domain=status.domain,
            timestamp=corrected_stamp(moment, sample.offset_micros, unit),
            unit=unit,
            recv_window=policy.window,
            offset_micros=sample.offset_micros,
            uncertainty_micros=sample.uncertainty_micros,
            round_trip_micros=sample.round_trip.microseconds,
            attempt=attempt,
        ),
    )


def _refuse(outcome: AdmissionStatus, status: ClockStatus, *, detail: str) -> TimingAdmission:
    """Build a refusal that carries no timing context.

    Args:
        outcome: Why it is refused.
        status: What was known about the clock.
        detail: What an operator should read.

    Returns:
        The refusal.
    """
    return TimingAdmission(
        outcome=outcome,
        domain=status.domain,
        state=status.state,
        detail=detail or f"{status.domain.label} is {status.state.value}",
    )


def recovery_for(
    *,
    exchange_code: int,
    outcome: RequestOutcome,
    side_effect: SideEffect,
    idempotent: bool = False,
    attempt: int = 0,
) -> TimingRecovery:
    """Decide what a timing rejection permits, and nothing more.

    Args:
        exchange_code: The venue's error code, if any.
        outcome: How Phase 034 classified the exchange.
        side_effect: What was at stake.
        idempotent: Whether the caller has declared that re-sending this request
            cannot create a second effect.
        attempt: How many times it has already been sent, counting from zero.

    Returns:
        The verdict.

    **This function decides; it does not act.** Nothing in Phase 036 sends a signed
    request, so a retry executor here would be a mechanism with no caller — which
    this repository has deleted once already. Phase 043 owns the executor and
    inherits this verdict.

    The rules, in the order they are applied and with the reason each is not the
    other way round:

    1. a code other than :data:`INVALID_TIMESTAMP_CODE` is not this module's
       business at all;
    2. an outcome that is not a **confirmed** failure gets
       :attr:`TimingRecovery.RESYNC_ONLY`. ADR-0089's rule is that a request whose
       fate is unknown is never replayed, and a timing rejection does not earn an
       exception to it. Note that ``-1021`` is declared unambiguous precisely so
       this branch is reachable rather than universal;
    3. a request already re-sent :data:`MAX_TIMING_RETRIES` times gets
       ``RESYNC_ONLY``. The bound is the whole safety property;
    4. a read-only request, or one the caller has explicitly declared idempotent,
       may be sent once more;
    5. anything else — a write with no idempotency declaration — gets
       ``RESYNC_ONLY``. **Silence is not a declaration.** A caller that has not said
       a re-send is safe has not said it is safe.
    """
    if exchange_code != INVALID_TIMESTAMP_CODE:
        return TimingRecovery.NO_ACTION
    if outcome is not RequestOutcome.FAILURE_CONFIRMED:
        return TimingRecovery.RESYNC_ONLY
    if attempt >= MAX_TIMING_RETRIES:
        return TimingRecovery.RESYNC_ONLY
    if side_effect is SideEffect.READ_ONLY or idempotent:
        return TimingRecovery.RESYNC_AND_RETRY_ONCE
    return TimingRecovery.RESYNC_ONLY


def round_trip_bucket(micros: int) -> str:
    """Which declared bucket a duration falls in.

    Args:
        micros: The duration, in microseconds.

    Returns:
        One of the labels :data:`ROUND_TRIP_BUCKET_BOUNDS_MILLIS` implies, or
        :data:`OVERFLOW_BUCKET`.

    Nine possible answers and no tenth, which is what makes this safe to publish as
    a diagnostic dimension. A raw nanosecond count would give every observation its
    own value, and ``docs/TELEMETRY_POLICY.md`` requires a value set that can be
    counted at the moment the dimension is written.
    """
    millis = micros // MICROSECONDS_PER_MILLISECOND
    for bound in ROUND_TRIP_BUCKET_BOUNDS_MILLIS:
        if millis <= bound:
            return f"<={bound}ms"
    return OVERFLOW_BUCKET


def offset_bucket(micros: int) -> str:
    """Which declared bucket a signed offset falls in.

    Args:
        micros: The offset, in microseconds. Negative means the host is ahead.

    Returns:
        A sign and a magnitude bucket.

    The sign is kept because *which way* a clock is wrong changes what an operator
    does about it, and it costs one bit of cardinality rather than an unbounded set.
    """
    sign = "-" if micros < 0 else "+"
    millis = abs(micros) // MICROSECONDS_PER_MILLISECOND
    for bound in OFFSET_BUCKET_BOUNDS_MILLIS:
        if millis <= bound:
            return f"{sign}<={bound}ms"
    return f"{sign}{OVERFLOW_BUCKET}"


__all__ = [
    "DEFAULT_SAMPLE_COUNT",
    "FUTURE_TOLERANCE_MILLIS",
    "INVALID_TIMESTAMP_CODE",
    "MAX_SAMPLE_COUNT",
    "MAX_TIMING_RETRIES",
    "OFFSET_BUCKET_BOUNDS_MILLIS",
    "ROUND_TRIP_BUCKET_BOUNDS_MILLIS",
    "SERVER_TIME_FIELD",
    "AdmissionStatus",
    "CalibrationSample",
    "ClockAnchor",
    "ClockDiscipline",
    "ClockDomain",
    "ClockStatus",
    "JumpDirection",
    "JumpVerdict",
    "RecvWindowPolicy",
    "ServerTimeReading",
    "SyncState",
    "TimingAdmission",
    "TimingContext",
    "TimingRecovery",
    "admit",
    "bound_window",
    "choose_sample",
    "corrected_stamp",
    "default_discipline",
    "detect_jump",
    "evaluate",
    "max_window_micros",
    "offset_bucket",
    "offset_moved_too_far",
    "recovery_for",
    "round_trip_bucket",
    "sample_offset",
    "server_time_from",
]
