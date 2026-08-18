"""What a credential may do, and what GLOBIN refuses to claim about it.

Every credential here is a reference and a set of bounded enum members. Nothing
in this file holds material, and nothing needs a store: an entitlement is decided
from what a use site demands and what an operator declared, both of which are
ordinary data.

The two assertions that carry the most weight are both about *not* permitting: a
withheld grant proved unreachable by any declaration, and a verification state
proved to have no member meaning "confirmed" -- so no future caller can write a
branch that treats an unverified declaration as a verified one.
"""

from collections.abc import Mapping

import pytest

from globin.adapters.entitlements import (
    REGISTER_NAME,
    SCHEMA,
    SCHEMA_VERSION,
    StateGrantRegister,
)
from globin.application.secrets import (
    ENTRY_REMEDIATION,
    VERDICT_REMEDIATION,
    entitlement,
    require_permitted,
    set_from_entry,
)
from globin.domain.entitlements import (
    CredentialRequirement,
    Grant,
    GrantDeclaration,
    GrantSet,
    PermissionVerdict,
    VerificationState,
    declaration_for,
    required_credentials,
    required_references,
    verify,
    withheld_grants,
)
from globin.domain.identifiers import EnvironmentId
from globin.domain.observability import REDACTED
from globin.domain.runtime_state import RuntimeArea, RuntimePersistenceError
from globin.domain.secrets import (
    EntryFault,
    SecretEntryOutcome,
    SecretKind,
    SecretReference,
    SecretResolution,
    SecretValue,
    StoreFault,
)
from globin.errors import ConfigurationError, ValidationError

PAPER = EnvironmentId("paper")
KEY = SecretReference(environment=PAPER, kind=SecretKind.API_KEY, name="venue_key")
OTHER = SecretReference(environment=PAPER, kind=SecretKind.API_KEY, name="other_key")


def demand(*grants: Grant, purpose: str = "read balances") -> CredentialRequirement:
    return CredentialRequirement(reference=KEY, demanded=GrantSet(grants), purpose=purpose)


def declare(*grants: Grant) -> GrantDeclaration:
    return GrantDeclaration(reference=KEY, declared=GrantSet(grants))


# ---------------------------------------------------------------------------
# The state vocabulary
# ---------------------------------------------------------------------------


def test_there_is_no_state_meaning_the_issuer_confirmed_anything() -> None:
    """The absence is the design, and this is what holds it in place.

    GLOBIN reaches no venue, so a member meaning "the issuer agrees" would be a
    lie with a name. ADR-0045 says a capability is a recorded state and never a
    pass; here the rule is enforced by there being nothing to write.
    """
    assert {state.value for state in VerificationState} == {
        "declared",
        "undeclared",
        "insufficient",
        "withheld",
    }


@pytest.mark.parametrize(
    "forbidden",
    [
        pytest.param("confirm", id="confirm"),
        pytest.param("verified", id="verified"),
        pytest.param("valid", id="valid"),
    ],
)
def test_no_state_name_suggests_something_was_checked(forbidden: str) -> None:
    assert not any(forbidden in state.value for state in VerificationState)


def test_exactly_one_state_permits_use() -> None:
    permitting = [
        state
        for state in VerificationState
        if PermissionVerdict(reference=KEY, state=state).permitted
    ]
    assert permitting == [VerificationState.DECLARED]


# ---------------------------------------------------------------------------
# The withheld refusal
# ---------------------------------------------------------------------------


def test_moving_funds_is_withheld() -> None:
    """SECURITY_BASELINE.md section 4, turned into a branch."""
    assert withheld_grants() == (Grant.TRANSFER,)


@pytest.mark.parametrize(
    "declared",
    [
        pytest.param((), id="nothing-declared"),
        pytest.param((Grant.READ,), id="read-declared"),
        pytest.param((Grant.TRANSFER,), id="transfer-declared"),
        pytest.param((Grant.READ, Grant.SUBMIT, Grant.TRANSFER), id="everything"),
    ],
)
def test_a_withheld_grant_cannot_be_bought_back_by_any_declaration(
    declared: tuple[Grant, ...],
) -> None:
    """The point of checking it first, before the declaration is consulted."""
    verdict = verify(demand(Grant.TRANSFER), declare(*declared))
    assert verdict.state is VerificationState.WITHHELD
    assert verdict.permitted is False


def test_a_withheld_grant_refuses_even_alongside_permitted_ones() -> None:
    verdict = verify(demand(Grant.READ, Grant.TRANSFER), declare(Grant.READ, Grant.TRANSFER))
    assert verdict.state is VerificationState.WITHHELD


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------


def test_a_demand_the_declaration_covers_is_permitted() -> None:
    verdict = verify(demand(Grant.READ), declare(Grant.READ, Grant.SUBMIT))
    assert verdict.state is VerificationState.DECLARED
    assert verdict.permitted is True


def test_a_declaration_carrying_more_than_is_needed_reports_the_excess() -> None:
    """A least-privilege observation, not a refusal."""
    verdict = verify(demand(Grant.READ), declare(Grant.READ, Grant.SUBMIT))
    assert verdict.excess == (Grant.SUBMIT,)
    assert verdict.permitted is True


def test_a_demand_the_declaration_does_not_cover_names_the_shortfall() -> None:
    verdict = verify(demand(Grant.READ, Grant.SUBMIT), declare(Grant.READ))
    assert verdict.state is VerificationState.INSUFFICIENT
    assert verdict.missing == (Grant.SUBMIT,)


def test_no_declaration_at_all_permits_nothing() -> None:
    verdict = verify(demand(Grant.READ), None)
    assert verdict.state is VerificationState.UNDECLARED
    assert verdict.missing == (Grant.READ,)


def test_a_demand_for_nothing_is_permitted_by_a_declaration_of_nothing() -> None:
    """Vacuous, and vacuously true rather than an error."""
    assert verify(demand(), declare()).state is VerificationState.DECLARED


# ---------------------------------------------------------------------------
# The grant set
# ---------------------------------------------------------------------------


def test_a_grant_set_is_canonical_whatever_order_it_was_built_in() -> None:
    assert GrantSet((Grant.SUBMIT, Grant.READ)) == GrantSet((Grant.READ, Grant.SUBMIT))


def test_duplicates_collapse() -> None:
    assert GrantSet((Grant.READ, Grant.READ)).grants == (Grant.READ,)


def test_covering_is_subset() -> None:
    everything = GrantSet((Grant.READ, Grant.SUBMIT))
    assert everything.covers(GrantSet((Grant.READ,))) is True
    assert everything.covers(everything) is True
    assert GrantSet((Grant.READ,)).covers(everything) is False


def test_a_requirement_must_say_what_it_is_for() -> None:
    """A refusal nobody can act on is worse than no refusal."""
    with pytest.raises(ValidationError):
        CredentialRequirement(reference=KEY, demanded=GrantSet(), purpose="  ")


def test_a_declaration_for_another_reference_is_not_found() -> None:
    declarations = (GrantDeclaration(reference=OTHER, declared=GrantSet((Grant.READ,))),)
    assert declaration_for(KEY, declarations) is None
    assert declaration_for(OTHER, declarations) is not None


# ---------------------------------------------------------------------------
# What start-up requires
# ---------------------------------------------------------------------------


def test_nothing_is_required_to_start_and_the_emptiness_is_owned() -> None:
    """Empty by derivation rather than by omission.

    GLOBIN reaches no venue, so no credential is genuinely needed at start-up.
    Phase 038 brings the first authenticated surface; adding one entry to the
    registry is all it takes for `bootstrap check` to begin demanding one, which
    is what this phase delivered instead of a non-empty tuple.
    """
    assert required_credentials() == ()
    assert required_references() == ()


# ---------------------------------------------------------------------------
# Remediation totality
# ---------------------------------------------------------------------------


def test_every_verification_state_tells_an_operator_what_to_do() -> None:
    assert set(VERDICT_REMEDIATION) == set(VerificationState)
    assert all(text.strip() for text in VERDICT_REMEDIATION.values())


def test_every_entry_fault_tells_an_operator_what_to_do() -> None:
    assert set(ENTRY_REMEDIATION) == set(EntryFault)
    assert all(text.strip() for text in ENTRY_REMEDIATION.values())


# ---------------------------------------------------------------------------
# The application layer
# ---------------------------------------------------------------------------


class _CountingStore:
    """A store that records how often it was asked to resolve anything."""

    def __init__(self, material: str = "material") -> None:
        self.resolved: list[SecretReference] = []
        self.stored: list[SecretReference] = []
        self.material = material

    def health(self) -> StoreFault | None:
        return None

    def resolve(self, reference: SecretReference, slot: object = None) -> SecretResolution:
        del slot
        self.resolved.append(reference)
        return SecretResolution(reference=reference, value=SecretValue(self.material))

    def store(
        self, reference: SecretReference, value: SecretValue, slot: object = None
    ) -> StoreFault | None:
        del value, slot
        self.stored.append(reference)
        return None

    def delete(self, reference: SecretReference, slot: object = None) -> StoreFault | None:
        del reference, slot
        return None

    def inventory(self) -> tuple[SecretReference, ...]:
        return ()


class _FixedEntry:
    """An entry that always produces the same outcome."""

    def __init__(self, outcome: SecretEntryOutcome) -> None:
        self.outcome = outcome
        self.prompts: list[str] = []

    def collect(self, prompt: str) -> SecretEntryOutcome:
        self.prompts.append(prompt)
        return self.outcome


def test_a_refused_verdict_never_reaches_the_store() -> None:
    """The roadmap's "before use", asserted as an absence of calls.

    There is no branch in which material is resolved and then discarded, and the
    observable form of that claim is that the store recorded zero calls.
    """
    store = _CountingStore()
    with pytest.raises(ConfigurationError):
        require_permitted(store, demand(Grant.SUBMIT), declare(Grant.READ))
    assert store.resolved == []


def test_a_withheld_demand_never_reaches_the_store_either() -> None:
    store = _CountingStore()
    with pytest.raises(ConfigurationError):
        require_permitted(store, demand(Grant.TRANSFER), declare(Grant.TRANSFER))
    assert store.resolved == []


def test_a_permitted_verdict_resolves_exactly_once() -> None:
    store = _CountingStore()
    value = require_permitted(store, demand(Grant.READ), declare(Grant.READ))
    assert store.resolved == [KEY]
    assert repr(value) == REDACTED


def test_a_refusal_message_carries_no_material() -> None:
    store = _CountingStore(material="GLOBIN-PHASE029-SYNTHETIC-CANARY")
    with pytest.raises(ConfigurationError) as caught:
        require_permitted(store, demand(Grant.SUBMIT), declare(Grant.READ))
    rendered = f"{caught.value}{caught.value.args!r}"
    assert "CANARY" not in rendered
    assert "submit" in rendered


def test_collection_that_failed_stores_nothing_and_names_the_fault() -> None:
    store = _CountingStore()
    entry = _FixedEntry(SecretEntryOutcome(fault=EntryFault.NOT_INTERACTIVE))
    outcome = set_from_entry(entry, store, KEY, prompt="key: ")
    assert outcome.stored is False
    assert outcome.entry_fault is EntryFault.NOT_INTERACTIVE
    assert store.stored == []


def test_a_collected_value_reaches_the_store_and_not_the_record() -> None:
    store = _CountingStore()
    entry = _FixedEntry(SecretEntryOutcome(value=SecretValue("GLOBIN-CANARY-029")))
    outcome = set_from_entry(entry, store, KEY, prompt="key: ")
    assert outcome.stored is True
    assert store.stored == [KEY]
    assert "CANARY" not in repr(outcome.as_record())


def test_verifying_a_set_of_requirements_answers_one_verdict_each() -> None:
    verdicts = entitlement(
        (demand(Grant.READ), demand(Grant.SUBMIT)),
        (declare(Grant.READ),),
    )
    assert [verdict.state for verdict in verdicts] == [
        VerificationState.DECLARED,
        VerificationState.INSUFFICIENT,
    ]


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def test_a_declaration_renders_its_reference_and_its_grants() -> None:
    record = declare(Grant.READ, Grant.SUBMIT).as_record()
    assert record == {
        "environment": "paper",
        "name": "venue_key",
        "kind": "api_key",
        "declared": ["read", "submit"],
    }


def test_a_verdict_renders_both_differences() -> None:
    record = verify(demand(Grant.READ, Grant.SUBMIT), declare(Grant.READ)).as_record()
    assert record["state"] == "insufficient"
    assert record["missing"] == ["submit"]
    assert record["excess"] == []


def test_grant_names_are_canonical() -> None:
    assert GrantSet((Grant.SUBMIT, Grant.READ)).names() == ("read", "submit")


# ---------------------------------------------------------------------------
# The register
# ---------------------------------------------------------------------------


class _Documents:
    """A state store that keeps documents in memory."""

    def __init__(self, *, refuse: bool = False) -> None:
        self.documents: dict[str, Mapping[str, object]] = {}
        self.refuse = refuse

    def publish(self, area: RuntimeArea, name: str, document: Mapping[str, object]) -> None:
        del area
        if self.refuse:
            msg = "this store is not writable"
            raise RuntimePersistenceError(msg)
        self.documents[name] = document

    def read(self, area: RuntimeArea, name: str) -> Mapping[str, object] | None:
        del area
        return self.documents.get(name)

    def discard(self, area: RuntimeArea, name: str) -> None:
        del area
        self.documents.pop(name, None)


def test_a_register_that_was_never_written_declares_nothing() -> None:
    """Which refuses, because nothing declared means nothing permitted."""
    assert StateGrantRegister(store=_Documents()).declarations() == ()


def test_a_store_that_cannot_be_read_declares_nothing() -> None:
    """The other half of the persistence boundary, and the refusing direction."""

    class _Unreadable(_Documents):
        def read(self, area: RuntimeArea, name: str) -> Mapping[str, object] | None:
            del area, name
            msg = "this store is not readable"
            raise RuntimePersistenceError(msg)

    assert StateGrantRegister(store=_Unreadable()).declarations() == ()


def test_a_declaration_survives_a_round_trip() -> None:
    register = StateGrantRegister(store=_Documents())
    assert register.declare(declare(Grant.READ, Grant.SUBMIT)) is True
    (found,) = register.declarations()
    assert found.reference == KEY
    assert found.declared.names() == ("read", "submit")


def test_declaring_the_same_reference_twice_replaces_rather_than_duplicates() -> None:
    """A register with two answers for one credential could not be consulted."""
    register = StateGrantRegister(store=_Documents())
    register.declare(declare(Grant.READ))
    register.declare(declare(Grant.SUBMIT))
    (found,) = register.declarations()
    assert found.declared.names() == ("submit",)


def test_two_references_are_both_kept_and_sorted() -> None:
    register = StateGrantRegister(store=_Documents())
    register.declare(GrantDeclaration(reference=OTHER, declared=GrantSet((Grant.READ,))))
    register.declare(declare(Grant.SUBMIT))
    assert [item.reference.name for item in register.declarations()] == [
        "other_key",
        "venue_key",
    ]


def test_a_store_that_cannot_be_written_reports_it_rather_than_raising() -> None:
    register = StateGrantRegister(store=_Documents(refuse=True))
    assert register.declare(declare(Grant.READ)) is False


@pytest.mark.parametrize(
    "document",
    [
        pytest.param({"schema": "something.else"}, id="another-schema"),
        pytest.param({"schema": SCHEMA, "schema_version": 99}, id="unknown-version"),
        pytest.param(
            {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "declarations": "no"},
            id="declarations-not-a-list",
        ),
    ],
)
def test_a_document_this_reader_does_not_recognise_declares_nothing(
    document: Mapping[str, object],
) -> None:
    """Refusing is the safe direction: nothing declared permits nothing."""
    store = _Documents()
    store.documents[REGISTER_NAME] = document
    assert StateGrantRegister(store=store).declarations() == ()


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param("not a mapping", id="not-a-mapping"),
        pytest.param({"name": "k", "kind": "api_key", "declared": []}, id="no-environment"),
        pytest.param({"environment": "paper", "kind": "api_key", "declared": []}, id="no-name"),
        pytest.param({"environment": "paper", "name": "k", "declared": []}, id="no-kind"),
        pytest.param({"environment": "paper", "name": "k", "kind": "api_key"}, id="no-declared"),
        pytest.param(
            {"environment": "paper", "name": "k", "kind": "nonsense", "declared": []},
            id="unknown-kind",
        ),
        pytest.param(
            {"environment": "PAPER!", "name": "k", "kind": "api_key", "declared": []},
            id="unusable-environment",
        ),
        pytest.param(
            {"environment": "paper", "name": "k", "kind": "api_key", "declared": ["fly"]},
            id="unknown-grant",
        ),
    ],
)
def test_one_malformed_entry_is_dropped_and_the_rest_survive(entry: object) -> None:
    """Dropping refuses one credential; raising would take the register out."""
    store = _Documents()
    store.documents[REGISTER_NAME] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "declarations": [
            entry,
            {
                "environment": "paper",
                "name": "venue_key",
                "kind": "api_key",
                "declared": ["read"],
            },
        ],
    }
    found = StateGrantRegister(store=store).declarations()
    assert [item.reference.name for item in found] == ["venue_key"]
