"""Configuration from a document on disk, through the composition root, to a stream.

The units are checked next door. What is checked here is the wiring, and one
claim in particular that no unit test can make: that a severity written in a TOML
file actually stops a record being written. Every step in between —
:class:`~globin.adapters.configuration.TomlConfigurationSource`, the fold, the
binding, :func:`~globin.runtime.composition.build_logger` and
:class:`~globin.adapters.observability.ThresholdLogSink` — has to be wired the
right way round for that to happen, and any of them could be individually correct
while the assembly is not.

The documents are written into ``tmp_path`` rather than committed. A deliberately
malformed one could not be committed anyway: ``.pre-commit-config.yaml`` runs
``check-toml`` over every file in the tree, so a fixture that exists to be
invalid would fail the hygiene gate rather than the test it was written for.
"""

import io
import json
import tomllib
from pathlib import Path

import pytest

from globin.adapters.configuration import TomlConfigurationSource
from globin.domain.configuration import default_config
from globin.domain.observability import Severity
from globin.errors import ConfigurationError
from globin.runtime.composition import build_configuration, build_logger


@pytest.fixture
def stream() -> io.StringIO:
    """A stream that keeps what was written to it."""
    return io.StringIO()


def _document(tmp_path: Path, text: str) -> Path:
    """Write a configuration document as UTF-8 without a byte-order mark."""
    path = tmp_path / "globin.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _severities(stream: io.StringIO) -> list[str]:
    """The severity of every record written, in order."""
    return [json.loads(line)["severity"] for line in stream.getvalue().splitlines()]


def _log_one_of_each(stream: io.StringIO, path: Path | None = None) -> None:
    """Wire a logger from ``path`` if given, then record at every severity."""
    sources = [] if path is None else [TomlConfigurationSource(path)]
    logger = build_logger(
        stream=stream,
        correlation_id="corr-config-1",
        config=build_configuration(sources),
    )
    logger.debug("phase.seven.debug")
    logger.info("phase.seven.info")
    logger.warning("phase.seven.warning")
    logger.error("phase.seven.error")
    logger.critical("phase.seven.critical")


def test_a_threshold_in_a_document_stops_records_being_written(
    tmp_path: Path, stream: io.StringIO
) -> None:
    _log_one_of_each(stream, _document(tmp_path, '[logging]\nmin_severity = "WARNING"\n'))
    assert _severities(stream) == ["WARNING", "ERROR", "CRITICAL"]


def test_the_strictest_threshold_keeps_only_the_worst(tmp_path: Path, stream: io.StringIO) -> None:
    _log_one_of_each(stream, _document(tmp_path, '[logging]\nmin_severity = "CRITICAL"\n'))
    assert _severities(stream) == ["CRITICAL"]


def test_a_document_that_configures_nothing_keeps_everything(
    tmp_path: Path, stream: io.StringIO
) -> None:
    _log_one_of_each(stream, _document(tmp_path, "# nothing to say\n"))
    assert _severities(stream) == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def test_logging_with_no_configuration_at_all_writes_everything(stream: io.StringIO) -> None:
    """Phase 006's behaviour, unchanged.

    This is the executable form of the compatibility claim: adding a
    configuration model must not alter what a caller who never asked for one
    sees. A default threshold above ``DEBUG`` would fail here.
    """
    logger = build_logger(stream=stream, correlation_id="corr-config-2")
    logger.debug("phase.seven.debug")
    logger.critical("phase.seven.critical")
    assert _severities(stream) == ["DEBUG", "CRITICAL"]


def test_records_that_clear_the_threshold_are_otherwise_untouched(
    tmp_path: Path, stream: io.StringIO
) -> None:
    """Filtering decides *whether* a record is written, never what it says."""
    path = _document(tmp_path, '[logging]\nmin_severity = "ERROR"\n')
    logger = build_logger(
        stream=stream,
        correlation_id="corr-config-3",
        config=build_configuration([TomlConfigurationSource(path)]),
    )
    logger.error("order.rejected", venue="binance", attempt=2)

    record = json.loads(stream.getvalue())
    assert record["event"] == "order.rejected"
    assert record["correlation_id"] == "corr-config-3"
    assert record["fields"] == {"attempt": 2, "venue": "binance"}


def test_a_later_source_overrides_an_earlier_one(tmp_path: Path) -> None:
    """The precedence rule, end to end rather than over generated layers."""
    weak = tmp_path / "weak.toml"
    weak.write_text('[logging]\nmin_severity = "DEBUG"\n', encoding="utf-8")
    strong = tmp_path / "strong.toml"
    strong.write_text('[logging]\nmin_severity = "ERROR"\n', encoding="utf-8")

    config = build_configuration([TomlConfigurationSource(weak), TomlConfigurationSource(strong)])
    assert config.logging.min_severity is Severity.ERROR


def test_building_with_no_sources_gives_the_declared_defaults() -> None:
    assert build_configuration() == default_config()


def test_a_document_with_an_unknown_setting_is_refused_by_name(tmp_path: Path) -> None:
    """The failure an operator is most likely to cause, and the one that must not
    pass silently: a setting that looks plausible and does nothing."""
    path = _document(tmp_path, '[logging]\nmin_severty = "WARNING"\n')
    with pytest.raises(ConfigurationError) as refused:
        build_configuration([TomlConfigurationSource(path)])
    message = str(refused.value)
    assert "logging.min_severty" in message
    assert str(path) in message


def test_a_document_with_an_unreadable_value_names_the_document(tmp_path: Path) -> None:
    path = _document(tmp_path, "[logging]\nmin_severity = 30\n")
    with pytest.raises(ConfigurationError) as refused:
        build_configuration([TomlConfigurationSource(path)])
    assert str(path) in str(refused.value)


def _overridden_by_a_working_document(tmp_path: Path, text: str) -> list[TomlConfigurationSource]:
    """A questionable document, with a sound one layered on top of it."""
    weak = tmp_path / "weak.toml"
    weak.write_text(text, encoding="utf-8")
    strong = tmp_path / "strong.toml"
    strong.write_text('[logging]\nmin_severity = "ERROR"\n', encoding="utf-8")
    return [TomlConfigurationSource(weak), TomlConfigurationSource(strong)]


def test_a_document_that_cannot_be_parsed_is_reported_even_when_overridden(
    tmp_path: Path,
) -> None:
    """Every source is read, so a broken file is never silently skipped."""
    sources = _overridden_by_a_working_document(tmp_path, "this is not = = toml\n")
    with pytest.raises(tomllib.TOMLDecodeError):
        build_configuration(sources)


def test_an_unknown_setting_is_reported_even_when_a_later_source_overrides_it(
    tmp_path: Path,
) -> None:
    """Nothing overrides a key that is not a setting, so a typo always survives
    the fold and is always refused."""
    sources = _overridden_by_a_working_document(tmp_path, '[logging]\nmin_severty = "WARNING"\n')
    with pytest.raises(ConfigurationError, match="min_severty"):
        build_configuration(sources)


def test_a_value_a_later_source_replaces_is_not_validated(tmp_path: Path) -> None:
    """Documented behaviour, held in place on purpose.

    Values are validated once, on the winner. A layer exists so that a stronger
    one may replace what it said, and a value that has been replaced has no
    effect to be wrong about — so ``"LOUD"`` below never reaches validation.

    This is the one place the fold's totality is visible from outside, and it is
    a trade rather than an oversight: validating losing values would put the
    schema inside the fold, where there is no origin to name and no completeness
    to check. If a later phase decides differently, this test is what turns that
    into a deliberate change.
    """
    sources = _overridden_by_a_working_document(tmp_path, '[logging]\nmin_severity = "LOUD"\n')
    assert build_configuration(sources).logging.min_severity is Severity.ERROR
