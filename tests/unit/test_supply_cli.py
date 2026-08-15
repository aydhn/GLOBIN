"""The entry point, and the branches a passing run never reaches.

Mirrors ``test_workflow_cli.py``, which exists for the same reason: the paths
that matter most are the ones taken when something is wrong, and those are
exactly the paths a healthy repository never exercises. A gate whose failure
handling has never run is a gate whose failure handling is a guess.
"""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.quality.execution.plan import Verdict
from tools.quality.supply import manifest
from tools.quality.supply.audit import Runner
from tools.quality.supply.cli import EXIT_USAGE, USAGE, UsageError, main, parse
from tools.quality.supply.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    MANIFEST_NAME,
    run_supply,
)
from tools.quality.supply.inventory import SupplyChainError

CLEAN_AUDIT = json.dumps({"dependencies": [{"name": "ruff", "version": "0.15.14", "vulns": []}]})


def _runner(payload: str, status: int = 204, body: str = "") -> Runner:
    """A child that answers both the audit and the probe.

    Args:
        payload: What ``pip-audit`` should print.
        status: The HTTP status ``gh`` should report.
        body: The response body ``gh`` should print.

    Returns:
        The callable, dispatching on whether ``gh`` was asked for.
    """

    def run(argv: Sequence[str], **_: object) -> subprocess.CompletedProcess[str]:
        if argv and argv[0] == "gh":
            return subprocess.CompletedProcess(list(argv), 0, f"HTTP/2.0 {status}\r\n\n{body}", "")
        return subprocess.CompletedProcess(list(argv), 0, payload, "")

    return run


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "online"),
    [
        pytest.param([], True, id="no argument runs the default"),
        pytest.param(["run"], True, id="the explicit spelling works"),
        pytest.param(["--offline"], False, id="the flag alone"),
        pytest.param(["run", "--offline"], False, id="both, in order"),
        pytest.param(["--offline", "run"], False, id="both, reversed"),
    ],
)
def test_the_command_line_is_read(argv: list[str], online: bool) -> None:
    """Every accepted spelling, so the refusals below are about real mistakes."""
    assert parse(argv) is online


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["nonsense"], id="an unknown word"),
        pytest.param(["run", "run"], id="a repeated command"),
        pytest.param(["--online"], id="a flag that does not exist"),
        pytest.param(["-o"], id="a short form nobody defined"),
    ],
)
def test_an_unrecognised_word_is_refused(argv: list[str]) -> None:
    """A typo that silently ran the default would write a manifest nobody asked for."""
    with pytest.raises(UsageError):
        parse(argv)


def test_a_bad_command_line_exits_two_and_prints_the_usage() -> None:
    """Distinct from every verdict, so "you typed it wrong" is never mistaken.

    for "the repository is in trouble".
    """
    assert main(["nonsense"]) == EXIT_USAGE
    assert EXIT_USAGE not in {EXIT_OK, EXIT_GATE_FAILED, EXIT_UNMEASURED}


def test_the_usage_documents_every_exit_code() -> None:
    """A reader who sees a `3` should be able to find out what it means."""
    for code in (EXIT_OK, EXIT_GATE_FAILED, EXIT_USAGE, EXIT_UNMEASURED):
        assert f"  {code}  " in USAGE
    assert "--offline" in USAGE


def test_a_directory_that_cannot_be_written_is_unmeasured_rather_than_passing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate failing to record its own result is not the gate passing."""

    def refuse(**_: object) -> int:
        message = "read-only file system"
        raise OSError(message)

    monkeypatch.setattr("tools.quality.supply.cli.run_supply", refuse)
    assert main([]) == EXIT_UNMEASURED


def test_the_module_starts_as_a_process(repo_root: Path) -> None:
    """``__main__`` is wiring, and starting it is the only way to find out it works.

    A coverage pragma would assert that the line does not need testing;
    ``QUALITY_GATES.md`` says that is exactly the claim not to make.
    """
    completed = subprocess.run(
        ["python", "-m", "tools.quality.supply", "nonsense"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=repo_root,
    )
    assert completed.returncode == EXIT_USAGE
    assert "unrecognised argument" in completed.stdout


# ---------------------------------------------------------------------------
# The gate's own branches
# ---------------------------------------------------------------------------


def test_an_online_run_measures_the_audit_and_the_platform(tmp_path: Path) -> None:
    """The path an offline test cannot reach, driven by an injected child.

    Both network-facing checks report, so the verdict is a real one rather than
    the ``unmeasured`` an offline run necessarily produces.
    """
    code = run_supply(online=True, output=tmp_path, runner=_runner(CLEAN_AUDIT))
    document = manifest.load((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))
    findings = document["findings"]
    assert isinstance(findings, dict)

    audit_entry = findings["vulnerability_audit"]
    assert isinstance(audit_entry, dict)
    assert audit_entry["verdict"] == Verdict.PASSED.value
    assert code == EXIT_OK


def test_a_vulnerability_fails_the_gate(tmp_path: Path) -> None:
    """An open finding is a failure, at any severity, while the toolchain is small."""
    payload = json.dumps(
        {
            "dependencies": [
                {
                    "name": "ruff",
                    "version": "0.15.14",
                    "vulns": [{"id": "GHSA-aaaa-bbbb-cccc", "fix_versions": []}],
                }
            ]
        }
    )
    code = run_supply(online=True, output=tmp_path, runner=_runner(payload))
    assert code == EXIT_GATE_FAILED

    document = manifest.load((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["overall"] == Verdict.FAILED.value
    assert manifest.REASON_AUDIT_VULNERABLE in verdict["reasons"]


def test_a_required_control_switched_off_fails_the_gate(tmp_path: Path) -> None:
    """A control that is available and disabled is the one state that is somebody's fault."""
    code = run_supply(
        online=True,
        output=tmp_path,
        runner=_runner(CLEAN_AUDIT, status=404, body='{"message":"Not Found"}'),
    )
    assert code == EXIT_GATE_FAILED

    document = manifest.load((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    assert manifest.REASON_CAPABILITY_REGRESSED in verdict["reasons"]


def test_an_unreadable_tree_is_unmeasured_rather_than_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An inventory that could not be collected is not an inventory of nothing.

    Reporting an empty tree as clean is the failure mode every refusal in
    ``inventory.py`` exists to prevent, and this is where it would surface.
    """

    def refuse(_: Path) -> tuple[object, ...]:
        message = "pyproject.toml is missing"
        raise SupplyChainError(message)

    monkeypatch.setattr("tools.quality.supply.gate.collect", refuse)
    code = run_supply(online=False, output=tmp_path, runner=_runner(CLEAN_AUDIT))
    assert code == EXIT_UNMEASURED

    document = manifest.load((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))
    findings = document["findings"]
    assert isinstance(findings, dict)
    inventory_entry = findings["inventory"]
    assert isinstance(inventory_entry, dict)
    assert inventory_entry["verdict"] == Verdict.UNMEASURED.value

    sbom_entry = findings["sbom"]
    assert isinstance(sbom_entry, dict)
    assert sbom_entry["verdict"] == Verdict.UNMEASURED.value
    assert sbom_entry["digest"] == ""


def test_a_malformed_waiver_register_fails_rather_than_being_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-closed: a register that cannot be read is not a register with nothing in it."""

    def refuse(_: Path) -> tuple[object, ...]:
        message = "waiver #1 omits owner"
        raise SupplyChainError(message)

    monkeypatch.setattr("tools.quality.supply.gate.waivers.load", refuse)
    code = run_supply(online=False, output=tmp_path, runner=_runner(CLEAN_AUDIT))
    assert code in {EXIT_GATE_FAILED, EXIT_UNMEASURED}

    document = manifest.load((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))
    findings = document["findings"]
    assert isinstance(findings, dict)
    entry = findings["waivers"]
    assert isinstance(entry, dict)
    assert entry["verdict"] == Verdict.FAILED.value


def test_a_tree_without_git_records_an_unknown_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest that invented a commit would be worse than one admitting it does not know.

    The waiver check is then unmeasured too, because expiry is judged against the
    commit's date and there is no date to judge against.
    """
    monkeypatch.setattr("tools.quality.supply.gate._committed_on", lambda: ("", None))
    monkeypatch.setattr("tools.quality.supply.gate._sha", lambda: "unknown")

    assert run_supply(online=False, output=tmp_path, runner=_runner(CLEAN_AUDIT)) == EXIT_UNMEASURED
    document = manifest.load((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))

    run = document["run"]
    assert isinstance(run, dict)
    assert run["commit"] == "unknown"

    findings = document["findings"]
    assert isinstance(findings, dict)
    entry = findings["waivers"]
    assert isinstance(entry, dict)
    assert entry["verdict"] == Verdict.UNMEASURED.value


def test_a_tree_git_cannot_list_leaves_the_secret_scan_unmeasured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scanning nothing successfully is not the same as finding nothing."""
    monkeypatch.setattr("tools.quality.supply.gate._tracked_files", tuple)

    assert run_supply(online=False, output=tmp_path, runner=_runner(CLEAN_AUDIT)) == EXIT_UNMEASURED
    document = manifest.load((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))
    findings = document["findings"]
    assert isinstance(findings, dict)
    entry = findings["secret_hygiene"]
    assert isinstance(entry, dict)
    assert entry["verdict"] == Verdict.UNMEASURED.value
    assert entry["scanned"] == 0
