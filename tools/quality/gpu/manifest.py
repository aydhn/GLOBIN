"""The GPU manifest: what was asked, what this host answered, and its digest.

The same document shape the other gates write — ``schema``, ``schema_version``,
``phase``, ``run``, ``findings``, ``verdict``, ``digest`` — so that a reader who
has seen one has seen them all, and so the digest rule is stated once per package
rather than invented per package.

**No wall clock, and no absolute path.** The only time recorded is the commit's
own. A manifest that changed because it was built on a different day could not be
compared with itself, and the determinism check would be measuring the clock
rather than the gate.

**A device model is recorded; nothing about the person using it is.** The manifest
is uploaded as a public-repository artefact, so the rule is the one
``tools/quality/runtime`` follows: a value that identifies the *machine's
hardware* answers the roadmap's question and is recorded, while a value that
identifies its *owner* is not. A GPU model is the former. No path outside the
repository appears here at all, because none is needed to answer any of the five
questions, and :func:`tools.quality.evidence.redaction.scan` runs over the
rendered document anyway rather than trusting that.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Final

SCHEMA: Final[str] = "globin.gpu.manifest"
"""What kind of document this is."""

SCHEMA_VERSION: Final[int] = 1
"""The version of that document's shape."""

PHASE: Final[int] = 23
"""The phase that introduced this gate."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""How a digest announces its algorithm."""

DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover: itself."""

REASON_DECLARATION_UNREADABLE: Final[str] = "GPU_DECLARATION_UNREADABLE"
"""The contract could not be parsed at all."""

REASON_TARGET_DIVERGED: Final[str] = "GPU_TARGET_DIVERGED"
"""The contract was written against a host the runtime contract does not declare."""

REASON_CAPABILITY_DUPLICATED: Final[str] = "GPU_CAPABILITY_DUPLICATED"
"""One capability is declared more than once, so the contract holds two answers."""

REASON_PHASE_MISPLACED: Final[str] = "GPU_PHASE_MISPLACED"
"""A capability names a phase that is already delivered, or beyond the programme."""

REASON_INTERFACE_CONTRADICTED: Final[str] = "GPU_INTERFACE_CONTRADICTED"
"""The contract both permits and forbids the same field."""

REASON_CAPABILITY_UNMEASURED: Final[str] = "GPU_CAPABILITY_UNMEASURED"
"""A probe failed, which is never a pass.

Distinct from a capability simply being absent. ADR-0045's whole argument is that
*we asked and it is not there* and *we could not ask* are different facts, and
only the second is a defect.
"""

REASON_CAPABILITY_MISSING: Final[str] = "GPU_CAPABILITY_MISSING"
"""A capability declared ``required`` is not present on this host."""

REASON_MANIFEST_NONDETERMINISTIC: Final[str] = "GPU_MANIFEST_NONDETERMINISTIC"
"""Two renderings of the same run disagreed, so the digest identifies nothing."""

REASON_MANIFEST_LEAKAGE: Final[str] = "GPU_MANIFEST_LEAKAGE"
"""The rendered manifest carried something that must not be published."""

REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_DECLARATION_UNREADABLE,
        REASON_TARGET_DIVERGED,
        REASON_CAPABILITY_DUPLICATED,
        REASON_PHASE_MISPLACED,
        REASON_INTERFACE_CONTRADICTED,
        REASON_CAPABILITY_UNMEASURED,
        REASON_CAPABILITY_MISSING,
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


class GpuManifestError(Exception):
    """A manifest could not be read, or did not verify.

    Kept in this module rather than shared with :mod:`tools.quality.gpu.plan` for
    the reason ``tools/quality/wheels/manifest.py`` gives about its own: a
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
        run: What was asked — the commit, the contract, the interface.
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
        GpuManifestError: If the text is not a JSON object, is not this schema,
            is not this version, or does not match its own digest.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the gpu manifest is not valid JSON: {fault}"
        raise GpuManifestError(msg) from fault
    if not isinstance(document, dict):
        msg = f"the gpu manifest is a {type(document).__name__}, expected an object"
        raise GpuManifestError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"the manifest declares schema {document.get('schema')!r}, expected {SCHEMA!r}"
        raise GpuManifestError(msg)
    if document.get("schema_version") != SCHEMA_VERSION:
        found = document.get("schema_version")
        msg = (
            f"the manifest declares version {found!r}, and this reader implements {SCHEMA_VERSION}"
        )
        raise GpuManifestError(msg)
    recorded = document.get(DIGEST_KEY)
    expected = digest(document)
    if recorded != expected:
        msg = f"the manifest records {recorded!r} but its content digests to {expected!r}"
        raise GpuManifestError(msg)
    return document
