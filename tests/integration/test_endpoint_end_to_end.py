"""The endpoint gate against a real tree, from contract to written manifest.

Two questions only this level can answer. The first is whether the gate's judgements
hold against *this* repository — which is a different claim from
``tests/unit/test_endpoint_plan.py``'s, where every source fragment is a literal. The
second is whether the artefact it writes is the one the other fourteen areas write:
canonical, self-verifying, free of any clock or absolute path, and byte-identical when
the gate is run twice.

**Nothing here opens a socket**, because the gate does not. That is the property that
lets it run on a machine where the surface has never been enabled, and it is asserted
rather than assumed: the gate is given a fixture tree with no network in it at all.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from tools.quality.endpoint.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    MANIFEST_NAME,
    declaration_of,
    run_endpoint,
)
from tools.quality.endpoint.manifest import (
    PHASE,
    REASON_ADDRESS_HARDCODED,
    REASON_CARDINALITY_UNPROVEN,
    REASON_DECLARATION_UNREADABLE,
    REASON_SOURCE_UNREADABLE,
    REASON_WILDCARD_PRESENT,
    REASONS,
    SCHEMA,
    SCHEMA_VERSION,
    EndpointManifestError,
)
from tools.quality.endpoint.manifest import load as load_manifest
from tools.quality.endpoint.plan import (
    CONFIG_MODULE,
    CONFIGURATION_FILE,
    DOMAIN_MODULE,
    METRICS_MODULE,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
"""The repository the gate reports on."""

COPIED: Final[tuple[str, ...]] = (CONFIGURATION_FILE, DOMAIN_MODULE, CONFIG_MODULE, METRICS_MODULE)
"""Everything a fixture tree needs before the gate can reach a verdict."""


def _tree(destination: Path) -> Path:
    """A minimal tree the gate can run against.

    Args:
        destination: Where to build it.

    Returns:
        The tree's root.

    Only the four files the gate reads are copied, plus the test modules the contract
    names and enough of the package for the wildcard sweep. A full copy would make each
    case slow for no gain, and copying only what is read is also how a missing file
    becomes testable.
    """
    for relative in COPIED:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((REPO_ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")
    declaration = declaration_of(REPO_ROOT)
    binding = destination / declaration.binding_module
    binding.parent.mkdir(parents=True, exist_ok=True)
    binding.write_text(
        (REPO_ROOT / declaration.binding_module).read_text(encoding="utf-8"), encoding="utf-8"
    )
    for path in declaration.tests.values():
        named = destination / path
        named.parent.mkdir(parents=True, exist_ok=True)
        named.write_text("# present\n", encoding="utf-8")
    return destination


# ---------------------------------------------------------------------------
# This repository
# ---------------------------------------------------------------------------


def test_this_repository_satisfies_its_own_endpoint_contract(tmp_path: Path) -> None:
    """The claim the gate exists to make, against the tree it was written for."""
    assert run_endpoint(root=REPO_ROOT, reports=tmp_path) == EXIT_OK
    document = load_manifest((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert document["verdict"] == {"verdict": "passed", "reasons": []}
    assert document["phase"] == PHASE


def test_every_check_the_gate_runs_reaches_a_verdict(tmp_path: Path) -> None:
    """Eleven findings, so a check silently dropped from the sequence is caught."""
    run_endpoint(root=REPO_ROOT, reports=tmp_path)
    findings = load_manifest((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))["findings"]
    assert isinstance(findings, dict)
    assert set(findings) == {
        "binding",
        "bounds",
        "cardinality",
        "contract",
        "expositions",
        "loopback",
        "routes",
        "switches",
        "tests",
        "vocabulary",
        "wildcard",
    }
    assert all(entry["verdict"] == "passed" for entry in findings.values())


def test_the_gate_opens_no_socket_and_starts_no_server() -> None:
    """Asserted by inspection, because the offline guard cannot see a listener.

    `tests/conftest.py` refuses outbound *connections*; a gate that bound a port would
    pass that guard while doing exactly the thing this gate promises not to do.
    """
    forbidden = ("socket", "http.server", "socketserver", "urllib", "requests", "subprocess")
    for module in ("gate.py", "plan.py", "manifest.py", "cli.py"):
        source = (REPO_ROOT / "tools" / "quality" / "endpoint" / module).read_text(encoding="utf-8")
        for name in forbidden:
            assert f"import {name}" not in source, f"{module} imports {name}"


# ---------------------------------------------------------------------------
# The artefact
# ---------------------------------------------------------------------------


def test_the_manifest_verifies_against_its_own_digest(tmp_path: Path) -> None:
    """A manifest that did not would identify nothing."""
    run_endpoint(root=REPO_ROOT, reports=tmp_path)
    document = load_manifest((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert document["schema"] == SCHEMA
    assert document["schema_version"] == SCHEMA_VERSION


def test_a_tampered_manifest_is_refused(tmp_path: Path) -> None:
    """The digest is a seal, so editing the document must break it."""
    run_endpoint(root=REPO_ROOT, reports=tmp_path)
    path = tmp_path / MANIFEST_NAME
    document = json.loads(path.read_text(encoding="utf-8"))
    document["phase"] = 999
    with pytest.raises(EndpointManifestError, match="digests to"):
        load_manifest(json.dumps(document))


def test_two_runs_of_the_gate_write_identical_bytes(tmp_path: Path) -> None:
    """Determinism, measured rather than promised.

    A manifest that changed between runs could not be compared with itself, and the
    gate's own determinism check would be measuring the clock.
    """
    first = tmp_path / "first"
    second = tmp_path / "second"
    run_endpoint(root=REPO_ROOT, reports=first)
    run_endpoint(root=REPO_ROOT, reports=second)
    assert (first / MANIFEST_NAME).read_bytes() == (second / MANIFEST_NAME).read_bytes()


def test_the_manifest_records_no_clock_and_no_absolute_path(tmp_path: Path) -> None:
    """The narrowest manifest in the tree: every value comes from two files.

    Unlike `runtime` and `gpu` there is no interpreter to fingerprint and no device to
    name, so there is nothing here that identifies the machine at all.
    """
    run_endpoint(root=REPO_ROOT, reports=tmp_path)
    text = (tmp_path / MANIFEST_NAME).read_text(encoding="utf-8")
    assert str(REPO_ROOT) not in text
    assert "C:" not in text
    assert "/Users" not in text
    for stamp in ("timestamp", "generated_at", "measured_at", "2026-"):
        assert stamp not in text


def test_every_reason_the_manifest_declares_is_spelled_consistently() -> None:
    """A closed set, so a reason the gate can emit and this does not name is a hole."""
    assert REASONS
    assert all(reason.startswith("ENDPOINT_") for reason in REASONS)
    assert all(reason == reason.upper() for reason in REASONS)


# ---------------------------------------------------------------------------
# What the gate does when it cannot get as far as checking
# ---------------------------------------------------------------------------


def test_an_absent_contract_fails_and_still_writes_a_manifest(tmp_path: Path) -> None:
    """A gate that left no artefact is indistinguishable from one that never ran."""
    reports = tmp_path / "reports"
    assert run_endpoint(root=tmp_path / "empty", reports=reports) == EXIT_GATE_FAILED
    document = load_manifest((reports / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert document["verdict"] == {
        "verdict": "failed",
        "reasons": [REASON_DECLARATION_UNREADABLE],
    }


def test_an_absent_source_module_fails_with_its_own_reason(tmp_path: Path) -> None:
    """Distinct from an absent contract: the contract was fine and the tree was not."""
    tree = _tree(tmp_path / "tree")
    (tree / METRICS_MODULE).unlink()
    reports = tmp_path / "reports"
    assert run_endpoint(root=tree, reports=reports) == EXIT_GATE_FAILED
    document = load_manifest((reports / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert document["verdict"] == {"verdict": "failed", "reasons": [REASON_SOURCE_UNREADABLE]}


def test_a_malformed_contract_fails_before_any_source_is_read(tmp_path: Path) -> None:
    """So a reader is sent to the contract rather than to a module."""
    tree = _tree(tmp_path / "tree")
    (tree / CONFIGURATION_FILE).write_text("this is = = not toml\n", encoding="utf-8")
    reports = tmp_path / "reports"
    assert run_endpoint(root=tree, reports=reports) == EXIT_GATE_FAILED
    document = load_manifest((reports / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert document["verdict"]["reasons"] == [REASON_DECLARATION_UNREADABLE]  # type: ignore[index]


# ---------------------------------------------------------------------------
# The gate catching a real regression, against a real tree
# ---------------------------------------------------------------------------


def test_hardcoding_an_address_in_the_binding_module_fails_the_gate(tmp_path: Path) -> None:
    """The regression this gate exists to catch, staged in a copy of the real tree.

    Loopback is used deliberately: a check that only refused a wildcard would pass this,
    and an address the module can spell is one it can bind without the value type ever
    seeing it.
    """
    tree = _tree(tmp_path / "tree")
    declaration = declaration_of(REPO_ROOT)
    binding = tree / declaration.binding_module
    binding.write_text(
        binding.read_text(encoding="utf-8") + '\nHARDCODED = "127.0.0.1"\n', encoding="utf-8"
    )
    reports = tmp_path / "reports"
    assert run_endpoint(root=tree, reports=reports) == EXIT_GATE_FAILED
    document = load_manifest((reports / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert REASON_ADDRESS_HARDCODED in document["verdict"]["reasons"]  # type: ignore[index]


def test_a_wildcard_anywhere_in_the_package_fails_the_gate(tmp_path: Path) -> None:
    """The absence the value type cannot see, swept over the whole package."""
    tree = _tree(tmp_path / "tree")
    smuggled = tree / "src" / "globin" / "smuggled.py"
    smuggled.write_text('LISTEN = "0.0.0.0"\n', encoding="utf-8")
    reports = tmp_path / "reports"
    assert run_endpoint(root=tree, reports=reports) == EXIT_GATE_FAILED
    document = load_manifest((reports / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert REASON_WILDCARD_PRESENT in document["verdict"]["reasons"]  # type: ignore[index]


def test_growing_a_vocabulary_without_moving_a_budget_fails_the_gate(tmp_path: Path) -> None:
    """The arithmetic that earns the gate, against the real registry.

    A seventh route grows the `route` vocabulary, so every budget naming it is now below
    its own product — and this is the only check in the repository that notices.
    """
    tree = _tree(tmp_path / "tree")
    domain = tree / DOMAIN_MODULE
    domain.write_text(
        domain.read_text(encoding="utf-8").replace(
            '    UNKNOWN = "unknown"', '    UNKNOWN = "unknown"\n    INVENTED = "invented"'
        ),
        encoding="utf-8",
    )
    reports = tmp_path / "reports"
    assert run_endpoint(root=tree, reports=reports) == EXIT_GATE_FAILED
    document = load_manifest((reports / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert REASON_CARDINALITY_UNPROVEN in document["verdict"]["reasons"]  # type: ignore[index]


def test_a_deleted_test_module_fails_the_gate(tmp_path: Path) -> None:
    """A claim asserted in the contract and enforced nowhere."""
    tree = _tree(tmp_path / "tree")
    declaration = declaration_of(REPO_ROOT)
    (tree / declaration.tests["unit"]).unlink()
    reports = tmp_path / "reports"
    assert run_endpoint(root=tree, reports=reports) == EXIT_GATE_FAILED


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def test_the_module_can_be_started_as_a_module() -> None:
    """The wiring in `__main__`, which only starting the module can exercise.

    A subprocess rather than a coverage pragma: a pragma asserts that a line does not
    need testing, and this is the one line whose whole job is to be reachable.
    """
    finished = subprocess.run(
        [sys.executable, "-m", "tools.quality.endpoint"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert finished.returncode == EXIT_OK, finished.stdout + finished.stderr
    assert "endpoint: verdict passed" in finished.stdout


def test_an_unrecognised_word_is_refused() -> None:
    """Refused rather than ignored, which is every command line here."""
    finished = subprocess.run(
        [sys.executable, "-m", "tools.quality.endpoint", "nonsense"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert finished.returncode == 2
    assert "unrecognised argument" in finished.stdout
