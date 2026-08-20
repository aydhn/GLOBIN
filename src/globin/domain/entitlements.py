"""What a credential is permitted to do, and what GLOBIN may claim about that.

`ROADMAP.md` row 029 asks for "permission verification before use". This module
is that verification, and the first thing to say about it is what it cannot be.

**GLOBIN reaches no venue.** Transport arrives in Phase 038 and the venue's own
permission model in Phase 039, so nothing here can ask an exchange whether a key
carries the grants somebody claims. What *is* decidable locally is containment:

    GLOBIN refuses to resolve a credential for an operation whose demanded
    grants are not a subset of the grants declared for it, and never claims the
    converse.

The containment is decidable. The truth of the declaration is not, and this
module is built so that nothing can pretend otherwise.

**There is deliberately no confirmed state.** :class:`VerificationState` has four
members and none of them means "the issuer confirms this". ADR-0045 says a
platform capability is a recorded state and never a pass; here that rule is
enforced by the *absence of a name*, so no one can write ``if state is
CONFIRMED`` and proceed. A property test pins the member set and asserts no
member's value contains ``confirm``, ``verified`` or ``valid``.

**One refusal outranks every declaration.**
``docs/security/SECURITY_BASELINE.md`` section 4 says any permission allowing
funds to leave the account is refused unless a phase's specification requires it
and an ADR records the decision. :func:`withheld_grants` turns that paragraph
into a branch: a demanded :attr:`Grant.TRANSFER` yields
:attr:`VerificationState.WITHHELD` whatever the declaration says, and no
declaration can buy it back.

**Grants are not a field on** :class:`~globin.domain.secrets.SecretReference`.
That type is ordered and is what ``store_key`` folds into a platform key; a
``grants`` field would make two references with the same store key compare
unequal, which would break the inventory and the rotation procedure at once. So
what a use site *demands* and what an operator *declares* are separate types
that name a reference rather than extending it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from globin.domain.secrets import SecretReference
from globin.errors import ValidationError


class Grant(StrEnum):
    """What an operation needs a credential to be allowed to do.

    Three members, deliberately coarse. These are *classes of capability* rather
    than a venue's permission names: Binance's own vocabulary is Phase 039's, and
    naming it here would be choosing from a register this phase has not read.
    """

    READ = "read"
    """Observe. Account state, balances, order history, market data behind a key."""

    SUBMIT = "submit"
    """Place, amend and cancel orders. Moves risk; moves no funds off the venue."""

    TRANSFER = "transfer"
    """Move funds off the venue, or between accounts.

    Present so that it can be **refused**, which is the only reason it is
    modelled at all. See :func:`withheld_grants`.
    """


class VerificationState(StrEnum):
    """What is known about whether a credential may do what is being asked.

    **Four members, and none of them means confirmed.** That absence is the
    design: GLOBIN cannot ask the issuer, so a member meaning "the issuer agrees"
    would be a lie with a name. Phase 039 is where an answer of that kind becomes
    possible, and it will add the member along with the ability to earn it.

    **Phase 034 gave GLOBIN a transport and changed nothing here**, which is worth
    saying because it looks as though it should have. That transport sends three
    public, unauthenticated requests; asking what a *credential* may do needs a
    signed request, and signing is Phase 038's. Reaching the venue and being able
    to ask it about a key are different capabilities.
    """

    DECLARED = "declared"
    """The demanded grants are covered by what an operator declared.

    **Not a pass.** It means somebody wrote down what this credential carries and
    the demand fits inside it. Nothing has checked the writing against the venue.
    """

    UNDECLARED = "undeclared"
    """No declaration exists for this reference, so nothing may be assumed."""

    INSUFFICIENT = "insufficient"
    """A declaration exists and does not cover what is demanded."""

    WITHHELD = "withheld"
    """A demanded grant is one GLOBIN refuses to exercise at all.

    Independent of any declaration, and unreachable by widening one.
    """


def withheld_grants() -> tuple[Grant, ...]:
    """Grants GLOBIN refuses regardless of what is declared.

    Returns:
        The withheld grants, in a fixed order.

    A function rather than a module constant, because a tuple literal is fine but
    the surrounding rule is not a constant's job to explain, and because every
    registry in this package is a function -- the layer contract refuses a call
    executed at import time.

    ``SECURITY_BASELINE.md`` section 4 is the source: withdrawal-shaped
    permission is refused "unless a phase's specification requires it and an ADR
    records the decision". No phase requires it, so the tuple has one member and
    the refusal is a branch rather than a sentence somebody must remember.
    """
    return (Grant.TRANSFER,)


@dataclass(frozen=True, slots=True, order=True)
class GrantSet:
    """A set of grants that compares, sorts and renders deterministically.

    Args:
        grants: The grants, in any order and with any duplicates.

    Canonicalised on construction -- sorted and de-duplicated -- so that two
    sets built from the same grants in different orders are equal, and so that
    :meth:`names` is stable in evidence.
    """

    grants: tuple[Grant, ...] = ()

    def __post_init__(self) -> None:
        """Sort and de-duplicate.

        A runtime type check was written here and removed: the field is typed
        ``tuple[Grant, ...]`` and mypy proves the branch unreachable, so it was
        an assertion about a case the type system already refuses. The values
        that reach this class from outside -- a stored register -- are converted
        through ``Grant(value)`` at that boundary, which raises there instead.
        """
        canonical = tuple(sorted(set(self.grants), key=lambda grant: grant.value))
        object.__setattr__(self, "grants", canonical)

    def covers(self, demanded: "GrantSet") -> bool:
        """Whether this set permits everything another set demands.

        Args:
            demanded: What a use site needs.

        Returns:
            Whether ``demanded`` is a subset of this set.
        """
        return set(demanded.grants) <= set(self.grants)

    def missing_from(self, demanded: "GrantSet") -> tuple[Grant, ...]:
        """What ``demanded`` needs that this set does not carry.

        Args:
            demanded: What a use site needs.

        Returns:
            The shortfall, sorted.
        """
        return tuple(sorted(set(demanded.grants) - set(self.grants), key=lambda grant: grant.value))

    def excess_over(self, demanded: "GrantSet") -> tuple[Grant, ...]:
        """What this set carries beyond what is demanded.

        Args:
            demanded: What a use site needs.

        Returns:
            The surplus, sorted.

        Reported rather than refused. A key carrying more than one use site needs
        is a least-privilege observation, not a reason to stop -- and refusing it
        would make one over-broad key unusable for every operation rather than
        prompting somebody to narrow it.
        """
        return tuple(sorted(set(self.grants) - set(demanded.grants), key=lambda grant: grant.value))

    def names(self) -> tuple[str, ...]:
        """The grant names, for a record.

        Returns:
            The values, in canonical order.
        """
        return tuple(grant.value for grant in self.grants)


@dataclass(frozen=True, slots=True)
class CredentialRequirement:
    """What one use site needs of one credential.

    Args:
        reference: The credential.
        demanded: The grants the operation needs.
        purpose: Why, in a short phrase a person can act on.

    Raises:
        ValidationError: If ``purpose`` is empty.

    ``purpose`` is required because this type is what a refusal is reported
    from, and "GLOBIN needs this credential" is not something anybody can act on.
    """

    reference: SecretReference
    demanded: GrantSet
    purpose: str

    def __post_init__(self) -> None:
        """Refuse a requirement that cannot explain itself.

        Raises:
            ValidationError: As documented on the class.
        """
        if not self.purpose.strip():
            msg = "a credential requirement must state its purpose"
            raise ValidationError(msg)


@dataclass(frozen=True, slots=True)
class GrantDeclaration:
    """What an operator states one credential carries.

    Args:
        reference: The credential.
        declared: The grants the operator says it has.

    **There is no timestamp**, and its absence is a decision rather than an
    omission. A date would need a clock injected through the composition root
    into a value type, and it would not participate in any verdict:
    :func:`verify` is a function of containment alone. Recording *when* somebody
    declared something is an audit question, and the register that stores these
    is free to answer it without the value type carrying it.

    **It cannot hold a secret.** There are two fields, one a reference and one a
    set of bounded enum members, so there is no branch in which material could be
    written into a declaration and no field for it to occupy.
    """

    reference: SecretReference
    declared: GrantSet

    def as_record(self) -> dict[str, object]:
        """Render as ordinary data.

        Returns:
            The reference's public parts and the declared grant names.
        """
        return {
            "environment": self.reference.environment.text,
            "name": self.reference.name,
            "kind": self.reference.kind.value,
            "declared": list(self.declared.names()),
        }


@dataclass(frozen=True, slots=True)
class PermissionVerdict:
    """Whether a credential may be used for what is being asked.

    Args:
        reference: The credential.
        state: What is known.
        missing: Demanded grants the declaration does not cover.
        excess: Declared grants the demand does not need.
    """

    reference: SecretReference
    state: VerificationState
    missing: tuple[Grant, ...] = ()
    excess: tuple[Grant, ...] = ()

    @property
    def permitted(self) -> bool:
        """Whether use may proceed.

        Returns:
            Whether the state is :attr:`VerificationState.DECLARED`.

        One state out of four permits, and it is spelled out here rather than
        left to each caller to remember which members are refusals.
        """
        return self.state is VerificationState.DECLARED

    def as_record(self) -> dict[str, object]:
        """Render as ordinary data.

        Returns:
            The reference's public parts, the state, and both differences.
        """
        return {
            "environment": self.reference.environment.text,
            "name": self.reference.name,
            "kind": self.reference.kind.value,
            "state": self.state.value,
            "missing": [grant.value for grant in self.missing],
            "excess": [grant.value for grant in self.excess],
        }


def verify(
    requirement: CredentialRequirement,
    declaration: GrantDeclaration | None,
) -> PermissionVerdict:
    """Decide whether a credential may be used for a requirement.

    Args:
        requirement: What the use site demands.
        declaration: What an operator declared, or ``None`` when nothing is.

    Returns:
        The verdict.

    The order of the four branches is the design. A withheld grant is checked
    **first**, before the declaration is even consulted, so that no declaration
    can reach the decision -- a check placed after the declaration would be one
    edit away from being satisfiable by declaring the grant.
    """
    withheld = tuple(grant for grant in withheld_grants() if grant in requirement.demanded.grants)
    if withheld:
        return PermissionVerdict(
            reference=requirement.reference,
            state=VerificationState.WITHHELD,
            missing=withheld,
        )
    if declaration is None:
        return PermissionVerdict(
            reference=requirement.reference,
            state=VerificationState.UNDECLARED,
            missing=requirement.demanded.grants,
        )
    if not declaration.declared.covers(requirement.demanded):
        return PermissionVerdict(
            reference=requirement.reference,
            state=VerificationState.INSUFFICIENT,
            missing=declaration.declared.missing_from(requirement.demanded),
        )
    return PermissionVerdict(
        reference=requirement.reference,
        state=VerificationState.DECLARED,
        excess=declaration.declared.excess_over(requirement.demanded),
    )


def declaration_for(
    reference: SecretReference,
    declarations: Sequence[GrantDeclaration],
) -> GrantDeclaration | None:
    """Find the declaration naming a reference.

    Args:
        reference: The credential.
        declarations: Every declaration the register holds.

    Returns:
        The first declaration for that reference, or ``None``.
    """
    for declaration in declarations:
        if declaration.reference == reference:
            return declaration
    return None


def required_credentials() -> tuple[CredentialRequirement, ...]:
    """Every credential a start-up genuinely cannot proceed without.

    Returns:
        The requirements. **Empty**, and empty by derivation rather than by
        omission.

    A start-up needs a credential only if a component that runs at start-up will
    use one. **Phase 035 built the signing layer and this set stayed empty**, which
    is the distinction: GLOBIN can sign a request, and nothing that runs at
    start-up sends one. Phase 039 verifies key permissions and is the first with a
    real requirement, so today the honest answer is none -- and declaring one here
    would make ``bootstrap check`` refuse on every clean host, including the one CI
    builds, which could only be satisfied by manufacturing a credential to meet a
    requirement nothing has established.

    **What changed in Phase 029 is that the emptiness became a derivation.** The
    composition root feeds this into ``StoreBackedSecrets.required`` and into the
    entitlement probe, so the phase that has a real requirement adds one entry
    here and the start-up begins demanding it with no further plumbing. That
    wiring, rather than a non-empty tuple, is this phase's deliverable.

    A function rather than a constant, for the reason every registry in this
    package is one: the layer contract refuses a call executed at import time.
    """
    return ()


def required_references() -> tuple[SecretReference, ...]:
    """Every reference a start-up must be able to resolve.

    Returns:
        The references named by :func:`required_credentials`, sorted and
        de-duplicated.
    """
    return tuple(sorted({item.reference for item in required_credentials()}))
