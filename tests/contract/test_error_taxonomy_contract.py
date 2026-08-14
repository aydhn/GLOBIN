"""The error taxonomy's shape, asserted rather than described.

``globin.errors`` states its design in prose: one root, five categories split by
who must act, and no inheritance from builtin exception types. Prose is what a
later phase edits around. These tests are what a later phase has to argue with.

The invariants below are chosen so that the plausible ways of eroding the
taxonomy each fail one of them: adding a sixth error class without a matching
:class:`~globin.errors.FaultDomain`, reusing a domain across two classes,
quietly making an error inherit :exc:`ValueError` so that old ``except`` clauses
keep working, or giving the root a domain so that ``raise GlobinError(...)``
becomes tempting.
"""

import re

import pytest

from globin.errors import (
    ConfigurationError,
    ExchangeError,
    FaultDomain,
    GlobinError,
    InternalError,
    TransportError,
    ValidationError,
)

#: The taxonomy's top level: the classes that divide GlobinError into kinds.
#:
#: Deliberately the *direct* subclasses rather than every descendant. A later
#: phase refining `ConfigurationError` into something more specific is extending
#: a category, which is fine and should not fail these tests; adding a sixth
#: category is a change to the taxonomy, which should.
CATEGORIES: tuple[type[GlobinError], ...] = (
    ConfigurationError,
    ValidationError,
    TransportError,
    ExchangeError,
    InternalError,
)


def test_every_category_descends_from_the_one_root() -> None:
    """A single ``except GlobinError`` must catch everything GLOBIN raises."""
    for category in CATEGORIES:
        assert issubclass(category, GlobinError)
        assert issubclass(category, Exception)


def test_the_declared_categories_are_the_real_ones() -> None:
    """The list above must not drift from the class tree it claims to describe."""
    assert set(GlobinError.__subclasses__()) == set(CATEGORIES)


@pytest.mark.parametrize("category", CATEGORIES, ids=lambda cls: cls.__name__)
def test_every_category_declares_a_fault_domain(category: type[GlobinError]) -> None:
    """An error with no category is the uncategorised error the module replaced."""
    assert isinstance(category.fault, FaultDomain)


def test_the_categories_and_the_fault_domains_correspond_exactly() -> None:
    """Neither side may gain a member without the other.

    Both directions matter. An unused domain is a category someone described and
    never built; a domain used twice means two classes claim to be the same kind
    of fault, which makes the whole axis meaningless.
    """
    declared = [category.fault for category in CATEGORIES]

    assert set(declared) == set(FaultDomain)
    assert len(declared) == len(set(declared)), f"a fault domain is claimed twice: {declared}"


def test_the_root_declares_no_fault_domain() -> None:
    """``GlobinError`` is for catching, not for raising.

    It is annotated with ``fault`` but never assigns it, so the omission is
    observable rather than a matter of etiquette: code that raises the bare root
    produces an object with no category at all.
    """
    assert not hasattr(GlobinError, "fault")
    assert "fault" in GlobinError.__annotations__


@pytest.mark.parametrize("category", CATEGORIES, ids=lambda cls: cls.__name__)
def test_no_category_inherits_a_builtin_error_type(category: type[GlobinError]) -> None:
    """The break from the ad-hoc ``ValueError`` scheme has to stay clean.

    Making :class:`~globin.errors.ValidationError` a subclass of
    :exc:`ValueError` would be an easy way to keep old ``except`` clauses
    working, and would hand every unrelated ``except ValueError`` in the codebase
    a GLOBIN fault it knows nothing about. ADR-0022 rejected it; this is the
    test that notices someone reversing the decision for convenience.
    """
    forbidden = (ValueError, TypeError, KeyError, LookupError, OSError, ArithmeticError)
    assert not issubclass(category, forbidden)


@pytest.mark.parametrize("category", CATEGORIES, ids=lambda cls: cls.__name__)
def test_a_raised_category_carries_its_message_and_its_domain(
    category: type[GlobinError],
) -> None:
    """Raising, catching by the root, and reading the domain must all work."""
    message = "the offending key"
    with pytest.raises(GlobinError) as caught:
        raise category(message)

    assert str(caught.value) == message
    assert caught.value.fault is category.fault
    assert isinstance(caught.value, category)


def test_fault_domain_round_trips_through_its_string_value() -> None:
    """A ``StrEnum`` so a domain can be logged or persisted without a conversion.

    Phase 006 gives faults somewhere to be logged, and Phase 012 gives them
    somewhere to be persisted. Both want a stable string, and the round trip is
    what makes reading one back safe.
    """
    for domain in FaultDomain:
        assert isinstance(domain, str)
        assert FaultDomain(str(domain)) is domain
        assert FaultDomain(domain.value) is domain


def test_no_category_is_named_after_a_layer_or_a_technology() -> None:
    """Names end in ``Error`` and describe a fault, not the code that raises it.

    The naming rule is the design. A hierarchy named after subsystems grows one
    class per subsystem and never answers the question a caller actually has, so
    ``AdapterError`` or ``TomlError`` appearing here would mean the axis had
    quietly changed.

    Matching is on whole CamelCase words rather than substrings: ``Transport``
    contains ``port`` and is not named after the ports layer. A substring check
    here failed on its first run, which is a fair reminder that a test can be
    wrong in the same way the code it guards can.
    """
    forbidden = {"Adapter", "Domain", "Port", "Ports", "Runtime", "Application", "Toml", "Ast"}
    for category in CATEGORIES:
        assert category.__name__.endswith("Error")
        words = set(re.findall(r"[A-Z][a-z]*", category.__name__))
        assert not words & forbidden, (
            f"{category.__name__} is named after a layer or a technology, "
            f"not after the party who must act"
        )
