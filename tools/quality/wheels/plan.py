"""What the wheel survey declares, and every judgement made about it.

Pure. Every function here takes text or values and returns findings; nothing reads
a file, opens a socket or looks at the clock. That is what lets the whole of the
reasoning be tested from literals, offline, in the way
``tools/quality/governance/plan.py`` separates its judgements from its gate.

**The tag matcher is a deliberate subset, and saying so is the point.** PEP 425
describes a compatibility set an installer computes for the interpreter it is
running on; this module answers a narrower question — *does a wheel exist that the
pinned interpreter could install* — for one implementation, one minor line and one
platform. It does not rank candidates, does not model manylinux or macOS version
ranges, and does not decide what ``pip`` would ultimately choose. Implementing
those to a standard nothing here would exercise would be untested code guarding
nothing, while implementing them badly would report availability an installer does
not agree with.

**Substring matching would get this wrong, and did.** ``xgboost`` and ``lightgbm``
publish ``py3-none-win_amd64`` — platform-specific and interpreter-agnostic,
because the native code is loaded through ``ctypes`` rather than built against a
Python ABI. A survey grepping filenames for ``cp314`` reports a gap in both that
does not exist. The reverse error is worse: ``cp314-cp314-win_amd64`` looks like it
would serve a free-threaded ``3.14t`` interpreter and does not, because the
free-threaded build has its own ABI. Tags are parsed, and the pairing of the
interpreter tag with the ABI tag is what decides.

**The version-specifier reader is narrower still, and refuses rather than guesses.**
It answers one question — does this ``Requires-Python`` admit the pinned minor line
— and supports only the four bound operators that question has an unambiguous
answer for. ``==``, ``!=``, ``~=`` and wildcards are refused by name, as is a bound
carrying a patch component *inside* the pinned line, because a minor line alone
cannot decide it. That is ``ENGINEERING_CONTRACT.md`` invariant 2: on ambiguity,
refuse.
"""

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Final

CONFIGURATION_FILE: Final[str] = "docs/engineering/wheel-survey.toml"
"""Where the declaration lives, relative to the repository root."""

SCHEMA: Final[int] = 1
"""The declaration format this module reads."""

AVAILABLE: Final[str] = "available"
"""A wheel matching the target exists."""

SOURCE_ONLY: Final[str] = "source-only"
"""No matching wheel; installing would build from a source distribution."""

ABSENT: Final[str] = "absent"
"""The distribution publishes nothing usable for the target."""

VERDICTS: Final[frozenset[str]] = frozenset({AVAILABLE, SOURCE_ONLY, ABSENT})
"""The whole verdict vocabulary. There is no fourth word.

Only :data:`AVAILABLE` is decidable offline from the record: it holds exactly when
a recorded filename satisfies the target. The other two both mean "no wheel", and
telling them apart requires asking the index whether a source distribution exists,
which is the probe's job rather than the gate's.
"""

PLATFORM_TAGS: Final[Mapping[str, str]] = {"AMD64": "win_amd64"}
"""How an architecture as the runtime contract spells it maps to a PEP 425 platform tag.

One entry, because one architecture is supported. An architecture absent from here
is refused rather than guessed at: ``ARM64`` would be ``win_arm64`` and inventing
that mapping without a host to check it against is exactly the assumption Phase 018
exists to remove.
"""

ANY_PLATFORM: Final[str] = "any"
"""The platform tag of a wheel that runs anywhere."""

NO_ABI: Final[str] = "none"
"""The ABI tag of a wheel that binds to no Python ABI."""

STABLE_ABI: Final[str] = "abi3"
"""The ABI tag of a wheel built against the limited API."""

SUPPORTED_OPERATORS: Final[frozenset[str]] = frozenset({">=", ">", "<=", "<"})
"""The version-specifier operators :func:`admits` can decide for a minor line."""

CPYTHON: Final[str] = "CPython"
"""The one implementation this survey reasons about."""

_WHEEL_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<distribution>[A-Za-z0-9_.]+)"
    r"-(?P<version>[A-Za-z0-9_.!+]+)"
    r"(?:-(?P<build>[0-9][A-Za-z0-9_.]*))?"
    r"-(?P<python>[A-Za-z0-9_.]+)"
    r"-(?P<abi>[A-Za-z0-9_.]+)"
    r"-(?P<platform>[A-Za-z0-9_.]+)"
    r"\.whl$"
)
"""PEP 427's filename grammar, as far as this module needs it."""

_SPECIFIER_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<operator>[<>=!~]{1,3})\s*(?P<version>[0-9]+(?:\.[0-9]+)*)$"
)
"""One clause of a ``Requires-Python`` value, restricted to numeric releases."""

_MINOR_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<major>[0-9]+)\.(?P<minor>[0-9]+)$")
"""A minor line, as ``runtime-contract.toml`` spells it."""


class WheelSurveyError(Exception):
    """The wheel survey could not be read, or a value in it could not be decided."""


@dataclass(frozen=True, slots=True, order=True)
class Wheel:
    """One wheel filename, parsed into the tags that decide compatibility.

    Args:
        filename: The name as published, kept so a finding can quote it.
        distribution: The normalised distribution name.
        version: The version segment, as written.
        python_tags: The interpreter tags, with a compressed set expanded.
        abi_tags: The ABI tags, likewise.
        platform_tags: The platform tags, likewise.
    """

    filename: str
    distribution: str
    version: str
    python_tags: tuple[str, ...]
    abi_tags: tuple[str, ...]
    platform_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Target:
    """The environment the survey is conducted against.

    Args:
        implementation: The interpreter implementation, as the runtime contract
            spells it.
        minor_line: The interpreter's minor line, ``"3.14"``.
        architecture: The machine architecture, as the runtime contract spells it.
        platform_tag: The PEP 425 spelling of that architecture on this host.
        free_threaded: Whether the target is a free-threaded build.
        index: The package index the survey read.
        surveyed: The date it was read, as an ISO string.
    """

    implementation: str
    minor_line: str
    architecture: str
    platform_tag: str
    free_threaded: bool
    index: str
    surveyed: str

    @property
    def release(self) -> tuple[int, int]:
        """The minor line as a comparable pair.

        Returns:
            ``(major, minor)``.

        Raises:
            WheelSurveyError: If the minor line is not ``major.minor``.
        """
        found = _MINOR_RE.match(self.minor_line)
        if found is None:
            msg = f"{CONFIGURATION_FILE}: target.minor_line {self.minor_line!r} is not major.minor"
            raise WheelSurveyError(msg)
        return int(found["major"]), int(found["minor"])

    @property
    def interpreter_tag(self) -> str:
        """The wheel tag naming this interpreter exactly.

        Returns:
            ``"cp314"`` for CPython 3.14.
        """
        major, minor = self.release
        return f"cp{major}{minor}"

    @property
    def abi_tag(self) -> str:
        """The wheel tag naming this build's ABI exactly.

        Returns:
            ``"cp314"`` for the default build, ``"cp314t"`` for the free-threaded
            one.
        """
        return f"{self.interpreter_tag}t" if self.free_threaded else self.interpreter_tag

    def free_threaded_twin(self) -> "Target":
        """The same target, built without the global interpreter lock.

        Returns:
            A copy with ``free_threaded`` inverted to ``True``.

        Phase 018 owns ADR-0050's provisional refusal of the free-threaded build,
        and the refusal is only worth anything if somebody computed what adopting
        it would cost. This is how that second verdict is reached without a second
        declaration to keep in step.
        """
        return replace(self, free_threaded=True)


@dataclass(frozen=True, slots=True, order=True)
class Library:
    """One library the roadmap schedules, and what the index said about it.

    Args:
        name: The PyPI distribution name.
        phase: The roadmap phase that schedules it.
        version: The version surveyed.
        requires_python: The distribution's published ``Requires-Python``.
        wheels: The filenames observed that could serve the target line.
        verdict: One of :data:`VERDICTS`.
        source: Where the metadata was read.
        reason: Why this library is in the survey, and anything notable about it.
        resolved_by: The phase that must resolve a gap, or ``None`` when there is
            no gap. Required exactly when the verdict is not :data:`AVAILABLE`.
    """

    name: str
    phase: int
    version: str
    requires_python: str
    wheels: tuple[str, ...]
    verdict: str
    source: str
    reason: str
    resolved_by: int | None = None


@dataclass(frozen=True, slots=True)
class Declaration:
    """The whole survey, as declared.

    Args:
        target: The environment surveyed against.
        libraries: Every surveyed library, in declaration order.
    """

    target: Target
    libraries: tuple[Library, ...]


def parse_wheel_filename(filename: str) -> Wheel:
    """Read a wheel filename into its tags.

    Args:
        filename: The name as published, including the ``.whl`` suffix.

    Returns:
        The parsed wheel, with every compressed tag set expanded.

    Raises:
        WheelSurveyError: If the name is not a wheel filename.

    A compressed tag set such as ``py2.py3`` is expanded here rather than at the
    point of comparison, so that every caller sees one shape.
    """
    found = _WHEEL_RE.match(filename)
    if found is None:
        msg = f"{filename!r} is not a wheel filename"
        raise WheelSurveyError(msg)
    return Wheel(
        filename=filename,
        distribution=found["distribution"],
        version=found["version"],
        python_tags=tuple(found["python"].split(".")),
        abi_tags=tuple(found["abi"].split(".")),
        platform_tags=tuple(found["platform"].split(".")),
    )


def _python_tag_admits(tag: str, *, minor: int, exact_only: bool) -> bool:
    """Whether an interpreter tag names a version the target could run.

    Args:
        tag: One interpreter tag, such as ``py3`` or ``cp313``.
        minor: The target's minor version.
        exact_only: When true, only the target's own ``cp3N`` tag qualifies.

    Returns:
        Whether the tag is in the target interpreter's compatibility set.

    ``exact_only`` is what separates an ABI-bound wheel from an ABI-free one. A
    ``cp312-none-any`` wheel installs on 3.14 because it binds to no ABI, while a
    ``cp312-cp312-win_amd64`` wheel does not, because 3.14 does not provide 3.12's
    ABI.
    """
    if tag == f"cp3{minor}":
        return True
    if exact_only:
        return False
    if tag == "py3":
        return True
    for prefix in ("py3", "cp3"):
        if tag.startswith(prefix) and tag[len(prefix) :].isdigit():
            return int(tag[len(prefix) :]) <= minor
    return False


def _pair_admits(python_tag: str, abi_tag: str, target: Target) -> bool:
    """Whether one interpreter-and-ABI pairing serves the target.

    Args:
        python_tag: One interpreter tag from the filename.
        abi_tag: One ABI tag from the filename.
        target: The environment surveyed against.

    Returns:
        Whether a wheel carrying this pairing could be installed.

    The pairing is judged together because neither half decides alone. An ABI tag
    of ``none`` frees the interpreter tag to be any version at or below the
    target's; the target's own ABI tag pins the interpreter tag to match exactly;
    and the free-threaded ABI and the default ABI never substitute for each other.
    """
    _, minor = target.release
    if abi_tag == NO_ABI:
        return _python_tag_admits(python_tag, minor=minor, exact_only=False)
    if abi_tag == STABLE_ABI:
        # The limited API is not offered by a free-threaded build, so a stable-ABI
        # wheel is not a route onto one. Recording that as "no" rather than "yes"
        # is what keeps the free-threaded finding honest.
        if target.free_threaded:
            return False
        return _python_tag_admits(python_tag, minor=minor, exact_only=False)
    if abi_tag == target.abi_tag:
        return _python_tag_admits(python_tag, minor=minor, exact_only=True)
    return False


def satisfies(wheel: Wheel, target: Target) -> bool:
    """Whether a wheel could be installed on the target.

    Args:
        wheel: The parsed filename.
        target: The environment surveyed against.

    Returns:
        Whether any pairing of the wheel's tags serves the target, on a platform
        the target can use.
    """
    if target.implementation != CPYTHON:
        return False
    platforms = set(wheel.platform_tags)
    if ANY_PLATFORM not in platforms and target.platform_tag not in platforms:
        return False
    return any(
        _pair_admits(python_tag, abi_tag, target)
        for python_tag in wheel.python_tags
        for abi_tag in wheel.abi_tags
    )


def serving_wheels(filenames: Sequence[str], target: Target) -> tuple[str, ...]:
    """Every recorded filename that serves the target.

    Args:
        filenames: The filenames recorded for one library.
        target: The environment surveyed against.

    Returns:
        The subset that satisfies the target, in the recorded order.

    Raises:
        WheelSurveyError: If any recorded name is not a wheel filename.
    """
    return tuple(name for name in filenames if satisfies(parse_wheel_filename(name), target))


def admits(specifier: str, target: Target) -> bool:
    """Whether a ``Requires-Python`` value admits the target's minor line.

    Args:
        specifier: The value as published, such as ``"<3.15,>=3.10"``.
        target: The environment surveyed against.

    Returns:
        Whether every clause is satisfied by the target's minor line.

    Raises:
        WheelSurveyError: If a clause is empty, malformed, uses an operator this
            module does not decide, or bounds a patch version inside the target's
            own minor line.

    An empty specifier is refused rather than read as "any version". A distribution
    that publishes no ``Requires-Python`` has said nothing, and treating silence as
    permission is the failure mode ``AGENTS.md`` calls out by name.
    """
    if not specifier.strip():
        msg = "an empty Requires-Python says nothing, and silence is not permission"
        raise WheelSurveyError(msg)
    line = target.release
    for raw in specifier.split(","):
        clause = raw.strip()
        found = _SPECIFIER_RE.match(clause)
        if found is None:
            msg = f"Requires-Python clause {clause!r} is not a numeric release bound"
            raise WheelSurveyError(msg)
        operator = found["operator"]
        if operator not in SUPPORTED_OPERATORS:
            supported = ", ".join(sorted(SUPPORTED_OPERATORS))
            msg = (
                f"Requires-Python clause {clause!r} uses {operator!r}, which this module "
                f"does not decide against a minor line. Supported: {supported}"
            )
            raise WheelSurveyError(msg)
        bound = tuple(int(part) for part in found["version"].split("."))
        if len(bound) > 2 and bound[:2] == line:
            msg = (
                f"Requires-Python clause {clause!r} bounds a patch version inside "
                f"{target.minor_line}, which a minor line alone cannot decide"
            )
            raise WheelSurveyError(msg)
        if not _bound_holds(operator, line, bound):
            return False
    return True


def _bound_holds(operator: str, line: tuple[int, ...], bound: tuple[int, ...]) -> bool:
    """Whether a minor line satisfies one release bound.

    Args:
        operator: One of :data:`SUPPORTED_OPERATORS`.
        line: The target's release tuple.
        bound: The clause's release tuple.

    Returns:
        The comparison, with both tuples zero-padded to equal length.
    """
    width = max(len(line), len(bound))
    left = (*line, *(0,) * (width - len(line)))
    right = (*bound, *(0,) * (width - len(bound)))
    if operator == ">=":
        return left >= right
    if operator == ">":
        return left > right
    if operator == "<=":
        return left <= right
    return left < right


def platform_tag_for(architecture: str) -> str:
    """The PEP 425 platform tag for an architecture the runtime contract names.

    Args:
        architecture: The architecture, as ``runtime-contract.toml`` spells it.

    Returns:
        The platform tag.

    Raises:
        WheelSurveyError: If no mapping is recorded for it.
    """
    tag = PLATFORM_TAGS.get(architecture)
    if tag is None:
        known = ", ".join(sorted(PLATFORM_TAGS))
        msg = f"no platform tag is recorded for architecture {architecture!r}. Known: {known}"
        raise WheelSurveyError(msg)
    return tag


def target_problems(
    target: Target,
    *,
    implementation: str,
    minor_line: str,
    architecture: str,
    free_threaded: bool,
) -> tuple[str, ...]:
    """Compare the survey's target against the runtime contract.

    Args:
        target: The target the survey declares.
        implementation: What the runtime contract declares.
        minor_line: Likewise.
        architecture: Likewise.
        free_threaded: Likewise.

    Returns:
        One sentence per disagreement, empty when the two agree.

    The survey's ``[target]`` is a tripwire rather than a second source of truth.
    A survey conducted against an interpreter the project does not run is not
    merely stale, it is misleading — it would report availability for a line
    nothing here uses while the pinned line went unexamined.
    """
    problems: list[str] = []
    for label, declared, contracted in (
        ("implementation", target.implementation, implementation),
        ("minor_line", target.minor_line, minor_line),
        ("architecture", target.architecture, architecture),
    ):
        if declared != contracted:
            problems.append(
                f"target.{label} is {declared!r} but the runtime contract declares {contracted!r}"
            )
    if target.free_threaded != free_threaded:
        problems.append(
            f"target.free_threaded is {target.free_threaded} but the runtime contract "
            f"declares {free_threaded}"
        )
    try:
        expected = platform_tag_for(architecture)
    except WheelSurveyError as fault:
        problems.append(str(fault))
        return tuple(problems)
    if target.platform_tag != expected:
        problems.append(
            f"target.platform_tag is {target.platform_tag!r}, but {architecture!r} is "
            f"{expected!r} under PEP 425"
        )
    return tuple(problems)


def verdict_problems(library: Library, target: Target) -> tuple[str, ...]:
    """Recompute a library's verdict from its own recorded evidence.

    Args:
        library: The declared entry.
        target: The environment surveyed against.

    Returns:
        One sentence per problem, empty when the record is consistent.

    This is what stops the declaration from being a transcription. A verdict is a
    claim about a set of filenames, so the filenames are recorded and the claim is
    recomputed; an entry asserting availability whose own evidence does not
    support it fails here, offline, without asking the index anything.
    """
    problems: list[str] = []
    if library.verdict not in VERDICTS:
        known = ", ".join(sorted(VERDICTS))
        problems.append(f"{library.name}: verdict {library.verdict!r} is not one of {known}")
        return tuple(problems)
    try:
        serving = serving_wheels(library.wheels, target)
        admitted = admits(library.requires_python, target)
    except WheelSurveyError as fault:
        problems.append(f"{library.name}: {fault}")
        return tuple(problems)

    if library.verdict == AVAILABLE and not serving:
        problems.append(
            f"{library.name}: recorded as {AVAILABLE!r}, but none of its "
            f"{len(library.wheels)} recorded wheels serves {_describe(target)}"
        )
    if library.verdict != AVAILABLE and serving:
        problems.append(
            f"{library.name}: recorded as {library.verdict!r}, but "
            f"{serving[0]!r} serves {_describe(target)}"
        )
    if not admitted:
        problems.append(
            f"{library.name}: Requires-Python {library.requires_python!r} does not admit "
            f"{target.minor_line}, so the pinned line is outside what this project supports"
        )
    for filename in library.wheels:
        wheel = parse_wheel_filename(filename)
        if wheel.version != library.version:
            problems.append(
                f"{library.name}: records version {library.version!r} but {filename!r} "
                f"carries {wheel.version!r}"
            )
    return tuple(problems)


def _describe(target: Target) -> str:
    """Name a target in a sentence.

    Args:
        target: The environment.

    Returns:
        A short description such as ``CPython 3.14 on win_amd64``, with the
        free-threaded build named when that is what is meant.
    """
    build = " free-threaded" if target.free_threaded else ""
    return f"{target.implementation} {target.minor_line}{build} on {target.platform_tag}"


def free_threaded_gaps(libraries: Sequence[Library], target: Target) -> tuple[str, ...]:
    """Which libraries would not install on a free-threaded build of the same line.

    Args:
        libraries: Every surveyed library.
        target: The declared target, which must not itself be free-threaded.

    Returns:
        The names of libraries with no wheel for the free-threaded twin, sorted.

    Raises:
        WheelSurveyError: If the declared target is already free-threaded, in
            which case this comparison has nothing to say.

    ADR-0050 refused the free-threaded build because *"Phase 018 has not yet
    surveyed whether the planned stack publishes for it"*. This is that survey. A
    single gap is enough to keep the refusal standing, and naming which one is
    what makes the refusal revisitable rather than permanent.
    """
    if target.free_threaded:
        msg = "the declared target is already free-threaded, so there is no twin to compare"
        raise WheelSurveyError(msg)
    twin = target.free_threaded_twin()
    return tuple(
        sorted(library.name for library in libraries if not serving_wheels(library.wheels, twin))
    )


def phase_problems(libraries: Sequence[Library], *, delivered: int, total: int) -> tuple[str, ...]:
    """Check that every entry names a real, undelivered phase.

    Args:
        libraries: Every surveyed library.
        delivered: The last completed phase.
        total: How many phases the programme has.

    Returns:
        One sentence per problem, empty when every entry is well placed.

    A library scheduled by a phase that has already shipped is not a survey entry,
    it is a dependency nobody adopted — and one scheduled by a phase beyond the
    programme is a typing error that would otherwise sit unread for years.
    """
    problems: list[str] = []
    for library in libraries:
        if library.phase <= delivered:
            problems.append(
                f"{library.name}: phase {library.phase:03d} is already delivered, so this is "
                f"an adoption rather than a survey entry"
            )
        elif library.phase > total:
            problems.append(
                f"{library.name}: phase {library.phase:03d} is beyond the {total}-phase programme"
            )
    return tuple(problems)


def gap_problems(libraries: Sequence[Library], *, delivered: int, total: int) -> tuple[str, ...]:
    """Check that every recorded gap is owned by a phase that can still close it.

    Args:
        libraries: Every surveyed library.
        delivered: The last completed phase.
        total: How many phases the programme has.

    Returns:
        One sentence per problem, empty when every gap is owned.

    A gap is not a failure. The roadmap asks this phase to *record* each gap
    rather than assume one, and a library whose upstream publishes no wheel is not
    something a gate can fix by going red. What is a failure is an **unowned**
    gap: recorded, then nobody's, then forgotten. So the verdict may say there is
    no wheel, and the entry must then name the phase that answers for it — the
    same bargain ``vulnerability-waivers.toml`` strikes, where the thing demanded
    is not the absence of a problem but a name against it.
    """
    problems: list[str] = []
    for library in libraries:
        if library.verdict == AVAILABLE:
            if library.resolved_by is not None:
                problems.append(
                    f"{library.name}: has a wheel, so resolved_by "
                    f"{library.resolved_by:03d} names a phase with nothing to do"
                )
            continue
        if library.resolved_by is None:
            problems.append(
                f"{library.name}: recorded as {library.verdict!r} with no resolved_by, "
                f"so the gap belongs to nobody"
            )
        elif library.resolved_by <= delivered:
            problems.append(
                f"{library.name}: resolved_by {library.resolved_by:03d} is already "
                f"delivered, so the gap was recorded against a phase that has shipped"
            )
        elif library.resolved_by > total:
            problems.append(
                f"{library.name}: resolved_by {library.resolved_by:03d} is beyond the "
                f"{total}-phase programme"
            )
    return tuple(problems)


def duplicate_libraries(libraries: Sequence[Library]) -> tuple[str, ...]:
    """Report any distribution surveyed more than once.

    Args:
        libraries: Every surveyed library.

    Returns:
        The repeated names, sorted.

    Two entries for one distribution would let the survey hold two verdicts about
    it, and nothing would say which one a reader should believe.
    """
    seen: dict[str, int] = {}
    for library in libraries:
        seen[library.name] = seen.get(library.name, 0) + 1
    return tuple(sorted(name for name, count in seen.items() if count > 1))


def read_declaration(document: Mapping[str, object]) -> Declaration:
    """Build the declaration from a parsed TOML document.

    Args:
        document: The parsed declaration.

    Returns:
        The declaration.

    Raises:
        WheelSurveyError: If the schema is unknown or any value is malformed.
    """
    schema = document.get("schema")
    if schema != SCHEMA:
        msg = (
            f"this tool reads {CONFIGURATION_FILE} schema {SCHEMA}, and the file "
            f"declares {schema!r}. Update the tool rather than reading it anyway"
        )
        raise WheelSurveyError(msg)

    table = _table(document, "target")
    target = Target(
        implementation=_text(table, "implementation", "target"),
        minor_line=_text(table, "minor_line", "target"),
        architecture=_text(table, "architecture", "target"),
        platform_tag=_text(table, "platform_tag", "target"),
        free_threaded=_flag(table, "free_threaded", "target"),
        index=_text(table, "index", "target"),
        surveyed=_date(table, "surveyed", "target"),
    )

    libraries = tuple(
        Library(
            name=_text(entry, "name", "library"),
            phase=_integer(entry, "phase", "library"),
            version=_text(entry, "version", "library"),
            requires_python=_text(entry, "requires_python", "library"),
            wheels=_strings(entry, "wheels", "library"),
            verdict=_text(entry, "verdict", "library"),
            source=_text(entry, "source", "library"),
            reason=_text(entry, "reason", "library"),
            resolved_by=_optional_integer(entry, "resolved_by", "library"),
        )
        for entry in _entries(document, "library")
    )
    if not libraries:
        msg = "library is empty: a wheel survey with no library surveys nothing"
        raise WheelSurveyError(msg)
    return Declaration(target=target, libraries=libraries)


def parse_declaration(text: str) -> Declaration:
    """Read the declaration from TOML text.

    Args:
        text: The contents of ``wheel-survey.toml``.

    Returns:
        The declaration.

    Raises:
        WheelSurveyError: If the text is not TOML, or the declaration is
            malformed.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as fault:
        msg = f"{CONFIGURATION_FILE} is not valid TOML: {fault}"
        raise WheelSurveyError(msg) from fault
    return read_declaration(document)


def _table(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    """Read a required sub-table.

    Args:
        document: The parsed declaration.
        name: The table's name.

    Returns:
        The table.

    Raises:
        WheelSurveyError: If it is absent or is not a table.
    """
    value = document.get(name)
    if not isinstance(value, Mapping):
        msg = f"{CONFIGURATION_FILE} has no [{name}] table"
        raise WheelSurveyError(msg)
    return value


def _entries(document: Mapping[str, object], name: str) -> tuple[Mapping[str, object], ...]:
    """Read an array of tables.

    Args:
        document: The parsed declaration.
        name: The array's name.

    Returns:
        Its entries, empty when the array is absent.

    Raises:
        WheelSurveyError: If the value is not a list of tables.
    """
    value = document.get(name, [])
    if not isinstance(value, list):
        msg = f"{CONFIGURATION_FILE}: [[{name}]] must be an array of tables"
        raise WheelSurveyError(msg)
    for entry in value:
        if not isinstance(entry, Mapping):
            found = type(entry).__name__
            msg = f"{CONFIGURATION_FILE}: [[{name}]] holds {found}, expected a table"
            raise WheelSurveyError(msg)
    return tuple(value)


def _text(table: Mapping[str, object], key: str, where: str) -> str:
    """Read a non-empty string.

    Args:
        table: The table holding it.
        key: Which setting.
        where: The table's name, for the message.

    Returns:
        The value.

    Raises:
        WheelSurveyError: If it is absent, is not a string, or is empty.
    """
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be a non-empty string"
        raise WheelSurveyError(msg)
    return value


def _strings(table: Mapping[str, object], key: str, where: str) -> tuple[str, ...]:
    """Read a non-empty list of strings.

    Args:
        table: The table holding it.
        key: Which setting.
        where: The table's name, for the message.

    Returns:
        The values.

    Raises:
        WheelSurveyError: If it is absent, is not a list, is empty, or holds
            anything that is not a string.
    """
    value = table.get(key)
    if not isinstance(value, list) or not value:
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be a non-empty list of strings"
        raise WheelSurveyError(msg)
    for item in value:
        if not isinstance(item, str):
            found = type(item).__name__
            msg = f"{CONFIGURATION_FILE}: {where}.{key} holds {found}, expected a string"
            raise WheelSurveyError(msg)
    return tuple(value)


def _integer(table: Mapping[str, object], key: str, where: str) -> int:
    """Read a positive integer.

    Args:
        table: The table holding it.
        key: Which setting.
        where: The table's name, for the message.

    Returns:
        The value.

    Raises:
        WheelSurveyError: If it is absent, is a :class:`bool`, is not an
            :class:`int`, or is not positive.
    """
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be a positive integer"
        raise WheelSurveyError(msg)
    return value


def _optional_integer(table: Mapping[str, object], key: str, where: str) -> int | None:
    """Read a positive integer that may be absent.

    Args:
        table: The table holding it.
        key: Which setting.
        where: The table's name, for the message.

    Returns:
        The value, or ``None`` when the key is absent.

    Raises:
        WheelSurveyError: If it is present but is not a positive integer.

    Absent and invalid are kept apart deliberately. Absent is a legitimate state
    that means "there is no gap here"; invalid is somebody having written a value
    this module cannot use, and reading that as absence would silently discard the
    only thing they were trying to say.
    """
    if key not in table:
        return None
    return _integer(table, key, where)


def _flag(table: Mapping[str, object], key: str, where: str) -> bool:
    """Read a boolean.

    Args:
        table: The table holding it.
        key: Which setting.
        where: The table's name, for the message.

    Returns:
        The value.

    Raises:
        WheelSurveyError: If it is absent or is not a boolean.
    """
    value = table.get(key)
    if not isinstance(value, bool):
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be true or false"
        raise WheelSurveyError(msg)
    return value


def _date(table: Mapping[str, object], key: str, where: str) -> str:
    """Read a bare TOML date as an ISO string.

    Args:
        table: The table holding it.
        key: Which setting.
        where: The table's name, for the message.

    Returns:
        The date, formatted ``YYYY-MM-DD``.

    Raises:
        WheelSurveyError: If it is absent, or is written as a quoted string
            rather than a bare date.

    A quoted date is refused for the reason ``vulnerability-waivers.toml`` gives:
    TOML has a date type, and a value written as a string has not been validated
    as a date by anything.
    """
    value = table.get(key)
    if not isinstance(value, date):
        msg = (
            f"{CONFIGURATION_FILE}: {where}.{key} writes {value!r}. Write it as a bare TOML "
            f"date (2026-08-16), not as a string — a quoted date does not compare as one"
        )
        raise WheelSurveyError(msg)
    return value.isoformat()
