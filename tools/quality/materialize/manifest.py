"""The materialization manifest: what could be built here, and its digest.

The same document shape every other gate writes -- ``schema``,
``schema_version``, ``phase``, ``run``, ``findings``, ``verdict``, ``digest`` --
so that a reader who has seen one has seen them all.

**No wall clock, no absolute path, and no artefact URL.** The first two for the
reason every manifest in this repository gives; the third because a lock holds
hundreds of them and a manifest is a summary. What is recorded of an artefact is
its cache-relative path, which is identical on every machine.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Final

SCHEMA: Final[str] = "globin.materialize.manifest"
"""What kind of document this is."""

SCHEMA_VERSION: Final[int] = 1
"""The version of that document's shape."""

PHASE: Final[int] = 29
"""The phase that introduced this gate."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""How a digest announces its algorithm."""

DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover: itself."""

MANIFEST_NAME: Final[str] = "materialize-manifest.json"
"""What the evidence file is called."""

REASON_LOCK_UNREADABLE: Final[str] = "MATERIALIZE_LOCK_UNREADABLE"
"""The lock could not be parsed, so nothing could be planned from it."""

REASON_DECLARATION_UNREADABLE: Final[str] = "MATERIALIZE_DECLARATION_UNREADABLE"
"""The lock policy could not be read, so the target is unknown."""

REASON_ARTEFACT_MISSING: Final[str] = "MATERIALIZE_ARTEFACT_MISSING"
"""A required artefact is absent from the wheelhouse, and nothing was fetched."""

REASON_ARTEFACT_CORRUPT: Final[str] = "MATERIALIZE_ARTEFACT_CORRUPT"
"""A cached artefact's bytes are not the bytes the lock names."""

REASON_ARTEFACT_UNHASHED: Final[str] = "MATERIALIZE_ARTEFACT_UNHASHED"
"""An artefact carries no digest in a permitted algorithm."""

REASON_ARTEFACT_INCOMPATIBLE: Final[str] = "MATERIALIZE_ARTEFACT_INCOMPATIBLE"
"""The lock offers nothing serving the declared target."""

REASON_SOURCE_FORBIDDEN: Final[str] = "MATERIALIZE_SOURCE_FORBIDDEN"
"""Only a source distribution is offered, and policy forbids building one."""

REASON_MANIFEST_NONDETERMINISTIC: Final[str] = "MATERIALIZE_MANIFEST_NONDETERMINISTIC"
"""Two renderings of one run disagreed, so the digest means nothing."""

REASON_MANIFEST_LEAKAGE: Final[str] = "MATERIALIZE_MANIFEST_LEAKAGE"
"""The rendered manifest matched a credential pattern."""

REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_LOCK_UNREADABLE,
        REASON_DECLARATION_UNREADABLE,
        REASON_ARTEFACT_MISSING,
        REASON_ARTEFACT_CORRUPT,
        REASON_ARTEFACT_UNHASHED,
        REASON_ARTEFACT_INCOMPATIBLE,
        REASON_SOURCE_FORBIDDEN,
        REASON_MANIFEST_NONDETERMINISTIC,
        REASON_MANIFEST_LEAKAGE,
    }
)
"""Every reason this manifest can record. A closed set, compared by contract test."""


class MaterializeManifestError(Exception):
    """A manifest could not be read, or disagrees with itself."""


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
        run: What was checked -- the commit, the lock, the target.
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
        MaterializeManifestError: If the text is not a JSON object, is not this
            schema, is not this version, or does not match its own digest.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the materialize manifest is not valid JSON: {fault}"
        raise MaterializeManifestError(msg) from fault
    if not isinstance(document, dict):
        msg = f"the materialize manifest is a {type(document).__name__}, expected an object"
        raise MaterializeManifestError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"the manifest declares schema {document.get('schema')!r}, expected {SCHEMA!r}"
        raise MaterializeManifestError(msg)
    if document.get("schema_version") != SCHEMA_VERSION:
        found = document.get("schema_version")
        msg = (
            f"the manifest declares version {found!r}, and this reader implements {SCHEMA_VERSION}"
        )
        raise MaterializeManifestError(msg)
    recorded = document.get(DIGEST_KEY)
    expected = digest(document)
    if recorded != expected:
        msg = f"the manifest records {recorded!r} but its content digests to {expected!r}"
        raise MaterializeManifestError(msg)
    return document
