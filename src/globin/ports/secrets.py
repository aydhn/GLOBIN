"""The contract through which GLOBIN reaches a local secret store.

One protocol, because there is one store. The split by *source of truth* that
:mod:`globin.ports.bootstrap` describes does not apply here: every operation
below addresses the same operating-system facility, and separating them would
produce protocols that could not be implemented independently.

**The surface is defined by what is absent**, which is
``docs/security/SECRET_STORE_CONTRACT.md`` §5 observed rather than restated.
There is no method that returns material to a caller who did not name a
reference, no enumeration that yields values, and no health check that reports
what it found. :meth:`SecretStore.inventory` returns *references*, which are
ordinary data, and that is the whole of what listing means here.

**Nothing in this protocol raises for an expected outcome.** An absent secret,
an unreachable store and a logon session with no credential set are answers, not
failures, and each arrives as a :class:`~globin.domain.secrets.StoreFault` — the
form ADR-0045 requires of a platform capability and the form
:class:`~globin.domain.bootstrap.SecretReadiness` already consumes. Raising
would push the classification out to every call site, which is where it would be
got wrong. :mod:`globin.application.secrets` is where a fault becomes a refusal,
because that is where the caller's intent — *needed* versus *checked for* — is
known.
"""

from typing import Protocol

from globin.domain.secrets import (
    SecretReference,
    SecretResolution,
    SecretSlot,
    SecretValue,
    StoreFault,
)


class SecretStore(Protocol):
    """A local, operating-system-protected store of named secrets."""

    def health(self) -> StoreFault | None:
        """Report whether the store can be reached at all.

        Returns:
            ``None`` when the backend is usable, or the fault that prevents it —
            :attr:`~globin.domain.secrets.StoreFault.BACKEND_UNAVAILABLE` where
            the platform facility is absent, and
            :attr:`~globin.domain.secrets.StoreFault.NO_CREDENTIAL_SET` where
            this logon session has no credential set, which
            ``phase_020_sources.md`` S-09 records as a real and documented state
            rather than a malfunction.

        Reports nothing about *contents*. A health check that listed what it
        found would be an inventory with a misleading name.
        """
        ...

    def resolve(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> SecretResolution:
        """Look one reference up.

        Args:
            reference: What to resolve.
            slot: Which copy of the material. Only rotation names the other.

        Returns:
            The resolution, carrying either the material or the fault that
            explains its absence. Never both, and never neither.

        The environment comparison ``SECRET_STORE_CONTRACT.md`` §3 requires
        happens here or above it, never below: an implementation that resolved
        across environments would make the isolation advisory. The key carries
        the environment, so a mismatch cannot resolve — the comparison is a
        property of :func:`~globin.domain.secrets.store_key` rather than a check
        somebody has to remember to write.
        """
        ...

    def store(
        self,
        reference: SecretReference,
        value: SecretValue,
        slot: SecretSlot = SecretSlot.CURRENT,
    ) -> StoreFault | None:
        """Write a value, creating or replacing.

        Args:
            reference: What to store it under.
            value: The material.
            slot: Which copy to write.

        Returns:
            ``None`` on success, or the fault that prevented the write.

        Replacing is what the platform does — ``phase_020_sources.md`` S-10 —
        and this protocol does not pretend otherwise. A caller that must not
        lose the previous value calls :func:`~globin.application.secrets.rotate`
        instead, which constructs the guarantee the platform does not offer.
        """
        ...

    def delete(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> StoreFault | None:
        """Remove a reference from the store.

        Args:
            reference: What to remove.
            slot: Which copy to remove.

        Returns:
            ``None`` on success, or the fault that prevented it —
            :attr:`~globin.domain.secrets.StoreFault.ABSENT` when there was
            nothing to remove, which a caller may legitimately ignore.
        """
        ...

    def inventory(self) -> tuple[SecretReference, ...]:
        """List what this store holds, by name only.

        Returns:
            Every reference GLOBIN owns in this store, sorted. No values, and no
            material of any kind.

        Sorted because every manifest in this repository renders a sorted list,
        and because an order that depended on enumeration would make two runs
        disagree about a document that is supposed to be deterministic.
        """
        ...
