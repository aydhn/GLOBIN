"""The bounded queue and the pump that drains it.

`domain/telemetry_delivery.py` decides *what to do*; this does it. The split is the
one `application/watchdog.py` made, and it buys the same thing: `tick()` is one
method, takes no clock of its own, and can be driven by hand — so the whole of
delivery, including every failure path, is tested with a fake clock and **no
threads at all**.

**The pump holds a source and never a recorder.** It cannot enqueue, because
nothing it holds has a method that would. That is what makes the reentrancy loop —
an export failure records a metric, which reaches the exporter, which fails —
untypeable rather than merely avoided, and an architecture test asserts the field
types rather than trusting this paragraph.

**Nothing here raises.** `offer` is contracted never to raise, and the pump
contains it anyway: a subsystem whose whole job is observation must not be able to
end the run it is observing.
"""

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from globin.application.observability import Logger
from globin.domain.clock import Duration, MonotonicReading
from globin.domain.telemetry_delivery import (
    DropPolicy,
    ExportAction,
    ExportEpisode,
    ExportOutcome,
    ExportPolicy,
    ExportState,
    apply_outcome,
    decide_export,
)

EVENT_EXPORT_RETRYING: str = "telemetry.export.retrying"
"""Emitted once, on entering the retry state."""

EVENT_EXPORT_STOPPED: str = "telemetry.export.stopped"
"""Emitted once, on retirement. There is no edge out of it."""

EVENT_EXPORT_RECOVERED: str = "telemetry.export.recovered"
"""Emitted once, when delivery resumes after a failure."""

EVENT_EXPORT_DROPPED: str = "telemetry.export.dropped"
"""Emitted once, the first time a full queue loses something."""


class TelemetryExporter(Protocol):
    """Somewhere a batch of documents can be handed to.

    Three contracts, all of which a test can hold an implementation to:

    - **`offer` never raises.** The caller is already handling the ordinary case
      and an exception here would replace the measurement with the story of its
      own delivery — `StallEvidenceCollector.capture`'s rule.
    - **`offer` bounds itself** to the policy's attempt timeout. This is a contract
      on the implementer rather than something the caller can enforce: CPython
      gives no way to interrupt a blocked call from another thread, and pretending
      otherwise with a timer would be building a supervisor.
    - **`offer` consumes the batch only on `DELIVERED`.** `REFUSED_BACKPRESSURE`
      means "I did not take it", which is what lets the pump requeue rather than
      silently lose a batch.
    """

    def offer(self, batch: Sequence[dict[str, object]]) -> ExportOutcome:
        """Hand a batch over.

        Args:
            batch: The documents.

        Returns:
            What happened.
        """
        ...

    def close(self) -> None:
        """Release whatever the exporter holds. Idempotent, never raises."""
        ...


@dataclass(slots=True)
class ExportQueue:
    """A bounded queue of documents waiting to be exported.

    Args:
        capacity: The most held at once.
        policy: Which end loses when it is full.
        items: The documents, oldest first.
        dropped: How many were lost to a full queue.

    The one place backpressure is expressed. It holds no lock, because only the
    object that owns it touches it; the lock, when a thread arrives, goes in the
    adapter — `SharedHeartbeatRegistry`'s arrangement.
    """

    capacity: int
    policy: DropPolicy
    items: deque[dict[str, object]]
    dropped: int = 0

    def offer(self, document: dict[str, object]) -> bool:
        """Add one document, dropping something if the queue is full.

        Args:
            document: What to add.

        Returns:
            Whether it was kept.
        """
        if len(self.items) < self.capacity:
            self.items.append(document)
            return True
        self.dropped += 1
        if self.policy is DropPolicy.DROP_NEWEST:
            return False
        self.items.popleft()
        self.items.append(document)
        return True

    def take(self, limit: int) -> tuple[dict[str, object], ...]:
        """Remove up to ``limit`` documents, oldest first.

        Args:
            limit: The most to take.

        Returns:
            What was taken.
        """
        taken = [self.items.popleft() for _ in range(min(limit, len(self.items)))]
        return tuple(taken)

    def restore(self, batch: Sequence[dict[str, object]]) -> None:
        """Put a refused batch back at the front.

        Args:
            batch: What the exporter did not take.

        Used only on `REFUSED_BACKPRESSURE`, which is the outcome that means the
        exporter did not consume what it was handed.
        """
        for document in reversed(batch):
            self.items.appendleft(document)

    def depth(self) -> int:
        """How many documents are waiting.

        Returns:
            The count.
        """
        return len(self.items)


def export_queue(policy: ExportPolicy) -> ExportQueue:
    """A queue with nothing in it.

    Args:
        policy: The bounds it enforces.

    Returns:
        The queue.

    A function because `deque()` is a call and a layer performs none at import.
    """
    return ExportQueue(capacity=policy.queue_capacity, policy=policy.drop_policy, items=deque())


@dataclass(slots=True)
class TelemetryPump:
    """Drains the queue into the exporter, one tick at a time.

    Args:
        queue: What is waiting.
        exporter: Where it goes.
        policy: The bounds.
        logger: Where a transition is announced.
        episode: What has happened so far. **No default**, for
            `RuntimeWatchdog.episode`'s reason: a mutable default would be shared.
        announced: Which events have already been logged.
    """

    queue: ExportQueue
    exporter: TelemetryExporter
    policy: ExportPolicy
    logger: Logger
    episode: ExportEpisode
    announced: set[str]

    def arm(self) -> None:
        """Move from disabled to idle, so a tick will do something."""
        if self.episode.state is ExportState.DISABLED:
            self.episode = replace(self.episode, state=ExportState.IDLE)

    def stand_down(self) -> None:
        """Stop scheduling work, whatever state the exporter is in.

        Disarming before joining is what makes a loop that survives a stop
        harmless, which is `WatchdogThread.stop`'s ordering rule.
        """
        if self.episode.state is not ExportState.STOPPED:
            self.episode = replace(self.episode, state=ExportState.DISABLED)

    def tick(self, now: MonotonicReading) -> ExportState:
        """Do whatever the decision function says to do now.

        Args:
            now: The current monotonic reading.

        Returns:
            The state this tick left the exporter in.

        The only entry point a loop uses and the only one a test needs — exactly
        `RuntimeWatchdog.tick`'s shape. **Do not add a lock here later**: there is
        no race, and writing one down would persuade a future reader there is.
        """
        decision = decide_export(
            episode=self.episode, queued=self.queue.depth(), now=now, policy=self.policy
        )
        if decision.action is not ExportAction.OFFER:
            self._settle(decision.state)
            return self.episode.state
        batch = self.queue.take(decision.batch_size)
        outcome = self._offer(batch)
        if outcome is not ExportOutcome.DELIVERED:
            # The port contracts that a batch is consumed ONLY on `DELIVERED`, so
            # anything else means the exporter still has nothing and the documents
            # are still ours. Restoring on backpressure alone would have made a
            # transient failure lose data silently -- which is what the first
            # version of this did, and what its own docstring already forbade.
            self.queue.restore(batch)
        before = self.episode.state
        self.episode = apply_outcome(
            episode=self.episode,
            outcome=outcome,
            taken=len(batch) if outcome is ExportOutcome.DELIVERED else 0,
            now=now,
            policy=self.policy,
        )
        self._announce_transition(before, self.episode.state)
        return self.episode.state

    def drain(self, deadline: MonotonicReading, now: MonotonicReading) -> int:
        """Flush what fits before the deadline.

        Args:
            deadline: The reading past which no further attempt is made.
            now: The current monotonic reading.

        Returns:
            How many documents were handed over.

        **One retry pass and then stop.** Backing off during shutdown is how a
        bounded flush spends its whole budget waiting rather than delivering, so
        this attempts, and on a failure attempts once more, and then gives up.
        """
        flushed = 0
        attempts = 0
        while self.queue.depth() and now.nanoseconds < deadline.nanoseconds and attempts < 2:
            batch = self.queue.take(self.policy.batch_size)
            outcome = self._offer(batch)
            if outcome is ExportOutcome.DELIVERED:
                flushed += len(batch)
                continue
            self.queue.restore(batch)
            attempts += 1
        return flushed

    def residual(self) -> int:
        """How many documents were never handed over.

        Returns:
            The queue depth.
        """
        return self.queue.depth()

    def summary(self) -> dict[str, object]:
        """What an operator needs to know about delivery.

        Returns:
            A JSON-safe mapping of integers and strings.
        """
        return {
            "state": self.episode.state.value,
            "delivered": self.episode.delivered,
            "queued": self.queue.depth(),
            "dropped": self.queue.dropped,
            "consecutive_failures": self.episode.consecutive_failures,
        }

    def _offer(self, batch: Sequence[dict[str, object]]) -> ExportOutcome:
        """Hand a batch over, containing anything the exporter does wrong.

        Args:
            batch: The documents.

        Returns:
            What happened, with an exception reported as a temporary failure.

        The port contracts `offer` never to raise. Containing it anyway is the
        difference between a contract and a guarantee: a third-party exporter that
        breaks the contract must not end the run it was measuring.
        """
        if not batch:
            return ExportOutcome.DELIVERED
        try:
            return self.exporter.offer(batch)
        except Exception:
            return ExportOutcome.TEMPORARY_FAILURE

    def _settle(self, state: ExportState) -> None:
        """Record a state the decision function reached without an attempt.

        Args:
            state: The new state.
        """
        if state is not self.episode.state and self.episode.state is not ExportState.STOPPED:
            before = self.episode.state
            self.episode = replace(self.episode, state=state)
            self._announce_transition(before, state)

    def _announce_transition(self, before: ExportState, after: ExportState) -> None:
        """Log a change of consequence, once.

        Args:
            before: The state left.
            after: The state entered.

        **A transition produces a record; a tick does not.** A pump logging every
        failed attempt at a five-second interval writes seventeen thousand records
        a day, and the rotation policy then discards the one that mattered.
        """
        if before is after:
            return
        if after is ExportState.RETRYING:
            self._once(EVENT_EXPORT_RETRYING, "warning")
        elif after is ExportState.STOPPED:
            self._once(EVENT_EXPORT_STOPPED, "error")
        elif after is ExportState.READY and before is ExportState.RETRYING:
            self._once(EVENT_EXPORT_RECOVERED, "info")
        if self.queue.dropped and EVENT_EXPORT_DROPPED not in self.announced:
            self._once(EVENT_EXPORT_DROPPED, "warning")

    def _once(self, event: str, severity: str) -> None:
        """Emit one event the first time it happens.

        Args:
            event: The event name.
            severity: Which logger method to use.
        """
        if event in self.announced:
            return
        self.announced.add(event)
        emit = getattr(self.logger, severity)
        emit(event, state=self.episode.state.value, failures=self.episode.consecutive_failures)


def telemetry_pump(
    *, exporter: TelemetryExporter, policy: ExportPolicy, logger: Logger
) -> TelemetryPump:
    """A pump with an empty queue, disabled until armed.

    Args:
        exporter: Where batches go.
        policy: The bounds.
        logger: Where a transition is announced.

    Returns:
        The pump.
    """
    return TelemetryPump(
        queue=export_queue(policy),
        exporter=exporter,
        policy=policy,
        logger=logger,
        episode=ExportEpisode(),
        announced=set(),
    )


def wait_for(decision_wait: Duration | None, policy: ExportPolicy) -> Duration:
    """How long a loop should sleep after a tick.

    Args:
        decision_wait: What the decision asked for, if anything.
        policy: The bounds.

    Returns:
        The shorter of the requested wait and the flush interval, so a pending
        flush is never delayed past one interval by a long backoff.
    """
    interval = Duration(policy.flush_interval_millis * 1_000_000)
    if decision_wait is None:
        return interval
    return Duration(min(decision_wait.nanoseconds, interval.nanoseconds))
