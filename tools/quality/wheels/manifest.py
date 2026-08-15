"""The wheel-survey manifest: what was checked, what was concluded, and its digest.

The same document shape the other gates write — ``schema``, ``schema_version``,
``phase``, ``run``, ``findings``, ``verdict``, ``digest`` — so that a reader who
has seen one has seen them all, and so the digest rule is stated once per package
rather than invented per package.

**No wall clock, and no absolute path.** The only time recorded is the commit's
own, for the reason ``vulnerability-waivers.toml`` gives about expiry: a manifest
that changes because it was built on a different day cannot be compared with
itself, and the determinism check would be measuring the clock. Paths are
repository-relative or they are not recorded, because this manifest is uploaded as
a public-repository artifact and every absolute path on the development host
carries the account holder's name.

**No credential, and no index token.** The survey reads a public index over an
unauthenticated request. Should that ever change, the URL is recorded and the
credential is not — but the honest position today is that there is nothing to
redact, and :func:`tools.quality.evidence.redaction.scan` runs over the rendered
document anyway rather than trusting that.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Final

SCHEMA: Final[str] = "globin.wheels.manifest"
"""What kind of document this is."""

SCHEMA_VERSION: Final[int] = 1
"""The version of that document's shape."""

PHASE: Final[int] = 18
"""The phase that introduced this gate."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""How a digest announces its algorithm."""

DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover: itself."""

REASON_DECLARATION_UNREADABLE: Final[str] = "WHEELS_DECLARATION_UNREADABLE"
"""The survey could not be parsed at all."""

REASON_TARGET_DIVERGED: Final[str] = "WHEELS_TARGET_DIVERGED"
"""The survey was conducted against an environment the runtime contract does not declare."""

REASON_RECORD_INCONSISTENT: Final[str] = "WHEELS_RECORD_INCONSISTENT"
"""A recorded verdict does not follow from the evidence recorded beside it."""

REASON_PHASE_MISPLACED: Final[str] = "WHEELS_PHASE_MISPLACED"
"""An entry names a phase that is already delivered, or beyond the programme."""

REASON_LIBRARY_DUPLICATED: Final[str] = "WHEELS_LIBRARY_DUPLICATED"
"""One distribution is surveyed more than once, so the survey holds two verdicts."""

REASON_WHEEL_UNAVAILABLE: Final[str] = "WHEELS_WHEEL_UNAVAILABLE"
"""A scheduled library has no wheel for the pinned interpreter."""

REASON_INDEX_DIVERGED: Final[str] = "WHEELS_INDEX_DIVERGED"
"""The probe found the index no longer matches the record."""

REASON_INDEX_UNREACHABLE: Final[str] = "WHEELS_INDEX_UNREACHABLE"
"""The probe could not read the index, which is never a pass."""

REASON_MANIFEST_NONDETERMINISTIC: Final[str] = "WHEELS_MANIFEST_NONDETERMINISTIC"
"""Two renderings of the same run disagreed."""

REASON_MANIFEST_LEAKAGE: Final[str] = "WHEELS_MANIFEST_LEAKAGE"
"""The rendered manifest carried something that must not be published."""

REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_DECLARATION_UNREADABLE,
        REASON_TARGET_DIVERGED,
        REASON_RECORD_INCONSISTENT,
        REASON_PHASE_MISPLACED,
        REASON_LIBRARY_DUPLICATED,
        REASON_WHEEL_UNAVAILABLE,
        REASON_INDEX_DIVERGED,
        REASON_INDEX_UNREACHABLE,
        REASON_MANIFEST_NONDETERMINISTIC,
        REASON_MANIFEST_LEAKAGE,
    }
)
"""Every reason this gate can give, as a closed set.

Closed so that a contract test can compare it against the reasons the gate is
capable of emitting, in both directions: a reason the gate can produce and this
set does not name is a hole, and a name here nothing can produce is a claim about
a check that does not exist.
"""


class WheelManifestError(Exception):
    """A manifest could not be read, or did not verify.

    Kept in this module rather than shared with :mod:`tools.quality.wheels.plan`
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
        run: What was checked — the commit, the declaration, the target.
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
        WheelManifestError: If the text is not a JSON object, is not this schema,
            is not this version, or does not match its own digest.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the wheel manifest is not valid JSON: {fault}"
        raise WheelManifestError(msg) from fault
    if not isinstance(document, dict):
        msg = f"the wheel manifest is a {type(document).__name__}, expected an object"
        raise WheelManifestError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"the manifest declares schema {document.get('schema')!r}, expected {SCHEMA!r}"
        raise WheelManifestError(msg)
    if document.get("schema_version") != SCHEMA_VERSION:
        found = document.get("schema_version")
        msg = (
            f"the manifest declares version {found!r}, and this reader implements {SCHEMA_VERSION}"
        )
        raise WheelManifestError(msg)
    recorded = document.get(DIGEST_KEY)
    expected = digest(document)
    if recorded != expected:
        msg = f"the manifest records {recorded!r} but its content digests to {expected!r}"
        raise WheelManifestError(msg)
    return document
