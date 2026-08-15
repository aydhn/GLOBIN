"""What a workflow may fetch, asserted against text that breaks each rule.

Every checker in ``tools/quality/supply/workflows.py`` is exercised twice: once
against a reference that is correct, and once against one that is wrong in
exactly one way. A checker nobody has watched fail is a checker nobody has any
reason to believe — ``docs/TESTING_STRATEGY.md`` makes that a rule.

The broken workflows are Python strings, never files. ``check-yaml`` runs over
everything committed and a file under ``.github/workflows/`` is live to GitHub,
so a hostile workflow cannot exist on disk in this repository.
"""

from pathlib import Path

import pytest

from tools.quality.supply.workflows import (
    action_repository,
    installed_pins,
    remote_references,
    undigested_docker_references,
    undocumented_pins,
    unpinned_references,
    workflow_paths,
)

FULL_SHA = "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"

PINNED = f"""\
jobs:
  build:
    steps:
      - uses: actions/checkout@{FULL_SHA} # v5.1.0
"""


def _workflow(reference: str) -> str:
    """One step using a given reference.

    Args:
        reference: Whatever should follow ``uses:``.

    Returns:
        A workflow fragment containing exactly that one reference.
    """
    return f"jobs:\n  build:\n    steps:\n      - uses: {reference}\n"


def test_a_full_sha_with_a_version_comment_is_accepted() -> None:
    """The shape the policy requires, so the negatives below mean something."""
    assert not unpinned_references(PINNED)
    assert not undocumented_pins(PINNED)


@pytest.mark.parametrize(
    "reference",
    [
        pytest.param("actions/checkout@v5 # v5.1.0", id="mutable major tag"),
        pytest.param("actions/checkout@v5.1.0 # v5.1.0", id="mutable exact tag"),
        pytest.param("actions/checkout@main # v5.1.0", id="branch"),
        pytest.param(f"actions/checkout@{FULL_SHA[:7]} # v5.1.0", id="short sha"),
        pytest.param(f"actions/checkout@{FULL_SHA[:39]} # v5.1.0", id="thirty-nine characters"),
        pytest.param(f"actions/checkout@{FULL_SHA}a # v5.1.0", id="forty-one characters"),
        pytest.param(f"actions/checkout@{FULL_SHA.upper()} # v5.1.0", id="uppercase hex"),
    ],
)
def test_a_reference_that_is_not_a_full_commit_is_reported(reference: str) -> None:
    """A tag is a label its owner can move, and a short SHA is a prefix.

    Both are refused, and the boundary cases are checked either side: thirty-nine
    and forty-one characters must fail as surely as ``v5`` does, or the length
    rule is decorative.
    """
    assert unpinned_references(_workflow(reference))


@pytest.mark.parametrize(
    "reference",
    [
        pytest.param(f"actions/checkout@{FULL_SHA}", id="no comment at all"),
        pytest.param(f"actions/checkout@{FULL_SHA} # v5", id="bare major"),
        pytest.param(f"actions/checkout@{FULL_SHA} # v5.1", id="two parts"),
        pytest.param(f"actions/checkout@{FULL_SHA} # latest", id="not a version"),
    ],
)
def test_a_pin_without_a_readable_version_is_reported(reference: str) -> None:
    """Forty hex characters tell a reader nothing about what they are approving.

    ``v5`` is refused specifically: it is the ambiguity the pin exists to remove,
    so recording it beside the pin puts the ambiguity straight back.
    """
    assert undocumented_pins(_workflow(reference))


def test_a_local_action_is_not_an_external_dependency() -> None:
    """``./`` names something already fixed by the commit under test.

    It has no upstream to be pinned to, so it is excluded from the set rather
    than exempted from the rule — the difference matters, because an exemption
    would have to be maintained.
    """
    local = _workflow("./.github/actions/thing")
    assert not remote_references(local)
    assert not unpinned_references(local)
    assert not undocumented_pins(local)


def test_a_docker_action_is_judged_by_digest_rather_than_by_commit() -> None:
    """A Docker tag is mutable in exactly the way a Git tag is.

    It is also not a commit, so testing it against the Git pattern would report
    every correctly-digested image as unpinned.
    """
    tagged = _workflow("docker://alpine:3.20 # v3.20.0")
    assert undigested_docker_references(tagged)
    assert not unpinned_references(tagged), "a Docker reference is not judged as a Git one"

    digested = _workflow(f"docker://alpine@sha256:{'a' * 64} # v3.20.0")
    assert not undigested_docker_references(digested)


def test_this_repository_uses_no_docker_action(repo_root: Path) -> None:
    """Asserted so that adding one is a decision rather than an accident."""
    for path in workflow_paths(repo_root):
        assert not undigested_docker_references(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        pytest.param(f"actions/checkout@{FULL_SHA}", "actions/checkout", id="plain"),
        pytest.param(
            f"github/codeql-action/init@{FULL_SHA}", "github/codeql-action", id="subdirectory"
        ),
        pytest.param(
            f"github/codeql-action/analyze@{FULL_SHA}", "github/codeql-action", id="second subdir"
        ),
    ],
)
def test_a_subdirectory_action_reports_its_repository(reference: str, expected: str) -> None:
    """Two programs at one commit in one repository are one dependency.

    ``codeql-action/init`` and ``codeql-action/analyze`` are pinned to the same
    SHA and verified once. Recording them as two would double an inventory and
    make the manifest disagree with itself.
    """
    assert action_repository(reference) == expected


def test_installed_pins_reads_every_exactly_pinned_package() -> None:
    """The workflow's own pins, which the inventory compares against the extra."""
    text = """\
jobs:
  build:
    steps:
      - run: |
          python -m pip install --upgrade pip
          python -m pip install "ruff==0.15.14" "mypy==2.1.0"
"""
    assert installed_pins(text) == {"ruff": "0.15.14", "mypy": "2.1.0"}


def test_a_range_is_not_read_as_a_pin() -> None:
    """``>=`` is a resolution instruction, and what it resolves to is not in the text."""
    text = 'jobs:\n  b:\n    steps:\n      - run: python -m pip install "ruff>=0.6"\n'
    assert installed_pins(text) == {}


def test_two_jobs_pinning_one_package_differently_is_refused() -> None:
    """Four jobs install overlapping subsets of one toolchain, and they must agree.

    Picking a winner would hide the disagreement. The whole reason exact versions
    are written in every job is that CI's verdict should not depend on which job
    measured.
    """
    text = """\
jobs:
  one:
    steps:
      - run: python -m pip install "ruff==0.15.14"
  two:
    steps:
      - run: python -m pip install "ruff==0.14.0"
"""
    with pytest.raises(ValueError, match="must agree about the toolchain"):
        installed_pins(text)


def test_workflow_paths_are_sorted(repo_root: Path) -> None:
    """Directory order is a filesystem property, and an inventory must not depend on one."""
    names = [path.name for path in workflow_paths(repo_root)]
    assert names == sorted(names)
    assert len(names) > 1, "this repository has more than one workflow since Phase 014"
