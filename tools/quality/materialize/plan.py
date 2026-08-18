"""Whether a lock could be materialized from local bytes, with no network.

Pure. Every function here takes values and returns a verdict, so a corrupt cached
wheel, an artefact nobody has fetched and a lock offering only a source
distribution are all testable from literals with nothing on disk.

**The network fallback is unreachable rather than merely un-taken.** This module
imports no networking module at all and takes the cache's contents as an
*argument*, so there is no branch somebody could add that reaches an index. That
is the same construction ``scripts/bootstrap.ps1`` uses when it refuses rather
than falling back, and it is what makes the offline verdict trustworthy: it is
not a promise that the code does not fetch, it is a module that cannot.

**The cache is not a source of trust; the lock is.** A cached artefact is
addressed *by* the digest the lock records -- name, version, algorithm, digest
and filename all participate in the key -- and its bytes are re-hashed before it
is used. A file that hashes to something else is not a cache hit that failed
validation; it is a different file that was never under that key.

**Artefact selection is the reference implementation's**, not this module's.
``packaging.pylock`` performs it, and it is handed **explicit tags** rather than
being allowed to default to ``sys_tags()``. That distinction is load-bearing:
this gate must return the same verdict on a 3.12 runner, a 3.14 runner and a
Linux development box, and defaulting would make it answer "could *this* machine
install it", which is a different question and a machine-specific one.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

WEAK_ALGORITHMS: Final[frozenset[str]] = frozenset({"md5", "sha1", "sha224"})
"""Digests too weak to establish that bytes are the bytes the lock names.

Refused by name here and in ``tools/quality/lock/plan.py``, and refused
regardless of what any policy file permits, so that widening a declaration
cannot widen this. pip's own hash-checking mode excludes the same three.
"""

PREFERRED_ALGORITHM: Final[str] = "sha256"
"""The digest this repository addresses artefacts by."""


class PlanState(StrEnum):
    """Whether the environment a lock describes could be built from local bytes."""

    SATISFIABLE = "satisfiable"
    """Every required artefact is present locally and hashes to what the lock names."""

    INCOMPLETE = "incomplete"
    """At least one required artefact is absent from the cache.

    **Fails rather than fetching.** A cache that reached for a missing artefact
    would be a network client wearing a cache's name, and the offline guarantee
    would be a promise rather than a property.
    """

    CORRUPT = "corrupt"
    """A cached artefact's bytes do not hash to what the lock records.

    The file is **left in place** and its path reported. Deleting the evidence of
    a corruption is how the ability to diagnose it is lost, and re-fetching would
    be the cache quietly becoming a network client.
    """

    INCOMPATIBLE = "incompatible"
    """No artefact the lock offers serves the declared tags."""

    SOURCE_ONLY = "source_only"
    """Only a source distribution is offered, and policy forbids building one."""

    UNHASHED = "unhashed"
    """An artefact carries no digest in a permitted algorithm.

    Distinct from :attr:`CORRUPT`: there is nothing to compare against, so the
    artefact could not be trusted even if its bytes were present.
    """


@dataclass(frozen=True, slots=True, order=True)
class CacheKey:
    """How one artefact is addressed in the wheelhouse.

    Args:
        name: The canonicalised, PEP 503 distribution name.
        version: The version the lock records.
        algorithm: The digest algorithm, lowercase.
        digest: The digest, lowercase hexadecimal.
        filename: The artefact's own filename.

    The filename participates because it carries the PEP 425 platform tags. A
    separate platform field would be a second spelling of what the filename
    already says, and two spellings of one fact is what
    ``SOURCE_OF_TRUTH.md`` calls drift.
    """

    name: str
    version: str
    algorithm: str
    digest: str
    filename: str

    def relative(self) -> str:
        """Where this artefact lives inside the wheelhouse.

        Returns:
            A repository-relative, forward-slashed path.

        Sharded by the digest's first two characters so that a wheelhouse holding
        thousands of artefacts does not put them all in one directory.
        """
        return f"{self.name}/{self.version}/{self.digest[:2]}/{self.filename}"


@dataclass(frozen=True, slots=True, order=True)
class ArtefactPlan:
    """What must be true for one distribution to be installable offline.

    Args:
        name: The canonicalised distribution name.
        state: What is known about it.
        key: How it is addressed, when the lock recorded enough to address it.
        detail: One sentence, when the state needs explaining.
    """

    name: str
    state: PlanState
    key: CacheKey | None = None
    detail: str = ""

    def as_record(self) -> dict[str, object]:
        """Render as ordinary data.

        Returns:
            The name, the state, the cache-relative path and the detail. **No
            URL**, because a manifest is a summary and a lock holds hundreds.
        """
        return {
            "name": self.name,
            "state": self.state.value,
            "path": "" if self.key is None else self.key.relative(),
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class MaterializationPlan:
    """Every distribution a lock names, and whether it could be installed here.

    Args:
        artefacts: One plan per distribution, sorted by name.
        allow_source: Whether policy permits building a source distribution.
    """

    artefacts: tuple[ArtefactPlan, ...]
    allow_source: bool

    def state(self) -> PlanState:
        """The plan's overall verdict.

        Returns:
            The worst state any artefact reached, or
            :attr:`PlanState.SATISFIABLE` when none is worse.

        Ordered by how much they tell an operator rather than alphabetically:
        a corrupt file is the most urgent because it means something on this
        machine is wrong, and an incomplete cache is the least because it means
        only that nothing has been fetched yet.
        """
        severity = (
            PlanState.CORRUPT,
            PlanState.UNHASHED,
            PlanState.INCOMPATIBLE,
            PlanState.SOURCE_ONLY,
            PlanState.INCOMPLETE,
        )
        present = {artefact.state for artefact in self.artefacts}
        for state in severity:
            if state in present:
                return state
        return PlanState.SATISFIABLE

    def unsatisfiable(self) -> tuple[ArtefactPlan, ...]:
        """Every artefact that would stop an offline install.

        Returns:
            Those not in :attr:`PlanState.SATISFIABLE`, sorted by name.
        """
        return tuple(
            sorted(
                artefact
                for artefact in self.artefacts
                if artefact.state is not PlanState.SATISFIABLE
            )
        )

    def as_record(self) -> dict[str, object]:
        """Render as ordinary data.

        Returns:
            The overall state, the policy, and one entry per artefact.
        """
        return {
            "state": self.state().value,
            "allow_source": self.allow_source,
            "artefacts": [artefact.as_record() for artefact in self.artefacts],
        }


def usable_digest(hashes: Sequence[tuple[str, str]]) -> tuple[str, str] | None:
    """Pick a digest strong enough to address an artefact by.

    Args:
        hashes: Algorithm and hexadecimal digest pairs, as the lock records them.

    Returns:
        The preferred pair, or ``None`` when none is usable.

    ``sha256`` is preferred and anything in :data:`WEAK_ALGORITHMS` is refused by
    name. An unrecognised-but-not-weak algorithm is accepted: the specification
    permits any of ``hashlib``'s, and refusing one this repository has not heard
    of would be refusing a stronger digest for being unfamiliar.
    """
    usable = [
        (algorithm.lower(), value.lower())
        for algorithm, value in hashes
        if algorithm.lower() not in WEAK_ALGORITHMS and value
    ]
    if not usable:
        return None
    for algorithm, value in usable:
        if algorithm == PREFERRED_ALGORITHM:
            return (algorithm, value)
    return usable[0]


def cache_key(
    *, name: str, version: str, filename: str, hashes: Sequence[tuple[str, str]]
) -> CacheKey | None:
    """Build the key one artefact is addressed by.

    Args:
        name: The canonicalised distribution name.
        version: The version the lock records.
        filename: The artefact's filename.
        hashes: Its recorded digests.

    Returns:
        The key, or ``None`` when no usable digest was recorded.
    """
    chosen = usable_digest(hashes)
    if chosen is None:
        return None
    algorithm, digest = chosen
    return CacheKey(
        name=name,
        version=version,
        algorithm=algorithm,
        digest=digest,
        filename=filename,
    )


def plan_for(
    selections: Sequence[tuple[str, str, str, Sequence[tuple[str, str]], bool]],
    present: Mapping[str, str],
    *,
    allow_source: bool,
) -> MaterializationPlan:
    """Decide whether every selected artefact could be installed offline.

    Args:
        selections: One tuple per distribution: name, version, filename, hashes,
            and whether the selected artefact is a source distribution. An empty
            filename means the lock offered nothing serving the declared tags.
        present: Cache-relative path to the digest its bytes actually hash to.
            **Supplied by the caller**, because reading the cache is I/O and this
            module performs none.
        allow_source: Whether policy permits building a source distribution.

    Returns:
        The plan.

    The ordering of the checks is the design. Compatibility is decided before
    hashing, because an artefact that does not serve this target is not worth
    hashing; the digest is required before presence, because an artefact with no
    digest could not be trusted even if it were present.
    """
    artefacts: list[ArtefactPlan] = []
    for name, version, filename, hashes, is_source in selections:
        if not filename:
            artefacts.append(
                ArtefactPlan(
                    name=name,
                    state=PlanState.INCOMPATIBLE,
                    detail="the lock offers nothing serving the declared tags",
                )
            )
            continue
        if is_source and not allow_source:
            artefacts.append(
                ArtefactPlan(
                    name=name,
                    state=PlanState.SOURCE_ONLY,
                    detail="only a source distribution is offered, and policy forbids building one",
                )
            )
            continue
        key = cache_key(name=name, version=version, filename=filename, hashes=hashes)
        if key is None:
            artefacts.append(
                ArtefactPlan(
                    name=name,
                    state=PlanState.UNHASHED,
                    detail="no digest in a permitted algorithm, so nothing could be verified",
                )
            )
            continue
        found = present.get(key.relative())
        if found is None:
            artefacts.append(
                ArtefactPlan(
                    name=name,
                    state=PlanState.INCOMPLETE,
                    key=key,
                    detail="not in the wheelhouse",
                )
            )
            continue
        if found.lower() != key.digest:
            artefacts.append(
                ArtefactPlan(
                    name=name,
                    state=PlanState.CORRUPT,
                    key=key,
                    detail="the cached bytes are not the bytes the lock names",
                )
            )
            continue
        artefacts.append(ArtefactPlan(name=name, state=PlanState.SATISFIABLE, key=key))
    return MaterializationPlan(artefacts=tuple(sorted(artefacts)), allow_source=allow_source)


def offline_problems(plan: MaterializationPlan) -> tuple[str, ...]:
    """Every reason this environment could not be built without a network.

    Args:
        plan: What the cache and the lock say about each other.

    Returns:
        One sentence per unsatisfiable artefact, empty when the plan is
        satisfiable.
    """
    return tuple(
        f"{artefact.name}: {artefact.state.value} -- {artefact.detail}"
        for artefact in plan.unsatisfiable()
    )
