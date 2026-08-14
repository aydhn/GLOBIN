"""Exercise the architecture review as the application actually assembles it.

The architecture tests substitute the contract source and the module source so
they can feed the checker a synthetic graph containing a deliberate violation.
That is the right way to prove the checker *can* fail, but it means those tests
never run the wiring: every collaborator is a double.

This level runs the real object graph — real TOML on disk, real source tree,
built by :func:`globin.runtime.composition.build_architecture_review` — so that
a fault in the wiring itself is caught. A composition root that returned a
review over the wrong directory would pass every architecture test in the
repository while checking nothing.

Still no network, no credentials and no exchange: an integration test in GLOBIN
means several components together, not several systems together.
"""

from pathlib import Path

import pytest

from globin.domain.architecture import ArchitectureReport, Layer
from globin.runtime.composition import (
    CONTRACT_RELATIVE_PATH,
    PACKAGE_RELATIVE_PATH,
    ROOT_PACKAGE,
    build_architecture_review,
)


@pytest.fixture(scope="module")
def report(repo_root: Path) -> ArchitectureReport:
    """The review of this repository, wired exactly as the application wires it."""
    return build_architecture_review(repo_root).run()


def test_the_composition_root_reads_the_paths_it_declares(repo_root: Path) -> None:
    """The constants are the wiring. If they point nowhere, the review is vacuous."""
    assert (repo_root / CONTRACT_RELATIVE_PATH).is_file()
    assert (repo_root / PACKAGE_RELATIVE_PATH).is_dir()
    assert ROOT_PACKAGE == "globin"


def test_the_wired_review_examines_the_real_package(repo_root: Path) -> None:
    """Guard against a review that passes because it found nothing to check.

    This is the failure mode a mocked test cannot see: point the composition
    root at an empty directory and every boundary assertion still passes.
    """
    review = build_architecture_review(repo_root)
    modules = review.module_source.modules()
    names = {item.module for item in modules}
    assert len(names) >= 10, f"the review only found {len(names)} modules; expected the package"
    for layer in Layer:
        expected = f"{ROOT_PACKAGE}.{layer.value}"
        assert expected in names, f"the review did not reach the {layer.value} layer"


def test_the_wired_review_reports_a_clean_repository(report: ArchitectureReport) -> None:
    detail = "\n  ".join(
        f"{item.module} -> {item.imported}: {item.rule}" for item in report.violations
    )
    assert report.is_clean, f"architecture boundary violations:\n  {detail}"


def test_the_wired_review_finds_no_import_cycle(report: ArchitectureReport) -> None:
    cycles = ["  " + " -> ".join([*cycle, cycle[0]]) for cycle in report.cycles]
    assert not report.cycles, "import cycles found:\n" + "\n".join(cycles)


def test_the_contract_loaded_from_disk_governs_every_layer(repo_root: Path) -> None:
    """The TOML on disk, not a fixture, must declare a policy for each layer."""
    contract = build_architecture_review(repo_root).contract_source.load()
    declared = {policy.layer for policy in contract.policies}
    assert declared == set(Layer)
