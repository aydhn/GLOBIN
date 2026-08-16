"""Running every lock check and reducing them to one verdict.

**The judgement lives in :mod:`tools.quality.lock.plan`; the sequencing lives
here.** Every decision this file makes is delegated to a pure function tested from
literals. What this module adds is order, I/O, and the arithmetic that turns a set
of answers into an exit code — the same division ``tools/quality/wheels/gate.py``
uses.

**Four modes, split by what they touch.** ``check`` reads files and opens no
socket. ``installed`` adds one read of this interpreter's own metadata, and still
opens none. ``relock`` and ``upgrade`` start ``pip``, which reaches the index —
which is why they are subcommands rather than the default, on the reasoning
``full`` gives: a gate that runs before every commit must work on an aeroplane.

**The child is injected, and that is not a convenience.** ADR-0024's offline
guarantee is enforced by refusing sockets in the *test* process, and a subprocess
sails past it in the opposite direction: the guard would catch nothing while the
child reached the network. A substitutable runner is what lets the regeneration
path be exercised without an index, and the default is the real thing, so no
caller outside a test passes one.

**A regenerated lock is checked before it is kept.** ``relock`` and ``upgrade``
produce a candidate, run the whole offline check against *that* rather than
against the committed file, and write it only if the verdict passes. A rejected
candidate is left under the run directory for inspection and the committed lock is
untouched — a tool that overwrites a good lock with a bad one has made the problem
worse than it found it.

**Line endings are normalised before anything is digested.** ``pip`` writes the
lock without controlling them, so on Windows it emits CRLF where ``.gitattributes``
stores LF (ledger S-04). Everything here reads with universal newlines and writes
with an explicit LF, and the digest recorded in the manifest is over the
normalised text — otherwise the determinism check would be measuring a checkout
setting.

**Not a second aggregate.** ADR-0042 put the run-level verdict in exactly one
place, and this is not it. The verdict here is about *this gate*, in the same
three-valued :class:`~tools.quality.execution.plan.Verdict` every other gate uses.
"""

import hashlib
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from importlib import metadata
from pathlib import Path
from typing import Final

from tools.quality.evidence.redaction import describe as describe_findings
from tools.quality.evidence.redaction import scan as scan_for_secrets
from tools.quality.execution.plan import Verdict, combine
from tools.quality.lock.manifest import (
    REASON_ARTEFACT_UNTRUSTED,
    REASON_DECLARATION_INCOMPLETE,
    REASON_DECLARATION_UNREADABLE,
    REASON_ENVIRONMENT_DIVERGED,
    REASON_ENVIRONMENT_UNMEASURED,
    REASON_FILE_UNREADABLE,
    REASON_HASH_MISSING,
    REASON_MANIFEST_LEAKAGE,
    REASON_MANIFEST_NONDETERMINISTIC,
    REASON_PACKAGE_MALFORMED,
    REASON_PRODUCER_UNEXPECTED,
    REASON_REFRESH_FAILED,
    REASON_REGISTER_DIVERGED,
    REASON_RUNTIME_UNLOCKED,
    REASON_SOURCE_ONLY,
    REASON_TARGET_DIVERGED,
    REASON_VERSION_UNSUPPORTED,
    REASON_WHEEL_INCOMPATIBLE,
)
from tools.quality.lock.manifest import build as build_manifest
from tools.quality.lock.manifest import render as render_manifest
from tools.quality.lock.plan import (
    CONFIGURATION_FILE,
    Declaration,
    Lock,
    LockError,
    artefact_problems,
    compatibility_problems,
    coverage_problems,
    declaration_problems,
    duplicate_packages,
    environment_problems,
    hash_problems,
    normalise,
    package_problems,
    parse_declaration,
    parse_lock,
    producer_problems,
    register_problems,
    runtime_problems,
    source_problems,
    target_problems,
    version_problems,
)
from tools.quality.runtime.plan import RuntimeBaselineError
from tools.quality.runtime.plan import parse_declaration as parse_runtime_contract
from tools.quality.supply.inventory import (
    CONTINUOUS_INTEGRATION,
    DEVELOPMENT,
    PYPI,
    PYPROJECT,
    SupplyChainError,
    collect,
    from_pyproject,
    from_workflows,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
"""The repository this gate reports on."""

OUTPUT_DIRECTORY: Final[str] = ".globin/lock"
"""Where the manifest is written, relative to the repository root.

Beside ``.globin/wheels``, ``.globin/runtime`` and ``.globin/drift``, under the
same ignored root. Regenerable, so nothing here is committed.
"""

MANIFEST_NAME: Final[str] = "lock-manifest.json"
"""The manifest's filename."""

REJECTED_NAME: Final[str] = "rejected-lock.toml"
"""Where a regenerated lock the gate refused is left, for a person to read."""

RUNTIME_CONTRACT: Final[str] = "docs/engineering/runtime-contract.toml"
"""The contract the declared target is compared against."""

ENVIRONMENT_DIRECTORY: Final[str] = ".venv"
"""The only environment ADR-0050 permits, and the only one ``installed`` measures."""

ROADMAP_TOTAL_PHASES: Final[int] = 320
"""How many phases the programme has."""

DELIVERED_PHASE: Final[int] = 20
"""A floor on what has shipped: no recorded gap may name this phase or an earlier one.

Deliberately a constant rather than a read of ``ROADMAP.md``, for the reason
``wheels/gate.py`` gives about its own: this bound exists to catch a gap pointing
at work that has already happened, and parsing the roadmap to discover it would
make the gate's verdict depend on a document the gate is not otherwise about. A
floor rather than a mirror, so it only needs revisiting when a gap is recorded.
"""

CHECK: Final[str] = "check"
INSTALLED: Final[str] = "installed"
RELOCK: Final[str] = "relock"
UPGRADE: Final[str] = "upgrade"

SHA_LENGTH: Final[int] = 40
"""How long a Git object name is."""

DEFAULT_REPOSITORY: Final[str] = "aydhn/GLOBIN"
"""Which repository the manifest records itself as describing."""

DEFAULT_TIMEOUT: Final[float] = 900.0
"""How long a resolution may take.

Generous: ``pip lock`` resolves the whole toolchain against an index, and a
timeout that fired on a slow connection would report a refresh failure that was
really a network hiccup.
"""

INTRINSIC_REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_VERSION_UNSUPPORTED,
        REASON_PRODUCER_UNEXPECTED,
        REASON_PACKAGE_MALFORMED,
        REASON_HASH_MISSING,
        REASON_ARTEFACT_UNTRUSTED,
        REASON_WHEEL_INCOMPATIBLE,
        REASON_SOURCE_ONLY,
    }
)
"""The findings that are about the lock itself rather than about the repository.

Only these decide whether a regenerated lock is kept — see :func:`_keep_or_reject`.
The rest (the declared target, the roots, the pins, the hook revisions, the runtime
pairing, this environment) describe work a person must now do, and every one of
them is *expected* to fail on the run that produces a new lock.
"""

EXIT_OK: Final[int] = 0
EXIT_GATE_FAILED: Final[int] = 1
EXIT_UNMEASURED: Final[int] = 3

Runner = Callable[..., "subprocess.CompletedProcess[str]"]
"""How a child is started. Substitutable so the resolution path is testable offline."""


def _sha(root: Path) -> str:
    """The commit under test, read without starting a process.

    Args:
        root: The repository root.

    Returns:
        The forty-character SHA, or ``"unknown"``.

    Read from ``.git`` directly, exactly as ``tools/quality/wheels/gate.py`` does,
    so that a manifest can be produced in a tree without Git on the path.
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
    """Read a repository file with universal newlines.

    Args:
        root: The repository root.
        relative: The repository-relative path.

    Returns:
        Its contents with line endings normalised to LF, or ``None`` when it
        cannot be read.

    ``Path.read_text`` applies universal newline translation, so a CRLF working
    copy and an LF one produce identical text here. That is what makes the digest
    recorded in the manifest a fact about content rather than about a checkout.
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


def _contract_values(root: Path) -> tuple[str, str, str, bool]:
    """Read what the runtime contract declares about the interpreter.

    Args:
        root: The repository root.

    Returns:
        The implementation, minor line, architecture and free-threaded flag.

    Raises:
        LockError: If the contract cannot be read or parsed.

    The runtime contract is read rather than restated. Phase 017 owns those values,
    and a second copy of them in this package would be a second thing to keep in
    step — which is the failure ``SOURCE_OF_TRUTH.md`` describes.
    """
    text = _read(root, RUNTIME_CONTRACT)
    if text is None:
        msg = f"{RUNTIME_CONTRACT} could not be read, so the lock's target cannot be checked"
        raise LockError(msg)
    try:
        contract = parse_runtime_contract(text)
    except RuntimeBaselineError as fault:
        msg = f"{RUNTIME_CONTRACT} could not be parsed: {fault}"
        raise LockError(msg) from fault
    interpreter = contract.interpreter
    return (
        interpreter.implementation,
        interpreter.minor_line,
        interpreter.architecture,
        interpreter.free_threaded,
    )


def installed_distributions() -> dict[str, str]:
    """What this interpreter can import, by distribution name and version.

    Returns:
        A mapping of distribution name to version.

    Read through :mod:`importlib.metadata` rather than by running ``pip list``: it
    is the standard library's own view of the environment it is running in, needs
    no child process, and therefore cannot be a network call by accident.
    """
    found: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        if name:
            found[str(name)] = distribution.version
    return found


def workflow_pins(root: Path) -> dict[str, str]:
    """What continuous integration installs at an exact version.

    Args:
        root: The repository root.

    Returns:
        Distribution name to version, for every exactly-pinned package the
        workflows install.

    Raises:
        SupplyChainError: If the workflow register cannot be read.

    Read through the inventory rather than by a second parse. Phase 014 owns how a
    workflow's install lines are read, and a second reader here would be a second
    thing to be wrong about the same file.
    """
    return {
        entry.name: entry.version
        for entry in from_workflows(root)
        if entry.ecosystem == PYPI and entry.scope == CONTINUOUS_INTEGRATION
    }


def _environment_finding(
    lock: Lock, declaration: Declaration, root: Path
) -> tuple[dict[str, object], str | None]:
    """Compare this environment against the lock, or record that it could not be.

    Args:
        lock: The parsed lock.
        declaration: The declaration, which names the seeded distributions.
        root: The repository root.

    Returns:
        The manifest entry, and the reason code to record, if any.

    **Running outside the project environment is unmeasured, not passed.** A gate
    asked "does this environment match the lock" that answered about some other
    interpreter would be answering a different question with this one's authority,
    and ADR-0045 is explicit that a thing which could not be measured is never a
    pass.
    """
    expected = (root / ENVIRONMENT_DIRECTORY).resolve()
    try:
        running = Path(sys.prefix).resolve()
    except OSError:
        running = Path(sys.prefix)
    if running != expected:
        problem = (
            f"this gate is running under {running.name!r} rather than the project "
            f"environment at {ENVIRONMENT_DIRECTORY}, so what is installed cannot be "
            f"compared against {lock.path}"
        )
        return _finding((problem,), measured=False), REASON_ENVIRONMENT_UNMEASURED

    diverged = environment_problems(lock, installed_distributions(), declaration.seeded)
    return _finding(diverged), REASON_ENVIRONMENT_DIVERGED if diverged else None


def _requirements_text(root: Path, declaration: Declaration) -> str:
    """The roots to resolve from, as a requirements file.

    Args:
        root: The repository root.
        declaration: The lock declaration, for the extra it covers.

    Returns:
        One requirement per line.

    Raises:
        LockError: If ``pyproject.toml`` cannot be read.

    Built from ``pyproject.toml`` rather than from the declaration's own ``roots``.
    The project file is the source; the declaration records what a resolution was
    performed from, and :func:`declaration_problems` compares the two. Resolving
    from the declaration would make that comparison compare a thing with itself.

    Deliberately not ``pip lock ".[dev]"``: that resolves the project itself and
    emits a ``directory`` entry with no version, which this gate refuses and which
    ``pip-audit`` reports as skipped.
    """
    try:
        declared = from_pyproject(root)
    except (SupplyChainError, OSError) as fault:
        msg = f"{PYPROJECT} could not be read, so there is nothing to resolve from: {fault}"
        raise LockError(msg) from fault

    lines = [
        f"{entry.name}{'' if entry.version == '*' else entry.version}"
        for entry in declared
        if entry.ecosystem == PYPI and entry.scope == DEVELOPMENT
    ]
    if not lines:
        msg = f"{PYPROJECT} declares no {declaration.dev_extra!r} requirements to resolve"
        raise LockError(msg)
    return "\n".join(sorted(lines)) + "\n"


def _constraints_text(
    lock: Lock | None,
    pinned: Mapping[str, str],
    only: Sequence[str],
    producer: tuple[str, str] | None = None,
) -> str:
    """What the resolution must not be allowed to move.

    Args:
        lock: The committed lock, if there is one.
        pinned: What the workflow register pins, by distribution name.
        only: The distributions that may move.
        producer: The declared producing tool and its version, held so the lock
            installs the same producer that wrote it.

    Returns:
        One ``name==version`` per line, empty when nothing is held.

    Three sources, and the order between them is a decision.

    **The workflow pins are held even on a wholesale relock.** ``pip lock`` has no
    ``--upgrade-package`` and re-resolves from bounds every time, so an
    unconstrained run takes the newest of everything — including the seven tools
    somebody chose deliberately and pinned after measuring with them. A lock exists
    to record the *transitive* set nobody had pinned; quietly upgrading the direct
    toolchain while doing it would be a different change wearing this one's
    clothes. Moving a tool is what ``upgrade`` is for, and what editing the
    workflow pin and relocking is for.

    **The committed lock is held underneath that**, so a relock does not
    gratuitously churn the forty-odd transitive versions either. A pin and a locked
    version that disagree is a state the gate already refuses, so on a healthy tree
    the two agree; where they do not, the pin wins, because it is the reviewed
    statement and the lock is the thing being corrected.

    Anything named in ``only`` is dropped from both, which is what lets a single
    package move while its neighbours stay put. If the upgrade genuinely needs a
    neighbour to move too, pip reports a conflict rather than dragging it along
    quietly, and naming that neighbour is then somebody's decision.
    """
    moving = {normalise(name) for name in only}
    held: dict[str, str] = {}
    if lock is not None:
        for package in lock.packages:
            if package.version is not None:
                held[package.normalised] = f"{package.name}=={package.version}"
    for name, version in pinned.items():
        held[normalise(name)] = f"{name}=={version}"
    if producer is not None:
        # Held last, and deliberately not droppable by `only`. The producing tool
        # is a transitive dependency of the toolchain it locks, so an
        # unconstrained resolution can lock a *newer* producer than the one that
        # wrote the file — an environment built from that lock would then hold a
        # pip that never produced it, and `[producer] version` would describe
        # nothing. Moving it is a deliberate edit to the declaration followed by a
        # relock, not something a resolution does on its own.
        tool, version = producer
        held[normalise(tool)] = f"{tool}=={version}"
        moving.discard(normalise(tool))
    return "\n".join(sorted(line for key, line in held.items() if key not in moving)) + "\n"


def _relock(
    root: Path,
    declaration: Declaration,
    committed: Lock | None,
    only: Sequence[str],
    runner: Runner | None,
    timeout: float,
) -> tuple[str | None, tuple[str, ...]]:
    """Re-resolve the declared roots and return the lock that came back.

    Args:
        root: The repository root.
        declaration: The lock declaration.
        committed: The lock as committed, needed to hold versions for an upgrade.
        only: The distributions to allow to move, empty for a wholesale relock.
        runner: How to start ``pip``.
        timeout: How long the resolution may take.

    Returns:
        The candidate lock's text with line endings normalised, and any problems.
        The text is ``None`` when nothing usable came back.

    **This is the one part of this package that reaches the network.** Every
    failure is caught and reported rather than allowed to escape: pip raises
    ``NotImplementedError`` from its own lock writer when an index entry carries no
    hash, and a traceback out of a gate is a gate that produced no evidence.
    """
    if only and committed is None:
        return None, ("an upgrade needs the committed lock to hold the other versions at",)
    try:
        requirements = _requirements_text(root, declaration)
    except LockError as fault:
        return None, (str(fault),)
    try:
        pinned = workflow_pins(root)
    except (SupplyChainError, OSError) as fault:
        return None, (f"the workflow register could not be read: {fault}",)

    with tempfile.TemporaryDirectory(prefix="globin-lock-") as workspace:
        area = Path(workspace)
        requirement_file = area / "requirements.txt"
        requirement_file.write_text(requirements, encoding="utf-8", newline="\n")
        output = area / "pylock.toml"

        argv = [sys.executable, "-m", "pip", "lock", "--disable-pip-version-check"]
        argv += ["--requirement", str(requirement_file)]
        constraints = _constraints_text(
            committed,
            pinned,
            only,
            (declaration.producer.tool, declaration.producer.version),
        )
        if constraints.strip():
            constraint_file = area / "constraints.txt"
            constraint_file.write_text(constraints, encoding="utf-8", newline="\n")
            argv += ["--constraint", str(constraint_file)]
        if not declaration.policy.allow_source:
            argv += ["--only-binary", ":all:"]
        argv += ["--output", str(output)]

        try:
            completed = (runner or subprocess.run)(
                argv, capture_output=True, text=True, check=False, timeout=timeout
            )
        except (OSError, subprocess.SubprocessError) as fault:
            return None, (f"pip lock could not be run: {fault}",)
        if completed.returncode != 0:
            return None, (f"pip lock exited {completed.returncode}: {_tail(completed.stderr)}",)
        try:
            return output.read_text(encoding="utf-8"), ()
        except OSError as fault:
            return None, (f"pip lock reported success and wrote no readable lock: {fault}",)


def _tail(text: str | None, limit: int = 400) -> str:
    """The end of a child's error output, short enough to put in a finding.

    Args:
        text: The captured stream.
        limit: How many characters to keep.

    Returns:
        The tail, collapsed to one line.
    """
    if not text:
        return "no output"
    collapsed = " ".join(text.split())
    return collapsed[-limit:]


def run_lock(
    *,
    root: Path | None = None,
    reports: Path | None = None,
    mode: str = CHECK,
    only: Sequence[str] = (),
    runner: Runner | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> int:
    """Check the lock and write the manifest.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.
        reports: Where to write. Defaults to :data:`OUTPUT_DIRECTORY` under root.
        mode: One of :data:`CHECK`, :data:`INSTALLED`, :data:`RELOCK` or
            :data:`UPGRADE`.
        only: For :data:`UPGRADE`, the distributions allowed to move.
        runner: How to start ``pip``. Defaults to :func:`subprocess.run`.
        timeout: How long a resolution may take.

    Returns:
        :data:`EXIT_OK`, :data:`EXIT_GATE_FAILED` or :data:`EXIT_UNMEASURED`.
    """
    base = REPO_ROOT if root is None else root
    directory = (base / OUTPUT_DIRECTORY) if reports is None else reports
    directory.mkdir(parents=True, exist_ok=True)

    reasons: list[str] = []
    findings: dict[str, object] = {}

    declared_text = _read(base, CONFIGURATION_FILE)
    if declared_text is None:
        problem = f"{CONFIGURATION_FILE} could not be read"
        return _fail_early(directory, base, problem, REASON_DECLARATION_UNREADABLE, mode)
    try:
        declaration = parse_declaration(declared_text)
    except LockError as fault:
        return _fail_early(directory, base, str(fault), REASON_DECLARATION_UNREADABLE, mode)

    committed_text = _read(base, declaration.dev_path)
    committed: Lock | None = None
    if committed_text is not None:
        try:
            committed = parse_lock(committed_text, path=declaration.dev_path)
        except LockError:
            committed = None

    candidate: str | None = None
    if mode in {RELOCK, UPGRADE}:
        candidate, refresh = _relock(base, declaration, committed, only, runner, timeout)
        findings["refresh"] = _finding(refresh)
        if refresh:
            reasons.append(REASON_REFRESH_FAILED)
        if candidate is None:
            return _fail_early(
                directory,
                base,
                "; ".join(refresh) or "no lock was produced",
                REASON_REFRESH_FAILED,
                mode,
            )

    lock_text = candidate if candidate is not None else committed_text
    if lock_text is None:
        problem = f"{declaration.dev_path} could not be read"
        return _fail_early(directory, base, problem, REASON_FILE_UNREADABLE, mode)
    try:
        lock = parse_lock(lock_text, path=declaration.dev_path)
    except LockError as fault:
        return _fail_early(directory, base, str(fault), REASON_FILE_UNREADABLE, mode)

    unsupported = version_problems(lock)
    findings["format"] = _finding(unsupported)
    if unsupported:
        reasons.append(REASON_VERSION_UNSUPPORTED)

    unexpected = producer_problems(lock, declaration)
    findings["producer"] = _finding(unexpected)
    if unexpected:
        reasons.append(REASON_PRODUCER_UNEXPECTED)

    try:
        implementation, minor_line, architecture, free_threaded = _contract_values(base)
    except LockError as fault:
        return _fail_early(directory, base, str(fault), REASON_TARGET_DIVERGED, mode)
    diverged = target_problems(
        declaration.target,
        implementation=implementation,
        minor_line=minor_line,
        architecture=architecture,
        free_threaded=free_threaded,
    )
    findings["target"] = _finding(diverged)
    if diverged:
        reasons.append(REASON_TARGET_DIVERGED)

    malformed = (
        *(problem for package in lock.packages for problem in package_problems(package, lock.path)),
        *(
            f"{lock.path}: {name} is locked more than once"
            for name in duplicate_packages(lock.packages)
        ),
    )
    findings["packages"] = _finding(malformed)
    if malformed:
        reasons.append(REASON_PACKAGE_MALFORMED)

    unhashed = tuple(
        problem
        for package in lock.packages
        for problem in hash_problems(package, declaration.policy, lock.path)
    )
    findings["hashes"] = _finding(unhashed)
    if unhashed:
        reasons.append(REASON_HASH_MISSING)

    untrusted = tuple(
        problem
        for package in lock.packages
        for problem in artefact_problems(package, declaration.target, lock.path)
    )
    findings["artefacts"] = _finding(untrusted)
    if untrusted:
        reasons.append(REASON_ARTEFACT_UNTRUSTED)

    incompatible = tuple(
        problem
        for package in lock.packages
        for problem in compatibility_problems(package, declaration.target, lock.path)
    )
    findings["compatibility"] = _finding(incompatible)
    if incompatible:
        reasons.append(REASON_WHEEL_INCOMPATIBLE)

    unowned = source_problems(
        lock.packages,
        declaration.target,
        declaration.policy,
        declaration.gaps,
        delivered=DELIVERED_PHASE,
        total=ROADMAP_TOTAL_PHASES,
    )
    findings["source"] = _finding(unowned)
    if unowned:
        reasons.append(REASON_SOURCE_ONLY)

    try:
        inventory = collect(base)
    except (SupplyChainError, OSError) as fault:
        return _fail_early(
            directory,
            base,
            f"the declaration registers could not be read: {fault}",
            REASON_DECLARATION_INCOMPLETE,
            mode,
        )

    incomplete = (
        *declaration_problems(declaration, inventory),
        *coverage_problems(lock, inventory),
    )
    findings["declaration"] = _finding(incomplete)
    if incomplete:
        reasons.append(REASON_DECLARATION_INCOMPLETE)

    registers = register_problems(lock, inventory)
    findings["registers"] = _finding(registers)
    if registers:
        reasons.append(REASON_REGISTER_DIVERGED)

    unlocked = runtime_problems(declaration, inventory)
    findings["runtime"] = _finding(unlocked)
    if unlocked:
        reasons.append(REASON_RUNTIME_UNLOCKED)

    if mode == INSTALLED:
        entry, reason = _environment_finding(lock, declaration, base)
        findings["environment"] = entry
        if reason is not None:
            reasons.append(reason)

    run = _run_section(base, declaration, lock, lock_text, mode)
    overall = combine([_verdict_of(entry) for entry in findings.values()])
    verdict = {"verdict": str(overall), "reasons": sorted(set(reasons))}

    document = build_manifest(run=run, findings=findings, verdict=verdict)
    rendered = render_manifest(document)
    if rendered != render_manifest(build_manifest(run=run, findings=findings, verdict=verdict)):
        return _fail_early(
            directory,
            base,
            "two renderings of the same run disagreed",
            REASON_MANIFEST_NONDETERMINISTIC,
            mode,
        )

    leaks = scan_for_secrets(MANIFEST_NAME, rendered)
    if leaks:
        return _fail_early(directory, base, describe_findings(leaks), REASON_MANIFEST_LEAKAGE, mode)

    (directory / MANIFEST_NAME).write_text(rendered, encoding="utf-8", newline="\n")

    if candidate is not None:
        sound = not set(reasons) & INTRINSIC_REASONS
        _keep_or_reject(base, directory, declaration, candidate, committed_text, sound=sound)

    _report(findings, overall, reasons)
    return _exit_code(overall)


def _keep_or_reject(
    root: Path,
    directory: Path,
    declaration: Declaration,
    candidate: str,
    committed: str | None,
    *,
    sound: bool,
) -> None:
    """Write a regenerated lock, or set it aside with the committed one untouched.

    Args:
        root: The repository root.
        directory: The run directory.
        declaration: The lock declaration.
        candidate: The regenerated lock's text.
        committed: The committed lock's text, if there was one.
        sound: Whether the candidate passed every check that is about the lock
            itself, as opposed to about the rest of the repository.

    **Soundness rather than the overall verdict decides this, and the distinction
    is what makes the upgrade procedure possible at all.** A fresh resolution moves
    versions, so it will almost always disagree with the pins in
    ``.github/workflows/`` — that is the *point* of running it, and the gate names
    the exact replacements. Refusing to keep a lock because the pins have not been
    edited yet would mean the pins could never be edited, because the lock they
    must be edited to match would never exist. So a divergence about the
    repository is reported and the lock is kept; a defect in the lock itself is
    reported and the committed file is left alone.

    Either way the exit code still reflects everything that was found, so nothing
    is swept aside by being written.

    A candidate that failed is kept under the run directory rather than discarded,
    because the fastest way to understand why a resolution was refused is to read
    the thing that was refused.
    """
    if not sound:
        (directory / REJECTED_NAME).write_text(candidate, encoding="utf-8", newline="\n")
        where = f"{OUTPUT_DIRECTORY}/{REJECTED_NAME}"
        print(f"lock: the regenerated lock was refused and is at {where}")
        print(f"lock: {declaration.dev_path} is unchanged")
        return
    if candidate == committed:
        print(f"lock: {declaration.dev_path} is unchanged")
        return
    (root / declaration.dev_path).write_text(candidate, encoding="utf-8", newline="\n")
    print(f"lock: {declaration.dev_path} was rewritten")
    print(f"lock: update [target] locked in {CONFIGURATION_FILE} to today's date")
    print("lock: run `python -m tools.quality lock` to see which pins must now change")


def _run_section(
    root: Path, declaration: Declaration, lock: Lock, lock_text: str, mode: str
) -> dict[str, object]:
    """What was checked, for the manifest's ``run`` section.

    Args:
        root: The repository root.
        declaration: The lock declaration.
        lock: The parsed lock.
        lock_text: Its text, already newline-normalised, for the digest.
        mode: Which subcommand ran.

    Returns:
        The section. No wall clock and no absolute path, and no artefact URL — a
        manifest is a summary rather than a copy.
    """
    artefacts = sum(len(package.artefacts) for package in lock.packages)
    hashed = sum(
        1 for package in lock.packages for artefact in package.artefacts if artefact.hashes
    )
    return {
        "repository": DEFAULT_REPOSITORY,
        "commit": _sha(root),
        "declaration": CONFIGURATION_FILE,
        "contract": RUNTIME_CONTRACT,
        "mode": mode,
        "lock": {
            "path": lock.path,
            "lock_version": lock.lock_version,
            "created_by": lock.created_by,
            "digest": "sha256:" + hashlib.sha256(lock_text.encode("utf-8")).hexdigest(),
            "packages": len(lock.packages),
            "artefacts": artefacts,
            "hashed": hashed,
        },
        "producer": {
            "tool": declaration.producer.tool,
            "version": declaration.producer.version,
            "experimental": declaration.producer.experimental,
        },
        "target": {
            "implementation": declaration.target.implementation,
            "minor_line": declaration.target.minor_line,
            "architecture": declaration.target.architecture,
            "platform_tag": declaration.target.platform_tag,
            "free_threaded": declaration.target.free_threaded,
            "index": declaration.target.index,
            "artefact_host": declaration.target.artefact_host,
            "locked": declaration.target.locked,
        },
        "runtime_locked": declaration.runtime_locked,
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


def _fail_early(directory: Path, root: Path, problem: str, reason: str, mode: str) -> int:
    """Write a manifest recording that the gate could not get as far as checking.

    Args:
        directory: Where to write.
        root: The repository root.
        problem: What went wrong.
        reason: The stable reason code.
        mode: Which subcommand ran.

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
            "contract": RUNTIME_CONTRACT,
            "mode": mode,
        },
        findings={"declaration": _finding((problem,))},
        verdict={"verdict": str(Verdict.FAILED), "reasons": [reason]},
    )
    (directory / MANIFEST_NAME).write_text(
        render_manifest(document), encoding="utf-8", newline="\n"
    )
    print(f"lock: {problem}")
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
        print(f"lock: {name}: {entry.get('verdict')}")
        problems = entry.get("problems")
        if isinstance(problems, list):
            for problem in problems:
                print(f"  - {problem}")
    print(f"lock: verdict {verdict}")
    if reasons:
        print(f"lock: reasons {', '.join(sorted(set(reasons)))}")


def declaration_of(root: Path | None = None) -> Declaration:
    """Read the lock declaration from a tree.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.

    Returns:
        The declaration.

    Raises:
        LockError: If it cannot be read or parsed.

    Exposed so that the contract test can assert facts about *this* repository's
    declaration without repeating how to find it.
    """
    base = REPO_ROOT if root is None else root
    text = _read(base, CONFIGURATION_FILE)
    if text is None:
        msg = f"{CONFIGURATION_FILE} could not be read"
        raise LockError(msg)
    return parse_declaration(text)


def lock_of(root: Path | None = None) -> Lock:
    """Read the committed development lock from a tree.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.

    Returns:
        The lock.

    Raises:
        LockError: If the declaration or the lock cannot be read or parsed.
    """
    base = REPO_ROOT if root is None else root
    declaration = declaration_of(base)
    text = _read(base, declaration.dev_path)
    if text is None:
        msg = f"{declaration.dev_path} could not be read"
        raise LockError(msg)
    return parse_lock(text, path=declaration.dev_path)
