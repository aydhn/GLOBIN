"""The release gate composed, over trees built for the occasion.

Every test here builds a **synthetic repository** in ``tmp_path`` and runs the
real gate against it. Nothing reads this repository's own tree: a test that could
only run against the real one would be a test that cannot describe a broken
arrangement, and every failure path below is an arrangement this repository does
not have.

**Git is faked by writing `.git` rather than by running `git init`.** The commit
reader parses `.git/HEAD` directly, so a handful of files is enough, and the test
neither depends on Git being installed nor pays for a process. Where the gate
genuinely starts Git — the release preconditions — the runner is injected, and
the double is a hand-written callable that **runs out**: a double that keeps
answering after its script ends turns "the gate asked more questions than
expected" into a passing test.
"""

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from tools.quality.release import assets, gate, manifest
from tools.quality.release.plan import FOUNDATION_CATEGORIES, MATRICES, category_letter

VERSION_SOURCE = 'from x import y\n\n__version__ = "0.1.0"\n'

CHANGELOG = """\
# Changelog

## [Unreleased]

## [0.1.0] - 2026-08-15

The foundation baseline.
"""

RELEASE_NOTES = """\
changelog:
  categories:
    - title: Features
      labels:
        - enhancement
    - title: Other Changes
      labels:
        - "*"
"""

DOCUMENT = "# A document\n\nWith a line of prose in it.\n"


def declaration(*, extra: str = "", status: str = "PASS", blocking: str = "true") -> str:
    """A complete declaration: one criterion per category, so none is empty.

    Args:
        extra: Appended verbatim, for tests that add a broken criterion.
        status: The status given to the first category's criterion.
        blocking: Whether that criterion blocks, as TOML.

    Returns:
        The TOML text.
    """
    header = """\
schema = 1

[release]
version_source = "src/globin/__init__.py"
changelog = "CHANGELOG.md"
release_notes = ".github/release.yml"
policy = "docs/release/RELEASE_POLICY.md"
acceptance = "docs/release/FOUNDATION_ACCEPTANCE.md"
"""
    blocks = []
    for index, category in enumerate(FOUNDATION_CATEGORIES):
        blocks.append(f"""
[[criterion]]
id = "FND-{category_letter(MATRICES[0], category)}-01"
category = "{category}"
requirement = "A requirement for {category}."
evidence = ["CHANGELOG.md"]
blocking = {blocking if index == 0 else "true"}
status = "{status if index == 0 else "PASS"}"
reason = "A recorded reason."
""")
    return header + "".join(blocks) + extra


def environment_declaration() -> str:
    """A complete, valid environment matrix, with one criterion per category.

    Returns:
        The TOML text.

    The gate reads every entry of `MATRICES`, so a tree carrying only the
    foundation matrix is an incomplete tree rather than a smaller one. This is
    generated from the spec for the same reason the foundation one is: a
    fourteenth category must not need this file edited.
    """
    spec = MATRICES[1]
    blocks = ["schema = 1\n"]
    for category in spec.categories:
        blocks.append(f"""
[[criterion]]
id = "{spec.prefix}-{category_letter(spec, category)}-01"
category = "{category}"
requirement = "A requirement for {category}."
evidence = ["CHANGELOG.md"]
blocking = true
status = "PASS"
reason = "A recorded reason."
""")
    return "".join(blocks)


def build_tree(root: Path, *, declaration_text: str | None = None, **replacements: str) -> None:
    """Write a repository the gate can read.

    Args:
        root: Where to build it.
        declaration_text: The foundation acceptance declaration. Defaults to a
            valid one.
        replacements: Path-to-contents overrides, for tests that break one file.
    """
    files: dict[str, str] = {
        "docs/engineering/foundation-acceptance.toml": (
            declaration() if declaration_text is None else declaration_text
        ),
        "docs/engineering/environment-acceptance.toml": environment_declaration(),
        "src/globin/__init__.py": VERSION_SOURCE,
        "CHANGELOG.md": CHANGELOG,
        ".github/release.yml": RELEASE_NOTES,
        "docs/release/RELEASE_POLICY.md": DOCUMENT,
        "docs/release/FOUNDATION_ACCEPTANCE.md": DOCUMENT,
        "docs/release/ENVIRONMENT_ACCEPTANCE.md": DOCUMENT,
    }
    files.update(replacements)

    for relative, contents in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8", newline="\n")

    head = root / ".git" / "refs" / "heads"
    head.mkdir(parents=True, exist_ok=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
    (head / "master").write_text("b" * 40 + "\n", encoding="utf-8")
    (root / ".git" / "config").write_text("[core]\n\tbare = false\n", encoding="utf-8")


class ScriptedGit:
    """Answers a fixed script of Git questions, then refuses.

    Keyed by the first argument so a test can say what ``rev-parse`` returns
    without caring in what order the gate asks. An unscripted question is an
    assertion failure rather than a default, because a double that answers
    everything cannot detect the gate asking something it should not.
    """

    def __init__(self, answers: Mapping[str, str], *, failing: Sequence[str] = ()) -> None:
        """Script the answers, and optionally which of them exit non-zero."""
        self.answers = dict(answers)
        self.failing = set(failing)
        self.asked: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str], **_: object) -> "subprocess.CompletedProcess[str]":
        """Answer one scripted question, or fail loudly on an unscripted one."""
        arguments = tuple(argv)[1:]
        self.asked.append(arguments)
        key = " ".join(arguments)
        for scripted, answer in self.answers.items():
            if key.startswith(scripted):
                if scripted in self.failing:
                    return subprocess.CompletedProcess(list(argv), 1, "", "git said no")
                return subprocess.CompletedProcess(list(argv), 0, answer + "\n", "")
        msg = f"the gate asked Git something the script does not cover: {key}"
        raise AssertionError(msg)


def clean_git(branch: str = "master", *, sha: str = "c" * 40, status: str = "") -> ScriptedGit:
    """A repository on the release branch, clean, and level with its remote."""
    return ScriptedGit(
        {
            "rev-parse --abbrev-ref HEAD": branch,
            "status --porcelain": status,
            "rev-parse HEAD": sha,
            "rev-parse origin/master": sha,
        }
    )


def read_manifest(reports: Path) -> dict[str, object]:
    """The manifest the gate wrote, refused if it does not describe itself."""
    return manifest.load((reports / assets.MANIFEST_FILE).read_text(encoding="utf-8"))


def findings(document: Mapping[str, object]) -> dict[str, object]:
    """The findings section."""
    found = document["findings"]
    assert isinstance(found, dict)
    return found


def reasons(document: Mapping[str, object]) -> list[str]:
    """The reason codes the verdict carries."""
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    recorded = verdict["reasons"]
    assert isinstance(recorded, list)
    return recorded


# ---------------------------------------------------------------------------
# The passing case
# ---------------------------------------------------------------------------


def test_a_complete_contract_passes_and_publishes_every_asset(tmp_path: Path) -> None:
    build_tree(tmp_path)
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_OK

    document = read_manifest(reports)
    assert document["phase"] == manifest.PHASE
    run = document["run"]
    assert isinstance(run, dict)
    assert run["version"] == "0.1.0"
    assert run["tag"] == "v0.1.0"
    assert run["commit"] == "b" * 40
    assert reasons(document) == []

    for name in (assets.ACCEPTANCE_FILE, assets.MANIFEST_FILE, assets.CHECKSUM_FILE):
        assert (reports / name).is_file()


def test_two_runs_over_one_tree_produce_identical_bytes(tmp_path: Path) -> None:
    """The property the whole evidence model rests on.

    Checked here as well as inside the gate, because the gate's own check could itself be wrong.
    """
    build_tree(tmp_path)
    reports = tmp_path / "out"

    gate.run_release(root=tmp_path, reports=reports)
    first = (reports / assets.MANIFEST_FILE).read_bytes()
    sums = (reports / assets.CHECKSUM_FILE).read_bytes()

    gate.run_release(root=tmp_path, reports=reports)
    assert (reports / assets.MANIFEST_FILE).read_bytes() == first
    assert (reports / assets.CHECKSUM_FILE).read_bytes() == sums


def test_the_checksum_file_covers_the_manifest_but_not_itself(tmp_path: Path) -> None:
    build_tree(tmp_path)
    reports = tmp_path / "out"
    gate.run_release(root=tmp_path, reports=reports)

    recorded = (reports / assets.CHECKSUM_FILE).read_text(encoding="utf-8")
    names = [line.split("  ")[1] for line in recorded.splitlines()]
    assert assets.MANIFEST_FILE in names
    assert assets.CHECKSUM_FILE not in names


def test_the_manifest_records_asset_digests_but_not_its_own(tmp_path: Path) -> None:
    """A document cannot state a digest computed over itself.

    Between the manifest and SHA256SUMS every published byte is described exactly once.
    """
    build_tree(tmp_path)
    reports = tmp_path / "out"
    gate.run_release(root=tmp_path, reports=reports)

    run = read_manifest(reports)["run"]
    assert isinstance(run, dict)
    digests = run["assets"]
    assert isinstance(digests, dict)
    assert assets.ACCEPTANCE_FILE in digests
    assert assets.MANIFEST_FILE not in digests


def test_the_published_manifest_carries_no_absolute_path(tmp_path: Path) -> None:
    """An absolute path on this host carries the account holder's full name."""
    build_tree(tmp_path)
    reports = tmp_path / "out"
    gate.run_release(root=tmp_path, reports=reports)

    rendered = (reports / assets.MANIFEST_FILE).read_text(encoding="utf-8")
    assert str(tmp_path) not in rendered
    assert rendered.isascii()


# ---------------------------------------------------------------------------
# Failures in the declaration
# ---------------------------------------------------------------------------


def test_a_missing_declaration_fails_and_still_writes_a_manifest(tmp_path: Path) -> None:
    """A gate that left no artefact reads exactly like one that never ran."""
    build_tree(tmp_path)
    (tmp_path / "docs/engineering/foundation-acceptance.toml").unlink()
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_DECLARATION_UNREADABLE in reasons(read_manifest(reports))


def test_a_declaration_that_is_not_toml_fails(tmp_path: Path) -> None:
    build_tree(tmp_path, declaration_text="schema = = 1")
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_DECLARATION_UNREADABLE in reasons(read_manifest(reports))


def test_a_duplicate_criterion_identifier_fails(tmp_path: Path) -> None:
    extra = """
[[criterion]]
id = "FND-A-01"
category = "repository-foundation"
requirement = "A second criterion wearing the first one's name."
evidence = ["CHANGELOG.md"]
blocking = true
status = "PASS"
reason = "A recorded reason."
"""
    build_tree(tmp_path, declaration_text=declaration(extra=extra))
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_CRITERION_DUPLICATE in reasons(read_manifest(reports))


def test_a_criterion_filed_under_the_wrong_category_fails(tmp_path: Path) -> None:
    extra = """
[[criterion]]
id = "FND-A-02"
category = "release-readiness"
requirement = "Numbered A, filed under P."
evidence = ["CHANGELOG.md"]
blocking = true
status = "PASS"
reason = "A recorded reason."
"""
    build_tree(tmp_path, declaration_text=declaration(extra=extra))
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_CRITERION_MALFORMED in reasons(read_manifest(reports))


def test_a_category_with_no_criteria_fails(tmp_path: Path) -> None:
    """The matrix would claim a capability group it does not cover."""
    text = declaration()
    marker = f'category = "{FOUNDATION_CATEGORIES[-1]}"'
    trimmed = text[: text.rindex("[[criterion]]", 0, text.index(marker))]
    build_tree(tmp_path, declaration_text=trimmed)
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_CATEGORY_EMPTY in reasons(read_manifest(reports))


def test_a_criterion_naming_evidence_that_does_not_exist_fails(tmp_path: Path) -> None:
    extra = """
[[criterion]]
id = "FND-A-02"
category = "repository-foundation"
requirement = "Answered by a file nobody wrote."
evidence = ["docs/absent.md"]
blocking = true
status = "PASS"
reason = "A recorded reason."
"""
    build_tree(tmp_path, declaration_text=declaration(extra=extra))
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_EVIDENCE_MISSING in reasons(read_manifest(reports))


@pytest.mark.parametrize("status", ["FAIL", "BLOCKED", "NOT_APPLICABLE"])
def test_a_blocking_criterion_that_did_not_pass_fails(tmp_path: Path, status: str) -> None:
    """BLOCKED stops a release exactly as FAIL does. It is never a pass."""
    build_tree(tmp_path, declaration_text=declaration(status=status))
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_BLOCKING_UNMET in reasons(read_manifest(reports))


def test_a_non_blocking_criterion_that_did_not_pass_does_not_stop_a_release(
    tmp_path: Path,
) -> None:
    """FND-P-05 is the real instance: recorded, unavailable, not blocking."""
    build_tree(tmp_path, declaration_text=declaration(status="BLOCKED", blocking="false"))
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_OK
    document = read_manifest(reports)
    acceptance = document["acceptance"]
    assert isinstance(acceptance, dict)
    # Keyed by matrix prefix since Phase 032, because a total across two bands
    # answers no question anybody has. The broken criterion is the foundation
    # matrix's, and the environment one alongside it must stay clean.
    foundation = acceptance[MATRICES[0].prefix]
    assert isinstance(foundation, dict)
    unresolved = foundation["unresolved"]
    assert isinstance(unresolved, list)
    assert len(unresolved) == 1

    environment = acceptance[MATRICES[1].prefix]
    assert isinstance(environment, dict)
    assert environment["unresolved"] == []


# ---------------------------------------------------------------------------
# Failures in the version, the changelog and the documents
# ---------------------------------------------------------------------------


def test_an_unreadable_version_source_fails(tmp_path: Path) -> None:
    build_tree(tmp_path)
    (tmp_path / "src/globin/__init__.py").unlink()
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_VERSION_UNREADABLE in reasons(read_manifest(reports))


def test_a_source_declaring_no_version_fails(tmp_path: Path) -> None:
    build_tree(tmp_path, **{"src/globin/__init__.py": "VERSION = '1.0.0'\n"})
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_VERSION_UNREADABLE in reasons(read_manifest(reports))


@pytest.mark.parametrize("version", ["0.1", "1.0.0a1", "01.2.3", "1.0.0+local"])
def test_a_version_this_project_cannot_tag_fails(tmp_path: Path, version: str) -> None:
    build_tree(tmp_path, **{"src/globin/__init__.py": f'__version__ = "{version}"\n'})
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_VERSION_MALFORMED in reasons(read_manifest(reports))


def test_a_changelog_that_does_not_announce_the_version_fails(tmp_path: Path) -> None:
    """The source says 0.1.0 and the changelog has never heard of it."""
    build_tree(tmp_path, **{"CHANGELOG.md": "# Changelog\n\n## [Unreleased]\n\n## [0.2.0] - x\n"})
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_CHANGELOG_INCOMPLETE in reasons(read_manifest(reports))


def test_a_version_announced_twice_fails(tmp_path: Path) -> None:
    """What a careless re-run of the release tooling would produce."""
    doubled = CHANGELOG + "\n## [0.1.0] - 2026-08-16\n\nAgain.\n"
    build_tree(tmp_path, **{"CHANGELOG.md": doubled})
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_CHANGELOG_INCOMPLETE in reasons(read_manifest(reports))


@pytest.mark.parametrize(
    "document",
    ["docs/release/RELEASE_POLICY.md", "docs/release/FOUNDATION_ACCEPTANCE.md", "CHANGELOG.md"],
)
def test_a_missing_release_document_fails(tmp_path: Path, document: str) -> None:
    build_tree(tmp_path)
    (tmp_path / document).unlink()
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_DOCUMENT_MISSING in reasons(read_manifest(reports))


def test_a_release_notes_configuration_without_a_catch_all_fails(tmp_path: Path) -> None:
    text = (
        "changelog:\n  categories:\n    - title: Features\n      labels:\n        - enhancement\n"
    )
    build_tree(tmp_path, **{".github/release.yml": text})
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_NOTES_MALFORMED in reasons(read_manifest(reports))


def test_a_malformed_release_notes_configuration_fails(tmp_path: Path) -> None:
    build_tree(tmp_path, **{".github/release.yml": "not: a release configuration\n"})
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_NOTES_MALFORMED in reasons(read_manifest(reports))


# ---------------------------------------------------------------------------
# The release preconditions
# ---------------------------------------------------------------------------


def test_the_preconditions_are_not_checked_unless_asked_for(tmp_path: Path) -> None:
    """A CI checkout legitimately differs from a developer's working tree."""
    build_tree(tmp_path)
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_OK
    assert "repository_state" not in findings(read_manifest(reports))


def test_a_clean_tree_on_master_level_with_its_remote_passes(tmp_path: Path) -> None:
    build_tree(tmp_path)
    reports = tmp_path / "out"
    git = clean_git()

    code = gate.run_release(root=tmp_path, reports=reports, check_repository=True, runner=git)

    assert code == gate.EXIT_OK
    assert findings(read_manifest(reports))["repository_state"] == {
        "verdict": "passed",
        "problems": [],
    }
    assert git.asked


def test_a_release_attempted_from_another_branch_fails(tmp_path: Path) -> None:
    build_tree(tmp_path)
    reports = tmp_path / "out"

    code = gate.run_release(
        root=tmp_path, reports=reports, check_repository=True, runner=clean_git("feature/x")
    )

    assert code == gate.EXIT_GATE_FAILED
    assert manifest.REASON_BRANCH_UNEXPECTED in reasons(read_manifest(reports))


def test_a_dirty_working_tree_fails(tmp_path: Path) -> None:
    build_tree(tmp_path)
    reports = tmp_path / "out"
    git = clean_git(status=" M pyproject.toml\n?? untracked.py")

    code = gate.run_release(root=tmp_path, reports=reports, check_repository=True, runner=git)

    assert code == gate.EXIT_GATE_FAILED
    assert manifest.REASON_WORKTREE_DIRTY in reasons(read_manifest(reports))


def test_a_local_branch_ahead_of_its_remote_fails(tmp_path: Path) -> None:
    """A tag pushed from a tree ahead of its remote names an unfetchable commit."""
    build_tree(tmp_path)
    reports = tmp_path / "out"
    git = ScriptedGit(
        {
            "rev-parse --abbrev-ref HEAD": "master",
            "status --porcelain": "",
            "rev-parse HEAD": "d" * 40,
            "rev-parse origin/master": "e" * 40,
        }
    )

    code = gate.run_release(root=tmp_path, reports=reports, check_repository=True, runner=git)

    assert code == gate.EXIT_GATE_FAILED
    assert manifest.REASON_REMOTE_DIVERGED in reasons(read_manifest(reports))


def test_git_refusing_to_answer_is_unmeasured_rather_than_clean(tmp_path: Path) -> None:
    """'We could not tell' must not be quietly rounded down to 'fine'."""
    build_tree(tmp_path)
    reports = tmp_path / "out"
    git = ScriptedGit(
        {"rev-parse --abbrev-ref HEAD": "master"}, failing=["rev-parse --abbrev-ref HEAD"]
    )

    code = gate.run_release(root=tmp_path, reports=reports, check_repository=True, runner=git)

    assert code == gate.EXIT_UNMEASURED
    assert manifest.REASON_REPOSITORY_STATE_UNMEASURED in reasons(read_manifest(reports))


def test_git_being_absent_is_unmeasured_rather_than_clean(tmp_path: Path) -> None:
    build_tree(tmp_path)
    reports = tmp_path / "out"

    def absent(*_: object, **__: object) -> "subprocess.CompletedProcess[str]":
        raise OSError(2, "no git on this machine")

    code = gate.run_release(root=tmp_path, reports=reports, check_repository=True, runner=absent)

    assert code == gate.EXIT_UNMEASURED
    assert manifest.REASON_REPOSITORY_STATE_UNMEASURED in reasons(read_manifest(reports))


def test_git_failing_partway_through_is_unmeasured_rather_than_partly_clean(
    tmp_path: Path,
) -> None:
    """The branch that matters: the first question answered, the second refused.

    A gate that recorded what it had learned and called the rest fine would report
    a clean tree it never looked at.
    """
    build_tree(tmp_path)
    reports = tmp_path / "out"
    git = ScriptedGit(
        {"rev-parse --abbrev-ref HEAD": "master", "status --porcelain": ""},
        failing=["status --porcelain"],
    )

    code = gate.run_release(root=tmp_path, reports=reports, check_repository=True, runner=git)

    assert code == gate.EXIT_UNMEASURED
    assert manifest.REASON_REPOSITORY_STATE_UNMEASURED in reasons(read_manifest(reports))


def test_git_refusing_the_remote_question_is_unmeasured(tmp_path: Path) -> None:
    """`origin/master` is the question most likely to fail in a shallow clone."""
    build_tree(tmp_path)
    reports = tmp_path / "out"
    git = ScriptedGit(
        {
            "rev-parse --abbrev-ref HEAD": "master",
            "status --porcelain": "",
            "rev-parse HEAD": "d" * 40,
            "rev-parse origin/master": "",
        },
        failing=["rev-parse origin/master"],
    )

    code = gate.run_release(root=tmp_path, reports=reports, check_repository=True, runner=git)

    assert code == gate.EXIT_UNMEASURED
    assert manifest.REASON_REPOSITORY_STATE_UNMEASURED in reasons(read_manifest(reports))


# ---------------------------------------------------------------------------
# The branches a passing run never reaches
# ---------------------------------------------------------------------------


def test_an_unreadable_release_notes_configuration_fails(tmp_path: Path) -> None:
    build_tree(tmp_path)
    (tmp_path / ".github" / "release.yml").unlink()
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_NOTES_MALFORMED in reasons(read_manifest(reports))


def test_a_criterion_filed_under_an_invented_category_fails(tmp_path: Path) -> None:
    extra = """
[[criterion]]
id = "FND-A-02"
category = "invented"
requirement = "Filed under a category nobody declared."
evidence = ["CHANGELOG.md"]
blocking = true
status = "PASS"
reason = "A recorded reason."
"""
    build_tree(tmp_path, declaration_text=declaration(extra=extra))
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_CATEGORY_UNKNOWN in reasons(read_manifest(reports))


def test_a_criterion_answered_by_nothing_fails(tmp_path: Path) -> None:
    """The matrix certifies by evidence rather than by assertion."""
    extra = """
[[criterion]]
id = "FND-A-02"
category = "repository-foundation"
requirement = "Answered by nothing at all."
evidence = []
blocking = true
status = "PASS"
reason = "A recorded reason."
"""
    build_tree(tmp_path, declaration_text=declaration(extra=extra))
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_CRITERION_UNJUSTIFIED in reasons(read_manifest(reports))


def test_a_tag_that_does_not_name_its_version_back_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unreachable while `tag_for` and `version_for` are inverses, which is the point.

    The day somebody adds a suffix to one of them, this is the check that says so rather
    than a release tagged v0.1.0 that reports 0.1.
    """
    build_tree(tmp_path)
    reports = tmp_path / "out"
    monkeypatch.setattr(gate, "version_for", lambda _tag: "9.9.9")

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_VERSION_TAG_MISMATCH in reasons(read_manifest(reports))


def test_a_manifest_that_renders_differently_twice_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Determinism is checked rather than asserted, so the check itself needs a failing case.

    Without one, a gate whose comparison was inverted would look identical to a gate whose
    output was stable.
    """
    build_tree(tmp_path)
    reports = tmp_path / "out"
    renders = iter(range(1000))

    def drifting(document: dict[str, object]) -> str:
        # `manifest.render` rather than `gate.render_manifest`: the gate imports
        # it under that alias and does not re-export it, so reading it through
        # the gate is a private access mypy is right to refuse.
        return manifest.render({**document, "nonce": next(renders)})

    monkeypatch.setattr(gate, "render_manifest", drifting)

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED


def test_a_manifest_carrying_something_it_must_not_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The manifest is attached to a public release.

    An absolute path on this host carries the account holder's full name, so it is scanned for
    before publishing rather than after. The reason text is carried into the manifest only for
    criteria that did **not** pass, so the leak is staged on one of those. That is a smaller
    published surface than it might have been, and this test is what establishes the scan still
    covers it.
    """
    leaking = declaration(status="BLOCKED", blocking="false").replace(
        'reason = "A recorded reason."',
        'reason = "Checked against C:\\\\Users\\\\Someone\\\\private\\\\notes.txt"',
        1,
    )
    build_tree(tmp_path, declaration_text=leaking)
    reports = tmp_path / "out"

    assert gate.run_release(root=tmp_path, reports=reports) == gate.EXIT_GATE_FAILED
    document = read_manifest(reports)
    assert manifest.REASON_MANIFEST_LEAKAGE in reasons(document)
    assert "must not" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Reading the commit, and signing capability
# ---------------------------------------------------------------------------


def test_the_commit_is_read_without_starting_a_process(tmp_path: Path) -> None:
    build_tree(tmp_path)
    reports = tmp_path / "out"

    gate.run_release(root=tmp_path, reports=reports)

    run = read_manifest(reports)["run"]
    assert isinstance(run, dict)
    assert run["commit"] == "b" * 40


def test_a_detached_head_and_an_unreadable_one_are_both_handled(tmp_path: Path) -> None:
    build_tree(tmp_path)
    reports = tmp_path / "out"

    (tmp_path / ".git" / "HEAD").write_text("f" * 40 + "\n", encoding="utf-8")
    gate.run_release(root=tmp_path, reports=reports)
    run = read_manifest(reports)["run"]
    assert isinstance(run, dict)
    assert run["commit"] == "f" * 40

    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/gone\n", encoding="utf-8")
    gate.run_release(root=tmp_path, reports=reports)
    run = read_manifest(reports)["run"]
    assert isinstance(run, dict)
    assert run["commit"] == "unknown"


def test_a_host_with_no_signing_configuration_records_it_as_unavailable(tmp_path: Path) -> None:
    """Never described as signed.

    A manufactured signature would prove possession of a key created for the purpose, which is
    worth nothing and reads as worth something.
    """
    build_tree(tmp_path)
    reports = tmp_path / "out"

    gate.run_release(root=tmp_path, reports=reports)

    capability = read_manifest(reports)["capability"]
    assert isinstance(capability, dict)
    signing = capability["tag_signing"]
    assert isinstance(signing, dict)
    assert signing["state"] == manifest.SIGNING_UNAVAILABLE


def test_a_host_with_a_signing_key_configured_is_not_reported_as_verified(
    tmp_path: Path,
) -> None:
    """Configuring a key says the host could sign.

    Only an actual verification says a tag was signed, and the gate never claims the verified
    state.
    """
    build_tree(tmp_path)
    (tmp_path / ".git" / "config").write_text("[user]\n\tsigningkey = ABC123\n", encoding="utf-8")
    reports = tmp_path / "out"

    gate.run_release(root=tmp_path, reports=reports)

    capability = read_manifest(reports)["capability"]
    assert isinstance(capability, dict)
    signing = capability["tag_signing"]
    assert isinstance(signing, dict)
    assert signing["state"] == manifest.SIGNING_ANNOTATED
    assert signing["state"] != manifest.SIGNING_SIGNED
