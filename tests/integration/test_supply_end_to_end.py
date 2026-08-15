"""The supply gate composed, against the real tree, offline.

Run with ``online=False``, because ADR-0024 makes the suite offline by
construction and an autouse fixture refuses outbound sockets. That is not a
weakened test: the point of these is the artefacts and the arithmetic, and the
platform probe's own judgement is covered from literals in
``tests/unit/test_supply_capability.py``.

The audit is likewise unmeasured here — nothing in the suite may reach an
advisory service — so the verdict under test is ``unmeasured`` rather than
``passed``. That is itself worth asserting: **an unmeasured check outranks a
passing one**, and a gate that reported this tree as passing while two of its
checks never ran would be exactly the failure Phase 014 exists to prevent.
"""

import json
from pathlib import Path

import pytest

from tools.quality.execution.plan import Verdict
from tools.quality.supply import manifest
from tools.quality.supply.cli import EXIT_USAGE, main
from tools.quality.supply.gate import (
    EXIT_UNMEASURED,
    INVENTORY_NAME,
    MANIFEST_NAME,
    SBOM_NAME,
    run_supply,
)


@pytest.fixture(scope="module")
def produced(tmp_path_factory: pytest.TempPathFactory) -> tuple[int, Path]:
    """One offline run of the gate, and where it wrote.

    Module-scoped because the run reads the whole tracked tree and every test
    below asks a different question about the same artefacts. Written to a
    temporary directory rather than to ``.globin/supply`` so the suite leaves the
    working tree exactly as it found it.
    """
    directory = tmp_path_factory.mktemp("supply")
    return run_supply(online=False, output=directory), directory


def test_the_gate_writes_all_three_artefacts(produced: tuple[int, Path]) -> None:
    """An inventory, a bill of materials and a manifest that seals both."""
    _, directory = produced
    for name in (INVENTORY_NAME, SBOM_NAME, MANIFEST_NAME):
        assert (directory / name).is_file(), f"{name} was not written"
        assert (directory / name).read_text(encoding="utf-8").strip()


def test_an_unmeasured_check_outranks_a_passing_one(produced: tuple[int, Path]) -> None:
    """Doubt about what ran casts doubt on what passed.

    Offline, the audit cannot reach an advisory service and the platform was not
    asked. Six checks pass and the verdict is still ``unmeasured``, which is the
    whole contract: a gate that answered "passed" here would be answering about
    checks that never ran.
    """
    code, directory = produced
    assert code == EXIT_UNMEASURED

    document = manifest.load((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["overall"] == Verdict.UNMEASURED.value
    assert manifest.REASON_AUDIT_UNMEASURED in verdict["reasons"]


def test_the_local_checks_pass_against_this_tree(produced: tuple[int, Path]) -> None:
    """The checks that need nothing outside the runner all succeed.

    Asserted separately from the verdict above so that a genuine regression in
    one of them is distinguishable from the expected offline unmeasurement.
    """
    _, directory = produced
    document = manifest.load((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    findings = document["findings"]
    assert isinstance(findings, dict)

    for name in ("inventory", "action_pins", "sbom", "waivers", "secret_hygiene"):
        entry = findings[name]
        assert isinstance(entry, dict)
        assert entry["verdict"] == Verdict.PASSED.value, f"{name}: {entry}"


def test_the_written_sbom_is_valid_and_reproducible(produced: tuple[int, Path]) -> None:
    """The document on disk is the one the manifest's digest describes.

    Rebuilt here from the same inventory rather than compared against a stored
    string, so what is asserted is that the generator is a function of the tree —
    which is the property a digest is worth having for.
    """
    _, directory = produced
    from tools.quality.supply import sbom as sbom_module

    written = json.loads((directory / SBOM_NAME).read_text(encoding="utf-8"))
    assert not sbom_module.validate(written)
    assert written["specVersion"] == sbom_module.SPEC_VERSION

    document = manifest.load((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    findings = document["findings"]
    assert isinstance(findings, dict)
    recorded = findings["sbom"]
    assert isinstance(recorded, dict)
    assert recorded["digest"] == sbom_module.digest(written)


def test_a_second_run_produces_the_same_bill_of_materials(
    produced: tuple[int, Path], tmp_path: Path
) -> None:
    """Two runs over one unchanged tree, byte for byte.

    The gate already compares two builds internally on every invocation. This
    compares two *invocations*, which additionally covers the reading of the tree
    rather than only the rendering of what was read.
    """
    _, first = produced
    run_supply(online=False, output=tmp_path)
    assert (tmp_path / SBOM_NAME).read_bytes() == (first / SBOM_NAME).read_bytes()
    assert (tmp_path / INVENTORY_NAME).read_bytes() == (first / INVENTORY_NAME).read_bytes()


def test_the_manifest_carries_no_absolute_path_and_no_wall_clock(
    produced: tuple[int, Path], repo_root: Path
) -> None:
    """Evidence CI publishes must not carry this machine's user name.

    Nor a timestamp: the only time in the document is the commit's own date, so
    two runs over one commit differ nowhere. That is what lets the manifest be
    compared rather than merely read.
    """
    _, directory = produced
    text = (directory / MANIFEST_NAME).read_text(encoding="utf-8")
    assert str(repo_root) not in text
    assert "C:\\\\Users" not in text
    assert str(directory) not in text

    document = manifest.load(text)
    run = document["run"]
    assert isinstance(run, dict)
    assert set(run) == {"commit", "committed", "repository", "branch", "cyclonedx_spec_version"}


def test_the_capability_section_records_every_control_as_unprobed(
    produced: tuple[int, Path],
) -> None:
    """Not omitted. A manifest missing an answer leaves a reader to infer one."""
    from tools.quality.supply.capability import CONTROLS, State

    _, directory = produced
    document = manifest.load((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    recorded = document["capability"]
    assert isinstance(recorded, dict)
    assert set(recorded) == {control.name for control in CONTROLS}
    for entry in recorded.values():
        assert isinstance(entry, dict)
        assert entry["state"] == State.NOT_PROBED.value
        assert entry["reason"]


def test_the_command_line_refuses_a_word_it_does_not_know() -> None:
    """A typo that silently ran the default would write a manifest nobody asked for.

    The usage code is distinct from every verdict, so "you typed it wrong" is
    never mistaken for "the repository is in trouble".
    """
    assert main(["nonsense"]) == EXIT_USAGE
    assert EXIT_USAGE not in {0, 1, EXIT_UNMEASURED}
