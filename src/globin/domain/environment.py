"""What GLOBIN needs of a host, how a shortfall is classified, and what is stable about it.

This module holds the judgement and none of the observation. Every function here
takes facts and returns a verdict, so a 32-bit interpreter, an ARM64 host under
emulation and a machine with no Git are all testable from literals and none of
them has to exist. Reading the host is :mod:`globin.adapters.environment`'s job.

**Five statuses rather than a boolean, and the fifth is the one that earns its
place.** ADR-0045 made a platform capability a recorded *state* rather than a
pass, and this applies the same rule to an environment:
:attr:`CapabilityStatus.UNKNOWN` means the question could not be answered, which
is different from :attr:`CapabilityStatus.UNSUPPORTED` meaning it was answered
badly. ``phase_028_sources.md`` S-02 is why that distinction is load-bearing
here rather than decorative — the fallback for native architecture is documented
to return a *wrong* answer on ARM64, so GLOBIN records `UNKNOWN` instead of
inheriting it.

**Required and optional are a type, not a convention.** A host missing Git is
not a host that must refuse to start, and a host whose interpreter is a
different minor line is. :func:`compatibility_of` folds the two into
:class:`EnvironmentCompatibility`, and only a failed *required* capability
reaches :attr:`EnvironmentCompatibility.BLOCKED`.

**The fingerprint cannot see a volatile field, because it is not given one.**
:func:`compatibility_fingerprint` takes a :class:`CompatibilityProjection`,
which carries no timestamp, no process identifier, no duration, no temporary
name and no absolute path — not because those are filtered out but because the
type has nowhere to put them. A fingerprint that excluded volatile fields by
*filtering* would silently start including one the day somebody added a field to
the snapshot; this one fails to compile instead.

What this module does not decide: which checks exist (that is
:func:`capabilities`, which is a registry a later phase adds to), what a
credential is (:mod:`globin.domain.secrets`), or what the wider health-check
suite a long-running process needs looks like (Phase 030).
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.errors import ValidationError

FINGERPRINT_LENGTH: Final[int] = 32
"""How many hexadecimal characters of the digest identify a compatibility state.

Thirty-two, which is half a SHA-256. Long enough that two genuinely different
environments will not collide, short enough to read aloud and to fit in a log
line. The full digest is available to anything that wants it; this is what gets
published.
"""

FINGERPRINT_SCHEMA: Final[str] = "globin.environment.compatibility.1"
"""What the fingerprint is a fingerprint *of*.

Mixed into the digest, so that a change to the projection's meaning produces
different fingerprints rather than silently comparing two things that were never
the same. The trailing number is the schema version and moves when the
projection's shape changes — the same rule
``docs/SERIALIZATION_POLICY.md`` sets for an envelope, applied to a digest.
"""


class CapabilityStatus(StrEnum):
    """What was concluded about one capability.

    Five members, and the split between the last three is what stops this
    collapsing into a boolean with extra steps:

    - :attr:`SUPPORTED` — measured, and it is what GLOBIN needs.
    - :attr:`UNSUPPORTED` — measured, and it is not.
    - :attr:`DEGRADED` — measured, usable, and worse than intended. A host that
      can start but should be fixed.
    - :attr:`UNKNOWN` — **not** measured. The probe was unavailable, the API was
      absent, or the only available answer is documented to be wrong. Never a
      synonym for "no".
    - :attr:`NOT_APPLICABLE` — the question does not arise on this host, which
      is how a Windows-only capability reports on a non-Windows interpreter
      without claiming a failure.
    """

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class CapabilitySeverity(StrEnum):
    """Whether GLOBIN may start without this capability.

    Two members and no third. A "recommended" tier would be a third thing that
    neither blocks nor is ignorable, and every caller would have to decide what
    it meant — which is how a severity axis stops meaning anything.
    """

    REQUIRED = "required"
    OPTIONAL = "optional"


class CapabilityCategory(StrEnum):
    """Which part of the host a capability describes.

    Used for grouping in a report and for nothing else. No logic branches on a
    category, because a category that changed behaviour would be a severity
    wearing a different name.
    """

    OPERATING_SYSTEM = "operating_system"
    INTERPRETER = "interpreter"
    VIRTUAL_ENVIRONMENT = "virtual_environment"
    ARCHITECTURE = "architecture"
    TOOLCHAIN = "toolchain"
    FILESYSTEM = "filesystem"


class CapabilityReason(StrEnum):
    """Why a capability is not simply supported.

    Bounded, and the bound is the point: these values reach a metric attribute
    and a readiness answer, so a free-text reason would be unbounded cardinality
    and a way for a path or a version string to escape into a label.
    ADR-0068's rule about attribute value sets is what this is obeying.

    :attr:`SATISFIED` is a member rather than ``None`` so that every check
    carries a reason and no caller has to handle the absent case.
    """

    SATISFIED = "satisfied"
    WRONG_PLATFORM = "wrong_platform"
    RELEASE_TOO_OLD = "release_too_old"
    IMPLEMENTATION_MISMATCH = "implementation_mismatch"
    VERSION_MISMATCH = "version_mismatch"
    ARCHITECTURE_MISMATCH = "architecture_mismatch"
    POINTER_WIDTH_MISMATCH = "pointer_width_mismatch"
    RUNNING_EMULATED = "running_emulated"
    PROBE_UNAVAILABLE = "probe_unavailable"
    PROBE_FAILED = "probe_failed"
    OUTSIDE_VIRTUAL_ENVIRONMENT = "outside_virtual_environment"
    WRONG_VIRTUAL_ENVIRONMENT = "wrong_virtual_environment"
    SYSTEM_SITE_PACKAGES_ENABLED = "system_site_packages_enabled"
    CONFIGURATION_UNREADABLE = "configuration_unreadable"
    EXECUTABLE_ABSENT = "executable_absent"
    PATH_UNUSABLE = "path_unusable"


class MachineArchitecture(StrEnum):
    """A processor architecture, as GLOBIN names it.

    A bounded vocabulary rather than the platform's integers, so that nothing
    above the adapter has to know an ``IMAGE_FILE_MACHINE_*`` value or a
    ``PROCESSOR_ARCHITECTURE_*`` one, and so that the two Windows enumerations —
    which use different numbers for the same architectures — meet in one place.

    :attr:`UNKNOWN` is a real member and is what an unmappable value becomes. It
    is never inferred: ``phase_028_sources.md`` S-01 records that Windows
    reports ``IMAGE_FILE_MACHINE_UNKNOWN`` for a process that is *not* emulated,
    which is the opposite of not knowing, and the adapter is what keeps those
    two apart.
    """

    AMD64 = "amd64"
    ARM64 = "arm64"
    X86 = "x86"
    ARM = "arm"
    IA64 = "ia64"
    UNKNOWN = "unknown"


class EmulationState(StrEnum):
    """Whether this process is running on the architecture it was built for.

    Three members. :attr:`UNKNOWN` is not a failure and not a synonym for
    :attr:`NATIVE`: ``phase_028_sources.md`` S-02 records that the only fallback
    available when ``IsWow64Process2`` is absent is *documented to answer wrongly*
    on ARM64, so a host that cannot run that function records not knowing rather
    than inheriting a wrong answer.
    """

    NATIVE = "native"
    EMULATED = "emulated"
    UNKNOWN = "unknown"


class EnvironmentCompatibility(StrEnum):
    """Whether this host may run GLOBIN.

    Three members, ordered by severity in :func:`compatibility_of`.
    :attr:`BLOCKED` is reached only by a failed *required* capability, which is
    what stops an absent developer tool from refusing a production start.
    """

    READY = "ready"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True, order=True)
class CapabilityCheck:
    """One question asked of the host, and the answer.

    Args:
        identifier: A stable dotted name, unique across the registry.
        category: Which part of the host this describes.
        severity: Whether GLOBIN may start without it.
        status: What was concluded.
        reason: Why, bounded.
        observed: What was seen, already safe to publish.
        expected: What was wanted, already safe to publish.

    ``observed`` and ``expected`` are **strings that have already been made
    safe**, not raw values awaiting redaction. That ordering is deliberate and
    matches ADR-0048's rule that redaction happens while the record is
    constructed rather than at a sink: a path is turned into a token or a
    fingerprint by the adapter that read it, so no absolute path is ever
    representable here and none can leak by being forgotten downstream.

    Ordering is derived so a set of checks renders deterministically, which the
    fingerprint depends on.
    """

    identifier: str
    category: CapabilityCategory
    severity: CapabilitySeverity
    status: CapabilityStatus
    reason: CapabilityReason = CapabilityReason.SATISFIED
    observed: str = ""
    expected: str = ""

    def __post_init__(self) -> None:
        """Validate the identifier.

        Raises:
            ValidationError: If the identifier is empty.
        """
        if not self.identifier:
            msg = "a capability check needs an identifier"
            raise ValidationError(msg)

    @property
    def blocking(self) -> bool:
        """Whether this check on its own prevents a start.

        Returns:
            ``True`` for a required capability that was measured and found
            wanting.

        :attr:`CapabilityStatus.UNKNOWN` is deliberately **not** blocking. A
        capability that could not be measured has not been shown to be absent,
        and refusing to start over an unmeasurable optional API would make a
        supported host unusable — the failure ADR-0045 named when it made
        absence a state. It reaches :attr:`EnvironmentCompatibility.DEGRADED`
        instead, which is visible without being fatal.
        """
        return (
            self.severity is CapabilitySeverity.REQUIRED
            and self.status is CapabilityStatus.UNSUPPORTED
        )

    @property
    def degrading(self) -> bool:
        """Whether this check makes the host worse than intended without stopping it.

        Returns:
            ``True`` for a degraded result, an unmeasured one, or an optional
            capability that is absent.
        """
        if self.status is CapabilityStatus.DEGRADED:
            return True
        if self.status is CapabilityStatus.UNKNOWN:
            return True
        return (
            self.severity is CapabilitySeverity.OPTIONAL
            and self.status is CapabilityStatus.UNSUPPORTED
        )

    def as_record(self) -> dict[str, object]:
        """This check as the mapping a report carries.

        Returns:
            Every field, all of them already safe to publish.
        """
        return {
            "identifier": self.identifier,
            "category": self.category.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "reason": self.reason.value,
            "observed": self.observed,
            "expected": self.expected,
        }


@dataclass(frozen=True, slots=True)
class ArchitectureCapability:
    """What this process runs on, and what the machine underneath it is.

    Args:
        process: The architecture this process was built for.
        native: The architecture of the host.
        emulation: Whether the two differ.

    Two architectures rather than one, because they can differ and the
    difference matters: an x64 interpreter on an ARM64 host runs under
    emulation, which is supported, slower, and invisible to
    :func:`platform.machine`. ``phase_028_sources.md`` S-01 and S-02 record how
    each is obtained and why only one API can answer the second honestly.
    """

    process: MachineArchitecture = MachineArchitecture.UNKNOWN
    native: MachineArchitecture = MachineArchitecture.UNKNOWN
    emulation: EmulationState = EmulationState.UNKNOWN

    def as_record(self) -> dict[str, object]:
        """This architecture as the mapping a report carries.

        Returns:
            The three values, all bounded.
        """
        return {
            "process": self.process.value,
            "native": self.native.value,
            "emulation": self.emulation.value,
        }


@dataclass(frozen=True, slots=True)
class CompatibilityProjection:
    """Everything the fingerprint is computed over, and nothing else.

    Args:
        checks: The capability checks, in registry order.
        architecture: What this process and this host are.

    **This type is the volatile-field exclusion.** It is not a filtered view of
    a snapshot; it is a separate type that has no field for a timestamp, a
    process identifier, a duration, a temporary name or an absolute path. A
    later phase that adds a volatile field to
    :class:`EnvironmentCapabilitySnapshot` cannot thereby change a fingerprint,
    because the field has nowhere to go here and
    :func:`compatibility_fingerprint` accepts nothing else.

    The alternative — hashing a snapshot minus a denylist of volatile keys — was
    rejected for the reason ``SOURCE_OF_TRUTH.md`` gives about second copies: the
    denylist is a list somebody must remember to extend, and the failure when
    they do not is a fingerprint that changes on every run and is therefore
    useless for exactly the comparison it exists to serve.
    """

    checks: tuple[CapabilityCheck, ...]
    architecture: ArchitectureCapability

    def canonical(self) -> str:
        """Render this projection as the exact text the digest is taken over.

        Returns:
            A deterministic, sorted, newline-delimited rendering.

        Sorted by identifier rather than left in registry order, so that
        reordering the registry does not change the fingerprint of an
        unchanged environment. Fields are joined with a character the bounded
        vocabularies cannot contain, so two different projections cannot render
        identically by concatenation.
        """
        lines = [FINGERPRINT_SCHEMA]
        lines.extend(
            "\x1f".join(
                (
                    check.identifier,
                    check.category.value,
                    check.severity.value,
                    check.status.value,
                    check.reason.value,
                )
            )
            for check in sorted(self.checks)
        )
        lines.append(
            "\x1f".join(
                (
                    self.architecture.process.value,
                    self.architecture.native.value,
                    self.architecture.emulation.value,
                )
            )
        )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class EnvironmentCapabilitySnapshot:
    """The whole of what GLOBIN knows about this host's fitness.

    Args:
        checks: Every capability check performed.
        architecture: What this process and this host are.
        toolchain: Which declared tools were found, by name only.

    ``toolchain`` carries **names and presence, never paths**. A resolved
    executable path on this host contains the account holder's name, and
    ``tools/quality/runtime/plan.py`` already established the rule that a path
    outside the repository is recorded as a fingerprint or not at all. Here
    there is no third option because there is no field for one.

    ``architecture`` is **required and has no default**, for the reason
    :attr:`~globin.domain.configuration.GlobinConfig.logging` has none: a
    default would be either ``field(default_factory=...)`` or a nested dataclass
    instance, and both are calls in a class body that
    ``tests/architecture/test_architecture_contract.py`` forbids a layer package
    from performing at import. The constraint produces the better design anyway
    — a snapshot that defaulted its architecture could claim
    :attr:`MachineArchitecture.UNKNOWN` without anything having tried to
    measure it.
    """

    checks: tuple[CapabilityCheck, ...]
    architecture: ArchitectureCapability
    toolchain: tuple[tuple[str, bool], ...] = ()

    def projection(self) -> CompatibilityProjection:
        """The stable part of this snapshot.

        Returns:
            A projection carrying the checks and the architecture.

        The toolchain is **excluded from the fingerprint** deliberately. Every
        toolchain capability is optional, so installing Git changes what a
        report says without changing whether this environment is the one GLOBIN
        was verified against — and a fingerprint that moved when a developer
        installed a tool would be answering a different question from the one it
        is asked.
        """
        return CompatibilityProjection(checks=self.checks, architecture=self.architecture)

    def compatibility(self) -> EnvironmentCompatibility:
        """Reduce this snapshot to one verdict.

        Returns:
            The compatibility.
        """
        return compatibility_of(self.checks)

    def blocking_reasons(self) -> tuple[CapabilityReason, ...]:
        """The bounded reasons that prevent a start, sorted and deduplicated.

        Returns:
            One entry per distinct reason, empty when nothing blocks.

        Bounded and deduplicated because this is what a readiness answer and an
        exit-code message carry, and a caller that wanted the detail has the
        checks themselves.
        """
        return tuple(sorted({check.reason for check in self.checks if check.blocking}))

    def as_record(self) -> dict[str, object]:
        """This snapshot as the mapping the evidence carries.

        Returns:
            The verdict, the fingerprint, the architecture, the toolchain and
            every check.
        """
        return {
            "compatibility": self.compatibility().value,
            "fingerprint": compatibility_fingerprint(self.projection()),
            "architecture": self.architecture.as_record(),
            "toolchain": [{"name": name, "present": present} for name, present in self.toolchain],
            "checks": [check.as_record() for check in self.checks],
            "blocking_reasons": [reason.value for reason in self.blocking_reasons()],
        }


def compatibility_of(checks: Sequence[CapabilityCheck]) -> EnvironmentCompatibility:
    """Fold a set of checks into one verdict.

    Args:
        checks: The checks to reduce.

    Returns:
        :attr:`~EnvironmentCompatibility.BLOCKED` if any required capability was
        measured and found unsupported, otherwise
        :attr:`~EnvironmentCompatibility.DEGRADED` if anything is degraded,
        unmeasured or an absent optional, otherwise
        :attr:`~EnvironmentCompatibility.READY`.

    An empty set is :attr:`~EnvironmentCompatibility.READY`, and that is
    deliberate rather than an oversight: a registry with no checks has found
    nothing wrong. It is also unreachable in practice, because
    :func:`~globin.domain.bootstrap.checks` registers the environment checks and
    a contract test asserts the registry is non-empty.
    """
    if any(check.blocking for check in checks):
        return EnvironmentCompatibility.BLOCKED
    if any(check.degrading for check in checks):
        return EnvironmentCompatibility.DEGRADED
    return EnvironmentCompatibility.READY


def compatibility_fingerprint(projection: CompatibilityProjection) -> str:
    """Digest a projection into a stable identifier.

    Args:
        projection: The stable part of a snapshot.

    Returns:
        The first :data:`FINGERPRINT_LENGTH` hexadecimal characters of the
        SHA-256 of the canonical rendering.

    Two runs on an unchanged host produce the same value; a run after the
    interpreter's minor line changed, or after a required capability started
    failing, produces a different one. A run that merely happened at a different
    time, in a different process, or took a different number of milliseconds
    produces the same one — not because those are filtered but because
    :class:`CompatibilityProjection` cannot carry them.

    SHA-256 rather than a shorter hash because every other digest in this
    repository is SHA-256, and a second algorithm would be a second thing to
    reason about for no gain.
    """
    digest = hashlib.sha256(projection.canonical().encode("utf-8")).hexdigest()
    return digest[:FINGERPRINT_LENGTH]
