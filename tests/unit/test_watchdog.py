"""The watchdog's pure domain: the policy, the graph, and the one decision.

Every case here is built from literals. Nothing reads a clock, starts a thread or
touches a port, which is the point of putting the whole judgement in this layer —
a stall that takes thirty seconds to happen in production takes none to assert.
"""

import pytest

from globin.domain.clock import Duration, MonotonicReading, instant_from_epoch_millis
from globin.domain.watchdog import (
    DEFAULT_ESCALATE_MILLIS,
    DEFAULT_INTERVAL_MILLIS,
    DEFAULT_STALL_MILLIS,
    MAXIMUM_COMPONENT_NAME,
    NANOSECONDS_PER_MILLISECOND,
    REASON_BEAT_MISSED,
    REASON_DISABLED,
    REASON_GRACE_EXPIRED,
    REASON_LATE_PROGRESS,
    REASON_NOTHING_MONITORED,
    REASON_OK,
    REASON_PROGRESS_STALLED,
    REASON_WITHIN_GRACE,
    REASONS,
    WATCHDOG_EVENTS,
    ComponentBeat,
    Criticality,
    HeartbeatSnapshot,
    StallEvidence,
    StallIncident,
    WatchdogAction,
    WatchdogDecision,
    WatchdogEpisode,
    WatchdogPolicy,
    WatchdogState,
    decide,
    may_move,
    settled,
    transitions,
)
from globin.errors import ValidationError

POLICY = WatchdogPolicy()
"""The declared defaults, which every timing case below is expressed against."""

ORIGIN = MonotonicReading(0)
"""An arbitrary monotonic origin. Its value is meaningless; only differences are."""


def reading(millis: int) -> MonotonicReading:
    """A monotonic reading that many milliseconds after the origin."""
    return MonotonicReading(millis * NANOSECONDS_PER_MILLISECOND)


def beat(
    name: str = "feed",
    *,
    at: int = 0,
    sequence: int = 1,
    criticality: Criticality = Criticality.REQUIRED,
) -> ComponentBeat:
    """One component beat, spelled in milliseconds since the origin."""
    return ComponentBeat(name=name, criticality=criticality, sequence=sequence, at=reading(at))


def snapshot(*beats: ComponentBeat, at: int) -> HeartbeatSnapshot:
    """A snapshot taken that many milliseconds after the origin."""
    return HeartbeatSnapshot(taken_at=reading(at), beats=tuple(beats))


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------


def test_the_declared_defaults_describe_a_watchdog_that_could_run() -> None:
    """The defaults must satisfy the same rules an operator's values do."""
    policy = WatchdogPolicy()
    assert policy.interval() == Duration(DEFAULT_INTERVAL_MILLIS * NANOSECONDS_PER_MILLISECOND)
    assert policy.stall() == Duration(DEFAULT_STALL_MILLIS * NANOSECONDS_PER_MILLISECOND)
    assert policy.deadline() == Duration(
        (DEFAULT_STALL_MILLIS + DEFAULT_ESCALATE_MILLIS) * NANOSECONDS_PER_MILLISECOND
    )


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        pytest.param({"interval_millis": 0}, "interval_millis", id="interval-below-floor"),
        pytest.param({"interval_millis": 900_000}, "interval_millis", id="interval-above-ceiling"),
        pytest.param({"grace_millis": -1}, "grace_millis", id="negative-grace"),
        pytest.param({"stall_millis": 10}, "stall_millis", id="stall-below-floor"),
        pytest.param({"escalate_millis": 0}, "escalate_millis", id="escalate-below-floor"),
    ],
)
def test_a_value_outside_its_range_is_refused_by_name(
    overrides: dict[str, int], fragment: str
) -> None:
    """The operator needs to know which value, not merely that one was wrong."""
    with pytest.raises(ValidationError, match=fragment):
        WatchdogPolicy(**overrides)


def test_a_stall_threshold_at_the_poll_interval_is_refused() -> None:
    """Otherwise every component looks stalled the first time it is examined.

    A component checked one interval after beating has by definition been silent
    for one interval, so a threshold at or below the interval fires on every tick.
    No range check on either value alone would notice.
    """
    with pytest.raises(ValidationError, match="every examined component would look stalled"):
        WatchdogPolicy(interval_millis=5_000, stall_millis=5_000)


def test_an_escalation_grace_below_the_poll_interval_is_refused() -> None:
    """A deadline that expires between two ticks is whatever the next tick was."""
    with pytest.raises(ValidationError, match="the deadline would expire unobserved"):
        WatchdogPolicy(interval_millis=10_000, stall_millis=30_000, escalate_millis=1_000)


def test_every_problem_with_a_policy_is_reported_at_once() -> None:
    """Fixing one must not merely reveal the next."""
    with pytest.raises(ValidationError) as caught:
        WatchdogPolicy(interval_millis=0, grace_millis=-1)
    assert "interval_millis" in str(caught.value)
    assert "grace_millis" in str(caught.value)


# ---------------------------------------------------------------------------
# The value types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [pytest.param("", id="empty"), pytest.param("x" * (MAXIMUM_COMPONENT_NAME + 1), id="too-long")],
)
def test_a_component_name_that_could_not_be_published_is_refused(name: str) -> None:
    with pytest.raises(ValidationError, match="component name"):
        ComponentBeat(name=name, criticality=Criticality.REQUIRED, sequence=0, at=ORIGIN)


def test_a_negative_progress_sequence_is_refused() -> None:
    with pytest.raises(ValidationError, match="cannot be negative"):
        ComponentBeat(name="feed", criticality=Criticality.REQUIRED, sequence=-1, at=ORIGIN)


def test_a_snapshot_whose_beats_are_out_of_name_order_is_refused() -> None:
    """Order is what makes the published incident the same on every run."""
    with pytest.raises(ValidationError, match="ordered by name"):
        snapshot(beat("zulu"), beat("alpha"), at=10)


def test_a_snapshot_naming_one_component_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="appears twice"):
        snapshot(beat("feed"), beat("feed"), at=10)


def test_a_beat_later_than_its_own_snapshot_is_refused() -> None:
    """The race that would otherwise raise from inside the watchdog loop.

    ``MonotonicReading.since`` refuses to subtract in the wrong direction, so a beat
    landing while the snapshot was being copied would blow up intermittently and
    only under load. Refusing it here makes it one loud domain error instead.
    """
    with pytest.raises(ValidationError, match="later than the snapshot"):
        snapshot(beat("feed", at=50), at=10)


def test_the_quietest_required_component_is_chosen_and_ties_break_by_name() -> None:
    """A published record digested by a gate cannot depend on dictionary order."""
    taken = snapshot(beat("alpha", at=5), beat("zulu", at=5), at=100)
    quietest = taken.quietest()
    assert quietest is not None
    assert quietest.name == "alpha"


def test_an_advisory_component_is_never_the_quietest() -> None:
    """Its silence is a warning; it may not be the reason a process ends."""
    taken = snapshot(
        beat("advisory", at=0, criticality=Criticality.ADVISORY),
        beat("required", at=90),
        at=100,
    )
    quietest = taken.quietest()
    assert quietest is not None
    assert quietest.name == "required"


def test_a_snapshot_with_nothing_required_has_no_quietest() -> None:
    taken = snapshot(beat("advisory", at=0, criticality=Criticality.ADVISORY), at=100)
    assert taken.quietest() is None


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------


def test_no_settled_state_may_return_to_health() -> None:
    """The no-rollback rule, asserted as an absence rather than as a guard."""
    for state in WatchdogState:
        if settled(state):
            assert not may_move(state, WatchdogState.HEALTHY)


def test_exactly_one_edge_enters_the_stalled_state() -> None:
    """What makes one incident per episode a property of the graph."""
    inbound = [pair for pair in transitions() if pair[1] is WatchdogState.STALLED]
    assert inbound == [(WatchdogState.SUSPECT, WatchdogState.STALLED)]


def test_recovery_has_exactly_one_inbound_edge() -> None:
    inbound = [pair for pair in transitions() if pair[1] is WatchdogState.HEALTHY]
    assert inbound == [
        (WatchdogState.STARTING, WatchdogState.HEALTHY),
        (WatchdogState.SUSPECT, WatchdogState.HEALTHY),
    ]


def test_every_state_can_stand_down() -> None:
    """Stopping must work from wherever the watchdog happens to be."""
    for state in WatchdogState:
        assert may_move(state, WatchdogState.DISABLED)


def test_staying_put_is_always_permitted_and_is_not_an_edge() -> None:
    """Sixteen self-pairs in the table would serve no reader."""
    for state in WatchdogState:
        assert may_move(state, state)
        assert (state, state) not in transitions()


def test_no_transition_is_listed_twice() -> None:
    assert len(set(transitions())) == len(transitions())


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------


def test_a_disabled_watchdog_judges_nothing() -> None:
    outcome = decide(
        episode=WatchdogEpisode(),
        snapshot=snapshot(beat(at=0), at=10_000_000),
        policy=POLICY,
        since_start=Duration(0),
        enabled=False,
    )
    assert outcome == WatchdogDecision(state=WatchdogState.DISABLED, reason=REASON_DISABLED)


def test_nothing_is_judged_inside_the_start_up_grace() -> None:
    """A component that has not started yet has not stalled."""
    outcome = decide(
        episode=WatchdogEpisode(state=WatchdogState.STARTING),
        snapshot=snapshot(beat(at=0), at=999_999),
        policy=POLICY,
        since_start=Duration(POLICY.grace().nanoseconds - 1),
    )
    assert outcome.state is WatchdogState.STARTING
    assert outcome.reason == REASON_WITHIN_GRACE


def test_an_armed_watchdog_with_nothing_required_is_healthy_and_says_why() -> None:
    outcome = decide(
        episode=WatchdogEpisode(state=WatchdogState.STARTING),
        snapshot=snapshot(at=10_000),
        policy=POLICY,
        since_start=POLICY.grace(),
    )
    assert outcome.state is WatchdogState.HEALTHY
    assert outcome.reason == REASON_NOTHING_MONITORED


def test_a_component_beating_inside_the_interval_is_healthy() -> None:
    outcome = decide(
        episode=WatchdogEpisode(state=WatchdogState.HEALTHY),
        snapshot=snapshot(beat(at=10_000), at=10_500),
        policy=POLICY,
        since_start=Duration(10_500 * NANOSECONDS_PER_MILLISECOND),
    )
    assert outcome.state is WatchdogState.HEALTHY
    assert outcome.reason == REASON_OK


def test_a_missed_interval_is_suspect_and_does_not_act() -> None:
    """One warning. No incident, no evidence, no process ended."""
    outcome = decide(
        episode=WatchdogEpisode(state=WatchdogState.HEALTHY),
        snapshot=snapshot(beat(at=10_000), at=12_000),
        policy=POLICY,
        since_start=Duration(12_000 * NANOSECONDS_PER_MILLISECOND),
    )
    assert outcome.state is WatchdogState.SUSPECT
    assert outcome.action is WatchdogAction.NOTHING
    assert outcome.reason == REASON_BEAT_MISSED


def test_a_suspect_component_that_beats_again_recovers() -> None:
    """The one recovery edge, exercised."""
    outcome = decide(
        episode=WatchdogEpisode(state=WatchdogState.SUSPECT, component="feed"),
        snapshot=snapshot(beat(at=20_000, sequence=2), at=20_100),
        policy=POLICY,
        since_start=Duration(20_100 * NANOSECONDS_PER_MILLISECOND),
    )
    assert outcome.state is WatchdogState.HEALTHY
    assert may_move(WatchdogState.SUSPECT, outcome.state)


def test_crossing_the_stall_threshold_confirms_and_asks_for_evidence() -> None:
    outcome = decide(
        episode=WatchdogEpisode(state=WatchdogState.SUSPECT, component="feed"),
        snapshot=snapshot(beat(at=0), at=DEFAULT_STALL_MILLIS + 1),
        policy=POLICY,
        since_start=Duration((DEFAULT_STALL_MILLIS + 1) * NANOSECONDS_PER_MILLISECOND),
    )
    assert outcome.state is WatchdogState.STALLED
    assert outcome.action is WatchdogAction.CAPTURE_EVIDENCE
    assert outcome.reason == REASON_PROGRESS_STALLED
    assert outcome.component == "feed"


def test_the_stall_threshold_is_exclusive_at_its_own_boundary() -> None:
    """Exactly the threshold is not yet past it, and the boundary is asserted."""
    outcome = decide(
        episode=WatchdogEpisode(state=WatchdogState.SUSPECT, component="feed"),
        snapshot=snapshot(beat(at=0), at=DEFAULT_STALL_MILLIS),
        policy=POLICY,
        since_start=Duration(DEFAULT_STALL_MILLIS * NANOSECONDS_PER_MILLISECOND),
    )
    assert outcome.state is WatchdogState.SUSPECT


def test_a_late_beat_after_a_confirmed_stall_is_recorded_and_changes_nothing() -> None:
    """The rule the phase exists to get right.

    The component resumed, and the machine stays exactly where it was: the process
    has already published a record saying it stalled, and a run whose evidence
    claims a stall the same run then denies is worth nothing to an operator.
    """
    episode = WatchdogEpisode(
        state=WatchdogState.SHUTDOWN_REQUESTED,
        component="feed",
        sequence=7,
        began=reading(DEFAULT_STALL_MILLIS),
    )
    outcome = decide(
        episode=episode,
        snapshot=snapshot(
            beat(at=DEFAULT_STALL_MILLIS + 100, sequence=8), at=DEFAULT_STALL_MILLIS + 200
        ),
        policy=POLICY,
        since_start=Duration((DEFAULT_STALL_MILLIS + 200) * NANOSECONDS_PER_MILLISECOND),
    )
    assert outcome.state is WatchdogState.SHUTDOWN_REQUESTED
    assert outcome.action is WatchdogAction.NOTHING
    assert outcome.reason == REASON_LATE_PROGRESS


def test_the_escalation_deadline_is_measured_from_the_stall_not_from_the_request() -> None:
    """A slow evidence capture must not postpone the end of the process.

    The deadline is ``stall_millis + escalate_millis`` after the stall began, so it
    is a bound rather than an aspiration: whatever the watchdog was doing in
    between, a required component silent this long ends the run.
    """
    began = reading(DEFAULT_STALL_MILLIS)
    episode = WatchdogEpisode(
        state=WatchdogState.SHUTDOWN_REQUESTED, component="feed", sequence=1, began=began
    )
    past = DEFAULT_STALL_MILLIS + DEFAULT_STALL_MILLIS + DEFAULT_ESCALATE_MILLIS + 1
    outcome = decide(
        episode=episode,
        snapshot=snapshot(beat(at=0), at=past),
        policy=POLICY,
        since_start=Duration(past * NANOSECONDS_PER_MILLISECOND),
    )
    assert outcome.state is WatchdogState.ESCALATING
    assert outcome.action is WatchdogAction.TERMINATE
    assert outcome.reason == REASON_GRACE_EXPIRED


def test_the_deadline_does_not_fire_before_it_is_reached() -> None:
    began = reading(DEFAULT_STALL_MILLIS)
    episode = WatchdogEpisode(
        state=WatchdogState.SHUTDOWN_REQUESTED, component="feed", sequence=1, began=began
    )
    inside = DEFAULT_STALL_MILLIS + DEFAULT_STALL_MILLIS + DEFAULT_ESCALATE_MILLIS
    outcome = decide(
        episode=episode,
        snapshot=snapshot(beat(at=0), at=inside),
        policy=POLICY,
        since_start=Duration(inside * NANOSECONDS_PER_MILLISECOND),
    )
    assert outcome.state is WatchdogState.SHUTDOWN_REQUESTED
    assert outcome.action is WatchdogAction.NOTHING


def test_a_stalled_episode_never_terminates_before_shutdown_has_been_requested() -> None:
    """Asking comes first, always. The deadline only runs against a request."""
    episode = WatchdogEpisode(
        state=WatchdogState.STALLED, component="feed", sequence=1, began=reading(0)
    )
    outcome = decide(
        episode=episode,
        snapshot=snapshot(beat(at=0), at=10_000_000),
        policy=POLICY,
        since_start=Duration(10_000_000 * NANOSECONDS_PER_MILLISECOND),
    )
    assert outcome.action is not WatchdogAction.TERMINATE


# ---------------------------------------------------------------------------
# The published record
# ---------------------------------------------------------------------------


def incident(**overrides: object) -> StallIncident:
    """A well-formed incident, with whatever the caller wants changed."""
    fields: dict[str, object] = {
        "incident_id": "0123456789abcdef0123456789abcdef",
        "run_id": "fedcba9876543210fedcba9876543210",
        "correlation_id": "00112233445566778899aabbccddeeff",
        "detected_at": instant_from_epoch_millis(1_780_000_000_000),
        "component": "feed",
        "silent": Duration(DEFAULT_STALL_MILLIS * NANOSECONDS_PER_MILLISECOND),
        "sequence": 41,
    }
    fields.update(overrides)
    return StallIncident(**fields)  # type: ignore[arg-type]


def test_an_incident_redacts_its_own_details() -> None:
    """A record that can only be built safely beats one a caller must sanitise."""
    built = incident(details=(("api_key", "live-secret"), ("component", "feed")))
    assert dict(built.details)["api_key"] == "[redacted]"
    assert dict(built.details)["component"] == "feed"


def test_an_incident_naming_an_unknown_reason_is_refused() -> None:
    with pytest.raises(ValidationError, match="not one of this module"):
        incident(reason="WATCHDOG_MADE_UP")


def test_evidence_that_lost_a_collector_is_not_complete_and_still_exists() -> None:
    """Half a capture is the normal case when something is already wrong."""
    partial = StallEvidence(native_dump=True, problems=("frames could not be read",))
    assert partial.native_dump
    assert not partial.complete()


def test_evidence_with_nothing_wrong_is_complete() -> None:
    assert StallEvidence(native_dump=True).complete()


# ---------------------------------------------------------------------------
# The closed vocabularies
# ---------------------------------------------------------------------------


def test_the_reason_set_holds_no_duplicates() -> None:
    assert len(set(REASONS)) == len(REASONS)


def test_every_reason_is_prefixed_so_a_stray_string_is_visible() -> None:
    assert all(reason.startswith("WATCHDOG_") for reason in REASONS)


def test_every_event_name_is_spellable_as_a_log_event() -> None:
    """The alphabet ``LogEvent`` enforces is lower case, digits, dots and underscores."""
    permitted = set("abcdefghijklmnopqrstuvwxyz0123456789._")
    for name in WATCHDOG_EVENTS:
        assert set(name) <= permitted, name


def test_the_event_set_holds_no_duplicates() -> None:
    assert len(set(WATCHDOG_EVENTS)) == len(WATCHDOG_EVENTS)
