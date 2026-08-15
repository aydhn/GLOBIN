"""The aggregate gate: one verdict, and the reasons behind it.

Runs in two places and reaches the same conclusion from the same code.

*In CI*, after every other job. It is handed ``toJSON(needs)`` and the digest of
the uploaded artifact, and it reads the evidence bundle that was downloaded back
out of that artifact — the published bytes, not a string a job reported about
itself.

*At a desk*, with neither. There is no ``needs`` context on a developer's
machine, so the gate falls back to the evidence the local run wrote. The verdict
comes from the same function either way, which is what stops CI and the developer
disagreeing about what "passed" means.

**Every unknown is a failure to pass, never a pass.** A required job that never
reported, an evidence manifest that will not load, a gate the evidence does not
mention, a version this code has not been taught — each produces
:data:`EXIT_UNMEASURED`. ``docs/engineering/QUALITY_GATES.md`` states the rule
this implements: a gate is either passed, failed, or not run, and "not run" never
reports as "passed".
"""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from tools.quality.evidence import gate as evidence_gate
from tools.quality.evidence.junit import EvidenceError
from tools.quality.evidence.manifest import digest, load
from tools.quality.execution.plan import Verdict, combine
from tools.quality.workflow.plan import (
    CI_VARIABLE,
    DIGEST_VARIABLE,
    NEEDS_VARIABLE,
    Configuration,
    WorkflowError,
    job_verdicts,
    load_configuration,
    read_needs,
)
from tools.quality.workflow.report import (
    SCHEMA,
    SCHEMA_VERSION,
    build,
    render_document,
    render_summary,
)

EXIT_OK: Final[int] = 0
"""Every required job passed and the published evidence agreed."""

EXIT_GATE_FAILED: Final[int] = 1
"""Something required failed. The tree is not good."""

EXIT_USAGE: Final[int] = 2
"""The command line was not understood."""

EXIT_UNMEASURED: Final[int] = 3
"""The result could not be determined, which is never a pass."""

REPORTS: Final[Path] = evidence_gate.REPO_ROOT / ".globin" / "workflow"
"""Where the aggregate is written.

Beside ``.globin/evidence`` and ``.globin/execution`` rather than inside either.
The aggregate is *about* the evidence, and writing it into the evidence directory
would put it inside the bundle whose digest it records — the circularity ADR-0042
exists to avoid.
"""

AGGREGATE_FILE: Final[str] = "aggregate-quality.json"
"""The machine-readable result. One name, no run identifier: the identity of a
run lives inside the document where it can be digested."""

SUMMARY_VARIABLE: Final[str] = "GITHUB_STEP_SUMMARY"
"""Where GitHub reads the human-readable summary from."""

MANIFEST_FILE: Final[str] = "evidence-manifest.json"
"""The evidence document this gate re-reads. Named here rather than imported
because the evidence package spells it inside a tuple of nine filenames, and
indexing into that by position would break the day a tenth is added."""


def expected_gates() -> tuple[str, ...]:
    """Which gates the published evidence must have recorded.

    Returns:
        The gate names, sorted.

    Derived from the evidence gate rather than listed here. ADR-0040 gives the
    evidence run five gates — the suite, its coverage, and the three tools it
    starts — and a second copy of that list would be one more thing to keep
    agreeing. Adding a sixth tool there makes it required here automatically,
    which is the direction the dependency should point.
    """
    tools = tuple(name for name, _file, _argv in evidence_gate.tool_commands())
    return tuple(sorted((*tools, "tests", "coverage")))


def run_aggregate(*, reports: Path | None = None, evidence: Path | None = None) -> int:
    """Decide whether this run passed, and write down why.

    Args:
        reports: Where to write the aggregate. Defaults to :data:`REPORTS`.
        evidence: Where to read the published evidence from. Defaults to the
            evidence gate's own directory, which is where CI downloads the
            artifact to and where a local run writes it.

    Returns:
        :data:`EXIT_OK`, :data:`EXIT_GATE_FAILED` or :data:`EXIT_UNMEASURED`.

    Writes the aggregate and the step summary before returning, so that a run
    which is about to fail still leaves behind the document explaining it. That
    ordering is the whole reason the summary is generated from the document
    rather than from the verdict.
    """
    directory = REPORTS if reports is None else reports
    evidence_directory = evidence_gate.REPORTS if evidence is None else evidence

    try:
        configuration = load_configuration()
    except WorkflowError as fault:
        print(f"[quality] configuration: {fault}")
        return EXIT_UNMEASURED

    problems: list[str] = []
    jobs, job_verdict = _job_results(configuration, problems)
    gates, gate_verdict = _evidence_results(evidence_directory, problems)
    verdict = combine([job_verdict, gate_verdict])

    document = build(
        run=_run_metadata(configuration, evidence_directory),
        jobs=jobs,
        gates=gates,
        verdict=verdict,
    )
    if problems:
        document["problems"] = problems
        document["digest"] = _resealed(document)

    _write(directory, document)
    _write_summary(document)
    _report(jobs, gates, problems, verdict)

    if verdict is Verdict.PASSED:
        return EXIT_OK
    return EXIT_GATE_FAILED if verdict is Verdict.FAILED else EXIT_UNMEASURED


def _job_results(
    configuration: Configuration, problems: list[str]
) -> tuple[dict[str, Verdict], Verdict]:
    """Read every required job's result out of the workflow context.

    Args:
        configuration: The declared requirements.
        problems: Appended to when something is wrong.

    Returns:
        The per-job verdicts, and their combination.

    On a developer's machine there is no context and there are no jobs, so this
    reports no verdict at all and lets the evidence decide. In CI a missing
    context is the opposite: the gate was asked to aggregate and was given
    nothing to aggregate, which is unmeasured.
    """
    raw = os.environ.get(NEEDS_VARIABLE, "").strip()
    if not raw:
        if os.environ.get(CI_VARIABLE):
            problems.append(
                f"{NEEDS_VARIABLE} was empty in CI, so no job result could be read at all"
            )
            return {}, Verdict.UNMEASURED
        return {}, Verdict.PASSED

    try:
        results = read_needs(raw)
    except WorkflowError as fault:
        problems.append(str(fault))
        return {}, Verdict.UNMEASURED

    verdicts = job_verdicts(results, required=configuration.required_jobs)
    problems.extend(
        f"required job '{job}' is {result}"
        for job, result in verdicts.items()
        if result is not Verdict.PASSED
    )
    return verdicts, combine(list(verdicts.values()))


def _evidence_results(directory: Path, problems: list[str]) -> tuple[dict[str, object], Verdict]:
    """Read what the published evidence concluded.

    Args:
        directory: Where the evidence bundle is.
        problems: Appended to when something is wrong.

    Returns:
        The manifest's ``gates`` section, and the verdict it implies.

    Three ways this refuses, and each is a real failure somebody would otherwise
    read as a pass: the manifest is absent, it will not load — which covers a
    wrong schema, an unknown version and a broken digest — or it records fewer
    gates than the evidence run is supposed to produce. The last is the one worth
    naming: an evidence run that crashed halfway can leave a manifest that parses
    and describes only the gates it reached.
    """
    path = directory / MANIFEST_FILE
    try:
        document = load(path.read_text(encoding="utf-8"))
    except OSError:
        problems.append(f"no evidence manifest at {_relative(path)}")
        return {}, Verdict.UNMEASURED
    except EvidenceError as fault:
        problems.append(f"evidence manifest is unusable: {fault}")
        return {}, Verdict.UNMEASURED

    section = document.get("gates")
    if not isinstance(section, Mapping):
        problems.append("evidence manifest records no gates section")
        return {}, Verdict.UNMEASURED

    gates = {str(name): entry for name, entry in section.items()}
    missing = [name for name in expected_gates() if name not in gates]
    if missing:
        problems.append(f"evidence manifest is missing gates: {', '.join(missing)}")
        return gates, Verdict.UNMEASURED

    verdicts = [_gate_verdict(entry) for entry in gates.values()]
    problems.extend(
        f"evidence gate '{name}' is {_gate_verdict(entry)}"
        for name, entry in sorted(gates.items())
        if _gate_verdict(entry) is not Verdict.PASSED
    )
    return gates, combine(verdicts)


def _gate_verdict(entry: object) -> Verdict:
    """Read one evidence gate's recorded verdict.

    Args:
        entry: The manifest entry.

    Returns:
        The verdict. ``passed`` absent or not a boolean is unmeasured, which is
        the state ADR-0040 gives a gate that did not run.
    """
    if not isinstance(entry, Mapping):
        return Verdict.UNMEASURED
    passed = entry.get("passed")
    if passed is True:
        return Verdict.PASSED
    if passed is False:
        return Verdict.FAILED
    return Verdict.UNMEASURED


def _run_metadata(configuration: Configuration, evidence: Path) -> dict[str, object]:
    """What this run was, for the document and the summary.

    Args:
        configuration: The declared requirements.
        evidence: Where the evidence bundle is.

    Returns:
        The ``run`` section.

    Read from the environment one variable at a time rather than by copying the
    CI context wholesale. A dump of everything GitHub sets is how a token reaches
    a published artifact, and this file is published.
    """
    return {
        "commit": os.environ.get("GITHUB_SHA", "unknown"),
        "workflow": os.environ.get("GITHUB_WORKFLOW", "unknown"),
        "run_id": os.environ.get("GITHUB_RUN_ID", "unknown"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "unknown"),
        "required_check": configuration.required_check,
        "artifact": configuration.artifact,
        "artifact_digest": os.environ.get(DIGEST_VARIABLE, "") or "not recorded",
        "retention_days": configuration.retention_days,
        "evidence": _relative(evidence / MANIFEST_FILE),
    }


def _relative(path: Path) -> str:
    """A path as this repository sees it.

    Args:
        path: An absolute path inside the repository.

    Returns:
        The repository-relative POSIX spelling, or just the filename when the
        path lies outside.

    Absolute paths never reach the document. One carries a user name on a
    developer's machine and a runner's directory layout in CI, and this file is
    published — the leak ADR-0040 decision 6 was written after finding.
    """
    try:
        return path.resolve().relative_to(evidence_gate.REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _resealed(document: dict[str, object]) -> str:
    """Recompute the digest after the problems list was added.

    Args:
        document: The aggregate.

    Returns:
        The digest covering everything except itself.

    The problems are part of the evidence, so they have to be inside the seal.
    Sealing twice costs one hash of a small document and keeps :func:`build`
    ignorant of a field only the gate knows how to fill.
    """
    return digest(document)


def _write(directory: Path, document: dict[str, object]) -> None:
    """Write the aggregate, leaving no half-written file behind.

    Args:
        directory: Where it goes.
        document: The aggregate.

    Written to a temporary name in the same directory and then moved into place.
    :func:`os.replace` is atomic when both paths are on one filesystem, which is
    what "same directory" buys, and it overwrites on Windows where
    :meth:`~pathlib.Path.rename` would raise. A reader therefore sees the previous
    aggregate or this one, never half of either — which matters because the step
    that uploads this file runs even when the step that wrote it failed.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / AGGREGATE_FILE
    staged = directory / f"{AGGREGATE_FILE}.partial"
    staged.write_text(render_document(document), encoding="utf-8", newline="\n")
    os.replace(staged, target)  # noqa: PTH105 - Path.rename is not atomic over an existing file


def _write_summary(document: dict[str, object]) -> None:
    """Append the step summary, when GitHub asked for one.

    Args:
        document: The aggregate.

    Does nothing when ``GITHUB_STEP_SUMMARY`` is unset, which is what makes the
    local and CI paths the same code rather than two implementations — the
    property ``tools/quality/evidence/gate.py`` already has.

    A summary that cannot be written is reported and does not change the verdict.
    The gate's answer is about the tree, and losing the cover page is not a reason
    to call a good tree bad — nor, since the verdict is decided before this runs,
    a way to make a bad one look good.
    """
    target = os.environ.get(SUMMARY_VARIABLE)
    if not target:
        return
    try:
        with Path(target).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(render_summary(document))
    except OSError as fault:
        print(f"[quality] summary: could not write it ({type(fault).__name__})")


def _report(
    jobs: Mapping[str, Verdict],
    gates: Mapping[str, object],
    problems: list[str],
    verdict: Verdict,
) -> None:
    """Print the short, actionable version.

    Args:
        jobs: Per-job verdicts.
        gates: What the evidence recorded.
        problems: What went wrong.
        verdict: The overall answer.

    ASCII only, and no dump of the document. Everything printed here is already
    in the aggregate; this is the part somebody reads in a terminal.
    """
    for job, result in jobs.items():
        print(f"[quality] job {job}: {result}")
    for name in sorted(gates):
        print(f"[quality] evidence {name}: {_gate_verdict(gates[name])}")
    for problem in problems:
        print(f"[quality] problem: {problem}")
    print(f"[quality] overall: {str(verdict).upper()}")


def read_aggregate(path: Path) -> dict[str, object]:
    """Read an aggregate back, for a caller that wants to inspect one.

    Args:
        path: The file.

    Returns:
        The document.

    Raises:
        WorkflowError: If it cannot be read, is not an object, or does not
            announce this schema at a version this code understands.

    Refusing an unrecognised version rather than reading it is the rule
    ``globin.domain.serialization`` states for everything GLOBIN persists, and
    ADR-0040 already applies to the evidence manifest.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as fault:
        msg = f"cannot read the aggregate: {type(fault).__name__} ({fault})"
        raise WorkflowError(msg) from fault
    if not isinstance(document, dict):
        msg = f"aggregate must be a JSON object, got {type(document).__name__}"
        raise WorkflowError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"aggregate announces schema {document.get('schema')!r}, expected {SCHEMA!r}"
        raise WorkflowError(msg)
    if document.get("schema_version") != SCHEMA_VERSION:
        msg = (
            f"aggregate is at schema version {document.get('schema_version')!r}; this reader "
            f"implements {SCHEMA_VERSION} and will not guess at another"
        )
        raise WorkflowError(msg)
    return document
