"""One verdict for a whole CI run, from the jobs and the evidence they published.

``tools/quality/evidence`` answers "was this tree good, on this machine". This
package answers the different question a branch protection rule asks: **did every
required job actually run, and did the evidence it published say yes.**

The distinction is not pedantry. GitHub reports a job that never ran as
``skipped``, and a skipped required check is reported to branch protection as
something other than a failure. A rule that trusts the check view alone is
therefore satisfied by a workflow that did nothing at all — which is the failure
mode this package exists to close, and why every classification here is
fail-closed.

**Two integrity layers, and neither contains the other.** A file-level manifest
(``checksums.sha256``) is computed *before* upload and travels *inside* the
artifact. The artifact's own SHA-256 is computed *by GitHub* at upload and can
only be known *after* it. An artifact carrying its own digest is impossible, so
the digest is carried in a job output and shown in the summary instead. See
ADR-0042.

Reads the evidence package rather than re-implementing it. The aggregate does not
parse JUnit or coverage: it re-runs ``python -m tools.quality.evidence verify``
against the bytes CI published, which already checks the manifest digest, the
checksums, count consistency and redaction.
"""

from tools.quality.workflow.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    EXIT_USAGE,
    run_aggregate,
)
from tools.quality.workflow.plan import (
    Configuration,
    WorkflowError,
    classify,
    job_verdicts,
    read_configuration,
    read_needs,
)
from tools.quality.workflow.report import SCHEMA, SCHEMA_VERSION, build, render_summary

__all__ = [
    "EXIT_GATE_FAILED",
    "EXIT_OK",
    "EXIT_UNMEASURED",
    "EXIT_USAGE",
    "SCHEMA",
    "SCHEMA_VERSION",
    "Configuration",
    "WorkflowError",
    "build",
    "classify",
    "job_verdicts",
    "read_configuration",
    "read_needs",
    "render_summary",
    "run_aggregate",
]
