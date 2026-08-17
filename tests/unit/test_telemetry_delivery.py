"""Delivery: the state machine, the bounded queue, and the pump between them.

Every case runs with a hand-cranked clock and **no threads**, which is what the
split between a pure decision function and the object that acts on it buys — the
same property `application/watchdog.py` has for a subject that is even harder to
test that way.
"""

import pytest

from globin.application.observability import Logger
from globin.application.telemetry_delivery import (
    EVENT_EXPORT_DROPPED,
    EVENT_EXPORT_RECOVERED,
    EVENT_EXPORT_RETRYING,
    EVENT_EXPORT_STOPPED,
    TelemetryPump,
    export_queue,
    telemetry_pump,
    wait_for,
)
from globin.domain.clock import MonotonicReading
from globin.domain.observability import LogEvent
from globin.domain.telemetry_delivery import (
    DropPolicy,
    ExportAction,
    ExportEpisode,
    ExportOutcome,
    ExportPolicy,
    ExportState,
    apply_outcome,
    backoff,
    decide_export,
    transitions,
)
from globin.errors import ValidationError


class Recorder:
    """A sink that keeps what it was given."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.events: list[LogEvent] = []

    def emit(self, event: LogEvent) -> None:
        """Keep one record.

        Args:
            event: The record.
        """
        self.events.append(event)


class Scripted:
    """An exporter that returns arranged outcomes in order."""

    def __init__(self, *outcomes: ExportOutcome) -> None:
        """Arrange what each attempt will return.

        Args:
            outcomes: The outcomes, in order. Once exhausted, delivery succeeds.
        """
        self.outcomes = list(outcomes)
        self.batches: list[int] = []
        self.closed = False

    def offer(self, batch: object) -> ExportOutcome:
        """Return the next arranged outcome.

        Args:
            batch: The documents, whose length is recorded.

        Returns:
            The arranged outcome.
        """
        self.batches.append(len(batch))  # type: ignore[arg-type]
        return self.outcomes.pop(0) if self.outcomes else ExportOutcome.DELIVERED

    def close(self) -> None:
        """Record that it was closed."""
        self.closed = True


class Exploding:
    """An exporter that breaks the port's never-raise contract."""

    def offer(self, batch: object) -> ExportOutcome:
        """Raise, which the pump must contain.

        Args:
            batch: Ignored.

        Raises:
            RuntimeError: Always.
        """
        del batch
        message = "a third-party exporter misbehaved"
        raise RuntimeError(message)

    def close(self) -> None:
        """Release nothing."""


def _pump(*outcomes: ExportOutcome, **overrides: object) -> tuple[TelemetryPump, Recorder]:
    """A pump with an arranged exporter.

    Args:
        outcomes: What each attempt returns.
        overrides: Policy fields to replace.

    Returns:
        The pump and its sink.
    """
    fields: dict[str, object] = {"batch_size": 2, "queue_capacity": 4, "failures_before_stop": 3}
    fields.update(overrides)
    sink = Recorder()
    pump = telemetry_pump(
        exporter=Scripted(*outcomes),
        policy=ExportPolicy(**fields),  # type: ignore[arg-type]
        logger=Logger(sink=sink, correlation_id="test-correlation"),
    )
    pump.arm()
    return pump, sink


# ---------------------------------------------------------------------------
# The policy: the orderings no range check would find
# ---------------------------------------------------------------------------


def test_the_declared_policy_is_constructible() -> None:
    """The positive case, so the refusals below mean something."""
    assert ExportPolicy().batch_size == 32


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param(
            {"batch_size": 500, "queue_capacity": 4}, "no batch ever fills", id="batch-above-queue"
        ),
        pytest.param(
            {"backoff_base_millis": 10_000, "backoff_max_millis": 1_000},
            "backoff is constant",
            id="base-above-cap",
        ),
        pytest.param(
            {"shutdown_timeout_millis": 100, "offer_timeout_millis": 2_000},
            "cannot complete",
            id="shutdown-below-attempt",
        ),
        pytest.param({"queue_capacity": 0}, "outside", id="empty-queue"),
        pytest.param({"flush_interval_millis": 1}, "outside", id="spinning-flush"),
        pytest.param({"failures_before_stop": 0}, "outside", id="retires-immediately"),
    ],
)
def test_a_policy_that_could_not_be_honoured_is_refused(
    overrides: dict[str, object], expected: str
) -> None:
    """The orderings are the load-bearing half, and each hides a real failure.

    A batch above the queue capacity means nothing is ever exported while every
    single value looks sane, which is exactly the class of defect a per-field
    range check cannot see.
    """
    with pytest.raises(ValidationError, match=expected):
        ExportPolicy(**overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Backoff and the transition graph
# ---------------------------------------------------------------------------


def test_backoff_doubles_and_then_stops() -> None:
    """Pure integer arithmetic, so it is comparable against a monotonic reading."""
    policy = ExportPolicy(backoff_base_millis=100, backoff_max_millis=1_000)
    delays = [backoff(n, policy).nanoseconds // 1_000_000 for n in range(1, 8)]
    assert delays == [100, 200, 400, 800, 1_000, 1_000, 1_000]


def test_nothing_leaves_the_stopped_state() -> None:
    """The absence that makes 'GLOBIN never hammers a dead endpoint' a property.

    A permanently failed exporter is retired for the life of the process, and that
    is a fact about the graph rather than about a counter somebody maintains.
    """
    assert not [pair for pair in transitions() if pair[0] is ExportState.STOPPED]
    assert [pair for pair in transitions() if pair[1] is ExportState.STOPPED]


def test_every_decision_lands_on_a_permitted_transition() -> None:
    """The check that found two missing edges in the watchdog's own table."""
    permitted = set(transitions())
    for state in ExportState:
        for queued in (0, 5):
            episode = ExportEpisode(state=state, next_attempt=MonotonicReading(0))
            decision = decide_export(
                episode=episode,
                queued=queued,
                now=MonotonicReading(10**12),
                policy=ExportPolicy(),
            )
            if decision.state is not state:
                assert (state, decision.state) in permitted, (state, decision.state)


def test_a_retry_waits_until_its_deadline() -> None:
    """Backoff is honoured by the decision rather than by the caller."""
    episode = ExportEpisode(
        state=ExportState.RETRYING, consecutive_failures=1, next_attempt=MonotonicReading(5_000)
    )
    decision = decide_export(
        episode=episode, queued=3, now=MonotonicReading(1_000), policy=ExportPolicy()
    )
    assert decision.action is ExportAction.WAIT
    assert decision.wait is not None
    assert decision.wait.nanoseconds == 4_000


def test_a_stopped_exporter_is_told_to_stop() -> None:
    """The only action a retired exporter ever produces."""
    decision = decide_export(
        episode=ExportEpisode(state=ExportState.STOPPED),
        queued=99,
        now=MonotonicReading(1),
        policy=ExportPolicy(),
    )
    assert decision.action is ExportAction.STOP


def test_the_deadline_runs_from_now_rather_than_from_the_attempt() -> None:
    """A slow attempt must not postpone the deadline it was measured against.

    The rule the watchdog states about an escalation running from the stall rather
    than from the request, applied to a retry.
    """
    policy = ExportPolicy(backoff_base_millis=1_000, backoff_max_millis=1_000)
    episode = apply_outcome(
        episode=ExportEpisode(state=ExportState.READY),
        outcome=ExportOutcome.TEMPORARY_FAILURE,
        taken=0,
        now=MonotonicReading(9_000_000_000),
        policy=policy,
    )
    assert episode.next_attempt is not None
    assert episode.next_attempt.nanoseconds == 9_000_000_000 + 1_000_000_000


# ---------------------------------------------------------------------------
# The bounded queue
# ---------------------------------------------------------------------------


def test_a_full_queue_drops_the_oldest_by_default() -> None:
    """Telemetry's value increases with recency.

    During an incident the observation most worth having is the one that just
    happened; dropping the newest fills the queue with stale data that outlives
    the event it was meant to explain.
    """
    queue = export_queue(ExportPolicy(queue_capacity=2, batch_size=1))
    for index in range(4):
        queue.offer({"n": index})
    assert [document["n"] for document in queue.items] == [2, 3]
    assert queue.dropped == 2


def test_dropping_the_newest_is_available_and_keeps_the_oldest() -> None:
    """The other policy, so the default is a choice rather than the only option."""
    queue = export_queue(
        ExportPolicy(queue_capacity=2, batch_size=1, drop_policy=DropPolicy.DROP_NEWEST)
    )
    for index in range(4):
        queue.offer({"n": index})
    assert [document["n"] for document in queue.items] == [0, 1]


def test_a_restored_batch_goes_back_to_the_front() -> None:
    """Order is preserved, so a retry sends what it was given in the order given."""
    queue = export_queue(ExportPolicy(queue_capacity=8, batch_size=2))
    for index in range(4):
        queue.offer({"n": index})
    batch = queue.take(2)
    queue.restore(batch)
    assert [document["n"] for document in queue.items] == [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# The pump
# ---------------------------------------------------------------------------


def test_a_delivered_batch_is_consumed() -> None:
    """The ordinary path."""
    pump, _ = _pump()
    for index in range(4):
        pump.queue.offer({"n": index})
    pump.tick(MonotonicReading(10**9))
    assert pump.queue.depth() == 2
    assert pump.episode.delivered == 2


def test_a_temporary_failure_keeps_the_batch() -> None:
    """The port contracts that a batch is consumed **only** on delivery.

    A first version of this restored only on backpressure, which made a transient
    failure lose data silently — and the port's own docstring already forbade it.
    """
    pump, _ = _pump(ExportOutcome.TEMPORARY_FAILURE)
    for index in range(4):
        pump.queue.offer({"n": index})
    pump.tick(MonotonicReading(10**9))
    assert pump.queue.depth() == 4
    assert pump.episode.delivered == 0
    assert pump.episode.state is ExportState.RETRYING


def test_backpressure_keeps_the_batch_too() -> None:
    """`REFUSED_BACKPRESSURE` means the exporter did not take it."""
    pump, _ = _pump(ExportOutcome.REFUSED_BACKPRESSURE)
    pump.queue.offer({"n": 0})
    pump.tick(MonotonicReading(10**9))
    assert pump.queue.depth() == 1


def test_a_permanent_failure_retires_the_exporter_and_keeps_the_residue() -> None:
    """Nothing leaves `STOPPED`, so the documents stay where they can be counted."""
    pump, sink = _pump(ExportOutcome.PERMANENT_FAILURE)
    pump.queue.offer({"n": 0})
    for step in range(1, 4):
        assert pump.tick(MonotonicReading(step * 10**9)) is ExportState.STOPPED
    assert pump.residual() == 1
    assert [event.event for event in sink.events] == [EVENT_EXPORT_STOPPED]


def test_repeated_failures_retire_the_exporter() -> None:
    """A remote that is never coming back stops being asked."""
    pump, _ = _pump(*[ExportOutcome.TEMPORARY_FAILURE] * 3, failures_before_stop=3)
    pump.queue.offer({"n": 0})
    for step in range(1, 8):
        pump.tick(MonotonicReading(step * 10**11))
    assert pump.episode.state is ExportState.STOPPED


def test_recovery_is_said_out_loud_once() -> None:
    """Three transitions, three records, and no record per tick.

    A pump logging every failed attempt at a five-second interval writes seventeen
    thousand records a day, and the rotation policy then discards the one that
    mattered.
    """
    pump, sink = _pump(ExportOutcome.TEMPORARY_FAILURE)
    for index in range(4):
        pump.queue.offer({"n": index})
    for step in range(1, 6):
        pump.tick(MonotonicReading(step * 10**10))
    events = [event.event for event in sink.events]
    assert events == [EVENT_EXPORT_RETRYING, EVENT_EXPORT_RECOVERED]


def test_a_full_queue_is_announced_once() -> None:
    """A drop is worth saying, and worth saying only once."""
    pump, sink = _pump(queue_capacity=1, batch_size=1)
    for index in range(20):
        pump.queue.offer({"n": index})
    pump.tick(MonotonicReading(10**9))
    assert [event.event for event in sink.events].count(EVENT_EXPORT_DROPPED) == 1


def test_an_exporter_that_raises_is_contained() -> None:
    """The port contracts `offer` never raises; containing it anyway is the guarantee.

    A third-party exporter that breaks its contract must not end the run it was
    measuring.
    """
    sink = Recorder()
    pump = telemetry_pump(
        exporter=Exploding(),
        policy=ExportPolicy(batch_size=1, queue_capacity=2),
        logger=Logger(sink=sink, correlation_id="c"),
    )
    pump.arm()
    pump.queue.offer({"n": 0})
    assert pump.tick(MonotonicReading(10**9)) is ExportState.RETRYING
    assert pump.queue.depth() == 1


def test_standing_down_stops_scheduling_without_retiring() -> None:
    """Disarming is reversible; retirement is not."""
    pump, _ = _pump()
    pump.queue.offer({"n": 0})
    pump.stand_down()
    assert pump.tick(MonotonicReading(10**9)) is ExportState.DISABLED
    assert pump.queue.depth() == 1


def test_standing_down_does_not_revive_a_retired_exporter() -> None:
    """`STOPPED` has no outgoing edge, and that includes this one."""
    pump, _ = _pump(ExportOutcome.PERMANENT_FAILURE)
    pump.queue.offer({"n": 0})
    pump.tick(MonotonicReading(10**9))
    pump.stand_down()
    assert pump.episode.state is ExportState.STOPPED


# ---------------------------------------------------------------------------
# The bounded final flush
# ---------------------------------------------------------------------------


def test_a_drain_flushes_what_fits() -> None:
    """The ordinary shutdown path."""
    pump, _ = _pump()
    for index in range(4):
        pump.queue.offer({"n": index})
    flushed = pump.drain(deadline=MonotonicReading(10**12), now=MonotonicReading(0))
    assert flushed == 4
    assert pump.residual() == 0


def test_a_drain_past_its_deadline_does_nothing() -> None:
    """A bounded flush that ignored its bound would not be bounded."""
    pump, _ = _pump()
    pump.queue.offer({"n": 0})
    assert pump.drain(deadline=MonotonicReading(10), now=MonotonicReading(1_000)) == 0
    assert pump.residual() == 1


def test_a_drain_retries_once_and_then_gives_up() -> None:
    """Backing off during shutdown spends the whole budget waiting.

    One retry pass, then stop, so the residue is reported rather than waited for.
    """
    pump, _ = _pump(*[ExportOutcome.TEMPORARY_FAILURE] * 5)
    for index in range(4):
        pump.queue.offer({"n": index})
    assert pump.drain(deadline=MonotonicReading(10**12), now=MonotonicReading(0)) == 0
    assert pump.residual() == 4


def test_the_summary_reports_what_an_operator_needs() -> None:
    """Integers and strings only, so it can be published without conversion."""
    pump, _ = _pump()
    pump.queue.offer({"n": 0})
    pump.tick(MonotonicReading(10**9))
    summary = pump.summary()
    assert summary["delivered"] == 1
    assert summary["state"] == ExportState.READY.value


def test_a_wait_never_exceeds_one_flush_interval() -> None:
    """A long backoff must not delay a pending flush past one interval."""
    policy = ExportPolicy(flush_interval_millis=1_000)
    from globin.domain.clock import Duration

    assert wait_for(Duration(10**12), policy).nanoseconds == 10**9
    assert wait_for(None, policy).nanoseconds == 10**9
