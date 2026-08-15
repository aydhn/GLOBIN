"""The canonical list of tests, and the digest that identifies it.

A manifest is what makes sharding answerable rather than hopeful. Without one,
"every test ran exactly once" is a claim; with one it is a comparison against a
named set.

Everything here is pure. Parsing takes text and returns node IDs; the digest
takes node IDs and returns a string. Nothing reads a file, starts a process or
consults the clock, which is what lets the whole module be tested from literals
— the same split ``tools/quality/mutation`` makes for the same reason.

**What the digest covers, and what it deliberately does not.** The payload is a
domain tag, the schema version, the selection expression, the count and the
sorted node IDs. Outside it, under ``meta``: when the manifest was generated, on
what platform, with which Python and which pytest. Those change between machines
without the *suite* changing, and a digest that moved with them could not answer
the only question it is for — do these two runs describe the same tests.

The schema version is inside the payload on purpose. If the canonicalisation
rules ever change, bumping the version must change every digest; otherwise an
old digest and a new one collide and the change is invisible.
"""

import hashlib
import json
import re
from typing import Final

SCHEMA: Final[str] = "globin.execution.manifest"
"""Identifies what kind of document this is, so a shard report fed to the
manifest reader is refused by name rather than by a missing key."""

SCHEMA_VERSION: Final[int] = 1
"""Bumped whenever the canonical payload changes shape."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""Names the algorithm in the value, so a future change is legible in the data."""

#: pytest's `--collect-only -q` summary, in both forms it takes. The plain form
#: is `866 tests collected in 0.58s`; with a marker expression it becomes
#: `240/963 tests collected (723 deselected) in 0.61s`.
SUMMARY_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<selected>\d+)(?:/\d+)? tests? collected", re.MULTILINE
)

#: A node ID as pytest writes one: a path, ``::``, then the rest.
#:
#: The path part refuses a backslash, because pytest emits forward slashes even
#: on Windows and a backslash there would mean the platform had started writing
#: paths its own way — a difference that must surface rather than be normalised
#: into a digest.
#:
#: The part **after** ``::`` deliberately permits a backslash, and that costs a
#: sentence because it is the opposite rule. pytest escapes special characters
#: inside a parametrised ID: a fixture string containing a newline appears as a
#: literal ``\n`` (two characters), and ``ç`` appears as ``\xe7``. Four real
#: tests in this repository are spelled that way. A blanket refusal dropped all
#: four, and only the count check below noticed.
#:
#: A newline or carriage return anywhere is still refused — those would split one
#: ID across two lines of the args file — and so is a leading ``@``, which
#: :mod:`argparse` would read as another file to expand.
NODE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[^\s\\@][^\\\n\r]*::[^\n\r]+$")


class ManifestError(Exception):
    """A manifest could not be read, parsed or trusted.

    Local to this package rather than a :mod:`globin.errors` type, for the
    reason ``tools/quality/mutation`` gives: a verifier that imports the package
    it verifies cannot report on one too broken to import.
    """


def parse_collection(output: str) -> tuple[str, ...]:
    """Read node IDs out of ``pytest --collect-only -q`` output.

    Args:
        output: Everything the collection run wrote to standard output.

    Returns:
        The node IDs, in the order pytest emitted them.

    Raises:
        ManifestError: If no summary line was found, if the count pytest
            reported disagrees with the number of IDs parsed, if a node ID is
            malformed, or if nothing was collected.

    The count comparison is the point of this function. pytest prints how many
    tests it collected, so the parser can check itself against the tool it is
    parsing rather than trusting its own regex — a free self-check, and the one
    that would catch a future change to the output format instead of silently
    producing a shorter manifest.
    """
    summary = SUMMARY_RE.search(output)
    if summary is None:
        msg = (
            "no collection summary found in pytest output. Expected a line like "
            "'866 tests collected in 0.58s'; the output format may have changed"
        )
        raise ManifestError(msg)

    lines = [line.strip() for line in output.splitlines()]
    node_ids = tuple(line for line in lines if line and NODE_ID_RE.match(line))

    stated = int(summary.group("selected"))
    if stated != len(node_ids):
        msg = (
            f"pytest reported {stated} tests but {len(node_ids)} node IDs were parsed. "
            f"The manifest would be wrong, so it is refused rather than written"
        )
        raise ManifestError(msg)
    if not node_ids:
        msg = "no tests were collected, so there is nothing to shard"
        raise ManifestError(msg)

    duplicates = sorted({name for name in node_ids if node_ids.count(name) > 1})
    if duplicates:
        msg = f"pytest reported the same node ID more than once: {duplicates}"
        raise ManifestError(msg)
    return node_ids


def canonical_order(node_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Sort node IDs into the order the digest is taken over.

    Args:
        node_ids: The IDs, in any order.

    Returns:
        The same IDs, sorted by code point.

    Plain :func:`sorted`, which means the same order on every platform and every
    Python version. Deliberately **not** pytest's traversal order: that depends
    on how the filesystem lists a directory, which is not something a digest
    should inherit.
    """
    return tuple(sorted(node_ids))


def digest(node_ids: tuple[str, ...], *, selection: str) -> str:
    r"""The stable identity of a set of tests.

    Args:
        node_ids: The IDs. Order does not matter; they are sorted first.
        selection: The marker expression the collection ran under. A manifest of
            ``unit`` is a different manifest from one of ``not external`` and
            must not digest alike.

    Returns:
        ``"sha256:"`` followed by 64 lowercase hexadecimal characters.

    ``sha256`` rather than ``md5`` or ``blake2b``: the first is flagged by
    Ruff's ``S324`` and arguing about a non-security use of a broken hash is a
    conversation worth not having; the second is equally available and less
    recognisable. With a few hundred short strings, speed decides nothing.

    The count is inside the payload so that ``["a\\nb"]`` and ``["a", "b"]``
    cannot hash alike. A newline in a node ID is already refused, which makes
    that unreachable — belt and braces, because a digest is exactly the place
    where "unreachable" ages badly.
    """
    ordered = canonical_order(node_ids)
    payload = "".join(
        [
            f"{SCHEMA}\n",
            f"schema_version={SCHEMA_VERSION}\n",
            f"selection={selection}\n",
            f"count={len(ordered)}\n",
            *(f"{node_id}\n" for node_id in ordered),
        ]
    )
    return DIGEST_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build(
    node_ids: tuple[str, ...], *, selection: str, meta: dict[str, object]
) -> dict[str, object]:
    """Assemble a manifest document.

    Args:
        node_ids: The collected IDs.
        selection: The marker expression they were collected under.
        meta: Volatile context — platform, versions, timings. Never digested.

    Returns:
        The document, ready to be rendered.
    """
    ordered = canonical_order(node_ids)
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "selection": selection,
        "count": len(ordered),
        "tests": list(ordered),
        "digest": digest(ordered, selection=selection),
        "meta": meta,
    }


def render(document: dict[str, object]) -> str:
    """Encode a document so that two writers cannot disagree about bytes.

    Args:
        document: Any of this package's documents.

    Returns:
        One line of JSON followed by a newline.

    ``sort_keys`` because key order must not depend on insertion order;
    ``separators`` because incidental whitespace is one more thing to differ
    about; and ``ensure_ascii`` because the result is then pure ASCII, which no
    editor, console codepage or ``core.autocrlf`` setting can alter.
    """
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def load(text: str) -> dict[str, object]:
    """Read a manifest back, refusing anything that cannot be trusted.

    Args:
        text: The rendered document.

    Returns:
        The document.

    Raises:
        ManifestError: If the text is not JSON, is not a manifest, was written
            by a different schema version, or carries a digest that disagrees
            with the tests it lists.

    The digest check is what makes a manifest evidence rather than a note. A
    file whose contents were edited by hand is refused here rather than being
    partitioned into shards that no longer describe the suite.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the manifest is not valid JSON: {fault}"
        raise ManifestError(msg) from fault

    if not isinstance(document, dict):
        msg = f"a manifest must be a JSON object, found {type(document).__name__}"
        raise ManifestError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"not a {SCHEMA} document: found schema {document.get('schema')!r}"
        raise ManifestError(msg)
    version = document.get("schema_version")
    if version != SCHEMA_VERSION:
        msg = (
            f"this tool reads {SCHEMA} version {SCHEMA_VERSION}, and the document "
            f"declares {version!r}. Regenerate it rather than reading it anyway"
        )
        raise ManifestError(msg)

    tests = document.get("tests")
    selection = document.get("selection")
    if not isinstance(tests, list) or not isinstance(selection, str):
        msg = "a manifest must carry a list of tests and a selection expression"
        raise ManifestError(msg)

    recomputed = digest(tuple(str(name) for name in tests), selection=selection)
    if document.get("digest") != recomputed:
        msg = (
            "the manifest's digest does not describe the tests it lists, so it has "
            "been edited or truncated. Regenerate it"
        )
        raise ManifestError(msg)
    return document
