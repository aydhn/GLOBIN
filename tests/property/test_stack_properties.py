"""Invariants of the stack judgements, over generated input.

A real invariant, not a restatement of the implementation. Each of these is a
property somebody could reasonably assume when reading the gate, and each would be
broken by a plausible refactor: an `any()` that should have been an `all()`, a
comparison that fell back to string ordering, a digest that stopped covering a
field.
"""

from hypothesis import given
from hypothesis import strategies as st

from tools.quality.stack.manifest import DIGEST_KEY, build, digest, render
from tools.quality.stack.plan import (
    Declaration,
    Deferral,
    Library,
    ProbeSpec,
    Target,
    binary64_problems,
    deferral_problems,
    registry_problems,
    version_problems,
)
from tools.quality.stack.probes import wheel_tag_of

VERSIONS = st.builds(
    lambda major, minor, patch: f"{major}.{minor}.{patch}",
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=0, max_value=99),
)

IDENTIFIERS = st.text(alphabet="abcdefghijklmnopqrstuvwxyz._", min_size=1, max_size=24)

PHASES = st.integers(min_value=1, max_value=400)


def a_library(version: str) -> Library:
    """A declared library at a given version."""
    return Library(
        name="numpy",
        import_name="numpy",
        version=version,
        wheel_tag="cp314-cp314-win_amd64",
        role="the numerical half",
        probes=("numpy.float64_is_binary64",),
    )


@given(
    mantissa=st.integers(min_value=0, max_value=112),
    bits=st.integers(min_value=8, max_value=128),
    item_bytes=st.integers(min_value=1, max_value=16),
)
def test_binary64_is_accepted_only_when_every_measurement_matches(
    mantissa: int, bits: int, item_bytes: int
) -> None:
    """The `all` that must not become an `any`.

    A float type is binary64 only if all four measurements agree. A checker that
    accepted three out of four would pass a `float32` build carrying one
    coincidental value.
    """
    problems = binary64_problems(
        mantissa_bits=mantissa, epsilon=2.0**-52, bits=bits, item_bytes=item_bytes
    )
    correct = mantissa == 52 and bits == 64 and item_bytes == 8
    assert (problems == ()) is correct


@given(mantissa=st.integers(min_value=0, max_value=112), bits=st.integers(8, 128))
def test_every_disagreement_is_reported_rather_than_only_the_first(
    mantissa: int, bits: int
) -> None:
    """An operator handed one problem at a time fixes one and rediscovers the next."""
    problems = binary64_problems(mantissa_bits=mantissa, epsilon=2.0**-52, bits=bits, item_bytes=8)
    expected = (mantissa != 52) + (bits != 64)
    assert len(problems) == expected


@given(declared=VERSIONS, locked=VERSIONS, installed=VERSIONS)
def test_versions_pass_only_when_all_three_registers_are_identical(
    declared: str, locked: str, installed: str
) -> None:
    """The four-way comparison, with the bound held satisfied.

    Any disagreement at all must be a problem. A comparison that normalised the
    versions before comparing would let `2.5.2` and `2.05.2` agree, which are
    different distributions on an index.
    """
    problems = version_problems(
        a_library(declared), installed=installed, locked=locked, bound=">=0.0.0"
    )
    assert (problems == ()) is (declared == locked == installed)


@given(declared=VERSIONS, floor=VERSIONS)
def test_a_declared_version_passes_its_bound_exactly_when_it_is_not_below_it(
    declared: str, floor: str
) -> None:
    """Ordering is numeric per component, never lexicographic.

    `"2.10.0" < "2.9.0"` is true as strings and false as versions, which is the
    class of bug this pins.
    """
    problems = version_problems(
        a_library(declared), installed=declared, locked=declared, bound=f">={floor}"
    )
    numeric = tuple(int(part) for part in declared.split("."))
    expected = numeric >= tuple(int(part) for part in floor.split("."))
    assert (problems == ()) is expected


@given(declared=st.sets(IDENTIFIERS, max_size=6), implemented=st.sets(IDENTIFIERS, max_size=6))
def test_a_registry_agrees_exactly_when_the_two_sets_are_equal(
    declared: set[str], implemented: set[str]
) -> None:
    """Both directions, always. A one-way check would let orphan probes accumulate."""
    declaration = Declaration(
        target=Target(implementation="CPython", minor_line="3.14", architecture="AMD64"),
        libraries=(),
        probes=tuple(ProbeSpec(identifier=name, because="because") for name in sorted(declared)),
        deferrals=(),
    )
    problems = registry_problems(declaration, frozenset(implemented))
    assert (problems == ()) is (declared == implemented)


@given(phases=st.lists(PHASES, max_size=6), delivered=PHASES)
def test_a_deferral_passes_exactly_when_its_phase_can_still_answer_it(
    phases: list[int], delivered: int
) -> None:
    """Strictly after the frontier, and inside the programme."""
    deferrals = [Deferral(question=f"q{index}", phase=phase) for index, phase in enumerate(phases)]
    problems = deferral_problems(deferrals, delivered=delivered, total=320)
    expected = all(delivered < phase <= 320 for phase in phases)
    assert (problems == ()) is expected


@given(text=st.text(max_size=200))
def test_a_wheel_tag_is_never_read_back_as_an_empty_string(text: str) -> None:
    """`None` and `""` mean different things to `provenance_problems`.

    One is "this artefact records no wheel", which a source install legitimately
    does; the other would be a tag that matches nothing and reads as a divergence.
    """
    assert wheel_tag_of(text) != ""


@given(
    commit=st.text(alphabet="0123456789abcdef", min_size=40, max_size=40),
    reasons=st.lists(st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ_", min_size=1), max_size=4),
)
def test_a_manifest_always_verifies_against_its_own_digest(commit: str, reasons: list[str]) -> None:
    """Whatever it carries, a freshly built manifest agrees with itself."""
    document = build(
        run={"commit": commit},
        findings={"target": {"verdict": "passed", "problems": []}},
        verdict={"verdict": "passed", "reasons": sorted(reasons)},
    )
    without = {key: value for key, value in document.items() if key != DIGEST_KEY}
    assert document[DIGEST_KEY] == digest(without)


@given(
    first=st.text(alphabet="0123456789abcdef", min_size=40, max_size=40),
    second=st.text(alphabet="0123456789abcdef", min_size=40, max_size=40),
)
def test_two_manifests_share_a_digest_only_when_they_share_their_content(
    first: str, second: str
) -> None:
    """A digest that ignored a section would make the evidence unverifiable."""
    findings: dict[str, object] = {"target": {"verdict": "passed", "problems": []}}
    verdict: dict[str, object] = {"verdict": "passed", "reasons": []}
    left = build(run={"commit": first}, findings=findings, verdict=verdict)
    right = build(run={"commit": second}, findings=findings, verdict=verdict)
    assert (left[DIGEST_KEY] == right[DIGEST_KEY]) is (first == second)


@given(commit=st.text(alphabet="0123456789abcdef", min_size=40, max_size=40))
def test_a_manifest_renders_to_one_ascii_line_whatever_it_carries(commit: str) -> None:
    """The property every gate's evidence shares, so one reader handles them all."""
    rendered = render(
        build(
            run={"commit": commit},
            findings={"target": {"verdict": "passed", "problems": []}},
            verdict={"verdict": "passed", "reasons": []},
        )
    )
    assert rendered.isascii()
    assert rendered.count("\n") == 1
    assert rendered.endswith("\n")
