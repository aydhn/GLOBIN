"""Assembling one health snapshot from the probes, in a fixed order.

This is the use case: it coordinates domain rules through ports and touches
nothing itself. Every measurement arrives from an adapter and every judgement
comes from :mod:`globin.domain.health`; what lives here is the *sequence*, the
failure containment, and the assembly of the finished document.

**A check that raises does not take the snapshot with it.** Each runs inside a
boundary that converts an unexpected exception into an ``UNKNOWN`` result carrying
:data:`~globin.domain.health.REASON_CHECK_RAISED`. That is not silent swallowing
and ``ENGINEERING_CONTRACT.md`` invariant 23 is satisfied rather than dodged: the
exception is recorded in the result, reported through the Phase 023 logger with its
type attached, and counted by
:meth:`~globin.domain.health.RuntimeHealthSnapshot.unmeasurable`. What is refused is
the alternative — a thread counter throwing and an operator investigating a full
disk learning nothing at all.

**The order is the registry's, and the results come back in it.**
:class:`~globin.domain.health.RuntimeHealthSnapshot` refuses a set of results that
is out of order, so a collector that gathered them concurrently and appended as
they finished would be caught at construction rather than producing a document
whose digest changed between identical runs.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from globin.application.observability import Logger
from globin.domain.clock import Duration, Instant, MonotonicReading
from globin.domain.health import (
    AGGREGATE_CHECK,
    REASON_ACCESS_DENIED,
    REASON_CHECK_RAISED,
    REASON_DISK_EXHAUSTED,
    REASON_DISK_LOW,
    REASON_LOCK_HELD_ELSEWHERE,
    REASON_LOGGING_FAULTED,
    REASON_LOGGING_NOT_RUNNING,
    REASON_MEMORY_LOW,
    REASON_OK,
    REASON_PATH_ESCAPED,
    REASON_PATH_MISSING,
    REASON_PATH_UNWRITABLE,
    REASON_PSUTIL_ABSENT,
    REASON_RSS_HIGH,
    REASON_TRACING_DISABLED,
    Availability,
    HealthCheckResult,
    HealthSeverity,
    HealthThresholds,
    HostSummary,
    LifecycleSummary,
    LoggingState,
    LoggingSummary,
    MemorySummary,
    PathSummary,
    PlatformSummary,
    ProcessSummary,
    Reading,
    RuntimeHealthSnapshot,
    ThreadSummary,
    absent,
    aggregate_state,
    checks,
)
from globin.ports.clock import Clock, MonotonicClock
from globin.ports.health import (
    HostResourceProbe,
    LifecycleProbe,
    LoggingStateProbe,
    MemoryProbe,
    PlatformProbe,
    ProcessProbe,
    RuntimeTreeProbe,
    ThreadProbe,
)

EVENT_SNAPSHOT_TAKEN: Final[str] = "health.snapshot.taken"
"""A snapshot was produced, whatever it concluded."""

EVENT_CHECK_RAISED: Final[str] = "health.check.raised"
"""A check raised rather than returning, and was contained."""


@dataclass(frozen=True, slots=True)
class Gathered:
    """Every summary one snapshot is built from.

    Args:
        platform: What is running this.
        process: What the process is consuming.
        host: What the machine has.
        paths: Whether the runtime tree is usable.
        lifecycle: This run and the one before it.
        logging: The diagnostics subsystem.
        threads: The live thread inventory.
        memory: The allocator tracer, when it was asked for.

    Gathered once and judged many times. Every check below reads from this rather
    than calling a probe, so the eighteen results describe one moment instead of
    eighteen successive ones — which is the same reason
    :class:`~globin.adapters.health.PsutilProcessProbe` reads its fields inside a
    single ``oneshot``.
    """

    platform: PlatformSummary
    process: ProcessSummary
    host: HostSummary
    paths: PathSummary
    lifecycle: LifecycleSummary
    logging: LoggingSummary
    threads: ThreadSummary
    memory: MemorySummary | None = None


@dataclass(frozen=True, slots=True)
class HealthCollector:
    """Takes one health snapshot.

    Args:
        clock: The wall clock, for the timestamp a human reads.
        monotonic: The monotonic clock, for durations.
        thresholds: What measurements are compared against.
        platform_probe: What is running this.
        process_probe: What the process is consuming.
        host_probe: What the machine has.
        tree_probe: Whether the runtime tree is usable.
        lifecycle_probe: This run and the one before it.
        logging_probe: The diagnostics subsystem.
        thread_probe: The live thread inventory.
        memory_probe: The allocator tracer.
        logger: Where a contained failure is reported.
        started: When the process started, as a monotonic reading. Uptime is the
            difference between this and a reading taken now, so a wall clock that
            steps — a manual correction, a daylight-saving transition, an NTP
            slew — cannot produce a negative or a wildly wrong uptime.
    """

    clock: Clock
    monotonic: MonotonicClock
    thresholds: HealthThresholds
    platform_probe: PlatformProbe
    process_probe: ProcessProbe
    host_probe: HostResourceProbe
    tree_probe: RuntimeTreeProbe
    lifecycle_probe: LifecycleProbe
    logging_probe: LoggingStateProbe
    thread_probe: ThreadProbe
    memory_probe: MemoryProbe
    logger: Logger
    started: MonotonicReading
    anchors: tuple[str, ...] = ()

    def snapshot(
        self,
        *,
        correlation_id: str,
        run_id: str,
        version: str,
        profile: str,
        config_fingerprint: str,
        context_fingerprint: str,
        include_memory: bool = False,
        memory_top: int = 10,
    ) -> RuntimeHealthSnapshot:
        """Measure this runtime once.

        Args:
            correlation_id: Binds the snapshot to the records taken while making it.
            run_id: The run this belongs to.
            version: GLOBIN's version.
            profile: The active runtime profile.
            config_fingerprint: A digest over the resolved configuration.
            context_fingerprint: The bootstrap's own fingerprint.
            include_memory: Whether to read the allocator tracer.
            memory_top: How many allocation sites to report.

        Returns:
            The snapshot, whatever state it came out in.

        Gathering is itself contained: a probe that raises produces an absent
        summary rather than aborting, because the checks that depend on the other
        probes are still worth running.
        """
        taken_at = self.clock.now()
        gathered = self._gather(include_memory=include_memory, memory_top=memory_top)
        results = self._judge(gathered, taken_at)
        state = aggregate_state(results)
        uptime = self.monotonic.reading().since(self.started)
        self.logger.info(
            EVENT_SNAPSHOT_TAKEN,
            state=str(state),
            checks=len(results),
            unmeasurable=sum(1 for result in results if result.severity is HealthSeverity.UNKNOWN),
        )
        return RuntimeHealthSnapshot(
            generated_at=taken_at,
            correlation_id=correlation_id,
            run_id=run_id,
            version=version,
            profile=profile,
            config_fingerprint=config_fingerprint,
            context_fingerprint=context_fingerprint,
            uptime=uptime,
            platform=gathered.platform,
            process=gathered.process,
            host=gathered.host,
            paths=gathered.paths,
            lifecycle=gathered.lifecycle,
            logging=gathered.logging,
            threads=gathered.threads,
            memory=gathered.memory,
            results=results,
            state=state,
        )

    def _gather(self, *, include_memory: bool, memory_top: int) -> Gathered:
        """Read every probe once, containing each one separately.

        Args:
            include_memory: Whether to read the allocator tracer.
            memory_top: How many allocation sites to report.

        Returns:
            The gathered summaries, with a fully-absent one standing in for any
            probe that raised.

        **Containment is per probe, and that granularity is the point.** A single
        `try` around the whole gather would mean a thread counter throwing takes
        the disk figures with it, which is the failure this module exists to
        prevent — an operator investigating a full disk would learn nothing. Each
        substitution carries :data:`~globin.domain.health.REASON_CHECK_RAISED`, so
        the checks that read it report `UNKNOWN` naming the right cause rather
        than reporting a library that is perfectly well installed.
        """
        return Gathered(
            platform=self._safely("platform", self.platform_probe.summary, _absent_platform),
            process=self._safely("process", self.process_probe.summary, _absent_process),
            host=self._safely("host", lambda: self.host_probe.summary(self.anchors), _absent_host),
            paths=self._safely("paths", self.tree_probe.summary, _absent_paths),
            lifecycle=self._safely("lifecycle", self.lifecycle_probe.summary, _absent_lifecycle),
            logging=self._safely("logging", self.logging_probe.summary, _absent_logging),
            threads=self._safely("threads", self.thread_probe.summary, _absent_threads),
            memory=(
                self._safely(
                    "memory", lambda: self.memory_probe.summary(memory_top), _absent_memory
                )
                if include_memory
                else None
            ),
        )

    def _safely[T](self, name: str, read: Callable[[], T], fallback: Callable[[], T]) -> T:
        """Read one probe, substituting an absence if it raises.

        Args:
            name: Which probe, for the record.
            read: How to read it.
            fallback: What to use instead when it raises.

        Returns:
            What the probe said, or the fallback.

        ``Exception`` and not ``BaseException``: a ``KeyboardInterrupt`` means
        somebody asked the process to stop, and swallowing one to finish a
        diagnostic would be the health surface refusing to let go.
        """
        try:
            return read()
        except Exception as fault:
            self.logger.error(  # noqa: TRY400 -- GLOBIN's Logger has no `exception`
                EVENT_CHECK_RAISED, check=name, fault=type(fault).__name__
            )
            return fallback()

    def _judge(self, gathered: Gathered, taken_at: Instant) -> tuple[HealthCheckResult, ...]:
        """Run every registered check, in registry order.

        Args:
            gathered: What the probes reported.
            taken_at: The snapshot's timestamp.

        Returns:
            One result per check, in registry order.
        """
        judgements: dict[str, Callable[[Gathered], HealthCheckResult]] = {
            "runtime.identity": self._identity,
            "runtime.uptime": self._uptime,
            "platform.interpreter": self._interpreter,
            "process.identity": self._process_identity,
            "process.memory": self._process_memory,
            "process.cpu": self._process_cpu,
            "process.threads": self._threads,
            "process.handles": self._handles,
            "host.cpu": self._host_cpu,
            "host.memory": self._host_memory,
            "host.disk": self._disk,
            "paths.present": self._paths_present,
            "paths.writable": self._paths_writable,
            "paths.boundary": self._paths_boundary,
            "instance.lock": self._lock,
            "logging.state": self._logging,
            "memory.tracing": self._tracing,
        }
        results: list[HealthCheckResult] = []
        for spec in checks():
            if spec.identifier == AGGREGATE_CHECK:
                continue
            results.append(self._contained(spec.identifier, judgements[spec.identifier], gathered))
        results.append(self._aggregate(tuple(results), taken_at))
        return tuple(results)

    def _contained(
        self,
        identifier: str,
        judgement: Callable[[Gathered], HealthCheckResult],
        gathered: Gathered,
    ) -> HealthCheckResult:
        """Run one check, converting an unexpected exception into a result.

        Args:
            identifier: The check being run.
            judgement: What to run.
            gathered: What the probes reported.

        Returns:
            The check's result, or an ``UNKNOWN`` one describing the exception.

        ``Exception`` and not ``BaseException``. A ``KeyboardInterrupt`` or a
        ``SystemExit`` means somebody asked the process to stop, and swallowing
        one to finish a diagnostic would be the health surface refusing to let go
        of a process an operator is trying to end.
        """
        started = self.monotonic.reading()
        try:
            result = judgement(gathered)
        except Exception as fault:
            # TRY400 advises `logger.exception`, which is an API GLOBIN's own
            # immutable Logger deliberately does not have: ADR-0026 and
            # `tests/architecture/test_logging_discipline.py` keep the standard
            # library's `logging` out of GLOBIN's call sites, and the rule assumes
            # this object is one of its loggers. The exception's TYPE is recorded
            # as a field; its message and traceback are not, deliberately — a
            # third-party exception's text is exactly where a credential ends up,
            # and redaction matches field names rather than free text.
            self.logger.error(  # noqa: TRY400
                EVENT_CHECK_RAISED, check=identifier, fault=type(fault).__name__
            )
            return HealthCheckResult(
                identifier=identifier,
                severity=HealthSeverity.UNKNOWN,
                summary=f"the {identifier} check could not complete",
                reason=REASON_CHECK_RAISED,
                details=(("fault", type(fault).__name__),),
                measured_at=self.clock.now(),
                took=self.monotonic.reading().since(started),
                remediation="read the runtime log for the recorded fault",
            )
        return HealthCheckResult(
            identifier=result.identifier,
            severity=result.severity,
            summary=result.summary,
            reason=result.reason,
            details=result.details,
            measured_at=self.clock.now(),
            took=self.monotonic.reading().since(started),
            remediation=result.remediation,
        )

    @staticmethod
    def _passed(identifier: str, summary: str, **details: object) -> HealthCheckResult:
        """A result that measured something and found it acceptable.

        Args:
            identifier: The check.
            summary: What it found.
            **details: Structured fields.

        Returns:
            The result.
        """
        return HealthCheckResult(
            identifier=identifier,
            severity=HealthSeverity.PASS,
            summary=summary,
            reason=REASON_OK,
            details=tuple(sorted(details.items())),
        )

    @staticmethod
    def _unknown(identifier: str, summary: str, reason: str) -> HealthCheckResult:
        """A result for a question this host could not answer.

        Args:
            identifier: The check.
            summary: Why there is no answer.
            reason: The declared code.

        Returns:
            The result.
        """
        return HealthCheckResult(
            identifier=identifier,
            severity=HealthSeverity.UNKNOWN,
            summary=summary,
            reason=reason,
        )

    def _identity(self, gathered: Gathered) -> HealthCheckResult:
        """This run knows which run it is."""
        return self._passed(
            "runtime.identity",
            "the run is identified",
            instance=gathered.lifecycle.instance_id,
            status=gathered.lifecycle.status,
        )

    def _uptime(self, _gathered: Gathered) -> HealthCheckResult:
        """Uptime is measurable and non-negative."""
        elapsed = self.monotonic.reading().since(self.started)
        return self._passed(
            "runtime.uptime", "uptime was measured", nanoseconds=elapsed.nanoseconds
        )

    def _interpreter(self, gathered: Gathered) -> HealthCheckResult:
        """The interpreter identifies itself."""
        return self._passed(
            "platform.interpreter",
            f"{gathered.platform.implementation} {gathered.platform.python_version}",
            system=gathered.platform.system,
            architecture=gathered.platform.architecture,
        )

    def _process_identity(self, gathered: Gathered) -> HealthCheckResult:
        """The process knows its own identifier."""
        return self._passed(
            "process.identity", "the process is identified", pid=gathered.process.pid
        )

    def _process_memory(self, gathered: Gathered) -> HealthCheckResult:
        """This process's resident set is below its warning threshold."""
        resident = gathered.process.resident_bytes
        if not resident.measured or resident.value is None:
            return self._unknown("process.memory", "no resident set could be read", resident.reason)
        if resident.value > self.thresholds.process_rss_warning_bytes:
            return HealthCheckResult(
                identifier="process.memory",
                severity=HealthSeverity.WARN,
                summary=f"resident set is {resident.value} bytes",
                reason=REASON_RSS_HIGH,
                details=(("resident_bytes", resident.value),),
                remediation="compare against diagnostics.process_rss_warning_bytes",
            )
        return self._passed(
            "process.memory", "resident set is within its threshold", resident_bytes=resident.value
        )

    def _process_cpu(self, gathered: Gathered) -> HealthCheckResult:
        """Cumulative CPU time was read.

        Never a percentage. See
        :data:`~globin.domain.health.REASON_CPU_NOT_SAMPLED`.
        """
        user = gathered.process.cpu_user
        if not user.measured or user.value is None:
            return self._unknown("process.cpu", "no CPU time could be read", user.reason)
        system = gathered.process.cpu_system
        return self._passed(
            "process.cpu",
            "cumulative CPU time was read",
            user_nanoseconds=user.value,
            system_nanoseconds=system.value if system.measured else -1,
        )

    def _threads(self, gathered: Gathered) -> HealthCheckResult:
        """The thread inventory was taken."""
        return self._passed(
            "process.threads",
            f"{gathered.threads.count} threads are alive",
            count=gathered.threads.count,
        )

    def _handles(self, gathered: Gathered) -> HealthCheckResult:
        """The Windows handle count, where this platform has one."""
        handles = gathered.process.handles
        if not handles.measured or handles.value is None:
            return self._unknown(
                "process.handles", "this platform reports no handle count", handles.reason
            )
        return self._passed("process.handles", "the handle count was read", handles=handles.value)

    def _host_cpu(self, gathered: Gathered) -> HealthCheckResult:
        """The host reports how many processors this process may use."""
        logical = gathered.host.logical_cpus
        if not logical.measured or logical.value is None:
            return self._unknown("host.cpu", "no processor count could be read", logical.reason)
        return self._passed("host.cpu", f"{logical.value} logical processors", cpus=logical.value)

    def _host_memory(self, gathered: Gathered) -> HealthCheckResult:
        """Available host memory is above its minimum."""
        available = gathered.host.available_memory_bytes
        if not available.measured or available.value is None:
            return self._unknown(
                "host.memory", "no host memory figure could be read", available.reason
            )
        if available.value < self.thresholds.minimum_available_memory_bytes:
            return HealthCheckResult(
                identifier="host.memory",
                severity=HealthSeverity.FAIL,
                summary=f"only {available.value} bytes of host memory are available",
                reason=REASON_MEMORY_LOW,
                details=(("available_bytes", available.value),),
                remediation=(
                    "free memory on the host, or lower diagnostics.minimum_available_memory_bytes"
                ),
            )
        return self._passed(
            "host.memory", "host memory is above its minimum", available_bytes=available.value
        )

    def _disk(self, gathered: Gathered) -> HealthCheckResult:
        """Every runtime filesystem has room to write.

        The worst filesystem decides, because GLOBIN writes to all of them and a
        check reporting the healthiest would be answering a question nobody asked.
        """
        if not gathered.host.filesystems:
            return self._unknown(
                "host.disk", "no runtime filesystem was measured", REASON_ACCESS_DENIED
            )
        measurements: list[tuple[str, int]] = []
        for entry in gathered.host.filesystems:
            free = entry.free_bytes
            if not free.measured or free.value is None:
                return self._unknown("host.disk", "a filesystem could not be read", free.reason)
            measurements.append((entry.anchor, free.value))
        anchor, free_bytes = min(measurements, key=lambda item: item[1])
        if free_bytes < self.thresholds.minimum_free_bytes:
            return HealthCheckResult(
                identifier="host.disk",
                severity=HealthSeverity.FAIL,
                summary=f"{anchor} has {free_bytes} bytes free",
                reason=REASON_DISK_EXHAUSTED,
                details=(("anchor", anchor), ("free_bytes", free_bytes)),
                remediation="free space, or lower diagnostics.minimum_free_bytes",
            )
        if free_bytes < self.thresholds.disk_warning_bytes:
            return HealthCheckResult(
                identifier="host.disk",
                severity=HealthSeverity.WARN,
                summary=f"{anchor} has {free_bytes} bytes free",
                reason=REASON_DISK_LOW,
                details=(("anchor", anchor), ("free_bytes", free_bytes)),
                remediation="free space before it reaches diagnostics.minimum_free_bytes",
            )
        return self._passed(
            "host.disk", "every runtime filesystem has room", anchor=anchor, free_bytes=free_bytes
        )

    def _paths_present(self, gathered: Gathered) -> HealthCheckResult:
        """Every declared runtime area exists and is a directory."""
        missing = [
            name
            for name, present, directory, _, _ in gathered.paths.areas
            if not present or not directory
        ]
        if not gathered.paths.root_present or missing:
            return HealthCheckResult(
                identifier="paths.present",
                severity=HealthSeverity.FAIL,
                summary="a declared runtime area is missing or is not a directory",
                reason=REASON_PATH_MISSING,
                details=(("areas", tuple(sorted(missing))),),
                remediation="run `globin bootstrap check`, which creates the tree",
            )
        return self._passed(
            "paths.present", "every runtime area exists", areas=len(gathered.paths.areas)
        )

    def _paths_writable(self, gathered: Gathered) -> HealthCheckResult:
        """Every declared runtime area can be written to."""
        unwritable = [name for name, _, _, writable, _ in gathered.paths.areas if not writable]
        if unwritable:
            return HealthCheckResult(
                identifier="paths.writable",
                severity=HealthSeverity.FAIL,
                summary="a declared runtime area is not writable",
                reason=REASON_PATH_UNWRITABLE,
                details=(("areas", tuple(sorted(unwritable))),),
                remediation="check the permissions on the runtime root",
            )
        return self._passed("paths.writable", "every runtime area is writable")

    def _paths_boundary(self, gathered: Gathered) -> HealthCheckResult:
        """No declared area resolves outside the approved root."""
        escaped = [name for name, _, _, _, inside in gathered.paths.areas if not inside]
        if escaped:
            return HealthCheckResult(
                identifier="paths.boundary",
                severity=HealthSeverity.FAIL,
                summary="a runtime area resolves outside the approved root",
                reason=REASON_PATH_ESCAPED,
                details=(("areas", tuple(sorted(escaped))),),
                remediation="remove the link or junction redirecting the runtime tree",
            )
        return self._passed("paths.boundary", "every runtime area is inside its root")

    def _lock(self, gathered: Gathered) -> HealthCheckResult:
        """This process is the machine's one coordinator, or something else is.

        Held elsewhere is a ``WARN`` rather than a ``FAIL``, and the distinction is
        deliberate: a second GLOBIN running is a fact an operator needs, but it is
        not a fault in *this* process, which is behaving correctly by not starting
        work. ``globin bootstrap check`` is the command that refuses.
        """
        if gathered.lifecycle.lock_held:
            return self._passed("instance.lock", "the coordinator lock is available")
        return HealthCheckResult(
            identifier="instance.lock",
            severity=HealthSeverity.WARN,
            summary="another GLOBIN coordinator holds the lock",
            reason=REASON_LOCK_HELD_ELSEWHERE,
            details=(("problem", gathered.lifecycle.lock_problem),),
            remediation="stop the other coordinator, or leave this one read-only",
        )

    def _logging(self, gathered: Gathered) -> HealthCheckResult:
        """The diagnostics subsystem is running, or says why it is not."""
        state = gathered.logging.state
        if state is LoggingState.FAULTED:
            return HealthCheckResult(
                identifier="logging.state",
                severity=HealthSeverity.FAIL,
                summary="the diagnostics subsystem recorded a fault",
                reason=REASON_LOGGING_FAULTED,
                details=(("last_fault", gathered.logging.last_fault),),
                remediation="read the fault file beside the runtime log",
            )
        if state is LoggingState.NOT_CONFIGURED:
            # Not a degradation, and the distinction is the whole reason this
            # branch exists separately. A short-lived command — `diagnostics
            # snapshot`, `doctor` — is a DIFFERENT PROCESS from any long-running
            # GLOBIN, so it cannot observe that process's sinks and deliberately
            # starts none of its own. The truthful answer is "not determined
            # here", which is UNKNOWN, and the registry marks it tolerated so a
            # read-only command does not report amber on every run. A process that
            # DID start the subsystem passes a probe carrying its real state, and
            # every other value below is judged normally.
            return self._unknown(
                "logging.state",
                "the diagnostics subsystem was not started by this command",
                REASON_LOGGING_NOT_RUNNING,
            )
        if state is not LoggingState.RUNNING:
            return HealthCheckResult(
                identifier="logging.state",
                severity=HealthSeverity.WARN,
                summary=f"the diagnostics subsystem is {state}",
                reason=REASON_LOGGING_NOT_RUNNING,
                details=(("state", str(state)),),
                remediation="the subsystem started and is no longer running; read the log",
            )
        return self._passed(
            "logging.state",
            "the diagnostics subsystem is running",
            destination=gathered.logging.destination,
        )

    def _tracing(self, gathered: Gathered) -> HealthCheckResult:
        """The allocator tracer, when it was asked for."""
        memory = gathered.memory
        if memory is None or not memory.tracing:
            return self._unknown("memory.tracing", "memory tracing is off", REASON_TRACING_DISABLED)
        current = memory.current_bytes
        return self._passed(
            "memory.tracing",
            "memory tracing is on",
            current_bytes=current.value if current.measured else -1,
            sites=len(memory.top),
        )

    def _aggregate(
        self, results: tuple[HealthCheckResult, ...], taken_at: Instant
    ) -> HealthCheckResult:
        """The check that answers for all the others.

        Args:
            results: What every other check concluded.
            taken_at: The snapshot's timestamp.

        Returns:
            One result carrying the aggregate state.
        """
        state = aggregate_state(results)
        severity = {
            "healthy": HealthSeverity.PASS,
            "degraded": HealthSeverity.WARN,
            "unhealthy": HealthSeverity.FAIL,
        }[str(state)]
        unmeasurable = sum(1 for item in results if item.severity is HealthSeverity.UNKNOWN)
        return HealthCheckResult(
            identifier=AGGREGATE_CHECK,
            severity=severity,
            summary=f"the runtime is {state}",
            reason=REASON_OK if severity is HealthSeverity.PASS else _worst_reason(results),
            details=(("checks", len(results)), ("unmeasurable", unmeasurable)),
            measured_at=taken_at,
            took=Duration(0),
        )


def _worst_reason(results: tuple[HealthCheckResult, ...]) -> str:
    """The reason code of the first result that explains a non-passing aggregate.

    Args:
        results: Every other check's result.

    Returns:
        A declared reason code.

    Registry order decides, so the code names the *earliest* thing that was wrong
    rather than an arbitrary one — the same rule
    :func:`globin.domain.bootstrap.exit_code_for` follows, and for the same reason:
    a later check may be unhappy because an earlier one was.
    """
    for severity in (HealthSeverity.FAIL, HealthSeverity.WARN, HealthSeverity.UNKNOWN):
        for result in results:
            if result.severity is severity:
                return result.reason
    return REASON_PSUTIL_ABSENT


def _raised(unit: str = "count") -> Reading:
    """A reading standing in for a probe that raised.

    Args:
        unit: What the quantity would have counted.

    Returns:
        The absence.
    """
    return absent(Availability.UNAVAILABLE, REASON_CHECK_RAISED, unit)


def _absent_platform() -> PlatformSummary:
    """A platform summary for a probe that raised."""
    return PlatformSummary("", "", "", "", "")


def _absent_process() -> ProcessSummary:
    """A process summary for a probe that raised."""
    return ProcessSummary(0, _raised(), _raised(), _raised(), _raised(), _raised(), _raised())


def _absent_host() -> HostSummary:
    """A host summary for a probe that raised."""
    return HostSummary(_raised(), _raised(), _raised(), _raised(), ())


def _absent_paths() -> PathSummary:
    """A path summary for a probe that raised.

    ``root_present`` is false and the area list is empty, so `paths.present`
    fails rather than passing vacuously: a tree nobody could inspect is not a
    tree anybody should write to.
    """
    return PathSummary(root_present=False)


def _absent_lifecycle() -> LifecycleSummary:
    """A lifecycle summary for a probe that raised."""
    return LifecycleSummary("", "", lock_held=False, lock_problem="the lifecycle probe raised")


def _absent_logging() -> LoggingSummary:
    """A logging summary for a probe that raised."""
    return LoggingSummary(LoggingState.FAULTED, "", "", _raised(), _raised())


def _absent_threads() -> ThreadSummary:
    """A thread summary for a probe that raised."""
    return ThreadSummary(0, ())


def _absent_memory() -> MemorySummary:
    """A memory summary for a probe that raised."""
    return MemorySummary(False, _raised(), _raised(), _raised(), _raised())
