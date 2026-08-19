"""What an operator can ask the REST transport, and what Phase 034 publishes.

Four use cases, and none of them can reach a socket except the one that says so in
its name. :func:`resolution_report` and :func:`self_test` are pure by construction
— this layer may import ``domain`` and ``ports`` and nothing else, so neither has
an object capable of a connection. :func:`run_probe` is handed a
:class:`~globin.ports.rest.RestTransport`, which is the only way a request reaches
this layer at all.

**The self-test is the offline half of the phase's evidence**, and it is a real
check rather than a formality: it recomputes the outcome classification from the
declared contract, compares the negotiation constants against their declaration in
both directions, and asserts the transport's prohibitions are all still prohibited.
A repository whose code and contract had drifted apart would fail it on a machine
with no network and no pytest.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from globin.domain.api_reality import ApiRealitySnapshot, EnvironmentName, ProductFamily
from globin.domain.rest import (
    AMBIGUOUS_EXCHANGE_CODES,
    AMBIGUOUS_STATUSES,
    MAX_LOGGED_BODY_BYTES,
    MAX_RESPONSE_BYTES,
    HttpMethod,
    QueryParameters,
    RequestOutcome,
    RequestSecurityIntent,
    ResponseEncoding,
    RestExchange,
    RestOutcomeInputs,
    RestRequest,
    SbeSchemaReference,
    SendState,
    SideEffect,
    classify,
    negotiation_headers,
)
from globin.domain.rest_contract import TransportContract
from globin.domain.rest_endpoint import EndpointResolution, ResolutionStatus, resolve, survey
from globin.errors import ValidationError
from globin.ports.rest import RestTransport

CHECK_NEGOTIATION: str = "negotiation.constants"
"""The declared header names against the ones the package actually sends."""

CHECK_AMBIGUOUS_STATUSES: str = "outcome.ambiguous_statuses"
"""The declared ambiguous statuses against the ones ``classify`` uses."""

CHECK_AMBIGUOUS_CODES: str = "outcome.ambiguous_exchange_codes"
"""The declared ambiguous venue codes against the ones ``classify`` uses."""

CHECK_CLASSIFICATION: str = "outcome.classification"
"""Every declared status, classified for a read and for a write."""

CHECK_PROHIBITIONS: str = "transport.prohibitions"
"""Every entry in the contract's prohibition table still declared prohibited."""

CHECK_LIMITS: str = "transport.limits"
"""The declared bounds against the package's own constants."""

CHECK_ENCODING: str = "encoding.canonical"
"""The canonical query encoder against fixed vectors."""

CHECK_SBE: str = "negotiation.sbe"
"""SBE negotiation offers one media type and carries the schema reference."""


@dataclass(frozen=True, slots=True)
class SelfTestFinding:
    """One check the self-test performed, and what it found."""

    check: str
    passed: bool
    detail: str = ""

    def as_record(self) -> dict[str, object]:
        """This finding as plain JSON-safe values."""
        return {"check": self.check, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class SelfTestReport:
    """Everything the offline self-test concluded."""

    findings: tuple[SelfTestFinding, ...]

    @property
    def passed(self) -> bool:
        """Whether every check passed."""
        return all(item.passed for item in self.findings)

    @property
    def failures(self) -> tuple[SelfTestFinding, ...]:
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


ENCODING_VECTORS: tuple[tuple[str, tuple[tuple[str, object], ...], str], ...] = (
    ("empty", (), ""),
    ("plain", (("symbol", "BTCUSDT"),), "symbol=BTCUSDT"),
    ("order-preserved", (("b", "2"), ("a", "1")), "b=2&a=1"),
    ("reserved-encoded", (("symbol", "BTC/USDT"),), "symbol=BTC%2FUSDT"),
    ("space-encoded", (("note", "a b"),), "note=a%20b"),
    ("unicode", (("note", "Türk"),), "note=T%C3%BCrk"),
    ("empty-value-transmitted", (("q", ""),), "q="),
    ("none-omitted", (("q", None),), ""),
    ("bool-is-a-word", (("f", True), ("g", False)), "f=true&g=false"),
    ("duplicate-preserved", (("s", "A"), ("s", "B")), "s=A&s=B"),
    ("large-integer", (("t", 1739999999999),), "t=1739999999999"),
)
"""Fixed inputs and the exact strings they must render to.

Vectors rather than properties, because these are the cases Phase 038's signer will
be computing a signature over. A property test lives beside them in
``tests/property`` and asserts the invariants; these assert the *values*, which is
what stops a well-intentioned change to the safe set going unnoticed.
"""


def _decimal_vectors() -> tuple[tuple[str, Decimal, str], ...]:
    """Decimal renderings that must not change.

    Returns:
        A label, the value, and the exact text it renders to.

    In a function rather than at module scope because a layer package performs no
    call at import, and ``Decimal("...")`` is a call.
    """
    return (
        ("scale-preserved", Decimal("0.00010000"), "0.00010000"),
        ("no-exponent", Decimal("1E-8"), "0.00000001"),
        ("trailing-zero-kept", Decimal("0.10"), "0.10"),
        ("integral", Decimal(100), "100"),
        ("negative", Decimal("-1.5"), "-1.5"),
    )


def _encoding_finding() -> SelfTestFinding:
    """Run the canonical encoding vectors.

    Returns:
        One finding naming every vector that did not render as declared.
    """
    wrong: list[str] = []
    for label, items, expected in ENCODING_VECTORS:
        rendered = QueryParameters(items=items).canonical()  # type: ignore[arg-type]
        if rendered != expected:
            wrong.append(f"{label}: expected {expected!r}, rendered {rendered!r}")
    for label, value, expected in _decimal_vectors():
        rendered = QueryParameters(items=(("v", value),)).canonical()
        if rendered != f"v={expected}":
            wrong.append(f"{label}: expected 'v={expected}', rendered {rendered!r}")
    return SelfTestFinding(
        check=CHECK_ENCODING,
        passed=not wrong,
        detail="; ".join(wrong) or f"{len(ENCODING_VECTORS) + 5} vectors render as declared",
    )


def _classification_finding(contract: TransportContract) -> SelfTestFinding:
    """Recompute every declared status against :func:`classify`.

    Args:
        contract: The declared contract.

    Returns:
        One finding naming every status whose classification contradicts its
        declaration.

    Both directions, and both side effects. A status declared ambiguous that
    classifies a mutating request as anything but
    :attr:`~globin.domain.rest.RequestOutcome.UNKNOWN` fails; so does a status
    declared unambiguous that classifies as ``UNKNOWN``. And every status must
    classify a *read* as a confirmed failure, because a read has nothing at stake —
    that half would catch a change that made ambiguity leak across the side-effect
    boundary.
    """
    wrong: list[str] = []
    for rule in contract.statuses:
        write = classify(
            RestOutcomeInputs(
                side_effect=SideEffect.MUTATING,
                send_state=SendState.COMPLETED,
                status=rule.code,
            )
        )
        read = classify(
            RestOutcomeInputs(
                side_effect=SideEffect.READ_ONLY,
                send_state=SendState.COMPLETED,
                status=rule.code,
            )
        )
        expected = (
            RequestOutcome.UNKNOWN
            if rule.ambiguous_when_mutating
            else (RequestOutcome.FAILURE_CONFIRMED)
        )
        if write is not expected:
            wrong.append(
                f"status {rule.code} is declared "
                f"{'ambiguous' if rule.ambiguous_when_mutating else 'unambiguous'} "
                f"and a write classifies as {write.value}"
            )
        if read is not RequestOutcome.FAILURE_CONFIRMED:
            wrong.append(f"status {rule.code} classifies a read as {read.value}")
    for rule in contract.exchange_codes:
        write = classify(
            RestOutcomeInputs(
                side_effect=SideEffect.MUTATING,
                send_state=SendState.COMPLETED,
                status=200,
                exchange_code=rule.code,
            )
        )
        expected = (
            RequestOutcome.UNKNOWN
            if rule.ambiguous_when_mutating
            else (RequestOutcome.FAILURE_CONFIRMED)
        )
        if write is not expected:
            wrong.append(f"code {rule.code} classifies a write as {write.value}")
    total = len(contract.statuses) + len(contract.exchange_codes)
    return SelfTestFinding(
        check=CHECK_CLASSIFICATION,
        passed=not wrong,
        detail="; ".join(wrong) or f"{total} declared rules recompute",
    )


def _sbe_finding() -> SelfTestFinding:
    """Whether SBE negotiation offers one media type and names its schema.

    Returns:
        The finding.

    The single-media-type rule is the one that keeps a stale schema id from being
    answered with JSON that GLOBIN would then believe was SBE. It is checked here as
    well as in the tests because it is a security property an operator may want to
    confirm on their own machine.
    """
    request = RestRequest(
        operation="selftest.sbe",
        method=HttpMethod.GET,
        path="/v3/time",
        encoding=ResponseEncoding.SBE,
        schema_reference=SbeSchemaReference(identifier=3, version=5),
    )
    headers = dict(negotiation_headers(request))
    problems: list[str] = []
    accept = headers.get("Accept", "")
    if "," in accept or "json" in accept.lower():
        problems.append(
            f"the SBE Accept header offers more than SBE ({accept!r}); an unsupported "
            "schema would then fall back to JSON silently"
        )
    if headers.get("X-MBX-SBE") != "3:5":
        problems.append(f"the schema reference rendered as {headers.get('X-MBX-SBE')!r}")
    return SelfTestFinding(
        check=CHECK_SBE,
        passed=not problems,
        detail="; ".join(problems) or "one media type offered, schema reference carried",
    )


def self_test(contract: TransportContract) -> SelfTestReport:
    """Check the package against its own declared contract, reaching nothing.

    Args:
        contract: The declared transport contract.

    Returns:
        The report.

    Eight checks. Every one of them compares two things this repository controls,
    which is what makes the self-test meaningful offline: it cannot tell you the
    venue still behaves as documented, and it can tell you the package still does
    what the document beside it says.
    """
    declared_limits = contract.limits
    limit_problems = [
        f"{name}: contract declares {declared}, package uses {actual}"
        for name, declared, actual in (
            ("max_response_bytes", declared_limits.get("max_response_bytes"), MAX_RESPONSE_BYTES),
            (
                "max_logged_body_bytes",
                declared_limits.get("max_logged_body_bytes"),
                MAX_LOGGED_BODY_BYTES,
            ),
        )
        if declared != actual
    ]
    statuses_agree = frozenset(AMBIGUOUS_STATUSES) == contract.ambiguous_statuses()
    codes_agree = frozenset(AMBIGUOUS_EXCHANGE_CODES) == contract.ambiguous_exchange_codes()
    permitted = sorted(name for name, value in contract.prohibitions.items() if value)
    negotiation = contract.negotiation.disagreements()
    return SelfTestReport(
        findings=(
            SelfTestFinding(
                check=CHECK_NEGOTIATION,
                passed=not negotiation,
                detail="; ".join(negotiation) or "every declared header matches the package",
            ),
            SelfTestFinding(
                check=CHECK_AMBIGUOUS_STATUSES,
                passed=statuses_agree,
                detail=(
                    ""
                    if statuses_agree
                    else (
                        f"contract declares {sorted(contract.ambiguous_statuses())}, "
                        f"package uses {sorted(AMBIGUOUS_STATUSES)}"
                    )
                ),
            ),
            SelfTestFinding(
                check=CHECK_AMBIGUOUS_CODES,
                passed=codes_agree,
                detail=(
                    ""
                    if codes_agree
                    else (
                        f"contract declares {sorted(contract.ambiguous_exchange_codes())}, "
                        f"package uses {sorted(AMBIGUOUS_EXCHANGE_CODES)}"
                    )
                ),
            ),
            _classification_finding(contract),
            SelfTestFinding(
                check=CHECK_PROHIBITIONS,
                passed=not permitted,
                detail=(
                    f"declared permitted: {', '.join(permitted)}"
                    if permitted
                    else f"{len(contract.prohibitions)} prohibitions still prohibited"
                ),
            ),
            SelfTestFinding(
                check=CHECK_LIMITS,
                passed=not limit_problems,
                detail="; ".join(limit_problems) or "declared bounds match the package",
            ),
            _encoding_finding(),
            _sbe_finding(),
        )
    )


def resolution_report(
    snapshot: ApiRealitySnapshot,
    *,
    family: ProductFamily,
    environment: EnvironmentName,
    stale_sources: Sequence[str] = (),
) -> EndpointResolution:
    """Resolve one product and environment, for an operator to read.

    Args:
        snapshot: Phase 033's registry.
        family: Which product family.
        environment: Which environment.
        stale_sources: Source identifiers past their re-check interval.

    Returns:
        The resolution or the refusal. Reaches nothing: this layer holds no object
        that could open a connection.
    """
    return resolve(snapshot, family=family, environment=environment, stale_sources=stale_sources)


def survey_report(
    snapshot: ApiRealitySnapshot, *, stale_sources: Sequence[str] = ()
) -> dict[str, object]:
    """Resolve every declared pair and summarise the result.

    Args:
        snapshot: Phase 033's registry.
        stale_sources: Source identifiers past their re-check interval.

    Returns:
        A JSON-safe mapping carrying every resolution and a count per outcome.

    **Refusals are counted, not hidden.** A survey that listed only what resolved
    would report a fail-closed registry as an empty one, when in fact the twenty-one
    pairs that refuse are the evidence the gate works.
    """
    resolutions = survey(snapshot, stale_sources=stale_sources)
    counts: dict[str, int] = {status.value: 0 for status in ResolutionStatus}
    for item in resolutions:
        counts[item.outcome.value] += 1
    return {
        "resolutions": [item.as_record() for item in resolutions],
        "counts": counts,
        "resolved": counts[ResolutionStatus.RESOLVED.value],
        "refused": len(resolutions) - counts[ResolutionStatus.RESOLVED.value],
    }


def run_probe(
    transport: RestTransport,
    resolution: EndpointResolution,
    *,
    operation: str,
    method: HttpMethod,
    path: str,
    correlation_id: str,
) -> RestExchange:
    """Send one public, read-only request and report what happened.

    Args:
        transport: How to send it.
        resolution: Where to send it.
        operation: GLOBIN's name for the request.
        method: Which verb.
        path: The path, relative to the endpoint's recorded prefix.
        correlation_id: What ties this exchange to its log records.

    Returns:
        The exchange, whatever its outcome.

    Raises:
        ValidationError: If the resolution asks for anything but a public intent.

    **Two properties are structural rather than reviewed.** The request is built
    here with :attr:`~globin.domain.rest.SideEffect.READ_ONLY` and
    :attr:`~globin.domain.rest.RequestSecurityIntent.PUBLIC` hardcoded — there is no
    parameter for either, so no caller can turn a probe into a write or into a
    credentialled request. And because the intent is public, nothing on this path
    reads the secret store at all.
    """
    if resolution.intent is not RequestSecurityIntent.PUBLIC:
        msg = (
            f"a probe was given a {resolution.intent.value} resolution; probes are public "
            "and credential-free, and there is no parameter that changes that"
        )
        raise ValidationError(msg)
    request = RestRequest(
        operation=operation,
        method=method,
        path=path,
        side_effect=SideEffect.READ_ONLY,
        intent=RequestSecurityIntent.PUBLIC,
        correlation_id=correlation_id,
    )
    return transport.send(resolution, request)
