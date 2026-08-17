"""Whether a running GLOBIN is still making progress, as pure domain types.

Phase 024 asked *how is this process doing*. This asks the one question a health
snapshot cannot answer about itself: *is anything still asking*. A process that has
stopped making progress does not report that it has — it reports nothing, and a
surface that is only read on request is silent in exactly the case that matters.

**Liveness is measured on a monotonic clock and nowhere else.** Wall-clock time
moves when an operator corrects it, when the host resumes from sleep, and twice a
year in most of the world; a stall threshold compared against it would fire on a
clock correction and stay quiet across a suspend. Every elapsed quantity here is a
:class:`~globin.domain.clock.Duration` derived from
:class:`~globin.domain.clock.MonotonicReading`. The one wall-clock value in this
module is :attr:`StallIncident.detected_at`, which exists so a human reading an
incident can find it in a log, and which nothing compares against anything.

**A heartbeat is a sequence, not a timestamp.** Rewriting a timestamp proves only
that some thread reached the line that rewrites it; a component looping inside a
wedged call can be doing that forever. What :class:`ComponentBeat` records is a
counter the component advances when it has actually got somewhere, so "still alive"
and "still progressing" are different observations rather than the same one.

**Recovery has exactly one inbound edge.** Once a stall is confirmed the machine
cannot return to :attr:`WatchdogState.HEALTHY`, and that is structural rather than
a guard somebody can forget: :func:`transitions` simply has no such pair. A
component that resumes after the process has already published a record saying it
stalled has missed whatever deadline mattered, and a run whose evidence claims a
stall the same run then denies is a run nobody will trust twice. The late beat is
recorded — see :data:`REASON_LATE_PROGRESS` — and changes nothing.

**This is not a supervisor.** Detecting, recording, asking and terminating are all
this layer does. Restarting a component, ordering a stop across subsystems,
classifying a failure or retrying anything belong to Phases 262 to 268, and the
absence is deliberate: terminating a process is not recovery, it is the considered
refusal of it.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.domain.clock import Duration, Instant, MonotonicReading
from globin.domain.observability import redact
from globin.errors import ValidationError

NANOSECONDS_PER_MILLISECOND: Final[int] = 1_000_000
"""What every threshold here is stored in milliseconds and compared in.

Settings are milliseconds because that is what an operator writes;
:class:`~globin.domain.clock.Duration` is nanoseconds because that is what the
monotonic clock reports. The conversion happens once, in this module, rather than
at each comparison.
"""

WATCHDOG_SCHEMA: Final[str] = "globin.watchdog.incident"
"""The schema name a published incident carries.

Lower case and dots only, which is what
``globin.domain.serialization.SCHEMA_NAME_ALPHABET`` permits — an underscore here
would be refused at the point of writing rather than at the point of reading.
"""

WATCHDOG_SCHEMA_VERSION: Final[int] = 1
"""Bumped when a field is removed or changes meaning, never when one is added."""

MINIMUM_INTERVAL_MILLIS: Final[int] = 100
"""How often the watchdog may look, at the fastest.

Below this the loop costs more than it measures: each pass takes a snapshot under a
lock, and a component beating once a second gains nothing from being examined ten
times between beats.
"""

MAXIMUM_INTERVAL_MILLIS: Final[int] = 60_000
"""And at the slowest. A watchdog that looks once a minute detects within a minute."""

MINIMUM_STALL_MILLIS: Final[int] = 1_000
"""The shortest silence that may be called a stall."""

MAXIMUM_STALL_MILLIS: Final[int] = 3_600_000
"""The longest. An hour of silence is the most any component may be given."""

MINIMUM_ESCALATE_MILLIS: Final[int] = 1_000
"""The shortest grace between asking the process to stop and stopping it."""

MAXIMUM_ESCALATE_MILLIS: Final[int] = 600_000
"""The longest. Ten minutes is already far past the point of a graceful stop."""

MINIMUM_GRACE_MILLIS: Final[int] = 0
"""Start-up grace may be nothing, for a process with nothing to warm up."""

MAXIMUM_GRACE_MILLIS: Final[int] = 600_000
"""And at most ten minutes, after which a start-up is a stall by another name."""

DEFAULT_INTERVAL_MILLIS: Final[int] = 1_000
"""How often the watchdog looks, unless configured otherwise."""

DEFAULT_STALL_MILLIS: Final[int] = 30_000
"""How long a required component may be silent before that is a stall."""

DEFAULT_ESCALATE_MILLIS: Final[int] = 15_000
"""How long the process is given to stop itself before it is stopped."""

DEFAULT_GRACE_MILLIS: Final[int] = 5_000
"""How long start-up is given before anything is judged."""

MAXIMUM_COMPONENT_NAME: Final[int] = 64
"""How long a monitored component's name may be.

The same bound ``globin.adapters.health`` puts on a thread name, and for the same
reason: the name is published, and an unbounded one is an unbounded record.
"""

MAXIMUM_EVIDENCE_THREADS: Final[int] = 32
"""How many threads a stall dump may describe.

A fixed constant rather than a setting, on the precedent of ``TRACEBACK_LIMIT`` in
``globin.adapters.diagnostics``. It is a bound chosen so a record stays readable,
not a policy an operator has any basis for varying — nobody can defend 24 frames
over 32, and ``docs/CONFIGURATION_POLICY.md`` warns that a configuration model is
exactly where fields like these accumulate.
"""

MAXIMUM_EVIDENCE_FRAMES: Final[int] = 24
"""How many frames of each thread, counting inwards.

Innermost rather than outermost: a hang is described by where it is parked, not by
how it got there.
"""

MAXIMUM_EVIDENCE_BYTES: Final[int] = 65_536
"""The outer bound on a rendered stall dump.

Thirty-two threads of twenty-four frames at roughly a hundred bytes each is about
seventy-seven kilobytes, so this is the bound that actually binds and the other two
shape how the truncation falls — evenly across threads rather than alphabetically.
"""


class Criticality(StrEnum):
    """Whether a component's silence is allowed to end the process."""

    REQUIRED = "required"
    """Its silence is a stall. Escalation follows."""

    ADVISORY = "advisory"
    """Its silence is worth a warning and nothing more.

    The same idea as ``HealthCheckSpec.tolerates_unknown``: the tolerance is
    declared once, visibly, at registration, rather than decided at the moment it
    would be convenient.
    """


class WatchdogState(StrEnum):
    """Where the watchdog is, in the only eight terms it uses."""

    DISABLED = "disabled"
    """Not armed. Either configuration switched it off, or it has stood down."""

    STARTING = "starting"
    """Armed, inside the start-up grace, judging nothing yet."""

    HEALTHY = "healthy"
    """Every required component has beaten within one interval."""

    SUSPECT = "suspect"
    """A required component has been silent longer than one interval.

    Deliberately derived from the poll interval rather than from a threshold of its
    own. A fourth setting would have to be defended, and "we looked and it had not
    moved since last time" is the natural meaning of a first warning.
    """

    STALLED = "stalled"
    """A required component has been silent longer than the stall threshold."""

    CAPTURING_EVIDENCE = "capturing_evidence"
    """Gathering the post-mortem.

    The one state that describes the watchdog rather than the process, and it earns
    its place for that reason: the collectors touch disk, and a watchdog wedged
    writing evidence onto a full disk would otherwise be published as ``stalled``
    for ever while the process it should have ended carried on.
    """

    SHUTDOWN_REQUESTED = "shutdown_requested"
    """The stop has been asked for, and the escalation deadline is running."""

    ESCALATING = "escalating"
    """The deadline passed. The process is being ended."""


class WatchdogAction(StrEnum):
    """What a decision asks the caller to do, in the only four terms it uses."""

    NOTHING = "nothing"
    CAPTURE_EVIDENCE = "capture_evidence"
    REQUEST_SHUTDOWN = "request_shutdown"
    TERMINATE = "terminate"


REASON_OK: Final[str] = "WATCHDOG_OK"
"""Every required component is beating."""

REASON_DISABLED: Final[str] = "WATCHDOG_DISABLED"
"""Configuration switched the watchdog off."""

REASON_WITHIN_GRACE: Final[str] = "WATCHDOG_WITHIN_GRACE"
"""Start-up grace has not elapsed, so nothing is judged yet."""

REASON_NOTHING_MONITORED: Final[str] = "WATCHDOG_NOTHING_MONITORED"
"""Armed, past grace, and no required component is registered."""

REASON_BEAT_MISSED: Final[str] = "WATCHDOG_BEAT_MISSED"
"""A required component missed an interval. A warning, not an incident."""

REASON_PROGRESS_STALLED: Final[str] = "WATCHDOG_PROGRESS_STALLED"
"""A required component passed the stall threshold."""

REASON_LATE_PROGRESS: Final[str] = "WATCHDOG_LATE_PROGRESS"
"""A component resumed after its stall was confirmed. Recorded, never acted on."""

REASON_GRACE_EXPIRED: Final[str] = "WATCHDOG_GRACE_EXPIRED"
"""The process did not stop itself inside the escalation deadline."""

REASON_EVIDENCE_PARTIAL: Final[str] = "WATCHDOG_EVIDENCE_PARTIAL"
"""At least one collector failed and the rest were still attempted."""

REASONS: Final[tuple[str, ...]] = (
    REASON_OK,
    REASON_DISABLED,
    REASON_WITHIN_GRACE,
    REASON_NOTHING_MONITORED,
    REASON_BEAT_MISSED,
    REASON_PROGRESS_STALLED,
    REASON_LATE_PROGRESS,
    REASON_GRACE_EXPIRED,
    REASON_EVIDENCE_PARTIAL,
)
"""Every reason this module can produce, closed so a stray string is visible."""

EVENT_WATCHDOG_ARMED: Final[str] = "watchdog.armed"
EVENT_WATCHDOG_STOOD_DOWN: Final[str] = "watchdog.stood.down"
EVENT_WATCHDOG_REGISTERED: Final[str] = "watchdog.component.registered"
EVENT_WATCHDOG_SUSPECT: Final[str] = "watchdog.suspect.detected"
EVENT_WATCHDOG_RECOVERED: Final[str] = "watchdog.heartbeat.recovered"
EVENT_WATCHDOG_STALLED: Final[str] = "watchdog.stall.confirmed"
EVENT_WATCHDOG_EVIDENCE_CAPTURED: Final[str] = "watchdog.evidence.captured"
EVENT_WATCHDOG_EVIDENCE_FAILED: Final[str] = "watchdog.evidence.failed"
EVENT_WATCHDOG_SHUTDOWN_REQUESTED: Final[str] = "watchdog.shutdown.requested"
EVENT_WATCHDOG_LATE_PROGRESS: Final[str] = "watchdog.late.progress"
EVENT_WATCHDOG_ESCALATED: Final[str] = "watchdog.escalation.started"
EVENT_WATCHDOG_LOOP_FAILED: Final[str] = "watchdog.loop.failed"

WATCHDOG_EVENTS: Final[tuple[str, ...]] = (
    EVENT_WATCHDOG_ARMED,
    EVENT_WATCHDOG_STOOD_DOWN,
    EVENT_WATCHDOG_REGISTERED,
    EVENT_WATCHDOG_SUSPECT,
    EVENT_WATCHDOG_RECOVERED,
    EVENT_WATCHDOG_STALLED,
    EVENT_WATCHDOG_EVIDENCE_CAPTURED,
    EVENT_WATCHDOG_EVIDENCE_FAILED,
    EVENT_WATCHDOG_SHUTDOWN_REQUESTED,
    EVENT_WATCHDOG_LATE_PROGRESS,
    EVENT_WATCHDOG_ESCALATED,
    EVENT_WATCHDOG_LOOP_FAILED,
)
"""Every event name this subsystem emits, closed for the same reason as reasons."""


@dataclass(frozen=True, slots=True)
class WatchdogPolicy:
    """The four durations that decide when silence becomes a terminated process.

    Args:
        interval_millis: How often the watchdog looks.
        grace_millis: How long start-up is given before anything is judged.
        stall_millis: How long a required component may be silent.
        escalate_millis: How long after the stall the process has to stop itself.

    Raises:
        ValidationError: If any value is out of range, or the thresholds describe a
            watchdog that could not do its job. Every problem is collected and
            reported at once, so fixing one does not merely reveal the next.

    **The ordering rules are the load-bearing half.** A stall threshold at or below
    the poll interval declares a stall on the first tick after every beat, because
    a component examined one interval after beating has by definition been silent
    for one interval. An escalation grace shorter than the interval expires between
    two ticks and is never observed, so the deadline would be whatever the next tick
    happened to be rather than what was configured. Neither is caught by a range
    check on any single value.
    """

    interval_millis: int = DEFAULT_INTERVAL_MILLIS
    grace_millis: int = DEFAULT_GRACE_MILLIS
    stall_millis: int = DEFAULT_STALL_MILLIS
    escalate_millis: int = DEFAULT_ESCALATE_MILLIS

    def __post_init__(self) -> None:
        """Refuse a policy that could not be honoured."""
        problems: list[str] = []
        bounded: tuple[tuple[str, int, int, int], ...] = (
            (
                "interval_millis",
                self.interval_millis,
                MINIMUM_INTERVAL_MILLIS,
                MAXIMUM_INTERVAL_MILLIS,
            ),
            ("grace_millis", self.grace_millis, MINIMUM_GRACE_MILLIS, MAXIMUM_GRACE_MILLIS),
            ("stall_millis", self.stall_millis, MINIMUM_STALL_MILLIS, MAXIMUM_STALL_MILLIS),
            (
                "escalate_millis",
                self.escalate_millis,
                MINIMUM_ESCALATE_MILLIS,
                MAXIMUM_ESCALATE_MILLIS,
            ),
        )
        for name, value, low, high in bounded:
            if not low <= value <= high:
                problems.append(f"{name} is {value}, and must be between {low} and {high}")
        if self.stall_millis <= self.interval_millis:
            problems.append(
                f"stall_millis {self.stall_millis} is not above interval_millis "
                f"{self.interval_millis}, so every examined component would look stalled"
            )
        if self.escalate_millis < self.interval_millis:
            problems.append(
                f"escalate_millis {self.escalate_millis} is below interval_millis "
                f"{self.interval_millis}, so the deadline would expire unobserved"
            )
        if problems:
            raise ValidationError("; ".join(problems))

    def interval(self) -> Duration:
        """How often the watchdog looks.

        Returns:
            The interval.
        """
        return Duration(self.interval_millis * NANOSECONDS_PER_MILLISECOND)

    def grace(self) -> Duration:
        """How long start-up is given.

        Returns:
            The grace.
        """
        return Duration(self.grace_millis * NANOSECONDS_PER_MILLISECOND)

    def stall(self) -> Duration:
        """How long a required component may be silent.

        Returns:
            The threshold.
        """
        return Duration(self.stall_millis * NANOSECONDS_PER_MILLISECOND)

    def deadline(self) -> Duration:
        """How long after a stall began the process must be gone.

        Returns:
            The stall threshold plus the escalation grace.

        **Measured from the stall, not from the request**, which is the difference
        between a bound and an aspiration. If the clock started when the watchdog
        got round to asking politely, a slow evidence capture would postpone the
        deadline, and the one thing this subsystem promises is that a required
        component silent for this long ends the process.
        """
        return Duration((self.stall_millis + self.escalate_millis) * NANOSECONDS_PER_MILLISECOND)


@dataclass(frozen=True, slots=True)
class ComponentBeat:
    """One monitored component, as of the last time it said anything.

    Args:
        name: What the component calls itself.
        criticality: Whether its silence may end the process.
        sequence: How many times it has reported progress. Zero at registration.
        at: When it last did, on the monotonic clock.

    Registration seeds a beat rather than leaving a gap, so "registered and never
    beaten" is measured by the same subtraction as everything else and there is no
    ``None`` timestamp for a caller to branch on.
    """

    name: str
    criticality: Criticality
    sequence: int
    at: MonotonicReading

    def __post_init__(self) -> None:
        """Refuse a name that could not be published, or a sequence that went back."""
        if not self.name or len(self.name) > MAXIMUM_COMPONENT_NAME:
            msg = (
                f"a component name must be between 1 and {MAXIMUM_COMPONENT_NAME} "
                f"characters, and {self.name!r} is {len(self.name)}"
            )
            raise ValidationError(msg)
        if self.sequence < 0:
            msg = (
                f"a progress sequence cannot be negative, and {self.name!r} reports {self.sequence}"
            )
            raise ValidationError(msg)


@dataclass(frozen=True, slots=True)
class HeartbeatSnapshot:
    """Every monitored component, frozen at one reading.

    Args:
        taken_at: The monotonic reading this snapshot describes.
        beats: Every component, ordered by name.

    Raises:
        ValidationError: If the beats are unordered, duplicated, or dated after the
            reading.

    **The last of those three is a race turned into a refusal.**
    :meth:`~globin.domain.clock.MonotonicReading.since` raises when handed the later
    reading, so a beat recorded while the snapshot was being copied would otherwise
    blow up inside the watchdog loop, intermittently and only under load. An adapter
    that reads ``taken_at`` after releasing its lock cannot produce one; this refuses
    the case anyway, because a loud domain error beats a mystery.
    """

    taken_at: MonotonicReading
    beats: tuple[ComponentBeat, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a snapshot that could not have been taken."""
        names = [beat.name for beat in self.beats]
        if names != sorted(names):
            msg = f"a heartbeat snapshot must be ordered by name, and this is {names}"
            raise ValidationError(msg)
        if len(set(names)) != len(names):
            msg = f"a component appears twice in one snapshot: {names}"
            raise ValidationError(msg)
        for beat in self.beats:
            if beat.at > self.taken_at:
                msg = (
                    f"{beat.name!r} reports a beat later than the snapshot that contains "
                    f"it, which means the reading was taken before the copy"
                )
                raise ValidationError(msg)

    def required(self) -> tuple[ComponentBeat, ...]:
        """The components whose silence may end the process.

        Returns:
            Them, in name order.
        """
        return tuple(beat for beat in self.beats if beat.criticality is Criticality.REQUIRED)

    def quietest(self) -> ComponentBeat | None:
        """The required component that has been silent longest.

        Returns:
            It, or ``None`` when nothing required is registered.

        Ties break by name so that two components silent since the same reading
        produce the same incident on every run — the record is published and
        digested, and a digest that depended on dictionary order would differ
        between two runs of one tree.
        """
        candidates = self.required()
        if not candidates:
            return None
        return min(candidates, key=lambda beat: (beat.at, beat.name))

    def beat_for(self, name: str) -> ComponentBeat | None:
        """One component by name.

        Args:
            name: What to look for.

        Returns:
            Its beat, or ``None`` when it is not registered.
        """
        return next((beat for beat in self.beats if beat.name == name), None)

    def silence_of(self, beat: ComponentBeat) -> Duration:
        """How long a component has been silent, as of this snapshot.

        Args:
            beat: The component.

        Returns:
            The elapsed monotonic duration.
        """
        return self.taken_at.since(beat.at)


@dataclass(frozen=True, slots=True)
class WatchdogEpisode:
    """What the watchdog remembers between ticks.

    Args:
        state: Where it is.
        component: Which component the current episode is about, if any.
        sequence: That component's progress counter when the episode opened.
        began: When the stall was confirmed, on the monotonic clock.

    ``began`` is the origin the escalation deadline is measured from, which is why
    it is remembered rather than recomputed.
    """

    state: WatchdogState = WatchdogState.DISABLED
    component: str = ""
    sequence: int = 0
    began: MonotonicReading | None = None


@dataclass(frozen=True, slots=True)
class WatchdogDecision:
    """One tick's conclusion: where to be, and what to do to get there.

    Args:
        state: The state this tick ends in.
        action: What the caller must perform.
        reason: Which of :data:`REASONS` explains it.
        component: The component the conclusion is about, if any.
        silent: How long that component had been silent.
    """

    state: WatchdogState
    action: WatchdogAction = WatchdogAction.NOTHING
    reason: str = REASON_OK
    component: str = ""
    silent: Duration | None = None


@dataclass(frozen=True, slots=True)
class FrameLine:
    """One frame of one thread's stack, in a form that names no person.

    Args:
        location: The source path, already reduced to a publishable form.
        function: The function's name.
        line: The line number.

    **There is no field for locals, and that is the point.**
    ``sys._current_frames`` hands out live frame objects whose ``f_locals`` hold the
    values a credential-reading function was working with, not merely the name of
    the function reading them. This type cannot carry them.
    """

    location: str
    function: str
    line: int


@dataclass(frozen=True, slots=True)
class ThreadStack:
    """Where one thread was parked when the stall was confirmed.

    Args:
        name: The thread's name, already sanitised.
        identifier: Its interpreter identifier.
        frames: Innermost frames, bounded by :data:`MAXIMUM_EVIDENCE_FRAMES`.
        truncated: Whether frames were dropped to honour that bound.
    """

    name: str
    identifier: int
    frames: tuple[FrameLine, ...] = ()
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class StallEvidence:
    """What could be gathered about a confirmed stall.

    Args:
        threads: One entry per described thread.
        native_dump: Whether ``faulthandler`` wrote its own all-thread traceback.
        truncated: Whether any bound was reached.
        problems: One sentence per collector that failed.

    **A failed collector is data, not an exception.** Each source is attempted
    independently and a failure in one must not stop the others, so this type can
    describe a capture that half worked — which is the normal case when the reason
    for capturing is that something is already wrong.
    """

    threads: tuple[ThreadStack, ...] = ()
    native_dump: bool = False
    truncated: bool = False
    problems: tuple[str, ...] = ()

    def complete(self) -> bool:
        """Whether every collector succeeded.

        Returns:
            ``True`` when nothing failed.
        """
        return not self.problems


@dataclass(frozen=True, slots=True)
class StallIncident:
    """One confirmed stall, in the form that is published.

    Args:
        incident_id: The identifier this incident is filed under.
        run_id: Which run it happened in.
        correlation_id: The run's correlation identifier.
        detected_at: When, in wall-clock terms, for a human reading a log.
        component: Which component went quiet.
        silent: How long it had been quiet when the stall was confirmed.
        sequence: Its progress counter at that moment.
        reason: Which of :data:`REASONS` applies.
        state: Where the watchdog was when this record was written.
        escalated: Whether the process was ended rather than stopping itself.
        evidence: What was gathered, when anything was.

    ``details`` are redacted on construction for the reason
    :class:`~globin.domain.observability.LogEvent` redacts its own: a record that
    can only be built safely is safer than one a caller must remember to sanitise.
    """

    incident_id: str
    run_id: str
    correlation_id: str
    detected_at: Instant
    component: str
    silent: Duration
    sequence: int
    reason: str = REASON_PROGRESS_STALLED
    state: WatchdogState = WatchdogState.STALLED
    escalated: bool = False
    evidence: StallEvidence | None = None
    details: tuple[tuple[str, object], ...] = ()

    def __post_init__(self) -> None:
        """Refuse an unknown reason, and redact whatever detail was handed over."""
        if self.reason not in REASONS:
            msg = f"{self.reason!r} is not one of this module's reasons"
            raise ValidationError(msg)
        safe = redact(dict(self.details))
        object.__setattr__(self, "details", tuple(sorted(safe.items())))


@dataclass(frozen=True, slots=True)
class WatchdogSummary:
    """What the health surface says about the watchdog.

    Args:
        enabled: Whether configuration switched it on.
        running: Whether its thread is alive right now.
        state: Where it is.
        monitored: How many components are registered.
        required: How many of those may end the process.
        suspects: Which required components are currently past one interval.
        quietest: The required component silent longest, if any.
        quietest_silent: How long that has been.
        incident_id: The incident this run raised, if it raised one.
        escalated: Whether the process was ended rather than stopping itself.

    Deliberately smaller than :class:`StallIncident`, and the difference is where
    each one goes. A health snapshot travels — into a support bundle, and from
    there to whoever the operator sends it to — so everything here is a count, a
    state name, or a component name somebody chose. No stack, no path and no
    timestamp crosses this boundary; those stay in the incident, which is written
    to the user-local runtime tree and is not a bundle candidate.
    """

    enabled: bool
    running: bool
    state: WatchdogState
    monitored: int = 0
    required: int = 0
    suspects: tuple[str, ...] = ()
    quietest: str = ""
    quietest_silent: Duration | None = None
    incident_id: str = ""
    escalated: bool = False


def transitions() -> tuple[tuple[WatchdogState, WatchdogState], ...]:
    """Every move the machine may make.

    Returns:
        Source and target, in a fixed order.

    A function rather than a constant because a tuple literal at module scope would
    be a call in a layer package, which ``tests/architecture`` refuses.

    Read the absences rather than the presences. There is no pair taking
    :attr:`WatchdogState.STALLED`, :attr:`WatchdogState.CAPTURING_EVIDENCE`,
    :attr:`WatchdogState.SHUTDOWN_REQUESTED` or :attr:`WatchdogState.ESCALATING`
    back to :attr:`WatchdogState.HEALTHY`, and there is exactly one edge into
    :attr:`WatchdogState.STALLED` — which is what makes one incident per episode a
    property of the graph rather than of a counter somebody has to get right.
    """
    return (
        (WatchdogState.DISABLED, WatchdogState.STARTING),
        (WatchdogState.STARTING, WatchdogState.HEALTHY),
        (WatchdogState.STARTING, WatchdogState.SUSPECT),
        # Straight from start-up to a stall, without pausing at suspect. Nothing
        # orders `grace_millis` against `stall_millis`, so a long grace over a
        # short stall is a legal policy — and when that grace ends, a component
        # that has been quiet throughout is already past the threshold. Found by
        # the property test rather than reasoned about, and admitted here rather
        # than forbidden in the policy: the situation is real, and refusing to
        # name it would only mean the machine reached a state its own table
        # denied.
        (WatchdogState.STARTING, WatchdogState.STALLED),
        (WatchdogState.HEALTHY, WatchdogState.SUSPECT),
        # And straight from healthy to a stall, skipping suspect entirely. The
        # watchdog looks every `interval_millis`, but nothing guarantees it is
        # *scheduled* that often: under load, or after the host resumes, two ticks
        # can be far enough apart that a component was within its interval at the
        # first and past the stall threshold at the second. Suspect is a courtesy
        # the machine extends when it gets the chance, not a station every episode
        # stops at.
        (WatchdogState.HEALTHY, WatchdogState.STALLED),
        (WatchdogState.SUSPECT, WatchdogState.HEALTHY),
        (WatchdogState.SUSPECT, WatchdogState.STALLED),
        (WatchdogState.STALLED, WatchdogState.CAPTURING_EVIDENCE),
        (WatchdogState.CAPTURING_EVIDENCE, WatchdogState.SHUTDOWN_REQUESTED),
        (WatchdogState.SHUTDOWN_REQUESTED, WatchdogState.ESCALATING),
        (WatchdogState.STARTING, WatchdogState.DISABLED),
        (WatchdogState.HEALTHY, WatchdogState.DISABLED),
        (WatchdogState.SUSPECT, WatchdogState.DISABLED),
        (WatchdogState.STALLED, WatchdogState.DISABLED),
        (WatchdogState.CAPTURING_EVIDENCE, WatchdogState.DISABLED),
        (WatchdogState.SHUTDOWN_REQUESTED, WatchdogState.DISABLED),
        (WatchdogState.ESCALATING, WatchdogState.DISABLED),
    )


def may_move(source: WatchdogState, target: WatchdogState) -> bool:
    """Whether one state may become another.

    Args:
        source: Where the machine is.
        target: Where it would go.

    Returns:
        ``True`` when the move is legal, and when it is not a move at all — staying
        put is always permitted, and treating it as an edge would put sixteen
        self-pairs in :func:`transitions` for no reader's benefit.
    """
    return source is target or (source, target) in transitions()


def settled(state: WatchdogState) -> bool:
    """Whether an incident has already been claimed in this state.

    Args:
        state: Where the machine is.

    Returns:
        ``True`` from the moment a stall is confirmed onwards.

    The one predicate the late-heartbeat rule needs: past this line the machine has
    already published a verdict, so a component resuming is recorded and ignored.
    """
    return state in (
        WatchdogState.STALLED,
        WatchdogState.CAPTURING_EVIDENCE,
        WatchdogState.SHUTDOWN_REQUESTED,
        WatchdogState.ESCALATING,
    )


def decide(
    *,
    episode: WatchdogEpisode,
    snapshot: HeartbeatSnapshot,
    policy: WatchdogPolicy,
    since_start: Duration,
    enabled: bool = True,
) -> WatchdogDecision:
    """Judge one tick.

    Args:
        episode: What the watchdog remembers.
        snapshot: Every component, frozen at one reading.
        policy: The thresholds.
        since_start: How long the watchdog has been armed.
        enabled: Whether configuration switched it on.

    Returns:
        Where this tick ends and what the caller must do.

    Values in, value out. No clock, no port, no logging and no mutation, which is
    what lets every row of :func:`transitions` be a test built from literals.
    """
    if not enabled or episode.state is WatchdogState.DISABLED:
        # **A disarmed episode stays disarmed, and only :meth:`arm` leaves it.**
        # Without this a tick arriving after ``stand_down`` would move straight to
        # ``HEALTHY``, which is both an edge :func:`transitions` does not contain
        # and a live hazard: :meth:`WatchdogThread.stop` disarms *before* it joins
        # precisely so that a loop which never noticed the wake event can do no
        # harm, and a cycle that could re-arm itself would undo that. Found by a
        # property test comparing every decision against the table.
        return WatchdogDecision(state=WatchdogState.DISABLED, reason=REASON_DISABLED)
    if settled(episode.state):
        return _settled_decision(episode=episode, snapshot=snapshot, policy=policy)
    if episode.state is WatchdogState.STARTING and since_start < policy.grace():
        # **Grace applies while starting, and not afterwards.** Testing the elapsed
        # time alone would let a ``HEALTHY`` episode fall back to ``STARTING`` —
        # an edge :func:`transitions` does not contain, and unreachable in
        # production only because ``since_start`` never decreases. Reading the
        # state as well says what the rule actually is: start-up is a phase the
        # machine leaves once, not a window it can re-enter.
        return WatchdogDecision(state=WatchdogState.STARTING, reason=REASON_WITHIN_GRACE)
    quietest = snapshot.quietest()
    if quietest is None:
        return WatchdogDecision(state=WatchdogState.HEALTHY, reason=REASON_NOTHING_MONITORED)
    silent = snapshot.silence_of(quietest)
    if silent > policy.stall():
        return WatchdogDecision(
            state=WatchdogState.STALLED,
            action=WatchdogAction.CAPTURE_EVIDENCE,
            reason=REASON_PROGRESS_STALLED,
            component=quietest.name,
            silent=silent,
        )
    if silent > policy.interval():
        return WatchdogDecision(
            state=WatchdogState.SUSPECT,
            reason=REASON_BEAT_MISSED,
            component=quietest.name,
            silent=silent,
        )
    return WatchdogDecision(state=WatchdogState.HEALTHY, component=quietest.name, silent=silent)


def _settled_decision(
    *, episode: WatchdogEpisode, snapshot: HeartbeatSnapshot, policy: WatchdogPolicy
) -> WatchdogDecision:
    """Judge a tick that arrives after a stall was confirmed.

    Args:
        episode: What the watchdog remembers.
        snapshot: Every component, frozen at one reading.
        policy: The thresholds.

    Returns:
        Where this tick ends and what the caller must do.

    Only two things can happen here, and returning to health is neither. The
    deadline may expire, or a component may resume — and a resumption is reported
    so that the incident records it, not so that anything reconsiders.
    """
    beat = snapshot.beat_for(episode.component)
    if beat is not None and beat.sequence > episode.sequence:
        return WatchdogDecision(
            state=episode.state, reason=REASON_LATE_PROGRESS, component=episode.component
        )
    began = episode.began
    if (
        episode.state is WatchdogState.SHUTDOWN_REQUESTED
        and began is not None
        # A snapshot older than the episode it is judged against cannot have
        # reached any deadline, and `since` refuses to subtract in that direction.
        # In production the ordering makes it unreachable — `tick` reads the clock
        # before it takes the snapshot, so the snapshot is never the earlier of the
        # two — but this function is pure and total by contract, and a property
        # test over generated input found the combination that made it raise. A
        # judgement that can raise would take the watchdog loop with it, and the
        # loop is deliberately written to stop rather than retry.
        and began <= snapshot.taken_at
    ):
        elapsed = snapshot.taken_at.since(began)
        if elapsed > policy.deadline():
            return WatchdogDecision(
                state=WatchdogState.ESCALATING,
                action=WatchdogAction.TERMINATE,
                reason=REASON_GRACE_EXPIRED,
                component=episode.component,
                silent=elapsed,
            )
    return WatchdogDecision(state=episode.state, reason=REASON_PROGRESS_STALLED)
