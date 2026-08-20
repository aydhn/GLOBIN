"""Asking a venue what time it is, and holding what it said for more than one caller.

Two things live here that cannot live anywhere else, and each is here for its own
reason.

:class:`RestServerTimeSource` reaches the venue, which only an adapter may do. It
drives Phase 034's transport rather than opening anything itself — there is no
second HTTP client in this repository and
``tests/architecture/test_library_discipline.py`` fails if one appears.

:class:`ClockManager` holds state and a lock. ``threading`` is I/O-capable in
``docs/architecture/dependency-rules.toml``, so the application layer may not
import it; every *decision* the manager makes is therefore delegated to
:mod:`globin.application.clock_sync`, and what remains here is bookkeeping.

**This module reads no clock**, which is what keeps
``tests/architecture/test_clock_discipline.py`` asserting that exactly one adapter
does. Both clocks arrive as ports and are read through them.

**Nothing here retries, and nothing here decides.** A failed probe becomes a
recorded failure; a stale domain becomes one calibration flight, not one per
caller; and whether a sample may be signed against is
:func:`globin.domain.clock_sync.admit`'s question, asked with values this module
merely stores.
"""

import threading
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from globin.application.clock_sync import (
    CalibrationOutcome,
    admit_request,
    read_server_time,
    status_for,
    take_sample,
)
from globin.application.rest import run_probe
from globin.domain.api_reality import ApiRealitySnapshot, SurfaceCapability
from globin.domain.auth_timing import RecvWindow, TimestampUnit
from globin.domain.clock import Duration, MonotonicReading
from globin.domain.clock_sync import (
    CalibrationSample,
    ClockAnchor,
    ClockDiscipline,
    ClockDomain,
    ClockStatus,
    ServerTimeReading,
    TimingAdmission,
    bound_window,
    choose_sample,
    default_discipline,
)
from globin.domain.rest import RequestOutcome
from globin.domain.rest_contract import TransportContract
from globin.domain.rest_endpoint import resolve
from globin.errors import ValidationError
from globin.ports.clock import Clock, MonotonicClock, ServerTimeSource
from globin.ports.rest import RestTransport

DEFAULT_FLIGHT_TIMEOUT_SECONDS: float = 30.0
"""How long a waiting caller will wait for somebody else's calibration.

A bound rather than a preference: without one, a leader wedged inside a socket read
would hold every other caller for ever, which is the failure a single-flight
mechanism is otherwise prone to. A waiter that gives up records a failure and
touches no shared state.
"""

CONTRACT_RELATIVE_PATH: str = "docs/engineering/clock-contract.toml"
"""Where the declared half of the clock layer lives, relative to the project root."""


@dataclass(frozen=True, slots=True)
class RestServerTimeSource:
    """The venue's server time, over Phase 034's REST transport.

    Args:
        transport: How a request is sent. The only object here that reaches a
            socket.
        snapshot: Phase 033's registry, the only source of endpoints.
        contract: The declared transport contract, the only source of paths.
        stale_sources: Source identifiers past their re-check interval.
        correlation: How a correlation id is minted for each exchange.

    **It resolves per call and caches nothing.** A cached resolution would survive a
    source going stale, which is the one condition Phase 034's ninth gate exists to
    catch.

    **It asks for milliseconds, and that is a measurement rather than laziness.**
    The venue documents ``X-MBX-TIME-UNIT: MICROSECOND`` and GLOBIN could negotiate
    it, but the gain would be to remove a half-millisecond quantisation from an
    estimate whose stated uncertainty is half a round trip — tens of milliseconds on
    any real link. Sending a header to improve an error term by three orders of
    magnitude less than the term itself would be precision theatre. The unit that
    *arrived* is recorded on every sample regardless, so a future change is visible
    rather than assumed.
    """

    transport: RestTransport
    snapshot: ApiRealitySnapshot
    contract: TransportContract
    correlation: Callable[[], str]
    stale_sources: tuple[str, ...] = ()

    def sample(self, domain: ClockDomain) -> ServerTimeReading | None:
        """Ask one clock domain for its current time.

        Args:
            domain: Which venue clock to ask.

        Returns:
            The reading, or ``None`` when the domain does not resolve, declares no
            probe, does not answer, or answers something that is not the documented
            shape.

        Raises:
            ValidationError: Never for a venue or network condition. Only a defect
                in GLOBIN reaches this, and Phase 034's transport already holds that
                line.

        Four ways this returns ``None``, and none of them is an exception:

        1. the endpoint does not resolve — an undocumented surface, an unsupported
           environment, or evidence past its re-check interval;
        2. the transport contract declares no ``{family}.time`` probe, so there is
           no path and one is never guessed;
        3. the exchange did not confirm success;
        4. the body was not the object the venue documents.

        The fourth is worth stating separately: a body that parsed but carried no
        ``serverTime`` is a **usable** HTTP response and an **unusable** clock
        reading, and collapsing those would let a changed venue contract look like a
        network problem.
        """
        resolution = resolve(
            self.snapshot,
            family=domain.family,
            environment=domain.environment,
            capability=SurfaceCapability.MARKET_DATA,
            stale_sources=self.stale_sources,
        )
        if not resolution.permitted:
            return None
        descriptor = self.contract.probe(domain.family, f"{domain.family.slug}.time")
        if descriptor is None:
            return None
        exchange = run_probe(
            self.transport,
            resolution,
            operation=descriptor.operation,
            method=descriptor.method,
            path=descriptor.path,
            correlation_id=self.correlation(),
        )
        if exchange.outcome is not RequestOutcome.SUCCESS_CONFIRMED or exchange.response is None:
            return None
        try:
            return read_server_time(exchange.response.payload, TimestampUnit.MILLISECONDS)
        except ValidationError:
            return None


@dataclass(slots=True)
class _DomainState:
    """One clock domain's mutable bookkeeping, guarded by the manager's lock.

    Deliberately not frozen and deliberately private. It is the only mutable state
    in the clock layer, it never leaves this module, and every rule applied to it
    lives somewhere that can be tested without it.
    """

    samples: tuple[CalibrationSample, ...] = ()
    anchor: ClockAnchor | None = None
    last_probe_failed: bool = False
    invalidated: bool = False
    invalidation_reason: str = ""


@dataclass(slots=True)
class _Flight:
    """One in-progress calibration that other callers may wait on.

    ``done`` is set exactly once, in a ``finally``, so a leader that raises still
    releases every waiter. ``outcome`` is written **before** ``done`` is set, which
    is what makes reading it after a successful wait safe without holding the lock.

    ``waiters`` counts how many callers are parked on this flight. It is bookkeeping
    for :meth:`ClockManager.waiting_on` rather than control flow — nothing here
    branches on it — and it exists because *how many callers a slow venue is
    currently holding* is a real diagnostic question that is otherwise unanswerable
    from outside.
    """

    done: threading.Event
    outcome: CalibrationOutcome | None = None
    waiters: int = 0


class ClockManager:
    """One calibration per domain, shared by every caller that needs it.

    Args:
        source: How the venue is asked.
        clock: The host's wall clock.
        monotonic: The host's monotonic clock.
        discipline: The thresholds to apply, or ``None`` for the declared defaults.
        flight_timeout_seconds: How long a waiter waits for somebody else's
            calibration.

    **A plain class rather than a dataclass**, and for a rule rather than a taste:
    a lock, two registries and a default discipline all want
    ``field(default_factory=...)``, which is a **call in a class body** and
    therefore work performed at import.
    ``tests/architecture/test_architecture_contract.py`` refuses that in every layer
    package — a blanket ban, deliberately stricter than the rule it stands for — and
    :mod:`globin.domain.rest` records the same trap for the same reason. Writing the
    constructor out moves the calls into a function body where they belong.

    **Single-flight per domain, and per domain is the important half.** A stale
    domain with a dozen callers produces one probe, not a dozen — but a *different*
    domain is never blocked by it, because the lock is held only while the small
    bookkeeping happens and never across the exchange itself. That is also what
    makes deadlock impossible here: no code path holds the lock while calling
    anything that could block.

    **A waiter that gives up changes nothing.** It records a failure for itself and
    returns; the leader's own result still lands, and the shared window is exactly
    what it would have been. Cancellation safety is therefore a property of the
    structure rather than a case that has to be handled.
    """

    __slots__ = (
        "_flights",
        "_lock",
        "_states",
        "clock",
        "discipline",
        "flight_timeout_seconds",
        "monotonic",
        "source",
    )

    def __init__(
        self,
        source: ServerTimeSource,
        clock: Clock,
        monotonic: MonotonicClock,
        discipline: ClockDiscipline | None = None,
        flight_timeout_seconds: float = DEFAULT_FLIGHT_TIMEOUT_SECONDS,
    ) -> None:
        """Build a manager holding no calibration for any domain.

        Args:
            source: How the venue is asked.
            clock: The host's wall clock.
            monotonic: The host's monotonic clock.
            discipline: The thresholds, or ``None`` for the declared defaults.
            flight_timeout_seconds: How long a waiter waits.

        **Every domain starts uninitialized and nothing here can change that.**
        There is no path by which a manager begins life believing it knows what time
        the venue thinks it is — no file is read, no offset is restored, and a fresh
        process therefore signs nothing until it has asked. That is the answer to
        "do not trust an old in-memory offset after a restart": there is no old
        offset to trust.
        """
        self.source = source
        self.clock = clock
        self.monotonic = monotonic
        self.discipline = discipline or default_discipline()
        self.flight_timeout_seconds = flight_timeout_seconds
        self._lock = threading.Lock()
        self._states: dict[str, _DomainState] = {}
        self._flights: dict[str, _Flight] = {}

    def calibrate(self, domain: ClockDomain) -> CalibrationOutcome:
        """Take one calibration for a domain, or wait for the one already running.

        Args:
            domain: Which clock to calibrate.

        Returns:
            The outcome. A waiter receives the leader's outcome; a waiter that timed
            out receives a failure of its own that changed no shared state.

        The leader does the exchange **outside** the lock. Holding it across a
        network call would turn one slow venue into a stalled process, and would
        make the timeout below the only thing standing between a wedged socket and a
        deadlock. Here the timeout is a courtesy to waiters rather than a safety
        mechanism.
        """
        key = domain.label
        with self._lock:
            existing = self._flights.get(key)
            previous = choose_sample(self._states.setdefault(key, _DomainState()).samples)
            flight = _Flight(done=threading.Event()) if existing is None else existing
            if existing is None:
                self._flights[key] = flight
        if existing is not None:
            return self._await(domain, existing)
        outcome = CalibrationOutcome(
            domain=domain, failed=True, detail="the calibration did not complete"
        )
        try:
            outcome = take_sample(
                self.source,
                domain,
                clock=self.clock,
                monotonic=self.monotonic,
                previous=previous,
                discipline=self.discipline,
            )
            self._fold(key, outcome)
        finally:
            flight.outcome = outcome
            with self._lock:
                self._flights.pop(key, None)
            flight.done.set()
        return outcome

    def _await(self, domain: ClockDomain, flight: _Flight) -> CalibrationOutcome:
        """Wait for another caller's calibration and take its answer.

        Args:
            domain: Which clock is being calibrated.
            flight: The flight to wait on.

        Returns:
            The leader's outcome, or a failure of this caller's own when the wait
            ran out.

        The failure returned on a timeout is **not** recorded against the domain.
        This caller learned nothing; the leader may still be about to succeed, and
        marking the domain degraded from here would be one caller's impatience
        overwriting another caller's measurement.
        """
        with self._lock:
            flight.waiters += 1
        try:
            if not flight.done.wait(timeout=self.flight_timeout_seconds):
                return CalibrationOutcome(
                    domain=domain,
                    failed=True,
                    detail=(
                        f"waited {self.flight_timeout_seconds:g}s for another caller's calibration "
                        f"of {domain.label} and it had not finished"
                    ),
                )
        finally:
            with self._lock:
                flight.waiters -= 1
        return flight.outcome or CalibrationOutcome(
            domain=domain, failed=True, detail="the calibration completed with no outcome"
        )

    def _fold(self, key: str, outcome: CalibrationOutcome) -> None:
        """Record one outcome against a domain's state.

        Args:
            key: The domain's label.
            outcome: What the calibration produced.

        An offset that moved further than the declared bound **replaces the window
        rather than joining it**, and marks the domain invalidated. Keeping both
        samples would let :func:`~globin.domain.clock_sync.choose_sample` pick
        whichever happened to be faster, which is to say it would pick between two
        contradictory beliefs on a criterion that has nothing to do with which is
        right.
        """
        with self._lock:
            state = self._states.setdefault(key, _DomainState())
            if outcome.failed or outcome.sample is None:
                state.last_probe_failed = True
                return
            state.last_probe_failed = False
            if outcome.offset_jumped:
                state.samples = (outcome.sample,)
                state.invalidated = True
                state.invalidation_reason = outcome.detail
            else:
                state.samples = bound_window(
                    state.samples, outcome.sample, self.discipline.sample_count
                )
                state.invalidated = False
                state.invalidation_reason = ""
            state.anchor = ClockAnchor(wall=self.clock.now(), monotonic=outcome.sample.taken_at)

    def invalidate(self, domain: ClockDomain, reason: str) -> None:
        """Disbelieve a domain's calibration until it is taken again.

        Args:
            domain: Which clock.
            reason: What disbelieved it, for the operator to read.

        What a venue ``-1021`` calls. The window is **kept** rather than cleared, so
        a diagnostic can still report what GLOBIN last believed and how wrong the
        venue said it was; the state is what refuses, and
        :attr:`~globin.domain.clock_sync.SyncState.UNSYNCHRONIZED` refuses whatever
        the window holds.
        """
        with self._lock:
            state = self._states.setdefault(domain.label, _DomainState())
            state.invalidated = True
            state.invalidation_reason = reason

    def status(self, domain: ClockDomain) -> ClockStatus:
        """What is known about one clock domain at this moment.

        Args:
            domain: Which clock.

        Returns:
            The status, including a fresh jump check when the domain has ever been
            calibrated.

        **The jump check happens here rather than at calibration**, and that is the
        point of it. A wall clock adjusted *between* a calibration and a request is
        exactly the case a calibration-time check would miss, and it is the common
        one: a time service corrects the host while GLOBIN sits idle.
        """
        with self._lock:
            state = self._states.get(domain.label, _DomainState())
            samples = state.samples
            anchor = state.anchor
            failed = state.last_probe_failed
            invalidated = state.invalidated
        now = ClockAnchor(wall=self.clock.now(), monotonic=self.monotonic.reading())
        chosen = choose_sample(samples)
        age = now.monotonic.since(chosen.taken_at) if chosen is not None else None
        return status_for(
            domain,
            samples=samples,
            age=age,
            discipline=self.discipline,
            last_probe_failed=failed,
            calibrated_at=anchor,
            now=now,
            invalidated=invalidated,
        )

    def admit(
        self,
        domain: ClockDomain,
        *,
        unit: TimestampUnit,
        window: RecvWindow,
        source_available: bool = True,
        attempt: int = 0,
    ) -> TimingAdmission:
        """Decide whether a signed request may be stamped against one domain.

        Args:
            domain: Which clock.
            unit: Which unit the timestamp should carry.
            window: The validity window that would be sent.
            source_available: Whether the domain can be calibrated at all.
            attempt: Which attempt this is.

        Returns:
            The admission.

        **The wall clock is read once, here, and the same reading is stamped.**
        Reading it again inside the stamping step would open a window — small, and
        exactly the kind that is impossible to reproduce — in which a clock
        adjustment could land between the check and the value it was checking.
        """
        status = self.status(domain)
        return admit_request(
            status,
            moment=self.clock.now(),
            unit=unit,
            window=window,
            discipline=self.discipline,
            source_available=source_available,
            attempt=attempt,
        )

    def calibrate_window(self, domain: ClockDomain) -> tuple[CalibrationOutcome, ...]:
        """Fill a domain's window, one exchange per sample.

        Args:
            domain: Which clock to calibrate.

        Returns:
            One outcome per exchange, in the order they were taken. Failures are
            included rather than dropped, because *three of five succeeded* and
            *three of three succeeded* are different facts about a link.

        **A calibration is a window, not an exchange, and this is the method that
        says so.** :meth:`calibrate` takes one sample because single-flight has to
        be per-exchange; but a window of one gives
        :func:`~globin.domain.clock_sync.choose_sample` nothing to choose between,
        which throws away the whole point of selecting the lowest round trip.

        **It also absorbs the first exchange**, which is the concrete reason this
        method exists rather than being a caller's loop. The first request on a
        fresh pool pays a TCP and TLS handshake; measured against the venue's own
        testnet from the declared host, that first exchange sometimes exceeds the
        transport's timeout outright and returns nothing at all. A single-sample
        calibration reports that as a total failure. A window reports it as one
        failed sample among several and estimates from the rest — which is what the
        pooling behaviour ADR-0093 cites actually requires of a caller.

        Nothing here retries a *failed* sample. Each iteration is one exchange, and
        a link where most of them fail is a link an operator needs told about rather
        than one this method should paper over.
        """
        return tuple(self.calibrate(domain) for _ in range(self.discipline.sample_count))

    def ensure_calibrated(self, domain: ClockDomain) -> ClockStatus:
        """Calibrate a domain if it would not currently admit, then report it.

        Args:
            domain: Which clock.

        Returns:
            The status after at most one calibration.

        **At most one**, and no loop. A domain that is still not synchronised after
        a fresh calibration has something wrong that another probe will not fix —
        the link is too slow, the venue is not answering, or the host clock is
        moving — and retrying would turn a diagnosis into a stall.
        """
        status = self.status(domain)
        if status.synchronized:
            return status
        self.calibrate(domain)
        return self.status(domain)

    def waiting_on(self, domain: ClockDomain) -> int:
        """How many callers are currently parked on a calibration of one domain.

        Args:
            domain: Which clock.

        Returns:
            The count, or ``0`` when no calibration is in flight.

        A diagnostic rather than a control: nothing in this module branches on it.
        It answers the question a stalled operator actually has — *is one slow venue
        holding everything, and how much* — which the single-flight design otherwise
        makes invisible from outside.
        """
        with self._lock:
            flight = self._flights.get(domain.label)
            return flight.waiters if flight else 0

    def known_domains(self) -> tuple[str, ...]:
        """Every domain this manager has state for, in a stable order.

        Returns:
            The labels, sorted.
        """
        with self._lock:
            return tuple(sorted(self._states))


@dataclass(frozen=True, slots=True)
class ClockContract:
    """The declared half of the clock layer, as the committed document states it.

    Args:
        schema: The document's schema version.
        phase: Which phase declared it.
        estimator: Which estimator the document says is used.
        defaults: The declared default thresholds, in milliseconds.
        states: The declared synchronisation states.
        admission: The declared admission outcomes, in gate order.
        recovery: The declared recovery verdicts.
        buckets: The declared bucket bounds.

    **A second statement of what the code does, so that the code can be checked
    rather than believed.** ``docs/engineering/SOURCE_OF_TRUTH.md`` refuses a second
    copy of a rule unless a test compares the copies, and
    ``tests/contract/test_clock_contract.py`` is that test — in both directions, so
    a value here the code does not carry fails, and a value in the code that is not
    declared here fails too.
    """

    schema: int
    phase: int
    estimator: str
    defaults: Mapping[str, int]
    states: tuple[str, ...]
    admission: tuple[str, ...]
    recovery: tuple[str, ...]
    buckets: Mapping[str, tuple[int, ...]]

    def as_record(self) -> dict[str, object]:
        """This contract as plain JSON-safe values."""
        return {
            "schema": self.schema,
            "phase": self.phase,
            "estimator": self.estimator,
            "defaults": dict(sorted(self.defaults.items())),
            "states": list(self.states),
            "admission": list(self.admission),
            "recovery": list(self.recovery),
            "buckets": {name: list(values) for name, values in sorted(self.buckets.items())},
        }


def read_clock_contract(path: Path) -> ClockContract | None:
    """Read the declared clock contract from a committed document.

    Args:
        path: Where the document is.

    Returns:
        The contract, or ``None`` when the document is absent.

    Raises:
        ValidationError: If the document exists and is not readable as this
            contract. An absent document established nothing; a malformed one is a
            defect, and the two are kept apart for the reason
            ``globin.adapters.configuration`` gives about a missing layer.
    """
    if not path.is_file():
        return None
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as fault:
        msg = f"the clock contract at {path.name} could not be read: {fault}"
        raise ValidationError(msg) from fault
    meta = _table(document, "meta", path)
    estimator = _table(document, "estimator", path)
    defaults = _table(document, "defaults", path)
    vocabulary = _table(document, "vocabulary", path)
    buckets = _table(document, "buckets", path)
    return ClockContract(
        schema=_integer(meta, "schema_version", path),
        phase=_integer(meta, "introduced_in_phase", path),
        estimator=_text(estimator, "selection", path),
        defaults={key: _integer(defaults, key, path) for key in sorted(defaults)},
        states=_words(vocabulary, "states", path),
        admission=_words(vocabulary, "admission", path),
        recovery=_words(vocabulary, "recovery", path),
        buckets={key: _numbers(buckets, key, path) for key in sorted(buckets)},
    )


def _table(document: Mapping[str, object], name: str, path: Path) -> Mapping[str, object]:
    """One required table out of the document.

    Args:
        document: The parsed document.
        name: Which table.
        path: Where it came from, for the message.

    Returns:
        The table.

    Raises:
        ValidationError: If the table is absent or is not a table.
    """
    value = document.get(name)
    if not isinstance(value, Mapping):
        msg = f"the clock contract at {path.name} carries no [{name}] table"
        raise ValidationError(msg)
    return value


def _text(table: Mapping[str, object], key: str, path: Path) -> str:
    """One required string out of a table.

    Args:
        table: The table.
        key: Which key.
        path: Where it came from, for the message.

    Returns:
        The string.

    Raises:
        ValidationError: If the key is absent or is not a non-empty string.
    """
    value = table.get(key)
    if not isinstance(value, str) or not value:
        msg = f"the clock contract at {path.name} carries no {key!r} string"
        raise ValidationError(msg)
    return value


def _integer(table: Mapping[str, object], key: str, path: Path) -> int:
    """One required integer out of a table.

    Args:
        table: The table.
        key: Which key.
        path: Where it came from, for the message.

    Returns:
        The integer.

    Raises:
        ValidationError: If the key is absent or is not an integer.
    """
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"the clock contract at {path.name} carries no {key!r} integer"
        raise ValidationError(msg)
    return value


def _words(table: Mapping[str, object], key: str, path: Path) -> tuple[str, ...]:
    """One required list of strings out of a table.

    Args:
        table: The table.
        key: Which key.
        path: Where it came from, for the message.

    Returns:
        The strings, in declaration order.

    Raises:
        ValidationError: If the key is absent or is not a list of strings.
    """
    value = table.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        msg = f"the clock contract at {path.name} carries no {key!r} list of words"
        raise ValidationError(msg)
    return tuple(str(item) for item in value)


def _numbers(table: Mapping[str, object], key: str, path: Path) -> tuple[int, ...]:
    """One required list of integers out of a table.

    Args:
        table: The table.
        key: Which key.
        path: Where it came from, for the message.

    Returns:
        The integers, in declaration order.

    Raises:
        ValidationError: If the key is absent or is not a list of integers.
    """
    value = table.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, int) and not isinstance(item, bool) for item in value
    ):
        msg = f"the clock contract at {path.name} carries no {key!r} list of integers"
        raise ValidationError(msg)
    return tuple(int(item) for item in value)


def discipline_from(
    *,
    sample_count: int,
    freshness_ttl_millis: int,
    degraded_grace_millis: int,
    max_round_trip_millis: int,
    max_uncertainty_millis: int,
    max_offset_jump_millis: int,
    max_wall_divergence_millis: int,
    network_budget_millis: int,
) -> ClockDiscipline:
    """Build a discipline from whole milliseconds, as configuration states them.

    Args:
        sample_count: How many samples the window keeps.
        freshness_ttl_millis: How long a sample stays fresh.
        degraded_grace_millis: How long a sample keeps a domain describable.
        max_round_trip_millis: The slowest usable round trip.
        max_uncertainty_millis: The widest admissible error bound.
        max_offset_jump_millis: How far the offset may move.
        max_wall_divergence_millis: How far the two host clocks may disagree.
        network_budget_millis: The unobservable delay a request is assumed to meet.

    Returns:
        The discipline.

    Raises:
        ValidationError: If the thresholds contradict each other. The refusal comes
            from :class:`~globin.domain.clock_sync.ClockDiscipline` itself, so an
            operator's configuration is checked by the same rules a default is.

    Milliseconds in, :class:`~globin.domain.clock.Duration` out. Configuration is
    written by people and people write milliseconds; ``Duration`` counts
    nanoseconds, and putting the conversion here means it happens once rather than
    at each of the eight fields' call sites.
    """
    return ClockDiscipline(
        sample_count=sample_count,
        freshness_ttl=_duration(freshness_ttl_millis),
        degraded_grace=_duration(degraded_grace_millis),
        max_round_trip=_duration(max_round_trip_millis),
        max_uncertainty=_duration(max_uncertainty_millis),
        max_offset_jump=_duration(max_offset_jump_millis),
        max_wall_divergence=_duration(max_wall_divergence_millis),
        network_budget=_duration(network_budget_millis),
    )


def _duration(millis: int) -> Duration:
    """A whole number of milliseconds as a duration.

    Args:
        millis: How many milliseconds.

    Returns:
        The duration.

    Raises:
        ValidationError: If the count is not a non-negative integer.
    """
    from globin.domain.clock import duration_from_millis

    return duration_from_millis(millis)


def sample_age(now: MonotonicReading, sample: CalibrationSample | None) -> Duration | None:
    """How long since a sample was taken, measured on the monotonic clock.

    Args:
        now: A fresh monotonic reading.
        sample: The sample, or ``None``.

    Returns:
        The elapsed duration, or ``None`` when there is no sample.

    Raises:
        ValidationError: If ``now`` precedes the sample, which
            :meth:`~globin.domain.clock.MonotonicReading.since` refuses.

    **Monotonic, never wall.** An age computed from wall-clock readings would shrink
    or grow whenever the host clock was adjusted, which is precisely the event that
    should make a calibration *less* trusted rather than apparently younger.
    """
    return None if sample is None else now.since(sample.taken_at)


__all__ = [
    "CONTRACT_RELATIVE_PATH",
    "DEFAULT_FLIGHT_TIMEOUT_SECONDS",
    "ClockContract",
    "ClockManager",
    "RestServerTimeSource",
    "discipline_from",
    "read_clock_contract",
    "sample_age",
]
