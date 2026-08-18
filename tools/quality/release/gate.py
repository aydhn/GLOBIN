"""Running every release check and reducing them to one verdict.

**The judgement lives in :mod:`tools.quality.release.plan`; the sequencing lives
here.** Every decision this file makes is delegated to a pure function tested
from literals. What this module adds is order, I/O, and the arithmetic that turns
a set of answers into an exit code — the same division
``tools/quality/governance/gate.py`` uses.

**Two questions, two subcommands, and the difference matters.** ``check`` asks
whether the release *contract* holds: the matrix parses, no identifier repeats,
every evidence path exists, no blocking criterion is unmet, the version is
taggable and the changelog announces it. It reads files, reaches nothing, and is
deterministic over a commit — which is what makes it safe to run in CI on every
push. ``ready`` asks the different question of whether a release may be cut *right
now*: the branch, the worktree and the agreement between local and remote.

Splitting them is not tidiness. Repository state is not a property of a commit —
a shallow CI checkout legitimately reports a different branch arrangement from a
developer's machine, and folding that into the default gate would make an
unmeasurable condition fail every CI run. Since unmeasured outranks failed
(ADR-0045), that failure would also be the *loudest* possible one, for the least
real reason.

**Determinism is checked rather than assumed.** The manifest is built twice and
the renderings compared byte for byte, exactly as the SBOM and the governance
manifest are. Asserting determinism in a docstring costs nothing and proves
nothing.
"""

import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from tools.quality.evidence.checksums import digest as digest_bytes
from tools.quality.evidence.redaction import describe as describe_findings
from tools.quality.evidence.redaction import scan as scan_for_secrets
from tools.quality.execution.plan import Verdict, combine
from tools.quality.release import assets
from tools.quality.release.manifest import (
    REASON_BLOCKING_UNMET,
    REASON_BRANCH_UNEXPECTED,
    REASON_CATEGORY_EMPTY,
    REASON_CATEGORY_UNKNOWN,
    REASON_CHANGELOG_INCOMPLETE,
    REASON_CRITERION_DUPLICATE,
    REASON_CRITERION_MALFORMED,
    REASON_CRITERION_UNJUSTIFIED,
    REASON_DECLARATION_UNREADABLE,
    REASON_DOCUMENT_MISSING,
    REASON_EVIDENCE_MISSING,
    REASON_MANIFEST_LEAKAGE,
    REASON_MANIFEST_NONDETERMINISTIC,
    REASON_NOTES_MALFORMED,
    REASON_REMOTE_DIVERGED,
    REASON_REPOSITORY_STATE_UNMEASURED,
    REASON_VERSION_MALFORMED,
    REASON_VERSION_TAG_MISMATCH,
    REASON_VERSION_UNREADABLE,
    REASON_WORKTREE_DIRTY,
    SIGNING_ANNOTATED,
    SIGNING_SIGNED,
    SIGNING_UNAVAILABLE,
)
from tools.quality.release.manifest import build as build_manifest
from tools.quality.release.manifest import render as render_manifest
from tools.quality.release.plan import (
    CONFIGURATION_FILE,
    MATRICES,
    Contract,
    Criterion,
    Matrix,
    ReleaseError,
    Status,
    blocking_failures,
    changelog_problems,
    duplicate_identifiers,
    empty_categories,
    malformed_identifiers,
    misfiled_identifiers,
    parse_declaration,
    read_version,
    release_notes_problems,
    tag_for,
    unjustified,
    unknown_categories,
    valid_version,
    version_for,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

OUTPUT_DIRECTORY: Final[str] = ".globin/release"
"""Beside ``.globin/supply``, ``.globin/evidence``, ``.globin/workflow`` and
``.globin/governance``, under the same ignored root. Regenerable, so nothing here
is committed — what is published is a copy attached to a release."""

SUPPLY_DIRECTORY: Final[str] = ".globin/supply"
"""Where ``python -m tools.quality supply`` leaves the SBOM this gate republishes."""

EXIT_OK: Final[int] = 0
EXIT_GATE_FAILED: Final[int] = 1
EXIT_UNMEASURED: Final[int] = 3
"""The same three codes every other gate here uses, so that a caller who knows
what ``3`` means from one does not have to learn a second vocabulary."""

DEFAULT_REPOSITORY: Final[str] = "aydhn/GLOBIN"
RELEASE_BRANCH: Final[str] = "master"
"""The only branch a release may be cut from. ``REQUIRED_GIT_BRANCH`` in
``src/globin/project_contract.py`` is the authority; a contract test compares
them so this constant cannot drift away from it."""

REMOTE_REF: Final[str] = "origin/master"
SHA_LENGTH: Final[int] = 40
GIT_TIMEOUT_SECONDS: Final[int] = 60

_UNEVALUATED: Final[str] = (
    "not evaluated: the version could not be read, so there is no release to check this against"
)
"""What a check downstream of an unusable version records.

Deliberately a **failure** rather than an unmeasured result. Unmeasured is for a
state of the world that could not be determined; a version that was read and
found invalid is known, and known to be wrong. Since unmeasured outranks failed,
recording these as unmeasured would make the gate exit 3 rather than 1 — reporting
a certainty as an uncertainty.
"""

Runner = Callable[..., "subprocess.CompletedProcess[str]"]
"""How a child process is started.

Injected rather than called directly, for the reason
:mod:`tools.quality.supply.audit` gives about its own: the suite's offline guard
patches sockets in one interpreter and a child has its own view of the world, so
a function that starts one must be substitutable to be testable. The default is
the real thing, so no caller outside a test ever passes one.
"""


def run_release(
    *,
    root: Path | None = None,
    reports: Path | None = None,
    check_repository: bool = False,
    runner: Runner | None = None,
) -> int:
    """Check the release contract, and optionally whether a release may be cut.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.
        reports: Where to write. Defaults to :data:`OUTPUT_DIRECTORY` under root.
        check_repository: Whether to add the release preconditions — branch,
            worktree and agreement with the remote. False for the contract check
            CI runs; true for ``ready``.
        runner: How to start Git. Defaults to :func:`subprocess.run`.

    Returns:
        :data:`EXIT_OK`, :data:`EXIT_GATE_FAILED` or :data:`EXIT_UNMEASURED`.
    """
    base = REPO_ROOT if root is None else root
    directory = (base / OUTPUT_DIRECTORY) if reports is None else reports
    directory.mkdir(parents=True, exist_ok=True)

    texts: dict[str, str] = {}
    for spec in MATRICES:
        declared = _read(base, spec.declaration)
        if declared is None:
            problem = f"{spec.declaration} could not be read"
            return _fail_early(directory, base, problem, REASON_DECLARATION_UNREADABLE)
        texts[spec.declaration] = declared
    try:
        contract = parse_declaration(texts)
    except ReleaseError as fault:
        return _fail_early(directory, base, str(fault), REASON_DECLARATION_UNREADABLE)

    reasons: list[str] = []
    findings: dict[str, object] = {}

    version = _version(base, contract, findings, reasons)
    tag = tag_for(version) if version else ""

    _check_documents(base, contract, findings, reasons)
    _check_changelog(base, contract, version, findings, reasons)
    _check_release_notes(base, contract, findings, reasons)
    _check_criteria(base, contract, findings, reasons)
    if check_repository:
        _check_repository(base, findings, reasons, runner)

    acceptance = _acceptance(contract)
    written = _write_assets(directory, base, acceptance)

    run: dict[str, object] = {
        "repository": DEFAULT_REPOSITORY,
        "commit": _sha(base),
        "declaration": CONFIGURATION_FILE,
        "declarations": [spec.declaration for spec in MATRICES],
        "version": version or "unknown",
        "tag": tag or "unknown",
        "version_source": contract.version_source,
        "documents": list(contract.documents()),
        "assets": _asset_digests(written),
        "preconditions_checked": check_repository,
    }
    capability = _capability(base)

    verdict = combine([_verdict_of(entry) for entry in findings.values()])
    document = build_manifest(
        run=run,
        acceptance=acceptance,
        findings=findings,
        capability=capability,
        verdict=_verdict(verdict, reasons),
    )
    rendered = render_manifest(document)
    again = render_manifest(
        build_manifest(
            run=run,
            acceptance=acceptance,
            findings=findings,
            capability=capability,
            verdict=_verdict(verdict, reasons),
        )
    )
    if rendered != again:
        reasons.append(REASON_MANIFEST_NONDETERMINISTIC)
        verdict = Verdict.FAILED

    leaks = scan_for_secrets(assets.MANIFEST_FILE, rendered)
    if leaks:
        reasons.append(REASON_MANIFEST_LEAKAGE)
        verdict = Verdict.FAILED
        print("release: the manifest carries something it must not:")
        print(describe_findings(leaks))

    if REASON_MANIFEST_NONDETERMINISTIC in reasons or REASON_MANIFEST_LEAKAGE in reasons:
        document = build_manifest(
            run=run,
            acceptance=acceptance,
            findings=findings,
            capability=capability,
            verdict=_verdict(verdict, reasons),
        )
        rendered = render_manifest(document)

    (directory / assets.MANIFEST_FILE).write_text(rendered, encoding="utf-8", newline="\n")
    _write_checksums(directory, {**written, assets.MANIFEST_FILE: rendered.encode("utf-8")})
    _report(findings, verdict, reasons, version, tag)
    return _exit_code(verdict)


def _version(
    root: Path, contract: Contract, findings: dict[str, object], reasons: list[str]
) -> str:
    """Read the declared version and judge it.

    Args:
        root: The repository root.
        contract: The release contract.
        findings: Mutated with the ``version_source`` and ``version_tag_parity``
            entries.
        reasons: Mutated with any reason codes raised.

    Returns:
        The version, or the empty string when it could not be read.

    **A check the version made impossible is recorded as failed, not as
    unmeasured.** Unmeasured means the state of the world could not be
    determined — the network was down, Git was absent. A version that was read
    and found invalid is the opposite of that: it is known, and known to be
    wrong. Recording the checks downstream of it as unmeasured would let the
    gate exit 3 rather than 1, reporting a certainty as an uncertainty, because
    unmeasured outranks failed.
    """
    source = _read(root, contract.version_source)
    if source is None:
        problem = f"{contract.version_source} could not be read"
        findings["version_source"] = _finding((problem,))
        reasons.append(REASON_VERSION_UNREADABLE)
        findings["version_tag_parity"] = _finding((_UNEVALUATED,))
        return ""

    try:
        version = read_version(source)
    except ReleaseError as fault:
        findings["version_source"] = _finding((str(fault),))
        reasons.append(REASON_VERSION_UNREADABLE)
        findings["version_tag_parity"] = _finding((_UNEVALUATED,))
        return ""

    if not valid_version(version):
        problem = (
            f"{version!r} is not a final release version; a release tag names "
            f"three dotted integers and nothing else"
        )
        findings["version_source"] = _finding((problem,))
        reasons.append(REASON_VERSION_MALFORMED)
        findings["version_tag_parity"] = _finding((_UNEVALUATED,))
        return ""

    findings["version_source"] = _finding(())
    findings["version_tag_parity"] = _finding(_parity(version))
    if _parity(version):
        reasons.append(REASON_VERSION_TAG_MISMATCH)
    return version


def _parity(version: str) -> tuple[str, ...]:
    """Whether the tag naming a version names that version back.

    Args:
        version: The version.

    Returns:
        One message when the round trip does not hold, empty otherwise.

    A tag and a version are related by a prefix and by nothing else, so this can
    only fail if the two functions stop being inverses. Checking it anyway is
    cheap, and the day somebody adds a suffix to one of them it is the check that
    says so rather than a release tagged ``v0.1.0`` that reports ``0.1``.
    """
    recovered = version_for(tag_for(version))
    if recovered == version:
        return ()
    return (f"the tag {tag_for(version)!r} names {recovered!r}, not {version!r}",)


def _check_documents(
    root: Path, contract: Contract, findings: dict[str, object], reasons: list[str]
) -> None:
    """Check that every document a release requires exists.

    Args:
        root: The repository root.
        contract: The release contract.
        findings: Mutated with the ``release_documents`` entry.
        reasons: Mutated with any reason codes raised.
    """
    absent = tuple(
        f"{relative} is declared by the release contract and does not exist"
        for relative in contract.documents()
        if not (root / relative).is_file()
    )
    findings["release_documents"] = _finding(absent)
    if absent:
        reasons.append(REASON_DOCUMENT_MISSING)


def _check_changelog(
    root: Path, contract: Contract, version: str, findings: dict[str, object], reasons: list[str]
) -> None:
    """Check that the changelog announces the version being released.

    Args:
        root: The repository root.
        contract: The release contract.
        version: The version, or the empty string when it could not be read.
        findings: Mutated with the ``changelog`` entry.
        reasons: Mutated with any reason codes raised.
    """
    text = _read(root, contract.changelog)
    if text is None:
        findings["changelog"] = _finding((f"{contract.changelog} could not be read",))
        reasons.append(REASON_CHANGELOG_INCOMPLETE)
        return
    if not version:
        findings["changelog"] = _finding((_UNEVALUATED,))
        reasons.append(REASON_CHANGELOG_INCOMPLETE)
        return
    problems = changelog_problems(text, version)
    findings["changelog"] = _finding(problems)
    if problems:
        reasons.append(REASON_CHANGELOG_INCOMPLETE)


def _check_release_notes(
    root: Path, contract: Contract, findings: dict[str, object], reasons: list[str]
) -> None:
    """Check GitHub's automatic release-notes configuration.

    Args:
        root: The repository root.
        contract: The release contract.
        findings: Mutated with the ``release_notes`` entry.
        reasons: Mutated with any reason codes raised.
    """
    text = _read(root, contract.release_notes)
    if text is None:
        findings["release_notes"] = _finding((f"{contract.release_notes} could not be read",))
        reasons.append(REASON_NOTES_MALFORMED)
        return
    problems = tuple(
        f"{contract.release_notes}: {problem}" for problem in release_notes_problems(text)
    )
    findings["release_notes"] = _finding(problems)
    if problems:
        reasons.append(REASON_NOTES_MALFORMED)


def _check_criteria(
    root: Path, contract: Contract, findings: dict[str, object], reasons: list[str]
) -> None:
    """Check the foundation matrix itself.

    Args:
        root: The repository root.
        contract: The release contract.
        findings: Mutated with four entries covering shape, coverage, evidence
            and the blocking criteria.
        reasons: Mutated with any reason codes raised.
    """
    shape: list[str] = []
    grouping: list[str] = []

    # Duplicates are checked across every matrix at once, and the rest per matrix.
    # Two bands using one identifier is exactly the collision this catches, and a
    # per-matrix check would miss it -- while an identifier's *shape* means
    # nothing without the spec that declares its prefix.
    duplicates = tuple(
        f"criterion identifier {identifier!r} is declared more than once"
        for identifier in duplicate_identifiers(contract.criteria)
    )
    shape.extend(duplicates)
    if duplicates:
        reasons.append(REASON_CRITERION_DUPLICATE)

    for matrix in contract.matrices:
        spec, entries = matrix.spec, matrix.criteria
        malformed = tuple(
            f"{spec.prefix}: criterion identifier {identifier!r} does not follow the declared shape"
            for identifier in malformed_identifiers(spec, entries)
        )
        misfiled = tuple(
            f"{spec.prefix}: {problem}" for problem in misfiled_identifiers(spec, entries)
        )
        shape.extend((*malformed, *misfiled))
        if malformed or misfiled:
            reasons.append(REASON_CRITERION_MALFORMED)

        unknown = tuple(
            f"{spec.prefix}: criterion category {name!r} is not a declared category"
            for name in unknown_categories(spec, entries)
        )
        empty = tuple(
            f"{spec.prefix}: category {name!r} has no criteria, so the matrix claims a "
            f"capability group it does not cover"
            for name in empty_categories(spec, entries)
        )
        grouping.extend((*unknown, *empty))
        if unknown:
            reasons.append(REASON_CATEGORY_UNKNOWN)
        if empty:
            reasons.append(REASON_CATEGORY_EMPTY)

    findings["criterion_shape"] = _finding(tuple(shape))
    findings["criterion_categories"] = _finding(tuple(grouping))

    criteria = contract.criteria

    unbacked = tuple(
        f"criterion {identifier} names neither an evidence path nor a command"
        for identifier in unjustified(criteria)
    )
    absent = tuple(
        f"criterion {criterion.identifier} names evidence that does not exist: {relative}"
        for criterion in sorted(criteria)
        for relative in criterion.evidence
        if not (root / relative).exists()
    )
    findings["criterion_evidence"] = _finding((*unbacked, *absent))
    if unbacked:
        reasons.append(REASON_CRITERION_UNJUSTIFIED)
    if absent:
        reasons.append(REASON_EVIDENCE_MISSING)

    unmet = blocking_failures(criteria)
    findings["blocking_criteria"] = _finding(unmet)
    if unmet:
        reasons.append(REASON_BLOCKING_UNMET)


def _check_repository(
    root: Path, findings: dict[str, object], reasons: list[str], runner: Runner | None
) -> None:
    """Check that a release may be cut from this working tree right now.

    Args:
        root: The repository root.
        findings: Mutated with the ``repository_state`` entry.
        reasons: Mutated with any reason codes raised.
        runner: How to start Git.

    Three conditions, and each has cost somebody a bad release somewhere: the
    branch must be the one releases come from, the worktree must hold nothing
    uncommitted, and the local branch must agree with the remote. The third is
    the one that matters most here — a tag pushed from a tree ahead of its remote
    names a commit nobody else can fetch.
    """
    branch = _git(root, ("rev-parse", "--abbrev-ref", "HEAD"), runner)
    if branch is None:
        findings["repository_state"] = _finding((), measured=False)
        reasons.append(REASON_REPOSITORY_STATE_UNMEASURED)
        return

    problems: list[str] = []
    if branch != RELEASE_BRANCH:
        problems.append(f"the branch is {branch!r}, and a release is cut from {RELEASE_BRANCH!r}")
        reasons.append(REASON_BRANCH_UNEXPECTED)

    status = _git(root, ("status", "--porcelain"), runner)
    if status is None:
        findings["repository_state"] = _finding(tuple(problems), measured=False)
        reasons.append(REASON_REPOSITORY_STATE_UNMEASURED)
        return
    if status:
        count = len(status.splitlines())
        problems.append(f"the working tree is not clean: {count} path(s) uncommitted or untracked")
        reasons.append(REASON_WORKTREE_DIRTY)

    local = _git(root, ("rev-parse", "HEAD"), runner)
    remote = _git(root, ("rev-parse", REMOTE_REF), runner)
    if local is None or remote is None:
        findings["repository_state"] = _finding(tuple(problems), measured=False)
        reasons.append(REASON_REPOSITORY_STATE_UNMEASURED)
        return
    if local != remote:
        problems.append(f"HEAD and {REMOTE_REF} disagree, so the commit is not on the remote")
        reasons.append(REASON_REMOTE_DIVERGED)

    findings["repository_state"] = _finding(tuple(problems))


def _git(root: Path, arguments: Sequence[str], runner: Runner | None) -> str | None:
    """Ask Git one question.

    Args:
        root: The repository root.
        arguments: The command, without the leading ``git``.
        runner: How to start the child. Defaults to :func:`subprocess.run`.

    Returns:
        The trimmed standard output, or ``None`` when Git could not answer —
        which the caller records as unmeasured rather than as clean.
    """
    try:
        completed = (runner or subprocess.run)(
            ["git", *arguments],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
            cwd=root,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _acceptance(contract: Contract) -> dict[str, object]:
    """Every band matrix, as counts and the criteria that did not pass.

    Args:
        contract: The release contract.

    Returns:
        The section, keyed by matrix prefix.

    Keyed by prefix rather than flattened, because a total across two bands
    answers no question anybody has: a reader wants to know whether *this* band
    is certified, and the counts of a band frozen two releases ago would dilute
    it.
    """
    return {matrix.spec.prefix: _matrix_acceptance(matrix) for matrix in contract.matrices}


def _matrix_acceptance(matrix: Matrix) -> dict[str, object]:
    """One band matrix, as counts and the criteria that did not pass.

    Args:
        matrix: The matrix.

    Returns:
        Its record, with every list in a stable order.

    Passing criteria are summarised rather than listed one by one, and the ones
    that did not pass are named in full. A record whose length grows with the
    number of things that are *fine* buries the ones that are not.
    """
    criteria = matrix.criteria
    counts = {status.value: 0 for status in Status}
    for criterion in criteria:
        counts[criterion.status.value] += 1

    by_category: dict[str, dict[str, object]] = {}
    for category in matrix.spec.categories:
        members = [entry for entry in criteria if entry.category == category]
        by_category[category] = {
            "total": len(members),
            "blocking": sum(1 for entry in members if entry.blocking),
            "passed": sum(1 for entry in members if entry.status is Status.PASS),
        }

    return {
        "band": matrix.spec.band,
        "document": matrix.spec.document,
        "total": len(criteria),
        "blocking": sum(1 for entry in criteria if entry.blocking),
        "counts": counts,
        "categories": by_category,
        "unresolved": [
            _criterion_document(entry)
            for entry in sorted(criteria)
            if entry.status is not Status.PASS
        ],
    }


def _criterion_document(criterion: Criterion) -> dict[str, object]:
    """One criterion, as it appears in the manifest.

    Args:
        criterion: The criterion.

    Returns:
        Its record.
    """
    return {
        "id": criterion.identifier,
        "category": criterion.category,
        "requirement": criterion.requirement,
        "blocking": criterion.blocking,
        "status": criterion.status.value,
        "reason": criterion.reason,
        "evidence": list(criterion.evidence),
        "command": criterion.command,
    }


def _capability(root: Path) -> dict[str, object]:
    """What the host will and will not do, recorded rather than assumed.

    Args:
        root: The repository root.

    Returns:
        The section.

    Only the *local* capability is decided here. Whether the platform has
    immutable releases switched on, and whether the tag ruleset exists, are
    questions for a credential and a network — ``tools/quality/supply``'s
    capability probe already holds both, and a second probe would be a second
    thing to keep in step. What this records is the one capability the release
    procedure needs and the host answers: whether a tag can be signed at all.
    """
    return {
        "tag_signing": {
            "state": _signing_state(root),
            "authority": "docs/research/phase_016_sources.md#s-14",
            "reason": (
                "An annotated tag carries a message, a tagger and a date; a signed tag "
                "additionally carries a signature. They are different guarantees and are "
                "recorded as different states."
            ),
        }
    }


def _signing_state(root: Path) -> str:
    """Whether this host can sign a tag.

    Args:
        root: The repository root.

    Returns:
        One of :data:`~tools.quality.release.manifest.SIGNING_STATES`.

    Read from the repository's committed Git configuration rather than by
    starting ``gpg``. A signing key is host state, and a gate that reported
    ``SIGNED_VERIFIED`` because a key existed somewhere would be describing the
    machine rather than the tag. The verified state is therefore never claimed
    here: it is set by the release procedure, from an actual verification, or it
    is not set at all.
    """
    configuration = _read(root, ".git/config") or ""
    if "signingkey" in configuration or "gpgsign = true" in configuration:
        return SIGNING_ANNOTATED
    return SIGNING_UNAVAILABLE


def _write_assets(
    directory: Path, root: Path, acceptance: Mapping[str, object]
) -> dict[str, bytes]:
    """Write the acceptance record and republish the SBOM, if there is one.

    Args:
        directory: Where release artefacts are written.
        root: The repository root.
        acceptance: The acceptance section.

    Returns:
        Each asset written, by name, with its bytes — for the checksum file.
    """
    written: dict[str, bytes] = {}

    # One asset per band matrix, named by the same table the gate read. A single
    # combined file would make a reader parse two bands to learn about one.
    files = {
        MATRICES[0].prefix: assets.ACCEPTANCE_FILE,
        MATRICES[1].prefix: assets.ENVIRONMENT_ACCEPTANCE_FILE,
    }
    for prefix, name in files.items():
        section = acceptance.get(prefix)
        if not isinstance(section, Mapping):  # pragma: no cover -- always a Mapping.
            continue
        rendered = render_manifest(dict(section))
        (directory / name).write_text(rendered, encoding="utf-8", newline="\n")
        written[name] = rendered.encode("utf-8")

    sbom = root / SUPPLY_DIRECTORY / assets.SBOM_FILE
    try:
        payload = sbom.read_bytes()
    except OSError:
        return written
    (directory / assets.SBOM_FILE).write_bytes(payload)
    written[assets.SBOM_FILE] = payload
    return written


def _write_checksums(directory: Path, written: Mapping[str, bytes]) -> None:
    """Write ``SHA256SUMS`` over everything published.

    Args:
        directory: Where release artefacts are written.
        written: Each asset's name and its bytes.

    The checksum file is excluded from its own inputs by
    :func:`tools.quality.release.assets.checksum_document`, which refuses rather
    than dropping it silently.
    """
    document = assets.checksum_document(written)
    (directory / assets.CHECKSUM_FILE).write_text(document, encoding="utf-8", newline="\n")


def _asset_digests(written: Mapping[str, bytes]) -> dict[str, str]:
    """Each published asset's digest, for the manifest.

    Args:
        written: Each asset's name and its bytes.

    Returns:
        The digests, keyed by name.

    The manifest's own digest is deliberately absent: a document cannot state a
    digest computed over itself. ``SHA256SUMS`` covers the manifest, and the
    manifest covers everything else — between them every published byte is
    described exactly once.
    """
    return {name: digest_bytes(payload) for name, payload in sorted(written.items())}


def _verdict(verdict: Verdict, reasons: Sequence[str]) -> dict[str, object]:
    """The verdict section.

    Args:
        verdict: The conclusion.
        reasons: The stable reason codes behind it.

    Returns:
        The section, with reasons sorted and deduplicated.
    """
    return {"verdict": str(verdict), "reasons": sorted(set(reasons))}


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


def _read(root: Path, relative: str) -> str | None:
    """Read a repository file.

    Args:
        root: The repository root.
        relative: The repository-relative path.

    Returns:
        Its text, or ``None`` when it cannot be read.
    """
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def _sha(root: Path) -> str:
    """The commit under test, read without starting a process.

    Args:
        root: The repository root.

    Returns:
        The forty-character SHA, or ``"unknown"``.

    Read from ``.git`` directly, exactly as the supply and governance gates do,
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

    A manifest is still written. A gate that failed silently and left no artefact
    would be indistinguishable, to anything reading the evidence afterwards, from
    a gate that never ran.
    """
    document = build_manifest(
        run={
            "repository": DEFAULT_REPOSITORY,
            "commit": _sha(root),
            "declaration": CONFIGURATION_FILE,
        },
        acceptance={},
        findings={"declaration": _finding((problem,))},
        capability={},
        verdict={"verdict": str(Verdict.FAILED), "reasons": [reason]},
    )
    (directory / assets.MANIFEST_FILE).write_text(
        render_manifest(document), encoding="utf-8", newline="\n"
    )
    print(f"release: {problem}")
    return EXIT_GATE_FAILED


def _report(
    findings: Mapping[str, object],
    verdict: Verdict,
    reasons: Sequence[str],
    version: str,
    tag: str,
) -> None:
    """Print what the gate established.

    Args:
        findings: Every check's entry.
        verdict: The conclusion.
        reasons: The stable reason codes behind it.
        version: The version read from the source.
        tag: The tag that version implies.

    ASCII only, because everything a gate prints must be — a Windows console
    encodes its output with the active code page, and a character it cannot
    represent turns a report into a traceback.
    """
    print(f"release: version {version or 'unknown'} -> tag {tag or 'unknown'}")
    for name, entry in sorted(findings.items()):
        if not isinstance(entry, dict):
            continue
        print(f"release: {name}: {entry.get('verdict')}")
        problems = entry.get("problems")
        if isinstance(problems, list):
            for problem in problems:
                print(f"  - {problem}")
    print(f"release: verdict {verdict}")
    if reasons:
        print(f"release: reasons {', '.join(sorted(set(reasons)))}")


__all__ = [
    "EXIT_GATE_FAILED",
    "EXIT_OK",
    "EXIT_UNMEASURED",
    "SIGNING_ANNOTATED",
    "SIGNING_SIGNED",
    "SIGNING_UNAVAILABLE",
    "Runner",
    "run_release",
]
