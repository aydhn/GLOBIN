"""Turning what the probes reported into classified checks.

Every observation arrives as an argument or through a hand-written double, so
each classification branch is reachable from literals — an ARM64 host, a host
that cannot answer at all, and a machine with no Git are all exercised here and
none of them exists.

This file exists separately from `test_environment.py` because that one tests the
*rules* and this one tests the *mapping onto them*. The distinction earned its
own module when the two halves were measured: the domain sat at 100% while this
layer sat at 32%, reached only incidentally through the bootstrap.
"""

from dataclasses import dataclass, field

import pytest

from globin.adapters.environment import DECLARED_TOOLCHAIN
from globin.application.environment import (
    ARCHITECTURE_EMULATION,
    ARCHITECTURE_NATIVE,
    TOOLCHAIN_PREFIX,
    architecture_checks,
    snapshot_from,
    toolchain_checks,
)
from globin.domain.bootstrap import RuntimeBaseline
from globin.domain.environment import (
    ArchitectureCapability,
    CapabilityCategory,
    CapabilityCheck,
    CapabilityReason,
    CapabilitySeverity,
    CapabilityStatus,
    EmulationState,
    EnvironmentCompatibility,
    MachineArchitecture,
)

BASELINE = RuntimeBaseline(
    system="Windows",
    minimum_release="10",
    implementation="CPython",
    minor_line="3.14",
    minimum_patch="3.14.5",
    architecture="AMD64",
    pointer_bits=64,
    free_threaded=False,
    allow_prerelease=False,
    environment_directory=".venv",
)

TOOLS = (("git", "version control, used by the release and supply gates"),)


@dataclass
class _Api:
    """Supplies a fixed architecture reading."""

    value: ArchitectureCapability

    def architecture(self) -> ArchitectureCapability:
        return self.value


@dataclass
class _Toolchain:
    """Reports presence from a fixed set, and counts how often it is asked."""

    present_names: frozenset[str] = frozenset()
    asked: list[str] = field(default_factory=list)

    def present(self, executable: str) -> bool:
        self.asked.append(executable)
        return executable in self.present_names


def architecture(
    *,
    process: MachineArchitecture = MachineArchitecture.AMD64,
    native: MachineArchitecture = MachineArchitecture.AMD64,
    emulation: EmulationState = EmulationState.NATIVE,
) -> ArchitectureCapability:
    """An architecture capability, defaulting to a healthy native host."""
    return ArchitectureCapability(process=process, native=native, emulation=emulation)


def named(checks: tuple[CapabilityCheck, ...], identifier: str) -> CapabilityCheck:
    """The one check with this identifier."""
    return next(check for check in checks if check.identifier == identifier)


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------


def test_a_matching_native_architecture_is_supported() -> None:
    """The control, and the case this host is in."""
    check = named(architecture_checks(architecture(), BASELINE), ARCHITECTURE_NATIVE)
    assert check.status is CapabilityStatus.SUPPORTED
    assert check.reason is CapabilityReason.SATISFIED
    assert check.severity is CapabilitySeverity.REQUIRED


def test_a_mismatched_native_architecture_is_unsupported_and_blocks() -> None:
    """The one thing in this phase that can refuse a start."""
    checks = architecture_checks(
        architecture(process=MachineArchitecture.ARM64, native=MachineArchitecture.ARM64),
        BASELINE,
    )
    check = named(checks, ARCHITECTURE_NATIVE)
    assert check.status is CapabilityStatus.UNSUPPORTED
    assert check.reason is CapabilityReason.ARCHITECTURE_MISMATCH
    assert check.blocking


def test_an_unknown_native_architecture_is_unknown_and_does_not_block() -> None:
    """The distinction that decides whether a supported host starts.

    A host predating Windows 10 version 1709 cannot answer this question, and
    refusing to start it would treat an absent measurement as a failed one.
    """
    checks = architecture_checks(
        architecture(native=MachineArchitecture.UNKNOWN, emulation=EmulationState.UNKNOWN),
        BASELINE,
    )
    check = named(checks, ARCHITECTURE_NATIVE)
    assert check.status is CapabilityStatus.UNKNOWN
    assert check.reason is CapabilityReason.PROBE_UNAVAILABLE
    assert not check.blocking
    assert check.degrading


def test_the_declared_architecture_is_compared_case_insensitively() -> None:
    """The contract says `AMD64` and the vocabulary says `amd64`.

    Comparing them without folding would report a mismatch on a host that
    matches, which is a failure mode indistinguishable from a real one.
    """
    check = named(architecture_checks(architecture(), BASELINE), ARCHITECTURE_NATIVE)
    assert BASELINE.architecture == "AMD64"
    assert check.status is CapabilityStatus.SUPPORTED


def test_running_natively_is_supported_and_optional() -> None:
    """Optional, because emulation is a cost rather than a refusal."""
    check = named(architecture_checks(architecture(), BASELINE), ARCHITECTURE_EMULATION)
    assert check.status is CapabilityStatus.SUPPORTED
    assert check.severity is CapabilitySeverity.OPTIONAL


def test_running_emulated_is_degraded_and_names_both_architectures() -> None:
    """An x64 interpreter on an ARM64 host: correct, slower, worth reporting."""
    checks = architecture_checks(
        architecture(
            process=MachineArchitecture.AMD64,
            native=MachineArchitecture.ARM64,
            emulation=EmulationState.EMULATED,
        ),
        BASELINE,
    )
    check = named(checks, ARCHITECTURE_EMULATION)
    assert check.status is CapabilityStatus.DEGRADED
    assert check.reason is CapabilityReason.RUNNING_EMULATED
    assert "amd64" in check.observed
    assert "arm64" in check.observed


def test_an_unknown_emulation_state_is_unknown() -> None:
    """Not a synonym for native, which is the whole reason it has a member."""
    checks = architecture_checks(architecture(emulation=EmulationState.UNKNOWN), BASELINE)
    check = named(checks, ARCHITECTURE_EMULATION)
    assert check.status is CapabilityStatus.UNKNOWN


def test_both_architecture_checks_are_in_the_architecture_category() -> None:
    """Grouping in a report, and nothing branches on it."""
    for check in architecture_checks(architecture(), BASELINE):
        assert check.category is CapabilityCategory.ARCHITECTURE


# ---------------------------------------------------------------------------
# Toolchain
# ---------------------------------------------------------------------------


def test_a_present_tool_is_supported() -> None:
    """The control."""
    checks = toolchain_checks(_Toolchain(present_names=frozenset({"git"})), TOOLS)
    assert checks[0].status is CapabilityStatus.SUPPORTED
    assert checks[0].reason is CapabilityReason.SATISFIED


def test_an_absent_tool_is_unsupported_optional_and_degrades_rather_than_blocks() -> None:
    """A correctly provisioned production host must not refuse over a developer tool."""
    checks = toolchain_checks(_Toolchain(), TOOLS)
    assert checks[0].status is CapabilityStatus.UNSUPPORTED
    assert checks[0].reason is CapabilityReason.EXECUTABLE_ABSENT
    assert checks[0].severity is CapabilitySeverity.OPTIONAL
    assert not checks[0].blocking
    assert checks[0].degrading


def test_every_toolchain_check_is_optional_whatever_is_declared() -> None:
    """There is no parameter that could make one required, and this pins that."""
    checks = toolchain_checks(_Toolchain(), DECLARED_TOOLCHAIN)
    assert checks
    assert all(check.severity is CapabilitySeverity.OPTIONAL for check in checks)


def test_the_identifier_carries_the_executable_name_under_one_prefix() -> None:
    """Bounded by the declaration, so it stays a low-cardinality value."""
    checks = toolchain_checks(_Toolchain(), TOOLS)
    assert checks[0].identifier == f"{TOOLCHAIN_PREFIX}git"


def test_the_expected_field_says_why_the_tool_is_listed() -> None:
    """So an operator can judge whether its absence matters to them."""
    checks = toolchain_checks(_Toolchain(), TOOLS)
    assert checks[0].expected == TOOLS[0][1]


def test_each_executable_is_looked_up_exactly_once() -> None:
    """Two lookups could disagree, producing a check nobody could resolve.

    A tool installed or removed between a status read and a reason read would
    yield `SUPPORTED` with `EXECUTABLE_ABSENT`, or the reverse.
    """
    probe = _Toolchain(present_names=frozenset({"git"}))
    toolchain_checks(probe, TOOLS)
    assert probe.asked == ["git"]


def test_declaring_no_tools_produces_no_checks() -> None:
    """Vacuous rather than an error: a host with nothing declared has nothing missing."""
    assert toolchain_checks(_Toolchain(), ()) == ()


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def test_the_snapshot_carries_the_architecture_and_both_kinds_of_check() -> None:
    """The whole assembly, on a healthy host."""
    snapshot = snapshot_from(
        api=_Api(architecture()),
        probe=_Toolchain(present_names=frozenset({"git"})),
        baseline=BASELINE,
        declared_toolchain=TOOLS,
    )
    assert snapshot.architecture.native is MachineArchitecture.AMD64
    assert snapshot.compatibility() is EnvironmentCompatibility.READY
    assert {check.identifier for check in snapshot.checks} == {
        ARCHITECTURE_NATIVE,
        ARCHITECTURE_EMULATION,
        f"{TOOLCHAIN_PREFIX}git",
    }


def test_the_snapshot_produces_no_operating_system_or_interpreter_check() -> None:
    """The largest refusal in the phase, asserted rather than described.

    Phase 021's `checks()` already judges the host, the interpreter and the
    virtual environment against the same contract. Two verdicts about one fact is
    drift, and a reader would have no way to decide which was authoritative.
    """
    snapshot = snapshot_from(
        api=_Api(architecture()),
        probe=_Toolchain(),
        baseline=BASELINE,
        declared_toolchain=TOOLS,
    )
    categories = {check.category for check in snapshot.checks}
    assert CapabilityCategory.OPERATING_SYSTEM not in categories
    assert CapabilityCategory.INTERPRETER not in categories
    assert CapabilityCategory.VIRTUAL_ENVIRONMENT not in categories


def test_the_toolchain_summary_and_the_toolchain_checks_agree() -> None:
    """One reading feeds both, so a report cannot contradict itself."""
    snapshot = snapshot_from(
        api=_Api(architecture()),
        probe=_Toolchain(present_names=frozenset({"git"})),
        baseline=BASELINE,
        declared_toolchain=DECLARED_TOOLCHAIN,
    )
    summary = dict(snapshot.toolchain)
    for check in snapshot.checks:
        if check.identifier.startswith(TOOLCHAIN_PREFIX):
            name = check.identifier.removeprefix(TOOLCHAIN_PREFIX)
            expected = CapabilityStatus.SUPPORTED if summary[name] else CapabilityStatus.UNSUPPORTED
            assert check.status is expected


def test_each_executable_is_probed_once_across_the_whole_assembly() -> None:
    """The summary and the checks share one reading rather than taking two."""
    probe = _Toolchain(present_names=frozenset({"git"}))
    snapshot_from(
        api=_Api(architecture()),
        probe=probe,
        baseline=BASELINE,
        declared_toolchain=DECLARED_TOOLCHAIN,
    )
    assert sorted(probe.asked) == sorted(name for name, _purpose in DECLARED_TOOLCHAIN)


def test_a_host_that_cannot_answer_is_degraded_rather_than_blocked() -> None:
    """What CI's runner and every non-Windows interpreter produce."""
    snapshot = snapshot_from(
        api=_Api(
            architecture(
                process=MachineArchitecture.UNKNOWN,
                native=MachineArchitecture.UNKNOWN,
                emulation=EmulationState.UNKNOWN,
            )
        ),
        probe=_Toolchain(),
        baseline=BASELINE,
        declared_toolchain=TOOLS,
    )
    assert snapshot.compatibility() is EnvironmentCompatibility.DEGRADED
    assert snapshot.blocking_reasons() == ()


def test_a_wrong_architecture_blocks_and_names_one_bounded_reason() -> None:
    """What an exit code 24 and a readiness answer are built from."""
    snapshot = snapshot_from(
        api=_Api(architecture(process=MachineArchitecture.ARM64, native=MachineArchitecture.ARM64)),
        probe=_Toolchain(present_names=frozenset({"git"})),
        baseline=BASELINE,
        declared_toolchain=TOOLS,
    )
    assert snapshot.compatibility() is EnvironmentCompatibility.BLOCKED
    assert snapshot.blocking_reasons() == (CapabilityReason.ARCHITECTURE_MISMATCH,)


@pytest.mark.parametrize("declared", [(), TOOLS, DECLARED_TOOLCHAIN])
def test_the_snapshot_publishes_no_path_whatever_is_declared(
    declared: tuple[tuple[str, str], ...],
) -> None:
    """The privacy property, over every declaration rather than one."""
    snapshot = snapshot_from(
        api=_Api(architecture()),
        probe=_Toolchain(present_names=frozenset({"git"})),
        baseline=BASELINE,
        declared_toolchain=declared,
    )
    rendered = str(snapshot.as_record())
    assert ":\\" not in rendered
    assert "/Users/" not in rendered
