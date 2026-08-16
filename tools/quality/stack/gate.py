"""Running every scientific-stack check and reducing them to one verdict.

**The judgement lives in :mod:`tools.quality.stack.plan`, the measurement in
:mod:`tools.quality.stack.probes`, and the sequencing here.** Every decision this
file makes is delegated to a pure function tested from literals; what this module
adds is order, I/O, and the arithmetic that turns a set of answers into an exit
code — the same division ``tools/quality/wheels/gate.py`` uses.

**It reaches no network.** No index is consulted, no resolver runs and ``pip`` is
never invoked. The question is entirely about what is installed here, now, which
is why — unlike ``supply`` — this has no ``probe`` subcommand and needs none.

**The measurement is injected, and that is not a convenience.** A test that had to
own a broken ``numpy`` to prove a broken ``numpy`` is refused could not exist.
Substituting the measurer is what lets every failing branch below be reached on a
host where everything is fine, and the default is the real thing, so no caller
outside a test ever passes one.

**Not a second aggregate.** ADR-0042 put the run-level verdict in exactly one
place, and this is not it. The verdict here is about *this gate*, in the same
three-valued :class:`~tools.quality.execution.plan.Verdict` every other gate uses.

**Determinism is checked rather than assumed.** The manifest is built twice and
the renderings compared byte for byte, exactly as the SBOM and the wheel survey
are.
"""

import tomllib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from tools.quality.evidence.redaction import describe as describe_findings
from tools.quality.evidence.redaction import scan as scan_for_secrets
from tools.quality.execution.plan import Verdict, combine
from tools.quality.lock.plan import LockError, normalise
from tools.quality.lock.plan import parse_lock as parse_runtime_lock
from tools.quality.runtime.plan import RuntimeBaselineError
from tools.quality.runtime.plan import parse_declaration as parse_runtime_contract
from tools.quality.stack.manifest import (
    REASON_DECLARATION_UNREADABLE,
    REASON_DEFERRAL_MISPLACED,
    REASON_LIBRARY_DUPLICATED,
    REASON_LIBRARY_UNCHECKED,
    REASON_LIBRARY_UNIMPORTABLE,
    REASON_MANIFEST_LEAKAGE,
    REASON_MANIFEST_NONDETERMINISTIC,
    REASON_PROBE_FAILED,
    REASON_PROVENANCE_DIVERGED,
    REASON_REGISTRY_INCONSISTENT,
    REASON_TARGET_DIVERGED,
    REASON_VERSION_DIVERGED,
)
from tools.quality.stack.manifest import build as build_manifest
from tools.quality.stack.manifest import render as render_manifest
from tools.quality.stack.plan import (
    CONFIGURATION_FILE,
    Declaration,
    Library,
    StackError,
    coverage_problems,
    deferral_problems,
    duplicate_libraries,
    identity_problems,
    implemented_probes,
    parse_declaration,
    provenance_problems,
    registry_problems,
    target_problems,
    version_problems,
)
from tools.quality.stack.probes import LibraryFacts, ProbeError
from tools.quality.stack.probes import measure as measure_library
from tools.quality.stack.probes import run as run_probe

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
"""The repository this gate reports on."""

OUTPUT_DIRECTORY: Final[str] = ".globin/stack"
"""Where the manifest is written, relative to the repository root.

Beside ``.globin/wheels``, ``.globin/lock`` and ``.globin/runtime``, under the
same ignored root. Regenerable, so nothing here is committed.
"""

MANIFEST_NAME: Final[str] = "stack-manifest.json"
"""The manifest's filename."""

RUNTIME_CONTRACT: Final[str] = "docs/engineering/runtime-contract.toml"
"""The contract the declaration's target is compared against."""

RUNTIME_LOCK: Final[str] = "pylock.toml"
"""The lock that pins the runtime dependencies."""

PROJECT_MANIFEST: Final[str] = "pyproject.toml"
"""The manifest that bounds them."""

DELIVERED_PHASE: Final[int] = 22
"""A floor on what has shipped: no deferral may name this phase or an earlier one.

A floor rather than a mirror, for the reason ``tools/quality/wheels/gate.py`` gives
about its own constant: requiring equality would oblige every remaining phase to
edit this line, and a constant that must be bumped to keep an unrelated suite green
is a constant people bump without reading.
"""

ROADMAP_TOTAL_PHASES: Final[int] = 320
"""How many phases the programme has."""

SHA_LENGTH: Final[int] = 40
"""How long a Git object name is."""

EXIT_OK: Final[int] = 0
EXIT_GATE_FAILED: Final[int] = 1
EXIT_UNMEASURED: Final[int] = 3
"""The three answers this gate gives, matching every other gate under ``tools/``."""

Measurer = Callable[[Library], LibraryFacts]
"""Reads what is installed for one library."""

ProbeRunner = Callable[[str], tuple[str, ...]]
"""Runs one probe and returns what it found wrong."""


def _sha(root: Path) -> str:
    """The commit under test, read without starting a process.

    Args:
        root: The repository root.

    Returns:
        The forty-character SHA, or ``"unknown"``.

    Read from ``.git`` directly, exactly as the other gates do, so a manifest can
    be produced in a tree with no Git on the path.
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


def _contract_values(root: Path) -> tuple[str, str, str]:
    """Read what the runtime contract declares about the interpreter.

    Args:
        root: The repository root.

    Returns:
        The implementation, minor line and architecture.

    Raises:
        StackError: If the contract cannot be read or parsed.

    The runtime contract is read rather than restated. Phase 017 owns those
    values, and a second copy here would be a second thing to keep in step.
    """
    text = _read(root, RUNTIME_CONTRACT)
    if text is None:
        msg = f"{RUNTIME_CONTRACT} could not be read, so the target cannot be checked"
        raise StackError(msg)
    try:
        contract = parse_runtime_contract(text)
    except RuntimeBaselineError as fault:
        msg = f"{RUNTIME_CONTRACT} could not be parsed: {fault}"
        raise StackError(msg) from fault
    interpreter = contract.interpreter
    return interpreter.implementation, interpreter.minor_line, interpreter.architecture


def locked_versions(root: Path) -> Mapping[str, str]:
    """Every version the runtime lock pins, by normalised name.

    Args:
        root: The repository root.

    Returns:
        Normalised distribution name to version. Empty when the lock cannot be
        read or parsed, which :func:`version_problems` reports per library rather
        than as one opaque failure.

    The lock is parsed by ``tools/quality/lock``'s own reader rather than by a
    second one written here. Two parsers for one format is exactly the drift
    ``SOURCE_OF_TRUTH.md`` exists to prevent, and that reader already refuses a
    lock version it does not implement.
    """
    text = _read(root, RUNTIME_LOCK)
    if text is None:
        return {}
    try:
        lock = parse_runtime_lock(text, path=RUNTIME_LOCK)
    except LockError:
        return {}
    return {
        package.normalised: package.version
        for package in lock.packages
        if package.version is not None
    }


def declared_bounds(root: Path) -> Mapping[str, str]:
    """Every runtime dependency ``pyproject.toml`` declares, by normalised name.

    Args:
        root: The repository root.

    Returns:
        Normalised distribution name to the specifier following it. A dependency
        declared with no specifier maps to the empty string, which
        :func:`~tools.quality.stack.plan.version_problems` reports as a form it
        cannot read rather than as a satisfied bound.

    Deliberately shallow, for the reason ``globin.adapters.bootstrap`` gives about
    its own requirement reader: this reads requirements GLOBIN wrote, and the
    moment it needs to be right about markers it needs ``packaging``.
    """
    text = _read(root, PROJECT_MANIFEST)
    if text is None:
        return {}
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    project = document.get("project")
    if not isinstance(project, dict):
        return {}
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        return {}
    bounds: dict[str, str] = {}
    for entry in dependencies:
        if not isinstance(entry, str):
            continue
        name, specifier = _split_requirement(entry)
        if name:
            bounds[normalise(name)] = specifier
    return bounds


def _split_requirement(requirement: str) -> tuple[str, str]:
    """Split a requirement into its name and its specifier.

    Args:
        requirement: A requirement string, such as ``"numpy>=2.5.2"``.

    Returns:
        The name and whatever followed it, both stripped.
    """
    head = requirement.strip()
    for index, character in enumerate(head):
        if character in "<>=!~ ;[(@":
            return head[:index].strip(), head[index:].strip()
    return head, ""


def run_stack(
    *,
    root: Path | None = None,
    measurer: Measurer | None = None,
    prober: ProbeRunner | None = None,
) -> int:
    """Check the installed scientific stack against its declared contract.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.
        measurer: Reads what is installed for one library. Defaults to the real
            one.
        prober: Runs one probe. Defaults to the real one.

    Returns:
        The process exit code.

    Raises:
        OSError: If the manifest cannot be written. Left to the caller, which is
            the layer that decides whether a missing artefact is fatal.
    """
    base = REPO_ROOT if root is None else root
    measure = measure_library if measurer is None else measurer
    probe = run_probe if prober is None else prober

    directory = base / OUTPUT_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)

    text = _read(base, CONFIGURATION_FILE)
    if text is None:
        return _fail_early(
            directory,
            base,
            f"{CONFIGURATION_FILE} could not be read",
            REASON_DECLARATION_UNREADABLE,
        )
    try:
        declaration = parse_declaration(text)
    except StackError as fault:
        return _fail_early(directory, base, str(fault), REASON_DECLARATION_UNREADABLE)

    findings: dict[str, object] = {}
    reasons: list[str] = []

    try:
        implementation, minor_line, architecture = _contract_values(base)
    except StackError as fault:
        return _fail_early(directory, base, str(fault), REASON_TARGET_DIVERGED)

    diverged = target_problems(
        declaration.target,
        implementation=implementation,
        minor_line=minor_line,
        architecture=architecture,
    )
    findings["target"] = _finding(diverged)
    if diverged:
        reasons.append(REASON_TARGET_DIVERGED)

    _structural(declaration, findings, reasons)
    _installed(declaration, base, findings, reasons, measure=measure)
    _behaviour(declaration, findings, reasons, probe=probe)

    misfiled = deferral_problems(
        declaration.deferrals, delivered=DELIVERED_PHASE, total=ROADMAP_TOTAL_PHASES
    )
    findings["deferrals"] = _finding(misfiled)
    if misfiled:
        reasons.append(REASON_DEFERRAL_MISPLACED)

    run = _run_section(base, declaration)
    overall = combine([_verdict_of(entry) for entry in findings.values()])
    verdict = {"verdict": str(overall), "reasons": sorted(set(reasons))}

    rendered = render_manifest(build_manifest(run=run, findings=findings, verdict=verdict))
    if rendered != render_manifest(build_manifest(run=run, findings=findings, verdict=verdict)):
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
    _report(findings, overall, reasons)
    return _exit_code(overall)


def _structural(declaration: Declaration, findings: dict[str, object], reasons: list[str]) -> None:
    """Check what the declaration says about itself.

    Args:
        declaration: The parsed declaration.
        findings: The manifest's findings, extended in place.
        reasons: The reason codes, extended in place.

    Nothing here is measured against the machine. These are the checks that would
    fail on a host with no Python at all, which is why they run before anything is
    imported.
    """
    duplicated = duplicate_libraries(declaration.libraries)
    findings["duplicates"] = _finding(
        tuple(f"{name} is declared more than once" for name in duplicated)
    )
    if duplicated:
        reasons.append(REASON_LIBRARY_DUPLICATED)

    inconsistent = registry_problems(declaration, implemented_probes())
    findings["registry"] = _finding(inconsistent)
    if inconsistent:
        reasons.append(REASON_REGISTRY_INCONSISTENT)

    unchecked = coverage_problems(declaration.libraries)
    findings["coverage"] = _finding(unchecked)
    if unchecked:
        reasons.append(REASON_LIBRARY_UNCHECKED)


def _installed(
    declaration: Declaration,
    root: Path,
    findings: dict[str, object],
    reasons: list[str],
    *,
    measure: Measurer,
) -> None:
    """Check what is installed against the four places a version is written down.

    Args:
        declaration: The parsed declaration.
        root: The repository root.
        findings: The manifest's findings, extended in place.
        reasons: The reason codes, extended in place.
        measure: Reads what is installed for one library.
    """
    locked = locked_versions(root)
    bounds = declared_bounds(root)

    versions: list[str] = []
    provenance: list[str] = []
    identity: list[str] = []
    observed: dict[str, object] = {}

    for library in declaration.libraries:
        facts = measure(library)
        key = normalise(library.name)
        observed[library.name] = {
            "installed": facts.installed,
            "wheel_tag": facts.wheel_tag,
            "importable": facts.module_location is not None,
        }
        versions.extend(
            version_problems(
                library,
                installed=facts.installed,
                locked=locked.get(key),
                bound=bounds.get(key),
            )
        )
        provenance.extend(provenance_problems(library, recorded_tag=facts.wheel_tag))
        identity.extend(identity_problems(library, module_location=facts.module_location))

    findings["versions"] = _finding(tuple(versions))
    if versions:
        reasons.append(REASON_VERSION_DIVERGED)
    findings["provenance"] = _finding(tuple(provenance))
    if provenance:
        reasons.append(REASON_PROVENANCE_DIVERGED)
    findings["identity"] = _finding(tuple(identity))
    if identity:
        reasons.append(REASON_LIBRARY_UNIMPORTABLE)
    findings["observed"] = observed


def _behaviour(
    declaration: Declaration,
    findings: dict[str, object],
    reasons: list[str],
    *,
    probe: ProbeRunner,
) -> None:
    """Run every probe each library declares, and record what each concluded.

    Args:
        declaration: The parsed declaration.
        findings: The manifest's findings, extended in place.
        reasons: The reason codes, extended in place.
        probe: Runs one probe and returns what it found wrong.

    Each probe's own verdict is recorded, not merely the aggregate. A manifest
    saying only "probes failed" would answer the question nobody has; the reason a
    reader opens this file is to learn *which* assumption stopped holding.
    """
    results: dict[str, object] = {}
    failed = False
    unmeasured = False
    for library in declaration.libraries:
        for identifier in library.probes:
            try:
                problems = probe(identifier)
            except ProbeError as fault:
                results[identifier] = _finding((str(fault),), measured=False)
                unmeasured = True
                continue
            results[identifier] = _finding(problems)
            failed = failed or bool(problems)
    findings["probes"] = results
    if failed:
        reasons.append(REASON_PROBE_FAILED)
    if unmeasured:
        reasons.append(REASON_LIBRARY_UNIMPORTABLE)


def _run_section(root: Path, declaration: Declaration) -> dict[str, object]:
    """What this run was about.

    Args:
        root: The repository root.
        declaration: The parsed declaration.

    Returns:
        The commit, the files consulted and the declared target.
    """
    return {
        "commit": _sha(root),
        "declaration": CONFIGURATION_FILE,
        "contract": RUNTIME_CONTRACT,
        "lock": RUNTIME_LOCK,
        "manifest": PROJECT_MANIFEST,
        "target": {
            "implementation": declaration.target.implementation,
            "minor_line": declaration.target.minor_line,
            "architecture": declaration.target.architecture,
        },
        "libraries": sorted(library.name for library in declaration.libraries),
    }


def _verdict_of(entry: object) -> Verdict:
    """Read a finding's verdict back out of its manifest entry.

    Args:
        entry: The entry, which may be a finding, a mapping of findings, or the
            observed section, which carries no verdict of its own.

    Returns:
        The verdict. A mapping of findings combines its members; anything with no
        recognisable verdict passes, because the observed section is data rather
        than a check and must not make the run unmeasured.
    """
    if not isinstance(entry, Mapping):
        return Verdict.UNMEASURED
    recorded = entry.get("verdict")
    if isinstance(recorded, str):
        for verdict in (Verdict.PASSED, Verdict.FAILED, Verdict.UNMEASURED):
            if recorded == str(verdict):
                return verdict
        return Verdict.UNMEASURED
    nested = [_verdict_of(value) for value in entry.values() if isinstance(value, Mapping)]
    return combine(nested) if nested else Verdict.PASSED


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
            "commit": _sha(root),
            "declaration": CONFIGURATION_FILE,
            "contract": RUNTIME_CONTRACT,
            "lock": RUNTIME_LOCK,
            "manifest": PROJECT_MANIFEST,
        },
        findings={"declaration": _finding((problem,))},
        verdict={"verdict": str(Verdict.FAILED), "reasons": [reason]},
    )
    (directory / MANIFEST_NAME).write_text(
        render_manifest(document), encoding="utf-8", newline="\n"
    )
    print(f"stack: {problem}")
    return EXIT_GATE_FAILED


def _report(findings: Mapping[str, object], verdict: Verdict, reasons: Sequence[str]) -> None:
    """Print what the gate established.

    Args:
        findings: Every check's entry.
        verdict: The conclusion.
        reasons: The stable reason codes behind it.

    ASCII only, because everything a gate prints must be — a Windows console
    encodes its output with the active code page, and a character it cannot
    represent turns a report into a traceback.
    """
    for name, entry in sorted(findings.items()):
        if name == "observed" or not isinstance(entry, Mapping):
            continue
        if isinstance(entry.get("verdict"), str):
            print(f"stack: {name}: {entry.get('verdict')}")
            problems = entry.get("problems")
            if isinstance(problems, list):
                for problem in problems:
                    print(f"  - {problem}")
            continue
        for identifier, nested in sorted(entry.items()):
            if not isinstance(nested, Mapping):
                continue
            print(f"stack: {identifier}: {nested.get('verdict')}")
            problems = nested.get("problems")
            if isinstance(problems, list):
                for problem in problems:
                    print(f"  - {problem}")
    print(f"stack: verdict {verdict}")
    if reasons:
        print(f"stack: reasons {', '.join(sorted(set(reasons)))}")


def declaration_of(root: Path | None = None) -> Declaration:
    """Read the stack declaration from a tree.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.

    Returns:
        The declaration.

    Raises:
        StackError: If it cannot be read or parsed.

    Exposed so that the contract test can assert facts about *this* repository's
    declaration without repeating how to find it.
    """
    base = REPO_ROOT if root is None else root
    text = _read(base, CONFIGURATION_FILE)
    if text is None:
        msg = f"{CONFIGURATION_FILE} could not be read"
        raise StackError(msg)
    return parse_declaration(text)
