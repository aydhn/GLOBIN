"""Invariants of the registry that hold for every input rather than for an example.

Three genuine invariants live here. The diff is reflexive, so an empty result means
agreement rather than a comparison that did not run. It is total over status
transitions, so no pair of the six words falls through unclassified. And rendering a
snapshot is stable, which is what lets a digest over it mean anything.

The opt-in network check at the end is the first user of the door
``tests/conftest.py`` built for this band.
"""

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from globin.adapters.api_reality import REGISTRY_PATH, digest, parse_registry, summarise
from globin.domain.api_reality import (
    ApiRealitySnapshot,
    CapabilityRecord,
    EnvironmentName,
    EnvironmentRecord,
    EvidenceKind,
    ProductFamily,
    ProductProfile,
    ProductScope,
    SourceAuthority,
    SourceObservation,
    SourceRegime,
    SurfaceStatus,
    diff,
)

SLUGS = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=2, max_size=20)
STATUSES = st.sampled_from(list(SurfaceStatus))


def source() -> SourceObservation:
    """One valid source.

    Returns:
        The observation.
    """
    return SourceObservation(
        identifier="doc",
        title="A document",
        location="https://raw.githubusercontent.com/binance/x/master/a.md",
        authority=SourceAuthority.PRIMARY,
        accessed="2026-08-19",
        regime=SourceRegime.DIGEST,
    )


def with_product(family: str, status: SurfaceStatus) -> ApiRealitySnapshot:
    """One snapshot carrying a single product at one status.

    Args:
        family: The family slug.
        status: Its status.

    Returns:
        The snapshot.
    """
    condition = "a stated condition" if status is SurfaceStatus.RESTRICTED else ""
    return ApiRealitySnapshot(
        sources=(source(),),
        products=(
            ProductProfile(
                family=ProductFamily(family),
                scope=ProductScope.TRADING,
                title="A product",
                capability=CapabilityRecord(
                    status=status,
                    evidence=EvidenceKind.DOCUMENTED,
                    source="doc",
                    condition=condition,
                ),
            ),
        ),
        environments=(
            EnvironmentRecord(
                family=ProductFamily(family),
                environment=EnvironmentName("production"),
                semantics="The live exchange.",
                capability=CapabilityRecord(
                    status=SurfaceStatus.SUPPORTED,
                    evidence=EvidenceKind.DOCUMENTED,
                    source="doc",
                ),
                carries_real_capital=True,
            ),
        ),
    )


@given(family=SLUGS, status=STATUSES)
def test_a_snapshot_never_differs_from_itself(family: str, status: SurfaceStatus) -> None:
    """Reflexivity, over every family spelling and every status word.

    Without it an empty diff would mean only that the comparison found nothing it
    knew how to look at.
    """
    built = with_product(family, status)
    assert diff(built, built).empty


@given(family=SLUGS, before=STATUSES, after=STATUSES)
def test_every_status_transition_is_classified(
    family: str, before: SurfaceStatus, after: SurfaceStatus
) -> None:
    """Totality over the six words, which is thirty-six pairs.

    A transition that fell through would be a capability moving with nothing said
    about it, and the pair most likely to fall through is the one nobody thought of.
    """
    found = diff(with_product(family, before), with_product(family, after))
    if before is after:
        assert found.empty
    else:
        assert len(found.findings) == 1
        assert found.findings[0].before == before.value
        assert found.findings[0].after == after.value


@given(family=SLUGS, before=STATUSES, after=STATUSES)
def test_a_diff_is_never_bigger_than_the_change(
    family: str, before: SurfaceStatus, after: SurfaceStatus
) -> None:
    """One moved field produces at most one finding.

    A diff that reported the same move twice would inflate a count somebody reads as
    severity.
    """
    found = diff(with_product(family, before), with_product(family, after))
    assert len(found.findings) <= 1


@given(family=SLUGS, status=STATUSES)
def test_rendering_a_snapshot_is_stable(family: str, status: SurfaceStatus) -> None:
    """Two renderings of one snapshot agree, which is what a digest rests on."""
    built = with_product(family, status)
    assert built.as_record() == built.as_record()
    assert digest({"registry": built.as_record()}) == digest({"registry": built.as_record()})


@given(family=SLUGS, status=STATUSES)
def test_a_status_appears_in_the_counts_exactly_as_often_as_it_is_recorded(
    family: str, status: SurfaceStatus
) -> None:
    """The counts and the listing are two views of one fact and may not disagree."""
    built = with_product(family, status)
    counts = built.status_counts()
    for word in SurfaceStatus:
        assert counts[word.value] == len(built.capabilities_with_status(word))


def test_the_committed_registry_renders_identically_twice(repo_root: Path) -> None:
    """Determinism over the real document rather than a generated one.

    The generated cases above are small; this is the one that would actually be
    published, and a digest over an unstable rendering would be a name for nothing.
    """
    snapshot = parse_registry((repo_root / REGISTRY_PATH).read_text(encoding="utf-8"))
    first = json.dumps(summarise(snapshot), sort_keys=True)
    second = json.dumps(
        summarise(parse_registry((repo_root / REGISTRY_PATH).read_text(encoding="utf-8"))),
        sort_keys=True,
    )
    assert first == second


@pytest.mark.external
@pytest.mark.network
@pytest.mark.slow
def test_every_recorded_source_still_answers(repo_root: Path) -> None:
    """The registry's sources are reachable and unchanged, asked of the venue itself.

    Excluded from every quality command by its `external` marker, so this runs when
    somebody asks for it and at no other time. It is the first real user of the
    opt-out `tests/conftest.py` built for this band before anything needed it.

    Read-only, bounded, and needs no credential: these are public documents. It
    changes nothing in the repository -- the committed registry is not rewritten
    whatever the answer is.
    """
    from tools.quality.venue.gate import run_api_reality

    outcome = run_api_reality(root=repo_root, refresh=True)
    assert outcome.reached_network
    assert outcome.checked > 0
    assert not outcome.findings, [item.detail for item in outcome.findings]
