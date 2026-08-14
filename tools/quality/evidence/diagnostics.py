"""Reading a linter's and a type checker's output into one comparable shape.

Pure. Parsing takes text and returns values; building takes values and returns a
document; rendering takes a document and returns bytes. Nothing here starts a
process or touches disk.

**Why this exists at all.** A test result was already evidence; a lint result and
a type result were not, so a run whose suite passed and whose types did not left
nothing behind to read. Both tools can say what they found in a form a machine
reads — ``ruff check --output-format=json`` and ``mypy --output=json``, both
verified against the pinned versions and recorded in
``docs/research/phase_011_sources.md`` — so neither needs a plugin and ADR-0032's
third condition holds.

**The rule worth knowing before reading the code.** *Every path is normalised, and
a path that cannot be normalised is not written.* Measured on this machine,
``ruff check . --output-format=json`` reports each ``filename`` as an absolute
Windows path beginning ``C:\\Users\\`` and continuing with the account's name —
even when the target given was ``.``. That string names a person, and the
evidence directory is uploaded to GitHub Actions. mypy is better behaved and emits
repository-relative paths, but with Windows separators, so the same run described
on two operating systems would not compare. Both problems have one answer:
repository-relative, forward slashes, always.

**What this is not.** It is not a second linter: no rule is interpreted, no
severity is judged, and a diagnostic is copied rather than assessed. Whether the
tools passed is their exit code's business, not this module's.
"""

import json
from dataclasses import dataclass
from typing import Final

from tools.quality.evidence.junit import EvidenceError

SCHEMA: Final[str] = "globin.evidence.diagnostics"
"""Identifies what kind of document this is, so a manifest fed to the diagnostics
reader is refused by name rather than by a missing key."""

SCHEMA_VERSION: Final[int] = 1
"""Bumped whenever the document changes shape."""

OUTSIDE_MARKER: Final[str] = "<outside>"
"""Stands in for the directories above the repository.

A path that does not sit under the root is reduced to this and its final
component. Emitting it verbatim is the leak this module exists to prevent, and
dropping the diagnostic entirely would hide a real finding, so the name survives
and the location does not.
"""

FORMAT_CODE: Final[str] = "format"
"""The code recorded for a file ``ruff format --check`` would rewrite.

``ruff format`` reports filenames rather than rules, so there is no code to copy.
Inventing one that looked like a Ruff rule would be worse than naming the tool's
own concern.
"""

FORMAT_PREFIX: Final[str] = "Would reformat: "
"""How ``ruff format --check`` announces a file it would rewrite.

Verified against ruff 0.15.14, which is the version ``.github/workflows/quality.yml``
pins and ``.pre-commit-config.yaml`` matches.
"""


@dataclass(frozen=True, slots=True, order=True)
class Diagnostic:
    """One thing a tool found, in the one shape both tools are read into.

    Args:
        path: Repository-relative, forward slashes, always.
        line: One-based, or zero where the finding is about the file rather than
            a place in it.
        column: One-based, or zero for the same reason.
        code: The rule or error code, empty where the tool gave none.
        message: What the tool said, copied and not interpreted.

    Ordered, and the field order is the sort order: two runs over the same tree
    must produce byte-identical evidence, and a tool's own output order is not
    guaranteed to be stable.
    """

    path: str
    line: int
    column: int
    code: str
    message: str


def normalise_path(text: str, *, repo_root: str) -> str:
    """Reduce a path a tool reported to one that names only the repository.

    Args:
        text: The path as the tool wrote it, absolute or relative, with either
            separator.
        repo_root: The repository root, as the caller knows it.

    Returns:
        A repository-relative path with forward slashes, or
        :data:`OUTSIDE_MARKER` and the final component when the path is not
        inside the repository.

    Case is folded for the comparison only, never in the result. Windows reports
    the same directory as ``C:\\Users`` and ``c:\\users`` in different tools, and
    a comparison that missed on case would leak the very path it was checking.
    """
    forward = text.replace("\\", "/")
    root = repo_root.replace("\\", "/").rstrip("/")
    if root and forward.casefold().startswith(root.casefold() + "/"):
        return forward[len(root) + 1 :]
    if forward.startswith("./"):
        return forward[2:]
    if ":" in forward or forward.startswith("/"):
        return f"{OUTSIDE_MARKER}/{forward.rsplit('/', 1)[-1]}"
    return forward


def from_ruff(text: str, *, repo_root: str) -> tuple[Diagnostic, ...]:
    """Read ``ruff check --output-format=json`` output.

    Args:
        text: What Ruff wrote. An empty string and ``[]`` both mean no findings.
        repo_root: The repository root, for normalising paths.

    Returns:
        The diagnostics, sorted.

    Raises:
        EvidenceError: If the text is neither empty nor a JSON array of objects.
    """
    if not text.strip():
        return ()
    payload = _decode(text, tool="ruff")
    if not isinstance(payload, list):
        msg = f"ruff output must be a JSON array, found {type(payload).__name__}"
        raise EvidenceError(msg)
    found = []
    for entry in payload:
        if not isinstance(entry, dict):
            msg = f"a ruff diagnostic must be an object, found {type(entry).__name__}"
            raise EvidenceError(msg)
        location = entry.get("location")
        place = location if isinstance(location, dict) else {}
        found.append(
            Diagnostic(
                path=normalise_path(_text(entry.get("filename")), repo_root=repo_root),
                line=_count(place.get("row")),
                column=_count(place.get("column")),
                code=_text(entry.get("code")),
                message=_text(entry.get("message")),
            )
        )
    return tuple(sorted(found))


def from_ruff_format(text: str, *, repo_root: str) -> tuple[Diagnostic, ...]:
    """Read ``ruff format --check`` output.

    Args:
        text: What Ruff wrote, one ``Would reformat:`` line per file and a
            trailing count.
        repo_root: The repository root, for normalising paths.

    Returns:
        One diagnostic per file that would be rewritten, sorted.

    There is no JSON format for ``ruff format``, so this reads the documented
    line prefix. Every other line is ignored rather than refused: the trailing
    summary and any warning are not findings, and a parser that raised on them
    would fail on the ordinary case.
    """
    return tuple(
        sorted(
            Diagnostic(
                path=normalise_path(line.removeprefix(FORMAT_PREFIX).strip(), repo_root=repo_root),
                line=0,
                column=0,
                code=FORMAT_CODE,
                message="the file is not formatted",
            )
            for line in text.splitlines()
            if line.startswith(FORMAT_PREFIX)
        )
    )


def from_mypy(text: str, *, repo_root: str) -> tuple[Diagnostic, ...]:
    """Read ``mypy --output=json`` output.

    Args:
        text: What mypy wrote, one JSON object per line.
        repo_root: The repository root, for normalising paths.

    Returns:
        The diagnostics, sorted.

    Raises:
        EvidenceError: If a line begins an object and is not one.

    mypy emits JSON Lines rather than a JSON array, so this reads line by line.
    A line that does not start with ``{`` is skipped rather than refused, because
    mypy's own summary is written alongside the diagnostics and is not one.
    """
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        entry = _decode(stripped, tool="mypy")
        if not isinstance(entry, dict):
            msg = f"a mypy diagnostic must be an object, found {type(entry).__name__}"
            raise EvidenceError(msg)
        found.append(
            Diagnostic(
                path=normalise_path(_text(entry.get("file")), repo_root=repo_root),
                line=_count(entry.get("line")),
                column=_count(entry.get("column")),
                code=_text(entry.get("code")),
                message=_text(entry.get("message")),
            )
        )
    return tuple(sorted(found))


def build(
    *, tool: str, command: str, exit_code: int | None, diagnostics: tuple[Diagnostic, ...]
) -> dict[str, object]:
    """Assemble a diagnostics document.

    Args:
        tool: Which tool produced it.
        command: The arguments it was given, for somebody reproducing the run.
            Repository-relative, because the interpreter's path is this machine's
            business.
        exit_code: What the tool returned, or ``None`` if it never did.
        diagnostics: What it found, already sorted.

    Returns:
        The document, ready to render.

    Carries no digest of its own. The manifest's digest covers the checksum of
    every file including this one, so a second seal here would be a second thing
    to keep in step for no additional guarantee.
    """
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "tool": tool,
        "command": command,
        "exit_code": exit_code,
        "count": len(diagnostics),
        "diagnostics": [
            {
                "path": entry.path,
                "line": entry.line,
                "column": entry.column,
                "code": entry.code,
                "message": entry.message,
            }
            for entry in diagnostics
        ],
    }


def render(document: dict[str, object]) -> str:
    """Encode a document so that two writers cannot disagree about bytes.

    Args:
        document: The diagnostics document.

    Returns:
        Indented JSON followed by a newline.

    Indented rather than compact, unlike the manifest: this file is read by a
    person looking for what failed, and the digest that makes byte-stability
    matter is taken over it from outside. ``sort_keys`` and ``ensure_ascii`` are
    kept for the manifest's reasons — key order must not depend on insertion
    order, and a non-ASCII path or message must not depend on the console.
    """
    return json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def _decode(text: str, *, tool: str) -> object:
    """Parse JSON, naming the tool whose output could not be read.

    Args:
        text: The JSON.
        tool: Which tool wrote it.

    Returns:
        Whatever it decoded to.

    Raises:
        EvidenceError: If the text is not JSON.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"{tool} output is not valid JSON: {fault}"
        raise EvidenceError(msg) from fault


def _text(value: object) -> str:
    """Read a string field, treating an absent or null one as empty.

    Args:
        value: What the tool wrote.

    Returns:
        The string, or ``""``.

    Ruff writes ``null`` for the code of a syntax error, and a diagnostic with no
    code is still a diagnostic. Refusing the whole report over one missing field
    would lose every other finding in it.
    """
    return value if isinstance(value, str) else ""


def _count(value: object) -> int:
    """Read a line or column, treating an unusable one as zero.

    Args:
        value: What the tool wrote.

    Returns:
        The number, or ``0``.

    ``bool`` is excluded explicitly: it is an ``int`` to :func:`isinstance`, and a
    report carrying ``True`` where a line number belongs is malformed rather than
    equal to one.
    """
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
