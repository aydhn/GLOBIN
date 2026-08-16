"""The only part of this package that runs a workload or reads a clock.

Everything else derives verdicts from what this produces. Keeping the measurement
in one module is what lets `plan.py` be tested with numbers written by hand, and
what lets this be tested by substituting the runner.

**No library is imported at module scope.** ``numpy`` is a declared runtime
dependency and ``torch`` is Phase 183's, so neither may be assumed present: the CI
``quality`` job installs the toolchain only, and a module-level import would make
this package unimportable there. Each backend imports inside its own function and
reports the absence as a state.
"""

import time
from collections.abc import Callable
from typing import Any, Final

from tools.quality.benchmark.plan import (
    CPU,
    CUDA,
    Measurement,
    State,
    Workload,
    reduce_timings,
)

Clock = Callable[[], int]
"""How a timing is taken, injected so a test needs no real elapsed time."""

DEFAULT_CLOCK: Final[Clock] = time.perf_counter_ns
"""The standard library's highest-resolution monotonic clock.

Integer nanoseconds, so no float rounding enters a recorded figure, and monotonic
so a wall-clock correction during a run cannot produce a negative duration.
"""


def measure(
    workload: Workload, warmup: int, repeats: int, reduction: str, clock: Clock = DEFAULT_CLOCK
) -> Measurement:
    """Run one workload and reduce its timings, or say why it did not run.

    Args:
        workload: What to run.
        warmup: Iterations to discard first.
        repeats: Timed iterations.
        reduction: Which of them becomes the figure.
        clock: How to time it.

    Returns:
        The measurement, carrying a state rather than raising.

    Every failure becomes a state. A gate that raised on a missing library would
    produce no evidence at all, which is worse than evidence saying the library is
    missing — and a host without a GPU is the normal case in CI rather than an
    exceptional one.
    """
    try:
        operation = _operation(workload)
    except _UnavailableError as absence:
        return Measurement(workload.identifier, absence.state, detail=absence.detail)

    try:
        for _ in range(warmup):
            operation()
        timings: list[int] = []
        for _ in range(repeats):
            started = clock()
            operation()
            timings.append(clock() - started)
        return Measurement(
            workload.identifier,
            State.MEASURED,
            nanoseconds=reduce_timings(tuple(timings), reduction),
            detail=workload.library,
        )
    except Exception as fault:
        return Measurement(workload.identifier, State.ERROR, detail=type(fault).__name__)


class _UnavailableError(Exception):
    """A backend could not be reached, with the state that describes why.

    Args:
        state: Which kind of absence.
        detail: A short note naming what was missing.
    """

    def __init__(self, state: State, detail: str) -> None:
        """Record the state and the note."""
        super().__init__(detail)
        self.state = state
        self.detail = detail


def _operation(workload: Workload) -> Callable[[], object]:
    """Build the callable one workload times.

    Args:
        workload: What to run.

    Returns:
        A callable taking no arguments.

    Raises:
        _UnavailableError: If the backend's library or device is not there.
    """
    if workload.backend == CPU:
        return _numpy_operation(workload)
    if workload.backend == CUDA:
        return _cuda_operation(workload)
    msg = f"the backend {workload.backend!r} has no runner"
    raise _UnavailableError(State.ERROR, msg)


def _numpy_operation(workload: Workload) -> Callable[[], object]:
    """A CPU workload, built on numpy.

    Args:
        workload: What to run.

    Returns:
        The callable.

    Raises:
        _UnavailableError: If numpy is not installed.

    The arrays are allocated once, outside the timed callable. Timing the
    allocation would measure the allocator rather than the workload, and would do
    it differently on the first iteration from every later one.
    """
    try:
        import numpy
    except ImportError:
        raise _UnavailableError(State.UNAVAILABLE, "numpy is not installed") from None

    family = workload.family
    if family == "matmul":
        left = numpy.ones((workload.size, workload.size), dtype=numpy.float64)
        right = numpy.ones((workload.size, workload.size), dtype=numpy.float64)
        return lambda: left @ right
    data = numpy.ones(workload.size, dtype=numpy.float64)
    if family == "reduction":
        return lambda: float(data.sum())
    return lambda: data * 2.0 + 1.0


def _cuda_operation(workload: Workload) -> Callable[[], object]:
    """A CUDA workload, if anything on this host could run one.

    Args:
        workload: What to run.

    Returns:
        The callable.

    Raises:
        _UnavailableError: Always, on any host GLOBIN currently has.

    **This is the honest shape of an unadopted backend.** ``torch`` is Phase 183's
    to adopt and is in no lock here, so the import fails and the workload records
    ``UNAVAILABLE`` naming the library. On a host that somehow had torch but no
    device, ``cuda.is_available()`` is false and the state is ``ABSENT`` instead —
    a different fact, because installing something more would not help.

    Nothing is stubbed and nothing is simulated. A harness that invented a figure
    for an unavailable backend would be the exact failure ADR-0045 exists to
    prevent, dressed as a measurement.
    """
    try:
        import torch
    except ImportError:
        raise _UnavailableError(State.UNAVAILABLE, "torch is not installed") from None
    if not torch.cuda.is_available():
        raise _UnavailableError(State.ABSENT, "no CUDA device is available to torch")
    return _torch_operation(torch, workload)


def _torch_operation(torch: Any, workload: Workload) -> Callable[[], object]:
    """The device-side callable, once a device is known to exist.

    Args:
        torch: The imported module.
        workload: What to run.

    Returns:
        The callable, which synchronises before returning.

    **It synchronises, and without that the measurement would be a fiction.** CUDA
    work is queued asynchronously, so a timed block that returned as soon as the
    call was *submitted* would record the submission cost and report a speedup of
    several hundred. This is the single most common way a GPU benchmark lies, and
    it lies in the flattering direction.
    """
    device = torch.device("cuda")
    family = workload.family
    if family == "matmul":
        left = torch.ones((workload.size, workload.size), dtype=torch.float64, device=device)
        right = torch.ones((workload.size, workload.size), dtype=torch.float64, device=device)

        def run_matmul() -> object:
            result = left @ right
            torch.cuda.synchronize()
            return result

        return run_matmul

    data = torch.ones(workload.size, dtype=torch.float64, device=device)
    if family == "reduction":

        def run_reduction() -> object:
            result = data.sum()
            torch.cuda.synchronize()
            return result

        return run_reduction

    def run_elementwise() -> object:
        result = data * 2.0 + 1.0
        torch.cuda.synchronize()
        return result

    return run_elementwise
