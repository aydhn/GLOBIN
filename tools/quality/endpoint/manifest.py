"""The endpoint manifest: what was declared, what the source says, and its digest.

The same document shape every other gate here writes — ``schema``,
``schema_version``, ``phase``, ``run``, ``findings``, ``verdict``, ``digest`` — so a
reader who has seen one has seen them all, and the digest rule is stated once per
package rather than reinvented.

**No wall clock, and no absolute path.** The only time recorded is the commit's own.
A manifest that changed because it was built on a different day could not be compared
with itself, and the determinism check would be measuring the clock rather than the
gate.

**Nothing about the machine appears at all**, which makes this the narrowest manifest
in the tree. Unlike ``runtime`` and ``gpu``, this gate reports on a *contract* rather
than a host: every value in it comes from two files in the repository, so there is no
interpreter path to fingerprint and no device to name.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Final

SCHEMA: Final[str] = "globin.endpoint.manifest"
"""What kind of document this is."""

SCHEMA_VERSION: Final[int] = 1
"""The version of that document's shape."""

PHASE: Final[int] = 27
"""The phase that introduced this gate."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""How a digest announces its algorithm."""

DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover: itself."""

REASON_DECLARATION_UNREADABLE: Final[str] = "ENDPOINT_DECLARATION_UNREADABLE"
"""The contract could not be read or parsed at all."""

REASON_CONTRACT_CONTRADICTED: Final[str] = "ENDPOINT_CONTRACT_CONTRADICTED"
"""The contract disagrees with itself, before any source was consulted."""

REASON_SOURCE_UNREADABLE: Final[str] = "ENDPOINT_SOURCE_UNREADABLE"
"""A module the contract describes could not be read."""

REASON_ROUTES_DIVERGED: Final[str] = "ENDPOINT_ROUTES_DIVERGED"
"""The declared route set and the source's route table disagree."""

REASON_LOOPBACK_UNDECLARED: Final[str] = "ENDPOINT_LOOPBACK_UNDECLARED"
"""The source does not declare an address the contract permits, or the value type."""

REASON_ADDRESS_HARDCODED: Final[str] = "ENDPOINT_ADDRESS_HARDCODED"
"""The module that binds spells an address rather than being handed one.

Any address, loopback included. One it cannot spell is one it cannot bind, so the
only address reachable is the one the value type has already refused to widen.
"""

REASON_WILDCARD_PRESENT: Final[str] = "ENDPOINT_WILDCARD_PRESENT"
"""A spelling of "every interface" appears somewhere in the package."""

REASON_BOUNDS_DIVERGED: Final[str] = "ENDPOINT_BOUNDS_DIVERGED"
"""A declared bound or default is not the one the source carries."""

REASON_SWITCHES_DIVERGED: Final[str] = "ENDPOINT_SWITCHES_DIVERGED"
"""A route's switch is missing, or defaults the other way."""

REASON_EXPOSITIONS_DIVERGED: Final[str] = "ENDPOINT_EXPOSITIONS_DIVERGED"
"""A declared content type is not one the source serves."""

REASON_CARDINALITY_UNPROVEN: Final[str] = "ENDPOINT_CARDINALITY_UNPROVEN"
"""A family's declared budget is not the product of its vocabularies in the source.

The one finding that is arithmetic rather than a comparison, and the reason this gate
is worth running: a seventh route grows the ``route`` vocabulary, and every budget
that names it must move in the same edit.
"""

REASON_VOCABULARY_DIVERGED: Final[str] = "ENDPOINT_VOCABULARY_DIVERGED"
"""A declared attribute vocabulary and the source's enum disagree."""

REASON_TEST_ABSENT: Final[str] = "ENDPOINT_TEST_ABSENT"
"""A test module the contract names does not exist, so a claim is enforced nowhere."""

REASON_MANIFEST_NONDETERMINISTIC: Final[str] = "ENDPOINT_MANIFEST_NONDETERMINISTIC"
"""Two renderings of the same run disagreed, so the digest identifies nothing."""

REASON_MANIFEST_LEAKAGE: Final[str] = "ENDPOINT_MANIFEST_LEAKAGE"
"""The rendered manifest carried something that must not be published."""

REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_DECLARATION_UNREADABLE,
        REASON_CONTRACT_CONTRADICTED,
        REASON_SOURCE_UNREADABLE,
        REASON_ROUTES_DIVERGED,
        REASON_LOOPBACK_UNDECLARED,
        REASON_ADDRESS_HARDCODED,
        REASON_WILDCARD_PRESENT,
        REASON_BOUNDS_DIVERGED,
        REASON_SWITCHES_DIVERGED,
        REASON_EXPOSITIONS_DIVERGED,
        REASON_CARDINALITY_UNPROVEN,
        REASON_VOCABULARY_DIVERGED,
        REASON_TEST_ABSENT,
        REASON_MANIFEST_NONDETERMINISTIC,
        REASON_MANIFEST_LEAKAGE,
    }
)
"""Every reason this gate can give, as a closed set.

Closed so a contract test can compare it against the reasons the gate is capable of
emitting, in both directions: a reason the gate can produce and this set does not name
is a hole, and a name here nothing can produce is a claim about a check that does not
exist.
"""


class EndpointManifestError(Exception):
    """A manifest could not be read, or did not verify.

    Kept in this module rather than shared with :mod:`tools.quality.endpoint.plan`,
    for the reason ``tools/quality/wheels/manifest.py`` gives about its own: a
    verifier that imports the package it verifies cannot report on one too broken to
    import.
    """


def render(document: Mapping[str, object]) -> str:
    """Render a manifest to its canonical form.

    Args:
        document: The manifest.

    Returns:
        One line of JSON with sorted keys, no incidental whitespace and no non-ASCII
        escape ambiguity, followed by a newline.
    """
    return (
        json.dumps(dict(document), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    )


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
        run: What was asked — the commit, the contract, the modules consulted.
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
        EndpointManifestError: If the text is not a JSON object, is not this schema,
            is not this version, or does not match its own digest.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the endpoint manifest is not valid JSON: {fault}"
        raise EndpointManifestError(msg) from fault
    if not isinstance(document, dict):
        msg = f"the endpoint manifest is a {type(document).__name__}, expected an object"
        raise EndpointManifestError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"the manifest declares schema {document.get('schema')!r}, expected {SCHEMA!r}"
        raise EndpointManifestError(msg)
    if document.get("schema_version") != SCHEMA_VERSION:
        found = document.get("schema_version")
        msg = (
            f"the manifest declares version {found!r}, and this reader implements {SCHEMA_VERSION}"
        )
        raise EndpointManifestError(msg)
    recorded = document.get(DIGEST_KEY)
    expected = digest(document)
    if recorded != expected:
        msg = f"the manifest records {recorded!r} but its content digests to {expected!r}"
        raise EndpointManifestError(msg)
    return document
