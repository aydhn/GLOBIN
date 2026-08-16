"""The stack gate against a whole tree, correct and then deliberately broken.

The unit tests establish that each judgement reaches the right answer from values.
This establishes the things a pure test cannot see: that the gate reads four
separate files and holds them against each other, that a change to any one of them
alone breaks the agreement, and that the manifest it writes reads back through its
own loader with its digest intact.

**Four components, which is what makes this an integration test.** The stack
contract declares a version, `pyproject.toml` bounds it, `pylock.toml` pins it and
the environment installs it. Each can move without the others, and the failure
that matters is the one where a register quietly stops agreeing with the rest.

**Every tree here is a temporary one.** A test that could only run against this
repository would be a test unable to describe a broken stack, which is most of
what is worth asserting.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from tests.support import REPO_ROOT, running_from_the_project_environment
from tests.unit.test_stack_gate import DECLARATION, LOCK, MANIFEST, measurer, prober
from tools.quality.stack import cli, gate, manifest


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A repository whose four registers agree about both libraries."""
    (tmp_path / "docs" / "engineering").mkdir(parents=True)
    (tmp_path / "docs" / "engineering" / "stack-contract.toml").write_text(
        DECLARATION, encoding="utf-8"
    )
    (tmp_path / "docs" / "engineering" / "runtime-contract.toml").write_text(
        (REPO_ROOT / "docs" / "engineering" / "runtime-contract.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "pylock.toml").write_text(LOCK, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(MANIFEST, encoding="utf-8")
    return tmp_path


def written(tree: Path) -> str:
    """The manifest the gate wrote, as text."""
    return (tree / gate.OUTPUT_DIRECTORY / gate.MANIFEST_NAME).read_text(encoding="utf-8")


def test_a_coherent_tree_passes_and_its_manifest_reads_back(tree: Path) -> None:
    """The whole loop: measure, judge, render, seal, and verify the seal."""
    assert gate.run_stack(root=tree, measurer=measurer(), prober=prober()) == gate.EXIT_OK
    document = manifest.load(written(tree))
    assert document["schema"] == manifest.SCHEMA
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["verdict"] == "passed"


def test_moving_the_lock_alone_breaks_the_agreement(tree: Path) -> None:
    """The failure a single-file check could not see.

    Every file is individually well-formed; what is wrong is that they no longer
    describe one stack.
    """
    (tree / "pylock.toml").write_text(LOCK.replace("2.5.2", "2.6.0"), encoding="utf-8")
    assert gate.run_stack(root=tree, measurer=measurer(), prober=prober()) == gate.EXIT_GATE_FAILED
    assert "pylock.toml pins numpy 2.6.0" in written(tree)


def test_moving_the_manifest_alone_breaks_the_agreement(tree: Path) -> None:
    (tree / "pyproject.toml").write_text(MANIFEST.replace(">=2.5.2", ">=9.0.0"), encoding="utf-8")
    assert gate.run_stack(root=tree, measurer=measurer(), prober=prober()) == gate.EXIT_GATE_FAILED
    assert "below" in written(tree)


def test_moving_the_runtime_contract_alone_breaks_the_agreement(tree: Path) -> None:
    """Phase 017 owns the interpreter; this gate owns nothing about it but must notice.

    A stack survey that quietly described a line the project no longer runs is
    exactly the drift the target comparison exists to catch.
    """
    contract = tree / "docs" / "engineering" / "runtime-contract.toml"
    contract.write_text(
        contract.read_text(encoding="utf-8").replace('minor_line = "3.14"', 'minor_line = "3.15"'),
        encoding="utf-8",
    )
    assert gate.run_stack(root=tree, measurer=measurer(), prober=prober()) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_TARGET_DIVERGED in written(tree)


def test_a_failing_run_still_leaves_a_verifiable_manifest(tree: Path) -> None:
    """A gate that left no artefact is indistinguishable from one that never ran.

    And the artefact a failing run leaves must still verify, or the evidence chain
    has a hole exactly where somebody needs to read it.
    """
    gate.run_stack(root=tree, measurer=measurer({}), prober=prober())
    document = manifest.load(written(tree))
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["verdict"] == "failed"
    assert verdict["reasons"]


def test_the_manifest_survives_a_round_trip_through_its_own_loader(tree: Path) -> None:
    """Rendering and loading are separate code paths and could disagree."""
    gate.run_stack(root=tree, measurer=measurer(), prober=prober())
    document = manifest.load(written(tree))
    assert manifest.render(document) == written(tree)


def test_the_module_runs_as_a_process() -> None:
    """The ``__main__`` guard is exercised rather than excluded from measurement.

    `docs/engineering/QUALITY_GATES.md` is explicit that a line excluded from
    measurement is a line nobody is measuring. The usage path is chosen because it
    reaches the guard without writing an artefact or importing a large library.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "tools.quality.stack", "nonsense"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=REPO_ROOT,
    )
    assert completed.returncode == cli.EXIT_USAGE
    assert "unrecognised argument" in completed.stdout


@pytest.mark.skipif(
    not running_from_the_project_environment(),
    reason="numpy and pandas arrive with the runtime lock, which only .venv installs",
)
def test_this_repository_passes_its_own_stack_gate() -> None:
    """The claim the phase actually makes, run against the real tree.

    Everything above proves the gate can describe a broken stack. This proves the
    stack on this host is not one — which is the sentence
    `docs/engineering/SCIENTIFIC_STACK.md` puts its name to.
    """
    assert gate.run_stack() == gate.EXIT_OK
