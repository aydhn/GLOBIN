"""The runtime gate against a whole tree, correct and then deliberately broken.

The unit tests establish that each checker reaches the right answer from values.
This establishes that the gate wires them to the right inputs, writes a manifest
that reads back, and returns an exit code that matches its own verdict — the three
things a pure test cannot see. It also establishes the one property no unit test
can: that a manifest produced from a real filesystem carries no absolute path.

**Every tree here is a temporary one**, and every child process is a hand-written
double rather than a real one. A test that could only run against this repository
would be a test unable to describe a broken environment, which is most of what is
worth asserting.

**The synthetic contract is derived from the interpreter running the suite.** The
alternative — writing ``3.14`` into the fixture — would make these tests assert
something about the CI matrix rather than about the gate, and they would fail on
the 3.12 job for a reason that has nothing to do with what they check.

**One finding can never pass in a synthetic tree, and that is correct.** The gate
compares the running interpreter against the environment of the tree it is
judging, and these trees are not the one the suite is running from. It reports
that rather than claiming it measured an environment it never ran. The tests below
assert exactly that, rather than working around it.
"""

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.quality.runtime import gate, manifest
from tools.quality.runtime.manifest import (
    REASON_BOOTSTRAP_FAILED,
    REASON_DECLARATION_UNREADABLE,
    REASON_DELETION_REFUSED,
    REASON_ENVIRONMENT_ABSENT,
    REASON_ENVIRONMENT_NONCOMPLIANT,
    REASON_HOST_UNSUPPORTED,
    REASON_INTERPRETER_FOREIGN,
    REASON_INTERPRETER_NONCOMPLIANT,
    REASON_MANIFEST_LEAKAGE,
    REASON_PIP_FOREIGN,
    REASON_TOOLCHAIN_UNAVAILABLE,
)

WORKFLOW = """\
name: Quality
on: [push]
jobs:
  quality:
    runs-on: windows-latest
    steps:
      - name: Install the toolchain
        run: |
          python -m pip install "ruff==0.15.14" "mypy==2.1.0"
"""


def contract(**overrides: str) -> str:
    """A contract this interpreter satisfies, with any line replaced."""
    info = sys.version_info
    values = {
        "implementation": sys.implementation.name,
        "minor_line": f"{info.major}.{info.minor}",
        "minimum_patch": f"{info.major}.{info.minor}.0",
        "architecture": "AMD64",
        "pointer_bits": "64",
        "free_threaded": "true",
        "allow_prerelease": "true",
        "system": "Windows",
        "minimum_release": "10",
        "directory": ".venv",
        "system_site_packages": "false",
    }
    values.update(overrides)
    return f"""\
schema = 1

[interpreter]
implementation = "{values["implementation"]}"
minor_line = "{values["minor_line"]}"
minimum_patch = "{values["minimum_patch"]}"
architecture = "{values["architecture"]}"
pointer_bits = {values["pointer_bits"]}
free_threaded = {values["free_threaded"]}
allow_prerelease = {values["allow_prerelease"]}

[host]
system = "{values["system"]}"
minimum_release = "{values["minimum_release"]}"

[environment]
directory = "{values["directory"]}"
system_site_packages = {values["system_site_packages"]}
"""


class _Launcher:
    """A stand-in for every child process the gate can start.

    Hand-written rather than a mock, per ``docs/TESTING_STRATEGY.md``: the default
    is a double satisfying the interface, and ``create_autospec`` is for the cases
    where a mock is genuinely right. It also records what it was asked to do, which
    is how idempotency is asserted — "the second run created nothing" is a claim
    about a call that did not happen.
    """

    def __init__(self, *, venv_succeeds: bool = True, site_packages: bool = False) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.venv_succeeds = venv_succeeds
        self.site_packages = site_packages

    def __call__(
        self, args: Sequence[str], **_kwargs: object
    ) -> "subprocess.CompletedProcess[str]":
        recorded = tuple(str(item) for item in args)
        self.calls.append(recorded)

        if "venv" in recorded:
            if not self.venv_succeeds:
                return subprocess.CompletedProcess(recorded, 1, "", "venv: no such option")
            write_environment(
                Path(recorded[-1]), site_packages=self.site_packages, location=Path(recorded[-1])
            )
        elif recorded[:2] == ("py", "-0p"):
            return subprocess.CompletedProcess(
                recorded, 0, " -V:3.14 *  C:\\Python314\\python.exe\n", ""
            )
        return subprocess.CompletedProcess(recorded, 0, "", "")

    @property
    def created(self) -> int:
        """How many times an environment was asked to be created."""
        return sum(1 for call in self.calls if "venv" in call)

    @property
    def installed(self) -> int:
        """How many times the toolchain was asked to be installed."""
        return sum(1 for call in self.calls if "install" in call)


def write_environment(
    directory: Path, *, site_packages: bool = False, location: Path | None = None
) -> None:
    """Write what :mod:`venv` writes, enough for the gate to judge it.

    Args:
        directory: Where the environment lives.
        site_packages: Whether to record the global site directory as visible.
        location: The location to record in ``activate.bat``, which is how a moved
            environment is detected. Defaults to ``directory``.
    """
    info = sys.version_info
    scripts = directory / "Scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (directory / "pyvenv.cfg").write_text(
        f"home = {sys.base_prefix}\n"
        f"include-system-site-packages = {'true' if site_packages else 'false'}\n"
        f"version = {info.major}.{info.minor}.{info.micro}\n",
        encoding="utf-8",
        newline="\n",
    )
    recorded = (location or directory).resolve()
    (scripts / "activate.bat").write_text(
        f'@echo off\nset "VIRTUAL_ENV={recorded}"\n', encoding="utf-8", newline="\n"
    )
    (scripts / "python.exe").write_bytes(b"")


def build_tree(root: Path, *, declaration: str | None = None, environment: bool = True) -> None:
    """Write a tree the gate can judge.

    Args:
        root: Where to write it.
        declaration: The contract, or ``None`` to omit it entirely.
        environment: Whether to write a well-formed ``.venv``.
    """
    if declaration is not None:
        target = root / "docs" / "engineering" / "runtime-contract.toml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(declaration, encoding="utf-8", newline="\n")

    workflow = root / ".github" / "workflows" / "quality.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(WORKFLOW, encoding="utf-8", newline="\n")

    if environment:
        write_environment(root / ".venv")


def run(root: Path, **options: object) -> int:
    """Run the gate over a prepared tree with every child injected."""
    options.setdefault("runner", _Launcher())
    return gate.run_runtime(root=root, reports=root / "out", **options)  # type: ignore[arg-type]


def read_manifest(root: Path) -> dict[str, object]:
    """Read back what the gate wrote, through the reader that verifies the digest."""
    return manifest.load((root / "out" / gate.MANIFEST_NAME).read_text(encoding="utf-8"))


def reasons_of(document: dict[str, object]) -> list[str]:
    """The reason codes a manifest records."""
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    recorded = verdict["reasons"]
    assert isinstance(recorded, list)
    return [str(reason) for reason in recorded]


def findings_of(document: dict[str, object]) -> dict[str, object]:
    """The findings a manifest records."""
    findings = document["findings"]
    assert isinstance(findings, dict)
    return findings


# ---------------------------------------------------------------------------
# A well-formed tree
# ---------------------------------------------------------------------------


def test_a_well_formed_tree_passes_every_check_it_can_and_says_which_it_cannot(
    tmp_path: Path,
) -> None:
    """The gate refuses to claim it measured an environment it is not running from.

    Everything about the host, the interpreter and the environment on disk passes.
    The one finding that fails is the one asserting the gate ran *inside* the
    environment it judged, which cannot be true of a temporary tree — and reporting
    it is better than a pass that would mean nothing.
    """
    build_tree(tmp_path, declaration=contract())
    assert run(tmp_path) == gate.EXIT_GATE_FAILED

    document = read_manifest(tmp_path)
    findings = findings_of(document)
    assert findings["host"] == {"verdict": "passed", "problems": []}
    assert findings["interpreter"] == {"verdict": "passed", "problems": []}
    assert findings["environment"] == {"verdict": "passed", "problems": []}
    assert reasons_of(document) == [REASON_INTERPRETER_FOREIGN]


def test_the_manifest_records_the_contract_it_judged_against(tmp_path: Path) -> None:
    """So a reader of the evidence need not also have the contract at that commit."""
    build_tree(tmp_path, declaration=contract())
    run(tmp_path)

    run_section = read_manifest(tmp_path)["run"]
    assert isinstance(run_section, dict)
    assert run_section["mode"] == "check"
    assert run_section["declaration"] == "docs/engineering/runtime-contract.toml"
    terms = run_section["contract"]
    assert isinstance(terms, dict)
    assert terms["minor_line"] == f"{sys.version_info.major}.{sys.version_info.minor}"


def test_the_manifest_carries_no_absolute_path(tmp_path: Path) -> None:
    """The privacy contract.

    Asserted against a manifest produced from a real filesystem rather than from values.

    ``recorded_path`` is unit-tested, but this is what establishes that every path the gate
    records actually goes through it — including the ones inside ``pyvenv.cfg``, ``pip``'s
    location and the base prefix.
    """
    build_tree(tmp_path, declaration=contract())
    run(tmp_path)

    rendered = (tmp_path / "out" / gate.MANIFEST_NAME).read_text(encoding="utf-8")
    assert str(tmp_path) not in rendered
    assert str(tmp_path.drive) not in rendered or not tmp_path.drive
    assert sys.base_prefix not in rendered
    assert sys.prefix not in rendered
    for fragment in ("Users", "AppData", "home/", "Program Files"):
        assert fragment not in rendered, f"{fragment!r} leaked into the manifest"


def test_two_runs_of_the_check_produce_the_same_manifest(tmp_path: Path) -> None:
    """No wall clock anywhere, so evidence from one commit is one document."""
    build_tree(tmp_path, declaration=contract())
    run(tmp_path)
    first = (tmp_path / "out" / gate.MANIFEST_NAME).read_text(encoding="utf-8")
    run(tmp_path)
    second = (tmp_path / "out" / gate.MANIFEST_NAME).read_text(encoding="utf-8")
    assert first == second


def test_the_check_creates_nothing(tmp_path: Path) -> None:
    """The whole reason ``check`` and ``bootstrap`` are separate commands."""
    build_tree(tmp_path, declaration=contract(), environment=False)
    launcher = _Launcher()
    run(tmp_path, runner=launcher)

    assert not (tmp_path / ".venv").exists()
    assert launcher.created == 0
    assert launcher.installed == 0


# ---------------------------------------------------------------------------
# Broken trees
# ---------------------------------------------------------------------------


def test_an_absent_environment_fails_and_names_the_script_that_creates_one(
    tmp_path: Path,
) -> None:
    build_tree(tmp_path, declaration=contract(), environment=False)
    assert run(tmp_path) == gate.EXIT_GATE_FAILED

    document = read_manifest(tmp_path)
    assert REASON_ENVIRONMENT_ABSENT in reasons_of(document)
    environment = findings_of(document)["environment"]
    assert isinstance(environment, dict)
    assert "bootstrap.ps1" in str(environment["problems"])


def test_an_environment_with_the_global_site_directory_visible_fails(tmp_path: Path) -> None:
    build_tree(tmp_path, declaration=contract(), environment=False)
    write_environment(tmp_path / ".venv", site_packages=True)
    assert run(tmp_path) == gate.EXIT_GATE_FAILED
    assert REASON_ENVIRONMENT_NONCOMPLIANT in reasons_of(read_manifest(tmp_path))


def test_a_moved_environment_is_detected(tmp_path: Path) -> None:
    """The failure that does not announce itself: the interpreter still runs.

    Only the console scripts misbehave.
    """
    build_tree(tmp_path, declaration=contract(), environment=False)
    write_environment(tmp_path / ".venv", location=tmp_path / "elsewhere" / ".venv")
    assert run(tmp_path) == gate.EXIT_GATE_FAILED

    document = read_manifest(tmp_path)
    assert REASON_ENVIRONMENT_NONCOMPLIANT in reasons_of(document)
    environment = findings_of(document)["environment"]
    assert isinstance(environment, dict)
    assert "moved or copied" in str(environment["problems"])


def test_an_interpreter_that_fails_the_contract_is_reported(tmp_path: Path) -> None:
    build_tree(tmp_path, declaration=contract(minor_line="2.7", minimum_patch="2.7.0"))
    assert run(tmp_path) == gate.EXIT_GATE_FAILED
    assert REASON_INTERPRETER_NONCOMPLIANT in reasons_of(read_manifest(tmp_path))


def test_a_missing_contract_still_writes_a_manifest(tmp_path: Path) -> None:
    """A gate that failed silently and left no artefact would be indistinguishable.

    To anything reading the evidence, from a gate that never ran.
    """
    build_tree(tmp_path, declaration=None)
    assert run(tmp_path) == gate.EXIT_GATE_FAILED

    document = read_manifest(tmp_path)
    assert REASON_DECLARATION_UNREADABLE in reasons_of(document)


def test_a_malformed_contract_is_refused_rather_than_partly_read(tmp_path: Path) -> None:
    build_tree(tmp_path, declaration="schema = 1\n[interpreter]\nminor_line = 3\n")
    assert run(tmp_path) == gate.EXIT_GATE_FAILED
    assert REASON_DECLARATION_UNREADABLE in reasons_of(read_manifest(tmp_path))


def test_a_contract_from_another_schema_version_is_refused(tmp_path: Path) -> None:
    build_tree(tmp_path, declaration=contract().replace("schema = 1", "schema = 99"))
    assert run(tmp_path) == gate.EXIT_GATE_FAILED
    assert REASON_DECLARATION_UNREADABLE in reasons_of(read_manifest(tmp_path))


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_creates_the_environment_and_installs_the_pinned_toolchain(
    tmp_path: Path,
) -> None:
    build_tree(tmp_path, declaration=contract(), environment=False)
    launcher = _Launcher()
    assert run(tmp_path, bootstrap=True, runner=launcher) == gate.EXIT_OK

    assert launcher.created == 1
    install = next(call for call in launcher.calls if "install" in call)
    assert "ruff==0.15.14" in install, "the pins come from the workflow register"
    assert "mypy==2.1.0" in install


def test_bootstrap_records_that_it_was_a_bootstrap_run(tmp_path: Path) -> None:
    """``run.mode`` says which subcommand produced this document.

    It is what tells a reader why the running-interpreter finding is absent from a
    bootstrap run and present in a check.
    """
    build_tree(tmp_path, declaration=contract(), environment=False)
    run(tmp_path, bootstrap=True)

    document = read_manifest(tmp_path)
    run_section = document["run"]
    assert isinstance(run_section, dict)
    assert run_section["mode"] == "bootstrap"
    assert "running_interpreter" not in findings_of(document)


def test_bootstrap_a_second_time_creates_nothing(tmp_path: Path) -> None:
    """Idempotency.

    Asserted as a call that did not happen rather than as an absence of visible change.
    """
    build_tree(tmp_path, declaration=contract())
    launcher = _Launcher()
    assert run(tmp_path, bootstrap=True, runner=launcher) == gate.EXIT_OK
    assert launcher.created == 0, "an environment that already complies is not rebuilt"


def test_bootstrap_refuses_to_build_from_a_non_compliant_interpreter(tmp_path: Path) -> None:
    """An environment inherits the interpreter it was built from.

    That is why building one from a failing interpreter would bake the failure in and then
    report it as an environment problem forever after.
    """
    build_tree(tmp_path, declaration=contract(minor_line="2.7", minimum_patch="2.7.0"))
    launcher = _Launcher()
    assert run(tmp_path, bootstrap=True, runner=launcher) == gate.EXIT_GATE_FAILED

    assert launcher.created == 0
    assert REASON_BOOTSTRAP_FAILED in reasons_of(read_manifest(tmp_path))


def test_a_failing_venv_creation_is_reported_rather_than_assumed(tmp_path: Path) -> None:
    build_tree(tmp_path, declaration=contract(), environment=False)
    launcher = _Launcher(venv_succeeds=False)
    assert run(tmp_path, bootstrap=True, runner=launcher) == gate.EXIT_GATE_FAILED

    document = read_manifest(tmp_path)
    assert REASON_BOOTSTRAP_FAILED in reasons_of(document)
    creation = findings_of(document)["environment_creation"]
    assert isinstance(creation, dict)
    assert "exited 1" in str(creation["problems"])


def test_recreate_removes_the_environment_and_builds_it_again(tmp_path: Path) -> None:
    build_tree(tmp_path, declaration=contract())
    marker = tmp_path / ".venv" / "marker.txt"
    marker.write_text("from the previous environment\n", encoding="utf-8")

    launcher = _Launcher()
    assert run(tmp_path, bootstrap=True, recreate=True, runner=launcher) == gate.EXIT_OK

    assert launcher.created == 1
    assert not marker.exists(), "recreate must remove the old environment, not merge into it"


def test_recreate_leaves_every_sibling_of_the_environment_alone(tmp_path: Path) -> None:
    """A recursive delete is one bad join away from removing something that matters."""
    build_tree(tmp_path, declaration=contract())
    keep = tmp_path / "src" / "important.py"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("# not an environment\n", encoding="utf-8")

    assert run(tmp_path, bootstrap=True, recreate=True) == gate.EXIT_OK

    assert keep.is_file(), "a sibling of the environment must survive a recreate"
    assert (tmp_path / "docs" / "engineering" / "runtime-contract.toml").is_file()


def test_a_contract_naming_an_escaping_directory_is_refused_before_anything_acts_on_it(
    tmp_path: Path,
) -> None:
    """The check that matters most in this file.

    ``deletion_problems`` refuses a target that is not the declared environment,
    but it cannot protect against a *declaration* that names a traversal — so the
    parser refuses that first, and this establishes that the refusal happens before
    any code reaches :func:`shutil.rmtree`. Nothing outside the tree can then be a
    deletion target, because the gate never gets a directory name to join.
    """
    outside = tmp_path.parent / f"{tmp_path.name}-sibling"
    outside.mkdir(exist_ok=True)
    witness = outside / "witness.txt"
    witness.write_text("must survive\n", encoding="utf-8")

    build_tree(tmp_path, declaration=contract(directory=".."))
    launcher = _Launcher()
    try:
        assert run(tmp_path, bootstrap=True, recreate=True, runner=launcher) == (
            gate.EXIT_GATE_FAILED
        )

        assert REASON_DECLARATION_UNREADABLE in reasons_of(read_manifest(tmp_path))
        assert launcher.created == 0
        assert witness.is_file(), "a directory outside the tree was removed"
        assert tmp_path.is_dir()
    finally:
        witness.unlink(missing_ok=True)
        outside.rmdir()


def test_an_unsupported_operating_system_is_reported(tmp_path: Path) -> None:
    """The contract names the system.

    That is why a tree declaring one this host is not fails here rather than three phases later
    in an adapter.
    """
    build_tree(tmp_path, declaration=contract(system="Haiku"))
    assert run(tmp_path) == gate.EXIT_GATE_FAILED
    assert REASON_HOST_UNSUPPORTED in reasons_of(read_manifest(tmp_path))


def test_requesting_a_runtime_install_records_what_this_launcher_can_do(
    tmp_path: Path,
) -> None:
    """Opt-in, and on a host with the legacy launcher it installs nothing and says so.

    A recorded state rather than a silent no-op (ADR-0045).
    """
    build_tree(tmp_path, declaration=contract(), environment=False)
    run(tmp_path, bootstrap=True, install_python=True)

    installation = findings_of(read_manifest(tmp_path))["runtime_installation"]
    assert isinstance(installation, dict)
    assert "no runtime was installed" in str(installation["problems"])


def test_a_tree_with_no_pinned_toolchain_cannot_be_bootstrapped(tmp_path: Path) -> None:
    """The versions come from the workflow register.

    That is why a tree without one has no toolchain to install rather than a default one.
    """
    build_tree(tmp_path, declaration=contract(), environment=False)
    (tmp_path / ".github" / "workflows" / "quality.yml").unlink()

    assert run(tmp_path, bootstrap=True) == gate.EXIT_GATE_FAILED
    assert REASON_TOOLCHAIN_UNAVAILABLE in reasons_of(read_manifest(tmp_path))


def test_a_refused_removal_stops_the_bootstrap_rather_than_building_over_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the old environment could not be removed.

    Creating on top of it would produce exactly the half-replaced state ``--recreate`` was asked
    to avoid.
    """
    build_tree(tmp_path, declaration=contract())
    monkeypatch.setattr(gate, "_remove", lambda *_a: ("it is held open by another process",))

    launcher = _Launcher()
    assert run(tmp_path, bootstrap=True, recreate=True, runner=launcher) == gate.EXIT_GATE_FAILED

    assert launcher.created == 0
    assert REASON_DELETION_REFUSED in reasons_of(read_manifest(tmp_path))


def test_a_manifest_that_would_publish_a_path_is_refused_rather_than_written_quietly(
    tmp_path: Path,
) -> None:
    """The last line of defence for the privacy contract.

    ``recorded_path`` keeps paths out of the observed sections, but a contract can
    put arbitrary text into the recorded terms. The gate scans its own rendered
    manifest before writing, so a value shaped like a user directory fails the gate
    instead of being uploaded to a public CI artifact.
    """
    build_tree(tmp_path, declaration=contract(architecture="C:/Users/Someone"))

    assert run(tmp_path) == gate.EXIT_GATE_FAILED
    assert REASON_MANIFEST_LEAKAGE in reasons_of(read_manifest(tmp_path))


def test_a_non_deterministic_manifest_fails_rather_than_being_written_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Determinism is checked rather than asserted in a docstring.

    Two builds of one run must render the same bytes, or the document is not evidence about a
    commit.
    """
    build_tree(tmp_path, declaration=contract())
    renderings = iter(("first\n", "second\n", "third\n", "fourth\n"))
    monkeypatch.setattr(gate, "render_manifest", lambda _document: next(renderings))

    assert run(tmp_path) == gate.EXIT_GATE_FAILED


def test_an_interpreter_with_no_importable_pip_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`pip install` would have nothing to run.

    That is a different fault from pip belonging to another interpreter and gets its own
    message.
    """
    build_tree(tmp_path, declaration=contract())
    monkeypatch.setattr(gate, "_pip_origin", lambda: None)

    assert run(tmp_path) == gate.EXIT_GATE_FAILED

    document = read_manifest(tmp_path)
    assert REASON_PIP_FOREIGN in reasons_of(document)
    origin = findings_of(document)["pip_origin"]
    assert isinstance(origin, dict)
    assert "no pip is importable" in str(origin["problems"])


def test_the_exit_code_matches_the_recorded_verdict(tmp_path: Path) -> None:
    """Three-valued, and the codes are the ones every other gate uses."""
    build_tree(tmp_path, declaration=contract(), environment=False)
    code = run(tmp_path)

    verdict = read_manifest(tmp_path)["verdict"]
    assert isinstance(verdict, dict)
    assert (code, verdict["verdict"]) == (gate.EXIT_GATE_FAILED, "failed")


def test_the_manifest_is_written_where_the_gate_says_it_is(tmp_path: Path) -> None:
    build_tree(tmp_path, declaration=contract())
    run(tmp_path)
    assert (tmp_path / "out" / gate.MANIFEST_NAME).is_file()
    assert gate.OUTPUT_DIRECTORY.startswith(".globin/")


def test_the_manifest_is_valid_json_with_a_trailing_newline(tmp_path: Path) -> None:
    build_tree(tmp_path, declaration=contract())
    run(tmp_path)
    rendered = (tmp_path / "out" / gate.MANIFEST_NAME).read_text(encoding="utf-8")
    assert rendered.endswith("\n")
    assert isinstance(json.loads(rendered), dict)


@pytest.mark.parametrize("subcommand", ["check", "bootstrap"])
def test_neither_subcommand_writes_outside_its_reports_directory(
    tmp_path: Path, subcommand: str
) -> None:
    """Whatever else the gate does, it does not scatter files through the tree."""
    build_tree(tmp_path, declaration=contract(), environment=False)
    before = {path for path in tmp_path.rglob("*") if path.is_file()}

    run(tmp_path, bootstrap=subcommand == "bootstrap")

    after = {path for path in tmp_path.rglob("*") if path.is_file()}
    created = after - before
    permitted = tmp_path / "out"
    environment = tmp_path / ".venv"
    assert all(
        path.is_relative_to(permitted) or path.is_relative_to(environment) for path in created
    ), f"unexpected files: {sorted(str(path) for path in created)}"
