"""Verify the 320-phase roadmap: its code skeleton and the Markdown document.

Two things are checked, and the distinction matters:

1. ``globin.roadmap`` holds the twenty immutable band boundaries fixed by the
   project charter. The expected bounds are repeated literally below so that
   editing the module alone cannot silently redefine the programme.
2. ``ROADMAP.md`` is parsed and checked *against* that skeleton. The document
   is never snapshotted; only its structural invariants are asserted.
"""

from pathlib import Path

import pytest

import globin
from globin.errors import ValidationError
from globin.project_contract import ROADMAP_TOTAL_PHASES
from globin.roadmap import PHASE_BAND_WIDTH, PHASE_BANDS, PhaseBand, band_for_phase
from tests.support import RoadmapRow

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
    with pytest.raises(ValidationError, match="phase must be in"):
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


#: The last phase that has actually been delivered — verified, committed and
#: pushed to ``origin/master``.
#:
#: This is a tripwire, and bumping it is meant to be a deliberate act. Marking a
#: phase ``Complete`` in ``ROADMAP.md`` is cheap; editing this constant forces
#: the claim to be made in code, in the same commit, where it is visible in the
#: diff. Raise it only when the phase genuinely satisfies
#: ``docs/engineering/DEFINITION_OF_DONE.md`` — never in advance, and never to
#: make a failing test pass.
LAST_COMPLETED_PHASE: int = 18


def test_no_future_phase_is_marked_complete(roadmap_rows: list[RoadmapRow]) -> None:
    """No phase beyond the delivered frontier may claim to be finished.

    Guards against the failure that matters most in a fixed programme: work
    described as done before it exists. Every later phase builds on the claim,
    so a false ``Complete`` is not a bookkeeping error — it silently invalidates
    everything that follows.
    """
    for row in roadmap_rows:
        if row.phase < LAST_COMPLETED_PHASE:
            assert row.status == "Complete", (
                f"phase {row.phase:03d} precedes the delivered frontier "
                f"({LAST_COMPLETED_PHASE:03d}) but is {row.status!r}"
            )
        elif row.phase == LAST_COMPLETED_PHASE:
            assert row.status in {"Active", "Complete"}, (
                f"phase {row.phase:03d} has unexpected status {row.status!r}"
            )
        else:
            assert row.status == "Planned", (
                f"phase {row.phase:03d} is beyond the delivered frontier "
                f"({LAST_COMPLETED_PHASE:03d}) and must be Planned, found {row.status!r}"
            )


def test_completed_frontier_is_within_the_programme() -> None:
    """A frontier outside 1..320 would silently disable the check above."""
    assert 1 <= LAST_COMPLETED_PHASE <= ROADMAP_TOTAL_PHASES


# --------------------------------------------------------------------------
# Everything that states the frontier in prose
#
# Four artefacts tell a reader how far the programme has got, and until Phase
# 007 only one of them was checked. A maturity claim that has drifted is the
# worst kind of stale documentation in this repository, because the whole point
# of `README.md`'s status section is that somebody can trust it without reading
# the code. Each is bound to `LAST_COMPLETED_PHASE`, which is itself the
# tripwire a phase must edit deliberately.
# --------------------------------------------------------------------------


def test_the_readme_states_the_delivered_frontier(repo_root: Path) -> None:
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    expected = f"Phase {LAST_COMPLETED_PHASE:03d} of {ROADMAP_TOTAL_PHASES} complete"
    assert expected in readme, f"README does not state {expected!r}"


def test_the_package_docstring_states_the_delivered_frontier() -> None:
    """The claim a reader meets first if they open the package rather than the.

    repository.
    """
    assert globin.__doc__ is not None
    expected = f"Phase {LAST_COMPLETED_PHASE} of {ROADMAP_TOTAL_PHASES}"
    assert expected in globin.__doc__, f"globin.__doc__ does not state {expected!r}"


def test_the_roadmap_banner_states_the_delivered_frontier(roadmap_text: str) -> None:
    """The banner is what stops a reader inferring maturity from the table."""
    for claim in (
        f"Phases 001-{LAST_COMPLETED_PHASE:03d} are complete",
        f"Phase {LAST_COMPLETED_PHASE + 1:03d} is next",
        f"Nothing beyond Phase {LAST_COMPLETED_PHASE:03d} is implemented",
    ):
        assert claim in roadmap_text, f"ROADMAP.md banner does not state {claim!r}"


def test_roadmap_statuses_are_from_the_known_vocabulary(roadmap_rows: list[RoadmapRow]) -> None:
    allowed = {"Planned", "Active", "Complete"}
    for row in roadmap_rows:
        assert row.status in allowed, f"phase {row.phase:03d} status {row.status!r} not allowed"
