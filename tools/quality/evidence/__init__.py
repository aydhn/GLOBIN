"""Deterministic test evidence: JUnit XML, coverage, a manifest and checksums.

A test run's result should not be only a colour in a terminal somebody watched.
This package turns one into files a machine can read and a person can check six
months later: which commit, which interpreter, which platform, how many tests
ended each way, what was slow, what coverage was measured against which floor,
which gate failed, and what the evidence's own digests are.

**Why this exists rather than a plugin.** ADR-0032 permits verification tooling
in a phase that does not name it, under six conditions, and condition 3 is that
it adds no dependency. A reporting plugin would be one. Everything here is
either native to tools the repository already pins — pytest writes JUnit XML
with ``--junitxml``, coverage.py writes XML and JSON itself — or standard
library: ``xml.etree`` to read, ``hashlib`` to digest, ``json`` to render.

**What it is not.** It is not a coverage implementation: coverage.py's own
numbers are copied, never recomputed. It is not a repository secret scanner:
`.pre-commit-config.yaml` runs one, Phase 015 owns the policy, and the check here
looks only at the files this package produced. It is not signing or provenance —
a checksum proves integrity, not origin, and key material needs a phase that has
thought about key material.

**The rule worth knowing before reading the code.** Evidence is produced whatever
the suite did, and producing it never softens what the suite did. A failing run
writes everything and then exits non-zero.

``python -m tools.quality evidence`` runs it; ``python -m tools.quality.evidence
verify`` re-reads what was written. Output goes to ``.globin/evidence``, which is
already ignored by Git and already asserted uncommittable.
"""

from tools.quality.evidence.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    EXIT_USAGE,
    run_evidence,
    verify_evidence,
)
from tools.quality.evidence.junit import EvidenceError

__all__ = [
    "EXIT_GATE_FAILED",
    "EXIT_OK",
    "EXIT_UNMEASURED",
    "EXIT_USAGE",
    "EvidenceError",
    "run_evidence",
    "verify_evidence",
]
