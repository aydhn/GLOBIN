"""The logging units: the event, the logger and the stream sink.

Every collaborator here is substituted. The sink is ``_RecordingSink``, a
hand-written class satisfying :class:`~globin.ports.observability.LogSink`
structurally — ``docs/TESTING_STRATEGY.md`` makes that the default and
``unittest.mock`` the exception, and a five-line recorder is easier to read than
a configured mock. The stream is a :class:`io.StringIO`.

What is deliberately *not* here: whether the composition root wires these
together correctly, which is
``tests/integration/test_logging_end_to_end.py``, and whether redaction holds
over generated input, which is
``tests/property/test_observability_properties.py``.
"""

import io
import json
from typing import Final

import pytest

from globin.adapters.observability import (
    ENVELOPE_KEYS,
    StreamLogSink,
    as_record,
    new_correlation_id,
)
from globin.application.observability import Logger, emitted_event
from globin.domain.observability import (
    EVENT_NAME_ALPHABET,
    MAX_REDACTION_DEPTH,
    REDACTED,
    LogEvent,
    Severity,
    is_sensitive,
    log_event,
    redact,
)
from globin.errors import ValidationError

SENTINEL: Final[str] = "SENTINEL-VALUE-4f2a"
"""A value distinctive enough that finding it in output is unambiguous."""


class _RecordingSink:
    """A sink that keeps what it was given, satisfying the port structurally."""

    def __init__(self) -> None:
        self.records: list[LogEvent] = []

    def emit(self, event: LogEvent) -> None:
        self.records.append(event)


class _BrokenStream(io.StringIO):
    """A stream whose every write fails, as a closed pipe or a full disk would."""

    def write(self, s: str, /) -> int:
        msg = f"stream is closed, refusing {len(s)} characters"
        raise OSError(msg)


def _logger() -> tuple[Logger, _RecordingSink]:
    sink = _RecordingSink()
    return Logger(sink=sink, correlation_id="corr-0001"), sink


# --------------------------------------------------------------------------
# Sensitivity and redaction
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "API_KEY",
        "binance_api_key",
        "apiKey",
        "client_secret",
        "TOKEN",
        "x-authorization",
    ],
)
def test_a_sensitive_name_is_recognised_however_it_is_written(key: str) -> None:
    """Substring matching is what catches a prefixed or suffixed name."""
    assert is_sensitive(key)


@pytest.mark.parametrize("key", ["symbol", "quantity", "order_id", "latency_ms", "keyboard"])
def test_an_ordinary_name_is_not_treated_as_sensitive(key: str) -> None:
    assert not is_sensitive(key)


def test_redaction_replaces_the_value_and_keeps_the_name() -> None:
    """The name has to survive: knowing a secret was present is diagnostic."""
    assert redact({"api_secret": SENTINEL}) == {"api_secret": REDACTED}


def test_redaction_reaches_a_secret_nested_under_an_innocent_name() -> None:
    result = redact({"request": {"headers": {"authorization": SENTINEL}}, "symbol": "BTCUSDT"})

    assert SENTINEL not in str(result)
    assert result["symbol"] == "BTCUSDT"


def test_redaction_descends_into_sequences() -> None:
    result = redact({"batch": [{"token": SENTINEL}, {"symbol": "ETHUSDT"}]})

    assert SENTINEL not in str(result)
    assert result["batch"] == ({"token": REDACTED}, {"symbol": "ETHUSDT"})


def test_a_secret_string_is_not_descended_into_character_by_character() -> None:
    """``str`` is a ``Sequence``; treating it as one would redact nothing at all."""
    assert redact({"password": "hunter2"}) == {"password": REDACTED}


def test_redaction_copies_so_the_caller_cannot_change_what_was_logged() -> None:
    original: dict[str, object] = {"symbol": "BTCUSDT", "nested": {"depth": 1}}
    result = redact(original)

    original["symbol"] = "MUTATED"
    nested = original["nested"]
    assert isinstance(nested, dict)
    nested["depth"] = 99

    assert result == {"symbol": "BTCUSDT", "nested": {"depth": 1}}


def test_redaction_refuses_to_render_beyond_the_depth_limit() -> None:
    payload: object = SENTINEL
    for _ in range(MAX_REDACTION_DEPTH + 3):
        payload = {"inner": payload}

    assert SENTINEL not in str(redact({"root": payload}))


def test_redaction_terminates_on_a_self_referential_structure() -> None:
    """Without the depth guard this recurses until the stack runs out."""
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    assert REDACTED in str(redact({"root": cyclic}))


# --------------------------------------------------------------------------
# LogEvent
# --------------------------------------------------------------------------


def test_an_event_redacts_itself_even_when_built_directly() -> None:
    """The guarantee cannot depend on callers using the factory."""
    event = LogEvent(
        severity=Severity.INFO,
        event="order.submitted",
        correlation_id="corr-1",
        fields=(("api_key", SENTINEL),),
    )

    assert event.fields == (("api_key", REDACTED),)


def test_fields_are_stored_sorted_so_two_equal_events_compare_equal() -> None:
    first = log_event(Severity.INFO, "a.b", "corr-1", {"zulu": 1, "alpha": 2})
    second = log_event(Severity.INFO, "a.b", "corr-1", {"alpha": 2, "zulu": 1})

    assert first.fields == (("alpha", 2), ("zulu", 1))
    assert first == second


def test_an_event_with_no_fields_is_allowed() -> None:
    assert log_event(Severity.INFO, "a.b", "corr-1").fields == ()


def test_as_mapping_returns_a_detached_copy() -> None:
    event = log_event(Severity.INFO, "a.b", "corr-1", {"symbol": "BTCUSDT"})
    mapping = event.as_mapping()
    mapping["symbol"] = "MUTATED"

    assert event.fields == (("symbol", "BTCUSDT"),)


def test_an_empty_event_name_is_refused() -> None:
    with pytest.raises(ValidationError, match="event name is empty"):
        log_event(Severity.INFO, "", "corr-1")


@pytest.mark.parametrize("name", ["Order.Submitted", "order submitted", "order-submitted", "ç"])
def test_an_event_name_outside_the_alphabet_is_refused(name: str) -> None:
    """Names are identifiers, not prose; a sentence here is a formatted message."""
    with pytest.raises(ValidationError, match="event names are lowercase"):
        log_event(Severity.INFO, name, "corr-1")


def test_every_permitted_character_is_actually_accepted() -> None:
    """Guards the alphabet against being narrowed without anyone noticing."""
    assert log_event(Severity.INFO, EVENT_NAME_ALPHABET, "corr-1").event == EVENT_NAME_ALPHABET


def test_an_empty_correlation_id_is_refused() -> None:
    with pytest.raises(ValidationError, match="empty correlation id"):
        log_event(Severity.INFO, "a.b", "")


# --------------------------------------------------------------------------
# Logger
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "severity"),
    [
        ("debug", Severity.DEBUG),
        ("info", Severity.INFO),
        ("warning", Severity.WARNING),
        ("error", Severity.ERROR),
        ("critical", Severity.CRITICAL),
    ],
)
def test_each_named_method_records_its_own_severity(method: str, severity: Severity) -> None:
    logger, sink = _logger()

    getattr(logger, method)("a.b", symbol="BTCUSDT")

    assert sink.records[0].severity is severity
    assert sink.records[0].fields == (("symbol", "BTCUSDT"),)


def test_binding_returns_a_new_logger_and_leaves_the_original_alone() -> None:
    """The whole reason context is explicit rather than ambient."""
    logger, sink = _logger()

    bound = logger.bind(component="review")
    logger.info("a.b")
    bound.info("c.d")

    assert bound is not logger
    assert logger.context == ()
    assert sink.records[0].fields == ()
    assert sink.records[1].fields == (("component", "review"),)


def test_a_narrower_binding_overrides_a_wider_one() -> None:
    logger, sink = _logger()

    logger.bind(stage="one").bind(stage="two").info("a.b")

    assert sink.records[0].fields == (("stage", "two"),)


def test_a_call_site_field_wins_over_bound_context() -> None:
    """The more specific statement is the one made where the event happened."""
    logger, sink = _logger()

    logger.bind(symbol="BTCUSDT").info("a.b", symbol="ETHUSDT")

    assert sink.records[0].fields == (("symbol", "ETHUSDT"),)


def test_bound_context_is_redacted_like_any_other_field() -> None:
    logger, sink = _logger()

    logger.bind(api_key=SENTINEL).info("a.b")

    assert sink.records[0].fields == (("api_key", REDACTED),)


def test_the_correlation_id_travels_with_every_record() -> None:
    logger, sink = _logger()

    logger.info("a.b")
    logger.bind(stage="one").info("c.d")

    assert [record.correlation_id for record in sink.records] == ["corr-0001", "corr-0001"]


def test_switching_correlation_keeps_the_sink_and_the_context() -> None:
    logger, sink = _logger()

    logger.bind(component="review").with_correlation("corr-0002").info("a.b")

    assert sink.records[0].correlation_id == "corr-0002"
    assert sink.records[0].fields == (("component", "review"),)


def test_the_record_a_logger_would_emit_can_be_built_without_emitting_it() -> None:
    logger, sink = _logger()

    event = emitted_event(logger.bind(component="review"), Severity.WARNING, "a.b", stage="one")

    assert not sink.records
    assert event.severity is Severity.WARNING
    assert event.correlation_id == "corr-0001"
    assert event.fields == (("component", "review"), ("stage", "one"))


# --------------------------------------------------------------------------
# The record shape and the stream sink
# --------------------------------------------------------------------------


def test_the_envelope_comes_first_and_fields_are_nested() -> None:
    """Nesting is what stops a field called ``event`` displacing the event name."""
    record = as_record(
        log_event(Severity.INFO, "a.b", "corr-1", {"event": "not.the.envelope"}), "T"
    )

    assert tuple(record)[: len(ENVELOPE_KEYS)] == ENVELOPE_KEYS
    assert record["event"] == "a.b"
    assert record["fields"] == {"event": "not.the.envelope"}


def test_fields_are_present_even_when_empty() -> None:
    """A stable shape means nothing reading the output needs a conditional."""
    assert as_record(log_event(Severity.INFO, "a.b", "corr-1"), "T")["fields"] == {}


def test_severity_is_written_by_name_not_by_number() -> None:
    assert as_record(log_event(Severity.WARNING, "a.b", "corr-1"), "T")["severity"] == "WARNING"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, True),
        (7, 7),
        (1.5, 1.5),
        ("text", "text"),
        ([1, 2], [1, 2]),
        ((1, 2), [1, 2]),
        ({"a": 1}, {"a": 1}),
    ],
)
def test_a_value_json_can_represent_passes_through(value: object, expected: object) -> None:
    record = as_record(log_event(Severity.INFO, "a.b", "corr-1", {"v": value}), "T")

    assert record["fields"] == {"v": expected}


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_a_non_finite_float_becomes_text_so_the_line_stays_valid_json(value: float) -> None:
    """``json`` emits bare ``NaN`` and ``Infinity``, which no strict reader accepts."""
    record = as_record(log_event(Severity.INFO, "a.b", "corr-1", {"v": value}), "T")
    fields = record["fields"]

    assert isinstance(fields, dict)
    assert isinstance(fields["v"], str)
    assert json.loads(json.dumps(record))


def test_a_value_json_cannot_represent_is_rendered_rather_than_refused() -> None:
    """Coercion is total: a logging call must not be able to raise."""
    record = as_record(log_event(Severity.INFO, "a.b", "corr-1", {"v": ValueError("boom")}), "T")

    assert record["fields"] == {"v": "ValueError('boom')"}


def test_the_sink_writes_one_json_line_per_record() -> None:
    stream = io.StringIO()
    sink = StreamLogSink(stream)

    sink.emit(log_event(Severity.INFO, "a.b", "corr-1", {"symbol": "BTCUSDT"}))
    sink.emit(log_event(Severity.ERROR, "c.d", "corr-1"))

    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["fields"] == {"symbol": "BTCUSDT"}
    assert json.loads(lines[1])["severity"] == "ERROR"


def test_the_written_line_carries_a_timezone_aware_timestamp() -> None:
    stream = io.StringIO()
    StreamLogSink(stream).emit(log_event(Severity.INFO, "a.b", "corr-1"))

    timestamp = json.loads(stream.getvalue())["timestamp"]
    assert timestamp.endswith("+00:00"), f"expected a UTC offset, got {timestamp!r}"


def test_non_ascii_is_escaped_so_any_stream_encoding_can_take_it() -> None:
    """GLOBIN's host is Windows, where a console stream is often not UTF-8."""
    stream = io.StringIO()
    StreamLogSink(stream).emit(log_event(Severity.INFO, "a.b", "corr-1", {"note": "ölçüm"}))

    written = stream.getvalue()
    assert written.isascii()
    assert json.loads(written)["fields"]["note"] == "ölçüm"


def test_a_failing_write_propagates_rather_than_disappearing() -> None:
    """A sink that discards records looks exactly like one that works."""
    with pytest.raises(OSError, match="stream is closed"):
        StreamLogSink(_BrokenStream()).emit(log_event(Severity.INFO, "a.b", "corr-1"))


def test_a_fresh_correlation_id_is_unique_and_printable() -> None:
    first, second = new_correlation_id(), new_correlation_id()

    assert first != second
    assert first.isalnum()
    assert len(first) == 32
