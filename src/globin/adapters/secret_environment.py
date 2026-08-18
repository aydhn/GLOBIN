"""A secret handed to this process, read from exactly one named variable.

**A hand-off, not a store**, and ``SECURITY_BASELINE.md`` §2 supplies both the
permission and its limit: environment variables are permitted "only as a hand-off,
never as storage. A process may receive a secret in its environment from the
store ... It must not be the place the secret rests between runs." So
:meth:`EnvironmentSecretProvider.store` and
:meth:`EnvironmentSecretProvider.delete` refuse. A provider that could write here
would make the environment the resting place that sentence forbids.

**It never scans.** There is no iteration over the mapping anywhere in this
module: every read is one lookup for a variable a locator named. That is a
property rather than a promise, and
``tests/unit/test_secret_environment.py`` proves it by handing in a mapping whose
iteration raises.

**This is not the environment configuration source.**
:class:`~globin.adapters.configuration.EnvironmentConfigurationSource` reads
``GLOBIN_`` variables and **refuses** any that look credential-shaped, because
``SECURITY_BASELINE.md`` says no secret arrives through configuration. That rule
is unchanged and this module does not weaken it: the variables read here are
named by a locator, carry no ``GLOBIN_`` prefix — :func:`variable_problems`
refuses one that does — and never enter a configuration layer, a fingerprint or a
provenance record.

**Which profiles may use it is decided above.** This adapter holds a boolean
rather than a policy, so it cannot re-decide; the set lives in
:mod:`globin.runtime.composition` because three of the four profile names are
venue vocabulary that ``tests/architecture/test_identifier_discipline.py`` refuses
as a live constant in the domain.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from globin.domain.secrets import (
    SecretLocator,
    SecretProviderKind,
    SecretReference,
    SecretResolution,
    SecretSlot,
    SecretValue,
    StoreFault,
)
from globin.errors import ValidationError


@dataclass(frozen=True, slots=True)
class EnvironmentSecretProvider:
    """Secrets this process was handed, one named variable at a time.

    Args:
        environment: The variables. **Handed in, never read from the process
            here**, which is the seam that lets a test substitute one — the same
            treatment :func:`~globin.adapters.runtime_state.resolve_root` gives
            the same mapping.
        locators: Which variable holds which reference.
        permitted: Whether this run's profile allows this mechanism at all.
            A decision, not a policy; see the module docstring.
    """

    environment: Mapping[str, str]
    locators: Mapping[SecretReference, SecretLocator]
    permitted: bool = False

    def health(self) -> StoreFault | None:
        """Report whether this mechanism may be used at all.

        Returns:
            ``None`` when permitted, and
            :attr:`~globin.domain.secrets.StoreFault.PROVIDER_NOT_PERMITTED`
            otherwise.

        Never :attr:`~globin.domain.secrets.StoreFault.BACKEND_UNAVAILABLE`: a
        process always has an environment, so the only thing that can be wrong
        here is GLOBIN's own policy. Reporting a platform fault for a policy
        decision would send an operator to repair something that is not broken.
        """
        if not self.permitted:
            return StoreFault.PROVIDER_NOT_PERMITTED
        return None

    def resolve(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> SecretResolution:
        """Read one reference's variable.

        Args:
            reference: What to resolve.
            slot: Which copy of the material.

        Returns:
            The resolution, carrying either the material or the fault.

        **The previous slot is always absent**, and that is the truth rather than
        a limitation: there is one variable per reference and no second one, so
        there is nowhere a previous value could be. Rotation against this
        provider therefore fails at its first step, before anything is written —
        which is the behaviour ``SECRET_STORE_CONTRACT.md`` §4 wants, arrived at
        by the mechanism having no second place rather than by a check.
        """
        if not self.permitted:
            return SecretResolution(reference=reference, fault=StoreFault.PROVIDER_NOT_PERMITTED)
        if slot is not SecretSlot.CURRENT:
            return SecretResolution(reference=reference, fault=StoreFault.ABSENT)
        locator = self.locators.get(reference)
        if locator is None or not locator.variable:
            return SecretResolution(reference=reference, fault=StoreFault.ABSENT)
        material = self.environment.get(locator.variable, "")
        if not material:
            return SecretResolution(reference=reference, fault=StoreFault.ABSENT)
        try:
            value = SecretValue(material)
        except ValidationError:
            return SecretResolution(reference=reference, fault=StoreFault.VALUE_TOO_LARGE)
        return SecretResolution(reference=reference, value=value)

    def store(
        self,
        reference: SecretReference,
        value: SecretValue,
        slot: SecretSlot = SecretSlot.CURRENT,
    ) -> StoreFault | None:
        """Refuse, without reading the material.

        Args:
            reference: What was asked for, and is not consulted.
            value: The material, which is **not** read.
            slot: Which copy, and is not consulted.

        Returns:
            :attr:`~globin.domain.secrets.StoreFault.PROVIDER_READ_ONLY`.

        That the value is never read is the point, the same point
        :meth:`~globin.adapters.secrets.UnavailableSecretStore.store` makes: a
        provider that handled the material would be one that had held it.
        """
        del reference, value, slot
        return StoreFault.PROVIDER_READ_ONLY

    def delete(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> StoreFault | None:
        """Refuse.

        Args:
            reference: What was asked for, and is not consulted.
            slot: Which copy, and is not consulted.

        Returns:
            :attr:`~globin.domain.secrets.StoreFault.PROVIDER_READ_ONLY`.

        GLOBIN did not put the variable there and cannot unset it in the parent
        that did. Reporting success would be claiming an effect this process
        cannot have.
        """
        del reference, slot
        return StoreFault.PROVIDER_READ_ONLY

    def inventory(self) -> tuple[SecretReference, ...]:
        """List the located references whose variable is present.

        Returns:
            Every reference a locator names and the environment supplies,
            sorted. Empty where this mechanism is not permitted.

        One lookup per locator, never an iteration over the environment. A scan
        would report variables GLOBIN was never told about, which is both a
        larger claim than it can support and a way to notice a secret it was not
        handed.
        """
        if not self.permitted:
            return ()
        found = [
            reference
            for reference, locator in self.locators.items()
            if locator.variable and self.environment.get(locator.variable, "")
        ]
        return tuple(sorted(found))


def environment_secret_provider(
    environment: Mapping[str, str],
    locators: tuple[SecretLocator, ...] = (),
    *,
    permitted: bool = False,
) -> EnvironmentSecretProvider:
    """Build the hand-off reader for this run.

    Args:
        environment: The variables to read when asked.
        locators: Which variable holds which reference. Entries naming another
            provider are ignored, so one declared set can be handed to every
            mechanism.
        permitted: Whether this run's profile allows this mechanism.

    Returns:
        The provider.

    Unlike the other two factories this one is not absent-safe, because there is
    no absence to be safe about: a process always has an environment. What it can
    be is *not permitted*, which is a policy state rather than a platform one and
    is carried as a boolean.
    """
    located = {
        locator.reference: locator
        for locator in locators
        if locator.provider is SecretProviderKind.ENVIRONMENT
    }
    return EnvironmentSecretProvider(environment=environment, locators=located, permitted=permitted)
