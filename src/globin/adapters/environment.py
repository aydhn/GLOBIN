r"""Reading the host's architecture and toolchain, and refusing to guess.

**This is the only module in the package that names** ``kernel32``, and
``tests/architecture/test_credential_discipline.py`` enforces that alongside the
same rule for ``advapi32`` in :mod:`globin.adapters.secrets`. The load lives
inside :func:`windows_system_api` for the reason
:func:`~globin.adapters.health.system_process_probe` puts its import inside a
function: at module scope it would run when :mod:`globin.adapters` is imported,
which the smoke test does on a non-Windows interpreter where ``WinDLL`` does not
exist at all.

**The central decision here is a refusal, and it is measured rather than
cautious.** ``phase_028_sources.md`` S-02 records Microsoft's own statement that
``GetNativeSystemInfo``, called from an x86 or x64 application on a 64-bit
system that is not Intel64 or x64 — an ARM64 machine — "will return information
as if the system is x86", and that the way to determine the truth is
``IsWow64Process2``. So:

- Where ``IsWow64Process2`` exists, it answers both questions and
  ``GetNativeSystemInfo`` is not consulted.
- Where it does not, ``GetNativeSystemInfo`` answers the **process** question
  only, and the **native** architecture is recorded as
  :attr:`~globin.domain.environment.MachineArchitecture.UNKNOWN`.

Inheriting the fallback's answer would produce a confident, wrong classification
in exactly the case the classification exists for. ADR-0045 is what makes
not-knowing cheap enough to prefer.

**The second trap is the constant's name.** ``IMAGE_FILE_MACHINE_UNKNOWN`` is
``0``, and S-01 records that Windows reports it for a process that is **not**
running under WOW64. Mapping it to ``UNKNOWN`` would report every ordinary
native host as unmeasured — and this host returns exactly that value on every
run, so the mistake would have been permanent rather than rare.
:func:`_architecture_from_wow64` reads it as "not emulated" and derives the
process architecture from the native machine.

**No path leaves this module.** :class:`PathToolchainProbe` resolves an
executable and returns a boolean; the location is discarded where it was found.
"""

import ctypes
import os
import shutil
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Final

from globin.domain.environment import (
    ArchitectureCapability,
    EmulationState,
    MachineArchitecture,
)

IMAGE_FILE_MACHINE_UNKNOWN: Final[int] = 0x0000
"""What ``IsWow64Process2`` reports for a process that is **not** emulated.

Named, and named with this docstring, because the constant's own name says the
opposite of what the value means here. ``phase_028_sources.md`` S-01 quotes the
documentation: "The value will be IMAGE_FILE_MACHINE_UNKNOWN if the target
process is not a WOW64 process."
"""

IMAGE_FILE_MACHINE: Final[tuple[tuple[int, MachineArchitecture], ...]] = (
    (0x014C, MachineArchitecture.X86),
    (0x01C0, MachineArchitecture.ARM),
    (0x01C4, MachineArchitecture.ARM),
    (0x0200, MachineArchitecture.IA64),
    (0x8664, MachineArchitecture.AMD64),
    (0xAA64, MachineArchitecture.ARM64),
)
"""The ``IMAGE_FILE_MACHINE_*`` values GLOBIN maps, as pairs.

A tuple of pairs rather than a :class:`dict` literal so that this module — like
every layer package — performs no call at import; a dict *literal* is not a
call, but the tuple form matches ``NAME_ALPHABET`` and the other declarative
constants in this repository and reads the same way.

``ARMNT`` (``0x01C4``) and ``ARM`` (``0x01C0``) both map to
:attr:`~globin.domain.environment.MachineArchitecture.ARM`: the distinction is
between instruction-set revisions of 32-bit ARM, which GLOBIN has no decision
that turns on. Deliberately **not** including ``IMAGE_FILE_MACHINE_UNKNOWN``,
because that value does not mean an architecture — see above.
"""

PROCESSOR_ARCHITECTURE: Final[tuple[tuple[int, MachineArchitecture], ...]] = (
    (0, MachineArchitecture.X86),
    (5, MachineArchitecture.ARM),
    (6, MachineArchitecture.IA64),
    (9, MachineArchitecture.AMD64),
    (12, MachineArchitecture.ARM64),
)
"""The ``PROCESSOR_ARCHITECTURE_*`` values ``GetNativeSystemInfo`` reports.

A **second** enumeration for the same concept, with different numbers — ``9`` is
AMD64 here and ``0x8664`` is AMD64 above. Both are mapped in this module and
nowhere else, so nothing upstream has to know that Windows names processor
architectures twice.
"""

DECLARED_TOOLCHAIN: Final[tuple[tuple[str, str], ...]] = (
    ("git", "version control, used by the release and supply gates"),
    ("py", "the Python launcher, used by scripts/bootstrap.ps1"),
    ("powershell", "Windows PowerShell, which runs scripts/verify.ps1"),
)
"""The executables GLOBIN's own tooling invokes, and why each is listed.

**Bounded and justified rather than a survey.** Every entry names something this
repository actually runs, which is the test for whether it belongs: a list of
tools a developer might plausibly have would report on a machine rather than on
GLOBIN's needs.

``pwsh`` is deliberately absent. ``phase_028_sources.md`` S-10 measured that
PowerShell 7 is not installed on this host while Windows PowerShell is, and
nothing here invokes ``pwsh`` — listing it would report a shortfall against a
requirement that does not exist.

Every one of these is **optional**. None is needed to run GLOBIN; each is needed
to develop or verify it, which is a different question and a different host.
"""


class _SYSTEM_INFO(ctypes.Structure):  # noqa: N801 -- the platform's own name
    """The ``SYSTEM_INFO`` structure, in the documented field order.

    The leading union is flattened to its struct arm: ``dwOemId`` overlays
    ``wProcessorArchitecture`` and ``wReserved``, and only the latter pair is
    ever read. Field widths are load-bearing — a wrong one does not raise, it
    reads a neighbouring field — so ``tests/unit/test_environment_adapter.py``
    asserts the names and count.
    """

    _fields_ = (
        ("wProcessorArchitecture", wintypes.WORD),
        ("wReserved", wintypes.WORD),
        ("dwPageSize", wintypes.DWORD),
        ("lpMinimumApplicationAddress", ctypes.c_void_p),
        ("lpMaximumApplicationAddress", ctypes.c_void_p),
        # `DWORD_PTR` is a pointer-sized unsigned integer, so `c_size_t` has the
        # right width. Spelled this way rather than as `POINTER(c_ulong)` because
        # that is a call, which a layer module may not perform at import.
        ("dwActiveProcessorMask", ctypes.c_size_t),
        ("dwNumberOfProcessors", wintypes.DWORD),
        ("dwProcessorType", wintypes.DWORD),
        ("dwAllocationGranularity", wintypes.DWORD),
        ("wProcessorLevel", wintypes.WORD),
        ("wProcessorRevision", wintypes.WORD),
    )


def _machine_from(
    table: tuple[tuple[int, MachineArchitecture], ...], value: int
) -> MachineArchitecture:
    """Map a platform integer through one of the two enumerations.

    Args:
        table: Which enumeration to read.
        value: The integer the platform reported.

    Returns:
        The architecture, or
        :attr:`~globin.domain.environment.MachineArchitecture.UNKNOWN` for a
        value not in the table.

    Total over an unbounded input by design. A new architecture appearing in a
    future Windows release becomes ``UNKNOWN`` rather than a crash, which is the
    behaviour ADR-0045 requires of an unrecognised platform answer.
    """
    for candidate, architecture in table:
        if candidate == value:
            return architecture
    return MachineArchitecture.UNKNOWN


def _architecture_from_wow64(process_machine: int, native_machine: int) -> ArchitectureCapability:
    """Classify what ``IsWow64Process2`` reported.

    Args:
        process_machine: The ``pProcessMachine`` value.
        native_machine: The ``pNativeMachine`` value.

    Returns:
        The architecture capability.

    The whole of S-01's trap is handled here. A ``process_machine`` of
    :data:`IMAGE_FILE_MACHINE_UNKNOWN` means the process is **not** running
    under WOW64 — so the process is running natively and its architecture *is*
    the native one. Any other value identifies the emulated architecture the
    process was built for, and the host is something else.
    """
    native = _machine_from(IMAGE_FILE_MACHINE, native_machine)
    if process_machine == IMAGE_FILE_MACHINE_UNKNOWN:
        return ArchitectureCapability(
            process=native,
            native=native,
            emulation=EmulationState.NATIVE,
        )
    return ArchitectureCapability(
        process=_machine_from(IMAGE_FILE_MACHINE, process_machine),
        native=native,
        emulation=EmulationState.EMULATED,
    )


@dataclass(frozen=True, slots=True)
class UnavailableSystemApi:
    """The answer on a host whose architecture cannot be read.

    Args:
        process: What is known about the process architecture, if anything.

    Returned by :func:`windows_system_api` on every non-Windows interpreter.
    Reports :attr:`~globin.domain.environment.MachineArchitecture.UNKNOWN` for
    the native architecture rather than guessing from
    :func:`platform.machine`, which describes the process rather than the host
    and would be wrong under emulation.
    """

    process: MachineArchitecture = MachineArchitecture.UNKNOWN

    def architecture(self) -> ArchitectureCapability:
        """Report what little is known.

        Returns:
            An architecture capability with an unknown native machine.
        """
        return ArchitectureCapability(
            process=self.process,
            native=MachineArchitecture.UNKNOWN,
            emulation=EmulationState.UNKNOWN,
        )


@dataclass(frozen=True, slots=True)
class WindowsArchitectureApi:
    """Architecture as ``kernel32`` reports it.

    Args:
        library: The loaded ``kernel32`` handle, injected so a test can
            substitute a fake without owning an ARM64 machine. Typed as
            :class:`~typing.Any` because ``ctypes`` gives a ``WinDLL`` no
            structural type a protocol could express.
        has_wow64_process2: Whether ``IsWow64Process2`` exists on this release.
            Probed once by the factory rather than on every call.
    """

    library: Any
    has_wow64_process2: bool

    def architecture(self) -> ArchitectureCapability:
        """Read the process and native architectures.

        Returns:
            The architecture capability, with ``UNKNOWN`` wherever this host
            cannot answer honestly.

        Two routes and one refusal, per ``phase_028_sources.md`` S-02. Where
        ``IsWow64Process2`` exists it is authoritative for both questions. Where
        it does not, ``GetNativeSystemInfo`` answers only the process question,
        because it is documented to misreport an ARM64 host — so the native
        architecture stays ``UNKNOWN`` and the emulation state with it.
        """
        if self.has_wow64_process2:
            process_machine = wintypes.USHORT(0)
            native_machine = wintypes.USHORT(0)
            ctypes.set_last_error(0)
            ok = self.library.IsWow64Process2(
                self.library.GetCurrentProcess(),
                ctypes.byref(process_machine),
                ctypes.byref(native_machine),
            )
            if ok:
                return _architecture_from_wow64(process_machine.value, native_machine.value)
        return self._from_native_system_info()

    def _from_native_system_info(self) -> ArchitectureCapability:
        """Read the process architecture only, and decline the native question.

        Returns:
            An architecture capability whose native machine is
            :attr:`~globin.domain.environment.MachineArchitecture.UNKNOWN`.

        Called when ``IsWow64Process2`` is absent or failed. The value this
        returns describes what the *process* sees, which on an ARM64 host is
        documented to be the emulated architecture rather than the real one —
        so it is recorded as the process architecture, which is what it is, and
        nothing is claimed about the machine.
        """
        info = _SYSTEM_INFO()
        self.library.GetNativeSystemInfo(ctypes.byref(info))
        return ArchitectureCapability(
            process=_machine_from(PROCESSOR_ARCHITECTURE, int(info.wProcessorArchitecture)),
            native=MachineArchitecture.UNKNOWN,
            emulation=EmulationState.UNKNOWN,
        )


@dataclass(frozen=True, slots=True)
class PathToolchainProbe:
    """Executable discovery through ``PATH`` and ``PATHEXT``.

    Resolves with :func:`shutil.which` and returns a boolean, discarding the
    location where it was found. ``phase_028_sources.md`` S-09 records why the
    mode is passed explicitly: on Windows ``which`` prepends the **current
    directory** unconditionally when the mode omits :data:`os.X_OK`, and
    consults ``NeedCurrentDirectoryForExePathW`` when it includes it. The
    default already includes it — measured — and it is spelled out anyway so
    that a later edit cannot silently widen the search to the working directory.
    """

    def present(self, executable: str) -> bool:
        """Whether an executable resolves on this host.

        Args:
            executable: The command name, without an extension.

        Returns:
            ``True`` when it resolves.

        Never raises. :func:`shutil.which` returns ``None`` rather than raising
        for an absent name, and an ``OSError`` from a malformed ``PATH`` entry
        is caught here because an unreadable directory on somebody's ``PATH``
        must not be able to end a start-up over an optional tool.
        """
        try:
            return shutil.which(executable, mode=os.F_OK | os.X_OK) is not None
        except OSError:
            return False


def windows_system_api() -> WindowsArchitectureApi | UnavailableSystemApi:
    """Build the architecture probe this host can offer.

    Returns:
        A ``kernel32``-backed probe where the library loads, and one that
        records the platform's absence where it does not.

    The presence of ``IsWow64Process2`` is probed **here, once**, with
    :func:`hasattr` — which on a ``WinDLL`` performs the ``GetProcAddress``
    lookup and raises :class:`AttributeError` when the export is missing. The
    function arrived in Windows 10 version 1709 (``phase_028_sources.md``
    S-01) and ``runtime-contract.toml`` declares a floor of Windows "10" with no
    build component, so a supported host genuinely may not have it.

    The platform check is :data:`sys.platform` rather than a ``try``/``except``
    around the load, because ``ctypes.WinDLL`` does not exist as an attribute on
    non-Windows CPython — reaching for it there raises
    :class:`AttributeError`, not :class:`OSError`.
    """
    if sys.platform != "win32":
        return UnavailableSystemApi()
    try:
        library = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:
        return UnavailableSystemApi()
    has_wow64_process2 = hasattr(library, "IsWow64Process2")
    if has_wow64_process2:
        library.IsWow64Process2.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.USHORT),
            ctypes.POINTER(wintypes.USHORT),
        )
        library.IsWow64Process2.restype = wintypes.BOOL
    library.GetNativeSystemInfo.argtypes = (ctypes.POINTER(_SYSTEM_INFO),)
    library.GetNativeSystemInfo.restype = None
    library.GetCurrentProcess.argtypes = ()
    library.GetCurrentProcess.restype = wintypes.HANDLE
    return WindowsArchitectureApi(library=library, has_wow64_process2=has_wow64_process2)
