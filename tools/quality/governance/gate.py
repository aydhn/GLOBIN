"""Running every governance check and reducing them to one verdict.

**The judgement lives in :mod:`tools.quality.governance.plan`; the sequencing
lives here.** Every decision this file makes is delegated to a pure function
tested from literals. What this module adds is order, I/O, and the arithmetic
that turns a set of answers into an exit code — the same division
``tools/quality/supply/gate.py`` uses.

**Offline, entirely.** Nothing here reaches the network, so the whole gate runs
on an aeroplane and so do its tests. The half of governance that *is* a platform
question — whether private vulnerability reporting is switched on, whether the
ruleset exists — belongs to the supply-chain gate's capability probe, which
already has the credential and the network for it. Splitting it that way keeps
one probe rather than two and keeps this gate testable without either.

**Not a second aggregate.** ADR-0042 put the run-level verdict in exactly one
place, and this is not it. The verdict here is about *this gate*, in the same
three-valued :class:`~tools.quality.execution.plan.Verdict` every other gate
uses.

**Determinism is checked rather than assumed.** The manifest is built twice and
the renderings compared byte for byte, exactly as the SBOM is. Asserting
determinism in a docstring costs nothing and proves nothing.
"""

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from tools.quality.evidence.redaction import describe as describe_findings
from tools.quality.evidence.redaction import scan as scan_for_secrets
from tools.quality.execution.plan import Verdict, combine
from tools.quality.governance.manifest import (
    REASON_CODEOWNERS_DUPLICATE,
    REASON_CODEOWNERS_UNPARSEABLE,
    REASON_DECLARATION_UNREADABLE,
    REASON_FILE_MISSING,
    REASON_MANIFEST_LEAKAGE,
    REASON_MANIFEST_NONDETERMINISTIC,
    REASON_PATH_UNCOVERED,
    REASON_PATTERN_UNMATCHED,
    REASON_POLICY_INCOMPLETE,
    REASON_PUBLIC_SOLICITATION,
    REASON_REPORTING_CHANNEL_DRIFT,
    REASON_SENSITIVE_PATH_ABSENT,
    REASON_TEMPLATE_INCOMPLETE,
)
from tools.quality.governance.manifest import build as build_manifest
from tools.quality.governance.manifest import render as render_manifest
from tools.quality.governance.plan import (
    CONFIGURATION_FILE,
    Declaration,
    GovernanceError,
    Rule,
    duplicate_codeowners,
    is_catch_all,
    missing_sections,
    ownerless,
    parse_codeowners,
    parse_declaration,
    solicits_vulnerability_detail,
    uncovered_sensitive_paths,
    unmatched_patterns,
)
from tools.quality.workflow.plan import WorkflowError, load_configuration

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

OUTPUT_DIRECTORY: Final[str] = ".globin/governance"
"""Beside ``.globin/supply``, ``.globin/evidence`` and ``.globin/workflow``, under
the same ignored root. Regenerable, so nothing here is committed."""

MANIFEST_NAME: Final[str] = "governance-manifest.json"

WORKFLOW_DIRECTORY: Final[str] = ".github/workflows"
"""Every file under here must be specifically owned. Adding a workflow is the
single most security-relevant change anybody makes in this repository, and
nothing else notices when one arrives unclaimed."""

EXIT_OK: Final[int] = 0
EXIT_GATE_FAILED: Final[int] = 1
EXIT_UNMEASURED: Final[int] = 3
"""The same three codes every other gate here uses, so that a caller who knows
what ``3`` means from one does not have to learn a second vocabulary."""

DEFAULT_REPOSITORY: Final[str] = "aydhn/GLOBIN"
SHA_LENGTH: Final[int] = 40

Lister = Callable[[Path], tuple[str, ...]]
"""How the gate discovers what is in the tree.

Injected for the reason :mod:`tools.quality.supply.audit` gives about its runner:
the default starts ``git``, and a child process has its own view of the world.
A test that could only run against this repository's real tree would be a test
that cannot describe a broken arrangement.
"""


def tracked_paths(root: Path) -> tuple[str, ...]:
    """Every file Git is tracking, as repository-relative POSIX paths.

    Args:
        root: The repository root.

    Returns:
        The paths, sorted. Empty when Git cannot answer, which the caller reports
        as unmeasured rather than as clean.

    Git's own list rather than a directory walk, so that coverage is judged over
    exactly what a push would publish — no caches, no virtual environment, no
    ``.globin/`` artefacts, and nothing else ``.gitignore`` excludes.

    ``--others --exclude-standard`` is included alongside the cached list because
    ``DEFINITION_OF_DONE.md`` requires the gate to run *before* staging: a check
    restricted to already-tracked files would be blind to exactly the files the
    current phase just wrote. ``tests/support.py`` reaches the same conclusion for
    the same reason.
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            cwd=root,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if completed.returncode != 0:
        return ()
    return tuple(sorted({line for line in completed.stdout.splitlines() if line.strip()}))


def with_directories(paths: Sequence[str]) -> tuple[str, ...]:
    """Every path, plus each directory prefix, so a directory pattern can match one.

    Args:
        paths: Repository-relative file paths.

    Returns:
        The files and every containing directory, each ending in ``/``, sorted.

    A CODEOWNERS pattern such as ``/tools/`` names a directory, and asking
    whether it matches any *file* would answer a different question from the one
    the declaration asks. Both spellings are therefore present.
    """
    known: set[str] = set(paths)
    for path in paths:
        parts = path.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            known.add("/".join(parts[:depth]) + "/")
    return tuple(sorted(known))


def _sha(root: Path) -> str:
    """The commit under test, read without starting a process.

    Args:
        root: The repository root.

    Returns:
        The forty-character SHA, or ``"unknown"``.

    Read from ``.git`` directly, exactly as ``tools/quality/supply/gate.py`` does,
    so that a manifest can be produced in a tree without Git on the path.
    ``unknown`` is recorded as such rather than invented.
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


def _missing_files(root: Path, declaration: Declaration) -> tuple[str, ...]:
    """Report declared governing files that do not exist.

    Args:
        root: The repository root.
        declaration: The declaration.

    Returns:
        One sentence per missing file.
    """
    return tuple(
        f"{relative!r} is declared in {CONFIGURATION_FILE} and does not exist"
        for relative in declaration.locations.required_files()
        if not (root / relative).is_file()
    )


def _absent_sensitive(root: Path, declaration: Declaration) -> tuple[str, ...]:
    """Report declared sensitive paths that no longer exist.

    Args:
        root: The repository root.
        declaration: The declaration.

    Returns:
        One sentence per absent path.

    This is the drift that decays most quietly. An entry describing a path that
    has been renamed reads as coverage and provides none, and nothing else in the
    repository would notice.
    """
    problems: list[str] = []
    for entry in sorted(declaration.sensitive_paths):
        target = root / entry.path.rstrip("/")
        exists = target.is_dir() if entry.path.endswith("/") else target.is_file()
        if not exists:
            problems.append(
                f"{entry.path!r} is declared security-sensitive and does not exist; "
                f"either it moved, or the declaration is describing a tree that has changed"
            )
    return tuple(problems)


def _template_problems(root: Path, declaration: Declaration) -> tuple[str, ...]:
    """Report a public issue template that solicits vulnerability detail.

    Args:
        root: The repository root.
        declaration: The declaration.

    Returns:
        One sentence per problem.

    This is the check the whole issue-template arrangement exists for.
    """
    directory = root / declaration.locations.issue_templates.rstrip("/")
    if not directory.is_dir():
        return (f"{declaration.locations.issue_templates!r} does not exist",)
    config = Path(declaration.locations.issue_template_config).name
    problems: list[str] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name == config:
            continue
        text = _read(root, f"{declaration.locations.issue_templates.rstrip('/')}/{path.name}")
        if text is None:
            problems.append(f"{path.name!r} could not be read")
            continue
        problems.extend(solicits_vulnerability_detail(path.name, text))
    return tuple(problems)


def _channel_problems(root: Path, declaration: Declaration) -> tuple[str, ...]:
    """Report disagreement about where a vulnerability is reported.

    Args:
        root: The repository root.
        declaration: The declaration.

    Returns:
        One sentence per document that does not name the declared channel.

    Three files must agree: the declaration names the channel, ``SECURITY.md``
    tells a reporter to use it, and the issue chooser links to it. Two of the
    three agreeing is the failure worth catching — a policy pointing one way and
    a chooser pointing another sends half the reports somewhere public, and
    neither file looks wrong on its own.
    """
    url = declaration.reporting_url
    problems: list[str] = []
    for relative in (
        declaration.locations.security_policy,
        declaration.locations.issue_template_config,
    ):
        text = _read(root, relative)
        if text is None:
            problems.append(f"{relative!r} could not be read, so the reporting channel is unknown")
        elif url not in text:
            problems.append(
                f"{relative!r} does not name the declared reporting channel {url!r}, "
                f"so a reporter following it would arrive somewhere else"
            )
    return tuple(problems)


def _ownership(root: Path, declaration: Declaration) -> tuple[dict[str, object], tuple[Rule, ...]]:
    """Everything the manifest records about who owns what, and the rules behind it.

    Args:
        root: The repository root.
        declaration: The declaration.

    Returns:
        The ownership section and the parsed rules. Both, because the caller
        needs the rules for the coverage checks and parsing twice would be two
        chances to disagree.

    Raises:
        GovernanceError: If the code-owners file cannot be parsed.
    """
    text = _read(root, declaration.locations.codeowners) or ""
    rules = parse_codeowners(text)
    section: dict[str, object] = {
        "location": declaration.locations.codeowners,
        "rules": [
            {
                "pattern": rule.pattern,
                "owners": list(rule.owners),
                "catch_all": is_catch_all(rule.pattern),
            }
            for rule in rules
        ],
        "owners": sorted({owner for rule in rules for owner in rule.owners}),
        "specific_patterns": sum(1 for rule in rules if not is_catch_all(rule.pattern)),
        # The inventory itself, not merely its length. A manifest recording that
        # nineteen paths are sensitive, without saying which, is a number rather
        # than evidence — and the reasons are the part a reader six months from
        # now actually needs.
        "sensitive": [
            {"path": entry.path, "category": entry.category, "reason": entry.reason}
            for entry in sorted(declaration.sensitive_paths)
        ],
    }
    return section, rules


def _capability(declaration: Declaration) -> dict[str, object]:
    """The controls decided by a written argument rather than by a setting.

    Args:
        declaration: The declaration.

    Returns:
        Each control's state, the document that decided it, and the reason.

    Recorded rather than omitted, per ADR-0045. An absent key and a recorded
    ``NOT_APPLICABLE`` read very differently six months later, and only one of
    them says anything.
    """
    return {
        entry.name: {
            "state": entry.state,
            "authority": entry.authority,
            "reason": entry.reason,
        }
        for entry in sorted(declaration.declared_capabilities)
    }


def run_governance(
    *, root: Path | None = None, reports: Path | None = None, lister: Lister | None = None
) -> int:
    """Check the governance arrangement against the tree and write the manifest.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.
        reports: Where to write. Defaults to :data:`OUTPUT_DIRECTORY` under root.
        lister: How to discover what is in the tree. Defaults to
            :func:`tracked_paths`.

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
    except GovernanceError as fault:
        return _fail_early(directory, base, str(fault), REASON_DECLARATION_UNREADABLE)

    paths = (lister or tracked_paths)(base)
    known = with_directories(paths)

    missing = _missing_files(base, declaration)
    findings["required_files"] = _finding(missing)
    if missing:
        reasons.append(REASON_FILE_MISSING)

    present = [
        candidate
        for candidate in declaration.locations.codeowners_candidates
        if (base / candidate).is_file()
    ]
    duplicates = duplicate_codeowners(present, authoritative=declaration.locations.codeowners)
    findings["codeowners_location"] = _finding(duplicates)
    if duplicates:
        reasons.append(REASON_CODEOWNERS_DUPLICATE)

    rules: tuple[Rule, ...] = ()
    ownership: dict[str, object] = {"location": declaration.locations.codeowners, "rules": []}
    try:
        ownership, rules = _ownership(base, declaration)
    except GovernanceError as fault:
        findings["codeowners_syntax"] = _finding((str(fault),))
        reasons.append(REASON_CODEOWNERS_UNPARSEABLE)
    else:
        findings["codeowners_syntax"] = _finding(())

    uncovered = uncovered_sensitive_paths(declaration.sensitive_paths, rules)
    workflows = [path for path in paths if path.startswith(f"{WORKFLOW_DIRECTORY}/")]
    uncovered = (*uncovered, *ownerless(workflows, rules))
    findings["ownership_coverage"] = _finding(uncovered, measured=bool(paths))
    if uncovered:
        reasons.append(REASON_PATH_UNCOVERED)

    unmatched = unmatched_patterns(rules, known) if paths else ()
    findings["pattern_reachability"] = _finding(unmatched, measured=bool(paths))
    if unmatched:
        reasons.append(REASON_PATTERN_UNMATCHED)

    absent = _absent_sensitive(base, declaration)
    findings["sensitive_paths"] = _finding(absent)
    if absent:
        reasons.append(REASON_SENSITIVE_PATH_ABSENT)

    policy_text = _read(base, declaration.locations.security_policy)
    policy_gaps = (
        tuple(
            f"{declaration.locations.security_policy} is missing the section {heading!r}"
            for heading in missing_sections(policy_text, declaration.security_policy_sections)
        )
        if policy_text is not None
        else (f"{declaration.locations.security_policy!r} could not be read",)
    )
    findings["security_policy"] = _finding(policy_gaps)
    if policy_gaps:
        reasons.append(REASON_POLICY_INCOMPLETE)

    template_text = _read(base, declaration.locations.pull_request_template)
    template_gaps = (
        tuple(
            f"{declaration.locations.pull_request_template} is missing the section {heading!r}"
            for heading in missing_sections(template_text, declaration.pull_request_sections)
        )
        if template_text is not None
        else (f"{declaration.locations.pull_request_template!r} could not be read",)
    )
    findings["pull_request_template"] = _finding(template_gaps)
    if template_gaps:
        reasons.append(REASON_TEMPLATE_INCOMPLETE)

    solicitation = _template_problems(base, declaration)
    findings["issue_templates"] = _finding(solicitation)
    if solicitation:
        reasons.append(REASON_PUBLIC_SOLICITATION)

    channel = _channel_problems(base, declaration)
    findings["reporting_channel"] = _finding(channel)
    if channel:
        reasons.append(REASON_REPORTING_CHANNEL_DRIFT)

    run: dict[str, object] = {
        "repository": DEFAULT_REPOSITORY,
        "commit": _sha(base),
        "declaration": CONFIGURATION_FILE,
        "required_check": _required_check(base),
        "tracked_paths": len(paths),
        "extension_points": [
            {"pattern": entry.pattern, "phase": entry.phase, "reason": entry.reason}
            for entry in sorted(declaration.extension_points)
        ],
    }

    verdict = combine([_verdict_of(entry) for entry in findings.values()])
    document = build_manifest(
        run=run,
        ownership=ownership,
        findings=findings,
        capability=_capability(declaration),
        verdict={"verdict": str(verdict), "reasons": sorted(set(reasons))},
    )

    rendered = render_manifest(document)
    again = render_manifest(
        build_manifest(
            run=run,
            ownership=ownership,
            findings=findings,
            capability=_capability(declaration),
            verdict={"verdict": str(verdict), "reasons": sorted(set(reasons))},
        )
    )
    if rendered != again:
        reasons.append(REASON_MANIFEST_NONDETERMINISTIC)
        verdict = Verdict.FAILED

    leaks = scan_for_secrets(MANIFEST_NAME, rendered)
    if leaks:
        reasons.append(REASON_MANIFEST_LEAKAGE)
        verdict = Verdict.FAILED
        print("governance: the manifest carries something it must not:")
        print(describe_findings(leaks))

    if REASON_MANIFEST_NONDETERMINISTIC in reasons or REASON_MANIFEST_LEAKAGE in reasons:
        document = build_manifest(
            run=run,
            ownership=ownership,
            findings=findings,
            capability=_capability(declaration),
            verdict={"verdict": str(verdict), "reasons": sorted(set(reasons))},
        )
        rendered = render_manifest(document)

    (directory / MANIFEST_NAME).write_text(rendered, encoding="utf-8", newline="\n")
    _report(findings, verdict, reasons)
    return _exit_code(verdict)


def _required_check(root: Path) -> str:
    """The check name a repository administrator marks as required.

    Args:
        root: The repository root.

    Returns:
        The declared name, or ``"unknown"`` when the settings file cannot be
        read.

    Read from ``[tool.globin.workflow] required_check`` rather than carried as a
    copy here. A second copy is how a rename leaves a stale name behind in a file
    nobody thought to look at.
    """
    try:
        return load_configuration(root).required_check
    except WorkflowError:
        return "unknown"


def _verdict_of(entry: object) -> Verdict:
    """Read one finding's verdict back out of the manifest entry.

    Args:
        entry: The finding.

    Returns:
        Its verdict, defaulting to unmeasured for anything unrecognised.
    """
    if isinstance(entry, dict):
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
    """Write a manifest recording that the gate could not read its own input.

    Args:
        directory: Where to write.
        root: The repository root.
        problem: What went wrong.
        reason: The stable reason code.

    Returns:
        :data:`EXIT_GATE_FAILED`.

    A manifest is still written. A gate that failed silently and left no
    artefact would be indistinguishable, to anything reading the evidence
    afterwards, from a gate that never ran.
    """
    document = build_manifest(
        run={
            "repository": DEFAULT_REPOSITORY,
            "commit": _sha(root),
            "declaration": CONFIGURATION_FILE,
        },
        ownership={},
        findings={"declaration": _finding((problem,))},
        capability={},
        verdict={"verdict": str(Verdict.FAILED), "reasons": [reason]},
    )
    (directory / MANIFEST_NAME).write_text(
        render_manifest(document), encoding="utf-8", newline="\n"
    )
    print(f"governance: {problem}")
    return EXIT_GATE_FAILED


def _report(findings: dict[str, object], verdict: Verdict, reasons: Sequence[str]) -> None:
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
        if not isinstance(entry, dict):
            continue
        problems = entry.get("problems")
        recorded = entry.get("verdict")
        print(f"governance: {name}: {recorded}")
        if isinstance(problems, list):
            for problem in problems:
                print(f"  - {problem}")
    print(f"governance: verdict {verdict}")
    if reasons:
        print(f"governance: reasons {', '.join(sorted(set(reasons)))}")
