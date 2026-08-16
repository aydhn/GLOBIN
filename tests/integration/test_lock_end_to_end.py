"""The lock gate against a whole tree, coherent and then deliberately pulled apart.

The unit tests establish that each judgement reaches the right answer from values.
This establishes that the gate wires them to the right inputs across four separate
files — the lock, the declaration, the runtime contract and the three declaration
registers — writes a manifest that reads back, and returns an exit code matching
its own verdict.

**Every divergence below is one somebody would actually create.** A tool added to
the project without relocking, a pin bumped by a dependency bot, a hook revision
moved on its own, a hash edited by hand. Each has its own reason code, because
each needs a different fix.

**Every tree here is a temporary one and every child is injected.** A test that
could only run against this repository would be a test unable to describe a broken
lock, which is most of what is worth asserting.
"""

import subprocess
from pathlib import Path

import pytest

from tools.quality.lock import gate
from tools.quality.lock.gate import EXIT_GATE_FAILED, EXIT_OK, RELOCK, run_lock
from tools.quality.lock.manifest import (
    REASON_ARTEFACT_UNTRUSTED,
    REASON_DECLARATION_INCOMPLETE,
    REASON_HASH_MISSING,
    REASON_REGISTER_DIVERGED,
    REASON_RUNTIME_UNLOCKED,
    REASON_TARGET_DIVERGED,
    REASON_WHEEL_INCOMPATIBLE,
    load,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
HOST = "https://files.pythonhosted.org/packages"


def entry(name: str, version: str, filename: str, digest: str = DIGEST_A, host: str = HOST) -> str:
    """One `[[packages]]` table, as `pip lock` writes one."""
    return (
        f'\n[[packages]]\nname = "{name}"\nversion = "{version}"\n'
        f'\n[[packages.wheels]]\nname = "{filename}"\nurl = "{host}/ab/{filename}"\n'
        f'\n[packages.wheels.hashes]\nsha256 = "{digest}"\n'
    )


def lock_text(*entries: str) -> str:
    """A whole lock file."""
    body = "".join(entries) or entry("ruff", "0.15.14", "ruff-0.15.14-py3-none-win_amd64.whl")
    return 'lock-version = "1.0"\ncreated-by = "pip"\n' + body


DEFAULT_LOCK = lock_text(
    entry("ruff", "0.15.14", "ruff-0.15.14-py3-none-win_amd64.whl"),
    entry("mypy", "2.1.0", "mypy-2.1.0-cp314-cp314-win_amd64.whl", digest=DIGEST_B),
)

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


def declaration_text(
    *,
    roots: str = '["ruff>=0.6", "mypy>=1.11"]',
    minor_line: str = "3.14",
    runtime_locked: str = "false",
    gaps: str = "",
) -> str:
    """The lock declaration, with the fields these tests move."""
    return f"""\
schema = 1

[producer]
tool = "pip"
version = "26.1.1"
experimental = true

[target]
implementation = "CPython"
minor_line = "{minor_line}"
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
roots = {roots}

[runtime]
path = "pylock.toml"
locked = {runtime_locked}
reason = "there are no runtime dependencies yet"

[project]
distribution = "globin"
installed = false

[environment]
seeded = ["pip"]
{gaps}"""


def pyproject_text(dev: str = '["ruff>=0.6", "mypy>=1.11"]', runtime: str = "[]") -> str:
    """The project file, with the two lists these tests move."""
    return (
        '[project]\nname = "globin"\nversion = "0.1.0"\n'
        f"dependencies = {runtime}\n\n"
        f"[project.optional-dependencies]\ndev = {dev}\n"
    )


def workflow_text(ruff: str = "0.15.14", mypy: str = "2.1.0") -> str:
    """A workflow installing the two pinned tools."""
    return (
        "name: Quality\non: [push]\njobs:\n  quality:\n    steps:\n"
        f'      - run: python -m pip install "ruff=={ruff}" "mypy=={mypy}"\n'
    )


def pre_commit_text(revision: str = "v0.15.14") -> str:
    """A hook configuration mirroring ruff."""
    return (
        "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
        f"    rev: {revision}\n    hooks:\n      - id: ruff\n"
    )


def build_tree(
    root: Path,
    *,
    lock: str = DEFAULT_LOCK,
    declaration: str | None = None,
    pyproject: str | None = None,
    workflow: str | None = None,
    pre_commit: str | None = None,
) -> None:
    """Write a coherent tree, with any one file replaced."""
    engineering = root / "docs" / "engineering"
    engineering.mkdir(parents=True, exist_ok=True)
    (engineering / "runtime-contract.toml").write_text(CONTRACT, encoding="utf-8", newline="\n")
    (engineering / "lock-policy.toml").write_text(
        declaration if declaration is not None else declaration_text(),
        encoding="utf-8",
        newline="\n",
    )
    (root / "pyproject.toml").write_text(
        pyproject if pyproject is not None else pyproject_text(), encoding="utf-8", newline="\n"
    )
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "quality.yml").write_text(
        workflow if workflow is not None else workflow_text(), encoding="utf-8", newline="\n"
    )
    (root / ".pre-commit-config.yaml").write_text(
        pre_commit if pre_commit is not None else pre_commit_text(),
        encoding="utf-8",
        newline="\n",
    )
    (root / "pylock.dev.toml").write_text(lock, encoding="utf-8", newline="\n")


def run(root: Path, **options: object) -> int:
    """Run the gate over a prepared tree, writing its evidence inside it."""
    return run_lock(root=root, reports=root / "out", **options)  # type: ignore[arg-type]


def reasons_of(root: Path) -> list[str]:
    """The reason codes the run recorded, read back through the digest check."""
    document = load((root / "out" / gate.MANIFEST_NAME).read_text(encoding="utf-8"))
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    return list(verdict["reasons"])


# ---------------------------------------------------------------------------
# A coherent tree
# ---------------------------------------------------------------------------


def test_a_coherent_tree_passes_offline(tmp_path: Path) -> None:
    """The control that every divergence below is measured against."""
    build_tree(tmp_path)
    assert run(tmp_path) == EXIT_OK
    assert reasons_of(tmp_path) == []


def test_the_offline_run_starts_no_child(tmp_path: Path) -> None:
    """`check` reaches nothing, and this is how that is established rather than asserted.

    An injected runner that raises would be caught; one that fails the test
    outright cannot be. `full` must work on an aeroplane, and a gate that quietly
    started `pip` would break that on the day the index was slow.
    """
    build_tree(tmp_path)

    def forbidden(*_args: object, **_kwargs: object) -> "subprocess.CompletedProcess[str]":
        message = "check must not start a child process"
        raise AssertionError(message)

    assert run(tmp_path, runner=forbidden) == EXIT_OK


# ---------------------------------------------------------------------------
# The four files pulled apart, one at a time
# ---------------------------------------------------------------------------


def test_a_tool_added_to_the_project_without_relocking_is_caught(tmp_path: Path) -> None:
    """It would be unlocked while appearing declared."""
    build_tree(tmp_path, pyproject=pyproject_text(dev='["ruff>=0.6", "mypy>=1.11", "black>=24"]'))
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert REASON_DECLARATION_INCOMPLETE in reasons_of(tmp_path)


def test_a_tool_removed_from_the_project_and_left_in_the_declaration_is_caught(
    tmp_path: Path,
) -> None:
    """The direction nothing else can see.

    pip records no dependency edges, so a root the project no longer declares is
    invisible to every other check — the lock still resolves, the hashes are
    still right, and nothing says the resolution was performed from a list
    somebody has since edited.
    """
    build_tree(tmp_path, pyproject=pyproject_text(dev='["ruff>=0.6"]'))
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert REASON_DECLARATION_INCOMPLETE in reasons_of(tmp_path)


def test_a_pin_bumped_without_relocking_is_caught_and_the_replacement_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The message is step two of the upgrade procedure, so it has to be exact."""
    build_tree(tmp_path, workflow=workflow_text(ruff="0.16.3"))
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert REASON_REGISTER_DIVERGED in reasons_of(tmp_path)
    assert "write ruff==0.15.14" in capsys.readouterr().out


def test_a_hook_revision_moved_on_its_own_is_caught(tmp_path: Path) -> None:
    """Both halves pass alone, which is what makes this one expensive to find by hand."""
    build_tree(tmp_path, pre_commit=pre_commit_text(revision="v0.16.3"))
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert REASON_REGISTER_DIVERGED in reasons_of(tmp_path)


def test_a_contract_moved_to_a_line_the_locked_wheels_cannot_serve_is_caught(
    tmp_path: Path,
) -> None:
    """The declared target is a tripwire against the contract, and this trips it."""
    build_tree(tmp_path, declaration=declaration_text(minor_line="3.13"))
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert REASON_TARGET_DIVERGED in reasons_of(tmp_path)


def test_a_runtime_dependency_appearing_without_its_lock_is_caught(tmp_path: Path) -> None:
    """The forward hook. Phase 021 meets this the moment it declares one."""
    build_tree(tmp_path, pyproject=pyproject_text(runtime='["httpx>=0.27"]'))
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert REASON_RUNTIME_UNLOCKED in reasons_of(tmp_path)


# ---------------------------------------------------------------------------
# The lock edited by hand
# ---------------------------------------------------------------------------


def test_a_removed_hash_is_caught(tmp_path: Path) -> None:
    """The failure that is otherwise silent: the file still looks like a lock."""
    build_tree(tmp_path, lock=DEFAULT_LOCK.replace(f'sha256 = "{DIGEST_B}"\n', ""))
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert REASON_HASH_MISSING in reasons_of(tmp_path)


def test_an_edited_artefact_host_is_caught(tmp_path: Path) -> None:
    """One URL among several hundred, pointing somewhere nobody declared."""
    build_tree(
        tmp_path,
        lock=lock_text(
            entry("ruff", "0.15.14", "ruff-0.15.14-py3-none-win_amd64.whl"),
            entry(
                "mypy",
                "2.1.0",
                "mypy-2.1.0-cp314-cp314-win_amd64.whl",
                digest=DIGEST_B,
                host="https://mirror.example/packages",
            ),
        ),
    )
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert REASON_ARTEFACT_UNTRUSTED in reasons_of(tmp_path)


def test_a_wheel_for_another_interpreter_is_caught(tmp_path: Path) -> None:
    """A lock whose entry cannot be installed on the pinned line."""
    build_tree(
        tmp_path,
        lock=lock_text(
            entry("ruff", "0.15.14", "ruff-0.15.14-py3-none-win_amd64.whl"),
            entry("mypy", "2.1.0", "mypy-2.1.0-cp313-cp313-win_amd64.whl", digest=DIGEST_B),
        ),
    )
    assert run(tmp_path) == EXIT_GATE_FAILED
    assert REASON_WHEEL_INCOMPATIBLE in reasons_of(tmp_path)


def test_a_version_edited_in_the_package_table_but_not_the_filename_is_caught(
    tmp_path: Path,
) -> None:
    """Editing one place is easy; editing every wheel filename beneath it is not."""
    build_tree(tmp_path, lock=DEFAULT_LOCK.replace('version = "2.1.0"', 'version = "2.9.9"'))
    assert run(tmp_path) == EXIT_GATE_FAILED


# ---------------------------------------------------------------------------
# The evidence itself
# ---------------------------------------------------------------------------


def test_the_manifest_verifies_after_every_kind_of_run(tmp_path: Path) -> None:
    """A run that failed still leaves a sealed, readable record of why."""
    build_tree(tmp_path, workflow=workflow_text(ruff="0.16.3"))
    run(tmp_path)
    assert reasons_of(tmp_path)


def test_a_manifest_edited_to_turn_its_verdict_into_a_pass_no_longer_verifies(
    tmp_path: Path,
) -> None:
    """The digest is what makes the record evidence rather than a note."""
    build_tree(tmp_path, workflow=workflow_text(ruff="0.16.3"))
    run(tmp_path)
    path = tmp_path / "out" / gate.MANIFEST_NAME
    path.write_text(
        path.read_text(encoding="utf-8").replace('"verdict":"failed"', '"verdict":"passed"'),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(Exception, match="digests to"):
        reasons_of(tmp_path)


def test_a_regenerated_lock_is_checked_against_the_same_tree_before_it_is_kept(
    tmp_path: Path,
) -> None:
    """`relock` judges the candidate, not the file it is about to replace."""
    build_tree(tmp_path)
    unhashed = lock_text(entry("ruff", "0.15.14", "ruff-0.15.14-py3-none-win_amd64.whl")).replace(
        f'sha256 = "{DIGEST_A}"\n', ""
    )

    def write(argv: list[str], **_kwargs: object) -> "subprocess.CompletedProcess[str]":
        Path(argv[argv.index("--output") + 1]).write_text(unhashed, encoding="utf-8", newline="\n")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    assert run(tmp_path, mode=RELOCK, runner=write) == EXIT_GATE_FAILED
    assert (tmp_path / "pylock.dev.toml").read_text(encoding="utf-8") == DEFAULT_LOCK
    assert (tmp_path / "out" / gate.REJECTED_NAME).exists()
