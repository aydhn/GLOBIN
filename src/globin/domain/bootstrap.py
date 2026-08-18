"""What must be true before GLOBIN starts, and how a failure is named.

This module holds the judgement and none of the observation. Every function here
is handed facts about a host and returns a verdict about them, so each branch is
reachable from literals and no test needs a wrong interpreter to prove that a
wrong interpreter is refused. Reading the host is
:mod:`globin.adapters.bootstrap`'s job, and sequencing the reads is
:mod:`globin.application.bootstrap`'s.

**A declared path is a string, not a** :class:`~pathlib.Path`. The domain may
import no I/O-capable module (``docs/architecture/dependency-rules.toml`` lists
``pathlib`` among them), and the constraint turns out to be the better design:
:class:`RuntimePaths` declares the runtime tree *relative to the project root*,
and the adapter is the only thing that ever knows where that root is. An absolute
path therefore cannot reach the evidence by being forgotten, because it cannot
reach this layer at all.

**A path that must be published is a** :class:`RecordedPath`, whose three
outcomes are enforced by construction rather than by convention. The same
three-outcome rule exists in ``tools/quality/runtime/plan.py`` as a dictionary;
here it is a type, so a fourth outcome is unrepresentable and "outside the
repository, with its absolute spelling attached" cannot be built at all.

**Status has four members, not three.** ``PASS``, ``WARN`` and ``FAIL`` are the
three a reader expects; ``UNMEASURED`` is the one ADR-0045 requires, and it
outranks ``FAIL`` when a run is reduced to a single answer. Not knowing is worse
than knowing something is broken, because a broken thing has been found and an
unmeasured one has not.

What this module deliberately does not decide: which configuration files exist
and what profiles they describe (Phase 026), which sources are consulted and in
what order (Phase 027), how a secret is stored (Phase 028) or collected
(Phase 029), and the wider health-check suite a long-running process will need
(Phase 030). :func:`checks` is a registry rather than a fixed list precisely so
those phases add to it instead of rewriting it.
"""

import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Final

from globin.domain.configuration import GlobinConfig
from globin.domain.dependency import DependencyInventory, LockState
from globin.domain.diagnostics_http import ReadinessReason
from globin.domain.environment import (
    EnvironmentCapabilitySnapshot,
    EnvironmentCompatibility,
    compatibility_fingerprint,
)
from globin.errors import InternalError, ValidationError

FINGERPRINT_LENGTH: Final[int] = 16
"""How many hexadecimal characters of a digest identify a path.

Sixteen, matching ``tools/quality/supply/secrets.py``. Long enough that two
different paths on one machine will not collide in practice, short enough that
nobody mistakes it for something reversible.
"""

VERSION_PARTS: Final[int] = 3
"""How many dot-separated integers a Python version has.

Named rather than written inline so that :func:`parse_version` reads as a rule
about versions instead of a comparison against a number somebody has to recognise.
"""

MAX_ROOT_SEARCH_DEPTH: Final[int] = 12
"""How many directories above the starting point may be searched for the root.

Bounded rather than unlimited. An unbounded walk finds *a* ``pyproject.toml``
eventually on most machines, and the one it finds depends on where the command
was typed — which is the precise ambiguity this phase exists to remove. Twelve is
deep enough for any checkout a person would create and shallow enough that the
search cannot wander into a parent project.
"""


class CheckStatus(StrEnum):
    """What a single check concluded.

    ``WARN`` is a real answer rather than a soft failure: it means the check was
    performed, the result is not what a fully-configured host would show, and
    starting anyway is defensible. Nothing here treats it as a failure, and
    :func:`exit_code_for` ignores it.
    """

    PASS = "pass"  # noqa: S105 -- a check verdict, not a credential
    FAIL = "fail"
    WARN = "warn"
    UNMEASURED = "unmeasured"


class ExitCode(IntEnum):
    """The process's answer, one value per kind of refusal.

    ``0``, ``1``, ``2`` and ``3`` keep the meanings every gate under ``tools/``
    already gives them, so a reader who knows one command knows this one. The
    values from ``10`` upwards are this phase's addition: the same class of
    failure always produces the same code, which is what lets a launcher branch
    on the reason without parsing English.

    The two ranges cannot collide, which is why the second one starts at ten
    rather than at four.

    **Phase 024 adds one value and reuses three, and the reuse is the decision.**
    ``globin diagnostics snapshot`` answers ``0`` for a healthy runtime, ``1`` for
    an unhealthy one and ``3`` for a degraded one — the same three words every gate
    under ``tools/`` already speaks, so a script that branches on one command
    branches on this one. What that leaves unsaid is the case where no snapshot
    could be produced at all, which is not a health state but a failure to measure
    one, and :attr:`DIAGNOSTICS_FAILED` is the value for it. Collapsing the two
    would make *the process is unhealthy* and *nobody could tell* indistinguishable
    to the one consumer that most needs them apart.

    **Phase 028 adds one value, and it is deliberately not**
    :attr:`HOST_UNSUPPORTED`. That code means the host failed the contract
    ``runtime-contract.toml`` declares — the wrong operating system, the wrong
    release. :attr:`ENVIRONMENT_INCOMPATIBLE` means the host satisfies that
    contract and fails a *capability* the contract does not describe, which
    today means its native processor architecture is not the declared one. A
    launcher branching on the two should behave differently: the first is a
    machine GLOBIN was never meant to run on, the second is one that was
    provisioned wrongly.

    **Phase 025 adds one value that no command ever returns.**
    :attr:`WATCHDOG_STALLED` is the status a process leaves behind when the
    watchdog ends it, and the watchdog ends it by terminating rather than by
    returning — so nothing in ``globin.runtime.cli`` can produce this code, and a
    launcher seeing it knows the run did not choose its own ending. That is the
    whole point of giving it a number of its own rather than reusing
    :attr:`INTERNAL`: a supervisor restarting on ``17`` and on ``23`` should not
    behave the same way, because one is a defect and the other is the safety
    mechanism working.
    """

    OK = 0
    GATE_FAILED = 1
    USAGE = 2
    UNMEASURED = 3
    HOST_UNSUPPORTED = 10
    INTERPRETER_MISMATCH = 11
    ENVIRONMENT_MISMATCH = 12
    DEPENDENCY_UNREADY = 13
    CONFIGURATION_INVALID = 14
    SECRETS_UNREADY = 15
    PATHS_UNUSABLE = 16
    INTERNAL = 17
    PROJECT_UNIDENTIFIED = 18
    RUNTIME_STATE_CORRUPT = 19
    INSTANCE_ALREADY_ACTIVE = 20
    RUNTIME_PERSISTENCE_FAILED = 21
    DIAGNOSTICS_FAILED = 22
    WATCHDOG_STALLED = 23
    ENVIRONMENT_INCOMPATIBLE = 24
    CREDENTIAL_NOT_ENTITLED = 25


class PathLocation(StrEnum):
    """Where a path is, in the only three terms that may be published."""

    REPOSITORY = "repository"
    OUTSIDE = "outside"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class RecordedPath:
    """A path in a form that is safe to write down.

    Args:
        location: Which of the three cases this is.
        path: The project-relative, POSIX-separated spelling. Present only when
            ``location`` is :attr:`PathLocation.REPOSITORY`.
        fingerprint: A stable, non-reversible identifier. Present only when
            ``location`` is :attr:`PathLocation.OUTSIDE`.

    Raises:
        ValidationError: If the fields do not match the location.

    Prefer the three factories — :func:`recorded_inside`, :func:`recorded_outside`
    and :func:`recorded_absent` — over calling this directly. They are the reason
    the invariant is cheap to satisfy.

    A path outside the project carries an account name often enough that treating
    it as public is not a risk worth taking, so it never appears. A fingerprint
    still answers the question a reader has, which is whether this is the *same*
    interpreter as last time rather than which interpreter it is.
    """

    location: PathLocation
    path: str | None = None
    fingerprint: str | None = None

    def __post_init__(self) -> None:
        """Refuse any combination the three outcomes do not describe."""
        expected: dict[PathLocation, tuple[bool, bool]] = {
            PathLocation.REPOSITORY: (True, False),
            PathLocation.OUTSIDE: (False, True),
            PathLocation.ABSENT: (False, False),
        }
        wants_path, wants_fingerprint = expected[self.location]
        if (self.path is not None) is not wants_path:
            msg = f"a {self.location.value} path {'needs' if wants_path else 'carries'} no spelling"
            raise ValidationError(msg)
        if (self.fingerprint is not None) is not wants_fingerprint:
            msg = (
                f"a {self.location.value} path "
                f"{'needs' if wants_fingerprint else 'carries'} no fingerprint"
            )
            raise ValidationError(msg)

    def as_record(self) -> dict[str, str]:
        """This path as the mapping the evidence carries.

        Returns:
            ``{"location": ...}`` plus whichever of ``path`` or ``fingerprint``
            this location has, and never both.
        """
        record = {"location": self.location.value}
        if self.path is not None:
            record["path"] = self.path
        if self.fingerprint is not None:
            record["fingerprint"] = self.fingerprint
        return record


def fingerprint_of(text: str) -> str:
    """A stable, non-reversible identifier for a string.

    Args:
        text: The value to identify. Never stored and never returned.

    Returns:
        The first :data:`FINGERPRINT_LENGTH` hexadecimal characters of its
        SHA-256.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


def recorded_inside(relative: str) -> RecordedPath:
    """Record a path that lies inside the project.

    Args:
        relative: Its project-relative, POSIX-separated spelling.

    Returns:
        The recorded path.

    Raises:
        ValidationError: If ``relative`` is empty or absolute.
    """
    if not relative:
        msg = "a path inside the project needs a relative spelling, and this one is empty"
        raise ValidationError(msg)
    if relative.startswith("/") or ":" in relative.split("/", 1)[0]:
        msg = f"{relative!r} is absolute, and an absolute path is never recorded"
        raise ValidationError(msg)
    return RecordedPath(location=PathLocation.REPOSITORY, path=relative)


def recorded_outside(absolute: str) -> RecordedPath:
    """Record a path that lies outside the project, as a fingerprint.

    Args:
        absolute: The path. Consumed to compute the fingerprint and discarded.

    Returns:
        The recorded path, carrying no spelling.
    """
    return RecordedPath(location=PathLocation.OUTSIDE, fingerprint=fingerprint_of(absolute))


def recorded_absent() -> RecordedPath:
    """Record that there is no path at all.

    Returns:
        The recorded path.

    Absence is recorded as absence rather than as an empty string, which would
    read as "a path that is the empty string".
    """
    return RecordedPath(location=PathLocation.ABSENT)


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """The runtime tree, declared relative to the project root.

    Args:
        config: Where non-secret configuration files will live. Phase 026 decides
            what goes in it.
        artifacts: The root of everything GLOBIN generates about itself.
        evidence: Where this phase's bootstrap manifest is written.
        logs: Where a long-running process will write its log files.
        state: Where a process will keep state that outlives one run.
        cache: Where a process will keep data it can afford to lose.

    **A declared root is a reservation, not a claim that anything writes there.**
    Only the roots in :data:`CREATED_PATHS` are brought into existence, and today
    that is one of them. ``REPOSITORY_LAYOUT.md`` refuses an empty directory named
    after a future capability because it reads as a claim that the capability is
    being worked on; a field on this class makes no such claim, because the class
    is a map rather than a tree.

    Every value is relative, and that is what makes the whole thing
    working-directory independent. Joining happens once, in the adapter, against
    a root that was discovered rather than assumed.

    There is deliberately no temporary root. Temporary work belongs in the
    platform's own temporary directory through :mod:`tempfile`, which cleans up
    after itself and does not need a reserved name; a project-local one would be
    a directory somebody has to remember to empty.
    """

    config: str = "config"
    artifacts: str = ".globin"
    evidence: str = ".globin/bootstrap"
    logs: str = ".globin/logs"
    state: str = ".globin/state"
    cache: str = ".globin/cache"

    def declared(self) -> dict[str, str]:
        """Every declared root, by name.

        Returns:
            Field name to project-relative spelling.
        """
        return {
            "config": self.config,
            "artifacts": self.artifacts,
            "evidence": self.evidence,
            "logs": self.logs,
            "state": self.state,
            "cache": self.cache,
        }


CREATED_PATHS: Final[tuple[str, ...]] = ("artifacts", "evidence")
"""Which declared roots the bootstrap may bring into existence.

An allowlist rather than a rule, so that creating a directory is a visible edit
to a named set rather than a consequence of writing a file into it. Everything
else in :class:`RuntimePaths` is declared and left alone until the phase that
owns it has something to put there.

A tuple rather than a :class:`frozenset` because ``frozenset(...)`` is a call,
and a layer package performs none at import.
"""


@dataclass(frozen=True, slots=True)
class HostFacts:
    """What was observed about the machine.

    Args:
        system: The operating system's name, as :func:`platform.system` gives it.
        release: Its release, as :func:`platform.release` gives it.
        machine: The processor architecture.
        pointer_bits: The width of a pointer, in bits.
    """

    system: str
    release: str
    machine: str
    pointer_bits: int


@dataclass(frozen=True, slots=True)
class InterpreterFacts:
    """What was observed about the running Python.

    Args:
        implementation: ``"cpython"``, ``"pypy"`` and so on, lower-cased by
            :data:`sys.implementation`.
        version: The three-part version, as ``"3.14.5"``.
        release_level: ``"final"`` for a released interpreter, otherwise the kind
            of pre-release this is.
        free_threaded: Whether this build runs without the global interpreter
            lock.
        executable: Where the interpreter is, recorded rather than spelled out.
        prefix: :data:`sys.prefix`, recorded.
        base_prefix: :data:`sys.base_prefix`, recorded.
        in_virtual_environment: Whether the two prefixes differ.
    """

    implementation: str
    version: str
    release_level: str
    free_threaded: bool
    executable: RecordedPath
    prefix: RecordedPath
    base_prefix: RecordedPath
    in_virtual_environment: bool


@dataclass(frozen=True, slots=True)
class RuntimeBaseline:
    """The contract a host must satisfy, as the declaration states it.

    Args:
        system: The only supported operating system.
        minimum_release: The oldest supported release of it.
        implementation: The only supported Python implementation.
        minor_line: The supported series, exactly — not a floor.
        minimum_patch: The oldest patch of that series this tree was verified on.
        architecture: The supported processor architecture.
        pointer_bits: The supported pointer width.
        free_threaded: Whether a free-threaded build is accepted.
        allow_prerelease: Whether a pre-release interpreter is accepted.
        environment_directory: The one permitted virtual-environment directory.

    Read from ``docs/engineering/runtime-contract.toml`` by the adapter. This is
    not a second copy of that file: it is the parsed shape of it, and Phase 017
    remains the phase that decides the values.
    """

    system: str
    minimum_release: str
    implementation: str
    minor_line: str
    minimum_patch: str
    architecture: str
    pointer_bits: int
    free_threaded: bool
    allow_prerelease: bool
    environment_directory: str


@dataclass(frozen=True, slots=True)
class CheckSpec:
    """One check the bootstrap can perform.

    Args:
        identifier: Stable and machine-readable, in ``area.subject`` form. It
            appears in the evidence and in operator runbooks, so it is renamed
            only with a schema version.
        category: The area, which is the identifier's first segment.
        exit_code: What the process returns when this check fails. Declared once
            here so that no call site can invent a second answer for the same
            failure.
    """

    identifier: str
    category: str
    exit_code: ExitCode


AGGREGATE_CHECK: Final[str] = "bootstrap.ready"
"""The identifier of the check that answers for all the others."""


def checks() -> tuple[CheckSpec, ...]:
    """Return every registered check, in the order the pipeline performs them.

    Returns:
        One specification per check.

    This is the registry, and it is a function rather than a constant for the
    reason :func:`globin.domain.identifiers.specifications` gives about itself:
    building a :class:`CheckSpec` is a call, and a layer package may perform none
    at import.

    The order is the dependency order and is load-bearing twice over: a later
    check may assume an earlier one passed, and :func:`exit_code_for` reports the
    first failure, so the code a caller sees names the *earliest* thing that was
    wrong rather than an arbitrary one.

    ``project.root`` is first because everything after it is read from underneath
    the root — the runtime contract, ``pyproject.toml``, the lock and the runtime
    tree. A bootstrap that judged the interpreter before knowing which project it
    was judging it for would be answering a question nobody asked.

    ``bootstrap.ready`` is last and is the aggregate. Its own exit code is the
    generic one, which it produces only when nothing before it failed — that is,
    when the report itself could not be completed.
    """
    return (
        CheckSpec("project.root", "project", ExitCode.PATHS_UNUSABLE),
        CheckSpec("runtime.host", "runtime", ExitCode.HOST_UNSUPPORTED),
        CheckSpec("runtime.architecture", "runtime", ExitCode.HOST_UNSUPPORTED),
        CheckSpec("environment.capability", "environment", ExitCode.ENVIRONMENT_INCOMPATIBLE),
        CheckSpec("python.implementation", "python", ExitCode.INTERPRETER_MISMATCH),
        CheckSpec("python.version", "python", ExitCode.INTERPRETER_MISMATCH),
        CheckSpec("python.environment", "python", ExitCode.ENVIRONMENT_MISMATCH),
        CheckSpec("project.identity", "project", ExitCode.PROJECT_UNIDENTIFIED),
        CheckSpec("dependency.lock", "dependency", ExitCode.DEPENDENCY_UNREADY),
        CheckSpec("config.valid", "config", ExitCode.CONFIGURATION_INVALID),
        CheckSpec("paths.runtime", "paths", ExitCode.PATHS_UNUSABLE),
        CheckSpec("paths.boundary", "paths", ExitCode.PATHS_UNUSABLE),
        CheckSpec("state.persistence", "state", ExitCode.RUNTIME_PERSISTENCE_FAILED),
        CheckSpec("state.previous_run", "state", ExitCode.RUNTIME_STATE_CORRUPT),
        CheckSpec("instance.lock", "instance", ExitCode.INSTANCE_ALREADY_ACTIVE),
        CheckSpec("secrets.required", "secrets", ExitCode.SECRETS_UNREADY),
        CheckSpec("secrets.entitlement", "secrets", ExitCode.CREDENTIAL_NOT_ENTITLED),
        CheckSpec("bootstrap.ready", "bootstrap", ExitCode.GATE_FAILED),
    )


def check_identifiers() -> tuple[str, ...]:
    """Return every check identifier, in pipeline order.

    Returns:
        The identifiers.
    """
    return tuple(spec.identifier for spec in checks())


def spec_for(identifier: str) -> CheckSpec:
    """Look up a check by its identifier.

    Args:
        identifier: The check identifier.

    Returns:
        Its declaration.

    Raises:
        InternalError: If no check has that identifier. A caller naming a check
            that does not exist has a bug rather than bad input.
    """
    for spec in checks():
        if spec.identifier == identifier:
            return spec
    msg = f"no check is registered as {identifier!r}"
    raise InternalError(msg)


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """What one check concluded, and what to do about it.

    Args:
        identifier: Which check this is. Must be one of :data:`CHECKS`.
        status: What it concluded.
        summary: One sentence stating the finding, in the past tense.
        remediation: What the operator should do. Required for every status
            except :attr:`CheckStatus.PASS`, because a failure a reader cannot
            act on is a failure reported twice.

    Raises:
        ValidationError: If the identifier is unknown, or a non-passing outcome
            offers no remediation.
    """

    identifier: str
    status: CheckStatus
    summary: str
    remediation: str = ""

    def __post_init__(self) -> None:
        """Refuse an unregistered check, or a problem with no way out."""
        spec_for(self.identifier)
        if self.status is not CheckStatus.PASS and not self.remediation:
            msg = f"{self.identifier} concluded {self.status.value} and offers no remediation"
            raise ValidationError(msg)

    @property
    def category(self) -> str:
        """The area this check belongs to."""
        return spec_for(self.identifier).category

    @property
    def exit_code(self) -> ExitCode:
        """What the process returns when this check fails."""
        return spec_for(self.identifier).exit_code

    def as_record(self) -> dict[str, str]:
        """This outcome as the mapping the evidence carries.

        Returns:
            The identifier, category, status, summary and remediation.
        """
        return {
            "id": self.identifier,
            "category": self.category,
            "status": self.status.value,
            "summary": self.summary,
            "remediation": self.remediation,
        }


@dataclass(frozen=True, slots=True)
class BootstrapReport:
    """Every check that was performed, in the order they were performed.

    Args:
        outcomes: One per check. Order is the pipeline's, not sorted, because a
            reader wants to see where the run stopped.

    Raises:
        ValidationError: If a check is reported twice.

    A partial report is legitimate and common: the pipeline stops at the first
    failure that makes a later check meaningless, so a report may carry three
    outcomes rather than twelve. That is why this class does not require the full
    set — a report claiming twelve checks after refusing at the second would be
    describing a run that did not happen.
    """

    outcomes: tuple[CheckOutcome, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a report that concludes twice about one check."""
        counted = Counter(outcome.identifier for outcome in self.outcomes)
        repeated = sorted(identifier for identifier, count in counted.items() if count > 1)
        if repeated:
            msg = f"the report concludes more than once about {repeated}"
            raise ValidationError(msg)

    def status_of(self, identifier: str) -> CheckStatus | None:
        """What one check concluded, if it ran.

        Args:
            identifier: The check identifier.

        Returns:
            Its status, or ``None`` if the run stopped before reaching it.
        """
        for outcome in self.outcomes:
            if outcome.identifier == identifier:
                return outcome.status
        return None

    @property
    def ready(self) -> bool:
        """Whether every registered check ran and none of them refused.

        A report missing a check is not ready. "We stopped early" and "everything
        passed" must never reduce to the same answer, which is the whole reason
        this property counts as well as inspects.
        """
        if len(self.outcomes) != len(checks()):
            return False
        return all(
            outcome.status in {CheckStatus.PASS, CheckStatus.WARN} for outcome in self.outcomes
        )


def exit_code_for(report: BootstrapReport) -> ExitCode:
    """Reduce a report to the one number the process returns.

    Args:
        report: The checks that were performed.

    Returns:
        :attr:`ExitCode.OK` when nothing refused, otherwise the code declared by
        the earliest check that did.

    Unmeasured outranks failed, which is the rule ``tools/quality`` already
    applies and ADR-0045's reasoning applied to a process's answer: a check that
    could not run has not passed, and reporting it as a specific failure would
    claim knowledge nobody has.

    :attr:`CheckStatus.WARN` is not a refusal and is ignored here.
    """
    for outcome in report.outcomes:
        if outcome.status is CheckStatus.UNMEASURED:
            return ExitCode.UNMEASURED
    for outcome in report.outcomes:
        if outcome.status is CheckStatus.FAIL:
            return outcome.exit_code
    return ExitCode.OK


@dataclass(frozen=True, slots=True)
class ProjectIdentity:
    """Which GLOBIN this is, and where its version came from.

    Args:
        name: The distribution name.
        version: The version string.
        source: ``"metadata"`` when read from an installed distribution,
            ``"package"`` when read from the imported package's ``__version__``.

    The source is carried rather than dropped because the two answers mean
    different things. Installed metadata describes what was installed; the
    package attribute describes the source tree that happens to be importable,
    which on a development machine can be newer than what is installed.
    """

    name: str
    version: str
    source: str


@dataclass(frozen=True, slots=True)
class DependencyReadiness:
    """What is known about the dependencies this process needs.

    Args:
        declared: Every distribution ``project.dependencies`` names, sorted.
        locked: Whether a runtime lock accompanies them.
        missing: Declared distributions this interpreter cannot import metadata
            for, sorted.
        inventory: What the lock and the environment say about each other, or
            ``None`` when that could not be measured.

    Still shallow, and still deliberately so: resolving a dependency graph is a
    network operation, and a process that ran a resolver at start-up would need a
    network to start. Nothing here resolves, downloads or consults an index.

    **Phase 029 made it one layer less shallow than it was.** The three fields
    above answer "is what was declared present", by name. They cannot see a
    version, so an environment whose numpy had drifted two minor releases from
    the lock answered yes. :attr:`inventory` is the answer to the question those
    three could not ask, and it is a separate type rather than six more fields
    for a specific reason: :meth:`DependencyInventory.projection` must be able to
    hand a fingerprint a value with no volatile field in it, which a filtered
    view of a growing class cannot do.

    ``None`` means *not measured* -- no project root, or a lock that could not be
    read -- and never "nothing is wrong". The distinction is the same one
    ADR-0045 draws for a platform capability.
    """

    declared: tuple[str, ...] = ()
    locked: bool = False
    missing: tuple[str, ...] = ()
    inventory: DependencyInventory | None = None

    def as_record(self) -> dict[str, object]:
        """This readiness as the mapping the evidence carries.

        Returns:
            The declared set, whether a lock accompanies it, what is missing, and
            the inventory when one was measured.
        """
        return {
            "declared": list(self.declared),
            "locked": self.locked,
            "missing": list(self.missing),
            "inventory": None if self.inventory is None else self.inventory.as_record(),
        }


@dataclass(frozen=True, slots=True)
class SecretReadiness:
    """What is known about the secrets this process needs.

    Args:
        required: The references a start-up needs resolved. Empty today, and
            empty on purpose rather than by omission: GLOBIN reaches no exchange
            and holds no credential, so the set of secrets a start-up requires is
            genuinely nothing.
        unavailable: Required references that could not be resolved, sorted.

    **No value ever reaches this type.** A reference identifies a secret; it is
    not one. ``docs/security/SECRET_STORE_CONTRACT.md`` §1 makes that distinction
    and gives the reference type itself to Phase 028, which is why nothing here
    is named after a credential and why this class carries identifiers only.

    That the required set is empty makes the check vacuously true, which is a
    different thing from a check that was skipped. The distinction is worth the
    type: when Phase 028 fills the set in, this class does not change shape.
    """

    required: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = ()

    def as_record(self) -> dict[str, object]:
        """This readiness as the mapping the evidence carries.

        Returns:
            How many references are required and which of them are unavailable.
            The identifiers of resolved references are not published, because a
            list of what a deployment holds is itself worth withholding.
        """
        return {"required": len(self.required), "unavailable": list(self.unavailable)}


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    """The validated facts the rest of GLOBIN may rely on, assembled once.

    Args:
        identity: Which GLOBIN this is.
        host: The machine it is running on.
        interpreter: The Python running it.
        config: The validated configuration.
        paths: The declared runtime tree inside the project.
        root: Where the project was found, recorded.
        dependencies: What is known about declared dependencies.
        secrets: What is known about required secret references.
        runtime_root: Where the *mutable* runtime tree is, recorded. Phase 022
            separated the two: ``paths`` names evidence written about this
            repository, and this names the user-local tree a running GLOBIN keeps
            state in. Always a fingerprint rather than a spelling, because the
            tree lives under a user profile and a user profile names its owner.
        fingerprint: A digest over everything above that a rerun on an unchanged
            host reproduces exactly.

    **This is only ever built after every check passed.** There is no
    partially-valid context for a caller to observe, which is the same property
    :class:`~globin.domain.configuration.GlobinConfig` has and for the same
    reason.

    What it deliberately does not carry: the process environment, the contents of
    any file, a mutable field, a handle to anything open, and — above all — a
    secret value. A module that needs one of those asks for it explicitly, which
    keeps the dependency visible instead of letting this object become the ambient
    state the composition root exists to avoid.
    """

    identity: ProjectIdentity
    host: HostFacts
    interpreter: InterpreterFacts
    config: GlobinConfig
    paths: RuntimePaths
    root: RecordedPath
    dependencies: DependencyReadiness
    secrets: SecretReadiness
    runtime_root: RecordedPath
    fingerprint: str

    def __repr__(self) -> str:
        """Identify this context without reproducing anything it holds.

        Returns:
            The type, the version and the fingerprint.

        Written out rather than left to the dataclass. The generated repr would
        expand every field, which is how a value nobody meant to print ends up in
        a traceback, a log line or a test failure — and this type is exactly the
        one a debugger will be pointed at.
        """
        return (
            f"RuntimeContext(version={self.identity.version!r}, fingerprint={self.fingerprint!r})"
        )


def context_fingerprint(
    *,
    identity: ProjectIdentity,
    host: HostFacts,
    interpreter: InterpreterFacts,
    dependencies: DependencyReadiness,
) -> str:
    """A digest identifying this combination of project, host and dependencies.

    Args:
        identity: Which GLOBIN this is.
        host: The machine.
        interpreter: The Python.
        dependencies: What is declared and what is present.

    Returns:
        ``"sha256:"`` followed by 64 lowercase hexadecimal characters.

    Deterministic by construction. Nothing volatile is folded in — no process
    identifier, no clock reading, no random value — so two runs on an unchanged
    host produce the same fingerprint and a change in it means something a person
    would want to know about actually changed. A correlation identifier, which is
    volatile on purpose, is a separate thing and is not this.

    The interpreter's *recorded* paths participate rather than its real ones, so
    the fingerprint is stable on one machine without ever having seen an absolute
    path.
    """
    parts: tuple[str, ...] = (
        identity.name,
        identity.version,
        host.system,
        host.release,
        host.machine,
        str(host.pointer_bits),
        interpreter.implementation,
        interpreter.version,
        interpreter.release_level,
        str(interpreter.free_threaded),
        _recorded_token(interpreter.executable),
        _recorded_token(interpreter.prefix),
        _recorded_token(interpreter.base_prefix),
        ",".join(dependencies.declared),
        str(dependencies.locked),
    )
    return "sha256:" + hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()


def _recorded_token(recorded: RecordedPath) -> str:
    """A recorded path as one string, for folding into a digest.

    Args:
        recorded: The recorded path.

    Returns:
        The location and whichever field it carries.
    """
    return f"{recorded.location.value}:{recorded.path or recorded.fingerprint or ''}"


# ---------------------------------------------------------------------------
# The judgements. Each takes facts and returns an outcome; none reads anything.
# ---------------------------------------------------------------------------


def host_outcome(facts: HostFacts, baseline: RuntimeBaseline) -> CheckOutcome:
    """Judge the operating system against the declared baseline.

    Args:
        facts: What was observed about the machine.
        baseline: What the declaration requires.

    Returns:
        The outcome of ``runtime.host``.
    """
    if facts.system != baseline.system:
        return CheckOutcome(
            identifier="runtime.host",
            status=CheckStatus.FAIL,
            summary=f"this host runs {facts.system or 'an unnamed system'}",
            remediation=(
                f"GLOBIN declares {baseline.system} as its only platform (ADR-0009). "
                f"Run it on {baseline.system}."
            ),
        )
    if not _release_at_least(facts.release, baseline.minimum_release):
        return CheckOutcome(
            identifier="runtime.host",
            status=CheckStatus.FAIL,
            summary=f"{facts.system} {facts.release} is older than the declared floor",
            remediation=(
                f"docs/engineering/runtime-contract.toml requires "
                f"{baseline.system} {baseline.minimum_release} or later."
            ),
        )
    return CheckOutcome(
        identifier="runtime.host",
        status=CheckStatus.PASS,
        summary=f"{facts.system} {facts.release} satisfies the declared baseline",
    )


def _release_at_least(observed: str, minimum: str) -> bool:
    """Whether an operating-system release is at least the declared floor.

    Args:
        observed: The release as the platform reports it.
        minimum: The declared floor.

    Returns:
        ``True`` when the observed release is the floor or later.

    Compared on the leading integer alone. Windows reports ``"10"`` and ``"11"``
    for the releases this contract names, and inventing a richer comparison would
    be inventing meaning for strings nobody has seen.
    """
    return _leading_integer(observed) >= _leading_integer(minimum)


def _leading_integer(text: str) -> int:
    """The integer a string starts with, or zero.

    Args:
        text: The string.

    Returns:
        The leading digits as an integer, or ``0`` when it starts with none.
    """
    digits = ""
    for character in text:
        if not character.isdigit():
            break
        digits += character
    return int(digits) if digits else 0


def architecture_outcome(facts: HostFacts, baseline: RuntimeBaseline) -> CheckOutcome:
    """Judge the processor architecture and pointer width.

    Args:
        facts: What was observed about the machine.
        baseline: What the declaration requires.

    Returns:
        The outcome of ``runtime.architecture``.
    """
    problems: list[str] = []
    if facts.machine.upper() != baseline.architecture.upper():
        problems.append(f"the architecture is {facts.machine!r}, not {baseline.architecture!r}")
    if facts.pointer_bits != baseline.pointer_bits:
        problems.append(f"pointers are {facts.pointer_bits}-bit, not {baseline.pointer_bits}-bit")
    if problems:
        return CheckOutcome(
            identifier="runtime.architecture",
            status=CheckStatus.FAIL,
            summary=_joined(problems),
            remediation=(
                "The wheel survey in docs/engineering/wheel-survey.toml was taken for "
                f"{baseline.architecture}. Use a {baseline.architecture} interpreter."
            ),
        )
    return CheckOutcome(
        identifier="runtime.architecture",
        status=CheckStatus.PASS,
        summary=f"{facts.machine} with {facts.pointer_bits}-bit pointers",
    )


def implementation_outcome(facts: InterpreterFacts, baseline: RuntimeBaseline) -> CheckOutcome:
    """Judge which Python implementation is running.

    Args:
        facts: What was observed about the interpreter.
        baseline: What the declaration requires.

    Returns:
        The outcome of ``python.implementation``.
    """
    if facts.implementation.lower() != baseline.implementation.lower():
        return CheckOutcome(
            identifier="python.implementation",
            status=CheckStatus.FAIL,
            summary=f"this is {facts.implementation}, not {baseline.implementation}",
            remediation=(
                f"docs/engineering/runtime-contract.toml declares {baseline.implementation}. "
                "Rebuild .venv with scripts/bootstrap.ps1."
            ),
        )
    if facts.free_threaded and not baseline.free_threaded:
        return CheckOutcome(
            identifier="python.implementation",
            status=CheckStatus.FAIL,
            summary="this is a free-threaded build, which the contract does not accept",
            remediation=(
                "The free-threaded build has a different ABI and a different wheel set, "
                "and docs/engineering/wheel-survey.toml has not surveyed it. "
                "Use the standard build."
            ),
        )
    return CheckOutcome(
        identifier="python.implementation",
        status=CheckStatus.PASS,
        summary=f"{facts.implementation}, standard build",
    )


def version_outcome(facts: InterpreterFacts, baseline: RuntimeBaseline) -> CheckOutcome:
    """Judge the interpreter's version against the declared line and floor.

    Args:
        facts: What was observed about the interpreter.
        baseline: What the declaration requires.

    Returns:
        The outcome of ``python.version``.

    The minor line is exact and the patch is a floor, which is Phase 017's
    decision restated in a judgement rather than a second declaration of it.
    """
    observed = parse_version(facts.version)
    if observed is None:
        return CheckOutcome(
            identifier="python.version",
            status=CheckStatus.UNMEASURED,
            summary=f"{facts.version!r} is not a three-part version",
            remediation="Report this: an interpreter that cannot state its own version is a bug.",
        )
    line = f"{observed[0]}.{observed[1]}"
    if line != baseline.minor_line:
        return CheckOutcome(
            identifier="python.version",
            status=CheckStatus.FAIL,
            summary=(
                f"this is Python {facts.version}, and the contract declares {baseline.minor_line}"
            ),
            remediation=(
                f"A tree verified on {baseline.minor_line} has not been verified on {line}. "
                "Rebuild .venv with scripts/bootstrap.ps1, or raise the line deliberately."
            ),
        )
    floor = parse_version(baseline.minimum_patch)
    if floor is not None and observed < floor:
        return CheckOutcome(
            identifier="python.version",
            status=CheckStatus.FAIL,
            summary=f"Python {facts.version} is older than the verified floor",
            remediation=(
                f"docs/engineering/runtime-contract.toml records {baseline.minimum_patch} "
                "as the oldest patch this tree was verified on."
            ),
        )
    if facts.release_level != "final" and not baseline.allow_prerelease:
        return CheckOutcome(
            identifier="python.version",
            status=CheckStatus.FAIL,
            summary=f"this is a {facts.release_level} interpreter, not a released one",
            remediation=(
                "A pre-release can change behaviour before it ships, so a gate that passed "
                "on one is evidence about a runtime that no longer exists."
            ),
        )
    return CheckOutcome(
        identifier="python.version",
        status=CheckStatus.PASS,
        summary=f"Python {facts.version} satisfies the {baseline.minor_line} line",
    )


def parse_version(text: str) -> tuple[int, int, int] | None:
    """Read a three-part version.

    Args:
        text: The version, as ``"3.14.5"``.

    Returns:
        Its three components, or ``None`` when the string is not three integers
        separated by dots.
    """
    parts = text.split(".")
    if len(parts) != VERSION_PARTS:
        return None
    if not all(part.isdigit() for part in parts):
        return None
    major, minor, patch = (int(part) for part in parts)
    return major, minor, patch


def environment_outcome(facts: InterpreterFacts, baseline: RuntimeBaseline) -> CheckOutcome:
    """Judge whether this interpreter is the project's own.

    Args:
        facts: What was observed about the interpreter.
        baseline: What the declaration requires, including the one permitted
            environment directory — which is where the expected location comes
            from, so nothing else has to be told it.

    Returns:
        The outcome of ``python.environment``.

    Decided on :data:`sys.prefix` rather than on the name ``python`` resolving to
    something. What is on ``PATH`` is a statement about the shell; what
    :data:`sys.prefix` says is a statement about the process that is asking.

    Both sides of the comparison are :class:`RecordedPath` values, so the check
    is performed on project-relative spellings and an absolute path is never
    needed to answer it.
    """
    expected = recorded_inside(baseline.environment_directory)
    if not facts.in_virtual_environment:
        return CheckOutcome(
            identifier="python.environment",
            status=CheckStatus.FAIL,
            summary="this interpreter is not running inside a virtual environment",
            remediation=(
                f"GLOBIN runs from {baseline.environment_directory}. "
                "Build it with scripts/bootstrap.ps1 and run through "
                f"{baseline.environment_directory}\\Scripts\\python.exe."
            ),
        )
    if facts.prefix != expected:
        return CheckOutcome(
            identifier="python.environment",
            status=CheckStatus.FAIL,
            summary="this interpreter belongs to a different environment from the project's",
            remediation=(
                f"The declared environment is {baseline.environment_directory} at the project "
                "root. Run through its own interpreter rather than whichever Python PATH found."
            ),
        )
    return CheckOutcome(
        identifier="python.environment",
        status=CheckStatus.PASS,
        summary=f"running from {baseline.environment_directory}",
    )


def root_outcome(root: RecordedPath, *, searched_from: str) -> CheckOutcome:
    """Judge whether the project root was found.

    Args:
        root: Where it was found, recorded.
        searched_from: How the search started, for the failure message.

    Returns:
        The outcome of ``project.root``.
    """
    if root.location is PathLocation.ABSENT:
        return CheckOutcome(
            identifier="project.root",
            status=CheckStatus.FAIL,
            summary=f"no project root was found {searched_from}",
            remediation=(
                "GLOBIN locates itself by searching upwards for a pyproject.toml naming this "
                f"project, at most {MAX_ROOT_SEARCH_DEPTH} directories. "
                "Run the command from inside a checkout."
            ),
        )
    return CheckOutcome(
        identifier="project.root",
        status=CheckStatus.PASS,
        summary=f"the project root was found {searched_from}",
    )


def identity_outcome(identity: ProjectIdentity | None, *, expected_name: str) -> CheckOutcome:
    """Judge whether this GLOBIN could identify itself.

    Args:
        identity: What was read, or ``None`` when nothing could be.
        expected_name: The distribution name the project contract declares.

    Returns:
        The outcome of ``project.identity``.

    Reading the version from the imported package rather than from installed
    metadata is a warning and not a failure. It is the normal state of a source
    checkout that has not been installed, and refusing to start there would make
    the diagnostic unusable exactly when somebody needs it.
    """
    if identity is None:
        return CheckOutcome(
            identifier="project.identity",
            status=CheckStatus.FAIL,
            summary="this GLOBIN could not state its own name and version",
            remediation=(
                "Install the project into its environment with scripts/bootstrap.ps1, "
                "which is what puts the distribution metadata in place."
            ),
        )
    if identity.name != expected_name:
        return CheckOutcome(
            identifier="project.identity",
            status=CheckStatus.FAIL,
            summary=f"the installed distribution is named {identity.name!r}",
            remediation=(
                f"src/globin/project_contract.py declares {expected_name!r}. "
                "Something other than GLOBIN is installed under this import name."
            ),
        )
    if identity.source != "metadata":
        return CheckOutcome(
            identifier="project.identity",
            status=CheckStatus.WARN,
            summary=f"{identity.name} {identity.version}, read from the source tree",
            remediation=(
                "The project is not installed in this environment, so the console entry "
                "point does not exist. Run scripts/bootstrap.ps1 to install it."
            ),
        )
    return CheckOutcome(
        identifier="project.identity",
        status=CheckStatus.PASS,
        summary=f"{identity.name} {identity.version}, from installed metadata",
    )


def dependency_outcome(readiness: DependencyReadiness) -> CheckOutcome:
    """Judge whether declared dependencies are present and locked.

    Args:
        readiness: What is declared, whether it is locked, and what is missing.

    Returns:
        The outcome of ``dependency.lock``.

    Nothing is resolved and no index is consulted. A process that ran a resolver
    to start would need a network to start, which is a property GLOBIN must not
    acquire by accident.
    """
    if readiness.missing:
        return CheckOutcome(
            identifier="dependency.lock",
            status=CheckStatus.FAIL,
            summary=f"declared but not installed: {_joined(readiness.missing)}",
            remediation=(
                "Install from the lock with scripts/bootstrap.ps1. "
                "Do not install them individually: the lock is what makes the set reproducible."
            ),
        )
    if readiness.declared and not readiness.locked:
        return CheckOutcome(
            identifier="dependency.lock",
            status=CheckStatus.FAIL,
            summary="runtime dependencies are declared and no runtime lock accompanies them",
            remediation=(
                "This checkout is incomplete: docs/engineering/DEPENDENCY_LOCKING.md "
                "requires pylock.toml beside project.dependencies, and it is missing. "
                "Fetch the repository again rather than resolving the versions here — "
                "an unlocked install is a different set of packages from the one that "
                "was verified."
            ),
        )
    if not readiness.declared:
        return CheckOutcome(
            identifier="dependency.lock",
            status=CheckStatus.PASS,
            summary="no runtime dependency is declared",
        )

    inventory = readiness.inventory
    if inventory is not None:
        if inventory.lock_state is LockState.UNSUPPORTED:
            return CheckOutcome(
                identifier="dependency.lock",
                status=CheckStatus.FAIL,
                summary=(
                    f"pylock.toml announces lock-version {inventory.lock_version}, "
                    f"which this GLOBIN does not implement"
                ),
                remediation=(
                    "PEP 751 requires a tool that does not support a lock's major "
                    "version to refuse it rather than read it optimistically. "
                    "Install a GLOBIN new enough for this lock, or fetch a "
                    "checkout whose lock this one can read."
                ),
            )
        if inventory.lock_state is LockState.UNREADABLE:
            return CheckOutcome(
                identifier="dependency.lock",
                status=CheckStatus.FAIL,
                summary="pylock.toml exists and could not be read",
                remediation=(
                    "The file is not valid TOML, or not the shape PEP 751 "
                    "describes. Fetch the repository again rather than editing "
                    "it here."
                ),
            )
        if inventory.lock_state is LockState.INTERPRETER_EXCLUDED:
            return CheckOutcome(
                identifier="dependency.lock",
                status=CheckStatus.FAIL,
                summary="pylock.toml was resolved for a different interpreter",
                remediation=(
                    "Its requires-python does not admit the interpreter running "
                    "GLOBIN. Build the environment with scripts/bootstrap.ps1, "
                    "which uses the interpreter the runtime contract declares."
                ),
            )
        divergent = inventory.unsatisfied()
        if divergent:
            names = tuple(observation.name for observation in divergent)
            return CheckOutcome(
                identifier="dependency.lock",
                status=CheckStatus.FAIL,
                summary=(
                    f"{len(divergent)} distribution(s) diverge from the lock: {_joined(names[:3])}"
                ),
                remediation=(
                    "Reinstall from the lock with scripts/bootstrap.ps1. "
                    "Installing the differences individually would produce a "
                    "third set of packages rather than the verified one."
                ),
            )
        if inventory.unknown_keys:
            return CheckOutcome(
                identifier="dependency.lock",
                status=CheckStatus.WARN,
                summary=(
                    f"pylock.toml carries {len(inventory.unknown_keys)} key(s) this "
                    f"GLOBIN does not know: {_joined(inventory.unknown_keys[:3])}"
                ),
                remediation=(
                    "PEP 751 makes an unknown key inside a supported major "
                    "version a warning rather than a refusal, so this does not "
                    "stop a start-up. The lock was written by a newer producer "
                    "than this GLOBIN was built against."
                ),
            )

    return CheckOutcome(
        identifier="dependency.lock",
        status=CheckStatus.PASS,
        summary=f"{len(readiness.declared)} declared, locked and installed",
    )


def configuration_outcome(config: GlobinConfig | None, *, problem: str = "") -> CheckOutcome:
    """Judge whether the configuration bound and validated.

    Args:
        config: The validated configuration, or ``None`` when binding refused.
        problem: What binding said, when it refused.

    Returns:
        The outcome of ``config.valid``.
    """
    if config is None:
        return CheckOutcome(
            identifier="config.valid",
            status=CheckStatus.FAIL,
            summary=problem or "the configuration could not be bound",
            remediation=(
                "Correct the setting the message names. "
                "docs/CONFIGURATION_POLICY.md lists every key and its permitted values."
            ),
        )
    return CheckOutcome(
        identifier="config.valid",
        status=CheckStatus.PASS,
        summary=f"bound, logging at {config.logging.min_severity.name}",
    )


def capability_outcome(snapshot: EnvironmentCapabilitySnapshot) -> CheckOutcome:
    """Judge whether this host's capabilities permit a start.

    Args:
        snapshot: What the capability probes reported.

    Returns:
        The outcome of ``environment.capability``.

    **Three verdicts collapse to two statuses, and the collapse is the
    decision.** :attr:`~globin.domain.environment.EnvironmentCompatibility.BLOCKED`
    is a :attr:`CheckStatus.FAIL`, and both ``READY`` and ``DEGRADED`` pass —
    ``DEGRADED`` as a :attr:`CheckStatus.WARN`, which
    :func:`exit_code_for` ignores.

    That is what stops this check making CI permanently red. The hosted runner
    is a legitimate machine that cannot answer the native-architecture question
    the way this one can, and ``DEGRADED`` is precisely the state ADR-0045
    invented for "measured, usable, and not what a fully-configured host would
    show". A phase that promoted degradation to failure would be re-deciding
    that, and should say so.
    """
    compatibility = snapshot.compatibility()
    fingerprint = compatibility_fingerprint(snapshot.projection())
    if compatibility is EnvironmentCompatibility.BLOCKED:
        reasons = ", ".join(reason.value for reason in snapshot.blocking_reasons())
        return CheckOutcome(
            identifier="environment.capability",
            status=CheckStatus.FAIL,
            summary=f"this host cannot run GLOBIN: {reasons}",
            remediation=(
                "A required environment capability is absent. The reasons above are "
                "bounded codes; docs/engineering/ENVIRONMENT_CAPABILITY.md maps each "
                "to what to do about it."
            ),
        )
    if compatibility is EnvironmentCompatibility.DEGRADED:
        degraded = ", ".join(
            sorted({check.reason.value for check in snapshot.checks if check.degrading})
        )
        return CheckOutcome(
            identifier="environment.capability",
            status=CheckStatus.WARN,
            summary=f"usable, with {degraded} ({fingerprint})",
            remediation=(
                "Starting is permitted. Each code above names a capability that is "
                "absent, unmeasurable or worse than intended; none of them blocks."
            ),
        )
    return CheckOutcome(
        identifier="environment.capability",
        status=CheckStatus.PASS,
        summary=f"every declared capability is supported ({fingerprint})",
    )


def secrets_outcome(readiness: SecretReadiness) -> CheckOutcome:
    """Judge whether every required secret reference can be resolved.

    Args:
        readiness: Which references are required and which are unavailable.

    Returns:
        The outcome of ``secrets.required``.

    Passing on an empty required set is a vacuous truth rather than a skipped
    check, and the summary says so. The distinction matters because the two look
    identical in a log and mean opposite things the day Phase 028 puts a store
    behind this.
    """
    if readiness.unavailable:
        return CheckOutcome(
            identifier="secrets.required",
            status=CheckStatus.FAIL,
            summary=f"{len(readiness.unavailable)} required reference(s) could not be resolved",
            remediation=(
                "Every reference GLOBIN needs must exist in the local store before start-up. "
                "The identifiers are listed above; their values are never printed."
            ),
        )
    if not readiness.required:
        return CheckOutcome(
            identifier="secrets.required",
            status=CheckStatus.PASS,
            summary="no secret is required to start, so there is nothing to resolve",
        )
    return CheckOutcome(
        identifier="secrets.required",
        status=CheckStatus.PASS,
        summary=f"all {len(readiness.required)} required reference(s) resolved",
    )


@dataclass(frozen=True, slots=True)
class EntitlementReadiness:
    """What is known about whether required credentials may do what is asked.

    Args:
        demanded: One identifier per requirement, sorted.
        refused: Identifiers whose verdict refuses, sorted.
        states: Identifier and verification state, sorted.

    A separate type from :class:`SecretReadiness` rather than three more fields
    on it, so that class keeps the shape and the "no value ever reaches this
    type" docstring it already has. This one answers a different question: not
    whether a credential resolves, but whether it is allowed to be used.

    Every field is a name or a bounded state. There is no field material could
    occupy.
    """

    demanded: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    states: tuple[tuple[str, str], ...] = ()

    def as_record(self) -> dict[str, object]:
        """This readiness as the mapping the evidence carries.

        Returns:
            What was demanded, what was refused, and the state of each.
        """
        return {
            "demanded": list(self.demanded),
            "refused": list(self.refused),
            "states": [list(pair) for pair in self.states],
        }


def entitlement_outcome(readiness: EntitlementReadiness) -> CheckOutcome:
    """Judge whether every required credential is permitted to be used.

    Args:
        readiness: What was demanded and how each verdict came out.

    Returns:
        The outcome of ``secrets.entitlement``.

    Passing on an empty demand set is a vacuous truth rather than a skipped
    check, and the summary says so -- the same distinction
    :func:`secrets_outcome` draws, for the same reason: the two look identical in
    a log and mean opposite things the day a phase declares a requirement.
    """
    if readiness.refused:
        return CheckOutcome(
            identifier="secrets.entitlement",
            status=CheckStatus.FAIL,
            summary=(
                f"{len(readiness.refused)} credential(s) not permitted to be used: "
                f"{_joined(readiness.refused)}"
            ),
            remediation=(
                "A credential is required for an operation its declared grants "
                "do not cover, or GLOBIN withholds the permission class "
                "outright. Declare what each key carries with globin secrets "
                "set; no declaration can grant a withheld class."
            ),
        )
    if not readiness.demanded:
        return CheckOutcome(
            identifier="secrets.entitlement",
            status=CheckStatus.PASS,
            summary="no credential is required, so there is nothing to permit",
        )
    return CheckOutcome(
        identifier="secrets.entitlement",
        status=CheckStatus.PASS,
        summary=f"all {len(readiness.demanded)} required credential(s) permitted",
    )


def paths_outcome(problems: Sequence[str], paths: RuntimePaths) -> CheckOutcome:
    """Judge whether the runtime tree is usable.

    Args:
        problems: One sentence per declared root that could not be used.
        paths: The declared tree, for the passing summary.

    Returns:
        The outcome of ``paths.runtime``.
    """
    if problems:
        return CheckOutcome(
            identifier="paths.runtime",
            status=CheckStatus.FAIL,
            summary=_joined(problems),
            remediation=(
                "Make the named location writable, or run from a checkout that is. "
                "GLOBIN creates nothing outside the project root."
            ),
        )
    created = sorted(CREATED_PATHS)
    return CheckOutcome(
        identifier="paths.runtime",
        status=CheckStatus.PASS,
        summary=f"{len(paths.declared())} roots declared, {len(created)} of them created",
    )


def ready_outcome(preceding: Sequence[CheckOutcome]) -> CheckOutcome:
    """Judge the run as a whole.

    Args:
        preceding: Every outcome produced before this one.

    Returns:
        The outcome of ``bootstrap.ready``.

    Raises:
        InternalError: If it is handed an outcome for itself, which would make
            the aggregate answer for its own answer.
    """
    if any(outcome.identifier == AGGREGATE_CHECK for outcome in preceding):
        msg = f"{AGGREGATE_CHECK} cannot be one of the outcomes it aggregates"
        raise InternalError(msg)

    expected = len(checks()) - 1
    if len(preceding) != expected:
        return CheckOutcome(
            identifier=AGGREGATE_CHECK,
            status=CheckStatus.FAIL,
            summary=f"{len(preceding)} of {expected} checks ran, so the run is incomplete",
            remediation="Read the outcomes above: the run stopped at the first refusal.",
        )
    refused = [
        outcome.identifier
        for outcome in preceding
        if outcome.status in {CheckStatus.FAIL, CheckStatus.UNMEASURED}
    ]
    if refused:
        return CheckOutcome(
            identifier=AGGREGATE_CHECK,
            status=CheckStatus.FAIL,
            summary=f"{_joined(refused)} did not pass",
            remediation="Act on the remediation each of those checks gave.",
        )
    warned = [outcome.identifier for outcome in preceding if outcome.status is CheckStatus.WARN]
    if warned:
        return CheckOutcome(
            identifier=AGGREGATE_CHECK,
            status=CheckStatus.WARN,
            summary=f"ready, with {_joined(warned)} worth reading",
            remediation="Nothing blocks start-up; the warnings above are worth acting on.",
        )
    return CheckOutcome(
        identifier=AGGREGATE_CHECK,
        status=CheckStatus.PASS,
        summary="every check passed, and GLOBIN may start",
    )


def _joined(items: Iterable[str]) -> str:
    """Join sentences or names into one readable phrase.

    Args:
        items: The pieces.

    Returns:
        Them, separated by semicolons.
    """
    return "; ".join(items)


@dataclass(frozen=True, slots=True)
class BootstrapOutcome:
    """Everything one bootstrap run concluded.

    Args:
        report: Every check that was performed.
        context: The assembled context, or ``None`` when the run refused.
        observed: The facts the checks were performed against, for the evidence.
            ``None`` rather than an empty mapping when nothing was measured,
            because ``field(default_factory=dict)`` is a call in a class body and
            a layer package performs none at import.

    Raises:
        ValidationError: If a context accompanies a report that is not ready.

    **The invariant is the phase.** A context that exists means every check
    passed, so a caller holding one has already been told it may proceed. There
    is no flag to read and no convention to remember, and a run that failed
    cannot hand anything downstream because there is nothing to hand.
    """

    report: BootstrapReport
    context: RuntimeContext | None = None
    observed: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        """Refuse a context the report does not justify."""
        if self.context is not None and not self.report.ready:
            msg = "a runtime context was assembled for a report that is not ready"
            raise ValidationError(msg)

    @property
    def exit_code(self) -> ExitCode:
        """What the process should return."""
        return exit_code_for(self.report)

    @property
    def ready(self) -> bool:
        """Whether GLOBIN may start."""
        return self.context is not None


def readiness_for(exit_code: ExitCode) -> ReadinessReason:
    """The readiness class an exit code implies.

    Args:
        exit_code: The code a bootstrap run would exit with.

    Returns:
        The bounded reason a reader should be told, never a sentence.

    **Total over** :class:`ExitCode` by construction: the mapping is consulted
    and anything absent from it becomes :attr:`ReadinessReason.UNKNOWN`, so a
    later phase adding a code cannot make this raise. A contract test asserts the
    totality anyway, and asserts that every reason except the three lifecycle
    ones is reachable from some code -- a member nothing can produce is
    vocabulary rather than a capability.

    **This function is why** :attr:`ReadinessReason.DEPENDENCY_UNREADY` **stopped
    being decorative.** It was declared in Phase 027 and, until Phase 029,
    nothing anywhere set it: ``mark_unready`` had no production caller, because
    no long-running run exists yet to call it. Rather than add a call to a run
    that does not exist, the reason is derived from the verdict a bootstrap
    already reaches, and published inside the digested part of its manifest.

    It lives here rather than beside :class:`ReadinessReason` because of the
    import graph: ``domain.configuration`` imports ``domain.diagnostics_http``
    and this module imports ``domain.configuration``, so the dependency may run
    this way and not the other. Putting it there would have been a cycle.
    """
    mapping = {
        ExitCode.OK: ReadinessReason.READY,
        ExitCode.HOST_UNSUPPORTED: ReadinessReason.ENVIRONMENT_INCOMPATIBLE,
        ExitCode.INTERPRETER_MISMATCH: ReadinessReason.ENVIRONMENT_INCOMPATIBLE,
        ExitCode.ENVIRONMENT_MISMATCH: ReadinessReason.ENVIRONMENT_INCOMPATIBLE,
        ExitCode.ENVIRONMENT_INCOMPATIBLE: ReadinessReason.ENVIRONMENT_INCOMPATIBLE,
        ExitCode.DEPENDENCY_UNREADY: ReadinessReason.DEPENDENCY_UNREADY,
        ExitCode.CONFIGURATION_INVALID: ReadinessReason.CONFIGURATION_INVALID,
        ExitCode.SECRETS_UNREADY: ReadinessReason.SECRETS_UNREADY,
    }
    return mapping.get(exit_code, ReadinessReason.UNKNOWN)
