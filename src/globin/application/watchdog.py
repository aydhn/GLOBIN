"""Driving the watchdog: one tick, and the escalation it may set off.

Everything that decides *what happens* to a stalled process lives here, and it is
all reachable by calling :meth:`RuntimeWatchdog.tick` with a clock the caller
controls. There is no thread in this module and no lock, because
``docs/architecture/dependency-rules.toml`` places ``threading`` out of reach of
this layer — and that restriction turns out to be the design rather than an
obstacle. A stall that takes thirty seconds in production takes none in a test.

**Nothing here needs to be atomic.** Only the watchdog thread calls
:meth:`~RuntimeWatchdog.tick`, so the episode is thread-confined and "exactly one
incident per stall" is a property of :func:`~globin.domain.watchdog.transitions`
having a single edge into ``STALLED``. Two things really are shared across
threads, and both live in the adapter: the heartbeat table, behind one small lock,
and the stop latch, which is a monotone boolean that needs none. Do not add a lock
here later — there is no race, and writing one down would persuade a future reader
that there is.

**The ordering inside a confirmed stall is fixed, and it is fixed the way it is so
that the last thing written survives the process.** Claim, log, capture, publish,
ask. The incident reaches disk through
:meth:`~globin.ports.runtime_state.StateStore.publish`, which fsyncs before it
renames, *before* anybody asks the process to stop — because if the ask fails the
next thing that happens is a termination that runs no cleanup at all.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from globin.application.observability import Logger
from globin.domain.bootstrap import ExitCode
from globin.domain.clock import Duration, MonotonicReading
from globin.domain.watchdog import (
    EVENT_WATCHDOG_ARMED,
    EVENT_WATCHDOG_ESCALATED,
    EVENT_WATCHDOG_EVIDENCE_CAPTURED,
    EVENT_WATCHDOG_EVIDENCE_FAILED,
    EVENT_WATCHDOG_LATE_PROGRESS,
    EVENT_WATCHDOG_RECOVERED,
    EVENT_WATCHDOG_SHUTDOWN_REQUESTED,
    EVENT_WATCHDOG_STALLED,
    EVENT_WATCHDOG_STOOD_DOWN,
    EVENT_WATCHDOG_SUSPECT,
    REASON_LATE_PROGRESS,
    WATCHDOG_SCHEMA,
    WATCHDOG_SCHEMA_VERSION,
    HeartbeatSnapshot,
    StallEvidence,
    StallIncident,
    WatchdogAction,
    WatchdogDecision,
    WatchdogEpisode,
    WatchdogPolicy,
    WatchdogState,
    WatchdogSummary,
    decide,
)
from globin.ports.clock import Clock, MonotonicClock
from globin.ports.runtime_state import ShutdownSignals
from globin.ports.watchdog import HeartbeatSource, ProcessTerminator, StallEvidenceCollector


@dataclass(slots=True)
class RuntimeWatchdog:
    """One process's watchdog, as a thing that can be ticked.

    Args:
        monotonic: The clock every elapsed quantity is measured on.
        clock: The wall clock, read once per incident so a human can find it.
        beats: Where the heartbeat table is read from.
        policy: The thresholds.
        evidence: What gathers a post-mortem.
        signals: The latch a graceful stop is asked for through.
        terminator: What ends the process when it will not end itself.
        logger: Where the structured record goes.
        run_id: Which run this is.
        correlation_id: The run's correlation identifier.
        new_incident_id: Mints an incident identifier. Injected, because minting one
            reads randomness and a published record must be reproducible in a test.
        episode: What it remembers between ticks. It has **no default**, for the
            reason ``globin.adapters.runtime_state.PlatformShutdownSignals`` gives
            about its own ``installed``: a default of ``WatchdogEpisode()`` would
            have to be constructed, and constructing one in a class body is work
            performed at import, which every layer package is forbidden.
        publish: Writes the incident durably. ``None`` when there is nowhere to
            write, which is a real configuration rather than an error.
        enabled: Whether configuration switched the watchdog on.
        escalation_enabled: Whether the process is ended when it will not end
            itself. Turning it off keeps the detection, the evidence and the
            graceful request and stops only at the termination, which is what an
            operator wants while they are still learning what their thresholds mean
            on their own host.
        started: When it was armed. ``None`` until it is.
        incident: The one incident this run raised, if it raised one.
        running: Whether the thread that ticks this is alive. Set by the adapter
            that owns it, and reported by :meth:`summary` so a health snapshot can
            tell "switched off" from "should be running and is not".
    """

    monotonic: MonotonicClock
    clock: Clock
    beats: HeartbeatSource
    policy: WatchdogPolicy
    evidence: StallEvidenceCollector
    signals: ShutdownSignals
    terminator: ProcessTerminator
    logger: Logger
    run_id: str
    correlation_id: str
    new_incident_id: Callable[[], str]
    episode: WatchdogEpisode
    publish: Callable[[Mapping[str, object]], None] | None = None
    enabled: bool = True
    escalation_enabled: bool = True
    started: MonotonicReading | None = None
    incident: StallIncident | None = None
    running: bool = False

    def arm(self) -> None:
        """Begin watching, and start the start-up grace running.

        Idempotent: arming an armed watchdog restarts nothing, because restarting
        the grace would let a caller postpone every threshold indefinitely by
        calling this in a loop.
        """
        if self.episode.state is not WatchdogState.DISABLED:
            return
        self.started = self.monotonic.reading()
        self.episode = WatchdogEpisode(state=WatchdogState.STARTING)
        self.logger.info(
            EVENT_WATCHDOG_ARMED,
            enabled=self.enabled,
            interval_millis=self.policy.interval_millis,
            stall_millis=self.policy.stall_millis,
            escalate_millis=self.policy.escalate_millis,
            grace_millis=self.policy.grace_millis,
        )

    def stand_down(self) -> None:
        """Stop watching, from wherever the machine happens to be.

        Idempotent, and legal from every state — :func:`transitions` gives every
        state an edge to ``DISABLED`` precisely so that stopping never has to check
        whether stopping is allowed.
        """
        if self.episode.state is WatchdogState.DISABLED:
            return
        previous = self.episode.state
        self.episode = replace(self.episode, state=WatchdogState.DISABLED)
        self.logger.info(EVENT_WATCHDOG_STOOD_DOWN, previous=str(previous))

    def tick(self) -> WatchdogState:
        """Look once, and do whatever looking implies.

        Returns:
            The state this tick ended in.

        The only entry point the loop uses, and the only one a test needs.
        """
        now = self.monotonic.reading()
        taken = self.beats.snapshot()
        since_start = now.since(self.started) if self.started is not None else Duration(0)
        decision = decide(
            episode=self.episode,
            snapshot=taken,
            policy=self.policy,
            since_start=since_start,
            enabled=self.enabled,
        )
        if decision.action is WatchdogAction.CAPTURE_EVIDENCE:
            self._confirm(decision, taken, now)
        elif decision.action is WatchdogAction.TERMINATE:
            self._escalate(decision)
        else:
            self._advance(decision, taken)
        return self.episode.state

    def summary(self, snapshot: HeartbeatSnapshot | None = None) -> WatchdogSummary:
        """What the health surface should say about this watchdog.

        Args:
            snapshot: A heartbeat snapshot to describe. Read from the source when
                omitted.

        Returns:
            Counts and names, and nothing that could carry a path or a stack.

        Read-only and bounded. It takes no lock of its own — the adapter's snapshot
        is already an immutable copy — so a health snapshot can never be blocked by
        a watchdog that is busy.
        """
        taken = self.beats.snapshot() if snapshot is None else snapshot
        quietest = taken.quietest()
        suspects = tuple(
            candidate.name
            for candidate in taken.required()
            if taken.silence_of(candidate) > self.policy.interval()
        )
        return WatchdogSummary(
            enabled=self.enabled,
            running=self.running,
            state=self.episode.state,
            monitored=len(taken.beats),
            required=len(taken.required()),
            suspects=suspects,
            quietest="" if quietest is None else quietest.name,
            quietest_silent=None if quietest is None else taken.silence_of(quietest),
            incident_id="" if self.incident is None else self.incident.incident_id,
            escalated=self.incident is not None and self.incident.escalated,
        )

    def _advance(self, decision: WatchdogDecision, snapshot: HeartbeatSnapshot) -> None:
        """Move to a state that needs no action, logging only what changed.

        Args:
            decision: This tick's conclusion.
            snapshot: What it was based on.

        **A heartbeat produces no record.** Only a *transition* does. A watchdog
        that logged every beat at a one-second interval would write eighty-six
        thousand records a day saying nothing happened, and the rotation policy
        would discard the one record that mattered to make room for them.
        """
        if decision.reason == REASON_LATE_PROGRESS:
            beat = snapshot.beat_for(decision.component)
            self.logger.warning(
                EVENT_WATCHDOG_LATE_PROGRESS,
                component=decision.component,
                was=self.episode.sequence,
                now=0 if beat is None else beat.sequence,
                state=str(self.episode.state),
            )
            return
        previous = self.episode.state
        if decision.state is previous:
            return
        self.episode = replace(self.episode, state=decision.state, component=decision.component)
        if decision.state is WatchdogState.SUSPECT:
            self.logger.warning(
                EVENT_WATCHDOG_SUSPECT,
                component=decision.component,
                silent_millis=_millis(decision.silent),
                reason=decision.reason,
            )
        elif decision.state is WatchdogState.HEALTHY and previous is WatchdogState.SUSPECT:
            self.logger.info(EVENT_WATCHDOG_RECOVERED, component=decision.component)

    def _confirm(
        self, decision: WatchdogDecision, snapshot: HeartbeatSnapshot, now: MonotonicReading
    ) -> None:
        """Claim the stall, gather what can be gathered, publish, then ask.

        Args:
            decision: This tick's conclusion.
            snapshot: What it was based on.
            now: The reading the escalation deadline is measured from.

        Walks ``STALLED`` to ``CAPTURING_EVIDENCE`` to ``SHUTDOWN_REQUESTED`` inside
        one tick rather than one per tick, because the deadline runs from the stall
        and spending three intervals getting to the request would spend them out of
        the grace an operator configured.
        """
        beat = snapshot.beat_for(decision.component)
        self.episode = WatchdogEpisode(
            state=WatchdogState.STALLED,
            component=decision.component,
            sequence=0 if beat is None else beat.sequence,
            began=now,
        )
        self.logger.critical(
            EVENT_WATCHDOG_STALLED,
            component=decision.component,
            silent_millis=_millis(decision.silent),
            sequence=self.episode.sequence,
            reason=decision.reason,
        )
        self.episode = replace(self.episode, state=WatchdogState.CAPTURING_EVIDENCE)
        gathered = self._capture()
        self.incident = StallIncident(
            incident_id=self.new_incident_id(),
            run_id=self.run_id,
            correlation_id=self.correlation_id,
            detected_at=self.clock.now(),
            component=decision.component,
            silent=decision.silent if decision.silent is not None else Duration(0),
            sequence=self.episode.sequence,
            reason=decision.reason,
            state=WatchdogState.CAPTURING_EVIDENCE,
            evidence=gathered,
        )
        self._write()
        self.episode = replace(self.episode, state=WatchdogState.SHUTDOWN_REQUESTED)
        self.signals.request()
        self.logger.critical(
            EVENT_WATCHDOG_SHUTDOWN_REQUESTED,
            component=decision.component,
            incident=self.incident.incident_id,
            deadline_millis=self.policy.stall_millis + self.policy.escalate_millis,
        )

    def _capture(self) -> StallEvidence:
        """Gather the post-mortem, surviving a collector that cannot.

        Returns:
            What was gathered, however partial.

        The collector is contracted never to raise, and this still contains it. A
        watchdog that died inside its own evidence capture would leave a process
        that is both stalled and unwatched, which is strictly worse than a stall
        with no stack attached.
        """
        try:
            gathered = self.evidence.capture(self.new_incident_id())
        except Exception as fault:
            self.logger.error(  # noqa: TRY400 - Logger has no exception()
                EVENT_WATCHDOG_EVIDENCE_FAILED, fault=type(fault).__name__
            )
            return StallEvidence(problems=(f"the collector raised {type(fault).__name__}",))
        if gathered.complete():
            self.logger.critical(
                EVENT_WATCHDOG_EVIDENCE_CAPTURED,
                threads=len(gathered.threads),
                native_dump=gathered.native_dump,
                truncated=gathered.truncated,
            )
        else:
            self.logger.error(
                EVENT_WATCHDOG_EVIDENCE_FAILED,
                threads=len(gathered.threads),
                problems=len(gathered.problems),
            )
        return gathered

    def _write(self) -> None:
        """Put the incident somewhere that survives the process.

        A publication failure is logged and does not stop the escalation. The
        purpose of the record is to explain a termination that is about to happen
        anyway, so a process left running because its post-mortem could not be
        filed would be the failure mode this subsystem exists to remove.
        """
        if self.publish is None or self.incident is None:
            return
        try:
            self.publish(as_record(self.incident))
        except Exception as fault:
            self.logger.error(  # noqa: TRY400 - Logger has no exception()
                EVENT_WATCHDOG_EVIDENCE_FAILED, fault=type(fault).__name__, stage="publish"
            )

    def _escalate(self, decision: WatchdogDecision) -> None:
        """End the process, having given it every chance to end itself.

        Args:
            decision: This tick's conclusion.

        What runs before the terminator is bounded and already durable: one log
        record, which the file sink flushes per record, and one republished
        incident, which is fsynced before its rename. Nothing here starts a bundle,
        opens a socket, or waits on a lock another thread would have to release —
        the reason this path exists is that another thread stopped releasing things.
        """
        self.episode = replace(self.episode, state=WatchdogState.ESCALATING)
        if self.incident is not None:
            self.incident = replace(
                self.incident,
                escalated=True,
                state=WatchdogState.ESCALATING,
                reason=decision.reason,
            )
            self._write()
        self.logger.critical(
            EVENT_WATCHDOG_ESCALATED,
            component=decision.component,
            reason=decision.reason,
            exit_code=int(ExitCode.WATCHDOG_STALLED),
            terminating=self.escalation_enabled,
        )
        if not self.escalation_enabled:
            return
        self.terminator.terminate(int(ExitCode.WATCHDOG_STALLED))


def as_record(incident: StallIncident) -> dict[str, object]:
    """One incident, as the document that is written down.

    Args:
        incident: What to describe.

    Returns:
        A mapping of JSON-safe values, with the schema and version at the top.

    Hand-built rather than derived from the dataclass, for the reason
    ``globin.adapters.health.snapshot_document`` gives about its own: a generic
    serialiser publishes whatever field somebody adds next, and this document is
    read by an operator after the worst thing that can happen to a run.
    """
    evidence = incident.evidence
    return {
        "schema": WATCHDOG_SCHEMA,
        "schema_version": WATCHDOG_SCHEMA_VERSION,
        "incident_id": incident.incident_id,
        "run_id": incident.run_id,
        "correlation_id": incident.correlation_id,
        "detected_at": str(incident.detected_at),
        "detected_at_epoch_millis": incident.detected_at.epoch_millis,
        "component": incident.component,
        "silent_nanoseconds": incident.silent.nanoseconds,
        "sequence": incident.sequence,
        "reason": incident.reason,
        "state": str(incident.state),
        "escalated": incident.escalated,
        "details": dict(incident.details),
        "evidence": None if evidence is None else _evidence_record(evidence),
    }


def _evidence_record(evidence: StallEvidence) -> dict[str, object]:
    """One capture, as the document carries it.

    Args:
        evidence: What was gathered.

    Returns:
        A mapping of JSON-safe values.
    """
    return {
        "native_dump": evidence.native_dump,
        "truncated": evidence.truncated,
        "problems": list(evidence.problems),
        "threads": [
            {
                "name": stack.name,
                "identifier": stack.identifier,
                "truncated": stack.truncated,
                "frames": [
                    {"location": frame.location, "function": frame.function, "line": frame.line}
                    for frame in stack.frames
                ],
            }
            for stack in evidence.threads
        ],
    }


def _millis(duration: Duration | None) -> int:
    """A duration in whole milliseconds, for a log field.

    Args:
        duration: What to convert, or ``None``.

    Returns:
        The milliseconds, or ``-1`` when there was no duration — which is a value
        no real elapsed time can take, and therefore not mistakable for one.
    """
    return -1 if duration is None else duration.milliseconds
