"""The wheel-survey reasoning, driven from literals.

Every function under test is pure, so nothing here needs a tree, a network or a
fixture file. That is the point of the split: the tag arithmetic is where this
phase can be wrong in a way nobody notices, so it is the part exercised most.

**The cases are real filenames.** ``xgboost-3.4.1-py3-none-win_amd64.whl`` and
``ta_lib-0.7.1-cp314-cp314-win_amd64.whl`` are what the index actually publishes,
and each pins a conclusion the survey draws. Inventing plausible-looking tags
instead would test the matcher against the author's belief about wheels rather
than against wheels.
"""

from datetime import date

import pytest

from tools.quality.wheels import plan

# ---------------------------------------------------------------------------
# Targets used across the module
# ---------------------------------------------------------------------------

PINNED = plan.Target(
    implementation="CPython",
    minor_line="3.14",
    architecture="AMD64",
    platform_tag="win_amd64",
    free_threaded=False,
    index="https://pypi.org/pypi/",
    surveyed="2026-08-16",
)

FREE_THREADED = PINNED.free_threaded_twin()


def library(**overrides: object) -> plan.Library:
    """A surveyed library, defaulting to a consistent, available one."""
    fields: dict[str, object] = {
        "name": "torch",
        "phase": 183,
        "version": "2.13.0",
        "requires_python": ">=3.10",
        "wheels": ("torch-2.13.0-cp314-cp314-win_amd64.whl",),
        "verdict": plan.AVAILABLE,
        "source": "https://pypi.org/pypi/torch/json",
        "reason": "Neural models.",
        "resolved_by": None,
    }
    fields.update(overrides)
    return plan.Library(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "python", "abi", "platform"),
    [
        ("torch-2.13.0-cp314-cp314-win_amd64.whl", ("cp314",), ("cp314",), ("win_amd64",)),
        ("numpy-2.5.2-cp314-cp314t-win_amd64.whl", ("cp314",), ("cp314t",), ("win_amd64",)),
        ("xgboost-3.4.1-py3-none-win_amd64.whl", ("py3",), ("none",), ("win_amd64",)),
        ("optuna-4.9.0-py3-none-any.whl", ("py3",), ("none",), ("any",)),
        ("thing-1.0-py2.py3-none-any.whl", ("py2", "py3"), ("none",), ("any",)),
        ("thing-1.0-1-cp314-abi3-win_amd64.whl", ("cp314",), ("abi3",), ("win_amd64",)),
    ],
)
def test_a_wheel_filename_parses_into_its_three_tag_sets(
    filename: str, python: tuple[str, ...], abi: tuple[str, ...], platform: tuple[str, ...]
) -> None:
    """A compressed set such as ``py2.py3`` is expanded once, here, not at every comparison."""
    wheel = plan.parse_wheel_filename(filename)
    assert (wheel.python_tags, wheel.abi_tags, wheel.platform_tags) == (python, abi, platform)


def test_the_build_tag_is_not_mistaken_for_part_of_the_version() -> None:
    """PEP 427 puts an optional build tag between version and interpreter tag.

    Reading it as part of the version would make every recorded version look wrong.
    """
    wheel = plan.parse_wheel_filename("thing-1.0-1-cp314-abi3-win_amd64.whl")
    assert wheel.version == "1.0"


@pytest.mark.parametrize(
    "filename",
    [
        "torch-2.13.0.tar.gz",
        "not-a-wheel",
        "too-few-cp314-win_amd64.whl",
        "",
        "torch-2.13.0-cp314-cp314-win_amd64.zip",
    ],
)
def test_something_that_is_not_a_wheel_filename_is_refused(filename: str) -> None:
    with pytest.raises(plan.WheelSurveyError):
        plan.parse_wheel_filename(filename)


# ---------------------------------------------------------------------------
# Tag matching against the pinned interpreter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "torch-2.13.0-cp314-cp314-win_amd64.whl",
        "xgboost-3.4.1-py3-none-win_amd64.whl",
        "optuna-4.9.0-py3-none-any.whl",
        "thing-1.0-cp312-none-any.whl",
        "thing-1.0-cp313-abi3-win_amd64.whl",
        "thing-1.0-py312-none-any.whl",
    ],
)
def test_a_wheel_the_pinned_interpreter_could_install_is_recognised(filename: str) -> None:
    assert plan.satisfies(plan.parse_wheel_filename(filename), PINNED)


@pytest.mark.parametrize(
    ("filename", "why"),
    [
        ("numpy-2.5.2-cp314-cp314t-win_amd64.whl", "the free-threaded ABI is a different build"),
        ("thing-1.0-cp313-cp313-win_amd64.whl", "3.14 does not provide 3.13's ABI"),
        ("thing-1.0-cp315-cp315-win_amd64.whl", "a later interpreter than the pinned one"),
        ("thing-1.0-cp314-cp314-manylinux1_x86_64.whl", "a platform this host is not"),
        ("thing-1.0-cp314-cp314-win32.whl", "the 32-bit platform tag"),
        ("thing-1.0-py315-none-any.whl", "a Python newer than the pinned line"),
    ],
)
def test_a_wheel_the_pinned_interpreter_could_not_install_is_rejected(
    filename: str, why: str
) -> None:
    assert not plan.satisfies(plan.parse_wheel_filename(filename), PINNED), why


def test_an_abi_free_wheel_for_an_older_cpython_still_installs() -> None:
    """``cp312-none-any`` binds to no ABI, so 3.14 can install it.

    ``cp312-cp312-win_amd64`` cannot, and the difference is the ABI tag alone.
    This pairing is the one a substring match gets wrong in both directions.
    """
    assert plan.satisfies(plan.parse_wheel_filename("thing-1.0-cp312-none-any.whl"), PINNED)
    assert not plan.satisfies(
        plan.parse_wheel_filename("thing-1.0-cp312-cp312-win_amd64.whl"), PINNED
    )


def test_a_platform_specific_interpreter_agnostic_wheel_is_available() -> None:
    """The finding this phase would have got wrong.

    ``xgboost`` and ``lightgbm`` load native code through ``ctypes`` rather than
    building against a Python ABI, so they publish one ``py3-none-win_amd64``
    wheel and no ``cp314`` anything. A survey grepping for ``cp314`` reports a gap
    in both that does not exist.
    """
    for filename in (
        "xgboost-3.4.1-py3-none-win_amd64.whl",
        "lightgbm-4.7.0-py3-none-win_amd64.whl",
    ):
        assert plan.satisfies(plan.parse_wheel_filename(filename), PINNED)


@pytest.mark.parametrize(
    "filename",
    [
        "thing-1.0-jy27-none-any.whl",
        "thing-1.0-pp310-none-any.whl",
        "thing-1.0-cp3x-none-any.whl",
        "thing-1.0-py-none-any.whl",
    ],
)
def test_an_interpreter_tag_this_module_does_not_recognise_is_refused(filename: str) -> None:
    """Another implementation's tag is not read as a CPython one.

    Returning ``False`` rather than attempting to interpret it is the same refusal
    the implementation check makes: this survey is about CPython, and a tag it
    cannot place is not evidence of anything.
    """
    assert not plan.satisfies(plan.parse_wheel_filename(filename), PINNED)


def test_no_wheel_satisfies_an_implementation_this_module_does_not_reason_about() -> None:
    """The survey is about CPython. Anything else is refused rather than assumed."""
    other = plan.Target(
        implementation="PyPy",
        minor_line="3.14",
        architecture="AMD64",
        platform_tag="win_amd64",
        free_threaded=False,
        index="https://pypi.org/pypi/",
        surveyed="2026-08-16",
    )
    assert not plan.satisfies(plan.parse_wheel_filename("optuna-4.9.0-py3-none-any.whl"), other)


# ---------------------------------------------------------------------------
# The free-threaded twin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "numpy-2.5.2-cp314-cp314t-win_amd64.whl",
        "xgboost-3.4.1-py3-none-win_amd64.whl",
        "optuna-4.9.0-py3-none-any.whl",
    ],
)
def test_an_abi_free_or_free_threaded_wheel_serves_a_free_threaded_build(filename: str) -> None:
    assert plan.satisfies(plan.parse_wheel_filename(filename), FREE_THREADED)


@pytest.mark.parametrize(
    "filename",
    ["ta_lib-0.7.1-cp314-cp314-win_amd64.whl", "thing-1.0-cp314-abi3-win_amd64.whl"],
)
def test_a_default_build_wheel_does_not_serve_a_free_threaded_build(filename: str) -> None:
    """The default ABI and the limited API are both absent from a free-threaded build.

    Treating either as a route onto ``3.14t`` would report the stack as ready for
    a change it is not ready for, which is the exact claim ADR-0050 refused to
    make without evidence.
    """
    assert not plan.satisfies(plan.parse_wheel_filename(filename), FREE_THREADED)


def test_the_free_threaded_twin_differs_only_in_the_build() -> None:
    assert FREE_THREADED.free_threaded is True
    assert FREE_THREADED.minor_line == PINNED.minor_line
    assert FREE_THREADED.platform_tag == PINNED.platform_tag


def test_the_abi_tag_names_the_build_it_belongs_to() -> None:
    assert (PINNED.interpreter_tag, PINNED.abi_tag) == ("cp314", "cp314")
    assert FREE_THREADED.abi_tag == "cp314t"


def test_a_free_threaded_target_has_no_twin_to_compare() -> None:
    with pytest.raises(plan.WheelSurveyError, match="already free-threaded"):
        plan.free_threaded_gaps([library()], FREE_THREADED)


def test_only_libraries_without_a_free_threaded_wheel_are_named() -> None:
    entries = [
        library(name="ta-lib", wheels=("ta_lib-0.7.1-cp314-cp314-win_amd64.whl",)),
        library(name="numpy", wheels=("numpy-2.5.2-cp314-cp314t-win_amd64.whl",)),
        library(name="optuna", wheels=("optuna-4.9.0-py3-none-any.whl",)),
    ]
    assert plan.free_threaded_gaps(entries, PINNED) == ("ta-lib",)


# ---------------------------------------------------------------------------
# Requires-Python
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "specifier", [">=3.10", ">=3.12", "<3.15,>=3.10", ">=3.9", "<4", ">3.13", "<=3.14"]
)
def test_a_specifier_that_admits_the_pinned_line_is_accepted(specifier: str) -> None:
    assert plan.admits(specifier, PINNED)


@pytest.mark.parametrize("specifier", [">=3.15", "<3.14", "<3.10,>=3.8", ">3.14"])
def test_a_specifier_that_excludes_the_pinned_line_is_rejected(specifier: str) -> None:
    assert not plan.admits(specifier, PINNED)


def test_the_binance_cap_admits_the_pinned_line_and_would_not_admit_the_next() -> None:
    """The sharpest finding in the survey, pinned as a test.

    Every ``binance-sdk-*`` distribution publishes ``<3.15,>=3.10``. The pinned
    line satisfies that; 3.15 would not. ADR-0050 chose an exact minor line rather
    than a floor, and this is the evidence that the choice was the right shape.
    """
    assert plan.admits("<3.15,>=3.10", PINNED)
    next_line = plan.Target(
        implementation="CPython",
        minor_line="3.15",
        architecture="AMD64",
        platform_tag="win_amd64",
        free_threaded=False,
        index="https://pypi.org/pypi/",
        surveyed="2026-08-16",
    )
    assert not plan.admits("<3.15,>=3.10", next_line)


@pytest.mark.parametrize("specifier", ["==3.14", "!=3.14", "~=3.14", "===3.14", "^3.14"])
def test_an_operator_this_module_does_not_decide_is_refused_rather_than_guessed(
    specifier: str,
) -> None:
    """On ambiguity, refuse. ``ENGINEERING_CONTRACT.md`` invariant 2."""
    with pytest.raises(plan.WheelSurveyError):
        plan.admits(specifier, PINNED)


@pytest.mark.parametrize("specifier", ["<3.14.3", ">=3.14.1"])
def test_a_bound_inside_the_pinned_line_is_refused(specifier: str) -> None:
    """A minor line alone cannot decide a patch-level bound within itself.

    Answering anyway would be right for some patch releases and wrong for others,
    with nothing recording which.
    """
    with pytest.raises(plan.WheelSurveyError, match="patch version inside"):
        plan.admits(specifier, PINNED)


def test_a_bound_inside_a_different_line_is_decided_normally() -> None:
    assert plan.admits(">=3.10.2", PINNED)


@pytest.mark.parametrize("specifier", ["", "   ", "3.14", ">=", ">=three"])
def test_a_specifier_that_says_nothing_usable_is_refused(specifier: str) -> None:
    """Silence is not permission.

    A distribution publishing no ``Requires-Python`` has made no claim, and
    reading that as "every version" is the assumption this phase exists to remove.
    """
    with pytest.raises(plan.WheelSurveyError):
        plan.admits(specifier, PINNED)


# ---------------------------------------------------------------------------
# Platform tags
# ---------------------------------------------------------------------------


def test_the_supported_architecture_maps_to_its_pep_425_tag() -> None:
    assert plan.platform_tag_for("AMD64") == "win_amd64"


def test_an_architecture_with_no_recorded_mapping_is_refused() -> None:
    """``ARM64`` would be ``win_arm64``, and nothing here has checked that.

    Inventing the mapping is the assumption this phase removes rather than makes.
    """
    with pytest.raises(plan.WheelSurveyError, match="no platform tag is recorded"):
        plan.platform_tag_for("ARM64")


# ---------------------------------------------------------------------------
# The target as a tripwire
# ---------------------------------------------------------------------------


def test_a_target_agreeing_with_the_runtime_contract_reports_nothing() -> None:
    assert (
        plan.target_problems(
            PINNED,
            implementation="CPython",
            minor_line="3.14",
            architecture="AMD64",
            free_threaded=False,
        )
        == ()
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("implementation", "PyPy"),
        ("minor_line", "3.13"),
        ("architecture", "ARM64"),
    ],
)
def test_a_target_disagreeing_with_the_runtime_contract_is_reported(field: str, value: str) -> None:
    """A survey against an interpreter the project does not run is worse than stale.

    It reports availability for a line nothing uses while the pinned line goes
    unexamined.
    """
    contract: dict[str, object] = {
        "implementation": "CPython",
        "minor_line": "3.14",
        "architecture": "AMD64",
        "free_threaded": False,
    }
    contract[field] = value
    problems = plan.target_problems(PINNED, **contract)  # type: ignore[arg-type]
    assert problems


def test_a_free_threaded_disagreement_is_reported() -> None:
    problems = plan.target_problems(
        PINNED,
        implementation="CPython",
        minor_line="3.14",
        architecture="AMD64",
        free_threaded=True,
    )
    assert any("free_threaded" in problem for problem in problems)


def test_a_platform_tag_that_does_not_follow_from_the_architecture_is_reported() -> None:
    wrong = plan.Target(
        implementation="CPython",
        minor_line="3.14",
        architecture="AMD64",
        platform_tag="win32",
        free_threaded=False,
        index="https://pypi.org/pypi/",
        surveyed="2026-08-16",
    )
    problems = plan.target_problems(
        wrong,
        implementation="CPython",
        minor_line="3.14",
        architecture="AMD64",
        free_threaded=False,
    )
    assert any("PEP 425" in problem for problem in problems)


def test_a_minor_line_that_is_not_major_dot_minor_is_refused() -> None:
    broken = plan.Target(
        implementation="CPython",
        minor_line="3.14.5",
        architecture="AMD64",
        platform_tag="win_amd64",
        free_threaded=False,
        index="https://pypi.org/pypi/",
        surveyed="2026-08-16",
    )
    with pytest.raises(plan.WheelSurveyError, match=r"not major\.minor"):
        _ = broken.release


# ---------------------------------------------------------------------------
# Recomputing a recorded verdict
# ---------------------------------------------------------------------------


def test_a_consistent_entry_reports_nothing() -> None:
    assert plan.verdict_problems(library(), PINNED) == ()


def test_an_entry_claiming_a_wheel_its_evidence_does_not_show_fails() -> None:
    """What stops the declaration being a transcription.

    The verdict is a claim about a set of filenames, so the filenames are recorded
    and the claim is recomputed.
    """
    entry = library(wheels=("torch-2.13.0-cp313-cp313-win_amd64.whl",))
    problems = plan.verdict_problems(entry, PINNED)
    assert any("recorded as 'available'" in problem for problem in problems)


def test_an_entry_denying_a_wheel_its_evidence_does_show_fails() -> None:
    entry = library(verdict=plan.SOURCE_ONLY, resolved_by=25)
    problems = plan.verdict_problems(entry, PINNED)
    assert any("serves" in problem for problem in problems)


def test_a_verdict_outside_the_vocabulary_is_refused() -> None:
    problems = plan.verdict_problems(library(verdict="probably"), PINNED)
    assert any("is not one of" in problem for problem in problems)


def test_a_recorded_wheel_for_a_different_version_is_reported() -> None:
    """A filename carrying another version means the record was edited by hand.

    Which is precisely what this file forbids.
    """
    entry = library(version="2.12.0")
    problems = plan.verdict_problems(entry, PINNED)
    assert any("carries" in problem for problem in problems)


def test_a_requires_python_excluding_the_pinned_line_is_reported() -> None:
    entry = library(requires_python=">=3.15")
    problems = plan.verdict_problems(entry, PINNED)
    assert any("does not admit" in problem for problem in problems)


def test_an_unparseable_filename_is_reported_rather_than_raised() -> None:
    """A judgement returns findings; it does not blow up the run."""
    problems = plan.verdict_problems(library(wheels=("nonsense",)), PINNED)
    assert problems


# ---------------------------------------------------------------------------
# Placement, gaps and duplicates
# ---------------------------------------------------------------------------


def test_an_entry_scheduled_by_a_future_phase_is_accepted() -> None:
    assert plan.phase_problems([library()], delivered=17, total=320) == ()


def test_an_entry_scheduled_by_a_delivered_phase_is_an_adoption_not_a_survey() -> None:
    problems = plan.phase_problems([library(phase=4)], delivered=17, total=320)
    assert any("already delivered" in problem for problem in problems)


def test_an_entry_beyond_the_programme_is_reported() -> None:
    problems = plan.phase_problems([library(phase=999)], delivered=17, total=320)
    assert any("beyond the" in problem for problem in problems)


def test_a_gap_owned_by_a_future_phase_is_accepted() -> None:
    """A gap is not a failure. An unowned gap is.

    The roadmap asks this phase to record each gap rather than assume one, and a
    library whose upstream publishes no wheel is not something a gate fixes by
    going red.
    """
    entry = library(verdict=plan.SOURCE_ONLY, wheels=("thing-1.0-cp313-cp313-win32.whl",))
    assert plan.gap_problems([library(**{"verdict": plan.SOURCE_ONLY})], delivered=17, total=320)
    owned = plan.Library(
        name=entry.name,
        phase=entry.phase,
        version=entry.version,
        requires_python=entry.requires_python,
        wheels=entry.wheels,
        verdict=plan.SOURCE_ONLY,
        source=entry.source,
        reason=entry.reason,
        resolved_by=25,
    )
    assert plan.gap_problems([owned], delivered=17, total=320) == ()


def test_a_gap_belonging_to_nobody_fails() -> None:
    problems = plan.gap_problems([library(verdict=plan.ABSENT)], delivered=17, total=320)
    assert any("belongs to nobody" in problem for problem in problems)


@pytest.mark.parametrize(("owner", "marker"), [(4, "already"), (999, "beyond the")])
def test_a_gap_owned_by_a_phase_that_cannot_close_it_fails(owner: int, marker: str) -> None:
    problems = plan.gap_problems(
        [library(verdict=plan.ABSENT, resolved_by=owner)], delivered=17, total=320
    )
    assert any(marker in problem for problem in problems)


def test_an_available_library_naming_an_owner_fails() -> None:
    """An owner against a library with nothing wrong is a phase given nothing to do."""
    problems = plan.gap_problems([library(resolved_by=25)], delivered=17, total=320)
    assert any("nothing to do" in problem for problem in problems)


def test_one_distribution_surveyed_twice_is_reported() -> None:
    """Two entries would let the survey hold two verdicts with nothing choosing."""
    assert plan.duplicate_libraries([library(), library()]) == ("torch",)
    assert plan.duplicate_libraries([library(), library(name="numpy")]) == ()


# ---------------------------------------------------------------------------
# Reading the declaration
# ---------------------------------------------------------------------------

MINIMAL = """
schema = 1

[target]
implementation = "CPython"
minor_line = "3.14"
architecture = "AMD64"
platform_tag = "win_amd64"
free_threaded = false
index = "https://pypi.org/pypi/"
surveyed = 2026-08-16

[[library]]
name = "optuna"
phase = 211
version = "4.9.0"
requires_python = ">=3.9"
wheels = ["optuna-4.9.0-py3-none-any.whl"]
verdict = "available"
source = "https://pypi.org/pypi/optuna/json"
reason = "Studies."
"""


def test_a_well_formed_declaration_parses() -> None:
    declaration = plan.parse_declaration(MINIMAL)
    assert declaration.target.minor_line == "3.14"
    assert declaration.target.surveyed == "2026-08-16"
    assert [entry.name for entry in declaration.libraries] == ["optuna"]
    assert declaration.libraries[0].resolved_by is None


def test_an_unknown_schema_is_refused_by_name() -> None:
    with pytest.raises(plan.WheelSurveyError, match="schema"):
        plan.parse_declaration(MINIMAL.replace("schema = 1", "schema = 2"))


def test_text_that_is_not_toml_is_refused() -> None:
    with pytest.raises(plan.WheelSurveyError, match="not valid TOML"):
        plan.parse_declaration("[[[")


def test_a_declaration_with_no_library_surveys_nothing() -> None:
    head = MINIMAL.split("[[library]]")[0]
    with pytest.raises(plan.WheelSurveyError, match="surveys nothing"):
        plan.parse_declaration(head)


def test_a_missing_target_table_is_refused() -> None:
    with pytest.raises(plan.WheelSurveyError, match=r"\[target\]"):
        plan.parse_declaration(MINIMAL.replace("[target]", "[environment]"))


@pytest.mark.parametrize(
    "line",
    [
        'implementation = "CPython"',
        'minor_line = "3.14"',
        "free_threaded = false",
        "surveyed = 2026-08-16",
    ],
)
def test_every_target_value_is_required(line: str) -> None:
    """There is no default for any of them.

    A default would let the survey silently describe an environment nobody chose.
    """
    with pytest.raises(plan.WheelSurveyError):
        plan.parse_declaration(MINIMAL.replace(line, ""))


def test_a_quoted_date_is_refused() -> None:
    """TOML has a date type, and a quoted date has been validated by nothing."""
    with pytest.raises(plan.WheelSurveyError, match="bare TOML"):
        plan.parse_declaration(MINIMAL.replace("surveyed = 2026-08-16", 'surveyed = "2026-08-16"'))


def test_a_bare_date_is_recorded_as_an_iso_string() -> None:
    declaration = plan.parse_declaration(MINIMAL)
    assert declaration.target.surveyed == date(2026, 8, 16).isoformat()


def test_a_free_threaded_flag_that_is_not_a_boolean_is_refused() -> None:
    with pytest.raises(plan.WheelSurveyError, match="true or false"):
        plan.parse_declaration(MINIMAL.replace("free_threaded = false", 'free_threaded = "no"'))


def test_a_phase_that_is_not_a_positive_integer_is_refused() -> None:
    with pytest.raises(plan.WheelSurveyError, match="positive integer"):
        plan.parse_declaration(MINIMAL.replace("phase = 211", "phase = 0"))


def test_a_boolean_is_not_accepted_where_an_integer_is_required() -> None:
    """``bool`` is an ``int`` in Python, and reading ``true`` as phase 1 would be silent."""
    with pytest.raises(plan.WheelSurveyError, match="positive integer"):
        plan.parse_declaration(MINIMAL.replace("phase = 211", "phase = true"))


def test_an_empty_wheel_list_is_refused() -> None:
    with pytest.raises(plan.WheelSurveyError, match="non-empty list"):
        plan.parse_declaration(MINIMAL.replace('["optuna-4.9.0-py3-none-any.whl"]', "[]"))


def test_a_wheel_list_holding_something_that_is_not_a_string_is_refused() -> None:
    with pytest.raises(plan.WheelSurveyError, match="expected a string"):
        plan.parse_declaration(MINIMAL.replace('["optuna-4.9.0-py3-none-any.whl"]', "[7]"))


TARGET_TABLE: dict[str, object] = {
    "implementation": "CPython",
    "minor_line": "3.14",
    "architecture": "AMD64",
    "platform_tag": "win_amd64",
    "free_threaded": False,
    "index": "https://pypi.org/pypi/",
    "surveyed": date(2026, 8, 16),
}


def test_a_library_array_that_is_not_an_array_of_tables_is_refused() -> None:
    with pytest.raises(plan.WheelSurveyError, match="array of tables"):
        plan.read_declaration({"schema": 1, "target": TARGET_TABLE, "library": "optuna"})


def test_a_library_array_holding_a_scalar_is_refused() -> None:
    with pytest.raises(plan.WheelSurveyError, match="expected a table"):
        plan.read_declaration({"schema": 1, "target": TARGET_TABLE, "library": ["optuna"]})


def test_a_present_but_invalid_resolved_by_is_refused_rather_than_read_as_absent() -> None:
    """Absent means "no gap here". Invalid means somebody wrote something unusable.

    Reading the second as the first would discard the only thing they were saying.
    """
    text = MINIMAL.replace('reason = "Studies."', 'reason = "Studies."\nresolved_by = -1')
    with pytest.raises(plan.WheelSurveyError, match="positive integer"):
        plan.parse_declaration(text)


def test_the_verdict_vocabulary_has_exactly_three_words() -> None:
    """Four words would need a fourth meaning, and nothing here has one."""
    assert {plan.AVAILABLE, plan.SOURCE_ONLY, plan.ABSENT} == plan.VERDICTS
