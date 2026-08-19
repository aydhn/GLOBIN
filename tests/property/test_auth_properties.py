"""Invariants of the signing path, over generated input.

The unit tests assert *values* — the venue's published vectors, the documented
bounds, the exact strings. These assert the *properties* those values are examples
of, over parameters Hypothesis chooses, which is where a case nobody thought of
shows up.

The central one is the prefix invariant: for **any** parameter set, appending a
signature leaves the signed span a literal prefix of the transmitted query string.
A fixed vector shows it holds once; this shows it holds for symbols with slashes,
values that are empty, keys that repeat, and every combination of those.

Nothing here computes a real signature. A signer is a function of bytes and is
tested against real keys in `tests/unit/test_signing.py`; what varies here is the
*payload*, so a fixed well-formed signature keeps the generated cases about
canonicalisation rather than about cryptography.
"""

from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import unquote

from hypothesis import given
from hypothesis import strategies as st

from globin.domain.auth import (
    SIGNATURE_PARAMETER,
    GeneratedSignature,
    SignatureAlgorithm,
    signed_parameters,
    signing_payload,
    spot_profile,
    timed_parameters,
)
from globin.domain.auth_timing import RecvWindow, TimestampUnit, stamp
from globin.domain.clock import instant
from globin.domain.rest import QueryParameters, percent_encode

PROFILE = spot_profile(SignatureAlgorithm.HMAC_SHA256)
"""The Spot signing profile, which every case here uses."""

SIGNATURE = GeneratedSignature("ab" * 32, SignatureAlgorithm.HMAC_SHA256)
"""A well-formed signature. What varies here is the payload, not the cryptography."""

keys = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126, blacklist_characters="=&"),
    min_size=1,
    max_size=12,
)
"""Parameter names: printable, non-empty, and never a delimiter.

`=` and `&` are excluded not because the encoder could not handle them — it
percent-encodes both — but because a *name* containing one is a caller bug rather
than a case worth generating, and `QueryParameters` has no rule against it.
"""

values = st.one_of(
    st.text(max_size=24),
    st.integers(min_value=-(2**40), max_value=2**40),
    st.booleans(),
    st.decimals(
        allow_nan=False, allow_infinity=False, places=8, min_value=-(10**6), max_value=10**6
    ),
    st.none(),
)
"""Every type `QueryValue` admits, including the one that renders to nothing.

`float` is absent because `QueryValue` excludes it, which is the point:
`docs/VALUE_TYPES_POLICY.md` forbids a binary float anywhere near a price, and a
query parameter is exactly where one would reach the venue.
"""

parameter_sets = st.lists(st.tuples(keys, values), max_size=8).map(
    lambda items: QueryParameters(items=tuple(items))
)
"""A parameter set the caller might build, repeats and omissions included."""

_EARLIEST = datetime(1971, 1, 1)  # noqa: DTZ001 -- a naive bound; the test attaches UTC
_LATEST = datetime(2200, 1, 1)  # noqa: DTZ001 -- Hypothesis generates naive datetimes
"""The range moments are drawn from.

Naive on purpose: `st.datetimes` produces naive values by default and the test
attaches UTC before building an `Instant`, which refuses a naive datetime outright.
Bounding the range keeps the generated moments inside what a venue timestamp could
plausibly describe.
"""


@given(parameters=parameter_sets)
def test_the_signed_span_is_always_a_prefix_of_the_transmitted_query(
    parameters: QueryParameters,
) -> None:
    """The invariant this phase exists to guarantee, over anything a caller can build."""
    payload = signing_payload(parameters, None, PROFILE)
    transmitted = signed_parameters(parameters, SIGNATURE, PROFILE).canonical()
    assert transmitted.startswith(payload.query_span)


@given(parameters=parameter_sets)
def test_appending_a_signature_adds_exactly_one_parameter(
    parameters: QueryParameters,
) -> None:
    """Nothing else moves, so the difference between the two strings is fully known."""
    payload = signing_payload(parameters, None, PROFILE)
    transmitted = signed_parameters(parameters, SIGNATURE, PROFILE).canonical()
    appended = f"{SIGNATURE_PARAMETER}={SIGNATURE.value()}"
    expected = f"{payload.query_span}&{appended}" if payload.query_span else appended
    assert transmitted == expected


@given(parameters=parameter_sets)
def test_the_signing_payload_is_the_canonical_rendering_unchanged(
    parameters: QueryParameters,
) -> None:
    """No second encoder, no re-ordering, no normalisation between the two."""
    assert signing_payload(parameters, None, PROFILE).query_span == parameters.canonical()


@given(parameters=parameter_sets)
def test_rendering_twice_gives_the_same_string(parameters: QueryParameters) -> None:
    """Determinism, which every signature depends on and no other generated case covers."""
    assert parameters.canonical() == parameters.canonical()


@given(parameters=parameter_sets)
def test_ordering_is_never_sorted(parameters: QueryParameters) -> None:
    """Declaration order survives, so a caller's ordering is what gets signed.

    Sorting would be a defensible design and would silently change every signature
    a caller had already computed against the same parameters.
    """
    transmitted = [pair.split("=", 1)[0] for pair in parameters.canonical().split("&") if pair]
    expected = [percent_encode(key) for key in parameters.transmitted()]
    assert transmitted == expected


@given(text=st.text(max_size=32))
def test_percent_encoding_leaves_only_unreserved_characters(text: str) -> None:
    """Whatever a value contains, what reaches the wire is ASCII and delimiter-free.

    This is what makes the venue's rule — *"any non-ASCII character must be
    percent-encoded before signing"* — satisfied by construction rather than by a
    step somebody could forget.
    """
    encoded = percent_encode(text)
    assert encoded.isascii()
    assert "&" not in encoded
    assert "=" not in encoded
    assert " " not in encoded


@given(text=st.text(max_size=32))
def test_percent_encoding_round_trips(text: str) -> None:
    """The venue decodes what GLOBIN encodes, so the value it reads is the value sent."""
    assert unquote(percent_encode(text)) == text


@given(
    parameters=parameter_sets,
    timestamp=st.integers(min_value=0, max_value=2**53 - 1),
    millis=st.decimals(
        min_value=Decimal("0.001"), max_value=Decimal(60000), places=3, allow_nan=False
    ),
)
def test_the_timing_parameters_are_always_the_last_two(
    parameters: QueryParameters, timestamp: int, millis: Decimal
) -> None:
    """A fixed suffix, so the signed span stays predictable whatever the caller sent."""
    timed = timed_parameters(parameters, timestamp=timestamp, recv_window=RecvWindow(millis))
    assert timed.transmitted()[-2:] == ("timestamp", "recvWindow")
    assert timed.canonical().startswith(parameters.canonical())


@given(millis=st.decimals(min_value=Decimal("0.001"), max_value=Decimal(60000), places=3))
def test_every_acceptable_window_renders_without_an_exponent(millis: Decimal) -> None:
    """Scientific notation is a rendering the venue never agreed to read."""
    rendered = str(RecvWindow(millis))
    assert "E" not in rendered.upper()
    assert Decimal(rendered) == millis


@given(moment=st.datetimes(min_value=_EARLIEST, max_value=_LATEST))
def test_the_two_timestamp_units_never_disagree_about_the_moment(moment: datetime) -> None:
    """Both derive from one exact conversion, so one cannot drift from the other."""
    aware = instant(moment.replace(tzinfo=UTC))
    micros = stamp(aware, TimestampUnit.MICROSECONDS)
    assert micros // 1000 == stamp(aware, TimestampUnit.MILLISECONDS)
