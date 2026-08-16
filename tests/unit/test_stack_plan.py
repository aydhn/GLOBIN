"""The scientific-stack judgements, exercised from literals.

Nothing here imports `numpy` or `pandas`, and that is the design being tested as
much as the code: every probe's *expectation* is a pure function, so a host where
`float64` is not binary64 can be described without owning one. A test that had to
break a library to prove a broken library is refused could not exist, and the
split between `plan` and `probes` is what removes the need for it.

Each checker is exercised by something it must catch and something it must not,
as `docs/TESTING_STRATEGY.md` requires. The second half matters more here: a
version comparison that rejected the correct version would fail the gate on a
correct machine, which is the expensive direction.
"""

import pytest

from tools.quality.stack.plan import (
    CONFIGURATION_FILE,
    Declaration,
    Deferral,
    Library,
    ProbeSpec,
    StackError,
    Target,
    binary64_problems,
    copy_on_write_problems,
    coverage_problems,
    deferral_problems,
    duplicate_libraries,
    identity_problems,
    implemented_probes,
    missing_value_problems,
    nan_infinity_problems,
    overflow_problems,
    parse_declaration,
    provenance_problems,
    registry_problems,
    round_trip_problems,
    target_problems,
    timestamp_problems,
    version_problems,
)

CORRECT_BINARY64: dict[str, object] = {
    "mantissa_bits": 52,
    "epsilon": 2.0**-52,
    "bits": 64,
    "item_bytes": 8,
}


def library(**overrides: object) -> Library:
    """A declared library, with the repository's real values as the default."""
    fields: dict[str, object] = {
        "name": "numpy",
        "import_name": "numpy",
        "version": "2.5.2",
        "wheel_tag": "cp314-cp314-win_amd64",
        "role": "the numerical half",
        "probes": ("numpy.float64_is_binary64",),
    }
    fields.update(overrides)
    return Library(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The probe expectations
# ---------------------------------------------------------------------------


def test_a_correct_binary64_is_accepted() -> None:
    """The expensive direction: rejecting a correct host fails a correct machine."""
    assert binary64_problems(**CORRECT_BINARY64) == ()  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        pytest.param("mantissa_bits", 23, "mantissa bits", id="a float32 mantissa"),
        pytest.param("epsilon", 1.1920929e-07, "epsilon", id="a float32 epsilon"),
        pytest.param("bits", 32, "32-bit", id="a narrow type"),
        pytest.param("item_bytes", 4, "4 bytes", id="a small item"),
    ],
)
def test_a_type_that_is_not_binary64_is_named_field_by_field(
    field: str, value: object, expected: str
) -> None:
    """Each disagreement is reported separately.

    A single "float64 is wrong" would leave an operator with nowhere to start;
    naming the field is what makes the finding actionable.
    """
    measurements = dict(CORRECT_BINARY64)
    measurements[field] = value
    problems = binary64_problems(**measurements)  # type: ignore[arg-type]
    assert len(problems) == 1
    assert expected in problems[0]


def test_the_epsilon_comparison_is_exact() -> None:
    """`FLOAT64_EPSILON` is written as a power of two so this can be exact.

    The decimal spelling `2.220446049250313e-16` round-trips today. Comparing
    against the power of two removes any dependence on that continuing to be true
    of this file's literal.
    """
    measurements = dict(CORRECT_BINARY64)
    measurements["epsilon"] = 2.0**-52 * (1 + 2.0**-52)
    assert binary64_problems(**measurements)  # type: ignore[arg-type]


def test_propagating_non_finite_results_are_accepted() -> None:
    assert (
        nan_infinity_problems(
            infinity_is_infinite=True, zero_over_zero_is_nan=True, nan_differs_from_itself=True
        )
        == ()
    )


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        pytest.param("infinity_is_infinite", "infinity", id="division by zero was substituted"),
        pytest.param("zero_over_zero_is_nan", "not-a-number", id="zero over zero was substituted"),
        pytest.param("nan_differs_from_itself", "IEEE-754", id="nan compared equal to itself"),
    ],
)
def test_a_substituted_non_finite_result_is_refused(field: str, expected: str) -> None:
    """A finite substitute is worse than an exception: it is a plausible number."""
    measurements = {
        "infinity_is_infinite": True,
        "zero_over_zero_is_nan": True,
        "nan_differs_from_itself": True,
        field: False,
    }
    problems = nan_infinity_problems(**measurements)
    assert len(problems) == 1
    assert expected in problems[0]


def test_an_overflow_that_wraps_and_warns_is_accepted() -> None:
    assert overflow_problems(wrapped_to=-(2**63), warned=True) == ()


def test_a_silent_overflow_is_refused_even_when_it_wrapped_correctly() -> None:
    """Wrapping is permitted; silence is not.

    This is the row that would be easiest to drop, and it is the one that matters:
    a wrap nothing reports cannot be told from a correct result.
    """
    problems = overflow_problems(wrapped_to=-(2**63), warned=False)
    assert len(problems) == 1
    assert "silent" in problems[0]


def test_an_overflow_that_produced_the_wrong_value_is_refused() -> None:
    problems = overflow_problems(wrapped_to=2**63, warned=True)
    assert len(problems) == 1
    assert "two's-complement" in problems[0]


def test_a_bit_exact_round_trip_in_the_right_dtype_is_accepted() -> None:
    assert round_trip_problems(bit_exact=True, dtype="float64") == ()


@pytest.mark.parametrize(
    ("bit_exact", "dtype", "expected"),
    [
        pytest.param(False, "float64", "bit-identical", id="values changed"),
        pytest.param(True, "float32", "float32", id="the dtype was narrowed"),
        pytest.param(True, "object", "object", id="the dtype became object"),
    ],
)
def test_a_round_trip_that_altered_the_column_is_refused(
    bit_exact: bool, dtype: str, expected: str
) -> None:
    problems = round_trip_problems(bit_exact=bit_exact, dtype=dtype)
    assert len(problems) == 1
    assert expected in problems[0]


def test_a_missing_value_that_stayed_missing_is_accepted() -> None:
    assert missing_value_problems(missing_positions=[1], dtype="float64") == ()


def test_a_missing_value_that_became_a_number_is_refused() -> None:
    """The quiet corruption this probe exists for.

    A missing value read back as `0.0` leaves no missing positions at all, and
    `0.0` is a plausible measurement in the right dtype. Nothing downstream could
    tell the two apart, which is why an empty position list is a failure rather
    than a pass.
    """
    problems = missing_value_problems(missing_positions=[], dtype="float64")
    assert len(problems) == 1
    assert "()" in problems[0]


def test_a_utc_timestamp_that_survived_is_accepted() -> None:
    assert timestamp_problems(timezone_name="UTC", instant_preserved=True, is_utc=True) == ()


@pytest.mark.parametrize(
    ("zone", "preserved", "utc", "expected"),
    [
        pytest.param("", True, True, "timezone", id="the timezone was dropped"),
        pytest.param("Europe/Istanbul", True, True, "Europe/Istanbul", id="it was converted"),
        pytest.param("UTC", False, True, "compare equal", id="the instant moved"),
        pytest.param("UTC", True, False, "TIME_POLICY", id="the value came back naive"),
    ],
)
def test_a_timestamp_that_lost_something_is_refused(
    zone: str, preserved: bool, utc: bool, expected: str
) -> None:
    problems = timestamp_problems(timezone_name=zone, instant_preserved=preserved, is_utc=utc)
    assert len(problems) == 1
    assert expected in problems[0]


def test_copy_on_write_is_judged_on_the_parent_alone() -> None:
    assert copy_on_write_problems(parent_unchanged=True) == ()
    assert copy_on_write_problems(parent_unchanged=False) == (
        "mutating a derived Series wrote through to its parent frame",
    )


# ---------------------------------------------------------------------------
# The structural judgements
# ---------------------------------------------------------------------------


def test_a_target_matching_the_runtime_contract_is_accepted() -> None:
    target = Target(implementation="CPython", minor_line="3.14", architecture="AMD64")
    assert (
        target_problems(target, implementation="CPython", minor_line="3.14", architecture="AMD64")
        == ()
    )


def test_the_target_comparison_ignores_casing_it_cannot_mean() -> None:
    """`platform` says `CPython` and `AMD64`; a contract may reasonably say either.

    A casing difference is not a divergence anybody intends, and failing on one
    would make the gate red for a reason no operator could act on.
    """
    target = Target(implementation="cpython", minor_line="3.14", architecture="amd64")
    assert (
        target_problems(target, implementation="CPython", minor_line="3.14", architecture="AMD64")
        == ()
    )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        pytest.param("implementation", "PyPy", "PyPy", id="another implementation"),
        pytest.param("minor_line", "3.13", "3.13", id="another minor line"),
        pytest.param("architecture", "ARM64", "ARM64", id="another architecture"),
    ],
)
def test_a_target_the_runtime_contract_does_not_declare_is_refused(
    field: str, value: str, expected: str
) -> None:
    """A stack verified on one interpreter says nothing about another."""
    fields = {"implementation": "CPython", "minor_line": "3.14", "architecture": "AMD64"}
    fields[field] = value
    problems = target_problems(
        Target(**fields), implementation="CPython", minor_line="3.14", architecture="AMD64"
    )
    assert len(problems) == 1
    assert expected in problems[0]


def test_a_library_declared_twice_is_reported_once() -> None:
    assert duplicate_libraries([library(), library(), library(name="pandas")]) == ("numpy",)


def test_distinct_libraries_are_spared() -> None:
    assert duplicate_libraries([library(), library(name="pandas")]) == ()


def test_a_library_with_no_probe_is_a_dependency_wearing_a_contracts_clothes() -> None:
    problems = coverage_problems([library(probes=())])
    assert len(problems) == 1
    assert "declares no probe" in problems[0]


def test_a_library_with_a_probe_is_spared() -> None:
    assert coverage_problems([library()]) == ()


def declaration(**overrides: object) -> Declaration:
    """A parsed declaration whose probe registry is internally consistent."""
    fields: dict[str, object] = {
        "target": Target(implementation="CPython", minor_line="3.14", architecture="AMD64"),
        "libraries": (library(),),
        "probes": (ProbeSpec(identifier="numpy.float64_is_binary64", because="because"),),
        "deferrals": (Deferral(question="the indicator numeric type", phase=113),),
    }
    fields.update(overrides)
    return Declaration(**fields)  # type: ignore[arg-type]


def test_a_registry_that_agrees_in_both_directions_is_accepted() -> None:
    assert registry_problems(declaration(), frozenset({"numpy.float64_is_binary64"})) == ()


def test_a_declared_probe_nothing_implements_is_a_claim_nobody_checks() -> None:
    problems = registry_problems(declaration(), frozenset())
    assert any("nothing implements it" in problem for problem in problems)


def test_an_implemented_probe_nothing_declares_is_a_check_nobody_asked_for() -> None:
    """The direction people forget.

    A probe running with nothing declaring it has no recorded reason to exist, so
    nobody can tell whether its failure matters.
    """
    problems = registry_problems(
        declaration(), frozenset({"numpy.float64_is_binary64", "numpy.orphan"})
    )
    assert any("nothing declares it" in problem for problem in problems)


def test_a_library_naming_an_undescribed_probe_is_refused() -> None:
    """The `because` field is the point of the declaration.

    A library may not reach a probe the probe table does not describe, because the
    description is what records the assumption the probe defends.
    """
    problems = registry_problems(
        declaration(libraries=(library(probes=("numpy.undescribed",)),)),
        frozenset({"numpy.float64_is_binary64", "numpy.undescribed"}),
    )
    assert any("does not describe" in problem for problem in problems)


# ---------------------------------------------------------------------------
# The four-way version comparison
# ---------------------------------------------------------------------------


def test_four_registers_that_agree_are_accepted() -> None:
    assert version_problems(library(), installed="2.5.2", locked="2.5.2", bound=">=2.5.2") == ()


def test_a_version_above_the_declared_floor_is_accepted() -> None:
    """`pyproject.toml` declares a floor, not a pin. Being above it is correct."""
    assert version_problems(library(), installed="2.5.2", locked="2.5.2", bound=">=2.0.0") == ()


@pytest.mark.parametrize(
    ("installed", "locked", "bound", "expected"),
    [
        pytest.param(None, "2.5.2", ">=2.5.2", "is not installed", id="not installed"),
        pytest.param("2.5.1", "2.5.2", ">=2.5.2", "2.5.1 is installed", id="installed differs"),
        pytest.param("2.5.2", None, ">=2.5.2", "pins no version", id="lock pins nothing"),
        pytest.param("2.5.2", "2.5.1", ">=2.5.2", "pins numpy 2.5.1", id="lock differs"),
        pytest.param("2.5.2", "2.5.2", None, "does not require it", id="manifest omits it"),
        pytest.param("2.5.2", "2.5.2", ">=2.9.0", "below", id="below the floor"),
    ],
)
def test_a_register_that_disagrees_is_named(
    installed: str | None, locked: str | None, bound: str | None, expected: str
) -> None:
    problems = version_problems(library(), installed=installed, locked=locked, bound=bound)
    assert any(expected in problem for problem in problems), problems


def test_a_specifier_this_gate_cannot_read_is_reported_rather_than_assumed_satisfied() -> None:
    """An unread constraint that passes is worse than one that fails.

    The gate reads `>=` because that is what this project writes. Anything else
    must say so rather than quietly counting as met.
    """
    problems = version_problems(library(), installed="2.5.2", locked="2.5.2", bound="==2.5.2")
    assert any("cannot read" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Provenance and identity
# ---------------------------------------------------------------------------


def test_a_matching_wheel_tag_is_accepted() -> None:
    assert provenance_problems(library(), recorded_tag="cp314-cp314-win_amd64") == ()


def test_a_free_threaded_wheel_is_caught_as_a_wrong_artefact() -> None:
    """The concrete case this exists for.

    `cp314t` is the free-threaded ABI, which `runtime-contract.toml` refuses. It
    installs cleanly and the lock's digest says nothing about it.
    """
    problems = provenance_problems(library(), recorded_tag="cp314-cp314t-win_amd64")
    assert len(problems) == 1
    assert "cp314t" in problems[0]


def test_an_artefact_recording_no_tag_cannot_have_its_provenance_checked() -> None:
    problems = provenance_problems(library(), recorded_tag=None)
    assert len(problems) == 1
    assert "records no wheel tag" in problems[0]


def test_an_importable_module_is_accepted() -> None:
    assert identity_problems(library(), module_location="C:/x/numpy/__init__.py") == ()


def test_a_module_that_cannot_be_imported_is_refused() -> None:
    problems = identity_problems(library(), module_location=None)
    assert len(problems) == 1
    assert "could not be imported" in problems[0]


def test_a_module_resolving_to_nowhere_is_refused() -> None:
    """A namespace package with no origin is not the library the lock pinned."""
    problems = identity_problems(library(), module_location="")
    assert len(problems) == 1
    assert "unnamed location" in problems[0]


# ---------------------------------------------------------------------------
# Deferrals
# ---------------------------------------------------------------------------


def test_a_question_deferred_to_a_future_phase_is_accepted() -> None:
    assert deferral_problems([Deferral(question="q", phase=113)], delivered=22, total=320) == ()


def test_a_question_deferred_to_a_delivered_phase_is_refused() -> None:
    """The same rule the policy documents' deferral tables are held to."""
    problems = deferral_problems([Deferral(question="q", phase=18)], delivered=22, total=320)
    assert len(problems) == 1
    assert "already been delivered" in problems[0]


def test_a_question_deferred_beyond_the_programme_is_refused() -> None:
    problems = deferral_problems([Deferral(question="q", phase=999)], delivered=22, total=320)
    assert len(problems) == 1
    assert "beyond the 320-phase programme" in problems[0]


# ---------------------------------------------------------------------------
# Reading the declaration
# ---------------------------------------------------------------------------

MINIMAL = """
schema = 1

[target]
implementation = "CPython"
minor_line = "3.14"
architecture = "AMD64"

[[library]]
name = "numpy"
import_name = "numpy"
version = "2.5.2"
wheel_tag = "cp314-cp314-win_amd64"
role = "the numerical half"
probes = ["numpy.float64_is_binary64"]

[[probe]]
id = "numpy.float64_is_binary64"
because = "PRECISION_POLICY.md defines the approximate regime in these terms"

[[deferral]]
question = "the indicator numeric type"
phase = 113
"""


def test_a_well_formed_declaration_parses() -> None:
    parsed = parse_declaration(MINIMAL)
    assert parsed.target.minor_line == "3.14"
    assert [entry.name for entry in parsed.libraries] == ["numpy"]
    assert [entry.identifier for entry in parsed.probes] == ["numpy.float64_is_binary64"]
    assert [entry.phase for entry in parsed.deferrals] == [113]


@pytest.mark.parametrize(
    ("mutation", "replacement", "expected"),
    [
        pytest.param("schema = 1", "schema = 2", "announces schema", id="another schema"),
        pytest.param("[target]", "[targets]", r"no \[target\] table", id="no target"),
        pytest.param('minor_line = "3.14"', "", "no non-empty string", id="a missing field"),
        pytest.param('name = "numpy"', 'name = ""', "no non-empty string", id="a blank field"),
        pytest.param("phase = 113", 'phase = "113"', "no integer", id="a phase as a string"),
        pytest.param("phase = 113", "phase = true", "no integer", id="a phase as a boolean"),
        pytest.param(
            'probes = ["numpy.float64_is_binary64"]',
            "probes = 1",
            "no list",
            id="probes not a list",
        ),
        pytest.param(
            'probes = ["numpy.float64_is_binary64"]',
            "probes = [1]",
            "non-string",
            id="a probe that is not a string",
        ),
    ],
)
def test_a_declaration_with_a_hole_in_it_is_refused(
    mutation: str, replacement: str, expected: str
) -> None:
    """Nothing is defaulted.

    A contract with a hole in it has not declared the thing the hole was for, and
    a gate that filled it in would be checking against its own guess.
    """
    with pytest.raises(StackError, match=expected):
        parse_declaration(MINIMAL.replace(mutation, replacement))


def test_a_declaration_that_is_not_toml_is_refused() -> None:
    with pytest.raises(StackError, match="not valid TOML"):
        parse_declaration("[unterminated")


def test_a_declaration_with_no_libraries_is_refused() -> None:
    """An empty array would make every check below pass over nothing."""
    stripped = MINIMAL.split("[[library]]", maxsplit=1)[0] + MINIMAL.split("[[probe]]", 1)[1]
    with pytest.raises(StackError, match=r"no \[\[library\]\] entries"):
        parse_declaration(stripped)


def test_an_entry_that_is_not_a_table_is_refused() -> None:
    """TOML permits `probe = ["a string"]`, which parses and is not an entry.

    The array exists and has a member, so a reader checking only for presence
    would walk on and then fail on an attribute lookup somewhere less obvious.
    """
    head, _probes = MINIMAL.split("[[probe]]", maxsplit=1)
    document = head.replace("schema = 1", 'schema = 1\nprobe = ["not a table"]', 1)
    document += '[[deferral]]\nquestion = "q"\nphase = 113\n'
    with pytest.raises(StackError, match="is not a table"):
        parse_declaration(document)


def test_the_error_message_names_the_file_a_reader_must_open() -> None:
    """A diagnosis nobody can act on is a failure reported twice."""
    with pytest.raises(StackError, match=CONFIGURATION_FILE):
        parse_declaration("schema = 99")


def test_the_implemented_registry_is_not_empty() -> None:
    """Guard the guard: an empty registry would make the comparison vacuous."""
    assert len(implemented_probes()) >= 7
