"""Whether to export, when to try again, and when to stop trying.

`metrics.py` decides what a measurement is; this decides what happens to it on the
way out. The two are separate because delivery has failure modes measurement does
not: a remote that is briefly unreachable, a queue that fills faster than it
drains, and a configuration that will never work no matter how long it is retried.

**A pure decision function and nothing else.** No clock is read here, no socket is
opened, no queue is held. :func:`decide_export` takes an episode, a queue depth
and a monotonic reading, and returns what to do — which is what makes the whole
state machine testable with literals, exactly as `domain/watchdog.py` is.

**Read the transition graph's absences.** There is one edge into `STOPPED` and
**none out of it**: a permanently failed exporter is retired for the life of the
process. That makes "GLOBIN never hammers a dead endpoint" a property of the graph
rather than of a counter somebody has to get right.

**No jitter.** Jitter de-synchronises a fleet; GLOBIN is one local process, so
adding it would put a randomness source in the retry path — which
`test_identifier_discipline.py` forbids outside adapters — for no benefit.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.domain.clock import Duration, MonotonicReading
from globin.errors import ValidationError

#: The shortest permitted flush interval, in milliseconds.
MINIMUM_FLUSH_MILLIS: Final[int] = 100

#: The longest permitted flush interval, in milliseconds.
MAXIMUM_FLUSH_MILLIS: Final[int] = 300_000

#: The smallest permitted bounded queue.
MINIMUM_QUEUE_CAPACITY: Final[int] = 1

#: The largest permitted bounded queue.
#:
#: Bounded so that "the queue is bounded" is a fact rather than a promise: at the
#: ceiling a queue of snapshots is still small enough to hold in memory without
#: competing with the work being measured.
MAXIMUM_QUEUE_CAPACITY: Final[int] = 4_096

#: The smallest permitted backoff, in milliseconds.
MINIMUM_BACKOFF_MILLIS: Final[int] = 100

#: The largest permitted backoff, in milliseconds.
MAXIMUM_BACKOFF_MILLIS: Final[int] = 600_000

#: How many doublings the backoff may accumulate before it stops growing.
#:
#: Ten, which at the default base is about a hundred seconds — past the cap in
#: every configuration, so the shift is a guard against an integer growing without
#: bound rather than a tuning knob.
MAXIMUM_BACKOFF_SHIFT: Final[int] = 10

#: Milliseconds in one second, used to convert a policy value to a duration.
MILLIS_PER_SECOND: Final[int] = 1_000

#: Nanoseconds in one millisecond.
NANOS_PER_MILLI: Final[int] = 1_000_000


class ExportState(StrEnum):
    """Where the exporter stands.

    `DISABLED` is structurally different from the rest and not merely a flag: with
    no exporter configured, no queue is built and no thread is started, so the
    state describes an object graph rather than a mode.
    """

    DISABLED = "disabled"
    IDLE = "idle"
    READY = "ready"
    RETRYING = "retrying"
    STOPPED = "stopped"


class ExportOutcome(StrEnum):
    """What one attempt to hand a batch over returned.

    `REFUSED_BACKPRESSURE` means *I did not take it*, which is what lets the pump
    keep the batch rather than lose it — a distinction a boolean cannot make.
    """

    DELIVERED = "delivered"
    TEMPORARY_FAILURE = "temporary_failure"
    PERMANENT_FAILURE = "permanent_failure"
    REFUSED_BACKPRESSURE = "refused_backpressure"


class ExportAction(StrEnum):
    """What the pump should do next."""

    NOTHING = "nothing"
    OFFER = "offer"
    WAIT = "wait"
    STOP = "stop"


class DropPolicy(StrEnum):
    """Which end of a full queue loses.

    `DROP_OLDEST` is the default. Telemetry's value increases with recency: during
    an incident the observation most worth having is the one that just happened,
    and dropping the newest fills the queue with stale data that outlives the
    event it was meant to explain.
    """

    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"


@dataclass(frozen=True, slots=True)
class ExportPolicy:
    """The bounds an exporter runs under.

    Args:
        queue_capacity: The most batches held at once.
        batch_size: The most snapshots handed over in one attempt.
        flush_interval_millis: How often the pump wakes.
        offer_timeout_millis: How long one attempt may take.
        shutdown_timeout_millis: How long a final flush may take.
        backoff_base_millis: The first retry delay.
        backoff_max_millis: The ceiling on a retry delay.
        failures_before_stop: Consecutive failures that retire the exporter.
        drop_policy: Which end of a full queue loses.

    Raises:
        ValidationError: If any value is out of range, or if any of four *orderings*
            is wrong.

    **The orderings are the load-bearing half**, and no single-value range check
    finds them — the lesson `WatchdogPolicy` records about itself. A batch larger
    than the queue can never be assembled, so nothing is ever exported while every
    value looks sane. A backoff base above its cap makes the delay constant. A
    shutdown timeout below one attempt's timeout means the final flush cannot
    complete even one offer, so the timeout is a lie.
    """

    queue_capacity: int = 256
    batch_size: int = 32
    flush_interval_millis: int = 5_000
    offer_timeout_millis: int = 2_000
    shutdown_timeout_millis: int = 5_000
    backoff_base_millis: int = 500
    backoff_max_millis: int = 60_000
    failures_before_stop: int = 5
    drop_policy: DropPolicy = DropPolicy.DROP_OLDEST

    def __post_init__(self) -> None:
        """Refuse a policy that could not be honoured."""
        problems = list(self._range_problems())
        if self.batch_size > self.queue_capacity:
            problems.append("the batch size is above the queue capacity, so no batch ever fills")
        if self.backoff_base_millis > self.backoff_max_millis:
            problems.append("the backoff base is above its ceiling, so backoff is constant")
        if self.shutdown_timeout_millis < self.offer_timeout_millis:
            problems.append("the shutdown timeout is below one attempt, so it cannot complete")
        if problems:
            raise ValidationError("; ".join(problems))

    def _range_problems(self) -> tuple[str, ...]:
        """Judge every value against its own bounds.

        Returns:
            One sentence per problem.
        """
        checks = (
            ("queue_capacity", self.queue_capacity, MINIMUM_QUEUE_CAPACITY, MAXIMUM_QUEUE_CAPACITY),
            ("batch_size", self.batch_size, 1, MAXIMUM_QUEUE_CAPACITY),
            (
                "flush_interval_millis",
                self.flush_interval_millis,
                MINIMUM_FLUSH_MILLIS,
                MAXIMUM_FLUSH_MILLIS,
            ),
            ("offer_timeout_millis", self.offer_timeout_millis, 1, MAXIMUM_FLUSH_MILLIS),
            ("shutdown_timeout_millis", self.shutdown_timeout_millis, 1, MAXIMUM_FLUSH_MILLIS),
            (
                "backoff_base_millis",
                self.backoff_base_millis,
                MINIMUM_BACKOFF_MILLIS,
                MAXIMUM_BACKOFF_MILLIS,
            ),
            (
                "backoff_max_millis",
                self.backoff_max_millis,
                MINIMUM_BACKOFF_MILLIS,
                MAXIMUM_BACKOFF_MILLIS,
            ),
            ("failures_before_stop", self.failures_before_stop, 1, 100),
        )
        return tuple(
            f"{name} is {value}, outside {low}..{high}"
            for name, value, low, high in checks
            if not low <= value <= high
        )

    def shutdown(self) -> Duration:
        """How long a final flush may take.

        Returns:
            The bound, as a duration.
        """
        return Duration(self.shutdown_timeout_millis * NANOS_PER_MILLI)


@dataclass(frozen=True, slots=True)
class ExportEpisode:
    """What has happened to the exporter so far.

    Args:
        state: Where it stands.
        consecutive_failures: How many attempts have failed in a row.
        next_attempt: The earliest reading at which another attempt may be made.
        delivered: How many batches have been handed over successfully.
        dropped: How many were lost to a full queue.
    """

    state: ExportState = ExportState.DISABLED
    consecutive_failures: int = 0
    next_attempt: MonotonicReading | None = None
    delivered: int = 0
    dropped: int = 0


@dataclass(frozen=True, slots=True)
class ExportDecision:
    """What the pump should do, and why.

    Args:
        state: The state this decision leaves the exporter in.
        action: What to do now.
        batch_size: How many items to take, when the action is to offer.
        wait: How long to wait, when the action is to wait.
    """

    state: ExportState
    action: ExportAction = ExportAction.NOTHING
    batch_size: int = 0
    wait: Duration | None = None


def backoff(consecutive_failures: int, policy: ExportPolicy) -> Duration:
    """How long to wait before the next attempt.

    Args:
        consecutive_failures: How many have failed in a row, at least one.
        policy: The bounds.

    Returns:
        The delay.

    Pure integer arithmetic — a shift and a `min`, with no float anywhere, which is
    what `PRECISION_POLICY.md` rule 1 requires and what keeps this comparable
    against a `MonotonicReading`.
    """
    shift = min(max(consecutive_failures - 1, 0), MAXIMUM_BACKOFF_SHIFT)
    millis = min(policy.backoff_base_millis << shift, policy.backoff_max_millis)
    return Duration(millis * NANOS_PER_MILLI)


def transitions() -> tuple[tuple[ExportState, ExportState], ...]:
    """Every state change the machine permits.

    Returns:
        Ordered pairs of ``(from, to)``.

    A function rather than a constant because a layer performs no call at import.
    **Nothing leaves `STOPPED`**, and that absence is the design: a permanently
    failed exporter is retired for the life of the process, so there is no path by
    which GLOBIN retries a configuration that will never work.
    """
    return (
        (ExportState.DISABLED, ExportState.IDLE),
        (ExportState.IDLE, ExportState.READY),
        (ExportState.IDLE, ExportState.DISABLED),
        (ExportState.READY, ExportState.IDLE),
        (ExportState.READY, ExportState.RETRYING),
        (ExportState.READY, ExportState.STOPPED),
        (ExportState.RETRYING, ExportState.READY),
        (ExportState.RETRYING, ExportState.IDLE),
        (ExportState.RETRYING, ExportState.STOPPED),
    )


def decide_export(
    *, episode: ExportEpisode, queued: int, now: MonotonicReading, policy: ExportPolicy
) -> ExportDecision:
    """What the pump should do right now.

    Args:
        episode: What has happened so far.
        queued: How many items are waiting.
        now: The current monotonic reading.
        policy: The bounds.

    Returns:
        The decision.

    Total: every combination of state and queue depth produces a decision, and
    none of them raises. A property test asserts every ``(state, action)`` pair it
    can produce appears in :func:`transitions`.
    """
    if episode.state is ExportState.STOPPED:
        return ExportDecision(state=ExportState.STOPPED, action=ExportAction.STOP)
    if episode.state is ExportState.DISABLED:
        return ExportDecision(state=ExportState.DISABLED)
    if (
        episode.state is ExportState.RETRYING
        and episode.next_attempt is not None
        and now.nanoseconds < episode.next_attempt.nanoseconds
    ):
        return ExportDecision(
            state=ExportState.RETRYING,
            action=ExportAction.WAIT,
            wait=Duration(episode.next_attempt.nanoseconds - now.nanoseconds),
        )
    if queued <= 0:
        return ExportDecision(state=ExportState.IDLE)
    return ExportDecision(
        state=ExportState.READY,
        action=ExportAction.OFFER,
        batch_size=min(queued, policy.batch_size),
    )


def apply_outcome(
    *,
    episode: ExportEpisode,
    outcome: ExportOutcome,
    taken: int,
    now: MonotonicReading,
    policy: ExportPolicy,
) -> ExportEpisode:
    """Fold one attempt's result into the episode.

    Args:
        episode: What had happened before.
        outcome: What the attempt returned.
        taken: How many items the attempt consumed.
        now: The current monotonic reading.
        policy: The bounds.

    Returns:
        The new episode.

    A permanent failure retires the exporter outright. A temporary one counts
    towards retirement and schedules the next attempt from *now*, so a slow attempt
    cannot postpone the deadline it was measured against — the rule the watchdog
    states about an escalation running from the stall rather than from the request.
    """
    if outcome is ExportOutcome.DELIVERED:
        return ExportEpisode(
            state=ExportState.READY,
            consecutive_failures=0,
            next_attempt=None,
            delivered=episode.delivered + taken,
            dropped=episode.dropped,
        )
    if outcome is ExportOutcome.PERMANENT_FAILURE:
        return ExportEpisode(
            state=ExportState.STOPPED,
            consecutive_failures=episode.consecutive_failures + 1,
            next_attempt=None,
            delivered=episode.delivered,
            dropped=episode.dropped,
        )
    failures = episode.consecutive_failures + 1
    if failures >= policy.failures_before_stop:
        return ExportEpisode(
            state=ExportState.STOPPED,
            consecutive_failures=failures,
            next_attempt=None,
            delivered=episode.delivered,
            dropped=episode.dropped,
        )
    delay = backoff(failures, policy)
    return ExportEpisode(
        state=ExportState.RETRYING,
        consecutive_failures=failures,
        next_attempt=MonotonicReading(now.nanoseconds + delay.nanoseconds),
        delivered=episode.delivered,
        dropped=episode.dropped,
    )
