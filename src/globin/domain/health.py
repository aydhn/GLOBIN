"""What a running GLOBIN can say about its own condition, as pure domain types.

Phase 021 asked *may this process start*. This asks the different question *how is
it doing now*, and the difference is not cosmetic. A bootstrap check runs once,
before anything exists, and its failure means refuse to start. A health check runs
against a process that is already running, may be asked repeatedly, and its failure
means something an operator should look at — not necessarily something that should
stop the machine. The two vocabularies are therefore separate, and
:class:`~globin.domain.bootstrap.CheckStatus` is deliberately not reused.

**Nothing here measures anything.** Every value arrives from an adapter, because
reading a clock, a process table or a filesystem is I/O and
``docs/architecture/dependency-rules.toml`` permits none of it in this layer. What
lives here is the vocabulary, the ordering, the thresholds' *shape*, and the one
reduction that turns many results into one state.

**A number that was not measured is never zero.** :class:`Availability` exists so
that "this host reports 4 GiB free", "psutil is not installed", "Windows has no
such counter" and "the operating system refused" are four different facts rather
than one number and three zeroes. Getting this wrong is the characteristic failure
of a health surface: a dashboard showing 0% memory used because nothing could read
it looks exactly like a dashboard showing a healthy process, and the second is a
conclusion nobody drew. ADR-0045 made the same rule for platform capabilities, and
this is that rule applied to a measurement rather than to a device.

**Redaction is not optional and not a caller's responsibility.**
:class:`HealthCheckResult` redacts its own details on construction, exactly as
:class:`~globin.domain.observability.LogEvent` does, so there is no way to build one
carrying a credential-shaped field. What that does *not* catch is a secret inside
free text — the redactor matches field names — and
``docs/engineering/RUNTIME_DIAGNOSTICS.md`` already states that limit rather than
implying it is covered.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.domain.clock import Duration, Instant
from globin.domain.observability import redact
from globin.domain.watchdog import WatchdogSummary
from globin.errors import ValidationError

HEALTH_SCHEMA_VERSION: Final[int] = 1
"""The version of the snapshot's own shape.

Bumped when a field is removed or changes meaning, never when one is added. A
consumer that understands version 1 must keep working against a version 1 document
produced by a later GLOBIN, which is what ``docs/SERIALIZATION_POLICY.md`` requires
of every persisted structure.
"""

EVIDENCE_FORMAT_VERSION: Final[int] = 1
"""The version of the evidence envelope the snapshot is published inside.

Separate from :data:`HEALTH_SCHEMA_VERSION` because the two can move
independently: a snapshot's fields may change while the envelope that carries it —
schema name, digest, published path — does not, and vice versa. One version
covering both would force a false bump on whichever half did not move.
"""

MAXIMUM_DETAIL_FIELDS: Final[int] = 16
"""How many structured details one check result may carry.

A bound rather than a convention. Details end up in a support bundle an operator
sends somewhere, and an unbounded map is how a diagnostic quietly becomes a data
export. Sixteen is enough for every check registered below and small enough that
nobody reaches for it as a place to put a payload.
"""

MAXIMUM_SUMMARY_LENGTH: Final[int] = 200
"""How long a check's human-readable summary may be.

Long enough for a sentence naming what was measured and what it was compared
against; short enough that a summary cannot become a smuggled log line.
"""


MINIMUM_THRESHOLD_BYTES: Final[int] = 1_048_576
"""The smallest byte threshold a health setting may carry — 1 MiB.

Below this a threshold is indistinguishable from zero in practice: a disk with a
megabyte free cannot publish a lifecycle record, so a minimum set lower describes a
condition GLOBIN could never operate in and would never warn about.
"""

MAXIMUM_THRESHOLD_BYTES: Final[int] = 1_099_511_627_776
"""The largest byte threshold a health setting may carry — 1 TiB.

A ceiling on the ceiling, for the reason ``RotationPolicy`` has one: a threshold of
an exabyte is not a strict operator, it is a typo, and it makes every check fail
forever without anybody being able to see why from the value.
"""

MINIMUM_BUDGET_MILLIS: Final[int] = 50
"""The smallest time budget a snapshot may be given."""

MAXIMUM_BUDGET_MILLIS: Final[int] = 60_000
"""The largest. A minute is already far past the point where a health command
should have been abandoned rather than waited for."""

MINIMUM_FRAME_DEPTH: Final[int] = 1
"""The shallowest traceback the allocator tracer may retain."""

MAXIMUM_FRAME_DEPTH: Final[int] = 64
"""The deepest.

Each frame is retained for every traced allocation, so the cost is multiplied by
allocation count rather than added once. ``tracemalloc``'s own default is one, and
a depth of sixty-four already turns a diagnostic into something that changes the
behaviour of the process being diagnosed.
"""

MAXIMUM_TOP_SITES: Final[int] = 64
"""The most allocation sites a memory summary may report."""


@dataclass(frozen=True, slots=True)
class HealthThresholds:
    """The bounds a health check compares a measurement against.

    Args:
        minimum_free_bytes: Below this on a runtime filesystem, ``FAIL``.
        disk_warning_bytes: Below this, ``WARN``.
        minimum_available_memory_bytes: Below this on the host, ``FAIL``.
        process_rss_warning_bytes: Above this for this process, ``WARN``.
        budget_millis: How long the whole snapshot may take.

    Raises:
        ValidationError: If a value is outside its declared range, or if the
            warning threshold is not above the failure threshold.

    **The ordering check is the one worth having.** A warning threshold at or below
    the failure threshold produces a check that can never warn: it fails first, and
    the warning band an operator configured has silently zero width. That is a
    misconfiguration nothing else would report, because every individual value is
    in range.
    """

    minimum_free_bytes: int
    disk_warning_bytes: int
    minimum_available_memory_bytes: int
    process_rss_warning_bytes: int
    budget_millis: int

    def __post_init__(self) -> None:
        """Refuse thresholds that are out of range or in the wrong order.

        Raises:
            ValidationError: As described above.
        """
        byte_fields = (
            "minimum_free_bytes",
            "disk_warning_bytes",
            "minimum_available_memory_bytes",
            "process_rss_warning_bytes",
        )
        for name in byte_fields:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                msg = f"{name} is a byte count, and {value!r} is not one"
                raise ValidationError(msg)
            if not MINIMUM_THRESHOLD_BYTES <= value <= MAXIMUM_THRESHOLD_BYTES:
                msg = (
                    f"{name} is between {MINIMUM_THRESHOLD_BYTES} and "
                    f"{MAXIMUM_THRESHOLD_BYTES} bytes, and {value} is not"
                )
                raise ValidationError(msg)
        if self.disk_warning_bytes <= self.minimum_free_bytes:
            msg = (
                f"disk_warning_bytes ({self.disk_warning_bytes}) is not above "
                f"minimum_free_bytes ({self.minimum_free_bytes}), so the check can never warn"
            )
            raise ValidationError(msg)
        if (
            isinstance(self.budget_millis, bool)
            or not MINIMUM_BUDGET_MILLIS <= self.budget_millis <= MAXIMUM_BUDGET_MILLIS
        ):
            msg = (
                f"budget_millis is between {MINIMUM_BUDGET_MILLIS} and "
                f"{MAXIMUM_BUDGET_MILLIS}, and {self.budget_millis!r} is not"
            )
            raise ValidationError(msg)


class HealthSeverity(StrEnum):
    """How a single check turned out.

    Four values rather than three, and the fourth is the one that matters.
    ``UNKNOWN`` is not a polite ``PASS``: it says the question was asked and no
    answer came back, which is a different fact from the answer being good. A
    vocabulary without it forces every unmeasurable check to lie in one direction
    or the other, and both lies are expensive — a false ``PASS`` hides a blind
    spot, and a false ``FAIL`` teaches an operator to ignore the surface.

    **``UNKNOWN`` rather than ``UNMEASURED``, and the difference from
    :class:`~globin.domain.bootstrap.CheckStatus` is deliberate.** A gate is
    ``UNMEASURED`` when it did not run. A health check is ``UNKNOWN`` when it *did*
    run and could not obtain an answer — the probe executed, the library was
    absent, the counter does not exist on this platform. Spelling those the same
    would flatten a distinction an operator acts on: one means *go and look at the
    harness*, the other means *this host cannot answer that question*.
    """

    PASS = "pass"  # noqa: S105 -- a check verdict, not a credential
    """Measured, and within the declared bound."""

    WARN = "warn"
    """Measured, and approaching the declared bound. Nothing is broken yet."""

    FAIL = "fail"
    """Measured, and outside the declared bound. Something needs attention."""

    UNKNOWN = "unknown"
    """Not measured. The reason code says why, and it is never a number."""


class RuntimeHealthState(StrEnum):
    """What the whole snapshot amounts to.

    Three values, deliberately not four: there is no ``UNKNOWN`` aggregate. A
    snapshot that could not be produced at all is not a state, it is an error, and
    it is reported through the exception path rather than by inventing a fourth
    word for it. The distinction is the same one ``BOOTSTRAP.md`` draws between a
    gate that failed and a gate that could not run.
    """

    HEALTHY = "healthy"
    """Every mandatory check passed."""

    DEGRADED = "degraded"
    """Something warned, or something could not be measured. Nothing has failed."""

    UNHEALTHY = "unhealthy"
    """At least one check failed."""


class Availability(StrEnum):
    """Why a measurement is present or absent.

    The four words are not synonyms and the difference between them is
    operationally load-bearing:

    * ``UNAVAILABLE`` is fixable by the operator — install the library, and the
      number appears.
    * ``UNSUPPORTED`` is not fixable at all on this platform, and telling somebody
      to fix it would waste their afternoon.
    * ``DENIED`` is fixable by changing privileges, which is a decision with a
      security cost rather than an installation step.
    * ``MEASURED`` is the only one that carries a number.

    Collapsing them into ``None`` would make all three absences look like the same
    problem, and collapsing them into ``0`` would make them look like an answer.
    """

    MEASURED = "measured"
    """A value was read, and it is in :attr:`Reading.value`."""

    UNAVAILABLE = "unavailable"
    """Nothing on this host could answer, but something could be made to."""

    UNSUPPORTED = "unsupported"
    """This platform has no such counter. Asking again will not help."""

    DENIED = "denied"
    """The operating system refused. The process lacks the privilege."""


REASON_OK: Final[str] = "HEALTH_OK"
"""Nothing to report; the measurement succeeded and cleared its bound."""

REASON_PSUTIL_ABSENT: Final[str] = "HEALTH_PSUTIL_ABSENT"
"""The process probe's library is not installed in this environment."""

REASON_CPU_NOT_SAMPLED: Final[str] = "HEALTH_CPU_NOT_SAMPLED"
"""A one-shot snapshot cannot produce an instantaneous CPU percentage.

psutil documents that the first ``cpu_percent`` call on a process returns a
meaningless ``0.0``, because a percentage is a ratio over an interval and the first
call has no previous reading to be an interval from. A snapshot command takes one
reading and exits, so there is no honest number to report. Cumulative CPU *times*
are reported instead, which is a fact rather than a rate, and the rate is left to
whoever holds two snapshots.
"""

REASON_COUNTER_UNSUPPORTED: Final[str] = "HEALTH_COUNTER_UNSUPPORTED"
"""This platform exposes no such counter."""

REASON_ACCESS_DENIED: Final[str] = "HEALTH_ACCESS_DENIED"
"""The operating system refused the read."""

REASON_PROCESS_GONE: Final[str] = "HEALTH_PROCESS_GONE"
"""The process disappeared between two reads of it."""

REASON_DISK_LOW: Final[str] = "HEALTH_DISK_LOW"
"""Free space on a runtime filesystem is under its warning threshold."""

REASON_DISK_EXHAUSTED: Final[str] = "HEALTH_DISK_EXHAUSTED"
"""Free space on a runtime filesystem is under its minimum."""

REASON_MEMORY_LOW: Final[str] = "HEALTH_MEMORY_LOW"
"""Available host memory is under its minimum."""

REASON_RSS_HIGH: Final[str] = "HEALTH_RSS_HIGH"
"""This process's resident set is over its warning threshold."""

REASON_PATH_MISSING: Final[str] = "HEALTH_PATH_MISSING"
"""A declared runtime directory does not exist."""

REASON_PATH_UNWRITABLE: Final[str] = "HEALTH_PATH_UNWRITABLE"
"""A declared runtime directory exists and cannot be written to."""

REASON_PATH_ESCAPED: Final[str] = "HEALTH_PATH_ESCAPED"
"""A runtime path resolves outside the approved root."""

REASON_LOCK_HELD_ELSEWHERE: Final[str] = "HEALTH_LOCK_HELD_ELSEWHERE"
"""Another process holds the single-instance lock."""

REASON_LOGGING_NOT_RUNNING: Final[str] = "HEALTH_LOGGING_NOT_RUNNING"
"""The diagnostics subsystem is not in its running state."""

REASON_LOGGING_FAULTED: Final[str] = "HEALTH_LOGGING_FAULTED"
"""The diagnostics subsystem recorded a fault of its own."""

REASON_TRACING_DISABLED: Final[str] = "HEALTH_TRACING_DISABLED"
"""Memory tracing is off, which is the default and is not a problem."""

REASON_CHECK_RAISED: Final[str] = "HEALTH_CHECK_RAISED"
"""A check raised rather than returning. The snapshot survived; this says so.

Not a silent swallow. ``ENGINEERING_CONTRACT.md`` invariant 23 forbids discarding
an exception, and nothing here discards one: the failure becomes a result carrying
this code, and the collector reports it through the Phase 023 sinks with the
exception attached. What is refused is the alternative — one probe raising and
taking the whole snapshot with it, so that an operator investigating a disk
problem learns nothing because a thread counter was unhappy.
"""

REASON_BUDGET_EXCEEDED: Final[str] = "HEALTH_BUDGET_EXCEEDED"
"""A check ran longer than the configured budget allowed."""

REASONS: Final[tuple[str, ...]] = (
    REASON_OK,
    REASON_PSUTIL_ABSENT,
    REASON_CPU_NOT_SAMPLED,
    REASON_COUNTER_UNSUPPORTED,
    REASON_ACCESS_DENIED,
    REASON_PROCESS_GONE,
    REASON_DISK_LOW,
    REASON_DISK_EXHAUSTED,
    REASON_MEMORY_LOW,
    REASON_RSS_HIGH,
    REASON_PATH_MISSING,
    REASON_PATH_UNWRITABLE,
    REASON_PATH_ESCAPED,
    REASON_LOCK_HELD_ELSEWHERE,
    REASON_LOGGING_NOT_RUNNING,
    REASON_LOGGING_FAULTED,
    REASON_TRACING_DISABLED,
    REASON_CHECK_RAISED,
    REASON_BUDGET_EXCEEDED,
)
"""Every code a check may carry, as a closed set.

A tuple rather than a ``frozenset``, because ``frozenset({...})`` is a *call* and
``tests/architecture/test_architecture_contract.py`` holds every layer package to
performing no work at import. Membership on twenty strings costs nothing worth
measuring, and the ordering the tuple happens to carry is never relied upon.

Closed for the reason every gate's ``REASONS`` is closed: a consumer that switches
on a code needs the set to be enumerable, and a code invented at a call site is one
nobody can switch on. A test asserts that each of these is reachable from real
code, so the set cannot rot into a list of names nothing produces.
"""


@dataclass(frozen=True, slots=True)
class Reading:
    """One measured quantity, or a stated reason why there is no number.

    Args:
        availability: Whether a value was obtained, and if not, of what kind the
            absence is.
        value: The quantity, present only when ``availability`` is
            :attr:`Availability.MEASURED`.
        unit: What the quantity counts — ``bytes``, ``nanoseconds``, ``count``.
        reason: The code explaining an absence, empty when measured.

    Raises:
        ValidationError: If a measured reading carries no value, if an unmeasured
            one carries a value, or if ``reason`` is not a declared code.

    **The two refusals are the whole point of the type.** A measured reading
    without a number and an unmeasured reading with one are both states that make
    every downstream consumer wrong, and both are cheap to make: a probe that
    returns ``Reading(Availability.MEASURED)`` after an early return, or one that
    reports the last successful value alongside a failure. Refusing at
    construction means neither can travel.
    """

    availability: Availability
    value: int | None = None
    unit: str = "count"
    reason: str = ""

    def __post_init__(self) -> None:
        """Refuse a reading whose availability and value disagree.

        Raises:
            ValidationError: As described above.
        """
        measured = self.availability is Availability.MEASURED
        if measured and self.value is None:
            msg = "a measured reading must carry a value"
            raise ValidationError(msg)
        if not measured and self.value is not None:
            msg = f"a {self.availability} reading must not carry a value, and this carries one"
            raise ValidationError(msg)
        if not measured and self.reason not in REASONS:
            msg = f"an absent reading must name a declared reason, and {self.reason!r} is not one"
            raise ValidationError(msg)
        if isinstance(self.value, bool):
            msg = "a reading's value is a count, and a bool is not one"
            raise ValidationError(msg)

    @property
    def measured(self) -> bool:
        """Whether this reading carries a number.

        Returns:
            ``True`` when a value is present.
        """
        return self.availability is Availability.MEASURED


def measured(value: int, unit: str = "count") -> Reading:
    """Build a reading that carries a number.

    Args:
        value: The quantity.
        unit: What it counts.

    Returns:
        The reading.
    """
    return Reading(Availability.MEASURED, value, unit)


def absent(availability: Availability, reason: str, unit: str = "count") -> Reading:
    """Build a reading that carries a stated absence instead of a number.

    Args:
        availability: Which kind of absence.
        reason: The declared code explaining it.
        unit: What the quantity would have counted.

    Returns:
        The reading.

    Raises:
        ValidationError: If ``availability`` is :attr:`Availability.MEASURED`.
    """
    if availability is Availability.MEASURED:
        msg = "absent() builds an absence; use measured() for a value"
        raise ValidationError(msg)
    return Reading(availability, None, unit, reason)


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    """What one check concluded, and what it was looking at.

    Args:
        identifier: The check's stable identifier, from :func:`checks`.
        severity: How it turned out.
        summary: One human sentence, bounded by :data:`MAXIMUM_SUMMARY_LENGTH`.
        reason: A declared code from :data:`REASONS`.
        details: Structured fields a machine can read, bounded by
            :data:`MAXIMUM_DETAIL_FIELDS` and redacted on construction.
        measured_at: When the check ran, in UTC.
        took: How long it took, from a monotonic clock, or ``None`` when the
            check did not time itself.
        remediation: What an operator should do, empty when there is nothing.

    Raises:
        ValidationError: If the summary or details exceed their bounds, or if
            ``reason`` is not a declared code.

    **The details are redacted here and nowhere else.** A caller cannot forget,
    because there is no unredacted way to build one — the same guarantee
    :class:`~globin.domain.observability.LogEvent` gives, obtained the same way and
    for the same reason. What redaction covers is field *names*; a credential
    inside ``summary`` or inside an exception message reproduced in ``details``
    would survive, and that limit is documented rather than papered over.
    """

    identifier: str
    severity: HealthSeverity
    summary: str
    reason: str = REASON_OK
    details: tuple[tuple[str, object], ...] = ()
    measured_at: Instant | None = None
    took: Duration | None = None
    remediation: str = ""

    def __post_init__(self) -> None:
        """Validate the bounds and redact the details.

        Raises:
            ValidationError: As described above.
        """
        if self.reason not in REASONS:
            msg = f"{self.reason!r} is not a declared health reason code"
            raise ValidationError(msg)
        if len(self.summary) > MAXIMUM_SUMMARY_LENGTH:
            msg = (
                f"a check summary is at most {MAXIMUM_SUMMARY_LENGTH} characters "
                f"and {self.identifier} produced {len(self.summary)}"
            )
            raise ValidationError(msg)
        if len(self.details) > MAXIMUM_DETAIL_FIELDS:
            msg = (
                f"a check carries at most {MAXIMUM_DETAIL_FIELDS} details "
                f"and {self.identifier} carries {len(self.details)}"
            )
            raise ValidationError(msg)
        cleaned = redact(dict(self.details))
        object.__setattr__(self, "details", tuple(sorted(cleaned.items())))


@dataclass(frozen=True, slots=True)
class HealthCheckSpec:
    """One registered check, and what its absence of an answer means.

    Args:
        identifier: The stable identifier a consumer switches on.
        category: The group it belongs to, for grouped rendering.
        tolerates_unknown: Whether this check being unmeasurable is an expected
            state of a healthy system rather than a gap in the picture.

    **The third field is the interesting one, and it exists because of a real
    host.** The CI ``quality`` job installs the development toolchain and never
    builds ``.venv``, so ``psutil`` is genuinely absent there and every
    process-resource check is ``UNKNOWN`` on every run. Without this field the
    aggregate would be ``DEGRADED`` forever on that host, and a state that is
    always amber is a state nobody reads. With it, an unmeasurability that was
    *predicted* is distinguished from one that was not — which is the same
    distinction ``gpu-contract.toml`` draws with ``absence_means``.
    """

    identifier: str
    category: str
    tolerates_unknown: bool = False


AGGREGATE_CHECK: Final[str] = "runtime.healthy"
"""The identifier of the check that answers for all the others."""


def checks() -> tuple[HealthCheckSpec, ...]:
    """Return every registered check, in the order a snapshot performs them.

    Returns:
        One specification per check, in a fixed order.

    A function rather than a constant, for the reason
    :func:`globin.domain.bootstrap.checks` gives about itself: constructing these
    is a call, and a layer package performs none at import.

    **The order is fixed and is part of the contract.** Two snapshots of the same
    process must serialise identically, and a registry that iterated a set would
    make the JSON differ between runs for no reason anybody could act on. It runs
    cheapest-first — identity and platform facts before anything that touches a
    filesystem or a process table — so a snapshot that is cut short by a budget
    still carries the parts that cost nothing.
    """
    return (
        HealthCheckSpec("runtime.identity", "runtime"),
        HealthCheckSpec("runtime.uptime", "runtime"),
        HealthCheckSpec("platform.interpreter", "platform"),
        HealthCheckSpec("process.identity", "process"),
        HealthCheckSpec("process.memory", "process", tolerates_unknown=True),
        HealthCheckSpec("process.cpu", "process", tolerates_unknown=True),
        HealthCheckSpec("process.threads", "process"),
        HealthCheckSpec("process.handles", "process", tolerates_unknown=True),
        HealthCheckSpec("host.cpu", "host"),
        HealthCheckSpec("host.memory", "host", tolerates_unknown=True),
        HealthCheckSpec("host.disk", "host"),
        HealthCheckSpec("paths.present", "paths"),
        HealthCheckSpec("paths.writable", "paths"),
        HealthCheckSpec("paths.boundary", "paths"),
        HealthCheckSpec("instance.lock", "instance"),
        HealthCheckSpec("logging.state", "logging", tolerates_unknown=True),
        HealthCheckSpec("memory.tracing", "memory", tolerates_unknown=True),
        HealthCheckSpec(AGGREGATE_CHECK, "runtime"),
    )


def check_identifiers() -> tuple[str, ...]:
    """Return every check identifier, in registry order.

    Returns:
        The identifiers.
    """
    return tuple(spec.identifier for spec in checks())


def spec_for(identifier: str) -> HealthCheckSpec:
    """Look up a check by its identifier.

    Args:
        identifier: The identifier to find.

    Returns:
        The specification.

    Raises:
        ValidationError: If no check carries that identifier.
    """
    for spec in checks():
        if spec.identifier == identifier:
            return spec
    msg = f"{identifier!r} is not a registered health check"
    raise ValidationError(msg)


@dataclass(frozen=True, slots=True)
class ProcessSummary:
    """What this process is consuming, as far as anything could tell.

    Args:
        pid: The operating-system process identifier.
        resident_bytes: Resident set size.
        virtual_bytes: Virtual memory size, where the platform reports one.
        cpu_user: Cumulative user CPU time.
        cpu_system: Cumulative system CPU time.
        threads: How many operating-system threads the process holds.
        handles: How many kernel handles it holds, a Windows counter.

    Every field is a :class:`Reading`, including the ones that will nearly always
    be present. A summary whose easy fields were plain integers and whose awkward
    ones were readings would invite a caller to treat the two differently, and the
    awkward ones are exactly the ones a caller gets wrong.

    **No instantaneous CPU percentage.** See :data:`REASON_CPU_NOT_SAMPLED`.
    """

    pid: int
    resident_bytes: Reading
    virtual_bytes: Reading
    cpu_user: Reading
    cpu_system: Reading
    threads: Reading
    handles: Reading


@dataclass(frozen=True, slots=True)
class FilesystemReading:
    """Free and total space on one filesystem behind the runtime tree.

    Args:
        anchor: The filesystem's root, as an opaque label rather than a path — a
            bare drive designator such as ``C:``, never the directory underneath
            it. A support bundle carries this, and a drive identifies a filesystem
            without identifying a person; the path beneath it names a user profile
            and therefore names somebody.
        total_bytes: Capacity.
        free_bytes: What is left.
    """

    anchor: str
    total_bytes: Reading
    free_bytes: Reading


@dataclass(frozen=True, slots=True)
class HostSummary:
    """What the machine has, as far as anything could tell.

    Args:
        logical_cpus: How many logical processors the interpreter may use.
        physical_cpus: How many physical cores, where that is knowable.
        total_memory_bytes: Installed physical memory.
        available_memory_bytes: What is left for a new allocation.
        filesystems: One entry per distinct filesystem behind the runtime tree,
            deduplicated by anchor and ordered by it.

    **Deduplicated, and that is a measurement decision rather than tidiness.** The
    five runtime areas normally sit on one drive, so asking each of them
    separately would run five identical syscalls and publish five identical
    answers, inviting a reader to believe five filesystems were checked.
    """

    logical_cpus: Reading
    physical_cpus: Reading
    total_memory_bytes: Reading
    available_memory_bytes: Reading
    filesystems: tuple[FilesystemReading, ...] = ()


@dataclass(frozen=True, slots=True)
class ThreadDescription:
    """One live thread, described without exposing what it is doing.

    Args:
        name: The thread's name, sanitised.
        identifier: Python's own thread identity, where it has one.
        native_identifier: The operating system's, where the platform reports one.
        alive: Whether it was alive when the inventory was taken.
        daemon: Whether the interpreter will exit without waiting for it.
        main: Whether it is the interpreter's main thread.

    **No stack in the health surface**, and the qualifier is load-bearing. A stack
    trace names functions, files and line numbers, and a thread parked inside a
    credential read would say so — and *this* document travels, into a support
    bundle and from there to whoever an operator sends it to. Phase 023's
    ``faulthandler`` already writes stacks, deliberately, into a file that is not
    the log.

    Phase 025 does publish thread stacks, and answers this refusal on its own terms
    rather than overriding it: a stall incident is written to the user-local
    ``state/watchdog.json``, is deliberately **not** a support-bundle candidate, and
    reduces every frame's filename through :func:`~globin.adapters.health.relative_location`
    — the same reduction :class:`AllocationSite` already uses. What crosses into
    this surface from the watchdog is
    :class:`~globin.domain.watchdog.WatchdogSummary`, which is counts and names.
    Reasoning: ADR-0066.
    """

    name: str
    identifier: int | None
    native_identifier: int | None
    alive: bool
    daemon: bool
    main: bool


@dataclass(frozen=True, slots=True)
class ThreadSummary:
    """The live thread inventory.

    Args:
        count: How many threads were alive.
        threads: One description each, ordered so two snapshots of the same
            process serialise identically.
    """

    count: int
    threads: tuple[ThreadDescription, ...] = ()


@dataclass(frozen=True, slots=True)
class AllocationSite:
    """One entry from a memory-tracing top-N.

    Args:
        location: Where the allocation was made, sanitised to a repository- or
            stdlib-relative form. An absolute path names a user's home directory
            and therefore a person.
        size_bytes: How much is currently allocated there.
        count: How many blocks.
    """

    location: str
    size_bytes: int
    count: int


@dataclass(frozen=True, slots=True)
class MemorySummary:
    """What the interpreter's allocator tracer reports, when it is running.

    Args:
        tracing: Whether tracing was on.
        frame_depth: How many frames each traceback retains.
        current_bytes: Currently traced allocation.
        peak_bytes: The high-water mark since tracing began.
        overhead_bytes: What the tracer itself is costing.
        top: The bounded, deterministically ordered top-N.

    **Off by default, and the default is the important part.** ``tracemalloc``
    costs CPU and memory on every allocation in the process, so a runtime that
    enabled it because the field existed would be paying a profiler's price to
    populate a diagnostic nobody asked for. It is enabled by an explicit setting or
    an explicit command, and a snapshot taken without it says ``tracing=False``
    rather than reporting zeroes.
    """

    tracing: bool
    frame_depth: Reading
    current_bytes: Reading
    peak_bytes: Reading
    overhead_bytes: Reading
    top: tuple[AllocationSite, ...] = ()


class LoggingState(StrEnum):
    """Where the diagnostics subsystem is in its own lifecycle.

    Declared here rather than read out of the adapter's internals. A health check
    that inspected private attributes would break the moment somebody refactored
    the thing it was reporting on, and would be reporting an implementation detail
    to an operator who cannot act on it.
    """

    NOT_CONFIGURED = "not_configured"
    """Built and never started. The CLI's read-only commands are here."""

    STARTING = "starting"
    """Opening sinks and installing hooks."""

    RUNNING = "running"
    """Sinks open, hooks installed, records being written."""

    STOPPING = "stopping"
    """Restoring hooks and closing sinks."""

    STOPPED = "stopped"
    """Closed cleanly. Nothing further will be written."""

    FAULTED = "faulted"
    """Something in the subsystem itself failed. The code says what."""


@dataclass(frozen=True, slots=True)
class LoggingSummary:
    """What the diagnostics subsystem will say about itself.

    Args:
        state: Where it is in its lifecycle.
        minimum_severity: The threshold below which records are discarded.
        destination: Where the log is written, as a runtime-relative label rather
            than an absolute path.
        rotation_max_bytes: The size at which the file rotates.
        rotation_backup_count: How many rotated files are kept.
        last_fault: A declared code for the last fault, empty when there was none.

    **No queue contents, and no listener internals.** There is no queue: Phase 023
    writes records synchronously through a sink chain. A summary that reported one
    would be describing an architecture this repository does not have.
    """

    state: LoggingState
    minimum_severity: str
    destination: str
    rotation_max_bytes: Reading
    rotation_backup_count: Reading
    last_fault: str = ""


@dataclass(frozen=True, slots=True)
class PlatformSummary:
    """What is running this, in the terms the runtime contract uses.

    Args:
        implementation: The interpreter implementation.
        python_version: Its version.
        architecture: The processor architecture.
        system: The operating system.
        release: Its release, at the granularity the security baseline permits.

    **No hostname, no user, no home directory and no command line.** Each of those
    identifies a person or a machine, each ends up in a support bundle, and none of
    them is needed to answer a question about health.
    ``docs/engineering/SUPPORT_BUNDLE.md`` lists them among the fields that are
    refused rather than redacted, because a field that is never collected cannot
    leak through a redactor that missed it.
    """

    implementation: str
    python_version: str
    architecture: str
    system: str
    release: str


@dataclass(frozen=True, slots=True)
class LifecycleSummary:
    """What is known about this run and the one before it.

    Args:
        status: The lifecycle status this run published.
        instance_id: This run's identity.
        lock_held: Whether the single-instance lock could be acquired.
        lock_problem: What the operating system said when it could not, empty
            otherwise.
        previous_ended_cleanly: Whether the previous run closed properly, or
            ``None`` when there was no previous run to ask about.

    ``lock_held`` is the result of *acquiring and releasing*, never of looking for
    a file. ADR-0059 is explicit that a lock file's existence proves only that
    GLOBIN once ran, and a diagnostic that concluded otherwise would report a
    crashed predecessor as a running instance.
    """

    status: str
    instance_id: str
    lock_held: bool
    lock_problem: str = ""
    previous_ended_cleanly: bool | None = None


@dataclass(frozen=True, slots=True)
class PathSummary:
    """Whether the runtime tree is in the shape the process needs.

    Args:
        root_present: Whether the runtime root exists.
        areas: One entry per declared area, naming the area and whether it is
            present, a directory, writable and inside the approved root.
    """

    root_present: bool
    areas: tuple[tuple[str, bool, bool, bool, bool], ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeHealthSnapshot:
    """Everything one health measurement produced.

    Args:
        generated_at: When the snapshot was taken, in UTC.
        correlation_id: The identity binding this snapshot to the records the run
            emitted while producing it.
        run_id: The run this belongs to.
        version: GLOBIN's version.
        profile: The active runtime profile.
        config_fingerprint: A digest over the resolved configuration, so two
            snapshots can be compared without publishing what was configured.
        context_fingerprint: The bootstrap's own fingerprint, carried through so a
            snapshot can be tied to the start-up that produced the process.
        uptime: How long the process has been running, from a monotonic clock.
        platform: What is running this.
        process: What the process is consuming.
        host: What the machine has.
        paths: Whether the runtime tree is usable.
        lifecycle: This run and the one before it.
        logging: The diagnostics subsystem.
        threads: The live thread inventory.
        memory: The allocator tracer, present only when it was running.
        watchdog: The liveness watchdog, present only when this process has one.
            ``None`` is a real answer rather than a gap — a short-lived command
            starts no watchdog, and Phase 025 deliberately added no long-running
            one, so today this is ``None`` everywhere the CLI renders a snapshot.
        results: Every check's result, in registry order.
        state: What the results amount to.
        schema_version: The snapshot shape's version.
        evidence_version: The envelope's version.

    Raises:
        ValidationError: If the results are not in registry order, or if a result
            names a check that is not registered.

    **The ordering check is not pedantry.** ``docs/SERIALIZATION_POLICY.md``
    requires a persisted structure to be deterministic, and a snapshot whose
    results arrived in whatever order the collector happened to finish in would
    produce a different document — and therefore a different digest — for an
    identical process. Refusing at construction means the collector cannot get it
    wrong quietly.
    """

    generated_at: Instant
    correlation_id: str
    run_id: str
    version: str
    profile: str
    config_fingerprint: str
    context_fingerprint: str
    uptime: Duration
    platform: PlatformSummary
    process: ProcessSummary
    host: HostSummary
    paths: PathSummary
    lifecycle: LifecycleSummary
    logging: LoggingSummary
    threads: ThreadSummary
    state: RuntimeHealthState
    memory: MemorySummary | None = None
    watchdog: WatchdogSummary | None = None
    results: tuple[HealthCheckResult, ...] = ()
    schema_version: int = HEALTH_SCHEMA_VERSION
    evidence_version: int = EVIDENCE_FORMAT_VERSION

    def __post_init__(self) -> None:
        """Refuse a snapshot whose results are not the registry, in order.

        Raises:
            ValidationError: As described above.
        """
        registered = check_identifiers()
        seen = tuple(result.identifier for result in self.results)
        unknown = [identifier for identifier in seen if identifier not in registered]
        if unknown:
            msg = f"a snapshot carries results for unregistered checks: {sorted(unknown)}"
            raise ValidationError(msg)
        expected = tuple(identifier for identifier in registered if identifier in set(seen))
        if seen != expected:
            msg = (
                "a snapshot's results must be in registry order; "
                f"expected {list(expected)} and got {list(seen)}"
            )
            raise ValidationError(msg)

    def result_for(self, identifier: str) -> HealthCheckResult | None:
        """Look up one check's result.

        Args:
            identifier: The check to find.

        Returns:
            The result, or ``None`` when the snapshot does not carry one.
        """
        for result in self.results:
            if result.identifier == identifier:
                return result
        return None

    def unmeasurable(self) -> tuple[str, ...]:
        """Every check that ran and could not answer, whether tolerated or not.

        Returns:
            The identifiers, in registry order.

        Separate from the aggregate on purpose. :func:`aggregate_state` forgives a
        *predicted* unmeasurability so that a host without ``psutil`` is not amber
        forever, and forgiving it in the verdict must not mean hiding it in the
        document: a reader can always count what could not be measured, whichever
        way the state came out.
        """
        return tuple(
            result.identifier
            for result in self.results
            if result.severity is HealthSeverity.UNKNOWN
        )


def aggregate_state(
    results: tuple[HealthCheckResult, ...],
    specs: tuple[HealthCheckSpec, ...] | None = None,
) -> RuntimeHealthState:
    """Reduce every check's severity to one state.

    Args:
        results: What the checks concluded.
        specs: The registry to read ``tolerates_unknown`` from, defaulting to
            :func:`checks`. Injected so a test can state a registry rather than
            depend on the real one.

    Returns:
        The aggregate state.

    **A failure always wins, and nothing forgives one.** ``FAIL`` means a check was
    performed and its answer was outside the declared bound, which is the one
    outcome that is never ambiguous.

    **An unmeasurability that was predicted does not count against the state, and
    one that was not does.** This is the part worth explaining, because it looks
    like leniency and is not. The CI ``quality`` job installs the development
    toolchain and never builds ``.venv``, so ``psutil`` is absent there on every
    run and four process checks report ``UNKNOWN`` every time; ``tracemalloc`` is
    off by default, so a fifth does too. Under a rule that treated every
    ``UNKNOWN`` as bad news, that host would report ``DEGRADED`` forever — and a
    signal that is always amber is a signal nobody reads, which costs more than the
    strictness buys. :attr:`HealthCheckSpec.tolerates_unknown` is where a check
    declares, in advance and in the registry rather than at a call site, that its
    silence is an expected state of a healthy system. It is the same bargain
    ``gpu-contract.toml`` strikes with ``absence_means``: absence is acceptable
    when somebody wrote down what it would mean.

    **What this deliberately does not do is hide it.** Every unmeasured check is
    still in :attr:`RuntimeHealthSnapshot.results` with its reason code, and
    :meth:`RuntimeHealthSnapshot.unmeasurable` counts them regardless of how the
    state came out. The characteristic failure mode of this design is a genuinely
    required probe being marked ``tolerates_unknown=True`` to quieten a noisy
    host, and the observable signal is a registry entry whose tolerance nobody can
    explain — which is why the flag lives in one visible table rather than being
    passed in by whoever is building the snapshot.
    """
    if any(result.severity is HealthSeverity.FAIL for result in results):
        return RuntimeHealthState.UNHEALTHY
    if any(result.severity is HealthSeverity.WARN for result in results):
        return RuntimeHealthState.DEGRADED
    tolerant = {spec.identifier for spec in (specs or checks()) if spec.tolerates_unknown}
    unexpected = any(
        result.severity is HealthSeverity.UNKNOWN and result.identifier not in tolerant
        for result in results
    )
    if unexpected:
        return RuntimeHealthState.DEGRADED
    return RuntimeHealthState.HEALTHY
