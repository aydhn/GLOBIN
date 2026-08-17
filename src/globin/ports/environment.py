"""The contracts through which GLOBIN learns what host it is running on.

Two protocols, split by *source of truth* in the way
:mod:`globin.ports.bootstrap` describes. :class:`WindowsSystemApi` wraps calls
into the operating system's own libraries; :class:`ToolchainProbe` asks the
filesystem and ``PATH`` what executables exist. Substituting either is how a
test proves that an ARM64 host under emulation is classified correctly without
owning an ARM64 host.

**Neither protocol raises, and neither returns a path.**

Not raising is ADR-0045's rule: a Windows API that is absent on this release, a
call that failed, and a tool that is not installed are three *answers*, and each
arrives as a value. An implementation that raised would push the classification
out to :mod:`globin.application.environment`, which is exactly where it would be
got wrong — and would make an absent optional tool capable of ending a start-up.

Not returning a path is the privacy rule ``tools/quality/runtime/plan.py``
already states about its own manifest: on this host every absolute path outside
the repository contains the account holder's full name.
:meth:`ToolchainProbe.present` therefore answers a **boolean**, and the
resolved location is discarded inside the adapter rather than travelling up and
being redacted later. There is no method here that could return a path, so
there is no code path that has to remember not to.
"""

from typing import Protocol

from globin.domain.environment import ArchitectureCapability


class WindowsSystemApi(Protocol):
    """The operating system's answers about processor architecture."""

    def architecture(self) -> ArchitectureCapability:
        """Report what this process and this host run on.

        Returns:
            The process architecture, the native architecture and whether the
            two differ. Any of the three may be
            :attr:`~globin.domain.environment.MachineArchitecture.UNKNOWN` or
            :attr:`~globin.domain.environment.EmulationState.UNKNOWN` when the
            question could not be answered honestly.

        **A wrong answer is worse than no answer here**, and the implementation
        is required to prefer ``UNKNOWN``. ``phase_028_sources.md`` S-02 records
        that ``GetNativeSystemInfo`` — the only fallback available when
        ``IsWow64Process2`` is absent — is documented to report an ARM64 host as
        x86 or x64, which is wrong in precisely the case this method exists to
        detect.
        """
        ...


class ToolchainProbe(Protocol):
    """Whether a named executable can be found on this host."""

    def present(self, executable: str) -> bool:
        """Report whether an executable resolves.

        Args:
            executable: The command name, without an extension. The
                implementation applies the platform's own extension rules.

        Returns:
            ``True`` when it resolves, ``False`` otherwise.

        Returns a boolean rather than a location, and that is the whole of the
        privacy design for this probe: a caller cannot publish a path it was
        never given.

        Never raises, including for a name that resolves to something
        unexecutable. Every toolchain capability is optional, so a discovery
        that went wrong degrades a report and authorises nothing.
        """
        ...
