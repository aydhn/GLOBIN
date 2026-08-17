"""Invariants of the diagnostics surface that hold over generated input, not examples.

Two of this surface's functions read text a remote party chose — a request target and
an ``Accept`` header — and both must be **total**: whatever arrives, they return an
answer rather than raising. Example-based tests can only demonstrate that for the
inputs somebody thought of, and the inputs that matter here are the ones nobody did.

The third property is about the bind address, where totality is not the point: what
matters is that the *set* of accepted values is exactly the loopback set, over
addresses generated rather than listed.
"""

import ipaddress

from hypothesis import given
from hypothesis import strategies as st

from globin.domain.diagnostics_http import (
    FULL_QUALITY,
    MAXIMUM_ACCEPT_LENGTH,
    DiagnosticsRoute,
    ExpositionFormat,
    LoopbackAddress,
    address_problems,
    media_ranges,
    negotiate,
    normalise_path,
    quality_of,
    route_paths,
)
from globin.errors import ValidationError


@given(st.text())
def test_negotiation_always_returns_a_format(header: str) -> None:
    """Total, because the scrape protocol has no failure mode here.

    Its rule is that a target supporting none of the offered protocols *"MUST use
    PrometheusText0.0.4 as a last resort"*, so there is no input for which the honest
    answer is an error.
    """
    assert negotiate(header) in set(ExpositionFormat)


@given(st.text(min_size=MAXIMUM_ACCEPT_LENGTH + 1))
def test_an_oversized_header_is_never_partly_honoured(header: str) -> None:
    """Past the bound the *whole* header is unusable, not the first kilobyte of it.

    Parsing half a negotiation is how a parser starts agreeing to something the client
    did not offer.
    """
    assert negotiate(header) is ExpositionFormat.PROMETHEUS_TEXT


@given(st.text())
def test_parsing_a_header_never_raises_and_stays_bounded(header: str) -> None:
    """The parser is the part a remote party controls the length of."""
    parsed = media_ranges(header)
    assert len(parsed) <= 16
    assert all(0 <= entry.quality <= FULL_QUALITY for entry in parsed)


@given(st.text())
def test_a_weight_is_always_within_range(value: str) -> None:
    """Including for text that is not a number at all, which reads as unacceptable."""
    assert 0 <= quality_of(value) <= FULL_QUALITY


@given(st.text())
def test_every_target_names_a_route_or_names_unknown(target: str) -> None:
    """Total over anything a client can put in a request line.

    Traversal, encoding tricks, control characters and megabytes of nonsense all land
    on ``unknown``, because the only thing that does not is an exact table entry.
    """
    assert normalise_path(target) in set(DiagnosticsRoute)


@given(st.text())
def test_only_a_declared_path_names_a_serving_route(target: str) -> None:
    """The stronger half: nothing outside the table can reach a route that answers."""
    declared = {path for path, _route in route_paths()}
    route = normalise_path(target)
    if route is not DiagnosticsRoute.UNKNOWN:
        assert target.split("?", 1)[0].split("#", 1)[0] in declared


@given(st.ip_addresses())
def test_an_address_is_accepted_exactly_when_it_is_loopback(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> None:
    """The accepted set is the loopback set, over generated addresses in both families.

    This is the property a denylist of spellings could not have: it holds for every
    address the two families contain, not for the handful somebody remembered.
    """
    text = str(address)
    if address.is_loopback:
        assert address_problems(text) == ()
        assert LoopbackAddress(text).text == text
    else:
        assert address_problems(text)
        try:
            LoopbackAddress(text)
        except ValidationError:
            return
        message = f"{text} was accepted and is not loopback"
        raise AssertionError(message)


@given(st.text())
def test_judging_an_address_never_raises(text: str) -> None:
    """A caller checking a whole configuration collects problems; it does not catch."""
    assert isinstance(address_problems(text), tuple)
