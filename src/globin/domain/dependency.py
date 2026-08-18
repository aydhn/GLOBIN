"""What GLOBIN's dependencies are, what is installed, and what is stable about it.

This module holds the judgement and none of the observation. Every function here
takes values and returns a verdict, so a missing distribution, a version that
moved underneath the lock and a package excluded by an environment marker are all
testable from literals and none of them has to be installed. Reading the lock and
the environment is :mod:`globin.adapters.dependency`'s job.

**The defect this module exists to fix.** Until Phase 029 a running GLOBIN knew
three things about its dependencies: which names ``pyproject.toml`` declared,
whether a lock file existed, and which declared names were absent.
:class:`~globin.domain.bootstrap.DependencyReadiness` said so and called itself
"deliberately shallow". What it could not see was a *version*, because
``installed_distributions()`` walked every distribution's metadata and then threw
the version away -- while the gate's own twin in ``tools/quality/lock/gate.py``
had been returning name-to-version pairs all along. An environment whose numpy
had drifted two minor versions from the lock was reported ready.

**Five states rather than a boolean, and the fifth earns its place.**
:attr:`DependencyState.NOT_APPLICABLE` means an entry's marker or its
``requires-python`` excludes this environment, which is different from it being
absent. Without it, a package legitimately not installed on this platform is
reported :attr:`DependencyState.MISSING` -- a false refusal, and one this
repository would have shipped the moment it declared its first marked dependency.

**The fingerprint cannot see a volatile field, because it is not given one.**
:func:`dependency_fingerprint` takes a :class:`DependencyProjection`, which has
two fields and nowhere to put a timestamp, a path, an artefact URL, a file size
or an upload time. It also cannot see ``lock_version`` or ``unknown_keys``, which
:class:`DependencyInventory` does carry: a producer moving a lock from ``1.0`` to
``1.1`` without changing a single package has not changed which dependencies this
environment has, and a fingerprint that moved would report a difference that does
not exist.

**This module reads no lock.** Parsing PEP 751 is
:mod:`globin.adapters.dependency`'s, and it does not do it by hand either --
``packaging.pylock`` is the specification's reference implementation and this
repository ships it. What arrives here is a :class:`LockReading`, which is
whatever a reader made of a document, including the ways it failed.

What this module does not decide: whether a wheel could be installed (that is
``tools/quality/materialize``), whether the committed lock is internally coherent
(``tools/quality/lock``, answering that since Phase 020), or what a long-running
process should re-check on a timer (Phase 030).
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from packaging.markers import InvalidMarker, Marker
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

FINGERPRINT_LENGTH: Final[int] = 32
"""How many hexadecimal characters of the digest identify a dependency state.

Thirty-two, matching :data:`globin.domain.environment.FINGERPRINT_LENGTH` rather
than choosing independently. Two fingerprints read side by side in one evidence
document should look like the same kind of thing.
"""

FINGERPRINT_SCHEMA: Final[str] = "globin.dependency.inventory.1"
"""What the fingerprint is a fingerprint *of*.

Mixed into the digest so that a change to the projection's meaning produces
different fingerprints rather than silently comparing two things that were never
the same. The trailing number moves when the rendering changes.
"""

SEPARATOR: Final[str] = "\x1f"
"""The unit separator, used to join fields inside one canonical line.

No PEP 503 name, no PEP 440 version and no member of the bounded enumerations
below can contain it, so two different projections cannot render identically by
concatenation.
"""


class LockState(StrEnum):
    """What a reader made of the lock document, including how it failed."""

    PRESENT = "present"
    """A lock was found, parsed, and describes this interpreter."""

    ABSENT = "absent"
    """No lock file exists beside the project."""

    UNREADABLE = "unreadable"
    """A file exists but is not TOML, or is not the shape PEP 751 describes."""

    UNSUPPORTED = "unsupported"
    """The lock's major version is one this reader does not implement.

    PEP 751 is explicit that this is a refusal rather than a warning: *"If a tool
    doesn't support a major version, it MUST raise an error."* The reference
    implementation enforces ``1 <= lock-version < 2`` and raises; this state is
    that raise, translated into a value.
    """

    NEWER_MINOR = "newer_minor"
    """The major version is supported and something was not recognised.

    The specification's companion clause to the one above: *"If a tool supports
    the major version but not the minor version, a tool SHOULD warn when an
    unknown key is seen."* A warning, not a refusal -- so this state degrades
    rather than blocks, and the keys that caused it are carried alongside so the
    warning can name them.
    """

    INTERPRETER_EXCLUDED = "interpreter_excluded"
    """The lock's own ``requires-python`` does not admit the running interpreter.

    Every comparison this module would go on to make is meaningless in that case,
    because the lock was resolved for a different interpreter than the one
    asking. Saying so is the only honest answer; reporting each package as
    missing would be technically true and entirely misleading.
    """


class DependencyState(StrEnum):
    """How one distribution stands between the lock and the environment."""

    SATISFIED = "satisfied"
    """Locked, installed, and the versions agree."""

    MISSING = "missing"
    """Locked and applicable here, but not installed."""

    VERSION_MISMATCH = "version_mismatch"
    """Locked and installed, but at a version the lock does not name.

    The state this phase exists to make visible. Before Phase 029 it was not
    merely unreported -- it was unrepresentable, because no version was read.
    """

    UNLOCKED = "unlocked"
    """Declared in ``pyproject.toml`` and absent from the lock.

    The runtime-side spelling of the question ``coverage_problems`` asks in the
    lock gate. Reaching it means the lock and the project declaration have
    diverged, which the gate would also refuse -- but the gate is not running
    when a GLOBIN process starts up on somebody's machine.
    """

    NOT_APPLICABLE = "not_applicable"
    """An environment marker or ``requires-python`` excludes it here.

    Not a problem, and specifically not :attr:`MISSING`. This is the state that
    stops the inventory crying wolf about a package that was never meant to be
    installed on this platform.
    """


@dataclass(frozen=True, slots=True, order=True)
class DependencyObservation:
    """One distribution, as the lock names it and as the environment holds it.

    Args:
        name: The canonicalised, PEP 503 name.
        state: How the two compare.
        locked_version: What the lock names, or empty when it names nothing.
        installed_version: What is installed, or empty when nothing is.

    ``order=True`` with ``name`` first, so sorting a tuple of these sorts by
    distribution -- which is what :meth:`DependencyProjection.canonical` relies
    on to keep a fingerprint stable across a reordered lock.
    """

    name: str
    state: DependencyState
    locked_version: str = ""
    installed_version: str = ""

    def as_record(self) -> dict[str, object]:
        """Render as ordinary data for an evidence document.

        Returns:
            A mapping of plain values. Nothing here is a path, a URL or a
            credential; a distribution name and a version are public facts about
            what this environment holds.
        """
        return {
            "name": self.name,
            "state": self.state.value,
            "locked_version": self.locked_version,
            "installed_version": self.installed_version,
        }


@dataclass(frozen=True, slots=True)
class DependencyProjection:
    """Everything the fingerprint is computed over, and nothing else.

    Args:
        observations: One per distribution, in any order.
        lock_state: What the reader made of the document.

    **This type is the volatile-field exclusion.** It is not a filtered view of
    an inventory; it is a separate type with two fields and nowhere to put a
    timestamp, a process identifier, a duration, an absolute path, an artefact
    URL, a file size or an upload time. A later phase that adds a volatile field
    to :class:`DependencyInventory` cannot thereby change a fingerprint, because
    the field has nowhere to go here and :func:`dependency_fingerprint` accepts
    nothing else.

    It also deliberately omits two fields the inventory *does* carry.
    ``lock_version`` and ``unknown_keys`` are facts about the document's
    producer, not about which dependencies this environment has, and a lock
    regenerated by a newer pip that changed neither a name nor a version should
    fingerprint identically.
    """

    observations: tuple[DependencyObservation, ...]
    lock_state: LockState

    def canonical(self) -> str:
        """Render this projection as the exact text the digest is taken over.

        Returns:
            A deterministic, sorted, newline-delimited rendering.

        Sorted by name rather than left in lock order, so that a relock which
        reorders ``[[packages]]`` does not move the fingerprint of an
        environment that did not change.
        """
        lines = [FINGERPRINT_SCHEMA]
        lines.extend(
            SEPARATOR.join(
                (
                    observation.name,
                    observation.state.value,
                    observation.locked_version,
                    observation.installed_version,
                )
            )
            for observation in sorted(self.observations)
        )
        lines.append(self.lock_state.value)
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class DependencyInventory:
    """The whole of what GLOBIN knows about the dependencies it is running on.

    Args:
        observations: One per distribution the lock names or the project
            declares.
        lock_state: What the reader made of the document.
        lock_version: The ``lock-version`` string, when one was read.
        unknown_keys: Keys the reader did not recognise, sorted and
            de-duplicated.
    """

    observations: tuple[DependencyObservation, ...]
    lock_state: LockState
    lock_version: str = ""
    unknown_keys: tuple[str, ...] = ()

    def projection(self) -> DependencyProjection:
        """The stable part of this inventory.

        Returns:
            A projection carrying the observations and the lock state, and
            nothing that could move without the environment moving.
        """
        return DependencyProjection(observations=self.observations, lock_state=self.lock_state)

    def unsatisfied(self) -> tuple[DependencyObservation, ...]:
        """Every observation that represents a real divergence.

        Returns:
            Those in :attr:`DependencyState.MISSING`,
            :attr:`DependencyState.VERSION_MISMATCH` or
            :attr:`DependencyState.UNLOCKED`, sorted by name.

        :attr:`DependencyState.NOT_APPLICABLE` is excluded deliberately: it is
        an answer, not a shortfall.
        """
        divergent = (
            DependencyState.MISSING,
            DependencyState.VERSION_MISMATCH,
            DependencyState.UNLOCKED,
        )
        return tuple(
            sorted(
                observation for observation in self.observations if observation.state in divergent
            )
        )

    def as_record(self) -> dict[str, object]:
        """Render as ordinary data for an evidence document.

        Returns:
            A mapping carrying the fingerprint, the lock state and every
            observation. No path and no URL appears, because none is held.
        """
        return {
            "fingerprint": dependency_fingerprint(self.projection()),
            "lock_state": self.lock_state.value,
            "lock_version": self.lock_version,
            "unknown_keys": list(self.unknown_keys),
            "observations": [observation.as_record() for observation in sorted(self.observations)],
            "unsatisfied": [observation.name for observation in self.unsatisfied()],
        }


@dataclass(frozen=True, slots=True, order=True)
class LockedEntry:
    """One package as a lock states it, before any judgement is applied.

    Args:
        name: The canonicalised, PEP 503 name.
        version: The version the lock names, or empty for a source tree.
        marker: The PEP 508 environment marker, or empty when there is none.
        requires_python: The per-package specifier, or empty when there is none.

    Deliberately four fields. A lock entry carries considerably more -- artefact
    URLs, hashes, sizes, upload times, index provenance -- and none of it is a
    fact about *which dependencies this environment has*. What is needed to
    decide that is the name, the version, and the two things that can exclude
    the entry from this environment entirely.
    """

    name: str
    version: str = ""
    marker: str = ""
    requires_python: str = ""


@dataclass(frozen=True, slots=True)
class LockReading:
    """What a reader made of one lock document, including the ways it failed.

    Args:
        state: The outcome. Only :attr:`LockState.PRESENT` and
            :attr:`LockState.NEWER_MINOR` carry entries.
        lock_version: The ``lock-version`` string, when one was read.
        entries: Every package the document names.
        unknown_keys: Keys the reader did not recognise.
        requires_python: The document's own ``requires-python``, when present.
    """

    state: LockState
    lock_version: str = ""
    entries: tuple[LockedEntry, ...] = ()
    unknown_keys: tuple[str, ...] = ()
    requires_python: str = ""


def canonical_name(name: str) -> str:
    """Normalise a distribution name to its PEP 503 form.

    Args:
        name: A distribution name in any spelling.

    Returns:
        The canonical form: lowercase, with runs of ``-``, ``_`` and ``.``
        collapsed to a single ``-``.

    Delegates to ``packaging.utils.canonicalize_name`` rather than
    reimplementing the substitution. Phase 029 adopted the library precisely so
    that this repository stops carrying its own spelling of the packaging
    specifications; a second implementation here would be the first to drift.
    """
    return str(canonicalize_name(name))


def requirement_name(requirement: str) -> str:
    """Extract the canonical distribution name from a PEP 508 requirement.

    Args:
        requirement: A requirement as ``project.dependencies`` spells it, such
            as ``numpy>=2.5.2``.

    Returns:
        The canonicalised name, or the empty string when it cannot be parsed.

    The predecessor of this function split on eight separator characters, and
    its own docstring said it "must not become" a requirement parser, "because
    the moment it needs to be right about markers it needs ``packaging`` and the
    zero-dependency invariant is gone". Phase 029 spent that invariant
    deliberately, so this is the parser that comment predicted.

    An unparseable requirement returns empty rather than raising. A malformed
    ``pyproject.toml`` is a real possibility on somebody's machine, and a
    start-up check that raised on it would report a crash where it should report
    a refusal with a remedy.
    """
    try:
        return canonical_name(Requirement(requirement).name)
    except InvalidRequirement:
        return ""


def versions_agree(locked: str, installed: str) -> bool:
    """Decide whether an installed version is the release the lock names.

    Args:
        locked: The version the lock records.
        installed: The version the environment reports.

    Returns:
        Whether they are the same release.

    Compared as PEP 440 versions rather than as strings, so ``1.0`` and ``1.0.0``
    agree -- they are two spellings of one release, and reporting a mismatch
    would send somebody to reinstall an environment that is already correct.

    **The gate compares these as raw strings, and the asymmetry is deliberate
    rather than drift.** ``tools/quality/lock`` asks whether the committed file's
    *text* describes this environment; this asks whether the *release* is the
    same. A contract test pins the direction -- what this accepts is a superset
    of what the gate accepts -- so the two cannot silently invert.

    Either side being empty is a disagreement: an absent version is not a
    version that matches. An unparseable version on either side falls back to a
    stripped string comparison, because refusing to answer would turn a legible
    mismatch into an exception.
    """
    if not locked or not installed:
        return False
    try:
        return Version(locked) == Version(installed)
    except InvalidVersion:
        return locked.strip() == installed.strip()


def admits_python(specifier: str, python_version: str) -> bool:
    """Decide whether a ``requires-python`` specifier admits an interpreter.

    Args:
        specifier: A PEP 440 specifier set, or empty.
        python_version: The interpreter's version.

    Returns:
        Whether the interpreter is admitted. An empty specifier admits
        everything, and an unparseable one also admits everything.

    An unparseable specifier admits rather than excludes, and that direction is
    chosen rather than defaulted. Excluding would silently drop a package out of
    the inventory and report nothing about it; admitting keeps it visible, so a
    genuine absence is still reported as :attr:`DependencyState.MISSING` and
    somebody sees it.

    ``prereleases=True`` because a lock resolved against a pre-release
    interpreter must still be comparable against it. The alternative reports
    every package as excluded on an alpha build, which is the answer nobody
    wants on the machine where it matters most.
    """
    if not specifier:
        return True
    try:
        return SpecifierSet(specifier).contains(python_version, prereleases=True)
    except (InvalidSpecifier, InvalidVersion):
        return True


def applies_here(
    entry: LockedEntry,
    environment: Mapping[str, str],
    python_version: str,
) -> bool:
    """Decide whether a locked entry is meant to be installed here.

    Args:
        entry: The entry as the lock states it.
        environment: The PEP 508 marker environment, supplied by the caller.
        python_version: The interpreter's full version.

    Returns:
        Whether both the marker and the per-package ``requires-python`` admit
        this environment.

    **The marker environment is an argument and is never read here.**
    ``Marker.evaluate()`` with no argument reads :mod:`platform` and :mod:`sys`,
    which is exactly the observation a domain module may not perform;
    ``tests/architecture/test_packaging_discipline.py`` refuses the no-argument
    form anywhere under the package. Being handed the environment is also what
    makes an ARM64 host, a Linux marker and a free-threaded build testable from
    literals on this machine.

    An unparseable marker admits, for the reason :func:`admits_python` gives.
    """
    if not admits_python(entry.requires_python, python_version):
        return False
    if not entry.marker:
        return True
    try:
        return bool(Marker(entry.marker).evaluate(dict(environment)))
    except InvalidMarker:
        return True


def inventory_from(
    *,
    declared: Sequence[str],
    reading: LockReading,
    installed: Mapping[str, str],
    environment: Mapping[str, str],
    python_version: str,
) -> DependencyInventory:
    """Compare what is declared, what is locked and what is installed.

    Args:
        declared: The PEP 508 requirement strings ``project.dependencies`` holds.
        reading: What a reader made of the lock document.
        installed: Canonicalised distribution name to installed version.
        environment: The PEP 508 marker environment.
        python_version: The interpreter's full version.

    Returns:
        An inventory carrying one observation per distribution.

    The comparison is one-directional on purpose. Every locked entry is
    classified, and every declared root the lock does not name is reported
    :attr:`DependencyState.UNLOCKED` -- but an *installed* distribution that is
    neither declared nor locked is **not reported at all**.

    That omission is the interesting one, and it is a capability limit rather
    than an oversight. Deciding an extra distribution is unexpected needs the
    seeded-package exemption list, which lives in
    ``docs/engineering/lock-policy.toml`` -- a file not shipped inside the wheel.
    Without it, ``pip``, ``setuptools`` and GLOBIN itself would all report as
    surplus on every start-up. ``tools/quality/lock`` already answers this
    correctly in the one place the declaration is readable, and answering it
    badly here would be worse than not answering it.

    A reading that carries no usable entries short-circuits: with no lock there
    is nothing to compare against, and reporting every declared root as
    :attr:`DependencyState.UNLOCKED` would drown the real finding, which is the
    lock state itself.
    """
    unusable = (LockState.ABSENT, LockState.UNREADABLE, LockState.UNSUPPORTED)
    if reading.state in unusable:
        return DependencyInventory(
            observations=(),
            lock_state=reading.state,
            lock_version=reading.lock_version,
            unknown_keys=reading.unknown_keys,
        )

    if not admits_python(reading.requires_python, python_version):
        return DependencyInventory(
            observations=(),
            lock_state=LockState.INTERPRETER_EXCLUDED,
            lock_version=reading.lock_version,
            unknown_keys=reading.unknown_keys,
        )

    observations: list[DependencyObservation] = []
    seen: set[str] = set()

    for entry in reading.entries:
        seen.add(entry.name)
        present = installed.get(entry.name, "")
        if not applies_here(entry, environment, python_version):
            state = DependencyState.NOT_APPLICABLE
        elif not present:
            state = DependencyState.MISSING
        elif versions_agree(entry.version, present):
            state = DependencyState.SATISFIED
        else:
            state = DependencyState.VERSION_MISMATCH
        observations.append(
            DependencyObservation(
                name=entry.name,
                state=state,
                locked_version=entry.version,
                installed_version=present,
            )
        )

    for requirement in declared:
        name = requirement_name(requirement)
        if not name or name in seen:
            continue
        seen.add(name)
        observations.append(
            DependencyObservation(
                name=name,
                state=DependencyState.UNLOCKED,
                locked_version="",
                installed_version=installed.get(name, ""),
            )
        )

    return DependencyInventory(
        observations=tuple(sorted(observations)),
        lock_state=reading.state,
        lock_version=reading.lock_version,
        unknown_keys=reading.unknown_keys,
    )


def dependency_fingerprint(projection: DependencyProjection) -> str:
    """Digest a projection into a stable identifier.

    Args:
        projection: The stable part of an inventory.

    Returns:
        The first :data:`FINGERPRINT_LENGTH` hexadecimal characters of the
        SHA-256 of the canonical rendering.

    Two start-ups on an unchanged environment produce the same value; one after
    a dependency was upgraded, removed or fell out of the lock produces a
    different one. One after the lock was regenerated by a newer producer, with
    no package changed, produces the same one -- not because the producer is
    filtered out but because :class:`DependencyProjection` cannot carry it.

    SHA-256 and thirty-two characters, matching
    :func:`globin.domain.environment.compatibility_fingerprint`. A second
    algorithm or a second length would be a second thing to reason about for no
    gain, and these two values are read side by side.
    """
    digest = hashlib.sha256(projection.canonical().encode("utf-8")).hexdigest()
    return digest[:FINGERPRINT_LENGTH]
