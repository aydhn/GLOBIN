"""Verify the 320-phase roadmap: its code skeleton and the Markdown document.

Two things are checked, and the distinction matters:

1. ``globin.roadmap`` holds the twenty immutable band boundaries fixed by the
   project charter. The expected bounds are repeated literally below so that
   editing the module alone cannot silently redefine the programme.
2. ``ROADMAP.md`` is parsed and checked *against* that skeleton. The document
   is never snapshotted; only its structural invariants are asserted.
"""

import pytest

from conftest import RoadmapRow
from globin.project_contract import ROADMAP_TOTAL_PHASES
from globin.roadmap import PHASE_BAND_WIDTH, PHASE_BANDS, PhaseBand, band_for_phase

#: The immutable band boundaries from the project charter, restated literally.
#: This is duplication on purpose — it is the tripwire.
EXPECTED_BAND_BOUNDS: tuple[tuple[int, int], ...] = (
    (1, 16),
    (17, 32),
    (33, 48),
    (49, 64),
    (65, 80),
    (81, 96),
    (97, 112),
    (113, 128),
    (129, 144),
    (145, 160),
    (161, 176),
    (177, 192),
    (193, 208),
    (209, 224),
    (225, 240),
    (241, 256),
    (257, 272),
    (273, 288),
    (289, 304),
    (305, 320),
)


# --------------------------------------------------------------------------
# Band skeleton (code)
# --------------------------------------------------------------------------


def test_there_are_twenty_bands() -> None:
    assert len(PHASE_BANDS) == len(EXPECTED_BAND_BOUNDS) == 20


def test_band_bounds_match_the_charter() -> None:
    actual = tuple((band.start, band.end) for band in PHASE_BANDS)
    assert actual == EXPECTED_BAND_BOUNDS


def test_every_band_is_sixteen_phases_wide() -> None:
    for band in PHASE_BANDS:
        assert band.width == PHASE_BAND_WIDTH, f"{band.title} spans {band.width} phases"


def test_bands_are_contiguous_and_cover_every_phase_exactly_once() -> None:
    covered: list[int] = []
    for band in PHASE_BANDS:
        covered.extend(range(band.start, band.end + 1))
    assert covered == list(range(1, ROADMAP_TOTAL_PHASES + 1))


def test_band_titles_are_unique() -> None:
    titles = [band.title for band in PHASE_BANDS]
    assert len(set(titles)) == len(titles)


def test_band_for_phase_resolves_every_phase() -> None:
    for phase in range(1, ROADMAP_TOTAL_PHASES + 1):
        band: PhaseBand = band_for_phase(phase)
        assert band.contains(phase)


@pytest.mark.parametrize("phase", [0, -1, ROADMAP_TOTAL_PHASES + 1, 1000])
def test_band_for_phase_rejects_out_of_range(phase: int) -> None:
    with pytest.raises(ValueError, match="phase must be in"):
        band_for_phase(phase)


# --------------------------------------------------------------------------
# ROADMAP.md (document, checked against the skeleton)
# --------------------------------------------------------------------------


def test_roadmap_lists_every_phase_exactly_once(roadmap_rows: list[RoadmapRow]) -> None:
    phases = [row.phase for row in roadmap_rows]
    expected = list(range(1, ROADMAP_TOTAL_PHASES + 1))
    missing = sorted(set(expected) - set(phases))
    duplicated = sorted({p for p in phases if phases.count(p) > 1})
    assert not missing, f"ROADMAP.md is missing phases: {missing}"
    assert not duplicated, f"ROADMAP.md duplicates phases: {duplicated}"
    assert phases == expected, "ROADMAP.md phases must appear in ascending order"


def test_every_roadmap_phase_has_a_unique_title(roadmap_rows: list[RoadmapRow]) -> None:
    titles = [row.title for row in roadmap_rows]
    duplicates = sorted({t for t in titles if titles.count(t) > 1})
    assert not duplicates, f"duplicate phase titles: {duplicates}"


def test_every_roadmap_phase_has_a_title_and_a_purpose(roadmap_rows: list[RoadmapRow]) -> None:
    for row in roadmap_rows:
        assert row.title, f"phase {row.phase:03d} has no title"
        assert row.purpose, f"phase {row.phase:03d} has no purpose"
        assert len(row.purpose) >= 20, (
            f"phase {row.phase:03d} purpose is too thin to be meaningful: {row.purpose!r}"
        )


def test_roadmap_band_headings_match_the_code_skeleton(roadmap_text: str) -> None:
    """Every band must appear as a heading naming its exact range and title."""
    for band in PHASE_BANDS:
        heading = f"## Phases {band.start:03d}-{band.end:03d} — {band.title}"
        assert heading in roadmap_text, f"missing or altered band heading: {heading!r}"


def test_no_future_phase_is_marked_complete(roadmap_rows: list[RoadmapRow]) -> None:
    """Only Phase 1 may ever be Active or Complete at this point in the programme."""
    for row in roadmap_rows:
        if row.phase == 1:
            assert row.status in {"Active", "Complete"}, (
                f"phase 001 has unexpected status {row.status!r}"
            )
        else:
            assert row.status == "Planned", (
                f"phase {row.phase:03d} must be Planned, found {row.status!r}"
            )


def test_roadmap_statuses_are_from_the_known_vocabulary(roadmap_rows: list[RoadmapRow]) -> None:
    allowed = {"Planned", "Active", "Complete"}
    for row in roadmap_rows:
        assert row.status in allowed, f"phase {row.phase:03d} status {row.status!r} not allowed"
