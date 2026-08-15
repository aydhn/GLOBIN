"""One document recording everything this phase established, and its own digest.

The shape is the one ``tools/quality/evidence/manifest.py`` and
``tools/quality/execution/manifest.py`` already proved, for the reason the former
gives: repeating a solved solution is cheaper than inventing a second one, and a
reader who knows one knows all three. A ``SCHEMA`` name and a ``SCHEMA_VERSION``
inside the digested payload, canonical JSON so two writers cannot disagree about
bytes, and a :func:`load` that refuses an unsupported version *and* recomputes the
digest.

**Sections, and why they are separated.** ``run`` is what was judged. ``findings``
is what each check established. ``capability`` is what the platform would answer.
``verdict`` is the conclusion and the reason codes behind it. A reader comparing
two manifests for one commit should see differences only in ``capability``,
because that is the one section whose answer lives somewhere this repository does
not control.

**Reason codes are stable strings, not sentences.** A sentence is for a human and
changes when somebody improves the wording; a code is for a machine and must not.
Both are recorded — the code in ``verdict.reasons`` and the prose beside the
finding it came from.

**No wall clock.** The only time in this document is the commit's own date, which
is a fact about the tree rather than about the run. ADR-0040 requires it of
evidence and the SBOM's determinism depends on it.
"""

import hashlib
import json
from typing import Final

from tools.quality.supply.inventory import SupplyChainError

SCHEMA: Final[str] = "globin.supply.manifest"
"""Identifies what kind of document this is, so an evidence manifest fed to this
reader is refused by name rather than by a missing key."""

SCHEMA_VERSION: Final[int] = 1
"""Bumped whenever the document changes shape, and inside the digested payload so
that a canonicalisation change cannot collide with an older digest."""

DIGEST_PREFIX: Final[str] = "sha256:"
DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover, because it holds the digest."""

PHASE: Final[int] = 14

#: Every reason a supply-chain gate can fail, as a stable identifier.
#:
#: Written out as constants rather than formatted from a message, so that a
#: dashboard or a later phase can count them without parsing English. The prose
#: explaining any particular occurrence lives beside the finding it describes.
REASON_INVENTORY_DRIFT: Final[str] = "SUPPLY_INVENTORY_DRIFT"
REASON_ACTION_UNPINNED: Final[str] = "SUPPLY_ACTION_UNPINNED"
REASON_ACTION_UNDOCUMENTED: Final[str] = "SUPPLY_ACTION_UNDOCUMENTED"
REASON_DOCKER_UNDIGESTED: Final[str] = "SUPPLY_DOCKER_UNDIGESTED"
REASON_SBOM_INVALID: Final[str] = "SUPPLY_SBOM_INVALID"
REASON_SBOM_NONDETERMINISTIC: Final[str] = "SUPPLY_SBOM_NONDETERMINISTIC"
REASON_AUDIT_UNMEASURED: Final[str] = "SUPPLY_AUDIT_UNMEASURED"
REASON_AUDIT_VULNERABLE: Final[str] = "SUPPLY_AUDIT_VULNERABLE"
REASON_WAIVER_EXPIRED: Final[str] = "SUPPLY_WAIVER_EXPIRED"
REASON_SECRET_FOUND: Final[str] = "SUPPLY_SECRET_FOUND"  # noqa: S105 - a reason code about secrets, not a secret
REASON_SECRET_ALLOWANCE_STALE: Final[str] = "SUPPLY_SECRET_ALLOWANCE_STALE"  # noqa: S105 - a reason code about secrets, not a secret
REASON_CAPABILITY_REGRESSED: Final[str] = "SUPPLY_CAPABILITY_REGRESSED"

REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_INVENTORY_DRIFT,
        REASON_ACTION_UNPINNED,
        REASON_ACTION_UNDOCUMENTED,
        REASON_DOCKER_UNDIGESTED,
        REASON_SBOM_INVALID,
        REASON_SBOM_NONDETERMINISTIC,
        REASON_AUDIT_UNMEASURED,
        REASON_AUDIT_VULNERABLE,
        REASON_WAIVER_EXPIRED,
        REASON_SECRET_FOUND,
        REASON_SECRET_ALLOWANCE_STALE,
        REASON_CAPABILITY_REGRESSED,
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
        whitespace, ASCII only, exactly as the evidence manifest does it.
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
    findings: dict[str, object],
    capability: dict[str, object],
    verdict: dict[str, object],
) -> dict[str, object]:
    """Assemble a manifest and seal it.

    Args:
        run: What was judged — commit, repository, branch, and the specification
            versions this phase targets.
        findings: One entry per check, each carrying its own verdict and detail.
        capability: One entry per platform control, each a state and a reason.
        verdict: The conclusion and the reason codes behind it.

    Returns:
        The document, digest included, ready to render.
    """
    document: dict[str, object] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE,
        "run": run,
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
        SupplyChainError: If the text is not JSON, is not a supply manifest, was
            written by a different schema version, or carries a digest that
            disagrees with its contents.

    The digest check is what makes this evidence rather than a note. A file edited
    by hand — to drop a finding, to change a verdict — is refused here rather than
    read and believed.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the supply manifest is not valid JSON: {fault}"
        raise SupplyChainError(msg) from fault

    if not isinstance(document, dict):
        msg = f"a supply manifest must be a JSON object, found {type(document).__name__}"
        raise SupplyChainError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"not a {SCHEMA} document: found schema {document.get('schema')!r}"
        raise SupplyChainError(msg)

    version = document.get("schema_version")
    if version != SCHEMA_VERSION:
        msg = (
            f"this tool reads {SCHEMA} version {SCHEMA_VERSION}, and the document "
            f"declares {version!r}. Regenerate it rather than reading it anyway"
        )
        raise SupplyChainError(msg)

    if document.get(DIGEST_KEY) != digest(document):
        msg = (
            "the supply manifest's digest does not describe its contents, so it has "
            "been edited or truncated. Regenerate it"
        )
        raise SupplyChainError(msg)

    return document
