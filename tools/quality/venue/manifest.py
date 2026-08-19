"""The evidence this gate publishes.

Kept in this package rather than shared, for the reason every sibling gate states:
a verifier that imports the package it verifies cannot report on one too broken to
import.

**No wall clock and no absolute path.** The only time recorded is what the registry
itself declares it observed. A manifest that changed because it was built on a
different day could not be compared with itself, and the determinism check would be
measuring the clock rather than the gate.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

SCHEMA: Final[str] = "globin.venue.manifest"
"""What this manifest calls itself.

Distinct from the package's own ``globin.api_reality.manifest``: the two describe
the same registry and are produced by different readers, and giving them one name
would invite a comparison that proves only that one of them ran.
"""

SCHEMA_VERSION: Final[int] = 1
"""The manifest shape."""

PHASE: Final[int] = 33
"""Which phase published it."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""What a digest begins with."""

DIGEST_KEY: Final[str] = "digest"
"""Which key holds the digest, and is excluded from its own input."""


class ManifestError(Exception):
    """A manifest is present and does not verify.

    Its own class rather than :class:`ValueError`, so that a caller can tell a
    manifest that failed to verify from any other bad value, and so that a reader
    is not invited to guess whether a type or a value was wrong.
    """


MANIFEST_NAME: Final[str] = "api-reality-manifest.json"
"""The filename inside the evidence directory."""

DIRECTORY: Final[str] = "venue"
"""Which evidence directory it goes in, under ``.globin``."""


def render(document: Mapping[str, object]) -> str:
    """One manifest as canonical JSON.

    Args:
        document: The manifest.

    Returns:
        Sorted keys, no incidental whitespace, ASCII only, one trailing newline.
    """
    return (
        json.dumps(dict(document), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    )


def digest(document: Mapping[str, object]) -> str:
    """One manifest's content digest.

    Args:
        document: The manifest, with or without its digest set.

    Returns:
        The prefix followed by 64 lowercase hexadecimal characters, taken over
        everything except the digest itself.
    """
    payload = {key: value for key, value in document.items() if key != DIGEST_KEY}
    return DIGEST_PREFIX + hashlib.sha256(render(payload).encode("utf-8")).hexdigest()


def build(
    *,
    run: Mapping[str, object],
    findings: Mapping[str, object],
    verdict: Mapping[str, object],
) -> dict[str, object]:
    """One manifest, with its digest set last.

    Args:
        run: What was read, and whether the network was reached.
        findings: What was concluded.
        verdict: The single answer.

    Returns:
        The manifest.
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
    """One manifest read back, refusing anything that does not verify.

    Args:
        text: The rendered manifest.

    Returns:
        The parsed document.

    Raises:
        ManifestError: If it is not JSON, not an object, announces the wrong schema or
            version, or its digest does not cover its content.
    """
    document = json.loads(text)
    if not isinstance(document, dict):
        msg = "the api reality manifest is not a JSON object"
        raise ManifestError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"the manifest announces schema {document.get('schema')!r}"
        raise ManifestError(msg)
    if document.get("schema_version") != SCHEMA_VERSION:
        msg = f"the manifest announces version {document.get('schema_version')!r}"
        raise ManifestError(msg)
    if document.get(DIGEST_KEY) != digest(document):
        msg = "the manifest was edited after its digest was taken"
        raise ManifestError(msg)
    return dict(document)
