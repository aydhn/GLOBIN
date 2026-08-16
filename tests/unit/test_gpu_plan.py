"""The GPU contract's judgements, from literals, on a machine with any hardware at all.

Every test here builds a :class:`~tools.quality.gpu.plan.Reading` by hand. That is
the whole point of separating the classifier from the probe: the branches that
matter most are the ones the development host **cannot** produce — no driver
installed, a driver that exits non-zero, a device reporting a compute capability
the parser refuses — and continuous integration runs on a machine with no GPU at
all, so a suite that only exercised the happy path would exercise nothing there.
"""

import pytest

from tools.quality.gpu.plan import (
    CONFIGURATION_FILE,
    Capability,
    Declaration,
    ForbiddenField,
    GpuContractError,
    Interface,
    Reading,
    State,
    Target,
    classify,
    duplicate_capabilities,
    forbidden_field_problems,
    gap_problems,
    is_deprecated,
    looks_like_compute_capability,
    looks_like_version,
    parse_declaration,
    parse_query_row,
    parse_version_table,
    phase_problems,
    target_problems,
)

FIELDS = ("name", "driver_version", "compute_cap", "memory.total")

CONTRACT = f"""
schema = 1

[target]
system = "Windows"
architecture = "AMD64"

[interface]
command = "nvidia-smi"
query_fields = {list(FIELDS)!r}
version_arguments = ["--version"]
format_arguments = ["--format=csv,noheader"]

[[forbidden_field]]
name = "cuda_version"
where = "--query-gpu"
reason = "not a valid field to query"

[[capability]]
id = "gpu.present"
question = "Is a device visible?"
source = "--query-gpu=name"
policy = "optional"
phase = 24
absence_means = "Later questions are unmeasurable."
""".replace("'", '"')


def declaration(**capability: object) -> Declaration:
    """A declaration with the five capabilities the gate classifies.

    Args:
        **capability: Overrides applied to every capability entry.

    Returns:
        The declaration.
    """
    identifiers = (
        "gpu.present",
        "gpu.driver_version",
        "gpu.compute_capability",
        "cuda.runtime_present",
        "cuda.toolkit_present",
    )
    defaults: dict[str, object] = {
        "question": "?",
        "source": "s",
        "policy": "optional",
        "phase": 24,
        "absence_means": "nothing depends on it",
    }
    defaults.update(capability)
    return Declaration(
        target=Target(system="Windows", architecture="AMD64"),
        interface=Interface(
            command="nvidia-smi",
            query_fields=FIELDS,
            version_arguments=("--version",),
            format_arguments=("--format=csv,noheader",),
        ),
        forbidden=(
            ForbiddenField(name="cuda_version", where="--query-gpu", reason="not valid"),
            ForbiddenField(name="CUDA version", where="--version", reason="deprecated"),
        ),
        capabilities=tuple(
            Capability(identifier=identifier, **defaults)  # type: ignore[arg-type]
            for identifier in identifiers
        ),
    )


def reading(**overrides: object) -> Reading:
    """A reading from a host with one working device.

    Args:
        **overrides: Fields to replace.

    Returns:
        The reading.
    """
    values: dict[str, object] = {
        "command_found": True,
        "query_ok": True,
        "query_output": "NVIDIA GeForce RTX 3050 Laptop GPU, 610.88, 8.6, 4096 MiB\n",
        "query_error": "",
        "version_ok": True,
        "version_output": (
            "NVIDIA-SMI version  : 610.88\n"
            'DRIVER version      : Deprecated, see "KMD version" instead\n'
            'CUDA version        : Deprecated, see "CUDA UMD version" instead\n'
            "KMD version         : 610.88\n"
            "CUDA UMD version    : 13.3\n"
        ),
        "toolkit_found": False,
    }
    values.update(overrides)
    return Reading(**values)  # type: ignore[arg-type]


def test_a_working_host_reports_every_capability_it_has() -> None:
    """The happy path, and the values that reach the manifest."""
    observed = classify(reading(), declaration())
    assert observed.states["gpu.present"] is State.PRESENT
    assert observed.driver_version == "610.88"
    assert observed.compute_capabilities == ("8.6",)
    assert observed.cuda_runtime_version == "13.3"


def test_the_deprecated_cuda_label_is_never_read_as_a_version() -> None:
    """The trap this whole contract exists for.

    The driver answers its own `CUDA version` label with the word *Deprecated*.
    Taking the first matching label would publish that sentence where a version
    belongs, and nothing downstream could tell it from a measurement.
    """
    observed = classify(reading(), declaration())
    assert observed.cuda_runtime_version == "13.3"
    assert "Deprecated" not in observed.cuda_runtime_version


def test_a_host_with_no_driver_is_absent_rather_than_broken() -> None:
    """The property continuous integration depends on.

    `gpu.present` is ABSENT because GLOBIN asked and there is none. Everything
    downstream is UNMEASURABLE because there was nothing to ask, which is a
    different claim and is recorded as one.
    """
    observed = classify(reading(command_found=False), declaration())
    assert observed.states["gpu.present"] is State.ABSENT
    assert observed.states["gpu.driver_version"] is State.UNMEASURABLE
    assert observed.states["cuda.runtime_present"] is State.UNMEASURABLE
    assert not gap_problems(observed.states, declaration().capabilities)


def test_a_driver_that_refuses_the_query_is_an_error_not_an_absence() -> None:
    """Not knowing why is a different fact from knowing why, and only one is a defect."""
    observed = classify(
        reading(query_ok=False, query_output="", query_error='Field "x" is not a valid field'),
        declaration(),
    )
    assert observed.states["gpu.present"] is State.ERROR
    assert gap_problems(observed.states, declaration().capabilities)


def test_a_driver_reporting_no_devices_is_an_absence() -> None:
    """A driver with no card is a real configuration, and it is not an error."""
    observed = classify(reading(query_output="\n"), declaration())
    assert observed.states["gpu.present"] is State.ABSENT
    assert not gap_problems(observed.states, declaration().capabilities)


def test_a_row_with_the_wrong_number_of_cells_is_refused_rather_than_guessed() -> None:
    """Guessing which cell went missing would put a driver version in another field."""
    observed = classify(reading(query_output="only, three, cells\n"), declaration())
    assert observed.states["gpu.present"] is State.ERROR
    assert observed.notes


def test_a_driver_version_that_is_not_a_version_is_refused() -> None:
    """Shape-checking is the second defence behind the forbidden-field table."""
    observed = classify(
        reading(query_output="Card, Deprecated see elsewhere, 8.6, 4096 MiB\n"), declaration()
    )
    assert observed.states["gpu.driver_version"] is State.ERROR
    assert observed.driver_version == ""


def test_several_devices_report_their_distinct_compute_capabilities() -> None:
    """Sorted and de-duplicated, so two runs on one host produce identical evidence."""
    observed = classify(
        reading(
            query_output=(
                "A, 610.88, 8.6, 4096 MiB\nB, 610.88, 7.5, 8192 MiB\nC, 610.88, 8.6, 1 MiB\n"
            )
        ),
        declaration(),
    )
    assert observed.compute_capabilities == ("7.5", "8.6")


def test_a_toolkit_is_never_inferred_from_a_runtime() -> None:
    """The distinction the target host itself demonstrates.

    A driver-side CUDA runtime says a prebuilt wheel would run. It says nothing
    about whether CUDA source could be built, and this host has the first without
    the second.
    """
    with_toolkit = classify(reading(toolkit_found=True), declaration())
    without = classify(reading(toolkit_found=False), declaration())
    assert with_toolkit.states["cuda.runtime_present"] is State.PRESENT
    assert with_toolkit.states["cuda.toolkit_present"] is State.PRESENT
    assert without.states["cuda.runtime_present"] is State.PRESENT
    assert without.states["cuda.toolkit_present"] is State.ABSENT


def test_a_toolkit_is_reported_even_when_no_driver_exists() -> None:
    """`nvcc` can be installed on a machine with no card, so it is asked independently."""
    observed = classify(reading(command_found=False, toolkit_found=True), declaration())
    assert observed.states["gpu.present"] is State.ABSENT
    assert observed.states["cuda.toolkit_present"] is State.PRESENT


def test_a_capability_the_classifier_never_reached_is_unmeasurable_not_missing() -> None:
    """Adding a row without teaching the classifier produces a visible *nobody asked*."""
    extended = declaration()
    extra = Capability(
        identifier="gpu.invented",
        question="?",
        source="s",
        policy="optional",
        phase=24,
        absence_means="n",
    )
    observed = classify(
        reading(),
        Declaration(
            target=extended.target,
            interface=extended.interface,
            forbidden=extended.forbidden,
            capabilities=(*extended.capabilities, extra),
        ),
    )
    assert observed.states["gpu.invented"] is State.UNMEASURABLE


def test_a_required_capability_that_is_absent_fails() -> None:
    """The word exists so the phase that depends on a GPU can say so."""
    required = declaration(policy="required")
    observed = classify(reading(command_found=False), required)
    assert gap_problems(observed.states, required.capabilities)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("610.88", True, id="two-part"),
        pytest.param("13.3", True, id="short"),
        pytest.param("1.2.3.4", True, id="four-part"),
        pytest.param("570", True, id="bare-integer"),
        pytest.param('Deprecated, see "KMD version" instead', False, id="a-deprecation-notice"),
        pytest.param("", False, id="empty"),
        pytest.param("v1.2", False, id="prefixed"),
        pytest.param("N/A", False, id="not-available"),
    ],
)
def test_a_version_is_recognised_by_shape(value: str, expected: bool) -> None:
    """Digits and dots. A sentence is not a version however plausible it reads."""
    assert looks_like_version(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("8.6", True, id="ordinary"),
        pytest.param("10.0", True, id="two-digit-major"),
        pytest.param("8", False, id="major-only"),
        pytest.param("8.6.1", False, id="three-part"),
        pytest.param("[N/A]", False, id="unsupported-marker"),
    ],
)
def test_a_compute_capability_is_always_major_dot_minor(value: str, expected: bool) -> None:
    """Narrower than a version, because a compute capability has exactly two parts."""
    assert looks_like_compute_capability(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param('Deprecated, see "KMD version" instead', True, id="as-the-driver-writes-it"),
        pytest.param("DEPRECATED", True, id="shouted"),
        pytest.param("610.88", False, id="an-actual-version"),
    ],
)
def test_a_deprecation_notice_is_recognised(value: str, expected: bool) -> None:
    """Measured on the target host; see `docs/research/phase_023_sources.md` S-03."""
    assert is_deprecated(value) is expected


def test_the_version_table_skips_a_line_with_no_separator() -> None:
    """The table is human-facing and has carried banner lines before.

    Refusing the whole reading over one cosmetic line would turn a formatting
    change into an unmeasured capability.
    """
    table = parse_version_table("a banner line\nCUDA UMD version : 13.3\n")
    assert table == {"cuda umd version": "13.3"}


def test_a_query_row_is_read_into_its_declared_fields() -> None:
    assert parse_query_row("A, 1.0, 8.6, 4 MiB", FIELDS)["compute_cap"] == "8.6"


def test_a_short_query_row_is_refused() -> None:
    with pytest.raises(GpuContractError, match="carried 2 values for 4 fields"):
        parse_query_row("A, 1.0", FIELDS)


def test_a_target_that_diverges_from_the_runtime_contract_is_reported() -> None:
    """The tripwire's whole job: somebody changed the runtime contract and not this."""
    problems = target_problems(
        Target(system="Windows", architecture="AMD64"), system="Linux", architecture="AMD64"
    )
    assert problems
    assert "Linux" in problems[0]


def test_a_repeated_capability_is_reported() -> None:
    """Two answers to one question, and which one wins would depend on iteration order."""
    repeated = declaration().capabilities
    assert duplicate_capabilities((*repeated, repeated[0]))


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        pytest.param(24, False, id="a-future-phase"),
        pytest.param(22, True, id="a-delivered-phase"),
        pytest.param(23, True, id="the-phase-recording-it"),
        pytest.param(321, True, id="beyond-the-programme"),
    ],
)
def test_a_gap_must_be_owned_by_a_phase_that_can_still_close_it(phase: int, expected: bool) -> None:
    """A gap owned by a shipped phase is one nobody will ever close.

    Phase 023 itself counts as delivered here, because a capability owned by the
    phase that records it is a promise the gate makes to itself.
    """
    problems = phase_problems(declaration(phase=phase).capabilities, delivered=23, total=320)
    assert bool(problems) is expected


def test_a_field_both_permitted_and_forbidden_is_a_contradiction() -> None:
    """A rule with an exception written directly underneath it."""
    interface = Interface(
        command="nvidia-smi",
        query_fields=("cuda_version",),
        version_arguments=("--version",),
        format_arguments=(),
    )
    assert forbidden_field_problems(
        interface, (ForbiddenField(name="cuda_version", where="--query-gpu", reason="r"),)
    )


def test_the_declaration_parses_and_refuses_a_wrong_schema() -> None:
    assert parse_declaration(CONTRACT).target.system == "Windows"
    with pytest.raises(GpuContractError, match="declares schema"):
        parse_declaration(CONTRACT.replace("schema = 1", "schema = 99"))


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        pytest.param(("[target]", "[wrong]"), "no \\[target\\] table", id="missing-table"),
        pytest.param(
            ('policy = "optional"', 'policy = "maybe"'), "not one of", id="unknown-policy"
        ),
        pytest.param(("phase = 24", 'phase = "24"'), "no integer", id="phase-as-a-string"),
        pytest.param(('command = "nvidia-smi"', 'command = ""'), "no 'command'", id="empty-string"),
        pytest.param(
            ("[[capability]]", "[[unused]]"), "no \\[\\[capability\\]\\] entries", id="no-entries"
        ),
    ],
)
def test_a_malformed_contract_is_refused_by_name(mutation: tuple[str, str], expected: str) -> None:
    """Every refusal path, so none of them is reachable only in theory."""
    old, new = mutation
    with pytest.raises(GpuContractError, match=expected):
        parse_declaration(CONTRACT.replace(old, new))


def test_the_configuration_file_is_where_the_gate_looks() -> None:
    assert CONFIGURATION_FILE == "docs/engineering/gpu-contract.toml"
