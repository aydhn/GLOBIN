"""The mutable runtime tree, the lifecycle record, and what makes each unsafe.

Where a running GLOBIN keeps state that outlives a function call, expressed as
rules rather than as paths. Every function here is handed facts and returns a
verdict about them, so a boundary violation can be described without creating one
and an unclean previous run can be judged without crashing a process first.

**Nothing here is a** :class:`~pathlib.Path`, and that is not a limitation being
worked around. ``docs/architecture/dependency-rules.toml`` lists ``pathlib`` among
the I/O-capable modules and the domain may import none of them, so this module
declares *relative segments* and :mod:`globin.adapters.runtime_state` is the only
thing that ever joins one to a root. The constraint is the better design for the
same reason it was in Phase 021: a path that does not exist here cannot escape
into the evidence by being forgotten.

**Four areas, and the difference between them is a promise about deletion.**

* ``state`` holds small, long-lived operational metadata. Deleting it loses
  diagnostics and nothing else — GLOBIN starts clean.
* ``cache`` holds data GLOBIN can regenerate. Deleting it must change **no**
  answer; a component that cannot honour that needs ``state``.
* ``run`` holds the live instance's lock and metadata. Safe to delete only while
  nothing is running.
* ``tmp`` holds one subdirectory per run, owned by that run.

**No secret, no credential and no bulk data ever goes in any of them.**
``docs/engineering/RUNTIME_FILESYSTEM.md`` says so where an operator reads it, and
ADR-0059 records why: this tree is small, non-secret and disposable, and the
moment it stops being any of those the properties everything else assumes stop
holding.

What this module deliberately does not decide: how a lock is taken (that needs the
operating system, so it is the adapter's), what a profile is (Phase 026), where
configuration files live (Phase 026), which sources set a value (Phase 027), and
everything about supervising subsystems, draining work in flight or recovering
trading state — Phases 257 to 270, none of which this anticipates.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.domain.bootstrap import CheckOutcome, CheckStatus, RecordedPath
from globin.errors import ConfigurationError, ValidationError

LIFECYCLE_SCHEMA_VERSION: Final[int] = 1
"""The shape of the lifecycle record.

Versioned from its first commit. A record written by a later GLOBIN and read by an
earlier one must be refused rather than misread, and a version field added after
the fact cannot describe the documents written before it.
"""

INSTANCE_SCHEMA_VERSION: Final[int] = 1
"""The shape of the instance metadata, versioned for the same reason."""

LOCK_FILE: Final[str] = "instance.lock"
"""The file whose *lock*, never whose existence, decides ownership."""

INSTANCE_FILE: Final[str] = "instance.json"
"""Where the active instance describes itself, inside the run area."""

LIFECYCLE_FILE: Final[str] = "lifecycle.json"
"""Where the last run's outcome is recorded, inside the state area."""

TRAVERSAL: Final[str] = ".."
"""The segment that would climb out of the tree."""

SEPARATORS: Final[str] = "/\\"
"""Both path separators Windows accepts, refused inside a single segment."""


class RuntimePersistenceError(ConfigurationError):
    """A small state document could not be published, or could not be read back.

    A :class:`~globin.errors.ConfigurationError` rather than a validation one: the
    caller did nothing wrong, and what must change is the machine. Its taxonomy
    docstring fits exactly — "nothing about the request was wrong; the environment
    it ran in was".

    **The previous document is intact whenever this is raised.** That is a
    guarantee of the writer rather than of this class, and it is the reason a
    failed publication is recoverable: the last thing that was successfully
    written is still there to read.
    """


class InstanceAlreadyActiveError(ConfigurationError):
    """Another GLOBIN coordinator already holds the lock on this machine.

    Also a :class:`~globin.errors.ConfigurationError`, for the same reason: the
    operator must act on the environment — stop the running instance — and no
    retry can help while it is up.

    **This is raised on a failed acquisition, never on the presence of a file.**
    A crashed process leaves its lock file behind; only the operating system knows
    whether anything is holding the region.
    """


class RuntimeArea(StrEnum):
    """The five directories of the mutable runtime tree.

    A closed set rather than free-form names, so a component asking for somewhere
    to write has to answer the question the enumeration poses: may this be deleted,
    and when.
    """

    STATE = "state"
    CACHE = "cache"
    RUN = "run"
    TMP = "tmp"

    LOGS = "logs"
    """Diagnostic records of what this installation did, newest first.

    Added by Phase 023, and the only area whose contents are *appended* rather
    than published whole. Every other area holds small documents written through
    :meth:`~globin.ports.runtime_state.StateStore.publish`, which replaces a file
    atomically; a log is the one thing GLOBIN writes that grows.

    That makes it the area ADR-0059 warned about — "a later phase writing
    something large into ``state/`` because the directory was already there" — so
    it is bounded rather than trusted. A sink here rotates at a declared size and
    keeps a declared number of files, and the two together are a hard ceiling on
    what this directory can ever cost. It is separate from ``state`` precisely so
    that the bound applies to the growing thing and not to the small ones.

    It is deletable. Deleting it loses the record of what happened and nothing
    else; no decision GLOBIN makes reads from here.
    """


class LifecycleStatus(StrEnum):
    """What the last run was doing when its record was last written.

    ``UNCLEAN`` is never *written* by a process — it is what a reader concludes
    when it finds ``RUNNING`` in a record no live process is holding a lock for.
    Writing it would require the crashed process to have survived its own crash.
    """

    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    UNCLEAN = "unclean"


class ShutdownReason(StrEnum):
    """Why a run ended, when it ended in a way it could record.

    ``SIGNALLED`` and ``INTERRUPTED`` are separate because they arrive by
    different routes and an operator reading the record wants to know which:
    ``INTERRUPTED`` is a keyboard interrupt in a foreground session, ``SIGNALLED``
    is a termination request from something else.
    """

    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    SIGNALLED = "signalled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RuntimeLayout:
    """The mutable tree, declared as segments relative to a user-local root.

    Args:
        namespace: The directory under the platform's per-user application data
            that GLOBIN owns. Everything else hangs off it.
        state: Small, long-lived operational metadata.
        cache: Reproducible data that may be deleted at any time.
        run: The live instance's lock and metadata.
        tmp: Per-run scratch space.
        logs: Bounded diagnostic records. The only area that is appended to.

    Raises:
        ValidationError: If any segment could leave the tree.

    Every field is a single segment, validated on construction. A layout that
    could escape its own root cannot be built, so the adapter never has to hold a
    value it must then refuse.
    """

    namespace: str = "GLOBIN"
    state: str = "state"
    cache: str = "cache"
    run: str = "run"
    tmp: str = "tmp"
    logs: str = "logs"

    def __post_init__(self) -> None:
        """Refuse any segment that is not a plain directory name."""
        problems = [
            problem
            for name, segment in self.declared().items()
            for problem in segment_problems(segment, named=name)
        ]
        if problems:
            raise ValidationError("; ".join(problems))

    def declared(self) -> dict[str, str]:
        """Every declared segment, by field name.

        Returns:
            Field name to segment.
        """
        return {
            "namespace": self.namespace,
            "state": self.state,
            "cache": self.cache,
            "run": self.run,
            "tmp": self.tmp,
            "logs": self.logs,
        }

    def segment_for(self, area: RuntimeArea) -> str:
        """The segment one area lives in.

        Args:
            area: Which area.

        Returns:
            Its single relative segment.
        """
        return {
            RuntimeArea.STATE: self.state,
            RuntimeArea.CACHE: self.cache,
            RuntimeArea.RUN: self.run,
            RuntimeArea.TMP: self.tmp,
            RuntimeArea.LOGS: self.logs,
        }[area]

    def areas(self) -> tuple[RuntimeArea, ...]:
        """Every area, in a fixed order.

        Returns:
            The five areas. Fixed rather than sorted at the call site, so two runs
            report their problems in the same order and a manifest built from them
            is deterministic.
        """
        return (
            RuntimeArea.STATE,
            RuntimeArea.CACHE,
            RuntimeArea.RUN,
            RuntimeArea.TMP,
            RuntimeArea.LOGS,
        )


def segment_problems(segment: str, *, named: str) -> tuple[str, ...]:
    """Judge whether one segment is a plain directory name.

    Args:
        segment: The candidate.
        named: What to call it in a message.

    Returns:
        One sentence per reason it is not, empty when it is safe.

    Four refusals, and each is a real route out of the tree rather than a
    hypothetical one. ``..`` climbs; a separator smuggles a second level past a
    check that only looked at one; a drive letter or a leading separator makes the
    "relative" segment absolute, which wins the join outright and lands the tree
    wherever the string said; an empty segment collapses to the parent.
    """
    problems: list[str] = []
    if not segment:
        problems.append(f"the {named} segment is empty, which resolves to its parent")
        return tuple(problems)
    if segment == TRAVERSAL or segment.strip() == TRAVERSAL:
        problems.append(f"the {named} segment is {TRAVERSAL!r}, which leaves the tree")
    if any(separator in segment for separator in SEPARATORS):
        problems.append(f"the {named} segment {segment!r} contains a path separator")
    if ":" in segment:
        problems.append(f"the {named} segment {segment!r} names a drive, so it is absolute")
    return tuple(problems)


def child_problems(child: str, *, area: RuntimeArea) -> tuple[str, ...]:
    """Judge whether a name may be joined inside an area.

    Args:
        child: The candidate file or directory name.
        area: Which area it would go in, for the message.

    Returns:
        One sentence per reason it may not be, empty when it is safe.

    The same rules as :func:`segment_problems`, applied at the point a caller
    supplies a name rather than at construction. This is the check that stands
    between "write the lifecycle record" and a caller who computed the filename
    from something it read.
    """
    return segment_problems(child, named=f"{area.value} entry")


@dataclass(frozen=True, slots=True)
class InstanceMetadata:
    """What the process holding the coordinator lock says about itself.

    Args:
        schema_version: The shape of this record.
        version: The GLOBIN version running.
        pid: The operating-system process identifier.
        instance_id: This run's identifier.
        started_at: When it started, as an ISO-8601 UTC instant.
        profile: The resolved configuration profile's name.
        root: Where the runtime tree is, recorded rather than spelled out.

    Raises:
        ValidationError: If the identifier or the process id is not usable.

    **Nothing here is a secret and nothing here is a path.** No credential, no
    resolved reference, no environment dump and no configuration dump. The root is
    a :class:`~globin.domain.bootstrap.RecordedPath`, which cannot carry an
    absolute spelling — the tree lives under a user profile, and a user profile
    directory names its owner.
    """

    version: str
    pid: int
    instance_id: str
    started_at: str
    profile: str
    root: RecordedPath
    schema_version: int = INSTANCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Refuse a record that could not identify the process it describes."""
        if not self.instance_id:
            msg = "instance metadata needs an identifier, and this one is empty"
            raise ValidationError(msg)
        if self.pid <= 0:
            msg = f"instance metadata carries pid {self.pid}, which is not a process"
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This metadata as the document that is published.

        Returns:
            Every field, with the root in its recorded form.
        """
        return {
            "schema_version": self.schema_version,
            "version": self.version,
            "pid": self.pid,
            "instance_id": self.instance_id,
            "started_at": self.started_at,
            "profile": self.profile,
            "root": self.root.as_record(),
        }


@dataclass(frozen=True, slots=True)
class LifecycleRecord:
    """What one run of GLOBIN was doing, and how it ended if it did.

    Args:
        status: What the run was doing when this was last written.
        instance_id: Which run this is.
        pid: The process that wrote it.
        started_at: When the run started, as an ISO-8601 UTC instant.
        finished_at: When it ended, or ``None`` while it is still running.
        reason: Why it ended, or ``None`` while it is still running.
        exit_code: The code it returned, or ``None`` while it is still running.
        schema_version: The shape of this record.

    Raises:
        ValidationError: If the three closing fields do not agree with the status.

    **A closed record and an open one are different shapes, and the type enforces
    it.** A record saying ``STOPPED`` with no finishing time would be a run that
    ended at no particular moment; one saying ``RUNNING`` with an exit code would
    be a process that returned and kept going. Both are unrepresentable.
    """

    status: LifecycleStatus
    instance_id: str
    pid: int
    started_at: str
    finished_at: str | None = None
    reason: ShutdownReason | None = None
    exit_code: int | None = None
    schema_version: int = LIFECYCLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Refuse a record whose closing fields disagree with its status."""
        if not self.instance_id:
            msg = "a lifecycle record needs an identifier, and this one is empty"
            raise ValidationError(msg)
        closed = self.status is LifecycleStatus.STOPPED
        present = self.finished_at is not None
        if closed is not present:
            msg = (
                f"a {self.status.value} record {'needs' if closed else 'carries'} no finishing time"
            )
            raise ValidationError(msg)
        if closed and self.reason is None:
            msg = "a stopped record must say why it stopped"
            raise ValidationError(msg)
        if not closed and self.exit_code is not None:
            msg = f"a {self.status.value} record carries an exit code, so it did not stop"
            raise ValidationError(msg)

    @property
    def ended_cleanly(self) -> bool:
        """Whether this record describes a run that closed itself."""
        return self.status is LifecycleStatus.STOPPED

    def as_record(self) -> dict[str, object]:
        """This record as the document that is published.

        Returns:
            Every field, with the two enumerations as their values.
        """
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "instance_id": self.instance_id,
            "pid": self.pid,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "reason": None if self.reason is None else self.reason.value,
            "exit_code": self.exit_code,
        }


def read_lifecycle(document: object) -> LifecycleRecord:
    """Read a lifecycle record back, refusing anything that is not one.

    Args:
        document: The parsed document.

    Returns:
        The record.

    Raises:
        ValidationError: If it is not an object, announces another schema version,
            or carries a field of the wrong type or an unknown value.

    A record from a future GLOBIN is **refused rather than read anyway**. Guessing
    at a shape somebody else defined is how a reader ends up confidently reporting
    the wrong thing about a run it did not understand.
    """
    if not isinstance(document, dict):
        msg = f"a lifecycle record must be an object, and this is a {type(document).__name__}"
        raise ValidationError(msg)
    version = document.get("schema_version")
    if version != LIFECYCLE_SCHEMA_VERSION:
        msg = (
            f"the lifecycle record announces schema version {version!r}, "
            f"and this GLOBIN implements {LIFECYCLE_SCHEMA_VERSION}"
        )
        raise ValidationError(msg)
    return LifecycleRecord(
        status=_member(LifecycleStatus, document.get("status"), field="status"),
        instance_id=_text(document, "instance_id"),
        pid=_integer(document, "pid"),
        started_at=_text(document, "started_at"),
        finished_at=_optional_text(document, "finished_at"),
        reason=(
            None
            if document.get("reason") is None
            else _member(ShutdownReason, document.get("reason"), field="reason")
        ),
        exit_code=_optional_integer(document, "exit_code"),
    )


def _member[MemberT: StrEnum](enumeration: type[MemberT], value: object, *, field: str) -> MemberT:
    """One enumeration member, read from a published value.

    Args:
        enumeration: The enumeration.
        value: What the document carried.
        field: The field name, for the message.

    Returns:
        The member.

    Raises:
        ValidationError: If the value names no member.
    """
    for member in enumeration:
        if member.value == value:
            return member
    permitted = [member.value for member in enumeration]
    msg = f"the lifecycle record's {field} is {value!r}; expected one of {permitted}"
    raise ValidationError(msg)


def _text(document: dict[str, object], key: str) -> str:
    """One required string field.

    Args:
        document: The parsed record.
        key: The field name.

    Returns:
        The value.

    Raises:
        ValidationError: If it is missing or is not a string.
    """
    value = document.get(key)
    if not isinstance(value, str):
        msg = f"the lifecycle record's {key} is {value!r}; expected a string"
        raise ValidationError(msg)
    return value


def _optional_text(document: dict[str, object], key: str) -> str | None:
    """One optional string field.

    Args:
        document: The parsed record.
        key: The field name.

    Returns:
        The value, or ``None`` when the record carries none.

    Raises:
        ValidationError: If it is present and is not a string.
    """
    value = document.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"the lifecycle record's {key} is {value!r}; expected a string or nothing"
        raise ValidationError(msg)
    return value


def _integer(document: dict[str, object], key: str) -> int:
    """One required integer field.

    Args:
        document: The parsed record.
        key: The field name.

    Returns:
        The value.

    Raises:
        ValidationError: If it is missing, is not an integer, or is a boolean —
            which Python makes an integer, so ``pid = true`` would otherwise read
            as process one.
    """
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"the lifecycle record's {key} is {value!r}; expected an integer"
        raise ValidationError(msg)
    return value


def _optional_integer(document: dict[str, object], key: str) -> int | None:
    """One optional integer field.

    Args:
        document: The parsed record.
        key: The field name.

    Returns:
        The value, or ``None`` when the record carries none.

    Raises:
        ValidationError: If it is present and is not an integer.
    """
    if document.get(key) is None:
        return None
    return _integer(document, key)


# ---------------------------------------------------------------------------
# The judgements. Each takes facts and returns an outcome; none reads anything.
# ---------------------------------------------------------------------------


def boundary_outcome(problems: Sequence[str], layout: RuntimeLayout) -> CheckOutcome:
    """Judge whether the runtime tree is where it claims to be.

    Args:
        problems: One sentence per area that could not be resolved safely.
        layout: The declared layout, for the passing summary.

    Returns:
        The outcome of ``paths.boundary``.
    """
    if problems:
        return CheckOutcome(
            identifier="paths.boundary",
            status=CheckStatus.FAIL,
            summary="; ".join(problems),
            remediation=(
                "GLOBIN refuses to write outside the runtime root it resolved. "
                "docs/engineering/RUNTIME_FILESYSTEM.md names the tree and how it is found."
            ),
        )
    return CheckOutcome(
        identifier="paths.boundary",
        status=CheckStatus.PASS,
        summary=f"{len(layout.areas())} areas resolve inside the runtime root",
    )


def persistence_outcome(problem: str) -> CheckOutcome:
    """Judge whether a small state document can be published atomically.

    Args:
        problem: What went wrong, or the empty string when nothing did.

    Returns:
        The outcome of ``state.persistence``.

    Probed by writing and removing a real document rather than by inspecting
    permissions. A directory that reports itself writable and then refuses
    ``os.replace`` is exactly the case an inspection misses.
    """
    if problem:
        return CheckOutcome(
            identifier="state.persistence",
            status=CheckStatus.FAIL,
            summary=problem,
            remediation=(
                "GLOBIN publishes state by writing a temporary file beside the destination "
                "and replacing it. Make the runtime state directory writable."
            ),
        )
    return CheckOutcome(
        identifier="state.persistence",
        status=CheckStatus.PASS,
        summary="a state document was written, replaced and removed",
    )


def previous_run_outcome(record: LifecycleRecord | None, problem: str = "") -> CheckOutcome:
    """Judge what the last run's record says, without inferring a live process.

    Args:
        record: The record that was read, or ``None`` when there was none.
        problem: Why it could not be read, when it could not.

    Returns:
        The outcome of ``state.previous_run``.

    **A record is evidence about a run that ended, never about one that is
    running.** Ownership is the lock's question and only the lock's, so an open
    record produces a warning rather than a refusal — the process that wrote it
    may have died a week ago.
    """
    if problem:
        return CheckOutcome(
            identifier="state.previous_run",
            status=CheckStatus.FAIL,
            summary=problem,
            remediation=(
                "The lifecycle record is unreadable. Delete it to start clean: it is "
                "diagnostic evidence about the previous run and nothing depends on it."
            ),
        )
    if record is None:
        return CheckOutcome(
            identifier="state.previous_run",
            status=CheckStatus.PASS,
            summary="no previous run has been recorded here",
        )
    if not record.ended_cleanly:
        return CheckOutcome(
            identifier="state.previous_run",
            status=CheckStatus.WARN,
            summary=(
                f"the previous run ({record.instance_id}) was still {record.status.value} "
                "when its record was last written, so it may have terminated uncleanly"
            ),
            remediation=(
                "Nothing blocks start-up: whether an instance is running is decided by the "
                "coordinator lock, not by this record. Read it as a diagnostic."
            ),
        )
    return CheckOutcome(
        identifier="state.previous_run",
        status=CheckStatus.PASS,
        summary=f"the previous run ended {record.reason.value if record.reason else 'cleanly'}",
    )


def lock_outcome(*, acquired: bool, problem: str = "") -> CheckOutcome:
    """Judge whether this process could take the coordinator lock.

    Args:
        acquired: Whether a non-blocking acquisition succeeded.
        problem: What the operating system said, when it did not.

    Returns:
        The outcome of ``instance.lock``.

    **The lock file's existence is not consulted, here or anywhere.** A crashed
    process leaves one behind, so a file on disk proves GLOBIN once ran and nothing
    else. What is judged is the result of an acquisition, which the operating
    system releases when the holder exits.
    """
    if not acquired:
        return CheckOutcome(
            identifier="instance.lock",
            status=CheckStatus.FAIL,
            summary=problem or "another GLOBIN coordinator holds the instance lock",
            remediation=(
                "One coordinator runs at a time on one machine. Stop the running GLOBIN, "
                "or wait for it to finish. Do not delete the lock file: it is not what "
                "decides ownership, and removing it would not release anything."
            ),
        )
    return CheckOutcome(
        identifier="instance.lock",
        status=CheckStatus.PASS,
        summary="the coordinator lock is available to this process",
    )
