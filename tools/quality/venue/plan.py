"""The registry, read a second time and judged without trusting the first reader.

Nothing under ``tools/`` imports :mod:`globin`, and here that separation earns
something rather than merely obeying a rule: :mod:`globin.adapters.api_reality`
and this module parse the same document independently, so a registry the package
would mis-read is caught by a reader that shares none of its code. Phase 020 drew
the same line between its lock parser and the reference implementation.

**Every verdict below is recomputed from the document.** Nothing is believed
because it is written down: a ``restricted`` row must name its condition, an
endpoint filed under a marked environment must carry that environment's marker in
its host, and a row claiming to have been *observed* is refused outright because
GLOBIN has never contacted the venue.

**This module reaches no network.** It imports nothing that could. The half that
does is in :mod:`tools.quality.venue.gate`, behind a verb an operator has to
type.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

SUPPORTED_SCHEMA: Final[int] = 1
"""The registry shape this gate reads. Anything else is refused rather than read."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""What a recorded content digest begins with."""

DIGEST_LENGTH: Final[int] = 64
"""How many hexadecimal characters follow the prefix."""

HEX: Final[frozenset[str]] = frozenset("0123456789abcdef")
"""The alphabet a digest body is spelled with, lowercase."""

PERMITTED_SCHEMES: Final[frozenset[str]] = frozenset({"https", "wss", "tcp+tls"})
"""Every scheme an endpoint may carry. Each one is encrypted."""

PERMITTED_HOSTS: Final[tuple[str, ...]] = (
    "raw.githubusercontent.com",
    "github.com",
    "developers.binance.com",
    "data.binance.vision",
)
"""Hosts a source location may name, and no fifth.

Compared against the parsed hostname rather than against the string, so a URL whose
path or credentials merely *contain* an approved name is refused. The two GitHub
hosts are additionally constrained to the venue's own organisation by
:data:`REQUIRED_GITHUB_PREFIX`.
"""

GITHUB_HOSTS: Final[frozenset[str]] = frozenset({"raw.githubusercontent.com", "github.com"})
"""The hosts whose paths must name the venue's own organisation.

Named explicitly rather than matched by suffix, because
``"raw.githubusercontent.com".endswith("github.com")`` is **False** -- the raw host
ends with ``githubusercontent.com``. A suffix test was written here first and let
any repository on the service through; the test that found it is
``test_anything_else_is_refused[wrong-org]``.
"""

REQUIRED_GITHUB_PREFIX: Final[str] = "/binance/"
"""What a GitHub source path must begin with.

Without it, `raw.githubusercontent.com` would admit any repository on the service,
and a registry could cite somebody's fork as though it were the specification.
"""

OBSERVED: Final[str] = "observed"
"""The evidence kind nothing in this repository may claim."""

RESTRICTED: Final[str] = "restricted"
"""The status that must name the condition restricting it."""

LATEST: Final[str] = "latest"
"""The schema lifecycle state at most one version per family and environment holds."""

MANUAL: Final[str] = "manual"
"""The source regime that cannot take part in drift detection."""

STRUCTURED: Final[str] = "structured"
"""The source regime compared field by field rather than by digest."""

STATUSES: Final[frozenset[str]] = frozenset(
    {"supported", "unsupported", "unknown", "deprecated", "announced", RESTRICTED}
)
"""The six status words, restated here rather than imported.

A restatement is the point: if the package's vocabulary and this one diverge, the
gate fails and somebody looks, which is what a second reader is for.
"""

EVIDENCE_KINDS: Final[frozenset[str]] = frozenset({"documented", "inferred", OBSERVED})
"""The three evidence kinds."""

REASON_UNREADABLE: Final[str] = "API_REALITY_REGISTRY_UNREADABLE"
REASON_SCHEMA: Final[str] = "API_REALITY_SCHEMA_UNSUPPORTED"
REASON_SOURCE_UNDECLARED: Final[str] = "API_REALITY_SOURCE_UNDECLARED"
REASON_SOURCE_OFF_ALLOWLIST: Final[str] = "API_REALITY_SOURCE_OFF_ALLOWLIST"
REASON_DUPLICATE_IDENTITY: Final[str] = "API_REALITY_IDENTITY_DUPLICATED"
REASON_OBSERVED_CLAIMED: Final[str] = "API_REALITY_OBSERVED_CLAIMED"
REASON_CONDITION_MISSING: Final[str] = "API_REALITY_CONDITION_MISSING"
REASON_SCHEMA_AMBIGUOUS: Final[str] = "API_REALITY_LATEST_SCHEMA_AMBIGUOUS"
REASON_ENDPOINT_SCHEME: Final[str] = "API_REALITY_ENDPOINT_SCHEME_REFUSED"
REASON_ENDPOINT_ENVIRONMENT: Final[str] = "API_REALITY_ENDPOINT_ENVIRONMENT_MIXED"
REASON_FIX_UNPROTECTED: Final[str] = "API_REALITY_FIX_UNPROTECTED"
REASON_DIGEST_MALFORMED: Final[str] = "API_REALITY_DIGEST_MALFORMED"
REASON_SOURCE_CHANGED: Final[str] = "API_REALITY_SOURCE_CHANGED"
REASON_SOURCE_UNREACHABLE: Final[str] = "API_REALITY_SOURCE_UNREACHABLE"
REASON_STRUCTURED_UNPARSEABLE: Final[str] = "API_REALITY_STRUCTURED_UNPARSEABLE"
REASON_UNPARSEABLE_RECOVERED: Final[str] = "API_REALITY_UNPARSEABLE_RECOVERED"
REASON_MANIFEST_NONDETERMINISTIC: Final[str] = "API_REALITY_MANIFEST_NONDETERMINISTIC"
REASON_MANIFEST_LEAKAGE: Final[str] = "API_REALITY_MANIFEST_LEAKAGE"

REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_UNREADABLE,
        REASON_SCHEMA,
        REASON_SOURCE_UNDECLARED,
        REASON_SOURCE_OFF_ALLOWLIST,
        REASON_DUPLICATE_IDENTITY,
        REASON_OBSERVED_CLAIMED,
        REASON_CONDITION_MISSING,
        REASON_SCHEMA_AMBIGUOUS,
        REASON_ENDPOINT_SCHEME,
        REASON_ENDPOINT_ENVIRONMENT,
        REASON_FIX_UNPROTECTED,
        REASON_DIGEST_MALFORMED,
        REASON_SOURCE_CHANGED,
        REASON_SOURCE_UNREACHABLE,
        REASON_STRUCTURED_UNPARSEABLE,
        REASON_UNPARSEABLE_RECOVERED,
        REASON_MANIFEST_NONDETERMINISTIC,
        REASON_MANIFEST_LEAKAGE,
    }
)
"""Every reason this gate can report, closed so a typo cannot invent one."""


class RegistryError(Exception):
    """The registry could not be read at all.

    Distinct from a finding: a finding is something the gate concluded, and this is
    the gate being unable to conclude anything.
    """


class SchemaError(RegistryError):
    """The registry is readable and announces a shape this gate does not read.

    Its own class so that :data:`REASON_SCHEMA` has a producer. A document nobody
    can parse and a document parsed fine but written to another version are
    different problems with different repairs -- one is a syntax defect and the
    other is a version skew between this gate and the declaration -- and reporting
    both as unreadable would send a reader looking for the wrong thing.
    """


@dataclass(frozen=True, slots=True, order=True)
class Finding:
    """One thing wrong with the registry.

    Args:
        reason: One of :data:`REASONS`.
        subject: What it is about.
        detail: What is wrong, in one phrase.
    """

    reason: str
    subject: str
    detail: str

    def as_record(self) -> dict[str, str]:
        """This finding as plain values.

        Returns:
            A mapping of three strings.
        """
        return {"reason": self.reason, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class Source:
    """One declared source, as this reader sees it."""

    identifier: str
    location: str
    regime: str
    digest: str
    known_unparseable: bool = False


@dataclass(frozen=True, slots=True)
class Declaration:
    """The registry, parsed independently of the package's own reader."""

    sources: tuple[Source, ...]
    products: tuple[dict[str, object], ...]
    surfaces: tuple[dict[str, object], ...]
    environments: tuple[dict[str, object], ...]
    endpoints: tuple[dict[str, object], ...]
    schemas: tuple[dict[str, object], ...]

    @property
    def capability_rows(self) -> tuple[tuple[str, dict[str, object]], ...]:
        """Every row carrying a status, evidence and source, with a label.

        Returns:
            Pairs of subject and row.
        """
        found: list[tuple[str, dict[str, object]]] = []
        found += [(f"product/{row.get('family')}", row) for row in self.products]
        found += [
            (f"surface/{row.get('family')}/{row.get('protocol')}", row) for row in self.surfaces
        ]
        found += [
            (f"environment/{row.get('family')}/{row.get('environment')}", row)
            for row in self.environments
        ]
        found += [(f"endpoint/{row.get('url')}", row) for row in self.endpoints]
        return tuple(found)


def _rows(document: dict[str, object], key: str) -> tuple[dict[str, object], ...]:
    """One array of tables, narrowed.

    Args:
        document: The parsed registry.
        key: The array name.

    Returns:
        Its entries.

    Raises:
        RegistryError: If present and not an array of tables.
    """
    value = document.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        msg = f"{key!r} is not an array of tables"
        raise RegistryError(msg)
    return tuple(dict(item) for item in value)


def parse_declaration(text: str) -> Declaration:
    """The registry, from its declared text.

    Args:
        text: The document.

    Returns:
        The declaration.

    Raises:
        RegistryError: If it does not parse or announces an unsupported schema.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as fault:
        msg = f"the registry is not valid TOML: {fault}"
        raise RegistryError(msg) from fault
    announced = document.get("schema")
    if announced != SUPPORTED_SCHEMA:
        msg = f"the registry announces schema {announced!r} and this gate reads {SUPPORTED_SCHEMA}"
        raise SchemaError(msg)
    return Declaration(
        sources=tuple(
            Source(
                identifier=str(row.get("id", "")),
                location=str(row.get("location", "")),
                regime=str(row.get("regime", "")),
                digest=str(row.get("digest", "")),
                known_unparseable=row.get("known_unparseable") is True,
            )
            for row in _rows(document, "source")
        ),
        products=_rows(document, "product"),
        surfaces=_rows(document, "surface"),
        environments=_rows(document, "environment"),
        endpoints=_rows(document, "endpoint"),
        schemas=_rows(document, "schema_version"),
    )


def host_permitted(location: str) -> bool:
    """Whether a source location names a host this gate will reach.

    Args:
        location: The URL.

    Returns:
        ``True`` when the scheme is https, the parsed hostname is on the
        allowlist, and a GitHub path names the venue's own organisation.

    The hostname is taken from :func:`urllib.parse.urlparse` rather than matched
    inside the string, so ``https://evil.test/raw.githubusercontent.com`` and
    ``https://raw.githubusercontent.com.evil.test/`` are both refused.
    """
    parsed = urlparse(location)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    if parsed.hostname not in PERMITTED_HOSTS:
        return False
    if parsed.hostname in GITHUB_HOSTS:
        return parsed.path.startswith(REQUIRED_GITHUB_PREFIX)
    return True


def digest_malformed(value: str) -> bool:
    """Whether a recorded digest is not a lowercase ``sha256:`` hex string.

    Args:
        value: The recorded digest.

    Returns:
        ``True`` when the prefix, length or alphabet is wrong.
    """
    if not value.startswith(DIGEST_PREFIX):
        return True
    body = value[len(DIGEST_PREFIX) :]
    return len(body) != DIGEST_LENGTH or bool(set(body) - HEX)


def _duplicate_findings(declaration: Declaration) -> list[Finding]:
    """Every identity declared more than once.

    Args:
        declaration: The registry.

    Returns:
        One finding per repeated identity.
    """
    groups: tuple[tuple[str, list[str]], ...] = (
        ("source", [item.identifier for item in declaration.sources]),
        ("product", [str(row.get("family")) for row in declaration.products]),
        (
            "surface",
            [f"{row.get('family')}/{row.get('protocol')}" for row in declaration.surfaces],
        ),
        (
            "environment",
            [f"{row.get('family')}/{row.get('environment')}" for row in declaration.environments],
        ),
        (
            "endpoint",
            [
                f"{row.get('family')}/{row.get('environment')}/{row.get('protocol')}"
                f"/{row.get('url')}/{row.get('port', 0)}"
                for row in declaration.endpoints
            ],
        ),
        (
            "schema",
            [
                f"{row.get('family')}/{row.get('environment')}"
                f"/{row.get('schema_id')}:{row.get('version')}"
                for row in declaration.schemas
            ],
        ),
    )
    found: list[Finding] = []
    for name, identities in groups:
        seen: set[str] = set()
        for identity in identities:
            if identity in seen:
                found.append(
                    Finding(REASON_DUPLICATE_IDENTITY, f"{name}/{identity}", "declared twice")
                )
            seen.add(identity)
    return found


def _source_findings(declaration: Declaration) -> list[Finding]:
    """Everything wrong with the declared sources or the citations of them.

    Args:
        declaration: The registry.

    Returns:
        Findings for undeclared citations, off-allowlist hosts and bad digests.
    """
    declared = {item.identifier for item in declaration.sources}
    found: list[Finding] = []
    for subject, row in declaration.capability_rows:
        cited = str(row.get("source", ""))
        if cited not in declared:
            found.append(
                Finding(REASON_SOURCE_UNDECLARED, subject, f"cites undeclared source {cited!r}")
            )
    for row in declaration.schemas:
        cited = str(row.get("source", ""))
        if cited not in declared:
            label = f"schema/{row.get('family')}/{row.get('schema_id')}:{row.get('version')}"
            found.append(
                Finding(REASON_SOURCE_UNDECLARED, label, f"cites undeclared source {cited!r}")
            )
    for source in declaration.sources:
        if not host_permitted(source.location):
            found.append(
                Finding(
                    REASON_SOURCE_OFF_ALLOWLIST,
                    f"source/{source.identifier}",
                    f"{source.location!r} is not an allowlisted official location",
                )
            )
        if source.digest and digest_malformed(source.digest):
            found.append(
                Finding(
                    REASON_DIGEST_MALFORMED,
                    f"source/{source.identifier}",
                    "the recorded digest is not a lowercase sha256 hex string",
                )
            )
        if source.regime == MANUAL and source.digest:
            found.append(
                Finding(
                    REASON_DIGEST_MALFORMED,
                    f"source/{source.identifier}",
                    "a manual source cannot have been hashed and carries a digest",
                )
            )
    return found


def _claim_findings(declaration: Declaration) -> list[Finding]:
    """Everything wrong with a row's own claim.

    Args:
        declaration: The registry.

    Returns:
        Findings for observed evidence, unrecognised words and missing conditions.
    """
    found: list[Finding] = []
    for subject, row in declaration.capability_rows:
        status = str(row.get("status", ""))
        evidence = str(row.get("evidence", ""))
        condition = str(row.get("condition", ""))
        if evidence == OBSERVED:
            found.append(
                Finding(
                    REASON_OBSERVED_CLAIMED,
                    subject,
                    "claims to have been observed, and GLOBIN has never contacted the venue",
                )
            )
        if status not in STATUSES:
            found.append(
                Finding(REASON_UNREADABLE, subject, f"status {status!r} is not one of six")
            )
        if evidence not in EVIDENCE_KINDS:
            found.append(
                Finding(REASON_UNREADABLE, subject, f"evidence {evidence!r} is not one of three")
            )
        if status == RESTRICTED and not condition:
            found.append(
                Finding(REASON_CONDITION_MISSING, subject, "is restricted and names no condition")
            )
    return found


def _endpoint_findings(declaration: Declaration) -> list[Finding]:
    """Everything wrong with an endpoint's address or its protection.

    Args:
        declaration: The registry.

    Returns:
        Findings for refused schemes, mixed environments and unprotected FIX.
    """
    markers: dict[tuple[str, str], str] = {}
    for row in declaration.environments:
        key = (str(row.get("family")), str(row.get("environment")))
        markers[key] = str(row.get("host_marker", ""))
    every_marker = {value for value in markers.values() if value}
    found: list[Finding] = []
    for row in declaration.endpoints:
        url = str(row.get("url", ""))
        subject = f"endpoint/{url}"
        scheme = urlparse(url).scheme
        if scheme not in PERMITTED_SCHEMES:
            found.append(Finding(REASON_ENDPOINT_SCHEME, subject, f"scheme {scheme!r} is refused"))
        key = (str(row.get("family")), str(row.get("environment")))
        if key not in markers:
            found.append(
                Finding(
                    REASON_ENDPOINT_ENVIRONMENT,
                    subject,
                    f"is filed under {key[1]!r}, which is not declared for {key[0]!r}",
                )
            )
        else:
            found += _mixing_findings(subject, url, markers[key], every_marker)
        if str(row.get("transport")) == "tcp_tls":
            found += _fix_findings(subject, row)
    return found


def _mixing_findings(subject: str, url: str, marker: str, every_marker: set[str]) -> list[Finding]:
    """Whether a host contradicts the environment it is filed under.

    Args:
        subject: What the finding is about.
        url: The address.
        marker: The marker this environment declares, empty for the live one.
        every_marker: Every marker any environment declares.

    Returns:
        At most one finding.
    """
    lowered = url.lower()
    if marker:
        if marker in lowered:
            return []
        return [Finding(REASON_ENDPOINT_ENVIRONMENT, subject, f"host omits marker {marker!r}")]
    stray = sorted(item for item in every_marker if item in lowered)
    if not stray:
        return []
    return [
        Finding(
            REASON_ENDPOINT_ENVIRONMENT,
            subject,
            f"is filed under a live environment and its host is spelled like {', '.join(stray)}",
        )
    ]


def _fix_findings(subject: str, row: dict[str, object]) -> list[Finding]:
    """Whether a FIX endpoint is missing a port, TLS or SNI.

    Args:
        subject: What the finding is about.
        row: The endpoint.

    Returns:
        At most one finding.
    """
    port = row.get("port", 0)
    if not isinstance(port, int) or isinstance(port, bool) or port <= 0:
        return [Finding(REASON_FIX_UNPROTECTED, subject, "records no port")]
    if not (row.get("tls_required") is True and row.get("sni_required") is True):
        return [Finding(REASON_FIX_UNPROTECTED, subject, "does not require both TLS and SNI")]
    return []


def _schema_findings(declaration: Declaration) -> list[Finding]:
    """Whether two schema versions claim to be current for one family.

    Args:
        declaration: The registry.

    Returns:
        One finding per ambiguous family and environment.
    """
    seen: dict[tuple[str, str], str] = {}
    found: list[Finding] = []
    for row in declaration.schemas:
        if str(row.get("state")) != LATEST:
            continue
        key = (str(row.get("family")), str(row.get("environment")))
        label = f"{row.get('schema_id')}:{row.get('version')}"
        if key in seen:
            found.append(
                Finding(
                    REASON_SCHEMA_AMBIGUOUS,
                    f"schema/{key[0]}/{key[1]}",
                    f"both {seen[key]} and {label} claim to be current",
                )
            )
        seen[key] = label
    return found


def findings_for(declaration: Declaration) -> tuple[Finding, ...]:
    """Everything wrong with the registry, recomputed from the document.

    Args:
        declaration: The registry.

    Returns:
        The findings, sorted so two runs report identically.
    """
    found = (
        _duplicate_findings(declaration)
        + _source_findings(declaration)
        + _claim_findings(declaration)
        + _endpoint_findings(declaration)
        + _schema_findings(declaration)
    )
    return tuple(sorted(found))
