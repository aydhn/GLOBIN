"""What the GPU contract declares, and every judgement made about it.

Pure. Every function here takes text or values and returns findings; nothing
starts a process, reads a file, opens a socket or looks at the clock. That is what
lets the whole of the reasoning be tested from literals on a machine with no GPU,
in the way ``tools/quality/wheels/plan.py`` separates its judgements from its gate.

**A state, never a boolean.** ADR-0045 settled that a platform capability is a
recorded state rather than a pass, because collapsing *we asked and it is there*,
*we asked and it is not*, *we could not ask* and *asking failed* into one bit
throws away the distinction a reader needs. Hardware is the same question with a
different subject, so :class:`State` has four members and no fifth.

**The parsers refuse rather than guess.** ``nvidia-smi`` answers a bad query with
prose on standard error and a non-zero code, and it answers two of its own
``--version`` labels with the word *Deprecated*. A reader that took either at face
value would record a sentence where a version belongs and would be believed,
because nothing downstream can tell a plausible string from a measured one. So a
value that does not look like what it claims to be is refused here, which is
``ENGINEERING_CONTRACT.md`` invariant 2 applied to a driver rather than to a
configuration file.

**Deprecated field names are data, not knowledge.** Which labels are deprecated is
declared in ``gpu-contract.toml`` and checked against the interface the contract
also declares. Hard-coding them would put the same fact in two places, and the one
in the code is the copy nobody would notice going stale.
"""

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

CONFIGURATION_FILE: Final[str] = "docs/engineering/gpu-contract.toml"
"""Where the declaration lives, relative to the repository root."""

SCHEMA: Final[int] = 1
"""The declaration format this module reads."""

OPTIONAL: Final[str] = "optional"
"""Nothing in GLOBIN depends on this capability, so an absence is information."""

REQUIRED: Final[str] = "required"
"""Something depends on this capability, so an absence is a gate failure.

No row carries it today, and that is a statement about GLOBIN rather than about
this gate: nothing here uses a GPU. The word exists so that the phase which makes
something depend on one has a way to say so.
"""

POLICIES: Final[frozenset[str]] = frozenset({OPTIONAL, REQUIRED})
"""The whole policy vocabulary. There is no third word."""

VERSION_SEPARATOR: Final[str] = ":"
"""How ``nvidia-smi --version`` separates a label from its value."""

DEPRECATED_MARKER: Final[str] = "deprecated"
"""What the driver says instead of a value when a label has been superseded."""

VERSION_PATTERN: Final[str] = r"^\d+(\.\d+)*$"
"""What a version must look like to be recorded as one.

Digits and dots, nothing else. The driver's own deprecation notices are prose and
fail this, which is the point: a detector that accepted them would publish
``"Deprecated, see \\"KMD version\\" instead"`` in the field where a downstream
phase expects to read a number.
"""

COMPUTE_CAPABILITY_PATTERN: Final[str] = r"^\d+\.\d+$"
"""What a compute capability must look like. Always major.minor, such as ``8.6``."""


class State(StrEnum):
    """What is known about one GPU capability."""

    PRESENT = "PRESENT"
    """Asked, and found."""

    ABSENT = "ABSENT"
    """Asked, and this host does not have it.

    **Not a failure.** A machine without an NVIDIA card is a fact about the
    machine, and a gate that went red for it would be reporting the hardware
    rather than the repository.
    """

    UNMEASURABLE = "UNMEASURABLE"
    """Not asked, because something it depends on was absent.

    Recorded rather than omitted, so that a manifest missing an answer says so
    instead of leaving a reader to infer one. Distinct from
    :attr:`ABSENT`: *there is no device to ask about* is a different claim from
    *the device says no*.
    """

    ERROR = "ERROR"
    """The probe itself failed.

    Never folded into :attr:`ABSENT`, for the reason
    :mod:`tools.quality.supply.capability` gives about its own equivalent: not
    knowing why is a different fact from knowing why, and only one of them is
    safe to build on.
    """


class GpuContractError(Exception):
    """The GPU contract could not be read, or does not say what it must."""


@dataclass(frozen=True, slots=True)
class Target:
    """The host the contract was written against.

    Args:
        system: The operating system, as ``runtime-contract.toml`` spells it.
        architecture: The machine architecture, likewise.
    """

    system: str
    architecture: str


@dataclass(frozen=True, slots=True)
class Interface:
    """The one command this gate may use, and what it may ask it.

    Args:
        command: The executable, which ships with the display driver.
        query_fields: The ``--query-gpu`` names verified against the tool's own
            ``--help-query-gpu`` output.
        version_arguments: How to ask for the version table.
        format_arguments: How to ask for machine-readable output.
    """

    command: str
    query_fields: tuple[str, ...]
    version_arguments: tuple[str, ...]
    format_arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ForbiddenField:
    """A field name that must never be read, and why.

    Args:
        name: The label or query name.
        where: Which interface offers it.
        reason: What reading it would actually produce.
    """

    name: str
    where: str
    reason: str


@dataclass(frozen=True, slots=True)
class Capability:
    """One question this phase is asked to answer without assuming the answer.

    Args:
        identifier: The stable dotted name, unique across the contract.
        question: What is being asked, in a sentence.
        source: Where the answer comes from.
        policy: Whether an absence is information or a failure.
        phase: Which phase answers for an absence.
        absence_means: What a reader should conclude if it is not there.
    """

    identifier: str
    question: str
    source: str
    policy: str
    phase: int
    absence_means: str


@dataclass(frozen=True, slots=True)
class Declaration:
    """The whole contract.

    Args:
        target: The host it was written against.
        interface: The command and the fields it may be asked for.
        forbidden: Field names that must never be read.
        capabilities: The questions, in declaration order.
    """

    target: Target
    interface: Interface
    forbidden: tuple[ForbiddenField, ...]
    capabilities: tuple[Capability, ...]


def parse_declaration(text: str) -> Declaration:
    """Read the declaration from TOML text.

    Args:
        text: The contents of ``gpu-contract.toml``.

    Returns:
        The declaration.

    Raises:
        GpuContractError: If the text is not TOML, or the declaration is
            malformed.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as fault:
        msg = f"{CONFIGURATION_FILE} is not valid TOML: {fault}"
        raise GpuContractError(msg) from fault
    return read_declaration(document)


def read_declaration(document: Mapping[str, object]) -> Declaration:
    """Read the declaration from an already-parsed document.

    Args:
        document: The parsed TOML.

    Returns:
        The declaration.

    Raises:
        GpuContractError: If a required table or key is missing or ill-typed.
    """
    if document.get("schema") != SCHEMA:
        found = document.get("schema")
        msg = f"{CONFIGURATION_FILE} declares schema {found!r}, and this reader implements {SCHEMA}"
        raise GpuContractError(msg)
    return Declaration(
        target=_target(_table(document, "target")),
        interface=_interface(_table(document, "interface")),
        forbidden=tuple(_forbidden(entry) for entry in _array(document, "forbidden_field")),
        capabilities=tuple(_capability(entry) for entry in _array(document, "capability")),
    )


def _table(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    """Read one required table.

    Args:
        document: The parsed TOML.
        name: The table's name.

    Returns:
        The table.

    Raises:
        GpuContractError: If it is missing or is not a table.
    """
    found = document.get(name)
    if not isinstance(found, Mapping):
        msg = f"{CONFIGURATION_FILE} has no [{name}] table"
        raise GpuContractError(msg)
    return found


def _array(document: Mapping[str, object], name: str) -> Sequence[Mapping[str, object]]:
    """Read one required array of tables.

    Args:
        document: The parsed TOML.
        name: The array's name.

    Returns:
        Its entries.

    Raises:
        GpuContractError: If it is missing, empty, or holds anything but tables.
    """
    found = document.get(name)
    if not isinstance(found, list) or not found:
        msg = f"{CONFIGURATION_FILE} declares no [[{name}]] entries"
        raise GpuContractError(msg)
    for entry in found:
        if not isinstance(entry, Mapping):
            msg = f"{CONFIGURATION_FILE} has a [[{name}]] entry that is not a table"
            raise GpuContractError(msg)
    return found


def _text(entry: Mapping[str, object], key: str, *, where: str) -> str:
    """Read one required string.

    Args:
        entry: The table to read from.
        key: The key.
        where: What to call the table in a message.

    Returns:
        The value.

    Raises:
        GpuContractError: If it is missing, not a string, or empty.
    """
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"{where} has no {key!r}"
        raise GpuContractError(msg)
    return value


def _strings(entry: Mapping[str, object], key: str, *, where: str) -> tuple[str, ...]:
    """Read one required array of non-empty strings.

    Args:
        entry: The table to read from.
        key: The key.
        where: What to call the table in a message.

    Returns:
        The values, in declaration order.

    Raises:
        GpuContractError: If it is missing, empty, or holds a non-string.
    """
    value = entry.get(key)
    if not isinstance(value, list) or not value:
        msg = f"{where} has no {key!r}"
        raise GpuContractError(msg)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            msg = f"{where} has a {key!r} entry that is not a non-empty string"
            raise GpuContractError(msg)
    return tuple(value)


def _target(entry: Mapping[str, object]) -> Target:
    """Build the target from its table.

    Args:
        entry: The ``[target]`` table.

    Returns:
        The target.

    Raises:
        GpuContractError: If a key is missing or ill-typed.
    """
    return Target(
        system=_text(entry, "system", where="[target]"),
        architecture=_text(entry, "architecture", where="[target]"),
    )


def _interface(entry: Mapping[str, object]) -> Interface:
    """Build the interface from its table.

    Args:
        entry: The ``[interface]`` table.

    Returns:
        The interface.

    Raises:
        GpuContractError: If a key is missing or ill-typed.
    """
    return Interface(
        command=_text(entry, "command", where="[interface]"),
        query_fields=_strings(entry, "query_fields", where="[interface]"),
        version_arguments=_strings(entry, "version_arguments", where="[interface]"),
        format_arguments=_strings(entry, "format_arguments", where="[interface]"),
    )


def _forbidden(entry: Mapping[str, object]) -> ForbiddenField:
    """Build one forbidden field from its table.

    Args:
        entry: The ``[[forbidden_field]]`` entry.

    Returns:
        The field.

    Raises:
        GpuContractError: If a key is missing or ill-typed.
    """
    where = "a [[forbidden_field]] entry"
    return ForbiddenField(
        name=_text(entry, "name", where=where),
        where=_text(entry, "where", where=where),
        reason=_text(entry, "reason", where=where),
    )


def _capability(entry: Mapping[str, object]) -> Capability:
    """Build one capability from its table.

    Args:
        entry: The ``[[capability]]`` entry.

    Returns:
        The capability.

    Raises:
        GpuContractError: If a key is missing, ill-typed, or the policy is not
            one of the two words :data:`POLICIES` allows.
    """
    where = "a [[capability]] entry"
    identifier = _text(entry, "id", where=where)
    policy = _text(entry, "policy", where=f"capability {identifier!r}")
    if policy not in POLICIES:
        allowed = ", ".join(sorted(POLICIES))
        msg = (
            f"capability {identifier!r} declares policy {policy!r}, which is not one of: {allowed}"
        )
        raise GpuContractError(msg)
    phase = entry.get("phase")
    if not isinstance(phase, int) or isinstance(phase, bool):
        msg = f"capability {identifier!r} has no integer 'phase'"
        raise GpuContractError(msg)
    return Capability(
        identifier=identifier,
        question=_text(entry, "question", where=f"capability {identifier!r}"),
        source=_text(entry, "source", where=f"capability {identifier!r}"),
        policy=policy,
        phase=phase,
        absence_means=_text(entry, "absence_means", where=f"capability {identifier!r}"),
    )


def target_problems(target: Target, *, system: str, architecture: str) -> tuple[str, ...]:
    """Report every way the declared target differs from the runtime contract.

    Args:
        target: What this contract says it was written against.
        system: What ``runtime-contract.toml`` declares.
        architecture: Likewise.

    Returns:
        One sentence per divergence, empty when the two agree.

    The copy in ``gpu-contract.toml`` is a tripwire. Its only job is to fail when
    somebody changes the runtime contract and forgets that this survey was
    conducted against the old one.
    """
    problems: list[str] = []
    if target.system != system:
        problems.append(
            f"the contract was written against system {target.system!r}, "
            f"but the runtime contract declares {system!r}"
        )
    if target.architecture != architecture:
        problems.append(
            f"the contract was written against architecture {target.architecture!r}, "
            f"but the runtime contract declares {architecture!r}"
        )
    return tuple(problems)


def duplicate_capabilities(capabilities: Sequence[Capability]) -> tuple[str, ...]:
    """Report every identifier declared more than once.

    Args:
        capabilities: Every declared capability.

    Returns:
        One sentence per repeated identifier, empty when each is unique.

    A repeated identifier means the contract holds two answers to one question,
    and which one a reader gets would depend on iteration order.
    """
    seen: set[str] = set()
    repeated: set[str] = set()
    for capability in capabilities:
        if capability.identifier in seen:
            repeated.add(capability.identifier)
        seen.add(capability.identifier)
    return tuple(f"{identifier} is declared more than once" for identifier in sorted(repeated))


def phase_problems(
    capabilities: Sequence[Capability], *, delivered: int, total: int
) -> tuple[str, ...]:
    """Report every capability owned by a phase that cannot own it.

    Args:
        capabilities: Every declared capability.
        delivered: A floor: no entry may name this phase or an earlier one.
        total: How many phases the programme has.

    Returns:
        One sentence per misplaced entry, empty when every owner is plausible.

    An entry naming a delivered phase is a gap nobody will ever close, because the
    phase that was going to close it has shipped. ADR-0052 made the same check for
    the wheel survey and for the same reason.
    """
    problems: list[str] = []
    for capability in capabilities:
        if capability.phase <= delivered:
            problems.append(
                f"{capability.identifier} is owned by phase {capability.phase}, "
                f"which has already been delivered"
            )
        elif capability.phase > total:
            problems.append(
                f"{capability.identifier} is owned by phase {capability.phase}, "
                f"and the programme has {total} phases"
            )
    return tuple(problems)


def forbidden_field_problems(
    interface: Interface, forbidden: Sequence[ForbiddenField]
) -> tuple[str, ...]:
    """Report every forbidden field the interface would nonetheless ask for.

    Args:
        interface: What the contract says may be asked.
        forbidden: What the contract says must never be read.

    Returns:
        One sentence per contradiction, empty when the two agree.

    The contract can contradict itself, and this is where that is caught: a field
    named in ``query_fields`` and also in ``[[forbidden_field]]`` is a rule with
    an exception written directly underneath it.
    """
    banned = {entry.name.strip().lower() for entry in forbidden}
    return tuple(
        f"{field!r} is listed in query_fields and also forbidden"
        for field in interface.query_fields
        if field.strip().lower() in banned
    )


def parse_query_row(line: str, fields: Sequence[str]) -> dict[str, str]:
    """Read one comma-separated device row into its declared fields.

    Args:
        line: One line of ``--format=csv,noheader`` output.
        fields: The ``--query-gpu`` names, in the order they were asked for.

    Returns:
        The values, keyed by field name.

    Raises:
        GpuContractError: If the row does not carry exactly one value per field.

    Refusing a short row matters more than it looks: ``nvidia-smi`` reports an
    unsupported field per device as ``[N/A]`` rather than by omitting it, so a row
    with the wrong number of cells is a row this reader has misunderstood, and
    guessing which cell went missing would put a driver version in the compute
    capability's place.
    """
    cells = [cell.strip() for cell in line.split(",")]
    if len(cells) != len(fields):
        msg = f"a device row carried {len(cells)} values for {len(fields)} fields: {line.strip()!r}"
        raise GpuContractError(msg)
    return dict(zip(fields, cells, strict=True))


def parse_version_table(text: str) -> dict[str, str]:
    """Read the ``nvidia-smi --version`` label/value table.

    Args:
        text: The command's standard output.

    Returns:
        Every label mapped to its value, labels lowercased and stripped.

    A line without a separator is skipped rather than refused. The table is
    human-facing and has carried banner lines before; refusing the whole reading
    because of one would turn a cosmetic change into an unmeasured capability.
    """
    table: dict[str, str] = {}
    for line in text.splitlines():
        label, separator, value = line.partition(VERSION_SEPARATOR)
        if not separator:
            continue
        name = label.strip().lower()
        if name:
            table[name] = value.strip()
    return table


def is_deprecated(value: str) -> bool:
    """Whether the driver answered with a deprecation notice instead of a value.

    Args:
        value: What the label mapped to.

    Returns:
        Whether it says the label has been superseded.

    Measured on this host rather than assumed: ``nvidia-smi --version`` answers
    both ``DRIVER version`` and ``CUDA version`` with prose beginning
    *Deprecated*. See ``docs/research/phase_023_sources.md``.
    """
    return DEPRECATED_MARKER in value.strip().lower()


def looks_like_version(value: str) -> bool:
    """Whether a value has the shape of a version rather than of a sentence.

    Args:
        value: The candidate.

    Returns:
        Whether it is digits separated by dots and nothing else.
    """
    return re.fullmatch(VERSION_PATTERN, value.strip()) is not None


def looks_like_compute_capability(value: str) -> bool:
    """Whether a value has the shape of a compute capability.

    Args:
        value: The candidate.

    Returns:
        Whether it is exactly ``major.minor``.
    """
    return re.fullmatch(COMPUTE_CAPABILITY_PATTERN, value.strip()) is not None


@dataclass(frozen=True, slots=True)
class Reading:
    """What the probes actually got back, before any of it is interpreted.

    Kept as inert data so that :func:`classify` is a pure function of it, which is
    what lets every branch below — including the ones this host cannot produce,
    such as having no driver at all — be exercised from literals.

    Args:
        command_found: Whether the interface's command exists on this host.
        query_ok: Whether the device query exited successfully.
        query_output: Its standard output.
        query_error: Its standard error, kept because the driver explains a bad
            field there rather than in the output.
        version_ok: Whether the version table exited successfully.
        version_output: Its standard output.
        toolkit_found: Whether a CUDA compiler is on the path.
    """

    command_found: bool
    query_ok: bool
    query_output: str
    query_error: str
    version_ok: bool
    version_output: str
    toolkit_found: bool


@dataclass(frozen=True, slots=True)
class Observation:
    """What was concluded about this host.

    Args:
        states: Each capability's identifier mapped to its measured state.
        devices: One mapping per device, keyed by the fields that were asked for.
        driver_version: The display driver version, or empty when unmeasured.
        compute_capabilities: Every distinct compute capability reported.
        cuda_runtime_version: The driver-side CUDA runtime, or empty.
        notes: Anything a reader would otherwise have to infer.
    """

    states: Mapping[str, State]
    devices: tuple[Mapping[str, str], ...]
    driver_version: str
    compute_capabilities: tuple[str, ...]
    cuda_runtime_version: str
    notes: tuple[str, ...]


def _devices_of(
    reading: Reading, fields: Sequence[str]
) -> tuple[tuple[Mapping[str, str], ...], str]:
    """Parse every device row, or explain why none could be.

    Args:
        reading: What the probes got back.
        fields: The query fields, in the order they were asked for.

    Returns:
        The rows, and a note which is empty when parsing succeeded.
    """
    rows: list[Mapping[str, str]] = []
    for line in reading.query_output.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(parse_query_row(line, fields))
        except GpuContractError as fault:
            return (), str(fault)
    return tuple(rows), ""


def classify(reading: Reading, declaration: Declaration) -> Observation:
    """Decide each capability's state from what the probes returned.

    Args:
        reading: What the probes got back.
        declaration: The contract, for the field order the query was asked in.

    Returns:
        The observation, with a state for every declared capability.

    The order of the checks is the argument. A missing command means no driver,
    which makes every later question :attr:`State.UNMEASURABLE` rather than
    :attr:`State.ABSENT` — GLOBIN did not learn that this host has no CUDA, it
    learned that there was nothing to ask. A command that exists but fails is
    :attr:`State.ERROR`, because a driver that will not answer is a different
    situation from one that answers no.

    The toolkit is deliberately independent of everything above it. ``nvcc`` can
    be installed on a machine with no device, and a machine with a device and a
    working runtime very often has no toolkit — which is this host. Deriving one
    from the other would report a guess.
    """
    fields = declaration.interface.query_fields
    notes: list[str] = []
    states: dict[str, State] = {}

    toolkit = State.PRESENT if reading.toolkit_found else State.ABSENT

    if not reading.command_found:
        notes.append(
            f"{declaration.interface.command} is not on this host, "
            "so no NVIDIA display driver is installed"
        )
        states = {
            "gpu.present": State.ABSENT,
            "gpu.driver_version": State.UNMEASURABLE,
            "gpu.compute_capability": State.UNMEASURABLE,
            "cuda.runtime_present": State.UNMEASURABLE,
            "cuda.toolkit_present": toolkit,
        }
        return _observation(states, declaration, (), "", (), "", tuple(notes))

    if not reading.query_ok:
        detail = reading.query_error.strip().splitlines()
        notes.append(
            f"{declaration.interface.command} exited non-zero: "
            f"{detail[0] if detail else 'no explanation given'}"
        )
        states = dict.fromkeys(
            ("gpu.present", "gpu.driver_version", "gpu.compute_capability"), State.ERROR
        )
        states["cuda.runtime_present"] = State.UNMEASURABLE
        states["cuda.toolkit_present"] = toolkit
        return _observation(states, declaration, (), "", (), "", tuple(notes))

    devices, problem = _devices_of(reading, fields)
    if problem:
        notes.append(problem)
        states = dict.fromkeys(
            ("gpu.present", "gpu.driver_version", "gpu.compute_capability"), State.ERROR
        )
        states["cuda.runtime_present"] = State.UNMEASURABLE
        states["cuda.toolkit_present"] = toolkit
        return _observation(states, declaration, (), "", (), "", tuple(notes))

    if not devices:
        notes.append("the driver is installed but reports no devices")
        states = {
            "gpu.present": State.ABSENT,
            "gpu.driver_version": State.UNMEASURABLE,
            "gpu.compute_capability": State.UNMEASURABLE,
            "cuda.runtime_present": State.UNMEASURABLE,
            "cuda.toolkit_present": toolkit,
        }
        return _observation(states, declaration, (), "", (), "", tuple(notes))

    states["gpu.present"] = State.PRESENT

    driver = devices[0].get("driver_version", "").strip()
    if looks_like_version(driver):
        states["gpu.driver_version"] = State.PRESENT
    else:
        states["gpu.driver_version"] = State.ERROR
        notes.append(f"the driver version did not look like a version: {driver!r}")
        driver = ""

    reported = [device.get("compute_cap", "").strip() for device in devices]
    capabilities = tuple(
        sorted({value for value in reported if looks_like_compute_capability(value)})
    )
    if capabilities:
        states["gpu.compute_capability"] = State.PRESENT
    else:
        states["gpu.compute_capability"] = State.ERROR
        notes.append("no device reported a compute capability of the form major.minor")

    runtime, runtime_note = _cuda_runtime(reading, declaration)
    if runtime_note:
        notes.append(runtime_note)
    states["cuda.runtime_present"] = State.PRESENT if runtime else State.ABSENT
    states["cuda.toolkit_present"] = toolkit
    if not reading.toolkit_found:
        notes.append("no CUDA compiler is on the path, so CUDA source cannot be built here")

    return _observation(states, declaration, devices, driver, capabilities, runtime, tuple(notes))


def _cuda_runtime(reading: Reading, declaration: Declaration) -> tuple[str, str]:
    """Read the driver-side CUDA runtime version, refusing a deprecated label.

    Args:
        reading: What the probes got back.
        declaration: The contract, for the labels that must never be read.

    Returns:
        The version, empty when there is none, and a note which is empty when
        nothing needed saying.

    This is the check the whole contract's ``[[forbidden_field]]`` table exists
    for. The driver offers a label spelled ``CUDA version`` whose value is the
    word *Deprecated* and a pointer to another label. A reader taking the first
    match would publish that sentence as a version number.
    """
    if not reading.version_ok:
        return "", "the version table could not be read"
    table = parse_version_table(reading.version_output)
    banned = {entry.name.strip().lower() for entry in declaration.forbidden}
    for label, value in sorted(table.items()):
        if "cuda" not in label or label in banned or is_deprecated(value):
            continue
        if looks_like_version(value):
            return value, ""
    for label, value in sorted(table.items()):
        if "cuda" in label and is_deprecated(value):
            return "", f"the driver reports {label!r} as deprecated rather than as a version"
    return "", "the version table named no CUDA runtime"


def _observation(
    states: Mapping[str, State],
    declaration: Declaration,
    devices: tuple[Mapping[str, str], ...],
    driver: str,
    capabilities: tuple[str, ...],
    runtime: str,
    notes: tuple[str, ...],
) -> Observation:
    """Assemble an observation, giving every declared capability a state.

    Args:
        states: What was decided.
        declaration: The contract, so nothing declared is left without an answer.
        devices: The parsed device rows.
        driver: The driver version, or empty.
        capabilities: Every distinct compute capability.
        runtime: The CUDA runtime version, or empty.
        notes: What a reader would otherwise have to infer.

    Returns:
        The observation.

    A capability the classifier never reached is recorded
    :attr:`State.UNMEASURABLE` rather than omitted, so that adding a row to the
    contract without teaching the classifier about it produces a visible
    *nobody asked* instead of a silently missing key.
    """
    complete = {
        capability.identifier: states.get(capability.identifier, State.UNMEASURABLE)
        for capability in declaration.capabilities
    }
    return Observation(
        states=complete,
        devices=devices,
        driver_version=driver,
        compute_capabilities=capabilities,
        cuda_runtime_version=runtime,
        notes=notes,
    )


def gap_problems(
    observed: Mapping[str, State], capabilities: Sequence[Capability]
) -> tuple[str, ...]:
    """Report every absence that is somebody's problem, and every failed probe.

    Args:
        observed: What each capability's state was measured to be.
        capabilities: Every declared capability.

    Returns:
        One sentence per problem, empty when every absence is owned and no probe
        errored.

    Two things fail here and one deliberately does not.

    An absent capability whose policy is :data:`REQUIRED` fails, because something
    in GLOBIN was said to depend on it. An absent capability whose policy is
    :data:`OPTIONAL` does **not** fail — it is recorded, it names the phase that
    answers for it, and that is the whole of ADR-0045 applied to hardware.

    A capability in :attr:`State.ERROR` always fails, whatever its policy. An
    optional capability that is missing is a fact; an optional capability nobody
    could measure is an unanswered question wearing a fact's clothes.
    """
    problems: list[str] = []
    for capability in capabilities:
        state = observed.get(capability.identifier, State.UNMEASURABLE)
        if state is State.ERROR:
            problems.append(f"{capability.identifier} could not be measured, which is never a pass")
        elif state is State.ABSENT and capability.policy == REQUIRED:
            problems.append(
                f"{capability.identifier} is absent and is declared {REQUIRED}: "
                f"{capability.absence_means}"
            )
    return tuple(problems)
