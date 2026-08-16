"""Measuring drift, and repairing what may be repaired without destroying anything.

This module sequences: it observes the host, reads what was accepted before,
hands both to :mod:`tools.quality.drift.plan` for judgement, writes the manifest
and returns an exit code. Every decision it makes about whether something is wrong
is made there, where a test can drive it without a machine.

**The observation is imported, not re-implemented.** Phase 017 already measures
this host and already knows how to do it without publishing a credential or a
person's name: ``observe_interpreter``, ``observe_host``, ``observe_environment``
and ``observe_pip`` are its functions and this module calls them. Phase 018 set
the precedent for reading another gate's contract rather than restating it, and
the reasoning is the same here — a second copy of an observation is a second thing
to keep in step, and the two would disagree on exactly the day it mattered.

**What this gate adds is the second measurement.** ``runtime`` asks whether this
host satisfies the contract, which is an absolute question. This asks whether the
host is what it was, which needs a previous answer to compare against. That
previous answer is a baseline, and a baseline is **accepted deliberately** — it is
the state somebody is willing to be held to, not merely the state a check happened
to see. ``check`` therefore never writes one. If it did, every run would certify
whatever it found and drift would be undetectable by construction.

**With no baseline, the answer is "not measured".** Not "no drift". The two are
different facts and ``docs/DEPENDENCY_POLICY.md`` prohibits conflating them by
name; the whole three-valued verdict vocabulary exists so that "could not look" and
"looked and found nothing" are never the same colour.

**Repair writes inside the environment and the repository, and nowhere else.**
That boundary is ADR-0050's, it is checked by a pure function rather than trusted,
and it is why most classes in the policy are ``operator``: a machine-wide
``pip.ini`` or a ``PIP_*`` variable can be *reported* and must not be *touched*.
"""

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from tools.quality.drift.manifest import (
    REASON_BASELINE_UNREADABLE,
    REASON_CLASS_UNDECLARED,
    REASON_CONTRACT_VIOLATED,
    REASON_DECLARATION_UNREADABLE,
    REASON_MANIFEST_LEAKAGE,
    REASON_MANIFEST_NONDETERMINISTIC,
    REASON_OBSERVATION_UNAVAILABLE,
    REASON_OPERATOR_REQUIRED,
    REASON_POLICY_INCONSISTENT,
    REASON_RECREATE_REQUIRED,
    REASON_REPAIR_FAILED,
    REASON_REPAIR_REFUSED,
    REASON_REPAIRABLE,
    DriftManifestError,
    build_baseline,
)
from tools.quality.drift.manifest import build as build_manifest
from tools.quality.drift.manifest import load_baseline as load_baseline_document
from tools.quality.drift.manifest import render as render_manifest
from tools.quality.drift.plan import CONFIGURATION_FILE as POLICY_FILE
from tools.quality.drift.plan import (
    REPAIR_BOOTSTRAP,
    REPAIR_IN_PLACE,
    REPAIR_OPERATOR,
    REPAIR_RECREATE,
    SEVERITY_MATERIAL,
    SEVERITY_VIOLATION,
    DriftPolicyError,
    Judgement,
    Policy,
    duplicate_classes,
    policy_problems,
    unreachable_rules,
)
from tools.quality.drift.plan import classify as classify_differences
from tools.quality.drift.plan import compare as compare_observations
from tools.quality.drift.plan import flatten as flatten_observation
from tools.quality.drift.plan import parse_declaration as parse_policy
from tools.quality.drift.plan import undeclared as undeclared_differences
from tools.quality.evidence.redaction import describe as describe_findings
from tools.quality.evidence.redaction import scan as scan_for_secrets
from tools.quality.execution.plan import Verdict, combine
from tools.quality.runtime.gate import (
    observe_environment,
    observe_host,
    observe_interpreter,
    observe_pip,
)
from tools.quality.runtime.plan import (
    Contract,
    RuntimeBaselineError,
    parse_pyvenv_cfg,
    recorded_path,
)
from tools.quality.runtime.plan import parse_declaration as parse_runtime_contract
from tools.quality.supply.inventory import (
    DEVELOPMENT,
    PYPI,
    SupplyChainError,
    from_pyproject,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
"""The repository this gate measures, found from this file rather than the cwd."""

OUTPUT_DIRECTORY: Final[str] = ".globin/drift"
"""Where the evidence is written, relative to the repository root."""

MANIFEST_NAME: Final[str] = "drift-manifest.json"
"""What the manifest is called."""

BASELINE_NAME: Final[str] = "drift-baseline.json"
"""What the accepted baseline is called."""

RUNTIME_CONTRACT: Final[str] = "docs/engineering/runtime-contract.toml"
"""The contract the environment is measured against, owned by Phase 017."""

PYVENV_CONFIG: Final[str] = "pyvenv.cfg"
"""The file inside an environment that records how it was created."""

SITE_PACKAGES_KEY: Final[str] = "include-system-site-packages"
"""The one key this gate is permitted to rewrite."""

CHECK: Final[str] = "check"
"""Compare the host against the accepted baseline, and write nothing else."""

ACCEPT: Final[str] = "accept"
"""Record the host as the state to be held to from now on."""

REPAIR: Final[str] = "repair"
"""Perform the bounded repairs the policy marks in-place, then measure again."""

EXIT_OK: Final[int] = 0
"""Every check passed."""

EXIT_GATE_FAILED: Final[int] = 1
"""A check failed."""

EXIT_UNMEASURED: Final[int] = 3
"""A check could not be measured, which is never a pass."""

DEFAULT_REPOSITORY: Final[str] = "aydhn/GLOBIN"
"""What to call this repository in the manifest when the environment does not say."""


def _sha(root: Path) -> str:
    """Return the commit this tree is at, without starting a process.

    Args:
        root: The repository root.

    Returns:
        The commit, or ``"unknown"``. Read from ``.git/HEAD`` directly because
        starting ``git`` to learn one string is a subprocess this gate does not
        otherwise need, and a gate that cannot read a file should say so rather
        than fail.
    """
    head = root / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if not text.startswith("ref:"):
        return text
    reference = root / ".git" / text.removeprefix("ref:").strip()
    try:
        return reference.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def _finding(problems: Sequence[str], *, measured: bool = True) -> dict[str, object]:
    """Turn a check's problems into a manifest entry.

    Args:
        problems: What was wrong, empty when nothing was.
        measured: Whether the check could be performed at all.

    Returns:
        The entry.
    """
    verdict = (
        Verdict.UNMEASURED if not measured else (Verdict.FAILED if problems else Verdict.PASSED)
    )
    return {"verdict": str(verdict), "problems": list(problems)}


def toolchain_names(root: Path) -> tuple[str, ...]:
    """Return the development toolchain this repository declares.

    Args:
        root: The repository root.

    Returns:
        The distribution names, sorted, or empty when the declaration cannot be
        read. Read through :mod:`tools.quality.supply.inventory` rather than by
        parsing ``pyproject.toml`` again, because that module already owns reading
        the registers and a second reader of the same table is a second thing to
        keep in step.
    """
    try:
        declared = from_pyproject(root)
    except (OSError, SupplyChainError):
        return ()
    return tuple(
        sorted(
            {
                entry.name
                for entry in declared
                if entry.scope == DEVELOPMENT and entry.ecosystem == PYPI
            }
        )
    )


def observe_toolchain(root: Path) -> dict[str, object]:
    """Return the installed version of each declared development tool.

    Args:
        root: The repository root.

    Returns:
        Distribution names mapped to the version installed, or ``"absent"`` where
        the tool is declared and not installed.

    **This resolves nothing.** It reads the metadata of distributions that are
    already installed and compares nothing itself. Phase 020 owns resolution and
    locking — running a resolver, writing a lockfile, claiming a transitive tree —
    and none of those happen here. Only the distributions this repository declares
    by name are read; whatever else is installed is somebody's business but not
    this gate's, and reporting it would be asserting a transitive tree nobody
    resolved.
    """
    from importlib.metadata import PackageNotFoundError, version

    installed: dict[str, object] = {}
    for name in toolchain_names(root):
        try:
            installed[name] = version(name)
        except PackageNotFoundError:
            installed[name] = "absent"
    return installed


def observe(root: Path, contract: Contract) -> dict[str, object]:
    """Record everything this gate compares, with paths made publishable.

    Args:
        root: The repository root.
        contract: The parsed runtime contract, which names the environment.

    Returns:
        The observation, nested by area.

    Every path outside the repository is a fingerprint rather than a path, because
    this document is uploaded as a public-repository artifact and every absolute
    path on the development host carries the account holder's name.

    ``pip`` configuration is reshaped from Phase 017's list of scopes into a
    mapping from scope to whether it exists, so that flattening produces one key
    per scope. A list would flatten to one key holding all four, and a change to
    any of them would then report as a change to all of them.
    """
    interpreter = observe_interpreter()
    host = observe_host()
    environment = observe_environment(root, contract.environment.directory)
    pip = observe_pip(root)
    sources = pip.get("configuration_sources")
    scopes: dict[str, object] = {}
    if isinstance(sources, list):
        for item in sources:
            if isinstance(item, Mapping):
                scopes[str(item.get("scope"))] = bool(item.get("exists"))
    base_prefix = Path(sys.base_prefix)
    return {
        "host": {
            "system": host.system,
            "release": host.release,
            "kernel": host.kernel,
        },
        "interpreter": {
            "implementation": interpreter.implementation,
            "version": interpreter.version.text,
            "release_level": interpreter.release_level,
            "free_threaded": interpreter.free_threaded,
            "pointer_bits": interpreter.pointer_bits,
            "machine": interpreter.machine,
            "executable": recorded_path(Path(sys.executable).resolve(), root=root),
            "base_prefix": recorded_path(base_prefix.resolve(), root=root),
            "in_virtual_environment": Path(sys.prefix) != base_prefix,
        },
        "environment": {
            "present": environment.present,
            "location": recorded_path(environment.location, root=root),
            "created_from": environment.config.get("version", "unknown"),
            "system_site_packages": environment.config.get(SITE_PACKAGES_KEY, "unknown"),
            "base_present": environment.base_present,
            "interpreter_present": environment.interpreter_present,
        },
        "pip": {
            "version": pip.get("version"),
            "module": pip.get("module"),
            "belongs_to_running_interpreter": pip.get("belongs_to_running_interpreter"),
            "config": scopes,
            "overrides": pip.get("environment_overrides"),
        },
        "toolchain": observe_toolchain(root),
    }


def write_problems(target: Path, *, root: Path, environment: Path) -> tuple[str, ...]:
    """Refuse a write that would land outside the boundary this tooling may touch.

    Args:
        target: What is about to be written.
        root: The repository root.
        environment: The project environment's directory.

    Returns:
        One message per reason the write is refused, empty when it is permitted.

    A pure function, deliberately, and separated for the reason
    :func:`tools.quality.runtime.plan.deletion_problems` gives about its own: the
    decision that permits a write is the one worth having tests for, and a decision
    embedded in the code that performs the write is a decision nobody can exercise
    without performing it.

    The boundary is ADR-0050's and is not this module's to widen. A write is
    permitted only inside the environment, and the environment must itself be
    inside the repository — an environment resolved somewhere else is either a
    misconfiguration or a symbolic link out of the tree, and neither is a thing to
    start editing files in.
    """
    problems: list[str] = []
    try:
        resolved = target.resolve()
        inside_environment = resolved.is_relative_to(environment.resolve())
        environment_inside_root = environment.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError) as fault:
        return (f"{target} could not be resolved, so it cannot be shown to be in bounds: {fault}",)
    if not environment_inside_root:
        problems.append(
            "the environment resolves outside the repository, and this tool "
            "writes nothing outside it"
        )
    if not inside_environment:
        problems.append(
            "the target resolves outside the environment, and repair writes only "
            "inside it (ADR-0050)"
        )
    if target.is_symlink():
        problems.append("the target is a link, and this tool does not write through one")
    return tuple(problems)


def repair_site_packages(root: Path, environment: Path) -> tuple[str, ...]:
    """Turn off system site-packages by rewriting one key in ``pyvenv.cfg``.

    Args:
        root: The repository root.
        environment: The project environment's directory.

    Returns:
        One message per reason the repair did not happen, empty on success.

    The whole of the repair. It rewrites one key and leaves every other line
    exactly as it found it — in particular ``home``, which records which
    interpreter the environment came from and which this tool has no business
    changing.

    This works because the flag is read afresh at interpreter start-up rather than
    baked in at creation: PEP 405 specifies that ``pyvenv.cfg`` is scanned when the
    interpreter launches, and the ``site`` module's documentation states that where
    ``include-system-site-packages`` is true "the system-level prefixes will be
    searched for site-packages, otherwise they won't". Sources are recorded in
    ``docs/research/phase_019_sources.md``.
    """
    target = environment / PYVENV_CONFIG
    refusals = write_problems(target, root=root, environment=environment)
    if refusals:
        return refusals
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as fault:
        return (f"{PYVENV_CONFIG} could not be read: {fault}",)
    try:
        parse_pyvenv_cfg(text)
    except RuntimeBaselineError as fault:
        return (f"{PYVENV_CONFIG} could not be understood, so it was left alone: {fault}",)
    lines = text.splitlines()
    rewritten: list[str] = []
    found = False
    for line in lines:
        name, separator, _value = line.partition("=")
        if separator and name.strip().lower() == SITE_PACKAGES_KEY:
            rewritten.append(f"{name.rstrip()} = false")
            found = True
        else:
            rewritten.append(line)
    if not found:
        rewritten.append(f"{SITE_PACKAGES_KEY} = false")
    try:
        target.write_text("\n".join(rewritten) + "\n", encoding="utf-8", newline="\n")
    except OSError as fault:
        return (f"{PYVENV_CONFIG} could not be written: {fault}",)
    return ()


REPAIRS: Final[dict[str, str]] = {
    "environment.system_site_packages": "repair_site_packages",
}
"""Which observation keys this tool is able to repair, and what performs each.

A closed table, compared against the policy in both directions by
``tests/contract/test_drift_contract.py``: a class the policy marks ``in-place``
with no entry here is a promise the tool cannot keep, and an entry here for a class
the policy does not mark ``in-place`` is code that never runs.

Named by function rather than holding the function so that the table is data a
test can read without importing what it calls.
"""


def _perform(name: str, root: Path, environment: Path) -> tuple[str, ...]:
    """Run one repair by name.

    Args:
        name: The entry from :data:`REPAIRS`.
        root: The repository root.
        environment: The project environment's directory.

    Returns:
        One message per reason it did not happen, empty on success.
    """
    if name == "repair_site_packages":
        return repair_site_packages(root, environment)
    return (f"no repair named {name!r} is implemented",)  # pragma: no cover - closed by test


def _judgement_entry(judgement: Judgement) -> dict[str, object]:
    """Render one judgement for the manifest.

    Args:
        judgement: What was judged.

    Returns:
        The entry. Values are carried because none of them is a secret: every
        observation key is a version, a flag, a fingerprint or a scope name, and
        the two that could have carried a credential — the pip index and the
        ``PIP_*`` values — are recorded as existence and names only.
    """
    return {
        "key": judgement.difference.key,
        "kind": judgement.difference.kind,
        "before": judgement.difference.before,
        "after": judgement.difference.after,
        "severity": judgement.severity,
        "repair": judgement.repair,
        "action": judgement.action,
    }


def _read_policy(root: Path) -> tuple[Policy | None, str]:
    """Read the drift policy.

    Args:
        root: The repository root.

    Returns:
        The policy and an empty message, or ``None`` and why not.
    """
    try:
        text = (root / POLICY_FILE).read_text(encoding="utf-8")
    except OSError as fault:
        return None, f"{POLICY_FILE} could not be read: {fault}"
    try:
        return parse_policy(text), ""
    except DriftPolicyError as fault:
        return None, str(fault)


def _read_contract(root: Path) -> tuple[Contract | None, str]:
    """Read the runtime contract this environment is measured against.

    Args:
        root: The repository root.

    Returns:
        The contract and an empty message, or ``None`` and why not.
    """
    try:
        text = (root / RUNTIME_CONTRACT).read_text(encoding="utf-8")
    except OSError as fault:
        return None, f"{RUNTIME_CONTRACT} could not be read: {fault}"
    try:
        return parse_runtime_contract(text), ""
    except RuntimeBaselineError as fault:
        return None, str(fault)


def _read_baseline(path: Path) -> tuple[dict[str, str] | None, str]:
    """Read the accepted baseline.

    Args:
        path: Where the baseline would be.

    Returns:
        The flattened observation and an empty message; ``None`` and an empty
        message when there is no baseline at all; or ``None`` and why it could not
        be read.

    The three-way answer is the point. "There is no baseline" and "there is a
    baseline and it is broken" are different facts with different verdicts, and
    collapsing them would let a corrupted file read as a first run.
    """
    if not path.is_file():
        return None, ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as fault:
        return None, f"{BASELINE_NAME} could not be read: {fault}"
    try:
        document = load_baseline_document(text)
    except DriftManifestError as fault:
        return None, str(fault)
    observation = document.get("observation")
    if not isinstance(observation, Mapping):
        return None, f"{BASELINE_NAME} carries no observation to compare against"
    return {str(key): str(value) for key, value in observation.items()}, ""


def run_drift(
    *,
    root: Path = REPO_ROOT,
    reports: Path | None = None,
    mode: str = CHECK,
) -> int:
    """Measure drift, and act on it only as far as the policy permits.

    Args:
        root: The repository root.
        reports: Where to write the evidence. Defaults to :data:`OUTPUT_DIRECTORY`
            under ``root``.
        mode: One of :data:`CHECK`, :data:`ACCEPT`, :data:`REPAIR`.

    Returns:
        ``0`` when everything passed, ``1`` when a check failed, ``3`` when
        something could not be measured.
    """
    directory = reports if reports is not None else root / OUTPUT_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    findings: dict[str, object] = {}
    reasons: list[str] = []

    policy, policy_fault = _read_policy(root)
    if policy is None:
        return _fail_early(directory, root, policy_fault, REASON_DECLARATION_UNREADABLE, mode)
    contract, contract_fault = _read_contract(root)
    if contract is None:
        return _fail_early(directory, root, contract_fault, REASON_DECLARATION_UNREADABLE, mode)

    inconsistent = (
        *policy_problems(policy),
        *duplicate_classes(policy),
        *unreachable_rules(policy),
    )
    findings["policy"] = _finding(inconsistent)
    if inconsistent:
        reasons.append(REASON_POLICY_INCONSISTENT)

    try:
        observation = observe(root, contract)
    except OSError as fault:
        findings["observation"] = _finding(
            (f"the host could not be observed: {fault}",), measured=False
        )
        reasons.append(REASON_OBSERVATION_UNAVAILABLE)
        return _write(directory, root, findings, reasons, mode)
    current = flatten_observation(observation)
    findings["observation"] = _finding(())

    environment = root / contract.environment.directory
    baseline_path = directory / BASELINE_NAME

    if mode == ACCEPT:
        if inconsistent:
            return _write(directory, root, findings, reasons, mode)
        document = build_baseline(commit=_sha(root), observation=current)
        rendered = render_manifest(document)
        # Scanned before it is written, for the same reason the manifest is: this
        # directory is uploaded, and `SECURITY_BASELINE.md` requires that anything
        # written to it be checked for absolute paths. `recorded_path` should have
        # fingerprinted every one of them already, and "should have" is not a
        # control.
        leaks = scan_for_secrets(BASELINE_NAME, rendered)
        if leaks:
            return _fail_early(
                directory, root, describe_findings(leaks), REASON_MANIFEST_LEAKAGE, mode
            )
        baseline_path.write_text(rendered, encoding="utf-8", newline="\n")
        findings["baseline"] = {
            "verdict": str(Verdict.PASSED),
            "problems": [],
            "detail": f"the host was accepted as the baseline, in {len(current)} recorded keys",
        }
        return _write(directory, root, findings, reasons, mode)

    baseline, baseline_fault = _read_baseline(baseline_path)
    if baseline_fault:
        findings["baseline"] = _finding((baseline_fault,), measured=False)
        reasons.append(REASON_BASELINE_UNREADABLE)
        return _write(directory, root, findings, reasons, mode)
    if baseline is None:
        findings["baseline"] = _finding(
            (
                "no baseline has been accepted, so there is nothing to compare against. "
                "Run `python -m tools.quality.drift accept` on a host you are willing to "
                "be held to. This is not a clean result: nothing was measured",
            ),
            measured=False,
        )
        return _write(directory, root, findings, reasons, mode)

    differences = compare_observations(baseline, current)
    unclassified = undeclared_differences(differences, policy)
    findings["classification"] = _finding(unclassified)
    if unclassified:
        reasons.append(REASON_CLASS_UNDECLARED)

    try:
        judgements = classify_differences(differences, policy)
    except DriftPolicyError as fault:
        findings["drift"] = _finding((str(fault),))
        reasons.append(REASON_POLICY_INCONSISTENT)
        return _write(directory, root, findings, reasons, mode)

    if mode == REPAIR:
        performed, refused, failed = _repair(judgements, root=root, environment=environment)
        findings["repairs"] = {
            "verdict": str(Verdict.FAILED if (refused or failed) else Verdict.PASSED),
            "problems": [*refused, *failed],
            "performed": list(performed),
        }
        if refused:
            reasons.append(REASON_REPAIR_REFUSED)
        if failed:
            reasons.append(REASON_REPAIR_FAILED)
        if performed:
            current = flatten_observation(observe(root, contract))
            differences = compare_observations(baseline, current)
            judgements = classify_differences(differences, policy)

    findings["drift"] = _drift_finding(judgements)
    reasons.extend(_reasons_for(judgements))
    return _write(directory, root, findings, reasons, mode)


def _repair(
    judgements: Sequence[Judgement], *, root: Path, environment: Path
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Perform every repair the policy marks in-place.

    Args:
        judgements: What was judged.
        root: The repository root.
        environment: The project environment's directory.

    Returns:
        What was performed, what was refused, and what failed.

    A judgement the policy marks ``in-place`` with no entry in :data:`REPAIRS` is
    **refused rather than skipped**. Skipping it would let the policy promise a
    repair the tool cannot perform and report success anyway, which is worse than
    either doing it or saying plainly that it will not.
    """
    performed: list[str] = []
    refused: list[str] = []
    failed: list[str] = []
    for judgement in judgements:
        if judgement.repair != REPAIR_IN_PLACE:
            continue
        key = judgement.difference.key
        name = REPAIRS.get(key)
        if name is None:
            refused.append(
                f"{POLICY_FILE} marks {key} repairable in place and no repair is implemented"
            )
            continue
        problems = _perform(name, root, environment)
        if problems:
            failed.extend(f"{key}: {problem}" for problem in problems)
            continue
        performed.append(f"{key}: {judgement.action}")
    return tuple(performed), tuple(refused), tuple(failed)


def _drift_finding(judgements: Sequence[Judgement]) -> dict[str, object]:
    """Render the drift itself as a manifest entry.

    Args:
        judgements: What was judged.

    Returns:
        The entry. Benign judgements are carried but are not problems: a patch
        that moved forward is worth being able to read afterwards and is not worth
        failing on.
    """
    problems = [
        f"{judgement.difference.key} is {judgement.severity}: "
        f"{judgement.difference.before or 'absent'} -> "
        f"{judgement.difference.after or 'absent'} ({judgement.repair})"
        for judgement in judgements
        if judgement.severity in {SEVERITY_VIOLATION, SEVERITY_MATERIAL}
    ]
    entry = _finding(problems)
    entry["differences"] = [_judgement_entry(judgement) for judgement in judgements]
    return entry


def _reasons_for(judgements: Sequence[Judgement]) -> tuple[str, ...]:
    """Return the reason codes a set of judgements earns.

    Args:
        judgements: What was judged.

    Returns:
        The codes, sorted and without repeats.
    """
    reasons: set[str] = set()
    for judgement in judgements:
        if judgement.severity == SEVERITY_VIOLATION:
            reasons.add(REASON_CONTRACT_VIOLATED)
        if judgement.severity not in {SEVERITY_VIOLATION, SEVERITY_MATERIAL}:
            continue
        if judgement.repair == REPAIR_IN_PLACE:
            reasons.add(REASON_REPAIRABLE)
        elif judgement.repair in {REPAIR_RECREATE, REPAIR_BOOTSTRAP}:
            reasons.add(REASON_RECREATE_REQUIRED)
        elif judgement.repair == REPAIR_OPERATOR:
            reasons.add(REASON_OPERATOR_REQUIRED)
    return tuple(sorted(reasons))


def _run_section(root: Path, mode: str) -> dict[str, object]:
    """What was checked, for the manifest's ``run`` section.

    Args:
        root: The repository root.
        mode: Which subcommand ran.

    Returns:
        The section. No wall clock and no absolute path.
    """
    return {
        "repository": os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY),
        "commit": _sha(root),
        "declaration": POLICY_FILE,
        "contract": RUNTIME_CONTRACT,
        "mode": mode,
    }


def _write(
    directory: Path,
    root: Path,
    findings: dict[str, object],
    reasons: Sequence[str],
    mode: str,
) -> int:
    """Build the manifest, prove it deterministic, scan it, and write it.

    Args:
        directory: Where the evidence goes.
        root: The repository root.
        findings: What each check concluded.
        reasons: The reason codes earned.
        mode: Which subcommand ran.

    Returns:
        The exit code.
    """
    run = _run_section(root, mode)
    overall = combine([_verdict_of(entry) for entry in findings.values()])
    verdict = {"verdict": str(overall), "reasons": sorted(set(reasons))}

    document = build_manifest(run=run, findings=findings, verdict=verdict)
    rendered = render_manifest(document)
    again = render_manifest(build_manifest(run=run, findings=findings, verdict=verdict))
    if rendered != again:
        return _fail_early(
            directory,
            root,
            "two renderings of the same run disagreed",
            REASON_MANIFEST_NONDETERMINISTIC,
            mode,
        )

    leaks = scan_for_secrets(MANIFEST_NAME, rendered)
    if leaks:
        return _fail_early(directory, root, describe_findings(leaks), REASON_MANIFEST_LEAKAGE, mode)

    (directory / MANIFEST_NAME).write_text(rendered, encoding="utf-8", newline="\n")
    _report(findings, overall, verdict["reasons"])
    return _exit_code(overall)


def _verdict_of(entry: object) -> Verdict:
    """Read a finding's verdict.

    Args:
        entry: The manifest entry.

    Returns:
        The verdict, treating anything unreadable as unmeasured rather than as a
        pass — the same direction of failure every other gate takes.
    """
    if isinstance(entry, Mapping):
        recorded = entry.get("verdict")
        for verdict in Verdict:
            if str(verdict) == recorded:
                return verdict
    return Verdict.UNMEASURED


def _exit_code(verdict: Verdict) -> int:
    """Turn a verdict into an exit code.

    Args:
        verdict: The overall verdict.

    Returns:
        ``0``, ``1`` or ``3``.
    """
    if verdict is Verdict.PASSED:
        return EXIT_OK
    return EXIT_GATE_FAILED if verdict is Verdict.FAILED else EXIT_UNMEASURED


def _fail_early(directory: Path, root: Path, problem: str, reason: str, mode: str) -> int:
    """Write a manifest for a run that could not proceed, then fail.

    Args:
        directory: Where the evidence goes.
        root: The repository root.
        problem: What went wrong.
        reason: The code for it.
        mode: Which subcommand ran.

    Returns:
        The exit code.

    A manifest is still written. A gate that failed silently and left no artefact
    would be indistinguishable, to anything reading the evidence afterwards, from a
    gate that never ran.
    """
    findings = {"declaration": _finding((problem,), measured=False)}
    run = _run_section(root, mode)
    verdict = {"verdict": str(Verdict.UNMEASURED), "reasons": [reason]}
    document = build_manifest(run=run, findings=findings, verdict=verdict)
    rendered = render_manifest(document)
    if not scan_for_secrets(MANIFEST_NAME, rendered):
        (directory / MANIFEST_NAME).write_text(rendered, encoding="utf-8", newline="\n")
    print(f"drift: {problem}")
    return EXIT_UNMEASURED


def _report(findings: Mapping[str, object], verdict: Verdict, reasons: Sequence[str]) -> None:
    """Print what happened, in ASCII.

    Args:
        findings: What each check concluded.
        verdict: The overall verdict.
        reasons: The codes earned.

    A Windows console encodes its output with the active code page, so a character
    outside it raises rather than prints. Everything here is ASCII.
    """
    print(f"drift: {verdict}")
    for name, entry in sorted(findings.items()):
        if not isinstance(entry, Mapping):
            continue
        problems = entry.get("problems")
        print(f"  {name}: {entry.get('verdict')}")
        if isinstance(problems, list):
            for problem in problems:
                print(f"    - {problem}")
        detail = entry.get("detail")
        if isinstance(detail, str):
            print(f"    {detail}")
    if reasons:
        print(f"  reasons: {', '.join(reasons)}")
