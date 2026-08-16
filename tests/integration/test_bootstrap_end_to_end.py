"""The whole bootstrap against real trees, from the composition root down.

Every tree here is temporary and built by this file, so each is exactly what its
test describes. Nothing reaches the network, nothing starts a process, and the
one thing written is the manifest — inside the temporary tree, never beside the
repository.

Where ``tests/unit/test_bootstrap_application.py`` substitutes every probe, this
substitutes none: the composition root wires the real ones, and what is varied is
the tree they read.
"""

import json
from pathlib import Path

import pytest

from globin.adapters.bootstrap import MANIFEST_NAME, load, render
from globin.adapters.bootstrap import build as build_manifest
from globin.domain.bootstrap import BootstrapOutcome, CheckStatus, ExitCode, RuntimePaths
from globin.errors import ConfigurationError
from globin.runtime.cli import main
from globin.runtime.composition import build_bootstrap
from tests.support import REPO_ROOT, running_from_the_project_environment

CONTRACT = """\
schema = 1

[interpreter]
implementation = "{implementation}"
minor_line = "{minor_line}"
minimum_patch = "{minimum_patch}"
architecture = "{architecture}"
pointer_bits = {pointer_bits}
free_threaded = false
allow_prerelease = true

[host]
system = "{system}"
minimum_release = "{minimum_release}"

[environment]
directory = "{directory}"
system_site_packages = false
"""

PROJECT = """\
[project]
name = "globin"
version = "0.1.0"
dependencies = {dependencies}
"""

#: A distribution every environment that can run this suite certainly has.
#:
#: `dependency_outcome` reports a MISSING dependency before an unlocked one, so
#: reaching the unlocked branch needs something actually installed. Naming a
#: runtime dependency of this project would not do: the continuous-integration
#: `quality` job installs the toolchain and nothing else, so `numpy` is absent
#: there and present here — and a fixture whose branch depends on which machine
#: runs it is a fixture that passes locally and fails in CI, which is exactly
#: what it did.
DECLARED_PRESENT = '["pytest"]'

#: A distribution no index has, so "locked and still not installed" is reachable
#: without installing anything.
DECLARED_ABSENT = '["nothing-is-called-this-anywhere"]'


def checkout(root: Path, **overrides: object) -> Path:
    """A tree the bootstrap can read, declaring a contract this host satisfies.

    The contract is written from what this interpreter actually is, so the tests
    below vary one field at a time and every other check still passes. Writing
    fixed values instead would make every test here fail on the day the pinned
    line moves, for a reason none of them is about.
    """
    import platform
    import struct
    import sys

    values: dict[str, object] = {
        "implementation": sys.implementation.name,
        "minor_line": f"{sys.version_info.major}.{sys.version_info.minor}",
        "minimum_patch": f"{sys.version_info.major}.{sys.version_info.minor}.0",
        "architecture": platform.machine(),
        "pointer_bits": struct.calcsize("P") * 8,
        "system": platform.system(),
        "minimum_release": "0",
        "directory": Path(sys.prefix).name,
    }
    dependencies = overrides.pop("dependencies", "[]")
    lock = overrides.pop("lock", False)
    values.update(overrides)

    (root / "pyproject.toml").write_text(
        PROJECT.format(dependencies=dependencies), encoding="utf-8", newline="\n"
    )
    engineering = root / "docs" / "engineering"
    engineering.mkdir(parents=True, exist_ok=True)
    (engineering / "runtime-contract.toml").write_text(
        CONTRACT.format(**values), encoding="utf-8", newline="\n"
    )
    if lock:
        (root / "pylock.toml").write_text('lock-version = "1.0"\n', encoding="utf-8", newline="\n")
    return root


def run(root: Path, *, gate: bool = True) -> BootstrapOutcome:
    """One bootstrap against a tree, wired by the composition root."""
    return build_bootstrap(root).run(stop_at_first_refusal=gate)


def section(outcome: BootstrapOutcome, name: str) -> dict[str, object]:
    """One section of what a run observed, narrowed so it can be indexed.

    `observed` is a mapping of `object`, because the manifest carries whatever a
    section chose to record. Narrowing once here is cheaper than a cast at every
    assertion, and it fails loudly if a section stops being a mapping.
    """
    assert outcome.observed is not None
    record = outcome.observed[name]
    assert isinstance(record, dict)
    return record


# ---------------------------------------------------------------------------
# A tree this host satisfies
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not running_from_the_project_environment(),
    reason="this asserts about the project's own .venv, which this interpreter is not",
)
def test_this_repository_bootstraps() -> None:
    """The control, and it has to be this repository rather than a temporary tree.

    `python.environment` compares `sys.prefix` against the declared environment
    directory *inside the project root*, and the interpreter running this suite
    lives in the real `.venv`. A temporary checkout therefore cannot satisfy that
    check however its contract is written — which is the check working rather than
    a limitation to route around. So the passing case is the repository itself,
    and every temporary tree below exercises a refusal.
    """
    outcome = run(REPO_ROOT)
    assert outcome.ready, [
        (check.identifier, check.summary)
        for check in outcome.report.outcomes
        if check.status is not CheckStatus.PASS
    ]
    assert outcome.exit_code is ExitCode.OK


def test_a_temporary_checkout_is_refused_because_it_is_not_this_environment(
    tmp_path: Path,
) -> None:
    """Stated as a test rather than left as a footnote to the one above.

    An interpreter belonging to another project's environment is exactly the
    mistake `python.environment` exists to catch, and a temporary tree is the
    cheapest way to produce one.
    """
    outcome = run(checkout(tmp_path))
    assert outcome.exit_code is ExitCode.ENVIRONMENT_MISMATCH
    assert outcome.report.outcomes[-1].identifier == "python.environment"


def test_only_the_allowlisted_directories_appear(tmp_path: Path) -> None:
    """A bootstrap creates the evidence tree and nothing else.

    Run as a diagnostic, because a gate stops at the first refusal and this tree
    refuses at `python.environment` before the runtime tree is ever prepared.
    """
    root = checkout(tmp_path)
    before = {path.name for path in root.iterdir()}
    run(root, gate=False)
    after = {path.name for path in root.iterdir()}
    assert after - before == {".globin"}
    assert (root / RuntimePaths().evidence).is_dir()
    assert not (root / RuntimePaths().logs).exists()
    assert not (root / RuntimePaths().config).exists()


def test_running_twice_leaves_the_tree_as_it_was(tmp_path: Path) -> None:
    """Idempotent: a check changes no configuration, dependency or credential."""
    root = checkout(tmp_path)
    run(root, gate=False)
    first = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    run(root, gate=False)
    assert sorted(path.relative_to(root).as_posix() for path in root.rglob("*")) == first


# ---------------------------------------------------------------------------
# Trees this host does not satisfy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "code", "identifier"),
    [
        pytest.param(
            {"system": "Plan9"}, ExitCode.HOST_UNSUPPORTED, "runtime.host", id="another-system"
        ),
        pytest.param(
            {"minimum_release": "9999"},
            ExitCode.HOST_UNSUPPORTED,
            "runtime.host",
            id="a-newer-floor",
        ),
        pytest.param(
            {"architecture": "SPARC"},
            ExitCode.HOST_UNSUPPORTED,
            "runtime.architecture",
            id="another-architecture",
        ),
        pytest.param(
            {"pointer_bits": 16},
            ExitCode.HOST_UNSUPPORTED,
            "runtime.architecture",
            id="another-width",
        ),
        pytest.param(
            {"implementation": "IronPython"},
            ExitCode.INTERPRETER_MISMATCH,
            "python.implementation",
            id="another-implementation",
        ),
        pytest.param(
            {"minor_line": "2.7"},
            ExitCode.INTERPRETER_MISMATCH,
            "python.version",
            id="another-minor-line",
        ),
        pytest.param(
            {"minimum_patch": "99.99.99"},
            ExitCode.INTERPRETER_MISMATCH,
            "python.version",
            id="an-unreachable-patch-floor",
        ),
        pytest.param(
            {"directory": "somewhere-else"},
            ExitCode.ENVIRONMENT_MISMATCH,
            "python.environment",
            id="another-environment-directory",
        ),
    ],
)
def test_a_tree_this_host_does_not_satisfy_refuses_with_its_own_code(
    tmp_path: Path, overrides: dict[str, object], code: ExitCode, identifier: str
) -> None:
    """Each failure class, end to end, and no context on any of them."""
    outcome = run(checkout(tmp_path, **overrides))
    assert outcome.exit_code is code
    assert outcome.context is None
    assert outcome.report.outcomes[-1].identifier == identifier
    assert outcome.report.outcomes[-1].status is CheckStatus.FAIL


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        pytest.param(
            {"dependencies": DECLARED_PRESENT}, "no runtime lock", id="declared-but-unlocked"
        ),
        pytest.param(
            {"dependencies": DECLARED_ABSENT, "lock": True},
            "not installed",
            id="locked-but-absent",
        ),
    ],
)
def test_a_dependency_the_environment_cannot_satisfy_is_refused(
    tmp_path: Path, overrides: dict[str, object], fragment: str
) -> None:
    """Run as a diagnostic, because `dependency.lock` comes after the environment.

    A gate would stop at `python.environment` — correctly, since a temporary tree
    is not this environment — and never reach the check under test.
    """
    outcome = run(checkout(tmp_path, **overrides), gate=False)
    assert outcome.report.status_of("dependency.lock") is CheckStatus.FAIL
    summary = next(
        check.summary for check in outcome.report.outcomes if check.identifier == "dependency.lock"
    )
    assert fragment in summary
    assert outcome.context is None


def test_a_tree_that_is_not_a_checkout_refuses_before_reading_anything(tmp_path: Path) -> None:
    """Nothing under an unrecognised directory is read, and nothing is created."""
    outcome = run(tmp_path)
    assert outcome.exit_code is ExitCode.PATHS_UNUSABLE
    assert not list(tmp_path.iterdir())


def test_a_tree_with_no_runtime_contract_is_unmeasured_rather_than_failed(
    tmp_path: Path,
) -> None:
    """A bootstrap that cannot read what it enforces has measured nothing."""
    root = checkout(tmp_path)
    (root / "docs" / "engineering" / "runtime-contract.toml").unlink()
    outcome = run(root)
    assert outcome.exit_code is ExitCode.UNMEASURED
    assert outcome.report.outcomes[-1].status is CheckStatus.UNMEASURED


def test_a_malformed_runtime_contract_is_reported_rather_than_partly_read(
    tmp_path: Path,
) -> None:
    """Nothing is defaulted, so a hole in the contract is a hole in the answer."""
    root = checkout(tmp_path)
    (root / "docs" / "engineering" / "runtime-contract.toml").write_text(
        "[interpreter]\nimplementation = 'CPython'\n", encoding="utf-8"
    )
    outcome = run(root)
    assert outcome.exit_code is ExitCode.UNMEASURED


# ---------------------------------------------------------------------------
# Working-directory independence
# ---------------------------------------------------------------------------


def test_the_same_project_is_found_from_every_directory_inside_it(tmp_path: Path) -> None:
    """The whole point of the bounded upward search."""
    root = checkout(tmp_path)
    nested = root / "src" / "globin" / "domain"
    nested.mkdir(parents=True)
    top = run(root, gate=False)
    deep = run(nested, gate=False)
    assert section(top, "project")["root"] == section(deep, "project")["root"]
    assert section(top, "interpreter") == section(deep, "interpreter")
    assert [check.status for check in top.report.outcomes] == [
        check.status for check in deep.report.outcomes
    ]


def test_a_checkout_nested_inside_another_project_does_not_borrow_its_parent(
    tmp_path: Path,
) -> None:
    """A `pyproject.toml` naming something else is not this project's root."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "unrelated"\n', encoding="utf-8")
    inner = tmp_path / "workspace" / "globin"
    inner.mkdir(parents=True)
    checkout(inner)
    outcome = run(inner, gate=False)
    assert section(outcome, "project")["root"] == {"location": "repository", "path": "."}
    assert (inner / ".globin").is_dir()
    assert not (tmp_path / ".globin").exists()


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def test_the_manifest_is_written_inside_the_tree_and_reads_back(tmp_path: Path) -> None:
    """Sealed, so a hand edit is refused rather than believed."""
    root = checkout(tmp_path)
    bootstrap = build_bootstrap(root)
    outcome = bootstrap.run(stop_at_first_refusal=False)
    recorded = bootstrap.record(outcome)
    assert recorded.path == f"{RuntimePaths().evidence}/{MANIFEST_NAME}"
    document = load((root / RuntimePaths().evidence / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert document["phase"] == 21


def test_two_runs_over_one_unchanged_tree_produce_identical_bytes(tmp_path: Path) -> None:
    """Determinism, checked rather than claimed."""
    root = checkout(tmp_path)
    first = render(build_manifest(run(root, gate=False)))
    second = render(build_manifest(run(root, gate=False)))
    assert first == second


def test_evidence_cannot_be_written_where_there_is_no_project(tmp_path: Path) -> None:
    """Nothing is written outside the project root, so a refusal is the only answer."""
    bootstrap = build_bootstrap(tmp_path)
    outcome = bootstrap.run(stop_at_first_refusal=True)
    with pytest.raises(ConfigurationError, match="nowhere to write evidence"):
        bootstrap.record(outcome)
    assert not list(tmp_path.iterdir())


# ---------------------------------------------------------------------------
# Through the command line
# ---------------------------------------------------------------------------


def test_the_command_line_reports_the_same_verdict_as_the_pipeline(tmp_path: Path) -> None:
    """One implementation, reached two ways."""
    import io

    root = checkout(tmp_path)
    out = io.StringIO()
    code = main(["bootstrap", "check", "--json"], stdout=out, stderr=io.StringIO(), start=root)
    document = json.loads(out.getvalue())
    assert code == int(run(root).exit_code)
    assert document["verdict"]["exit_code"] == code


def test_a_refused_run_still_writes_its_evidence(tmp_path: Path) -> None:
    """A gate that failed silently and left no artefact looks like one that never ran."""
    import io

    root = checkout(tmp_path, system="Plan9")
    code = main(["bootstrap", "evidence"], stdout=io.StringIO(), stderr=io.StringIO(), start=root)
    assert code == int(ExitCode.HOST_UNSUPPORTED)
    document = load((root / RuntimePaths().evidence / MANIFEST_NAME).read_text(encoding="utf-8"))
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["ready"] is False
    assert verdict["reasons"] == ["BOOTSTRAP_RUNTIME_HOST"]
