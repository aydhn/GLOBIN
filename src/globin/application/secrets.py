"""Using the secret store: requiring, rotating, and reporting readiness.

Three use cases, and the split between them is the caller's *intent* rather than
the store's behaviour. :func:`require` is for a caller that cannot proceed
without the material, so a fault becomes a refusal. :func:`readiness` is for a
caller asking whether a start-up could proceed, so a fault becomes a report.
:func:`rotate` is for replacing material without losing it. The port raises for
none of them, which is what lets one implementation serve all three.

**Rotation is constructed here because the platform supplies none of it.**
``phase_020_sources.md`` S-10 records that a Windows credential write creates or
replaces, that the only flag offered *preserves* rather than *compares*, and
that there is no conditional write, version token or exchange.
``docs/security/SECRET_STORE_CONTRACT.md`` §4 therefore specifies an ordering
and says "that ordering is the whole of the guarantee". :func:`rotate`
implements it, with one addition the contract implies but does not spell:
because a write replaces, the previous value must be **moved to
:attr:`~globin.domain.secrets.SecretSlot.PREVIOUS` before the new one is
written**, or step 3's "retire the previous one" would be retiring something
that no longer exists.

**Nothing here caches.** §7 discharges Microsoft's collect-late-discard-early
principle "by resolving a secret in the narrowest scope that needs it and
holding no long-lived cache", and a memoising resolver would quietly become the
second store nobody declared. Every call reaches the port.

**No function here logs the material, and none logs a value-shaped derivative.**
An audit record may name the reference, the operation, the outcome and the
environment; §4 forbids the old material, the new material and any part of
either, which rules out a "changed from X to Y" record and a digest computed
over a value GLOBIN would have to retain to compare against.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from globin.domain.bootstrap import SecretReadiness
from globin.domain.entitlements import (
    CredentialRequirement,
    GrantDeclaration,
    PermissionVerdict,
    VerificationState,
    declaration_for,
    verify,
)
from globin.domain.secrets import (
    EntryFault,
    EntryProblem,
    SecretLocator,
    SecretProviderKind,
    SecretReference,
    SecretResolution,
    SecretSlot,
    SecretValue,
    StoreFault,
    store_key,
)
from globin.errors import ConfigurationError, InternalError
from globin.ports.secret_entry import SecretEntry
from globin.ports.secrets import SecretStore

REMEDIATION: dict[StoreFault, str] = {
    StoreFault.ABSENT: "store it before starting; no value is ever printed back",
    StoreFault.ENVIRONMENT_MISMATCH: "the reference names a different environment",
    StoreFault.KIND_MISMATCH: "the stored material is not the kind requested",
    StoreFault.NO_CREDENTIAL_SET: (
        "this logon session has no credential set; a network logon does not have one"
    ),
    StoreFault.BACKEND_UNAVAILABLE: "the local credential store is not reachable on this host",
    StoreFault.BACKEND_REFUSED: "the credential store refused the operation",
    StoreFault.VALUE_TOO_LARGE: "the value exceeds what a credential blob can hold",
    StoreFault.VERIFICATION_FAILED: "the value read back did not match the value written",
    StoreFault.PROVIDER_READ_ONLY: (
        "this provider is a hand-off rather than a store, so it never accepts a write"
    ),
    StoreFault.PROVIDER_NOT_PERMITTED: (
        "this profile does not permit that provider; store the value in the local store instead"
    ),
    StoreFault.ENVELOPE_CORRUPT: (
        "the stored envelope failed its own integrity check; rotate the credential to replace it"
    ),
}
"""What an operator should do about each fault, in one bounded phrase.

A plain :class:`dict` rather than a mapping proxy or a frozen structure, because
this is the application layer and the no-call-at-import rule binds layer
*packages* — but it is treated as constant and a contract test asserts it covers
every member of :class:`~globin.domain.secrets.StoreFault`, so a fault added
later cannot arrive without a remediation.

None of these phrases contains material, a length, or anything derived from a
value. ``SECRET_STORE_CONTRACT.md`` §3 permits an error to "name the logical
secret, name the backend fault, and name the command that would remediate it",
and that is the whole permitted surface.
"""


@dataclass(frozen=True, slots=True)
class RotationOutcome:
    """What a rotation did, and whether the previous value survived it.

    Args:
        reference: What was rotated.
        rotated: Whether the new value is now current and verified.
        fault: Why not, when it is not.
        previous_recoverable: Whether working material for this reference can
            still be obtained.

    ``previous_recoverable`` is the field that matters and it is the reason this
    is a type rather than a boolean. §4's guarantee is not "rotation succeeds";
    it is "**a failure at any step leaves the previous secret resolvable**". A
    caller that only learned rotation had failed would not know whether it had
    failed safely, and that is precisely the question an operator is about to
    ask.

    On every failure path it carries whether a previous value existed to be
    preserved — which is the honest answer, because a rotation of a reference
    that held nothing has nothing to fall back on. It is not "the rotation was
    undone": nothing here rolls back, and the current slot after a verification
    failure may hold either value.
    """

    reference: SecretReference
    rotated: bool
    fault: StoreFault | None = None
    previous_recoverable: bool = True

    def as_record(self) -> dict[str, object]:
        """This outcome as the mapping an audit record carries.

        Returns:
            The reference's parts and what happened, and no material.
        """
        return {
            "environment": self.reference.environment.text,
            "kind": self.reference.kind.value,
            "name": self.reference.name,
            "rotated": self.rotated,
            "fault": self.fault.value if self.fault is not None else None,
            "previous_recoverable": self.previous_recoverable,
        }


def require(store: SecretStore, reference: SecretReference) -> SecretValue:
    """Resolve a secret a caller cannot proceed without.

    Args:
        store: The store to ask.
        reference: What is needed.

    Returns:
        The material.

    Raises:
        ConfigurationError: If the reference does not resolve, for any reason.
            The message names the reference and the fault; it never carries the
            material, a prefix of it, or a length.

    A :class:`~globin.errors.ConfigurationError` rather than any other category
    because the operator must change something about the environment before a
    retry could succeed — which is exactly what that class documents. Every
    fault maps to it, including
    :attr:`~globin.domain.secrets.StoreFault.BACKEND_UNAVAILABLE`: a store that
    cannot be reached on this host is a host that was not prepared, not a
    transport failure and not a GLOBIN defect.
    """
    resolution = store.resolve(reference)
    if resolution.value is None:
        fault = resolution.fault
        detail = REMEDIATION.get(fault, "the store did not say why") if fault else ""
        msg = (
            f"the secret {reference.name!r} ({reference.kind.value}) for environment "
            f"{reference.environment.text!r} could not be resolved: "
            f"{fault.value if fault else 'unknown'} -- {detail}"
        )
        raise ConfigurationError(msg)
    return resolution.value


def resolve(store: SecretStore, reference: SecretReference) -> SecretResolution:
    """Resolve a secret whose absence is an acceptable answer.

    Args:
        store: The store to ask.
        reference: What to look for.

    Returns:
        The resolution, unchanged from the store.

    A pass-through, and deliberately so. It exists to give a caller who wants
    the non-raising behaviour something to call that says which behaviour it
    chose, rather than reaching past the application layer into the port.
    """
    return store.resolve(reference)


def readiness(store: SecretStore, required: tuple[SecretReference, ...]) -> SecretReadiness:
    """Report whether every required reference resolves.

    Args:
        store: The store to ask.
        required: The references a start-up needs. Empty today, and empty
            because GLOBIN holds no credentials rather than by omission.

    Returns:
        The readiness, naming the required references and the unavailable ones.

    Feeds :func:`~globin.domain.bootstrap.secrets_outcome` unchanged, which is
    why the return type is Phase 021's rather than a new one: that function
    already distinguishes a vacuous pass from a skipped check, and this phase
    had no reason to make it distinguish anything else.

    **The store is consulted once per reference and the values are discarded
    immediately.** A readiness check that held what it resolved in order to
    report on it would be the cache §7 forbids.
    """
    unavailable = tuple(
        sorted(reference.name for reference in required if not store.resolve(reference).resolved)
    )
    return SecretReadiness(
        required=tuple(sorted(reference.name for reference in required)),
        unavailable=unavailable,
    )


def rotate(
    store: SecretStore, reference: SecretReference, replacement: SecretValue
) -> RotationOutcome:
    """Replace a secret's material without losing the previous value.

    Args:
        store: The store to write through.
        reference: What to rotate.
        replacement: The new material.

    Returns:
        The outcome, including whether the previous material is still
        resolvable after a failure.

    The ordering ``SECRET_STORE_CONTRACT.md`` §4 requires, with the step the
    platform forces in front of it:

    0. Copy the current value to :attr:`~globin.domain.secrets.SecretSlot.PREVIOUS`.
       Without this there is nothing to fall back to, because step 1 replaces.
    1. Write the new value to :attr:`~globin.domain.secrets.SecretSlot.CURRENT`.
    2. Read it back and compare it against what was written.
    3. Only then delete the previous copy.

    A failure at 0 leaves everything untouched. A failure at 1 or 2 leaves the
    previous value at ``PREVIOUS`` and reports
    ``previous_recoverable=True`` — the current slot may hold either value at
    that point, which is why the outcome reports recoverability rather than
    claiming the rotation was undone. Nothing here rolls back, because a
    rollback that failed would leave no record of which write had won.

    Rotating a reference that has no current value is not an error: there is
    nothing to preserve, so it degenerates to a write followed by a
    verification, and ``previous_recoverable`` is ``True`` vacuously.
    """
    current = store.resolve(reference)
    had_previous = current.value is not None

    if current.value is not None:
        fault = store.store(reference, current.value, SecretSlot.PREVIOUS)
        if fault is not None:
            return RotationOutcome(
                reference=reference,
                rotated=False,
                fault=fault,
                previous_recoverable=had_previous,
            )

    fault = store.store(reference, replacement, SecretSlot.CURRENT)
    if fault is not None:
        return RotationOutcome(
            reference=reference,
            rotated=False,
            fault=fault,
            previous_recoverable=had_previous,
        )

    verification = store.resolve(reference, SecretSlot.CURRENT)
    if verification.value is None or verification.value != replacement:
        return RotationOutcome(
            reference=reference,
            rotated=False,
            fault=StoreFault.VERIFICATION_FAILED,
            previous_recoverable=had_previous,
        )

    if had_previous:
        store.delete(reference, SecretSlot.PREVIOUS)
    return RotationOutcome(reference=reference, rotated=True)


def inventory_keys(references: tuple[SecretReference, ...]) -> tuple[str, ...]:
    """Render the store keys a set of references occupies.

    Args:
        references: The references to render.

    Returns:
        One key per reference, for the current slot, sorted.

    Useful in a report and safe in one: a key is built from an environment, a
    kind and a name, all of which are ordinary data. It is offered here so that
    a caller never composes a key itself — ``SECRET_STORE_CONTRACT.md`` §2
    permits exactly one builder, and this routes to it.
    """
    return tuple(sorted(store_key(reference) for reference in references))


ENTRY_REMEDIATION: dict[EntryFault, str] = {
    EntryFault.NOT_INTERACTIVE: (
        "Run this at a terminal. Collection is interactive only, so that "
        "material never reaches shell history or a process command line."
    ),
    EntryFault.ECHO_UNAVAILABLE: (
        "This terminal cannot hide what you type, so nothing was read. Use a "
        "console that supports it rather than accepting a visible entry."
    ),
    EntryFault.CANCELLED: "Nothing was stored. Run the command again when ready.",
    EntryFault.MISMATCH: (
        "The two entries differed, so nothing was stored. Run the command again."
    ),
    EntryFault.REFUSED_FORMAT: (
        "The material cannot be stored as typed. The reported problems say "
        "which rule it broke; no part of what you typed is shown."
    ),
    EntryFault.ENTRY_UNAVAILABLE: (
        "The terminal could not be read. Run this directly rather than through "
        "a wrapper that redirects input."
    ),
}
"""What to do about each way collection can fail.

Total over :class:`~globin.domain.secrets.EntryFault`, and a contract test says
so. A fault with no remediation is a refusal an operator cannot act on, which is
the failure mode this table exists to prevent.
"""

VERDICT_REMEDIATION: dict[VerificationState, str] = {
    VerificationState.DECLARED: (
        "Permitted by the declaration on record. Nothing has verified that "
        "declaration against the venue, and nothing in this phase can."
    ),
    VerificationState.UNDECLARED: (
        "No grants are declared for this credential. Declare them with "
        "globin secrets set, which asks what the key is permitted to do."
    ),
    VerificationState.INSUFFICIENT: (
        "The declaration does not cover what this operation needs. Either "
        "narrow the operation or re-declare the credential to match the key."
    ),
    VerificationState.WITHHELD: (
        "GLOBIN refuses this permission class outright. SECURITY_BASELINE.md "
        "section 4 withholds anything that can move funds off the account, and "
        "no declaration can grant it."
    ),
}
"""What to do about each verification state.

Total over :class:`~globin.domain.entitlements.VerificationState`, asserted by a
contract test for the same reason as the table above.
"""


@dataclass(frozen=True, slots=True)
class CollectionOutcome:
    """What one interactive collection did, end to end.

    Args:
        reference: What was being set.
        stored: Whether material is now current for that reference.
        entry_fault: Why collection failed, when it did.
        problems: Which format rules the material broke, when it did.
        store_fault: Why the write failed, when it did.
        rotation: The rotation outcome, when the command rotated rather than set.

    **No field can hold material.** There is no value field, and there is no
    branch that could add one: :class:`~globin.domain.secrets.SecretValue` has no
    encoder and no string form, so it could not be rendered even if a field
    existed.
    """

    reference: SecretReference
    stored: bool
    entry_fault: EntryFault | None = None
    problems: tuple[EntryProblem, ...] = ()
    store_fault: StoreFault | None = None
    rotation: RotationOutcome | None = None

    def as_record(self) -> dict[str, object]:
        """This outcome as the mapping a record carries.

        Returns:
            The reference's public parts and what happened. No material, because
            none is held.
        """
        return {
            "environment": self.reference.environment.text,
            "kind": self.reference.kind.value,
            "name": self.reference.name,
            "stored": self.stored,
            "entry_fault": None if self.entry_fault is None else self.entry_fault.value,
            "problems": [problem.value for problem in self.problems],
            "store_fault": None if self.store_fault is None else self.store_fault.value,
            "rotation": None if self.rotation is None else self.rotation.as_record(),
        }


def set_from_entry(
    entry: SecretEntry,
    store: SecretStore,
    reference: SecretReference,
    *,
    prompt: str,
) -> CollectionOutcome:
    """Collect a secret from a person and store it.

    Args:
        entry: How to ask.
        store: Where to put it.
        reference: What is being set.
        prompt: What to show before the entry.

    Returns:
        What happened, with no material in it.

    The value exists for the width of this function and is handed straight to the
    store. Nothing caches it, nothing logs it, and the outcome that comes back
    has no field it could occupy.
    """
    outcome = entry.collect(prompt)
    if outcome.value is None:
        return CollectionOutcome(
            reference=reference,
            stored=False,
            entry_fault=outcome.fault,
            problems=outcome.problems,
        )
    fault = store.store(reference, outcome.value)
    return CollectionOutcome(
        reference=reference,
        stored=fault is None,
        store_fault=fault,
    )


def rotate_from_entry(
    entry: SecretEntry,
    store: SecretStore,
    reference: SecretReference,
    *,
    prompt: str,
) -> CollectionOutcome:
    """Collect a replacement and rotate to it.

    Args:
        entry: How to ask.
        store: Where to write.
        reference: What is being rotated.
        prompt: What to show before the entry.

    Returns:
        What happened, carrying the rotation outcome when one was attempted.

    Reuses :func:`rotate` unchanged. Collection replaces only where the
    replacement value comes from; the four-step ordering that keeps the previous
    value resolvable is not reimplemented here and must not be.
    """
    outcome = entry.collect(prompt)
    if outcome.value is None:
        return CollectionOutcome(
            reference=reference,
            stored=False,
            entry_fault=outcome.fault,
            problems=outcome.problems,
        )
    rotation = rotate(store, reference, outcome.value)
    return CollectionOutcome(
        reference=reference,
        stored=rotation.rotated,
        store_fault=rotation.fault,
        rotation=rotation,
    )


def entitlement(
    requirements: tuple[CredentialRequirement, ...],
    declarations: tuple[GrantDeclaration, ...],
) -> tuple[PermissionVerdict, ...]:
    """Verify every requirement against what is declared.

    Args:
        requirements: What the use sites demand.
        declarations: What an operator declared.

    Returns:
        One verdict per requirement, in the order the requirements were given.
    """
    return tuple(
        verify(requirement, declaration_for(requirement.reference, declarations))
        for requirement in requirements
    )


def require_permitted(
    store: SecretStore,
    requirement: CredentialRequirement,
    declaration: GrantDeclaration | None,
) -> SecretValue:
    """Resolve a credential only if it is permitted to do what is being asked.

    Args:
        store: The store to ask.
        requirement: What the use site demands.
        declaration: What an operator declared, or ``None``.

    Returns:
        The material.

    Raises:
        ConfigurationError: If the verdict refuses. The message names the state
            and the missing grants, and carries no material -- the store is never
            reached, so no material exists to leak.

    **This is the roadmap's "before use", made structural.** The verdict is
    computed first and the function returns without touching the store when it
    refuses, so there is no branch in which material is resolved and then
    discarded. A unit test asserts the store double recorded zero calls on a
    refused verdict, which is the observable form of that claim.
    """
    verdict = verify(requirement, declaration)
    if not verdict.permitted:
        missing = ", ".join(grant.value for grant in verdict.missing)
        msg = (
            f"{requirement.reference.name} is not permitted to "
            f"{requirement.purpose}: {verdict.state.value}"
            f"{f' (missing {missing})' if missing else ''}. "
            f"{VERDICT_REMEDIATION[verdict.state]}"
        )
        raise ConfigurationError(msg)
    return require(store, requirement.reference)


@dataclass(frozen=True, slots=True)
class ProviderRoutedStore:
    """One store's worth of surface over several mechanisms, chosen by name.

    Args:
        providers: Every mechanism this run has, by kind.
        locators: Which mechanism holds which reference.
        default: The mechanism a reference with no locator uses.

    Raises:
        InternalError: If a locator names a provider that is not in
            ``providers``, or if ``default`` is not one of them. Refused at
            **construction**, so there is no run in which a reference routes to
            nothing and no call site that has to handle a missing mechanism.

    **There is no fallback and there is no chain.** Exactly one mechanism is
    consulted for a reference, ever, and its fault is the answer. A store that
    tried the vault when the Credential Manager said
    :attr:`~globin.domain.secrets.StoreFault.ABSENT` would make "where is this
    secret" unanswerable, would double the cost of every failed lookup, and would
    let a value be served from a weaker mechanism than the operator believed.
    ``SECRET_STORE_CONTRACT.md`` §3 names that last one as forbidden outright:
    "never a quiet fall back to somewhere less protected".

    **The default is not a fallback either.** It is reached only when *nobody
    named a provider*, which is a different situation from somebody naming one
    and being wrong — the distinction
    :func:`~globin.domain.config_layout.profile_from` already draws about
    profiles, and the reason a locator naming an absent mechanism is refused at
    construction rather than quietly defaulted.
    """

    providers: Mapping[SecretProviderKind, SecretStore]
    locators: Mapping[SecretReference, SecretLocator]
    default: SecretProviderKind

    def __post_init__(self) -> None:
        """Refuse a routing table that could not answer."""
        if self.default not in self.providers:
            listed = ", ".join(sorted(kind.value for kind in self.providers))
            msg = (
                f"the default provider {self.default.value!r} is not among the "
                f"mechanisms this run has ({listed or 'none'})"
            )
            raise InternalError(msg)
        unknown = sorted(
            {
                locator.provider.value
                for locator in self.locators.values()
                if locator.provider not in self.providers
            }
        )
        if unknown:
            msg = (
                f"{', '.join(unknown)} named by a locator but not among this run's "
                f"mechanisms; a reference that routes nowhere is refused here rather "
                f"than at the moment it is needed"
            )
            raise InternalError(msg)

    def _for(self, reference: SecretReference) -> SecretStore:
        """Which mechanism holds one reference.

        Args:
            reference: What is being addressed.

        Returns:
            The one store to ask. Never a sequence, and never a second attempt.
        """
        locator = self.locators.get(reference)
        kind = locator.provider if locator is not None else self.default
        return self.providers[kind]

    def health(self) -> StoreFault | None:
        """Report whether the default mechanism can be reached.

        Returns:
            The default provider's own answer.

        The *default* rather than an aggregate over all of them, because an
        aggregate would have to decide what "one of three is unreachable" means
        and every answer to that is misleading. A per-mechanism report is what
        ``globin secrets doctor`` is for.
        """
        return self.providers[self.default].health()

    def resolve(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> SecretResolution:
        """Look one reference up in its own mechanism.

        Args:
            reference: What to resolve.
            slot: Which copy of the material.

        Returns:
            That mechanism's resolution, whatever it is.
        """
        return self._for(reference).resolve(reference, slot)

    def store(
        self,
        reference: SecretReference,
        value: SecretValue,
        slot: SecretSlot = SecretSlot.CURRENT,
    ) -> StoreFault | None:
        """Write a value to the mechanism that holds this reference.

        Args:
            reference: What to store it under.
            value: The material.
            slot: Which copy to write.

        Returns:
            ``None`` on success, or that mechanism's fault. A read-only
            mechanism answers
            :attr:`~globin.domain.secrets.StoreFault.PROVIDER_READ_ONLY`, and
            nothing here converts that into an attempt somewhere else.
        """
        return self._for(reference).store(reference, value, slot)

    def delete(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> StoreFault | None:
        """Remove a reference from the mechanism that holds it.

        Args:
            reference: What to remove.
            slot: Which copy.

        Returns:
            ``None`` on success, or that mechanism's fault.
        """
        return self._for(reference).delete(reference, slot)

    def inventory(self) -> tuple[SecretReference, ...]:
        """List what every mechanism holds, by name only.

        Returns:
            The union across mechanisms, de-duplicated and sorted.

        Sorted and de-duplicated because a reference could in principle be
        declared to one mechanism and present in another's declared set, and a
        listing that reported it twice would read as two secrets.
        """
        found: set[SecretReference] = set()
        for provider in self.providers.values():
            found.update(provider.inventory())
        return tuple(sorted(found))
