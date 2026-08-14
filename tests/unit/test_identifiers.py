"""The identifier registry and the five types that read it.

Phase 011's claim is that every kind of thing GLOBIN names has one canonical
form, and that the form is stated once. These tests hold both halves: that the
registry answers for every kind, and that each type refuses everything the
registry does not describe.

The refusals matter more than the acceptances. A type that accepts its canonical
form and also accepts three other spellings has not fixed a canonical form — it
has documented a preference — so every rule below is exercised by a value that
breaks it, and the assertion names which rule was broken rather than only that
something was.
"""

from collections.abc import Callable
from typing import Final, cast

import pytest

from globin.domain.identifiers import (
    HEX_ALPHABET,
    MAX_NAME_LENGTH,
    MAX_OPAQUE_LENGTH,
    MIN_NAME_LENGTH,
    MIN_OPAQUE_LENGTH,
    NAME_ALPHABET,
    OPAQUE_ALPHABET,
    RUN_ID_LENGTH,
    EnvironmentId,
    IdentifierKind,
    ModelId,
    OrderId,
    ProductId,
    RunId,
    environment_id,
    model_id,
    order_id,
    product_id,
    run_id,
    satisfies,
    specification,
    specifications,
)
from globin.domain.values import symbol
from globin.errors import InternalError, ValidationError

#: A well-formed value of each kind that carries its own type, paired with the
#: type that must hold it. ``SYMBOL`` is absent because Phase 008 owns it.
CANONICAL_EXAMPLES: Final[tuple[tuple[type, str], ...]] = (
    (ProductId, "spot"),
    (EnvironmentId, "production"),
    (RunId, "0" * RUN_ID_LENGTH),
    (ModelId, "direction.gradient_boosted"),
    (OrderId, "GLOBIN-a_1"),
)


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------


def test_every_kind_has_a_specification() -> None:
    """A kind without one is a module edited in half."""
    described = {spec.kind for spec in specifications()}
    assert described == set(IdentifierKind)


def test_specifications_are_returned_in_declaration_order() -> None:
    """Order is what lets a document list them without choosing its own."""
    assert [spec.kind for spec in specifications()] == list(IdentifierKind)


def test_a_kind_with_no_specification_is_an_internal_fault() -> None:
    """The caller cannot fix this by sending different input, so it is not validation."""
    with pytest.raises(InternalError, match="has no specification"):
        specification(cast("IdentifierKind", "NOT_A_KIND"))


@pytest.mark.parametrize("kind", list(IdentifierKind))
def test_every_specification_describes_a_reachable_form(kind: IdentifierKind) -> None:
    """Bounds that cross, or an empty alphabet, describe nothing constructible."""
    spec = specification(kind)
    assert spec.kind == kind
    assert 0 < spec.min_length <= spec.max_length
    assert spec.alphabet
    assert len(set(spec.alphabet)) == len(spec.alphabet), "the alphabet repeats a character"
    assert spec.summary.endswith("."), "a summary is a sentence"


def test_the_symbol_specification_is_derived_from_phase_008() -> None:
    """A restated bound is free to drift from the one it restates.

    The symbol form belongs to `globin.domain.values`. Deriving it here means
    widening a currency code widens this automatically, so the two cannot
    disagree and no tripwire comparing them is needed.
    """
    spec = specification(IdentifierKind.SYMBOL)
    assert satisfies(str(symbol("BTC", "USDT")), spec)
    assert satisfies(str(symbol("A" * 16, "B" * 16)), spec), "the longest legal pair must fit"


# --------------------------------------------------------------------------
# satisfies() reports; it never refuses
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("spot", True, id="canonical"),
        pytest.param("s", False, id="too short"),
        pytest.param("s" * (MAX_NAME_LENGTH + 1), False, id="too long"),
        pytest.param("Spot", False, id="wrong case"),
        pytest.param("spot margin", False, id="stray character"),
        pytest.param(7, False, id="not a string"),
        pytest.param(None, False, id="none"),
    ],
)
def test_satisfies_answers_rather_than_raising(text: object, expected: bool) -> None:
    """A predicate that raised could not be used to hold one module's value against another's."""
    assert satisfies(text, specification(IdentifierKind.PRODUCT)) is expected


# --------------------------------------------------------------------------
# The types refuse
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("held", "text"), CANONICAL_EXAMPLES)
def test_a_canonical_value_is_accepted_and_renders_as_itself(held: type, text: str) -> None:
    """Rendering must round-trip, or the canonical form is not what is stored."""
    assert str(held(text=text)) == text


@pytest.mark.parametrize(("held", "text"), CANONICAL_EXAMPLES)
def test_an_identifier_is_usable_as_a_key(held: type, text: str) -> None:
    """An identifier is a dictionary key wherever it is useful at all.

    Two values built from the same text must be the same key, or grouping a
    report by identifier would split one thing into several.
    """
    assert {held(text=text): 1}[held(text=text)] == 1


def test_two_kinds_with_the_same_text_are_not_equal() -> None:
    """The reason each kind gets a type rather than sharing one.

    `spot` as a product and `spot` as an environment are different facts. A
    single type carrying both would compare them equal and let either be passed
    where the other belongs, which is the confusion Phase 008 built types to
    prevent.

    Both sides are held as `object` because mypy's `strict_equality` otherwise
    reports the comparison as one that cannot be true — which is the assertion,
    but proved by the type checker rather than at run time. The run-time proof
    is the one that survives someone merging the two types later.
    """
    product: object = product_id("spot")
    environment: object = environment_id("spot")
    assert product != environment


@pytest.mark.parametrize(
    ("factory", "text", "message"),
    [
        pytest.param(product_id, "", "is 0 characters", id="product empty"),
        pytest.param(product_id, "s", "expected between 2 and 64", id="product too short"),
        pytest.param(
            product_id, "s" * (MAX_NAME_LENGTH + 1), "expected between", id="product too long"
        ),
        pytest.param(product_id, "SPOT", "contains", id="product uppercase"),
        pytest.param(product_id, "spot-margin", "contains", id="product hyphen"),
        pytest.param(environment_id, "Production", "contains", id="environment uppercase"),
        pytest.param(run_id, "0" * (RUN_ID_LENGTH - 1), "expected exactly 32", id="run too short"),
        pytest.param(run_id, "0" * (RUN_ID_LENGTH + 1), "expected exactly 32", id="run too long"),
        pytest.param(run_id, "F" * RUN_ID_LENGTH, "contains", id="run uppercase hex"),
        pytest.param(run_id, "z" * RUN_ID_LENGTH, "contains", id="run outside hex"),
        pytest.param(model_id, "Model", "contains", id="model uppercase"),
        pytest.param(order_id, "abc", "expected between 4 and 64", id="order too short"),
        pytest.param(order_id, "abc def", "contains", id="order space"),
        pytest.param(order_id, "abc.def", "contains", id="order full stop"),
    ],
)
def test_a_malformed_identifier_is_refused_by_the_rule_it_breaks(
    factory: Callable[[str], object], text: str, message: str
) -> None:
    """A refusal that does not say which rule was broken sends the caller guessing."""
    with pytest.raises(ValidationError, match=message):
        factory(text)


@pytest.mark.parametrize("held", [ProductId, EnvironmentId, RunId, ModelId, OrderId])
def test_a_non_string_is_refused_however_it_was_constructed(held: type) -> None:
    """The field annotation is not a check, and a value read from a document has no mypy."""
    with pytest.raises(ValidationError, match="construct it through the matching factory"):
        held(text=7)


def test_a_fixed_length_kind_says_exactly_rather_than_between() -> None:
    """`between 32 and 32` reads as a bug in the message rather than a rule."""
    with pytest.raises(ValidationError, match="expected exactly 32"):
        run_id("abc")


# --------------------------------------------------------------------------
# The alphabets say what they claim to say
# --------------------------------------------------------------------------


def test_the_name_alphabet_admits_no_uppercase() -> None:
    """Folding case would make two names one; admitting both would make one name two."""
    assert not set(NAME_ALPHABET) & set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def test_the_opaque_alphabet_admits_both_cases_and_no_separator_of_its_own() -> None:
    """An order identifier crosses a boundary and returns; case is data, not style."""
    assert {"A", "a", "-", "_"} <= set(OPAQUE_ALPHABET)
    assert not {".", "/", " "} & set(OPAQUE_ALPHABET)


def test_the_hex_alphabet_is_exactly_lowercase_hexadecimal() -> None:
    """`uuid4().hex` renders lowercase, and accepting both would double every run."""
    assert set(HEX_ALPHABET) == set("0123456789abcdef")


def test_the_bounds_leave_room_between_them() -> None:
    """A minimum above a maximum describes a form nothing satisfies."""
    assert MIN_NAME_LENGTH < MAX_NAME_LENGTH
    assert MIN_OPAQUE_LENGTH < MAX_OPAQUE_LENGTH
