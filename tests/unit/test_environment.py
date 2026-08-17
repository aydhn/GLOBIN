"""Environment capability: how a shortfall is classified, and what stays stable.

Every host below is a literal. An ARM64 machine under emulation, a Windows
release predating `IsWow64Process2`, and a developer box with no Git are all
exercised here and none of them exists — which is the whole reason the judgement
lives in the domain and the reading lives in the adapter.

The two properties that carry the most weight are both about *not* failing:
an unmeasurable capability degrades rather than blocks, and the fingerprint does
not move when something volatile does.
"""

import pytest

from globin.domain.environment import (
    FINGERPRINT_LENGTH,
    FINGERPRINT_SCHEMA,
    ArchitectureCapability,
    CapabilityCategory,
    CapabilityCheck,
    CapabilityReason,
    CapabilitySeverity,
    CapabilityStatus,
    CompatibilityProjection,
    EmulationState,
    EnvironmentCapabilitySnapshot,
    EnvironmentCompatibility,
    MachineArchitecture,
    compatibility_fingerprint,
    compatibility_of,
)
from globin.errors import ValidationError

NATIVE_AMD64 = ArchitectureCapability(
    process=MachineArchitecture.AMD64,
    native=MachineArchitecture.AMD64,
    emulation=EmulationState.NATIVE,
)


def check(
    identifier: str = "environment.architecture.native",
    *,
    severity: CapabilitySeverity = CapabilitySeverity.REQUIRED,
    status: CapabilityStatus = CapabilityStatus.SUPPORTED,
    reason: CapabilityReason = CapabilityReason.SATISFIED,
) -> CapabilityCheck:
    """A check, with the parts a test does not care about filled in."""
    return CapabilityCheck(
        identifier=identifier,
        category=CapabilityCategory.ARCHITECTURE,
        severity=severity,
        status=status,
        reason=reason,
    )


def snapshot(*checks: CapabilityCheck) -> EnvironmentCapabilitySnapshot:
    """A snapshot over the given checks, on a native AMD64 host."""
    return EnvironmentCapabilitySnapshot(checks=checks, architecture=NATIVE_AMD64)


# ---------------------------------------------------------------------------
# What blocks and what does not
# ---------------------------------------------------------------------------


def test_a_failing_required_capability_blocks() -> None:
    """The only thing that does."""
    result = compatibility_of([check(status=CapabilityStatus.UNSUPPORTED)])
    assert result is EnvironmentCompatibility.BLOCKED


def test_an_unmeasurable_required_capability_degrades_rather_than_blocks() -> None:
    """The distinction ADR-0045 exists for, and it decides whether a host starts.

    A capability that could not be measured has not been shown to be absent.
    `phase_028_sources.md` S-02 records that a host predating Windows 10 version
    1709 cannot answer the native-architecture question at all, and
    `runtime-contract.toml` declares a floor of "10" with no build component — so
    such a host is supported and unanswerable at once. Refusing to start it would
    treat an absent measurement as a failed one.
    """
    result = compatibility_of([check(status=CapabilityStatus.UNKNOWN)])
    assert result is EnvironmentCompatibility.DEGRADED


def test_a_missing_optional_capability_degrades_rather_than_blocks() -> None:
    """An absent developer tool must never stop a correctly provisioned host."""
    result = compatibility_of(
        [check(severity=CapabilitySeverity.OPTIONAL, status=CapabilityStatus.UNSUPPORTED)]
    )
    assert result is EnvironmentCompatibility.DEGRADED


def test_a_degraded_capability_degrades() -> None:
    """Running under emulation is the case: correct, slower, worth saying."""
    result = compatibility_of([check(status=CapabilityStatus.DEGRADED)])
    assert result is EnvironmentCompatibility.DEGRADED


def test_a_not_applicable_capability_changes_nothing() -> None:
    """How a Windows-only question reports on a host where it does not arise."""
    result = compatibility_of([check(status=CapabilityStatus.NOT_APPLICABLE)])
    assert result is EnvironmentCompatibility.READY


def test_everything_supported_is_ready() -> None:
    """The control."""
    assert compatibility_of([check(), check("other")]) is EnvironmentCompatibility.READY


def test_one_blocking_capability_outranks_any_number_of_degrading_ones() -> None:
    """Severity is ordered, so a reader is told the worst thing rather than the first."""
    result = compatibility_of(
        [
            check("a", status=CapabilityStatus.UNKNOWN),
            check("b", status=CapabilityStatus.UNSUPPORTED),
            check("c", status=CapabilityStatus.DEGRADED),
        ]
    )
    assert result is EnvironmentCompatibility.BLOCKED


def test_an_empty_set_is_ready_and_that_is_deliberate() -> None:
    """A registry with no checks has found nothing wrong.

    Unreachable in practice — `checks()` registers the capability check and a
    contract test asserts the registry is non-empty — and stated here so the
    vacuous case is a decision rather than an accident.
    """
    assert compatibility_of([]) is EnvironmentCompatibility.READY


def test_a_check_needs_an_identifier() -> None:
    """It reaches evidence and a runbook, so an empty one is not a check."""
    with pytest.raises(ValidationError):
        CapabilityCheck(
            identifier="",
            category=CapabilityCategory.ARCHITECTURE,
            severity=CapabilitySeverity.REQUIRED,
            status=CapabilityStatus.SUPPORTED,
        )


def test_blocking_reasons_are_bounded_deduplicated_and_sorted() -> None:
    """This is what a readiness answer and an exit message carry."""
    result = snapshot(
        check(
            "a", status=CapabilityStatus.UNSUPPORTED, reason=CapabilityReason.ARCHITECTURE_MISMATCH
        ),
        check(
            "b", status=CapabilityStatus.UNSUPPORTED, reason=CapabilityReason.ARCHITECTURE_MISMATCH
        ),
        check("c", status=CapabilityStatus.UNSUPPORTED, reason=CapabilityReason.WRONG_PLATFORM),
    )
    assert result.blocking_reasons() == (
        CapabilityReason.ARCHITECTURE_MISMATCH,
        CapabilityReason.WRONG_PLATFORM,
    )


def test_a_degrading_capability_contributes_no_blocking_reason() -> None:
    """Otherwise a report would name a cause for a refusal that did not happen."""
    assert snapshot(check(status=CapabilityStatus.UNKNOWN)).blocking_reasons() == ()


# ---------------------------------------------------------------------------
# The fingerprint
# ---------------------------------------------------------------------------


def test_the_same_environment_twice_produces_the_same_fingerprint() -> None:
    """The property the whole thing exists for."""
    first = snapshot(check()).projection()
    second = snapshot(check()).projection()
    assert compatibility_fingerprint(first) == compatibility_fingerprint(second)


def test_a_changed_status_changes_the_fingerprint() -> None:
    """The other direction, so the stability above is not vacuous."""
    healthy = snapshot(check()).projection()
    broken = snapshot(check(status=CapabilityStatus.UNSUPPORTED)).projection()
    assert compatibility_fingerprint(healthy) != compatibility_fingerprint(broken)


def test_a_changed_native_architecture_changes_the_fingerprint() -> None:
    """The architecture is part of what makes this environment the one it is."""
    here = snapshot(check()).projection()
    elsewhere = CompatibilityProjection(
        checks=(check(),),
        architecture=ArchitectureCapability(
            process=MachineArchitecture.ARM64,
            native=MachineArchitecture.ARM64,
            emulation=EmulationState.NATIVE,
        ),
    )
    assert compatibility_fingerprint(here) != compatibility_fingerprint(elsewhere)


def test_reordering_the_registry_does_not_change_the_fingerprint() -> None:
    """A phase inserting a check ahead of another must not invalidate every record.

    The canonical rendering sorts by identifier, so registry order — which is a
    dependency order and may legitimately change — is not part of the identity.
    """
    forwards = CompatibilityProjection(checks=(check("a"), check("b")), architecture=NATIVE_AMD64)
    backwards = CompatibilityProjection(checks=(check("b"), check("a")), architecture=NATIVE_AMD64)
    assert compatibility_fingerprint(forwards) == compatibility_fingerprint(backwards)


def test_the_toolchain_is_outside_the_fingerprint() -> None:
    """Installing Git changes a report without changing which environment this is.

    Every toolchain capability is optional, so a fingerprint that moved when a
    developer installed a tool would be answering a different question from the
    one it is asked.
    """
    without = EnvironmentCapabilitySnapshot(
        checks=(check(),), architecture=NATIVE_AMD64, toolchain=(("git", False),)
    )
    with_git = EnvironmentCapabilitySnapshot(
        checks=(check(),), architecture=NATIVE_AMD64, toolchain=(("git", True),)
    )
    assert compatibility_fingerprint(without.projection()) == compatibility_fingerprint(
        with_git.projection()
    )


def test_the_projection_has_no_field_for_anything_volatile() -> None:
    """The exclusion is structural, not a filter somebody must remember to extend.

    A denylist of volatile keys is a list that goes stale; this asserts the
    stronger property — the projection type has nowhere to put a timestamp, a
    process identifier or a duration, so a later phase adding one to the snapshot
    cannot thereby change a fingerprint.
    """
    fields = set(CompatibilityProjection.__dataclass_fields__)
    assert fields == {"checks", "architecture"}


def test_the_schema_is_mixed_into_the_digest() -> None:
    """So a change to the projection's meaning cannot silently compare as equal."""
    assert FINGERPRINT_SCHEMA in snapshot(check()).projection().canonical()


def test_the_fingerprint_is_the_declared_length_of_hexadecimal() -> None:
    """Published, so its shape is a contract."""
    value = compatibility_fingerprint(snapshot(check()).projection())
    assert len(value) == FINGERPRINT_LENGTH
    assert set(value) <= set("0123456789abcdef")


def test_two_projections_cannot_collide_by_concatenation() -> None:
    """Fields are joined with a character the bounded vocabularies cannot contain.

    Without a separator outside the alphabet, a check named `a` with status `bc`
    and one named `ab` with status `c` would render identically.
    """
    first = CompatibilityProjection(checks=(check("a.b"),), architecture=NATIVE_AMD64)
    second = CompatibilityProjection(checks=(check("a"), check("b")), architecture=NATIVE_AMD64)
    assert compatibility_fingerprint(first) != compatibility_fingerprint(second)


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


def test_the_record_carries_the_verdict_the_fingerprint_and_every_check() -> None:
    """What reaches evidence and the CLI."""
    record = snapshot(check()).as_record()
    assert record["compatibility"] == EnvironmentCompatibility.READY.value
    assert record["fingerprint"] == compatibility_fingerprint(snapshot(check()).projection())
    assert len(record["checks"]) == 1  # type: ignore[arg-type]


def test_the_snapshot_has_no_field_that_could_hold_a_path() -> None:
    """The privacy design, asserted on the type rather than on what a caller prints.

    A resolved executable path on this host contains the account holder's name.
    The toolchain carries names and presence, and there is no third field.
    """
    fields = set(EnvironmentCapabilitySnapshot.__dataclass_fields__)
    assert fields == {"checks", "architecture", "toolchain"}


def test_the_record_publishes_no_path_for_a_present_tool() -> None:
    """A boolean is what the probe returns, so a path cannot reach the record."""
    record = EnvironmentCapabilitySnapshot(
        checks=(check(),), architecture=NATIVE_AMD64, toolchain=(("git", True),)
    ).as_record()
    assert record["toolchain"] == [{"name": "git", "present": True}]
