"""Architecture detection, driven by a fake `kernel32`, and the two traps in it.

No test here needs an ARM64 machine, a Windows release predating
`IsWow64Process2`, or a failing Win32 call. Every one arrives through a fake,
which is the only way the interesting cases are reachable at all from a native
AMD64 development host.

**Both traps are measured rather than remembered**, and
`docs/research/phase_028_sources.md` records each:

- S-01: `IMAGE_FILE_MACHINE_UNKNOWN` is `0` and means the process is **not**
  emulated. Reading it as "unknown architecture" would report every ordinary
  native host as unmeasured — including this one, on every run.
- S-02: `GetNativeSystemInfo` is documented to report an ARM64 host as x86 or
  x64, and Microsoft's own remark routes the question to `IsWow64Process2`. So
  the fallback answers the *process* question only.
"""

import ctypes
import os
from dataclasses import dataclass, field
from typing import Any

import pytest

from globin.adapters.environment import (
    _SYSTEM_INFO,
    DECLARED_TOOLCHAIN,
    IMAGE_FILE_MACHINE_UNKNOWN,
    PathToolchainProbe,
    UnavailableSystemApi,
    WindowsArchitectureApi,
    _architecture_from_wow64,
    windows_system_api,
)
from globin.domain.environment import EmulationState, MachineArchitecture

MACHINE_AMD64 = 0x8664
MACHINE_ARM64 = 0xAA64
MACHINE_X86 = 0x014C

ARCH_AMD64 = 9
ARCH_ARM64 = 12


@dataclass
class _FakeKernel32:
    """A stand-in for the architecture half of `kernel32`.

    Args:
        process_machine: What `IsWow64Process2` reports for this process.
        native_machine: What it reports for the host.
        wow64_succeeds: Whether the call returns non-zero.
        native_arch: What `GetNativeSystemInfo` reports, for the fallback path.
    """

    process_machine: int = IMAGE_FILE_MACHINE_UNKNOWN
    native_machine: int = MACHINE_AMD64
    wow64_succeeds: bool = True
    native_arch: int = ARCH_AMD64
    calls: list[str] = field(default_factory=list)

    def GetCurrentProcess(self) -> int:  # noqa: N802 -- the platform's name
        return -1

    def IsWow64Process2(self, handle: Any, process: Any, native: Any) -> int:  # noqa: N802
        del handle
        self.calls.append("IsWow64Process2")
        if not self.wow64_succeeds:
            ctypes.set_last_error(5)
            return 0
        process._obj.value = self.process_machine  # noqa: SLF001
        native._obj.value = self.native_machine  # noqa: SLF001
        return 1

    def GetNativeSystemInfo(self, info: Any) -> None:  # noqa: N802
        self.calls.append("GetNativeSystemInfo")
        info._obj.wProcessorArchitecture = self.native_arch  # noqa: SLF001


def api(*, has_wow64: bool = True, **kwargs: Any) -> WindowsArchitectureApi:
    """An architecture probe over a fake library."""
    return WindowsArchitectureApi(library=_FakeKernel32(**kwargs), has_wow64_process2=has_wow64)


# ---------------------------------------------------------------------------
# The first trap: UNKNOWN means "not emulated"
# ---------------------------------------------------------------------------


def test_a_process_machine_of_unknown_means_native_not_unmeasured() -> None:
    """S-01, and the value this host returns on every single run.

    Microsoft: "The value will be IMAGE_FILE_MACHINE_UNKNOWN if the target
    process is not a WOW64 process." A mapping written against the constant's
    *name* rather than that sentence would report every healthy native machine as
    unmeasured, permanently.
    """
    result = api(process_machine=IMAGE_FILE_MACHINE_UNKNOWN, native_machine=MACHINE_AMD64)
    architecture = result.architecture()
    assert architecture.emulation is EmulationState.NATIVE
    assert architecture.native is MachineArchitecture.AMD64
    assert architecture.process is MachineArchitecture.AMD64


def test_the_process_architecture_is_derived_from_the_native_one_when_not_emulated() -> None:
    """There is no other source for it: `pProcessMachine` carries no architecture here."""
    architecture = api(
        process_machine=IMAGE_FILE_MACHINE_UNKNOWN, native_machine=MACHINE_ARM64
    ).architecture()
    assert architecture.process is MachineArchitecture.ARM64
    assert architecture.native is MachineArchitecture.ARM64


def test_a_non_zero_process_machine_is_emulation() -> None:
    """An x64 interpreter on an ARM64 host: supported, slower, and worth reporting."""
    architecture = api(process_machine=MACHINE_AMD64, native_machine=MACHINE_ARM64).architecture()
    assert architecture.emulation is EmulationState.EMULATED
    assert architecture.process is MachineArchitecture.AMD64
    assert architecture.native is MachineArchitecture.ARM64


def test_a_32_bit_process_on_a_64_bit_host_is_emulation() -> None:
    """The classic WOW64 case, which is what the API was named for."""
    architecture = api(process_machine=MACHINE_X86, native_machine=MACHINE_AMD64).architecture()
    assert architecture.emulation is EmulationState.EMULATED
    assert architecture.process is MachineArchitecture.X86


# ---------------------------------------------------------------------------
# The second trap: the fallback must not answer the native question
# ---------------------------------------------------------------------------


def test_without_the_modern_api_the_native_architecture_is_unknown_not_guessed() -> None:
    """S-02, and the reason the plan for this phase changed.

    `GetNativeSystemInfo` is documented to report an ARM64 host as x86 or x64.
    Inheriting that answer would produce a confident, wrong classification in
    exactly the case native detection exists for — so the native machine is
    `UNKNOWN` and the emulation state with it.
    """
    architecture = api(has_wow64=False, native_arch=ARCH_AMD64).architecture()
    assert architecture.native is MachineArchitecture.UNKNOWN
    assert architecture.emulation is EmulationState.UNKNOWN


def test_the_fallback_still_answers_the_process_question() -> None:
    """It is equivalent to `GetSystemInfo` there, and correct."""
    architecture = api(has_wow64=False, native_arch=ARCH_AMD64).architecture()
    assert architecture.process is MachineArchitecture.AMD64


def test_the_modern_api_is_not_called_when_it_is_absent() -> None:
    """Calling a missing export is an `AttributeError`, not a recoverable failure."""
    probe = api(has_wow64=False)
    probe.architecture()
    assert "IsWow64Process2" not in probe.library.calls


def test_a_failed_call_falls_back_rather_than_raising() -> None:
    """A Win32 failure is an answer under ADR-0045, never an exception."""
    probe = api(wow64_succeeds=False, native_arch=ARCH_ARM64)
    architecture = probe.architecture()
    assert probe.library.calls == ["IsWow64Process2", "GetNativeSystemInfo"]
    assert architecture.native is MachineArchitecture.UNKNOWN
    assert architecture.process is MachineArchitecture.ARM64


def test_the_modern_api_makes_the_fallback_unnecessary() -> None:
    """Two sources for one fact is how they come to disagree."""
    probe = api()
    probe.architecture()
    assert probe.library.calls == ["IsWow64Process2"]


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(MACHINE_AMD64, MachineArchitecture.AMD64, id="amd64"),
        pytest.param(MACHINE_ARM64, MachineArchitecture.ARM64, id="arm64"),
        pytest.param(MACHINE_X86, MachineArchitecture.X86, id="x86"),
        pytest.param(0x01C0, MachineArchitecture.ARM, id="arm"),
        pytest.param(0x01C4, MachineArchitecture.ARM, id="armnt folds onto arm"),
        pytest.param(0x0200, MachineArchitecture.IA64, id="ia64"),
        pytest.param(0xDEAD, MachineArchitecture.UNKNOWN, id="an architecture nobody has yet"),
    ],
)
def test_every_image_file_machine_value_maps(value: int, expected: MachineArchitecture) -> None:
    """Total over an unbounded input: a future architecture is `UNKNOWN`, not a crash."""
    architecture = _architecture_from_wow64(value, MACHINE_AMD64)
    if value == IMAGE_FILE_MACHINE_UNKNOWN:
        pytest.skip("covered by the not-emulated case, where the meaning inverts")
    assert architecture.process is expected


def test_the_system_info_structure_has_the_documented_fields_in_order() -> None:
    """A wrong field width reads a neighbour rather than raising.

    The leading union is flattened to its struct arm, so `wProcessorArchitecture`
    must be first — reading it from the wrong offset would misreport every host.
    """
    assert [name for name, _type in _SYSTEM_INFO._fields_][:3] == [
        "wProcessorArchitecture",
        "wReserved",
        "dwPageSize",
    ]


def test_the_active_processor_mask_field_is_pointer_sized() -> None:
    """`DWORD_PTR` is pointer-sized, and every field after it depends on that.

    `c_size_t` replaced `POINTER(c_ulong)` to avoid a call at import. A narrower
    type would shift every subsequent field, which is precisely the silent
    corruption a structure test exists to prevent.
    """
    fields = dict(_SYSTEM_INFO._fields_)
    assert ctypes.sizeof(fields["dwActiveProcessorMask"]) == ctypes.sizeof(ctypes.c_void_p)


# ---------------------------------------------------------------------------
# The host that cannot answer at all
# ---------------------------------------------------------------------------


def test_a_host_with_no_win32_reports_unknown_rather_than_guessing_from_platform() -> None:
    """`platform.machine()` describes the process, not the host, and lies under emulation."""
    architecture = UnavailableSystemApi().architecture()
    assert architecture.native is MachineArchitecture.UNKNOWN
    assert architecture.emulation is EmulationState.UNKNOWN


def test_the_factory_returns_something_that_answers_on_any_host() -> None:
    """Whichever half this machine gets, the caller sees one shape and no exception."""
    architecture = windows_system_api().architecture()
    assert architecture.process in set(MachineArchitecture)
    assert architecture.emulation in set(EmulationState)


# ---------------------------------------------------------------------------
# The toolchain
# ---------------------------------------------------------------------------


def test_the_toolchain_probe_answers_a_boolean_and_never_a_path() -> None:
    """The privacy design: a caller cannot publish a path it was never given."""
    assert PathToolchainProbe().present("python") is True
    assert PathToolchainProbe().present("no-such-executable-anywhere") is False


def test_the_toolchain_probe_does_not_raise_when_the_lookup_itself_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable directory on somebody's `PATH` must not end a start-up.

    Every toolchain capability is optional, so a discovery that went wrong
    degrades a report and authorises nothing. Driven by making the lookup raise
    rather than by planting a malformed `PATH`, because the operating system
    refuses to store one — the `except OSError` branch is what is under test, and
    this reaches it directly.
    """

    def refuse(*args: object, **kwargs: object) -> str | None:
        del args, kwargs
        msg = "a directory on PATH could not be read"
        raise OSError(msg)

    monkeypatch.setattr("globin.adapters.environment.shutil.which", refuse)
    assert PathToolchainProbe().present("git") is False


def test_the_toolchain_probe_passes_a_mode_that_includes_execute() -> None:
    """`phase_028_sources.md` S-09, and it is a security-relevant default.

    On Windows `shutil.which` prepends the **current directory** unconditionally
    when the mode omits `os.X_OK`, and consults `NeedCurrentDirectoryForExePathW`
    when it includes it. The default already includes it; passing it explicitly
    is what stops a later edit widening the search to the working directory
    without anybody noticing.
    """
    recorded: dict[str, int] = {}

    def capture(cmd: str, mode: int = 0, path: object = None) -> str | None:
        del cmd, path
        recorded["mode"] = mode
        return None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("globin.adapters.environment.shutil.which", capture)
    try:
        PathToolchainProbe().present("git")
    finally:
        monkeypatch.undo()
    assert recorded["mode"] & os.X_OK


def test_every_declared_tool_states_why_it_is_listed() -> None:
    """A list of tools somebody might have would report on a machine, not on GLOBIN.

    The test for whether an entry belongs is that this repository actually runs
    it, and the reason field is where that is written down.
    """
    assert DECLARED_TOOLCHAIN
    for name, purpose in DECLARED_TOOLCHAIN:
        assert name == name.lower(), f"{name} is not lowercase"
        assert name, "an executable with no name"
        assert len(purpose) > 20, f"{name} is listed without saying why"


def test_pwsh_is_not_declared() -> None:
    """`phase_028_sources.md` S-10: PowerShell 7 is absent here and nothing invokes it.

    Listing it would report a shortfall against a requirement that does not
    exist, which is how an optional-capability report becomes noise people ignore.
    """
    assert "pwsh" not in {name for name, _purpose in DECLARED_TOOLCHAIN}
