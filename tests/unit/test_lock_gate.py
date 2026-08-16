"""The sequencing, the I/O and the failure paths a passing run never reaches.

The pure judgements are `test_lock_plan.py`'s. What this establishes is that the
gate wires them to the right inputs, records what it did even when it could not
finish, and — the one property no pure test can see — that a lock's recorded
digest is a fact about content rather than about a checkout's line endings.

**Every child process is injected.** `relock` starts `pip`, which reaches an
index; the suite's offline guard patches sockets in *this* interpreter and a child
has its own view of the world, so a test that let the real thing run would sail
past the guard rather than be caught by it.
"""

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.quality.evidence.redaction import Finding
from tools.quality.execution.plan import Verdict
from tools.quality.lock import gate
from tools.quality.lock.gate import (
    CHECK,
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    INSTALLED,
    INTRINSIC_REASONS,
    RELOCK,
    UPGRADE,
    Runner,
    _constraints_text,
    _exit_code,
    _finding,
    _read,
    _sha,
    _verdict_of,
    run_lock,
)
from tools.quality.lock.gate import (
    _report as report,
)
from tools.quality.lock.gate import (
    _tail as tail,
)
from tools.quality.lock.manifest import (
    REASON_DECLARATION_INCOMPLETE,
    REASON_DECLARATION_UNREADABLE,
    REASON_FILE_UNREADABLE,
    REASON_MANIFEST_LEAKAGE,
    REASON_PACKAGE_MALFORMED,
    REASON_PRODUCER_UNEXPECTED,
    REASON_REFRESH_FAILED,
    REASON_TARGET_DIVERGED,
    REASON_VERSION_UNSUPPORTED,
    REASONS,
    load,
)
from tools.quality.lock.plan import Lock, LockedPackage, LockError, parse_lock

DIGEST = "a" * 64
SHA = "0123456789abcdef0123456789abcdef01234567"

LOCK = f"""\
lock-version = "1.0"
created-by = "pip"

[[packages]]
name = "ruff"
version = "0.15.14"

[[packages.wheels]]
name = "ruff-0.15.14-py3-none-win_amd64.whl"
url = "https://files.pythonhosted.org/packages/ab/ruff-0.15.14-py3-none-win_amd64.whl"

[packages.wheels.hashes]
sha256 = "{DIGEST}"
"""

DECLARATION = """\
schema = 1

[producer]
tool = "pip"
version = "26.1.1"
experimental = true

[target]
implementation = "CPython"
minor_line = "3.14"
architecture = "AMD64"
platform_tag = "win_amd64"
free_threaded = false
index = "https://pypi.org/simple"
artefact_host = "files.pythonhosted.org"
locked = 2026-08-16

[policy]
require_hashes = true
hash_algorithms = ["sha256"]
allow_source = false

[dev]
path = "pylock.dev.toml"
extra = "dev"
roots = ["ruff>=0.6"]

[runtime]
path = "pylock.toml"
locked = false
reason = "there are no runtime dependencies yet"

[project]
distribution = "globin"
installed = false

[environment]
seeded = ["pip"]
"""

CONTRACT = """\
schema = 1

[interpreter]
implementation = "CPython"
minor_line = "3.14"
minimum_patch = "3.14.0"
architecture = "AMD64"
pointer_bits = 64
free_threaded = false
allow_prerelease = true

[host]
system = "Windows"
minimum_release = "10"

[environment]
directory = ".venv"
system_site_packages = false
"""

PYPROJECT = """\
[project]
name = "globin"
version = "0.1.0"
dependencies = []

[project.optional-dependencies]
dev = ["ruff>=0.6"]
"""

WORKFLOW = """\
name: Quality
on: [push]
jobs:
  quality:
    steps:
      - run: python -m pip install "ruff==0.15.14"
"""

PRE_COMMIT = """\
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.14
    hooks:
      - id: ruff
"""


RUNTIME_LOCK = f"""\
lock-version = "1.0"
created-by = "pip"

[[packages]]
name = "psutil"
version = "7.2.2"

[[packages.wheels]]
name = "psutil-7.2.2-cp37-abi3-win_amd64.whl"
url = "https://files.pythonhosted.org/packages/b4/psutil-7.2.2-cp37-abi3-win_amd64.whl"

[packages.wheels.hashes]
sha256 = "{DIGEST}"
"""

RUNTIME_DECLARATION = DECLARATION.replace(
    """\
[runtime]
path = "pylock.toml"
locked = false
reason = "there are no runtime dependencies yet"
""",
    """\
[runtime]
path = "pylock.toml"
locked = true
extra = ""
reason = "one runtime dependency, locked beside it"
roots = ["psutil>=7.2.2"]
""",
)

RUNTIME_PYPROJECT = PYPROJECT.replace("dependencies = []", 'dependencies = ["psutil>=7.2.2"]')


def build_tree(
    root: Path,
    *,
    lock: str | None = LOCK,
    declaration: str | None = DECLARATION,
    pyproject: str = PYPROJECT,
    runtime_lock: str | None = None,
) -> None:
    """Write a tree the lock gate can judge.

    Args:
        root: Where to write it.
        lock: The development lock, or ``None`` to omit it.
        declaration: The lock declaration, or ``None`` to omit it.
        pyproject: The project file, so a tree can declare runtime dependencies.
        runtime_lock: The runtime lock, or ``None`` to omit it.
    """
    engineering = root / "docs" / "engineering"
    engineering.mkdir(parents=True, exist_ok=True)
    (engineering / "runtime-contract.toml").write_text(CONTRACT, encoding="utf-8", newline="\n")
    if declaration is not None:
        (engineering / "lock-policy.toml").write_text(declaration, encoding="utf-8", newline="\n")

    (root / "pyproject.toml").write_text(pyproject, encoding="utf-8", newline="\n")
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "quality.yml").write_text(WORKFLOW, encoding="utf-8", newline="\n")
    (root / ".pre-commit-config.yaml").write_text(PRE_COMMIT, encoding="utf-8", newline="\n")

    if lock is not None:
        (root / "pylock.dev.toml").write_text(lock, encoding="utf-8", newline="\n")
    if runtime_lock is not None:
        (root / "pylock.toml").write_text(runtime_lock, encoding="utf-8", newline="\n")


def run(root: Path, **options: object) -> int:
    """Run the gate over a prepared tree, writing its evidence inside it."""
    return run_lock(root=root, reports=root / "out", **options)  # type: ignore[arg-type]


def manifest_of(root: Path) -> dict[str, object]:
    """The manifest the run wrote, verified against its own digest."""
    return load((root / "out" / gate.MANIFEST_NAME).read_text(encoding="utf-8"))


def reasons_of(document: dict[str, object]) -> list[str]:
    """The reason codes the manifest records."""
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    return list(verdict["reasons"])


def completed(returncode: int = 0, stderr: str = "") -> "subprocess.CompletedProcess[str]":
    """What an injected child reports."""
    return subprocess.CompletedProcess([], returncode, stdout="", stderr=stderr)


# ---------------------------------------------------------------------------
# The happy path, and what it records
# ---------------------------------------------------------------------------


def test_a_coherent_tree_passes_and_records_what_it_checked(tmp_path: Path) -> None:
    """The control, and the shape of the evidence."""
    build_tree(tmp_path)
    assert run(tmp_path) == EXIT_OK
    document = manifest_of(tmp_path)
    run_section = document["run"]
    assert isinstance(run_section, dict)
    assert run_section["mode"] == CHECK
    assert run_section["declaration"] == "docs/engineering/lock-policy.toml"
    lock_section = run_section["lock"]
    assert isinstance(lock_section, dict)
    assert lock_section["packages"] == 1
    assert lock_section["artefacts"] == 1
    assert lock_section["hashed"] == 1


def test_the_recorded_lock_digest_is_the_same_for_a_crlf_and_an_lf_checkout(
    tmp_path: Path,
) -> None:
    """The whole reason the digest is over normalised text.

    `pip` writes the lock without controlling line endings, so on Windows it emits
    CRLF where `.gitattributes` stores LF. A digest over raw bytes would differ
    between two checkouts of one commit, and the determinism check would be
    measuring a Git setting rather than a dependency set.
    """
    unix, windows = tmp_path / "unix", tmp_path / "windows"
    build_tree(unix)
    build_tree(windows)
    (windows / "pylock.dev.toml").write_bytes(LOCK.replace("\n", "\r\n").encode("utf-8"))

    assert run(unix) == EXIT_OK
    assert run(windows) == EXIT_OK

    def digest_of(root: Path) -> object:
        section = manifest_of(root)["run"]
        assert isinstance(section, dict)
        lock_section = section["lock"]
        assert isinstance(lock_section, dict)
        return lock_section["digest"]

    assert digest_of(unix) == digest_of(windows)


def test_two_runs_over_one_tree_produce_the_same_manifest(tmp_path: Path) -> None:
    """No wall clock, so the same tree yields the same bytes on any day."""
    build_tree(tmp_path)
    run(tmp_path)
    first = (tmp_path / "out" / gate.MANIFEST_NAME).read_text(encoding="utf-8")
    run(tmp_path)
    assert (tmp_path / "out" / gate.MANIFEST_NAME).read_text(encoding="utf-8") == first


def test_the_manifest_carries_no_absolute_path(tmp_path: Path) -> None:
    """No absolute path reaches the evidence.

    It is uploaded from a public repository, and every absolute path on the
    development host carries the account holder's name.
    """
    build_tree(tmp_path)
    run(tmp_path)
    text = (tmp_path / "out" / gate.MANIFEST_NAME).read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert "C:\\\\" not in text


# ---------------------------------------------------------------------------
# Failures that still leave evidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        pytest.param({"declaration": None}, REASON_DECLARATION_UNREADABLE, id="no-declaration"),
        pytest.param(
            {"declaration": "schema = 9\n"}, REASON_DECLARATION_UNREADABLE, id="wrong-schema"
        ),
        pytest.param({"lock": None}, REASON_FILE_UNREADABLE, id="no-lock"),
        pytest.param({"lock": "not toml"}, REASON_FILE_UNREADABLE, id="unparsable-lock"),
    ],
)
def test_a_run_that_cannot_get_as_far_as_checking_still_writes_a_manifest(
    tmp_path: Path, kwargs: dict[str, object], reason: str
) -> None:
    """A gate that failed silently is indistinguishable from one that never ran."""
    build_tree(tmp_path, **kwargs)  # type: ignore[arg-type]
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert reason in reasons_of(manifest_of(tmp_path))


def test_an_unreadable_runtime_contract_is_reported_rather_than_skipped(tmp_path: Path) -> None:
    """The target cannot be compared against a contract nobody can read."""
    build_tree(tmp_path)
    (tmp_path / "docs" / "engineering" / "runtime-contract.toml").unlink()
    assert run(tmp_path) == EXIT_GATE_FAILED


# ---------------------------------------------------------------------------
# The commit, read without a process
# ---------------------------------------------------------------------------


def test_a_detached_head_is_read(tmp_path: Path) -> None:
    """Read from `.git` directly, so a manifest can be produced without Git."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text(SHA, encoding="utf-8", newline="\n")
    assert _sha(tmp_path) == SHA


def test_a_symbolic_head_is_followed(tmp_path: Path) -> None:
    """The ordinary case: HEAD names a ref and the ref holds the object name."""
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8", newline="\n")
    (git / "refs" / "heads" / "master").write_text(SHA, encoding="utf-8", newline="\n")
    assert _sha(tmp_path) == SHA


@pytest.mark.parametrize(
    "setup",
    [
        pytest.param("none", id="no-git"),
        pytest.param("short", id="not-an-object-name"),
        pytest.param("dangling", id="ref-that-does-not-exist"),
    ],
)
def test_a_commit_that_cannot_be_read_is_recorded_as_unknown(tmp_path: Path, setup: str) -> None:
    """Recorded as unknown rather than invented."""
    if setup != "none":
        (tmp_path / ".git").mkdir()
        text = "abc\n" if setup == "short" else "ref: refs/heads/gone\n"
        (tmp_path / ".git" / "HEAD").write_text(text, encoding="utf-8", newline="\n")
    assert _sha(tmp_path) == "unknown"


# ---------------------------------------------------------------------------
# The environment comparison
# ---------------------------------------------------------------------------


def test_comparing_an_environment_from_outside_it_is_unmeasured_rather_than_passed(
    tmp_path: Path,
) -> None:
    """A gate answering about some other interpreter with this one's authority.

    The synthetic tree has no `.venv`, and the suite is not running from one
    inside it, so the comparison cannot be made. ADR-0045: a thing that could not
    be measured is never a pass.
    """
    build_tree(tmp_path)
    assert run(tmp_path, mode=INSTALLED) == EXIT_UNMEASURED
    document = manifest_of(tmp_path)
    findings = document["findings"]
    assert isinstance(findings, dict)
    environment = findings["environment"]
    assert isinstance(environment, dict)
    assert environment["verdict"] == str(Verdict.UNMEASURED)


def test_the_installed_distributions_reader_names_this_interpreters_own_packages() -> None:
    """Read through `importlib.metadata`, so it starts no child and opens no socket."""
    found = gate.installed_distributions()
    assert found
    assert all(isinstance(name, str) for name in found)
    assert all(isinstance(version, str) for version in found.values())


# ---------------------------------------------------------------------------
# Regeneration
# ---------------------------------------------------------------------------


def test_a_pip_that_cannot_be_started_is_reported_rather_than_raised(tmp_path: Path) -> None:
    """A traceback out of a gate is a gate that produced no evidence."""
    build_tree(tmp_path)

    def refuse(*_args: object, **_kwargs: object) -> "subprocess.CompletedProcess[str]":
        msg = "no pip"
        raise OSError(msg)

    assert run(tmp_path, mode=RELOCK, runner=refuse) == EXIT_GATE_FAILED
    assert REASON_REFRESH_FAILED in reasons_of(manifest_of(tmp_path))


def test_a_pip_that_exits_non_zero_is_reported(tmp_path: Path) -> None:
    """The common case: a resolution nobody can satisfy."""
    build_tree(tmp_path)
    assert (
        run(
            tmp_path,
            mode=RELOCK,
            runner=lambda *_a, **_k: completed(returncode=1, stderr="ResolutionImpossible"),
        )
        == EXIT_GATE_FAILED
    )
    assert REASON_REFRESH_FAILED in reasons_of(manifest_of(tmp_path))


def test_a_pip_that_reports_success_and_writes_nothing_is_reported(tmp_path: Path) -> None:
    """Success with no artefact is not success."""
    build_tree(tmp_path)
    assert run(tmp_path, mode=RELOCK, runner=lambda *_a, **_k: completed()) == EXIT_GATE_FAILED
    assert REASON_REFRESH_FAILED in reasons_of(manifest_of(tmp_path))


def _writer(text: str) -> Runner:
    """An injected pip that writes the given lock to the requested output path."""

    def write(argv: list[str], **_kwargs: object) -> "subprocess.CompletedProcess[str]":
        output = Path(argv[argv.index("--output") + 1])
        output.write_text(text, encoding="utf-8", newline="\n")
        return completed()

    return write


def test_a_regenerated_lock_that_passes_is_kept(tmp_path: Path) -> None:
    """And the committed file is what changed."""
    build_tree(tmp_path)
    moved = LOCK.replace("0.15.14", "0.16.3")
    assert run(tmp_path, mode=RELOCK, runner=_writer(moved)) != EXIT_UNMEASURED
    assert (tmp_path / "pylock.dev.toml").read_text(encoding="utf-8") == moved


def test_a_regenerated_lock_that_is_unsound_is_refused_and_set_aside(tmp_path: Path) -> None:
    """A tool that overwrote a good lock with a bad one made the problem worse.

    Unsound means wrong *about the lock* — here, an artefact with no digest.
    """
    build_tree(tmp_path)
    unhashed = LOCK.replace(f'\n[packages.wheels.hashes]\nsha256 = "{DIGEST}"\n', "\n")
    assert run(tmp_path, mode=RELOCK, runner=_writer(unhashed)) == EXIT_GATE_FAILED
    assert (tmp_path / "pylock.dev.toml").read_text(encoding="utf-8") == LOCK
    assert (tmp_path / "out" / gate.REJECTED_NAME).read_text(encoding="utf-8") == unhashed


def test_a_regenerated_lock_that_only_diverges_from_the_registers_is_kept(
    tmp_path: Path,
) -> None:
    """Otherwise the pins could never be brought into line with it.

    A fresh resolution moves versions; that is what running it is *for*. Refusing
    to keep the lock until the workflow pins already matched would mean the pins
    could never be edited, because the lock they must be edited to match would
    never exist. The exit code still reports the divergence.
    """
    build_tree(tmp_path)
    moved = LOCK.replace("0.15.14", "0.16.3")
    assert run(tmp_path, mode=RELOCK, runner=_writer(moved)) == EXIT_GATE_FAILED
    assert (tmp_path / "pylock.dev.toml").read_text(encoding="utf-8") == moved
    assert not (tmp_path / "out" / gate.REJECTED_NAME).exists()


def test_a_regeneration_that_changes_nothing_writes_nothing(tmp_path: Path) -> None:
    """Byte-identical output leaves the file's modification time alone."""
    build_tree(tmp_path)
    before = (tmp_path / "pylock.dev.toml").stat().st_mtime_ns
    assert run(tmp_path, mode=RELOCK, runner=_writer(LOCK)) == EXIT_OK
    assert (tmp_path / "pylock.dev.toml").stat().st_mtime_ns == before


def test_an_upgrade_needs_a_committed_lock_to_hold_the_others_at(tmp_path: Path) -> None:
    """There is nothing to constrain against."""
    build_tree(tmp_path, lock=None)
    assert run(tmp_path, mode=UPGRADE, only=("ruff",), runner=_writer(LOCK)) == EXIT_GATE_FAILED


# ---------------------------------------------------------------------------
# The runtime lock, which until Phase 024 this package could neither regenerate
# nor check against what had been declared
# ---------------------------------------------------------------------------


def _runtime_tree(root: Path, runtime_lock: str | None = RUNTIME_LOCK) -> None:
    """A tree that declares one runtime dependency and locks it."""
    build_tree(
        root,
        declaration=RUNTIME_DECLARATION,
        pyproject=RUNTIME_PYPROJECT,
        runtime_lock=runtime_lock,
    )


def _sequence_writer(texts: Sequence[str]) -> Runner:
    """An injected pip that writes a different lock on each successive call.

    One run now resolves twice — the development roots, then the runtime ones —
    so a writer that answers with the same text both times cannot tell the two
    apart, and a test using it would pass whichever lock the gate wrote.
    """
    remaining = list(texts)

    def write(argv: list[str], **_kwargs: object) -> "subprocess.CompletedProcess[str]":
        output = Path(argv[argv.index("--output") + 1])
        output.write_text(remaining.pop(0), encoding="utf-8", newline="\n")
        return completed()

    return write


def test_a_declared_runtime_dependency_the_runtime_lock_omits_fails_the_gate(
    tmp_path: Path,
) -> None:
    """The hole Phase 024 fell into, pinned as a test rather than as a comment.

    Every other runtime finding asks whether `pylock.toml` is sound in itself.
    None of them notices a package `pyproject.toml` declares and the lock does
    not, which is the exact state that returned a clean `passed` when `psutil`
    was declared and the lock was left alone.
    """
    build_tree(
        tmp_path,
        declaration=RUNTIME_DECLARATION,
        pyproject=RUNTIME_PYPROJECT,
        runtime_lock=LOCK,
    )
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert REASON_DECLARATION_INCOMPLETE in reasons_of(manifest_of(tmp_path))


def test_a_runtime_lock_that_covers_its_declaration_passes(tmp_path: Path) -> None:
    """The other direction, so the check above is not merely always-failing."""
    _runtime_tree(tmp_path)
    assert run(tmp_path) == EXIT_OK


def test_a_relock_regenerates_the_runtime_lock_as_well(tmp_path: Path) -> None:
    """Both locks, one command.

    Until Phase 024 `relock` resolved only the development roots, so a repository
    with runtime dependencies had no supported way to move them at all — and
    `DEPENDENCY_LOCKING.md` is explicit that a lock is never edited by hand.
    """
    _runtime_tree(tmp_path)
    moved = RUNTIME_LOCK.replace("7.2.2", "7.2.3")
    assert run(tmp_path, mode=RELOCK, runner=_sequence_writer([LOCK, moved])) != EXIT_UNMEASURED
    assert (tmp_path / "pylock.dev.toml").read_text(encoding="utf-8") == LOCK
    assert (tmp_path / "pylock.toml").read_text(encoding="utf-8") == moved


def test_a_refused_runtime_candidate_leaves_the_committed_runtime_lock_alone(
    tmp_path: Path,
) -> None:
    """And is set aside under its own name, not the development one's."""
    _runtime_tree(tmp_path)
    unhashed = RUNTIME_LOCK.replace(f'\n[packages.wheels.hashes]\nsha256 = "{DIGEST}"\n', "\n")
    assert run(tmp_path, mode=RELOCK, runner=_sequence_writer([LOCK, unhashed])) == EXIT_GATE_FAILED
    assert (tmp_path / "pylock.toml").read_text(encoding="utf-8") == RUNTIME_LOCK
    rejected = tmp_path / "out" / gate.REJECTED_RUNTIME_NAME
    assert rejected.read_text(encoding="utf-8") == unhashed


def test_the_runtime_resolution_is_not_constrained_by_the_workflow_pins(tmp_path: Path) -> None:
    """The registers have no opinion about `project.dependencies`.

    `.github/workflows/` pins the tools a job installs and names nothing in the
    runtime set, so holding those pins over a runtime resolution would constrain
    it with a register that is not about it. The producer is dropped for the same
    reason: pip writes the lock and appears in no runtime one.
    """
    _runtime_tree(tmp_path)
    seen: list[str] = []
    writer = _sequence_writer([LOCK, RUNTIME_LOCK])

    def record(argv: list[str], **kwargs: object) -> "subprocess.CompletedProcess[str]":
        if "--constraint" in argv:
            seen.append(Path(argv[argv.index("--constraint") + 1]).read_text(encoding="utf-8"))
        else:
            seen.append("")
        return writer(argv, **kwargs)

    run(tmp_path, mode=RELOCK, runner=record)
    assert len(seen) == 2
    assert "ruff==0.15.14" in seen[0]
    assert "ruff" not in seen[1]
    assert "pip==" not in seen[1]


def test_the_resolution_holds_the_workflow_pins_and_the_producer(tmp_path: Path) -> None:
    """A relock records the transitive set; it does not upgrade the chosen tools.

    An unconstrained resolution takes the newest of everything, including the
    seven tools somebody pinned after measuring with them, and the producer that
    wrote the file. Both are held, and asserted here through the constraints file
    the gate hands to pip.
    """
    build_tree(tmp_path)
    seen: list[str] = []

    def record(argv: list[str], **_kwargs: object) -> "subprocess.CompletedProcess[str]":
        constraint = Path(argv[argv.index("--constraint") + 1])
        seen.append(constraint.read_text(encoding="utf-8"))
        return _writer(LOCK)(argv)

    run(tmp_path, mode=RELOCK, runner=record)
    assert seen
    assert "ruff==0.15.14" in seen[0]
    assert "pip==26.1.1" in seen[0]


def test_an_upgrade_drops_the_named_package_from_the_constraints() -> None:
    """That is what lets one package move while its neighbours stay put."""
    lock = Lock(
        path="pylock.dev.toml",
        lock_version="1.0",
        created_by="pip",
        packages=(
            LockedPackage("ruff", "0.15.14", (), None, None),
            LockedPackage("mypy", "2.1.0", (), None, None),
        ),
    )
    text = _constraints_text(lock, {}, ("ruff",))
    assert "mypy==2.1.0" in text
    assert "ruff==" not in text


def test_the_producer_is_held_even_when_it_was_named_for_upgrade() -> None:
    """Moving it is an edit to the declaration followed by a relock.

    Otherwise `upgrade pip` would lock a producer that never wrote the file, and
    `[producer] version` would describe nothing.
    """
    lock = Lock(
        path="pylock.dev.toml",
        lock_version="1.0",
        created_by="pip",
        packages=(LockedPackage("pip", "26.1.1", (), None, None),),
    )
    assert "pip==26.1.1" in _constraints_text(lock, {}, ("pip",), ("pip", "26.1.1"))


def test_a_workflow_pin_overrides_a_stale_locked_version_in_the_constraints() -> None:
    """The pin is the reviewed statement; the lock is the thing being corrected."""
    lock = Lock(
        path="pylock.dev.toml",
        lock_version="1.0",
        created_by="pip",
        packages=(LockedPackage("ruff", "0.15.14", (), None, None),),
    )
    text = _constraints_text(lock, {"ruff": "0.16.3"}, ())
    assert "ruff==0.16.3" in text
    assert "ruff==0.15.14" not in text


# ---------------------------------------------------------------------------
# The small pieces
# ---------------------------------------------------------------------------


def test_an_unmeasured_check_that_found_nothing_is_unmeasured_not_passed() -> None:
    """The order in `_finding` matters, and this is what pins it."""
    assert _finding((), measured=False)["verdict"] == str(Verdict.UNMEASURED)
    assert _finding(())["verdict"] == str(Verdict.PASSED)
    assert _finding(("a problem",))["verdict"] == str(Verdict.FAILED)


@pytest.mark.parametrize(
    ("verdict", "code"),
    [
        pytest.param(Verdict.PASSED, EXIT_OK, id="passed"),
        pytest.param(Verdict.FAILED, EXIT_GATE_FAILED, id="failed"),
        pytest.param(Verdict.UNMEASURED, EXIT_UNMEASURED, id="unmeasured"),
    ],
)
def test_each_verdict_has_its_own_exit_code(verdict: Verdict, code: int) -> None:
    """Three codes, and unmeasured is not zero."""
    assert _exit_code(verdict) == code


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param("not a mapping", id="not-a-mapping"),
        pytest.param({"verdict": "?"}, id="unknown"),
    ],
)
def test_an_unrecognisable_finding_reads_back_as_unmeasured(entry: object) -> None:
    """Defaulting to passed would be the one unsafe direction."""
    assert _verdict_of(entry) is Verdict.UNMEASURED


def test_reading_a_file_that_is_not_there_returns_none_rather_than_raising(
    tmp_path: Path,
) -> None:
    """Every caller distinguishes absent from unreadable by this."""
    assert _read(tmp_path, "nothing.toml") is None


def test_every_intrinsic_reason_is_a_declared_reason() -> None:
    """The soundness split cannot name a code the manifest does not know."""
    assert INTRINSIC_REASONS <= REASONS


def test_the_lock_the_gate_reads_back_is_the_one_it_was_given(tmp_path: Path) -> None:
    """`lock_of` is what the contract test uses to talk about a real tree."""
    build_tree(tmp_path)
    assert gate.lock_of(tmp_path).packages == parse_lock(LOCK, path="pylock.dev.toml").packages


# ---------------------------------------------------------------------------
# The remaining refusals, each reached through the gate rather than around it
# ---------------------------------------------------------------------------


def test_a_malformed_runtime_contract_is_reported_rather_than_partly_read(
    tmp_path: Path,
) -> None:
    """Phase 017 owns those values, and a half-read contract is not one of them."""
    build_tree(tmp_path)
    (tmp_path / "docs" / "engineering" / "runtime-contract.toml").write_text(
        "schema = 99\n", encoding="utf-8", newline="\n"
    )
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert REASON_TARGET_DIVERGED in reasons_of(manifest_of(tmp_path))


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        pytest.param(
            ('lock-version = "1.0"', 'lock-version = "2.0"'),
            REASON_VERSION_UNSUPPORTED,
            id="format",
        ),
        pytest.param(
            ('created-by = "pip"', 'created-by = "uv"'), REASON_PRODUCER_UNEXPECTED, id="producer"
        ),
        pytest.param(
            ('name = "ruff"\nversion', 'name = "Ruff"\nversion'),
            REASON_PACKAGE_MALFORMED,
            id="unnormalised-name",
        ),
    ],
)
def test_each_lock_defect_earns_its_own_reason_code(
    tmp_path: Path, mutation: tuple[str, str], reason: str
) -> None:
    """One code per defect, because each needs a different fix."""
    old, new = mutation
    build_tree(tmp_path, lock=LOCK.replace(old, new))
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert reason in reasons_of(manifest_of(tmp_path))


def test_a_tree_whose_registers_cannot_be_read_is_reported(tmp_path: Path) -> None:
    """The four-way comparison needs all four, and three of them is not an answer."""
    build_tree(tmp_path)
    (tmp_path / ".pre-commit-config.yaml").unlink()
    assert run(tmp_path) == EXIT_GATE_FAILED


def test_a_project_file_with_no_development_requirements_cannot_be_resolved_from(
    tmp_path: Path,
) -> None:
    """`relock` resolves the project's roots, and an empty extra names none."""
    build_tree(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "globin"\nversion = "0.1.0"\ndependencies = []\n',
        encoding="utf-8",
        newline="\n",
    )
    assert run(tmp_path, mode=RELOCK, runner=lambda *_a, **_k: completed()) == EXIT_GATE_FAILED
    assert REASON_REFRESH_FAILED in reasons_of(manifest_of(tmp_path))


def test_a_relock_over_a_tree_with_no_project_file_is_reported(tmp_path: Path) -> None:
    """There is nothing to resolve from."""
    build_tree(tmp_path)
    (tmp_path / "pyproject.toml").unlink()
    assert run(tmp_path, mode=RELOCK, runner=lambda *_a, **_k: completed()) == EXIT_GATE_FAILED


def test_a_relock_over_a_tree_with_no_workflow_register_is_reported(tmp_path: Path) -> None:
    """The pins are held during a resolution, so they have to be readable first."""
    build_tree(tmp_path)
    (tmp_path / ".github" / "workflows" / "quality.yml").unlink()
    assert run(tmp_path, mode=RELOCK, runner=lambda *_a, **_k: completed()) == EXIT_GATE_FAILED


@pytest.mark.parametrize(
    ("captured", "expected"),
    [
        pytest.param(None, "no output", id="none"),
        pytest.param("", "no output", id="empty"),
        pytest.param("a\n  b\nc", "a b c", id="collapsed"),
    ],
)
def test_a_childs_error_output_is_collapsed_to_one_line(
    captured: str | None, expected: str
) -> None:
    """A finding is one sentence, and a traceback is not."""
    assert tail(captured) == expected


def test_a_long_error_output_is_truncated_from_the_end() -> None:
    """The end is where the message is; the beginning is where the banner is."""
    assert tail("x" * 100 + "the actual failure", limit=18) == "the actual failure"


def test_a_report_survives_a_finding_that_is_not_a_mapping(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reporting is the last thing that runs, and it must not be what fails."""
    report({"odd": "not a mapping"}, Verdict.PASSED, ())
    assert "verdict" in capsys.readouterr().out


def test_reading_a_declaration_that_is_not_there_raises_rather_than_returning_empty(
    tmp_path: Path,
) -> None:
    """An empty declaration is indistinguishable from one that permits everything."""
    with pytest.raises(LockError, match="could not be read"):
        gate.declaration_of(tmp_path)


def test_reading_a_lock_that_is_not_there_raises(tmp_path: Path) -> None:
    """Likewise, and the message names the file the declaration pointed at."""
    build_tree(tmp_path, lock=None)
    with pytest.raises(LockError, match=r"pylock\.dev\.toml"):
        gate.lock_of(tmp_path)


def test_a_manifest_that_would_carry_a_secret_is_refused_rather_than_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The last gate before anything is published.

    The manifest records counts rather than URLs, so there should be nothing to
    find; scanning it anyway rather than trusting that is the whole point of the
    check, and this is what proves the branch exists.
    """
    build_tree(tmp_path)
    finding = Finding(source=gate.MANIFEST_NAME, line=1, description="a bearer token")
    monkeypatch.setattr(gate, "scan_for_secrets", lambda _source, _text: (finding,))
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert REASON_MANIFEST_LEAKAGE in reasons_of(manifest_of(tmp_path))
