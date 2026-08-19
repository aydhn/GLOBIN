"""What an environment promises, as opposed to what it is called.

:class:`~globin.domain.identifiers.EnvironmentId` carries a name and says plainly
that it asserts nothing about what the name means: *"Naming an environment is not
classifying one. ADR-0006 refuses to treat 'not production' as a single thing, and
Phase 035 models the classes and their guarantees."* This module is that model.

**Four classes, and the fourth is why the module exists.** Phase 033's registry
classifies environments the *venue* publishes, each an
:class:`~globin.domain.api_reality.EnvironmentRecord` carrying ``semantics``,
``carries_real_capital`` and a ``host_marker``. It has no row for ``paper``,
GLOBIN's own simulated execution, and structurally cannot have one: a registry of
venue facts has nowhere to put an environment the venue has never heard of, and
inventing a row for one would be recording a claim about Binance that Binance does
not make.

**The guarantee that carries this phase's other half is**
:attr:`EnvironmentGuarantees.accepts_credential`. It is ``False`` for exactly one
class, and it is gate 1 of :func:`globin.application.auth.resolve_auth` — checked
*before* the registry, before a credential is looked up, and before any signer is
selected. An environment GLOBIN simulates has no venue to authenticate to, so
there is nothing a credential could mean there.

**This module names no environment, and that is an architecture rule rather than
a preference.** ``tests/architecture/test_identifier_discipline.py`` refuses a
venue instance name anywhere in the domain layer, because *which* environments a
venue publishes is answered against the venue and changes without GLOBIN being
redeployed. So the *kinds* live here as :class:`EnvironmentClass` — which is
shape — and the *mapping from a name to a kind* lives in
``docs/engineering/environment-classes.toml``, read by
:mod:`globin.adapters.environment_class` and carried as an
:class:`EnvironmentClassification`. The first draft of this module put the mapping
here and the tripwire caught it, which is the check working rather than a hurdle.

**The class values are GLOBIN's vocabulary, not the venue's**, for the same
reason and following :class:`~globin.domain.api_reality.ProductScope`'s
precedent. A venue that renamed its testnet would change a row in a document, not
a member of an enumeration.

**Two guarantees are not derivable from the others**, which is why there are seven
booleans rather than a severity:

:attr:`EnvironmentGuarantees.market_data_is_real` is ``True`` for
:attr:`EnvironmentClass.LIVE_CAPITAL` *and for*
:attr:`EnvironmentClass.INTERNAL_SIMULATION`, and ``False`` for the two venue
sandboxes. Demo Mode's own document says *"Realistic market data is not equal to
'real' market data"*; ``config/profiles/paper.toml`` says *"Simulated execution
against real market data"*. So the simulated environment has real prices and
computed fills, while demo has realistic prices and — to itself — real fills.
Collapsing the two into one "is this real" axis would lose exactly the distinction
a backtest's validity turns on.

:attr:`EnvironmentGuarantees.feature_parity_with_live` is what separates the two
venue sandboxes, which agree on every other field. Demo Mode is documented as
*"always has the same features as the live exchange"*; the testnet is documented
as having order books *independent* of the live exchange, with new features
appearing there first. A caller asking *does behaviour here predict production*
gets different answers, and without this field the two classes would be
indistinguishable and the roadmap row's "distinct guarantees" would be untrue.

This module performs no I/O, reads no document and knows no host. It is pure data
and total functions, which is what lets the authentication gate consult it from
the domain layer.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.errors import InternalError, ValidationError

SCHEMA: Final[str] = "globin.environment.classes"
"""What a document produced by this surface calls itself."""

SCHEMA_VERSION: Final[int] = 1
"""The version every document this surface emits is written against."""

PHASE: Final[int] = 35
"""The phase that built this. Recorded in evidence rather than inferred."""

GLOBIN_OWN_SOURCE: Final[str] = "globin-own"
"""What a guarantee cites when GLOBIN itself is the one making the claim.

Deliberately **not** an identifier in ``binance-api-reality.toml``'s source table,
and deliberately not shaped like one. Internal simulation is an environment GLOBIN
hosts, so its guarantees are GLOBIN's own declaration; citing a venue document for
them would attribute a claim to Binance that Binance has never made.
``tests/contract/test_environment_class_contract.py`` asserts that this is the
only class citing it and that no venue-hosted class does.
"""

MAX_CLASSIFIED_NAMES: Final[int] = 32
"""How many environment names one classification may carry.

A bound rather than a limit anybody has approached — four names are classified
today. It exists because a classification is built from a document, and every
document this repository reads is bounded rather than trusted.
"""


class EnvironmentClass(StrEnum):
    """What kind of environment this is, among the four the programme recognises.

    ROADMAP row 035 names exactly these — *"production, testnet, demo and internal
    simulation as distinct classes with distinct guarantees"* — and there is no
    fifth. A venue that published a new environment would add a **name**, which is
    data in ``environment-classes.toml``; a new *kind* of guarantee requires
    somebody to read a document and decide what it promises, which is why this is
    an enumeration and the mapping is not.

    **The values are GLOBIN's own words**, following
    :class:`~globin.domain.api_reality.ProductScope`, which spells ``trading`` and
    ``supporting`` rather than anything the venue calls itself. A domain module
    naming a venue instance is what
    ``tests/architecture/test_identifier_discipline.py`` refuses, and the ``venue_``
    prefix carries real meaning besides: it separates the two classes the venue
    hosts from the one GLOBIN does.
    """

    LIVE_CAPITAL = "live_capital"
    """The live exchange. The only class where an order moves real capital."""

    VENUE_TESTNET = "venue_testnet"
    """Separate venue infrastructure with its own keys and independent order books.

    Distinguished from :attr:`VENUE_DEMO` by
    :attr:`EnvironmentGuarantees.feature_parity_with_live` alone: new features are
    documented as appearing here first, so behaviour observed here does not
    predict production.
    """

    VENUE_DEMO = "venue_demo"
    """Virtual balances on the venue's demo hosts, with the live feature set.

    Documented as *"always has the same features as the live exchange"*, which is
    the one guarantee separating it from :attr:`VENUE_TESTNET`.
    """

    INTERNAL_SIMULATION = "internal_simulation"
    """GLOBIN's own simulated execution. No venue, and therefore no credential.

    The class the default profile names, and the one this module exists for. Every
    other class is something Phase 033's registry could describe.
    """


@dataclass(frozen=True, slots=True, order=True)
class EnvironmentGuarantees:
    """What one class promises, as seven independent facts.

    Raises:
        ValidationError: On empty semantics or an empty source; on a class that
            reaches no venue while claiming to accept a credential, own venue
            state, bind an order or match the live feature set; or on one that
            risks real capital without binding orders.

    **Seven booleans rather than a tier**, because they are genuinely independent —
    the module docstring records the two pairs that prove it. A severity would have
    to choose an order between "loses money" and "shows real prices", and no such
    order is right for both a risk check and a research check.

    The consistency rules below each rule out a class that would be a
    contradiction rather than a surprise. An environment that reaches no venue
    cannot own state at a venue, cannot accept a credential — there is nobody to
    present one to — cannot bind an order, and cannot match a live feature set it
    has no access to. A class that got any of those wrong would pass every gate in
    :mod:`globin.application.auth` and then fail at a socket, which is the failure
    mode fail-closed exists to prevent.
    """

    environment_class: EnvironmentClass
    carries_real_capital: bool
    reaches_venue: bool
    accepts_credential: bool
    orders_are_binding: bool
    market_data_is_real: bool
    state_is_venue_owned: bool
    feature_parity_with_live: bool
    source: str
    semantics: str

    def __post_init__(self) -> None:
        """Refuse a class whose guarantees contradict one another."""
        if not self.semantics:
            msg = f"{self.environment_class.value} declares no semantics"
            raise ValidationError(msg)
        if not self.source:
            msg = f"{self.environment_class.value} cites no source for its guarantees"
            raise ValidationError(msg)
        if not self.reaches_venue:
            unreachable = (
                ("accepts_credential", "accept a credential; there is nobody to present one to"),
                ("state_is_venue_owned", "own state at a venue it does not reach"),
                ("orders_are_binding", "bind an order at a venue it does not reach"),
                ("feature_parity_with_live", "match a live feature set it has no access to"),
            )
            for field, description in unreachable:
                if getattr(self, field):
                    msg = (
                        f"{self.environment_class.value} reaches no venue and claims to "
                        f"{description}"
                    )
                    raise ValidationError(msg)
        if self.carries_real_capital and not self.orders_are_binding:
            msg = (
                f"{self.environment_class.value} risks real capital and declares its orders "
                "non-binding; capital does not move without a binding order"
            )
            raise ValidationError(msg)

    @property
    def venue_hosted(self) -> bool:
        """Whether the venue is the one that runs this class of environment.

        Returns:
            ``True`` for every class but :attr:`EnvironmentClass.INTERNAL_SIMULATION`.

        The same question as :attr:`reaches_venue` today and named separately
        because they are different claims: one is about who operates the
        environment and the other about whether a request leaves this machine. A
        class that was venue-hosted and unreachable would need them apart.
        """
        return self.environment_class is not EnvironmentClass.INTERNAL_SIMULATION

    def as_record(self) -> dict[str, object]:
        """These guarantees as plain JSON-safe values."""
        return {
            "class": self.environment_class.value,
            "carries_real_capital": self.carries_real_capital,
            "reaches_venue": self.reaches_venue,
            "accepts_credential": self.accepts_credential,
            "orders_are_binding": self.orders_are_binding,
            "market_data_is_real": self.market_data_is_real,
            "state_is_venue_owned": self.state_is_venue_owned,
            "feature_parity_with_live": self.feature_parity_with_live,
            "source": self.source,
            "semantics": self.semantics,
        }


def guarantees() -> tuple[EnvironmentGuarantees, ...]:
    """Every class and what it promises, in declaration order.

    Returns:
        One entry per member of :class:`EnvironmentClass`, and no other.

    A function rather than a constant, for the reason every registry in this
    package is one: ``tests/architecture/test_architecture_contract.py`` holds
    every layer package to performing no work at import, and constructing a
    dataclass is work.

    ``semantics`` is kept short here and long in
    ``docs/engineering/environment-classes.toml``. The contract test compares the
    *guarantees* between the two rather than the prose, so an editorial
    improvement to the document does not fail the suite — the rule
    ``docs/TESTING_STRATEGY.md`` states about snapshot tests, applied to the one
    place it would be tempting to ignore.
    """
    return (
        EnvironmentGuarantees(
            environment_class=EnvironmentClass.LIVE_CAPITAL,
            carries_real_capital=True,
            reaches_venue=True,
            accepts_credential=True,
            orders_are_binding=True,
            market_data_is_real=True,
            state_is_venue_owned=True,
            feature_parity_with_live=True,
            source="spot-rest",
            semantics="The live exchange; the only class where an order moves capital.",
        ),
        EnvironmentGuarantees(
            environment_class=EnvironmentClass.VENUE_TESTNET,
            carries_real_capital=False,
            reaches_venue=True,
            accepts_credential=True,
            orders_are_binding=False,
            market_data_is_real=False,
            state_is_venue_owned=True,
            feature_parity_with_live=False,
            source="spot-testnet",
            semantics="Separate venue infrastructure with its own keys and order books.",
        ),
        EnvironmentGuarantees(
            environment_class=EnvironmentClass.VENUE_DEMO,
            carries_real_capital=False,
            reaches_venue=True,
            accepts_credential=True,
            orders_are_binding=False,
            market_data_is_real=False,
            state_is_venue_owned=True,
            feature_parity_with_live=True,
            source="spot-demo",
            semantics="Virtual balances on venue-hosted demo infrastructure.",
        ),
        EnvironmentGuarantees(
            environment_class=EnvironmentClass.INTERNAL_SIMULATION,
            carries_real_capital=False,
            reaches_venue=False,
            accepts_credential=False,
            orders_are_binding=False,
            market_data_is_real=True,
            state_is_venue_owned=False,
            feature_parity_with_live=False,
            source=GLOBIN_OWN_SOURCE,
            semantics="GLOBIN's own simulated execution against real market data.",
        ),
    )


def guarantees_for(environment_class: EnvironmentClass) -> EnvironmentGuarantees:
    """What one class promises.

    Args:
        environment_class: The class.

    Returns:
        Its guarantees.

    Raises:
        InternalError: If the class has no declared guarantees, which
            :func:`guarantees` returning one entry per member already prevents. It
            is raised rather than defaulted because a class with no guarantees is a
            broken invariant rather than bad input.
    """
    for entry in guarantees():
        if entry.environment_class is environment_class:
            return entry
    msg = f"{environment_class.value} has no declared guarantees"
    raise InternalError(msg)


@dataclass(frozen=True, slots=True)
class EnvironmentClassification:
    """Which environment names belong to which classes, read from a document.

    Raises:
        ValidationError: On an empty name, a duplicate name, or more than
            :data:`MAX_CLASSIFIED_NAMES` entries.

    **The instance register the domain layer may hold but not spell.**
    ``tests/architecture/test_identifier_discipline.py`` refuses a venue
    environment *name* anywhere in this layer, and it is right to: which
    environments a venue publishes changes without GLOBIN being redeployed, so a
    tuple compiled into the innermost layer would be wrong quietly. This type is
    the shape of that register; the values arrive from
    ``docs/engineering/environment-classes.toml`` through
    :mod:`globin.adapters.environment_class`.

    **Declared rather than computed**, wherever the values come from. A rule such
    as *a name containing "test" is a testnet* would be a naming heuristic deciding
    a security-relevant fact, and
    :class:`~globin.domain.api_reality.EnvironmentRecord` already learned that
    lesson from the other direction: its ``host_marker`` exists so a live host
    filed under a paper environment is refused **structurally**, rather than by a
    rule about spelling that somebody trusts.
    """

    entries: tuple[tuple[str, EnvironmentClass], ...] = ()

    def __post_init__(self) -> None:
        """Refuse a classification that could not answer a question unambiguously."""
        if len(self.entries) > MAX_CLASSIFIED_NAMES:
            msg = (
                f"a classification carries {len(self.entries)} environments and the limit is "
                f"{MAX_CLASSIFIED_NAMES}"
            )
            raise ValidationError(msg)
        seen: set[str] = set()
        for name, _ in self.entries:
            if not name:
                msg = "a classification carries an environment with an empty name"
                raise ValidationError(msg)
            if name in seen:
                msg = (
                    f"a classification files {name!r} twice; an environment belongs to exactly "
                    "one class, and two rows would make the answer depend on read order"
                )
                raise ValidationError(msg)
            seen.add(name)

    def classify(self, name: str) -> EnvironmentClass | None:
        """Which class an environment name belongs to.

        Args:
            name: The environment's name, as
                :class:`~globin.domain.identifiers.EnvironmentId` or
                :class:`~globin.domain.api_reality.EnvironmentName` spells it.

        Returns:
            The class, or ``None`` when the name is not one this document
            classifies.

        **``None`` rather than a default, and that is the fail-closed half.** A
        name nobody has classified is not *probably a testnet*; it is a name whose
        guarantees nobody has written down. :mod:`globin.application.auth` turns
        that into a refusal. Defaulting to the safest class would be defensible and
        would still be a guess, and a guess about which environment this is is the
        one guess ADR-0006 forbids by name.
        """
        for entry, environment_class in self.entries:
            if entry == name:
                return environment_class
        return None

    def guarantees_for_name(self, name: str) -> EnvironmentGuarantees | None:
        """What an environment name promises, if it is classified at all.

        Args:
            name: The environment's name.

        Returns:
            Its guarantees, or ``None`` when the name is unclassified.

        The one call the authentication gate needs, so a caller never has to
        remember that an unclassified name and a classified one take two steps.
        """
        environment_class = self.classify(name)
        return None if environment_class is None else guarantees_for(environment_class)

    def credentialled_names(self) -> tuple[str, ...]:
        """Every environment name a credential may be presented in.

        Returns:
            The names, sorted, whose class accepts a credential.

        Derived rather than listed, so an environment whose class stopped accepting
        credentials disappears from here without anybody editing a second list.
        """
        return tuple(
            sorted(
                name
                for name, environment_class in self.entries
                if guarantees_for(environment_class).accepts_credential
            )
        )

    def as_record(self) -> dict[str, object]:
        """This classification as plain JSON-safe values."""
        return {
            "environments": [
                {"name": name, "class": environment_class.value}
                for name, environment_class in self.entries
            ],
            "credentialled": list(self.credentialled_names()),
        }


__all__ = [
    "GLOBIN_OWN_SOURCE",
    "MAX_CLASSIFIED_NAMES",
    "PHASE",
    "SCHEMA",
    "SCHEMA_VERSION",
    "EnvironmentClass",
    "EnvironmentClassification",
    "EnvironmentGuarantees",
    "guarantees",
    "guarantees_for",
]
