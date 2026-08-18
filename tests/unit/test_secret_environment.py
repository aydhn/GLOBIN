"""The environment hand-off provider, and the router that reaches one mechanism.

Two subjects in one file because they are two halves of the same question: which
mechanism holds a reference, and what that mechanism will and will not do.

**The refusals are the deliverable, not the reads.** A hand-off that could be
written to would make the environment "the place the secret rests between runs",
which `SECURITY_BASELINE.md` section 2 forbids; a router with a fallback would
serve a value from a weaker mechanism than the operator believed, which
`SECRET_STORE_CONTRACT.md` section 3 forbids by name. Both are asserted as
counted calls rather than as returned faults, because a fault can be right for
the wrong reason and a call count cannot.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

import pytest

from globin.adapters.secret_environment import (
    EnvironmentSecretProvider,
    environment_secret_provider,
)
from globin.application.secrets import ProviderRoutedStore
from globin.domain.identifiers import environment_id
from globin.domain.secrets import (
    MAX_MATERIAL_BYTES,
    MAX_SECRET_BYTES,
    SecretKind,
    SecretLocator,
    SecretProviderKind,
    SecretReference,
    SecretResolution,
    SecretSlot,
    SecretValue,
    StoreFault,
)
from globin.errors import InternalError

MATERIAL = "not-a-real-api-key-0000"
VARIABLE = "GLOBIN_VENUE_HANDOFF"

REFERENCE = SecretReference(
    environment=environment_id("paper"),
    kind=SecretKind.API_KEY,
    name="venue_key",
)

VAULTED = SecretReference(
    environment=environment_id("paper"),
    kind=SecretKind.PRIVATE_KEY,
    name="venue_signing_key",
)

HANDOFF = SecretLocator(
    provider=SecretProviderKind.ENVIRONMENT,
    reference=REFERENCE,
    variable="VENUE_HANDOFF_KEY",
)


class _RefusingMapping(Mapping[str, str]):
    """A mapping that answers a lookup and refuses to be walked.

    The point of the file, in a class: `EnvironmentSecretProvider` claims it
    never scans, and a comment saying so is not evidence. Handing it something
    that raises on iteration turns the claim into something the suite checks.
    """

    def __init__(self, values: dict[str, str]) -> None:
        """Bind the values.

        Args:
            values: What a lookup may find.
        """
        self._values = values

    def __getitem__(self, key: str) -> str:
        """Look one variable up.

        Args:
            key: Which variable.

        Returns:
            Its value.
        """
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        """Refuse to be walked.

        Raises:
            AssertionError: Always. Nothing may enumerate the environment.
        """
        message = "the environment provider must never iterate its mapping"
        raise AssertionError(message)

    def __len__(self) -> int:
        """Refuse to be sized.

        Raises:
            AssertionError: Always.
        """
        message = "the environment provider must never size its mapping"
        raise AssertionError(message)


@dataclass
class _CountingStore:
    """A store that records every call it receives."""

    resolution: SecretResolution | None = None
    fault: StoreFault | None = None
    calls: list[str] = field(default_factory=list)
    held: tuple[SecretReference, ...] = ()

    def health(self) -> StoreFault | None:
        """Record and answer."""
        self.calls.append("health")
        return self.fault

    def resolve(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> SecretResolution:
        """Record and answer.

        Args:
            reference: What was asked for.
            slot: Which copy.
        """
        del slot
        self.calls.append("resolve")
        if self.resolution is not None:
            return self.resolution
        return SecretResolution(reference=reference, fault=StoreFault.ABSENT)

    def store(
        self,
        reference: SecretReference,
        value: SecretValue,
        slot: SecretSlot = SecretSlot.CURRENT,
    ) -> StoreFault | None:
        """Record and answer.

        Args:
            reference: What was asked for.
            value: The material, which is not read.
            slot: Which copy.
        """
        del reference, value, slot
        self.calls.append("store")
        return self.fault

    def delete(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> StoreFault | None:
        """Record and answer.

        Args:
            reference: What was asked for.
            slot: Which copy.
        """
        del reference, slot
        self.calls.append("delete")
        return self.fault

    def inventory(self) -> tuple[SecretReference, ...]:
        """Record and answer."""
        self.calls.append("inventory")
        return self.held


def provider(**values: str) -> EnvironmentSecretProvider:
    """A permitted provider over a refusing mapping.

    Args:
        values: The variables it may find.

    Returns:
        The provider.
    """
    return EnvironmentSecretProvider(
        environment=_RefusingMapping(dict(values)),
        locators={REFERENCE: HANDOFF},
        permitted=True,
    )


# ---------------------------------------------------------------------------
# The hand-off: what it reads
# ---------------------------------------------------------------------------


def test_a_named_variable_resolves() -> None:
    """The happy path, so the refusals below are not vacuously true."""
    resolution = provider(VENUE_HANDOFF_KEY=MATERIAL).resolve(REFERENCE)
    assert resolution.value is not None
    assert resolution.value.material() == MATERIAL


def test_the_provider_never_iterates_its_mapping() -> None:
    """A scan would notice secrets GLOBIN was never handed.

    Every method is exercised against a mapping that raises on iteration, so the
    property is structural rather than asserted in prose.
    """
    reader = provider(VENUE_HANDOFF_KEY=MATERIAL)
    assert reader.health() is None
    assert reader.resolve(REFERENCE).resolved
    assert reader.inventory() == (REFERENCE,)
    assert reader.store(REFERENCE, SecretValue(MATERIAL)) is StoreFault.PROVIDER_READ_ONLY
    assert reader.delete(REFERENCE) is StoreFault.PROVIDER_READ_ONLY


def test_an_unset_variable_is_absent() -> None:
    """Nothing handed in is absence, not a malfunction."""
    assert provider().resolve(REFERENCE).fault is StoreFault.ABSENT


def test_an_empty_variable_is_absent_rather_than_an_empty_secret() -> None:
    """A blank hand-off is nothing, and must not become a value."""
    assert provider(VENUE_HANDOFF_KEY="").resolve(REFERENCE).fault is StoreFault.ABSENT


def test_a_reference_with_no_locator_is_absent() -> None:
    """This mechanism reads only what it was told to read."""
    assert provider(VENUE_HANDOFF_KEY=MATERIAL).resolve(VAULTED).fault is StoreFault.ABSENT


def test_the_previous_slot_is_always_absent() -> None:
    """There is one variable per reference and no second one.

    Rotation therefore fails at its first step, before anything is written —
    arrived at by the mechanism having no second place rather than by a check.
    """
    reader = provider(VENUE_HANDOFF_KEY=MATERIAL)
    assert reader.resolve(REFERENCE, SecretSlot.PREVIOUS).fault is StoreFault.ABSENT


def test_material_the_value_type_refuses_is_reported_rather_than_raised() -> None:
    """Nothing in the port raises for an expected outcome.

    The bound is the *type's* since Phase 031, not the credential store's. A
    hand-off can carry material larger than the store's ceiling — an operator may
    hand a process a key that belongs in the vault — so the store's number would
    be the wrong refusal here.
    """
    oversized = provider(VENUE_HANDOFF_KEY="x" * (MAX_MATERIAL_BYTES + 1))
    assert oversized.resolve(REFERENCE).fault is StoreFault.VALUE_TOO_LARGE


def test_a_hand_off_may_carry_more_than_the_credential_store_would_accept() -> None:
    """The mechanisms have different ceilings, and this one is not the store's.

    Refusing at 2560 bytes here would make an environment hand-off unable to
    deliver exactly the material the vault exists to hold.
    """
    large = provider(VENUE_HANDOFF_KEY="x" * (MAX_SECRET_BYTES + 1))
    resolution = large.resolve(REFERENCE)
    assert resolution.resolved


# ---------------------------------------------------------------------------
# The hand-off: what it refuses
# ---------------------------------------------------------------------------


def test_a_forbidden_profile_refuses_before_anything_is_read() -> None:
    """A policy state, not a platform one.

    Never `BACKEND_UNAVAILABLE`: a process always has an environment, so
    reporting a platform fault would send an operator to repair something that is
    not broken.
    """
    refused = EnvironmentSecretProvider(
        environment=_RefusingMapping({"VENUE_HANDOFF_KEY": MATERIAL}),
        locators={REFERENCE: HANDOFF},
        permitted=False,
    )
    assert refused.health() is StoreFault.PROVIDER_NOT_PERMITTED
    assert refused.resolve(REFERENCE).fault is StoreFault.PROVIDER_NOT_PERMITTED
    assert refused.inventory() == ()


def test_a_write_is_refused_without_the_material_being_read() -> None:
    """A provider that handled the material would be one that had held it."""
    assert provider().store(REFERENCE, SecretValue(MATERIAL)) is StoreFault.PROVIDER_READ_ONLY


def test_the_factory_keeps_only_the_locators_that_name_it() -> None:
    """One declared set can be handed to every mechanism."""
    elsewhere = SecretLocator(
        provider=SecretProviderKind.DPAPI_VAULT,
        reference=VAULTED,
    )
    built = environment_secret_provider(
        {"VENUE_HANDOFF_KEY": MATERIAL}, (HANDOFF, elsewhere), permitted=True
    )
    assert built.inventory() == (REFERENCE,)


def test_the_factory_is_not_permitted_by_default() -> None:
    """The gate is opt-in, which is the direction an allow-list takes."""
    assert environment_secret_provider({}, (HANDOFF,)).health() is (
        StoreFault.PROVIDER_NOT_PERMITTED
    )


# ---------------------------------------------------------------------------
# The router: exactly one mechanism, and no chain
# ---------------------------------------------------------------------------


def routed(
    **kwargs: object,
) -> tuple[ProviderRoutedStore, _CountingStore, _CountingStore]:
    """A router over two counting stores.

    Args:
        kwargs: Overrides for the routing table.

    Returns:
        The router, the Credential Manager double and the vault double.

    The two doubles are returned rather than reached for through
    `ProviderRoutedStore.providers`, which is typed as the port: a test that
    reached through the mapping would be asserting against something the type
    says it cannot see, and would stop type-checking the moment the port grew.
    """
    manager = _CountingStore()
    vault = _CountingStore()
    defaults: dict[str, object] = {
        "providers": {
            SecretProviderKind.CREDENTIAL_MANAGER: manager,
            SecretProviderKind.DPAPI_VAULT: vault,
        },
        "locators": {},
        "default": SecretProviderKind.CREDENTIAL_MANAGER,
    }
    defaults.update(kwargs)
    return ProviderRoutedStore(**defaults), manager, vault  # type: ignore[arg-type]


def test_an_absent_secret_is_never_looked_for_a_second_time() -> None:
    """The absence of a fallback, asserted as a call count.

    A fault can be right for the wrong reason; a count of zero calls to the other
    mechanism cannot. `SECRET_STORE_CONTRACT.md` section 3 forbids "a quiet fall
    back to somewhere less protected", and this is what proves there is none.
    """
    store, manager, vault = routed()
    assert store.resolve(REFERENCE).fault is StoreFault.ABSENT
    assert manager.calls == ["resolve"]
    assert vault.calls == []


def test_a_locator_sends_a_reference_to_its_own_mechanism() -> None:
    """Routing is by declaration, never by trying one and then the other."""
    locator = SecretLocator(provider=SecretProviderKind.DPAPI_VAULT, reference=VAULTED)
    store, manager, vault = routed(locators={VAULTED: locator})
    store.resolve(VAULTED)
    assert vault.calls == ["resolve"]
    assert manager.calls == []


def test_a_reference_with_no_locator_uses_the_default() -> None:
    """Reached only when nobody named a provider, which is not a fallback."""
    store, manager, _ = routed()
    store.store(REFERENCE, SecretValue(MATERIAL))
    assert manager.calls == ["store"]


def test_a_write_is_never_retried_elsewhere() -> None:
    """A refused write stays refused."""
    store, manager, vault = routed()
    manager.fault = StoreFault.BACKEND_REFUSED
    assert store.store(REFERENCE, SecretValue(MATERIAL)) is StoreFault.BACKEND_REFUSED
    assert vault.calls == []


def test_a_delete_reaches_one_mechanism() -> None:
    """Deleting from the wrong mechanism would leave the value in place."""
    store, manager, vault = routed()
    store.delete(REFERENCE)
    assert manager.calls == ["delete"]
    assert vault.calls == []


def test_health_reports_the_default_mechanism() -> None:
    """An aggregate would have to decide what "one of three is down" means."""
    store, manager, _ = routed()
    manager.fault = StoreFault.NO_CREDENTIAL_SET
    assert store.health() is StoreFault.NO_CREDENTIAL_SET


def test_the_inventory_is_the_union_deduplicated_and_sorted() -> None:
    """A reference in two declared sets is one secret, not two."""
    store, manager, vault = routed()
    manager.held = (VAULTED, REFERENCE)
    vault.held = (VAULTED,)
    assert store.inventory() == tuple(sorted({REFERENCE, VAULTED}))


def test_a_default_that_is_not_present_is_refused_at_construction() -> None:
    """There is no run in which a reference routes to nothing."""
    with pytest.raises(InternalError, match="is not among the mechanisms"):
        routed(default=SecretProviderKind.ENVIRONMENT)


def test_a_locator_naming_an_absent_mechanism_is_refused_at_construction() -> None:
    """Refused here rather than at the moment the secret is needed.

    A misspelled provider is a different situation from nobody naming one, and
    defaulting it would erase the distinction.
    """
    locator = SecretLocator(
        provider=SecretProviderKind.ENVIRONMENT, reference=REFERENCE, variable="X"
    )
    with pytest.raises(InternalError, match="named by a locator"):
        routed(locators={REFERENCE: locator})
