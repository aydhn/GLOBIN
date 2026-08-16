"""What the lock declares, and every judgement made about it.

Pure. Every function here takes text or values and returns findings; nothing reads
a file, opens a socket or looks at the clock. That is what lets the whole of the
reasoning be tested from literals, offline, in the way
``tools/quality/wheels/plan.py`` separates its judgements from its gate.

**This is a second, independent reader of PEP 751, and that is the point.** The
lock is written by ``pip``'s vendored implementation; validating it with that same
implementation would establish only that pip agrees with itself. So the file is
parsed here with ``tomllib`` and nothing else, and every claim it makes is
recomputed —
[ADR-0054](../../../docs/adr/0054-the-toolchain-is-locked-with-pep-751-and-the-verdict-is-recomputed.md)
records why, and ``docs/research/phase_020_sources.md`` records the evidence.

**Three checks a reader would expect are absent, by construction rather than by
oversight.** A pip-produced lock records only ``lock-version``, ``created-by`` and
``packages`` — no interpreter requirement, no index, no markers, and no dependency
edges (ledger entry S-03). So the environment the lock is valid for is declared
beside it in ``lock-policy.toml`` rather than read out of it; and because there are
no edges, a package that is neither a declared root nor reachable from one cannot
be told apart from an ordinary transitive one. :func:`declaration_problems`
compares **roots** in both directions and the orphaned-transitive case is closed by
relocking. Claiming otherwise would be claiming a coverage this module does not
have.

**The tag work is Phase 018's and is called, not copied.**
:func:`compatibility_problems` builds a :class:`tools.quality.wheels.plan.Target`
and asks ``serving_wheels`` the same question the wheel survey asks. A second tag
parser here would be a second thing to be wrong in a different way.

**A bound this module cannot decide is refused, where the inventory assumes.**
``inventory._satisfies`` returns ``True`` for any specifier it cannot read, which
is right there: a false disagreement would make a gate cry wolf about a version
nobody chose. It is wrong here. A lock exists to say exactly what will be
installed, so a bound whose satisfaction cannot be decided is reported rather than
waved through — ``ENGINEERING_CONTRACT.md`` invariant 2, on ambiguity, refuse.
"""

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final
from urllib.parse import urlsplit

from tools.quality.supply.inventory import (
    CONTINUOUS_INTEGRATION,
    DEVELOPMENT,
    HOOK_MIRROR_SUFFIX,
    PRE_COMMIT,
    PYPI,
    PYPROJECT,
    Dependency,
    release,
)
from tools.quality.wheels.plan import (
    Target,
    WheelSurveyError,
    parse_wheel_filename,
    serving_wheels,
)
from tools.quality.wheels.plan import target_problems as _wheels_target_problems

CONFIGURATION_FILE: Final[str] = "docs/engineering/lock-policy.toml"
"""Where the declaration lives, relative to the repository root."""

SCHEMA: Final[int] = 1
"""The declaration format this module reads."""

SUPPORTED_LOCK_MAJOR: Final[int] = 1
"""The PEP 751 major version this reader implements."""

SUPPORTED_LOCK_MINOR: Final[int] = 0
"""The highest minor within that major this reader implements.

A lock announcing a *higher* minor is refused rather than read optimistically. PEP
751 allows a minor bump to add fields, and a reader that ignored them would be
recomputing a verdict from an incomplete picture while reporting a complete one.
"""

WEAK_ALGORITHMS: Final[frozenset[str]] = frozenset({"md5", "sha1"})
"""Digest algorithms refused by name, whatever the policy says.

Both have practical collision attacks. A policy permitting one would be a policy
this module declines to enforce, so the refusal sits here rather than in the
declaration, where somebody could widen it.
"""

HASH_WIDTHS: Final[Mapping[str, int]] = {"sha256": 64, "sha384": 96, "sha512": 128}
"""How many hexadecimal characters each permitted algorithm produces.

An algorithm absent from here cannot be checked for shape, so the declaration is
refused rather than the value trusted. That is the same stance
``wheels.plan.PLATFORM_TAGS`` takes about an architecture it has no mapping for.
"""

DIRECT_KINDS: Final[tuple[str, ...]] = ("vcs", "directory", "archive")
"""Package shapes PEP 751 permits and this repository refuses.

Each names a source that is not an artefact on the declared index: a revision in
somebody's repository, a path on somebody's disk, an archive at an arbitrary URL.
None is reproducible from the index the declaration names, and ``pip-audit``
reports a package with no version as skipped, which under ``--strict`` fails the
audit anyway. Refusing them here names the reason.
"""

HTTPS: Final[str] = "https"
"""The only scheme an artefact may be served over."""

_HEX_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]+$")
"""A digest, lowercase. Uppercase is refused so two spellings cannot both be canonical."""

_LOCK_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<major>[0-9]+)\.(?P<minor>[0-9]+)$")
"""PEP 751's ``lock-version``, which is ``major.minor``."""

_NORMALISE_RE: Final[re.Pattern[str]] = re.compile(r"[-_.]+")
"""PEP 503's runs of separator characters, which normalise to one hyphen."""

_REQUIREMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?P<specifier>.*)$"
)
"""A declared root: a distribution name and whatever bounds it."""

_LOWER_BOUND_RE: Final[re.Pattern[str]] = re.compile(r"^>=\s*(?P<version>[A-Za-z0-9._+!-]+)$")
"""The one specifier shape this module decides. Everything else is refused."""


class LockError(Exception):
    """The lock or its declaration could not be read, or a value could not be decided."""


def normalise(name: str) -> str:
    """Normalise a distribution name.

    Args:
        name: The name as written.

    Returns:
        The PEP 503 normalised form: separator runs collapsed to one hyphen, and
        lowercased.
    """
    return _NORMALISE_RE.sub("-", name).lower()


@dataclass(frozen=True, slots=True, order=True)
class LockedFile:
    """One artefact recorded for a package.

    Args:
        name: The filename as published.
        url: Where it is served from, or ``None`` when the lock gave a path.
        path: A filesystem path, or ``None``. Recorded so it can be refused by
            name rather than silently read as an absent URL.
        hashes: Digest algorithm to value, as recorded.
    """

    name: str
    url: str | None
    path: str | None
    hashes: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True, order=True)
class LockedPackage:
    """One package the lock records.

    Args:
        name: The distribution name, as written.
        version: The exact version, or ``None`` when the lock recorded none.
        wheels: Every recorded wheel, in recorded order.
        sdist: The recorded source distribution, if any.
        direct_kind: Which of :data:`DIRECT_KINDS` the entry uses, if any.
    """

    name: str
    version: str | None
    wheels: tuple[LockedFile, ...]
    sdist: LockedFile | None
    direct_kind: str | None

    @property
    def normalised(self) -> str:
        """This package's PEP 503 name.

        Returns:
            The normalised distribution name.
        """
        return normalise(self.name)

    @property
    def artefacts(self) -> tuple[LockedFile, ...]:
        """Every artefact recorded for this package.

        Returns:
            The wheels, followed by the source distribution when there is one.
        """
        return (*self.wheels, *((self.sdist,) if self.sdist is not None else ()))


@dataclass(frozen=True, slots=True)
class Lock:
    """A whole lock file, as recorded.

    Args:
        path: The repository-relative path it was read from.
        lock_version: The format version it announces.
        created_by: The tool that wrote it.
        packages: Every recorded package, in recorded order.
    """

    path: str
    lock_version: str
    created_by: str
    packages: tuple[LockedPackage, ...]


@dataclass(frozen=True, slots=True)
class Producer:
    """What wrote the lock, as declared.

    Args:
        tool: The producing tool's name, compared against the lock's ``created-by``.
        version: That tool's version. Recorded because the lock cannot say it.
        experimental: Whether the producing feature is labelled experimental
            upstream. Carried into the manifest so the hedge is visible in the
            evidence rather than only in a document.
    """

    tool: str
    version: str
    experimental: bool


@dataclass(frozen=True, slots=True)
class LockTarget:
    """The environment the lock was resolved for.

    Args:
        implementation: The interpreter implementation.
        minor_line: Its minor line.
        architecture: The machine architecture.
        platform_tag: The PEP 425 spelling of that architecture.
        free_threaded: Whether the target is a free-threaded build.
        index: The package index the resolution used.
        artefact_host: The host every artefact URL must be served from.
        locked: The date the lock was produced, as an ISO string.
    """

    implementation: str
    minor_line: str
    architecture: str
    platform_tag: str
    free_threaded: bool
    index: str
    artefact_host: str
    locked: str

    def as_wheel_target(self) -> Target:
        """This target as the wheel survey spells one.

        Returns:
            A :class:`tools.quality.wheels.plan.Target`, so Phase 018's tag
            matcher can be asked the compatibility question directly rather than
            having it reimplemented here.
        """
        return Target(
            implementation=self.implementation,
            minor_line=self.minor_line,
            architecture=self.architecture,
            platform_tag=self.platform_tag,
            free_threaded=self.free_threaded,
            index=self.index,
            surveyed=self.locked,
        )


@dataclass(frozen=True, slots=True)
class Policy:
    """What the lock's contents must satisfy.

    Args:
        require_hashes: Whether every artefact must carry a digest.
        hash_algorithms: The digest algorithms permitted, each of which must be
            one :data:`HASH_WIDTHS` knows the width of.
        allow_source: Whether a package may be served as a source distribution
            only.
    """

    require_hashes: bool
    hash_algorithms: tuple[str, ...]
    allow_source: bool


@dataclass(frozen=True, slots=True, order=True)
class Gap:
    """A package that cannot be installed as a wheel, and the phase answering for it.

    Args:
        name: The distribution name.
        phase: The phase that must resolve it.
        reason: Why the gap exists.
    """

    name: str
    phase: int
    reason: str


@dataclass(frozen=True, slots=True)
class Declaration:
    """The whole lock declaration, as written.

    Args:
        producer: What wrote the lock.
        target: What it was resolved for.
        policy: What its contents must satisfy.
        dev_path: The repository-relative path of the development lock.
        dev_extra: Which ``pyproject.toml`` extra the development lock covers.
        roots: The requirement strings the lock was resolved from.
        runtime_locked: Whether a runtime lock is declared to exist.
        runtime_path: Where it would live.
        seeded: Distributions the environment creates itself, exempt from the
            unexpected-package check by name rather than by a silent allowance.
        gaps: Every recorded source-only gap, each owned by a phase.
    """

    producer: Producer
    target: LockTarget
    policy: Policy
    dev_path: str
    dev_extra: str
    roots: tuple[str, ...]
    runtime_locked: bool
    runtime_path: str
    seeded: tuple[str, ...]
    gaps: tuple[Gap, ...]


# ---------------------------------------------------------------------------
# Reading the lock
# ---------------------------------------------------------------------------


def parse_lock(text: str, *, path: str) -> Lock:
    """Read a PEP 751 lock from TOML text.

    Args:
        text: The lock's contents.
        path: The repository-relative path, for messages and for the record.

    Returns:
        The lock.

    Raises:
        LockError: If the text is not TOML, or its top level is not the shape PEP
            751 describes.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as fault:
        msg = f"{path} is not valid TOML: {fault}"
        raise LockError(msg) from fault

    version = document.get("lock-version")
    if not isinstance(version, str) or not version.strip():
        msg = f"{path}: lock-version must be a non-empty string"
        raise LockError(msg)
    created = document.get("created-by")
    if not isinstance(created, str) or not created.strip():
        msg = f"{path}: created-by must be a non-empty string"
        raise LockError(msg)

    entries = document.get("packages")
    if not isinstance(entries, list):
        msg = f"{path}: packages must be an array of tables"
        raise LockError(msg)
    packages = tuple(_package(entry, index, path) for index, entry in enumerate(entries))
    return Lock(path=path, lock_version=version, created_by=created, packages=packages)


def _package(entry: object, index: int, path: str) -> LockedPackage:
    """Read one ``[[packages]]`` entry.

    Args:
        entry: The parsed table.
        index: Its position, for a message when it has no usable name.
        path: The lock's path, for messages.

    Returns:
        The package.

    Raises:
        LockError: If the entry is not a table, or a field has the wrong type.
    """
    if not isinstance(entry, Mapping):
        msg = f"{path}: packages[{index}] is {type(entry).__name__}, expected a table"
        raise LockError(msg)
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        msg = f"{path}: packages[{index}] has no usable name"
        raise LockError(msg)

    version = entry.get("version")
    if version is not None and not isinstance(version, str):
        msg = f"{path}: {name} declares a version that is not a string"
        raise LockError(msg)

    wheels = entry.get("wheels", [])
    if not isinstance(wheels, list):
        msg = f"{path}: {name} declares wheels that are not an array of tables"
        raise LockError(msg)

    sdist = entry.get("sdist")
    if sdist is not None and not isinstance(sdist, Mapping):
        msg = f"{path}: {name} declares an sdist that is not a table"
        raise LockError(msg)

    direct = next((kind for kind in DIRECT_KINDS if kind in entry), None)
    return LockedPackage(
        name=name,
        version=version or None,
        wheels=tuple(_file(wheel, name, path) for wheel in wheels),
        sdist=_file(sdist, name, path) if sdist is not None else None,
        direct_kind=direct,
    )


def _file(entry: object, package: str, path: str) -> LockedFile:
    """Read one artefact table.

    Args:
        entry: The parsed table.
        package: Which package it belongs to, for messages.
        path: The lock's path, for messages.

    Returns:
        The artefact.

    Raises:
        LockError: If the entry is not a table, or a field has the wrong type.
    """
    if not isinstance(entry, Mapping):
        msg = f"{path}: {package} records an artefact that is not a table"
        raise LockError(msg)
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        msg = f"{path}: {package} records an artefact with no name"
        raise LockError(msg)
    url = entry.get("url")
    if url is not None and not isinstance(url, str):
        msg = f"{path}: {package} records a url for {name} that is not a string"
        raise LockError(msg)
    location = entry.get("path")
    if location is not None and not isinstance(location, str):
        msg = f"{path}: {package} records a path for {name} that is not a string"
        raise LockError(msg)
    hashes = entry.get("hashes", {})
    if not isinstance(hashes, Mapping):
        msg = f"{path}: {package} records hashes for {name} that are not a table"
        raise LockError(msg)
    for algorithm, value in hashes.items():
        if not isinstance(value, str):
            msg = f"{path}: {package} records a {algorithm} hash for {name} that is not a string"
            raise LockError(msg)
    return LockedFile(
        name=name,
        url=url or None,
        path=location or None,
        hashes=tuple(sorted((str(key), str(value)) for key, value in hashes.items())),
    )


# ---------------------------------------------------------------------------
# Judging the lock
# ---------------------------------------------------------------------------


def version_problems(lock: Lock) -> tuple[str, ...]:
    """Whether the lock announces a format this reader implements.

    Args:
        lock: The parsed lock.

    Returns:
        One sentence per problem, empty when the version is supported.
    """
    found = _LOCK_VERSION_RE.match(lock.lock_version)
    if found is None:
        return (
            f"{lock.path}: lock-version {lock.lock_version!r} is not major.minor, so this "
            f"reader cannot tell whether it implements the format",
        )
    major, minor = int(found["major"]), int(found["minor"])
    if major != SUPPORTED_LOCK_MAJOR:
        return (
            f"{lock.path}: lock-version {lock.lock_version} has major {major}, and this "
            f"reader implements {SUPPORTED_LOCK_MAJOR}",
        )
    if minor > SUPPORTED_LOCK_MINOR:
        return (
            f"{lock.path}: lock-version {lock.lock_version} is ahead of the "
            f"{SUPPORTED_LOCK_MAJOR}.{SUPPORTED_LOCK_MINOR} this reader implements, so it may "
            f"carry fields this gate would not check",
        )
    return ()


def producer_problems(lock: Lock, declaration: Declaration) -> tuple[str, ...]:
    """Whether the lock was written by the declared tool.

    Args:
        lock: The parsed lock.
        declaration: The declaration beside it.

    Returns:
        One sentence per problem, empty when they agree.

    Two checks, and the second exists because of what the first cannot do. A lock
    records the producer's *name* and never its version, so the declared version is
    not recomputable from ``created-by``. But the producer here is ``pip``, and pip
    is a real transitive dependency of the declared toolchain — so it appears in
    the lock as an ordinary package, with a version. Requiring those two to agree
    closes the seam from the other side: **the pip the lock installs is the pip the
    lock was made with**, which is checkable, where "the pip that ran" is not.

    A producer that does not appear in the lock is not a problem. The pairing is a
    coherence requirement where the evidence exists, not a demand that it exist.
    """
    problems: list[str] = []
    if lock.created_by != declaration.producer.tool:
        problems.append(
            f"{lock.path}: created-by is {lock.created_by!r}, and {CONFIGURATION_FILE} "
            f"declares the producer is {declaration.producer.tool!r}"
        )
    tool = normalise(declaration.producer.tool)
    for package in lock.packages:
        if package.normalised != tool or package.version is None:
            continue
        if package.version != declaration.producer.version:
            problems.append(
                f"{lock.path} locks {package.name} {package.version} while "
                f"{CONFIGURATION_FILE} declares the lock was produced by "
                f"{declaration.producer.tool} {declaration.producer.version}; the lock would "
                f"install a producer other than the one that wrote it"
            )
    return tuple(problems)


def target_problems(
    target: LockTarget,
    *,
    implementation: str,
    minor_line: str,
    architecture: str,
    free_threaded: bool,
) -> tuple[str, ...]:
    """Compare the declared target against the runtime contract.

    Args:
        target: The target the declaration states.
        implementation: What the runtime contract declares.
        minor_line: Likewise.
        architecture: Likewise.
        free_threaded: Likewise.

    Returns:
        One sentence per disagreement, empty when the two agree.

    Delegated to Phase 018's comparison rather than reimplemented. The seam exists
    as its own function so the delegation is one named thing a test can pin.

    It adds one check the delegate does not make. ``wheels.plan.target_problems``
    compares the minor line as a *string*, so a declaration and a contract that
    both spell it unusably still agree with each other and pass. Parsing it here
    is what turns that into a finding, rather than leaving it to surface much later
    as an unreadable failure inside the compatibility check.
    """
    problems = list(
        _wheels_target_problems(
            target.as_wheel_target(),
            implementation=implementation,
            minor_line=minor_line,
            architecture=architecture,
            free_threaded=free_threaded,
        )
    )
    try:
        _ = target.as_wheel_target().release
    except WheelSurveyError as fault:
        problems.append(f"{CONFIGURATION_FILE}: the declared target cannot be compared: {fault}")
    return tuple(problems)


def package_problems(package: LockedPackage, lock_path: str) -> tuple[str, ...]:
    """Whether one package entry is usable and reproducible.

    Args:
        package: The entry.
        lock_path: The lock's path, for messages.

    Returns:
        One sentence per problem, empty when the entry is sound.
    """
    problems: list[str] = []
    if package.name != package.normalised:
        problems.append(
            f"{lock_path}: {package.name!r} is not normalised; PEP 503 spells it "
            f"{package.normalised!r}, and two spellings of one distribution are two entries"
        )
    if package.direct_kind is not None:
        problems.append(
            f"{lock_path}: {package.name} is recorded as a {package.direct_kind} source, which "
            f"is not reproducible from the declared index and which pip-audit cannot resolve"
        )
    if package.version is None:
        problems.append(
            f"{lock_path}: {package.name} records no version, so nothing can say what would "
            f"be installed and pip-audit reports it as skipped"
        )
    if not package.artefacts and package.direct_kind is None:
        problems.append(f"{lock_path}: {package.name} records no artefact at all")
    return tuple(problems)


def duplicate_packages(packages: Sequence[LockedPackage]) -> tuple[str, ...]:
    """Report any distribution locked more than once.

    Args:
        packages: Every locked package.

    Returns:
        The repeated normalised names, sorted.

    Two entries for one distribution would let the lock hold two versions of it,
    and nothing would say which one an installer should take.
    """
    seen: dict[str, int] = {}
    for package in packages:
        seen[package.normalised] = seen.get(package.normalised, 0) + 1
    return tuple(sorted(name for name, count in seen.items() if count > 1))


def hash_problems(package: LockedPackage, policy: Policy, lock_path: str) -> tuple[str, ...]:
    """Whether every artefact carries a usable digest.

    Args:
        package: The entry.
        policy: What the declaration requires.
        lock_path: The lock's path, for messages.

    Returns:
        One sentence per problem, empty when every artefact is hashed.

    This is the check the property tests exercise hardest, because its failure is
    silent: an unhashed artefact installs from whatever the URL happens to serve,
    and the lock still looks like a lock.
    """
    problems: list[str] = []
    permitted = set(policy.hash_algorithms)
    for artefact in package.artefacts:
        if not artefact.hashes:
            if policy.require_hashes:
                problems.append(
                    f"{lock_path}: {package.name} records {artefact.name} with no hash, so "
                    f"nothing verifies what is downloaded"
                )
            continue
        usable = 0
        for algorithm, value in artefact.hashes:
            if algorithm in WEAK_ALGORITHMS:
                problems.append(
                    f"{lock_path}: {package.name} records {artefact.name} under {algorithm}, "
                    f"which is refused by name whatever the policy permits"
                )
                continue
            if algorithm not in permitted:
                continue
            width = HASH_WIDTHS[algorithm]
            if len(value) != width or _HEX_RE.match(value) is None:
                problems.append(
                    f"{lock_path}: {package.name} records a {algorithm} hash for "
                    f"{artefact.name} that is not {width} lowercase hexadecimal characters"
                )
                continue
            usable += 1
        if policy.require_hashes and not usable:
            algorithms = ", ".join(sorted(permitted))
            problems.append(
                f"{lock_path}: {package.name} records {artefact.name} with no hash in a "
                f"permitted algorithm ({algorithms})"
            )
    return tuple(problems)


def artefact_problems(
    package: LockedPackage, target: LockTarget, lock_path: str
) -> tuple[str, ...]:
    """Whether every artefact is served from somewhere the declaration permits.

    Args:
        package: The entry.
        target: The declared target, which names the artefact host.
        lock_path: The lock's path, for messages.

    Returns:
        One sentence per problem, empty when every artefact is well located.

    A ``path`` is refused rather than tolerated. A lock resolvable only relative to
    somebody's checkout is not a lock, and PEP 751 permits the field precisely
    because some producers write one.
    """
    problems: list[str] = []
    for artefact in package.artefacts:
        if artefact.path is not None:
            problems.append(
                f"{lock_path}: {package.name} records {artefact.name} as a filesystem path, "
                f"which resolves only relative to one checkout"
            )
            continue
        if artefact.url is None:
            problems.append(f"{lock_path}: {package.name} records {artefact.name} with no url")
            continue
        parts = urlsplit(artefact.url)
        if parts.scheme != HTTPS:
            problems.append(
                f"{lock_path}: {package.name} serves {artefact.name} over "
                f"{parts.scheme or 'no scheme'!r}, and only {HTTPS} is permitted"
            )
            continue
        if "@" in parts.netloc:
            problems.append(
                f"{lock_path}: {package.name} serves {artefact.name} from a url carrying "
                f"credentials before the host"
            )
            continue
        if parts.hostname != target.artefact_host:
            problems.append(
                f"{lock_path}: {package.name} serves {artefact.name} from "
                f"{parts.hostname!r}, and {CONFIGURATION_FILE} declares {target.artefact_host!r}"
            )
    return tuple(problems)


def compatibility_problems(
    package: LockedPackage, target: LockTarget, lock_path: str
) -> tuple[str, ...]:
    """Whether a recorded wheel serves the pinned interpreter.

    Args:
        package: The entry.
        target: The declared target.
        lock_path: The lock's path, for messages.

    Returns:
        One sentence per problem, empty when the package is installable as a
        wheel and every filename agrees with the entry carrying it.

    A package with no wheel at all is not reported here — that is
    :func:`source_problems`, which asks a different question and answers it with
    the gap bargain rather than with a failure.
    """
    if not package.wheels:
        return ()
    problems: list[str] = []
    wheel_target = target.as_wheel_target()
    names = [artefact.name for artefact in package.wheels]
    try:
        serving = serving_wheels(names, wheel_target)
    except WheelSurveyError as fault:
        return (f"{lock_path}: {package.name}: {fault}",)

    if not serving:
        problems.append(
            f"{lock_path}: {package.name} records {len(names)} wheels and none serves "
            f"{target.implementation} {target.minor_line} on {target.platform_tag}"
        )
    for filename in names:
        wheel = parse_wheel_filename(filename)
        if normalise(wheel.distribution) != package.normalised:
            problems.append(
                f"{lock_path}: {package.name} records {filename}, whose own name is "
                f"{wheel.distribution!r}"
            )
        if package.version is not None and wheel.version != package.version:
            problems.append(
                f"{lock_path}: {package.name} records version {package.version!r} but "
                f"{filename} carries {wheel.version!r}"
            )
    return tuple(problems)


def source_problems(
    packages: Sequence[LockedPackage],
    target: LockTarget,
    policy: Policy,
    gaps: Sequence[Gap],
    *,
    delivered: int,
    total: int,
) -> tuple[str, ...]:
    """Whether every package that must be built from source is owned by a phase.

    Args:
        packages: Every locked package.
        target: The declared target.
        policy: What the declaration permits.
        gaps: The recorded gaps.
        delivered: The last completed phase.
        total: How many phases the programme has.

    Returns:
        One sentence per problem, empty when every gap is owned.

    The bargain is ``wheel-survey.toml``'s, and it is deliberate: a package whose
    upstream publishes no wheel is not something a gate can fix by going red. What
    is a failure is an **unowned** gap — recorded, then nobody's, then forgotten.
    A gap recorded against a package that turns out to have a wheel fails too, in
    the other direction, so the register cannot accumulate entries nobody needs.
    """
    problems: list[str] = []
    owned = {normalise(gap.name): gap for gap in gaps}
    wheel_target = target.as_wheel_target()
    unserved: set[str] = set()

    for package in packages:
        names = [artefact.name for artefact in package.wheels]
        try:
            serving = serving_wheels(names, wheel_target) if names else ()
        except WheelSurveyError:
            continue
        if serving:
            continue
        unserved.add(package.normalised)
        if policy.allow_source and package.sdist is not None:
            continue
        gap = owned.get(package.normalised)
        if gap is None:
            problems.append(
                f"{package.name} has no wheel for the pinned interpreter and no [[gap]] "
                f"in {CONFIGURATION_FILE} names a phase answering for it"
            )
        elif gap.phase <= delivered:
            problems.append(
                f"{package.name}: the gap is recorded against phase {gap.phase:03d}, which "
                f"has already shipped"
            )
        elif gap.phase > total:
            problems.append(
                f"{package.name}: the gap names phase {gap.phase:03d}, beyond the "
                f"{total}-phase programme"
            )

    for name, gap in sorted(owned.items()):
        if name not in unserved:
            problems.append(
                f"{gap.name}: a gap is recorded, but the lock has a wheel for it, so the "
                f"entry names a phase with nothing to do"
            )
    return tuple(problems)


def satisfies_bound(version: str, specifier: str) -> bool | None:
    """Whether an exact version clears a lower bound.

    Args:
        version: The locked version.
        specifier: The declared bound, such as ``>=8.0``.

    Returns:
        The comparison, or ``None`` when the specifier is one this module does not
        decide.

    Three-valued on purpose. ``inventory._satisfies`` collapses "cannot decide"
    into ``True`` because a false disagreement there would be a gate crying wolf;
    here the caller must be able to tell the two apart, because a lock whose bound
    nobody can evaluate is a lock nobody has checked.
    """
    found = _LOWER_BOUND_RE.match(specifier.strip())
    if found is None:
        return None
    return release(version) >= release(found["version"])


def _requirement_parts(text: str) -> tuple[str, str]:
    """Split a requirement into a normalised name and its specifier.

    Args:
        text: A requirement such as ``pytest>=8.0``.

    Returns:
        The normalised name and the specifier, which may be empty.

    Raises:
        LockError: If the string does not begin with a distribution name.
    """
    found = _REQUIREMENT_RE.match(text.strip())
    if found is None:
        msg = f"{CONFIGURATION_FILE} declares a root this reader cannot name: {text!r}"
        raise LockError(msg)
    return normalise(found["name"]), found["specifier"].strip()


def declaration_problems(
    declaration: Declaration, declared: Sequence[Dependency]
) -> tuple[str, ...]:
    """Compare the declared roots against ``pyproject.toml``, in both directions.

    Args:
        declaration: The lock declaration.
        declared: The whole collected inventory.

    Returns:
        One sentence per disagreement, empty when the two agree.

    Both directions, because each catches a different mistake and neither catches
    the other's. A root in ``pyproject.toml`` and not here is a tool the lock was
    never resolved from, so it is unlocked while appearing declared. A root here
    and not in ``pyproject.toml`` is a tool somebody removed from the project and
    left in the lock, which the absence of dependency edges (ledger S-03) makes
    otherwise undetectable.
    """
    try:
        roots = dict(map(_requirement_parts, declaration.roots))
    except LockError as fault:
        return (str(fault),)

    extra = {
        normalise(entry.name): entry.version
        for entry in declared
        if entry.ecosystem == PYPI and entry.source == PYPROJECT and entry.scope == DEVELOPMENT
    }

    problems: list[str] = []
    for name in sorted(set(extra) - set(roots)):
        problems.append(
            f"{PYPROJECT} declares {name} in the {declaration.dev_extra!r} extra, and "
            f"{CONFIGURATION_FILE} does not list it as a root, so the lock was never "
            f"resolved from it"
        )
    for name in sorted(set(roots) - set(extra)):
        problems.append(
            f"{CONFIGURATION_FILE} lists {name} as a root, and {PYPROJECT} no longer "
            f"declares it in the {declaration.dev_extra!r} extra"
        )
    for name in sorted(set(roots) & set(extra)):
        if roots[name] != extra[name]:
            problems.append(
                f"{name}: {CONFIGURATION_FILE} resolved from {roots[name]!r} and {PYPROJECT} "
                f"now declares {extra[name]!r}"
            )
    return tuple(problems)


def coverage_problems(lock: Lock, declared: Sequence[Dependency]) -> tuple[str, ...]:
    """Whether every declared development tool is locked, at a version clearing its bound.

    Args:
        lock: The parsed lock.
        declared: The whole collected inventory.

    Returns:
        One sentence per problem, empty when the lock covers the toolchain.
    """
    locked = {package.normalised: package for package in lock.packages}
    problems: list[str] = []
    for entry in declared:
        if entry.ecosystem != PYPI or entry.source != PYPROJECT or entry.scope != DEVELOPMENT:
            continue
        package = locked.get(normalise(entry.name))
        if package is None:
            problems.append(f"{entry.name} is declared in {PYPROJECT} and {lock.path} omits it")
            continue
        if package.version is None:
            continue
        verdict = satisfies_bound(package.version, entry.version)
        if verdict is None:
            problems.append(
                f"{entry.name}: {PYPROJECT} declares {entry.version!r}, which this module "
                f"does not decide against a locked version. Only a >= bound is decidable"
            )
        elif not verdict:
            problems.append(
                f"{entry.name}: {lock.path} locks {package.version} and {PYPROJECT} "
                f"declares {entry.version!r}"
            )
    return tuple(problems)


def register_problems(lock: Lock, declared: Sequence[Dependency]) -> tuple[str, ...]:
    """Whether the pins and hook revisions agree with the lock.

    Args:
        lock: The parsed lock.
        declared: The whole collected inventory.

    Returns:
        One sentence per disagreement, each naming the exact replacement, empty
        when every register agrees.

    The lock is resolved and the other three registers are declared, so this is
    the join between them rather than a fourth entry in ``inventory.drift()`` —
    that module states about itself that it runs no resolver, and putting a
    resolution into it would make the claim false.
    """
    locked = {package.normalised: package for package in lock.packages}
    problems: list[str] = []

    for entry in declared:
        if entry.ecosystem != PYPI or entry.scope != CONTINUOUS_INTEGRATION:
            continue
        package = locked.get(normalise(entry.name))
        if package is None:
            problems.append(
                f"{entry.source} installs {entry.name}=={entry.version}, which {lock.path} "
                f"does not lock"
            )
            continue
        if package.version is not None and package.version != entry.version:
            problems.append(
                f"{entry.source} pins {entry.name}=={entry.version} and {lock.path} locks "
                f"{package.version}; write {entry.name}=={package.version}"
            )

    for entry in declared:
        if entry.ecosystem != PRE_COMMIT:
            continue
        repository = entry.name.rpartition("/")[2]
        tool = repository.removesuffix(HOOK_MIRROR_SUFFIX)
        if tool == repository:
            continue
        package = locked.get(normalise(tool))
        if package is None or package.version is None:
            continue
        if entry.version.removeprefix("v") != package.version:
            problems.append(
                f"{entry.source} pins {entry.name} at {entry.version} and {lock.path} locks "
                f"{tool} {package.version}; the hook and the gate would disagree about "
                f"whether a file is clean"
            )
    return tuple(problems)


def runtime_problems(declaration: Declaration, declared: Sequence[Dependency]) -> tuple[str, ...]:
    """Whether runtime dependencies and a runtime lock have appeared together.

    Args:
        declaration: The lock declaration.
        declared: The whole collected inventory.

    Returns:
        One sentence per problem, empty when the two agree.

    This is the forward hook ADR-0054 Decision 2 describes. Today
    ``project.dependencies`` is empty and no runtime lock exists, so it passes
    silently. The moment Phase 021 declares the first runtime dependency it fails,
    and the only way to satisfy it is to produce the lock — which is the obligation
    being enforced rather than remembered.
    """
    runtime = sorted(
        {entry.name for entry in declared if entry.ecosystem == PYPI and entry.scope == "runtime"}
    )
    if not runtime:
        return ()
    if declaration.runtime_locked:
        return ()
    names = ", ".join(runtime)
    return (
        f"{PYPROJECT} declares runtime dependencies ({names}) while {CONFIGURATION_FILE} "
        f"records [runtime] locked = false. A runtime dependency and {declaration.runtime_path} "
        f"arrive together, or what ships is unlocked",
    )


def environment_problems(
    lock: Lock, installed: Mapping[str, str], seeded: Sequence[str]
) -> tuple[str, ...]:
    """Compare an environment against the lock.

    Args:
        lock: The parsed lock.
        installed: Distribution name to version, as observed.
        seeded: Distributions the environment creates itself.

    Returns:
        One sentence per difference, empty when the environment matches.

    Pure: the caller observes the environment and passes the result in, so every
    branch here is reachable from literals without building a virtual environment
    to produce one.
    """
    expected = {
        package.normalised: package.version
        for package in lock.packages
        if package.version is not None
    }
    present = {normalise(name): version for name, version in installed.items()}
    exempt = {normalise(name) for name in seeded}

    problems: list[str] = []
    for name in sorted(set(expected) - set(present)):
        problems.append(f"{name} {expected[name]} is locked and is not installed")
    for name in sorted(set(present) - set(expected) - exempt):
        problems.append(f"{name} {present[name]} is installed and {lock.path} does not lock it")
    for name in sorted(set(expected) & set(present)):
        if expected[name] != present[name]:
            problems.append(
                f"{name}: {lock.path} locks {expected[name]} and {present[name]} is installed"
            )
    return tuple(problems)


# ---------------------------------------------------------------------------
# Reading the declaration
# ---------------------------------------------------------------------------


def read_declaration(document: Mapping[str, object]) -> Declaration:
    """Build the declaration from a parsed TOML document.

    Args:
        document: The parsed declaration.

    Returns:
        The declaration.

    Raises:
        LockError: If the schema is unknown or any value is malformed.
    """
    schema = document.get("schema")
    if schema != SCHEMA:
        msg = (
            f"this tool reads {CONFIGURATION_FILE} schema {SCHEMA}, and the file declares "
            f"{schema!r}. Update the tool rather than reading it anyway"
        )
        raise LockError(msg)

    producer_table = _table(document, "producer")
    producer = Producer(
        tool=_text(producer_table, "tool", "producer"),
        version=_text(producer_table, "version", "producer"),
        experimental=_flag(producer_table, "experimental", "producer"),
    )

    target_table = _table(document, "target")
    target = LockTarget(
        implementation=_text(target_table, "implementation", "target"),
        minor_line=_text(target_table, "minor_line", "target"),
        architecture=_text(target_table, "architecture", "target"),
        platform_tag=_text(target_table, "platform_tag", "target"),
        free_threaded=_flag(target_table, "free_threaded", "target"),
        index=_text(target_table, "index", "target"),
        artefact_host=_text(target_table, "artefact_host", "target"),
        locked=_date(target_table, "locked", "target"),
    )

    policy_table = _table(document, "policy")
    algorithms = _strings(policy_table, "hash_algorithms", "policy")
    for algorithm in algorithms:
        if algorithm not in HASH_WIDTHS:
            known = ", ".join(sorted(HASH_WIDTHS))
            msg = (
                f"{CONFIGURATION_FILE}: policy.hash_algorithms names {algorithm!r}, whose "
                f"digest width this module does not know. Known: {known}"
            )
            raise LockError(msg)
    policy = Policy(
        require_hashes=_flag(policy_table, "require_hashes", "policy"),
        hash_algorithms=algorithms,
        allow_source=_flag(policy_table, "allow_source", "policy"),
    )

    dev_table = _table(document, "dev")
    runtime_table = _table(document, "runtime")
    environment_table = _table(document, "environment")

    return Declaration(
        producer=producer,
        target=target,
        policy=policy,
        dev_path=_text(dev_table, "path", "dev"),
        dev_extra=_text(dev_table, "extra", "dev"),
        roots=_strings(dev_table, "roots", "dev"),
        runtime_locked=_flag(runtime_table, "locked", "runtime"),
        runtime_path=_text(runtime_table, "path", "runtime"),
        seeded=_strings(environment_table, "seeded", "environment"),
        gaps=tuple(
            Gap(
                name=_text(entry, "name", "gap"),
                phase=_integer(entry, "phase", "gap"),
                reason=_text(entry, "reason", "gap"),
            )
            for entry in _entries(document, "gap")
        ),
    )


def parse_declaration(text: str) -> Declaration:
    """Read the declaration from TOML text.

    Args:
        text: The contents of ``lock-policy.toml``.

    Returns:
        The declaration.

    Raises:
        LockError: If the text is not TOML, or the declaration is malformed.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as fault:
        msg = f"{CONFIGURATION_FILE} is not valid TOML: {fault}"
        raise LockError(msg) from fault
    return read_declaration(document)


def _table(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    """Read a required sub-table.

    Args:
        document: The parsed declaration.
        name: The table's name.

    Returns:
        The table.

    Raises:
        LockError: If it is absent or is not a table.
    """
    value = document.get(name)
    if not isinstance(value, Mapping):
        msg = f"{CONFIGURATION_FILE} has no [{name}] table"
        raise LockError(msg)
    return value


def _entries(document: Mapping[str, object], name: str) -> tuple[Mapping[str, object], ...]:
    """Read an array of tables.

    Args:
        document: The parsed declaration.
        name: The array's name.

    Returns:
        Its entries, empty when the array is absent.

    Raises:
        LockError: If the value is not a list of tables.
    """
    value = document.get(name, [])
    if not isinstance(value, list):
        msg = f"{CONFIGURATION_FILE}: [[{name}]] must be an array of tables"
        raise LockError(msg)
    for entry in value:
        if not isinstance(entry, Mapping):
            found = type(entry).__name__
            msg = f"{CONFIGURATION_FILE}: [[{name}]] holds {found}, expected a table"
            raise LockError(msg)
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
        LockError: If it is absent, is not a string, or is empty.
    """
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be a non-empty string"
        raise LockError(msg)
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
        LockError: If it is absent, is not a list, is empty, or holds anything
            that is not a string.
    """
    value = table.get(key)
    if not isinstance(value, list) or not value:
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be a non-empty list of strings"
        raise LockError(msg)
    for item in value:
        if not isinstance(item, str):
            found = type(item).__name__
            msg = f"{CONFIGURATION_FILE}: {where}.{key} holds {found}, expected a string"
            raise LockError(msg)
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
        LockError: If it is absent, is a :class:`bool`, is not an :class:`int`, or
            is not positive.
    """
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be a positive integer"
        raise LockError(msg)
    return value


def _flag(table: Mapping[str, object], key: str, where: str) -> bool:
    """Read a boolean.

    Args:
        table: The table holding it.
        key: Which setting.
        where: The table's name, for the message.

    Returns:
        The value.

    Raises:
        LockError: If it is absent or is not a boolean.
    """
    value = table.get(key)
    if not isinstance(value, bool):
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be true or false"
        raise LockError(msg)
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
        LockError: If it is absent, or is written as a quoted string rather than a
            bare date.

    A quoted date is refused for the reason ``vulnerability-waivers.toml`` gives:
    TOML has a date type, and a value written as a string has not been validated as
    a date by anything.
    """
    value = table.get(key)
    if not isinstance(value, date):
        msg = (
            f"{CONFIGURATION_FILE}: {where}.{key} writes {value!r}. Write it as a bare TOML "
            f"date (2026-08-16), not as a string - a quoted date does not compare as one"
        )
        raise LockError(msg)
    return value.isoformat()
