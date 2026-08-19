"""The environment class model and its reader, refusal by refusal.

`tests/contract/test_environment_class_contract.py` checks the **committed**
documents against each other, which is the claim that matters. This file checks
what the types and the reader do with documents nobody has committed — every
refusal, and every disagreement `disagreements()` can report.

That split is deliberate. A contract test that constructed its own broken
documents would stop being about the repository; a unit test that only read the
committed one would leave every error branch unexercised, which is how a refusal
quietly stops refusing.
"""

from pathlib import Path
from typing import Any, Final

import pytest

from globin.adapters.environment_class import (
    CLASSES_PATH,
    SUPPORTED_SCHEMA,
    DeclaredClass,
    disagreements,
    guarantees_of,
    read_classes,
)
from globin.domain.environment_class import (
    GLOBIN_OWN_SOURCE,
    MAX_CLASSIFIED_NAMES,
    EnvironmentClass,
    EnvironmentClassification,
    EnvironmentGuarantees,
    guarantees,
    guarantees_for,
)
from globin.errors import InternalError, ValidationError

VENUE_FIELDS: Final[dict[str, bool]] = {
    "carries_real_capital": False,
    "reaches_venue": True,
    "accepts_credential": True,
    "orders_are_binding": False,
    "market_data_is_real": False,
    "state_is_venue_owned": True,
    "feature_parity_with_live": True,
}
"""A coherent set of guarantees for a venue-hosted class, to vary one at a time."""


def _guarantees(**overrides: object) -> EnvironmentGuarantees:
    """Build a guarantee set, overriding whatever a test is about.

    Args:
        **overrides: Any field on :class:`EnvironmentGuarantees`.

    Returns:
        The guarantees.
    """
    fields: dict[str, Any] = {
        "environment_class": EnvironmentClass.VENUE_DEMO,
        "source": "spot-demo",
        "semantics": "a coherent class",
        **VENUE_FIELDS,
    }
    fields.update(overrides)
    return EnvironmentGuarantees(**fields)


# ---------------------------------------------------------------------------
# The guarantees refuse what they cannot mean
# ---------------------------------------------------------------------------


def test_a_class_with_no_semantics_is_refused() -> None:
    """An environment whose guarantees are unstated is the assumption ADR-0006 prevents."""
    with pytest.raises(ValidationError, match="declares no semantics"):
        _guarantees(semantics="")


def test_a_class_citing_no_source_is_refused() -> None:
    """A guarantee with no citation is a claim nobody can check."""
    with pytest.raises(ValidationError, match="cites no source"):
        _guarantees(source="")


@pytest.mark.parametrize(
    ("field", "phrase"),
    [
        pytest.param("accepts_credential", "present one to", id="credential"),
        pytest.param("state_is_venue_owned", "own state", id="state"),
        pytest.param("orders_are_binding", "bind an order", id="orders"),
        pytest.param("feature_parity_with_live", "feature set", id="parity"),
    ],
)
def test_a_class_that_reaches_no_venue_cannot_claim_a_venue_fact(field: str, phrase: str) -> None:
    """Four contradictions, each refused with a message naming which one."""
    unreachable = dict.fromkeys(VENUE_FIELDS, False)
    unreachable[field] = True
    with pytest.raises(ValidationError, match=phrase):
        _guarantees(
            environment_class=EnvironmentClass.INTERNAL_SIMULATION,
            source=GLOBIN_OWN_SOURCE,
            **unreachable,
        )


def test_real_capital_without_binding_orders_is_refused() -> None:
    """Capital does not move without a binding order."""
    with pytest.raises(ValidationError, match="capital does not move"):
        _guarantees(carries_real_capital=True, orders_are_binding=False)


def test_venue_hosted_is_true_for_every_class_but_the_simulated_one() -> None:
    """A named property rather than a comparison callers write themselves."""
    for entry in guarantees():
        expected = entry.environment_class is not EnvironmentClass.INTERNAL_SIMULATION
        assert entry.venue_hosted is expected, entry.environment_class


def test_a_guarantee_record_is_json_safe() -> None:
    """Every leaf a string or a boolean, so a manifest can carry it."""
    record = _guarantees().as_record()
    assert record["class"] == EnvironmentClass.VENUE_DEMO.value
    assert all(isinstance(value, (str, bool)) for value in record.values())


def test_a_class_with_no_declared_guarantees_is_an_internal_error() -> None:
    """A broken invariant rather than bad input, so it raises rather than defaulting.

    Unreachable through the real enumeration, which is why it is exercised through
    a member that does not exist rather than by weakening the function.
    """

    class Fake:
        """Something shaped like a class member and filed under no guarantees."""

        value = "not_a_class"

    with pytest.raises(InternalError, match="has no declared guarantees"):
        guarantees_for(Fake())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The classification
# ---------------------------------------------------------------------------


def test_a_classification_refuses_an_empty_name() -> None:
    """An environment with no name could never be matched, and would refuse silently."""
    with pytest.raises(ValidationError, match="empty name"):
        EnvironmentClassification(entries=(("", EnvironmentClass.VENUE_DEMO),))


def test_a_classification_refuses_more_names_than_it_bounds() -> None:
    """Every document this repository reads is bounded rather than trusted."""
    entries = tuple(
        (f"env{index}", EnvironmentClass.VENUE_DEMO) for index in range(MAX_CLASSIFIED_NAMES + 1)
    )
    with pytest.raises(ValidationError, match=str(MAX_CLASSIFIED_NAMES)):
        EnvironmentClassification(entries=entries)


def test_a_classification_record_lists_names_and_the_credentialled_subset() -> None:
    """What `globin auth classes --json` publishes, and it carries nothing sensitive."""
    classification = EnvironmentClassification(
        entries=(
            ("somewhere", EnvironmentClass.VENUE_TESTNET),
            ("nowhere", EnvironmentClass.INTERNAL_SIMULATION),
        )
    )
    record = classification.as_record()
    assert record["credentialled"] == ["somewhere"]
    assert record["environments"] == [
        {"name": "somewhere", "class": "venue_testnet"},
        {"name": "nowhere", "class": "internal_simulation"},
    ]


def test_an_empty_classification_classifies_nothing() -> None:
    """The fail-closed floor: with no rows, every name is unclassified."""
    empty = EnvironmentClassification()
    assert empty.classify("production") is None
    assert empty.credentialled_names() == ()
    assert guarantees_of(empty) == ()


# ---------------------------------------------------------------------------
# The reader refuses a document that is wrong about itself
# ---------------------------------------------------------------------------


def _complete_classes() -> str:
    """Every class declared coherently, so a test can break exactly one thing.

    Returns:
        A TOML document.
    """
    rows = []
    for entry in guarantees():
        booleans = "\n".join(
            f"{field} = {str(getattr(entry, field)).lower()}" for field in VENUE_FIELDS
        )
        rows.append(
            f'[[class]]\nname = "{entry.environment_class.value}"\n{booleans}\n'
            f'source = "{entry.source}"\n'
        )
    return f"schema = {SUPPORTED_SCHEMA}\n\n" + "\n".join(rows)


def _write(tmp_path: Path, document: str) -> Path:
    """Write a document and return its path.

    Args:
        tmp_path: Where to write it.
        document: The TOML source.

    Returns:
        The path.
    """
    path = tmp_path / "classes.toml"
    path.write_text(document, encoding="utf-8")
    return path


def test_a_complete_document_reads(tmp_path: Path) -> None:
    """The positive case, so every refusal below is not vacuously satisfied."""
    result = read_classes(_write(tmp_path, _complete_classes()))
    assert result is not None
    classification, declared = result
    assert classification.entries == ()
    assert len(declared) == len(EnvironmentClass)
    assert disagreements(declared) == ()


def test_a_table_that_is_not_an_array_of_tables_is_refused(tmp_path: Path) -> None:
    """A shape the reader cannot walk, refused rather than silently skipped."""
    # Placed before any table header. A key appended to the end of the document
    # would be filed inside the last `[[class]]` table, where the reader never
    # looks — which is a TOML fact worth stating rather than rediscovering.
    document = _complete_classes().replace(
        f"schema = {SUPPORTED_SCHEMA}",
        f'schema = {SUPPORTED_SCHEMA}\nmember = "not a table"',
        1,
    )
    with pytest.raises(ValidationError, match="array of tables"):
        read_classes(_write(tmp_path, document))


def test_a_class_name_that_is_not_a_string_is_refused(tmp_path: Path) -> None:
    """A number where a name belongs means the document and the reader disagree."""
    document = f"schema = {SUPPORTED_SCHEMA}\n\n[[class]]\nname = 7\n"
    with pytest.raises(ValidationError, match="not a string"):
        read_classes(_write(tmp_path, document))


def test_a_class_declared_twice_is_refused(tmp_path: Path) -> None:
    """Two rows would make the guarantees depend on read order."""
    first = _complete_classes()
    duplicate = first.split("[[class]]")[1]
    with pytest.raises(ValidationError, match="twice"):
        read_classes(_write(tmp_path, first + "\n[[class]]" + duplicate))


def test_a_guarantee_that_is_not_a_boolean_is_refused(tmp_path: Path) -> None:
    """A missing guarantee is not `False`; it is a document nobody finished."""
    document = _complete_classes().replace("reaches_venue = true", 'reaches_venue = "yes"', 1)
    with pytest.raises(ValidationError, match="every guarantee is a boolean"):
        read_classes(_write(tmp_path, document))


def test_a_class_row_citing_no_source_is_refused(tmp_path: Path) -> None:
    """The document's whole contribution is provenance."""
    document = _complete_classes().replace('source = "spot-rest"', 'source = ""', 1)
    with pytest.raises(ValidationError, match="cites no source"):
        read_classes(_write(tmp_path, document))


def test_a_member_with_no_name_is_refused(tmp_path: Path) -> None:
    """A row that classifies nothing."""
    document = _complete_classes() + '\n[[member]]\nclass = "venue_demo"\n'
    with pytest.raises(ValidationError, match="no name"):
        read_classes(_write(tmp_path, document))


def test_a_member_naming_an_unknown_class_is_refused(tmp_path: Path) -> None:
    """The document and the enumeration have drifted, which is what this reports."""
    document = _complete_classes() + '\n[[member]]\nname = "x"\nclass = "sandbox"\n'
    with pytest.raises(ValidationError, match="not one of"):
        read_classes(_write(tmp_path, document))


# ---------------------------------------------------------------------------
# Disagreements
# ---------------------------------------------------------------------------


def test_a_disagreeing_boolean_is_reported(tmp_path: Path) -> None:
    """The comparison the second copy exists to make possible, shown failing."""
    document = _complete_classes().replace(
        "market_data_is_real = true", "market_data_is_real = false", 1
    )
    result = read_classes(_write(tmp_path, document))
    assert result is not None
    problems = disagreements(result[1])
    assert any("market_data_is_real" in item for item in problems), problems


def test_a_disagreeing_source_is_reported(tmp_path: Path) -> None:
    """A guarantee that agrees on its value and not on its citation is uncheckable."""
    document = _complete_classes().replace('source = "spot-rest"', 'source = "somewhere"', 1)
    result = read_classes(_write(tmp_path, document))
    assert result is not None
    problems = disagreements(result[1])
    assert any(".source:" in item for item in problems), problems


def test_a_class_the_document_omits_is_reported() -> None:
    """`read_classes` refuses one, so this exercises `disagreements` directly.

    The two checks are separate on purpose: the reader refuses an *incomplete
    document*, and this function reports a *disagreeing set of rows*, which a
    caller could assemble some other way.
    """
    partial = tuple(
        DeclaredClass(
            environment_class=entry.environment_class,
            values=tuple((field, getattr(entry, field)) for field in VENUE_FIELDS),
            source=entry.source,
        )
        for entry in guarantees()
        if entry.environment_class is not EnvironmentClass.VENUE_DEMO
    )
    problems = disagreements(partial)
    assert problems == ("venue_demo: declared by the package, not by the document",)


def test_the_reader_path_constant_points_at_the_committed_document() -> None:
    """One spelling, so a reader and a gate cannot look at different files."""
    assert CLASSES_PATH.endswith("environment-classes.toml")
    assert Path(__file__).resolve().parents[2].joinpath(CLASSES_PATH).is_file()
