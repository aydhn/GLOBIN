"""The aggregate document, and the summary a person reads.

Pure: building takes values and returns a document, rendering takes a document
and returns text. The same split — and the same digest rule — as
``tools/quality/evidence/manifest.py``, whose :func:`~tools.quality.evidence.manifest.render`
and :func:`~tools.quality.evidence.manifest.digest` are reused rather than
rewritten. Two canonical JSON writers in one repository would be two things to
keep agreeing.

**Three sections, for the same reason the evidence manifest has three.** ``run``
holds what the run *was* — the commit, the workflow, the artifact and its digest.
``jobs`` holds one entry per required job. ``gates`` holds what the published
evidence concluded. A reader comparing two aggregates knows immediately which
differences are about the code and which are about the run.

**The artifact digest lives here and not in the artifact.** GitHub computes it
when the upload completes, so nothing inside the bundle can contain it — an
artifact whose manifest included its own digest would be a file that had to
contain its own hash. The bundle carries per-file checksums, computed before
upload; this document carries the bundle's digest, learned after. ADR-0042
records the split.

Everything rendered is ASCII, for the reason ``tools/quality/execution/gate.py``
gives: a console codepage that cannot render a character turns a report into a
traceback, and this runs on Windows.
"""

from collections.abc import Mapping
from typing import Final

from tools.quality.evidence.manifest import digest as seal
from tools.quality.evidence.manifest import render
from tools.quality.execution.plan import Verdict

SCHEMA: Final[str] = "globin.workflow.aggregate"
"""Identifies what kind of document this is, so an evidence manifest fed to the
aggregate reader is refused by name rather than by a missing key."""

SCHEMA_VERSION: Final[int] = 1
"""The first version. Bumped whenever the document changes shape, and inside the
digested payload so a canonicalisation change cannot collide with an older digest.

The rule ``globin.domain.serialization`` states for everything GLOBIN persists —
an unknown version is refused rather than read — applies to this document too.
It starts at one because zero would read as "not yet versioned".
"""

UNKNOWN: Final[str] = "unknown"
"""What a run field says when CI did not supply it. Never blank: a blank cell in
a summary reads as a value somebody forgot to look at rather than one that was
not there."""

REPRODUCTION: Final[tuple[tuple[str, str], ...]] = (
    ("Everything the gate checks", "powershell -ExecutionPolicy Bypass -File scripts/verify.ps1"),
    ("The canonical gate alone", "python -m tools.quality full"),
    ("Write the evidence", "python -m tools.quality evidence"),
    ("Check the evidence already written", "python -m tools.quality.evidence verify"),
    ("This aggregate, locally", "python -m tools.quality aggregate"),
)
"""Commands a reader can run to reproduce what CI did.

Every one is a real command in ``tools/quality/commands.py`` or
``scripts/verify.ps1``, and ``tests/contract`` checks that each still resolves —
a troubleshooting section naming a command that does not exist is worse than no
section, because it costs the reader the time to find out.
"""


def build(
    *,
    run: dict[str, object],
    jobs: Mapping[str, Verdict],
    gates: Mapping[str, object],
    verdict: Verdict,
) -> dict[str, object]:
    """Assemble the aggregate document and seal it.

    Args:
        run: What the run was — commit, workflow, artifact, digest.
        jobs: One verdict per required job.
        gates: What the published evidence concluded, copied from its manifest.
        verdict: The overall answer.

    Returns:
        The document, with its digest set.

    The verdict is recorded rather than left to be recomputed by a reader. A
    consumer that had to re-derive it would be a second implementation of the
    rule, and the two would eventually disagree about a run nobody could rerun.
    """
    document: dict[str, object] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "run": dict(run),
        "jobs": {job: str(result) for job, result in jobs.items()},
        "gates": dict(gates),
        "verdict": str(verdict),
    }
    document["digest"] = seal(document)
    return document


def render_document(document: dict[str, object]) -> str:
    """Encode the aggregate so two writers cannot disagree about bytes.

    Args:
        document: The aggregate.

    Returns:
        One line of JSON followed by a newline.
    """
    return render(document)


def render_summary(document: dict[str, object]) -> str:
    """Render the aggregate as a GitHub step summary.

    Args:
        document: The aggregate, as :func:`build` produced it.

    Returns:
        Markdown, newline-terminated.

    Short by construction, like ``tools/quality/evidence/summary.py``: the
    verdict, which job failed, what the evidence measured, and how to reproduce
    it. The stack traces and the thousand test names are in the artifact, which
    is where somebody who has decided to care will go.
    """
    run = _section(document, "run")
    jobs = _section(document, "jobs")
    gates = _section(document, "gates")
    verdict = str(document.get("verdict", Verdict.UNMEASURED))

    lines = [
        "## GLOBIN quality gate",
        "",
        f"**{verdict.upper()}** - commit `{run.get('commit', UNKNOWN)}`, "
        f"run {run.get('run_id', UNKNOWN)} attempt {run.get('run_attempt', UNKNOWN)}",
        "",
        "| Required job | Result |",
        "|---|---|",
    ]
    lines.extend(f"| {job} | {_verdict(jobs[job])} |" for job in sorted(jobs))

    if gates:
        lines.extend(["", "| Evidence gate | Result | Findings |", "|---|---|---|"])
        lines.extend(
            f"| {name} | {_verdict(_passed(gates[name]))} | {_findings(gates[name])} |"
            for name in sorted(gates)
        )

    lines.extend(
        [
            "",
            "| Evidence | Value |",
            "|---|---|",
            f"| Artifact | `{run.get('artifact', UNKNOWN)}` |",
            f"| Artifact digest | `{run.get('artifact_digest', UNKNOWN)}` |",
            f"| Retention | {run.get('retention_days', UNKNOWN)} days |",
            f"| Manifest | {run.get('evidence', UNKNOWN)} |",
        ]
    )

    problems = document.get("problems")
    if isinstance(problems, list) and problems:
        lines.extend(["", "### What went wrong", ""])
        lines.extend(f"- {problem}" for problem in problems)

    lines.extend(["", "### Reproducing this locally", "", "| Step | Command |", "|---|---|"])
    lines.extend(f"| {label} | `{command}` |" for label, command in REPRODUCTION)

    return "\n".join(lines) + "\n"


def _section(document: dict[str, object], name: str) -> dict[str, object]:
    """One section of the aggregate, or an empty one.

    Args:
        document: The aggregate.
        name: The section's key.

    Returns:
        The section. A missing or malformed one renders as blanks rather than
        raising: a summary that crashed would take the diagnostics with it, which
        is ``evidence/summary.py``'s reasoning and holds here for the same reason.
    """
    section = document.get(name)
    return section if isinstance(section, dict) else {}


def _passed(entry: object) -> str:
    """Read one evidence gate's verdict out of its manifest entry.

    Args:
        entry: The recorded gate.

    Returns:
        The verdict as one of :class:`~tools.quality.execution.plan.Verdict`'s
        spellings. A gate that did not say is unmeasured, never blank.
    """
    if not isinstance(entry, dict):
        return str(Verdict.UNMEASURED)
    passed = entry.get("passed")
    if passed is True:
        return str(Verdict.PASSED)
    if passed is False:
        return str(Verdict.FAILED)
    return str(Verdict.UNMEASURED)


def _findings(entry: object) -> str:
    """How many things an evidence gate found.

    Args:
        entry: The recorded gate.

    Returns:
        The count, or ``-`` where the gate counts nothing. Coverage has no
        findings, and a blank there would read as zero of them.
    """
    if not isinstance(entry, dict):
        return "-"
    findings = entry.get("findings")
    return str(findings) if isinstance(findings, int) and not isinstance(findings, bool) else "-"


def _verdict(value: object) -> str:
    """Spell a verdict for the summary.

    Args:
        value: The recorded verdict.

    Returns:
        ``passed``, ``FAILED`` or ``NOT RUN``. The two that are not a pass are
        shouted, because a table of lowercase words is one a reader skims.
    """
    text = str(value)
    if text == str(Verdict.PASSED):
        return "passed"
    if text == str(Verdict.FAILED):
        return "FAILED"
    return "NOT RUN"
