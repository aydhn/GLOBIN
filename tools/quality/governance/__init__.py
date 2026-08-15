"""Whether this repository's governance arrangement still describes the repository.

Phase 014 built the detection — a content secret scanner, a generated SBOM, a
vulnerability audit, CodeQL, secret scanning with push protection. What it did
not build was the layer around them: who is answerable for a change, how a
security-relevant change is recognised as one, and where a vulnerability report
goes on a repository that is now public.

Those are files — ``.github/CODEOWNERS``, ``SECURITY.md``, the issue chooser, the
change template — and files decay in a way nothing else here notices. A workflow
is added and no owner covers it. A scanner's configuration moves and the
sensitive-path inventory does not. A security policy loses the section naming its
reporting channel. Every one of those leaves a repository that looks governed and
is not, and none of them fails a test that was written before they happened.

**So the arrangement is declared, and the declaration is checked against the
tree in both directions.** ``docs/engineering/governance.toml`` is what a human
wrote down; this package compares it with what is actually there. A declared path
that no longer exists and a real workflow nobody owns are both findings, and the
second is the one that decays quietly.

**Offline, entirely.** Every check here reads the working tree, so the gate runs
without a network and so do its tests (ADR-0024). The half of governance that is
a *platform* question — whether private vulnerability reporting is switched on,
whether the ruleset still exists — belongs to
:mod:`tools.quality.supply.capability`, which already holds the credential and
the network for it. Two probes would be two things to keep in step.

**What is not decided here.** The run-level verdict belongs to
``tools/quality/workflow`` (ADR-0042); this gate reports its own. The reasoning
behind the arrangement is ``docs/security/GOVERNANCE.md`` and ADR-0047, and this
package restates neither — it asserts them.
"""

from tools.quality.governance.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    run_governance,
)
from tools.quality.governance.manifest import REASONS, SCHEMA, SCHEMA_VERSION
from tools.quality.governance.plan import Declaration, GovernanceError, Rule, SensitivePath

__all__ = [
    "EXIT_GATE_FAILED",
    "EXIT_OK",
    "EXIT_UNMEASURED",
    "REASONS",
    "SCHEMA",
    "SCHEMA_VERSION",
    "Declaration",
    "GovernanceError",
    "Rule",
    "SensitivePath",
    "run_governance",
]
