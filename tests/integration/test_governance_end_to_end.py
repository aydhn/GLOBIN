"""The governance gate against a whole tree, correct and then deliberately broken.

The unit tests establish that each checker reaches the right answer from values.
This establishes that the gate wires them to the right inputs, writes a manifest
that reads back, and returns an exit code that matches its own verdict — the
three things a pure test cannot see.

**Every tree here is a temporary one**, and the lister is injected rather than
starting ``git``. A test that could only run against this repository would be a
test unable to describe a broken arrangement, which is most of what is worth
asserting.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.quality.governance import gate, manifest
from tools.quality.governance.plan import GovernanceError

DECLARATION = """\
schema = 1

[locations]
codeowners = ".github/CODEOWNERS"
security_policy = "SECURITY.md"
governance_policy = "docs/security/GOVERNANCE.md"
security_baseline = "docs/security/SECURITY_BASELINE.md"
vulnerability_runbook = "docs/security/VULNERABILITY_RESPONSE.md"
pull_request_template = ".github/pull_request_template.md"
issue_template_config = ".github/ISSUE_TEMPLATE/config.yml"
issue_templates = ".github/ISSUE_TEMPLATE/"
codeowners_candidates = ["CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"]

[security_policy]
required_sections = ["## How to report"]
reporting_url = "https://example.invalid/advisories/new"

[pull_request_template]
required_sections = ["## Security impact"]

[[sensitive_path]]
path = ".github/workflows/"
category = "continuous-integration"
reason = "The only place this repository executes code it did not write."

[[declared_capability]]
name = "code_owner_review"
state = "NOT_APPLICABLE"
authority = "docs/adr/0005-master-only-git-workflow.md"
reason = "There is no pull request to review."
"""

CODEOWNERS = "*                    @owner\n/.github/workflows/  @owner\n"

VANISHED_PATH = """
[[sensitive_path]]
path = "gone/"
category = "renamed"
reason = "A directory that has since moved."
"""

TREE: dict[str, str] = {
    "docs/engineering/governance.toml": DECLARATION,
    ".github/CODEOWNERS": CODEOWNERS,
    "SECURITY.md": (
        "# Security Policy\n\n## How to report\n\n"
        "Use https://example.invalid/advisories/new and never a public issue.\n"
    ),
    "docs/security/GOVERNANCE.md": "# Repository Governance\n",
    "docs/security/SECURITY_BASELINE.md": "# Security Baseline\n",
    "docs/security/VULNERABILITY_RESPONSE.md": "# Vulnerability Response\n",
    ".github/pull_request_template.md": "# Purpose\n\n## Security impact\n\nNothing changed.\n",
    ".github/ISSUE_TEMPLATE/config.yml": (
        "blank_issues_enabled: false\ncontact_links:\n"
        "  - url: https://example.invalid/advisories/new\n"
    ),
    ".github/ISSUE_TEMPLATE/bug_report.md": "# Bug\n\n## Expected behaviour\n",
    ".github/workflows/quality.yml": "name: Quality\n",
}


def build_tree(root: Path, overrides: dict[str, str | None] | None = None) -> tuple[str, ...]:
    """Write a governed tree and return the paths a lister would report.

    Args:
        root: Where to write it.
        overrides: Files to replace, or to remove when the value is ``None``.

    Returns:
        Every written path, repository-relative with forward slashes.
    """
    files = dict(TREE)
    for relative, content in (overrides or {}).items():
        if content is None:
            files.pop(relative, None)
        else:
            files[relative] = content
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return tuple(sorted(files))


def run(root: Path, paths: Sequence[str]) -> int:
    """Run the gate over a prepared tree with the lister injected."""
    return gate.run_governance(root=root, reports=root / "out", lister=lambda _root: tuple(paths))


def read_manifest(root: Path) -> dict[str, object]:
    """Read back what the gate wrote, through the reader that verifies the digest."""
    return manifest.load((root / "out" / gate.MANIFEST_NAME).read_text(encoding="utf-8"))


def test_a_governed_tree_passes_and_records_why(tmp_path: Path) -> None:
    paths = build_tree(tmp_path)
    assert run(tmp_path, paths) == gate.EXIT_OK

    document = read_manifest(tmp_path)
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["verdict"] == "passed"
    assert verdict["reasons"] == []

    findings = document["findings"]
    assert isinstance(findings, dict)
    assert findings, "a manifest recording no checks would pass by having asked nothing"
    assert all(
        isinstance(entry, dict) and entry["verdict"] == "passed" for entry in findings.values()
    )

    capability = document["capability"]
    assert isinstance(capability, dict)
    assert capability["code_owner_review"] == {
        "state": "NOT_APPLICABLE",
        "authority": "docs/adr/0005-master-only-git-workflow.md",
        "reason": "There is no pull request to review.",
    }, "a control decided by argument is recorded with the argument, not as a bare state"


def test_the_manifest_is_byte_stable_across_two_runs(tmp_path: Path) -> None:
    """Determinism is checked rather than asserted in prose.

    The gate builds its own manifest twice and compares; this establishes that
    two *invocations* agree too, which is what makes a digest comparable between
    a developer's machine and a runner.
    """
    paths = build_tree(tmp_path)
    run(tmp_path, paths)
    first = (tmp_path / "out" / gate.MANIFEST_NAME).read_bytes()
    run(tmp_path, paths)
    assert (tmp_path / "out" / gate.MANIFEST_NAME).read_bytes() == first


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        pytest.param(
            {"SECURITY.md": None},
            manifest.REASON_FILE_MISSING,
            id="the security policy is gone",
        ),
        pytest.param(
            {"CODEOWNERS": CODEOWNERS},
            manifest.REASON_CODEOWNERS_DUPLICATE,
            id="a second code-owners file appeared",
        ),
        pytest.param(
            {".github/CODEOWNERS": "*  @owner\n"},
            manifest.REASON_PATH_UNCOVERED,
            id="only the catch-all owns a sensitive path",
        ),
        pytest.param(
            {".github/CODEOWNERS": CODEOWNERS + "/nowhere/  @owner\n"},
            manifest.REASON_PATTERN_UNMATCHED,
            id="a pattern matches nothing",
        ),
        pytest.param(
            {"SECURITY.md": "# Security Policy\n\nhttps://example.invalid/advisories/new\n"},
            manifest.REASON_POLICY_INCOMPLETE,
            id="the policy lost the section naming its channel",
        ),
        pytest.param(
            {".github/pull_request_template.md": "# Purpose\n\nNothing.\n"},
            manifest.REASON_TEMPLATE_INCOMPLETE,
            id="the change template stopped asking about security",
        ),
        pytest.param(
            {
                ".github/ISSUE_TEMPLATE/report.md": (
                    "# Report\n\nGive us a proof of concept and the affected versions.\n"
                )
            },
            manifest.REASON_PUBLIC_SOLICITATION,
            id="a public template started collecting exploits",
        ),
        pytest.param(
            {"SECURITY.md": "# Security Policy\n\n## How to report\n\nEmail somebody.\n"},
            manifest.REASON_REPORTING_CHANNEL_DRIFT,
            id="the policy and the chooser disagree about the channel",
        ),
        pytest.param(
            {"docs/engineering/governance.toml": DECLARATION + VANISHED_PATH},
            manifest.REASON_SENSITIVE_PATH_ABSENT,
            id="a declared sensitive path no longer exists",
        ),
    ],
)
def test_each_way_the_arrangement_can_rot_is_caught(
    tmp_path: Path, overrides: dict[str, str | None], reason: str
) -> None:
    """Every one of these leaves a repository that looks governed and is not.

    None of them fails anything else in this repository, which is the whole
    argument for the gate existing.
    """
    paths = build_tree(tmp_path, overrides)
    assert run(tmp_path, paths) == gate.EXIT_GATE_FAILED

    verdict = read_manifest(tmp_path)["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["verdict"] == "failed"
    assert reason in verdict["reasons"]


def test_an_unreadable_declaration_still_leaves_a_manifest(tmp_path: Path) -> None:
    """A gate that failed silently and left nothing is indistinguishable from one that never ran."""
    paths = build_tree(tmp_path, {"docs/engineering/governance.toml": "schema = = 1"})
    assert run(tmp_path, paths) == gate.EXIT_GATE_FAILED

    verdict = read_manifest(tmp_path)["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["reasons"] == [manifest.REASON_DECLARATION_UNREADABLE]


def test_a_missing_declaration_is_reported_rather_than_defaulted(tmp_path: Path) -> None:
    paths = build_tree(tmp_path, {"docs/engineering/governance.toml": None})
    assert run(tmp_path, paths) == gate.EXIT_GATE_FAILED
    assert (tmp_path / "out" / gate.MANIFEST_NAME).is_file()


def test_an_ownerless_codeowners_line_is_a_failure_rather_than_a_crash(tmp_path: Path) -> None:
    """GitHub reads it as removing ownership, so the gate must survive to say so."""
    paths = build_tree(tmp_path, {".github/CODEOWNERS": CODEOWNERS + "/docs/\n"})
    assert run(tmp_path, paths) == gate.EXIT_GATE_FAILED

    verdict = read_manifest(tmp_path)["verdict"]
    assert isinstance(verdict, dict)
    assert manifest.REASON_CODEOWNERS_UNPARSEABLE in verdict["reasons"]


def test_a_tree_git_cannot_describe_is_unmeasured_rather_than_clean(tmp_path: Path) -> None:
    """An empty listing means the gate could not see the tree, not that the tree is fine.

    Unmeasured outranks failed and is never zero, which is the rule every gate
    here shares: doubt about what ran casts doubt on what passed.
    """
    build_tree(tmp_path)
    assert run(tmp_path, []) == gate.EXIT_UNMEASURED

    verdict = read_manifest(tmp_path)["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["verdict"] == "unmeasured"


def test_the_manifest_carries_no_absolute_path(tmp_path: Path) -> None:
    """It is uploaded as an artifact from a public repository.

    On the development host every absolute path contains the account holder's
    full name, so a published file holding one names a person.
    """
    paths = build_tree(tmp_path)
    run(tmp_path, paths)
    text = (tmp_path / "out" / gate.MANIFEST_NAME).read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert ":\\" not in text
    assert text.isascii()


def test_a_declaration_carrying_an_absolute_path_is_caught_before_publication(
    tmp_path: Path,
) -> None:
    """The manifest is uploaded as an artifact from a public repository.

    On the development host every absolute path contains the account holder's
    full name, so one reaching a reason field in ``governance.toml`` would be
    published under that person's name. The scanner the evidence gate already
    uses is run over this manifest for exactly that case.
    """
    leaky = DECLARATION.replace(
        'reason = "The only place this repository executes code it did not write."',
        'reason = "Observed at C:\\\\Users\\\\somebody\\\\GLOBIN while debugging."',
    )
    paths = build_tree(tmp_path, {"docs/engineering/governance.toml": leaky})
    assert run(tmp_path, paths) == gate.EXIT_GATE_FAILED

    verdict = read_manifest(tmp_path)["verdict"]
    assert isinstance(verdict, dict)
    assert manifest.REASON_MANIFEST_LEAKAGE in verdict["reasons"]


def test_the_commit_is_read_from_git_without_starting_a_process(tmp_path: Path) -> None:
    """A manifest can be produced in a tree where Git is not on the path.

    ``.git/HEAD`` is read directly, exactly as the supply gate does it. An
    unreadable one is recorded as ``unknown`` rather than invented.
    """
    sha = "a" * 40
    (tmp_path / ".git" / "refs" / "heads").mkdir(parents=True)
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
    (tmp_path / ".git" / "refs" / "heads" / "master").write_text(sha, encoding="utf-8")

    paths = build_tree(tmp_path)
    run(tmp_path, paths)
    run_section = read_manifest(tmp_path)["run"]
    assert isinstance(run_section, dict)
    assert run_section["commit"] == sha


def test_a_detached_head_and_a_missing_one_are_both_handled(tmp_path: Path) -> None:
    """A detached HEAD holds the SHA itself; an absent one is not guessed at."""
    sha = "b" * 40
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text(f"{sha}\n", encoding="utf-8")
    assert gate._sha(tmp_path) == sha  # noqa: SLF001 - the gate's own private reader

    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/gone\n", encoding="utf-8")
    assert gate._sha(tmp_path) == "unknown"  # noqa: SLF001 - as above


def test_a_directory_git_does_not_know_lists_nothing(tmp_path: Path) -> None:
    """The real lister, against a tree that is not a repository.

    ``git ls-files`` exits non-zero outside a work tree, and the gate reads that
    as an empty listing — which the caller reports as unmeasured rather than as
    a tree with nothing in it.
    """
    assert gate.tracked_paths(tmp_path) == ()


def test_a_path_contributes_every_directory_above_it() -> None:
    """A pattern naming a directory must be able to match one."""
    known = gate.with_directories(["a/b/c.txt", "d.txt"])
    assert known == ("a/", "a/b/", "a/b/c.txt", "d.txt")


def test_the_reader_refuses_the_gates_own_output_when_it_is_edited(tmp_path: Path) -> None:
    paths = build_tree(tmp_path)
    run(tmp_path, paths)
    target = tmp_path / "out" / gate.MANIFEST_NAME
    target.write_text(
        target.read_text(encoding="utf-8").replace('"passed"', '"failed"', 1),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(GovernanceError, match="digest"):
        read_manifest(tmp_path)
