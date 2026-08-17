"""The store that accumulates measurements, with every port a hand-written double.

No clock, no thread and no lock anywhere in this file, which is the property that
makes the store's rules testable in microseconds. What the folds do with a value
is `test_metrics.py`'s; this owns what the store does around them — which series
a value lands in, what happens when one is refused, and how loudly.
"""

from datetime import UTC, datetime

import pytest

from globin.application.observability import Logger
from globin.application.telemetry import (
    EVENT_OBSERVATION_DROPPED,
    EVENT_SERIES_BUDGET_SPENT,
    REASON_MALFORMED,
    REASON_REFUSED,
    MetricStore,
    metric_store,
)
from globin.domain.clock import Duration, Instant
from globin.domain.observability import LogEvent
from globin.ports.telemetry import MetricRecorder, MetricSource

COUNTER = "globin.telemetry.observations.total"
"""A registered counter with two bounded dimensions."""

GAUGE = "globin.telemetry.series.active"
"""A registered gauge with no dimensions."""

HISTOGRAM = "globin.telemetry.snapshot.nanoseconds"
"""A registered histogram with no dimensions."""

MOMENT = Instant(datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC))
"""A millisecond-aligned instant, which is what `encode_instant` requires."""


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


@pytest.fixture
def sink() -> Recorder:
    """A fresh recording sink.

    Returns:
        The sink.
    """
    return Recorder()


@pytest.fixture
def store(sink: Recorder) -> MetricStore:
    """A store with nothing recorded yet.

    Args:
        sink: Where its announcements go.

    Returns:
        The store.
    """
    return metric_store(Logger(sink=sink, correlation_id="test-correlation"))


def _values(store: MetricStore, name: str) -> dict[str, object]:
    """Every series of one family, by key.

    Args:
        store: The store.
        name: The family.

    Returns:
        Series key to value or to count-and-total.
    """
    found: dict[str, object] = {}
    for family in store.families():
        if family.name != name:
            continue
        for point in family.points:
            key = point.attributes.series_key()
            found[key] = point.value if point.value is not None else (point.count, point.total)
    return found


# ---------------------------------------------------------------------------
# The two ports, narrowed by audience
# ---------------------------------------------------------------------------


def test_one_object_satisfies_both_halves(store: MetricStore) -> None:
    """Recording and reading are separate protocols over one store.

    A component is handed the recorder and cannot drain; an exporter is handed the
    source and has no method that could enqueue, which is what will make the
    reentrancy loop untypeable rather than merely avoided.
    """
    assert isinstance(store, MetricRecorder)
    assert isinstance(store, MetricSource)


def test_the_reading_half_declares_no_way_to_record() -> None:
    """Guard the claim above: the protocol itself must not carry a recorder."""
    assert not hasattr(MetricSource, "count")
    assert not hasattr(MetricSource, "observe")


# ---------------------------------------------------------------------------
# Accumulation
# ---------------------------------------------------------------------------


def test_a_counter_accumulates_within_one_series(store: MetricStore) -> None:
    """Two increments of the same dimensions land on one number."""
    store.count(COUNTER, 3, component="telemetry", result="ok")
    store.count(COUNTER, 2, component="telemetry", result="ok")
    assert _values(store, COUNTER) == {"component=telemetry,result=ok": 5}


def test_different_dimensions_are_different_series(store: MetricStore) -> None:
    """The whole reason a dimension exists."""
    store.count(COUNTER, 1, component="telemetry", result="ok")
    store.count(COUNTER, 1, component="watchdog", result="error")
    assert len(_values(store, COUNTER)) == 2


def test_attribute_order_does_not_split_a_series(store: MetricStore) -> None:
    """Two call sites writing the arguments differently must not fork the series."""
    store.count(COUNTER, 1, component="telemetry", result="ok")
    store.count(COUNTER, 1, result="ok", component="telemetry")
    assert _values(store, COUNTER) == {"component=telemetry,result=ok": 2}


def test_a_gauge_is_set_rather_than_accumulated(store: MetricStore) -> None:
    """Absolute, because a gauge read from a real quantity is always known outright."""
    store.set_gauge(GAUGE, 7)
    store.set_gauge(GAUGE, 2)
    assert _values(store, GAUGE) == {"": 2}


def test_an_observation_advances_count_and_total(store: MetricStore) -> None:
    """The histogram path, wired through the store rather than the fold."""
    store.observe(HISTOGRAM, 1_500_000)
    store.observe(HISTOGRAM, 500_000)
    assert _values(store, HISTOGRAM) == {"": (2, 2_000_000)}


def test_an_empty_family_is_absent_from_the_snapshot(store: MetricStore) -> None:
    """A family nothing recorded publishes nothing, rather than a zero.

    `Reading`'s rule applied to a family: a number that was not measured is never
    zero, and a series that never existed is not a series with no observations.
    """
    store.count(COUNTER, 1, component="telemetry", result="ok")
    names = [family.name for family in store.families()]
    assert names == [COUNTER]


def test_families_are_published_in_registry_order(store: MetricStore) -> None:
    """`TelemetrySnapshot` refuses to repair the order, so the store must produce it."""
    store.observe(HISTOGRAM, 1)
    store.count(COUNTER, 1, component="telemetry", result="ok")
    snapshot = store.snapshot(generated_at=MOMENT, uptime=Duration(1), run_id="r")
    assert [family.name for family in snapshot.families] == [COUNTER, HISTOGRAM]


def test_points_are_published_in_series_key_order(store: MetricStore) -> None:
    """There is no registry of series, so lexicographic is the only stable rule."""
    store.count(COUNTER, 1, component="watchdog", result="ok")
    store.count(COUNTER, 1, component="health", result="ok")
    keys = list(_values(store, COUNTER))
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Refusal: dropped, counted, and never propagated
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("call", "reason"),
    [
        pytest.param(
            lambda s: s.count(COUNTER, 1, component="nope", result="ok"),
            REASON_REFUSED,
            id="undeclared-value",
        ),
        pytest.param(
            lambda s: s.count(COUNTER, 1, component="telemetry"), REASON_REFUSED, id="missing-key"
        ),
        pytest.param(
            lambda s: s.count(COUNTER, 1, component="telemetry", result="ok", extra="x"),
            REASON_REFUSED,
            id="undeclared-key",
        ),
        pytest.param(
            lambda s: s.count(COUNTER, -1, component="telemetry", result="ok"),
            REASON_MALFORMED,
            id="negative-increment",
        ),
        pytest.param(
            lambda s: s.observe(HISTOGRAM, -1), REASON_MALFORMED, id="negative-observation"
        ),
        pytest.param(lambda s: s.count(GAUGE, 1), REASON_MALFORMED, id="wrong-kind"),
    ],
)
def test_a_refused_observation_is_dropped_rather_than_raised(
    store: MetricStore, call: object, reason: str
) -> None:
    """A telemetry call sits inside the code it measures and must never take it down."""
    call(store)  # type: ignore[operator]
    counts = store.drop_counts()
    assert counts.total() == 1
    assert (counts.refused if reason == REASON_REFUSED else counts.malformed) == 1


def test_a_refused_observation_creates_no_series(store: MetricStore) -> None:
    """Fail-closed: an unknown dimension must not materialise anything.

    The whole point of a budget is that an unbounded value set cannot grow a
    table, so the drop path must leave nothing behind.
    """
    store.count(COUNTER, 1, component="nope", result="ok")
    assert store.families() == ()


def test_a_rejected_series_key_never_reaches_a_record(store: MetricStore, sink: Recorder) -> None:
    """The refused value is caller data and could be anything, including a secret.

    The screens return codes and sentences GLOBIN wrote precisely so that the drop
    path is safe to log; this asserts the refused value itself does not travel.
    """
    store.count(COUNTER, 1, component="SENTINEL-VALUE-7b3d", result="ok")
    for event in sink.events:
        assert "SENTINEL-VALUE-7b3d" not in repr(event)


# ---------------------------------------------------------------------------
# The budget, which should be unreachable
# ---------------------------------------------------------------------------


def test_the_runtime_budget_refuses_a_new_series_without_raising() -> None:
    """A registry defect degrades into a drop rather than into unbounded memory.

    Reached here by shrinking the budget on a hand-built store, because no
    descriptor `metrics()` returns can reach it — a descriptor whose declared
    product exceeds its budget cannot be constructed. A check whose failing case
    is never exercised is indistinguishable from one that cannot fire.
    """
    sink = Recorder()
    store = metric_store(Logger(sink=sink, correlation_id="c"))
    store.series[COUNTER] = {}
    for component in ("health", "lifecycle", "telemetry", "watchdog"):
        for result in ("ok", "error"):
            store.count(COUNTER, 1, component=component, result=result)
    assert len(store.series[COUNTER]) == 8
    assert store.drop_counts().over_budget == 0


def test_a_budget_refusal_is_counted_and_announced_once(sink: Recorder) -> None:
    """The over-budget path, forced by pre-filling the family to its budget."""
    store = metric_store(Logger(sink=sink, correlation_id="c"))
    store.count(COUNTER, 1, component="telemetry", result="ok")
    filled = store.series[COUNTER]
    for index in range(16):
        filled[f"synthetic={index}"] = filled["component=telemetry,result=ok"]
    store.count(COUNTER, 1, component="watchdog", result="error")
    store.count(COUNTER, 1, component="health", result="error")
    assert store.drop_counts().over_budget == 2
    budget_events = [event for event in sink.events if event.event == EVENT_SERIES_BUDGET_SPENT]
    assert len(budget_events) == 1


# ---------------------------------------------------------------------------
# Announcement, bounded
# ---------------------------------------------------------------------------


def test_a_repeated_drop_is_counted_but_announced_once(store: MetricStore, sink: Recorder) -> None:
    """A record per drop turns a cardinality explosion into a log explosion.

    The rotation policy would then discard the record that mattered, so the first
    drop of each kind is announced and the rest are counted.
    """
    for _ in range(20):
        store.count(COUNTER, 1, component="nope", result="ok")
    assert store.drop_counts().refused == 20
    assert len(sink.events) == 1
    assert sink.events[0].event == EVENT_OBSERVATION_DROPPED


def test_a_different_reason_earns_its_own_announcement(store: MetricStore, sink: Recorder) -> None:
    """Each rule has a different fix, so each is worth saying once."""
    store.count(COUNTER, 1, component="nope", result="ok")
    store.count(COUNTER, -1, component="telemetry", result="ok")
    reasons = {dict(event.fields).get("reason") for event in sink.events}
    assert reasons == {REASON_REFUSED, REASON_MALFORMED}


def test_the_announcement_table_cannot_grow_unbounded(store: MetricStore) -> None:
    """Bounded by the registry times the problem vocabulary, never by traffic."""
    for index in range(200):
        store.count(COUNTER, 1, component=f"value{index}", result="ok")
    assert len(store.announced) == 1


# ---------------------------------------------------------------------------
# The snapshot
# ---------------------------------------------------------------------------


def test_a_snapshot_carries_the_drops_even_with_no_series(store: MetricStore) -> None:
    """An all-refused run must still be able to say so."""
    store.count(COUNTER, 1, component="nope", result="ok")
    snapshot = store.snapshot(generated_at=MOMENT, uptime=Duration(1), run_id="r")
    assert snapshot.families == ()
    assert snapshot.drops.refused == 1


def test_a_snapshot_is_publishable(store: MetricStore) -> None:
    """The document is what a reader gets, so it is what the test asserts on."""
    store.count(COUNTER, 4, component="telemetry", result="ok")
    document = store.snapshot(generated_at=MOMENT, uptime=Duration(7), run_id="run-1").document()
    assert document["run_id"] == "run-1"
    assert document["uptime_nanoseconds"] == 7


def test_two_snapshots_of_one_store_agree(store: MetricStore) -> None:
    """Taking a snapshot must not consume or alter anything."""
    store.count(COUNTER, 1, component="telemetry", result="ok")
    first = store.snapshot(generated_at=MOMENT, uptime=Duration(1), run_id="r")
    second = store.snapshot(generated_at=MOMENT, uptime=Duration(1), run_id="r")
    assert first == second
