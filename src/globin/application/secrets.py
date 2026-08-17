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

from dataclasses import dataclass

from globin.domain.bootstrap import SecretReadiness
from globin.domain.secrets import (
    SecretReference,
    SecretResolution,
    SecretSlot,
    SecretValue,
    StoreFault,
    store_key,
)
from globin.errors import ConfigurationError
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
