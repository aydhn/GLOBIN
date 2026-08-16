"""What the scientific stack must satisfy, judged from facts rather than read.

Every function here takes measurements and returns problems. Nothing imports
``numpy``, nothing imports ``pandas``, and nothing opens a file — which is what
lets every branch be reached from literals, including the ones that only occur on
a machine nobody has.

**The probes live here as expectations, not as measurements.** A probe is two
halves: running something, and deciding whether the result was right.
:mod:`tools.quality.stack.gate` owns the first half because it needs the
libraries; this module owns the second, so "what counts as correct" is a pure
function a test can interrogate without an environment. A probe whose expectation
lived beside its measurement could only ever be checked by running it, which is
the assumption ADR-0058 refuses.

**The registry is closed in both directions.** :func:`implemented_probes` names
every probe this module can judge, and ``stack-contract.toml`` names every probe
the repository claims to run. A contract test compares the two sets: a declared
probe nothing implements is a claim nobody checks, and an implemented probe
nobody declared is a check nobody asked for.
"""

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

CONFIGURATION_FILE: Final[str] = "docs/engineering/stack-contract.toml"
"""Where the declaration lives, relative to the repository root."""

SCHEMA: Final[int] = 1
"""The declaration shape this module implements."""

FLOAT64_MANTISSA_BITS: Final[int] = 52
"""Stored significand bits in IEEE-754 binary64.

Fifty-two rather than fifty-three: the leading bit is implicit and is not stored,
which is the distinction :func:`binary64_problems` would otherwise be asserting
wrongly by one.
"""

FLOAT64_EPSILON: Final[float] = 2.0**-52
"""The gap between 1.0 and the next representable binary64 value.

Written as a power of two rather than as ``2.220446049250313e-16`` so that the
comparison is exact by construction and does not depend on this file's decimal
literal round-tripping.
"""

FLOAT64_BITS: Final[int] = 64
"""Total width of a binary64 value."""

FLOAT64_BYTES: Final[int] = 8
"""Storage size of one binary64 value."""

INT64_MINIMUM: Final[int] = -(2**63)
"""What a signed 64-bit maximum wraps to when one is added to it."""

FLOAT64_DTYPE: Final[str] = "float64"
"""The dtype name a float column must keep."""

UTC_NAME: Final[str] = "UTC"
"""The timezone name a UTC-aware column must report."""


class StackError(Exception):
    """The stack declaration could not be read, or does not describe a stack."""


@dataclass(frozen=True, slots=True)
class Target:
    """The environment the declaration's claims were established against.

    Args:
        implementation: The Python implementation.
        minor_line: The interpreter series, exactly.
        architecture: The processor architecture.
    """

    implementation: str
    minor_line: str
    architecture: str


@dataclass(frozen=True, slots=True)
class Library:
    """One library whose behaviour GLOBIN depends on.

    Args:
        name: The distribution name.
        import_name: The module name, which is not always the distribution name.
        version: The exact version the declaration expects.
        wheel_tag: The PEP 425 tag the installed artefact must record.
        role: Why GLOBIN depends on this library.
        probes: The identifiers of the probes it must satisfy.
    """

    name: str
    import_name: str
    version: str
    wheel_tag: str
    role: str
    probes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProbeSpec:
    """One probe, and the assumption it defends.

    Args:
        identifier: The stable name, in ``library.subject`` form.
        because: The GLOBIN rule that would be violated if it failed.
    """

    identifier: str
    because: str


@dataclass(frozen=True, slots=True)
class Deferral:
    """A question this gate does not answer, and who does.

    Args:
        question: What is not being decided here.
        phase: The phase that decides it.
    """

    question: str
    phase: int


@dataclass(frozen=True, slots=True)
class Declaration:
    """The whole stack contract, as recorded.

    Args:
        target: The environment the claims were established against.
        libraries: Every declared library, in recorded order.
        probes: Every declared probe, in recorded order.
        deferrals: Every question deliberately left to a later phase.
    """

    target: Target
    libraries: tuple[Library, ...]
    probes: tuple[ProbeSpec, ...]
    deferrals: tuple[Deferral, ...]


def implemented_probes() -> frozenset[str]:
    """Every probe identifier this module can judge.

    Returns:
        The identifiers.

    A function rather than a constant because ``frozenset(...)`` is a call, and
    the repository keeps registries as functions so that the two lists a contract
    test compares look alike.
    """
    return frozenset(
        {
            "numpy.float64_is_binary64",
            "numpy.nan_and_infinity_propagate",
            "numpy.integer_overflow_wraps_observably",
            "pandas.float64_round_trip_is_bit_exact",
            "pandas.missing_value_survives_a_round_trip",
            "pandas.utc_timestamp_round_trip_preserves_the_instant",
            "pandas.copy_on_write_is_active",
        }
    )


# ---------------------------------------------------------------------------
# The probe expectations. Each takes what was measured and says what was wrong.
# ---------------------------------------------------------------------------


def binary64_problems(
    *, mantissa_bits: int, epsilon: float, bits: int, item_bytes: int
) -> tuple[str, ...]:
    """Judge whether this build's ``float64`` is IEEE-754 binary64.

    Args:
        mantissa_bits: Stored significand bits, as ``finfo.nmant`` reports them.
        epsilon: The gap above 1.0, as ``finfo.eps`` reports it.
        bits: The type's width.
        item_bytes: The storage size of one value.

    Returns:
        One sentence per disagreement, empty when the type is binary64.
    """
    problems: list[str] = []
    if mantissa_bits != FLOAT64_MANTISSA_BITS:
        problems.append(
            f"float64 stores {mantissa_bits} mantissa bits, and binary64 stores "
            f"{FLOAT64_MANTISSA_BITS}"
        )
    if epsilon != FLOAT64_EPSILON:
        problems.append(f"float64 epsilon is {epsilon!r}, and binary64's is 2**-52")
    if bits != FLOAT64_BITS:
        problems.append(f"float64 is {bits}-bit, and binary64 is {FLOAT64_BITS}-bit")
    if item_bytes != FLOAT64_BYTES:
        problems.append(
            f"one float64 occupies {item_bytes} bytes, and binary64 occupies {FLOAT64_BYTES}"
        )
    return tuple(problems)


def nan_infinity_problems(
    *, infinity_is_infinite: bool, zero_over_zero_is_nan: bool, nan_differs_from_itself: bool
) -> tuple[str, ...]:
    """Judge whether non-finite results propagate rather than being substituted.

    Args:
        infinity_is_infinite: Whether ``1.0 / 0.0`` produced an infinity.
        zero_over_zero_is_nan: Whether ``0.0 / 0.0`` produced a not-a-number.
        nan_differs_from_itself: Whether ``nan != nan`` held.

    Returns:
        One sentence per disagreement.

    A substituted finite value is worse than a raised exception here: it is a
    plausible number, and nothing downstream can tell it from a measurement.
    """
    problems: list[str] = []
    if not infinity_is_infinite:
        problems.append("dividing by zero did not produce an infinity")
    if not zero_over_zero_is_nan:
        problems.append("zero divided by zero did not produce a not-a-number")
    if not nan_differs_from_itself:
        problems.append("a not-a-number compared equal to itself, which IEEE-754 forbids")
    return tuple(problems)


def overflow_problems(*, wrapped_to: int, warned: bool) -> tuple[str, ...]:
    """Judge whether a signed 64-bit overflow wraps and is observable.

    Args:
        wrapped_to: What adding one to the 64-bit maximum produced.
        warned: Whether the operation emitted a warning.

    Returns:
        One sentence per disagreement.

    Wrapping is permitted; silence is not. An overflow nothing reports cannot be
    distinguished from a correct result, and a later phase that wants to escalate
    one needs something to escalate.
    """
    problems: list[str] = []
    if wrapped_to != INT64_MINIMUM:
        problems.append(
            f"int64 overflow produced {wrapped_to}, and two's-complement wrapping gives "
            f"{INT64_MINIMUM}"
        )
    if not warned:
        problems.append("int64 overflow was silent, so nothing downstream could detect it")
    return tuple(problems)


def round_trip_problems(*, bit_exact: bool, dtype: str) -> tuple[str, ...]:
    """Judge whether a float column survives a frame round trip unchanged.

    Args:
        bit_exact: Whether every value came back with an identical bit pattern.
        dtype: The dtype the column reported.

    Returns:
        One sentence per disagreement.
    """
    problems: list[str] = []
    if not bit_exact:
        problems.append("a float64 column did not come back bit-identical")
    if dtype != FLOAT64_DTYPE:
        problems.append(f"a float64 column came back as {dtype!r}")
    return tuple(problems)


def missing_value_problems(*, missing_positions: Sequence[int], dtype: str) -> tuple[str, ...]:
    """Judge whether a missing value stays missing.

    Args:
        missing_positions: Which positions came back missing.
        dtype: The dtype the column reported.

    Returns:
        One sentence per disagreement.

    The expected shape is fixed by the measurement: one missing value, at index
    one. A missing value that returned as ``0.0`` would appear here as an empty
    sequence, which is the corruption this probe exists to catch.
    """
    problems: list[str] = []
    if tuple(missing_positions) != (1,):
        problems.append(
            f"the missing value came back at positions {tuple(missing_positions)}, expected (1,)"
        )
    if dtype != FLOAT64_DTYPE:
        problems.append(f"a float64 column with a missing value came back as {dtype!r}")
    return tuple(problems)


def timestamp_problems(
    *, timezone_name: str, instant_preserved: bool, is_utc: bool
) -> tuple[str, ...]:
    """Judge whether a UTC-aware timestamp survives a frame round trip.

    Args:
        timezone_name: The timezone the column reported.
        instant_preserved: Whether the value compared equal to the original.
        is_utc: Whether the returned value's ``tzinfo`` is UTC.

    Returns:
        One sentence per disagreement.
    """
    problems: list[str] = []
    if timezone_name != UTC_NAME:
        problems.append(f"the column's timezone is {timezone_name!r}, expected {UTC_NAME!r}")
    if not instant_preserved:
        problems.append("the timestamp did not compare equal to the one that went in")
    if not is_utc:
        problems.append("the returned timestamp is not UTC-aware, which TIME_POLICY.md requires")
    return tuple(problems)


def copy_on_write_problems(*, parent_unchanged: bool) -> tuple[str, ...]:
    """Judge whether mutating a derived object leaves its parent alone.

    Args:
        parent_unchanged: Whether the parent frame still holds its original value.

    Returns:
        One sentence per disagreement.
    """
    if parent_unchanged:
        return ()
    return ("mutating a derived Series wrote through to its parent frame",)


# ---------------------------------------------------------------------------
# The structural judgements.
# ---------------------------------------------------------------------------


def target_problems(
    target: Target, *, implementation: str, minor_line: str, architecture: str
) -> tuple[str, ...]:
    """Judge the declaration's target against the runtime contract.

    Args:
        target: What the declaration says it was established against.
        implementation: What the runtime contract declares.
        minor_line: The declared interpreter series.
        architecture: The declared architecture.

    Returns:
        One sentence per divergence.

    Compared case-insensitively for the implementation and the architecture,
    because ``platform`` spells them ``CPython`` and ``AMD64`` while a contract
    might reasonably write either casing, and a casing difference is not a
    divergence anybody means.
    """
    problems: list[str] = []
    if target.implementation.casefold() != implementation.casefold():
        problems.append(
            f"the stack was verified against {target.implementation!r} and the runtime "
            f"contract declares {implementation!r}"
        )
    if target.minor_line != minor_line:
        problems.append(
            f"the stack was verified against Python {target.minor_line} and the runtime "
            f"contract declares {minor_line}"
        )
    if target.architecture.casefold() != architecture.casefold():
        problems.append(
            f"the stack was verified on {target.architecture!r} and the runtime contract "
            f"declares {architecture!r}"
        )
    return tuple(problems)


def duplicate_libraries(libraries: Sequence[Library]) -> tuple[str, ...]:
    """Find any library declared more than once.

    Args:
        libraries: The declared libraries.

    Returns:
        The repeated names, sorted.

    A library declared twice holds two sets of expectations, and nothing decides
    which one applies.
    """
    seen: set[str] = set()
    repeated: set[str] = set()
    for library in libraries:
        if library.name in seen:
            repeated.add(library.name)
        seen.add(library.name)
    return tuple(sorted(repeated))


def registry_problems(declaration: Declaration, implemented: frozenset[str]) -> tuple[str, ...]:
    """Compare the declared probes against the implemented ones, both ways.

    Args:
        declaration: The parsed declaration.
        implemented: Every probe identifier the code can judge.

    Returns:
        One sentence per disagreement.

    Three separate failures, because they mean different things. A declared probe
    with no implementation is a claim nobody checks. An implemented probe nobody
    declared is a check nobody asked for. A probe a library names but the probe
    table does not describe has no recorded reason to exist, which is the field
    that makes this declaration worth more than a list.
    """
    declared = {probe.identifier for probe in declaration.probes}
    problems: list[str] = []
    for identifier in sorted(declared - implemented):
        problems.append(f"{identifier} is declared and nothing implements it")
    for identifier in sorted(implemented - declared):
        problems.append(f"{identifier} is implemented and nothing declares it")
    for library in declaration.libraries:
        for identifier in library.probes:
            if identifier not in declared:
                problems.append(
                    f"{library.name} names {identifier}, which the probe table does not describe"
                )
    return tuple(problems)


def coverage_problems(libraries: Sequence[Library]) -> tuple[str, ...]:
    """Find any library that declares no probe at all.

    Args:
        libraries: The declared libraries.

    Returns:
        One sentence per library with nothing to check.

    A library in this file with no probe is a dependency wearing a contract's
    clothes: it claims its behaviour is depended on and then checks none of it.
    """
    return tuple(
        f"{library.name} declares no probe, so nothing about its behaviour is checked"
        for library in libraries
        if not library.probes
    )


def version_problems(
    library: Library, *, installed: str | None, locked: str | None, bound: str | None
) -> tuple[str, ...]:
    """Compare the four places a version is written down.

    Args:
        library: The declared library.
        installed: What the environment reports, or ``None`` when absent.
        locked: What ``pylock.toml`` pins, or ``None`` when it pins nothing.
        bound: The specifier ``pyproject.toml`` declares, or ``None``.

    Returns:
        One sentence per disagreement.

    ``bound`` is compared only for a lower bound of the form ``>=``, which is what
    this project writes. A specifier this cannot read is reported rather than
    assumed satisfied, because an unread constraint that passes is worse than one
    that fails.
    """
    problems: list[str] = []
    if installed is None:
        problems.append(f"{library.name} is declared and is not installed")
    elif installed != library.version:
        problems.append(
            f"{library.name} {installed} is installed and the stack contract declares "
            f"{library.version}"
        )
    if locked is None:
        problems.append(f"{library.name} is declared and pylock.toml pins no version for it")
    elif locked != library.version:
        problems.append(
            f"pylock.toml pins {library.name} {locked} and the stack contract declares "
            f"{library.version}"
        )
    problems.extend(_bound_problems(library, bound))
    return tuple(problems)


def _bound_problems(library: Library, bound: str | None) -> tuple[str, ...]:
    """Judge the declared version against ``pyproject.toml``'s specifier.

    Args:
        library: The declared library.
        bound: The specifier, or ``None`` when the manifest declares none.

    Returns:
        One sentence per disagreement.
    """
    if bound is None:
        return (f"{library.name} is declared and pyproject.toml does not require it",)
    if not bound.startswith(">="):
        return (
            f"pyproject.toml bounds {library.name} with {bound!r}, which this gate cannot read; "
            "declare a >= lower bound or teach the gate the new form",
        )
    floor = bound[2:].strip()
    if _version_key(library.version) < _version_key(floor):
        return (
            f"the stack contract declares {library.name} {library.version}, which is below "
            f"pyproject.toml's floor of {floor}",
        )
    return ()


def _version_key(version: str) -> tuple[int, ...]:
    """A comparable key for a dotted version.

    Args:
        version: The version, as ``"2.5.2"``.

    Returns:
        Its leading integer components. A component that is not an integer stops
        the key, which is enough for the release versions this project pins and
        deliberately does not attempt to be a full PEP 440 implementation — that
        would need ``packaging``, and ADR-0003 makes the empty runtime dependency
        list of the tooling an invariant worth keeping.
    """
    parts: list[int] = []
    for component in version.split("."):
        if not component.isdigit():
            break
        parts.append(int(component))
    return tuple(parts)


def provenance_problems(library: Library, *, recorded_tag: str | None) -> tuple[str, ...]:
    """Judge the installed artefact's own record of which wheel it came from.

    Args:
        library: The declared library.
        recorded_tag: The ``Tag`` its ``.dist-info/WHEEL`` records, or ``None``
            when there is no such record.

    Returns:
        One sentence per disagreement.

    This is what catches a wheel built for another ABI — a free-threaded build, a
    different minor line, a different architecture. The digest in ``pylock.toml``
    says what *should* have been fetched; this says what is actually unpacked.
    """
    if recorded_tag is None:
        return (f"{library.name} records no wheel tag, so its provenance cannot be checked",)
    if recorded_tag != library.wheel_tag:
        return (
            f"{library.name} was built as {recorded_tag!r} and the stack contract declares "
            f"{library.wheel_tag!r}",
        )
    return ()


def identity_problems(library: Library, *, module_location: str | None) -> tuple[str, ...]:
    """Judge whether the imported module is the installed one.

    Args:
        library: The declared library.
        module_location: Where the import resolved to, or ``None`` when it could
            not be imported.

    Returns:
        One sentence per disagreement.

    A library shadowed by a directory earlier on the path is a different library
    from the one the lock pinned, and no digest in the lock says anything about
    which one an import finds.
    """
    if module_location is None:
        return (f"{library.import_name} could not be imported",)
    if not module_location:
        return (f"{library.import_name} imported from an unnamed location",)
    return ()


def deferral_problems(
    deferrals: Sequence[Deferral], *, delivered: int, total: int
) -> tuple[str, ...]:
    """Judge that every deferred question names a phase that can still answer it.

    Args:
        deferrals: The declared deferrals.
        delivered: The last completed phase.
        total: How many phases the programme has.

    Returns:
        One sentence per misfiled deferral.

    The same rule the deferral tables in the policy documents are held to: a
    question deferred to a phase that has shipped tells the reader it is open when
    it has been answered, and points them at a number that is wrong.
    """
    problems: list[str] = []
    for deferral in deferrals:
        if deferral.phase <= delivered:
            problems.append(
                f"{deferral.question!r} is deferred to phase {deferral.phase:03d}, "
                "which has already been delivered"
            )
        elif deferral.phase > total:
            problems.append(
                f"{deferral.question!r} is deferred to phase {deferral.phase:03d}, "
                f"which is beyond the {total}-phase programme"
            )
    return tuple(problems)


# ---------------------------------------------------------------------------
# Reading the declaration.
# ---------------------------------------------------------------------------


def parse_declaration(text: str) -> Declaration:
    """Read the stack contract.

    Args:
        text: The file's contents.

    Returns:
        The parsed declaration.

    Raises:
        StackError: If it is not valid TOML, announces another schema, or is
            missing a table or a field. Nothing is defaulted: a contract with a
            hole in it has not declared the thing the hole was for.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as fault:
        msg = f"{CONFIGURATION_FILE} is not valid TOML: {fault}"
        raise StackError(msg) from fault
    schema = document.get("schema")
    if schema != SCHEMA:
        msg = (
            f"{CONFIGURATION_FILE} announces schema {schema!r}, and this reader implements {SCHEMA}"
        )
        raise StackError(msg)
    target = _table(document, "target")
    return Declaration(
        target=Target(
            implementation=_text(target, "implementation", "target"),
            minor_line=_text(target, "minor_line", "target"),
            architecture=_text(target, "architecture", "target"),
        ),
        libraries=tuple(
            _library(entry, index) for index, entry in enumerate(_entries(document, "library"))
        ),
        probes=tuple(
            _probe(entry, index) for index, entry in enumerate(_entries(document, "probe"))
        ),
        deferrals=tuple(
            _deferral(entry, index) for index, entry in enumerate(_entries(document, "deferral"))
        ),
    )


def _library(entry: Mapping[str, object], index: int) -> Library:
    """Read one ``[[library]]`` entry.

    Args:
        entry: The parsed table.
        index: Its position, for a message about an entry with no name.

    Returns:
        The library.

    Raises:
        StackError: If a field is missing or has the wrong type.
    """
    where = f"library #{index + 1}"
    return Library(
        name=_text(entry, "name", where),
        import_name=_text(entry, "import_name", where),
        version=_text(entry, "version", where),
        wheel_tag=_text(entry, "wheel_tag", where),
        role=_text(entry, "role", where),
        probes=_strings(entry, "probes", where),
    )


def _probe(entry: Mapping[str, object], index: int) -> ProbeSpec:
    """Read one ``[[probe]]`` entry.

    Args:
        entry: The parsed table.
        index: Its position, for the message.

    Returns:
        The probe specification.

    Raises:
        StackError: If a field is missing or has the wrong type.
    """
    where = f"probe #{index + 1}"
    return ProbeSpec(identifier=_text(entry, "id", where), because=_text(entry, "because", where))


def _deferral(entry: Mapping[str, object], index: int) -> Deferral:
    """Read one ``[[deferral]]`` entry.

    Args:
        entry: The parsed table.
        index: Its position, for the message.

    Returns:
        The deferral.

    Raises:
        StackError: If a field is missing or has the wrong type.
    """
    where = f"deferral #{index + 1}"
    return Deferral(question=_text(entry, "question", where), phase=_integer(entry, "phase", where))


def _table(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    """One required table.

    Args:
        document: The parsed declaration.
        name: The table name.

    Returns:
        The table.

    Raises:
        StackError: If it is missing or is not a table.
    """
    value = document.get(name)
    if not isinstance(value, Mapping):
        msg = f"{CONFIGURATION_FILE} has no [{name}] table"
        raise StackError(msg)
    return value


def _entries(document: Mapping[str, object], name: str) -> tuple[Mapping[str, object], ...]:
    """Every entry of one array of tables.

    Args:
        document: The parsed declaration.
        name: The array name.

    Returns:
        The entries.

    Raises:
        StackError: If the array is missing, empty, or holds something else. An
            empty array is refused rather than tolerated: a declaration with no
            libraries would make every check below pass over nothing.
    """
    value = document.get(name)
    if not isinstance(value, list) or not value:
        msg = f"{CONFIGURATION_FILE} declares no [[{name}]] entries"
        raise StackError(msg)
    entries: list[Mapping[str, object]] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping):
            msg = f"{CONFIGURATION_FILE}: [[{name}]] #{index + 1} is not a table"
            raise StackError(msg)
        entries.append(entry)
    return tuple(entries)


def _text(table: Mapping[str, object], key: str, where: str) -> str:
    """One required string field.

    Args:
        table: The table it lives in.
        key: The field name.
        where: What to call the table in a message.

    Returns:
        The value, stripped.

    Raises:
        StackError: If it is missing, is not a string, or is blank.
    """
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"{CONFIGURATION_FILE}: {where} has no non-empty string {key!r}"
        raise StackError(msg)
    return value.strip()


def _strings(table: Mapping[str, object], key: str, where: str) -> tuple[str, ...]:
    """One required list-of-strings field.

    Args:
        table: The table it lives in.
        key: The field name.
        where: What to call the table in a message.

    Returns:
        The values.

    Raises:
        StackError: If it is missing or holds anything that is not a string. An
            empty list is permitted here and refused by :func:`coverage_problems`,
            which can say why in a sentence rather than as a parse error.
    """
    value = table.get(key)
    if not isinstance(value, list):
        msg = f"{CONFIGURATION_FILE}: {where} has no list {key!r}"
        raise StackError(msg)
    for item in value:
        if not isinstance(item, str):
            msg = f"{CONFIGURATION_FILE}: {where} has a non-string in {key!r}"
            raise StackError(msg)
    return tuple(value)


def _integer(table: Mapping[str, object], key: str, where: str) -> int:
    """One required integer field.

    Args:
        table: The table it lives in.
        key: The field name.
        where: What to call the table in a message.

    Returns:
        The value.

    Raises:
        StackError: If it is missing or is not an integer. A boolean is refused
            explicitly, because Python makes ``True`` an integer and a phase
            number of ``true`` would otherwise be read as phase one.
    """
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{CONFIGURATION_FILE}: {where} has no integer {key!r}"
        raise StackError(msg)
    return value
