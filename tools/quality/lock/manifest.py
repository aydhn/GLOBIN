"""The lock manifest: what was checked, what was concluded, and its digest.

The same document shape the other gates write — ``schema``, ``schema_version``,
``phase``, ``run``, ``findings``, ``verdict``, ``digest`` — so that a reader who
has seen one has seen them all, and so the digest rule is stated once per package
rather than invented per package.

**No wall clock, and no absolute path.** The only time recorded is the commit's
own. A manifest that changes because it was built on a different day cannot be
compared with itself, and the determinism check would be measuring the clock.
Paths are repository-relative or they are not recorded, because this manifest is
uploaded as a public-repository artifact and every absolute path on the
development host carries the account holder's name.

**No artefact URL is recorded here.** The lock itself carries several hundred of
them and they are public, but a manifest is a summary rather than a copy: what is
recorded is how many artefacts were checked and how many carried a hash, not where
each one lives. :func:`tools.quality.evidence.redaction.scan` runs over the
rendered document anyway rather than trusting that, because a URL carrying
credentials is one of the shapes it looks for.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Final

SCHEMA: Final[str] = "globin.lock.manifest"
"""What kind of document this is."""

SCHEMA_VERSION: Final[int] = 1
"""The version of that document's shape."""

PHASE: Final[int] = 20
"""The phase that introduced this gate."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""How a digest announces its algorithm."""

DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover: itself."""

REASON_DECLARATION_UNREADABLE: Final[str] = "LOCK_DECLARATION_UNREADABLE"
"""``lock-policy.toml`` is absent, is not TOML, or holds a value this reader refuses."""

REASON_FILE_UNREADABLE: Final[str] = "LOCK_FILE_UNREADABLE"
"""A declared lock file is absent or is not TOML."""

REASON_VERSION_UNSUPPORTED: Final[str] = "LOCK_VERSION_UNSUPPORTED"
"""The lock announces a format version this reader does not implement."""

REASON_PRODUCER_UNEXPECTED: Final[str] = "LOCK_PRODUCER_UNEXPECTED"
"""The lock was written by a tool the declaration does not name."""

REASON_TARGET_DIVERGED: Final[str] = "LOCK_TARGET_DIVERGED"
"""The lock was resolved for an environment the runtime contract does not declare."""

REASON_PACKAGE_MALFORMED: Final[str] = "LOCK_PACKAGE_MALFORMED"
"""A package entry has no usable name, no version, or a shape that is not reproducible."""

REASON_HASH_MISSING: Final[str] = "LOCK_HASH_MISSING"
"""An artefact carries no hash, or carries one in an algorithm the policy refuses."""

REASON_ARTEFACT_UNTRUSTED: Final[str] = "LOCK_ARTEFACT_UNTRUSTED"
"""An artefact is served from somewhere the declaration does not permit."""

REASON_WHEEL_INCOMPATIBLE: Final[str] = "LOCK_WHEEL_INCOMPATIBLE"
"""No recorded wheel serves the interpreter the runtime contract pins."""

REASON_SOURCE_ONLY: Final[str] = "LOCK_SOURCE_ONLY"
"""A package would have to be built from source, and no phase owns that gap."""

REASON_DECLARATION_INCOMPLETE: Final[str] = "LOCK_DECLARATION_INCOMPLETE"
"""The declared roots and ``pyproject.toml`` disagree, or a declared tool is unlocked."""

REASON_REGISTER_DIVERGED: Final[str] = "LOCK_REGISTER_DIVERGED"
"""A continuous-integration pin or a hook revision disagrees with the locked version."""

REASON_RUNTIME_UNLOCKED: Final[str] = "LOCK_RUNTIME_UNLOCKED"
"""Runtime dependencies are declared while no runtime lock exists."""

REASON_ENVIRONMENT_DIVERGED: Final[str] = "LOCK_ENVIRONMENT_DIVERGED"
"""What is installed is not what the lock records."""

REASON_ENVIRONMENT_UNMEASURED: Final[str] = "LOCK_ENVIRONMENT_UNMEASURED"
"""The environment could not be compared, which is never a pass."""

REASON_REFRESH_FAILED: Final[str] = "LOCK_REFRESH_FAILED"
"""Regenerating the lock did not produce one this gate accepts."""

REASON_MANIFEST_NONDETERMINISTIC: Final[str] = "LOCK_MANIFEST_NONDETERMINISTIC"
"""Two renderings of the same run disagreed."""

REASON_MANIFEST_LEAKAGE: Final[str] = "LOCK_MANIFEST_LEAKAGE"
"""The rendered manifest carried something that must not be published."""

REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_DECLARATION_UNREADABLE,
        REASON_FILE_UNREADABLE,
        REASON_VERSION_UNSUPPORTED,
        REASON_PRODUCER_UNEXPECTED,
        REASON_TARGET_DIVERGED,
        REASON_PACKAGE_MALFORMED,
        REASON_HASH_MISSING,
        REASON_ARTEFACT_UNTRUSTED,
        REASON_WHEEL_INCOMPATIBLE,
        REASON_SOURCE_ONLY,
        REASON_DECLARATION_INCOMPLETE,
        REASON_REGISTER_DIVERGED,
        REASON_RUNTIME_UNLOCKED,
        REASON_ENVIRONMENT_DIVERGED,
        REASON_ENVIRONMENT_UNMEASURED,
        REASON_REFRESH_FAILED,
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


class LockManifestError(Exception):
    """A manifest could not be read, or did not verify.

    Kept in this module rather than shared with :mod:`tools.quality.lock.plan` for
    the reason ``tools/quality/execution/manifest.py`` gives about its own: a
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
        run: What was checked — the commit, the declaration, the lock, the target.
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
        LockManifestError: If the text is not a JSON object, is not this schema,
            is not this version, or does not match its own digest.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the lock manifest is not valid JSON: {fault}"
        raise LockManifestError(msg) from fault
    if not isinstance(document, dict):
        msg = f"the lock manifest is a {type(document).__name__}, expected an object"
        raise LockManifestError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"the manifest declares schema {document.get('schema')!r}, expected {SCHEMA!r}"
        raise LockManifestError(msg)
    if document.get("schema_version") != SCHEMA_VERSION:
        found = document.get("schema_version")
        msg = (
            f"the manifest declares version {found!r}, and this reader implements {SCHEMA_VERSION}"
        )
        raise LockManifestError(msg)
    recorded = document.get(DIGEST_KEY)
    expected = digest(document)
    if recorded != expected:
        msg = f"the manifest records {recorded!r} but its content digests to {expected!r}"
        raise LockManifestError(msg)
    return document
