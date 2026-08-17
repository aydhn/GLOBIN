"""The secret store's domain: what a reference is, what a value refuses, and the key.

Every assertion here is from literals. No store is opened, no platform is
consulted, and nothing in this module could behave differently on a machine with
no credential manager — which is the point of putting the judgement in the domain.

**Every secret-shaped string below is synthetic and worthless**, in the shape
`docs/TESTING_STRATEGY.md` prescribes. None resembles a real credential, because
ADR-0048's prohibition admits no exception and because
`tools/quality/evidence/redaction.py` scans what the suite publishes.
"""

import dataclasses
import json

import pytest

from globin.domain.identifiers import environment_id
from globin.domain.observability import REDACTED
from globin.domain.secrets import (
    KEY_PREFIX,
    MAX_NAME_LENGTH,
    MAX_SECRET_BYTES,
    NAME_ALPHABET,
    SecretKind,
    SecretReference,
    SecretResolution,
    SecretSlot,
    SecretValue,
    StoreFault,
    store_key,
)
from globin.errors import InternalError, ValidationError

MATERIAL = "not-a-real-secret-0000"
"""Synthetic, obviously non-credential material used throughout."""


def reference(name: str = "venue_key", environment: str = "paper") -> SecretReference:
    """A reference, with the parts a test does not care about filled in."""
    return SecretReference(
        environment=environment_id(environment),
        kind=SecretKind.API_KEY,
        name=name,
    )


# ---------------------------------------------------------------------------
# A reference is ordinary data
# ---------------------------------------------------------------------------


def test_a_reference_renders_itself_in_full() -> None:
    """It carries no material, so hiding it would serve nothing and cost debugging."""
    text = repr(reference())
    assert "venue_key" in text
    assert "paper" in text
    assert REDACTED not in text


def test_a_reference_is_ordered_so_a_set_of_them_renders_deterministically() -> None:
    """Every manifest in this repository sorts what it lists."""
    unsorted = (reference("b"), reference("a"), reference("c"))
    assert [item.name for item in sorted(unsorted)] == ["a", "b", "c"]


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("", id="empty"),
        pytest.param("Venue_Key", id="uppercase, which would fold silently later"),
        pytest.param("venue key", id="a space"),
        pytest.param("venue:key", id="the key separator"),
        pytest.param("venue.key", id="a dot, which is outside the alphabet"),
        pytest.param("x" * (MAX_NAME_LENGTH + 1), id="longer than the bound"),
    ],
)
def test_a_name_outside_the_alphabet_is_refused(name: str) -> None:
    """Refused at construction, so two names a caller believes distinct never exist.

    Uppercase matters most here. `store_key` folds case, so `Venue_Key` and
    `venue_key` would produce one credential; refusing the uppercase spelling
    outright means a caller never forms the pair in the first place.
    """
    with pytest.raises(ValidationError):
        reference(name)


def test_a_name_exactly_at_the_bound_is_accepted() -> None:
    """The boundary itself, so the constant is a rule rather than a suggestion."""
    assert reference("x" * MAX_NAME_LENGTH).name == "x" * MAX_NAME_LENGTH


def test_every_permitted_character_really_is_permitted() -> None:
    """The alphabet is the rule, so it is exercised rather than trusted."""
    assert reference(NAME_ALPHABET.replace("-", "") + "-").name


# ---------------------------------------------------------------------------
# A value is not
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "render",
    [
        pytest.param(str, id="str()"),
        pytest.param(repr, id="repr(), which is what a traceback reaches for"),
        pytest.param(lambda value: f"{value}", id="an f-string"),
        pytest.param(lambda value: f"{value:>40}", id="an f-string with a format spec"),
        # Percent formatting is the subject of these two rows, not an accident:
        # `%s` routes through `__str__` and `%r` through `__repr__`, and both are
        # still reached by third-party code and by the standard library's own
        # `logging`. UP031 would have this rewritten as an f-string, which would
        # test a route these rows exist to cover separately.
        pytest.param(lambda value: "%s" % (value,), id="percent-s"),  # noqa: UP031
        pytest.param(lambda value: "%r" % (value,), id="percent-r"),  # noqa: UP031
        pytest.param(lambda value: str([value]), id="inside a list"),
        pytest.param(lambda value: str({"k": value}), id="inside a dict"),
        pytest.param(lambda value: str((value,)), id="inside a tuple"),
        pytest.param(lambda value: format(value), id="format()"),
    ],
)
def test_a_value_renders_as_the_marker_through_every_route(render: object) -> None:
    """`__repr__` matters more than `__str__`, and the format spec is the one people miss.

    `object.__format__` with a non-empty spec does not route through `__str__`,
    so a type overriding only the first two would raise on `f"{value:>40}"` — and
    a redaction that raises is one somebody removes.
    """
    rendered = render(SecretValue(MATERIAL))  # type: ignore[operator]
    assert MATERIAL not in rendered
    assert REDACTED in rendered


def test_a_value_has_no_dict_for_a_dump_helper_to_walk() -> None:
    """The structural half of section 1's second obligation."""
    with pytest.raises(TypeError):
        vars(SecretValue(MATERIAL))


def test_a_value_is_not_a_dataclass_so_asdict_cannot_enumerate_it() -> None:
    """A `slots=True` dataclass still has a field register; this deliberately does not."""
    assert not dataclasses.is_dataclass(SecretValue(MATERIAL))


def test_a_value_is_unhashable_so_it_cannot_become_a_key_or_a_set_member() -> None:
    """Two fewer structures material could reach and later be rendered from."""
    with pytest.raises(TypeError):
        hash(SecretValue(MATERIAL))


def test_a_value_survives_json_only_as_the_marker() -> None:
    """The serialiser meeting the object and doing the obvious thing.

    `json.dumps(default=str)` is the obvious thing, and it is what section 1 names
    as the failure mode to design out. It reaches `__str__`, which is redacted.
    """
    rendered = json.dumps({"value": SecretValue(MATERIAL)}, default=str)
    assert MATERIAL not in rendered
    assert REDACTED in rendered


def test_two_values_with_the_same_material_compare_equal() -> None:
    """Constant-time comparison must still be a correct comparison."""
    assert SecretValue(MATERIAL) == SecretValue(MATERIAL)


def test_two_values_with_different_material_compare_unequal() -> None:
    """The other direction, so the check above is not vacuously true."""
    assert SecretValue(MATERIAL) != SecretValue("something-else-000000")


def test_a_value_compared_against_a_foreign_type_is_simply_unequal() -> None:
    """`NotImplemented` falls back to identity, which is `False` and not an error."""
    assert SecretValue(MATERIAL) != MATERIAL


def test_an_empty_value_is_refused() -> None:
    """An empty secret is a caller mistake, not a secret."""
    with pytest.raises(ValidationError):
        SecretValue("")


def test_a_value_at_the_ceiling_is_accepted_and_one_byte_over_is_not() -> None:
    """The boundary measured on the real host, as `phase_028_sources.md` S-05 records.

    2560 succeeds and 2561 fails against the platform. The domain refuses the
    second *before* the platform is reached, which is what turns an undocumented
    `RPC_X_BAD_STUB_DATA` into a named refusal.
    """
    assert SecretValue("x" * MAX_SECRET_BYTES).size_bytes() == MAX_SECRET_BYTES
    with pytest.raises(ValidationError, match="exceeds"):
        SecretValue("x" * (MAX_SECRET_BYTES + 1))


def test_the_ceiling_is_measured_in_encoded_bytes_not_characters() -> None:
    """A multi-byte character costs what it costs, which is the platform's unit."""
    with pytest.raises(ValidationError):
        SecretValue("é" * MAX_SECRET_BYTES)


def test_the_material_is_reachable_for_the_one_caller_that_must_have_it() -> None:
    """A store that could not read the value would not be a store."""
    assert SecretValue(MATERIAL).material() == MATERIAL


# ---------------------------------------------------------------------------
# The one key builder
# ---------------------------------------------------------------------------


def test_the_key_carries_every_part_of_the_identity() -> None:
    """Verbose on purpose: the platform permits 32767 characters."""
    key = store_key(reference())
    assert key.startswith(KEY_PREFIX.lower())
    assert "paper" in key
    assert SecretKind.API_KEY.value in key
    assert "venue_key" in key
    assert key.endswith(SecretSlot.CURRENT.value)


def test_the_key_is_lowercase_because_the_platform_folds_case_silently() -> None:
    """The platform folds case silently, so the builder must fold it deliberately.

    `phase_028_sources.md` S-06: a credential written under one spelling is
    returned for another, with no error and no warning.
    """
    assert store_key(reference()) == store_key(reference()).lower()


def test_two_environments_produce_two_keys() -> None:
    """The isolation section 3 requires is a property of the key, not a later check."""
    assert store_key(reference(environment="paper")) != store_key(reference(environment="testnet"))


def test_two_kinds_produce_two_keys() -> None:
    """A wrong-kind resolution cannot silently succeed."""
    first = SecretReference(environment=environment_id("paper"), kind=SecretKind.API_KEY, name="k")
    second = SecretReference(
        environment=environment_id("paper"), kind=SecretKind.API_SECRET, name="k"
    )
    assert store_key(first) != store_key(second)


def test_the_two_slots_produce_two_keys() -> None:
    """Rotation depends on this: the previous value must survive the new write."""
    assert store_key(reference(), SecretSlot.CURRENT) != store_key(reference(), SecretSlot.PREVIOUS)


def test_a_name_ending_in_previous_cannot_collide_with_another_names_previous_slot() -> None:
    """Why the slot is a bounded key component rather than a suffix on the name.

    Were the previous slot spelled by appending to the name, a reference
    legitimately called `venue_key_previous` would address the same credential as
    the previous slot of `venue_key`, and a rotation would destroy an unrelated
    secret.
    """
    decoy = store_key(reference("venue_key_previous"), SecretSlot.CURRENT)
    real = store_key(reference("venue_key"), SecretSlot.PREVIOUS)
    assert decoy != real


def test_the_key_is_a_pure_function_of_the_identity() -> None:
    """Identical inputs give an identical key, which section 2 requires."""
    assert store_key(reference()) == store_key(reference())


# ---------------------------------------------------------------------------
# A resolution carries exactly one outcome
# ---------------------------------------------------------------------------


def test_a_resolution_with_a_value_is_resolved() -> None:
    """The ordinary success."""
    resolution = SecretResolution(reference=reference(), value=SecretValue(MATERIAL))
    assert resolution.resolved


def test_a_resolution_with_a_fault_is_not() -> None:
    """The ordinary failure."""
    resolution = SecretResolution(reference=reference(), fault=StoreFault.ABSENT)
    assert not resolution.resolved


@pytest.mark.parametrize(
    ("value", "fault"),
    [
        pytest.param(SecretValue(MATERIAL), StoreFault.ABSENT, id="both"),
        pytest.param(None, None, id="neither"),
    ],
)
def test_a_resolution_carrying_both_or_neither_is_refused(
    value: SecretValue | None, fault: StoreFault | None
) -> None:
    """Exactly one outcome, enforced at construction rather than documented.

    Both would let a caller read the value and ignore the fault; neither is a
    third state nobody wrote a branch for.
    """
    with pytest.raises(InternalError):
        SecretResolution(reference=reference(), value=value, fault=fault)


def test_a_resolution_record_never_carries_the_value() -> None:
    """The record is what reaches evidence, and the value has no representation in it."""
    record = SecretResolution(reference=reference(), value=SecretValue(MATERIAL)).as_record()
    assert MATERIAL not in json.dumps(record)
    assert record["resolved"] is True
    assert record["fault"] is None


def test_a_resolution_record_names_the_fault_when_there_is_one() -> None:
    """Section 3: an explicit error, never a silent absence."""
    record = SecretResolution(reference=reference(), fault=StoreFault.NO_CREDENTIAL_SET).as_record()
    assert record["fault"] == StoreFault.NO_CREDENTIAL_SET.value


def test_the_key_builder_refuses_a_reference_that_bypassed_validation() -> None:
    """The guard on a type constructed some way that skipped `__post_init__`.

    Unreachable through the public constructor, which is why it is reached here
    by writing through the frozen dataclass. A defensive guard nobody has seen
    fire is indistinguishable from one that cannot, and this one stands between a
    malformed reference and a key with an empty component — which the platform
    would accept and which would collide with every other such key.
    """
    reference_ = reference()
    object.__setattr__(reference_, "name", "")
    with pytest.raises(ValidationError, match="incomplete reference"):
        store_key(reference_)
