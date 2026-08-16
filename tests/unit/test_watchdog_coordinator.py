"""The escalation machine, driven by a clock the test owns.

Nothing here starts a thread and nothing here sleeps. The coordinator takes its
readings from an injected clock and performs every effect through a port, so the
whole chain — suspect, stall, evidence, request, deadline, termination — is
exercised in microseconds and always in the same order.

Every double is a hand-written class satisfying a ``Protocol`` structurally, which
is what ``docs/TESTING_STRATEGY.md`` asks for: a mock would satisfy any interface,
including one the production code does not have.
"""

from dataclasses import dataclass, field

import pytest

from globin.application.observability import Logger
from globin.application.watchdog import RuntimeWatchdog, as_record
from globin.domain.bootstrap import ExitCode
from globin.domain.clock import Duration, Instant, MonotonicReading, instant_from_epoch_millis
from globin.domain.observability import LogEvent, Severity
from globin.domain.watchdog import (
    DEFAULT_ESCALATE_MILLIS,
    DEFAULT_STALL_MILLIS,
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
    NANOSECONDS_PER_MILLISECOND,
    ComponentBeat,
    Criticality,
    FrameLine,
    HeartbeatSnapshot,
    StallEvidence,
    ThreadStack,
    WatchdogEpisode,
    WatchdogPolicy,
    WatchdogState,
)

INCIDENT_ID = "0123456789abcdef0123456789abcdef"
RUN_ID = "fedcba9876543210fedcba9876543210"
CORRELATION_ID = "00112233445566778899aabbccddeeff"
WALL = instant_from_epoch_millis(1_780_000_000_000)


def reading(millis: int) -> MonotonicReading:
    """A monotonic reading that many milliseconds after the origin."""
    return MonotonicReading(millis * NANOSECONDS_PER_MILLISECOND)


@dataclass(slots=True)
class _Clock:
    """A monotonic clock the test moves by hand."""

    at: MonotonicReading

    def reading(self) -> MonotonicReading:
        return self.at


@dataclass(frozen=True, slots=True)
class _Wall:
    """A wall clock that never moves, so an incident is byte-identical each run."""

    def now(self) -> Instant:
        return WALL


@dataclass(slots=True)
class _Beats:
    """A heartbeat source the test sets directly."""

    taken: HeartbeatSnapshot

    def snapshot(self) -> HeartbeatSnapshot:
        return self.taken


@dataclass(slots=True)
class _Evidence:
    """A collector that records what it was asked for, and can misbehave."""

    result: StallEvidence
    calls: list[str] = field(default_factory=list)
    explodes: bool = False

    def capture(self, incident_id: str) -> StallEvidence:
        self.calls.append(incident_id)
        if self.explodes:
            msg = "the collector could not read this process"
            raise RuntimeError(msg)
        return self.result


@dataclass(slots=True)
class _Signals:
    """The stop latch, with the same monotone behaviour the real one has."""

    stopped: bool = False
    installs: int = 0

    def install(self) -> None:
        self.installs += 1

    def request(self) -> None:
        self.stopped = True

    def requested(self) -> bool:
        return self.stopped


@dataclass(slots=True)
class _Terminator:
    """Records the exit code instead of ending the test runner."""

    codes: list[int] = field(default_factory=list)

    def terminate(self, code: int) -> None:
        self.codes.append(code)


@dataclass(slots=True)
class _Sink:
    """Keeps every record so a test can assert on fields rather than on text."""

    events: list[LogEvent] = field(default_factory=list)

    def emit(self, event: LogEvent) -> None:
        self.events.append(event)


@dataclass(slots=True)
class _Store:
    """Records published documents, and can refuse to accept one."""

    documents: list[dict[str, object]] = field(default_factory=list)
    explodes: bool = False

    def publish(self, document: object) -> None:
        if self.explodes:
            msg = "the runtime tree is read-only"
            raise OSError(msg)
        assert isinstance(document, dict)
        self.documents.append(document)


@dataclass(slots=True)
class Harness:
    """Everything one watchdog needs, with each part reachable from a test."""

    cycle: RuntimeWatchdog
    clock: _Clock
    beats: _Beats
    evidence: _Evidence
    signals: _Signals
    terminator: _Terminator
    sink: _Sink
    store: _Store

    def at(self, millis: int, *beats: ComponentBeat) -> None:
        """Move the clock and replace the heartbeat table in one step."""
        self.clock.at = reading(millis)
        self.beats.taken = HeartbeatSnapshot(
            taken_at=reading(millis), beats=tuple(sorted(beats, key=lambda beat: beat.name))
        )

    def events(self, name: str) -> list[LogEvent]:
        """Every record carrying one event name."""
        return [event for event in self.sink.events if event.event == name]

    def fields(self, name: str) -> dict[str, object]:
        """The fields of the first record carrying one event name."""
        return self.events(name)[0].as_mapping()


def beat(
    name: str = "feed",
    *,
    at: int = 0,
    sequence: int = 1,
    criticality: Criticality = Criticality.REQUIRED,
) -> ComponentBeat:
    """One component beat, spelled in milliseconds since the origin."""
    return ComponentBeat(name=name, criticality=criticality, sequence=sequence, at=reading(at))


@pytest.fixture
def harness() -> Harness:
    """An armed-able watchdog wired entirely to doubles."""
    clock = _Clock(at=reading(0))
    beats = _Beats(taken=HeartbeatSnapshot(taken_at=reading(0)))
    evidence = _Evidence(
        result=StallEvidence(
            threads=(
                ThreadStack(
                    name="MainThread",
                    identifier=1,
                    frames=(FrameLine(location="globin/runtime/cli.py", function="main", line=7),),
                ),
            ),
            native_dump=True,
        )
    )
    signals = _Signals()
    terminator = _Terminator()
    sink = _Sink()
    store = _Store()
    cycle = RuntimeWatchdog(
        monotonic=clock,
        clock=_Wall(),
        beats=beats,
        policy=WatchdogPolicy(),
        evidence=evidence,
        signals=signals,
        terminator=terminator,
        logger=Logger(sink=sink, correlation_id=CORRELATION_ID),
        run_id=RUN_ID,
        correlation_id=CORRELATION_ID,
        new_incident_id=lambda: INCIDENT_ID,
        episode=WatchdogEpisode(),
        publish=store.publish,
    )
    return Harness(
        cycle=cycle,
        clock=clock,
        beats=beats,
        evidence=evidence,
        signals=signals,
        terminator=terminator,
        sink=sink,
        store=store,
    )


def drive_to_stall(harness: Harness) -> None:
    """Arm, pass the grace, and cross the stall threshold in one confirmed tick."""
    harness.cycle.arm()
    harness.at(DEFAULT_STALL_MILLIS + 1, beat(at=0, sequence=41))
    harness.cycle.tick()


# ---------------------------------------------------------------------------
# Arming and standing down
# ---------------------------------------------------------------------------


def test_arming_records_the_thresholds_it_will_hold_the_process_to(harness: Harness) -> None:
    """An operator reading one record should not have to find the config too."""
    harness.cycle.arm()
    assert harness.cycle.episode.state is WatchdogState.STARTING
    fields = harness.fields(EVENT_WATCHDOG_ARMED)
    assert fields["stall_millis"] == DEFAULT_STALL_MILLIS
    assert fields["escalate_millis"] == DEFAULT_ESCALATE_MILLIS


def test_arming_twice_does_not_restart_the_grace(harness: Harness) -> None:
    """Otherwise a caller in a loop could postpone every threshold for ever."""
    harness.cycle.arm()
    first = harness.cycle.started
    harness.clock.at = reading(10_000)
    harness.cycle.arm()
    assert harness.cycle.started == first
    assert len(harness.events(EVENT_WATCHDOG_ARMED)) == 1


def test_standing_down_is_idempotent_and_legal_from_anywhere(harness: Harness) -> None:
    drive_to_stall(harness)
    harness.cycle.stand_down()
    harness.cycle.stand_down()
    assert harness.cycle.episode.state is WatchdogState.DISABLED
    assert len(harness.events(EVENT_WATCHDOG_STOOD_DOWN)) == 1


def test_a_disabled_watchdog_ticks_without_judging_anything(harness: Harness) -> None:
    harness.cycle.enabled = False
    harness.cycle.arm()
    harness.at(10_000_000, beat(at=0))
    assert harness.cycle.tick() is WatchdogState.DISABLED
    assert harness.store.documents == []
    assert harness.terminator.codes == []


# ---------------------------------------------------------------------------
# Ordinary running
# ---------------------------------------------------------------------------


def test_a_heartbeat_produces_no_record_and_only_a_transition_does(harness: Harness) -> None:
    """A record per beat would bury the one record that mattered.

    At the default interval that is eighty-six thousand lines a day saying nothing
    happened, and the rotation policy would discard the stall to make room.
    """
    harness.cycle.arm()
    for moment in range(6_000, 12_000, 500):
        harness.at(moment, beat(at=moment, sequence=moment))
        harness.cycle.tick()
    assert harness.events(EVENT_WATCHDOG_SUSPECT) == []
    assert len(harness.sink.events) == 1


def test_a_missed_interval_warns_once_and_recovery_says_so(harness: Harness) -> None:
    harness.cycle.arm()
    harness.at(10_000, beat(at=6_000, sequence=1))
    assert harness.cycle.tick() is WatchdogState.SUSPECT
    harness.at(11_000, beat(at=11_000, sequence=2))
    assert harness.cycle.tick() is WatchdogState.HEALTHY
    assert len(harness.events(EVENT_WATCHDOG_SUSPECT)) == 1
    assert harness.fields(EVENT_WATCHDOG_RECOVERED)["component"] == "feed"
    assert harness.terminator.codes == []


def test_a_component_staying_suspect_is_not_warned_about_twice(harness: Harness) -> None:
    """Only a change of state is a record."""
    harness.cycle.arm()
    harness.at(10_000, beat(at=6_000))
    harness.cycle.tick()
    harness.at(11_000, beat(at=6_000))
    harness.cycle.tick()
    assert len(harness.events(EVENT_WATCHDOG_SUSPECT)) == 1


# ---------------------------------------------------------------------------
# A confirmed stall
# ---------------------------------------------------------------------------


def test_a_confirmed_stall_claims_captures_publishes_and_asks_in_that_order(
    harness: Harness,
) -> None:
    """The ordering is the guarantee: the evidence is durable before the ask.

    If the ask fails, the next thing that happens is a termination that runs no
    cleanup at all, so anything not already on disk is lost.
    """
    drive_to_stall(harness)
    assert harness.cycle.episode.state is WatchdogState.SHUTDOWN_REQUESTED
    assert harness.evidence.calls == [INCIDENT_ID]
    assert harness.signals.requested()
    assert len(harness.store.documents) == 1
    order = [event.event for event in harness.sink.events]
    assert order.index(EVENT_WATCHDOG_STALLED) < order.index(EVENT_WATCHDOG_EVIDENCE_CAPTURED)
    assert order.index(EVENT_WATCHDOG_EVIDENCE_CAPTURED) < order.index(
        EVENT_WATCHDOG_SHUTDOWN_REQUESTED
    )


def test_the_stall_record_is_critical_and_names_the_component_and_its_sequence(
    harness: Harness,
) -> None:
    drive_to_stall(harness)
    record = harness.events(EVENT_WATCHDOG_STALLED)[0]
    assert record.severity is Severity.CRITICAL
    assert record.as_mapping()["component"] == "feed"
    assert record.as_mapping()["sequence"] == 41


def test_only_one_incident_is_raised_however_long_the_stall_lasts(harness: Harness) -> None:
    """Exactly-once, and it is the graph that guarantees it rather than a counter."""
    drive_to_stall(harness)
    for moment in (DEFAULT_STALL_MILLIS + 2, DEFAULT_STALL_MILLIS + 3):
        harness.at(moment, beat(at=0, sequence=41))
        harness.cycle.tick()
    assert len(harness.events(EVENT_WATCHDOG_STALLED)) == 1
    assert harness.evidence.calls == [INCIDENT_ID]


def test_a_late_beat_after_a_confirmed_stall_is_recorded_and_reverses_nothing(
    harness: Harness,
) -> None:
    """The rule this phase exists to get right."""
    drive_to_stall(harness)
    harness.at(DEFAULT_STALL_MILLIS + 10, beat(at=DEFAULT_STALL_MILLIS + 5, sequence=42))
    assert harness.cycle.tick() is WatchdogState.SHUTDOWN_REQUESTED
    fields = harness.fields(EVENT_WATCHDOG_LATE_PROGRESS)
    assert fields["was"] == 41
    assert fields["now"] == 42


# ---------------------------------------------------------------------------
# Evidence that half works
# ---------------------------------------------------------------------------


def test_a_collector_that_raises_is_recorded_and_the_escalation_continues(
    harness: Harness,
) -> None:
    """A watchdog that died in its own capture leaves a stalled, unwatched process."""
    harness.evidence.explodes = True
    drive_to_stall(harness)
    assert harness.events(EVENT_WATCHDOG_EVIDENCE_FAILED)
    assert harness.signals.requested()
    assert harness.cycle.incident is not None
    assert harness.cycle.incident.evidence is not None
    assert harness.cycle.incident.evidence.problems


def test_a_partial_capture_is_reported_as_a_failure_and_still_published(
    harness: Harness,
) -> None:
    harness.evidence.result = StallEvidence(
        native_dump=True, problems=("the frames could not be read",)
    )
    drive_to_stall(harness)
    assert harness.events(EVENT_WATCHDOG_EVIDENCE_FAILED)
    assert harness.events(EVENT_WATCHDOG_EVIDENCE_CAPTURED) == []
    assert len(harness.store.documents) == 1


def test_a_publication_that_fails_does_not_stop_the_process_being_stopped(
    harness: Harness,
) -> None:
    """The record explains a termination that is about to happen anyway."""
    harness.store.explodes = True
    drive_to_stall(harness)
    assert harness.signals.requested()
    assert harness.events(EVENT_WATCHDOG_EVIDENCE_FAILED)


def test_a_watchdog_with_nowhere_to_publish_still_asks(harness: Harness) -> None:
    harness.cycle.publish = None
    drive_to_stall(harness)
    assert harness.signals.requested()
    assert harness.store.documents == []


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


def expire(harness: Harness) -> None:
    """Move past the deadline, measured from the stall rather than the request."""
    past = DEFAULT_STALL_MILLIS + DEFAULT_STALL_MILLIS + DEFAULT_ESCALATE_MILLIS + 2
    harness.at(past, beat(at=0, sequence=41))
    harness.cycle.tick()


def test_the_deadline_expiring_ends_the_process_with_its_own_exit_code(
    harness: Harness,
) -> None:
    drive_to_stall(harness)
    expire(harness)
    assert harness.terminator.codes == [int(ExitCode.WATCHDOG_STALLED)]
    assert harness.cycle.episode.state is WatchdogState.ESCALATING


def test_the_incident_is_republished_as_escalated_before_the_process_ends(
    harness: Harness,
) -> None:
    """The last durable evidence, because no closing lifecycle record follows."""
    drive_to_stall(harness)
    expire(harness)
    assert len(harness.store.documents) == 2
    assert harness.store.documents[-1]["escalated"] is True


def test_escalation_switched_off_keeps_everything_except_the_killing(
    harness: Harness,
) -> None:
    """The switch an operator wants while learning what their thresholds mean."""
    harness.cycle.escalation_enabled = False
    drive_to_stall(harness)
    expire(harness)
    assert harness.terminator.codes == []
    assert harness.fields(EVENT_WATCHDOG_ESCALATED)["terminating"] is False
    assert harness.cycle.incident is not None
    assert harness.cycle.incident.escalated


def test_nothing_is_terminated_while_the_process_is_still_inside_its_grace(
    harness: Harness,
) -> None:
    drive_to_stall(harness)
    inside = DEFAULT_STALL_MILLIS + DEFAULT_STALL_MILLIS + DEFAULT_ESCALATE_MILLIS
    harness.at(inside, beat(at=0, sequence=41))
    harness.cycle.tick()
    assert harness.terminator.codes == []


# ---------------------------------------------------------------------------
# What the health surface is told
# ---------------------------------------------------------------------------


def test_the_summary_counts_what_is_monitored_and_names_the_quietest(
    harness: Harness,
) -> None:
    harness.cycle.arm()
    harness.at(
        20_000,
        beat("feed", at=1_000),
        beat("chatter", at=19_900, criticality=Criticality.ADVISORY),
    )
    summary = harness.cycle.summary()
    assert summary.monitored == 2
    assert summary.required == 1
    assert summary.quietest == "feed"
    assert summary.suspects == ("feed",)
    assert summary.state is WatchdogState.STARTING


def test_the_summary_reports_the_incident_and_whether_it_escalated(
    harness: Harness,
) -> None:
    drive_to_stall(harness)
    expire(harness)
    summary = harness.cycle.summary()
    assert summary.incident_id == INCIDENT_ID
    assert summary.escalated


def test_the_summary_of_an_empty_registry_names_nothing(harness: Harness) -> None:
    summary = harness.cycle.summary()
    assert summary.monitored == 0
    assert summary.quietest == ""
    assert summary.quietest_silent is None


# ---------------------------------------------------------------------------
# The published document
# ---------------------------------------------------------------------------


def test_the_published_incident_carries_its_schema_and_version(harness: Harness) -> None:
    drive_to_stall(harness)
    document = harness.store.documents[0]
    assert document["schema"] == "globin.watchdog.incident"
    assert document["schema_version"] == 1


def test_the_published_incident_renders_its_evidence_without_a_frame_object(
    harness: Harness,
) -> None:
    drive_to_stall(harness)
    evidence = harness.store.documents[0]["evidence"]
    assert isinstance(evidence, dict)
    threads = evidence["threads"]
    assert isinstance(threads, list)
    assert threads[0]["frames"] == [
        {"location": "globin/runtime/cli.py", "function": "main", "line": 7}
    ]


def test_an_incident_with_no_evidence_renders_a_null_rather_than_an_empty_shape(
    harness: Harness,
) -> None:
    """A reader must be able to tell "nothing was gathered" from "nothing was wrong"."""
    drive_to_stall(harness)
    assert harness.cycle.incident is not None
    document = as_record(
        type(harness.cycle.incident)(
            incident_id=INCIDENT_ID,
            run_id=RUN_ID,
            correlation_id=CORRELATION_ID,
            detected_at=WALL,
            component="feed",
            silent=Duration(0),
            sequence=1,
        )
    )
    assert document["evidence"] is None


def test_the_published_incident_carries_no_credential_from_its_details(
    harness: Harness,
) -> None:
    """Redaction happens on construction, so there is no unsafe way to build one."""
    drive_to_stall(harness)
    assert harness.cycle.incident is not None
    document = as_record(
        type(harness.cycle.incident)(
            incident_id=INCIDENT_ID,
            run_id=RUN_ID,
            correlation_id=CORRELATION_ID,
            detected_at=WALL,
            component="feed",
            silent=Duration(0),
            sequence=1,
            details=(("api_key", "live-secret"),),
        )
    )
    details = document["details"]
    assert isinstance(details, dict)
    assert details["api_key"] == "[redacted]"
