"""The stack manifest: what was probed, what it concluded, and its digest.

The same document shape every other gate here writes — ``schema``,
``schema_version``, ``phase``, ``run``, ``findings``, ``verdict``, ``digest`` — so
a reader who has seen ``.globin/wheels`` or ``.globin/runtime`` has seen this, and
the digest rule is stated once per package rather than invented per package.

**No wall clock, and no absolute path.** The only time recorded is the commit's
own. A manifest that changed because it was built on a different day could not be
compared with itself, and the determinism check two lines from the end of the gate
would be measuring the clock. Paths are repository-relative or they are not
recorded: this file is published as a public-repository artifact, and every
absolute path on a development host carries the account holder's name.

**No version of anything is recorded that was not measured.** The versions in this
document come from the installed distributions and from the files that pin them,
never from the declaration alone — a manifest that echoed the declaration back
would agree with it by construction, which is the mirror ADR-0052 warns about.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Final

SCHEMA: Final[str] = "globin.stack.manifest"
"""What kind of document this is."""

SCHEMA_VERSION: Final[int] = 1
"""The version of that document's shape."""

PHASE: Final[int] = 22
"""The phase that introduced this gate."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""How a digest announces its algorithm."""

DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover: itself."""

REASON_DECLARATION_UNREADABLE: Final[str] = "STACK_DECLARATION_UNREADABLE"
"""The stack contract could not be parsed at all."""

REASON_TARGET_DIVERGED: Final[str] = "STACK_TARGET_DIVERGED"
"""The stack was verified against an environment the runtime contract does not declare."""

REASON_REGISTRY_INCONSISTENT: Final[str] = "STACK_REGISTRY_INCONSISTENT"
"""The declared probes and the implemented probes do not agree."""

REASON_LIBRARY_DUPLICATED: Final[str] = "STACK_LIBRARY_DUPLICATED"
"""One library is declared more than once, so it holds two sets of expectations."""

REASON_LIBRARY_UNCHECKED: Final[str] = "STACK_LIBRARY_UNCHECKED"
"""A declared library names no probe, so nothing about its behaviour is checked."""

REASON_VERSION_DIVERGED: Final[str] = "STACK_VERSION_DIVERGED"
"""The four places a version is written down do not agree."""

REASON_PROVENANCE_DIVERGED: Final[str] = "STACK_PROVENANCE_DIVERGED"
"""An installed artefact was built for an interpreter other than the pinned one."""

REASON_LIBRARY_UNIMPORTABLE: Final[str] = "STACK_LIBRARY_UNIMPORTABLE"
"""A declared library could not be imported, so nothing about it could be measured."""

REASON_PROBE_FAILED: Final[str] = "STACK_PROBE_FAILED"
"""A behaviour probe did not observe what the contract requires."""

REASON_DEFERRAL_MISPLACED: Final[str] = "STACK_DEFERRAL_MISPLACED"
"""A deferred question names a phase that has shipped, or one beyond the programme."""

REASON_MANIFEST_NONDETERMINISTIC: Final[str] = "STACK_MANIFEST_NONDETERMINISTIC"
"""Two renderings of the same run disagreed, so the digest identifies nothing."""

REASON_MANIFEST_LEAKAGE: Final[str] = "STACK_MANIFEST_LEAKAGE"
"""The rendered manifest carried something that must not be published."""

REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_DECLARATION_UNREADABLE,
        REASON_TARGET_DIVERGED,
        REASON_REGISTRY_INCONSISTENT,
        REASON_LIBRARY_DUPLICATED,
        REASON_LIBRARY_UNCHECKED,
        REASON_VERSION_DIVERGED,
        REASON_PROVENANCE_DIVERGED,
        REASON_LIBRARY_UNIMPORTABLE,
        REASON_PROBE_FAILED,
        REASON_DEFERRAL_MISPLACED,
        REASON_MANIFEST_NONDETERMINISTIC,
        REASON_MANIFEST_LEAKAGE,
    }
)
"""Every reason this gate can give, as a closed set.

Closed so a contract test can compare it against what the gate is capable of
emitting, in both directions: a reason the gate produces and this set does not
name is a hole, and a name here nothing can produce is a claim about a check that
does not exist.
"""


class StackManifestError(Exception):
    """A manifest could not be read, or did not verify.

    Kept here rather than shared with :mod:`tools.quality.stack.plan` for the
    reason ``tools/quality/wheels/manifest.py`` gives about its own: a verifier
    that imports the package it verifies cannot report on one too broken to
    import.
    """


def render(document: Mapping[str, object]) -> str:
    """Render a manifest to its canonical form.

    Args:
        document: The manifest.

    Returns:
        One line of JSON with sorted keys, no incidental whitespace and no
        non-ASCII escape ambiguity, followed by a newline.
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
        StackManifestError: If the text is not a JSON object, is not this schema,
            is not this version, or does not match its own digest.

    Four refusals in a fixed order, each with its own message, because "this file
    is wrong" is a diagnosis nobody can act on.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the stack manifest is not valid JSON: {fault}"
        raise StackManifestError(msg) from fault
    if not isinstance(document, dict):
        msg = f"the stack manifest is a {type(document).__name__}, expected an object"
        raise StackManifestError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"the manifest declares schema {document.get('schema')!r}, expected {SCHEMA!r}"
        raise StackManifestError(msg)
    if document.get("schema_version") != SCHEMA_VERSION:
        found = document.get("schema_version")
        msg = (
            f"the manifest declares version {found!r}, and this reader implements {SCHEMA_VERSION}"
        )
        raise StackManifestError(msg)
    recorded = document.get(DIGEST_KEY)
    expected = digest(document)
    if recorded != expected:
        msg = f"the manifest records {recorded!r} but its content digests to {expected!r}"
        raise StackManifestError(msg)
    return document
