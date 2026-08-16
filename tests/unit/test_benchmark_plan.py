"""The workload benefit gate's pure judgement: the contract, and what a number means.

Every measurement here is written by hand, so a speedup can be asserted exactly
rather than being whatever this machine happened to do. What running a workload
produces is `test_benchmark_gate.py`'s.
"""

import pytest

from tools.quality.benchmark.plan import (
    CPU,
    CUDA,
    MAXIMUM_REPEATS,
    MAXIMUM_SIZE,
    BenchmarkContractError,
    Declaration,
    Measurement,
    Method,
    State,
    Target,
    Workload,
    classify,
    duplicate_workloads,
    gap_problems,
    parse_declaration,
    phase_problems,
    read_declaration,
    reduce_timings,
    shape_problems,
    target_problems,
)

CONTRACT = """\
schema = 1

[target]
system = "Windows"
architecture = "AMD64"

[method]
warmup = 1
repeats = 3
reduction = "minimum"
clock = "time.perf_counter_ns"

[[workload]]
id = "matmul.cpu"
question = "What does it cost here?"
backend = "cpu"
library = "numpy"
phase = 22
speedup_threshold = 1.0
size = 8

[[workload]]
id = "matmul.cuda"
question = "Does the device pay?"
backend = "cuda"
library = "torch"
phase = 183
speedup_threshold = 2.0
size = 8
"""


def workload(
    identifier: str = "matmul.cpu",
    backend: str = CPU,
    phase: int = 22,
    threshold: float = 1.0,
    size: int = 8,
) -> Workload:
    """One declared workload."""
    return Workload(identifier, "why", backend, "numpy", phase, threshold, size)


def declaration(*workloads: Workload, **method: object) -> Declaration:
    """A declaration over the given workloads."""
    values: dict[str, object] = {
        "warmup": 1,
        "repeats": 3,
        "reduction": "minimum",
        "clock": "time.perf_counter_ns",
    }
    values.update(method)
    return Declaration(
        schema=1,
        target=Target("Windows", "AMD64"),
        method=Method(**values),  # type: ignore[arg-type]
        workloads=workloads or (workload(),),
    )


# ---------------------------------------------------------------------------
# Reading the contract
# ---------------------------------------------------------------------------


def test_a_well_formed_contract_parses() -> None:
    parsed = parse_declaration(CONTRACT)
    assert len(parsed.workloads) == 2
    assert parsed.method.repeats == 3
    assert parsed.workloads[0].family == "matmul"


def test_unreadable_toml_is_reported_rather_than_raised_as_a_parser_error() -> None:
    with pytest.raises(BenchmarkContractError, match="readable TOML"):
        parse_declaration("not toml = = =")


def test_another_schema_is_refused() -> None:
    with pytest.raises(BenchmarkContractError, match="announces schema"):
        parse_declaration(CONTRACT.replace("schema = 1", "schema = 9"))


def test_a_contract_with_no_workloads_is_refused() -> None:
    with pytest.raises(BenchmarkContractError, match="declares no workloads"):
        read_declaration({"schema": 1, "target": {}, "method": {}})


def test_a_missing_table_is_reported() -> None:
    with pytest.raises(BenchmarkContractError, match=r"\[target\] table"):
        read_declaration({"schema": 1, "method": {}, "workload": [{}]})


def test_a_missing_string_is_reported() -> None:
    document = {"schema": 1, "target": {"architecture": "AMD64"}, "method": {}, "workload": [{}]}
    with pytest.raises(BenchmarkContractError, match="'system'"):
        read_declaration(document)


def test_a_boolean_count_is_refused() -> None:
    """A bool is an int in Python, and this one would be a silent misreading.

    `true` resolving to one repeat is the kind of accident that looks like it
    worked.
    """
    document = {
        "schema": 1,
        "target": {"system": "Windows", "architecture": "AMD64"},
        "method": {"warmup": True, "repeats": 3, "reduction": "minimum", "clock": "c"},
        "workload": [{}],
    }
    with pytest.raises(BenchmarkContractError, match="'warmup'"):
        read_declaration(document)


def test_a_workload_that_is_not_a_table_is_refused() -> None:
    document = {
        "schema": 1,
        "target": {"system": "Windows", "architecture": "AMD64"},
        "method": {"warmup": 1, "repeats": 1, "reduction": "minimum", "clock": "c"},
        "workload": ["not a table"],
    }
    with pytest.raises(BenchmarkContractError, match="not a table"):
        read_declaration(document)


def test_a_missing_threshold_is_refused() -> None:
    document = {
        "schema": 1,
        "target": {"system": "Windows", "architecture": "AMD64"},
        "method": {"warmup": 1, "repeats": 1, "reduction": "minimum", "clock": "c"},
        "workload": [
            {"id": "a.cpu", "question": "q", "backend": "cpu", "library": "n", "phase": 1}
        ],
    }
    with pytest.raises(BenchmarkContractError, match="speedup_threshold"):
        read_declaration(document)


# ---------------------------------------------------------------------------
# What the contract must not say
# ---------------------------------------------------------------------------


def test_a_contract_written_for_this_host_agrees_with_the_runtime_contract() -> None:
    target = Target("Windows", "AMD64")
    assert target_problems(target, system="Windows", architecture="AMD64") == ()


def test_a_contract_written_for_another_host_is_reported() -> None:
    problems = target_problems(Target("Linux", "arm64"), system="Windows", architecture="AMD64")
    assert len(problems) == 2


def test_a_repeated_identifier_is_reported() -> None:
    """A repeat is not a style problem.

    The manifest is keyed by identifier, so the second entry would silently
    replace the first and the contract would describe a measurement nobody took.
    """
    assert duplicate_workloads((workload(), workload()))


def test_distinct_identifiers_are_accepted() -> None:
    assert duplicate_workloads((workload("a.cpu"), workload("b.cpu"))) == ()


@pytest.mark.parametrize(
    ("built", "expected"),
    [
        pytest.param(declaration(reduction="mean"), "reduction", id="unimplemented-reduction"),
        pytest.param(declaration(repeats=0), "repeats", id="no-repeats"),
        pytest.param(declaration(repeats=MAXIMUM_REPEATS + 1), "repeats", id="too-many-repeats"),
        pytest.param(
            declaration(workload("MatMul.CPU")), "lowercase identifier", id="bad-identifier"
        ),
        pytest.param(declaration(workload("nodots")), "lowercase identifier", id="not-dotted"),
        pytest.param(
            declaration(workload("a.cpu", backend="quantum")), "backend", id="unknown-backend"
        ),
        pytest.param(declaration(workload(size=0)), "size", id="zero-size"),
        pytest.param(declaration(workload(size=MAXIMUM_SIZE + 1)), "size", id="oversized"),
        pytest.param(
            declaration(workload("m.cuda", backend=CUDA, phase=183, threshold=2.0)),
            "baseline",
            id="unpaired-cuda",
        ),
        pytest.param(
            declaration(workload("m.cpu", threshold=2.0)),
            "compared against itself",
            id="baseline-with-a-threshold",
        ),
    ],
)
def test_a_contract_this_harness_cannot_act_on_is_reported(
    built: Declaration, expected: str
) -> None:
    problems = shape_problems(built)
    assert any(expected in problem for problem in problems)


def test_a_coherent_contract_has_no_shape_problems() -> None:
    built = declaration(workload("m.cpu"), workload("m.cuda", backend=CUDA, phase=183, threshold=2))
    assert shape_problems(built) == ()


# ---------------------------------------------------------------------------
# Phases, and why the floor is asymmetric
# ---------------------------------------------------------------------------


def test_a_cpu_workload_may_name_a_delivered_phase() -> None:
    """It names the phase that adopted the library it already uses."""
    assert phase_problems((workload(phase=22),), delivered=24, total=320) == ()


def test_a_cuda_workload_naming_a_delivered_phase_is_reported() -> None:
    """A gap nobody will ever close, which is ADR-0052's rule."""
    problems = phase_problems(
        (workload("m.cuda", backend=CUDA, phase=20),), delivered=24, total=320
    )
    assert any("already been delivered" in problem for problem in problems)


def test_a_phase_beyond_the_programme_is_reported() -> None:
    problems = phase_problems((workload(phase=999),), delivered=24, total=320)
    assert any("320 phases" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Reduction and classification
# ---------------------------------------------------------------------------


def test_the_minimum_is_the_recorded_figure() -> None:
    """The minimum, not the mean.

    Every source of noise on a general-purpose machine adds time, so the minimum
    is the closest available estimate of the workload's own cost.
    """
    assert reduce_timings((90, 100, 500), "minimum") == 90


def test_no_timings_at_all_is_refused() -> None:
    with pytest.raises(BenchmarkContractError, match="no timings"):
        reduce_timings((), "minimum")


def test_an_unimplemented_reduction_is_refused() -> None:
    with pytest.raises(BenchmarkContractError, match="not implemented"):
        reduce_timings((1,), "mean")


def test_a_cpu_workload_is_its_own_baseline() -> None:
    built = declaration(workload("m.cpu"))
    verdicts = classify(built, (Measurement("m.cpu", State.MEASURED, 100),))
    assert verdicts[0].speedup == 1.0
    assert verdicts[0].benefits is False


def test_a_device_workload_faster_than_its_threshold_benefits() -> None:
    built = declaration(
        workload("m.cpu"), workload("m.cuda", backend=CUDA, phase=183, threshold=2.0)
    )
    verdicts = classify(
        built,
        (Measurement("m.cpu", State.MEASURED, 1000), Measurement("m.cuda", State.MEASURED, 250)),
    )
    assert verdicts[1].speedup == 4.0
    assert verdicts[1].benefits is True


def test_a_device_workload_below_its_threshold_does_not_benefit() -> None:
    """A workload 1.1x faster is slower once the transfer is paid for."""
    built = declaration(
        workload("m.cpu"), workload("m.cuda", backend=CUDA, phase=183, threshold=2.0)
    )
    verdicts = classify(
        built,
        (Measurement("m.cpu", State.MEASURED, 1000), Measurement("m.cuda", State.MEASURED, 910)),
    )
    assert verdicts[1].benefits is False


def test_an_unavailable_backend_keeps_its_state_and_its_reason() -> None:
    built = declaration(workload("m.cuda", backend=CUDA, phase=183, threshold=2.0))
    verdicts = classify(
        built, (Measurement("m.cuda", State.UNAVAILABLE, detail="torch is not installed"),)
    )
    assert verdicts[0].state is State.UNAVAILABLE
    assert verdicts[0].speedup is None


def test_a_workload_with_no_measurement_becomes_an_error_rather_than_vanishing() -> None:
    """Silence is the one answer a harness must never give.

    A missing row and a row saying "this failed" look identical in a summary, and
    only one of them is a reason to look.
    """
    verdicts = classify(declaration(workload("m.cpu")), ())
    assert verdicts[0].state is State.ERROR


def test_a_device_workload_with_no_usable_baseline_is_an_error() -> None:
    built = declaration(
        workload("m.cpu"), workload("m.cuda", backend=CUDA, phase=183, threshold=2.0)
    )
    verdicts = classify(
        built,
        (Measurement("m.cpu", State.UNAVAILABLE), Measurement("m.cuda", State.MEASURED, 10)),
    )
    assert verdicts[1].state is State.ERROR


def test_a_zero_measurement_is_an_error_rather_than_an_infinite_speedup() -> None:
    built = declaration(
        workload("m.cpu"), workload("m.cuda", backend=CUDA, phase=183, threshold=2.0)
    )
    verdicts = classify(
        built,
        (Measurement("m.cpu", State.MEASURED, 1000), Measurement("m.cuda", State.MEASURED, 0)),
    )
    assert verdicts[1].state is State.ERROR


def test_verdicts_come_back_in_declaration_order() -> None:
    built = declaration(workload("a.cpu"), workload("b.cpu"))
    verdicts = classify(
        built,
        (Measurement("b.cpu", State.MEASURED, 2), Measurement("a.cpu", State.MEASURED, 1)),
    )
    assert [item.identifier for item in verdicts] == ["a.cpu", "b.cpu"]


def test_only_an_error_is_a_gate_failure() -> None:
    """Absence is a state; not knowing why is a defect."""
    built = declaration(workload("m.cpu"))
    absent = classify(built, (Measurement("m.cpu", State.UNAVAILABLE),))
    assert gap_problems(absent) == ()
    errored = classify(built, (Measurement("m.cpu", State.ERROR, detail="boom"),))
    assert gap_problems(errored)


def test_an_error_with_no_recorded_reason_still_says_so() -> None:
    built = declaration(workload("m.cpu"))
    problems = gap_problems(classify(built, (Measurement("m.cpu", State.ERROR),)))
    assert any("no reason recorded" in problem for problem in problems)
