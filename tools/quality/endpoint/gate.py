"""Running every endpoint check and reducing them to one verdict.

**The judgement lives in :mod:`tools.quality.endpoint.plan`; the sequencing lives
here.** Every decision this file makes is delegated to a pure function tested from
literals. What this module adds is order, file reading, and the arithmetic that turns a
set of answers into an exit code — the division ``tools/quality/gpu/gate.py`` draws.

**It reaches nothing, and binds nothing.** No socket is opened, no server started and
no question asked of this host. Every verdict is a comparison between
``endpoint-contract.toml`` and the source beside it, which is what makes this safe to
run anywhere — including on a machine where the surface has never been enabled, and on
continuous integration, where it has not.

**It is nonetheless kept out of ``full``**, for ADR-0032 condition 5's reason as much
as for cost: the gate reads the tree rather than the host, so it *could* live in the
commit gate — but the checks it performs are already enforced by
``tests/architecture/test_library_discipline.py`` and the unit suite, and a second
mechanism running on every commit would be paying twice for one guarantee. What this
gate adds over those tests is the *artefact*: a manifest a reader can compare between
two commits.

**Determinism is checked rather than assumed.** The manifest is built twice and the
renderings compared byte for byte, exactly as every other gate here does.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from tools.quality.endpoint.manifest import (
    REASON_ADDRESS_HARDCODED,
    REASON_BOUNDS_DIVERGED,
    REASON_CARDINALITY_UNPROVEN,
    REASON_CONTRACT_CONTRADICTED,
    REASON_DECLARATION_UNREADABLE,
    REASON_EXPOSITIONS_DIVERGED,
    REASON_LOOPBACK_UNDECLARED,
    REASON_MANIFEST_LEAKAGE,
    REASON_MANIFEST_NONDETERMINISTIC,
    REASON_ROUTES_DIVERGED,
    REASON_SOURCE_UNREADABLE,
    REASON_SWITCHES_DIVERGED,
    REASON_TEST_ABSENT,
    REASON_VOCABULARY_DIVERGED,
    REASON_WILDCARD_PRESENT,
)
from tools.quality.endpoint.manifest import build as build_manifest
from tools.quality.endpoint.manifest import render as render_manifest
from tools.quality.endpoint.plan import (
    CONFIG_MODULE,
    CONFIGURATION_FILE,
    DOMAIN_MODULE,
    METRICS_MODULE,
    Declaration,
    EndpointContractError,
    binding_problems,
    bound_problems,
    contract_problems,
    exposition_problems,
    family_problems,
    loopback_problems,
    parse_declaration,
    route_problems,
    switch_problems,
    test_problems,
    vocabulary_problems,
    wildcard_problems,
)
from tools.quality.evidence.redaction import describe as describe_findings
from tools.quality.evidence.redaction import scan as scan_for_secrets
from tools.quality.execution.plan import Verdict, combine

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
"""The repository this gate reports on."""

OUTPUT_DIRECTORY: Final[str] = ".globin/endpoint"
"""Where the manifest is written, relative to the repository root."""

MANIFEST_NAME: Final[str] = "endpoint-manifest.json"
"""The manifest's filename."""

PACKAGE_DIRECTORY: Final[str] = "src/globin"
"""The package the wildcard check sweeps."""

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


def run_endpoint(*, root: Path | None = None, reports: Path | None = None) -> int:
    """Recompute the endpoint contract against the source and write the manifest.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.
        reports: Where to write. Defaults to :data:`OUTPUT_DIRECTORY` under root.

    Returns:
        :data:`EXIT_OK`, :data:`EXIT_GATE_FAILED` or :data:`EXIT_UNMEASURED`.

    The order is the order of dependence. The contract is judged against itself before
    any source is read, because a contract that contradicts itself would otherwise be
    reported as a *source* problem and send a reader to the wrong file.
    """
    base = REPO_ROOT if root is None else root
    directory = (base / OUTPUT_DIRECTORY) if reports is None else reports
    directory.mkdir(parents=True, exist_ok=True)

    declared = _read(base, CONFIGURATION_FILE)
    if declared is None:
        problem = f"{CONFIGURATION_FILE} could not be read"
        return _fail_early(directory, base, problem, REASON_DECLARATION_UNREADABLE)
    try:
        declaration = parse_declaration(declared)
    except EndpointContractError as fault:
        return _fail_early(directory, base, str(fault), REASON_DECLARATION_UNREADABLE)

    sources: dict[str, str] = {}
    for name in (DOMAIN_MODULE, CONFIG_MODULE, METRICS_MODULE, declaration.binding_module):
        text = _read(base, name)
        if text is None:
            problem = f"{name} could not be read"
            return _fail_early(directory, base, problem, REASON_SOURCE_UNREADABLE)
        sources[name] = text

    domain = sources[DOMAIN_MODULE]
    config = sources[CONFIG_MODULE]
    metrics = sources[METRICS_MODULE]
    binding = sources[declaration.binding_module]
    package = _package_sources(base)

    checks: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("contract", REASON_CONTRACT_CONTRADICTED, contract_problems(declaration)),
        ("routes", REASON_ROUTES_DIVERGED, route_problems(declaration, domain)),
        ("loopback", REASON_LOOPBACK_UNDECLARED, loopback_problems(declaration, domain)),
        ("binding", REASON_ADDRESS_HARDCODED, binding_problems(declaration, binding)),
        ("wildcard", REASON_WILDCARD_PRESENT, wildcard_problems(declaration, package)),
        ("bounds", REASON_BOUNDS_DIVERGED, bound_problems(declaration, domain, config)),
        ("switches", REASON_SWITCHES_DIVERGED, switch_problems(declaration, config)),
        ("expositions", REASON_EXPOSITIONS_DIVERGED, exposition_problems(declaration, domain)),
        ("vocabulary", REASON_VOCABULARY_DIVERGED, vocabulary_problems(declaration, domain)),
        ("cardinality", REASON_CARDINALITY_UNPROVEN, family_problems(declaration, domain, metrics)),
        (
            "tests",
            REASON_TEST_ABSENT,
            test_problems(declaration, _tests_present(base, declaration)),
        ),
    )

    findings = {name: _finding(problems) for name, _reason, problems in checks}
    reasons = [reason for _name, reason, problems in checks if problems]
    run = _run_section(base, declaration)
    overall = combine([_verdict_of(entry) for entry in findings.values()])
    verdict = {"verdict": str(overall), "reasons": sorted(set(reasons))}

    rendered = render_manifest(build_manifest(run=run, findings=findings, verdict=verdict))
    again = render_manifest(build_manifest(run=run, findings=findings, verdict=verdict))
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
    _report(findings, overall, reasons)
    return _exit_code(overall)


def declaration_of(root: Path | None = None) -> Declaration:
    """Read the endpoint contract from a tree.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.

    Returns:
        The declaration.

    Raises:
        EndpointContractError: If it cannot be read or parsed.

    Exposed so a contract test can assert facts about *this* repository's contract
    without repeating how to find it.
    """
    base = REPO_ROOT if root is None else root
    text = _read(base, CONFIGURATION_FILE)
    if text is None:
        msg = f"{CONFIGURATION_FILE} could not be read"
        raise EndpointContractError(msg)
    return parse_declaration(text)


def _read(root: Path, relative: str) -> str | None:
    """One file's text, or ``None`` when it cannot be read.

    Args:
        root: The repository root.
        relative: The repository-relative path.

    Returns:
        The text, or ``None``.
    """
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def _package_sources(root: Path) -> dict[str, str]:
    """Every module in the package, by repository-relative path.

    Args:
        root: The repository root.

    Returns:
        Each module's text, sorted so two runs report identically.

    A module that cannot be read is skipped rather than failing the sweep: the sweep
    looks for a token's *presence*, and a file nobody can read carries none.
    """
    sources: dict[str, str] = {}
    for path in sorted((root / PACKAGE_DIRECTORY).rglob("*.py")):
        try:
            sources[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return sources


def _tests_present(root: Path, declaration: Declaration) -> dict[str, bool]:
    """Whether each test module the contract names exists.

    Args:
        root: The repository root.
        declaration: The parsed contract.

    Returns:
        Each kind mapped to whether its module was found.
    """
    return {kind: (root / path).is_file() for kind, path in declaration.tests.items()}


def _sha(root: Path) -> str:
    """The commit under test, read without starting a process.

    Args:
        root: The repository root.

    Returns:
        The forty-character SHA, or ``"unknown"``.

    Read from ``.git`` directly, exactly as the other gates do, so a manifest can be
    produced in a tree without Git on the path.
    """
    head = root / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if not text.startswith("ref:"):
        return text if len(text) == SHA_LENGTH else "unknown"
    reference = text.removeprefix("ref:").strip()
    try:
        resolved = (root / ".git" / reference).read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    return resolved if len(resolved) == SHA_LENGTH else "unknown"


def _run_section(root: Path, declaration: Declaration) -> dict[str, object]:
    """What was asked, for the manifest's ``run`` section.

    Args:
        root: The repository root.
        declaration: The parsed contract.

    Returns:
        The section. No wall clock and no absolute path.
    """
    return {
        "repository": DEFAULT_REPOSITORY,
        "commit": _sha(root),
        "declaration": CONFIGURATION_FILE,
        "modules": sorted(
            {DOMAIN_MODULE, CONFIG_MODULE, METRICS_MODULE, declaration.binding_module}
        ),
        "contract_schema_version": declaration.schema_version,
        "introduced_in_phase": declaration.phase,
        "loopback": {
            "addresses": list(declaration.addresses),
            "default": declaration.default_address,
            "value_type": declaration.value_type,
            "binding_module": declaration.binding_module,
        },
        "routes": [
            {
                "path": route.path,
                "route": route.route,
                "switch": route.switch,
                "answers_by_default": route.answers_by_default,
            }
            for route in declaration.routes
        ],
        "expositions": [
            {"format": exposition.format, "content_type": exposition.content_type}
            for exposition in declaration.expositions
        ],
        "bounds": [
            {
                "name": bound.name,
                "minimum": bound.minimum,
                "maximum": bound.maximum,
                "default": bound.default,
            }
            for bound in declaration.bounds
        ],
        "families": [
            {
                "name": family.name,
                "kind": family.kind,
                "attributes": list(family.attributes),
                "series": family.series,
                "budget": family.budget,
            }
            for family in declaration.families
        ],
        "tests": dict(sorted(declaration.tests.items())),
    }


def _finding(problems: Sequence[str]) -> dict[str, object]:
    """One check's entry.

    Args:
        problems: What it concluded, empty when it passed.

    Returns:
        The entry.
    """
    return {
        "verdict": str(Verdict.PASSED if not problems else Verdict.FAILED),
        "problems": list(problems),
    }


def _verdict_of(entry: object) -> Verdict:
    """Recover a finding's verdict.

    Args:
        entry: The finding.

    Returns:
        The verdict, or :attr:`Verdict.UNMEASURED` for anything unrecognised.
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
    would be indistinguishable, to anything reading the evidence afterwards, from a
    gate that never ran.
    """
    document = build_manifest(
        run={
            "repository": DEFAULT_REPOSITORY,
            "commit": _sha(root),
            "declaration": CONFIGURATION_FILE,
        },
        findings={"declaration": _finding((problem,))},
        verdict={"verdict": str(Verdict.FAILED), "reasons": [reason]},
    )
    (directory / MANIFEST_NAME).write_text(
        render_manifest(document), encoding="utf-8", newline="\n"
    )
    print(f"endpoint: {problem}")
    return EXIT_GATE_FAILED


def _report(findings: Mapping[str, object], verdict: Verdict, reasons: Sequence[str]) -> None:
    """Print what the gate established.

    Args:
        findings: Every check's entry.
        verdict: The conclusion.
        reasons: The stable reason codes behind it.

    ASCII only, because everything a gate prints must be — a Windows console encodes
    its output with the active code page, and a character it cannot represent turns a
    report into a traceback.
    """
    for name, entry in sorted(findings.items()):
        if not isinstance(entry, Mapping):
            continue
        print(f"endpoint: {name}: {entry.get('verdict')}")
        problems = entry.get("problems")
        if isinstance(problems, list):
            for problem in problems:
                print(f"  ! {problem}")
    print(f"endpoint: verdict {verdict}")
    if reasons:
        print(f"endpoint: reasons {', '.join(sorted(set(reasons)))}")
