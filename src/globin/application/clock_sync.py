"""Calibrating a venue clock, deciding whether to sign against it, and proving both offline.

Four use cases and one self-test, and none of them can reach a socket except by
being handed something that can. This layer may import ``domain`` and ``ports``
only, so :func:`take_sample` reaches the venue exactly to the extent that the
:class:`~globin.ports.clock.ServerTimeSource` it is given does, and everything else
here is arithmetic over values.

**Where the two readings are taken is the whole correctness of the estimate**, and
it is here rather than in the adapter deliberately. An adapter that measured its own
round trip would be measuring the wrong span — its own socket handling rather than
the exchange — and it would have no wall-clock anchor to pair the measurement with.
:func:`take_sample` brackets the call, so the span measured is exactly the span
between GLOBIN asking and GLOBIN being answered.

**The self-test's strongest check is not about GLOBIN.** ``clock.venue_rule``
takes an admitted timing context and runs the venue's own published pseudo-code
against it, both evaluations, with a simulated ``serverTime`` at the extremes of
the stated uncertainty. It is the one check here whose expected answer this
repository did not choose — the same role
:data:`globin.application.auth.CHECK_KNOWN_ANSWER` plays for signing.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from globin.domain.api_reality import ApiRealitySnapshot, ProtocolKind, SurfaceCapability
from globin.domain.auth_timing import RecvWindow, TimestampUnit
from globin.domain.clock import (
    MICROSECONDS_PER_MILLISECOND,
    Duration,
    Instant,
    MonotonicReading,
)
from globin.domain.clock_sync import (
    FUTURE_TOLERANCE_MILLIS,
    OFFSET_BUCKET_BOUNDS_MILLIS,
    ROUND_TRIP_BUCKET_BOUNDS_MILLIS,
    AdmissionStatus,
    CalibrationSample,
    ClockAnchor,
    ClockDiscipline,
    ClockDomain,
    ClockStatus,
    JumpDirection,
    JumpVerdict,
    RecvWindowPolicy,
    ServerTimeReading,
    SyncState,
    TimingAdmission,
    TimingRecovery,
    admit,
    corrected_stamp,
    detect_jump,
    evaluate,
    offset_bucket,
    offset_moved_too_far,
    recovery_for,
    round_trip_bucket,
    sample_offset,
    server_time_from,
)
from globin.domain.rest import RequestOutcome, SideEffect
from globin.domain.rest_contract import TransportContract
from globin.domain.rest_endpoint import ResolutionStatus, resolve
from globin.errors import ValidationError
from globin.ports.clock import Clock, MonotonicClock, ServerTimeSource

SERVER_TIME_OPERATION_SUFFIX: str = "time"
"""How a product's server-time probe is spelled in ``rest-transport.toml``.

The full operation is ``{family}.time``, built at the call site. A second product
family therefore needs a row in that document and no change here — the same rule
``globin.runtime.cli`` already follows for its probe verbs.
"""

CHECK_ESTIMATOR: str = "clock.estimator"
"""The midpoint estimator against hand-computed vectors."""

CHECK_UNITS: str = "clock.units"
"""Millisecond and microsecond conversion, exact and floored once."""

CHECK_STATE_MACHINE: str = "clock.state_machine"
"""Every state is reachable and exactly one of them admits."""

CHECK_ADMISSION: str = "clock.admission"
"""Every declared refusal fires for its own reason."""

CHECK_RECV_WINDOW: str = "clock.recv_window"
"""The window bounds hold and the rendering is canonical."""

CHECK_RECOVERY: str = "clock.recovery"
"""The ``-1021`` recovery table recomputes, including what it refuses."""

CHECK_VENUE_RULE: str = "clock.venue_rule"
"""An admitted timestamp satisfies the venue's own published processing rule."""

CHECK_BUCKETS: str = "clock.buckets"
"""Every published bucket dimension has the cardinality its bounds imply."""


@dataclass(frozen=True, slots=True)
class DomainAvailability:
    """Whether one clock domain can be calibrated at all, and why not when it cannot.

    Args:
        domain: Which clock.
        available: Whether a server-time probe could be sent for it.
        resolution: What Phase 034's endpoint resolution answered.
        operation: The probe operation that would be used, when there is one.
        detail: What an operator should read.

    **Three of the four families the brief names are permanently unavailable
    today, and that is a measurement rather than a gap.** Phase 033 records the
    REST surface of every non-Spot family as ``unknown`` and the registry carries no
    endpoint for one, because the derivatives documentation is client-rendered and
    ``docs/SOURCE_POLICY.md`` forbids both scraping it and accepting a summary of
    it. So ``/fapi/v1/time``, ``/dapi/v1/time`` and ``/eapi/v1/time`` are spelled
    nowhere in this package: the domain is *named*, and asking it anything refuses.
    """

    domain: ClockDomain
    available: bool
    resolution: str
    operation: str = ""
    detail: str = ""

    def as_record(self) -> dict[str, object]:
        """This availability as plain JSON-safe values."""
        return {
            "domain": self.domain.as_record(),
            "available": self.available,
            "resolution": self.resolution,
            "operation": self.operation,
            "detail": self.detail,
        }


def declared_domains(
    snapshot: ApiRealitySnapshot,
    contract: TransportContract,
    *,
    stale_sources: Sequence[str] = (),
) -> tuple[DomainAvailability, ...]:
    """Every clock domain the registry describes, and whether each can be asked.

    Args:
        snapshot: Phase 033's registry. The only source of endpoints.
        contract: The declared transport contract, which names the probe paths.
        stale_sources: Source identifiers past their re-check interval.

    Returns:
        One availability per declared product-and-environment pair, in registry
        order, unavailable ones included.

    **Unavailable domains are listed rather than filtered out**, for the reason
    :func:`globin.application.rest.survey_report` gives about refusals: a list
    containing only what works would report a fail-closed registry as an empty one,
    when the refusals are the evidence that the gate works.

    Two gates, and the order matters. The endpoint must resolve *first* — a family
    whose REST surface is undocumented has no address, and looking up a probe path
    for it would be asking which door to knock on in a building that is not
    recorded. Only then is the probe consulted, which is what keeps the rule *a path
    is never guessed* structural.
    """
    results: list[DomainAvailability] = []
    for record in snapshot.environments:
        domain = ClockDomain(
            family=record.family, environment=record.environment, protocol=ProtocolKind.REST
        )
        resolution = resolve(
            snapshot,
            family=record.family,
            environment=record.environment,
            capability=SurfaceCapability.MARKET_DATA,
            stale_sources=stale_sources,
        )
        if not resolution.permitted:
            results.append(
                DomainAvailability(
                    domain=domain,
                    available=False,
                    resolution=resolution.outcome.value,
                    detail=resolution.detail,
                )
            )
            continue
        operation = f"{record.family.slug}.{SERVER_TIME_OPERATION_SUFFIX}"
        descriptor = contract.probe(record.family, operation)
        if descriptor is None:
            results.append(
                DomainAvailability(
                    domain=domain,
                    available=False,
                    resolution=resolution.outcome.value,
                    detail=(
                        f"the transport contract declares no {operation!r} probe; a server-time "
                        "path is never guessed"
                    ),
                )
            )
            continue
        results.append(
            DomainAvailability(
                domain=domain,
                available=True,
                resolution=ResolutionStatus.RESOLVED.value,
                operation=descriptor.operation,
                detail=f"{descriptor.method.value} {descriptor.path} (weight {descriptor.weight})",
            )
        )
    return tuple(results)


@dataclass(frozen=True, slots=True)
class CalibrationOutcome:
    """What one calibration round produced.

    Args:
        domain: Which clock was asked.
        sample: The sample, when the venue answered usably.
        failed: Whether the probe failed.
        offset_jumped: Whether the offset moved further than the declared bound.
        detail: What an operator should read.

    Raises:
        ValidationError: If a successful outcome carries no sample, or a failure
            carries one.

    **A failed calibration is a value, never an exception.** The venue not answering
    is an ordinary state of the world that the caller records as
    :attr:`~globin.domain.clock_sync.SyncState.DEGRADED`; unwinding a stack for it
    would make an expected condition look like a defect, and would push the
    classification out to every call site.
    """

    domain: ClockDomain
    sample: CalibrationSample | None = None
    failed: bool = False
    offset_jumped: bool = False
    detail: str = ""

    def __post_init__(self) -> None:
        """Refuse an outcome that reports one thing and carries another."""
        if self.failed and self.sample is not None:
            msg = "a calibration outcome reports a failure and still carries a sample"
            raise ValidationError(msg)
        if not self.failed and self.sample is None:
            msg = "a calibration outcome reports success and carries no sample"
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This outcome as plain JSON-safe values."""
        return {
            "domain": self.domain.as_record(),
            "sample": self.sample.as_record() if self.sample else None,
            "failed": self.failed,
            "offset_jumped": self.offset_jumped,
            "detail": self.detail,
        }


def take_sample(
    source: ServerTimeSource,
    domain: ClockDomain,
    *,
    clock: Clock,
    monotonic: MonotonicClock,
    previous: CalibrationSample | None = None,
    discipline: ClockDiscipline,
) -> CalibrationOutcome:
    """Ask one venue clock the time, and turn the exchange into a sample.

    Args:
        source: How to ask.
        domain: Which clock.
        clock: The host's wall clock, read exactly once.
        monotonic: The host's monotonic clock, read exactly twice.
        previous: The sample the domain was last anchored on, for jump detection.
        discipline: The thresholds to apply.

    Returns:
        The outcome, carrying a sample or naming why there is none.

    The bracketing, and why each read is where it is:

    .. code-block:: text

        anchor   = clock.now()          the one wall read; the midpoint's origin
        started  = monotonic.reading()  taken immediately after, adjacent to it
        reading  = source.sample(...)   the exchange
        finished = monotonic.reading()  the span ends here

    **One wall read, not two.** A second wall read at the end would let a clock
    adjustment landing mid-flight enter the offset directly. Extending a single
    anchor by a monotonic span cannot: the monotonic clock is documented as *"not
    affected by system clock updates"*, so the span is the true elapsed time
    whatever the operator did to the date.

    The wall clock is read *before* the monotonic one and the two are adjacent, so
    the span measured from ``started`` is at most a hair shorter than the span from
    ``anchor``. The difference is the cost of two consecutive function calls and is
    orders of magnitude inside
    :attr:`~globin.domain.clock_sync.CalibrationSample.uncertainty_micros`, which is
    where it is accounted for rather than ignored.
    """
    anchor = clock.now()
    started = monotonic.reading()
    reading = source.sample(domain)
    finished = monotonic.reading()
    if reading is None:
        return CalibrationOutcome(
            domain=domain,
            failed=True,
            detail=f"the server-time probe for {domain.label} did not return a usable reading",
        )
    sample = sample_offset(
        domain, reading=reading, wall_anchor=anchor, started=started, finished=finished
    )
    jumped = _offset_moved(previous, sample, discipline)
    return CalibrationOutcome(
        domain=domain,
        sample=sample,
        offset_jumped=jumped,
        detail=(
            (
                f"the estimated offset for {domain.label} moved by more than "
                f"{discipline.max_offset_jump.milliseconds}ms since the last calibration"
            )
            if jumped
            else ""
        ),
    )


def _offset_moved(
    previous: CalibrationSample | None,
    current: CalibrationSample,
    discipline: ClockDiscipline,
) -> bool:
    """Whether the offset moved further than a venue clock plausibly could.

    Args:
        previous: The previous anchor, if any.
        current: The sample just taken.
        discipline: Whose bound applies.

    Returns:
        ``True`` when the movement exceeds the bound.

    A thin wrapper so this module reads as one sequence of decisions; the rule
    itself is :func:`globin.domain.clock_sync.offset_moved_too_far`, which is where
    it can be tested without a source.
    """
    return offset_moved_too_far(previous, current, discipline)


def status_for(
    domain: ClockDomain,
    *,
    samples: tuple[CalibrationSample, ...],
    age: Duration | None,
    discipline: ClockDiscipline,
    last_probe_failed: bool = False,
    calibrated_at: ClockAnchor | None = None,
    now: ClockAnchor | None = None,
    invalidated: bool = False,
) -> ClockStatus:
    """Fold a domain's window, its age and a jump check into one status.

    Args:
        domain: Which clock.
        samples: The calibration window.
        age: How long since the chosen sample was taken.
        discipline: The thresholds.
        last_probe_failed: Whether the most recent attempt failed.
        calibrated_at: Both host clocks as they read when the domain was last
            calibrated.
        now: Both host clocks as they read at this moment.
        invalidated: Whether something disbelieved the estimate.

    Returns:
        The status.

    The jump check runs only when **both** anchors are supplied, which is the
    honest condition: a domain that has never calibrated has no earlier pair to
    compare against, and inventing one would manufacture a verdict.
    """
    jump = (
        detect_jump(earlier=calibrated_at, later=now, discipline=discipline)
        if calibrated_at is not None and now is not None
        else None
    )
    return evaluate(
        domain,
        samples=samples,
        age=age,
        discipline=discipline,
        last_probe_failed=last_probe_failed,
        jump=jump,
        invalidated=invalidated,
    )


def admit_request(
    status: ClockStatus,
    *,
    moment: Instant,
    unit: TimestampUnit,
    window: RecvWindow,
    discipline: ClockDiscipline,
    source_available: bool = True,
    attempt: int = 0,
) -> TimingAdmission:
    """Decide whether a signed request may be stamped against this clock.

    Args:
        status: What is known about the clock domain.
        moment: The host's wall clock, read once by the caller.
        unit: Which unit the timestamp should carry.
        window: The validity window that would be sent.
        discipline: The thresholds.
        source_available: Whether the domain can be calibrated at all.
        attempt: Which attempt this is.

    Returns:
        A :class:`~globin.domain.clock_sync.TimingAdmission`.

    A thin seam over :func:`globin.domain.clock_sync.admit` that builds the policy
    from the window, so a caller passes the value an operator configured rather than
    assembling a policy object at every call site.
    """
    return admit(
        status,
        moment=moment,
        unit=unit,
        policy=RecvWindowPolicy(window=window),
        discipline=discipline,
        source_available=source_available,
        attempt=attempt,
    )


def timing_recovery(
    *,
    exchange_code: int,
    outcome: RequestOutcome,
    side_effect: SideEffect,
    idempotent: bool = False,
    attempt: int = 0,
) -> TimingRecovery:
    """What a timing rejection permits, decided and not acted on.

    Args:
        exchange_code: The venue's error code.
        outcome: How Phase 034 classified the exchange.
        side_effect: What was at stake.
        idempotent: Whether re-sending cannot create a second effect.
        attempt: How many times it has already been sent.

    Returns:
        The verdict.

    Exposed here so that Phase 043's executor has one import to reach for, and so
    the rule is testable from the layer that will own the caller. The decision is
    :func:`globin.domain.clock_sync.recovery_for`.
    """
    return recovery_for(
        exchange_code=exchange_code,
        outcome=outcome,
        side_effect=side_effect,
        idempotent=idempotent,
        attempt=attempt,
    )


@dataclass(frozen=True, slots=True)
class ClockFinding:
    """One check the clock self-test performed, and what it found."""

    check: str
    passed: bool
    detail: str = ""

    def as_record(self) -> dict[str, object]:
        """This finding as plain JSON-safe values."""
        return {"check": self.check, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ClockSelfTest:
    """Everything the offline clock self-test concluded."""

    findings: tuple[ClockFinding, ...]

    @property
    def passed(self) -> bool:
        """Whether every check passed."""
        return all(item.passed for item in self.findings)

    @property
    def failures(self) -> tuple[ClockFinding, ...]:
        """Every check that did not pass, in order."""
        return tuple(item for item in self.findings if not item.passed)

    def as_record(self) -> dict[str, object]:
        """This report as plain JSON-safe values."""
        return {
            "passed": self.passed,
            "checked": len(self.findings),
            "failed": len(self.failures),
            "findings": [item.as_record() for item in self.findings],
        }


def _fixture_domain() -> ClockDomain:
    """A clock domain for the self-test to reason about.

    Returns:
        A domain built from identifiers the registry uses.

    In a function rather than at module scope because a layer package performs no
    call at import.
    """
    from globin.domain.api_reality import EnvironmentName, ProductFamily

    return ClockDomain(
        family=ProductFamily("spot"),
        environment=EnvironmentName("testnet"),
        protocol=ProtocolKind.REST,
    )


def _fixture_moment() -> Instant:
    """A fixed moment for the self-test, chosen from the venue's own example.

    Returns:
        The instant whose epoch milliseconds are ``1499827319559`` — the timestamp
        the venue publishes in its own worked signing examples, and the one Phase
        035's known-answer vectors already use.
    """
    from globin.domain.clock import instant_from_epoch_millis

    return instant_from_epoch_millis(1499827319559)


def _fixture_sample(offset_micros: int, round_trip_millis: int) -> CalibrationSample:
    """A sample with a chosen offset and round trip.

    Args:
        offset_micros: How far ahead the venue is.
        round_trip_millis: How long the exchange took.

    Returns:
        The sample.
    """
    return CalibrationSample(
        domain=_fixture_domain(),
        offset_micros=offset_micros,
        round_trip=Duration(round_trip_millis * MICROSECONDS_PER_MILLISECOND * 1_000),
        taken_at=MonotonicReading(round_trip_millis * MICROSECONDS_PER_MILLISECOND * 1_000),
        wall_anchor_micros=_fixture_moment().epoch_micros,
        reported_unit=TimestampUnit.MILLISECONDS,
    )


def _estimator_finding() -> ClockFinding:
    """Whether the midpoint estimator reproduces hand-computed vectors."""
    domain = _fixture_domain()
    anchor = _fixture_moment()
    wrong: list[str] = []
    for label, ahead_micros, rtt_millis in (
        ("zero-offset", 0, 40),
        ("venue-ahead", 250_000, 40),
        ("venue-behind", -250_000, 40),
        ("slow-link", 0, 400),
    ):
        rtt_nanos = rtt_millis * MICROSECONDS_PER_MILLISECOND * 1_000
        true_midpoint = anchor.epoch_micros + (rtt_millis * MICROSECONDS_PER_MILLISECOND) // 2
        reading = ServerTimeReading(
            epoch_micros=true_midpoint + ahead_micros, unit=TimestampUnit.MILLISECONDS
        )
        sample = sample_offset(
            domain,
            reading=reading,
            wall_anchor=anchor,
            started=MonotonicReading(0),
            finished=MonotonicReading(rtt_nanos),
        )
        if sample.offset_micros != ahead_micros:
            wrong.append(
                f"{label}: estimated {sample.offset_micros} and the venue was {ahead_micros}"
            )
        if sample.uncertainty_micros != (rtt_millis * MICROSECONDS_PER_MILLISECOND) // 2:
            wrong.append(f"{label}: uncertainty is not half the round trip")
    return ClockFinding(
        check=CHECK_ESTIMATOR,
        passed=not wrong,
        detail="; ".join(wrong) or "four vectors estimate exactly, uncertainty is half the trip",
    )


def _units_finding() -> ClockFinding:
    """Whether the two timestamp units convert exactly and floor once."""
    from globin.domain.clock import instant

    problems: list[str] = []
    moment = instant(_fixture_moment().moment.replace(microsecond=999_999))
    micros = corrected_stamp(moment, 1, TimestampUnit.MICROSECONDS)
    millis = corrected_stamp(moment, 1, TimestampUnit.MILLISECONDS)
    if micros != moment.epoch_micros + 1:
        problems.append("the microsecond stamp is not exact")
    if millis != (moment.epoch_micros + 1) // MICROSECONDS_PER_MILLISECOND:
        problems.append("the millisecond stamp is not a single floor of the corrected value")
    if millis * MICROSECONDS_PER_MILLISECOND > micros:
        problems.append("the millisecond stamp rounded forward, into the venue's future")
    if corrected_stamp(moment, 0, TimestampUnit.MILLISECONDS) != moment.epoch_millis:
        problems.append("a zero correction does not agree with Instant.epoch_millis")
    return ClockFinding(
        check=CHECK_UNITS,
        passed=not problems,
        detail="; ".join(problems) or "microseconds exact, milliseconds floored once and backwards",
    )


def _state_machine_finding(discipline: ClockDiscipline) -> ClockFinding:
    """Whether every state is reachable and exactly one of them admits."""
    domain = _fixture_domain()
    healthy = (_fixture_sample(1_000, 40),)
    threshold = discipline.max_wall_divergence.microseconds
    reached = {
        evaluate(domain, samples=(), age=None, discipline=discipline).state,
        evaluate(domain, samples=healthy, age=Duration(0), discipline=discipline).state,
        evaluate(
            domain,
            samples=healthy,
            age=Duration(discipline.freshness_ttl.nanoseconds * 2),
            discipline=discipline,
        ).state,
        evaluate(
            domain,
            samples=healthy,
            age=Duration(0),
            discipline=discipline,
            last_probe_failed=True,
        ).state,
        evaluate(
            domain,
            samples=healthy,
            age=Duration(0),
            discipline=discipline,
            jump=JumpVerdict(
                direction=JumpDirection.FORWARD,
                divergence_micros=threshold * 4,
                threshold_micros=threshold,
            ),
        ).state,
    }
    admitting = sorted(state.value for state in SyncState if state.admits)
    problems: list[str] = []
    missing = sorted(state.value for state in SyncState if state not in reached)
    if missing:
        problems.append(f"unreachable states: {', '.join(missing)}")
    if admitting != [SyncState.SYNCHRONIZED.value]:
        problems.append(f"states that admit a signature: {', '.join(admitting)}")
    return ClockFinding(
        check=CHECK_STATE_MACHINE,
        passed=not problems,
        detail=(
            "; ".join(problems)
            or f"all {len(SyncState)} states reachable, only {SyncState.SYNCHRONIZED.value} admits"
        ),
    )


def _admission_finding(discipline: ClockDiscipline) -> ClockFinding:
    """Whether every declared refusal fires for its own reason."""
    domain = _fixture_domain()
    moment = _fixture_moment()
    healthy = (_fixture_sample(1_000, 40),)
    fresh = evaluate(domain, samples=healthy, age=Duration(0), discipline=discipline)
    stale = evaluate(
        domain,
        samples=healthy,
        age=Duration(discipline.freshness_ttl.nanoseconds * 2),
        discipline=discipline,
    )
    empty = evaluate(domain, samples=(), age=None, discipline=discipline)
    window = RecvWindow(Decimal(5000))
    narrow = RecvWindow(Decimal(1))
    expected = (
        (AdmissionStatus.CLOCK_SOURCE_UNAVAILABLE, fresh, window, False),
        (AdmissionStatus.CLOCK_NOT_SYNCHRONIZED, empty, window, True),
        (AdmissionStatus.CLOCK_CALIBRATION_STALE, stale, window, True),
        (AdmissionStatus.RECV_WINDOW_POLICY_VIOLATION, fresh, narrow, True),
        (AdmissionStatus.ADMITTED, fresh, window, True),
    )
    wrong = []
    for want, status, chosen, available in expected:
        got = admit_request(
            status,
            moment=moment,
            unit=TimestampUnit.MILLISECONDS,
            window=chosen,
            discipline=discipline,
            source_available=available,
        )
        if got.outcome is not want:
            wrong.append(f"expected {want.value} and got {got.outcome.value}")
        if got.admitted != (got.context is not None):
            wrong.append(f"{got.outcome.value} disagrees with whether it carries a context")
    return ClockFinding(
        check=CHECK_ADMISSION,
        passed=not wrong,
        detail="; ".join(wrong) or f"{len(expected)} admission outcomes fire for their own reason",
    )


def _recv_window_finding() -> ClockFinding:
    """Whether the documented window bounds hold and the rendering is canonical."""
    problems: list[str] = []
    for text, expected_micros in (("5000", 5_000_000), ("6000.346", 6_000_346)):
        policy = RecvWindowPolicy(window=RecvWindow(Decimal(text)))
        if policy.micros != expected_micros:
            problems.append(
                f"{text} is {policy.micros} microseconds and should be {expected_micros}"
            )
        if str(policy.window) != text:
            problems.append(f"{text} renders as {str(policy.window)!r}")
    for refused in ("60000.001", "5000.1234", "0"):
        try:
            RecvWindow(Decimal(refused))
            problems.append(f"{refused} was accepted as a window")
        except ValidationError:
            continue
    policy = RecvWindowPolicy(window=RecvWindow(Decimal(5000)))
    if not policy.covers(5_000_000) or policy.covers(5_000_001):
        problems.append("a window does not cover exactly its own width")
    if policy.as_record()["adaptive"] is not False:
        problems.append("the window policy reports itself as adaptive")
    return ClockFinding(
        check=CHECK_RECV_WINDOW,
        passed=not problems,
        detail="; ".join(problems) or "bounds, three decimals and canonical rendering all hold",
    )


def _recovery_finding() -> ClockFinding:
    """Whether the timing-recovery table recomputes, refusals included."""
    cases = (
        (
            "other-code",
            -1022,
            RequestOutcome.FAILURE_CONFIRMED,
            SideEffect.READ_ONLY,
            False,
            0,
            TimingRecovery.NO_ACTION,
        ),
        (
            "read-confirmed",
            -1021,
            RequestOutcome.FAILURE_CONFIRMED,
            SideEffect.READ_ONLY,
            False,
            0,
            TimingRecovery.RESYNC_AND_RETRY_ONCE,
        ),
        (
            "write-idempotent",
            -1021,
            RequestOutcome.FAILURE_CONFIRMED,
            SideEffect.MUTATING,
            True,
            0,
            TimingRecovery.RESYNC_AND_RETRY_ONCE,
        ),
        (
            "write-silent",
            -1021,
            RequestOutcome.FAILURE_CONFIRMED,
            SideEffect.MUTATING,
            False,
            0,
            TimingRecovery.RESYNC_ONLY,
        ),
        (
            "unknown-outcome",
            -1021,
            RequestOutcome.UNKNOWN,
            SideEffect.MUTATING,
            True,
            0,
            TimingRecovery.RESYNC_ONLY,
        ),
        (
            "already-retried",
            -1021,
            RequestOutcome.FAILURE_CONFIRMED,
            SideEffect.READ_ONLY,
            False,
            1,
            TimingRecovery.RESYNC_ONLY,
        ),
    )
    wrong = [
        f"{label}: expected {want.value} and got {got.value}"
        for label, code, outcome, effect, idempotent, attempt, want in cases
        if (
            got := timing_recovery(
                exchange_code=code,
                outcome=outcome,
                side_effect=effect,
                idempotent=idempotent,
                attempt=attempt,
            )
        )
        is not want
    ]
    return ClockFinding(
        check=CHECK_RECOVERY,
        passed=not wrong,
        detail="; ".join(wrong) or f"{len(cases)} recovery cases recompute, four of them refusals",
    )


def _venue_rule_finding(discipline: ClockDiscipline) -> ClockFinding:
    """Whether an admitted timestamp satisfies the venue's own published rule.

    Returns:
        The finding.

    **The strongest check here, because its expected answer is not GLOBIN's.** The
    venue publishes its processing logic as pseudo-code; this runs both evaluations
    of it against an admitted timing context, with the simulated ``serverTime``
    placed at each extreme of the stated uncertainty and then delayed by the whole
    network budget. If GLOBIN's own error bound is honest, both checks pass at both
    extremes. If it is optimistic, this fails.
    """
    domain = _fixture_domain()
    moment = _fixture_moment()
    sample = _fixture_sample(200_000, 40)
    status = evaluate(domain, samples=(sample,), age=Duration(0), discipline=discipline)
    window = RecvWindow(Decimal(5000))
    admission = admit_request(
        status,
        moment=moment,
        unit=TimestampUnit.MILLISECONDS,
        window=window,
        discipline=discipline,
    )
    if admission.context is None:
        return ClockFinding(
            check=CHECK_VENUE_RULE,
            passed=False,
            detail=f"a healthy clock did not admit: {admission.outcome.value}",
        )
    stamp_micros = admission.context.timestamp * MICROSECONDS_PER_MILLISECOND
    truth = moment.epoch_micros + sample.offset_micros
    uncertainty = sample.uncertainty_micros
    budget = discipline.network_budget.microseconds
    tolerance = FUTURE_TOLERANCE_MILLIS * MICROSECONDS_PER_MILLISECOND
    window_micros = int(window.millis * MICROSECONDS_PER_MILLISECOND)
    problems: list[str] = []
    for label, skew in (("venue-early", -uncertainty), ("venue-late", uncertainty)):
        first = truth + skew
        if not stamp_micros < first + tolerance:
            problems.append(f"{label}: the venue's first check would reject the timestamp")
        if not first - stamp_micros <= window_micros:
            problems.append(f"{label}: the venue's first window check would reject it")
        second = first + budget
        if not second - stamp_micros <= window_micros:
            problems.append(f"{label}: the venue's second, pre-matching-engine check would reject")
    return ClockFinding(
        check=CHECK_VENUE_RULE,
        passed=not problems,
        detail=(
            "; ".join(problems)
            or "both venue checks pass at both extremes of the stated uncertainty, after the "
            "whole network budget is spent"
        ),
    )


def _buckets_finding() -> ClockFinding:
    """Whether every published bucket dimension has the cardinality its bounds imply."""
    trips = {
        round_trip_bucket(value * MICROSECONDS_PER_MILLISECOND)
        for value in (0, 1, 5, 6, 10, 26, 51, 101, 251, 501, 1_001, 10_000)
    }
    offsets = {
        offset_bucket(sign * value * MICROSECONDS_PER_MILLISECOND)
        for sign in (1, -1)
        for value in (0, 1, 2, 6, 26, 101, 501, 1_001, 10_000)
    }
    problems: list[str] = []
    if len(trips) > len(ROUND_TRIP_BUCKET_BOUNDS_MILLIS) + 1:
        problems.append(f"round-trip buckets produced {len(trips)} distinct values")
    if len(offsets) > (len(OFFSET_BUCKET_BOUNDS_MILLIS) + 1) * 2:
        problems.append(f"offset buckets produced {len(offsets)} distinct values")
    return ClockFinding(
        check=CHECK_BUCKETS,
        passed=not problems,
        detail=(
            "; ".join(problems)
            or f"at most {len(ROUND_TRIP_BUCKET_BOUNDS_MILLIS) + 1} round-trip and "
            f"{(len(OFFSET_BUCKET_BOUNDS_MILLIS) + 1) * 2} offset values, as the bounds imply"
        ),
    )


def self_test(discipline: ClockDiscipline) -> ClockSelfTest:
    """Check the clock layer against its own rules and the venue's, offline.

    Args:
        discipline: The thresholds to check against.

    Returns:
        The report.

    Eight checks, and one of them is worth more than the other seven:
    :data:`CHECK_VENUE_RULE` runs the venue's own published processing pseudo-code
    against a timestamp GLOBIN admitted, at both extremes of the error bound GLOBIN
    claimed. Every other check compares two things this repository controls, which
    is what an offline self-test can do — it cannot tell an operator the venue still
    behaves as documented, and it can tell them this package still does what the
    document beside it says.
    """
    return ClockSelfTest(
        findings=(
            _estimator_finding(),
            _units_finding(),
            _state_machine_finding(discipline),
            _admission_finding(discipline),
            _recv_window_finding(),
            _recovery_finding(),
            _venue_rule_finding(discipline),
            _buckets_finding(),
        )
    )


def status_summary(statuses: Sequence[ClockStatus]) -> dict[str, object]:
    """Reduce a set of clock statuses to one JSON-safe report.

    Args:
        statuses: The statuses, in whatever order the caller holds them.

    Returns:
        A mapping carrying every status and a count per state.

    Counts are keyed by every declared state rather than only the ones observed, so
    a report from a host where nothing calibrated has the same shape as one from a
    host where everything did — which is what makes two reports comparable.
    """
    counts: dict[str, int] = {state.value: 0 for state in SyncState}
    for status in statuses:
        counts[status.state.value] += 1
    ordered = sorted(statuses, key=lambda item: item.domain.label)
    return {
        "statuses": [item.as_record() for item in ordered],
        "counts": counts,
        "synchronized": counts[SyncState.SYNCHRONIZED.value],
        "unsynchronized": len(statuses) - counts[SyncState.SYNCHRONIZED.value],
    }


def read_server_time(payload: object, unit: TimestampUnit) -> ServerTimeReading:
    """Read a venue's answer out of a decoded body.

    Args:
        payload: The decoded JSON body.
        unit: Which unit the request negotiated.

    Returns:
        The reading.

    Raises:
        ValidationError: If the body is not the documented shape.

    Re-exported from :mod:`globin.domain.clock_sync` so an adapter has one import
    for the whole use case rather than reaching into the domain for half of it.
    """
    return server_time_from(payload, unit)


__all__ = [
    "CHECK_ADMISSION",
    "CHECK_BUCKETS",
    "CHECK_ESTIMATOR",
    "CHECK_RECOVERY",
    "CHECK_RECV_WINDOW",
    "CHECK_STATE_MACHINE",
    "CHECK_UNITS",
    "CHECK_VENUE_RULE",
    "SERVER_TIME_OPERATION_SUFFIX",
    "CalibrationOutcome",
    "ClockAnchor",
    "ClockFinding",
    "ClockSelfTest",
    "DomainAvailability",
    "admit_request",
    "declared_domains",
    "read_server_time",
    "self_test",
    "status_for",
    "status_summary",
    "take_sample",
    "timing_recovery",
]
