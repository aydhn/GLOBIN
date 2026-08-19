"""Invariants of the canonical encoder, over generated input rather than examples.

``tests/unit/test_rest.py`` pins the exact bytes for the cases Phase 038's signer
will meet. This asserts the properties that must hold for input nobody thought of:
arbitrary Unicode, every reserved character, very large integers, and decimals at
scales no fixture would have chosen.

**Why both.** A property test says *this is always true* and cannot say *this is the
string*. A signature is computed over a specific string, so the vectors are the
contract and these are the guard against a change that keeps the vectors passing
while breaking everything else.
"""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from globin.domain.rest import (
    MAX_QUERY_PARAMETERS,
    UNRESERVED,
    QueryParameters,
    encode_value,
    join_path,
    percent_encode,
)

RESERVED = "!*'();:@&=+$,/?#[]% \t\n\"<>\\^`{|}~"
"""Every character RFC 3986 reserves, plus whitespace and the ones a shell mangles.

``~`` is in this string and is *unreserved*, deliberately: a strategy drawing from
here should still produce at least one character the encoder passes through, so a
test asserting "everything is escaped" would be wrong rather than vacuous.
"""

keys = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=0x2FFF), min_size=1, max_size=24
)
values = st.one_of(
    st.text(max_size=48),
    st.text(alphabet=RESERVED, max_size=16),
    st.integers(min_value=-(2**63), max_value=2**63 - 1),
    st.booleans(),
    st.decimals(
        allow_nan=False, allow_infinity=False, places=8, min_value=-(10**12), max_value=10**12
    ),
    st.none(),
)


class TestPercentEncoding:
    """What must be true of the escape, whatever it is handed."""

    @given(st.text(max_size=200))
    def test_the_output_is_always_ascii(self, text: str) -> None:
        """A query string reaches a socket as bytes; a non-ASCII escape is not an escape."""
        assert percent_encode(text).isascii()

    @given(st.text(max_size=200))
    def test_only_unreserved_characters_survive_unescaped(self, text: str) -> None:
        """Everything else becomes ``%XX``, which is the whole guarantee."""
        encoded = percent_encode(text)
        index = 0
        while index < len(encoded):
            character = encoded[index]
            if character == "%":
                assert (
                    encoded[index + 1 : index + 3].isupper()
                    or encoded[index + 1 : index + 3].isdigit()
                )
                index += 3
                continue
            assert character in UNRESERVED
            index += 1

    @given(st.text(max_size=200))
    def test_encoding_is_deterministic(self, text: str) -> None:
        """The same value twice is the same string twice, or a signature is a coin toss."""
        assert percent_encode(text) == percent_encode(text)

    @given(st.text(alphabet=RESERVED, min_size=1, max_size=32))
    def test_no_delimiter_survives_in_a_value(self, text: str) -> None:
        """A raw ``&`` or ``=`` in a value is how one parameter becomes two.

        This is the injection this encoder exists to prevent, and it is asserted
        over generated reserved-character soup rather than over three examples.
        """
        encoded = percent_encode(text)
        for delimiter in ("&", "=", "?", "#"):
            assert delimiter not in encoded

    @given(st.text(max_size=100))
    def test_the_escape_is_reversible(self, text: str) -> None:
        """Round-tripping proves nothing was lost, not merely that nothing looks wrong.

        Decoded by hand rather than with ``urllib.parse.unquote``: reusing the
        standard library here would test that two implementations of the same idea
        agree, and the whole reason this encoder exists is that a domain module may
        not import ``urllib``.
        """
        encoded = percent_encode(text)
        out = bytearray()
        index = 0
        while index < len(encoded):
            if encoded[index] == "%":
                out.append(int(encoded[index + 1 : index + 3], 16))
                index += 3
            else:
                out.append(ord(encoded[index]))
                index += 1
        assert bytes(out).decode("utf-8") == text


class TestQueryCanonicalisation:
    """What must be true of a whole query string."""

    @given(st.lists(st.tuples(keys, values), max_size=12))
    def test_the_rendering_is_stable(self, items: list[tuple[str, object]]) -> None:
        """Two renderings of one set agree, which is what *canonical* means."""
        query = QueryParameters(items=tuple(items))  # type: ignore[arg-type]
        assert query.canonical() == query.canonical()

    @given(st.lists(st.tuples(keys, values), max_size=12))
    def test_declaration_order_is_never_rearranged(self, items: list[tuple[str, object]]) -> None:
        """Phase 038 signs the string as sent; a re-ordering signer signs a fiction."""
        query = QueryParameters(items=tuple(items))  # type: ignore[arg-type]
        rendered = query.canonical()
        expected = [key for key, value in items if encode_value(value) is not None]
        seen = [pair.split("=", 1)[0] for pair in rendered.split("&") if pair]
        assert seen == [percent_encode(key) for key in expected]

    @given(st.lists(st.tuples(keys, values), max_size=12))
    def test_a_transmitted_key_count_matches_the_rendered_pair_count(
        self, items: list[tuple[str, object]]
    ) -> None:
        """The model and the wire agree about how many parameters there are."""
        query = QueryParameters(items=tuple(items))  # type: ignore[arg-type]
        rendered = query.canonical()
        pairs = [pair for pair in rendered.split("&") if pair] if rendered else []
        assert len(pairs) == len(query.transmitted())

    @given(st.lists(st.tuples(keys, values), max_size=12))
    def test_none_is_the_only_thing_that_disappears(self, items: list[tuple[str, object]]) -> None:
        """An empty string is transmitted; only ``None`` is omitted.

        The three-state distinction, asserted as an invariant rather than on the
        one fixture that happens to carry all three.
        """
        query = QueryParameters(items=tuple(items))  # type: ignore[arg-type]
        omitted = set(query.declared()) - set(query.transmitted())
        for key in omitted:
            assert all(value is None for name, value in items if name == key)

    @given(st.lists(st.tuples(keys, values), min_size=1, max_size=8))
    def test_a_repeated_key_is_never_collapsed(self, items: list[tuple[str, object]]) -> None:
        """Duplicating the whole list must double every transmitted key."""
        once = QueryParameters(items=tuple(items))  # type: ignore[arg-type]
        twice = QueryParameters(items=tuple(items) * 2)  # type: ignore[arg-type]
        assert len(twice.transmitted()) == 2 * len(once.transmitted())

    @given(st.integers(min_value=0, max_value=MAX_QUERY_PARAMETERS))
    def test_the_bound_admits_exactly_what_it_declares(self, count: int) -> None:
        """A bound that refused its own limit would be off by one."""
        items = tuple((f"k{index}", "1") for index in range(count))
        assert len(QueryParameters(items=items).declared()) == count


class TestDecimalRendering:
    """Financial precision, over generated values rather than five fixtures."""

    @given(
        st.decimals(allow_nan=False, allow_infinity=False, places=8, min_value=0, max_value=10**9)
    )
    def test_a_decimal_never_renders_in_exponent_notation(self, value: Decimal) -> None:
        """A venue parsing ``1E-8`` as a quantity is a venue rejecting the order."""
        rendered = encode_value(value)
        assert rendered is not None
        assert "E" not in rendered
        assert "e" not in rendered

    @given(
        st.decimals(allow_nan=False, allow_infinity=False, places=8, min_value=0, max_value=10**9)
    )
    def test_a_decimal_round_trips_to_the_same_value(self, value: Decimal) -> None:
        """The rendering loses no precision, which is the point of refusing ``float``."""
        rendered = encode_value(value)
        assert rendered is not None
        assert Decimal(rendered) == value

    @given(st.integers(min_value=-(2**63), max_value=2**63 - 1))
    def test_a_very_large_integer_renders_exactly(self, value: int) -> None:
        """Millisecond and microsecond timestamps are large, and are not approximations."""
        assert encode_value(value) == str(value)


class TestPathJoining:
    """The join never produces a doubled separator, whatever the two halves look like."""

    @given(
        st.text(alphabet="abc/", max_size=12),
        st.text(alphabet="abc/", min_size=1, max_size=12).filter(lambda text: text.strip("/")),
    )
    def test_no_doubled_separator_is_ever_produced(self, prefix: str, path: str) -> None:
        """``//`` is a different resource, and some gateways answer it with a redirect."""
        joined = join_path(prefix, path)
        assert "//" not in joined
        assert joined.startswith("/")

    @given(
        st.text(alphabet="abc/", max_size=12),
        st.text(alphabet="abc/", min_size=1, max_size=12).filter(lambda text: text.strip("/")),
    )
    def test_joining_is_deterministic(self, prefix: str, path: str) -> None:
        """Same inputs, same target — what ``canonical_target`` promises its caller."""
        assert join_path(prefix, path) == join_path(prefix, path)
