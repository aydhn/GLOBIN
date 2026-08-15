"""Deterministic quality evidence: JUnit XML, coverage, diagnostics, a manifest and checksums.

A quality run's result should not be only a colour in a terminal somebody
watched. This package turns one into files a machine can read and a person can
check six months later: which commit, which interpreter, which platform, how many
tests ended each way, what was slow, what coverage was measured against which
floor, what Ruff and mypy found, which gates failed, and what the evidence's own
digests are.

**Five gates, and all of them run.** The suite, its coverage, `ruff check`,
`ruff format --check` and `mypy`. Each is recorded separately, so "the suite
failed" and "the types failed" are never one undifferentiated failure. Collecting
every result before returning non-zero is the one deliberate departure from the
fail-fast rule `QUALITY_GATES.md` sets for every other command, and ADR-0040 is
where it is argued.

**Why this exists rather than a plugin.** ADR-0032 permits verification tooling
in a phase that does not name it, under six conditions, and condition 3 is that
it adds no dependency. A reporting plugin would be one. Everything here is
either native to tools the repository already pins — pytest writes JUnit XML with
``--junitxml``, coverage.py writes XML, JSON, text and HTML itself, Ruff writes
JSON with ``--output-format=json`` and mypy with ``--output=json`` — or standard
library: ``xml.etree`` to read, ``hashlib`` to digest, ``json`` to render.

**What it is not.** It is not a coverage implementation: coverage.py's own
numbers are copied, never recomputed. It is not a second linter: a diagnostic is
copied rather than assessed, and whether a tool passed is its exit code's
business. It is not a repository secret scanner: `.pre-commit-config.yaml` runs
one, `docs/security/SECURITY_BASELINE.md` owns the policy, and the check here
looks only at the files this package produced. It is not signing or provenance —
a checksum proves integrity, not origin, and key material needs a phase that has
thought about key material.

**The rule worth knowing before reading the code.** Evidence is produced whatever
the gates did, and producing it never softens what they did. A failing run writes
everything and then exits non-zero.

**And the one worth knowing second.** No file written here carries an absolute
path. Ruff reports one for every diagnostic, `coverage xml` writes one into a
``<source>`` element, and on this host every absolute path contains the account
holder's full name — so each is normalised before it is written, and
:mod:`~tools.quality.evidence.redaction` fails verification if one survives.

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
