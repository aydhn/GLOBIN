"""This repository's own lock, and the gate held to what it was added as.

Everything here is about the real tree rather than a synthetic one. The unit tests
establish that each judgement reaches the right answer from values; this
establishes that *this* lock is one those judgements pass, that the declaration
beside it describes this machine's contract, and that the gate is still the shape
`docs/engineering/QUALITY_GATES.md` says it is.

**Recomputed, not believed.** Every hash, every wheel tag and every cross-register
version below is derived from the lock's own contents. That is ADR-0054's whole
argument, and asserting it here is what keeps the argument true.
"""

import ast
import tomllib
from pathlib import Path

import pytest

from tests.support import git_committable_files
from tools.quality.commands import COMMANDS, find
from tools.quality.lock import gate, manifest, plan
from tools.quality.lock.gate import DELIVERED_PHASE, ROADMAP_TOTAL_PHASES, declaration_of, lock_of
from tools.quality.runtime.gate import DEVELOPMENT_LOCK
from tools.quality.supply.inventory import collect

LOCK_COMMAND = "lock"


@pytest.fixture(scope="module")
def declaration() -> plan.Declaration:
    """This repository's lock declaration."""
    return declaration_of()


@pytest.fixture(scope="module")
def lock() -> plan.Lock:
    """This repository's committed development lock."""
    return lock_of()


# ---------------------------------------------------------------------------
# The lock exists, is named as the standard requires, and is committed
# ---------------------------------------------------------------------------


def test_the_lock_is_named_as_pep_751_requires(declaration: plan.Declaration) -> None:
    """The name is not a choice.

    A lock is `pylock.toml` or `pylock.<name>.toml`, and `pip-audit --locked`
    globs exactly that at a project path. A file called anything else is a file
    every consumer ignores.
    """
    name = declaration.dev_path
    assert name == "pylock.dev.toml"
    assert name.startswith("pylock.")
    assert name.endswith(".toml")
    assert "/" not in name, "the lock lives at the repository root"


def test_the_lock_and_the_declaration_are_committable() -> None:
    """The `.gitignore`-depth trap Phase 018 fell into.

    A pattern without a leading slash matches at every depth, so a bare `lock/`
    somewhere would silently swallow `tools/quality/lock/` and the package would
    be absent from the clone that CI builds. Checked against Git's own answer.
    """
    committable = set(git_committable_files())
    assert "pylock.dev.toml" in committable
    assert "docs/engineering/lock-policy.toml" in committable
    package = {path for path in committable if path.startswith("tools/quality/lock/")}
    assert package, "the lock package is not committable"
    assert "tools/quality/lock/gate.py" in package


def test_nothing_under_the_run_directory_is_committable() -> None:
    """Evidence is regenerable, and `.globin/` is ignored before the first byte."""
    assert not [path for path in git_committable_files() if path.startswith(".globin/")]


# ---------------------------------------------------------------------------
# The lock says what it claims to say
# ---------------------------------------------------------------------------


def test_the_lock_announces_a_format_this_reader_implements(lock: plan.Lock) -> None:
    """A minor ahead of this reader would carry fields the gate would not check."""
    assert plan.version_problems(lock) == ()


def test_the_lock_was_written_by_the_declared_producer(
    lock: plan.Lock, declaration: plan.Declaration
) -> None:
    """And it installs the same producer that wrote it."""
    assert plan.producer_problems(lock, declaration) == ()


def test_every_package_is_reproducible(lock: plan.Lock) -> None:
    """Normalised, versioned, and served as an artefact rather than a source tree."""
    problems = [
        problem
        for package in lock.packages
        for problem in plan.package_problems(package, lock.path)
    ]
    assert not problems, problems
    assert plan.duplicate_packages(lock.packages) == ()


def test_every_artefact_carries_a_digest(lock: plan.Lock, declaration: plan.Declaration) -> None:
    """The one job a lock has.

    An unhashed entry installs whatever the URL happens to serve, and the file
    still looks exactly like a lock.
    """
    problems = [
        problem
        for package in lock.packages
        for problem in plan.hash_problems(package, declaration.policy, lock.path)
    ]
    assert not problems, problems


def test_every_artefact_is_served_over_https_from_the_declared_host(
    lock: plan.Lock, declaration: plan.Declaration
) -> None:
    """A lock is several hundred URLs, and one pointing elsewhere is unreadable by eye."""
    problems = [
        problem
        for package in lock.packages
        for problem in plan.artefact_problems(package, declaration.target, lock.path)
    ]
    assert not problems, problems


def test_no_artefact_url_carries_a_credential(lock: plan.Lock) -> None:
    """It would be committed, published and cached, and would look like every other URL.

    Asserted separately from the check above so the failure names this rather than
    a host mismatch — `SECURITY_BASELINE.md` treats a credential in a committed
    file as the thing that must never happen, not as one finding among several.
    """
    for package in lock.packages:
        for artefact in package.artefacts:
            assert artefact.url is not None
            assert "@" not in artefact.url.split("//", 1)[1].split("/", 1)[0]


def test_every_package_has_a_wheel_for_the_pinned_interpreter(
    lock: plan.Lock, declaration: plan.Declaration
) -> None:
    """Through Phase 018's tag matcher, called rather than reimplemented."""
    problems = [
        problem
        for package in lock.packages
        for problem in plan.compatibility_problems(package, declaration.target, lock.path)
    ]
    assert not problems, problems


def test_no_package_would_have_to_be_built_from_source(
    lock: plan.Lock, declaration: plan.Declaration
) -> None:
    """And any that did would name the phase answering for it."""
    problems = plan.source_problems(
        lock.packages,
        declaration.target,
        declaration.policy,
        declaration.gaps,
        delivered=DELIVERED_PHASE,
        total=ROADMAP_TOTAL_PHASES,
    )
    assert not problems, problems


def test_the_lock_is_not_empty(lock: plan.Lock) -> None:
    """`pip-audit --locked` raises on a lock recording no packages.

    So an empty one would not merely be useless, it would break the vulnerability
    gate — which is why no runtime lock is created while `project.dependencies` is
    empty.
    """
    assert len(lock.packages) > 1


# ---------------------------------------------------------------------------
# The declaration describes this machine and this project
# ---------------------------------------------------------------------------


def test_the_declared_target_matches_the_runtime_contract(
    repo_root: Path, declaration: plan.Declaration
) -> None:
    """A lock resolved for an interpreter nothing here runs is misleading, not stale."""
    contract = tomllib.loads(
        (repo_root / "docs" / "engineering" / "runtime-contract.toml").read_text(encoding="utf-8")
    )
    interpreter = contract["interpreter"]
    assert (
        plan.target_problems(
            declaration.target,
            implementation=interpreter["implementation"],
            minor_line=interpreter["minor_line"],
            architecture=interpreter["architecture"],
            free_threaded=interpreter["free_threaded"],
        )
        == ()
    )


def test_the_index_is_public(declaration: plan.Declaration) -> None:
    """No credential, no private mirror, nothing that would need one."""
    assert declaration.target.index == "https://pypi.org/simple"
    assert "@" not in declaration.target.index


def test_the_declared_roots_and_the_project_file_agree(
    repo_root: Path, declaration: plan.Declaration
) -> None:
    """In both directions, because each catches a mistake the other cannot."""
    assert plan.declaration_problems(declaration, collect(repo_root)) == ()


def test_every_declared_tool_is_locked_at_a_version_clearing_its_bound(
    repo_root: Path, lock: plan.Lock
) -> None:
    """The toolchain is covered, and covered by something the project admits."""
    assert plan.coverage_problems(lock, collect(repo_root)) == ()


def test_every_pin_and_hook_revision_agrees_with_the_lock(repo_root: Path, lock: plan.Lock) -> None:
    """Four registers, one version each.

    The hook case is the one that bites hardest: both halves pass on their own, so
    a developer commits through a hook calling a file clean and watches CI call it
    dirty with no diff between them.
    """
    assert plan.register_problems(lock, collect(repo_root)) == ()


def test_the_runtime_lock_statement_matches_the_project_file(
    repo_root: Path, declaration: plan.Declaration
) -> None:
    """The forward hook, checked against the state it describes."""
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == []
    assert declaration.runtime_locked is False
    assert plan.runtime_problems(declaration, collect(repo_root)) == ()


def test_the_declaration_records_that_the_producer_is_experimental(
    declaration: plan.Declaration,
) -> None:
    """`pip` labels both `lock` and `install -r pylock.toml` EXPERIMENTAL.

    Recorded rather than assumed away: it is the stated reason this gate
    recomputes every verdict, and the reason `bootstrap` keeps a `--from-pins`
    hand-crank.
    """
    assert declaration.producer.tool == "pip"
    assert declaration.producer.experimental is True


def test_bootstrap_and_the_declaration_spell_the_lock_the_same_way(
    declaration: plan.Declaration,
) -> None:
    """A tripwire rather than a second source.

    `tools/quality/runtime/gate.py` names the file it installs from, and the
    declaration names the file the gate checks. If those two ever disagree,
    bootstrap would install one lock while the gate verified another.
    """
    assert declaration.dev_path == DEVELOPMENT_LOCK


# ---------------------------------------------------------------------------
# The gate is what it was added as
# ---------------------------------------------------------------------------


def test_the_command_is_registered_and_starts_no_declared_tool() -> None:
    """`check` reads files. It launches nothing whose absence could go unnoticed."""
    command = find(LOCK_COMMAND)
    assert command is not None
    assert len(command.steps) == 1
    assert command.steps[0].modules == ()
    assert command.steps[0].argv == ("-m", "tools.quality.lock")


def test_the_command_sits_after_drift_and_before_the_mutating_ones() -> None:
    """Order is part of the contract, and the tail is ordered by phase."""
    names = [command.name for command in COMMANDS]
    assert names.index("drift") + 1 == names.index(LOCK_COMMAND)
    assert names.index(LOCK_COMMAND) < names.index("fix")


def test_the_gate_is_in_neither_fast_nor_full() -> None:
    """It writes an artefact, and `full` reports rather than produces.

    The assertions that must gate a commit are in this module, which the coverage
    step already runs.
    """
    for name in ("fast", "full"):
        command = find(name)
        assert command is not None
        assert LOCK_COMMAND not in {step.name for step in command.steps}


def test_the_gate_writes_only_inside_the_ignored_run_directory() -> None:
    """Everything it produces is regenerable, so nothing it produces is committed."""
    assert gate.OUTPUT_DIRECTORY == ".globin/lock"
    assert gate.OUTPUT_DIRECTORY.startswith(".globin/")


def test_the_manifest_names_the_phase_that_introduced_the_gate() -> None:
    """A reader asking which phase asked for this has an answer in the evidence."""
    assert manifest.PHASE == 20


def test_every_reason_the_gate_can_emit_is_declared() -> None:
    """Both directions, so neither a hole nor a claim about a check that does not exist.

    Read from the gate's own import list rather than from a second hand-written
    tuple: a reason imported and never used would still be declared, and a reason
    used without being imported would not compile.
    """
    source = Path(gate.__file__).read_text(encoding="utf-8")
    imported = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module == "tools.quality.lock.manifest"
        for alias in node.names
        if alias.name.startswith("REASON_")
    }
    emittable = {getattr(manifest, name) for name in imported}
    assert emittable, "the gate imports no reason codes"
    assert emittable <= manifest.REASONS
    assert manifest.REASONS - emittable == set(), "declared but unreachable"


def test_nothing_in_the_package_can_write_the_declaration_it_reads() -> None:
    """A declaration a tool rewrites is a mirror of that tool.

    `relock` prints the lines a person must change; changing them is theirs. The
    only paths this package writes are the run directory and the lock itself.
    """
    for module in Path(gate.__file__).parent.glob("*.py"):
        text = module.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "write_text" in line and "#" not in line.split("write_text")[0]:
                assert "CONFIGURATION_FILE" not in line, f"{module.name}: {line.strip()}"


def test_the_gate_summary_is_ascii(capsys: pytest.CaptureFixture[str]) -> None:
    """A Windows console encodes with the active code page.

    A character it cannot represent turns a report into a traceback.
    """
    gate.run_lock()
    assert capsys.readouterr().out.isascii()
