"""Logging as the application actually assembles it, from call site to written line.

The unit tests substitute the sink, so they prove the logger builds the right
record but never that anything writes one. The property tests build records
without a stream at all. Neither would notice a composition root that wired a
logger to the wrong stream, or a sink that serialised into a shape nothing can
read back.

This level runs the real graph — :func:`globin.runtime.composition.build_logger`,
the real serialiser, a real stream — and reads the output back as JSON. The
stream is a :class:`io.StringIO` rather than a file because the thing under test
is the wiring, not the filesystem; still no network, no credentials and no
exchange.
"""

import io
import json
from typing import Final

import pytest

from globin.runtime.composition import build_logger

PLANTED_CREDENTIAL: Final[str] = "PLANTED-CREDENTIAL-9c41"
"""A credential-shaped value, so its absence downstream is unambiguous."""


@pytest.fixture
def stream() -> io.StringIO:
    """Somewhere the wired logger can write that a test can read back."""
    return io.StringIO()


def _records(stream: io.StringIO) -> list[dict[str, object]]:
    """Parse everything written so far, one JSON object per line."""
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_the_wired_logger_writes_a_record_that_parses(stream: io.StringIO) -> None:
    build_logger(stream=stream, correlation_id="corr-int-1").info(
        "architecture.review.completed", modules=14, clean=True
    )

    (record,) = _records(stream)
    assert record["event"] == "architecture.review.completed"
    assert record["severity"] == "INFO"
    assert record["correlation_id"] == "corr-int-1"
    assert record["fields"] == {"clean": True, "modules": 14}


def test_every_record_from_one_logger_shares_its_correlation_id(stream: io.StringIO) -> None:
    """The point of the phase: related events are findable as a group."""
    logger = build_logger(stream=stream, correlation_id="corr-int-2")
    logger.info("run.started")
    logger.bind(stage="review").warning("run.slow", elapsed_ms=1200)
    logger.error("run.failed")

    records = _records(stream)
    assert [record["correlation_id"] for record in records] == ["corr-int-2"] * 3
    assert [record["severity"] for record in records] == ["INFO", "WARNING", "ERROR"]


def test_a_planted_credential_does_not_reach_the_stream(stream: io.StringIO) -> None:
    """The end-to-end form of invariant 24, asserted against real written bytes.

    Every other redaction test inspects a structure. This one inspects what was
    actually written, which is the thing the invariant is about.
    """
    logger = build_logger(stream=stream, correlation_id="corr-int-3")
    logger.bind(api_key=PLANTED_CREDENTIAL).info(
        "account.opened",
        symbol="BTCUSDT",
        request={"headers": {"authorization": PLANTED_CREDENTIAL}},
        batch=[{"session_id": PLANTED_CREDENTIAL}],
    )

    written = stream.getvalue()
    assert PLANTED_CREDENTIAL not in written
    assert written.count("[redacted]") == 3
    assert json.loads(written)["fields"]["symbol"] == "BTCUSDT"


def test_a_logger_built_without_a_correlation_id_gets_a_fresh_one(stream: io.StringIO) -> None:
    first = build_logger(stream=stream)
    second = build_logger(stream=stream)
    first.info("a.b")
    second.info("c.d")

    identifiers = {record["correlation_id"] for record in _records(stream)}
    assert len(identifiers) == 2
    assert all(identifier for identifier in identifiers)


def test_the_default_stream_is_standard_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Log output must not contaminate whatever a program writes to standard output.

    Built without a stream, so this is the only test exercising the branch a real
    run takes.
    """
    build_logger(correlation_id="corr-int-4").info("startup.completed")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["event"] == "startup.completed"
