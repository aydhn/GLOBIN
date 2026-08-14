"""Invariants of the identifier registry, over generated input.

Three real invariants live here, and each would survive a rewrite of how the
rules are spelled.

*The registry and the types cannot disagree.* :func:`~globin.domain.identifiers.satisfies`
and every constructor answer the same question by different routes — one
reports, the other refuses — so any text on which they differ is a defect in one
of them. This is the property worth having: the example-based tests check the
forms somebody thought of, and this checks the ones nobody did.

*Validity does not depend on order.* Shape is a length and an alphabet, neither
of which a permutation changes. A rule that quietly became order-sensitive —
a prefix requirement, say — would be a different rule wearing the same name.

*The one producer obeys the registry.* Nothing else mints an identifier, so if
:func:`~globin.adapters.identifiers.new_run_id` and the run specification ever
part company, every run in every log is unreadable and no example test would
say so.
"""

from typing import Final

from hypothesis import given
from hypothesis import strategies as st

from globin.adapters.identifiers import new_run_id
from globin.domain.identifiers import (
    EnvironmentId,
    IdentifierKind,
    IdentifierSpec,
    ModelId,
    OrderId,
    ProductId,
    RunId,
    satisfies,
    specification,
)
from globin.errors import ValidationError

#: The kinds that carry a type of their own. ``SYMBOL`` is absent because
#: :class:`~globin.domain.values.Symbol` predates this registry and Phase 008
#: owns its construction.
CONSTRUCTED_KINDS: Final[dict[IdentifierKind, type]] = {
    IdentifierKind.PRODUCT: ProductId,
    IdentifierKind.ENVIRONMENT: EnvironmentId,
    IdentifierKind.RUN: RunId,
    IdentifierKind.MODEL: ModelId,
    IdentifierKind.ORDER: OrderId,
}

constructed_kinds = st.sampled_from(sorted(CONSTRUCTED_KINDS, key=lambda kind: kind.value))
kinds = st.sampled_from(list(IdentifierKind))


def _in_form(spec: IdentifierSpec) -> st.SearchStrategy[str]:
    """Text drawn from a specification's alphabet, within its length bounds.

    Args:
        spec: The form to generate against.

    Returns:
        A strategy producing text the specification must accept.
    """
    return st.text(
        alphabet=sorted(set(spec.alphabet)),
        min_size=spec.min_length,
        max_size=spec.max_length,
    )


def _any_text() -> st.SearchStrategy[str]:
    """Arbitrary short text, most of which no specification accepts.

    Returns:
        A strategy producing text of any shape, bounded so shrinking stays quick.
    """
    return st.text(max_size=80)


@given(kind=kinds, data=st.data())
def test_text_in_a_specifications_form_satisfies_it(
    kind: IdentifierKind, data: st.DataObject
) -> None:
    """The generator and the predicate must agree on what the form is.

    If this fails, either the alphabet admits a character the length rule then
    rejects, or the bounds cross — both of which describe a form nothing
    reaches.
    """
    spec = specification(kind)
    assert satisfies(data.draw(_in_form(spec)), spec)


@given(kind=constructed_kinds, data=st.data())
def test_the_predicate_and_the_constructor_never_disagree(
    kind: IdentifierKind, data: st.DataObject
) -> None:
    """Two statements of one rule, held against each other over arbitrary text.

    `satisfies` reports and the constructor refuses. They read the same
    specification, so a text either passes both or fails both; anything else
    means one of them grew a rule the other does not have.
    """
    spec = specification(kind)
    text = data.draw(_any_text())
    reported = satisfies(text, spec)
    try:
        CONSTRUCTED_KINDS[kind](text=text)
    except ValidationError:
        constructed = False
    else:
        constructed = True
    assert reported == constructed


@given(kind=kinds, data=st.data())
def test_validity_does_not_depend_on_order(kind: IdentifierKind, data: st.DataObject) -> None:
    """Shape is a length and an alphabet, and a permutation changes neither.

    A rule that became order-sensitive — a required prefix, a forbidden leading
    digit — would still pass every example test written against the forms it
    was designed around.
    """
    spec = specification(kind)
    text = data.draw(_in_form(spec))
    assert satisfies("".join(data.draw(st.permutations(list(text)))), spec)


@given(kind=kinds, data=st.data())
def test_a_character_outside_the_alphabet_is_always_refused(
    kind: IdentifierKind, data: st.DataObject
) -> None:
    """One stray character is enough, wherever it sits.

    Refusing only a leading or trailing stray is the plausible half-rule, and it
    would let `spot margin` through as one product.
    """
    spec = specification(kind)
    body = data.draw(_in_form(spec))
    stray = data.draw(st.text(min_size=1, max_size=1).filter(lambda ch: ch not in spec.alphabet))
    position = data.draw(st.integers(min_value=0, max_value=len(body)))
    assert not satisfies(body[:position] + stray + body[position:], spec)


@given(count=st.integers(min_value=1, max_value=8))
def test_minted_run_identifiers_fit_the_form_and_differ(count: int) -> None:
    """The only producer of an identifier, held to the registry that describes it.

    Two claims, because either alone is satisfiable by something useless. A
    generator returning one constant fits the form every time; a generator
    returning arbitrary text is distinct every time. A run identifier has to be
    both, and `new_run_id` is the only thing in GLOBIN that mints one.

    Switching to `uuid1`, to uppercase hexadecimal, or to a dashed rendering
    would break every run identifier in every log, and no example test would
    say so.
    """
    spec = specification(IdentifierKind.RUN)
    minted = [str(new_run_id()) for _ in range(count)]
    assert all(satisfies(text, spec) for text in minted)
    assert len(set(minted)) == count, "a minted identifier repeated"
