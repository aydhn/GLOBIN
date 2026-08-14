"""Invariants of the roadmap band lookup, over every phase number rather than a few.

``tests/contract/test_roadmap_contract.py`` already restates the twenty band
boundaries literally and checks ``ROADMAP.md`` against them. That is the right
test for *those are the boundaries*. It is the wrong test for *the lookup
behaves correctly at all 320 inputs and refuses everything else*, which is what
these assert.

The two are complementary rather than redundant: the contract test would still
pass if :func:`~globin.roadmap.band_for_phase` were subtly wrong at a boundary,
and these would still pass if someone changed a band's title.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from globin.errors import ValidationError
from globin.project_contract import ROADMAP_TOTAL_PHASES
from globin.roadmap import PHASE_BAND_WIDTH, PHASE_BANDS, band_for_phase

#: Every phase number the programme defines.
phases = st.integers(min_value=1, max_value=ROADMAP_TOTAL_PHASES)

#: Everything else. Both sides of the range, and far enough out to catch a check
#: that only ever tested one direction.
non_phases = st.integers().filter(lambda value: not 1 <= value <= ROADMAP_TOTAL_PHASES)


@given(phase=phases)
def test_every_phase_in_the_programme_resolves_to_a_band(phase: int) -> None:
    """The lookup is total over its stated domain.

    A gap between two bands would be invisible to a spot check and fatal to the
    contract that every phase belongs somewhere.
    """
    band = band_for_phase(phase)

    assert band in PHASE_BANDS
    assert band.contains(phase)
    assert band.start <= phase <= band.end


@given(phase=non_phases)
def test_a_phase_outside_the_programme_is_refused(phase: int) -> None:
    """Out of range must raise, not return the nearest band.

    Returning something plausible is how an off-by-one in a caller becomes a
    silently wrong answer rather than a stack trace.
    """
    with pytest.raises(ValidationError, match="phase must be in") as refused:
        band_for_phase(phase)

    assert str(phase) in str(refused.value)


@given(phase=phases)
def test_the_band_holding_any_phase_is_a_full_band(phase: int) -> None:
    """Every band spans exactly ``PHASE_BAND_WIDTH`` phases, reached from any member."""
    band = band_for_phase(phase)

    assert band.width == PHASE_BAND_WIDTH
    assert band.end - band.start + 1 == PHASE_BAND_WIDTH


@given(earlier=phases, later=phases)
def test_band_order_follows_phase_order(earlier: int, later: int) -> None:
    """Bands are contiguous and ascending, so the lookup preserves ordering.

    This is what makes "which band is this phase in" answerable by comparing band
    starts, and it fails immediately if a band is ever reordered or overlapped.
    """
    if earlier > later:
        earlier, later = later, earlier

    assert band_for_phase(earlier).start <= band_for_phase(later).start


@given(
    phase=phases,
    offset=st.integers(min_value=-ROADMAP_TOTAL_PHASES, max_value=ROADMAP_TOTAL_PHASES),
)
def test_membership_agrees_with_the_band_bounds(phase: int, offset: int) -> None:
    """``contains`` must be exactly the bounds check, including at both edges.

    The chained comparison short-circuits, so the low and high arms are separate
    branches; an offset that ranges over the whole programme reaches both.
    """
    band = band_for_phase(phase)
    candidate = phase + offset

    assert band.contains(candidate) == (band.start <= candidate <= band.end)
