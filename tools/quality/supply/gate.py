"""Running every supply-chain check and reducing them to one verdict.

**The judgement lives in the modules; the sequencing lives here.** Every decision
this file makes is delegated — :func:`~tools.quality.supply.inventory.drift`,
:func:`~tools.quality.supply.sbom.validate`,
:func:`~tools.quality.supply.capability.judge` and the rest each answer one
question from values, offline, and are tested that way. What this module adds is
order, I/O and the arithmetic that turns a set of answers into an exit code.

**Not a second aggregate.** ADR-0042 put the run-level verdict in exactly one
place, and this is not it. The verdict here is about *this gate*, in the same
three-valued :class:`~tools.quality.execution.plan.Verdict` every other gate
uses, and ``tools/quality/workflow`` reads it alongside them. A gate that
declared a run good or bad would be the second answer that ADR exists to prevent.

**Determinism is checked rather than assumed.** The SBOM is built twice, from two
independent traversals of the inventory, and the renderings are compared byte for
byte. Asserting determinism in a docstring costs nothing and proves nothing; the
comparison is what makes the claim falsifiable, and it is cheap.

**Unmeasured is not passed.** An audit that could not run, a waiver register that
could not be dated, a check whose input was missing — each produces
:attr:`~tools.quality.execution.plan.Verdict.UNMEASURED` and exit code
:data:`EXIT_UNMEASURED`, which is not zero. Doubt about what ran casts doubt on
what passed.
"""

import os
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Final

from tools.quality.execution.plan import Verdict, combine
from tools.quality.supply import audit, capability, secrets, waivers
from tools.quality.supply.inventory import (
    PINNED,
    PYPI,
    SupplyChainError,
    collect,
    drift,
    render,
)
from tools.quality.supply.manifest import (
    REASON_ACTION_UNDOCUMENTED,
    REASON_ACTION_UNPINNED,
    REASON_AUDIT_UNMEASURED,
    REASON_AUDIT_VULNERABLE,
    REASON_CAPABILITY_REGRESSED,
    REASON_DOCKER_UNDIGESTED,
    REASON_INVENTORY_DRIFT,
    REASON_SBOM_INVALID,
    REASON_SBOM_NONDETERMINISTIC,
    REASON_SECRET_ALLOWANCE_STALE,
    REASON_SECRET_FOUND,
    REASON_WAIVER_EXPIRED,
)
from tools.quality.supply.manifest import build as build_manifest
from tools.quality.supply.manifest import render as render_manifest
from tools.quality.supply.sbom import SPEC_VERSION, ecosystem_counts
from tools.quality.supply.sbom import build as build_sbom
from tools.quality.supply.sbom import digest as sbom_digest
from tools.quality.supply.sbom import render as render_sbom
from tools.quality.supply.sbom import validate as validate_sbom
from tools.quality.supply.workflows import (
    undigested_docker_references,
    undocumented_pins,
    unpinned_references,
    workflow_paths,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

OUTPUT_DIRECTORY: Final[str] = ".globin/supply"
"""Beside ``.globin/evidence`` and ``.globin/workflow``, under the same ignored
root. Regenerable, so nothing here is committed."""

MANIFEST_NAME: Final[str] = "supply-manifest.json"
SBOM_NAME: Final[str] = "sbom.cyclonedx.json"
INVENTORY_NAME: Final[str] = "dependency-inventory.json"

EXIT_OK: Final[int] = 0
EXIT_GATE_FAILED: Final[int] = 1
EXIT_UNMEASURED: Final[int] = 3
"""The same three codes ``tools/quality/workflow/gate.py`` uses, and for the same
reason: a caller that already knows what ``3`` means from one gate should not
have to learn a second vocabulary for another."""

DEFAULT_REPOSITORY: Final[str] = "aydhn/GLOBIN"
SHA_LENGTH: Final[int] = 40


def _sha() -> str:
    """The commit under test, read without starting a process.

    Returns:
        The forty-character SHA, or ``"unknown"``.

    Read from ``.git`` directly, exactly as ``tools/quality/evidence/gate.py``
    does, so that a manifest can be produced in a tree without Git on the path.
    ``unknown`` is recorded as such rather than invented.
    """
    head = REPO_ROOT / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if not text.startswith("ref:"):
        return text if len(text) == SHA_LENGTH else "unknown"
    reference = REPO_ROOT / ".git" / text.removeprefix("ref:").strip()
    try:
        return reference.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def _committed_on() -> tuple[str, date | None]:
    """When the commit under test was made.

    Returns:
        Its ISO 8601 committer date and the plain date, or ``("", None)`` when
        Git cannot answer.

    This is the only date anything here uses. The wall clock is deliberately
    never read: the SBOM's timestamp, the waiver expiry check and the manifest
    all take their notion of "now" from the tree being judged, so the same commit
    receives the same verdict on any machine on any day.

    A tree without Git yields ``None``, and the waiver check then reports
    :attr:`~tools.quality.execution.plan.Verdict.UNMEASURED` rather than assuming
    nothing has expired.
    """
    try:
        completed = subprocess.run(
            ["git", "show", "-s", "--format=%cI", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            cwd=REPO_ROOT,
        )
    except (OSError, subprocess.SubprocessError):
        return "", None
    stamp = completed.stdout.strip()
    if completed.returncode != 0 or not stamp:
        return "", None
    try:
        return stamp, datetime.fromisoformat(stamp).date()
    except ValueError:
        return stamp, None


def _tracked_files() -> tuple[str, ...]:
    """Every file Git is tracking, as repository-relative POSIX paths.

    Returns:
        The paths, sorted. Empty when Git cannot answer, which the secret scan
        reports as unmeasured rather than as clean.

    Git's own list rather than a directory walk, so that the scan covers exactly
    what a push would publish — no caches, no virtual environment, no
    ``.globin/`` artefacts, and nothing else ``.gitignore`` excludes.
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            cwd=REPO_ROOT,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if completed.returncode != 0:
        return ()
    return tuple(sorted(line for line in completed.stdout.splitlines() if line.strip()))


def _pin_findings() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """What is wrong with the pins, across every workflow in the repository.

    Returns:
        Unpinned references, undocumented pins, and undigested Docker references.

    Every workflow, not only ``quality.yml``. Phase 014 adds a second one, and a
    checker that knew the name of the first would have silently stopped covering
    the repository the moment it did.
    """
    unpinned: list[str] = []
    undocumented: list[str] = []
    undigested: list[str] = []
    for path in workflow_paths(REPO_ROOT):
        text = path.read_text(encoding="utf-8")
        unpinned.extend(unpinned_references(text))
        undocumented.extend(undocumented_pins(text))
        undigested.extend(undigested_docker_references(text))
    return tuple(sorted(unpinned)), tuple(sorted(undocumented)), tuple(sorted(undigested))


def _verdict(problems: object, *, measured: bool = True) -> Verdict:
    """The verdict for one check.

    Args:
        problems: Whatever the check returned. Truthy means it found something.
        measured: Whether the check was able to run at all.

    Returns:
        :attr:`~tools.quality.execution.plan.Verdict.UNMEASURED` when it could
        not run, :attr:`~tools.quality.execution.plan.Verdict.FAILED` when it
        found something, and
        :attr:`~tools.quality.execution.plan.Verdict.PASSED` otherwise.

    The order matters: an unmeasured check that also happens to have found
    nothing is unmeasured, not passed.
    """
    if not measured:
        return Verdict.UNMEASURED
    return Verdict.FAILED if problems else Verdict.PASSED


def run_supply(
    *,
    online: bool = True,
    output: Path | None = None,
    runner: audit.Runner | None = None,
) -> int:
    """Run every supply-chain check, write the artefacts, and report a verdict.

    Args:
        online: Whether the gate may reach the network. When ``False`` **neither**
            the vulnerability audit nor the platform probe runs, and both are
            recorded as unmeasured — which is not a pass, so an offline run can
            never return :data:`EXIT_OK`.
        output: Where to write. Defaults to :data:`OUTPUT_DIRECTORY` under the
            repository root.
        runner: How to start a child, passed through to the audit and the
            probe. Injected only by tests; the default is :func:`subprocess.run`.

    Returns:
        :data:`EXIT_OK`, :data:`EXIT_GATE_FAILED` or :data:`EXIT_UNMEASURED`.

    **One flag for both, and it was two.** The first version disabled only the
    platform probe, which made ``--offline`` a false name: the audit still
    started ``pip-audit``, which resolves against an index and queries an
    advisory service. That went unnoticed because
    [ADR-0024](../../../docs/adr/0024-tests-are-offline-and-isolated-by-construction.md)'s
    guarantee is enforced by refusing sockets *in the test process*, and a child
    process has its own. A suite whose child reaches the network is a suite that
    reaches the network. The two switches are therefore one, and it means what it
    says.
    """
    directory = output or (REPO_ROOT / OUTPUT_DIRECTORY)
    directory.mkdir(parents=True, exist_ok=True)

    commit = _sha()
    timestamp, committed = _committed_on()
    repository = os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY)
    branch = os.environ.get("GITHUB_REF_NAME", "master")

    findings: dict[str, object] = {}
    reasons: list[str] = []
    verdicts: list[Verdict] = []

    # --- the inventory, and whether the three registers agree ---------------
    try:
        dependencies = collect(REPO_ROOT)
        disagreements = drift(dependencies)
        inventory_text = render(dependencies)
        (directory / INVENTORY_NAME).write_text(inventory_text, encoding="utf-8", newline="\n")
        inventory_verdict = _verdict(disagreements)
    except SupplyChainError as fault:
        dependencies, disagreements = (), (str(fault),)
        inventory_text, inventory_verdict = "", Verdict.UNMEASURED
    findings["inventory"] = {
        "verdict": inventory_verdict.value,
        "counts": ecosystem_counts(dependencies),
        "total": len(dependencies),
        "drift": list(disagreements),
    }
    verdicts.append(inventory_verdict)
    if disagreements:
        reasons.append(REASON_INVENTORY_DRIFT)

    # --- what the workflows fetch ------------------------------------------
    unpinned, undocumented, undigested = _pin_findings()
    pins_verdict = _verdict(unpinned or undocumented or undigested)
    findings["action_pins"] = {
        "verdict": pins_verdict.value,
        "unpinned": list(unpinned),
        "undocumented": list(undocumented),
        "undigested_docker": list(undigested),
    }
    verdicts.append(pins_verdict)
    reasons.extend(
        code
        for code, offenders in (
            (REASON_ACTION_UNPINNED, unpinned),
            (REASON_ACTION_UNDOCUMENTED, undocumented),
            (REASON_DOCKER_UNDIGESTED, undigested),
        )
        if offenders
    )

    # --- the SBOM, built twice so determinism is checked rather than claimed -
    sbom_problems, digest_value = _write_sbom(
        directory, dependencies, repository, commit, timestamp, reasons
    )
    sbom_verdict = _verdict(sbom_problems, measured=bool(dependencies))
    findings["sbom"] = {
        "verdict": sbom_verdict.value,
        "path": f"{OUTPUT_DIRECTORY}/{SBOM_NAME}",
        "spec_version": SPEC_VERSION,
        "digest": digest_value,
        "problems": list(sbom_problems),
    }
    verdicts.append(sbom_verdict)

    # --- waivers, dated against the commit rather than the clock ------------
    try:
        register = waivers.load(REPO_ROOT)
        stale = waivers.expired(register, on=committed) if committed else ()
        waiver_verdict = _verdict(stale, measured=committed is not None)
        waiver_detail = [f"{w.vulnerability} ({w.package}) expired {w.expires}" for w in stale]
    except SupplyChainError as fault:
        register, waiver_verdict, waiver_detail = (), Verdict.FAILED, [str(fault)]
    findings["waivers"] = {
        "verdict": waiver_verdict.value,
        "total": len(register),
        "expired": len(waiver_detail),
        "detail": waiver_detail,
    }
    verdicts.append(waiver_verdict)
    if waiver_detail:
        reasons.append(REASON_WAIVER_EXPIRED)

    # --- the vulnerability audit -------------------------------------------
    # Against the inventory's own pinned distributions, so that the audit, the
    # SBOM and the manifest all describe one set rather than three.
    pinned = tuple(
        (entry.name, entry.version)
        for entry in dependencies
        if entry.ecosystem == PYPI and entry.resolution == PINNED
    )
    report = (
        audit.run(pinned, register, runner=runner)
        if online
        else audit.Report(
            outcome=audit.Outcome.TOOL_MISSING,
            detail="the gate was asked not to reach the network, so no audit was performed",
        )
    )
    audit_verdict = (
        Verdict.UNMEASURED
        if not report.measured
        else (Verdict.FAILED if report.open_count else Verdict.PASSED)
    )
    findings["vulnerability_audit"] = {
        "verdict": audit_verdict.value,
        "outcome": report.outcome.value,
        "audited": report.audited,
        "open": report.open_count,
        "waived": len(report.vulnerabilities) - report.open_count,
        "detail": report.detail,
        "findings": [entry.as_document() for entry in report.vulnerabilities],
    }
    verdicts.append(audit_verdict)
    if not report.measured:
        reasons.append(REASON_AUDIT_UNMEASURED)
    elif report.open_count:
        reasons.append(REASON_AUDIT_VULNERABLE)

    # --- secrets, by content, reported as fingerprints ----------------------
    tracked = _tracked_files()
    leaks: list[secrets.Finding] = []
    for path in tracked:
        if not secrets.scannable(path):
            continue
        try:
            text = (REPO_ROOT / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        leaks.extend(secrets.scan_text(path, text))
    stale_allowances = secrets.unused_allowances(frozenset(tracked))
    secrets_verdict = _verdict(leaks or stale_allowances, measured=bool(tracked))
    findings["secret_hygiene"] = {
        "verdict": secrets_verdict.value,
        "scanned": len(tracked),
        "findings": [entry.as_document() for entry in sorted(leaks)],
        "stale_allowances": list(stale_allowances),
    }
    verdicts.append(secrets_verdict)
    if leaks:
        reasons.append(REASON_SECRET_FOUND)
    if stale_allowances:
        reasons.append(REASON_SECRET_ALLOWANCE_STALE)

    # --- what the platform says --------------------------------------------
    states = (
        capability.probe(repository, runner=runner)
        if online
        else {
            control.name: (
                capability.State.NOT_PROBED,
                "the gate was asked not to reach the network",
            )
            for control in capability.CONTROLS
        }
    )
    regressions = capability.judge(states)
    verdicts.append(_verdict(regressions))
    if regressions:
        reasons.append(REASON_CAPABILITY_REGRESSED)

    overall = combine(verdicts)
    document = build_manifest(
        run={
            "commit": commit,
            "committed": timestamp,
            "repository": repository,
            "branch": branch,
            "cyclonedx_spec_version": SPEC_VERSION,
        },
        findings=findings,
        capability={
            name: {"state": state.value, "reason": reason}
            for name, (state, reason) in sorted(states.items())
        },
        verdict={"overall": overall.value, "reasons": sorted(set(reasons))},
    )
    (directory / MANIFEST_NAME).write_text(
        render_manifest(document), encoding="utf-8", newline="\n"
    )

    _summarise(findings, states, regressions, overall)
    if overall is Verdict.PASSED:
        return EXIT_OK
    return EXIT_GATE_FAILED if overall is Verdict.FAILED else EXIT_UNMEASURED


def _write_sbom(
    directory: Path,
    dependencies: tuple[object, ...],
    repository: str,
    commit: str,
    timestamp: str,
    reasons: list[str],
) -> tuple[tuple[str, ...], str]:
    """Build the SBOM twice, compare the renderings, write one, and validate it.

    Args:
        directory: Where to write.
        dependencies: The collected inventory.
        repository: The canonical ``owner/name``.
        commit: The commit being described.
        timestamp: Its committer date.
        reasons: The reason-code list, appended to in place when something is wrong.

    Returns:
        The validation problems and the document's digest.

    Two builds rather than one because determinism is the property this document
    is bought for. Building once and asserting the result is stable would be
    asserting exactly what has not been checked; building twice and comparing
    bytes turns the claim into a test that runs on every invocation.
    """
    if not dependencies:
        return ("the inventory is empty, so no SBOM was produced",), ""

    arguments = {
        "repository": repository,
        "commit": commit,
        "timestamp": timestamp,
        "project": "globin",
        "project_version": _project_version(),
        "generator_version": _project_version(),
    }
    first = build_sbom(dependencies, **arguments)  # type: ignore[arg-type]
    second = build_sbom(dependencies, **arguments)  # type: ignore[arg-type]

    problems = list(validate_sbom(first))
    if problems:
        reasons.append(REASON_SBOM_INVALID)
    if render_sbom(first) != render_sbom(second):
        problems.append(
            "two builds of the SBOM over one unchanged inventory produced different "
            "bytes, so its digest is not evidence of anything"
        )
        reasons.append(REASON_SBOM_NONDETERMINISTIC)

    (directory / SBOM_NAME).write_text(render_sbom(first), encoding="utf-8", newline="\n")
    return tuple(problems), sbom_digest(first)


def _project_version() -> str:
    """The version GLOBIN declares for itself.

    Returns:
        The value of ``__version__``, or ``"unknown"``.

    Read as text rather than by importing ``globin``, because this tooling does
    not import the package it measures — ``tools`` and ``src`` are separate
    import roots and a gate that needed the package on the path would fail in the
    one situation it exists to report on.
    """
    path = REPO_ROOT / "src" / "globin" / "__init__.py"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("__version__"):
                return line.partition("=")[2].strip().strip('"').strip("'")
    except OSError:
        return "unknown"
    return "unknown"


def _summarise(
    findings: dict[str, object],
    states: dict[str, tuple[capability.State, str]],
    regressions: tuple[str, ...],
    overall: Verdict,
) -> None:
    """Print what the gate established.

    Args:
        findings: Each check and its verdict.
        states: Each platform control and its state.
        regressions: Controls that policy requires and that are off.
        overall: The combined verdict.

    ASCII only, for the reason ``tools/quality/execution/gate.py`` gives: a
    Windows console in a non-UTF-8 codepage turns a tick into a traceback, and a
    gate that crashes while reporting success is worse than one that prints
    plainly.
    """
    print("[supply] checks:")
    for name in sorted(findings):
        entry = findings[name]
        verdict = entry.get("verdict") if isinstance(entry, dict) else "?"
        print(f"  {name:22} {verdict}")

    print("[supply] platform capability:")
    for name, (state, reason) in sorted(states.items()):
        print(f"  {name:38} {state.value:26} {reason[:60]}")

    for problem in regressions:
        print(f"[supply] REGRESSION: {problem}")
    print(f"[supply] overall: {overall.value.upper()}")
