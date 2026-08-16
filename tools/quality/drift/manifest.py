"""The drift manifest: what diverged, what would repair it, and its digest.

The same document shape the other gates write — ``schema``, ``schema_version``,
``phase``, ``run``, ``findings``, ``verdict``, ``digest`` — so that a reader who
has seen one has seen them all, and so the digest rule is stated once per package
rather than invented per package.

**No wall clock, and no absolute path.** A drift manifest is the one document in
this repository most tempted by a timestamp, because drift is a claim about time.
It still records none: a manifest that changes because it was built on a different
day cannot be compared with itself, and the determinism check would be measuring
the clock rather than the host. What orders two measurements is the commit each was
taken at, which is recorded. Paths outside the repository are fingerprints, never
paths, because this manifest is uploaded as a public-repository artifact and every
absolute path on the development host carries the account holder's name.

**No configuration value, ever.** Drift detection reads whether a ``pip``
configuration source exists and which ``PIP_*`` variables are set by name. It never
reads what any of them says, for the reason
:mod:`tools.quality.runtime.gate` gives where it makes the same refusal: the name
says an override is in force, which is the fact worth having, and the value says
what it is, which is the fact worth not publishing. An index URL is the single most
likely place in this document for a credential to appear, and the way to keep one
out is not to read it.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Final

SCHEMA: Final[str] = "globin.drift.manifest"
"""What kind of document this is."""

SCHEMA_VERSION: Final[int] = 1
"""The version of that document's shape."""

PHASE: Final[int] = 19
"""The phase that introduced this gate."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""How a digest announces its algorithm."""

DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover: itself."""

BASELINE_SCHEMA: Final[str] = "globin.drift.baseline"
"""What kind of document a recorded baseline is.

A separate schema from the manifest rather than a reused one. They are read by
different code at different times and a reader pointed at the wrong file should
say so, which is only possible if the two announce themselves differently.
"""

REASON_DECLARATION_UNREADABLE: Final[str] = "DRIFT_DECLARATION_UNREADABLE"
"""The drift policy could not be parsed at all."""

REASON_POLICY_INCONSISTENT: Final[str] = "DRIFT_POLICY_INCONSISTENT"
"""A recorded repair verdict does not follow from the action recorded beside it."""

REASON_CLASS_UNDECLARED: Final[str] = "DRIFT_CLASS_UNDECLARED"
"""Something diverged that the policy does not classify, so nobody has judged it."""

REASON_BASELINE_UNREADABLE: Final[str] = "DRIFT_BASELINE_UNREADABLE"
"""A baseline exists but could not be read or did not verify, which is never a pass."""

REASON_OBSERVATION_UNAVAILABLE: Final[str] = "DRIFT_OBSERVATION_UNAVAILABLE"
"""The host could not be observed, so no comparison was possible."""

REASON_CONTRACT_VIOLATED: Final[str] = "DRIFT_CONTRACT_VIOLATED"
"""Drift has taken the environment outside the runtime contract."""

REASON_REPAIRABLE: Final[str] = "DRIFT_REPAIRABLE"
"""Drift was found that a bounded repair inside the environment would correct."""

REASON_RECREATE_REQUIRED: Final[str] = "DRIFT_RECREATE_REQUIRED"
"""Drift was found that nothing short of recreating the environment corrects."""

REASON_OPERATOR_REQUIRED: Final[str] = "DRIFT_OPERATOR_REQUIRED"
"""Drift was found outside the boundary this tooling may act within."""

REASON_REPAIR_REFUSED: Final[str] = "DRIFT_REPAIR_REFUSED"
"""A repair was asked for and refused because performing it would cross that boundary."""

REASON_REPAIR_FAILED: Final[str] = "DRIFT_REPAIR_FAILED"
"""A repair was attempted within the boundary and did not succeed."""

REASON_MANIFEST_NONDETERMINISTIC: Final[str] = "DRIFT_MANIFEST_NONDETERMINISTIC"
"""Two renderings of the same run disagreed."""

REASON_MANIFEST_LEAKAGE: Final[str] = "DRIFT_MANIFEST_LEAKAGE"
"""The rendered manifest carried something that must not be published."""

REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_DECLARATION_UNREADABLE,
        REASON_POLICY_INCONSISTENT,
        REASON_CLASS_UNDECLARED,
        REASON_BASELINE_UNREADABLE,
        REASON_OBSERVATION_UNAVAILABLE,
        REASON_CONTRACT_VIOLATED,
        REASON_REPAIRABLE,
        REASON_RECREATE_REQUIRED,
        REASON_OPERATOR_REQUIRED,
        REASON_REPAIR_REFUSED,
        REASON_REPAIR_FAILED,
        REASON_MANIFEST_NONDETERMINISTIC,
        REASON_MANIFEST_LEAKAGE,
    }
)
"""Every reason this gate can give, as a closed set.

Closed so that a contract test can compare it against the reasons the gate is
capable of emitting, in both directions: a reason the gate can produce and this
set does not name is a hole, and a name here nothing can produce is a claim about
a check that does not exist.

**There is deliberately no reason for "no baseline was recorded", and it is still
not a pass.** A reason code names something that went wrong, and nothing has: a
machine on its first run, and every continuous-integration runner, has no prior
state to have diverged from. But the verdict is *unmeasured* rather than *passed*,
because the gate looked for a comparison and did not make one. ``UNMEASURED``
outranks ``FAILED`` in :func:`tools.quality.execution.plan.combine` precisely so
that this cannot read as clean, and ``docs/DEPENDENCY_POLICY.md`` prohibits
conflating "could not look" with "looked and found nothing" by name. The finding
carries the sentence telling a reader how to record a baseline, which is the
useful half of an answer that is otherwise only "no".
"""


class DriftManifestError(Exception):
    """A manifest or a baseline could not be read, or did not verify.

    Kept in this module rather than shared with :mod:`tools.quality.drift.plan`
    for the reason ``tools/quality/execution/manifest.py`` gives about its own: a
    verifier that imports the package it verifies cannot report on one too broken
    to import.
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
        run: What was checked — the commit, the declaration, the mode.
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


def build_baseline(*, commit: str, observation: Mapping[str, object]) -> dict[str, object]:
    """Assemble a baseline and stamp it with its digest.

    Args:
        commit: The commit the observation was taken at, which is what orders two
            baselines when neither carries a clock.
        observation: What the host looked like.

    Returns:
        The baseline, digest included.

    The digest is not here to defend against an attacker; a baseline lives in an
    ignored directory on the developer's own machine. It is here because a
    half-written file is indistinguishable from a valid one otherwise, and a
    comparison against a truncated baseline would report drift that never happened.
    """
    document: dict[str, object] = {
        "schema": BASELINE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE,
        "commit": commit,
        "observation": dict(observation),
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
        DriftManifestError: If the text is not a JSON object, is not this schema,
            is not this version, or does not match its own digest.
    """
    return _load(text, schema=SCHEMA, what="drift manifest")


def load_baseline(text: str) -> dict[str, object]:
    """Read a baseline, refusing one that does not verify.

    Args:
        text: The rendered baseline.

    Returns:
        The baseline.

    Raises:
        DriftManifestError: As :func:`load`, and additionally if the document is a
            manifest rather than a baseline. The two live in the same directory and
            a reader pointed at the wrong one should say which it found.
    """
    return _load(text, schema=BASELINE_SCHEMA, what="drift baseline")


def _load(text: str, *, schema: str, what: str) -> dict[str, object]:
    """Read and verify a document of either kind.

    Args:
        text: The rendered document.
        schema: The schema the caller expects.
        what: What to call the document in a message.

    Returns:
        The document.

    Raises:
        DriftManifestError: If the text is not a JSON object, is not ``schema``, is
            not this version, or does not match its own digest.

    One implementation rather than two nearly identical ones, because the checks
    are the same four and a second copy of them is a place for the two to drift —
    which would be a poor showing from this package in particular.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the {what} is not valid JSON: {fault}"
        raise DriftManifestError(msg) from fault
    if not isinstance(document, dict):
        msg = f"the {what} is a {type(document).__name__}, expected an object"
        raise DriftManifestError(msg)
    if document.get("schema") != schema:
        msg = f"the {what} declares schema {document.get('schema')!r}, expected {schema!r}"
        raise DriftManifestError(msg)
    if document.get("schema_version") != SCHEMA_VERSION:
        found = document.get("schema_version")
        msg = f"the {what} declares version {found!r}, and this reader implements {SCHEMA_VERSION}"
        raise DriftManifestError(msg)
    recorded = document.get(DIGEST_KEY)
    expected = digest(document)
    if recorded != expected:
        msg = f"the {what} records {recorded!r} but its content digests to {expected!r}"
        raise DriftManifestError(msg)
    return document
