"""The self-test's failing branches, and the probe path's one refusal.

The self-test passes against the committed contract, which
`tests/contract/test_rest_contract.py` asserts. What is here is the other
direction: each check driven against a contract that has *drifted*, because a
check that could not fail is a check nobody should read.

The probe is exercised through a hand-written double satisfying
:class:`~globin.ports.rest.RestTransport`. No socket is opened, and the double is
hand-written rather than mocked per ``docs/TESTING_STRATEGY.md``.
"""

from dataclasses import replace

import pytest

from globin.application.rest import (
    CHECK_AMBIGUOUS_CODES,
    CHECK_AMBIGUOUS_STATUSES,
    CHECK_CLASSIFICATION,
    CHECK_LIMITS,
    CHECK_NEGOTIATION,
    CHECK_PROHIBITIONS,
    SelfTestFinding,
    SelfTestReport,
    run_probe,
    self_test,
)
from globin.domain.api_reality import ProductFamily, SurfaceCapability
from globin.domain.rest import (
    BodyShape,
    EndpointRole,
    HttpMethod,
    RequestOutcome,
    RequestSecurityIntent,
    ResponseEncoding,
    RestDiagnosticsRecord,
    RestExchange,
    RestRequest,
    RestResponse,
    SendState,
    SideEffect,
)
from globin.domain.rest_contract import (
    NegotiationDeclaration,
    ProbeDescriptor,
    StatusRule,
    TransportContract,
)
from globin.domain.rest_endpoint import EndpointResolution, ResolutionStatus, ResolvedEndpoint
from globin.errors import ValidationError


def _negotiation(**overrides: str) -> NegotiationDeclaration:
    """A declaration that agrees with the package unless a test disagrees with it."""
    fields = {
        "accept_header": "Accept",
        "media_type_json": "application/json",
        "media_type_sbe": "application/sbe",
        "sbe_schema_header": "X-MBX-SBE",
        "sbe_schema_format": "<ID>:<VERSION>",
        "time_unit_header": "X-MBX-TIME-UNIT",
        "time_unit_microsecond": "MICROSECOND",
        "retry_after_header": "Retry-After",
        "used_weight_prefix": "X-MBX-USED-WEIGHT-",
        "order_count_prefix": "X-MBX-ORDER-COUNT-",
        "source": "s",
        "sbe_source": "s",
    }
    fields.update(overrides)
    return NegotiationDeclaration(**fields)


def _contract(**overrides: object) -> TransportContract:
    """A contract that agrees with the package unless a test disagrees with it."""
    statuses = tuple(
        StatusRule(
            code=code,
            meaning="x",
            ambiguous_when_mutating=ambiguous,
            reason="y",
            source="s",
        )
        for code, ambiguous in (
            (409, True),
            (500, True),
            (502, True),
            (503, True),
            (504, True),
            (403, False),
            (418, False),
            (429, False),
        )
    )
    fields: dict[str, object] = {
        "negotiation": _negotiation(),
        "probes": (),
        "statuses": statuses,
        "exchange_codes": (
            StatusRule(
                code=-1006,
                meaning="UNEXPECTED_RESP",
                ambiguous_when_mutating=True,
                reason="y",
                source="s",
            ),
            StatusRule(
                code=-1021,
                meaning="INVALID_TIMESTAMP",
                ambiguous_when_mutating=False,
                reason="y",
                source="s",
            ),
            StatusRule(
                code=-1007,
                meaning="TIMEOUT",
                ambiguous_when_mutating=True,
                reason="y",
                source="s",
            ),
        ),
        "limits": {"max_response_bytes": 8388608, "max_logged_body_bytes": 512},
        "prohibitions": {"automatic_retry": False},
        "phase": 34,
        "observed_on": "2026-08-19",
    }
    fields.update(overrides)
    return TransportContract(**fields)  # type: ignore[arg-type]


def _finding(check: str, report: SelfTestReport) -> SelfTestFinding:
    """One named finding out of a report."""
    return next(item for item in report.findings if item.check == check)


class TestTheSelfTestPasses:
    """The baseline, so every failure below means something."""

    def test_a_contract_that_agrees_passes_every_check(self) -> None:
        """Eight checks, all comparing two things this repository controls."""
        report = self_test(_contract())
        assert report.passed
        assert report.failures == ()
        assert len(report.findings) == 8

    def test_the_record_is_json_safe(self) -> None:
        """It goes into the manifest."""
        import json

        assert json.loads(json.dumps(self_test(_contract()).as_record()))["passed"] is True


class TestEveryCheckCanFail:
    """A check that could not fail is a check nobody should read."""

    def test_a_drifted_header_fails_the_negotiation_check(self) -> None:
        """A contract naming a header the package does not send is a lie."""
        contract = _contract(negotiation=_negotiation(sbe_schema_header="X-WRONG"))
        report = self_test(contract)
        assert not report.passed
        assert not _finding(CHECK_NEGOTIATION, report).passed

    def test_a_missing_ambiguous_status_fails(self) -> None:
        """The declared set and the classifier's set must agree exactly."""
        statuses = tuple(item for item in _contract().statuses if item.code != 503)
        report = self_test(_contract(statuses=statuses))
        assert not _finding(CHECK_AMBIGUOUS_STATUSES, report).passed

    def test_a_missing_ambiguous_code_fails(self) -> None:
        """Same, for the venue codes."""
        report = self_test(_contract(exchange_codes=()))
        assert not _finding(CHECK_AMBIGUOUS_CODES, report).passed

    def test_a_status_declared_the_wrong_way_round_fails_classification(self) -> None:
        """The check that recomputes ``classify`` from the declaration.

        A 503 declared unambiguous, with a classifier that still calls it
        ``UNKNOWN``, is the drift this exists to catch — and it is the direction
        that matters, because it would mean somebody had loosened the document
        while the code still fails closed.
        """
        statuses = tuple(
            replace(item, ambiguous_when_mutating=False) if item.code == 503 else item
            for item in _contract().statuses
        )
        report = self_test(_contract(statuses=statuses))
        finding = _finding(CHECK_CLASSIFICATION, report)
        assert not finding.passed
        assert "503" in finding.detail

    def test_a_venue_code_declared_the_wrong_way_round_fails_classification(self) -> None:
        """The same, on the code half."""
        codes = (
            StatusRule(
                code=-1007,
                meaning="TIMEOUT",
                ambiguous_when_mutating=False,
                reason="y",
                source="s",
            ),
        )
        report = self_test(_contract(exchange_codes=codes))
        assert not _finding(CHECK_CLASSIFICATION, report).passed

    def test_a_drifted_limit_fails(self) -> None:
        """A declared bound the package does not enforce is a number nobody applies."""
        report = self_test(_contract(limits={"max_response_bytes": 1}))
        finding = _finding(CHECK_LIMITS, report)
        assert not finding.passed
        assert "max_response_bytes" in finding.detail

    def test_a_prohibition_declared_permitted_cannot_reach_the_check(self) -> None:
        """The type refuses it first, which is stronger than a check that reports it.

        ``TransportContract`` will not hold a ``true`` prohibition, so the
        self-test's own prohibition check can only ever see a valid table. Both
        guards are kept: one refuses at construction and one reports on a contract
        that somehow reached the caller anyway.
        """
        with pytest.raises(ValidationError, match="permitted"):
            _contract(prohibitions={"automatic_retry": True})
        assert _finding(CHECK_PROHIBITIONS, self_test(_contract())).passed


class _RecordingTransport:
    """A hand-written :class:`~globin.ports.rest.RestTransport` that opens nothing.

    Records what it was asked to send, which is what the probe tests assert on.
    """

    def __init__(self) -> None:
        """Start with nothing sent."""
        self.opened = False
        self.closed = False
        self.sent: list[RestRequest] = []

    def open(self) -> None:
        """Mark the transport ready."""
        self.opened = True

    def close(self) -> None:
        """Mark the transport closed."""
        self.closed = True

    def send(self, resolution: EndpointResolution, request: RestRequest) -> RestExchange:
        """Record the request and report a confirmed success.

        The response is real rather than ``None``, because ``RestExchange`` refuses
        a confirmed success that carries nothing — which it caught on this double's
        first draft, and which is the type doing exactly its job.
        """
        del resolution
        self.sent.append(request)
        return RestExchange(
            operation=request.operation,
            outcome=RequestOutcome.SUCCESS_CONFIRMED,
            send_state=SendState.COMPLETED,
            diagnostics=RestDiagnosticsRecord(
                correlation_id=request.correlation_id,
                operation=request.operation,
                family="spot",
                environment="testnet",
                role="primary",
                host="h",
                method=request.method.value,
                intent=request.intent.value,
                side_effect=request.side_effect.value,
                encoding=request.encoding.value,
                time_unit=request.time_unit.value,
                send_state=SendState.COMPLETED.value,
                outcome=RequestOutcome.SUCCESS_CONFIRMED.value,
                status=200,
            ),
            response=RestResponse(
                status=200,
                shape=BodyShape.OBJECT,
                outcome=RequestOutcome.SUCCESS_CONFIRMED,
                payload={},
            ),
        )


def _resolution(intent: RequestSecurityIntent = RequestSecurityIntent.PUBLIC) -> EndpointResolution:
    """A resolution pointing at a host nothing will reach."""
    endpoint = ResolvedEndpoint(
        family="spot",
        environment="testnet",
        role=EndpointRole.PRIMARY,
        url="https://nowhere.invalid/api",
        host="nowhere.invalid",
        port=0,
        path_prefix="/api",
        capabilities=("market_data",),
        auth="none",
        carries_real_capital=False,
        source="s",
    )
    return EndpointResolution(
        outcome=ResolutionStatus.RESOLVED,
        requested_family="spot",
        requested_environment="testnet",
        requested_capability="market_data",
        intent=intent,
        encoding=ResponseEncoding.JSON,
        endpoint=endpoint,
    )


class TestTheProbePath:
    """Two properties that are structural rather than reviewed."""

    def test_a_probe_is_always_read_only_and_always_public(self) -> None:
        """Hardcoded, with no parameter for either.

        No caller can turn a probe into a write or into a credentialled request,
        because there is nothing to pass that would do it.
        """
        transport = _RecordingTransport()
        run_probe(
            transport,
            _resolution(),
            operation="spot.ping",
            method=HttpMethod.GET,
            path="/v3/ping",
            correlation_id="c1",
        )
        sent = transport.sent[0]
        assert sent.side_effect is SideEffect.READ_ONLY
        assert sent.intent is RequestSecurityIntent.PUBLIC

    def test_a_credentialled_resolution_is_refused(self) -> None:
        """The guard on the other side, so no external run can be talked into one."""
        transport = _RecordingTransport()
        with pytest.raises(ValidationError, match="credential-free"):
            run_probe(
                transport,
                _resolution(RequestSecurityIntent.SIGNED),
                operation="spot.ping",
                method=HttpMethod.GET,
                path="/v3/ping",
                correlation_id="c1",
            )
        assert transport.sent == []

    def test_the_exchange_is_returned_unchanged(self) -> None:
        """The application layer adds nothing to what the transport concluded."""
        transport = _RecordingTransport()
        exchange = run_probe(
            transport,
            _resolution(),
            operation="spot.ping",
            method=HttpMethod.GET,
            path="/v3/ping",
            correlation_id="c1",
        )
        assert exchange.outcome is RequestOutcome.SUCCESS_CONFIRMED
        assert exchange.diagnostics.correlation_id == "c1"


class TestProbeDescriptorsAreDataRatherThanCode:
    """A family with no declared probe gets nothing, never a guessed path."""

    def test_a_declared_probe_is_found_by_family_and_operation(self) -> None:
        """Both halves of the key, so two products may share an operation suffix."""
        probe = ProbeDescriptor(
            family=ProductFamily("spot"),
            operation="spot.ping",
            method=HttpMethod.GET,
            path="/v3/ping",
            capability=SurfaceCapability.MARKET_DATA,
            weight=1,
            security="NONE",
            notes="x",
            source="s",
        )
        contract = _contract(probes=(probe,))
        assert contract.probe(ProductFamily("spot"), "spot.ping") is probe
        assert contract.probe(ProductFamily("spot"), "spot.time") is None
        assert contract.probe(ProductFamily("options"), "spot.ping") is None
