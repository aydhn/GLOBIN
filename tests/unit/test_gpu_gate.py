"""The GPU gate end to end, with the host substituted: sequencing, exit codes and the CLI.

The judgements are tested from literals in `test_gpu_plan.py`. What is proved here
is what the gate does with them — which manifest it writes, which exit code it
returns, and that it writes one at all when it could not get as far as checking.

**Every probe is injected.** No test here starts `nvidia-smi`, so the whole file
runs identically on a host with a device, a host without one, and CI's GPU-less
runner. That is the same reason `tools/quality/supply/capability.py` injects its
runner: a gate that can only be tested on a host with the thing it detects is a
gate this suite cannot cover, and the hosts that matter most are the ones without.
"""

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from tests.support import REPO_ROOT
from tools.quality.gpu.cli import EXIT_USAGE, USAGE, UsageError, main, parse
from tools.quality.gpu.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    MANIFEST_NAME,
    declaration_of,
    run_gpu,
)
from tools.quality.gpu.manifest import load
from tools.quality.gpu.plan import CONFIGURATION_FILE, GpuContractError
from tools.quality.gpu.probes import TOOLKIT_COMMAND, Locator, Runner, read

DEVICES = "NVIDIA GeForce RTX 3050 Laptop GPU, 610.88, 8.6, 4096 MiB\n"

VERSIONS = (
    "NVIDIA-SMI version  : 610.88\n"
    'DRIVER version      : Deprecated, see "KMD version" instead\n'
    "CUDA UMD version    : 13.3\n"
)


def runner(
    *, devices: str = DEVICES, versions: str = VERSIONS, code: int = 0, error: str = ""
) -> Runner:
    """A substitute for :func:`subprocess.run` answering as a working driver would.

    Args:
        devices: What the device query prints.
        versions: What the version table prints.
        code: The exit code both calls return.
        error: What the device query prints on standard error.

    Returns:
        A callable matching the runner protocol.
    """

    def run(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        wanted_versions = any("--version" in argument for argument in argv)
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=code,
            stdout=versions if wanted_versions else devices,
            stderr="" if wanted_versions else error,
        )

    return run


def locator(*, present: tuple[str, ...] = ("nvidia-smi",)) -> Locator:
    """A substitute for :func:`shutil.which`.

    Args:
        present: Which executables exist on the imagined host.

    Returns:
        A callable answering a path or ``None``.
    """
    return lambda name: f"C:/fake/{name}" if name in present else None


def manifest_at(reports: Path) -> dict[str, object]:
    """The manifest the gate wrote, verified against its own digest."""
    return load((reports / MANIFEST_NAME).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------


def test_a_host_with_a_working_device_passes(tmp_path: Path) -> None:
    """The happy path, against this repository's real contract."""
    code = run_gpu(reports=tmp_path, runner=runner(), locate=locator())
    document = manifest_at(tmp_path)
    assert code == EXIT_OK
    assert document["verdict"] == {"verdict": "passed", "reasons": []}
    assert document["run"]["observed"]["driver_version"] == "610.88"  # type: ignore[index]
    assert document["run"]["observed"]["cuda_runtime_version"] == "13.3"  # type: ignore[index]


def test_a_host_with_no_nvidia_device_also_passes(tmp_path: Path) -> None:
    """A GPU-less host passes, which is the property continuous integration depends on.

    CI runs on `windows-latest`, which has no GPU. A gate that failed here would
    be permanently red on the only host that must stay green, and it would be
    reporting the hardware rather than the repository.
    """
    code = run_gpu(reports=tmp_path, runner=runner(), locate=locator(present=()))
    document = manifest_at(tmp_path)
    assert code == EXIT_OK
    states = {
        record["id"]: record["state"]
        for record in document["findings"]["capabilities"]["capabilities"]  # type: ignore[index]
    }
    assert states["gpu.present"] == "ABSENT"
    assert states["gpu.driver_version"] == "UNMEASURABLE"


def test_a_toolkit_without_a_driver_is_still_recorded(tmp_path: Path) -> None:
    """`nvcc` is asked for independently, so neither answer is derived from the other."""
    run_gpu(reports=tmp_path, runner=runner(), locate=locator(present=(TOOLKIT_COMMAND,)))
    states = {
        record["id"]: record["state"]
        for record in manifest_at(tmp_path)["findings"]["capabilities"]["capabilities"]  # type: ignore[index]
    }
    assert states["gpu.present"] == "ABSENT"
    assert states["cuda.toolkit_present"] == "PRESENT"


def test_a_driver_that_errors_fails_the_gate(tmp_path: Path) -> None:
    """`ERROR` is never a pass, whatever the capability's policy."""
    code = run_gpu(
        reports=tmp_path,
        runner=runner(devices="", code=1, error='Field "x" is not a valid field to query.'),
        locate=locator(),
    )
    document = manifest_at(tmp_path)
    assert code == EXIT_GATE_FAILED
    assert "GPU_CAPABILITY_UNMEASURED" in document["verdict"]["reasons"]  # type: ignore[index]


def test_two_runs_over_one_unchanged_host_produce_identical_bytes(tmp_path: Path) -> None:
    """Determinism, checked rather than claimed.

    No wall clock is recorded anywhere, so the only way two runs could differ is
    if something in the manifest depended on iteration order.
    """
    first, second = tmp_path / "a", tmp_path / "b"
    run_gpu(reports=first, runner=runner(), locate=locator())
    run_gpu(reports=second, runner=runner(), locate=locator())
    assert (first / MANIFEST_NAME).read_bytes() == (second / MANIFEST_NAME).read_bytes()


def test_the_manifest_is_written_with_one_trailing_newline_and_no_carriage_return(
    tmp_path: Path,
) -> None:
    """Written with an explicit newline, so Windows does not translate it."""
    run_gpu(reports=tmp_path, runner=runner(), locate=locator())
    raw = (tmp_path / MANIFEST_NAME).read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw


def test_the_manifest_records_no_absolute_path(tmp_path: Path) -> None:
    """It is published as a public artefact, and every absolute path here names its owner."""
    run_gpu(reports=tmp_path, runner=runner(), locate=locator())
    rendered = (tmp_path / MANIFEST_NAME).read_text(encoding="utf-8")
    assert "C:/fake" not in rendered
    assert str(tmp_path) not in rendered


def test_a_missing_contract_still_leaves_a_manifest(tmp_path: Path) -> None:
    """A failed gate still leaves evidence that it ran.

    A gate that failed silently and left no artefact would be indistinguishable,
    to anything reading the evidence afterwards, from a gate that never ran.
    """
    empty = tmp_path / "tree"
    empty.mkdir()
    code = run_gpu(root=empty, reports=tmp_path, runner=runner(), locate=locator())
    document = manifest_at(tmp_path)
    assert code == EXIT_GATE_FAILED
    assert document["verdict"]["reasons"] == ["GPU_DECLARATION_UNREADABLE"]  # type: ignore[index]


def test_a_malformed_contract_is_named_rather_than_crashing(tmp_path: Path) -> None:
    """The operator edits a file, so the message names the file."""
    tree = tmp_path / "tree"
    (tree / "docs" / "engineering").mkdir(parents=True)
    (tree / CONFIGURATION_FILE).write_text("schema = 99\n", encoding="utf-8", newline="\n")
    code = run_gpu(root=tree, reports=tmp_path, runner=runner(), locate=locator())
    assert code == EXIT_GATE_FAILED
    assert manifest_at(tmp_path)["verdict"]["reasons"] == ["GPU_DECLARATION_UNREADABLE"]  # type: ignore[index]


def test_an_unreadable_runtime_contract_is_reported_as_a_diverged_target(
    tmp_path: Path,
) -> None:
    """The target cannot be checked, which is not the same as it being wrong."""
    tree = tmp_path / "tree"
    (tree / "docs" / "engineering").mkdir(parents=True)
    (tree / CONFIGURATION_FILE).write_text(
        (REPO_ROOT / CONFIGURATION_FILE).read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    code = run_gpu(root=tree, reports=tmp_path, runner=runner(), locate=locator())
    assert code == EXIT_GATE_FAILED
    assert manifest_at(tmp_path)["verdict"]["reasons"] == ["GPU_TARGET_DIVERGED"]  # type: ignore[index]


def test_the_gate_prints_only_ascii(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Everything a gate prints must be ASCII.

    A Windows console encodes its output with the active code page, and a
    character it cannot represent turns a report into a traceback.
    """
    run_gpu(reports=tmp_path, runner=runner(), locate=locator())
    captured = capsys.readouterr()
    assert captured.out.isascii()
    assert "gpu: verdict" in captured.out


def test_declaration_of_refuses_a_tree_with_no_contract(tmp_path: Path) -> None:
    """The helper the contract test uses, held to the same refusal."""
    with pytest.raises(GpuContractError, match="could not be read"):
        declaration_of(tmp_path)


# --------------------------------------------------------------------------
# The probes
# --------------------------------------------------------------------------


def test_the_probe_skips_the_query_entirely_when_the_command_is_absent() -> None:
    """A `FileNotFoundError` and a driver refusing a field mean opposite things.

    Attempting the query anyway would deliver both to the classifier looking
    alike: no driver, versus a driver asked the wrong question.
    """
    started: list[Sequence[str]] = []

    def record(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        started.append(argv)
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout="", stderr="")

    reading = read(declaration_of().interface, runner=record, locate=locator(present=()))
    assert reading.command_found is False
    assert started == []


def test_the_probe_asks_for_exactly_the_declared_fields() -> None:
    """A field outside the contract is a field somebody guessed."""
    asked: list[Sequence[str]] = []

    def record(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        asked.append(argv)
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout="", stderr="")

    interface = declaration_of().interface
    read(interface, runner=record, locate=locator())
    query = next(argument for argv in asked for argument in argv if argument.startswith("--query"))
    assert query == f"--query-gpu={','.join(interface.query_fields)}"


@pytest.mark.parametrize(
    "fault",
    [
        pytest.param(OSError("the driver is not responding"), id="an-os-error"),
        pytest.param(subprocess.TimeoutExpired("nvidia-smi", 20.0), id="a-timeout"),
    ],
)
def test_a_probe_that_cannot_run_reports_rather_than_raises(fault: Exception) -> None:
    """A probe reports its own failure rather than raising.

    Turning *the tool is absent* into an exception would make the common case on
    a GPU-less host travel the same path as a genuine fault.
    """

    def explode(_argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise fault

    reading = read(declaration_of().interface, runner=explode, locate=locator())
    assert reading.command_found is True
    assert reading.query_ok is False


def test_the_probe_uses_the_real_defaults_when_none_are_injected() -> None:
    """The production path, exercised without asserting anything about this host.

    Whether a device exists here is not this test's business — that it can ask
    without being handed a substitute is.
    """
    reading = read(declaration_of().interface)
    assert isinstance(reading.command_found, bool)
    assert isinstance(reading.toolkit_found, bool)


# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------


def test_the_default_subcommand_is_check() -> None:
    """One optional word, and no parser that would make `ch` mean `check`.

    `parse` returns nothing: it either accepts the command line or raises. There
    is one subcommand, so there is no choice to hand back.
    """
    parse([])
    parse(["check"])


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["probe"], id="a-subcommand-this-gate-does-not-have"),
        pytest.param(["check", "check"], id="the-same-word-twice"),
        pytest.param(["--json"], id="a-flag-from-another-command"),
    ],
)
def test_an_unrecognised_argument_is_refused(argv: list[str]) -> None:
    with pytest.raises(UsageError, match="unrecognised argument"):
        parse(argv)


def test_the_command_line_reports_usage_rather_than_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A traceback is not a user interface."""
    assert main(["nonsense"]) == EXIT_USAGE
    assert "usage: python -m tools.quality.gpu" in capsys.readouterr().out


def test_the_usage_text_states_that_absence_is_not_a_failure() -> None:
    """The one thing a reader of this gate most needs to know before running it."""
    assert "not a failure" in USAGE
    assert "Reaches no network" in USAGE


def test_the_usage_text_is_ascii() -> None:
    assert USAGE.isascii()


def test_a_gate_that_cannot_write_its_artefacts_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A read-only or full disk is reported, not raised at an operator.

    `main` promises never to raise: every fault becomes a code and a sentence,
    because a traceback is not a user interface. The failure is `UNMEASURED`
    rather than `GATE_FAILED` — nothing was established either way.
    """

    def refuse(**_kwargs: object) -> int:
        raise OSError(13, "access is denied")

    monkeypatch.setattr("tools.quality.gpu.cli.run_gpu", refuse)
    assert main([]) == 3
    assert "could not write its artefacts" in capsys.readouterr().out


@pytest.mark.slow
def test_the_module_runs_as_a_real_process() -> None:
    """The `__main__` guard, exercised rather than excluded from measurement.

    `QUALITY_GATES.md` refuses a coverage pragma here: a pragma asserts that a
    line does not need testing, and starting the module is the only way to find
    out whether it works. `pythonpath` is a pytest setting and does not cross a
    process boundary, so the child is told where the package is.
    """
    import os

    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH", "")
    root = str(REPO_ROOT)
    environment["PYTHONPATH"] = f"{root}{os.pathsep}{existing}" if existing else root
    # A list, never a shell, and the executable is this interpreter.
    completed = subprocess.run(
        [sys.executable, "-m", "tools.quality.gpu", "check"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env=environment,
        timeout=120,
    )
    assert completed.returncode in {0, 1, 3}, completed.stderr
    assert "gpu: verdict" in completed.stdout
