"""Asking this host what it has, through the one interface the contract allows.

Everything impure about the GPU gate is here, and it is deliberately thin: the
probes gather text and say whether a command ran, and
:func:`tools.quality.gpu.plan.classify` decides what any of it means. That split is
what makes the reasoning testable on a machine with no GPU, which is every machine
continuous integration runs on.

**The runner is injected, and that is not a convenience.** ``tools/conftest`` is
not where the offline guarantee lives — ADR-0024 enforces it by refusing sockets in
the test process, and a probe that started a real subprocess would sail past that
in the opposite direction, because ``nvidia-smi`` is not a socket. A substitutable
runner is what lets every branch be exercised, including the ones this host cannot
produce: no driver at all, a driver that exits non-zero, and a device that reports
a compute capability the parser refuses.

**Nothing here raises.** A probe that could not run returns a reading saying so.
Turning *the tool is absent* into an exception would make the common case on a
GPU-less host travel the same path as a genuine fault, and the whole point of
ADR-0045 is that those two are different.

**No shell, ever.** The command and its arguments are passed as a list, so nothing
this reads can be interpreted as shell syntax. ``shutil.which`` decides whether the
executable exists rather than an exception from the attempt, because a missing
executable is an answer here rather than an error.
"""

import shutil
import subprocess
from collections.abc import Callable, Sequence
from typing import Final

from tools.quality.gpu.plan import Interface, Reading

Runner = Callable[..., subprocess.CompletedProcess[str]]
"""How a probe starts a process.

Injected for the reason :mod:`tools.quality.supply.capability` gives about its
own: a gate that can only be tested on a host with the thing it detects is a gate
this suite cannot cover, and the hosts that matter most here are the ones without.
"""

Locator = Callable[[str], str | None]
"""How a probe decides an executable exists. :func:`shutil.which` by default."""

DEFAULT_TIMEOUT: Final[float] = 20.0
"""How long any one probe may take.

Bounded because ``nvidia-smi`` talks to a kernel-mode driver, and a driver in a
bad state can hang rather than fail. An unbounded gate would hang the commit.
"""

TOOLKIT_COMMAND: Final[str] = "nvcc"
"""The CUDA compiler, whose presence is what distinguishes a toolkit from a runtime.

Kept separate from the display driver on purpose. A machine can have a working
driver-side CUDA runtime and no toolkit — which is this host — and it can have a
toolkit and no device. Deriving either from the other would publish a guess.
"""


def _run(
    command: str,
    arguments: Sequence[str],
    *,
    runner: Runner,
    timeout: float,
) -> tuple[bool, str, str]:
    """Start one process and collect what it said.

    Args:
        command: The executable.
        arguments: Its arguments, already split.
        runner: How to start it.
        timeout: How long it may take.

    Returns:
        Whether it exited successfully, its standard output, and its standard
        error.

    A timeout, an ``OSError`` and a non-zero exit are all reported as failure with
    whatever text was captured. They are distinguished by the caller only where
    the distinction changes a state, which keeps the classifier's branches to the
    ones that mean something.
    """
    try:
        # A list, never a string, so nothing here can be read as shell syntax. The
        # command comes from the contract rather than from the environment, and the
        # arguments are built from declared field names. Bandit does not flag this
        # call because `runner` is injected and it cannot see through the
        # indirection -- which is a limitation of the check, not an absence of the
        # hazard, so the reasoning is written down rather than left to a directive.
        completed = runner(
            [command, *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as fault:
        return False, "", str(fault)
    return completed.returncode == 0, completed.stdout or "", completed.stderr or ""


def read(
    interface: Interface,
    *,
    runner: Runner | None = None,
    locate: Locator | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Reading:
    """Ask this host everything the contract allows, and report what came back.

    Args:
        interface: The command and the fields it may be asked for.
        runner: How to start a process. Defaults to :func:`subprocess.run`.
        locate: How to find an executable. Defaults to :func:`shutil.which`.
        timeout: How long any one probe may take.

    Returns:
        The raw reading, for :func:`tools.quality.gpu.plan.classify` to interpret.

    The device query is skipped entirely when the command is absent, rather than
    attempted and allowed to fail. A ``FileNotFoundError`` and a driver refusing a
    field would otherwise arrive at the classifier looking alike, and they mean
    opposite things: no driver, versus a driver that was asked the wrong question.
    """
    start = subprocess.run if runner is None else runner
    find = shutil.which if locate is None else locate

    toolkit_found = find(TOOLKIT_COMMAND) is not None

    if find(interface.command) is None:
        return Reading(
            command_found=False,
            query_ok=False,
            query_output="",
            query_error="",
            version_ok=False,
            version_output="",
            toolkit_found=toolkit_found,
        )

    query = f"--query-gpu={','.join(interface.query_fields)}"
    query_ok, query_output, query_error = _run(
        interface.command,
        [query, *interface.format_arguments],
        runner=start,
        timeout=timeout,
    )
    version_ok, version_output, _ = _run(
        interface.command,
        list(interface.version_arguments),
        runner=start,
        timeout=timeout,
    )
    return Reading(
        command_found=True,
        query_ok=query_ok,
        query_output=query_output,
        query_error=query_error,
        version_ok=version_ok,
        version_output=version_output,
        toolkit_found=toolkit_found,
    )
