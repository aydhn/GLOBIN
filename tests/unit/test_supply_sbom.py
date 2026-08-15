"""The CycloneDX 1.7 document, and the determinism it is bought for.

A SBOM whose bytes change when nothing changed cannot be evidence of anything.
Most of this module is about the fields that would ordinarily drift — the serial
number, the timestamp and the component order — and about the validator that
catches it when they do.
"""

import json

import pytest

from tools.quality.supply import sbom
from tools.quality.supply.inventory import (
    CONTINUOUS_INTEGRATION,
    DEVELOPMENT,
    GITHUB_ACTIONS,
    PINNED,
    PYPI,
    RANGED,
    Dependency,
)

FULL_SHA = "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"
COMMIT = "1d0dc5d072556f9e7cc6943247cf3a5d023481c0"
OTHER_COMMIT = "b644383000000000000000000000000000000000"

ARGUMENTS = {
    "repository": "aydhn/GLOBIN",
    "commit": COMMIT,
    "timestamp": "2026-08-15T04:36:13+03:00",
    "project": "globin",
    "project_version": "0.1.0",
    "generator_version": "0.1.0",
}

DEPENDENCIES = (
    Dependency(PYPI, "ruff", "0.15.14", CONTINUOUS_INTEGRATION, PINNED, "w.yml"),
    Dependency(PYPI, "ruff", ">=0.6", DEVELOPMENT, RANGED, "pyproject.toml"),
    Dependency(
        GITHUB_ACTIONS, "actions/checkout", FULL_SHA, CONTINUOUS_INTEGRATION, PINNED, "w.yml"
    ),
)


@pytest.fixture
def document() -> dict[str, object]:
    """A valid BOM over three dependencies."""
    return sbom.build(DEPENDENCIES, **ARGUMENTS)


def test_the_required_fields_carry_the_values_the_specification_demands(
    document: dict[str, object],
) -> None:
    """``bomFormat`` and ``specVersion`` are the two the schema requires."""
    assert document["bomFormat"] == "CycloneDX"
    assert document["specVersion"] == "1.7"
    assert str(document["serialNumber"]).startswith("urn:uuid:")
    assert not sbom.validate(document)


def test_two_builds_of_one_inventory_are_byte_identical(document: dict[str, object]) -> None:
    """The property the whole module exists for.

    Built twice from the same values, rather than compared against a stored
    string, because what is being asserted is that the *generator* is a function
    of its input — not that one particular output was recorded correctly.
    """
    again = sbom.build(DEPENDENCIES, **ARGUMENTS)
    assert sbom.render(document) == sbom.render(again)
    assert sbom.digest(document) == sbom.digest(again)


def test_the_serial_is_derived_from_the_commit_rather_than_generated() -> None:
    """A random serial would change the digest on every run for no reason.

    Two commits still get two serials, so the derivation does not collapse
    distinct trees onto one identifier.
    """
    first = sbom.serial_number("aydhn/GLOBIN", COMMIT)
    assert first == sbom.serial_number("aydhn/GLOBIN", COMMIT)
    assert first != sbom.serial_number("aydhn/GLOBIN", OTHER_COMMIT)
    assert first != sbom.serial_number("someone/else", COMMIT)


def test_a_ranged_dependency_gets_no_version_and_no_package_url(
    document: dict[str, object],
) -> None:
    """A range is not a version, and a package URL naming one claims an artefact.

    No index could resolve ``pkg:pypi/ruff@>=0.6``. The range is preserved as a
    property instead, so nothing is lost and nothing is overstated.
    """
    components = document["components"]
    assert isinstance(components, list)
    ranged = next(entry for entry in components if entry["bom-ref"].endswith("#development"))
    assert "version" not in ranged
    assert "purl" not in ranged
    assert {"name": "globin:specifier", "value": ">=0.6"} in ranged["properties"]


def test_one_package_in_two_scopes_produces_two_distinguishable_components(
    document: dict[str, object],
) -> None:
    """``bom-ref`` must be unique, and ``ruff`` legitimately appears twice."""
    components = document["components"]
    assert isinstance(components, list)
    refs = [entry["bom-ref"] for entry in components]
    assert len(refs) == len(set(refs))
    assert sum(1 for entry in components if entry["name"] == "ruff") == 2


def test_components_are_ordered_by_the_key_the_document_shows(
    document: dict[str, object],
) -> None:
    """Ordered by ``bom-ref`` rather than by the inventory's dataclass ordering.

    Both are total, so either would be deterministic. This one is *checkable*:
    the key it sorts on is visible in the file, so a reader can confirm the order
    without knowing how the inventory sorts its fields.
    """
    components = document["components"]
    assert isinstance(components, list)
    refs = [entry["bom-ref"] for entry in components]
    assert refs == sorted(refs)


def test_the_dependency_graph_states_only_what_is_known(document: dict[str, object]) -> None:
    """The root depends on each declared component, and nothing else is claimed.

    Nothing here resolves a transitive tree, so inventing edges between
    components to make the graph look complete would be inventing facts.
    """
    edges = document["dependencies"]
    assert isinstance(edges, list)
    root = edges[0]
    assert root["ref"] == "globin@0.1.0"
    assert len(root["dependsOn"]) == len(DEPENDENCIES)
    assert all(not edge["dependsOn"] for edge in edges[1:])


# ---------------------------------------------------------------------------
# What the validator catches
# ---------------------------------------------------------------------------


def test_a_wrong_specification_version_is_reported(document: dict[str, object]) -> None:
    """A reader would apply the wrong schema, which is worse than refusing."""
    document["specVersion"] = "1.6"
    assert any("specVersion" in problem for problem in sbom.validate(document))


def test_a_wrong_format_is_reported(document: dict[str, object]) -> None:
    """``bomFormat`` has exactly one permitted value."""
    document["bomFormat"] = "SPDX"
    assert any("bomFormat" in problem for problem in sbom.validate(document))


def test_a_duplicate_component_is_reported(document: dict[str, object]) -> None:
    """A ``bom-ref`` identifies one component; two would make every edge ambiguous."""
    components = document["components"]
    assert isinstance(components, list)
    components.append(components[0])
    assert any("more than one component" in problem for problem in sbom.validate(document))


def test_components_out_of_order_are_reported(document: dict[str, object]) -> None:
    """The check that would catch a generator that stopped sorting."""
    components = document["components"]
    assert isinstance(components, list)
    components.reverse()
    assert any("canonical order" in problem for problem in sbom.validate(document))


def test_an_edge_pointing_at_nothing_is_reported(document: dict[str, object]) -> None:
    """A dependency graph naming a component the document does not contain."""
    edges = document["dependencies"]
    assert isinstance(edges, list)
    edges[0]["dependsOn"].append("pypi/ghost@1.0.0#development")
    assert any("not a component in this BOM" in problem for problem in sbom.validate(document))


def test_a_component_without_a_type_is_reported(document: dict[str, object]) -> None:
    """``type`` and ``name`` are the two fields a component must carry."""
    components = document["components"]
    assert isinstance(components, list)
    del components[0]["type"]
    assert any("declares no type" in problem for problem in sbom.validate(document))


def test_a_missing_components_array_is_reported() -> None:
    """Refused rather than read as a BOM describing nothing."""
    assert any("components is missing" in problem for problem in sbom.validate({}))


def test_a_serial_that_is_not_a_urn_is_reported(document: dict[str, object]) -> None:
    """RFC 4122 or nothing; a bare integer is neither."""
    document["serialNumber"] = "42"
    assert any("RFC 4122" in problem for problem in sbom.validate(document))


def test_the_rendering_is_json_and_ascii(document: dict[str, object]) -> None:
    """Parseable by anything, and unaffected by any console codepage."""
    text = sbom.render(document)
    assert json.loads(text)
    assert text.isascii()
    assert text.endswith("\n")


def test_ecosystem_counts_include_the_zeroes() -> None:
    """A missing key and a zero mean different things, and only one of them is true."""
    counts = sbom.ecosystem_counts(DEPENDENCIES)
    assert counts["pypi"] == 2
    assert counts["github-actions"] == 1
    assert counts["pre-commit"] == 0
