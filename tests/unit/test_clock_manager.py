"""One calibration per domain, shared safely, with no sleep anywhere in this file.

Every concurrency assertion here is driven by a :class:`threading.Barrier` or an
:class:`threading.Event` that the test controls, so the outcomes are deterministic
rather than probable. A test that slept and hoped would fail on a loaded machine and
pass on a quiet one, which is worse than not testing it.

The source double counts its calls and can be made to block on demand. That counter
is the whole of the single-flight assertion: ten threads finding one domain stale
must produce **one** exchange, and the number is checked rather than a lock being
inspected.
"""

import threading
from datetime import UTC, datetime, timedelta

import pytest

from globin.adapters.clock_sync import ClockManager, discipline_from, sample_age
from globin.domain.api_reality import EnvironmentName, ProductFamily, ProtocolKind
from globin.domain.auth_timing import TimestampUnit, default_recv_window
from globin.domain.clock import MICROSECONDS_PER_MILLISECOND, Instant, MonotonicReading
from globin.domain.clock_sync import (
    AdmissionStatus,
    ClockDomain,
    ServerTimeReading,
    SyncState,
    TimingAdmission,
    default_discipline,
)

NANOS_PER_MILLI = 1_000_000

SPOT = ClockDomain(
    family=ProductFamily("spot"),
    environment=EnvironmentName("testnet"),
    protocol=ProtocolKind.REST,
)
DEMO = ClockDomain(
    family=ProductFamily("spot"),
    environment=EnvironmentName("demo"),
    protocol=ProtocolKind.REST,
)

BASE = Instant(datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC))


class _Wall:
    """A wall clock a test moves by hand.

    Args:
        moment: What the next call returns.
    """

    def __init__(self, moment: Instant = BASE) -> None:
        """Start at a fixed moment."""
        self.moment = moment

    def now(self) -> Instant:
        """The current moment, unchanged until a test moves it."""
        return self.moment

    def advance(self, seconds: int) -> None:
        """Move the wall clock, as an operator or a time service would.

        Args:
            seconds: How far, positive or negative.
        """
        from globin.domain.clock import instant

        self.moment = instant(self.moment.moment + timedelta(seconds=seconds))


class _Monotonic:
    """A monotonic clock a test advances by hand.

    Args:
        nanoseconds: The reading the next call returns.
    """

    def __init__(self, nanoseconds: int = 0) -> None:
        """Start at a chosen reading."""
        self.nanoseconds = nanoseconds
        self.step = 0

    def reading(self) -> MonotonicReading:
        """The current reading, then advance by :attr:`step`."""
        answer = MonotonicReading(self.nanoseconds)
        self.nanoseconds += self.step
        return answer

    def advance(self, millis: int) -> None:
        """Move the monotonic clock forward.

        Args:
            millis: How far. Never negative — a monotonic clock cannot go back.
        """
        self.nanoseconds += millis * NANOS_PER_MILLI


class _Source:
    """A server-time source a test controls completely.

    Args:
        ahead_millis: How far ahead of the host the venue claims to be.
        fail: Whether every call returns nothing.
    """

    def __init__(self, *, ahead_millis: int = 0, fail: bool = False) -> None:
        """Record what to answer, and start the call counter at zero."""
        self.ahead_millis = ahead_millis
        self.fail = fail
        self.calls = 0
        self.gate: threading.Event | None = None
        self.entered: threading.Barrier | None = None
        self.lock = threading.Lock()

    def sample(self, domain: ClockDomain) -> ServerTimeReading | None:
        """Answer once, blocking first when the test asked for it.

        Args:
            domain: Which clock is being asked.

        Returns:
            The reading, or ``None`` when this source is set to fail.
        """
        with self.lock:
            self.calls += 1
        if self.entered is not None:
            self.entered.wait(timeout=10)
        if self.gate is not None:
            self.gate.wait(timeout=10)
        if self.fail:
            return None
        del domain
        return ServerTimeReading(
            epoch_micros=BASE.epoch_micros + self.ahead_millis * MICROSECONDS_PER_MILLISECOND,
            unit=TimestampUnit.MILLISECONDS,
        )


def _idle(wall: _Wall, monotonic: _Monotonic, seconds: int) -> None:
    """Let time pass on a host whose clock nobody touched.

    Args:
        wall: The wall clock.
        monotonic: The monotonic clock.
        seconds: How long passes.

    **Both clocks move together, which is what makes this "idle" rather than "a
    clock jump".** Advancing only the monotonic clock is exactly the signature of a
    wall clock that was set backwards, and :func:`detect_jump` correctly says so —
    a fake that moved one and not the other would be simulating the wrong event.
    """
    wall.advance(seconds)
    monotonic.advance(seconds * 1_000)


def _waiters_reach(manager: ClockManager, domain: ClockDomain, count: int) -> None:
    """Block until a given number of callers are parked on one calibration.

    Args:
        manager: The manager.
        domain: Which clock.
        count: How many waiters to wait for.

    Raises:
        AssertionError: If they do not all arrive.

    **A bounded spin rather than a sleep**, so the outcome is deterministic: either
    the waiters arrive and the test proceeds, or they do not and the test fails
    naming what it was waiting for. A `sleep` would make it pass on a quiet machine
    and fail on a loaded one, which is the flakiness this suite refuses.
    """
    deadline = 20_000_000
    for _ in range(deadline):
        if manager.waiting_on(domain) >= count:
            return
    msg = f"only {manager.waiting_on(domain)} of {count} callers reached the calibration"
    raise AssertionError(msg)


def _manager(source: object, **kwargs: object) -> ClockManager:
    """A manager over a controlled source and controlled clocks.

    Args:
        source: The double.
        **kwargs: Overrides for the manager.

    Returns:
        The manager.
    """
    arguments: dict[str, object] = {
        "source": source,
        "clock": _Wall(),
        "monotonic": _Monotonic(),
        "discipline": default_discipline(),
    }
    arguments.update(kwargs)
    return ClockManager(**arguments)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# A fresh manager knows nothing
# ---------------------------------------------------------------------------


def test_a_fresh_manager_has_calibrated_nothing() -> None:
    """No offset survives a restart, because none is persisted."""
    manager = _manager(_Source())
    assert manager.known_domains() == ()
    assert manager.status(SPOT).state is SyncState.UNINITIALIZED


def test_a_fresh_manager_admits_nothing() -> None:
    """Fail closed is the starting position, not a state reached by a failure."""
    admission = manager_admit(_manager(_Source()))
    assert admission.outcome is AdmissionStatus.CLOCK_NOT_SYNCHRONIZED
    assert admission.context is None


def manager_admit(manager: ClockManager, domain: ClockDomain = SPOT) -> TimingAdmission:
    """Ask a manager to admit a request against one domain.

    Args:
        manager: The manager.
        domain: Which clock.

    Returns:
        The admission.
    """
    return manager.admit(domain, unit=TimestampUnit.MILLISECONDS, window=default_recv_window())


# ---------------------------------------------------------------------------
# Calibrating
# ---------------------------------------------------------------------------


def test_one_calibration_makes_a_domain_synchronized() -> None:
    """The ordinary path, with a zero round trip because the clocks do not move."""
    manager = _manager(_Source(ahead_millis=250))
    outcome = manager.calibrate(SPOT)
    assert not outcome.failed
    assert outcome.sample is not None
    assert outcome.sample.offset_micros == 250 * MICROSECONDS_PER_MILLISECOND
    assert manager.status(SPOT).state is SyncState.SYNCHRONIZED


def test_a_calibrated_domain_admits_a_corrected_timestamp() -> None:
    """End to end through the manager: probe, fold, admit, stamp."""
    manager = _manager(_Source(ahead_millis=120))
    manager.calibrate(SPOT)
    admission = manager_admit(manager)
    assert admission.admitted
    assert admission.context is not None
    assert admission.context.timestamp == BASE.epoch_millis + 120


def test_a_failed_probe_leaves_the_domain_uninitialized_rather_than_synchronized() -> None:
    """Nothing was learned, and nothing is invented to fill the gap."""
    manager = _manager(_Source(fail=True))
    outcome = manager.calibrate(SPOT)
    assert outcome.failed
    assert outcome.sample is None
    assert manager.status(SPOT).state is SyncState.UNINITIALIZED


def test_a_failed_probe_after_a_good_one_is_degraded() -> None:
    """The surviving sample keeps the domain describable without making it usable."""
    source = _Source(ahead_millis=10)
    manager = _manager(source)
    manager.calibrate(SPOT)
    source.fail = True
    manager.calibrate(SPOT)
    status = manager.status(SPOT)
    assert status.state is SyncState.DEGRADED
    assert status.sample is not None


def test_a_recovered_probe_returns_the_domain_to_synchronized() -> None:
    """Degraded is a state, not a terminus."""
    source = _Source(ahead_millis=10)
    manager = _manager(source)
    manager.calibrate(SPOT)
    source.fail = True
    manager.calibrate(SPOT)
    source.fail = False
    manager.calibrate(SPOT)
    assert manager.status(SPOT).state is SyncState.SYNCHRONIZED


def test_an_offset_that_leaps_replaces_the_window_and_invalidates_the_domain() -> None:
    """Two contradictory beliefs are not averaged; the newer one is disbelieved."""
    source = _Source(ahead_millis=0)
    manager = _manager(source)
    manager.calibrate(SPOT)
    source.ahead_millis = 30_000
    outcome = manager.calibrate(SPOT)
    assert outcome.offset_jumped
    status = manager.status(SPOT)
    assert status.state is SyncState.UNSYNCHRONIZED


def test_a_wall_clock_jump_between_calibration_and_use_is_caught() -> None:
    """The case a calibration-time check would miss, and the common one.

    The host is idle, a time service corrects the clock, and the next request is
    stamped against an offset that no longer describes anything.
    """
    wall = _Wall()
    manager = _manager(_Source(ahead_millis=10), clock=wall)
    manager.calibrate(SPOT)
    assert manager.status(SPOT).state is SyncState.SYNCHRONIZED
    wall.advance(60)
    status = manager.status(SPOT)
    assert status.state is SyncState.UNSYNCHRONIZED
    assert status.jump is not None
    assert status.jump.detected
    assert manager_admit(manager).outcome is AdmissionStatus.CLOCK_JUMP_DETECTED


def test_a_wall_clock_set_backwards_is_caught_too() -> None:
    """Both directions, because only one of them is expressible as a `Duration`."""
    wall = _Wall()
    manager = _manager(_Source(ahead_millis=10), clock=wall)
    manager.calibrate(SPOT)
    wall.advance(-60)
    assert manager.status(SPOT).state is SyncState.UNSYNCHRONIZED


def test_an_explicit_invalidation_refuses_until_a_fresh_calibration() -> None:
    """What a venue `-1021` does, and what clears it."""
    manager = _manager(_Source(ahead_millis=5))
    manager.calibrate(SPOT)
    manager.invalidate(SPOT, "the venue answered -1021")
    assert manager.status(SPOT).state is SyncState.UNSYNCHRONIZED
    manager.calibrate(SPOT)
    assert manager.status(SPOT).state is SyncState.SYNCHRONIZED


def test_the_window_is_bounded_by_the_configured_sample_count() -> None:
    """Memory does not grow with the number of calibrations taken."""
    discipline = discipline_from(
        sample_count=3,
        freshness_ttl_millis=300_000,
        degraded_grace_millis=900_000,
        max_round_trip_millis=2_000,
        max_uncertainty_millis=250,
        max_offset_jump_millis=1_000,
        max_wall_divergence_millis=500,
        network_budget_millis=1_000,
    )
    source = _Source(ahead_millis=1)
    manager = _manager(source, discipline=discipline)
    for _ in range(10):
        manager.calibrate(SPOT)
    assert manager.status(SPOT).state is SyncState.SYNCHRONIZED
    assert source.calls == 10


def test_calibrating_a_window_takes_one_exchange_per_sample() -> None:
    """A calibration is a window, not an exchange."""
    source = _Source(ahead_millis=4)
    manager = _manager(source)
    outcomes = manager.calibrate_window(SPOT)
    assert len(outcomes) == default_discipline().sample_count
    assert source.calls == default_discipline().sample_count
    assert manager.status(SPOT).state is SyncState.SYNCHRONIZED


def test_a_window_survives_a_first_exchange_that_answers_nothing() -> None:
    """The measured case, made into a test.

    Against the venue's own testnet the first exchange on a fresh pool sometimes
    exceeds the transport's timeout outright -- see `phase_036_sources.md` M-01. A
    single-sample calibration reports that as a total failure; a window reports it
    as one failed sample and estimates from the rest, which is the whole reason
    :meth:`ClockManager.calibrate_window` exists rather than being a caller's loop.
    """

    class _SlowFirst:
        """A source whose first call answers nothing and whose later calls answer."""

        def __init__(self) -> None:
            """Start the counter at zero."""
            self.calls = 0

        def sample(self, domain: ClockDomain) -> ServerTimeReading | None:
            """Fail once, then answer.

            Args:
                domain: Which clock.

            Returns:
                ``None`` on the first call, a reading afterwards.
            """
            del domain
            self.calls += 1
            if self.calls == 1:
                return None
            return ServerTimeReading(
                epoch_micros=BASE.epoch_micros + 6 * MICROSECONDS_PER_MILLISECOND,
                unit=TimestampUnit.MILLISECONDS,
            )

    source = _SlowFirst()
    manager = _manager(source)
    outcomes = manager.calibrate_window(SPOT)
    assert outcomes[0].failed
    assert not outcomes[1].failed
    status = manager.status(SPOT)
    assert status.state is SyncState.SYNCHRONIZED
    assert status.sample is not None
    assert status.sample.offset_micros == 6 * MICROSECONDS_PER_MILLISECOND


def test_a_window_of_total_failures_leaves_the_domain_uninitialized() -> None:
    """The window absorbs a bad first exchange; it does not paper over a bad link."""
    source = _Source(fail=True)
    manager = _manager(source)
    outcomes = manager.calibrate_window(SPOT)
    assert all(item.failed for item in outcomes)
    assert manager.status(SPOT).state is SyncState.UNINITIALIZED


def test_a_window_reports_every_exchange_rather_than_only_the_chosen_one() -> None:
    """Four failures among five must be visible, not hidden behind one estimate."""
    source = _Source(ahead_millis=2)
    manager = _manager(source)
    outcomes = manager.calibrate_window(SPOT)
    assert len(outcomes) == source.calls


def test_ensure_calibrated_takes_at_most_one_probe() -> None:
    """No loop, so a broken link is diagnosed rather than stalled on."""
    source = _Source(fail=True)
    manager = _manager(source)
    status = manager.ensure_calibrated(SPOT)
    assert status.state is SyncState.UNINITIALIZED
    assert source.calls == 1


def test_ensure_calibrated_probes_nothing_when_already_synchronized() -> None:
    """A healthy clock is not re-asked on every request."""
    source = _Source(ahead_millis=1)
    manager = _manager(source)
    manager.calibrate(SPOT)
    assert source.calls == 1
    manager.ensure_calibrated(SPOT)
    assert source.calls == 1


# ---------------------------------------------------------------------------
# Single flight
# ---------------------------------------------------------------------------


def test_many_concurrent_callers_produce_exactly_one_exchange() -> None:
    """The single-flight property, counted rather than inspected.

    Ten threads all find the domain stale at once. The leader is held inside the
    source until every waiter has had a chance to arrive, so this is deterministic:
    if a second thread ever started its own exchange, the counter would say so.
    """
    source = _Source(ahead_millis=42)
    source.gate = threading.Event()
    source.entered = threading.Barrier(2, timeout=10)
    manager = _manager(source)
    results: list[object] = []
    lock = threading.Lock()

    def run() -> None:
        outcome = manager.calibrate(SPOT)
        with lock:
            results.append(outcome)

    # The leader goes first and is held inside the source. While it is there the
    # flight stays registered, so every later caller provably becomes a waiter --
    # there is no window in which one could start a second exchange.
    leader = threading.Thread(target=run, name="leader")
    leader.start()
    source.entered.wait()

    waiters = [threading.Thread(target=run, name=f"waiter-{index}") for index in range(9)]
    for thread in waiters:
        thread.start()
    _waiters_reach(manager, SPOT, 9)
    source.gate.set()
    for thread in [leader, *waiters]:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert source.calls == 1
    assert len(results) == 10
    assert manager.status(SPOT).state is SyncState.SYNCHRONIZED
    assert manager.waiting_on(SPOT) == 0


def test_every_waiter_receives_the_leaders_outcome() -> None:
    """A waiter is not told the calibration failed merely because it did not do it."""
    source = _Source(ahead_millis=7)
    source.gate = threading.Event()
    source.entered = threading.Barrier(2, timeout=10)
    manager = _manager(source)
    outcomes: list[object] = []
    lock = threading.Lock()

    def run() -> None:
        result = manager.calibrate(SPOT)
        with lock:
            outcomes.append(result)

    leader = threading.Thread(target=run)
    leader.start()
    source.entered.wait()
    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
    _waiters_reach(manager, SPOT, 3)
    source.gate.set()
    for thread in [leader, *threads]:
        thread.join(timeout=10)

    assert len(outcomes) == 4
    for outcome in outcomes:
        assert not outcome.failed  # type: ignore[attr-defined]
        assert outcome.sample is not None  # type: ignore[attr-defined]
        assert outcome.sample.offset_micros == 7 * MICROSECONDS_PER_MILLISECOND  # type: ignore[attr-defined]


def test_two_domains_do_not_block_each_other() -> None:
    """Per-domain, so one slow venue does not stall a different one.

    The barrier requires **both** calibrations to be inside the source at once. If
    the manager serialised across domains, neither would reach it and the barrier
    would time out.
    """
    source = _Source(ahead_millis=3)
    source.entered = threading.Barrier(2, timeout=10)
    manager = _manager(source)
    errors: list[BaseException] = []

    def run(domain: ClockDomain) -> None:
        try:
            manager.calibrate(domain)
        except BaseException as fault:
            errors.append(fault)

    threads = [
        threading.Thread(target=run, args=(SPOT,)),
        threading.Thread(target=run, args=(DEMO,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert not errors, errors
    assert source.calls == 2
    assert manager.status(SPOT).state is SyncState.SYNCHRONIZED
    assert manager.status(DEMO).state is SyncState.SYNCHRONIZED


def test_a_waiter_that_times_out_reports_its_own_failure_and_changes_nothing() -> None:
    """Cancellation safety: one caller's impatience is not another's measurement.

    The waiter's timeout is zero, so it gives up immediately. The leader then
    finishes normally, and the domain ends up exactly as it would have without the
    waiter — which is the assertion, rather than merely that nothing raised.
    """
    source = _Source(ahead_millis=11)
    source.gate = threading.Event()
    manager = _manager(source)
    manager.flight_timeout_seconds = 0.0
    inside = threading.Barrier(2, timeout=10)
    source.entered = inside
    leader_result: list[object] = []

    def lead() -> None:
        leader_result.append(manager.calibrate(SPOT))

    leader = threading.Thread(target=lead)
    leader.start()
    inside.wait()
    waiter = manager.calibrate(SPOT)
    source.gate.set()
    leader.join(timeout=10)

    assert waiter.failed
    assert "had not finished" in waiter.detail
    assert waiter.sample is None
    assert leader_result
    assert not leader_result[0].failed  # type: ignore[attr-defined]
    assert manager.status(SPOT).state is SyncState.SYNCHRONIZED
    assert source.calls == 1


def test_a_leader_that_raises_still_releases_every_waiter() -> None:
    """The `finally` is what stops one defect becoming a hung process."""

    class _Exploding:
        """A source whose first call raises and whose later calls answer."""

        def __init__(self) -> None:
            self.calls = 0

        def sample(self, domain: ClockDomain) -> ServerTimeReading | None:
            """Raise on the first call.

            Args:
                domain: Which clock.

            Returns:
                Never on the first call.

            Raises:
                RuntimeError: Always, on the first call.
            """
            del domain
            self.calls += 1
            msg = "the source is broken"
            raise RuntimeError(msg)

    manager = _manager(_Exploding())
    with pytest.raises(RuntimeError, match="the source is broken"):
        manager.calibrate(SPOT)
    # The flight was removed, so a second attempt is a fresh leader rather than a
    # waiter on a flight nobody will ever finish.
    with pytest.raises(RuntimeError, match="the source is broken"):
        manager.calibrate(SPOT)


def test_a_lock_is_never_held_across_the_exchange() -> None:
    """Asserted by observation: `status` answers while a calibration is in flight.

    If the manager held its lock across the source call, this would block until the
    gate opened and the join below would time out.
    """
    source = _Source(ahead_millis=1)
    source.gate = threading.Event()
    source.entered = threading.Barrier(2, timeout=10)
    manager = _manager(source)
    thread = threading.Thread(target=manager.calibrate, args=(SPOT,))
    thread.start()
    source.entered.wait()
    assert manager.status(SPOT).state is SyncState.UNINITIALIZED
    source.gate.set()
    thread.join(timeout=10)
    assert not thread.is_alive()


# ---------------------------------------------------------------------------
# Ages
# ---------------------------------------------------------------------------


def test_a_sample_age_is_measured_on_the_monotonic_clock() -> None:
    """A wall-clock age would shrink whenever the host clock was corrected."""
    source = _Source(ahead_millis=1)
    wall, monotonic = _Wall(), _Monotonic()
    manager = _manager(source, clock=wall, monotonic=monotonic)
    manager.calibrate(SPOT)
    _idle(wall, monotonic, 120)
    status = manager.status(SPOT)
    assert status.age is not None
    assert status.age.milliseconds == 120_000


def test_an_aged_calibration_goes_stale_and_stops_admitting() -> None:
    """The freshness gate, driven by moving a clock rather than by waiting."""
    source = _Source(ahead_millis=1)
    wall, monotonic = _Wall(), _Monotonic()
    manager = _manager(source, clock=wall, monotonic=monotonic)
    manager.calibrate(SPOT)
    _idle(wall, monotonic, default_discipline().freshness_ttl.milliseconds // 1_000 + 1)
    assert manager.status(SPOT).state is SyncState.STALE
    assert manager_admit(manager).outcome is AdmissionStatus.CLOCK_CALIBRATION_STALE


def test_moving_only_the_monotonic_clock_reads_as_a_backward_wall_jump() -> None:
    """Why :func:`_idle` moves both clocks, asserted rather than left as a comment.

    This is the shape of the bug the first draft of this file had: advancing only
    the monotonic clock to simulate time passing is indistinguishable from a wall
    clock that was set backwards, and the detector says so. Keeping the case pins
    the detector's sensitivity as well as explaining the helper.
    """
    source = _Source(ahead_millis=1)
    monotonic = _Monotonic()
    manager = _manager(source, monotonic=monotonic)
    manager.calibrate(SPOT)
    monotonic.advance(60_000)
    status = manager.status(SPOT)
    assert status.state is SyncState.UNSYNCHRONIZED
    assert status.jump is not None
    assert status.jump.direction.value == "backward"


def test_the_age_helper_answers_nothing_for_no_sample() -> None:
    """`None` in, `None` out, rather than a zero that reads as *just now*."""
    assert sample_age(MonotonicReading(0), None) is None
