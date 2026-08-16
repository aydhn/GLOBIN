"""Running ``pip-audit``, and refusing to read its silence as good news.

**The failure this module exists to prevent.** A vulnerability scanner has three
possible outcomes and two of them look alike from a distance: it found nothing,
it could not look, and it found something. A wrapper that checks only the exit
code — or worse, one written as ``pip-audit || true`` — reports the first two
identically. The repository would then pass its supply-chain gate on a day the
advisory service was down, and nobody would know the difference until the day it
mattered.

So every non-finding outcome here becomes an explicit :class:`Outcome` that is
not :attr:`Outcome.CLEAN`, and the gate treats each as a failure. A scan that did
not happen is a scan that did not happen.

**No ``--fix``, ever.** ``pip-audit`` can upgrade what it finds. Choosing a
version is the review process this phase is *building* — ``docs/DEPENDENCY_POLICY.md``
— and a tool that quietly performs that review while running a check would be
making the decision the process exists to make.

**``--strict``, so an unauditable dependency is an error.** Without it a package
whose version cannot be determined is skipped, and skipped packages are counted
as fine. That is the same conflation in a smaller box.
"""

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.quality.supply.waivers import OPEN, WAIVED, Waiver

Runner = Callable[..., subprocess.CompletedProcess[str]]
"""How a child is started.

Injected rather than called directly so the gate can be composed and tested
without a network — the pattern ``tools/quality/evidence`` established and
``test_evidence_end_to_end.py`` describes as "the gate composed with an
injected process runner". The default is the real thing, so no caller outside
a test ever passes one.
"""

TOOL: Final[str] = "pip-audit"

NO_VULNERABILITIES: Final[int] = 0
VULNERABILITIES_FOUND: Final[int] = 1
"""The two exit codes ``pip-audit`` documents. Anything else is a fault in the
tool or in what it was asked to do, and is classified as such rather than as a
verdict about this repository."""

DEFAULT_TIMEOUT: Final[int] = 300
"""Five minutes. The audit resolves dependencies against an index and queries an
advisory service, both of which are network calls on a runner with a cold cache.
Bounded anyway, because a wedged network read is the failure a timeout exists for.
"""


class Outcome(StrEnum):
    """What running the audit established."""

    CLEAN = "clean"
    """It ran, and found nothing."""

    VULNERABLE = "vulnerable"
    """It ran, and found something."""

    TOOL_MISSING = "tool-missing"
    """``pip-audit`` is not installed. Not a pass: the audit did not happen."""

    COLLECTION_FAILED = "collection-failed"
    """It could not determine what to audit."""

    SERVICE_UNREACHABLE = "service-unreachable"
    """It could not reach the advisory data."""

    UNREADABLE = "unreadable"
    """It produced output this reader cannot parse. Reported rather than guessed
    at, because guessing would mean choosing between "clean" and "vulnerable"
    with no evidence for either."""


#: Substrings that identify a network or advisory-service failure in ``pip-audit``'s
#: diagnostics. Matched so that "the internet was down" is not filed under "your
#: dependencies could not be collected", which would send somebody looking in the
#: wrong place.
SERVICE_MARKERS: Final[tuple[str, ...]] = (
    "connection",
    "timed out",
    "timeout",
    "temporary failure in name resolution",
    "max retries exceeded",
    "service unavailable",
    "certificate",
)


@dataclass(frozen=True, slots=True, order=True)
class Vulnerability:
    """One advisory against one installed package.

    Args:
        package: The distribution name.
        version: The version installed when the audit ran.
        identifier: The advisory identifier, such as a GHSA or PYSEC.
        fix_versions: Versions the advisory says resolve it, in order.
        disposition: :data:`~tools.quality.supply.waivers.OPEN` or
            :data:`~tools.quality.supply.waivers.WAIVED`. A waived finding is
            still a finding, and still appears in the report.
        waiver_owner: Who accepted it, empty when it is open.
    """

    package: str
    version: str
    identifier: str
    fix_versions: tuple[str, ...] = ()
    disposition: str = OPEN
    waiver_owner: str = ""

    def as_document(self) -> dict[str, object]:
        """This finding as JSON-ready values.

        Returns:
            The mapping, sorted by the renderer rather than here.
        """
        return {
            "package": self.package,
            "version": self.version,
            "identifier": self.identifier,
            "fix_versions": list(self.fix_versions),
            "disposition": self.disposition,
            "waiver_owner": self.waiver_owner,
        }


@dataclass(frozen=True, slots=True)
class Report:
    """What one audit run established.

    Args:
        outcome: Which of the six things happened.
        vulnerabilities: Every finding, ordered, waived ones included.
        detail: What went wrong, when something did.
        audited: How many distributions were examined.
    """

    outcome: Outcome
    vulnerabilities: tuple[Vulnerability, ...] = ()
    detail: str = ""
    audited: int = 0

    @property
    def open_count(self) -> int:
        """Findings nobody has accepted.

        Returns:
            The number whose disposition is :data:`~tools.quality.supply.waivers.OPEN`.
            This is the number that fails the gate; the total is not, because a
            waived finding has already been decided about.
        """
        return sum(1 for entry in self.vulnerabilities if entry.disposition == OPEN)

    @property
    def measured(self) -> bool:
        """Whether the audit actually happened.

        Returns:
            ``True`` only for :attr:`Outcome.CLEAN` and :attr:`Outcome.VULNERABLE`.
            Every other outcome means the question was not answered, and the gate
            reads that as a failure rather than as an absence of findings.
        """
        return self.outcome in {Outcome.CLEAN, Outcome.VULNERABLE}


def available() -> bool:
    """Whether ``pip-audit`` is installed.

    Returns:
        ``True`` when it is importable as a module. Checked by module rather than
        by executable name for the reason ``tools/quality/commands.py`` gives: the
        gate launches it as ``python -m pip_audit``, so what matters is whether
        *this* interpreter can find it, not whether some ``pip-audit.exe`` is on
        the path.
    """
    return shutil.which(TOOL) is not None or _importable()


def _importable() -> bool:
    """Whether ``pip_audit`` can be imported by the running interpreter.

    Returns:
        ``True`` when the module is present.
    """
    from importlib.util import find_spec

    try:
        return find_spec("pip_audit") is not None
    except (ImportError, ValueError):
        return False


def parse(payload: str, waivers: tuple[Waiver, ...]) -> tuple[Vulnerability, ...]:
    """Turn ``pip-audit``'s JSON into findings, applying the waiver register.

    Args:
        payload: The tool's ``--format=json`` output.
        waivers: The loaded register.

    Returns:
        Every advisory against every package, ordered, each marked open or waived.

    Raises:
        ValueError: If the payload is not the shape ``pip-audit`` documents.
            Raised rather than returning nothing, because "no findings" and
            "unparseable" must not produce the same value.

    A waiver changes only the disposition. The finding, its identifier and the
    version it was found against all survive into the report, so that a reader
    six months later can see what was accepted rather than only what was left.
    """
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as fault:
        msg = f"{TOOL} produced output that is not JSON: {fault}"
        raise ValueError(msg) from fault

    if not isinstance(document, dict) or not isinstance(document.get("dependencies"), list):
        msg = f"{TOOL} produced JSON without a 'dependencies' array"
        # ValueError rather than TypeError: every caller catches ValueError to keep
        # "unparseable" from collapsing into "no findings", and a TypeError would
        # escape that handler and be reported as a crash instead of an outcome.
        raise ValueError(msg)  # noqa: TRY004

    found: list[Vulnerability] = []
    for dependency in document["dependencies"]:
        if not isinstance(dependency, dict):
            continue
        name, version = str(dependency.get("name", "")), str(dependency.get("version", ""))
        for advisory in dependency.get("vulns", []) or []:
            if not isinstance(advisory, dict):
                continue
            identifier = str(advisory.get("id", ""))
            covering = next((w for w in waivers if w.covers(identifier, name)), None)
            found.append(
                Vulnerability(
                    package=name,
                    version=version,
                    identifier=identifier,
                    fix_versions=tuple(str(fix) for fix in advisory.get("fix_versions", []) or []),
                    disposition=WAIVED if covering else OPEN,
                    waiver_owner=covering.owner if covering else "",
                )
            )
    return tuple(sorted(found))


def classify_failure(exit_code: int, stderr: str) -> tuple[Outcome, str]:
    """Why an audit that did not produce findings did not produce them.

    Args:
        exit_code: What the tool returned.
        stderr: What it said.

    Returns:
        The outcome and the detail to record.

    Separated from the running so it can be tested from literals. Every branch
    here returns something that is not :attr:`Outcome.CLEAN`, which is the
    property worth asserting: there is no path through this function that turns a
    failure into a pass.
    """
    lowered = stderr.lower()
    if any(marker in lowered for marker in SERVICE_MARKERS):
        return Outcome.SERVICE_UNREACHABLE, (
            f"{TOOL} exited {exit_code} and could not reach the advisory service. "
            f"This is NOT a clean audit: {stderr.strip()[:200]}"
        )
    return Outcome.COLLECTION_FAILED, (
        f"{TOOL} exited {exit_code} without a usable result. "
        f"This is NOT a clean audit: {stderr.strip()[:200]}"
    )


def run(
    project: Path,
    waivers: tuple[Waiver, ...],
    *,
    timeout: int = DEFAULT_TIMEOUT,
    runner: Runner | None = None,
) -> Report:
    """Audit the dependency set this repository has locked.

    Args:
        project: The repository root, which is where ``pip-audit`` looks for
            ``pylock.toml`` and ``pylock.*.toml``.
        waivers: The loaded waiver register.
        timeout: Seconds allowed.
        runner: How to start the child. Injected so the gate can be composed and
            tested without a network; the default is :func:`subprocess.run`.

    Returns:
        The report. Never raises for an audit failure — the failure is the
        report's :attr:`Report.outcome`, so that the gate records what happened
        rather than losing it to a traceback.

    **The lock, not the ambient environment and no longer a synthesised
    requirements file.** Auditing what happens to be installed sounds equivalent
    and is not: on a developer's machine the user-level site-packages contains
    whatever else that person works on, and ``--strict`` correctly refuses to audit
    a package that is not on any index.

    Until Phase 020 this audited a requirements file written from the inventory's
    exact pins, and let ``pip-audit`` resolve it. That was the best available then
    and it had a real defect: the resolution happened *at audit time*, against a
    live index, so the report described a set nobody had installed and which could
    differ between two runs on the same commit. ``--locked`` resolves nothing. It
    reads names and versions straight out of ``pylock.dev.toml``, which is the file
    ``scripts/bootstrap.ps1`` installs from — so the audited set and the installed
    set are now the same set, byte for byte.

    Every lock in the directory is picked up, so the runtime lock Phase 021 adds is
    audited with no change here.

    **Not called by the test suite.** It starts a process and reaches the network;
    ADR-0024 makes the suite offline. :func:`parse` and :func:`classify_failure`
    carry all the judgement and are tested from literals.
    """
    if runner is None and not available():
        return Report(
            outcome=Outcome.TOOL_MISSING,
            detail=f"{TOOL} is not installed, so no audit was performed",
        )

    try:
        completed = (runner or subprocess.run)(
            [
                sys.executable,
                "-m",
                "pip_audit",
                "--locked",
                str(project),
                "--format=json",
                "--strict",
                "--progress-spinner=off",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Report(
            outcome=Outcome.SERVICE_UNREACHABLE,
            detail=f"{TOOL} did not finish within {timeout}s. This is NOT a clean audit",
        )
    except OSError as fault:
        return Report(outcome=Outcome.TOOL_MISSING, detail=f"{TOOL} could not be started: {fault}")

    if completed.returncode not in {NO_VULNERABILITIES, VULNERABILITIES_FOUND}:
        outcome, detail = classify_failure(completed.returncode, completed.stderr)
        return Report(outcome=outcome, detail=detail)

    try:
        vulnerabilities = parse(completed.stdout, waivers)
        audited = len(json.loads(completed.stdout).get("dependencies", []))
    except ValueError as fault:
        # Exit code 1 means "vulnerabilities found" *or*, under `--strict`, "a
        # dependency could not be audited" — and the second prints nothing to
        # stdout. Reading an unparseable result as a finding count would report
        # zero vulnerabilities from a run that never examined anything.
        outcome, detail = classify_failure(completed.returncode, completed.stderr or str(fault))
        return Report(outcome=outcome, detail=detail)

    outcome = Outcome.VULNERABLE if vulnerabilities else Outcome.CLEAN
    return Report(outcome=outcome, vulnerabilities=vulnerabilities, audited=audited)
