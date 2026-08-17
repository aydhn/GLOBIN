"""The three things that had to live in an adapter, each tested for its reason.

A file that can fail, a thread that must be joinable, and two provider bridges
that must be absent without breaking anything. No socket is opened anywhere in
this file, and the offline guard would fail it if one were.
"""

import threading
from pathlib import Path

import pytest

from globin.adapters.telemetry import (
    DisabledExporter,
    LocalFileExporter,
    TelemetryThread,
    append_stream,
    render_line,
    telemetry_thread,
)
from globin.adapters.telemetry_otel import (
    REASON_OTEL_ABSENT,
    OpenTelemetryBridge,
    UnavailableOpenTelemetry,
    opentelemetry_bridge,
    otel_mapping,
)
from globin.adapters.telemetry_prometheus import (
    LOOPBACK_ADDRESS,
    MAXIMUM_PORT,
    MINIMUM_PORT,
    PrometheusPublisher,
    UnavailablePrometheus,
    port_problems,
    prometheus_mapping,
    prometheus_publisher,
    render_exposition,
    start_loopback_listener,
)
from globin.application.observability import Logger
from globin.application.telemetry_delivery import telemetry_pump
from globin.domain.clock import MonotonicReading
from globin.domain.metrics import metric_names
from globin.domain.observability import LogEvent
from globin.domain.telemetry_delivery import ExportOutcome, ExportPolicy


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


class Refusing:
    """A stream that fails the way a full disk does."""

    def write(self, text: str) -> int:
        """Refuse to write.

        Args:
            text: Ignored.

        Raises:
            OSError: Always.
        """
        del text
        message = "no space left on device"
        raise OSError(message)

    def flush(self) -> None:
        """Do nothing."""

    def close(self) -> None:
        """Do nothing."""


# ---------------------------------------------------------------------------
# The local exporter, which is what makes the state machine reachable
# ---------------------------------------------------------------------------


def test_a_batch_is_appended_as_json_lines(tmp_path: Path) -> None:
    """The ordinary path, against a real file."""
    destination = tmp_path / "logs" / "telemetry.ndjson"
    exporter = LocalFileExporter(
        open_stream=append_stream(
            destination, lambda parent: parent.mkdir(parents=True, exist_ok=True)
        ),
        render=render_line,
    )
    assert exporter.offer([{"n": 1}, {"n": 2}]) is ExportOutcome.DELIVERED
    exporter.close()
    assert destination.read_text(encoding="utf-8").splitlines() == ['{"n":1}', '{"n":2}']


def test_a_failing_write_is_temporary(tmp_path: Path) -> None:
    """A full disk may not be full a minute later, so the failure is retryable."""
    del tmp_path
    exporter = LocalFileExporter(open_stream=lambda: Refusing(), render=render_line)  # type: ignore[arg-type,return-value]
    assert exporter.offer([{"n": 1}]) is ExportOutcome.TEMPORARY_FAILURE


def test_writing_after_close_is_permanent(tmp_path: Path) -> None:
    """Nothing about a closed exporter will change, so retrying is pointless."""
    exporter = LocalFileExporter(
        open_stream=append_stream(
            tmp_path / "x.ndjson", lambda p: p.mkdir(parents=True, exist_ok=True)
        ),
        render=render_line,
    )
    exporter.close()
    assert exporter.offer([{"n": 1}]) is ExportOutcome.PERMANENT_FAILURE


def test_closing_twice_is_harmless(tmp_path: Path) -> None:
    """Idempotent, because shutdown paths call it more than once."""
    exporter = LocalFileExporter(
        open_stream=append_stream(
            tmp_path / "x.ndjson", lambda p: p.mkdir(parents=True, exist_ok=True)
        ),
        render=render_line,
    )
    exporter.close()
    exporter.close()
    assert exporter.closed


def test_a_line_refuses_a_value_json_cannot_hold() -> None:
    """`allow_nan=False` turns a silent `NaN` into a refusal.

    A `NaN` written into a telemetry stream is a number every reader parses and
    none can compare, which is the corruption the float ban exists to prevent.
    """
    with pytest.raises(ValueError, match="Out of range"):
        render_line({"n": float("nan")})


def test_a_disabled_exporter_refuses_permanently() -> None:
    """An absent library will not appear, so retrying it forever is wrong."""
    assert DisabledExporter(reason="absent").offer([{"n": 1}]) is ExportOutcome.PERMANENT_FAILURE


# ---------------------------------------------------------------------------
# The thread
# ---------------------------------------------------------------------------


def _thread(spawned: list[dict[str, object]]) -> TelemetryThread:
    """A thread wrapper whose spawn records rather than starts.

    Args:
        spawned: Where the arguments are recorded.

    Returns:
        The wrapper.
    """
    sink = Recorder()
    pump = telemetry_pump(
        exporter=DisabledExporter(reason="none"),
        policy=ExportPolicy(),
        logger=Logger(sink=sink, correlation_id="c"),
    )
    wrapper = telemetry_thread(
        pump=pump,
        interval_seconds=0.01,
        monotonic=lambda: MonotonicReading(1),
        logger=Logger(sink=sink, correlation_id="c"),
    )

    class Fake:
        """A thread that records its arguments and never runs."""

        def __init__(self, **kwargs: object) -> None:
            spawned.append(kwargs)

        def start(self) -> None:
            """Do nothing."""

        def join(self, timeout: float | None = None) -> None:
            """Do nothing."""
            del timeout

        def is_alive(self) -> bool:
            """Report finished.

            Returns:
                Always ``False``.
            """
            return False

    wrapper.spawn = Fake  # type: ignore[assignment]
    return wrapper


def test_the_thread_is_named_and_not_a_daemon() -> None:
    """The interpreter kills a daemon without unwinding.

    A daemon part-way through an export during teardown is undefined behaviour, so
    non-daemon means a forgotten stop hangs the suite loudly rather than corrupting
    a file quietly.
    """
    spawned: list[dict[str, object]] = []
    _thread(spawned).start()
    assert spawned[0]["daemon"] is False
    assert spawned[0]["name"] == "globin-telemetry"


def test_starting_twice_starts_one_thread() -> None:
    """Idempotent, because a caller cannot always know what already ran."""
    spawned: list[dict[str, object]] = []
    wrapper = _thread(spawned)
    wrapper.start()
    wrapper.start()
    assert len(spawned) == 1


def test_stopping_disarms_before_it_waits() -> None:
    """A loop that never notices the event is harmless once the pump is disarmed.

    `WatchdogThread.stop`'s ordering rule, and it matters more than the wait's
    bound does.
    """
    spawned: list[dict[str, object]] = []
    wrapper = _thread(spawned)
    wrapper.start()
    assert wrapper.stop()
    assert wrapper.pump.episode.state.value == "disabled"


def test_stopping_a_thread_that_never_started_is_harmless() -> None:
    """Shutdown runs whatever the application did."""
    spawned: list[dict[str, object]] = []
    assert _thread(spawned).stop()


def test_a_real_thread_starts_and_joins() -> None:
    """One test uses a real thread, because the wrapper's whole job is to own one.

    Bounded and joined in the same test, so a broken stop hangs here rather than
    leaking into the rest of the suite.
    """
    sink = Recorder()
    pump = telemetry_pump(
        exporter=DisabledExporter(reason="none"),
        policy=ExportPolicy(flush_interval_millis=100),
        logger=Logger(sink=sink, correlation_id="c"),
    )
    wrapper = TelemetryThread(
        pump=pump,
        wake=threading.Event(),
        interval_seconds=0.01,
        monotonic=lambda: MonotonicReading(1),
        logger=Logger(sink=sink, correlation_id="c"),
        join_seconds=2.0,
    )
    wrapper.start()
    assert wrapper.stop()
    assert wrapper.thread is None


# ---------------------------------------------------------------------------
# The provider bridges: absent without breaking anything
# ---------------------------------------------------------------------------


def test_an_absent_opentelemetry_records_rather_than_raises() -> None:
    """ADR-0045's rule applied to a library instead of a device."""
    absent = UnavailableOpenTelemetry()
    assert not absent.available
    assert absent.reason == REASON_OTEL_ABSENT
    assert absent.offer([{"n": 1}]) is ExportOutcome.PERMANENT_FAILURE


def test_an_absent_prometheus_records_rather_than_raises() -> None:
    """The same shape, because the same thing is true of it."""
    absent = UnavailablePrometheus()
    assert not absent.available
    assert absent.offer([{"n": 1}]) is ExportOutcome.PERMANENT_FAILURE


def test_the_factories_return_something_usable_either_way() -> None:
    """Whether the library is here or not, the caller gets an object with a state."""
    for built in (opentelemetry_bridge(), prometheus_publisher()):
        assert isinstance(built.available, bool)
        assert built.reason


def test_a_publisher_binds_nothing_by_default() -> None:
    """A default bootstrap opens no socket, by construction rather than by branch."""
    publisher = prometheus_publisher()
    assert getattr(publisher, "listening", False) is False


@pytest.mark.parametrize(
    "port",
    [
        pytest.param(0, id="zero"),
        pytest.param(80, id="privileged"),
        pytest.param(MINIMUM_PORT - 1, id="just-below"),
        pytest.param(MAXIMUM_PORT + 1, id="above-range"),
        pytest.param(True, id="bool"),
    ],
)
def test_an_unusable_listener_port_is_reported(port: int) -> None:
    """Validated before anything binds, because binding is the irreversible part."""
    assert port_problems(port)


def test_a_usable_port_has_no_problems() -> None:
    """The positive case."""
    assert port_problems(9_464) == ()


def test_the_loopback_address_is_the_only_one_declared() -> None:
    """The library's own default is `0.0.0.0`, which is every interface.

    GLOBIN declares one address as a constant and exposes no setting that could
    widen it, so the absence of an address parameter is the security posture.
    """
    assert LOOPBACK_ADDRESS == "127.0.0.1"


# ---------------------------------------------------------------------------
# Exposition rendering, which needs no library at all
# ---------------------------------------------------------------------------


def test_a_counter_renders_with_its_labels() -> None:
    """The textfile route works with no library installed.

    An operator's node_exporter reads a file, and requiring a dependency to produce
    one would make the simplest deployment the most fragile.
    """
    document: dict[str, object] = {
        "families": [
            {
                "name": "globin.telemetry.observations.total",
                "kind": "counter",
                "points": [{"series": "component=telemetry,result=ok", "value": 5}],
            }
        ]
    }
    text = render_exposition(document)
    assert "# TYPE globin_telemetry_observations_total counter" in text
    assert 'globin_telemetry_observations_total{component="telemetry",result="ok"} 5' in text


def test_a_histogram_renders_count_and_sum() -> None:
    """What Prometheus expects of a histogram it did not compute buckets for."""
    document: dict[str, object] = {
        "families": [
            {
                "name": "globin.telemetry.snapshot.nanoseconds",
                "kind": "histogram",
                "points": [{"series": "", "count": 2, "total": 900}],
            }
        ]
    }
    text = render_exposition(document)
    assert "globin_telemetry_snapshot_nanoseconds_count 2" in text
    assert "globin_telemetry_snapshot_nanoseconds_sum 900" in text


def test_an_unregistered_family_renders_nothing() -> None:
    """The mapping is a declaration, so a name outside it is not exportable."""
    document: dict[str, object] = {
        "families": [{"name": "globin.invented.total", "kind": "counter", "points": []}]
    }
    assert render_exposition(document) == ""


def test_both_mappings_cover_the_registry_in_both_directions() -> None:
    """A metric with no mapping is unexportable; a mapping for none is a fiction."""
    for mapping in (otel_mapping(), prometheus_mapping()):
        assert tuple(row[0] for row in mapping) == metric_names()


# ---------------------------------------------------------------------------
# The bridges, driven with fake instruments so no provider is required
# ---------------------------------------------------------------------------


class Instrument:
    """An instrument that records what it was asked to publish."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.added: list[int] = []
        self.recorded: list[int] = []

    def add(self, value: int) -> None:
        """Advance a counter.

        Args:
            value: The increment.
        """
        self.added.append(value)

    def record(self, value: int) -> None:
        """Record an observation.

        Args:
            value: The observation.
        """
        self.recorded.append(value)


class Breaking(Instrument):
    """An instrument that throws, the way a misconfigured provider does."""

    def add(self, value: int) -> None:
        """Raise instead of recording.

        Args:
            value: Ignored.

        Raises:
            RuntimeError: Always.
        """
        del value
        message = "the provider rejected the instrument"
        raise RuntimeError(message)


def _bridge(instrument: Instrument) -> OpenTelemetryBridge:
    """A bridge whose every family publishes to the supplied instrument.

    Args:
        instrument: What every family publishes to.

    Returns:
        The bridge.
    """
    return OpenTelemetryBridge(meter=None, instruments=dict.fromkeys(metric_names(), instrument))


def test_the_bridge_publishes_a_counter_and_a_histogram() -> None:
    """The mapping actually reaches an instrument, rather than merely existing."""
    instrument = Instrument()
    document: dict[str, object] = {
        "families": [
            {
                "name": "globin.telemetry.observations.total",
                "kind": "counter",
                "points": [{"series": "", "value": 4}],
            },
            {
                "name": "globin.telemetry.snapshot.nanoseconds",
                "kind": "histogram",
                "points": [{"series": "", "count": 1, "total": 900}],
            },
        ]
    }
    assert _bridge(instrument).offer([document]) is ExportOutcome.DELIVERED
    assert instrument.added == [4]
    assert instrument.recorded == [900]


def test_a_provider_that_throws_is_a_temporary_failure() -> None:
    """A provider must never end the run it was measuring."""
    document: dict[str, object] = {
        "families": [
            {
                "name": "globin.telemetry.observations.total",
                "kind": "counter",
                "points": [{"series": "", "value": 1}],
            }
        ]
    }
    assert _bridge(Breaking()).offer([document]) is ExportOutcome.TEMPORARY_FAILURE


@pytest.mark.parametrize(
    "document",
    [
        pytest.param({}, id="no-families"),
        pytest.param({"families": "not-a-list"}, id="families-not-a-list"),
        pytest.param({"families": [None]}, id="family-not-a-mapping"),
        pytest.param({"families": [{"name": 1, "points": []}]}, id="name-not-a-string"),
        pytest.param(
            {"families": [{"name": "globin.telemetry.observations.total", "points": "x"}]},
            id="points-not-a-list",
        ),
        pytest.param(
            {"families": [{"name": "globin.invented.total", "kind": "counter", "points": []}]},
            id="unregistered-family",
        ),
        pytest.param(
            {
                "families": [
                    {
                        "name": "globin.telemetry.observations.total",
                        "kind": "counter",
                        "points": [None],
                    }
                ]
            },
            id="point-not-a-mapping",
        ),
    ],
)
def test_a_malformed_document_publishes_nothing_and_does_not_raise(
    document: dict[str, object],
) -> None:
    """A bridge reads a document it did not build, so every shape must be survivable.

    None of these is a GLOBIN document. Each is what a decoder, a partial write or
    a future schema version could hand over, and none of them may take a run down.
    """
    instrument = Instrument()
    assert _bridge(instrument).offer([document]) is ExportOutcome.DELIVERED
    assert instrument.added == []
    assert instrument.recorded == []


def test_closing_a_bridge_releases_nothing_and_is_safe() -> None:
    """The provider owns its own lifecycle, so this is deliberately empty."""
    _bridge(Instrument()).close()


def test_a_publisher_keeps_the_newest_exposition() -> None:
    """The textfile route: whatever was published last is what a scrape reads."""
    publisher = PrometheusPublisher(registry=None)
    document: dict[str, object] = {
        "families": [
            {
                "name": "globin.telemetry.observations.total",
                "kind": "counter",
                "points": [{"series": "", "value": 7}],
            }
        ]
    }
    assert publisher.offer([document]) is ExportOutcome.DELIVERED
    assert "globin_telemetry_observations_total 7" in publisher.latest


def test_a_publisher_that_cannot_render_reports_a_temporary_failure() -> None:
    """A document that is not a mapping at all is survivable rather than fatal."""
    publisher = PrometheusPublisher(registry=None)
    malformed: list[dict[str, object]] = [None]  # type: ignore[list-item]
    assert publisher.offer(malformed) is ExportOutcome.TEMPORARY_FAILURE


class Server:
    """A listener that records its shutdown."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.stopped = 0

    def shutdown(self) -> None:
        """Record one shutdown."""
        self.stopped += 1


class Angry:
    """A listener that refuses to shut down."""

    def shutdown(self) -> None:
        """Raise instead of stopping.

        Raises:
            RuntimeError: Always.
        """
        message = "the server refused"
        raise RuntimeError(message)


def test_closing_a_publisher_shuts_a_listener_down_once() -> None:
    """Idempotent, because shutdown paths call close more than once."""
    server = Server()
    publisher = PrometheusPublisher(registry=None, server=server)
    assert publisher.listening
    publisher.close()
    publisher.close()
    assert server.stopped == 1
    assert not publisher.listening


def test_a_listener_whose_shutdown_raises_is_contained() -> None:
    """A teardown that raised would turn a clean run into a failed one."""
    PrometheusPublisher(registry=None, server=Angry()).close()


def test_an_unusable_port_is_refused_before_anything_binds() -> None:
    """Binding is the irreversible part, so validation happens first.

    No socket is opened here, and the offline guard would not have caught one if
    it were: it blocks outbound connections rather than listeners. That gap is
    exactly why the port is validated before `start_http_server` is reached.
    """
    publisher = PrometheusPublisher(registry=None)
    with pytest.raises(ValueError, match="outside"):
        start_loopback_listener(publisher, 80)
    assert not publisher.listening
