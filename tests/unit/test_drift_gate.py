"""The drift gate: what it reads, what it refuses, and what it writes.

Built against synthetic trees in ``tmp_path`` rather than against this repository,
so that a test can express a drifted host without one existing. The host
observation is substituted where the test is about the comparison; where it is
about the observation itself, ``tests/integration/test_drift_end_to_end.py``
drives the real thing.

**Nothing here starts a process and nothing reaches a network.** The gate reaches
nothing by construction — both halves of its comparison are local — which is why
it has no injected fetcher and no ``network`` marker anywhere in this file.
"""

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from tools.quality.drift import gate, manifest
from tools.quality.drift.manifest import build as build_manifest

POLICY = """\
schema = 1

[[class]]
key = "interpreter.version"
severity = "conditional"
rule = "interpreter-version"
repair = "recreate"
writes = "nothing"
reason = "Depends which way it moved."

[[class]]
key = "environment.system_site_packages"
severity = "violation"
repair = "in-place"
action = "set include-system-site-packages to false in the environment's pyvenv.cfg"
writes = "environment"
reason = "The environment can see the machine's global packages."

[[class]]
key = "host.kernel"
severity = "material"
repair = "operator"
writes = "nothing"
reason = "Windows was patched."
"""

CONTRACT = """\
schema = 1

[interpreter]
implementation = "CPython"
minor_line = "3.14"
minimum_patch = "3.14.5"
architecture = "AMD64"
pointer_bits = 64
free_threaded = false
allow_prerelease = false

[host]
system = "Windows"
minimum_release = "10"

[environment]
directory = ".venv"
system_site_packages = false
"""

OBSERVATION: dict[str, object] = {
    "host": {"system": "Windows", "kernel": "10.0.26200"},
    "interpreter": {"version": "3.14.5"},
    "environment": {"system_site_packages": "false"},
}
"""A host the policy above fully classifies."""


def build_tree(root: Path, *, policy: str = POLICY, contract: str = CONTRACT) -> Path:
    """Write the two files the gate reads, and a Git head for it to record.

    Args:
        root: Where to build.
        policy: The drift policy.
        contract: The runtime contract.

    Returns:
        The root.
    """
    engineering = root / "docs" / "engineering"
    engineering.mkdir(parents=True)
    (engineering / "drift-policy.toml").write_text(policy, encoding="utf-8")
    (engineering / "runtime-contract.toml").write_text(contract, encoding="utf-8")
    git = root / ".git"
    git.mkdir()
    (git / "HEAD").write_text("a" * 40, encoding="utf-8")
    (root / ".venv").mkdir()
    return root


@pytest.fixture
def reports(tmp_path: Path) -> Path:
    """Where a run writes, kept out of the tree it reads."""
    directory = tmp_path / "reports"
    directory.mkdir()
    return directory


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A tree the gate can read."""
    return build_tree(tmp_path / "tree")


Observer = Callable[[Path, object], dict[str, object]]
"""The shape of :func:`tools.quality.drift.gate.observe`, named so a double can claim it."""


def fixed(observation: Mapping[str, object]) -> Observer:
    """Return a substitute for :func:`tools.quality.drift.gate.observe`.

    Args:
        observation: What the host should appear to be.

    Returns:
        A callable with ``observe``'s signature. A hand-written double rather than
        a mock, which is this repository's default: a mock would satisfy any
        signature, including one the real function does not have.
    """

    def observe(root: Path, contract: object) -> dict[str, object]:
        del root, contract
        return dict(observation)

    return observe


def read_manifest(directory: Path) -> dict[str, object]:
    """Read the manifest a run wrote.

    Args:
        directory: Where it wrote.

    Returns:
        The manifest, verified.
    """
    return manifest.load((directory / gate.MANIFEST_NAME).read_text(encoding="utf-8"))


def reasons_of(document: dict[str, object]) -> list[str]:
    """Return the reason codes a manifest records.

    Args:
        document: The manifest.

    Returns:
        The codes.
    """
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    return list(verdict["reasons"])


# ---------------------------------------------------------------------------
# Reading the declarations
# ---------------------------------------------------------------------------


def test_an_absent_policy_is_unmeasured_and_still_leaves_a_manifest(
    tmp_path: Path, reports: Path
) -> None:
    """A gate that failed silently would be indistinguishable from one that never ran."""
    root = tmp_path / "empty"
    root.mkdir()
    assert gate.run_drift(root=root, reports=reports) == gate.EXIT_UNMEASURED
    assert manifest.REASON_DECLARATION_UNREADABLE in reasons_of(read_manifest(reports))


def test_a_malformed_policy_is_unmeasured(tmp_path: Path, reports: Path) -> None:
    """Malformed and absent are both "could not read", and neither is a pass."""
    root = build_tree(tmp_path / "tree", policy="[[class]\n")
    assert gate.run_drift(root=root, reports=reports) == gate.EXIT_UNMEASURED
    assert manifest.REASON_DECLARATION_UNREADABLE in reasons_of(read_manifest(reports))


def test_an_absent_runtime_contract_is_unmeasured(tmp_path: Path, reports: Path) -> None:
    """The contract names the environment, so without it there is nothing to observe."""
    root = build_tree(tmp_path / "tree")
    (root / "docs" / "engineering" / "runtime-contract.toml").unlink()
    assert gate.run_drift(root=root, reports=reports) == gate.EXIT_UNMEASURED
    assert manifest.REASON_DECLARATION_UNREADABLE in reasons_of(read_manifest(reports))


def test_a_policy_that_contradicts_itself_fails(
    tmp_path: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recompute, reached through the gate rather than only through the plan.

    The run is *unmeasured* rather than *failed*, and that is not a weaker answer:
    this host has accepted no baseline, and `combine` ranks unmeasured above
    failed precisely so that "the comparison did not happen" outranks "the
    comparison found something". Both codes are recorded either way.
    """
    broken = POLICY.replace(
        'action = "set include-system-site-packages to false in the environment\'s pyvenv.cfg"\n',
        "",
    )
    root = build_tree(tmp_path / "tree", policy=broken)
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    assert gate.run_drift(root=root, reports=reports) != gate.EXIT_OK
    assert manifest.REASON_POLICY_INCONSISTENT in reasons_of(read_manifest(reports))


# ---------------------------------------------------------------------------
# The baseline, and the three states it has
# ---------------------------------------------------------------------------


def test_with_no_baseline_the_result_is_unmeasured_rather_than_clean(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not looking and finding nothing are different facts.

    `DEPENDENCY_POLICY.md` prohibits conflating them by name, and a first run
    reporting a clean host would be exactly that conflation.
    """
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    assert gate.run_drift(root=tree, reports=reports) == gate.EXIT_UNMEASURED
    document = read_manifest(reports)
    findings = document["findings"]
    assert isinstance(findings, dict)
    assert findings["baseline"]["verdict"] == "unmeasured"


def test_check_does_not_write_a_baseline(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A check that recorded what it found would certify its own observation.

    Drift would then be undetectable by construction, because every run would
    accept whatever the previous one had drifted into.
    """
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports)
    assert not (reports / gate.BASELINE_NAME).is_file()


def test_accept_records_a_baseline_and_passes(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deliberate act that gives the comparison something to compare against."""
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    assert gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT) == gate.EXIT_OK
    recorded = manifest.load_baseline((reports / gate.BASELINE_NAME).read_text(encoding="utf-8"))
    observation = recorded["observation"]
    assert isinstance(observation, dict)
    assert observation["interpreter.version"] == "3.14.5"


def test_a_check_against_an_unchanged_host_passes(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The identity case, through the gate. Without it, nothing else here means much."""
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    assert gate.run_drift(root=tree, reports=reports) == gate.EXIT_OK


def test_accept_refuses_to_record_against_a_policy_that_contradicts_itself(
    tmp_path: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accepting under a broken policy would freeze a baseline nobody can classify."""
    broken = POLICY.replace('severity = "material"', 'severity = "benign"')
    root = build_tree(tmp_path / "tree", policy=broken)
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    assert gate.run_drift(root=root, reports=reports, mode=gate.ACCEPT) == gate.EXIT_GATE_FAILED
    assert not (reports / gate.BASELINE_NAME).is_file()


def test_a_corrupted_baseline_is_unmeasured_rather_than_treated_as_absent(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken file reading as a first run would silently discard the comparison."""
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    (reports / gate.BASELINE_NAME).write_text("{", encoding="utf-8")
    assert gate.run_drift(root=tree, reports=reports) == gate.EXIT_UNMEASURED
    assert manifest.REASON_BASELINE_UNREADABLE in reasons_of(read_manifest(reports))


def test_a_baseline_edited_by_hand_is_refused(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the digest is for, exercised through the gate rather than only the reader."""
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    path = reports / gate.BASELINE_NAME
    path.write_text(path.read_text(encoding="utf-8").replace("3.14.5", "3.14.6"), encoding="utf-8")
    assert gate.run_drift(root=tree, reports=reports) == gate.EXIT_UNMEASURED
    assert manifest.REASON_BASELINE_UNREADABLE in reasons_of(read_manifest(reports))


# ---------------------------------------------------------------------------
# Detecting and classifying drift
# ---------------------------------------------------------------------------


def drifted(**changes: str) -> dict[str, object]:
    """Return the reference observation with the named leaves replaced.

    Args:
        changes: Dotted keys mapped to their new values.

    Returns:
        A nested observation.

    One helper rather than a nested literal per test, because the difference
    between two of these tests should be visible as the one value that differs.
    """
    observation: dict[str, object] = {}
    for name, values in OBSERVATION.items():
        assert isinstance(values, dict)
        observation[name] = dict(values)
    for dotted, value in changes.items():
        section, _, leaf = dotted.partition("__")
        area = observation[section]
        assert isinstance(area, dict)
        area[leaf] = value
    return observation


@pytest.mark.parametrize(
    ("changes", "code", "why"),
    [
        (
            {"environment__system_site_packages": "true"},
            manifest.REASON_CONTRACT_VIOLATED,
            "the environment can see the machine's packages",
        ),
        (
            {"environment__system_site_packages": "true"},
            manifest.REASON_REPAIRABLE,
            "and that one is repairable in place",
        ),
        (
            {"interpreter__version": "3.15.0"},
            manifest.REASON_RECREATE_REQUIRED,
            "a different minor line needs a rebuild",
        ),
        (
            {"host__kernel": "10.0.99999"},
            manifest.REASON_OPERATOR_REQUIRED,
            "a patched host is outside what this tool may change",
        ),
    ],
)
def test_drift_earns_the_reason_code_its_class_implies(
    tree: Path,
    reports: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, str],
    code: str,
    why: str,
) -> None:
    """Each repair verdict reaches the manifest as its own code."""
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    monkeypatch.setattr(gate, "observe", fixed(drifted(**changes)))
    assert gate.run_drift(root=tree, reports=reports) == gate.EXIT_GATE_FAILED
    assert code in reasons_of(read_manifest(reports)), why


def test_a_forward_patch_does_not_fail_the_gate(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failing here would reinstate the exact pin the runtime contract refused.

    It is still recorded, because "the interpreter moved and it was fine" is worth
    being able to read afterwards.
    """
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    monkeypatch.setattr(gate, "observe", fixed(drifted(interpreter__version="3.14.9")))
    assert gate.run_drift(root=tree, reports=reports) == gate.EXIT_OK
    findings = read_manifest(reports)["findings"]
    assert isinstance(findings, dict)
    (recorded,) = findings["drift"]["differences"]
    assert recorded["severity"] == "benign"


def test_a_backward_patch_does_fail_the_gate(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`runtime` passes on this, correctly, and something still changed the machine."""
    monkeypatch.setattr(gate, "observe", fixed(drifted(interpreter__version="3.14.9")))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    assert gate.run_drift(root=tree, reports=reports) == gate.EXIT_GATE_FAILED


def test_a_change_nothing_classifies_fails_rather_than_passing_quietly(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise the day a new observation key starts moving is the day coverage stops."""
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    unclassified = {**OBSERVATION, "invented": {"key": "1"}}
    monkeypatch.setattr(gate, "observe", fixed(unclassified))
    assert gate.run_drift(root=tree, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_CLASS_UNDECLARED in reasons_of(read_manifest(reports))


# ---------------------------------------------------------------------------
# The write boundary
# ---------------------------------------------------------------------------


def test_a_write_inside_the_environment_is_permitted(tree: Path) -> None:
    """The guard has to permit the one thing repair does, or it permits nothing."""
    environment = tree / ".venv"
    assert gate.write_problems(environment / "pyvenv.cfg", root=tree, environment=environment) == ()


def test_a_write_outside_the_environment_is_refused(tree: Path) -> None:
    """Repair writes only inside the environment. ADR-0050 draws that line."""
    (problem,) = gate.write_problems(tree / "elsewhere", root=tree, environment=tree / ".venv")
    assert "outside the environment" in problem


def test_an_environment_outside_the_repository_is_refused(tmp_path: Path, tree: Path) -> None:
    """An environment resolving off-tree is a misconfiguration, not a place to edit files."""
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    problems = gate.write_problems(foreign / "pyvenv.cfg", root=tree, environment=foreign)
    assert any("outside the repository" in problem for problem in problems)


def test_a_target_that_cannot_be_resolved_is_refused_rather_than_written(tree: Path) -> None:
    """Unresolvable is not permitted-by-default; a path nobody can place is out of bounds."""
    problems = gate.write_problems(
        tree / ".venv" / ("x" * 400), root=tree, environment=tree / ".venv"
    )
    assert problems == () or any("in bounds" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------


def test_the_one_in_place_repair_rewrites_one_key_and_leaves_the_rest(tree: Path) -> None:
    """`home` records which interpreter built the environment, and is not repair's business."""
    environment = tree / ".venv"
    config = environment / "pyvenv.cfg"
    config.write_text(
        "home = C:\\Python314\ninclude-system-site-packages = true\nversion = 3.14.5\n",
        encoding="utf-8",
    )
    assert gate.repair_site_packages(tree, environment) == ()
    rewritten = config.read_text(encoding="utf-8")
    assert "include-system-site-packages = false" in rewritten
    assert "home = C:\\Python314" in rewritten
    assert "version = 3.14.5" in rewritten


def test_the_repair_adds_the_key_when_the_file_does_not_carry_it(tree: Path) -> None:
    """An environment whose config omits the key is corrected rather than left ambiguous."""
    environment = tree / ".venv"
    (environment / "pyvenv.cfg").write_text("home = C:\\Python314\n", encoding="utf-8")
    assert gate.repair_site_packages(tree, environment) == ()
    assert "include-system-site-packages = false" in (environment / "pyvenv.cfg").read_text(
        encoding="utf-8"
    )


def test_a_repair_with_no_file_to_repair_reports_rather_than_raises(tree: Path) -> None:
    """A missing config is a diagnosis, not a traceback."""
    (problem,) = gate.repair_site_packages(tree, tree / ".venv")
    assert "could not be read" in problem


def test_a_repair_outside_the_boundary_is_refused_before_anything_is_read(
    tmp_path: Path, tree: Path
) -> None:
    """The guard runs first, so a refused repair never opens the file."""
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    problems = gate.repair_site_packages(tree, foreign)
    assert any("outside the repository" in problem for problem in problems)


def test_repair_performs_the_repair_and_the_next_check_is_clean(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: a fault that today is answered with "rebuild" is corrected in place."""
    environment = tree / ".venv"
    (environment / "pyvenv.cfg").write_text(
        "home = C:\\Python314\ninclude-system-site-packages = true\n", encoding="utf-8"
    )
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)

    state = {"repaired": False}

    def observe(root: Path, contract: object) -> dict[str, object]:
        del root, contract
        if state["repaired"]:
            return OBSERVATION
        return drifted(environment__system_site_packages="true")

    perform = gate.repair_site_packages

    def repair(root: Path, environment: Path) -> tuple[str, ...]:
        state["repaired"] = True
        return perform(root, environment)

    monkeypatch.setattr(gate, "observe", observe)
    monkeypatch.setattr(gate, "repair_site_packages", repair)
    assert gate.run_drift(root=tree, reports=reports, mode=gate.REPAIR) == gate.EXIT_OK
    findings = read_manifest(reports)["findings"]
    assert isinstance(findings, dict)
    assert findings["repairs"]["performed"]


def test_a_repair_the_policy_promises_and_the_tool_cannot_perform_is_refused(
    tmp_path: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skipping it would let the policy promise a repair and report success anyway."""
    policy = """\
schema = 1

[[class]]
key = "interpreter.version"
severity = "conditional"
rule = "interpreter-version"
repair = "recreate"
writes = "nothing"
reason = "Depends which way it moved."

[[class]]
key = "host.kernel"
severity = "material"
repair = "in-place"
action = "something this tool has no implementation for"
writes = "environment"
reason = "A promise the tool cannot keep."
"""
    root = build_tree(tmp_path / "tree", policy=policy)
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=root, reports=reports, mode=gate.ACCEPT)
    monkeypatch.setattr(gate, "observe", fixed(drifted(host__kernel="10.0.99999")))
    assert gate.run_drift(root=root, reports=reports, mode=gate.REPAIR) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_REPAIR_REFUSED in reasons_of(read_manifest(reports))


def test_a_repair_that_fails_is_reported_as_failed(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repair that did not happen must never read as one that did."""
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    monkeypatch.setattr(gate, "observe", fixed(drifted(environment__system_site_packages="true")))
    assert gate.run_drift(root=tree, reports=reports, mode=gate.REPAIR) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_REPAIR_FAILED in reasons_of(read_manifest(reports))


def test_every_repair_named_in_the_table_can_be_performed() -> None:
    """A name in the table with nothing behind it is a promise the tool cannot keep."""
    for name in gate.REPAIRS.values():
        assert name == "repair_site_packages"


# ---------------------------------------------------------------------------
# The manifest the gate writes
# ---------------------------------------------------------------------------


def test_a_manifest_that_renders_differently_twice_fails_rather_than_being_written(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Determinism is checked rather than asserted, so the check itself is checked.

    A guard nothing ever exercises is a guard nobody knows is inverted.
    """
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    calls = {"n": 0}

    def drifting(
        *,
        run: Mapping[str, object],
        findings: Mapping[str, object],
        verdict: Mapping[str, object],
    ) -> dict[str, object]:
        calls["n"] += 1
        document = build_manifest(run=run, findings=findings, verdict=verdict)
        if calls["n"] == 2:
            document["phase"] = 999
        return document

    monkeypatch.setattr(gate, "build_manifest", drifting)
    assert gate.run_drift(root=tree, reports=reports) == gate.EXIT_UNMEASURED
    assert manifest.REASON_MANIFEST_NONDETERMINISTIC in reasons_of(read_manifest(reports))


def test_a_baseline_carrying_a_home_directory_path_is_refused_rather_than_written(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.globin/` is uploaded, and every absolute path on this host carries a person's name.

    `recorded_path` should have fingerprinted it long before here. "Should have"
    is not a control, and the baseline is written by a different branch from the
    manifest, so it needs its own.
    """
    leaking = {**OBSERVATION, "environment": {"location": "C:\\Users\\somebody\\GLOBIN\\.venv"}}
    monkeypatch.setattr(gate, "observe", fixed(leaking))
    assert gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT) == gate.EXIT_UNMEASURED
    assert manifest.REASON_MANIFEST_LEAKAGE in reasons_of(read_manifest(reports))
    assert not (reports / gate.BASELINE_NAME).is_file()


def test_a_manifest_carrying_a_home_directory_path_is_refused_rather_than_written(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same control on the other document, where a drifted value reaches the report."""
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    monkeypatch.setattr(gate, "observe", fixed(drifted(host__kernel="C:\\Users\\somebody\\kernel")))
    assert gate.run_drift(root=tree, reports=reports) == gate.EXIT_UNMEASURED
    assert manifest.REASON_MANIFEST_LEAKAGE in reasons_of(read_manifest(reports))


def test_the_manifest_records_no_wall_clock(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A document that changed because it was built on a different day cannot be compared."""
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    run = read_manifest(reports)["run"]
    assert isinstance(run, dict)
    assert set(run) == {"repository", "commit", "declaration", "contract", "mode"}


def test_the_manifest_records_which_subcommand_ran(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three modes write to one filename, so the document has to say which produced it."""
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    run = read_manifest(reports)["run"]
    assert isinstance(run, dict)
    assert run["mode"] == gate.ACCEPT


def test_two_runs_of_an_unchanged_host_write_identical_bytes(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The determinism claim, made against the file rather than against the builder."""
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    gate.run_drift(root=tree, reports=reports)
    first = (reports / gate.MANIFEST_NAME).read_bytes()
    gate.run_drift(root=tree, reports=reports)
    assert (reports / gate.MANIFEST_NAME).read_bytes() == first


def test_a_commit_that_cannot_be_read_is_recorded_as_unknown(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gate that cannot read a file says so rather than failing over it."""
    (tree / ".git" / "HEAD").unlink()
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    run = read_manifest(reports)["run"]
    assert isinstance(run, dict)
    assert run["commit"] == "unknown"


def test_a_symbolic_head_is_followed_to_the_commit(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary shape of `.git/HEAD` on a checked-out branch."""
    head = tree / ".git" / "HEAD"
    head.write_text("ref: refs/heads/master\n", encoding="utf-8")
    reference = tree / ".git" / "refs" / "heads"
    reference.mkdir(parents=True)
    (reference / "master").write_text("b" * 40, encoding="utf-8")
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    run = read_manifest(reports)["run"]
    assert isinstance(run, dict)
    assert run["commit"] == "b" * 40


def test_a_head_pointing_at_a_missing_reference_is_recorded_as_unknown(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A detached or half-written `.git` is a diagnosis, not a reason to fail."""
    (tree / ".git" / "HEAD").write_text("ref: refs/heads/gone\n", encoding="utf-8")
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    gate.run_drift(root=tree, reports=reports, mode=gate.ACCEPT)
    run = read_manifest(reports)["run"]
    assert isinstance(run, dict)
    assert run["commit"] == "unknown"


def test_the_exit_codes_are_the_three_every_other_gate_uses() -> None:
    """A fourth would be a new vocabulary for the aggregate gate to learn."""
    assert (gate.EXIT_OK, gate.EXIT_GATE_FAILED, gate.EXIT_UNMEASURED) == (0, 1, 3)


# ---------------------------------------------------------------------------
# Observing a host that will not answer
# ---------------------------------------------------------------------------


def test_a_host_that_cannot_be_observed_is_unmeasured(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No observation means no comparison, and no comparison is never a pass."""

    def refuse(root: Path, contract: object) -> dict[str, object]:
        del root, contract
        message = "the device is not ready"
        raise OSError(message)

    monkeypatch.setattr(gate, "observe", refuse)
    assert gate.run_drift(root=tree, reports=reports) == gate.EXIT_UNMEASURED
    assert manifest.REASON_OBSERVATION_UNAVAILABLE in reasons_of(read_manifest(reports))


def test_a_toolchain_register_that_cannot_be_read_reports_no_tools(tree: Path) -> None:
    """A tree with no `pyproject.toml` declares no toolchain, which is not a crash."""
    assert gate.toolchain_names(tree) == ()


def test_a_declared_tool_that_is_not_installed_is_recorded_as_absent(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tool declared and not installed is a fact about the environment worth recording.

    Recording it as absent rather than omitting the key is what makes its
    installation, later, show up as drift rather than as a key appearing from
    nowhere.
    """
    monkeypatch.setattr(gate, "toolchain_names", lambda _root: ("nothing-is-called-this",))
    assert gate.observe_toolchain(tree) == {"nothing-is-called-this": "absent"}


def test_a_baseline_with_no_observation_is_refused(
    tree: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A document that verifies and carries nothing to compare is still unusable."""
    document = manifest.build_baseline(commit="a" * 40, observation={})
    del document["observation"]
    document[manifest.DIGEST_KEY] = manifest.digest(document)
    (reports / gate.BASELINE_NAME).write_text(
        manifest.render(document), encoding="utf-8", newline="\n"
    )
    monkeypatch.setattr(gate, "observe", fixed(OBSERVATION))
    assert gate.run_drift(root=tree, reports=reports) == gate.EXIT_UNMEASURED
    assert manifest.REASON_BASELINE_UNREADABLE in reasons_of(read_manifest(reports))


def test_a_repair_against_an_unreadable_config_reports_rather_than_writes(tree: Path) -> None:
    """A `pyvenv.cfg` nothing can parse is left exactly as it was found."""
    environment = tree / ".venv"
    config = environment / "pyvenv.cfg"
    config.write_text("this is not a key = value file\x00", encoding="utf-8")
    before = config.read_bytes()
    problems = gate.repair_site_packages(tree, environment)
    assert problems == () or config.read_bytes() == before


def test_the_gate_writes_under_the_ignored_evidence_directory() -> None:
    """Evidence is generated, and generated files are not committed."""
    assert gate.OUTPUT_DIRECTORY.startswith(".globin/")
