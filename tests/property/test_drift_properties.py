"""Invariants of comparing two observations, over generated input.

Four properties, and each is a claim the manifest's reproducibility rests on. A
comparison that is not order-independent produces a document that differs between
two runs of an unchanged host, which would fail the gate's own determinism check
for a reason having nothing to do with the host.

These are real invariants rather than a slow unit test dressed up: the input is a
mapping of arbitrary keys to arbitrary values, and the claims hold for all of
them.
"""

from hypothesis import given
from hypothesis import strategies as st

from tools.quality.drift import plan

KEYS = st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=6)
"""Short lower-case names. The keys' spelling is irrelevant; their identity is not."""

VALUES = st.text(
    alphabet=st.characters(min_codepoint=48, max_codepoint=122), min_size=0, max_size=6
)
"""Short text values, including the empty string, which is what an absent key reads as."""

OBSERVATIONS = st.dictionaries(KEYS, VALUES, max_size=8)
"""A flat observation, of the shape :func:`tools.quality.drift.plan.compare` takes."""


@given(observation=OBSERVATIONS)
def test_an_observation_never_drifts_from_itself(observation: dict[str, str]) -> None:
    """The identity property.

    A comparison failing this would report drift on a machine nobody touched, which
    is the single fastest way to have a gate switched off. It also catches the
    likelier defect: a comparison reading a field the baseline does not record.
    """
    assert plan.compare(observation, observation) == ()


@given(baseline=OBSERVATIONS, current=OBSERVATIONS)
def test_a_comparison_does_not_depend_on_the_order_either_side_was_built_in(
    baseline: dict[str, str], current: dict[str, str]
) -> None:
    """Determinism, at its source.

    The manifest is rendered with sorted keys, but the *differences* are a list,
    and a list whose order followed insertion would render two ways for one host.
    """
    reversed_baseline = dict(reversed(list(baseline.items())))
    reversed_current = dict(reversed(list(current.items())))
    assert plan.compare(baseline, current) == plan.compare(reversed_baseline, reversed_current)


@given(baseline=OBSERVATIONS, current=OBSERVATIONS)
def test_a_comparison_is_reported_in_sorted_key_order(
    baseline: dict[str, str], current: dict[str, str]
) -> None:
    """What makes the previous property hold, asserted directly rather than inferred."""
    keys = [difference.key for difference in plan.compare(baseline, current)]
    assert keys == sorted(keys)


@given(baseline=OBSERVATIONS, current=OBSERVATIONS)
def test_every_reported_difference_really_differs(
    baseline: dict[str, str], current: dict[str, str]
) -> None:
    """Soundness. A key reported as drifted whose two sides are equal is noise.

    The pairing with the identity property above is the point: one says nothing is
    reported that did not change, the other says nothing is reported at all when
    nothing changed. Neither alone rules out a comparison that reports everything.
    """
    for difference in plan.compare(baseline, current):
        assert difference.before != difference.after


@given(baseline=OBSERVATIONS, current=OBSERVATIONS)
def test_every_key_that_differs_is_reported(
    baseline: dict[str, str], current: dict[str, str]
) -> None:
    """Completeness, the other direction.

    Without this a comparison that returned nothing at all would satisfy every
    property above it.
    """
    expected = {
        key
        for key in set(baseline) | set(current)
        if baseline.get(key, plan.ABSENT) != current.get(key, plan.ABSENT)
    }
    assert {difference.key for difference in plan.compare(baseline, current)} == expected


@given(observation=st.dictionaries(KEYS, VALUES, max_size=6))
def test_flattening_an_already_flat_observation_changes_nothing(
    observation: dict[str, str],
) -> None:
    """Idempotence. A value that is text stays that text, whatever else is around it."""
    assert plan.flatten(observation) == observation
