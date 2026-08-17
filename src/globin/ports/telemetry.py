"""The seams telemetry is reached through.

Two protocols over one object, narrowed by **audience** rather than by subject.
That is `ports/watchdog.py`'s arrangement and it is chosen for the same reason: a
component that records a measurement must be structurally unable to drain the
store, and whatever drains it must be structurally unable to record. Handing a
call site a :class:`MetricRecorder` and a snapshot builder a :class:`MetricSource`
makes that a property of the type rather than of anybody's discipline — and it is
what will break the reentrancy loop when an exporter arrives, because an exporter
holding only a source has no method that could enqueue.

Both are `Protocol`s satisfied structurally, so the application object that
implements them names neither. Nothing here performs I/O.
"""

from typing import Protocol, runtime_checkable

from globin.domain.metrics import DropCounts, MetricSnapshot


@runtime_checkable
class MetricRecorder(Protocol):
    """The recording half: what a component measuring itself is handed.

    Every method takes a **declared** metric name and the attributes that family
    declares. None of them raises: a telemetry call must never take down the code
    it is measuring, so a refused observation is dropped and counted instead.
    """

    def count(self, name: str, increment: int = 1, **attributes: str) -> None:
        """Advance a counter.

        Args:
            name: The declared metric name.
            increment: How much to add, never negative.
            attributes: Every attribute key the family declares.
        """
        ...

    def set_gauge(self, name: str, value: int, **attributes: str) -> None:
        """Set a gauge to an absolute value.

        Args:
            name: The declared metric name.
            value: The new value.
            attributes: Every attribute key the family declares.
        """
        ...

    def observe(self, name: str, value: int, **attributes: str) -> None:
        """Record one histogram observation.

        Args:
            name: The declared metric name.
            value: The observation, in the family's stored scale.
            attributes: Every attribute key the family declares.
        """
        ...


@runtime_checkable
class MetricSource(Protocol):
    """The reading half: what a snapshot builder or an exporter is handed.

    Deliberately has no way to record. An exporter that could record its own
    failures would close a loop — failure records a metric, which reaches the
    exporter, which fails — and this protocol is where that loop is made
    untypeable rather than merely avoided.
    """

    def families(self) -> tuple[MetricSnapshot, ...]:
        """Every family with at least one materialised series.

        Returns:
            The families, in registry order, each with its points in series-key
            order.
        """
        ...

    def drop_counts(self) -> DropCounts:
        """How many observations were refused, by the rule that refused them.

        Returns:
            The counts.
        """
        ...
