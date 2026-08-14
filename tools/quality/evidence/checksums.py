"""SHA-256 over the evidence files, and the check that they still match.

Pure: takes names and bytes, returns text. The caller reads the files.

**What this proves, and what it does not.** A checksum manifest detects that a
file changed between being produced and being read — a truncated upload, a
corrupted archive, an artifact somebody edited before quoting it. It is an
**integrity check, not a signature**: anybody who can alter a file can also
recompute its digest and rewrite this list. It carries no proof of origin.

Signing, provenance and attestation are deliberately out of scope. They need key
material, and key material needs the secret-handling policy that **Phase 015**
owns. Saying so here is the point: a checksum file looks like security, and the
difference is worth one paragraph rather than a later argument.

**Determinism.** Entries are sorted by path, paths are written with forward
slashes whatever produced them, and the manifest never lists itself. Two runs
over the same files produce the same bytes on Windows and on POSIX, which is what
makes the file comparable rather than merely present.
"""

import hashlib
from pathlib import PurePath
from typing import Final

from tools.quality.evidence.junit import EvidenceError

#: Names the algorithm in the file, so a future change is legible in the data
#: rather than inferred from the digest's length.
ALGORITHM: Final[str] = "sha256"

#: Two spaces between digest and path, as `sha256sum` writes them. Not because
#: anything here shells out to it, but because a person who pipes this file into
#: that tool should get the answer they expect.
SEPARATOR: Final[str] = "  "


def digest(payload: bytes) -> str:
    """The SHA-256 of some bytes.

    Args:
        payload: The file's contents.

    Returns:
        Sixty-four lowercase hexadecimal characters.
    """
    return hashlib.sha256(payload).hexdigest()


def relative_name(path: PurePath, *, root: PurePath) -> str:
    """A path as it should appear in the manifest.

    Args:
        path: The file.
        root: The directory the manifest describes.

    Returns:
        The path relative to ``root``, with forward slashes.

    Raises:
        EvidenceError: If ``path`` is not inside ``root``.

    Normalising the separator is what lets a manifest written on Windows be
    verified on POSIX and compare equal. Refusing a path outside the root is what
    stops an absolute path — carrying a user name and a home directory — reaching
    a file that gets uploaded.
    """
    try:
        relative = path.relative_to(root)
    except ValueError as fault:
        msg = (
            f"{path} is not inside {root}, so it has no relative name; a manifest "
            f"must not carry an absolute path"
        )
        raise EvidenceError(msg) from fault
    return relative.as_posix()


def render(entries: dict[str, bytes]) -> str:
    """Write a checksum manifest.

    Args:
        entries: Each file's relative name and its contents.

    Returns:
        One ``digest  name`` line per file, sorted by name, newline-terminated.

    Sorted by name rather than by insertion order, so that the file does not
    depend on the order a directory happened to be walked in.
    """
    lines = [f"{digest(payload)}{SEPARATOR}{name}" for name, payload in sorted(entries.items())]
    return "\n".join(lines) + "\n" if lines else ""


def load(text: str) -> dict[str, str]:
    """Read a checksum manifest back.

    Args:
        text: The rendered file.

    Returns:
        Each recorded name and its digest.

    Raises:
        EvidenceError: If a line is malformed, or a name appears twice.

    A duplicate name is refused rather than resolved by last-wins. Two different
    digests for one path means the file describes something that cannot be true,
    and picking one of them would be inventing an answer.
    """
    recorded: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        recorded_digest, separator, name = line.partition(SEPARATOR)
        if not separator or not name or len(recorded_digest) != 64:
            msg = f"line {number} of the checksum manifest is malformed: {line!r}"
            raise EvidenceError(msg)
        if name in recorded:
            msg = f"the checksum manifest lists {name!r} more than once"
            raise EvidenceError(msg)
        recorded[name] = recorded_digest
    return recorded


def verify(recorded: dict[str, str], present: dict[str, bytes]) -> tuple[str, ...]:
    """Compare a manifest against the files it describes.

    Args:
        recorded: What the manifest claims, from :func:`load`.
        present: What is actually on disk.

    Returns:
        One human-readable line per disagreement, sorted, empty when everything
        matches.

    Reports all three kinds of disagreement rather than the first: a file whose
    contents changed, one the manifest lists that is gone, and one that appeared
    without being listed. The third matters as much as the others — an artifact
    containing a file nobody recorded is an artifact nobody has checked.
    """
    problems: list[str] = []
    for name in sorted(set(recorded) | set(present)):
        if name not in present:
            problems.append(f"{name}: recorded but missing")
        elif name not in recorded:
            problems.append(f"{name}: present but not recorded")
        elif (actual := digest(present[name])) != recorded[name]:
            problems.append(f"{name}: contents changed (recorded {recorded[name]}, found {actual})")
    return tuple(problems)
