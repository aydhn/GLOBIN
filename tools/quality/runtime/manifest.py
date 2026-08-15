"""One document recording the host this repository was verified on, and its digest.

The shape is the one ``tools/quality/governance/manifest.py`` already proved, for
the reason that module gives about the two before it: repeating a solved solution
is cheaper than inventing a second one, and a reader who knows one knows all five.
A ``SCHEMA`` name and a ``SCHEMA_VERSION`` inside the digested payload, canonical
JSON so two writers cannot disagree about bytes, and a :func:`load` that refuses
an unsupported version *and* recomputes the digest.

**Sections, and why they are separated.** ``run`` is what was judged, including
the contract it was judged against. ``observed`` is what the machine reports about
itself — host, interpreter, environment, pip and launcher discovery. ``findings``
is what each check established. ``capability`` is the pair of platform facts that
are states rather than passes (ADR-0045). ``verdict`` is the conclusion and the
reason codes behind it.

**No wall clock, and no absolute path.** The only time here is the commit, which
is a fact about the tree rather than about the run. Every path has been through
:func:`tools.quality.runtime.plan.recorded_path` first, so a path inside the
repository appears relative to it and a path outside appears as a fingerprint —
this file is uploaded as a CI artifact from a public repository, and on the
development host the interpreter and ``pip`` both live under directories carrying
the account holder's full name.

**No configuration value, ever.** ``pip`` configuration is recorded as which
sources exist and which ``PIP_*`` variables are set, by name. Never a value: an
index URL is the single most likely place in this whole document for a credential
to appear, and the way to keep one out is not to read it.
"""

import hashlib
import json
from typing import Final

from tools.quality.runtime.plan import RuntimeBaselineError

SCHEMA: Final[str] = "globin.runtime.manifest"
"""Identifies what kind of document this is, so a governance manifest fed to this
reader is refused by name rather than by a missing key."""

SCHEMA_VERSION: Final[int] = 1
"""Bumped whenever the document changes shape, and inside the digested payload so
that a canonicalisation change cannot collide with an older digest."""

DIGEST_PREFIX: Final[str] = "sha256:"
DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover, because it holds the digest."""

PHASE: Final[int] = 17

#: Every reason the runtime gate can fail, as a stable identifier.
#:
#: Written out as constants rather than formatted from a message, on the reasoning
#: ``tools/quality/supply/manifest.py`` gives: a sentence is for a human and
#: changes when somebody improves the wording; a code is for a machine and must
#: not.
REASON_DECLARATION_UNREADABLE: Final[str] = "RUNTIME_DECLARATION_UNREADABLE"
REASON_HOST_UNSUPPORTED: Final[str] = "RUNTIME_HOST_UNSUPPORTED"
REASON_INTERPRETER_NONCOMPLIANT: Final[str] = "RUNTIME_INTERPRETER_NONCOMPLIANT"
REASON_INTERPRETER_FOREIGN: Final[str] = "RUNTIME_INTERPRETER_FOREIGN"
REASON_ENVIRONMENT_ABSENT: Final[str] = "RUNTIME_ENVIRONMENT_ABSENT"
REASON_ENVIRONMENT_NONCOMPLIANT: Final[str] = "RUNTIME_ENVIRONMENT_NONCOMPLIANT"
REASON_PIP_FOREIGN: Final[str] = "RUNTIME_PIP_FOREIGN"
REASON_TOOLCHAIN_UNAVAILABLE: Final[str] = "RUNTIME_TOOLCHAIN_UNAVAILABLE"
REASON_BOOTSTRAP_FAILED: Final[str] = "RUNTIME_BOOTSTRAP_FAILED"
REASON_DELETION_REFUSED: Final[str] = "RUNTIME_DELETION_REFUSED"
REASON_MANIFEST_NONDETERMINISTIC: Final[str] = "RUNTIME_MANIFEST_NONDETERMINISTIC"
REASON_MANIFEST_LEAKAGE: Final[str] = "RUNTIME_MANIFEST_LEAKAGE"

REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_DECLARATION_UNREADABLE,
        REASON_HOST_UNSUPPORTED,
        REASON_INTERPRETER_NONCOMPLIANT,
        REASON_INTERPRETER_FOREIGN,
        REASON_ENVIRONMENT_ABSENT,
        REASON_ENVIRONMENT_NONCOMPLIANT,
        REASON_PIP_FOREIGN,
        REASON_TOOLCHAIN_UNAVAILABLE,
        REASON_BOOTSTRAP_FAILED,
        REASON_DELETION_REFUSED,
        REASON_MANIFEST_NONDETERMINISTIC,
        REASON_MANIFEST_LEAKAGE,
    }
)
"""The closed set. A contract test asserts that every code the gate can emit is in
here, so a new failure mode cannot arrive with an undeclared name."""


def render(document: dict[str, object]) -> str:
    """Encode a manifest so that two writers cannot disagree about bytes.

    Args:
        document: The manifest.

    Returns:
        One line of JSON followed by a newline — sorted keys, no incidental
        whitespace, ASCII only, exactly as the governance and supply manifests do
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
    observed: dict[str, object],
    findings: dict[str, object],
    capability: dict[str, object],
    verdict: dict[str, object],
) -> dict[str, object]:
    """Assemble a manifest and seal it.

    Args:
        run: What was judged — repository, commit, and the contract's own terms.
        observed: What the machine reports about itself, with every path already
            reduced to a repository-relative spelling or a fingerprint.
        findings: One entry per check, each carrying its own verdict and detail.
        capability: The platform facts that are states rather than passes.
        verdict: The conclusion and the reason codes behind it.

    Returns:
        The document, digest included, ready to render.
    """
    document: dict[str, object] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE,
        "run": run,
        "observed": observed,
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
        RuntimeBaselineError: If the text is not JSON, is not a runtime manifest,
            was written by a different schema version, or carries a digest that
            disagrees with its contents.

    The digest check is what makes this evidence rather than a note. A file edited
    by hand — to drop a finding, to change a verdict — is refused here rather than
    read and believed.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the runtime manifest is not valid JSON: {fault}"
        raise RuntimeBaselineError(msg) from fault

    if not isinstance(document, dict):
        msg = f"a runtime manifest must be a JSON object, found {type(document).__name__}"
        raise RuntimeBaselineError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"not a {SCHEMA} document: found schema {document.get('schema')!r}"
        raise RuntimeBaselineError(msg)

    version = document.get("schema_version")
    if version != SCHEMA_VERSION:
        msg = (
            f"this tool reads {SCHEMA} version {SCHEMA_VERSION}, and the document "
            f"declares {version!r}. Regenerate it rather than reading it anyway"
        )
        raise RuntimeBaselineError(msg)

    if document.get(DIGEST_KEY) != digest(document):
        msg = (
            "the runtime manifest's digest does not describe its contents, so it has "
            "been edited or truncated. Regenerate it"
        )
        raise RuntimeBaselineError(msg)

    return document
