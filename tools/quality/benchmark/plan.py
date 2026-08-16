"""The judgement half of the workload benefit gate: no I/O, no clock, no library.

Everything here is a function of the declaration and of measurements handed in.
That split is what makes the verdict checkable rather than believed — the same
arrangement ``tools/quality/gpu/plan.py`` uses, and for the same reason.

**A verdict is recomputed, never recorded.** The manifest stores what was
measured; every conclusion drawn from those numbers is derived again on each run
by the functions below. An entry claiming a workload benefits whose own figures do
not support it therefore fails without anybody having to notice.

**A timing is not reproducible and a verdict is.** Two runs on one host produce
different nanoseconds, so nothing here asserts that a measurement repeats. What
repeats is the *method* — declared once in the contract — and the derivation of a
verdict from a measurement, which is pure arithmetic over integers.
"""

import re
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

CONFIGURATION_FILE: Final[str] = "docs/engineering/benchmark-contract.toml"
"""Where the declaration lives, relative to the repository root."""

SCHEMA: Final[int] = 1
"""The declaration schema this reader implements."""

CPU: Final[str] = "cpu"
"""The backend every host has."""

CUDA: Final[str] = "cuda"
"""The backend that needs a device and a library able to reach it."""

BACKENDS: Final[tuple[str, ...]] = (CPU, CUDA)
"""Every backend a workload may declare."""

MINIMUM: Final[str] = "minimum"
"""The one reduction this harness implements."""

REDUCTIONS: Final[tuple[str, ...]] = (MINIMUM,)
"""Every reduction a contract may declare."""

IDENTIFIER_PATTERN: Final[str] = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
"""What a workload identifier looks like: dotted, lowercase, at least two parts."""

MAXIMUM_REPEATS: Final[int] = 64
"""How many timed iterations a contract may ask for.

A bound because this runs in CI. A contract asking for ten thousand repeats of a
matrix multiply would turn a reporting gate into a job that times out, and the
failure would look like an infrastructure problem rather than a declaration one.
"""

MAXIMUM_SIZE: Final[int] = 1 << 26
"""The largest problem size a workload may declare — 64Mi elements.

At float64 that is half a gibibyte per array, which is already more than a CI
runner should be asked to allocate. A contract wanting more is describing a
different kind of harness.
"""


class State(StrEnum):
    """What measuring one workload established.

    Four states, and ``ABSENT`` and ``UNAVAILABLE`` are deliberately not the same
    word. A host with no NVIDIA device cannot answer a CUDA question no matter
    what is installed; a host with a device but no library able to reach it is one
    ``pip install`` away from an answer. Telling an operator to install something
    that would not help is a different kind of wrong from telling them nothing.
    """

    MEASURED = "measured"
    """The workload ran and produced a figure."""

    UNAVAILABLE = "unavailable"
    """The backend's library is not adopted. The owning phase is recorded."""

    ABSENT = "absent"
    """No device of the required kind is present on this host."""

    ERROR = "error"
    """The workload was attempted and failed. Always a gate failure."""


class BenchmarkContractError(Exception):
    """The declaration could not be read, or contradicts itself."""


@dataclass(frozen=True, slots=True)
class Target:
    """The host the contract was written against.

    Args:
        system: The operating system.
        architecture: The processor architecture.
    """

    system: str
    architecture: str


@dataclass(frozen=True, slots=True)
class Method:
    """How every measurement is taken.

    Args:
        warmup: Iterations run and discarded first.
        repeats: Timed iterations.
        reduction: Which of them becomes the figure.
        clock: The clock's name, recorded so a reader knows what was used.
    """

    warmup: int
    repeats: int
    reduction: str
    clock: str


@dataclass(frozen=True, slots=True)
class Workload:
    """One thing worth timing.

    Args:
        identifier: The stable name a consumer switches on.
        question: What measuring it would answer.
        backend: Where it would run.
        library: The distribution the backend needs.
        phase: Who owns adopting that library.
        speedup_threshold: The ratio at which the backend is worth using.
        size: The problem size.
    """

    identifier: str
    question: str
    backend: str
    library: str
    phase: int
    speedup_threshold: float
    size: int

    @property
    def family(self) -> str:
        """The part of the identifier naming the shape of work.

        Returns:
            Everything before the last dot, so ``matmul.cuda`` pairs with
            ``matmul.cpu``.
        """
        return self.identifier.rsplit(".", maxsplit=1)[0]


@dataclass(frozen=True, slots=True)
class Declaration:
    """The whole contract.

    Args:
        schema: The declared schema version.
        target: The host it was written against.
        method: How measurements are taken.
        workloads: What is worth timing.
    """

    schema: int
    target: Target
    method: Method
    workloads: tuple[Workload, ...]


@dataclass(frozen=True, slots=True)
class Measurement:
    """What running one workload produced.

    Args:
        identifier: Which workload.
        state: What was established.
        nanoseconds: The reduced figure, present only when measured.
        detail: A short note — a library name, an error class.
    """

    identifier: str
    state: State
    nanoseconds: int | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Verdict:
    """What one workload's measurement means.

    Args:
        identifier: Which workload.
        state: What was established.
        nanoseconds: The reduced figure, when there is one.
        baseline_nanoseconds: The CPU figure it was compared against.
        speedup: The ratio, rounded to three places, when both figures exist.
        benefits: Whether the ratio cleared the declared threshold.
        detail: A short note.
    """

    identifier: str
    state: State
    nanoseconds: int | None = None
    baseline_nanoseconds: int | None = None
    speedup: float | None = None
    benefits: bool | None = None
    detail: str = ""


def parse_declaration(text: str) -> Declaration:
    """Read the contract.

    Args:
        text: The file's content.

    Returns:
        The declaration.

    Raises:
        BenchmarkContractError: If it cannot be read or announces another schema.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as fault:
        msg = f"{CONFIGURATION_FILE} is not readable TOML: {fault}"
        raise BenchmarkContractError(msg) from fault
    return read_declaration(document)


def read_declaration(document: dict[str, object]) -> Declaration:
    """Build the declaration from a parsed document.

    Args:
        document: The parsed TOML.

    Returns:
        The declaration.

    Raises:
        BenchmarkContractError: If a required table or key is missing or of the
            wrong type.
    """
    schema = document.get("schema")
    if schema != SCHEMA:
        msg = f"{CONFIGURATION_FILE} announces schema {schema!r}; this reader implements {SCHEMA}"
        raise BenchmarkContractError(msg)
    target = _table(document, "target")
    method = _table(document, "method")
    entries = document.get("workload")
    if not isinstance(entries, list) or not entries:
        msg = f"{CONFIGURATION_FILE} declares no workloads"
        raise BenchmarkContractError(msg)
    return Declaration(
        schema=SCHEMA,
        target=Target(system=_text(target, "system"), architecture=_text(target, "architecture")),
        method=Method(
            warmup=_count(method, "warmup"),
            repeats=_count(method, "repeats"),
            reduction=_text(method, "reduction"),
            clock=_text(method, "clock"),
        ),
        workloads=tuple(_workload(entry) for entry in entries),
    )


def _table(document: dict[str, object], name: str) -> dict[str, object]:
    """One required table.

    Args:
        document: The parsed TOML.
        name: The table's name.

    Returns:
        The table.

    Raises:
        BenchmarkContractError: If it is missing or is not a table.
    """
    value = document.get(name)
    if not isinstance(value, dict):
        msg = f"{CONFIGURATION_FILE} has no [{name}] table"
        raise BenchmarkContractError(msg)
    return value


def _text(table: dict[str, object], key: str) -> str:
    """One required string.

    Args:
        table: Where to look.
        key: The key.

    Returns:
        The value.

    Raises:
        BenchmarkContractError: If it is missing or is not a non-empty string.
    """
    value = table.get(key)
    if not isinstance(value, str) or not value:
        msg = f"{CONFIGURATION_FILE}: {key!r} is missing or is not a string"
        raise BenchmarkContractError(msg)
    return value


def _count(table: dict[str, object], key: str) -> int:
    """One required non-negative integer.

    Args:
        table: Where to look.
        key: The key.

    Returns:
        The value.

    Raises:
        BenchmarkContractError: If it is missing, not an integer, or negative.
            A ``bool`` is refused, because ``true`` resolving to one repeat is
            the kind of accident that looks like it worked.
    """
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        msg = f"{CONFIGURATION_FILE}: {key!r} is missing or is not a count"
        raise BenchmarkContractError(msg)
    return value


def _workload(entry: object) -> Workload:
    """One workload entry.

    Args:
        entry: The parsed table.

    Returns:
        The workload.

    Raises:
        BenchmarkContractError: If a key is missing or of the wrong type.
    """
    if not isinstance(entry, dict):
        msg = f"{CONFIGURATION_FILE}: a [[workload]] entry is not a table"
        raise BenchmarkContractError(msg)
    threshold = entry.get("speedup_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, int | float) or threshold <= 0:
        msg = f"{CONFIGURATION_FILE}: speedup_threshold is missing or is not a positive number"
        raise BenchmarkContractError(msg)
    return Workload(
        identifier=_text(entry, "id"),
        question=_text(entry, "question"),
        backend=_text(entry, "backend"),
        library=_text(entry, "library"),
        phase=_count(entry, "phase"),
        speedup_threshold=float(threshold),
        size=_count(entry, "size"),
    )


def target_problems(target: Target, *, system: str, architecture: str) -> tuple[str, ...]:
    """Whether the contract was written for the host it is being read on.

    Args:
        target: What the contract declares.
        system: What the runtime contract declares.
        architecture: The same.

    Returns:
        One sentence per divergence, empty when they agree.
    """
    problems: list[str] = []
    if target.system != system:
        problems.append(
            f"the benchmark contract targets {target.system!r} and the runtime "
            f"contract declares {system!r}"
        )
    if target.architecture != architecture:
        problems.append(
            f"the benchmark contract targets {target.architecture!r} and the runtime "
            f"contract declares {architecture!r}"
        )
    return tuple(problems)


def duplicate_workloads(workloads: tuple[Workload, ...]) -> tuple[str, ...]:
    """Whether any identifier is declared twice.

    Args:
        workloads: Every declared workload.

    Returns:
        One sentence per repeat.

    A repeat is not a style problem: the manifest is keyed by identifier, so the
    second entry would silently replace the first and the contract would describe
    a measurement nobody took.
    """
    seen: set[str] = set()
    problems: list[str] = []
    for workload in workloads:
        if workload.identifier in seen:
            problems.append(f"{workload.identifier} is declared more than once")
        seen.add(workload.identifier)
    return tuple(problems)


def shape_problems(declaration: Declaration) -> tuple[str, ...]:
    """Whether every declared value is one this harness can act on.

    Args:
        declaration: The contract.

    Returns:
        One sentence per problem.

    Checked here rather than trusted, because each of these would otherwise fail
    somewhere far from its cause: an unknown reduction as a ``KeyError`` inside the
    runner, an oversized problem as a memory error in CI, an unpaired CUDA workload
    as a speedup against a baseline that does not exist.
    """
    problems: list[str] = []
    method = declaration.method
    if method.reduction not in REDUCTIONS:
        problems.append(
            f"the declared reduction {method.reduction!r} is not one of {list(REDUCTIONS)}"
        )
    if not 0 < method.repeats <= MAXIMUM_REPEATS:
        problems.append(f"repeats is {method.repeats}; it is between 1 and {MAXIMUM_REPEATS}")
    pattern = re.compile(IDENTIFIER_PATTERN)
    families = {workload.family for workload in declaration.workloads if workload.backend == CPU}
    for workload in declaration.workloads:
        if not pattern.match(workload.identifier):
            problems.append(f"{workload.identifier!r} is not a dotted lowercase identifier")
        if workload.backend not in BACKENDS:
            problems.append(
                f"{workload.identifier} declares backend {workload.backend!r}, "
                f"which is not one of {list(BACKENDS)}"
            )
        if not 0 < workload.size <= MAXIMUM_SIZE:
            problems.append(
                f"{workload.identifier} declares size {workload.size}; "
                f"it is between 1 and {MAXIMUM_SIZE}"
            )
        if workload.backend != CPU and workload.family not in families:
            problems.append(
                f"{workload.identifier} has no {workload.family}.{CPU} baseline to be "
                f"compared against, so its speedup could never be computed"
            )
        if workload.backend == CPU and workload.speedup_threshold != 1.0:
            problems.append(
                f"{workload.identifier} is a baseline and declares a threshold of "
                f"{workload.speedup_threshold}; a baseline is compared against itself"
            )
    return tuple(problems)


def phase_problems(
    workloads: tuple[Workload, ...], *, delivered: int, total: int
) -> tuple[str, ...]:
    """Whether every workload names a phase that could still adopt its library.

    Args:
        workloads: Every declared workload.
        delivered: A floor: only a *cpu* workload may name this phase or earlier.
        total: How many phases the programme has.

    Returns:
        One sentence per misplaced entry.

    **The floor applies asymmetrically, and that asymmetry is the point.** A `cpu`
    workload names the phase that adopted the library it already uses, which is
    necessarily a delivered one — numpy arrived in Phase 021 and was verified in
    022. A non-`cpu` workload that is not measurable names the phase that *would*
    make it measurable, and a delivered phase there is a gap nobody will ever
    close, which is exactly what ADR-0052 refuses for the wheel survey.
    """
    problems: list[str] = []
    for workload in workloads:
        if workload.phase > total:
            problems.append(
                f"{workload.identifier} is owned by phase {workload.phase}, "
                f"and the programme has {total} phases"
            )
        elif workload.backend != CPU and workload.phase <= delivered:
            problems.append(
                f"{workload.identifier} is owned by phase {workload.phase}, "
                f"which has already been delivered"
            )
    return tuple(problems)


def reduce_timings(timings: tuple[int, ...], reduction: str) -> int:
    """Turn the timed iterations into the one recorded figure.

    Args:
        timings: Every timed iteration, in nanoseconds.
        reduction: Which reduction the contract declares.

    Returns:
        The figure.

    Raises:
        BenchmarkContractError: If there are no timings, or the reduction is not
            one this harness implements.

    ``minimum`` and nothing else, for now. Every source of noise on a
    general-purpose machine *adds* time — another process, a page fault, a
    frequency change — so the minimum is the closest available estimate of the
    workload's own cost, and a mean on a laptop largely measures what else the
    laptop was doing.
    """
    if not timings:
        msg = "a workload produced no timings"
        raise BenchmarkContractError(msg)
    if reduction != MINIMUM:
        msg = f"the reduction {reduction!r} is not implemented"
        raise BenchmarkContractError(msg)
    return min(timings)


def classify(
    declaration: Declaration, measurements: tuple[Measurement, ...]
) -> tuple[Verdict, ...]:
    """Turn measurements into verdicts, in declaration order.

    Args:
        declaration: The contract.
        measurements: What running the workloads produced.

    Returns:
        One verdict per declared workload, in the order the contract declares
        them, so two runs serialise identically.

    A workload with no measurement becomes ``ERROR`` rather than being omitted.
    Silence is the one answer a harness must never give: a missing row and a row
    saying "this failed" look identical in a summary, and only one of them is a
    reason to look.
    """
    taken = {item.identifier: item for item in measurements}
    baselines = {
        workload.family: taken[workload.identifier].nanoseconds
        for workload in declaration.workloads
        if workload.backend == CPU
        and workload.identifier in taken
        and taken[workload.identifier].state is State.MEASURED
    }
    verdicts: list[Verdict] = []
    for workload in declaration.workloads:
        measurement = taken.get(workload.identifier)
        if measurement is None:
            verdicts.append(
                Verdict(
                    identifier=workload.identifier,
                    state=State.ERROR,
                    detail="no measurement was recorded",
                )
            )
            continue
        verdicts.append(_verdict(workload, measurement, baselines.get(workload.family)))
    return tuple(verdicts)


def _verdict(workload: Workload, measurement: Measurement, baseline: int | None) -> Verdict:
    """One workload's verdict.

    Args:
        workload: What was declared.
        measurement: What was measured.
        baseline: The family's CPU figure, when there is one.

    Returns:
        The verdict.
    """
    if measurement.state is not State.MEASURED or measurement.nanoseconds is None:
        return Verdict(
            identifier=workload.identifier,
            state=measurement.state,
            detail=measurement.detail,
        )
    if workload.backend == CPU:
        return Verdict(
            identifier=workload.identifier,
            state=State.MEASURED,
            nanoseconds=measurement.nanoseconds,
            baseline_nanoseconds=measurement.nanoseconds,
            speedup=1.0,
            benefits=False,
            detail=measurement.detail,
        )
    if baseline is None or measurement.nanoseconds == 0:
        return Verdict(
            identifier=workload.identifier,
            state=State.ERROR,
            nanoseconds=measurement.nanoseconds,
            detail="no usable baseline to compare against",
        )
    speedup = round(baseline / measurement.nanoseconds, 3)
    return Verdict(
        identifier=workload.identifier,
        state=State.MEASURED,
        nanoseconds=measurement.nanoseconds,
        baseline_nanoseconds=baseline,
        speedup=speedup,
        benefits=speedup >= workload.speedup_threshold,
        detail=measurement.detail,
    )


def gap_problems(verdicts: tuple[Verdict, ...]) -> tuple[str, ...]:
    """Which verdicts are failures rather than recorded absences.

    Args:
        verdicts: Every verdict.

    Returns:
        One sentence per failure.

    ``ABSENT`` and ``UNAVAILABLE`` are states and pass; ``ERROR`` always fails.
    That is ADR-0045's rule unchanged: absence is a fact worth recording, and not
    knowing *why* something did not run is different from knowing why.
    """
    return tuple(
        f"{verdict.identifier} could not be measured: {verdict.detail or 'no reason recorded'}"
        for verdict in verdicts
        if verdict.state is State.ERROR
    )
