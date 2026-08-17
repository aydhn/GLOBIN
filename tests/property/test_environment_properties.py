"""Invariants of the compatibility fingerprint and the store key, over generated input.

Two real invariants, each of which a hand-written example can only sample:

- The fingerprint is a **function** of the compatibility state, and of nothing
  else. Determinism and sensitivity are the two halves, and both need arbitrary
  inputs to be worth asserting — a pair of hand-picked snapshots proves the
  function distinguishes those two.
- `store_key` is **injective modulo case**. Two references differing in any part
  produce different keys; two differing only in case produce the same one, which
  is the property the platform's silent case-folding makes a correctness
  requirement rather than a nicety.
"""

import json

from hypothesis import given
from hypothesis import strategies as st

from globin.domain.environment import (
    ArchitectureCapability,
    CapabilityCategory,
    CapabilityCheck,
    CapabilityReason,
    CapabilitySeverity,
    CapabilityStatus,
    CompatibilityProjection,
    EmulationState,
    EnvironmentCapabilitySnapshot,
    MachineArchitecture,
    compatibility_fingerprint,
    compatibility_of,
)
from globin.domain.identifiers import environment_id
from globin.domain.secrets import (
    NAME_ALPHABET,
    SecretKind,
    SecretReference,
    store_key,
)

identifiers = st.text(alphabet="abcdefghijklmnopqrstuvwxyz._", min_size=1, max_size=40)
names = st.text(alphabet=NAME_ALPHABET, min_size=1, max_size=32)
environments = st.sampled_from(["paper", "demo", "testnet", "live", "production"])


@st.composite
def checks(draw: st.DrawFn) -> CapabilityCheck:
    """An arbitrary capability check."""
    return CapabilityCheck(
        identifier=draw(identifiers),
        category=draw(st.sampled_from(list(CapabilityCategory))),
        severity=draw(st.sampled_from(list(CapabilitySeverity))),
        status=draw(st.sampled_from(list(CapabilityStatus))),
        reason=draw(st.sampled_from(list(CapabilityReason))),
        observed=draw(st.text(max_size=20)),
        expected=draw(st.text(max_size=20)),
    )


@st.composite
def architectures(draw: st.DrawFn) -> ArchitectureCapability:
    """An arbitrary architecture capability."""
    return ArchitectureCapability(
        process=draw(st.sampled_from(list(MachineArchitecture))),
        native=draw(st.sampled_from(list(MachineArchitecture))),
        emulation=draw(st.sampled_from(list(EmulationState))),
    )


@st.composite
def projections(draw: st.DrawFn) -> CompatibilityProjection:
    """An arbitrary compatibility projection."""
    return CompatibilityProjection(
        checks=tuple(draw(st.lists(checks(), max_size=6))),
        architecture=draw(architectures()),
    )


@st.composite
def references(draw: st.DrawFn) -> SecretReference:
    """An arbitrary secret reference."""
    return SecretReference(
        environment=environment_id(draw(environments)),
        kind=draw(st.sampled_from(list(SecretKind))),
        name=draw(names),
    )


# ---------------------------------------------------------------------------
# The fingerprint
# ---------------------------------------------------------------------------


@given(projections())
def test_the_fingerprint_is_deterministic(projection: CompatibilityProjection) -> None:
    """Two digests of one projection agree, whatever the projection is."""
    assert compatibility_fingerprint(projection) == compatibility_fingerprint(projection)


@given(projections())
def test_the_fingerprint_is_always_the_declared_shape(
    projection: CompatibilityProjection,
) -> None:
    """It is published, so a caller may rely on its length and alphabet."""
    value = compatibility_fingerprint(projection)
    assert len(value) == 32
    assert set(value) <= set("0123456789abcdef")


@given(projections(), st.text(max_size=20), st.text(max_size=20))
def test_the_observed_and_expected_text_is_outside_the_fingerprint(
    projection: CompatibilityProjection, observed: str, expected: str
) -> None:
    """Changing a human-readable detail must not change the environment's identity.

    `observed` and `expected` carry a rendered version string or a tool's purpose
    — text that can change for editorial reasons without the host changing at
    all. A fingerprint that moved when a message was reworded would report drift
    that did not happen.
    """
    altered = CompatibilityProjection(
        checks=tuple(
            CapabilityCheck(
                identifier=check.identifier,
                category=check.category,
                severity=check.severity,
                status=check.status,
                reason=check.reason,
                observed=observed,
                expected=expected,
            )
            for check in projection.checks
        ),
        architecture=projection.architecture,
    )
    assert compatibility_fingerprint(projection) == compatibility_fingerprint(altered)


@given(projections(), st.sampled_from(list(CapabilityStatus)))
def test_changing_a_status_changes_the_fingerprint(
    projection: CompatibilityProjection, status: CapabilityStatus
) -> None:
    """The sensitivity half. Skipped where the status is already the one drawn.

    Without this the determinism property above would be satisfied by a constant
    function, which is the failure mode a stability test is most prone to.
    """
    if not projection.checks:
        return
    first = projection.checks[0]
    if first.status is status:
        return
    altered = CompatibilityProjection(
        checks=(
            CapabilityCheck(
                identifier=first.identifier,
                category=first.category,
                severity=first.severity,
                status=status,
                reason=first.reason,
            ),
            *projection.checks[1:],
        ),
        architecture=projection.architecture,
    )
    assert compatibility_fingerprint(projection) != compatibility_fingerprint(altered)


@given(st.lists(checks(), max_size=6), architectures())
def test_ordering_the_checks_does_not_change_the_fingerprint(
    drawn: list[CapabilityCheck], architecture: ArchitectureCapability
) -> None:
    """Registry order is a dependency order and may legitimately change."""
    forwards = CompatibilityProjection(checks=tuple(drawn), architecture=architecture)
    backwards = CompatibilityProjection(checks=tuple(reversed(drawn)), architecture=architecture)
    assert compatibility_fingerprint(forwards) == compatibility_fingerprint(backwards)


@given(st.lists(checks(), max_size=8), architectures())
def test_the_verdict_never_depends_on_the_order_the_checks_arrive_in(
    drawn: list[CapabilityCheck], architecture: ArchitectureCapability
) -> None:
    """A host is as fit as it is, whichever order the questions were asked in."""
    del architecture
    assert compatibility_of(drawn) is compatibility_of(list(reversed(drawn)))


@given(st.lists(checks(), max_size=8), architectures())
def test_a_snapshot_record_is_json_serialisable_and_carries_no_object(
    drawn: list[CapabilityCheck], architecture: ArchitectureCapability
) -> None:
    """The record reaches evidence, so every value in it must be a plain type."""
    record = EnvironmentCapabilitySnapshot(
        checks=tuple(drawn), architecture=architecture
    ).as_record()
    assert json.loads(json.dumps(record, allow_nan=False)) == record


# ---------------------------------------------------------------------------
# The store key
# ---------------------------------------------------------------------------


@given(references())
def test_the_store_key_is_deterministic(reference: SecretReference) -> None:
    """Section 2: identical inputs give an identical key."""
    assert store_key(reference) == store_key(reference)


@given(references())
def test_the_store_key_is_always_lowercase(reference: SecretReference) -> None:
    """The property the platform's silent case-folding makes a requirement.

    `phase_028_sources.md` S-06 measured that two target names differing only in
    case are one credential, with no error and no warning. A key that was not
    already folded would produce collisions that look like distinct entries.
    """
    assert store_key(reference) == store_key(reference).lower()


@given(references(), references())
def test_two_different_references_never_share_a_key(
    first: SecretReference, second: SecretReference
) -> None:
    """Injectivity, which is what makes the environment isolation real.

    Two references that differ in any part must address different credentials —
    otherwise a `testnet` key could resolve for `live`, which section 3 exists to
    prevent.
    """
    if first == second:
        return
    assert store_key(first) != store_key(second)


@given(references())
def test_a_key_never_contains_whitespace_or_a_control_character(
    reference: SecretReference,
) -> None:
    """It is a platform target name, and one carrying either would be unusable."""
    key = store_key(reference)
    assert key == key.strip()
    assert all(character.isprintable() for character in key)
