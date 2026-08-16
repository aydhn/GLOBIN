"""Invariants of the health vocabulary over generated input.

Three properties are worth generating for, and each has a real failure behind it
rather than being a restatement of the code:

* the reduction is total and order-independent — a snapshot must not depend on
  which order the collector happened to finish in;
* a reading is either measured or explained, never both and never neither;
* a member name that survives the safety check survives it again after being
  built, so the archive writer and the manifest cannot disagree.
"""

from hypothesis import given
from hypothesis import strategies as st

from globin.domain.health import (
    REASON_CHECK_RAISED,
    REASON_OK,
    Availability,
    HealthCheckResult,
    HealthCheckSpec,
    HealthSeverity,
    RuntimeHealthState,
    absent,
    aggregate_state,
    check_identifiers,
    measured,
)
from globin.domain.support import member_problems, safe_member_name

severities = st.sampled_from(list(HealthSeverity))
identifiers = st.sampled_from(list(check_identifiers()))


@st.composite
def results(draw: st.DrawFn) -> HealthCheckResult:
    """One result with a generated identifier and severity."""
    severity = draw(severities)
    return HealthCheckResult(
        identifier=draw(identifiers),
        severity=severity,
        summary="generated",
        reason=REASON_OK if severity is HealthSeverity.PASS else REASON_CHECK_RAISED,
    )


@given(st.lists(results(), max_size=12))
def test_the_reduction_is_total(items: list[HealthCheckResult]) -> None:
    """Every input produces one of the three states, and nothing raises."""
    assert aggregate_state(tuple(items)) in set(RuntimeHealthState)


@given(st.lists(results(), max_size=12))
def test_the_reduction_does_not_depend_on_order(items: list[HealthCheckResult]) -> None:
    """A snapshot must not depend on which order the collector finished in."""
    forwards = aggregate_state(tuple(items))
    backwards = aggregate_state(tuple(reversed(items)))
    assert forwards is backwards


@given(st.lists(results(), max_size=12))
def test_a_failure_always_dominates(items: list[HealthCheckResult]) -> None:
    """Nothing forgives a failure, whatever else is present."""
    if any(item.severity is HealthSeverity.FAIL for item in items):
        assert aggregate_state(tuple(items)) is RuntimeHealthState.UNHEALTHY


@given(st.lists(results(), max_size=12))
def test_tolerating_every_check_can_only_improve_the_state(
    items: list[HealthCheckResult],
) -> None:
    """A tolerant registry never makes a system look worse than a strict one."""
    strict = tuple(HealthCheckSpec(name, "g") for name in check_identifiers())
    tolerant = tuple(
        HealthCheckSpec(name, "g", tolerates_unknown=True) for name in check_identifiers()
    )
    order = {
        RuntimeHealthState.HEALTHY: 0,
        RuntimeHealthState.DEGRADED: 1,
        RuntimeHealthState.UNHEALTHY: 2,
    }
    assert (
        order[aggregate_state(tuple(items), tolerant)]
        <= order[aggregate_state(tuple(items), strict)]
    )


@given(st.integers(min_value=0, max_value=1 << 40))
def test_a_measured_reading_always_carries_its_number(value: int) -> None:
    reading = measured(value, "bytes")
    assert reading.measured
    assert reading.value == value


@given(st.sampled_from([a for a in Availability if a is not Availability.MEASURED]))
def test_an_absent_reading_never_carries_a_number(availability: Availability) -> None:
    reading = absent(availability, REASON_CHECK_RAISED, "bytes")
    assert not reading.measured
    assert reading.value is None
    assert reading.reason


@given(
    st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=40),
    st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=40),
)
def test_a_member_name_that_is_built_is_a_member_name_that_is_safe(
    area: str, filename: str
) -> None:
    """The writer and the manifest cannot disagree about what is acceptable."""
    try:
        member = safe_member_name(area, filename)
    except Exception:
        return
    assert member_problems(member) == ()


@given(st.text(max_size=80))
def test_the_member_check_is_total(member: str) -> None:
    """Any string produces a verdict rather than an exception."""
    assert isinstance(member_problems(member), tuple)
