"""The sequencing, the I/O and the exit arithmetic of the workload benefit gate.

The judgement lives in :mod:`tools.quality.benchmark.plan` and the measurement in
:mod:`tools.quality.benchmark.probes`. What is here is the order they happen in,
where the evidence goes, and what the process returns.

**This gate reports on the MACHINE rather than on the tree**, which is why it is
in neither ``fast`` nor ``full``: its verdict can change without a commit and a
commit cannot change it, and a gate inside ``full`` should fail for something the
commit did. That is ADR-0032 condition 5, and it is the same argument
``tools/quality/gpu`` makes about itself.
"""

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from tools.quality.benchmark.manifest import (
    MANIFEST_NAME_DEFAULT,
    REASON_DECLARATION_UNREADABLE,
    REASON_MANIFEST_LEAKAGE,
    REASON_MANIFEST_NONDETERMINISTIC,
    REASON_PHASE_MISPLACED,
    REASON_TARGET_DIVERGED,
    REASON_WORKLOAD_DUPLICATED,
    REASON_WORKLOAD_ERRORED,
    REASON_WORKLOAD_MALFORMED,
)
from tools.quality.benchmark.manifest import build as build_manifest
from tools.quality.benchmark.manifest import render as render_manifest
from tools.quality.benchmark.plan import (
    CONFIGURATION_FILE,
    BenchmarkContractError,
    Declaration,
    Measurement,
    State,
    classify,
    duplicate_workloads,
    gap_problems,
    parse_declaration,
    phase_problems,
    shape_problems,
    target_problems,
)
from tools.quality.benchmark.plan import (
    Verdict as WorkloadVerdict,
)
from tools.quality.benchmark.probes import measure
from tools.quality.evidence.redaction import describe as describe_findings
from tools.quality.evidence.redaction import scan as scan_for_secrets
from tools.quality.execution.plan import Verdict, combine
from tools.quality.runtime.plan import RuntimeBaselineError
from tools.quality.runtime.plan import parse_declaration as parse_runtime_contract

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
"""The repository this gate reports on."""

OUTPUT_DIRECTORY: Final[str] = ".globin/benchmark"
"""Where the manifest is written, relative to the repository root.

Beside ``.globin/gpu`` and ``.globin/stack``, under the same ignored root.
Regenerable, so nothing here is committed.
"""

MANIFEST_NAME: Final[str] = MANIFEST_NAME_DEFAULT
"""The manifest's filename."""

RUNTIME_CONTRACT: Final[str] = "docs/engineering/runtime-contract.toml"
"""The contract the declared target is compared against."""

DEFAULT_REPOSITORY: Final[str] = "aydhn/GLOBIN"
"""Which repository the evidence is about."""

ROADMAP_TOTAL_PHASES: Final[int] = 320
"""How many phases the programme has."""

DELIVERED_PHASE: Final[int] = 24
"""A floor on what has shipped.

Applied only to a workload whose backend is not ``cpu``. A ``cpu`` workload names
the phase that adopted the library it already uses, which is necessarily delivered
— numpy arrived in Phase 021. An unmeasurable non-``cpu`` workload names the phase
that *would* make it measurable, and a delivered phase there is a gap nobody will
ever close.
"""

EXIT_OK: Final[int] = 0
"""Every workload was measured or recorded a state."""

EXIT_GATE_FAILED: Final[int] = 1
"""Something the contract asserts is not true of this tree."""

EXIT_UNMEASURED: Final[int] = 3
"""The gate could not establish what it was asked to establish."""

SHA_LENGTH: Final[int] = 40
"""How long a Git object name is."""


def _read(root: Path, relative: str) -> str | None:
    """Read a file under the repository root.

    Args:
        root: The repository root.
        relative: The path, relative to it.

    Returns:
        The text, or ``None`` when it could not be read.
    """
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def _finding(problems: Sequence[str]) -> dict[str, object]:
    """One check's manifest entry.

    Args:
        problems: What it found, empty when it found nothing.

    Returns:
        The entry.
    """
    return {
        "verdict": str(Verdict.PASSED if not problems else Verdict.FAILED),
        "problems": list(problems),
    }


def _sha(root: Path) -> str:
    """The commit the evidence is about, read without starting a process.

    Args:
        root: The repository root.

    Returns:
        The forty-character SHA, or ``"unknown"``.

    Read from ``.git`` directly, exactly as the other gates do, so a manifest can
    be produced in a tree with no Git on the path — and so the gate starts no
    child, which is one fewer thing that can fail on a machine it was not written
    for.
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


def _contract_values(root: Path) -> tuple[str, str]:
    """What the runtime contract declares about this host.

    Args:
        root: The repository root.

    Returns:
        The system and the architecture.

    Raises:
        BenchmarkContractError: If the runtime contract cannot be read.
    """
    text = _read(root, RUNTIME_CONTRACT)
    if text is None:
        msg = f"{RUNTIME_CONTRACT} could not be read"
        raise BenchmarkContractError(msg)
    try:
        contract = parse_runtime_contract(text)
    except RuntimeBaselineError as fault:
        raise BenchmarkContractError(str(fault)) from fault
    return contract.host.system, contract.interpreter.architecture


def run_benchmark(
    *,
    root: Path | None = None,
    reports: Path | None = None,
    measurements: tuple[Measurement, ...] | None = None,
) -> int:
    """Measure the declared workloads and write the manifest.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.
        reports: Where to write. Defaults to :data:`OUTPUT_DIRECTORY` under root.
        measurements: Pre-taken measurements, injected so a test can exercise the
            whole gate without running a workload or waiting for a clock.

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
        problem = f"{CONFIGURATION_FILE} could not be read"
        return _fail_early(directory, base, problem, REASON_DECLARATION_UNREADABLE)
    try:
        declaration = parse_declaration(declared)
    except BenchmarkContractError as fault:
        return _fail_early(directory, base, str(fault), REASON_DECLARATION_UNREADABLE)

    try:
        system, architecture = _contract_values(base)
    except BenchmarkContractError as fault:
        return _fail_early(directory, base, str(fault), REASON_TARGET_DIVERGED)

    diverged = target_problems(declaration.target, system=system, architecture=architecture)
    findings["target"] = _finding(diverged)
    if diverged:
        reasons.append(REASON_TARGET_DIVERGED)

    duplicated = duplicate_workloads(declaration.workloads)
    findings["duplicates"] = _finding(duplicated)
    if duplicated:
        reasons.append(REASON_WORKLOAD_DUPLICATED)

    malformed = shape_problems(declaration)
    findings["shape"] = _finding(malformed)
    if malformed:
        reasons.append(REASON_WORKLOAD_MALFORMED)

    misplaced = phase_problems(
        declaration.workloads, delivered=DELIVERED_PHASE, total=ROADMAP_TOTAL_PHASES
    )
    findings["phases"] = _finding(misplaced)
    if misplaced:
        reasons.append(REASON_PHASE_MISPLACED)

    taken = _measure(declaration) if measurements is None else measurements
    verdicts = classify(declaration, taken)
    errored = gap_problems(verdicts)
    findings["workloads"] = _workload_finding(verdicts, errored)
    if errored:
        reasons.append(REASON_WORKLOAD_ERRORED)

    run = _run_section(base, declaration)
    observed = _observed_section(verdicts)
    overall = combine([_verdict_of(entry) for entry in findings.values()])
    verdict = {"verdict": str(overall), "reasons": sorted(set(reasons))}

    document = build_manifest(run={**run, "observed": observed}, findings=findings, verdict=verdict)
    rendered = render_manifest(document)

    # The determinism check is applied to the FINDINGS half only, and that
    # narrowing is the honest form of the check rather than a weakening of it.
    # `observed` holds nanoseconds, which differ every run by design; comparing
    # them would make the gate fail for the reason it exists to measure. What must
    # be a pure function of its inputs is the derivation of verdicts from the
    # contract and the recorded numbers, and that is what is compared here.
    again = render_manifest(
        build_manifest(
            run={**run, "observed": observed},
            findings={"workloads": _workload_finding(classify(declaration, taken), errored)}
            | {key: value for key, value in findings.items() if key != "workloads"},
            verdict=verdict,
        )
    )
    if rendered != again:
        return _fail_early(
            directory,
            base,
            "two derivations of the same measurements disagreed",
            REASON_MANIFEST_NONDETERMINISTIC,
        )

    leaks = scan_for_secrets(MANIFEST_NAME, rendered)
    if leaks:
        return _fail_early(directory, base, describe_findings(leaks), REASON_MANIFEST_LEAKAGE)

    (directory / MANIFEST_NAME).write_text(rendered, encoding="utf-8", newline="\n")
    _report(verdicts, overall, reasons)
    return _exit_code(overall)


def _measure(declaration: Declaration) -> tuple[Measurement, ...]:
    """Run every declared workload.

    Args:
        declaration: The contract.

    Returns:
        One measurement per workload, in declaration order.
    """
    method = declaration.method
    return tuple(
        measure(workload, method.warmup, method.repeats, method.reduction)
        for workload in declaration.workloads
    )


def _workload_finding(
    verdicts: tuple[WorkloadVerdict, ...], problems: Sequence[str]
) -> dict[str, object]:
    """The workloads check's manifest entry.

    Args:
        verdicts: What every workload concluded.
        problems: The ones that are failures.

    Returns:
        The entry, with one record per workload in declaration order.
    """
    return {
        "verdict": str(Verdict.PASSED if not problems else Verdict.FAILED),
        "problems": list(problems),
        "workloads": [
            {
                "id": verdict.identifier,
                "state": str(verdict.state),
                "benefits": verdict.benefits,
                "speedup": verdict.speedup,
                "detail": verdict.detail,
            }
            for verdict in verdicts
        ],
    }


def _observed_section(verdicts: tuple[WorkloadVerdict, ...]) -> dict[str, object]:
    """What was measured, for the manifest's ``run.observed`` section.

    Args:
        verdicts: What every workload concluded.

    Returns:
        The section. These are the numbers that move between runs.
    """
    return {
        "timings": [
            {
                "id": verdict.identifier,
                "nanoseconds": verdict.nanoseconds,
                "baseline_nanoseconds": verdict.baseline_nanoseconds,
            }
            for verdict in verdicts
        ],
        "measured": sum(1 for verdict in verdicts if verdict.state is State.MEASURED),
        "benefiting": sorted(
            verdict.identifier for verdict in verdicts if verdict.benefits is True
        ),
    }


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
        "method": {
            "warmup": declaration.method.warmup,
            "repeats": declaration.method.repeats,
            "reduction": declaration.method.reduction,
            "clock": declaration.method.clock,
        },
        "workloads": len(declaration.workloads),
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
    for candidate in Verdict:
        if str(candidate) == recorded:
            return candidate
    return Verdict.UNMEASURED


def _exit_code(verdict: Verdict) -> int:
    """Turn the overall verdict into a process exit code.

    Args:
        verdict: The conclusion.

    Returns:
        The code.
    """
    if verdict is Verdict.PASSED:
        return EXIT_OK
    return EXIT_GATE_FAILED if verdict is Verdict.FAILED else EXIT_UNMEASURED


def _fail_early(directory: Path, root: Path, problem: str, reason: str) -> int:
    """Write a manifest recording that the gate could not get as far as measuring.

    Args:
        directory: Where to write.
        root: The repository root.
        problem: What went wrong.
        reason: The stable reason code.

    Returns:
        :data:`EXIT_GATE_FAILED`.

    A manifest is still written, for the reason every other gate writes one: a
    gate that failed silently and left no artefact is indistinguishable, to
    anything reading the evidence afterwards, from a gate that never ran.
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
    print(f"benchmark: {problem}")
    return EXIT_GATE_FAILED


def _report(
    verdicts: tuple[WorkloadVerdict, ...], verdict: Verdict, reasons: Sequence[str]
) -> None:
    """Print what the gate established.

    Args:
        verdicts: What every workload concluded.
        verdict: The conclusion.
        reasons: The stable reason codes behind it.

    ASCII only, because a Windows console encodes its output with the active code
    page and a character it cannot represent turns a report into a traceback.
    """
    for item in verdicts:
        line = f"benchmark: {item.identifier}: {item.state}"
        if item.speedup is not None:
            line += f" speedup {item.speedup}"
        if item.benefits is not None and item.state is State.MEASURED:
            line += " (benefits)" if item.benefits else ""
        if item.detail:
            line += f" [{item.detail}]"
        print(line)
    print(f"benchmark: verdict {verdict}")
    if reasons:
        print(f"benchmark: reasons {', '.join(sorted(set(reasons)))}")


def declaration_of(root: Path | None = None) -> Declaration:
    """Read the benchmark contract from a tree.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.

    Returns:
        The declaration.

    Raises:
        BenchmarkContractError: If it cannot be read or parsed.

    Exposed so the contract test can assert facts about *this* repository's
    contract without repeating how to find it.
    """
    base = REPO_ROOT if root is None else root
    text = _read(base, CONFIGURATION_FILE)
    if text is None:
        msg = f"{CONFIGURATION_FILE} could not be read"
        raise BenchmarkContractError(msg)
    return parse_declaration(text)


def digest_of(payload: bytes) -> str:
    """A content digest, for a caller that needs one without importing hashlib.

    Args:
        payload: What to hash.

    Returns:
        The lowercase hex digest.
    """
    return hashlib.sha256(payload).hexdigest()
