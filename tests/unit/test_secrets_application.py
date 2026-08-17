"""Requiring, resolving, rotating: where a fault becomes a refusal or a report.

The store here is an in-memory double satisfying the `SecretStore` protocol,
which `docs/TESTING_STRATEGY.md` makes the default. It can be made to fail on a
chosen operation, which is how the rotation guarantee is exercised — the whole
value of the ordering is what happens when a step fails, and that never happens
by itself.
"""

from dataclasses import dataclass, field

import pytest

from globin.application.secrets import (
    REMEDIATION,
    inventory_keys,
    readiness,
    require,
    resolve,
    rotate,
)
from globin.domain.identifiers import environment_id
from globin.domain.secrets import (
    SecretKind,
    SecretReference,
    SecretResolution,
    SecretSlot,
    SecretValue,
    StoreFault,
    store_key,
)
from globin.errors import ConfigurationError

OLD = "old-value-not-a-secret"
NEW = "new-value-not-a-secret"

REFERENCE = SecretReference(
    environment=environment_id("paper"),
    kind=SecretKind.API_KEY,
    name="venue_key",
)


@dataclass
class _Store:
    """An in-memory secret store that can be made to fail on demand.

    Args:
        held: What it currently holds, keyed exactly as the real store keys it.
        fail_writes_to: A slot whose writes always fail, or ``None``.
        corrupt_verification: Whether a read of the current slot returns
            something other than what was written, which is the one failure a
            rotation cannot detect any other way.

    The corruption applies **only after the current slot has been written**, so
    that it models the failure it is named for. Corrupting every read would also
    corrupt rotation's step 0 — the copy of the *existing* value to the previous
    slot — which is a different fault entirely and would make the test assert
    something other than what it claims.
    """

    held: dict[str, str] = field(default_factory=dict)
    fail_writes_to: SecretSlot | None = None
    corrupt_verification: bool = False
    deleted: list[str] = field(default_factory=list)
    _current_written: bool = False

    def health(self) -> StoreFault | None:
        return None

    def resolve(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> SecretResolution:
        key = store_key(reference, slot)
        if key not in self.held:
            return SecretResolution(reference=reference, fault=StoreFault.ABSENT)
        material = self.held[key]
        if self.corrupt_verification and slot is SecretSlot.CURRENT and self._current_written:
            material = "something-else-entirely"
        return SecretResolution(reference=reference, value=SecretValue(material))

    def store(
        self,
        reference: SecretReference,
        value: SecretValue,
        slot: SecretSlot = SecretSlot.CURRENT,
    ) -> StoreFault | None:
        if self.fail_writes_to is slot:
            return StoreFault.BACKEND_REFUSED
        self.held[store_key(reference, slot)] = value.material()
        if slot is SecretSlot.CURRENT:
            self._current_written = True
        return None

    def delete(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> StoreFault | None:
        key = store_key(reference, slot)
        self.deleted.append(key)
        if key not in self.held:
            return StoreFault.ABSENT
        del self.held[key]
        return None

    def inventory(self) -> tuple[SecretReference, ...]:
        return ()


def loaded(**kwargs: object) -> _Store:
    """A store already holding the reference's current value."""
    store = _Store(**kwargs)  # type: ignore[arg-type]
    store.held[store_key(REFERENCE, SecretSlot.CURRENT)] = OLD
    return store


# ---------------------------------------------------------------------------
# Requiring
# ---------------------------------------------------------------------------


def test_requiring_a_present_secret_returns_it() -> None:
    """The ordinary path."""
    assert require(loaded(), REFERENCE) == SecretValue(OLD)


def test_requiring_an_absent_secret_refuses_with_the_fault_named() -> None:
    """Section 3: an explicit error, never a silent absence."""
    with pytest.raises(ConfigurationError, match=StoreFault.ABSENT.value):
        require(_Store(), REFERENCE)


def test_a_refusal_names_the_reference_and_carries_no_material() -> None:
    """Section 3 permits the logical name, the fault and the remediation. Nothing else."""
    store = _Store()
    with pytest.raises(ConfigurationError) as caught:
        require(store, REFERENCE)
    message = str(caught.value)
    assert "venue_key" in message
    assert "paper" in message
    assert OLD not in message
    assert NEW not in message


def test_a_refusal_carries_no_length_either() -> None:
    """A length is a fact about the material, and section 4 forbids any part of it."""
    store = _Store()
    store.held[store_key(REFERENCE)] = OLD
    with pytest.raises(ConfigurationError) as caught:
        require(
            store,
            SecretReference(
                environment=environment_id("testnet"),
                kind=SecretKind.API_KEY,
                name="venue_key",
            ),
        )
    assert str(len(OLD)) not in str(caught.value)


def test_every_fault_has_a_remediation() -> None:
    """A failure a reader cannot act on is a failure reported twice."""
    assert set(REMEDIATION) == set(StoreFault)


def test_no_remediation_phrase_could_carry_material() -> None:
    """They are fixed strings with no interpolation, which is what makes that true."""
    for fault, phrase in REMEDIATION.items():
        assert phrase == REMEDIATION[fault]
        assert "{" not in phrase, f"{fault} could interpolate"
        assert "%" not in phrase, f"{fault} could interpolate"


def test_resolving_reports_rather_than_refuses() -> None:
    """The non-raising half, for a caller whose absence is an acceptable answer."""
    result = resolve(_Store(), REFERENCE)
    assert not result.resolved
    assert result.fault is StoreFault.ABSENT


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def test_an_empty_requirement_is_vacuously_ready() -> None:
    """GLOBIN holds no credentials, so the required set is genuinely nothing."""
    result = readiness(_Store(), ())
    assert result.required == ()
    assert result.unavailable == ()


def test_a_present_requirement_is_ready() -> None:
    """The control."""
    assert readiness(loaded(), (REFERENCE,)).unavailable == ()


def test_an_absent_requirement_is_named_but_not_raised() -> None:
    """A start-up check must receive this without unwinding."""
    result = readiness(_Store(), (REFERENCE,))
    assert result.required == ("venue_key",)
    assert result.unavailable == ("venue_key",)


def test_readiness_carries_names_and_never_values() -> None:
    """`SecretReadiness` holds identifiers only, and this is where that is enforced."""
    result = readiness(loaded(), (REFERENCE,))
    assert OLD not in repr(result)


# ---------------------------------------------------------------------------
# Rotation, and the guarantee that survives a failure
# ---------------------------------------------------------------------------


def test_a_successful_rotation_leaves_the_new_value_current() -> None:
    """The ordinary path."""
    store = loaded()
    outcome = rotate(store, REFERENCE, SecretValue(NEW))
    assert outcome.rotated
    assert store.held[store_key(REFERENCE, SecretSlot.CURRENT)] == NEW


def test_a_successful_rotation_retires_the_previous_copy() -> None:
    """Step 3, and only after the read-back verified."""
    store = loaded()
    rotate(store, REFERENCE, SecretValue(NEW))
    assert store_key(REFERENCE, SecretSlot.PREVIOUS) not in store.held


def test_the_previous_value_is_copied_before_the_new_one_is_written() -> None:
    """The step the platform forces, and the reason `SecretSlot` exists.

    A Windows credential write *replaces*, so by the time the new value is
    written the old one is gone. Without the copy there would be nothing for
    section 4's "only then retire the previous one" to retire.
    """
    store = loaded(fail_writes_to=SecretSlot.CURRENT)
    rotate(store, REFERENCE, SecretValue(NEW))
    assert store.held[store_key(REFERENCE, SecretSlot.PREVIOUS)] == OLD


def test_a_failure_writing_the_new_value_leaves_the_previous_recoverable() -> None:
    """Section 4's whole guarantee, at the step most likely to fail."""
    outcome = rotate(loaded(fail_writes_to=SecretSlot.CURRENT), REFERENCE, SecretValue(NEW))
    assert not outcome.rotated
    assert outcome.fault is StoreFault.BACKEND_REFUSED
    assert outcome.previous_recoverable


def test_a_failure_copying_the_previous_value_changes_nothing() -> None:
    """Failing at step 0 must not have touched the current slot."""
    store = loaded(fail_writes_to=SecretSlot.PREVIOUS)
    outcome = rotate(store, REFERENCE, SecretValue(NEW))
    assert not outcome.rotated
    assert store.held[store_key(REFERENCE, SecretSlot.CURRENT)] == OLD


def test_a_read_back_that_disagrees_fails_the_rotation() -> None:
    """The verification step, and the only thing it can catch.

    The platform offers no compare-and-swap, so a write that reported success and
    stored something else is undetectable any other way.
    """
    outcome = rotate(loaded(corrupt_verification=True), REFERENCE, SecretValue(NEW))
    assert not outcome.rotated
    assert outcome.fault is StoreFault.VERIFICATION_FAILED
    assert outcome.previous_recoverable


def test_a_failed_verification_does_not_retire_the_previous_copy() -> None:
    """Otherwise the guarantee would be void exactly when it is needed."""
    store = loaded(corrupt_verification=True)
    rotate(store, REFERENCE, SecretValue(NEW))
    assert store.held[store_key(REFERENCE, SecretSlot.PREVIOUS)] == OLD


def test_rotating_a_reference_that_holds_nothing_is_not_an_error() -> None:
    """It degenerates to a write and a verification, which is the honest behaviour."""
    store = _Store()
    outcome = rotate(store, REFERENCE, SecretValue(NEW))
    assert outcome.rotated
    assert store.held[store_key(REFERENCE, SecretSlot.CURRENT)] == NEW


def test_rotating_something_absent_deletes_no_previous_copy() -> None:
    """There was none, so a delete would be asking the store about nothing."""
    store = _Store()
    rotate(store, REFERENCE, SecretValue(NEW))
    assert store.deleted == []


def test_a_failed_rotation_of_an_absent_reference_reports_nothing_recoverable() -> None:
    """Honest rather than reassuring: there was no previous material to fall back on."""
    outcome = rotate(_Store(fail_writes_to=SecretSlot.CURRENT), REFERENCE, SecretValue(NEW))
    assert not outcome.rotated
    assert not outcome.previous_recoverable


def test_a_rotation_record_carries_no_material() -> None:
    """Section 4: not the old value, not the new one, and no part of either."""
    record = rotate(loaded(), REFERENCE, SecretValue(NEW)).as_record()
    assert OLD not in str(record)
    assert NEW not in str(record)
    assert record["rotated"] is True


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


def test_inventory_keys_route_through_the_one_builder() -> None:
    """Section 2 permits exactly one, so a caller never composes a key itself."""
    assert inventory_keys((REFERENCE,)) == (store_key(REFERENCE),)


def test_inventory_keys_are_sorted() -> None:
    """Deterministic rendering, like every other list this repository publishes."""
    other = SecretReference(
        environment=environment_id("paper"), kind=SecretKind.API_KEY, name="another"
    )
    assert inventory_keys((REFERENCE, other)) == tuple(sorted(inventory_keys((REFERENCE, other))))
