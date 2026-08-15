"""Running every wheel-survey check and reducing them to one verdict.

**The judgement lives in :mod:`tools.quality.wheels.plan`; the sequencing lives
here.** Every decision this file makes is delegated to a pure function tested from
literals. What this module adds is order, I/O, and the arithmetic that turns a set
of answers into an exit code — the same division ``tools/quality/governance/gate.py``
uses.

**Two commands, because one of them reaches the network and one does not.** The
default ``check`` reads the declaration and the runtime contract and recomputes
every verdict from the evidence recorded beside it; it opens no socket, so it runs
on an aeroplane and so do its tests. ``probe`` does all of that and then asks the
index whether the record is still true. That split is ``tools/quality/supply``'s,
for its reason: ``full`` runs before every commit, and a gate in it must not
depend on a service being up.

**The probe is injected, and that is not a convenience.** ADR-0024's offline
guarantee is enforced by refusing sockets in the *test* process, and a function
that opens one inside that process would sail past it in the opposite direction —
the guard would catch the test rather than the gate. A substitutable fetcher is
what lets the network path be exercised without a network, and the default is the
real thing, so no caller outside a test ever passes one.

**Not a second aggregate.** ADR-0042 put the run-level verdict in exactly one
place, and this is not it. The verdict here is about *this gate*, in the same
three-valued :class:`~tools.quality.execution.plan.Verdict` every other gate uses.

**Determinism is checked rather than assumed.** The manifest is built twice and
the renderings compared byte for byte, exactly as the SBOM is.
"""

import json
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from tools.quality.evidence.redaction import describe as describe_findings
from tools.quality.evidence.redaction import scan as scan_for_secrets
from tools.quality.execution.plan import Verdict, combine
from tools.quality.runtime.plan import RuntimeBaselineError
from tools.quality.runtime.plan import parse_declaration as parse_runtime_contract
from tools.quality.wheels.manifest import (
    REASON_DECLARATION_UNREADABLE,
    REASON_INDEX_DIVERGED,
    REASON_INDEX_UNREACHABLE,
    REASON_LIBRARY_DUPLICATED,
    REASON_MANIFEST_LEAKAGE,
    REASON_MANIFEST_NONDETERMINISTIC,
    REASON_PHASE_MISPLACED,
    REASON_RECORD_INCONSISTENT,
    REASON_TARGET_DIVERGED,
    REASON_WHEEL_UNAVAILABLE,
)
from tools.quality.wheels.manifest import build as build_manifest
from tools.quality.wheels.manifest import render as render_manifest
from tools.quality.wheels.plan import (
    CONFIGURATION_FILE,
    Declaration,
    Library,
    Target,
    WheelSurveyError,
    duplicate_libraries,
    free_threaded_gaps,
    gap_problems,
    parse_declaration,
    phase_problems,
    serving_wheels,
    target_problems,
    verdict_problems,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
"""The repository this gate reports on."""

OUTPUT_DIRECTORY: Final[str] = ".globin/wheels"
"""Where the manifest is written, relative to the repository root.

Beside ``.globin/supply``, ``.globin/governance`` and ``.globin/runtime``, under
the same ignored root. Regenerable, so nothing here is committed.
"""

MANIFEST_NAME: Final[str] = "wheel-manifest.json"
"""The manifest's filename."""

RUNTIME_CONTRACT: Final[str] = "docs/engineering/runtime-contract.toml"
"""The contract the survey's target is compared against."""

ROADMAP_TOTAL_PHASES: Final[int] = 320
"""How many phases the programme has."""

DELIVERED_PHASE: Final[int] = 18
"""A floor on what has shipped: no survey entry may name this phase or an earlier one.

Deliberately a constant rather than a read of ``ROADMAP.md``. This bound exists to
catch a survey entry pointing at work that has already happened — which is an
adoption wearing a survey's clothes — and parsing the roadmap to discover it would
make the gate's verdict depend on a document the gate is not otherwise about.

**A floor, not a mirror.** ``tests/contract/test_wheels_contract.py`` asserts it
never *exceeds* ``LAST_COMPLETED_PHASE`` rather than equalling it, so the value
only needs revisiting when the survey does. Requiring equality would oblige every
one of the remaining phases to edit this line for no reason, and a constant that
must be bumped to keep an unrelated suite green is a constant people bump without
reading. Erring low makes the gate too permissive rather than wrongly rejecting,
which is the safe direction for a bound whose whole job is to catch an obvious
mistake.
"""

SHA_LENGTH: Final[int] = 40
"""How long a Git object name is."""

DEFAULT_REPOSITORY: Final[str] = "aydhn/GLOBIN"
"""Which repository the manifest records itself as describing."""

DEFAULT_TIMEOUT: Final[float] = 30.0
"""How long one index request may take."""

HTTPS: Final[str] = "https"
"""The only scheme the probe will open."""

EXIT_OK: Final[int] = 0
EXIT_GATE_FAILED: Final[int] = 1
EXIT_UNMEASURED: Final[int] = 3

Fetcher = Callable[..., str]
"""How the probe reads one index document. Substitutable so the network path is testable."""


def fetch(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Read one index document over HTTPS.

    Args:
        url: The document's location.
        timeout: How long to wait.

    Returns:
        The response body, decoded as UTF-8.

    Raises:
        WheelSurveyError: If the URL is not HTTPS.
        OSError: If the request fails. :class:`urllib.error.URLError` is one.

    The scheme is checked rather than trusted. The URLs come from a file in this
    repository, which makes them ours rather than a stranger's — but ``file://``
    and ``http://`` are both reachable through the same call, and a survey that
    could be pointed at the local disk by editing a TOML string is a survey whose
    evidence means less than it appears to.
    """
    if not url.startswith(f"{HTTPS}://"):
        msg = f"the probe reads {HTTPS} only, and {url!r} is not"
        raise WheelSurveyError(msg)
    request = urllib.request.Request(  # noqa: S310 — the scheme is checked above
        url, headers={"User-Agent": f"{DEFAULT_REPOSITORY} wheel survey"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = response.read()
    return str(body.decode("utf-8"))


def _sha(root: Path) -> str:
    """The commit under test, read without starting a process.

    Args:
        root: The repository root.

    Returns:
        The forty-character SHA, or ``"unknown"``.

    Read from ``.git`` directly, exactly as ``tools/quality/governance/gate.py``
    does, so that a manifest can be produced in a tree without Git on the path.
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

    The order matters: an unmeasured check that also happens to have found
    nothing is unmeasured, not passed.
    """
    verdict = (
        Verdict.UNMEASURED if not measured else (Verdict.FAILED if problems else Verdict.PASSED)
    )
    return {"verdict": str(verdict), "problems": list(problems)}


def _contract_values(root: Path) -> tuple[str, str, str, bool]:
    """Read what the runtime contract declares about the interpreter.

    Args:
        root: The repository root.

    Returns:
        The implementation, minor line, architecture and free-threaded flag.

    Raises:
        WheelSurveyError: If the contract cannot be read or parsed.

    The runtime contract is read rather than restated. Phase 017 owns those
    values, and a second copy of them in this package would be a second thing to
    keep in step — which is the failure ``SOURCE_OF_TRUTH.md`` describes.
    """
    text = _read(root, RUNTIME_CONTRACT)
    if text is None:
        msg = f"{RUNTIME_CONTRACT} could not be read, so the survey's target cannot be checked"
        raise WheelSurveyError(msg)
    try:
        contract = parse_runtime_contract(text)
    except RuntimeBaselineError as fault:
        msg = f"{RUNTIME_CONTRACT} could not be parsed: {fault}"
        raise WheelSurveyError(msg) from fault
    interpreter = contract.interpreter
    return (
        interpreter.implementation,
        interpreter.minor_line,
        interpreter.architecture,
        interpreter.free_threaded,
    )


def _availability(libraries: Sequence[Library], target: Target) -> tuple[str, ...]:
    """Report every scheduled library with no wheel for the pinned interpreter.

    Args:
        libraries: Every surveyed library.
        target: The environment surveyed against.

    Returns:
        One sentence per library without a wheel, empty when the stack is covered.

    This is the question Phase 018 exists to answer, and it is separate from
    whether the record is internally consistent. A record can be perfectly
    consistent about a library that cannot be installed.
    """
    problems: list[str] = []
    for library in libraries:
        try:
            serving = serving_wheels(library.wheels, target)
        except WheelSurveyError as fault:
            problems.append(f"{library.name}: {fault}")
            continue
        if not serving:
            owner = (
                f"phase {library.resolved_by:03d}" if library.resolved_by is not None else "nobody"
            )
            problems.append(
                f"{library.name} {library.version} has no wheel for the pinned "
                f"interpreter, and the gap is owned by {owner}"
            )
    return tuple(problems)


def _index_problems(
    libraries: Sequence[Library], *, fetcher: Fetcher, timeout: float
) -> tuple[tuple[str, ...], bool]:
    """Compare the record against the live index.

    Args:
        libraries: Every surveyed library.
        fetcher: How to read one index document.
        timeout: How long each request may take.

    Returns:
        The disagreements, and whether every library was actually reached.

    A library that could not be reached makes the probe *unmeasured* rather than
    passed. ``docs/DEPENDENCY_POLICY.md`` states the rule this follows: a scanner
    has three possible results and two of them look alike from a distance, so
    "could not look" gets its own outcome and never counts as "found nothing".
    """
    problems: list[str] = []
    measured = True
    for library in libraries:
        try:
            payload = fetcher(library.source, timeout=timeout)
        except (OSError, WheelSurveyError) as fault:
            measured = False
            problems.append(f"{library.name}: {library.source} could not be read: {fault}")
            continue
        try:
            document = json.loads(payload)
            info = document["info"]
            published = {entry["filename"] for entry in document["urls"]}
        except (json.JSONDecodeError, KeyError, TypeError) as fault:
            measured = False
            problems.append(f"{library.name}: {library.source} is not the expected JSON: {fault}")
            continue

        version = info.get("version")
        if version != library.version:
            problems.append(
                f"{library.name}: the record surveys {library.version}, and the index now "
                f"publishes {version} as current"
            )
            continue
        requires = info.get("requires_python")
        if requires != library.requires_python:
            problems.append(
                f"{library.name} {library.version}: the record says Requires-Python "
                f"{library.requires_python!r}, and the index says {requires!r}"
            )
        vanished = sorted(set(library.wheels) - published)
        if vanished:
            problems.append(
                f"{library.name} {library.version}: recorded {', '.join(vanished)}, which "
                f"the index no longer publishes"
            )
    return tuple(problems), measured


def run_wheels(
    *,
    root: Path | None = None,
    reports: Path | None = None,
    probe: bool = False,
    fetcher: Fetcher | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> int:
    """Check the wheel survey and write the manifest.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.
        reports: Where to write. Defaults to :data:`OUTPUT_DIRECTORY` under root.
        probe: Whether to also compare the record against the index.
        fetcher: How to read the index. Defaults to :func:`fetch`.
        timeout: How long each index request may take.

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
        return _fail_early(directory, base, unreadable, REASON_DECLARATION_UNREADABLE, probe=probe)
    try:
        declaration = parse_declaration(declared)
    except WheelSurveyError as fault:
        return _fail_early(directory, base, str(fault), REASON_DECLARATION_UNREADABLE, probe=probe)

    target = declaration.target
    libraries = declaration.libraries

    try:
        implementation, minor_line, architecture, free_threaded = _contract_values(base)
    except WheelSurveyError as fault:
        return _fail_early(directory, base, str(fault), REASON_TARGET_DIVERGED, probe=probe)

    diverged = target_problems(
        target,
        implementation=implementation,
        minor_line=minor_line,
        architecture=architecture,
        free_threaded=free_threaded,
    )
    findings["target"] = _finding(diverged)
    if diverged:
        reasons.append(REASON_TARGET_DIVERGED)

    duplicated = duplicate_libraries(libraries)
    findings["duplicates"] = _finding(
        tuple(f"{name} is surveyed more than once" for name in duplicated)
    )
    if duplicated:
        reasons.append(REASON_LIBRARY_DUPLICATED)

    misplaced = (
        *phase_problems(libraries, delivered=DELIVERED_PHASE, total=ROADMAP_TOTAL_PHASES),
        *gap_problems(libraries, delivered=DELIVERED_PHASE, total=ROADMAP_TOTAL_PHASES),
    )
    findings["phases"] = _finding(misplaced)
    if misplaced:
        reasons.append(REASON_PHASE_MISPLACED)

    inconsistent = tuple(
        problem for library in libraries for problem in verdict_problems(library, target)
    )
    findings["record"] = _finding(inconsistent)
    if inconsistent:
        reasons.append(REASON_RECORD_INCONSISTENT)

    unavailable = _availability(libraries, target)
    findings["availability"] = _finding(
        tuple(problem for problem in unavailable if "owned by nobody" in problem)
    )
    if any("owned by nobody" in problem for problem in unavailable):
        reasons.append(REASON_WHEEL_UNAVAILABLE)

    findings["free_threaded"] = _free_threaded_finding(libraries, target)

    if probe:
        divergence, measured = _index_problems(libraries, fetcher=fetcher or fetch, timeout=timeout)
        findings["index"] = _finding(divergence, measured=measured)
        if not measured:
            reasons.append(REASON_INDEX_UNREACHABLE)
        elif divergence:
            reasons.append(REASON_INDEX_DIVERGED)

    run = _run_section(base, target, libraries, probe=probe)
    overall = combine([_verdict_of(entry) for entry in findings.values()])

    document = build_manifest(
        run=run,
        findings=findings,
        verdict={"verdict": str(overall), "reasons": sorted(set(reasons))},
    )
    rendered = render_manifest(document)
    if rendered != render_manifest(
        build_manifest(
            run=run,
            findings=findings,
            verdict={"verdict": str(overall), "reasons": sorted(set(reasons))},
        )
    ):
        return _fail_early(
            directory,
            base,
            "two renderings of the same run disagreed",
            REASON_MANIFEST_NONDETERMINISTIC,
            probe=probe,
        )

    leaks = scan_for_secrets(MANIFEST_NAME, rendered)
    if leaks:
        return _fail_early(
            directory, base, describe_findings(leaks), REASON_MANIFEST_LEAKAGE, probe=probe
        )

    (directory / MANIFEST_NAME).write_text(rendered, encoding="utf-8", newline="\n")
    _report(findings, overall, reasons)
    return _exit_code(overall)


def _free_threaded_finding(libraries: Sequence[Library], target: Target) -> dict[str, object]:
    """What adopting a free-threaded build would currently cost.

    Args:
        libraries: Every surveyed library.
        target: The declared target.

    Returns:
        A manifest entry that always passes, carrying the names of the libraries
        that would block the change.

    **This finding never fails the gate, and that is the decision.** ADR-0050
    refused the free-threaded build; a gap here is that refusal being correct, not
    something going wrong. Failing on it would make the gate red for holding the
    position the project deliberately holds. What it does instead is name the
    blockers, so the day the list empties is a day somebody can see.
    """
    try:
        blocked = free_threaded_gaps(libraries, target)
    except WheelSurveyError as fault:
        return {"verdict": str(Verdict.PASSED), "problems": [], "detail": str(fault)}
    detail = (
        "the free-threaded build is refused by ADR-0050, and this is what adopting it "
        f"would currently cost: {len(blocked)} of {len(libraries)} surveyed libraries "
        "publish no wheel for it"
    )
    return {
        "verdict": str(Verdict.PASSED),
        "problems": [],
        "blocked": list(blocked),
        "detail": detail,
    }


def _run_section(
    root: Path, target: Target, libraries: Sequence[Library], *, probe: bool
) -> dict[str, object]:
    """What was checked, for the manifest's ``run`` section.

    Args:
        root: The repository root.
        target: The environment surveyed against.
        libraries: Every surveyed library.
        probe: Whether the index was consulted.

    Returns:
        The section. No wall clock and no absolute path.
    """
    return {
        "repository": DEFAULT_REPOSITORY,
        "commit": _sha(root),
        "declaration": CONFIGURATION_FILE,
        "contract": RUNTIME_CONTRACT,
        "mode": "probe" if probe else "check",
        "target": {
            "implementation": target.implementation,
            "minor_line": target.minor_line,
            "architecture": target.architecture,
            "platform_tag": target.platform_tag,
            "free_threaded": target.free_threaded,
            "index": target.index,
            "surveyed": target.surveyed,
        },
        "libraries": len(libraries),
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


def _fail_early(directory: Path, root: Path, problem: str, reason: str, *, probe: bool) -> int:
    """Write a manifest recording that the gate could not get as far as checking.

    Args:
        directory: Where to write.
        root: The repository root.
        problem: What went wrong.
        reason: The stable reason code.
        probe: Whether the index was to have been consulted.

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
            "mode": "probe" if probe else "check",
        },
        findings={"declaration": _finding((problem,))},
        verdict={"verdict": str(Verdict.FAILED), "reasons": [reason]},
    )
    (directory / MANIFEST_NAME).write_text(
        render_manifest(document), encoding="utf-8", newline="\n"
    )
    print(f"wheels: {problem}")
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
        if not isinstance(entry, Mapping):
            continue
        print(f"wheels: {name}: {entry.get('verdict')}")
        blocked = entry.get("blocked")
        if isinstance(blocked, list) and blocked:
            print(f"  - would block a free-threaded build: {', '.join(blocked)}")
        problems = entry.get("problems")
        if isinstance(problems, list):
            for problem in problems:
                print(f"  - {problem}")
    print(f"wheels: verdict {verdict}")
    if reasons:
        print(f"wheels: reasons {', '.join(sorted(set(reasons)))}")


def declaration_of(root: Path | None = None) -> Declaration:
    """Read the survey declaration from a tree.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.

    Returns:
        The declaration.

    Raises:
        WheelSurveyError: If it cannot be read or parsed.

    Exposed so that the contract test can assert facts about *this* repository's
    survey without repeating how to find it.
    """
    base = REPO_ROOT if root is None else root
    text = _read(base, CONFIGURATION_FILE)
    if text is None:
        msg = f"{CONFIGURATION_FILE} could not be read"
        raise WheelSurveyError(msg)
    return parse_declaration(text)
