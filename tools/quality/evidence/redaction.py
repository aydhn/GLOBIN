"""A narrow check that nothing secret-shaped reached the evidence files.

Pure: takes text, returns findings.

**Scope, stated first, because the risk here is scope.** This inspects the files
this package produces, immediately before they are uploaded, and nothing else. It
is **not** a repository secret scanner — `.pre-commit-config.yaml` already runs
one of those over the tree — and it is not the secret-handling policy, which is
`docs/security/SECURITY_BASELINE.md`. A check that grew into either would be
doing another document's work badly. What this *implements* is one clause of that
policy: that a value which must not be published is removed before the record
exists rather than before it is displayed.

**Why it exists at all, given that.** Because the evidence pipeline is the one
place in this repository that takes files off a build machine and publishes them.
`pyproject.toml` sets `junit_logging = "no"` so captured output never reaches the
XML in the first place, and the manifest is assembled from values this package
chose rather than from anything scraped. This is the backstop for both: if a
later change starts capturing output, or a new manifest field carries something
it should not, the gate says so before the artifact is uploaded rather than after
somebody downloads it.

**It is fail-safe, not fail-proof.** It matches shapes, so a secret spelled in a
way nobody anticipated passes. A checker that claimed otherwise would be worse
than one that says what it does.
"""

import re
from dataclasses import dataclass
from typing import Final

#: Names that mean "this value is a secret", in the spellings a config file, an
#: environment variable or a JSON payload would use. Deliberately the same idea
#: as `globin.domain.observability`'s redaction — which keys on field names
#: rather than on value shapes — and deliberately not an import of it: a
#: verifier does not import the package it verifies.
SENSITIVE_NAMES: Final[tuple[str, ...]] = (
    "api_key",
    "apikey",
    "api-key",
    "secret",
    "password",
    "passwd",
    "token",
    "credential",
    "private_key",
    "authorization",
    "auth_token",
    "session_id",
    "cookie",
)

#: A sensitive name followed by an assignment and a value with something in it.
#:
#: The optional quote *before* the separator is what makes this match JSON as
#: well as an environment variable: `"token": "..."` closes the key before the
#: colon, and without it this would inspect the evidence manifest — a JSON file —
#: and find nothing by construction.
#:
#: The value must be at least eight characters, which is what keeps `token = ""`
#: and `secret: null` — both of which appear in placeholder configuration — from
#: being reported as leaks.
ASSIGNMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<name>" + "|".join(SENSITIVE_NAMES) + r")"
    r"[\"']?\s*[=:]\s*"
    r"[\"']?(?P<value>[A-Za-z0-9_\-./+]{8,})",
    re.IGNORECASE,
)

#: Shapes that are a credential whatever they are called. A bearer token in a
#: header and a private key block both identify themselves.
LITERAL_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("a bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9_\-.]{16,}", re.IGNORECASE)),
    ("a private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a URL carrying credentials", re.compile(r"://[^\s/:@]+:[^\s/@]+@")),
    # An absolute path is not a credential, and it is here for the same reason
    # the others are: it is something this machine knows and an artifact should
    # not carry. On this host every absolute path contains the account holder's
    # full name, so a published file holding one names a person. Found in
    # practice -- `coverage xml` writes the repository root into a `<source>`
    # element -- which is why the gate now normalises it and this says so if the
    # normalisation ever stops working.
    (
        "an absolute Windows path",
        re.compile(r"\b[A-Za-z]:[\\/]{1,2}(?:Users|home)\b", re.IGNORECASE),
    ),
    ("an absolute home path", re.compile(r"(?:^|[\s\"'(])/(?:home|Users)/[^\s\"')]+")),
)


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing that looked like a secret.

    Args:
        source: Which evidence file it was found in.
        line: The one-based line number.
        description: What matched, named rather than quoted.

    The matched text is deliberately **not** carried. A finding is printed, and
    printing the suspected secret in the CI log that the gate exists to keep it
    out of would be the whole failure, committed by the check meant to prevent
    it.
    """

    source: str
    line: int
    description: str


def scan(source: str, text: str) -> tuple[Finding, ...]:
    """Look for secret-shaped content in one evidence file.

    Args:
        source: The file's relative name, for the report.
        text: Its contents.

    Returns:
        Every finding, in the order the lines appear.
    """
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if match := ASSIGNMENT_RE.search(line):
            findings.append(
                Finding(
                    source=source,
                    line=number,
                    description=f"a value assigned to {match.group('name').lower()!r}",
                )
            )
        findings.extend(
            Finding(source=source, line=number, description=description)
            for description, pattern in LITERAL_PATTERNS
            if pattern.search(line)
        )
    return tuple(findings)


def describe(findings: tuple[Finding, ...]) -> str:
    """Render findings for a person, without reproducing what was found.

    Args:
        findings: What :func:`scan` returned.

    Returns:
        One line per finding, sorted so two runs report identically.
    """
    lines = sorted(f"  {item.source}:{item.line}: {item.description}" for item in findings)
    return "\n".join(lines)
