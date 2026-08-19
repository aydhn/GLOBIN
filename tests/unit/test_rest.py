"""The REST value types, the canonical encoder, and the outcome rule.

The outcome tests are the ones that matter. Everything else here guards a
rendering; :func:`~globin.domain.rest.classify` guards the difference between *this
order did not happen* and *this order may have happened*, which is the one mistake
in this phase that could cost money.
"""

import json
from decimal import Decimal

import pytest

from globin.domain.rest import (
    AMBIGUOUS_EXCHANGE_CODES,
    AMBIGUOUS_STATUSES,
    MAX_BODY_BYTES,
    MAX_HEADERS,
    MAX_PATH_LENGTH,
    MAX_QUERY_PARAMETERS,
    MAX_RESPONSE_BYTES,
    UNRESERVED,
    BodyShape,
    ExchangeFault,
    Honoured,
    HttpMethod,
    QueryParameters,
    RateLimitReport,
    RequestBody,
    RequestOutcome,
    RequestSecurityIntent,
    ResponseEncoding,
    RestDiagnosticsRecord,
    RestExchange,
    RestOutcomeInputs,
    RestRequest,
    RestResponse,
    RestTiming,
    SbeEnvelope,
    SbeSchemaReference,
    SendState,
    SideEffect,
    TimeoutPolicy,
    TimeUnitPreference,
    TransportFailureKind,
    classify,
    encode_value,
    join_path,
    negotiation_headers,
    percent_encode,
)
from globin.errors import ValidationError


class TestPercentEncoding:
    """Every character outside the unreserved set is escaped, in uppercase hex."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            pytest.param("BTCUSDT", "BTCUSDT", id="alphanumeric-passes"),
            pytest.param("a-b_c.d~e", "a-b_c.d~e", id="the-four-unreserved-punctuation"),
            pytest.param("BTC/USDT", "BTC%2FUSDT", id="slash-is-escaped"),
            pytest.param("a b", "a%20b", id="space-is-not-a-plus"),
            pytest.param("a+b", "a%2Bb", id="plus-is-escaped"),
            pytest.param("a&b=c", "a%26b%3Dc", id="delimiters-are-escaped"),
            pytest.param("Türk", "T%C3%BCrk", id="utf-8-multibyte"),
            pytest.param("東", "%E6%9D%B1", id="utf-8-three-byte"),
            pytest.param("", "", id="empty"),
        ],
    )
    def test_the_vectors_render_exactly(self, text: str, expected: str) -> None:
        """Phase 038 signs the output of this function, so the bytes are the contract."""
        assert percent_encode(text) == expected

    def test_the_escape_is_uppercase(self) -> None:
        """RFC 3986 asks producers to normalise to uppercase, and a signature depends on it.

        A signature computed over ``%2f`` does not match one computed over ``%2F``,
        so this is load-bearing for the phase that has not been built yet rather
        than a stylistic preference.
        """
        assert percent_encode("/") == "%2F"
        assert "%2f" not in percent_encode("/")

    def test_the_unreserved_set_is_exactly_rfc_3986(self) -> None:
        """Narrower than the standard library's default, deliberately.

        ``urllib.parse.quote`` leaves ``/`` alone, which is right for a path and
        wrong for a value. The set is asserted rather than described so a widening
        edit has to change this line too.
        """
        expected = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        assert expected == UNRESERVED
        assert "/" not in UNRESERVED


class TestValueEncoding:
    """How a parameter value becomes wire text."""

    def test_a_boolean_is_a_word_and_not_a_number(self) -> None:
        """``bool`` subclasses ``int``, so the check order is load-bearing.

        An ``isinstance(value, int)`` test reached first renders ``True`` as ``1``.
        Binance documents ``true``. This is exactly the kind of correctness that
        survives review and dies in a refactor, so it gets its own test.
        """
        assert encode_value(True) == "true"
        assert encode_value(False) == "false"
        assert encode_value(1) == "1"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param(Decimal("0.00010000"), "0.00010000", id="scale-preserved"),
            pytest.param(Decimal("1E-8"), "0.00000001", id="no-exponent-notation"),
            pytest.param(Decimal("0.10"), "0.10", id="trailing-zero-kept"),
            pytest.param(Decimal(100), "100", id="integral"),
            pytest.param(Decimal("-1.5"), "-1.5", id="negative"),
            pytest.param(Decimal("1234567890.123456789"), "1234567890.123456789", id="long"),
        ],
    )
    def test_a_decimal_keeps_the_scale_it_was_given(self, value: Decimal, expected: str) -> None:
        """The venue compares a quantity against a step size.

        A scale GLOBIN normalised away is a scale the venue never agreed to, so
        ``0.10`` must not become ``0.1``.
        """
        assert encode_value(value) == expected

    @pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
    def test_a_non_finite_decimal_is_refused(self, value: Decimal) -> None:
        """There is no wire spelling of these, and a venue would reject whatever we sent."""
        with pytest.raises(ValidationError, match="finite"):
            encode_value(value)

    def test_none_means_omit_rather_than_empty(self) -> None:
        """The three states the brief asks to be told apart start here."""
        assert encode_value(None) is None
        assert encode_value("") == ""

    @pytest.mark.parametrize("value", [1.5, [1], {"a": 1}, object()])
    def test_an_unsupported_type_is_refused(self, value: object) -> None:
        """``float`` is refused with the rest, and that is the point.

        ``docs/PRECISION_POLICY.md`` forbids a binary float near a price, and a
        query parameter is precisely where one would reach the venue. A caller
        holding a float has a bug, and the boundary is where it should surface.
        """
        with pytest.raises(ValidationError, match="permitted types"):
            encode_value(value)


class TestQueryParameters:
    """Order, duplicates, and the three states of absence."""

    def test_declaration_order_is_preserved_and_never_sorted(self) -> None:
        """Phase 038 signs the string as sent; a re-ordering signer signs a fiction."""
        query = QueryParameters(items=(("b", "2"), ("a", "1"), ("c", "3")))
        assert query.canonical() == "b=2&a=1&c=3"

    def test_a_duplicate_key_survives(self) -> None:
        """A mapping would keep the last one and lose an element of a batch silently."""
        query = QueryParameters(items=(("s", "A"), ("s", "B")))
        assert query.canonical() == "s=A&s=B"
        assert query.declared() == ("s", "s")

    def test_declared_and_transmitted_differ_where_the_value_is_none(self) -> None:
        """*Never mentioned* and *mentioned and omitted* render alike and are not alike."""
        query = QueryParameters(items=(("a", "1"), ("b", None), ("c", "")))
        assert query.declared() == ("a", "b", "c")
        assert query.transmitted() == ("a", "c")
        assert query.canonical() == "a=1&c="

    def test_an_empty_set_renders_to_nothing_rather_than_a_bare_question_mark(self) -> None:
        """A URL with a trailing ``?`` is a different URL from one without it."""
        assert QueryParameters().canonical() == ""

    def test_the_record_carries_no_value(self) -> None:
        """A query parameter is where a signature and an API key travel.

        The record is what reaches a diagnostic, so it carries key names and counts
        and nothing else — safe by construction rather than by remembering to
        redact.
        """
        record = QueryParameters(
            items=(("signature", "deadbeef"), ("apiKey", "secret"))
        ).as_record()
        assert "deadbeef" not in str(record)
        assert "secret" not in str(record)
        assert record["declared_count"] == 2

    def test_an_empty_key_is_refused(self) -> None:
        """``=value`` is not a parameter."""
        with pytest.raises(ValidationError, match="empty name"):
            QueryParameters(items=(("", "1"),))

    def test_the_count_is_bounded(self) -> None:
        """A bound nobody has hit, so that the size depends on something watched."""
        too_many = tuple((f"k{index}", "1") for index in range(MAX_QUERY_PARAMETERS + 1))
        with pytest.raises(ValidationError, match="limit"):
            QueryParameters(items=too_many)


class TestPathJoining:
    """One separator at the join, and no query smuggled through the path."""

    @pytest.mark.parametrize(
        ("prefix", "path", "expected"),
        [
            pytest.param("/api", "/v3/ping", "/api/v3/ping", id="both-rooted"),
            pytest.param("api", "v3/ping", "/api/v3/ping", id="neither-rooted"),
            pytest.param("/api/", "/v3/ping", "/api/v3/ping", id="trailing-and-leading"),
            pytest.param("", "/v3/ping", "/v3/ping", id="no-prefix"),
            pytest.param("/", "/v3/ping", "/v3/ping", id="prefix-is-only-a-slash"),
        ],
    )
    def test_no_doubled_separator_is_ever_produced(
        self, prefix: str, path: str, expected: str
    ) -> None:
        """``//`` in a path is a different resource, and some gateways redirect on it."""
        assert join_path(prefix, path) == expected

    @pytest.mark.parametrize("character", ["?", "#"])
    def test_a_query_or_fragment_in_the_path_is_refused(self, character: str) -> None:
        """A parameter smuggled through the path bypasses the encoder entirely.

        That is the failure worth refusing: it would reach the venue unencoded and,
        once Phase 038 exists, outside the signature.
        """
        with pytest.raises(ValidationError, match="QueryParameters"):
            join_path("/api", f"/v3/ping{character}a=1")

    def test_an_empty_path_is_refused(self) -> None:
        """A request has to ask for something."""
        with pytest.raises(ValidationError, match="empty"):
            join_path("/api", "")


class TestOutcomeClassification:
    """The five-member outcome, and why a read and a write differ."""

    @pytest.mark.parametrize("status", sorted(AMBIGUOUS_STATUSES))
    def test_an_ambiguous_status_is_unknown_for_a_write(self, status: int) -> None:
        """Binance documents 5XX as *execution status UNKNOWN* and 409 as partial."""
        outcome = classify(
            RestOutcomeInputs(
                side_effect=SideEffect.MUTATING, send_state=SendState.COMPLETED, status=status
            )
        )
        assert outcome is RequestOutcome.UNKNOWN

    @pytest.mark.parametrize("status", sorted(AMBIGUOUS_STATUSES))
    def test_the_same_status_is_a_confirmed_failure_for_a_read(self, status: int) -> None:
        """Nothing was at stake, so there is nothing at the venue to be uncertain about.

        The half that would catch ambiguity leaking across the side-effect
        boundary, which is the change that would quietly make every price query
        unretryable.
        """
        outcome = classify(
            RestOutcomeInputs(
                side_effect=SideEffect.READ_ONLY, send_state=SendState.COMPLETED, status=status
            )
        )
        assert outcome is RequestOutcome.FAILURE_CONFIRMED

    @pytest.mark.parametrize("status", [403, 418, 429])
    def test_a_gateway_refusal_is_confirmed_even_for_a_write(self, status: int) -> None:
        """All three are refused at the edge before any matching engine saw them.

        Marking them ambiguous "to be safe" would be unsafe: Phase 043 never
        retries an ambiguous outcome, so an ordinary rate-limit rejection — the one
        failure that is always retryable — would become permanently unretryable.
        """
        outcome = classify(
            RestOutcomeInputs(
                side_effect=SideEffect.MUTATING, send_state=SendState.COMPLETED, status=status
            )
        )
        assert outcome is RequestOutcome.FAILURE_CONFIRMED

    @pytest.mark.parametrize("code", sorted(AMBIGUOUS_EXCHANGE_CODES))
    def test_an_ambiguous_venue_code_beats_a_successful_status(self, code: int) -> None:
        """``-1007`` says *execution status unknown* in the venue's own words.

        Checked before the status, because the code can accompany more than one and
        is the more specific statement.
        """
        outcome = classify(
            RestOutcomeInputs(
                side_effect=SideEffect.MUTATING,
                send_state=SendState.COMPLETED,
                status=200,
                exchange_code=code,
            )
        )
        assert outcome is RequestOutcome.UNKNOWN

    def test_bytes_that_left_with_no_answer_are_unknown_for_a_write(self) -> None:
        """The state the whole outcome model exists for."""
        outcome = classify(
            RestOutcomeInputs(side_effect=SideEffect.MUTATING, send_state=SendState.SENT)
        )
        assert outcome is RequestOutcome.UNKNOWN

    def test_bytes_that_never_left_are_never_unknown(self) -> None:
        """A connection that failed before a write provably changed nothing."""
        outcome = classify(
            RestOutcomeInputs(side_effect=SideEffect.MUTATING, send_state=SendState.NOT_SENT)
        )
        assert outcome is RequestOutcome.NOT_SENT

    def test_globins_own_refusal_is_distinct_from_the_networks(self) -> None:
        """The remedy differs: one is a configuration, the other is a cable."""
        outcome = classify(
            RestOutcomeInputs(side_effect=SideEffect.MUTATING, send_state=SendState.REFUSED)
        )
        assert outcome is RequestOutcome.REJECTED_BEFORE_SEND

    def test_an_unreadable_body_is_only_ambiguous_behind_a_success(self) -> None:
        """The correction Phase 034 made after seeing a 403 report UNKNOWN.

        A 403 carries a firewall's HTML page and is still a complete answer: the
        venue refused at the edge. Treating an unreadable body as uncertainty there
        manufactured doubt the venue had already resolved. Behind a 2xx it is real
        uncertainty, because *accepted* and *what it did* are different questions.
        """
        behind_success = classify(
            RestOutcomeInputs(
                side_effect=SideEffect.MUTATING,
                send_state=SendState.COMPLETED,
                status=200,
                answer_understood=False,
            )
        )
        behind_refusal = classify(
            RestOutcomeInputs(
                side_effect=SideEffect.MUTATING,
                send_state=SendState.COMPLETED,
                status=403,
                answer_understood=False,
            )
        )
        assert behind_success is RequestOutcome.UNKNOWN
        assert behind_refusal is RequestOutcome.FAILURE_CONFIRMED

    def test_a_success_carrying_a_venue_code_is_a_confirmed_failure(self) -> None:
        """Some documented batch endpoints refuse inside a 200 envelope."""
        outcome = classify(
            RestOutcomeInputs(
                side_effect=SideEffect.MUTATING,
                send_state=SendState.COMPLETED,
                status=200,
                exchange_code=-2010,
            )
        )
        assert outcome is RequestOutcome.FAILURE_CONFIRMED

    def test_a_read_never_returns_unknown_from_any_input(self) -> None:
        """Stated as a property rather than case by case, because it is the invariant.

        There is nothing at the venue to be uncertain about for a read, so no
        combination of status, code and send state may produce ``UNKNOWN``.
        """
        states = (SendState.REFUSED, SendState.NOT_SENT, SendState.SENT, SendState.COMPLETED)
        codes = (0, -1007, -2010)
        statuses = (0, 200, 204, 403, 409, 418, 429, 500, 502, 503, 504)
        for state in states:
            for code in codes:
                for status in statuses:
                    outcome = classify(
                        RestOutcomeInputs(
                            side_effect=SideEffect.READ_ONLY,
                            send_state=state,
                            status=status,
                            exchange_code=code,
                        )
                    )
                    assert outcome is not RequestOutcome.UNKNOWN


class TestNegotiation:
    """What GLOBIN asks for, and the one media type it deliberately does not offer."""

    def test_json_is_the_default_and_sends_no_time_unit_header(self) -> None:
        """Millisecond is the documented default and is not a documented header value."""
        request = RestRequest(operation="p", method=HttpMethod.GET, path="/v3/ping")
        headers = dict(negotiation_headers(request))
        assert headers["Accept"] == "application/json"
        assert "X-MBX-TIME-UNIT" not in headers

    def test_asking_for_milliseconds_sends_no_header_either(self) -> None:
        """``MILLISECOND`` is not a spelling the documentation offers.

        ``docs/SOURCE_POLICY.md`` forbids inventing a parameter value, and asking
        for the documented default is the same act as not asking. The preference is
        still recorded — what GLOBIN wanted is evidence — it simply reaches no wire.
        """
        request = RestRequest(
            operation="p",
            method=HttpMethod.GET,
            path="/v3/time",
            time_unit=TimeUnitPreference.MILLISECONDS,
        )
        assert "X-MBX-TIME-UNIT" not in dict(negotiation_headers(request))

    def test_asking_for_microseconds_sends_the_documented_singular_spelling(self) -> None:
        """Quoted from the venue: ``X-MBX-TIME-UNIT:MICROSECOND``. Singular."""
        request = RestRequest(
            operation="p",
            method=HttpMethod.GET,
            path="/v3/time",
            time_unit=TimeUnitPreference.MICROSECONDS,
        )
        assert dict(negotiation_headers(request))["X-MBX-TIME-UNIT"] == "MICROSECOND"

    def test_sbe_offers_one_media_type_and_never_two(self) -> None:
        """The security property of the SBE half, asserted rather than reviewed.

        The venue documents that an ``Accept`` naming both media types "will fall
        back to JSON" when the schema is unsupported. GLOBIN would then hold a JSON
        body while its own record said SBE — an optimistic acceptance of a
        capability that was not available. Offering one media type deletes the
        branch rather than handling it.
        """
        request = RestRequest(
            operation="p",
            method=HttpMethod.GET,
            path="/v3/time",
            encoding=ResponseEncoding.SBE,
            schema_reference=SbeSchemaReference(identifier=3, version=5),
        )
        headers = dict(negotiation_headers(request))
        assert headers["Accept"] == "application/sbe"
        assert "json" not in headers["Accept"]
        assert "," not in headers["Accept"]

    def test_the_sbe_schema_renders_as_the_documented_format(self) -> None:
        """``<ID>:<VERSION>``, which is what Phase 033's ``SchemaVersion.label`` already was."""
        request = RestRequest(
            operation="p",
            method=HttpMethod.GET,
            path="/v3/time",
            encoding=ResponseEncoding.SBE,
            schema_reference=SbeSchemaReference(identifier=3, version=5),
        )
        assert dict(negotiation_headers(request))["X-MBX-SBE"] == "3:5"

    def test_headers_are_sorted_so_two_identical_requests_are_byte_identical(self) -> None:
        """What makes a canonical request canonical."""
        request = RestRequest(
            operation="p", method=HttpMethod.GET, path="/v3/ping", headers=(("Z", "1"), ("A", "2"))
        )
        names = [name for name, _ in negotiation_headers(request)]
        assert names == sorted(names)

    def test_the_user_agent_carries_no_version(self) -> None:
        """It is sent to a third party on every request.

        The cheapest possible place to leak which build an operator is running, so
        it carries a name and nothing else.
        """
        request = RestRequest(operation="p", method=HttpMethod.GET, path="/v3/ping")
        assert dict(negotiation_headers(request))["User-Agent"] == "GLOBIN"


class TestRestRequest:
    """What a request refuses to be."""

    def test_sbe_without_a_schema_cannot_be_constructed(self) -> None:
        """The venue cannot answer a request that names no schema."""
        with pytest.raises(ValidationError, match="names no schema"):
            RestRequest(
                operation="p",
                method=HttpMethod.GET,
                path="/v3/time",
                encoding=ResponseEncoding.SBE,
            )

    def test_a_schema_with_json_cannot_be_constructed(self) -> None:
        """The reference would be sent and ignored, which is a lie in the record."""
        with pytest.raises(ValidationError, match="would be sent and ignored"):
            RestRequest(
                operation="p",
                method=HttpMethod.GET,
                path="/v3/time",
                schema_reference=SbeSchemaReference(identifier=3, version=5),
            )

    @pytest.mark.parametrize("method", [HttpMethod.GET, HttpMethod.HEAD])
    def test_a_body_on_a_bodiless_method_is_refused(self, method: HttpMethod) -> None:
        """A body the venue will ignore is a body somebody expected to be read."""
        from globin.domain.rest import RequestBody

        with pytest.raises(ValidationError, match="carries a body"):
            RestRequest(
                operation="p",
                method=method,
                path="/v3/ping",
                body=RequestBody(content=b"{}", content_type="application/json"),
            )

    def test_an_over_long_operation_name_is_refused(self) -> None:
        """An operation name becomes a metric attribute, so it is bounded."""
        with pytest.raises(ValidationError, match="limit"):
            RestRequest(operation="x" * 200, method=HttpMethod.GET, path="/v3/ping")

    def test_the_canonical_target_is_stable_across_calls(self) -> None:
        """The property Phase 038's signer depends on."""
        request = RestRequest(
            operation="p",
            method=HttpMethod.GET,
            path="/v3/klines",
            query=QueryParameters(items=(("symbol", "BTCUSDT"), ("limit", 500))),
        )
        first = request.canonical_target("/api")
        assert first == request.canonical_target("/api")
        assert first == "/api/v3/klines?symbol=BTCUSDT&limit=500"

    def test_a_request_with_no_query_renders_no_question_mark(self) -> None:
        """*No parameters* and *an empty set of parameters* render alike."""
        request = RestRequest(operation="p", method=HttpMethod.GET, path="/v3/ping")
        assert request.canonical_target("/api") == "/api/v3/ping"


class TestTimeoutPolicy:
    """Four declared bounds against a client that applies one."""

    def test_the_policy_says_which_bounds_are_real(self) -> None:
        """A measurement that was not taken is never reported as taken.

        Phase 024's rule, restated: the standard library's client applies a single
        timeout, so three of the four fields are declared rather than enforced and
        the policy says so instead of letting a caller assume otherwise.
        """
        honoured = TimeoutPolicy().honoured()
        assert honoured["pool_seconds"] == Honoured.NOT_SUPPORTED.value
        assert honoured["read_seconds"] == Honoured.SUBSUMED.value

    def test_the_effective_timeout_is_the_largest_bound(self) -> None:
        """Taking the smallest would cut a legitimate slow read short."""
        policy = TimeoutPolicy(connect_seconds=1.0, read_seconds=30.0, write_seconds=2.0)
        assert policy.effective_seconds == 30.0

    @pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan")])
    def test_a_bound_that_would_not_bound_is_refused(self, value: float) -> None:
        """A timeout of zero or infinity is a request that waits for ever."""
        with pytest.raises(ValidationError):
            TimeoutPolicy(read_seconds=value)


class TestRestExchange:
    """The record that must not lie about itself."""

    def _record(self) -> RestDiagnosticsRecord:
        return RestDiagnosticsRecord(
            correlation_id="c1",
            operation="p",
            family="spot",
            environment="testnet",
            role="primary",
            host="h",
            method="GET",
            intent="public",
            side_effect="read_only",
            encoding="json",
            time_unit="provider_default",
            send_state="completed",
            outcome="success_confirmed",
        )

    def test_confirmed_success_without_a_response_is_refused(self) -> None:
        """A success with nothing to show for it is a claim nobody can check."""
        with pytest.raises(ValidationError, match="carries no response"):
            RestExchange(
                operation="p",
                outcome=RequestOutcome.SUCCESS_CONFIRMED,
                send_state=SendState.COMPLETED,
                diagnostics=self._record(),
            )

    def test_a_failure_and_a_response_together_are_refused(self) -> None:
        """A transport fault means no answer was understood; both cannot be true."""
        with pytest.raises(ValidationError, match="both"):
            RestExchange(
                operation="p",
                outcome=RequestOutcome.FAILURE_CONFIRMED,
                send_state=SendState.SENT,
                diagnostics=self._record(),
                failure=TransportFailureKind.CONNECTION_RESET,
                detail="reset",
                response=RestResponse(
                    status=200, shape=BodyShape.EMPTY, outcome=RequestOutcome.SUCCESS_CONFIRMED
                ),
            )

    def test_at_risk_is_exactly_the_unknown_outcome(self) -> None:
        """A named property so the check reads the same everywhere it appears."""
        unknown = RestExchange(
            operation="p",
            outcome=RequestOutcome.UNKNOWN,
            send_state=SendState.SENT,
            diagnostics=self._record(),
        )
        confirmed = RestExchange(
            operation="p",
            outcome=RequestOutcome.FAILURE_CONFIRMED,
            send_state=SendState.COMPLETED,
            diagnostics=self._record(),
        )
        assert unknown.at_risk is True
        assert confirmed.at_risk is False


class TestRecordsCarryNothingSensitive:
    """What reaches a diagnostic, asserted rather than reviewed."""

    def test_the_diagnostic_record_has_no_field_for_a_url_or_a_header(self) -> None:
        """Safe by construction rather than by remembering to redact.

        Redaction downstream is a second line of defence over a record that already
        carries nothing to redact, which is why the absence is asserted on the
        *shape* rather than on one example.
        """
        record = RestDiagnosticsRecord(
            correlation_id="c1",
            operation="spot.ping",
            family="spot",
            environment="testnet",
            role="primary",
            host="testnet.example",
            method="GET",
            intent="public",
            side_effect="read_only",
            encoding="json",
            time_unit="provider_default",
            send_state="completed",
            outcome="success_confirmed",
        ).as_record()
        for forbidden in ("url", "query", "headers", "body", "signature", "api_key"):
            assert forbidden not in record

    def test_a_correlation_id_is_required(self) -> None:
        """An event nothing can be tied to is an event nobody can follow."""
        with pytest.raises(ValidationError, match="correlation"):
            RestDiagnosticsRecord(
                correlation_id="",
                operation="p",
                family="spot",
                environment="testnet",
                role="primary",
                host="h",
                method="GET",
                intent="public",
                side_effect="read_only",
                encoding="json",
                time_unit="provider_default",
                send_state="completed",
                outcome="success_confirmed",
            )

    def test_an_sbe_envelope_publishes_a_size_and_never_its_payload(self) -> None:
        """Opaque by construction: there is no accessor that decodes anything."""
        record = SbeEnvelope(payload=b"\x00\x01secret-bytes").as_record()
        assert record["byte_count"] == 14
        assert "secret" not in str(record)


class TestSmallValueTypes:
    """The remaining types, each refusing the one thing it must."""

    def test_an_exchange_fault_must_name_a_code(self) -> None:
        """A fault that reports no fault is not a fault."""
        with pytest.raises(ValidationError, match="no code"):
            ExchangeFault(code=0)

    def test_a_negative_elapsed_time_is_refused(self) -> None:
        """It would mean a monotonic clock went backwards, which is a defect."""
        with pytest.raises(ValidationError, match="negative"):
            RestTiming(elapsed_nanoseconds=-1)

    @pytest.mark.parametrize("field", ["identifier", "version"])
    def test_a_negative_schema_component_is_refused(self, field: str) -> None:
        """No published schema has one."""
        with pytest.raises(ValidationError, match="negative"):
            SbeSchemaReference(**{"identifier": 1, "version": 1, field: -1})

    def test_an_empty_rate_limit_report_is_absence_and_not_zero(self) -> None:
        """A venue that said nothing about weight did not say the weight was zero."""
        report = RateLimitReport()
        assert report.retry_after_seconds is None
        assert report.used_weight == ()

    def test_a_response_reports_an_empty_limit_report_rather_than_none(self) -> None:
        """Callers stop caring which of the two happened."""
        response = RestResponse(
            status=200, shape=BodyShape.EMPTY, outcome=RequestOutcome.SUCCESS_CONFIRMED
        )
        assert response.limits.used_weight == ()

    def test_a_request_reports_a_default_timeout_policy_rather_than_none(self) -> None:
        """Same reason, and the same shape."""
        request = RestRequest(
            operation="p",
            method=HttpMethod.GET,
            path="/v3/ping",
            intent=RequestSecurityIntent.PUBLIC,
        )
        assert request.timeout_policy.effective_seconds > 0
        assert request.parameters.canonical() == ""


class TestTheRemainingRefusalsAndRecords:
    """The branches a correct caller never reaches, and the records nothing else reads.

    Each of these is either a narrowing that would silently accept the wrong type if
    it broke, or a `as_record` that has to survive `json.dumps` because it reaches
    the Phase 034 manifest.
    """

    def test_a_non_numeric_timeout_is_refused(self) -> None:
        """A string where a duration belongs would bound nothing at all."""
        with pytest.raises(ValidationError, match="must be a number"):
            TimeoutPolicy(read_seconds="ten")  # type: ignore[arg-type]

    def test_a_boolean_timeout_is_refused(self) -> None:
        """``bool`` is an ``int`` subclass, so ``True`` would read as one second."""
        with pytest.raises(ValidationError, match="must be a number"):
            TimeoutPolicy(read_seconds=True)

    def test_the_timeout_policy_publishes_a_record(self) -> None:
        """Four durations and, beside them, which are enforced."""
        record = TimeoutPolicy().as_record()
        assert json.loads(json.dumps(record))["effective_seconds"] > 0
        honoured = record["honoured"]
        assert isinstance(honoured, dict)
        assert set(honoured) == {
            "connect_seconds",
            "read_seconds",
            "write_seconds",
            "pool_seconds",
        }

    def test_an_over_long_path_is_refused(self) -> None:
        """Bounded so the size depends on something somebody is watching."""
        with pytest.raises(ValidationError, match="limit is"):
            join_path("/api", "/" + "x" * MAX_PATH_LENGTH)

    def test_a_non_integer_schema_component_is_refused(self) -> None:
        """A schema reference is two integers, and a string is not one."""
        with pytest.raises(ValidationError, match="must be an integer"):
            SbeSchemaReference(identifier="3", version=5)  # type: ignore[arg-type]

    def test_the_schema_reference_publishes_a_record(self) -> None:
        """It reaches the resolution record and therefore the manifest."""
        assert SbeSchemaReference(identifier=3, version=5).as_record() == {
            "identifier": 3,
            "version": 5,
        }

    def test_an_over_large_body_is_refused(self) -> None:
        """A body nothing bounds is a body that reaches a socket unmeasured."""
        with pytest.raises(ValidationError, match="limit is"):
            RequestBody(content=b"x" * (MAX_BODY_BYTES + 1), content_type="application/json")

    def test_a_body_that_is_not_bytes_is_refused(self) -> None:
        """The body is what gets signed, so an object re-serialised later is not it."""
        with pytest.raises(ValidationError, match="a request body is str"):
            RequestBody(content="{}", content_type="application/json")  # type: ignore[arg-type]

    def test_the_body_record_carries_a_size_and_never_the_content(self) -> None:
        """A signed request's body is exactly where credential material would be."""
        record = RequestBody(content=b'{"secret":"x"}', content_type="application/json").as_record()
        assert record == {"content_type": "application/json", "byte_count": 14}
        assert "secret" not in str(record)

    def test_a_request_with_no_operation_is_refused(self) -> None:
        """An operation name becomes a metric attribute; an empty one is not a name."""
        with pytest.raises(ValidationError, match="no operation name"):
            RestRequest(operation="", method=HttpMethod.GET, path="/v3/ping")

    def test_too_many_headers_are_refused(self) -> None:
        """Bounded for the reason every other collection here is."""
        headers = tuple((f"H{index}", "v") for index in range(MAX_HEADERS + 1))
        with pytest.raises(ValidationError, match="limit is"):
            RestRequest(operation="p", method=HttpMethod.GET, path="/v3/ping", headers=headers)

    def test_a_body_content_type_reaches_the_headers(self) -> None:
        """A body the venue cannot type is a body it will refuse."""
        request = RestRequest(
            operation="p",
            method=HttpMethod.POST,
            path="/v3/order",
            body=RequestBody(content=b"{}", content_type="application/json"),
        )
        assert dict(negotiation_headers(request))["Content-Type"] == "application/json"

    def test_an_over_large_sbe_payload_is_refused(self) -> None:
        """The same cap the transport applies, asserted where the envelope is built."""
        with pytest.raises(ValidationError, match="limit is"):
            SbeEnvelope(payload=b"x" * (MAX_RESPONSE_BYTES + 1))

    def test_an_exchange_reporting_a_failure_must_explain_it(self) -> None:
        """A fault with no message is one nobody can act on."""
        record = RestDiagnosticsRecord(
            correlation_id="c1",
            operation="p",
            family="spot",
            environment="testnet",
            role="primary",
            host="h",
            method="GET",
            intent="public",
            side_effect="read_only",
            encoding="json",
            time_unit="provider_default",
            send_state="sent",
            outcome="unknown",
        )
        with pytest.raises(ValidationError, match="explains nothing"):
            RestExchange(
                operation="p",
                outcome=RequestOutcome.UNKNOWN,
                send_state=SendState.SENT,
                diagnostics=record,
                failure=TransportFailureKind.CONNECTION_RESET,
            )

    def test_every_record_survives_json(self) -> None:
        """All of them reach the Phase 034 manifest, so all of them must serialise."""
        request = RestRequest(
            operation="p",
            method=HttpMethod.GET,
            path="/v3/ping",
            query=QueryParameters(items=(("a", "1"),)),
        )
        response = RestResponse(
            status=200,
            shape=BodyShape.OBJECT,
            outcome=RequestOutcome.SUCCESS_CONFIRMED,
            binary=SbeEnvelope(payload=b"x"),
            fault=ExchangeFault(code=-1121, message="Invalid symbol."),
            rate_limits=RateLimitReport(retry_after_seconds=17, used_weight=(("1M", 42),)),
            timing=RestTiming(elapsed_nanoseconds=5),
        )
        for record in (request.as_record(), response.as_record()):
            assert json.loads(json.dumps(record))
