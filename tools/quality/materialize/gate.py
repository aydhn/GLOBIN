"""Sequencing the offline materialization checks and writing what they concluded.

The only module in this package that touches the world. Everything it decides is
decided by :mod:`tools.quality.materialize.plan`, which is pure; this reads the
lock, hashes the wheelhouse and writes the manifest.

**It reaches no network**, which is what lets it live inside
``python -m tools.quality full``. The two subcommands that do reach one --
``fetch`` and ``cleanroom`` -- are deliberately outside that command and carry
the same capitalised warning ``tools/quality/lock/cli.py`` uses.

Artefact selection is ``packaging.pylock``'s, handed **explicit tags built from
the declared target** rather than being allowed to default to ``sys_tags()``.
Defaulting would make this gate answer "could this machine install it", which is
machine-specific -- and would make ``full`` reject the committed lock on the 3.12
matrix leg.
"""

import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from packaging.tags import Tag

from tools.quality.evidence.redaction import describe as describe_findings
from tools.quality.evidence.redaction import scan as scan_for_secrets
from tools.quality.execution.plan import Verdict
from tools.quality.materialize import manifest as manifest_module
from tools.quality.materialize.cache import CacheError, Wheelhouse
from tools.quality.materialize.plan import (
    CacheKey,
    MaterializationPlan,
    PlanState,
    cache_key,
    offline_problems,
    plan_for,
)

SHA_LENGTH: Final[int] = 40
"""How long a Git object name is."""

LOCK_POLICY: Final[str] = "docs/engineering/lock-policy.toml"
"""Where the declared target lives."""

OUTPUT_DIRECTORY: Final[str] = ".globin/materialize"
"""Where the manifest is written, relative to the repository root."""

EXIT_OK: Final[int] = 0
EXIT_GATE_FAILED: Final[int] = 1
EXIT_USAGE: Final[int] = 2
EXIT_UNMEASURED: Final[int] = 3

DELIVERED_PHASE: Final[int] = 29
"""The phase this gate was delivered in.

Compared with ``<=`` against the roadmap frontier and never with ``==``: the
direction that matters is that a gate must never claim more has shipped than
actually has, and an equality goes stale the moment the frontier moves.
"""

_STATE_REASONS: Final[Mapping[PlanState, str]] = {
    PlanState.INCOMPLETE: manifest_module.REASON_ARTEFACT_MISSING,
    PlanState.CORRUPT: manifest_module.REASON_ARTEFACT_CORRUPT,
    PlanState.UNHASHED: manifest_module.REASON_ARTEFACT_UNHASHED,
    PlanState.INCOMPATIBLE: manifest_module.REASON_ARTEFACT_INCOMPATIBLE,
    PlanState.SOURCE_ONLY: manifest_module.REASON_SOURCE_FORBIDDEN,
}
"""Which reason code each unsatisfiable state contributes."""


def commit_of(root: Path) -> str:
    """The commit under test, read without starting a process.

    Args:
        root: The repository root.

    Returns:
        The forty-character SHA, or ``"unknown"``.

    Read from ``.git`` directly, exactly as the other gates do, so that a
    manifest can be produced in a tree with no Git on the path.
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


def declared_target(root: Path) -> tuple[tuple[Tag, ...], bool, str]:
    """The tags and source policy the lock policy declares.

    Args:
        root: The repository root.

    Returns:
        The tags an artefact must serve **in priority order**, whether a source
        build is permitted, and a problem sentence which is empty when the
        declaration was read.

    **An ordered tuple rather than a set, and the order is meaning rather than
    determinism.** PEP 425 tag order *is* preference: the first tag a wheel
    matches is the wheel that should be chosen, so handing ``select`` an
    unordered collection would ask it to pick without telling it what "better"
    means. ``Tag`` is also deliberately unorderable in ``packaging``, which is
    the library declining to invent a preference of its own -- so sorting one is
    not merely wrong here, it does not typecheck.

    **Machine-independent by construction.** Every tag is built from the
    declaration rather than from this interpreter, so the same lock produces the
    same verdict on a 3.12 runner, a 3.14 runner and a Linux development box.
    """
    try:
        document = tomllib.loads((root / LOCK_POLICY).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as fault:
        return ((), False, f"{LOCK_POLICY} could not be read: {fault}")
    target = document.get("target")
    policy = document.get("policy")
    if not isinstance(target, dict) or not isinstance(policy, dict):
        return ((), False, f"{LOCK_POLICY} declares no target or no policy")
    minor = str(target.get("minor_line", "")).replace(".", "")
    platform = str(target.get("platform_tag", ""))
    free_threaded = bool(target.get("free_threaded", False))
    if not minor or not platform or not minor.isdigit():
        return ((), False, f"{LOCK_POLICY} declares an incomplete target")

    major, line = minor[0], int(minor[1:])
    interpreter = f"cp{minor}"
    abi = f"{interpreter}t" if free_threaded else interpreter

    ordered: list[Tag] = [Tag(interpreter, abi, platform)]
    if not free_threaded:
        # Descending, because a wheel built against a newer stable ABI is a
        # better match than one built against an older. `abi3` is skipped
        # entirely on a free-threaded build: the limited API is not offered
        # there, which is the trap ADR-0052 recorded.
        ordered += [
            Tag(f"cp{major}{candidate}", "abi3", platform) for candidate in range(line, 1, -1)
        ]
    ordered += [
        Tag(interpreter, "none", platform),
        Tag(interpreter, "none", "any"),
        Tag(f"py{minor}", "none", "any"),
        Tag(f"py{major}", "none", "any"),
    ]
    return (tuple(ordered), bool(policy.get("allow_source", False)), "")


def selections_from(
    lock_text: str, tags: tuple[Tag, ...]
) -> tuple[Sequence[tuple[str, str, str, Sequence[tuple[str, str]], bool]], str]:
    """Ask the reference implementation which artefact serves each distribution.

    Args:
        lock_text: The lock document.
        tags: The tags an artefact must serve.

    Returns:
        One selection per distribution and a problem sentence, which is empty
        when the lock was read.

    ``Pylock.select`` is handed the tags explicitly rather than being allowed to
    default to ``sys_tags()``, which is what keeps this verdict the same on every
    runner.

    **It is all-or-nothing, which was measured rather than assumed.** ``select``
    raises as soon as *any* package has no artefact serving the tags, instead of
    yielding the rest and omitting that one. So a single unservable distribution
    is reported here as a lock-level problem naming that package, and
    :attr:`~tools.quality.materialize.plan.PlanState.INCOMPATIBLE` is reached
    through the pure planning API rather than through this path. That is a
    defensible answer for a gate: an environment that cannot be fully built is
    not partly buildable.
    """
    from packaging.pylock import (
        PackageSdist,
        PackageWheel,
        Pylock,
        PylockValidationError,
    )

    try:
        lock = Pylock.from_dict(tomllib.loads(lock_text))
    except (tomllib.TOMLDecodeError, PylockValidationError) as fault:
        return ((), f"the lock could not be read: {fault}")

    served: dict[str, tuple[str, str, str, Sequence[tuple[str, str]], bool]] = {}
    try:
        for package, artefact in lock.select(tags=tags):
            name = str(package.name)
            version = "" if package.version is None else str(package.version)
            if isinstance(artefact, (PackageWheel, PackageSdist)):
                hashes = tuple(
                    (str(algorithm), str(value))
                    for algorithm, value in dict(artefact.hashes).items()
                )
                served[name] = (
                    name,
                    version,
                    str(artefact.name or ""),
                    hashes,
                    isinstance(artefact, PackageSdist),
                )
            else:
                served[name] = (name, version, "", (), False)
    except Exception as fault:
        return ((), f"the lock could not be resolved against the target: {fault}")

    for package in lock.packages:
        served.setdefault(str(package.name), (str(package.name), "", "", (), False))
    return (tuple(sorted(served.values())), "")


def _finding(problems: Sequence[str], *, measured: bool = True) -> dict[str, object]:
    """One finding, in the shape every gate writes.

    Args:
        problems: One sentence per problem.
        measured: Whether the check could run at all.

    Returns:
        The finding.
    """
    if not measured:
        verdict = Verdict.UNMEASURED
    elif problems:
        verdict = Verdict.FAILED
    else:
        verdict = Verdict.PASSED
    return {"verdict": str(verdict), "problems": list(problems)}


def run_materialize(
    root: Path | None = None,
    *,
    lock_name: str = "pylock.toml",
    wheelhouse: Path | None = None,
) -> int:
    """Check whether the committed lock could be materialized offline.

    Args:
        root: The repository root. Defaults to this file's grandparent's parent.
        lock_name: Which lock to plan from.
        wheelhouse: Where artefacts live. Defaults to the declared wheelhouse.

    Returns:
        The exit code.

    Reaches no network. An empty wheelhouse is a real answer -- ``incomplete``,
    reported per artefact -- rather than a reason to fetch.
    """
    here = Path(__file__).resolve().parents[3] if root is None else root
    tags, allow_source, target_problem = declared_target(here)

    try:
        lock_text = (here / lock_name).read_text(encoding="utf-8")
    except OSError as fault:
        lock_text = ""
        lock_problem = f"{lock_name} could not be read: {fault}"
    else:
        lock_problem = ""

    selections: Sequence[tuple[str, str, str, Sequence[tuple[str, str]], bool]] = ()
    if not target_problem and not lock_problem:
        selections, lock_problem = selections_from(lock_text, tags)

    measured = not target_problem and not lock_problem
    keys: tuple[CacheKey, ...] = ()
    digests: dict[str, str] = {}
    cache_problem = ""
    plan = MaterializationPlan(artefacts=(), allow_source=allow_source)

    if measured:
        keys = tuple(
            key
            for name, version, filename, hashes, _ in selections
            if filename
            and (key := cache_key(name=name, version=version, filename=filename, hashes=hashes))
            is not None
        )
        house = Wheelhouse(root=wheelhouse or (here / ".globin" / "wheelhouse"))
        try:
            digests = house.digests(keys)
        except CacheError as fault:
            cache_problem = str(fault)
        plan = plan_for(selections, digests, allow_source=allow_source)

    # `nothing_fetched` is deliberately narrow: it means every shortfall is
    # merely that the artefact has not been fetched. An artefact that is
    # UNHASHED, INCOMPATIBLE, SOURCE_ONLY or CORRUPT is a genuine fault about
    # the lock or the cache, and fetching would not fix any of them -- so those
    # fail even on a machine whose wheelhouse is empty.
    shortfalls = {artefact.state for artefact in plan.unsatisfiable()}
    nothing_fetched = (
        measured and not digests and bool(plan.artefacts) and shortfalls <= {PlanState.INCOMPLETE}
    )
    findings = {
        "target": _finding([target_problem] if target_problem else []),
        "lock": _finding([lock_problem] if lock_problem else [], measured=not target_problem),
        "cache": _finding([cache_problem] if cache_problem else [], measured=measured),
        "offline": _finding(
            [] if (not measured or nothing_fetched) else list(offline_problems(plan)),
            measured=measured and not nothing_fetched,
        ),
    }

    reasons = sorted(
        {
            _STATE_REASONS[artefact.state]
            for artefact in plan.unsatisfiable()
            if artefact.state in _STATE_REASONS
        }
    )
    if target_problem:
        reasons.append(manifest_module.REASON_DECLARATION_UNREADABLE)
    if lock_problem:
        reasons.append(manifest_module.REASON_LOCK_UNREADABLE)

    # An EMPTY wheelhouse is `unmeasured`, not `failed`, and the distinction is
    # the whole difference between a useful gate and one that is red on every
    # clean checkout. Artefacts are not committed -- they are hundreds of
    # megabytes -- so a fresh clone has nothing to plan against and the honest
    # answer is that offline readiness has not been established, not that it has
    # been established to be absent. `drift` draws exactly this line with an
    # unrecorded baseline, and exits 3 for the same reason.
    #
    # A wheelhouse that HAS been populated and is wrong still fails. That is the
    # case worth failing: somebody fetched artefacts and one of them is not what
    # the lock names.
    if nothing_fetched:
        verdict = Verdict.UNMEASURED
        reasons = []
    elif not measured:
        verdict = Verdict.UNMEASURED
    elif reasons:
        verdict = Verdict.FAILED
    else:
        verdict = Verdict.PASSED
    run = {
        "commit": commit_of(here),
        "lock": lock_name,
        "declaration": LOCK_POLICY,
        "tags": len(tags),
        "allow_source": allow_source,
        "artefacts": len(plan.artefacts),
        "cached": len(digests),
        "plan": plan.as_record(),
    }
    document = manifest_module.build(
        run=run,
        findings=findings,
        verdict={"verdict": str(verdict), "reasons": sorted(set(reasons))},
    )
    rendered = manifest_module.render(document)

    if rendered != manifest_module.render(
        manifest_module.build(
            run=run,
            findings=findings,
            verdict={"verdict": str(verdict), "reasons": sorted(set(reasons))},
        )
    ):
        print("materialize: two renderings of one run disagreed")
        return EXIT_GATE_FAILED
    leaks = scan_for_secrets(manifest_module.MANIFEST_NAME, rendered)
    if leaks:
        print("materialize: the manifest matched a credential pattern")
        print(describe_findings(leaks))
        return EXIT_GATE_FAILED

    directory = here / OUTPUT_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    (directory / manifest_module.MANIFEST_NAME).write_text(rendered, encoding="utf-8", newline="\n")

    for name, finding in sorted(findings.items()):
        print(f"materialize: {name}: {finding['verdict']}")
        problems = finding["problems"]
        if isinstance(problems, list):
            for problem in problems:
                print(f"  - {problem}")
    if nothing_fetched:
        print(
            f"materialize: the wheelhouse holds none of the {len(plan.artefacts)} "
            f"artefacts this lock names, so offline readiness is unestablished "
            f"rather than absent. Populate it deliberately; nothing here fetches."
        )
    print(f"materialize: verdict {verdict}")

    if verdict is Verdict.UNMEASURED:
        return EXIT_UNMEASURED
    return EXIT_OK if verdict is Verdict.PASSED else EXIT_GATE_FAILED
