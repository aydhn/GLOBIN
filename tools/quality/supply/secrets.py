"""Looking inside files for credentials, and reporting what was found without repeating it.

``tests/contract/test_repository_contract.py`` checks *filenames*, and says why:
"a regular expression hunting for secrets inside files would miss anything
unusual". That remains true, and this module does not replace it. What it adds is
the other half — a file called ``config.py`` containing a private key is invisible
to a filename check, and that is the shape most real leaks have.

**Reported as fingerprints, never as values.** A scanner that prints what it
found has published the secret a second time, into a log, an artifact and a CI
step summary, all of which outlive the file. Every finding here carries a
truncated SHA-256 of the match and nothing else. Two runs finding the same secret
produce the same fingerprint, which is enough to tell "still there" from "a new
one" without anybody ever seeing the value.

**High-confidence patterns only.** Each pattern below matches a shape that is a
credential or is nothing — a key header, a provider's token prefix and length, a
bot-token grammar. Entropy heuristics are deliberately absent: this repository is
full of SHA-256 digests, forty-character commits and Hypothesis seeds, and a
scanner that flagged those would be turned off within a week.

**The allowlist is per file and per pattern.** Not per file, which would blind
the scanner to everything else in a file exempted for one reason, and never
global. Each entry states why. The two entries that exist are this module and the
test that exercises it, which necessarily contain the patterns they look for.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final

FINGERPRINT_LENGTH: Final[int] = 12
"""How much of the digest to show.

Twelve hexadecimal characters is forty-eight bits — far too few to reverse, and
far more than enough to distinguish the handful of findings a repository could
ever have at once. Showing the whole digest would invite somebody to try
confirming a guess against it.
"""


@dataclass(frozen=True, slots=True, order=True)
class Finding:
    """One suspected credential, described without being repeated.

    Args:
        path: The repository-relative file it was found in.
        line: The one-based line number.
        pattern: Which pattern matched, by name.
        fingerprint: A truncated SHA-256 of the matched text.
    """

    path: str
    line: int
    pattern: str
    fingerprint: str

    def as_document(self) -> dict[str, object]:
        """This finding as JSON-ready values.

        Returns:
            The mapping. It contains no part of the matched text, which is the
            property the whole module exists to preserve.
        """
        return {
            "path": self.path,
            "line": self.line,
            "pattern": self.pattern,
            "fingerprint": self.fingerprint,
        }


#: Every pattern, by name. The names are what an allowlist entry refers to, so
#: they are part of the contract and not merely labels.
#:
#: Each is anchored on a shape its issuer defines. `ghp_` and its siblings are
#: GitHub's documented token prefixes; `AKIA` is an AWS access key identifier;
#: `xox` with a type letter is Slack's; a Telegram bot token is a numeric id, a
#: colon and a fixed-length secret. A PEM header is not a guess at all.
PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "private-key-header": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "github-fine-grained-token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b"),
    "aws-access-key-id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "telegram-bot-token": re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_\-]{32,33}\b"),
    "putty-private-key": re.compile(r"PuTTY-User-Key-File-\d"),
}

#: Where a pattern is permitted to match, and why. A pair of file and pattern,
#: never a bare file — exempting a whole file would blind the scanner to every
#: other pattern in it, which is how an allowlist stops meaning anything.
ALLOWED: Final[dict[tuple[str, str], str]] = {
    ("tools/quality/supply/secrets.py", name): (
        "this module defines the pattern; it cannot look for a shape it may not contain"
    )
    for name in PATTERNS
} | {
    ("tests/unit/test_supply_secrets.py", name): (
        "the test proves each pattern fires, which requires a string that matches it. "
        "Every value there is syntactically valid and cryptographically worthless"
    )
    for name in PATTERNS
}

#: Files whose contents are not text and cannot be scanned as such. Judged by
#: suffix rather than by sniffing bytes, because the set is small and known.
BINARY_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".whl", ".pyc"}
)


def fingerprint(matched: str) -> str:
    """A stable, non-reversible identifier for a matched string.

    Args:
        matched: The text a pattern matched. Never stored, never returned.

    Returns:
        The first :data:`FINGERPRINT_LENGTH` hexadecimal characters of its
        SHA-256.
    """
    return hashlib.sha256(matched.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


def scan_text(path: str, text: str) -> tuple[Finding, ...]:
    """Every credential-shaped string in one file.

    Args:
        path: The repository-relative path, used both for reporting and for
            consulting :data:`ALLOWED`.
        text: The file's contents.

    Returns:
        One finding per match, ordered by line then by pattern name so that two
        runs over one file report identically.

    A file may match several patterns and a line may match more than one; each is
    reported separately, because "there is a secret in this file" is a much less
    useful sentence than "line 40 looks like an AWS key".
    """
    found: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for name in sorted(PATTERNS):
            if (path, name) in ALLOWED:
                continue
            for match in PATTERNS[name].finditer(line):
                found.append(
                    Finding(
                        path=path,
                        line=number,
                        pattern=name,
                        fingerprint=fingerprint(match.group(0)),
                    )
                )
    return tuple(sorted(found))


def scannable(path: str) -> bool:
    """Whether a file is worth reading as text.

    Args:
        path: The repository-relative path.

    Returns:
        ``False`` for the suffixes in :data:`BINARY_SUFFIXES`, ``True``
        otherwise. A file with no suffix is scanned: ``.gitattributes`` and
        ``LICENSE`` are text, and so is almost anything else without one.

    ``PurePosixPath`` rather than ``Path`` because the paths handed here come
    from ``git ls-files``, which reports forward slashes on every platform. Using
    the local flavour would make this behave differently on Windows for no reason
    anybody wants.
    """
    return PurePosixPath(path).suffix not in BINARY_SUFFIXES


def unused_allowances(scanned: frozenset[str]) -> tuple[str, ...]:
    """Allowlist entries for files that no longer exist.

    Args:
        scanned: Every path that was scanned.

    Returns:
        One sentence per stale entry.

    An allowlist that keeps entries for deleted files is an allowlist nobody
    maintains, and the next person to read it cannot tell which lines still mean
    something. This turns that into a failing check rather than a comment.
    """
    stale = sorted({path for path, _ in ALLOWED if path not in scanned})
    return tuple(
        f"{path} is allowlisted in secrets.py but was not scanned; remove the entry"
        for path in stale
    )
