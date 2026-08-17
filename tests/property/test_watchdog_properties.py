"""The watchdog's invariants over generated input, rather than over chosen input.

The unit tests pick the cases a person thought of. These assert the properties
that must hold for *every* case, and the two that matter most are the ones a
hand-written test cannot reach: that :func:`decide` is **total** — no combination
of episode, snapshot, policy and elapsed time makes it raise — and that the state
it returns is always one the transition table permits.

That second property is what keeps the table and the function from drifting apart.
A table is a claim about the machine; a function is the machine. Comparing them
over generated input is the only way the claim stays true.
"""

from hypothesis import assume, given
from hypothesis import strategies as st

from globin.domain.clock import Duration, MonotonicReading
from globin.domain.watchdog import (
    MAXIMUM_COMPONENT_NAME,
    MAXIMUM_ESCALATE_MILLIS,
    MAXIMUM_GRACE_MILLIS,
    MAXIMUM_INTERVAL_MILLIS,
    MAXIMUM_STALL_MILLIS,
    MINIMUM_ESCALATE_MILLIS,
    MINIMUM_GRACE_MILLIS,
    MINIMUM_INTERVAL_MILLIS,
    MINIMUM_STALL_MILLIS,
    NANOSECONDS_PER_MILLISECOND,
    REASONS,
    ComponentBeat,
    Criticality,
    HeartbeatSnapshot,
    WatchdogEpisode,
    WatchdogPolicy,
    WatchdogState,
    decide,
    may_move,
    settled,
    transitions,
)
from globin.errors import ValidationError

NAMES = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),
    min_size=1,
    max_size=8,
)
"""Component names that are always constructible, so a refusal means something."""


@st.composite
def policies(draw: st.DrawFn) -> WatchdogPolicy:
    """A policy that satisfies every rule, built rather than filtered.

    Drawing the stall above the interval and the escalation at or above it means
    Hypothesis never has to reject a candidate, which keeps the search on the
    behaviour instead of on the constructor.
    """
    interval = draw(st.integers(MINIMUM_INTERVAL_MILLIS, MAXIMUM_INTERVAL_MILLIS))
    stall = draw(st.integers(max(MINIMUM_STALL_MILLIS, interval + 1), MAXIMUM_STALL_MILLIS))
    escalate = draw(st.integers(max(MINIMUM_ESCALATE_MILLIS, interval), MAXIMUM_ESCALATE_MILLIS))
    grace = draw(st.integers(MINIMUM_GRACE_MILLIS, MAXIMUM_GRACE_MILLIS))
    return WatchdogPolicy(
        interval_millis=interval,
        grace_millis=grace,
        stall_millis=stall,
        escalate_millis=escalate,
    )


@st.composite
def snapshots(draw: st.DrawFn) -> HeartbeatSnapshot:
    """A well-formed snapshot: ordered, unique, and never dated after its beats."""
    taken = draw(st.integers(0, 10_000_000))
    names = draw(st.lists(NAMES, min_size=0, max_size=5, unique=True))
    beats = [
        ComponentBeat(
            name=name,
            criticality=draw(st.sampled_from(Criticality)),
            sequence=draw(st.integers(0, 1_000)),
            at=MonotonicReading(draw(st.integers(0, taken)) * NANOSECONDS_PER_MILLISECOND),
        )
        for name in sorted(names)
    ]
    return HeartbeatSnapshot(
        taken_at=MonotonicReading(taken * NANOSECONDS_PER_MILLISECOND), beats=tuple(beats)
    )


@st.composite
def episodes(draw: st.DrawFn) -> WatchdogEpisode:
    """Any episode the machine could be in, including impossible-looking ones."""
    state = draw(st.sampled_from(WatchdogState))
    began = draw(st.integers(0, 10_000_000))
    return WatchdogEpisode(
        state=state,
        component=draw(st.one_of(st.just(""), NAMES)),
        sequence=draw(st.integers(0, 1_000)),
        began=MonotonicReading(began * NANOSECONDS_PER_MILLISECOND)
        if draw(st.booleans())
        else None,
    )


@given(
    episode=episodes(),
    snapshot=snapshots(),
    policy=policies(),
    elapsed=st.integers(0, 10_000_000),
    enabled=st.booleans(),
)
def test_deciding_is_total(
    episode: WatchdogEpisode,
    snapshot: HeartbeatSnapshot,
    policy: WatchdogPolicy,
    elapsed: int,
    enabled: bool,
) -> None:
    """No input makes the judgement raise.

    The watchdog's whole value is that it keeps running when the process does not.
    A ``decide`` that could raise would take the loop with it — and the loop is
    deliberately written to stop rather than retry, so one bad tick would remove
    the protection permanently.
    """
    outcome = decide(
        episode=episode,
        snapshot=snapshot,
        policy=policy,
        since_start=Duration(elapsed * NANOSECONDS_PER_MILLISECOND),
        enabled=enabled,
    )
    assert outcome.reason in REASONS


@given(
    episode=episodes(),
    snapshot=snapshots(),
    policy=policies(),
    elapsed=st.integers(0, 10_000_000),
)
def test_every_decision_lands_on_a_state_the_table_permits(
    episode: WatchdogEpisode,
    snapshot: HeartbeatSnapshot,
    policy: WatchdogPolicy,
    elapsed: int,
) -> None:
    """The table is a claim about the machine; this is what keeps it true.

    Either the tick stays put, or it moves along an edge :func:`transitions`
    declares. Nothing else is reachable, so a new branch in ``decide`` that forgot
    to add its pair fails here rather than in production.
    """
    outcome = decide(
        episode=episode,
        snapshot=snapshot,
        policy=policy,
        since_start=Duration(elapsed * NANOSECONDS_PER_MILLISECOND),
    )
    assert may_move(episode.state, outcome.state)


@given(
    episode=episodes(),
    snapshot=snapshots(),
    policy=policies(),
    elapsed=st.integers(0, 10_000_000),
)
def test_a_settled_episode_never_becomes_healthy_again(
    episode: WatchdogEpisode,
    snapshot: HeartbeatSnapshot,
    policy: WatchdogPolicy,
    elapsed: int,
) -> None:
    """The no-rollback rule, over every input rather than over one.

    A late beat, a recovered component and a quiet registry all reach this branch,
    and none of them may undo a stall the process has already published.
    """
    assume(settled(episode.state))
    outcome = decide(
        episode=episode,
        snapshot=snapshot,
        policy=policy,
        since_start=Duration(elapsed * NANOSECONDS_PER_MILLISECOND),
    )
    assert outcome.state is not WatchdogState.HEALTHY
    assert outcome.state is not WatchdogState.SUSPECT


@given(snapshot=snapshots())
def test_no_component_is_ever_silent_for_a_negative_time(
    snapshot: HeartbeatSnapshot,
) -> None:
    """``Duration`` refuses a negative value, so this asserts the subtraction order.

    A snapshot whose reading predated one of its beats would make
    ``MonotonicReading.since`` raise. The type refuses that combination on
    construction, and this is the property that refusal buys.
    """
    for beat in snapshot.beats:
        assert snapshot.silence_of(beat).nanoseconds >= 0


@given(snapshot=snapshots())
def test_the_quietest_required_component_is_the_one_silent_longest(
    snapshot: HeartbeatSnapshot,
) -> None:
    """And it is never an advisory one, whatever the advisory ones are doing."""
    quietest = snapshot.quietest()
    required = snapshot.required()
    if quietest is None:
        assert required == ()
        return
    assert quietest.criticality is Criticality.REQUIRED
    longest = max(snapshot.silence_of(beat).nanoseconds for beat in required)
    assert snapshot.silence_of(quietest).nanoseconds == longest


@given(
    interval=st.integers(-1_000, 200_000),
    grace=st.integers(-1_000, 1_000_000),
    stall=st.integers(-1_000, 5_000_000),
    escalate=st.integers(-1_000, 1_000_000),
)
def test_a_policy_either_validates_or_refuses_and_never_half_builds(
    interval: int, grace: int, stall: int, escalate: int
) -> None:
    """Fail closed: there is no partially valid policy for a caller to observe.

    Every rejection is a :class:`~globin.errors.ValidationError`, never a
    ``TypeError`` from arithmetic on a value that should not have got that far.
    """
    try:
        policy = WatchdogPolicy(
            interval_millis=interval,
            grace_millis=grace,
            stall_millis=stall,
            escalate_millis=escalate,
        )
    except ValidationError:
        return
    assert policy.stall_millis > policy.interval_millis
    assert policy.escalate_millis >= policy.interval_millis
    assert policy.deadline().nanoseconds > policy.stall().nanoseconds


@given(name=NAMES, sequence=st.integers(0, 10_000), at=st.integers(0, 10_000_000))
def test_a_beat_that_constructs_carries_exactly_what_it_was_given(
    name: str, sequence: int, at: int
) -> None:
    """Immutability, asserted rather than assumed: nothing is normalised in transit."""
    reading = MonotonicReading(at * NANOSECONDS_PER_MILLISECOND)
    beat = ComponentBeat(name=name, criticality=Criticality.REQUIRED, sequence=sequence, at=reading)
    assert beat.name == name
    assert beat.sequence == sequence
    assert beat.at == reading
    assert len(beat.name) <= MAXIMUM_COMPONENT_NAME


def test_the_only_backwards_edge_is_the_recovery_one() -> None:
    """Not a property test, and it lives here because it is about the whole graph.

    The machine moves forwards with exactly one exception, and the exception is
    the point: ``suspect → healthy`` is how a component that missed one interval
    gets forgiven. Every other backwards edge would be a way to revisit ``stalled``
    and raise a second incident for one episode, which is the guarantee the graph
    exists to provide.
    """
    order = list(WatchdogState)
    backwards = [
        (source, target)
        for source, target in transitions()
        if target is not WatchdogState.DISABLED and order.index(target) <= order.index(source)
    ]
    assert backwards == [(WatchdogState.SUSPECT, WatchdogState.HEALTHY)]
