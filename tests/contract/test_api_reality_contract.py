"""The committed registry, held to the rules it exists to enforce.

Unlike the unit tests, which build a record to make one refusal fire, these read
the document that ships. A rule nothing currently violates is worth asserting here
precisely because it is the state a later edit would break quietly.
"""

import tomllib
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.api_reality import REGISTRY_PATH, parse_registry
from globin.domain.api_reality import (
    ApiRealitySnapshot,
    EnvironmentName,
    EvidenceKind,
    ProductFamily,
    ProtocolKind,
    SourceRegime,
    SurfaceStatus,
)
from tools.quality.venue.gate import REGISTRY_PATH as GATE_REGISTRY_PATH
from tools.quality.venue.plan import STATUSES, findings_for, parse_declaration

SPOT: Final[ProductFamily] = ProductFamily("spot")


@pytest.fixture(scope="module")
def registry_text(repo_root: Path) -> str:
    """The committed registry, as text.

    Args:
        repo_root: The repository root.

    Returns:
        The document.
    """
    return (repo_root / REGISTRY_PATH).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def registry(registry_text: str) -> ApiRealitySnapshot:
    """The committed registry, parsed by the package's reader.

    Args:
        registry_text: The document.

    Returns:
        The snapshot.
    """
    return parse_registry(registry_text)


def test_the_committed_registry_parses_and_validates(registry: ApiRealitySnapshot) -> None:
    """Reaching this point is the assertion: the constructor refuses a bad one."""
    assert registry.products
    assert registry.sources


def test_the_gate_finds_nothing_wrong_with_it(registry_text: str) -> None:
    """The second reader agrees, and it shares no code with the first."""
    assert findings_for(parse_declaration(registry_text)) == ()


def test_both_readers_count_the_same_rows(registry_text: str, registry: ApiRealitySnapshot) -> None:
    """Two independent parses of one document must see the same document.

    This is what makes the second reader worth having: if the two ever disagree
    about how many endpoints exist, one of them is wrong and nobody would otherwise
    find out.
    """
    other = parse_declaration(registry_text)
    assert len(other.sources) == len(registry.sources)
    assert len(other.endpoints) == len(registry.endpoints)
    assert len(other.schemas) == len(registry.schemas)


def test_nothing_claims_to_have_been_observed(registry: ApiRealitySnapshot) -> None:
    """GLOBIN has never contacted the venue.

    The evidence kind exists because a later phase will have a transport. Until
    then, a row claiming observation is a lie the registry cannot be allowed to
    tell, and this is the assertion that stops one being written.
    """
    for product in registry.products:
        assert product.capability.evidence is not EvidenceKind.OBSERVED
    for surface in registry.surfaces:
        assert surface.capability.evidence is not EvidenceKind.OBSERVED
    for environment in registry.environments:
        assert environment.capability.evidence is not EvidenceKind.OBSERVED
    for endpoint in registry.endpoints:
        assert endpoint.capability.evidence is not EvidenceKind.OBSERVED


def test_the_registry_path_is_spelled_once_per_reader(repo_root: Path) -> None:
    """The two readers must look at the same file.

    They cannot share the constant -- nothing under ``tools`` imports the package --
    so the next best thing is a test that compares them.
    """
    assert REGISTRY_PATH == GATE_REGISTRY_PATH
    assert (repo_root / REGISTRY_PATH).is_file()


def test_the_two_readers_agree_about_the_status_words() -> None:
    """Six words, restated in the gate and compared here.

    A restatement that nothing compares is a copy waiting to drift.
    """
    assert {item.value for item in SurfaceStatus} == STATUSES


def test_spot_is_documented_in_three_environments(registry: ApiRealitySnapshot) -> None:
    """Production, demo and testnet, each with its own semantics.

    ADR-0006 requires that the classes are never conflated. A registry recording one
    non-production environment would have conflated them by omission.
    """
    for name in ("production", "demo", "testnet"):
        found = registry.environment(SPOT, EnvironmentName(name))
        assert found is not None, name
        assert found.semantics


def test_demo_and_testnet_do_not_share_semantics(registry: ApiRealitySnapshot) -> None:
    """The venue tabulates the difference, so the registry may not flatten it."""
    demo = registry.environment(SPOT, EnvironmentName("demo"))
    testnet = registry.environment(SPOT, EnvironmentName("testnet"))
    assert demo is not None
    assert testnet is not None
    assert demo.semantics != testnet.semantics


def test_only_the_live_environment_is_unmarked(registry: ApiRealitySnapshot) -> None:
    """Every environment that risks no real capital declares how its hosts are spelled."""
    for record in registry.environments:
        assert record.carries_real_capital != bool(record.host_marker)


def test_fix_capabilities_are_not_inherited_by_other_products(
    registry: ApiRealitySnapshot,
) -> None:
    """One product documents FIX and the others do not say.

    The sharpest available case of the phase's central rule: a capability recorded
    against one product must never be copied to another. Anything other than unknown
    here would be a guess.
    """
    for family in ("usds_m_futures", "coin_m_futures", "options"):
        found = registry.surface(ProductFamily(family), ProtocolKind.FIX_ORDER_ENTRY)
        assert found is not None, family
        assert found.capability.status is SurfaceStatus.UNKNOWN


def test_spot_fix_is_restricted_and_names_its_condition(registry: ApiRealitySnapshot) -> None:
    """The one product that does document FIX documents a condition with it."""
    found = registry.surface(SPOT, ProtocolKind.FIX_ORDER_ENTRY)
    assert found is not None
    assert found.capability.status is SurfaceStatus.RESTRICTED
    assert found.capability.condition


def test_unknown_is_recorded_and_unsupported_is_not_guessed(
    registry: ApiRealitySnapshot,
) -> None:
    """The registry records unknowns and asserts no absences.

    Not a quality target -- it is the honest consequence of the venue publishing a
    machine-readable specification for one product family. An `unsupported` row
    would be a claim that the documents state an absence, and none of them does.
    """
    counts = registry.status_counts()
    assert counts["unknown"] > 0
    assert counts["unsupported"] == 0


def test_every_source_is_either_cited_or_watched(registry: ApiRealitySnapshot) -> None:
    """A source earns its place by supporting a claim or by being re-checkable.

    The first draft of this test required every source to be cited, and the registry
    failed it for five sources -- among them the venue's own changelog. That was the
    test being wrong rather than the registry: a changelog supports no single row and
    is exactly the document worth watching, because it is where a change is announced
    before anything else moves.

    What is not defensible is a source that is neither cited nor refreshable. That one
    supports nothing and cannot tell anybody when it changes, so it is a URL in a file.
    """
    cited = {item.capability.source for item in registry.products}
    cited |= {item.capability.source for item in registry.surfaces}
    cited |= {item.capability.source for item in registry.environments}
    cited |= {item.capability.source for item in registry.endpoints}
    cited |= {item.source for item in registry.schemas}
    idle = sorted(
        item.identifier
        for item in registry.sources
        if item.identifier not in cited and not item.refreshable
    )
    assert not idle, f"declared, uncited and unwatchable: {idle}"


def test_the_changelog_is_watched(registry: ApiRealitySnapshot) -> None:
    """The venue announces a change there before anything else moves.

    It supports no capability row, and a registry that only declared the documents it
    quoted would have no way to notice a change coming.
    """
    changelog = next(
        (item for item in registry.sources if "changelog" in item.location.lower()), None
    )
    assert changelog is not None
    assert changelog.refreshable
    assert changelog.digest


def test_the_unrefreshable_sources_are_named_rather_than_hidden(
    registry: ApiRealitySnapshot,
) -> None:
    """A source no refresh can re-check is recorded as such.

    Drift detection covers less than it appears to, and the count is published so
    that the limit is stated rather than discovered.
    """
    assert registry.unrefreshable_sources()


def test_the_registry_announces_the_schema_the_package_reads(repo_root: Path) -> None:
    """A document announcing another shape is refused rather than read anyway."""
    document = tomllib.loads((repo_root / REGISTRY_PATH).read_text(encoding="utf-8"))
    assert document["schema"] == 1
    assert document["target"]["phase"] == 33


DOCUMENT: Final[str] = "docs/engineering/BINANCE_API_REALITY.md"


@pytest.fixture(scope="module")
def guide(repo_root: Path) -> str:
    """The living document that describes the registry.

    Args:
        repo_root: The repository root.

    Returns:
        Its text.
    """
    return (repo_root / DOCUMENT).read_text(encoding="utf-8")


def test_the_guide_states_the_counts_the_registry_carries(
    guide: str, registry: ApiRealitySnapshot
) -> None:
    """Every number in the document's summary table is recomputed from the registry.

    The document hedges the table as a dated snapshot and points a reader at the
    command, which is honest but not sufficient: a restatement nothing compares is a
    copy waiting to drift, and this repository binds those rather than dating them.
    """
    rows = {
        "Product families": len(registry.products),
        "Product-and-protocol surfaces": len(registry.surfaces),
        "Product-and-environment pairs": len(registry.environments),
        "Schema versions": len(registry.schemas),
    }
    for label, count in rows.items():
        assert f"| {label} | {count} |" in guide, f"{DOCUMENT} misstates {label}"
    assert f"| Endpoints | {len(registry.endpoints)}, all Spot |" in guide
    assert f"| Sources | {len(registry.sources)}," in guide


def test_the_guide_states_how_many_sources_cannot_be_rechecked(
    guide: str, registry: ApiRealitySnapshot
) -> None:
    """The limit of drift detection is published, so it is stated rather than found."""
    found = len(registry.unrefreshable_sources())
    assert f"of which {found} cannot be re-checked at all" in guide


def test_the_guide_lists_every_verb_the_group_answers(guide: str) -> None:
    """A verb missing from the document is one nobody finds.

    Compared against the closed tuple in the CLI rather than a hand-written list, so
    an eighth verb cannot arrive undocumented.
    """
    from globin.runtime.cli import API_REALITY_SUBCOMMANDS

    for verb in API_REALITY_SUBCOMMANDS:
        assert f"`{verb}" in guide, f"{DOCUMENT} does not mention the {verb!r} verb"
    spelled = {3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight"}
    assert f"{spelled[len(API_REALITY_SUBCOMMANDS)]} read-only verbs" in guide


def test_the_guide_states_how_many_lifecycle_files_do_not_parse(
    guide: str, registry: ApiRealitySnapshot
) -> None:
    """A measured defect in the venue's own files, restated and therefore compared.

    If Binance repairs one, the gate fails on the recovered source and this fails on
    the count, so the document cannot go on describing a world that has moved.
    """
    structured = [item for item in registry.sources if item.regime is SourceRegime.STRUCTURED]
    broken = [item for item in structured if item.known_unparseable]
    spelled = {1: "one", 2: "two", 3: "three", 4: "four"}
    claim = (
        f"{spelled[len(broken)].capitalize()} of Binance's "
        f"{spelled[len(structured)]} lifecycle files are not valid JSON"
    )
    assert claim in guide, f"{DOCUMENT} does not state {claim!r}"
