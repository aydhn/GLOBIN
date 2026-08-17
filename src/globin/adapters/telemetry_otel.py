"""The only module in GLOBIN that may name `opentelemetry`.

`system_process_probe` is the template, and the reason is the same: the CI
`quality` job installs the toolchain with plain `pip` and never builds `.venv`, so
these packages are **absent on every CI run**. The import therefore sits inside a
function, the absence returns a recording object rather than raising, and
`tests/architecture/test_library_discipline.py` enforces the single site on the
real import graph.

**GLOBIN's names are mapped, never mutated.** The canonical `globin.*` spelling is
what the domain declares and it reaches an exporter unchanged; where a provider
needs a different one, it is *declared beside* the canonical name in a table a
reviewer can read. A derived mapping would silently merge two distinct series the
first time two names normalised to one, and the merge would be invisible in the
code, invisible in the diff, and visible only as a wrong number on a dashboard.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from globin.domain.metrics import MetricDescriptor, metrics
from globin.domain.telemetry import MetricKind, unit_specification
from globin.domain.telemetry_delivery import ExportOutcome

REASON_OTEL_ABSENT: str = "OTEL_LIBRARY_ABSENT"
"""No OpenTelemetry package is installed on this host."""

REASON_OTEL_PRESENT: str = "OTEL_LIBRARY_PRESENT"
"""The API is importable and a meter can be obtained."""


def otel_instrument_name(descriptor: MetricDescriptor) -> str:
    """The OpenTelemetry name for one family.

    Args:
        descriptor: The family.

    Returns:
        Its canonical GLOBIN name, unchanged.

    Identical by design rather than by accident: OpenTelemetry permits dots and
    lowercase, so there is nothing to translate, and *saying so in a function* is
    what keeps the two from silently diverging when somebody edits one.
    """
    return descriptor.name


def otel_unit(descriptor: MetricDescriptor) -> str:
    """The UCUM unit an OpenTelemetry instrument declares.

    Args:
        descriptor: The family.

    Returns:
        The unit's exporter spelling.
    """
    return unit_specification(descriptor.unit).exporter_name


def otel_mapping() -> tuple[tuple[str, str, str, str], ...]:
    """Every family, as an OpenTelemetry instrument would be declared.

    Returns:
        Tuples of ``(globin name, otel name, instrument kind, unit)``.

    A function returning literals derived from the registry, so a contract test can
    compare it against `metrics()` in both directions without importing the
    library. That is what lets the mapping be checked on a machine that has no
    OpenTelemetry installed, which is every CI run.
    """
    kinds = {
        MetricKind.COUNTER: "counter",
        MetricKind.GAUGE: "observable_gauge",
        MetricKind.HISTOGRAM: "histogram",
    }
    return tuple(
        (
            descriptor.name,
            otel_instrument_name(descriptor),
            kinds[descriptor.kind],
            otel_unit(descriptor),
        )
        for descriptor in metrics()
    )


@dataclass(frozen=True, slots=True)
class UnavailableOpenTelemetry:
    """What stands in when the library is not installed.

    Records the absence rather than raising, which is ADR-0045's rule applied to a
    library instead of a device: an absence is a state, and a state is reportable.
    """

    reason: str = REASON_OTEL_ABSENT

    @property
    def available(self) -> bool:
        """Whether the library is present.

        Returns:
            Always ``False``.
        """
        return False

    def offer(self, batch: Sequence[dict[str, object]]) -> ExportOutcome:
        """Refuse permanently, since an absent library will not appear.

        Args:
            batch: Ignored.

        Returns:
            Always a permanent failure.
        """
        del batch
        return ExportOutcome.PERMANENT_FAILURE

    def close(self) -> None:
        """Release nothing."""


@dataclass(slots=True)
class OpenTelemetryBridge:
    """Publishes GLOBIN snapshots onto OpenTelemetry instruments.

    Args:
        meter: The provider's meter, held as `Any` because the library's own types
            may not be importable where this is typed.
        instruments: Instruments already created, by GLOBIN name.
        reason: Why this bridge exists in the state it does.

    **The API alone is a no-op unless an SDK is installed**, and that is what makes
    "no socket in a default bootstrap" structural rather than configured. GLOBIN
    publishes through the API; whoever embeds GLOBIN installs an SDK and owns the
    network decision.
    """

    meter: Any
    instruments: dict[str, Any]
    reason: str = REASON_OTEL_PRESENT

    @property
    def available(self) -> bool:
        """Whether the library is present.

        Returns:
            Always ``True``.
        """
        return True

    def offer(self, batch: Sequence[dict[str, object]]) -> ExportOutcome:
        """Record every counter and histogram in a batch of snapshots.

        Args:
            batch: Telemetry snapshot documents.

        Returns:
            What happened. Never raises: a provider that throws must not end the
            run it was measuring.
        """
        try:
            for document in batch:
                self._record(document)
        except Exception:
            return ExportOutcome.TEMPORARY_FAILURE
        return ExportOutcome.DELIVERED

    def _record(self, document: dict[str, object]) -> None:
        """Publish one snapshot document.

        Args:
            document: The snapshot.
        """
        families = document.get("families")
        if not isinstance(families, list):
            return
        for family in families:
            if isinstance(family, dict):
                self._family(family)

    def _family(self, family: dict[str, object]) -> None:
        """Publish one family's points.

        Args:
            family: The family document.
        """
        name = family.get("name")
        kind = family.get("kind")
        points = family.get("points")
        if not isinstance(name, str) or not isinstance(points, list):
            return
        instrument = self.instruments.get(name)
        if instrument is None:
            return
        for point in points:
            if not isinstance(point, dict):
                continue
            if kind == MetricKind.COUNTER.value and isinstance(point.get("value"), int):
                instrument.add(point["value"])
            elif kind == MetricKind.HISTOGRAM.value and isinstance(point.get("total"), int):
                instrument.record(point["total"])

    def close(self) -> None:
        """Release nothing. The provider owns its own lifecycle."""


def opentelemetry_bridge() -> UnavailableOpenTelemetry | OpenTelemetryBridge:
    """The bridge, or a recorded absence.

    Returns:
        A working bridge when the library is importable, and an object that says
        why when it is not.

    The import is **inside the function**, which is the whole point: at module
    scope, a machine without the library could not import this module at all, and
    every layer above would have to know that. `system_process_probe`'s docstring
    calls that the worst shape a dependency can have.
    """
    try:
        from opentelemetry import metrics as otel_metrics
    except ImportError:
        return UnavailableOpenTelemetry()
    meter = otel_metrics.get_meter("globin")
    instruments: dict[str, Any] = {}
    for descriptor in metrics():
        unit = otel_unit(descriptor)
        if descriptor.kind is MetricKind.COUNTER:
            instruments[descriptor.name] = meter.create_counter(
                otel_instrument_name(descriptor), unit=unit, description=descriptor.description
            )
        elif descriptor.kind is MetricKind.HISTOGRAM:
            instruments[descriptor.name] = meter.create_histogram(
                otel_instrument_name(descriptor), unit=unit, description=descriptor.description
            )
    return OpenTelemetryBridge(meter=meter, instruments=instruments)
