"""The drift gate against this repository and this machine.

``tests/unit/test_drift_gate.py`` substitutes the observation, because a test
about the *comparison* should not depend on the host it runs on. This module does
the opposite: it runs the real observation against the real declarations, which is
the only way to find out that the two agree. A policy that classifies keys the
host does not report, or a host that reports keys the policy does not classify, is
a disagreement neither module alone can see.

**Offline, and it starts nothing.** The gate reaches nothing by construction, and
the one subprocess here starts the module to prove it can be started.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from tools.quality.drift import gate, manifest, plan
from tools.quality.runtime.plan import parse_declaration as parse_runtime_contract


@pytest.fixture(scope="module")
def contract(repo_root: Path) -> object:
    """The runtime contract this repository declares."""
    return parse_runtime_contract((repo_root / gate.RUNTIME_CONTRACT).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def policy(repo_root: Path) -> plan.Policy:
    """The drift policy this repository declares."""
    return plan.parse_declaration((repo_root / plan.CONFIGURATION_FILE).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def observation(repo_root: Path, contract: object) -> dict[str, str]:
    """This machine, observed once and flattened."""
    return plan.flatten(gate.observe(repo_root, contract))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The observation this host actually produces
# ---------------------------------------------------------------------------


def test_the_host_can_be_observed(observation: dict[str, str]) -> None:
    """Before anything else is asserted, the observation has to happen at all."""
    assert observation


def test_every_area_the_policy_expects_is_observed(observation: dict[str, str]) -> None:
    """A policy classifying an area nothing reports would be classifying nothing."""
    areas = {key.split(".", 1)[0] for key in observation}
    assert {"host", "interpreter", "environment", "pip"} <= areas


def test_every_observed_key_is_classified_by_the_policy(
    observation: dict[str, str], policy: plan.Policy
) -> None:
    """The disagreement neither unit module can see.

    If the host reports a key nothing classifies, the first time that key moves the
    gate fails with `DRIFT_CLASS_UNDECLARED` and somebody has to decide what it
    means under time pressure. Deciding now is cheaper.
    """
    unclassified = sorted(key for key in observation if policy.for_key(key) is None)
    assert not unclassified, f"observed but unclassified: {unclassified}"


def test_no_observed_value_carries_an_absolute_path(observation: dict[str, str]) -> None:
    """Every path outside the repository is a fingerprint, because this is published.

    `.globin/` is uploaded as a public-repository artifact, and every absolute path
    on a Windows development host contains the account holder's name.
    """
    for key, value in observation.items():
        assert ":\\Users" not in value, f"{key} carries an absolute path"
        assert not value.startswith("/home/"), f"{key} carries an absolute path"


def test_the_toolchain_is_observed_for_every_tool_the_project_declares(
    repo_root: Path, observation: dict[str, str]
) -> None:
    """The register is read rather than restated, so the two cannot disagree."""
    declared = gate.toolchain_names(repo_root)
    assert declared, "no development toolchain is declared"
    for name in declared:
        assert f"toolchain.{name}" in observation


def test_an_installed_tool_is_recorded_at_the_version_that_is_installed(
    repo_root: Path,
) -> None:
    """The running pytest's version is knowable independently of this gate."""
    installed = gate.observe_toolchain(repo_root)
    assert installed["pytest"] == pytest.__version__


def test_observing_twice_reports_the_same_host(
    repo_root: Path, contract: object, observation: dict[str, str]
) -> None:
    """An observation that varied between two calls would make drift meaningless."""
    again = plan.flatten(gate.observe(repo_root, contract))  # type: ignore[arg-type]
    assert again == observation


# ---------------------------------------------------------------------------
# The round trip, against real declarations
# ---------------------------------------------------------------------------


def test_accepting_then_checking_this_host_reports_no_drift(
    repo_root: Path, tmp_path: Path
) -> None:
    """The claim the continuous-integration job makes: accept and check agree.

    It is a real determinism claim rather than a tautology. Every recorded value
    has to survive being written to JSON, read back and compared, and a field that
    was unstable — a set rendered in iteration order, a path resolved differently
    on the second call — fails exactly here.
    """
    assert gate.run_drift(root=repo_root, reports=tmp_path, mode=gate.ACCEPT) == gate.EXIT_OK
    assert gate.run_drift(root=repo_root, reports=tmp_path) == gate.EXIT_OK


def test_a_check_with_no_baseline_is_unmeasured_on_this_repository(
    repo_root: Path, tmp_path: Path
) -> None:
    """The state a fresh clone is in, and it is not a pass."""
    assert gate.run_drift(root=repo_root, reports=tmp_path) == gate.EXIT_UNMEASURED


def test_the_manifest_this_repository_produces_verifies(repo_root: Path, tmp_path: Path) -> None:
    """A document that does not verify is evidence of nothing."""
    gate.run_drift(root=repo_root, reports=tmp_path, mode=gate.ACCEPT)
    document = manifest.load((tmp_path / gate.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert document["phase"] == manifest.PHASE


def test_two_accepts_of_an_unchanged_host_record_the_same_baseline(
    repo_root: Path, tmp_path: Path
) -> None:
    """Byte-for-byte, which is what makes a baseline comparable at all."""
    gate.run_drift(root=repo_root, reports=tmp_path, mode=gate.ACCEPT)
    first = (tmp_path / gate.BASELINE_NAME).read_bytes()
    gate.run_drift(root=repo_root, reports=tmp_path, mode=gate.ACCEPT)
    assert (tmp_path / gate.BASELINE_NAME).read_bytes() == first


def test_a_repair_run_on_an_undrifted_host_changes_nothing(repo_root: Path, tmp_path: Path) -> None:
    """`repair` on a clean machine must be a no-op, or it is not safe to run."""
    gate.run_drift(root=repo_root, reports=tmp_path, mode=gate.ACCEPT)
    config = repo_root / ".venv" / "pyvenv.cfg"
    before = config.read_bytes() if config.is_file() else None
    assert gate.run_drift(root=repo_root, reports=tmp_path, mode=gate.REPAIR) == gate.EXIT_OK
    after = config.read_bytes() if config.is_file() else None
    assert after == before


# ---------------------------------------------------------------------------
# Starting the module
# ---------------------------------------------------------------------------


def test_the_module_can_be_started_and_reports_its_usage() -> None:
    """The entry point, exercised rather than annotated with a coverage pragma.

    Starting the module is the only way to find out whether it starts.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "tools.quality.drift", "--help"],
        capture_output=True,
        cwd=gate.REPO_ROOT,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 2
    assert b"usage: python -m tools.quality.drift" in completed.stdout
