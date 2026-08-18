"""One document recording what a release was allowed to be, and its own digest.

The shape is the one ``tools/quality/supply/manifest.py`` proved and
``tools/quality/governance/manifest.py`` repeated, for the reason both give:
repeating a solved solution is cheaper than inventing a second one, and a reader
who knows one knows all five. A ``SCHEMA`` name and a ``SCHEMA_VERSION`` inside
the digested payload, canonical JSON so two writers cannot disagree about bytes,
and a :func:`load` that refuses an unsupported version *and* recomputes the
digest.

**Sections, and why they are separated.** ``run`` is what was judged — the
commit, the version and the tag it implies. ``acceptance`` is the foundation
matrix reduced to counts and the criteria that did not pass. ``findings`` is what
each check established. ``capability`` is what the platform will and will not do,
recorded in ADR-0045's vocabulary rather than flattened to a pass. ``verdict`` is
the conclusion and the reason codes behind it.

**No wall clock, and no absolute path.** The only time here is the commit's own
date, which is a fact about the tree rather than about the run — the same choice
``tools/quality/supply/sbom.py`` makes so that two runs over one commit produce
one document. Every path is repository-relative: this file is published as a
release asset from a public repository, and on the development host every
absolute path contains the account holder's full name.

**A published digest is not a signature.** The digest below proves that a
document has not been edited since it was written; it proves nothing about who
wrote it. Signing is a separate mechanism this repository does not have key
material for, and the distinction is kept in the vocabulary rather than blurred —
see :data:`SIGNING_STATES`.
"""

import hashlib
import json
from typing import Final

from tools.quality.release.plan import ReleaseError

SCHEMA: Final[str] = "globin.release.manifest"
"""Identifies what kind of document this is, so a governance manifest fed to this
reader is refused by name rather than by a missing key."""

SCHEMA_VERSION: Final[int] = 2
"""Bumped whenever the document changes shape, and inside the digested payload so
that a canonicalisation change cannot collide with an older digest."""

DIGEST_PREFIX: Final[str] = "sha256:"
DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover, because it holds the digest."""

PHASE: Final[int] = 16

#: How a tag's cryptographic status is recorded.
#:
#: Three words, because three things are true at different times and conflating
#: them is the specific dishonesty this vocabulary exists to prevent. An
#: *annotated* tag is a real Git object carrying a message, a tagger and a date;
#: it is not signed. A *signed* tag additionally carries a signature Git can
#: verify against a key. ``UNAVAILABLE`` says the host holds no key material at
#: all, which is a fact about the machine rather than a property of the tag.
SIGNING_ANNOTATED: Final[str] = "ANNOTATED_UNSIGNED"
SIGNING_SIGNED: Final[str] = "SIGNED_VERIFIED"
SIGNING_UNAVAILABLE: Final[str] = "UNAVAILABLE"

SIGNING_STATES: Final[frozenset[str]] = frozenset(
    {SIGNING_ANNOTATED, SIGNING_SIGNED, SIGNING_UNAVAILABLE}
)
"""The closed set. A contract test asserts the gate can emit nothing else, so
that "signed" cannot arrive as a description of a tag that merely has a message.
"""

#: Every reason the release gate can refuse, as a stable identifier.
#:
#: Written out as constants rather than formatted from a message, on the
#: reasoning ``tools/quality/supply/manifest.py`` gives: a sentence is for a
#: human and changes when somebody improves the wording; a code is for a machine
#: and must not.
REASON_DECLARATION_UNREADABLE: Final[str] = "RELEASE_DECLARATION_UNREADABLE"
REASON_CRITERION_DUPLICATE: Final[str] = "RELEASE_CRITERION_DUPLICATE"
REASON_CRITERION_MALFORMED: Final[str] = "RELEASE_CRITERION_MALFORMED"
REASON_CRITERION_UNJUSTIFIED: Final[str] = "RELEASE_CRITERION_UNJUSTIFIED"
REASON_CATEGORY_UNKNOWN: Final[str] = "RELEASE_CATEGORY_UNKNOWN"
REASON_CATEGORY_EMPTY: Final[str] = "RELEASE_CATEGORY_EMPTY"
REASON_EVIDENCE_MISSING: Final[str] = "RELEASE_EVIDENCE_MISSING"
REASON_BLOCKING_UNMET: Final[str] = "RELEASE_BLOCKING_UNMET"
REASON_VERSION_UNREADABLE: Final[str] = "RELEASE_VERSION_UNREADABLE"
REASON_VERSION_MALFORMED: Final[str] = "RELEASE_VERSION_MALFORMED"
REASON_VERSION_TAG_MISMATCH: Final[str] = "RELEASE_VERSION_TAG_MISMATCH"
REASON_CHANGELOG_INCOMPLETE: Final[str] = "RELEASE_CHANGELOG_INCOMPLETE"
REASON_DOCUMENT_MISSING: Final[str] = "RELEASE_DOCUMENT_MISSING"
REASON_NOTES_MALFORMED: Final[str] = "RELEASE_NOTES_MALFORMED"
REASON_BRANCH_UNEXPECTED: Final[str] = "RELEASE_BRANCH_UNEXPECTED"
REASON_WORKTREE_DIRTY: Final[str] = "RELEASE_WORKTREE_DIRTY"
REASON_REMOTE_DIVERGED: Final[str] = "RELEASE_REMOTE_DIVERGED"
REASON_REPOSITORY_STATE_UNMEASURED: Final[str] = "RELEASE_REPOSITORY_STATE_UNMEASURED"
REASON_MANIFEST_NONDETERMINISTIC: Final[str] = "RELEASE_MANIFEST_NONDETERMINISTIC"
REASON_MANIFEST_LEAKAGE: Final[str] = "RELEASE_MANIFEST_LEAKAGE"

REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_DECLARATION_UNREADABLE,
        REASON_CRITERION_DUPLICATE,
        REASON_CRITERION_MALFORMED,
        REASON_CRITERION_UNJUSTIFIED,
        REASON_CATEGORY_UNKNOWN,
        REASON_CATEGORY_EMPTY,
        REASON_EVIDENCE_MISSING,
        REASON_BLOCKING_UNMET,
        REASON_VERSION_UNREADABLE,
        REASON_VERSION_MALFORMED,
        REASON_VERSION_TAG_MISMATCH,
        REASON_CHANGELOG_INCOMPLETE,
        REASON_DOCUMENT_MISSING,
        REASON_NOTES_MALFORMED,
        REASON_BRANCH_UNEXPECTED,
        REASON_WORKTREE_DIRTY,
        REASON_REMOTE_DIVERGED,
        REASON_REPOSITORY_STATE_UNMEASURED,
        REASON_MANIFEST_NONDETERMINISTIC,
        REASON_MANIFEST_LEAKAGE,
    }
)
"""The closed set. A contract test asserts that every code the gate can emit is
in here, so a new failure mode cannot arrive with an undeclared name."""


def render(document: dict[str, object]) -> str:
    """Encode a manifest so that two writers cannot disagree about bytes.

    Args:
        document: The manifest.

    Returns:
        One line of JSON followed by a newline — sorted keys, no incidental
        whitespace, ASCII only, exactly as the evidence, supply, workflow and
        governance manifests do it.
    """
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def digest(document: dict[str, object]) -> str:
    """The stable identity of a manifest's contents.

    Args:
        document: The manifest, with or without a digest already in it.

    Returns:
        ``"sha256:"`` followed by 64 lowercase hexadecimal characters, taken over
        everything except the digest field.
    """
    payload = {key: value for key, value in document.items() if key != DIGEST_KEY}
    return DIGEST_PREFIX + hashlib.sha256(render(payload).encode("utf-8")).hexdigest()


def build(
    *,
    run: dict[str, object],
    acceptance: dict[str, object],
    findings: dict[str, object],
    capability: dict[str, object],
    verdict: dict[str, object],
) -> dict[str, object]:
    """Assemble a manifest and seal it.

    Args:
        run: What was judged — repository, commit, version, tag and documents.
        acceptance: The foundation matrix, as counts and the criteria that did
            not pass.
        findings: One entry per check, each carrying its own verdict and detail.
        capability: What the platform and the host will and will not do, each a
            recorded state rather than a pass.
        verdict: The conclusion and the reason codes behind it.

    Returns:
        The document, digest included, ready to render.
    """
    document: dict[str, object] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE,
        "run": run,
        "acceptance": acceptance,
        "findings": findings,
        "capability": capability,
        "verdict": verdict,
    }
    document[DIGEST_KEY] = digest(document)
    return document


def load(text: str) -> dict[str, object]:
    """Read a manifest back, refusing anything that cannot be trusted.

    Args:
        text: The rendered document.

    Returns:
        The document.

    Raises:
        ReleaseError: If the text is not JSON, is not a release manifest, was
            written by a different schema version, or carries a digest that
            disagrees with its contents.

    The digest check is what makes this evidence rather than a note. A file
    edited by hand — to drop a finding, to change a verdict, to turn a
    ``BLOCKED`` into a ``PASS`` before publishing it as a release asset — is
    refused here rather than read and believed.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the release manifest is not valid JSON: {fault}"
        raise ReleaseError(msg) from fault

    if not isinstance(document, dict):
        msg = f"a release manifest must be a JSON object, found {type(document).__name__}"
        raise ReleaseError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"not a {SCHEMA} document: found schema {document.get('schema')!r}"
        raise ReleaseError(msg)

    version = document.get("schema_version")
    if version != SCHEMA_VERSION:
        msg = (
            f"this tool reads {SCHEMA} version {SCHEMA_VERSION}, and the document "
            f"declares {version!r}. Regenerate it rather than reading it anyway"
        )
        raise ReleaseError(msg)

    if document.get(DIGEST_KEY) != digest(document):
        msg = (
            "the release manifest's digest does not describe its contents, so it has "
            "been edited or truncated. Regenerate it"
        )
        raise ReleaseError(msg)

    return document
