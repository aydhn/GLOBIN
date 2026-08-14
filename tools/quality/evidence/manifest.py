"""The evidence manifest: what a run was, what it found, and what it wrote.

Pure. Building takes values and returns a document; rendering takes a document
and returns bytes; loading takes bytes and returns a document or refuses it.

**The shape is deliberately the one ``tools/quality/execution/manifest.py``
already proved.** A ``SCHEMA`` name and a ``SCHEMA_VERSION`` inside the digested
payload, canonical JSON so two writers cannot disagree about bytes, and a
``load`` that refuses an unsupported version *and* recomputes the digest. That
module solved these problems for the shard manifest; repeating the solution is
cheaper than inventing a second one, and a reader who knows one knows both.

**What the digest covers.** Everything except the digest field itself. A
manifest is evidence, and evidence that could be edited in one section without
the digest noticing would be evidence about the sections somebody chose not to
edit.

**Two sections, and why.** ``run`` holds what the run *was* and what it *found* —
the commit, the interpreter, the platform, the counts, the coverage, the verdicts.
``timing`` holds durations. The split is for readers rather than for the digest:
two runs of the same tree differ in ``timing`` and nowhere else, so a reader
comparing two manifests knows immediately which differences are real.

**No timestamps, and no absolute paths.** A timestamp would make every manifest
differ from every other for no reason anybody cares about, and an absolute path
on this machine carries a user name into a file that CI publishes.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Final

from tools.quality.evidence.junit import EvidenceError

SCHEMA: Final[str] = "globin.evidence.manifest"
"""Identifies what kind of document this is, so a shard manifest fed to the
evidence reader is refused by name rather than by a missing key."""

SCHEMA_VERSION: Final[int] = 1
"""Bumped whenever the document changes shape. Inside the digested payload, so a
canonicalisation change cannot collide with an older digest."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""Names the algorithm in the value, so a future change is legible in the data."""

DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover, because it holds the digest."""


def render(document: dict[str, object]) -> str:
    """Encode a document so that two writers cannot disagree about bytes.

    Args:
        document: The manifest.

    Returns:
        One line of JSON followed by a newline.

    ``sort_keys`` because key order must not depend on insertion order;
    ``separators`` because incidental whitespace is one more thing to differ
    about; and ``ensure_ascii`` because the result is then pure ASCII, which no
    editor, console codepage or ``core.autocrlf`` setting can alter.
    """
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def digest(document: dict[str, object]) -> str:
    """The stable identity of a manifest's contents.

    Args:
        document: The manifest, with or without a digest already in it.

    Returns:
        ``"sha256:"`` followed by 64 lowercase hexadecimal characters.

    Taken over the canonical rendering of everything except the digest field, so
    that computing it and verifying it are the same operation on the same bytes.
    """
    payload = {key: value for key, value in document.items() if key != DIGEST_KEY}
    return DIGEST_PREFIX + hashlib.sha256(render(payload).encode("utf-8")).hexdigest()


def build(*, run: dict[str, object], timing: dict[str, object]) -> dict[str, object]:
    """Assemble a manifest and seal it.

    Args:
        run: What the run was and what it found.
        timing: What it cost. Separated so a reader comparing two manifests can
            see at once which differences are inherent.

    Returns:
        The document, digest included, ready to render.
    """
    document: dict[str, object] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "run": run,
        "timing": timing,
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
        EvidenceError: If the text is not JSON, is not a manifest, was written by
            a different schema version, or carries a digest that disagrees with
            its contents.

    The digest check is what makes a manifest evidence rather than a note. A file
    edited by hand — to change a count, to raise a coverage figure — is refused
    here rather than read and believed.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the evidence manifest is not valid JSON: {fault}"
        raise EvidenceError(msg) from fault

    if not isinstance(document, dict):
        msg = f"an evidence manifest must be a JSON object, found {type(document).__name__}"
        raise EvidenceError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"not a {SCHEMA} document: found schema {document.get('schema')!r}"
        raise EvidenceError(msg)

    version = document.get("schema_version")
    if version != SCHEMA_VERSION:
        msg = (
            f"this tool reads {SCHEMA} version {SCHEMA_VERSION}, and the document "
            f"declares {version!r}. Regenerate it rather than reading it anyway"
        )
        raise EvidenceError(msg)

    if document.get(DIGEST_KEY) != digest(document):
        msg = (
            "the evidence manifest's digest does not describe its contents, so it "
            "has been edited or truncated. Regenerate it"
        )
        raise EvidenceError(msg)
    return document


def counts_are_consistent(run: Mapping[str, object]) -> tuple[str, ...]:
    """Check a manifest's arithmetic against itself.

    Args:
        run: The ``run`` section. A :class:`~collections.abc.Mapping` because
            nothing here writes to it, and because an invariant ``dict``
            annotation would refuse a caller holding a narrower value type.

    Returns:
        One line per inconsistency, empty when the numbers add up.

    The outcome counts are produced by one parser from one file, so they should
    always agree. Checking anyway is cheap, and it is what would catch a future
    change that started assembling them from two sources — the point at which
    "should always agree" stops being true.
    """
    parts = ("passed", "failed", "errors", "skipped")
    counts: dict[str, int] = {}
    for name in (*parts, "collected"):
        value = run.get(name)
        # `bool` is excluded explicitly: it is an `int` to `isinstance`, and a
        # manifest carrying `True` where a count belongs is malformed rather
        # than equal to one.
        if not isinstance(value, int) or isinstance(value, bool):
            return (f"{name} is not an integer count: {value!r}",)
        counts[name] = value

    problems = [f"{name} is negative: {counts[name]}" for name in parts if counts[name] < 0]
    total = sum(counts[name] for name in parts)
    if total != counts["collected"]:
        problems.append(
            f"the outcomes sum to {total} but {counts['collected']} tests were "
            f"collected; one of them is wrong"
        )
    return tuple(problems)
