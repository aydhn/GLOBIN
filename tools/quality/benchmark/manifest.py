"""The benchmark manifest: what was asked, what this host measured, and its digest.

The same document shape every other gate writes — ``schema``, ``schema_version``,
``phase``, ``run``, ``findings``, ``verdict``, ``digest`` — so a reader who has
seen one has seen them all.

**This is the one manifest in the repository that is not byte-stable across runs,
and it says so rather than hoping nobody notices.** A timing is a measurement, and
measurements move. The document is therefore split so that a reader knows which
half to compare: ``run.observed`` holds nanoseconds, which differ every run, and
``findings`` holds verdicts, which are a pure function of the contract and those
nanoseconds and are recomputed on every read. The determinism check every other
gate applies to its whole document is applied here to the contract-derived half
only, and ``gate.py`` says which.

**No wall clock and no absolute path**, exactly as elsewhere. A GPU model is
recorded because it answers the roadmap's question about the hardware; nothing
identifying the machine's owner appears, and
:func:`tools.quality.evidence.redaction.scan` runs over the rendered document
rather than trusting that.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Final

SCHEMA: Final[str] = "globin.benchmark.manifest"
"""What kind of document this is."""

SCHEMA_VERSION: Final[int] = 1
"""The version of that document's shape."""

PHASE: Final[int] = 24
"""The phase that introduced this gate."""

MANIFEST_NAME_DEFAULT: Final[str] = "benchmark-manifest.json"
"""The manifest's filename, declared beside the schema it names."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""How a digest announces its algorithm."""

DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover: itself."""

REASON_DECLARATION_UNREADABLE: Final[str] = "BENCHMARK_DECLARATION_UNREADABLE"
"""The contract could not be parsed at all."""

REASON_TARGET_DIVERGED: Final[str] = "BENCHMARK_TARGET_DIVERGED"
"""The contract was written against a host the runtime contract does not declare."""

REASON_WORKLOAD_DUPLICATED: Final[str] = "BENCHMARK_WORKLOAD_DUPLICATED"
"""One workload is declared more than once, so the manifest would hold two answers."""

REASON_WORKLOAD_MALFORMED: Final[str] = "BENCHMARK_WORKLOAD_MALFORMED"
"""A declared value is one this harness cannot act on."""

REASON_PHASE_MISPLACED: Final[str] = "BENCHMARK_PHASE_MISPLACED"
"""A workload names a phase that is already delivered, or beyond the programme."""

REASON_WORKLOAD_ERRORED: Final[str] = "BENCHMARK_WORKLOAD_ERRORED"
"""A workload was attempted and failed, which is never a pass.

Distinct from a backend simply being unavailable. ADR-0045's argument is that *we
asked and it is not there* and *we could not ask* are different facts, and only
the second is a defect.
"""

REASON_MANIFEST_NONDETERMINISTIC: Final[str] = "BENCHMARK_MANIFEST_NONDETERMINISTIC"
"""Two derivations of the same measurements disagreed.

Narrower than the same reason in every other gate, and deliberately so. What is
compared here is the *findings* half — the verdicts derived from the contract and
the recorded numbers — not the measurements themselves, which are expected to
differ. A disagreement therefore means the derivation is not a function of its
inputs, which is a defect in this package rather than noise on the host.
"""

REASON_MANIFEST_LEAKAGE: Final[str] = "BENCHMARK_MANIFEST_LEAKAGE"
"""The rendered manifest carried something that must not be published."""

REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_DECLARATION_UNREADABLE,
        REASON_TARGET_DIVERGED,
        REASON_WORKLOAD_DUPLICATED,
        REASON_WORKLOAD_MALFORMED,
        REASON_PHASE_MISPLACED,
        REASON_WORKLOAD_ERRORED,
        REASON_MANIFEST_NONDETERMINISTIC,
        REASON_MANIFEST_LEAKAGE,
    }
)
"""Every reason this gate can give, as a closed set.

Closed so a contract test can compare it against what the gate can actually emit,
in both directions: a reason the gate produces and this set does not name is a
hole, and a name here nothing produces is a claim about a check that does not
exist.
"""


class BenchmarkManifestError(Exception):
    """A manifest could not be read, or did not verify.

    Kept here rather than shared with :mod:`tools.quality.benchmark.plan`, for the
    reason every other gate's manifest gives about its own: a verifier that imports
    the package it verifies cannot report on one too broken to import.
    """


def render(document: Mapping[str, object]) -> str:
    """Render a manifest to its canonical form.

    Args:
        document: The manifest.

    Returns:
        One line of JSON with sorted keys, no incidental whitespace and no
        non-ASCII escape ambiguity, followed by a newline.
    """
    payload = dict(document)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def digest(document: Mapping[str, object]) -> str:
    """Digest every part of a manifest except the digest itself.

    Args:
        document: The manifest, with or without a digest already present.

    Returns:
        The digest, prefixed with its algorithm.
    """
    payload = {key: value for key, value in document.items() if key != DIGEST_KEY}
    return DIGEST_PREFIX + hashlib.sha256(render(payload).encode("utf-8")).hexdigest()


def build(
    *,
    run: Mapping[str, object],
    findings: Mapping[str, object],
    verdict: Mapping[str, object],
) -> dict[str, object]:
    """Assemble a manifest and stamp it with its digest.

    Args:
        run: What was asked — the commit, the contract, the method, the numbers.
        findings: What each check concluded.
        verdict: The overall result and the reasons for it.

    Returns:
        The manifest, digest included.
    """
    document: dict[str, object] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE,
        "run": dict(run),
        "findings": dict(findings),
        "verdict": dict(verdict),
    }
    document[DIGEST_KEY] = digest(document)
    return document


def load(text: str) -> dict[str, object]:
    """Read a manifest, refusing one that does not verify.

    Args:
        text: The rendered manifest.

    Returns:
        The manifest.

    Raises:
        BenchmarkManifestError: If the text is not a JSON object, is not this
            schema, is not this version, or does not match its own digest.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the benchmark manifest is not valid JSON: {fault}"
        raise BenchmarkManifestError(msg) from fault
    if not isinstance(document, dict):
        msg = f"the benchmark manifest is a {type(document).__name__}, expected an object"
        raise BenchmarkManifestError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"the manifest declares schema {document.get('schema')!r}, expected {SCHEMA!r}"
        raise BenchmarkManifestError(msg)
    if document.get("schema_version") != SCHEMA_VERSION:
        found = document.get("schema_version")
        msg = (
            f"the manifest declares version {found!r}, and this reader implements {SCHEMA_VERSION}"
        )
        raise BenchmarkManifestError(msg)
    recorded = document.get(DIGEST_KEY)
    expected = digest(document)
    if recorded != expected:
        msg = f"the manifest records {recorded!r} but its content digests to {expected!r}"
        raise BenchmarkManifestError(msg)
    return document
