"""Running every GPU check and reducing them to one verdict.

**The judgement lives in :mod:`tools.quality.gpu.plan`; the sequencing lives
here.** Every decision this file makes is delegated to a pure function tested from
literals. What this module adds is order, I/O, and the arithmetic that turns a set
of answers into an exit code — the same division ``tools/quality/wheels/gate.py``
uses.

**One command, and it reaches no network.** Unlike ``supply`` and ``wheels``,
there is no ``probe`` subcommand here, because everything this gate asks is
answerable from this machine. It starts a local process that ships with the
display driver and reads nothing else. That is why it is safe in ``full`` in
principle — and it is nonetheless kept out of ``full``, for the separate reason
ADR-0032 condition 5 gives: it reports on the host rather than on the tree, and a
commit gate should fail for something the commit did.

**Absence is not failure, and this is where that is enforced.** A host with no
NVIDIA device produces a manifest full of ``ABSENT`` and exits zero. What exits
non-zero is a contract that contradicts itself, a gap nobody owns, a probe that
errored, or a manifest that cannot be reproduced. Continuous integration runs on a
machine with no GPU, so any other arrangement would make the required check
permanently red.

**Determinism is checked rather than assumed.** The manifest is built twice and
the renderings compared byte for byte, exactly as the wheel survey's is.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from tools.quality.evidence.redaction import describe as describe_findings
from tools.quality.evidence.redaction import scan as scan_for_secrets
from tools.quality.execution.plan import Verdict, combine
from tools.quality.gpu.manifest import (
    REASON_CAPABILITY_DUPLICATED,
    REASON_CAPABILITY_MISSING,
    REASON_CAPABILITY_UNMEASURED,
    REASON_DECLARATION_UNREADABLE,
    REASON_INTERFACE_CONTRADICTED,
    REASON_MANIFEST_LEAKAGE,
    REASON_MANIFEST_NONDETERMINISTIC,
    REASON_PHASE_MISPLACED,
    REASON_TARGET_DIVERGED,
)
from tools.quality.gpu.manifest import build as build_manifest
from tools.quality.gpu.manifest import render as render_manifest
from tools.quality.gpu.plan import (
    CONFIGURATION_FILE,
    Declaration,
    GpuContractError,
    Observation,
    State,
    classify,
    duplicate_capabilities,
    forbidden_field_problems,
    gap_problems,
    parse_declaration,
    phase_problems,
    target_problems,
)
from tools.quality.gpu.probes import DEFAULT_TIMEOUT, Locator, Runner, read
from tools.quality.runtime.plan import RuntimeBaselineError
from tools.quality.runtime.plan import parse_declaration as parse_runtime_contract

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
"""The repository this gate reports on."""

OUTPUT_DIRECTORY: Final[str] = ".globin/gpu"
"""Where the manifest is written, relative to the repository root.

Beside ``.globin/wheels``, ``.globin/runtime`` and the rest, under the same
ignored root. Regenerable, so nothing here is committed.
"""

MANIFEST_NAME: Final[str] = "gpu-manifest.json"
"""The manifest's filename."""

RUNTIME_CONTRACT: Final[str] = "docs/engineering/runtime-contract.toml"
"""The contract the declared target is compared against."""

ROADMAP_TOTAL_PHASES: Final[int] = 320
"""How many phases the programme has."""

DELIVERED_PHASE: Final[int] = 23
"""A floor: no capability may be owned by this phase or an earlier one.

Deliberately a constant rather than a read of ``ROADMAP.md``, and deliberately a
floor rather than a mirror, for both of the reasons
``tools/quality/wheels/gate.py`` states about its own. It catches a gap pointing
at work that has already happened, and erring low makes the gate permissive rather
than wrongly rejecting.

**It is 23 rather than 22**, which is the one place this differs from the wheel
survey's reasoning. The survey was written in Phase 018 about phases after it; this
contract is written in Phase 023 and is delivered by it, so an entry naming Phase
023 would be a gap the gate promises to close *itself* — a promise no gate can
keep. The first version of this constant was 22 and a unit test caught the
mismatch between the number and the sentence explaining it.
"""

SHA_LENGTH: Final[int] = 40
"""How long a Git object name is."""

DEFAULT_REPOSITORY: Final[str] = "aydhn/GLOBIN"
"""Which repository the manifest records itself as describing."""

EXIT_OK: Final[int] = 0
"""Every check passed."""

EXIT_GATE_FAILED: Final[int] = 1
"""A check failed."""

EXIT_UNMEASURED: Final[int] = 3
"""A check could not be measured, which is never a pass."""


def _sha(root: Path) -> str:
    """The commit under test, read without starting a process.

    Args:
        root: The repository root.

    Returns:
        The forty-character SHA, or ``"unknown"``.

    Read from ``.git`` directly, exactly as the other gates do, so that a manifest
    can be produced in a tree without Git on the path.
    """
    head = root / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if not text.startswith("ref:"):
        return text if len(text) == SHA_LENGTH else "unknown"
    reference = root / ".git" / text.removeprefix("ref:").strip()
    try:
        return reference.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def _read(root: Path, relative: str) -> str | None:
    """Read a repository file.

    Args:
        root: The repository root.
        relative: The repository-relative path.

    Returns:
        Its contents, or ``None`` when it cannot be read.
    """
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def _finding(problems: Sequence[str], *, measured: bool = True) -> dict[str, object]:
    """One check's entry in the manifest.

    Args:
        problems: What the check found.
        measured: Whether the check ran at all.

    Returns:
        The entry, carrying its own verdict.

    The order matters: an unmeasured check that also happens to have found nothing
    is unmeasured, not passed.
    """
    verdict = (
        Verdict.UNMEASURED if not measured else (Verdict.FAILED if problems else Verdict.PASSED)
    )
    return {"verdict": str(verdict), "problems": list(problems)}


def _contract_values(root: Path) -> tuple[str, str]:
    """Read what the runtime contract declares about this host.

    Args:
        root: The repository root.

    Returns:
        The system and the architecture.

    Raises:
        GpuContractError: If the contract cannot be read or parsed.

    The runtime contract is read rather than restated. Phase 017 owns those
    values, and a second copy of them in this package would be a second thing to
    keep in step — the failure ``SOURCE_OF_TRUTH.md`` describes.
    """
    text = _read(root, RUNTIME_CONTRACT)
    if text is None:
        msg = f"{RUNTIME_CONTRACT} could not be read, so the declared target cannot be checked"
        raise GpuContractError(msg)
    try:
        contract = parse_runtime_contract(text)
    except RuntimeBaselineError as fault:
        msg = f"{RUNTIME_CONTRACT} could not be parsed: {fault}"
        raise GpuContractError(msg) from fault
    return contract.host.system, contract.interpreter.architecture


def _capability_finding(observation: Observation, declaration: Declaration) -> dict[str, object]:
    """The per-capability section: every question, and what this host answered.

    Args:
        observation: What was measured.
        declaration: The contract, for the question and the owning phase.

    Returns:
        The entry, carrying one record per declared capability.

    Every capability appears whatever its state, because a manifest that omitted
    the absent ones would make *not there* indistinguishable from *not asked*,
    which is the confusion ADR-0045 exists to prevent.
    """
    records = [
        {
            "id": capability.identifier,
            "question": capability.question,
            "source": capability.source,
            "policy": capability.policy,
            "phase": capability.phase,
            "state": str(observation.states.get(capability.identifier, State.UNMEASURABLE)),
        }
        for capability in declaration.capabilities
    ]
    problems = gap_problems(observation.states, declaration.capabilities)
    entry = _finding(problems)
    entry["capabilities"] = records
    return entry


def _observed_section(observation: Observation) -> dict[str, object]:
    """What this host actually is, for the manifest's ``observed`` section.

    Args:
        observation: What was measured.

    Returns:
        The section.

    Device *models* are recorded because they answer the roadmap's question.
    Nothing identifying the machine's owner appears, and no path outside the
    repository appears at all.
    """
    return {
        "devices": [dict(sorted(device.items())) for device in observation.devices],
        "device_count": len(observation.devices),
        "driver_version": observation.driver_version,
        "compute_capabilities": list(observation.compute_capabilities),
        "cuda_runtime_version": observation.cuda_runtime_version,
        "notes": list(observation.notes),
    }


def run_gpu(
    *,
    root: Path | None = None,
    reports: Path | None = None,
    runner: Runner | None = None,
    locate: Locator | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> int:
    """Check the GPU contract against this host and write the manifest.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.
        reports: Where to write. Defaults to :data:`OUTPUT_DIRECTORY` under root.
        runner: How to start a process. Defaults to :func:`subprocess.run`.
        locate: How to find an executable. Defaults to :func:`shutil.which`.
        timeout: How long any one probe may take.

    Returns:
        :data:`EXIT_OK`, :data:`EXIT_GATE_FAILED` or :data:`EXIT_UNMEASURED`.
    """
    base = REPO_ROOT if root is None else root
    directory = (base / OUTPUT_DIRECTORY) if reports is None else reports
    directory.mkdir(parents=True, exist_ok=True)

    reasons: list[str] = []
    findings: dict[str, object] = {}

    declared = _read(base, CONFIGURATION_FILE)
    if declared is None:
        unreadable = f"{CONFIGURATION_FILE} could not be read"
        return _fail_early(directory, base, unreadable, REASON_DECLARATION_UNREADABLE)
    try:
        declaration = parse_declaration(declared)
    except GpuContractError as fault:
        return _fail_early(directory, base, str(fault), REASON_DECLARATION_UNREADABLE)

    try:
        system, architecture = _contract_values(base)
    except GpuContractError as fault:
        return _fail_early(directory, base, str(fault), REASON_TARGET_DIVERGED)

    diverged = target_problems(declaration.target, system=system, architecture=architecture)
    findings["target"] = _finding(diverged)
    if diverged:
        reasons.append(REASON_TARGET_DIVERGED)

    duplicated = duplicate_capabilities(declaration.capabilities)
    findings["duplicates"] = _finding(duplicated)
    if duplicated:
        reasons.append(REASON_CAPABILITY_DUPLICATED)

    misplaced = phase_problems(
        declaration.capabilities, delivered=DELIVERED_PHASE, total=ROADMAP_TOTAL_PHASES
    )
    findings["phases"] = _finding(misplaced)
    if misplaced:
        reasons.append(REASON_PHASE_MISPLACED)

    contradicted = forbidden_field_problems(declaration.interface, declaration.forbidden)
    findings["interface"] = _finding(contradicted)
    if contradicted:
        reasons.append(REASON_INTERFACE_CONTRADICTED)

    observation = classify(
        read(declaration.interface, runner=runner, locate=locate, timeout=timeout), declaration
    )
    findings["capabilities"] = _capability_finding(observation, declaration)
    states = observation.states.values()
    if any(state is State.ERROR for state in states):
        reasons.append(REASON_CAPABILITY_UNMEASURED)
    if gap_problems(observation.states, declaration.capabilities) and not any(
        state is State.ERROR for state in states
    ):
        reasons.append(REASON_CAPABILITY_MISSING)

    run = _run_section(base, declaration)
    observed = _observed_section(observation)
    overall = combine([_verdict_of(entry) for entry in findings.values()])
    verdict = {"verdict": str(overall), "reasons": sorted(set(reasons))}

    document = build_manifest(run={**run, "observed": observed}, findings=findings, verdict=verdict)
    rendered = render_manifest(document)
    again = render_manifest(
        build_manifest(run={**run, "observed": observed}, findings=findings, verdict=verdict)
    )
    if rendered != again:
        return _fail_early(
            directory,
            base,
            "two renderings of the same run disagreed",
            REASON_MANIFEST_NONDETERMINISTIC,
        )

    leaks = scan_for_secrets(MANIFEST_NAME, rendered)
    if leaks:
        return _fail_early(directory, base, describe_findings(leaks), REASON_MANIFEST_LEAKAGE)

    (directory / MANIFEST_NAME).write_text(rendered, encoding="utf-8", newline="\n")
    _report(findings, observation, overall, reasons)
    return _exit_code(overall)


def _run_section(root: Path, declaration: Declaration) -> dict[str, object]:
    """What was asked, for the manifest's ``run`` section.

    Args:
        root: The repository root.
        declaration: The contract.

    Returns:
        The section. No wall clock and no absolute path.
    """
    return {
        "repository": DEFAULT_REPOSITORY,
        "commit": _sha(root),
        "declaration": CONFIGURATION_FILE,
        "contract": RUNTIME_CONTRACT,
        "target": {
            "system": declaration.target.system,
            "architecture": declaration.target.architecture,
        },
        "interface": {
            "command": declaration.interface.command,
            "query_fields": list(declaration.interface.query_fields),
        },
        "capabilities": len(declaration.capabilities),
    }


def _verdict_of(entry: object) -> Verdict:
    """Read a finding's verdict back out of its manifest entry.

    Args:
        entry: The entry.

    Returns:
        The verdict, defaulting to unmeasured for anything unrecognised.
    """
    if not isinstance(entry, Mapping):
        return Verdict.UNMEASURED
    recorded = entry.get("verdict")
    for verdict in (Verdict.PASSED, Verdict.FAILED, Verdict.UNMEASURED):
        if recorded == str(verdict):
            return verdict
    return Verdict.UNMEASURED


def _exit_code(verdict: Verdict) -> int:
    """Turn a verdict into a process exit code.

    Args:
        verdict: The gate's conclusion.

    Returns:
        The code.
    """
    if verdict is Verdict.PASSED:
        return EXIT_OK
    return EXIT_GATE_FAILED if verdict is Verdict.FAILED else EXIT_UNMEASURED


def _fail_early(directory: Path, root: Path, problem: str, reason: str) -> int:
    """Write a manifest recording that the gate could not get as far as checking.

    Args:
        directory: Where to write.
        root: The repository root.
        problem: What went wrong.
        reason: The stable reason code.

    Returns:
        :data:`EXIT_GATE_FAILED`.

    A manifest is still written. A gate that failed silently and left no artefact
    would be indistinguishable, to anything reading the evidence afterwards, from
    a gate that never ran.
    """
    document = build_manifest(
        run={
            "repository": DEFAULT_REPOSITORY,
            "commit": _sha(root),
            "declaration": CONFIGURATION_FILE,
            "contract": RUNTIME_CONTRACT,
        },
        findings={"declaration": _finding((problem,))},
        verdict={"verdict": str(Verdict.FAILED), "reasons": [reason]},
    )
    (directory / MANIFEST_NAME).write_text(
        render_manifest(document), encoding="utf-8", newline="\n"
    )
    print(f"gpu: {problem}")
    return EXIT_GATE_FAILED


def _report(
    findings: Mapping[str, object],
    observation: Observation,
    verdict: Verdict,
    reasons: Sequence[str],
) -> None:
    """Print what the gate established.

    Args:
        findings: Every check's entry.
        observation: What was measured.
        verdict: The conclusion.
        reasons: The stable reason codes behind it.

    ASCII only, because everything a gate prints must be — a Windows console
    encodes its output with the active code page, and a character it cannot
    represent turns a report into a traceback.
    """
    for name, entry in sorted(findings.items()):
        if not isinstance(entry, Mapping):
            continue
        print(f"gpu: {name}: {entry.get('verdict')}")
        capabilities = entry.get("capabilities")
        if isinstance(capabilities, list):
            for record in capabilities:
                if isinstance(record, Mapping):
                    print(f"  - {record.get('id')}: {record.get('state')}")
        problems = entry.get("problems")
        if isinstance(problems, list):
            for problem in problems:
                print(f"  ! {problem}")
    for note in observation.notes:
        print(f"gpu: note: {note}")
    print(f"gpu: verdict {verdict}")
    if reasons:
        print(f"gpu: reasons {', '.join(sorted(set(reasons)))}")


def declaration_of(root: Path | None = None) -> Declaration:
    """Read the GPU contract from a tree.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.

    Returns:
        The declaration.

    Raises:
        GpuContractError: If it cannot be read or parsed.

    Exposed so that the contract test can assert facts about *this* repository's
    contract without repeating how to find it.
    """
    base = REPO_ROOT if root is None else root
    text = _read(base, CONFIGURATION_FILE)
    if text is None:
        msg = f"{CONFIGURATION_FILE} could not be read"
        raise GpuContractError(msg)
    return parse_declaration(text)
