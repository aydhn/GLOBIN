"""Invariants of the wheel-tag judgements, over generated input.

Three of these are the reason this file exists rather than more examples.

**A free-threaded ABI never satisfies a default build, and the reverse.** The
example tests check the pairings somebody thought of. The property checks the
shape of the answer for any pairing at all, which is the right strength for a rule
whose failure mode is reporting the stack ready for a change it is not ready for —
the exact claim ADR-0050 declined to make without evidence.

**A platform the target is not is never installable.** Same argument, for the rule
that stops a Linux wheel from being counted as Windows coverage.

**Deciding a version bound never returns an answer it cannot justify.** ``admits``
either decides or raises; there is no third outcome where it guesses. A property
is how that is checked against operators and bounds nobody enumerated.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tools.quality.wheels import plan

MINORS = st.integers(min_value=6, max_value=30)
"""Interpreter minor versions, spanning well below and well above the pinned line."""

PLATFORMS = st.sampled_from(["win_amd64", "win32", "manylinux1_x86_64", "macosx_11_0_arm64"])

DISTRIBUTIONS = st.sampled_from(["torch", "numpy", "optuna", "ta_lib", "thing"])

VERSIONS = st.sampled_from(["1.0", "2.13.0", "0.7.1", "4.9.0"])


def target_for(minor: int, *, free_threaded: bool) -> plan.Target:
    """A target on the given minor line."""
    return plan.Target(
        implementation="CPython",
        minor_line=f"3.{minor}",
        architecture="AMD64",
        platform_tag="win_amd64",
        free_threaded=free_threaded,
        index="https://pypi.org/pypi/",
        surveyed="2026-08-16",
    )


@st.composite
def wheel_filenames(draw: st.DrawFn) -> str:
    """A syntactically valid wheel filename, over the tags this survey meets."""
    distribution = draw(DISTRIBUTIONS)
    version = draw(VERSIONS)
    minor = draw(MINORS)
    python_tag = draw(st.sampled_from([f"cp3{minor}", f"py3{minor}", "py3", "py2.py3"]))
    abi_tag = draw(st.sampled_from([f"cp3{minor}", f"cp3{minor}t", "abi3", "none"]))
    platform_tag = draw(PLATFORMS)
    return f"{distribution}-{version}-{python_tag}-{abi_tag}-{platform_tag}.whl"


targets = st.builds(target_for, MINORS, free_threaded=st.booleans())


# ---------------------------------------------------------------------------
# The matcher is total
# ---------------------------------------------------------------------------


@given(filename=wheel_filenames(), target=targets)
def test_deciding_a_well_formed_wheel_never_raises(filename: str, target: plan.Target) -> None:
    """A judgement returns an answer.

    A matcher that raised on an unfamiliar tag would turn one odd wheel on the
    index into a gate that cannot run at all.
    """
    assert plan.satisfies(plan.parse_wheel_filename(filename), target) in (True, False)


@given(filename=wheel_filenames())
def test_parsing_recovers_the_tags_the_filename_was_built_from(filename: str) -> None:
    wheel = plan.parse_wheel_filename(filename)
    rebuilt = "-".join(
        (
            wheel.distribution,
            wheel.version,
            ".".join(wheel.python_tags),
            ".".join(wheel.abi_tags),
            ".".join(wheel.platform_tags),
        )
    )
    assert f"{rebuilt}.whl" == filename


# ---------------------------------------------------------------------------
# The free-threaded boundary
# ---------------------------------------------------------------------------


@given(minor=MINORS, free_threaded=st.booleans(), platform=PLATFORMS)
def test_a_free_threaded_abi_serves_only_a_free_threaded_build(
    minor: int, free_threaded: bool, platform: str
) -> None:
    """The two ABIs never substitute for each other, in either direction.

    Getting this wrong in one direction understates coverage; getting it wrong in
    the other reports the stack ready for a build it cannot run on.
    """
    target = target_for(minor, free_threaded=free_threaded)
    threaded = plan.parse_wheel_filename(f"thing-1.0-cp3{minor}-cp3{minor}t-{platform}.whl")
    default = plan.parse_wheel_filename(f"thing-1.0-cp3{minor}-cp3{minor}-{platform}.whl")
    usable = platform in {"win_amd64", "any"}
    assert plan.satisfies(threaded, target) == (free_threaded and usable)
    assert plan.satisfies(default, target) == (not free_threaded and usable)


@given(minor=MINORS)
def test_the_stable_abi_is_not_a_route_onto_a_free_threaded_build(minor: int) -> None:
    """A free-threaded build does not offer the limited API.

    Counting an ``abi3`` wheel as coverage would quietly shrink the list of
    blockers that ADR-0050's refusal rests on.
    """
    wheel = plan.parse_wheel_filename(f"thing-1.0-cp3{minor}-abi3-win_amd64.whl")
    assert plan.satisfies(wheel, target_for(minor, free_threaded=False))
    assert not plan.satisfies(wheel, target_for(minor, free_threaded=True))


# ---------------------------------------------------------------------------
# Platform and interpreter bounds
# ---------------------------------------------------------------------------


FOREIGN_PLATFORMS = st.sampled_from(["win32", "manylinux1_x86_64", "macosx_11_0_arm64"])


@given(target=targets, platform=FOREIGN_PLATFORMS)
def test_a_wheel_for_another_platform_is_never_installable(
    target: plan.Target, platform: str
) -> None:
    filename = f"thing-1.0-py3-none-{platform}.whl"
    assert not plan.satisfies(plan.parse_wheel_filename(filename), target)


@given(target=targets)
def test_a_pure_python_wheel_serves_every_cpython_target(target: plan.Target) -> None:
    """``py3-none-any`` binds to no ABI and no platform.

    Every pure-Python entry in the survey rests on this, including the whole
    Binance SDK family.
    """
    assert plan.satisfies(plan.parse_wheel_filename("thing-1.0-py3-none-any.whl"), target)


@given(minor=MINORS, offset=st.integers(min_value=1, max_value=8))
def test_an_abi_bound_wheel_for_a_later_interpreter_is_never_installable(
    minor: int, offset: int
) -> None:
    later = minor + offset
    wheel = plan.parse_wheel_filename(f"thing-1.0-cp3{later}-cp3{later}-win_amd64.whl")
    assert not plan.satisfies(wheel, target_for(minor, free_threaded=False))


@given(minor=MINORS, offset=st.integers(min_value=1, max_value=8))
def test_an_abi_free_wheel_for_an_earlier_interpreter_is_always_installable(
    minor: int, offset: int
) -> None:
    """The asymmetry that a substring match cannot express.

    Binding to no ABI makes an older interpreter tag forward-compatible; binding
    to one does not.
    """
    earlier = max(0, minor - offset)
    wheel = plan.parse_wheel_filename(f"thing-1.0-cp3{earlier}-none-any.whl")
    assert plan.satisfies(wheel, target_for(minor, free_threaded=False))


# ---------------------------------------------------------------------------
# Version bounds decide or refuse; they never guess
# ---------------------------------------------------------------------------


@given(minor=MINORS, bound=MINORS, operator=st.sampled_from(sorted(plan.SUPPORTED_OPERATORS)))
def test_a_supported_bound_on_another_line_is_always_decided(
    minor: int, bound: int, operator: str
) -> None:
    target = target_for(minor, free_threaded=False)
    assert plan.admits(f"{operator}3.{bound}", target) in (True, False)


@given(minor=MINORS, lower=MINORS, upper=MINORS)
def test_a_range_admits_exactly_the_lines_inside_it(minor: int, lower: int, upper: int) -> None:
    """The shape every ``binance-sdk-*`` distribution publishes: a floor and a cap."""
    target = target_for(minor, free_threaded=False)
    assert plan.admits(f">=3.{lower},<3.{upper}", target) == (lower <= minor < upper)


@given(minor=MINORS, operator=st.sampled_from(["==", "!=", "~=", "==="]))
def test_an_operator_outside_the_supported_set_always_refuses(minor: int, operator: str) -> None:
    """On ambiguity, refuse.

    An operator this module cannot decide against a minor line must never return
    an answer, because the wrong answer here is indistinguishable from the right
    one until a release nobody is watching.
    """
    target = target_for(minor, free_threaded=False)
    try:
        plan.admits(f"{operator}3.{minor}", target)
    except plan.WheelSurveyError:
        return
    pytest.fail(f"{operator!r} was decided rather than refused")


@given(minor=MINORS, specifier=st.text(max_size=8))
def test_deciding_a_bound_is_never_silently_wrong(minor: int, specifier: str) -> None:
    """Arbitrary text either parses as a bound or raises. There is no third outcome."""
    target = target_for(minor, free_threaded=False)
    try:
        result = plan.admits(specifier, target)
    except plan.WheelSurveyError:
        return
    assert result in (True, False)
