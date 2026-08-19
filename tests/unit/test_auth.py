"""The authentication domain: what may be constructed, and what may not.

Everything here is pure. No key is loaded, no signature is computed and no store is
consulted — those belong to `test_signing.py` and `test_auth_application.py`. What
this file establishes is that the *types* refuse the states that would matter.

The refusals worth reading twice, because each rules out a request the venue would
reject or a record that would leak:

- a payload that already carries a signature, which would mean signing something
  claiming to be signed;
- a request signed twice, which would leave the venue two signatures and one
  parameter name;
- a credential whose two references are the same, which would put the private
  material in a header;
- a `RecvWindow` built from a `float`, which cannot hold the third decimal place
  the venue documents;
- an `AuthenticatedRequest` with no API key header, which is a signature
  identifying nobody.
"""

from decimal import Decimal

import pytest

from globin.domain.api_reality import ApiKeyType
from globin.domain.auth import (
    API_KEY_HEADER,
    MAX_SIGNATURE_LENGTH,
    SIGNATURE_PARAMETER,
    AuthenticatedRequest,
    AuthStatus,
    CredentialBinding,
    GeneratedSignature,
    ParameterPlacement,
    SecurityType,
    SignatureAlgorithm,
    SignatureEncoding,
    SigningPayload,
    SigningProfile,
    algorithm_for,
    api_key_fingerprint,
    asymmetric,
    encoded_signature,
    encoding_for,
    key_type_for,
    signed_parameters,
    signing_payload,
    spot_profile,
    timed_parameters,
)
from globin.domain.auth_timing import (
    MAX_RECV_WINDOW_DECIMALS,
    RecvWindow,
    TimestampUnit,
    default_recv_window,
    max_recv_window,
    parse_recv_window,
    stamp,
)
from globin.domain.clock import instant
from globin.domain.identifiers import EnvironmentId
from globin.domain.observability import REDACTED
from globin.domain.rest import (
    HttpMethod,
    QueryParameters,
    RequestBody,
    RestRequest,
)
from globin.domain.secrets import SecretKind, SecretReference
from globin.errors import ValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reference(name: str, kind: SecretKind = SecretKind.API_KEY) -> SecretReference:
    """A secret reference for a testnet credential.

    Args:
        name: Its logical name.
        kind: What sort of material it names.

    Returns:
        The reference. Ordinary data by design, so nothing here is sensitive.
    """
    return SecretReference(environment=EnvironmentId("testnet"), kind=kind, name=name)


def _binding(key_type: ApiKeyType = ApiKeyType.HMAC) -> CredentialBinding:
    """A credential binding naming two distinct references.

    Args:
        key_type: Which key type it declares.

    Returns:
        The binding.
    """
    return CredentialBinding(
        api_key=_reference("venue_key"),
        material=_reference("venue_secret", SecretKind.API_SECRET),
        key_type=key_type,
    )


def _signature(
    algorithm: SignatureAlgorithm = SignatureAlgorithm.HMAC_SHA256,
) -> GeneratedSignature:
    """A well-formed signature of the right shape for an algorithm.

    Args:
        algorithm: Which algorithm to claim.

    Returns:
        The signature. Computed by nothing — this file tests types, not signers.
    """
    if encoding_for(algorithm) is SignatureEncoding.HEX:
        return GeneratedSignature("ab" * 32, algorithm)
    return GeneratedSignature("QUJD" * 16, algorithm)


# ---------------------------------------------------------------------------
# Security types
# ---------------------------------------------------------------------------


def test_only_none_needs_neither_a_key_nor_a_signature() -> None:
    """The documented rule: everything but NONE is SIGNED."""
    assert not SecurityType.NONE.requires_api_key
    assert not SecurityType.NONE.requires_signature
    for member in SecurityType:
        if member is not SecurityType.NONE:
            assert member.requires_api_key, member
            assert member.requires_signature, member


def test_a_public_request_carries_a_public_intent() -> None:
    """So the transport's own gate refuses a credential on this path."""
    assert SecurityType.NONE.intent.value == "public"
    assert SecurityType.USER_STREAM.intent.value == "signed"


# ---------------------------------------------------------------------------
# The algorithm mapping
# ---------------------------------------------------------------------------


def test_every_key_type_maps_to_an_algorithm_and_back() -> None:
    """A lookup rather than a branch, so the lookup is total in both directions."""
    for key_type in ApiKeyType:
        assert key_type_for(algorithm_for(key_type)) is key_type


def test_every_algorithm_has_a_documented_encoding() -> None:
    """Hex for HMAC and base64 for both asymmetric types."""
    assert encoding_for(SignatureAlgorithm.HMAC_SHA256) is SignatureEncoding.HEX
    assert encoding_for(SignatureAlgorithm.RSA_PKCS1V15_SHA256) is SignatureEncoding.BASE64
    assert encoding_for(SignatureAlgorithm.ED25519) is SignatureEncoding.BASE64


def test_exactly_one_algorithm_is_symmetric() -> None:
    """The distinction that decides key loading, case sensitivity and which library is needed."""
    assert not asymmetric(SignatureAlgorithm.HMAC_SHA256)
    assert asymmetric(SignatureAlgorithm.RSA_PKCS1V15_SHA256)
    assert asymmetric(SignatureAlgorithm.ED25519)


def test_a_profile_pairing_the_wrong_encoding_cannot_be_built() -> None:
    """A typo here would reach the venue as a signature it cannot read."""
    with pytest.raises(ValidationError, match="the documentation pairs it with"):
        SigningProfile(
            algorithm=SignatureAlgorithm.ED25519,
            encoding=SignatureEncoding.HEX,
            placement=ParameterPlacement.QUERY_THEN_BODY,
        )


def test_the_spot_profile_signs_query_then_body() -> None:
    """The venue's rule stated exactly, and reducing to query-only for a GET."""
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    assert profile.placement is ParameterPlacement.QUERY_THEN_BODY
    assert profile.signature_parameter == SIGNATURE_PARAMETER
    assert profile.api_key_header == API_KEY_HEADER


# ---------------------------------------------------------------------------
# Credential bindings
# ---------------------------------------------------------------------------


def test_a_binding_naming_one_reference_twice_is_refused() -> None:
    """The key identifier travels in a header on every request; the material never does."""
    reference = _reference("same")
    with pytest.raises(ValidationError, match="one reference for both"):
        CredentialBinding(api_key=reference, material=reference, key_type=ApiKeyType.HMAC)


def test_a_binding_spanning_two_environments_is_refused() -> None:
    """A credential belongs to one environment, which is what the store key already encodes."""
    with pytest.raises(ValidationError, match="belongs to one environment"):
        CredentialBinding(
            api_key=_reference("key"),
            material=SecretReference(
                environment=EnvironmentId("production"),
                kind=SecretKind.API_SECRET,
                name="secret",
            ),
            key_type=ApiKeyType.HMAC,
        )


def test_a_binding_record_carries_names_and_no_material() -> None:
    """A reference is ordinary data; there is no field a value could occupy."""
    record = _binding().as_record()
    assert record["api_key_name"] == "venue_key"
    assert record["material_name"] == "venue_secret"
    assert set(record) == {
        "environment",
        "key_type",
        "algorithm",
        "api_key_name",
        "material_name",
    }


# ---------------------------------------------------------------------------
# Signatures refuse to render themselves
# ---------------------------------------------------------------------------


def test_a_signature_redacts_through_all_three_hooks() -> None:
    """`repr` matters most: a traceback, a debugger and a container all reach for it."""
    signature = _signature()
    assert str(signature) == REDACTED
    assert repr(signature) == REDACTED
    assert f"{signature}" == REDACTED
    assert f"{signature:>40}" == REDACTED
    assert signature.value() not in repr({"signature": signature})


def test_a_signature_has_no_dict_to_walk() -> None:
    """`vars`, `asdict` and anything written against either find nothing."""
    with pytest.raises(TypeError):
        vars(_signature())


def test_a_signature_is_unhashable() -> None:
    """So it cannot become a dictionary key or a set member and be rendered later."""
    with pytest.raises(TypeError):
        {_signature()}


def test_a_signature_record_carries_no_signature() -> None:
    """Its algorithm and its length are safe; its value has no representation here."""
    record = _signature().as_record()
    assert set(record) == {"algorithm", "length"}
    assert _signature().value() not in str(record)


def test_a_signature_beyond_the_bound_is_refused() -> None:
    """An RSA-4096 signature fits with room; nothing legitimate exceeds this."""
    with pytest.raises(ValidationError, match="limit"):
        GeneratedSignature("a" * (MAX_SIGNATURE_LENGTH + 1), SignatureAlgorithm.HMAC_SHA256)


# ---------------------------------------------------------------------------
# The signing payload
# ---------------------------------------------------------------------------


def test_the_payload_concatenates_without_separator() -> None:
    """The venue's own wording, implemented rather than paraphrased."""
    payload = SigningPayload(query_span="a=1&b=2", body_span="c=3")
    assert payload.text == "a=1&b=2c=3"
    assert payload.as_bytes() == b"a=1&b=2c=3"


def test_a_payload_already_carrying_a_signature_is_refused() -> None:
    """Signing something that claims to be signed is a state with no correct outcome."""
    with pytest.raises(ValidationError, match="already carries"):
        SigningPayload(query_span=f"a=1&{SIGNATURE_PARAMETER}=abc")
    with pytest.raises(ValidationError, match="already carries"):
        SigningPayload(query_span=f"{SIGNATURE_PARAMETER}=abc")


def test_a_payload_record_carries_lengths_and_no_characters() -> None:
    """A signing payload for an order holds a symbol, a side, a quantity and a price."""
    record = SigningPayload(query_span="symbol=BTCUSDT", body_span="").as_record()
    assert set(record) == {"query_length", "body_length", "total_length"}
    assert "BTCUSDT" not in str(record)


def test_the_query_span_is_the_canonical_rendering_unchanged() -> None:
    """The whole exact-bytes guarantee in one assertion."""
    parameters = QueryParameters(items=(("symbol", "BTC/USDT"), ("note", "a b")))
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    assert signing_payload(parameters, None, profile).query_span == parameters.canonical()


def test_a_body_is_decoded_rather_than_re_serialised() -> None:
    """`RequestBody` holds bytes precisely so what is signed is what is sent."""
    body = RequestBody(content=b"quantity=1", content_type="application/x-www-form-urlencoded")
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    payload = signing_payload(QueryParameters(items=(("s", "1"),)), body, profile)
    assert payload.body_span == "quantity=1"
    assert payload.text == "s=1quantity=1"


def test_a_body_that_is_not_utf8_is_refused() -> None:
    """The venue's rule concatenates the body as characters, so it must be decodable."""
    body = RequestBody(content=b"\xff\xfe", content_type="application/octet-stream")
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    with pytest.raises(ValidationError, match="not valid UTF-8"):
        signing_payload(QueryParameters(), body, profile)


def test_a_query_only_profile_ignores_the_body() -> None:
    """The placement is read rather than assumed, so a product that differs can say so."""
    body = RequestBody(content=b"x=1", content_type="text/plain")
    profile = SigningProfile(
        algorithm=SignatureAlgorithm.HMAC_SHA256,
        encoding=SignatureEncoding.HEX,
        placement=ParameterPlacement.QUERY_ONLY,
    )
    payload = signing_payload(QueryParameters(items=(("s", "1"),)), body, profile)
    assert payload.body_span == ""


# ---------------------------------------------------------------------------
# Timing parameters
# ---------------------------------------------------------------------------


def test_the_timing_parameters_are_appended_in_a_fixed_order() -> None:
    """Declaration order is preserved, so the signed span stays predictable."""
    parameters = QueryParameters(items=(("symbol", "BTCUSDT"),))
    timed = timed_parameters(parameters, timestamp=1, recv_window=default_recv_window())
    assert timed.canonical() == "symbol=BTCUSDT&timestamp=1&recvWindow=5000"


def test_a_request_already_carrying_a_timestamp_is_refused() -> None:
    """Two would leave the venue choosing one, and GLOBIN signing the other."""
    with pytest.raises(ValidationError, match="already carries"):
        timed_parameters(QueryParameters(items=(("timestamp", 1),)), timestamp=2)


def test_a_window_may_be_omitted_entirely() -> None:
    """It is documented optional, so `None` sends none rather than sending a default."""
    timed = timed_parameters(QueryParameters(), timestamp=7, recv_window=None)
    assert timed.canonical() == "timestamp=7"


def test_the_window_scale_survives_into_the_rendering() -> None:
    """The venue sees the rendering, and GLOBIN signs what the venue sees."""
    timed = timed_parameters(
        QueryParameters(), timestamp=1, recv_window=RecvWindow(Decimal("5000.000"))
    )
    assert timed.canonical() == "timestamp=1&recvWindow=5000.000"


# ---------------------------------------------------------------------------
# recvWindow
# ---------------------------------------------------------------------------


def test_the_default_and_maximum_are_the_documented_ones() -> None:
    """5000 and 60000, quoted from the Timing security section."""
    assert str(default_recv_window()) == "5000"
    assert str(max_recv_window()) == "60000"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        pytest.param("60000.001", "exceeds", id="above-the-maximum"),
        pytest.param("5000.1234", "decimal places", id="four-decimals"),
        pytest.param("0", "not positive", id="zero"),
        pytest.param("-1", "not positive", id="negative"),
        pytest.param("NaN", "finite", id="not-a-number"),
        pytest.param("about five", "not a decimal number", id="not-numeric"),
    ],
)
def test_an_unacceptable_window_is_refused(text: str, reason: str) -> None:
    """Each bound the venue documents, refused rather than clamped."""
    with pytest.raises(ValidationError, match=reason):
        parse_recv_window(text)


def test_the_documented_example_window_is_accepted() -> None:
    """`6000.346` is the venue's own example of three decimal places."""
    assert str(parse_recv_window("6000.346")) == "6000.346"
    assert parse_recv_window("6000.346").as_record()["decimal_places"] == MAX_RECV_WINDOW_DECIMALS


def test_a_float_is_refused_rather_than_converted() -> None:
    """`6000.346` as a float is not `6000.346`, and the message says which type arrived."""
    with pytest.raises(ValidationError, match="must be a Decimal"):
        RecvWindow(6000.346)


def test_two_windows_of_one_duration_are_equal_and_render_differently() -> None:
    """Equality answers *is this the same window*; the rendering is what gets signed."""
    assert RecvWindow(Decimal(5000)) == RecvWindow(Decimal("5000.000"))
    assert str(RecvWindow(Decimal(5000))) != str(RecvWindow(Decimal("5000.000")))


def test_a_window_record_carries_a_string_rather_than_a_number() -> None:
    """A JSON number would be parsed back into a float and undo the whole point."""
    assert isinstance(default_recv_window().as_record()["millis"], str)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


def test_both_units_derive_from_one_conversion() -> None:
    """A timestamp computed two ways that disagreed would be two moments in one request."""
    from datetime import UTC, datetime

    moment = instant(datetime(2017, 7, 12, 2, 41, 59, 559000, tzinfo=UTC))
    assert stamp(moment, TimestampUnit.MILLISECONDS) == 1499827319559
    assert stamp(moment, TimestampUnit.MICROSECONDS) == 1499827319559000


def test_the_millisecond_stamp_matches_the_venues_own_example() -> None:
    """The value the documentation prints in its worked HMAC example."""
    from datetime import UTC, datetime

    moment = instant(datetime(2017, 7, 12, 2, 41, 59, 559000, tzinfo=UTC))
    assert stamp(moment, TimestampUnit.MILLISECONDS) == 1499827319559


# ---------------------------------------------------------------------------
# Signing, and the wire invariant
# ---------------------------------------------------------------------------


def test_the_signed_span_is_a_prefix_of_the_transmitted_query() -> None:
    """The invariant this phase exists to guarantee, as a string comparison."""
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    timed = timed_parameters(
        QueryParameters(items=(("symbol", "BTCUSDT"),)),
        timestamp=1499827319559,
        recv_window=default_recv_window(),
    )
    payload = signing_payload(timed, None, profile)
    signature = _signature()
    request = RestRequest(
        operation="spot.account",
        method=HttpMethod.GET,
        path="/v3/account",
        query=signed_parameters(timed, signature, profile),
        headers=((API_KEY_HEADER, "an-identifier"),),
    )
    authenticated = AuthenticatedRequest(
        request=request,
        signed_span=payload.query_span,
        profile=profile,
        timestamp=1499827319559,
        timestamp_unit=TimestampUnit.MILLISECONDS,
        recv_window=default_recv_window(),
    )
    assert authenticated.wire_matches("/api")
    target = request.canonical_target("/api")
    expected = f"/api/v3/account?{payload.query_span}&{SIGNATURE_PARAMETER}={signature.value()}"
    assert target == expected


def test_a_request_cannot_be_signed_twice() -> None:
    """The venue would receive two values under one parameter name."""
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    once = signed_parameters(QueryParameters(items=(("a", "1"),)), _signature(), profile)
    with pytest.raises(ValidationError, match="cannot be signed twice"):
        signed_parameters(once, _signature(), profile)


def test_a_payload_cannot_be_built_from_parameters_that_carry_a_signature() -> None:
    """The other end of the same rule, checked where the payload is built."""
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    signed = signed_parameters(QueryParameters(items=(("a", "1"),)), _signature(), profile)
    with pytest.raises(ValidationError, match="already carry"):
        signing_payload(signed, None, profile)


def test_an_authenticated_request_without_a_key_header_is_refused() -> None:
    """A signature without a key identifies nobody."""
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    parameters = QueryParameters(items=(("a", "1"),))
    request = RestRequest(
        operation="x",
        method=HttpMethod.GET,
        path="/v3/x",
        query=signed_parameters(parameters, _signature(), profile),
    )
    with pytest.raises(ValidationError, match="carries no X-MBX-APIKEY"):
        AuthenticatedRequest(
            request=request,
            signed_span=parameters.canonical(),
            profile=profile,
            timestamp=1,
            timestamp_unit=TimestampUnit.MILLISECONDS,
        )


def test_an_authenticated_request_without_a_signature_is_refused() -> None:
    """Signing that produced nothing reaching the wire is a claim with nothing behind it."""
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    request = RestRequest(
        operation="x",
        method=HttpMethod.GET,
        path="/v3/x",
        query=QueryParameters(items=(("a", "1"),)),
        headers=((API_KEY_HEADER, "identifier"),),
    )
    with pytest.raises(ValidationError, match="carries no 'signature'"):
        AuthenticatedRequest(
            request=request,
            signed_span="a=1",
            profile=profile,
            timestamp=1,
            timestamp_unit=TimestampUnit.MILLISECONDS,
        )


def test_an_authenticated_request_record_carries_no_signature() -> None:
    """It carries the profile, the timing and a length, and nothing that could be replayed."""
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    parameters = QueryParameters(items=(("a", "1"),))
    signature = _signature()
    request = RestRequest(
        operation="x",
        method=HttpMethod.GET,
        path="/v3/x",
        query=signed_parameters(parameters, signature, profile),
        headers=((API_KEY_HEADER, "identifier"),),
    )
    record = AuthenticatedRequest(
        request=request,
        signed_span=parameters.canonical(),
        profile=profile,
        timestamp=1,
        timestamp_unit=TimestampUnit.MILLISECONDS,
    ).as_record()
    assert signature.value() not in str(record)
    assert "identifier" not in str(record)


# ---------------------------------------------------------------------------
# The retry seam Phase 043 inherits
# ---------------------------------------------------------------------------


def _authenticated(window: RecvWindow | None) -> AuthenticatedRequest:
    """A signed request stamped at zero, for the expiry checks.

    Args:
        window: The declared validity window, or ``None``.

    Returns:
        The request.
    """
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    parameters = QueryParameters(items=(("a", "1"),))
    request = RestRequest(
        operation="x",
        method=HttpMethod.GET,
        path="/v3/x",
        query=signed_parameters(parameters, _signature(), profile),
        headers=((API_KEY_HEADER, "identifier"),),
    )
    return AuthenticatedRequest(
        request=request,
        signed_span=parameters.canonical(),
        profile=profile,
        timestamp=0,
        timestamp_unit=TimestampUnit.MILLISECONDS,
        recv_window=window,
    )


def test_a_request_inside_its_window_needs_no_resignature() -> None:
    """The hook Phase 043 plugs into, which nothing in this phase calls."""
    assert not _authenticated(default_recv_window()).requires_resignature(4_999)


def test_a_request_past_its_window_needs_resignature() -> None:
    """Replaying it would send something the venue rejects."""
    assert _authenticated(default_recv_window()).requires_resignature(5_001)


def test_a_request_with_no_window_always_needs_resignature() -> None:
    """Without one GLOBIN cannot say it is still valid, and re-sign is always safe."""
    assert _authenticated(None).requires_resignature(0)


def test_a_signed_request_is_frozen() -> None:
    """The retry contract, as a property of the type rather than a rule.

    A retry that changed a parameter would have to build a new request, which means
    signing again. There is no path by which a mutated request keeps an old
    signature, because there is no path by which a request is mutated.
    """
    authenticated = _authenticated(default_recv_window())
    with pytest.raises((AttributeError, TypeError)):
        authenticated.timestamp = 1  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        authenticated.request.query = QueryParameters()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Fingerprints and encoding
# ---------------------------------------------------------------------------


def test_a_fingerprint_is_short_and_not_the_key() -> None:
    """Enough to tell two credentials apart, far too little to narrow a search."""
    # Sixty-four characters, shaped like a real key identifier and invented here.
    # The venue publishes an illustrative one; using it would put a key-shaped
    # literal in the tree for no benefit, since what this asserts is a property of
    # the fingerprint rather than of any particular key.
    key = "an-invented-api-key-identifier-for-this-test-and-nothing-else-01"
    fingerprint = api_key_fingerprint(key)
    assert len(fingerprint) == 12
    assert fingerprint not in key
    assert key[:12] != fingerprint


def test_two_keys_produce_two_fingerprints() -> None:
    """Otherwise it would tell an operator nothing."""
    assert api_key_fingerprint("one") != api_key_fingerprint("another")


def test_an_absent_key_produces_no_fingerprint() -> None:
    """Rather than a fingerprint of nothing, which would look like a real one."""
    assert api_key_fingerprint("") == ""


def test_a_base64_signature_is_percent_encoded_for_the_wire() -> None:
    """`/`, `+` and `=` all leave RFC 3986's unreserved set, as the venue's example shows."""
    signature = GeneratedSignature("ab+/cd==", SignatureAlgorithm.ED25519)
    assert encoded_signature(signature) == "ab%2B%2Fcd%3D%3D"


def test_the_auth_status_enumeration_has_exactly_one_permitting_member() -> None:
    """Every other member is a refusal, and a second permitting one would be a hole."""
    permitting = [member for member in AuthStatus if member.permits]
    assert permitting == [AuthStatus.RESOLVED]
