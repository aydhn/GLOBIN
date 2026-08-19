"""The environment classes, checked against the package and against the registry.

Three documents have to agree about what an environment is, and each knows
something the others do not.

`globin.domain.environment_class` holds the **shape** — four kinds and what each
guarantees — and may not name an environment at all, because
`tests/architecture/test_identifier_discipline.py` refuses a venue instance name in
the domain layer.

`docs/engineering/environment-classes.toml` holds the **instances** and the
**provenance**: which name is which kind, and which document each guarantee was
read from.

`docs/engineering/binance-api-reality.toml` holds what the **venue** documents,
one row per product-and-environment pair, for the three environments the venue
publishes and not for the one GLOBIN hosts.

This file compares all three, in both directions wherever both directions mean
something. The comparison that earns the file is the last one: `paper` must be
classified and must have **no registry row at all**, because an environment GLOBIN
simulates having a venue endpoint would be a contradiction rather than a surprise.
"""

import tomllib
from pathlib import Path
from typing import Any, Final

import pytest

from globin.adapters.environment_class import (
    CLASSES_PATH,
    GUARANTEE_FIELDS,
    SUPPORTED_SCHEMA,
    disagreements,
    guarantees_of,
    read_classes,
)
from globin.domain.environment_class import (
    GLOBIN_OWN_SOURCE,
    EnvironmentClass,
    EnvironmentClassification,
    guarantees,
    guarantees_for,
)
from globin.errors import ValidationError

REGISTRY_RELATIVE_PATH: Final[str] = "docs/engineering/binance-api-reality.toml"
"""Phase 033's registry."""


@pytest.fixture(scope="module")
def repo_root() -> Path:
    """Where the repository is, from this file."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def read(repo_root: Path) -> tuple[EnvironmentClassification, tuple[Any, ...]]:
    """The classification and the declared class rows."""
    result = read_classes(repo_root / CLASSES_PATH)
    assert result is not None, f"{CLASSES_PATH} must be readable"
    return result


@pytest.fixture(scope="module")
def registry(repo_root: Path) -> dict[str, Any]:
    """Phase 033's registry as a parsed document."""
    return tomllib.loads((repo_root / REGISTRY_RELATIVE_PATH).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The document against the package
# ---------------------------------------------------------------------------


def test_the_document_and_the_package_agree_on_every_guarantee(
    read: tuple[EnvironmentClassification, tuple[Any, ...]],
) -> None:
    """The comparison the second copy exists to make possible."""
    _classification, declared = read
    assert disagreements(declared) == ()


def test_every_class_is_declared_and_no_other(
    read: tuple[EnvironmentClassification, tuple[Any, ...]],
) -> None:
    """Both directions. A class the document omits would answer as unclassified."""
    _classification, declared = read
    assert {row.environment_class for row in declared} == set(EnvironmentClass)


def test_every_declared_guarantee_field_is_a_field_on_the_type() -> None:
    """The reader lists the fields rather than deriving them, so the list is checked.

    Deriving would make a field added to the dataclass and forgotten in the
    document read as `False`, which is a guarantee silently weakened. Listing makes
    it a visible failure — and means this assertion has to exist.
    """
    entry = guarantees()[0]
    for field in GUARANTEE_FIELDS:
        assert isinstance(getattr(entry, field), bool), field


def test_only_the_simulated_class_cites_globin_itself() -> None:
    """A venue-hosted class citing GLOBIN would attribute a claim to nobody.

    And the reverse: the simulated class citing a Binance document would attribute
    to Binance a claim about an environment Binance has never heard of.
    """
    for entry in guarantees():
        own = entry.source == GLOBIN_OWN_SOURCE
        assert own == (entry.environment_class is EnvironmentClass.INTERNAL_SIMULATION), entry


def test_every_venue_class_cites_a_source_the_registry_declares(
    registry: dict[str, Any],
) -> None:
    """A guarantee whose citation names nothing is a citation nobody could check."""
    known = {row["id"] for row in registry["source"]}
    for entry in guarantees():
        if entry.source == GLOBIN_OWN_SOURCE:
            continue
        assert entry.source in known, entry.environment_class


# ---------------------------------------------------------------------------
# The document against the registry
# ---------------------------------------------------------------------------


def test_every_registry_environment_is_classified(
    read: tuple[EnvironmentClassification, tuple[Any, ...]], registry: dict[str, Any]
) -> None:
    """An environment the registry knows and the classes do not would refuse every request."""
    classification, _declared = read
    names = {row["environment"] for row in registry["environment"]}
    unclassified = sorted(name for name in names if classification.classify(name) is None)
    assert not unclassified, f"the registry declares environments with no class: {unclassified}"


def test_the_capital_guarantee_agrees_with_the_registry(
    read: tuple[EnvironmentClassification, tuple[Any, ...]], registry: dict[str, Any]
) -> None:
    """The one guarantee both documents carry, so the one that can disagree.

    `carries_real_capital` is restated in the class model precisely so this
    comparison exists. Two documents that agreed by nobody checking would be two
    copies rather than one fact.
    """
    classification, _declared = read
    for row in registry["environment"]:
        facts = classification.guarantees_for_name(row["environment"])
        assert facts is not None, row["environment"]
        assert facts.carries_real_capital == row.get("carries_real_capital", False), (
            f"{row['environment']}: the registry and the class model disagree about capital"
        )


def test_the_simulated_class_has_no_registry_row_at_all(
    read: tuple[EnvironmentClassification, tuple[Any, ...]], registry: dict[str, Any]
) -> None:
    """The check that earns this file.

    An environment GLOBIN simulates cannot have a venue endpoint, and the failure
    if it did would be silent: `resolve()` would hand back a URL, `resolve_auth`
    would still refuse at gate 1, and the two documents would disagree about
    whether a venue exists with nothing reporting it.
    """
    classification, _declared = read
    simulated = {
        name
        for name, environment_class in classification.entries
        if environment_class is EnvironmentClass.INTERNAL_SIMULATION
    }
    assert simulated, "no environment is classified as internal simulation"
    published = {row["environment"] for row in registry["environment"]}
    overlap = sorted(simulated & published)
    assert not overlap, (
        f"{overlap} is classified as internal simulation and has a registry row; an "
        "environment GLOBIN simulates has no venue"
    )
    endpoints = {row["environment"] for row in registry["endpoint"]}
    assert not simulated & endpoints


def test_no_simulated_environment_accepts_a_credential(
    read: tuple[EnvironmentClassification, tuple[Any, ...]],
) -> None:
    """Gate 1 of the authentication admission, asserted as a property of the data."""
    classification, _declared = read
    for name, environment_class in classification.entries:
        facts = guarantees_for(environment_class)
        if environment_class is EnvironmentClass.INTERNAL_SIMULATION:
            assert not facts.accepts_credential, name
            assert not facts.reaches_venue, name


def test_the_default_profile_is_classified(repo_root: Path, read: tuple[Any, ...]) -> None:
    """`paper` is `DEFAULT_PROFILE`, so an unclassified one would refuse by default.

    Read from the profile directory rather than named here, so a profile renamed
    without a class fails rather than being missed.
    """
    classification, _declared = read
    profiles = sorted(path.stem for path in (repo_root / "config" / "profiles").glob("*.toml"))
    assert profiles, "no configuration profiles were found"
    unclassified = [name for name in profiles if classification.classify(name) is None]
    assert not unclassified, f"a configuration profile names no environment class: {unclassified}"


# ---------------------------------------------------------------------------
# The classes are genuinely distinct
# ---------------------------------------------------------------------------


def test_no_two_classes_carry_identical_guarantees() -> None:
    """ROADMAP row 035 says "distinct guarantees", so identical rows would make it untrue.

    This is the assertion that forced `feature_parity_with_live` to exist: without
    it the two venue sandboxes agreed on every field, and two classes that promise
    exactly the same thing are one class with two names.
    """
    seen: dict[tuple[bool, ...], EnvironmentClass] = {}
    for entry in guarantees():
        shape = tuple(getattr(entry, field) for field in GUARANTEE_FIELDS)
        clash = seen.get(shape)
        assert clash is None, (
            f"{entry.environment_class.value} and {clash.value if clash else ''} promise "
            "exactly the same thing, so they are one class with two names"
        )
        seen[shape] = entry.environment_class


def test_exactly_one_class_risks_real_capital() -> None:
    """More than one would mean two ways to lose money and one place to check."""
    risky = [item.environment_class for item in guarantees() if item.carries_real_capital]
    assert risky == [EnvironmentClass.LIVE_CAPITAL]


def test_a_class_that_reaches_no_venue_cannot_claim_a_venue_fact() -> None:
    """The consistency rule, exercised rather than trusted."""
    with pytest.raises(ValidationError, match="reaches no venue"):
        guarantees()[0].__class__(
            environment_class=EnvironmentClass.INTERNAL_SIMULATION,
            carries_real_capital=False,
            reaches_venue=False,
            accepts_credential=True,
            orders_are_binding=False,
            market_data_is_real=True,
            state_is_venue_owned=False,
            feature_parity_with_live=False,
            source=GLOBIN_OWN_SOURCE,
            semantics="a contradiction",
        )


# ---------------------------------------------------------------------------
# The reader
# ---------------------------------------------------------------------------


def test_an_absent_document_is_unmeasured_rather_than_an_error(tmp_path: Path) -> None:
    """Absent and wrong are different states with different remedies."""
    assert read_classes(tmp_path / "nothing.toml") is None


def test_an_unparseable_document_is_unmeasured_rather_than_an_error(tmp_path: Path) -> None:
    """Same rule as `globin.adapters.api_reality`, for the same reason."""
    path = tmp_path / "broken.toml"
    path.write_text("this is not = = toml", encoding="utf-8")
    assert read_classes(path) is None


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param("schema = 99\n", "understands", id="wrong-schema"),
        pytest.param(
            f'schema = {SUPPORTED_SCHEMA}\n[[class]]\nname = "nope"\n',
            "not one of",
            id="unknown-class",
        ),
        pytest.param(
            f"schema = {SUPPORTED_SCHEMA}\n",
            "declares no guarantees",
            id="no-classes",
        ),
    ],
)
def test_a_document_that_is_wrong_about_itself_raises(
    tmp_path: Path, document: str, expected: str
) -> None:
    """Present-and-wrong is a defect in this repository, so it raises rather than returning None."""
    path = tmp_path / "wrong.toml"
    path.write_text(document, encoding="utf-8")
    with pytest.raises(ValidationError, match=expected):
        read_classes(path)


def test_a_classification_refuses_a_name_filed_twice() -> None:
    """Two rows would make the answer depend on read order."""
    with pytest.raises(ValidationError, match="twice"):
        EnvironmentClassification(
            entries=(
                ("somewhere", EnvironmentClass.VENUE_DEMO),
                ("somewhere", EnvironmentClass.VENUE_TESTNET),
            )
        )


def test_an_unclassified_name_is_none_rather_than_a_guess(
    read: tuple[EnvironmentClassification, tuple[Any, ...]],
) -> None:
    """Fail-closed. ADR-0006 forbids exactly the guess a default would make."""
    classification, _declared = read
    assert classification.classify("staging") is None
    assert classification.guarantees_for_name("staging") is None


def test_the_credentialled_names_are_derived_rather_than_listed(
    read: tuple[EnvironmentClassification, tuple[Any, ...]],
) -> None:
    """A second list would be a second place to forget an environment."""
    classification, _declared = read
    names = classification.credentialled_names()
    for name in names:
        facts = classification.guarantees_for_name(name)
        assert facts is not None, name
        assert facts.accepts_credential, name
    for name, _class in classification.entries:
        facts = classification.guarantees_for_name(name)
        assert facts is not None
        assert (name in names) == facts.accepts_credential, name


def test_the_used_classes_are_the_ones_something_is_filed_under(
    read: tuple[EnvironmentClassification, tuple[Any, ...]],
) -> None:
    """A class nothing names is a definition rather than a state this host can be in."""
    classification, _declared = read
    used = {item.environment_class for item in guarantees_of(classification)}
    assert used == {environment_class for _name, environment_class in classification.entries}
