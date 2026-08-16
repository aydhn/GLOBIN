"""The pure health vocabulary: readings, results, the registry and the reduction.

Everything here is a function of values written by hand. What the collector does
with real probes is `test_health_collector.py`'s; what a probe reads off this host
is `test_health_adapters.py`'s.

The reduction gets the most attention, because it is the one piece of logic an
operator's behaviour actually depends on: it decides whether a snapshot is amber.
"""

import pytest

from globin.domain.clock import Duration, Instant, instant_from_epoch_millis
from globin.domain.health import (
    AGGREGATE_CHECK,
    HEALTH_SCHEMA_VERSION,
    MAXIMUM_DETAIL_FIELDS,
    MAXIMUM_SUMMARY_LENGTH,
    REASON_CHECK_RAISED,
    REASON_DISK_EXHAUSTED,
    REASON_DISK_LOW,
    REASON_OK,
    REASON_PSUTIL_ABSENT,
    REASONS,
    Availability,
    FilesystemReading,
    HealthCheckResult,
    HealthCheckSpec,
    HealthSeverity,
    HealthThresholds,
    HostSummary,
    LifecycleSummary,
    LoggingState,
    LoggingSummary,
    PathSummary,
    PlatformSummary,
    ProcessSummary,
    Reading,
    RuntimeHealthSnapshot,
    RuntimeHealthState,
    ThreadSummary,
    absent,
    aggregate_state,
    check_identifiers,
    checks,
    measured,
    spec_for,
)
from globin.errors import ValidationError


def result(
    identifier: str = "runtime.identity",
    severity: HealthSeverity = HealthSeverity.PASS,
    reason: str = REASON_OK,
) -> HealthCheckResult:
    """One result, with everything else defaulted."""
    return HealthCheckResult(identifier, severity, "a summary", reason)


# ---------------------------------------------------------------------------
# Reading: a measurement and an absence are different shapes
# ---------------------------------------------------------------------------


def test_a_measured_reading_carries_its_value() -> None:
    reading = measured(1024, "bytes")
    assert reading.measured
    assert reading.value == 1024
    assert reading.reason == ""


def test_an_absent_reading_carries_a_reason_and_no_value() -> None:
    reading = absent(Availability.UNAVAILABLE, REASON_PSUTIL_ABSENT, "bytes")
    assert not reading.measured
    assert reading.value is None
    assert reading.reason == REASON_PSUTIL_ABSENT


def test_a_measured_reading_without_a_value_is_refused() -> None:
    """The shape a probe produces after an early return."""
    with pytest.raises(ValidationError, match="must carry a value"):
        Reading(Availability.MEASURED)


def test_an_absent_reading_carrying_a_value_is_refused() -> None:
    """The shape a probe produces when it reports the last good figure beside a failure."""
    with pytest.raises(ValidationError, match="must not carry a value"):
        Reading(Availability.DENIED, 1, "bytes", REASON_PSUTIL_ABSENT)


def test_an_absent_reading_must_name_a_declared_reason() -> None:
    with pytest.raises(ValidationError, match="declared reason"):
        Reading(Availability.UNAVAILABLE, None, "bytes", "INVENTED")


def test_a_boolean_is_not_a_count() -> None:
    """`True` is an `int` in Python, and a count of `True` is nobody's measurement."""
    with pytest.raises(ValidationError, match="bool is not one"):
        Reading(Availability.MEASURED, True, "count")


def test_absent_refuses_to_build_a_measurement() -> None:
    with pytest.raises(ValidationError, match="use measured"):
        absent(Availability.MEASURED, REASON_OK)


# ---------------------------------------------------------------------------
# What a check result bounds, and what it redacts
# ---------------------------------------------------------------------------


def test_a_result_redacts_its_own_details() -> None:
    """The guarantee `LogEvent` gives, obtained the same way."""
    built = HealthCheckResult(
        "host.disk",
        HealthSeverity.PASS,
        "fine",
        REASON_OK,
        details=(("api_key", "AKIAsecret"), ("free_bytes", 10)),
    )
    assert dict(built.details)["api_key"] == "[redacted]"
    assert dict(built.details)["free_bytes"] == 10


def test_a_results_details_are_sorted_so_two_runs_serialise_the_same() -> None:
    built = HealthCheckResult(
        "host.disk", HealthSeverity.PASS, "fine", REASON_OK, details=(("z", 1), ("a", 2))
    )
    assert [key for key, _ in built.details] == ["a", "z"]


def test_an_undeclared_reason_is_refused() -> None:
    with pytest.raises(ValidationError, match="not a declared health reason"):
        HealthCheckResult("host.disk", HealthSeverity.PASS, "fine", "MADE_UP")


def test_an_oversized_summary_is_refused() -> None:
    """A summary is a sentence, not a place to smuggle a log line."""
    with pytest.raises(ValidationError, match="at most"):
        HealthCheckResult("host.disk", HealthSeverity.PASS, "x" * (MAXIMUM_SUMMARY_LENGTH + 1))


def test_too_many_details_are_refused() -> None:
    """An unbounded map is how a diagnostic becomes a data export."""
    details = tuple((f"k{index}", index) for index in range(MAXIMUM_DETAIL_FIELDS + 1))
    with pytest.raises(ValidationError, match="at most"):
        HealthCheckResult("host.disk", HealthSeverity.PASS, "fine", REASON_OK, details=details)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_the_registry_is_ordered_and_ends_with_the_aggregate() -> None:
    identifiers = check_identifiers()
    assert identifiers[-1] == AGGREGATE_CHECK
    assert len(set(identifiers)) == len(identifiers)


def test_every_registered_check_can_be_looked_up() -> None:
    for identifier in check_identifiers():
        assert spec_for(identifier).identifier == identifier


def test_an_unregistered_check_cannot_be_looked_up() -> None:
    with pytest.raises(ValidationError, match="not a registered"):
        spec_for("nothing.at.all")


def test_the_registry_is_the_same_tuple_every_call() -> None:
    """A function rather than a constant, but not a source of variation."""
    assert checks() == checks()


def test_every_declared_reason_is_a_string_and_the_set_is_not_empty() -> None:
    assert REASONS
    assert all(isinstance(reason, str) for reason in REASONS)


# ---------------------------------------------------------------------------
# The reduction — the piece an operator's behaviour depends on
# ---------------------------------------------------------------------------


def test_all_pass_is_healthy() -> None:
    assert aggregate_state((result(),)) is RuntimeHealthState.HEALTHY


def test_any_failure_is_unhealthy() -> None:
    results = (result(), result("host.disk", HealthSeverity.FAIL, REASON_DISK_EXHAUSTED))
    assert aggregate_state(results) is RuntimeHealthState.UNHEALTHY


def test_a_failure_outranks_a_warning_and_an_unknown() -> None:
    """Nothing forgives a failure."""
    results = (
        result("process.memory", HealthSeverity.UNKNOWN, REASON_PSUTIL_ABSENT),
        result("host.disk", HealthSeverity.WARN, REASON_DISK_LOW),
        result("host.memory", HealthSeverity.FAIL, REASON_DISK_EXHAUSTED),
    )
    assert aggregate_state(results) is RuntimeHealthState.UNHEALTHY


def test_a_warning_is_degraded() -> None:
    results = (result(), result("host.disk", HealthSeverity.WARN, REASON_DISK_LOW))
    assert aggregate_state(results) is RuntimeHealthState.DEGRADED


def test_a_predicted_unmeasurability_does_not_make_a_system_amber() -> None:
    """The CI host: psutil absent on every run, and still healthy.

    `process.memory` is marked `tolerates_unknown` in the registry, so its silence
    is an expected state of a healthy system rather than a gap in the picture.
    """
    results = (result(), result("process.memory", HealthSeverity.UNKNOWN, REASON_PSUTIL_ABSENT))
    assert aggregate_state(results) is RuntimeHealthState.HEALTHY


def test_an_unpredicted_unmeasurability_is_degraded() -> None:
    """`host.disk` is mandatory: `shutil.disk_usage` needs no library."""
    results = (result(), result("host.disk", HealthSeverity.UNKNOWN, REASON_CHECK_RAISED))
    assert aggregate_state(results) is RuntimeHealthState.DEGRADED


def test_the_registry_can_be_injected_so_a_test_states_its_own_tolerance() -> None:
    specs = (HealthCheckSpec("host.disk", "host", tolerates_unknown=True),)
    results = (result("host.disk", HealthSeverity.UNKNOWN, REASON_CHECK_RAISED),)
    assert aggregate_state(results, specs) is RuntimeHealthState.HEALTHY


def test_no_results_at_all_is_healthy_rather_than_an_error() -> None:
    """Vacuous, and deliberately not a fourth state.

    A snapshot that produced nothing is an error reported through the exception
    path rather than a verdict, so there is no `unknown` aggregate to return.
    """
    assert aggregate_state(()) is RuntimeHealthState.HEALTHY


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------


def thresholds(**overrides: int) -> HealthThresholds:
    """A valid set of thresholds, with named fields overridden."""
    values = {
        "minimum_free_bytes": 268_435_456,
        "disk_warning_bytes": 1_073_741_824,
        "minimum_available_memory_bytes": 134_217_728,
        "process_rss_warning_bytes": 1_073_741_824,
        "budget_millis": 5_000,
    }
    values.update(overrides)
    return HealthThresholds(**values)


def test_a_valid_threshold_set_is_accepted() -> None:
    assert thresholds().budget_millis == 5_000


def test_a_warning_threshold_at_or_below_the_failure_threshold_is_refused() -> None:
    """The misconfiguration nothing else would report: a warning band of zero width."""
    with pytest.raises(ValidationError, match="can never warn"):
        thresholds(disk_warning_bytes=268_435_456)


def test_a_threshold_below_its_floor_is_refused() -> None:
    with pytest.raises(ValidationError, match="is between"):
        thresholds(minimum_free_bytes=1)


def test_a_threshold_above_its_ceiling_is_refused() -> None:
    with pytest.raises(ValidationError, match="is between"):
        thresholds(process_rss_warning_bytes=1 << 60)


def test_a_boolean_threshold_is_refused() -> None:
    with pytest.raises(ValidationError, match="not one"):
        thresholds(minimum_free_bytes=True)


def test_a_budget_outside_its_range_is_refused() -> None:
    with pytest.raises(ValidationError, match="budget_millis"):
        thresholds(budget_millis=1)


# ---------------------------------------------------------------------------
# The snapshot
# ---------------------------------------------------------------------------


def snapshot(results: tuple[HealthCheckResult, ...]) -> RuntimeHealthSnapshot:
    """A snapshot carrying the given results and defaults elsewhere."""
    nothing = absent(Availability.UNAVAILABLE, REASON_PSUTIL_ABSENT)
    return RuntimeHealthSnapshot(
        generated_at=instant_from_epoch_millis(0),
        correlation_id="c",
        run_id="r",
        version="0.1.0",
        profile="default",
        config_fingerprint="sha256:" + "0" * 64,
        context_fingerprint="",
        uptime=Duration(0),
        platform=PlatformSummary("CPython", "3.14.5", "AMD64", "Windows", "11"),
        process=ProcessSummary(1, nothing, nothing, nothing, nothing, nothing, nothing),
        host=HostSummary(nothing, nothing, nothing, nothing, ()),
        paths=PathSummary(root_present=True),
        lifecycle=LifecycleSummary("running", "i", lock_held=True),
        logging=LoggingSummary(LoggingState.RUNNING, "DEBUG", "logs", nothing, nothing),
        threads=ThreadSummary(1, ()),
        state=RuntimeHealthState.HEALTHY,
        results=results,
    )


def test_a_snapshot_accepts_results_in_registry_order() -> None:
    built = snapshot((result("runtime.identity"), result("host.disk")))
    assert built.result_for("host.disk") is not None
    assert built.result_for("nothing") is None
    assert built.schema_version == HEALTH_SCHEMA_VERSION


def test_a_snapshot_refuses_results_out_of_registry_order() -> None:
    """Refused at construction rather than discovered later.

    A collector appending results as checks finish would produce a different
    document — and therefore a different digest — for an identical process.
    """
    with pytest.raises(ValidationError, match="registry order"):
        snapshot((result("host.disk"), result("runtime.identity")))


def test_a_snapshot_refuses_a_result_for_a_check_that_is_not_registered() -> None:
    with pytest.raises(ValidationError, match="unregistered"):
        snapshot((result("invented.check"),))


def test_a_snapshot_counts_what_could_not_be_measured_whatever_the_state() -> None:
    """Forgiving an unmeasurability in the verdict must not hide it in the document."""
    built = snapshot(
        (
            result("runtime.identity"),
            result("process.memory", HealthSeverity.UNKNOWN, REASON_PSUTIL_ABSENT),
        )
    )
    assert built.unmeasurable() == ("process.memory",)


def test_a_filesystem_reading_names_its_anchor_and_nothing_under_it() -> None:
    entry = FilesystemReading("C:", measured(10, "bytes"), measured(5, "bytes"))
    assert entry.anchor == "C:"


def test_an_instant_and_a_duration_are_the_only_time_types_a_snapshot_carries() -> None:
    built = snapshot((result(),))
    assert isinstance(built.generated_at, Instant)
    assert isinstance(built.uptime, Duration)
