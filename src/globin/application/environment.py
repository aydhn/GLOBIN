"""Assembling the environment capability snapshot from what the probes report.

This module sequences the reads and turns each into a
:class:`~globin.domain.environment.CapabilityCheck`. It performs no I/O itself —
every observation arrives as an argument or through a port — which is what lets
the whole classification be tested from literals, including hosts that do not
exist.

**It reuses rather than re-derives.** The operating system, the interpreter and
the virtual environment are already observed by
:mod:`globin.adapters.bootstrap` and already judged against
``docs/engineering/runtime-contract.toml`` by
:mod:`globin.domain.bootstrap`. Building a second reader of that contract would
be the drift ``SOURCE_OF_TRUTH.md`` exists to prevent, so
:func:`snapshot_from` takes the facts Phase 021 already gathers and adds only
what nothing else measures: the architecture split, the toolchain, and the
fingerprint.

**Nothing here is required except what a start-up genuinely needs.** The
architecture checks are required; every toolchain check is optional. That is not
a hedge — ``phase_028_sources.md`` S-10 measured that PowerShell 7 is absent on
the development host, and a required-toolchain model would have blocked a start
over a tool nothing runs.
"""

from globin.domain.bootstrap import RuntimeBaseline
from globin.domain.environment import (
    ArchitectureCapability,
    CapabilityCategory,
    CapabilityCheck,
    CapabilityReason,
    CapabilitySeverity,
    CapabilityStatus,
    EmulationState,
    EnvironmentCapabilitySnapshot,
    MachineArchitecture,
)
from globin.ports.environment import ToolchainProbe, WindowsSystemApi

ARCHITECTURE_NATIVE: str = "environment.architecture.native"
"""Identifier of the check asking whether the host's architecture is known and supported."""

ARCHITECTURE_EMULATION: str = "environment.architecture.emulation"
"""Identifier of the check asking whether this process runs natively."""

TOOLCHAIN_PREFIX: str = "environment.toolchain."
"""What every toolchain check's identifier begins with.

A prefix rather than a fixed set, because the identifier carries the executable
name — which is bounded by :data:`~globin.adapters.environment.DECLARED_TOOLCHAIN`
and therefore still a low-cardinality value, as ADR-0068 requires of anything
that could reach a metric attribute.
"""


def architecture_checks(
    architecture: ArchitectureCapability, baseline: RuntimeBaseline
) -> tuple[CapabilityCheck, ...]:
    """Judge what the architecture probe reported.

    Args:
        architecture: What the process and the host run on.
        baseline: The declared contract, for the architecture it requires.

    Returns:
        Two checks: whether the native architecture is the declared one, and
        whether this process runs natively on it.

    **An unknown native architecture is `UNKNOWN`, never `UNSUPPORTED`.** The
    distinction decides whether a host starts: ``UNSUPPORTED`` on a required
    capability blocks, and ``UNKNOWN`` degrades. ``phase_028_sources.md`` S-02
    records that a host predating Windows 10 version 1709 cannot answer the
    native question at all, and refusing to start such a host over an
    unanswerable question would be treating an absent measurement as a failed
    one — the mistake ADR-0045 exists to prevent.

    **Emulation is `DEGRADED`, not `UNSUPPORTED`.** An x64 interpreter on an
    ARM64 host runs correctly and more slowly. That is worth reporting and is
    not worth refusing, and the two checks are separate so that a report can say
    which of the two situations a host is in.
    """
    declared = baseline.architecture.strip().lower()
    native = architecture.native

    if native is MachineArchitecture.UNKNOWN:
        native_check = CapabilityCheck(
            identifier=ARCHITECTURE_NATIVE,
            category=CapabilityCategory.ARCHITECTURE,
            severity=CapabilitySeverity.REQUIRED,
            status=CapabilityStatus.UNKNOWN,
            reason=CapabilityReason.PROBE_UNAVAILABLE,
            observed=MachineArchitecture.UNKNOWN.value,
            expected=declared,
        )
    elif native.value == declared:
        native_check = CapabilityCheck(
            identifier=ARCHITECTURE_NATIVE,
            category=CapabilityCategory.ARCHITECTURE,
            severity=CapabilitySeverity.REQUIRED,
            status=CapabilityStatus.SUPPORTED,
            observed=native.value,
            expected=declared,
        )
    else:
        native_check = CapabilityCheck(
            identifier=ARCHITECTURE_NATIVE,
            category=CapabilityCategory.ARCHITECTURE,
            severity=CapabilitySeverity.REQUIRED,
            status=CapabilityStatus.UNSUPPORTED,
            reason=CapabilityReason.ARCHITECTURE_MISMATCH,
            observed=native.value,
            expected=declared,
        )

    if architecture.emulation is EmulationState.NATIVE:
        emulation_check = CapabilityCheck(
            identifier=ARCHITECTURE_EMULATION,
            category=CapabilityCategory.ARCHITECTURE,
            severity=CapabilitySeverity.OPTIONAL,
            status=CapabilityStatus.SUPPORTED,
            observed=EmulationState.NATIVE.value,
            expected=EmulationState.NATIVE.value,
        )
    elif architecture.emulation is EmulationState.EMULATED:
        emulation_check = CapabilityCheck(
            identifier=ARCHITECTURE_EMULATION,
            category=CapabilityCategory.ARCHITECTURE,
            severity=CapabilitySeverity.OPTIONAL,
            status=CapabilityStatus.DEGRADED,
            reason=CapabilityReason.RUNNING_EMULATED,
            observed=f"{architecture.process.value} on {architecture.native.value}",
            expected=EmulationState.NATIVE.value,
        )
    else:
        emulation_check = CapabilityCheck(
            identifier=ARCHITECTURE_EMULATION,
            category=CapabilityCategory.ARCHITECTURE,
            severity=CapabilitySeverity.OPTIONAL,
            status=CapabilityStatus.UNKNOWN,
            reason=CapabilityReason.PROBE_UNAVAILABLE,
            observed=EmulationState.UNKNOWN.value,
            expected=EmulationState.NATIVE.value,
        )
    return (native_check, emulation_check)


def toolchain_checks(
    probe: ToolchainProbe, declared: tuple[tuple[str, str], ...]
) -> tuple[CapabilityCheck, ...]:
    """Ask whether each declared executable is present.

    Args:
        probe: How to look one up.
        declared: The executables and the reason each is listed.

    Returns:
        One optional check per declared executable, in declaration order.

    Every check is :attr:`~globin.domain.environment.CapabilitySeverity.OPTIONAL`
    and there is deliberately no way to declare a required one. GLOBIN itself
    invokes none of these at run time — they are what *developing and verifying*
    GLOBIN needs — so a required toolchain would make a correctly provisioned
    production host refuse to start.

    The ``expected`` field carries the declared reason rather than the word
    "present", so a report says *why* the tool is listed and an operator can
    judge whether its absence matters to them.

    **Each executable is looked up exactly once.** Calling the probe twice —
    once for the status and once for the reason — would let a tool installed or
    removed between the two calls produce a check whose status and reason
    disagree, which is a contradiction no reader could resolve.
    """
    return tuple(
        _toolchain_check(name, purpose, present=probe.present(name)) for name, purpose in declared
    )


def _toolchain_check(name: str, purpose: str, *, present: bool) -> CapabilityCheck:
    """Build one toolchain check from a single presence reading.

    Args:
        name: The executable's name.
        purpose: Why GLOBIN's tooling lists it.
        present: What the probe answered, read once.

    Returns:
        The check.
    """
    return CapabilityCheck(
        identifier=f"{TOOLCHAIN_PREFIX}{name}",
        category=CapabilityCategory.TOOLCHAIN,
        severity=CapabilitySeverity.OPTIONAL,
        status=CapabilityStatus.SUPPORTED if present else CapabilityStatus.UNSUPPORTED,
        reason=CapabilityReason.SATISFIED if present else CapabilityReason.EXECUTABLE_ABSENT,
        observed=name,
        expected=purpose,
    )


def snapshot_from(
    *,
    api: WindowsSystemApi,
    probe: ToolchainProbe,
    baseline: RuntimeBaseline,
    declared_toolchain: tuple[tuple[str, str], ...],
) -> EnvironmentCapabilitySnapshot:
    """Assemble the whole capability snapshot.

    Args:
        api: The architecture probe.
        probe: The toolchain probe.
        baseline: The declared runtime contract.
        declared_toolchain: Which executables to look for, and why.

    Returns:
        The snapshot, from which a compatibility verdict and a fingerprint
        follow.

    **The operating system, the interpreter and the virtual environment are
    deliberately absent from this snapshot.** Phase 021's
    :func:`~globin.domain.bootstrap.checks` already judges all three against the
    same ``runtime-contract.toml`` and already refuses a wrong host fail-closed.
    Producing a second verdict about one fact is the drift
    ``SOURCE_OF_TRUTH.md`` exists to prevent, and it would be worse than
    ordinary duplication here because the two could disagree — a reader would
    have no way to decide which was authoritative.

    What this adds is what nothing else measures: the split between process and
    native architecture, the toolchain, and a fingerprint over the result. The
    snapshot is a *supplement* to the bootstrap report, not a replacement, and
    :func:`~globin.domain.bootstrap.checks` is where the two meet.

    The toolchain is probed once per executable and the readings are shared
    between the checks and the summary, so a report cannot contain two
    disagreeing answers about one tool.
    """
    architecture = api.architecture()
    toolchain = tuple((name, probe.present(name)) for name, _purpose in declared_toolchain)
    presence = dict(toolchain)
    checks = (
        *architecture_checks(architecture, baseline),
        *(
            _toolchain_check(name, purpose, present=presence[name])
            for name, purpose in declared_toolchain
        ),
    )
    return EnvironmentCapabilitySnapshot(
        checks=checks,
        architecture=architecture,
        toolchain=toolchain,
    )
