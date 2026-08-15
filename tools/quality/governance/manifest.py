"""One document recording the governance arrangement, and its own digest.

The shape is the one ``tools/quality/supply/manifest.py`` already proved, for the
reason that module gives about the two before it: repeating a solved solution is
cheaper than inventing a second one, and a reader who knows one knows all four. A
``SCHEMA`` name and a ``SCHEMA_VERSION`` inside the digested payload, canonical
JSON so two writers cannot disagree about bytes, and a :func:`load` that refuses
an unsupported version *and* recomputes the digest.

**Sections, and why they are separated.** ``run`` is what was judged. ``ownership``
is who answers for what. ``findings`` is what each check established.
``capability`` is the pair of controls decided by argument rather than by setting.
``verdict`` is the conclusion and the reason codes behind it.

**No wall clock, and no absolute path.** The only time here is the commit's own
date, which is a fact about the tree rather than about the run. Every path is
repository-relative — this file is uploaded as a CI artifact from a public
repository, and on the development host every absolute path contains the account
holder's full name.
"""

import hashlib
import json
from typing import Final

from tools.quality.governance.plan import GovernanceError

SCHEMA: Final[str] = "globin.governance.manifest"
"""Identifies what kind of document this is, so a supply manifest fed to this
reader is refused by name rather than by a missing key."""

SCHEMA_VERSION: Final[int] = 1
"""Bumped whenever the document changes shape, and inside the digested payload so
that a canonicalisation change cannot collide with an older digest."""

DIGEST_PREFIX: Final[str] = "sha256:"
DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover, because it holds the digest."""

PHASE: Final[int] = 15

#: Every reason the governance gate can fail, as a stable identifier.
#:
#: Written out as constants rather than formatted from a message, on the
#: reasoning ``tools/quality/supply/manifest.py`` gives: a sentence is for a human
#: and changes when somebody improves the wording; a code is for a machine and
#: must not.
REASON_DECLARATION_UNREADABLE: Final[str] = "GOVERNANCE_DECLARATION_UNREADABLE"
REASON_FILE_MISSING: Final[str] = "GOVERNANCE_FILE_MISSING"
REASON_CODEOWNERS_DUPLICATE: Final[str] = "GOVERNANCE_CODEOWNERS_DUPLICATE"
REASON_CODEOWNERS_UNPARSEABLE: Final[str] = "GOVERNANCE_CODEOWNERS_UNPARSEABLE"
REASON_PATH_UNCOVERED: Final[str] = "GOVERNANCE_PATH_UNCOVERED"
REASON_PATTERN_UNMATCHED: Final[str] = "GOVERNANCE_PATTERN_UNMATCHED"
REASON_SENSITIVE_PATH_ABSENT: Final[str] = "GOVERNANCE_SENSITIVE_PATH_ABSENT"
REASON_POLICY_INCOMPLETE: Final[str] = "GOVERNANCE_POLICY_INCOMPLETE"
REASON_TEMPLATE_INCOMPLETE: Final[str] = "GOVERNANCE_TEMPLATE_INCOMPLETE"
REASON_PUBLIC_SOLICITATION: Final[str] = "GOVERNANCE_PUBLIC_SOLICITATION"
REASON_REPORTING_CHANNEL_DRIFT: Final[str] = "GOVERNANCE_REPORTING_CHANNEL_DRIFT"
REASON_MANIFEST_NONDETERMINISTIC: Final[str] = "GOVERNANCE_MANIFEST_NONDETERMINISTIC"
REASON_MANIFEST_LEAKAGE: Final[str] = "GOVERNANCE_MANIFEST_LEAKAGE"

REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_DECLARATION_UNREADABLE,
        REASON_FILE_MISSING,
        REASON_CODEOWNERS_DUPLICATE,
        REASON_CODEOWNERS_UNPARSEABLE,
        REASON_PATH_UNCOVERED,
        REASON_PATTERN_UNMATCHED,
        REASON_SENSITIVE_PATH_ABSENT,
        REASON_POLICY_INCOMPLETE,
        REASON_TEMPLATE_INCOMPLETE,
        REASON_PUBLIC_SOLICITATION,
        REASON_REPORTING_CHANNEL_DRIFT,
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
        whitespace, ASCII only, exactly as the supply and evidence manifests do
        it.
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
    ownership: dict[str, object],
    findings: dict[str, object],
    capability: dict[str, object],
    verdict: dict[str, object],
) -> dict[str, object]:
    """Assemble a manifest and seal it.

    Args:
        run: What was judged — repository, commit, and the declared locations.
        ownership: The code-owners arrangement, as patterns and coverage counts.
        findings: One entry per check, each carrying its own verdict and detail.
        capability: The controls decided by a written argument, each a state, an
            authority and a reason.
        verdict: The conclusion and the reason codes behind it.

    Returns:
        The document, digest included, ready to render.
    """
    document: dict[str, object] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE,
        "run": run,
        "ownership": ownership,
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
        GovernanceError: If the text is not JSON, is not a governance manifest,
            was written by a different schema version, or carries a digest that
            disagrees with its contents.

    The digest check is what makes this evidence rather than a note. A file edited
    by hand — to drop a finding, to change a verdict — is refused here rather than
    read and believed.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the governance manifest is not valid JSON: {fault}"
        raise GovernanceError(msg) from fault

    if not isinstance(document, dict):
        msg = f"a governance manifest must be a JSON object, found {type(document).__name__}"
        raise GovernanceError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"not a {SCHEMA} document: found schema {document.get('schema')!r}"
        raise GovernanceError(msg)

    version = document.get("schema_version")
    if version != SCHEMA_VERSION:
        msg = (
            f"this tool reads {SCHEMA} version {SCHEMA_VERSION}, and the document "
            f"declares {version!r}. Regenerate it rather than reading it anyway"
        )
        raise GovernanceError(msg)

    if document.get(DIGEST_KEY) != digest(document):
        msg = (
            "the governance manifest's digest does not describe its contents, so it has "
            "been edited or truncated. Regenerate it"
        )
        raise GovernanceError(msg)

    return document
