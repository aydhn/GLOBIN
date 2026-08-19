"""Recompute the registry's claims, and optionally ask the venue whether they hold.

Two verbs, because one of them reaches the network and one does not. ``check`` is
the default and reads only the committed document; ``refresh`` adds the half that
fetches, and it is not in ``full`` for the reason every networked gate is not:
``full`` runs before every commit and must work on an aeroplane.

**The fetcher is injected, and that is not a convenience.** ADR-0024's offline
guarantee is enforced by refusing sockets in the *test* process, and a function
that opened one inside that process would sail past the guard in the opposite
direction -- the guard would catch the test rather than the gate. A substitutable
fetcher is what lets the network path be exercised without a network, and the
default is the real thing, so no caller outside a test passes one.

**Only official machine-readable resources are fetched.** ``SOURCE_POLICY.md``
requires it and names documentation ingestion specifically; the allowlist in
:mod:`tools.quality.venue.plan` is checked against the parsed hostname, and a
redirect that leaves it is refused rather than followed.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tools.quality.evidence.redaction import describe as describe_findings
from tools.quality.evidence.redaction import scan as scan_for_secrets
from tools.quality.venue.manifest import (
    DIRECTORY,
    MANIFEST_NAME,
)
from tools.quality.venue.manifest import (
    build as build_manifest,
)
from tools.quality.venue.manifest import (
    render as render_manifest,
)
from tools.quality.venue.plan import (
    LATEST,
    MANUAL,
    REASON_MANIFEST_LEAKAGE,
    REASON_MANIFEST_NONDETERMINISTIC,
    REASON_SCHEMA,
    REASON_SOURCE_CHANGED,
    REASON_SOURCE_UNREACHABLE,
    REASON_STRUCTURED_UNPARSEABLE,
    REASON_UNPARSEABLE_RECOVERED,
    REASON_UNREADABLE,
    REASONS,
    STATUSES,
    STRUCTURED,
    SUPPORTED_SCHEMA,
    Declaration,
    Finding,
    RegistryError,
    SchemaError,
    Source,
    findings_for,
    host_permitted,
    parse_declaration,
)

REGISTRY_PATH: Final[str] = "docs/engineering/binance-api-reality.toml"
"""Where the declaration lives, relative to the repository root."""

ARTEFACT_ROOT: Final[str] = ".globin"
"""Where evidence is published."""

EXIT_OK: Final[int] = 0
EXIT_GATE_FAILED: Final[int] = 1
EXIT_UNMEASURED: Final[int] = 3

DEFAULT_TIMEOUT: Final[float] = 30.0
"""How long one fetch may take.

Bounded rather than generous: these are small static documents on a content
delivery network, and a fetch that hangs should be reported rather than waited on.
"""

MAX_RESPONSE_BYTES: Final[int] = 8 * 1024 * 1024
"""The most one source may return.

The largest document the registry cites is under 300 kilobytes. The bound exists so
that a redirect to something enormous cannot exhaust this process.
"""

USER_AGENT: Final[str] = "GLOBIN api-reality gate"
"""What this gate calls itself when it fetches."""

Fetcher = Callable[..., bytes]
"""What performs one fetch. Substituted in tests, never in production."""


def fetch(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """One official document, fetched over https and nothing else.

    Args:
        url: Where to read it from.
        timeout: How long to wait.

    Returns:
        The body, truncated at :data:`MAX_RESPONSE_BYTES`.

    Raises:
        RegistryError: If the URL is not on the allowlist, or the response is not
            reachable.

    The allowlist is checked here as well as at validation time, because these are
    two different moments: one asks whether the registry may *record* a location,
    and this asks whether this process may *open* one. A redirect is refused rather
    than followed -- :class:`urllib.request.HTTPRedirectHandler` is replaced, so a
    301 to somewhere off the allowlist becomes an error instead of a fetch.
    """
    if not host_permitted(url):
        msg = f"{url!r} is not an allowlisted official location"
        raise RegistryError(msg)
    request = urllib.request.Request(  # noqa: S310 — the scheme and host are checked above
        url, headers={"User-Agent": USER_AGENT}
    )
    opener = urllib.request.build_opener(_NoRedirects)
    try:
        with opener.open(request, timeout=timeout) as response:
            return bytes(response.read(MAX_RESPONSE_BYTES))
    except (urllib.error.URLError, OSError, ValueError) as fault:
        msg = f"{url} could not be read: {fault}"
        raise RegistryError(msg) from fault


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect handler that refuses rather than follows.

    Every location the registry cites is a stable raw document. A redirect means
    the venue moved something, which is a fact worth reporting rather than silently
    absorbing -- and following one is how an allowlist stops meaning anything.
    """

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        """Refuse a redirect.

        Args:
            *_args: What the standard library would pass. Unread.
            **_kwargs: The same.

        Returns:
            ``None``, which the standard library treats as a refusal and turns
            into an error rather than a second request.
        """
        return


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one run concluded.

    Args:
        code: The process exit code.
        findings: What was wrong.
        reached_network: Whether anything was fetched.
        checked: How many sources were re-checked.
    """

    code: int
    findings: tuple[Finding, ...]
    reached_network: bool
    checked: int


def _refresh_findings(
    declaration: Declaration, *, fetcher: Fetcher, timeout: float
) -> tuple[list[Finding], int]:
    """Ask each refreshable source whether the record still holds.

    Args:
        declaration: The registry.
        fetcher: What performs one fetch.
        timeout: How long each may take.

    Returns:
        The findings, and how many sources were reached.

    A manual source is skipped rather than failed: it has no fetchable text form,
    which the registry records rather than hides. A structured source is additionally
    parsed, because three of the four the venue publishes are not currently valid
    JSON and a gate that only hashed them would report them as fine.
    """
    found: list[Finding] = []
    checked = 0
    for source in declaration.sources:
        if source.regime == MANUAL:
            continue
        subject = f"source/{source.identifier}"
        try:
            body = fetcher(source.location, timeout=timeout)
        except RegistryError as fault:
            found.append(Finding(REASON_SOURCE_UNREACHABLE, subject, str(fault)))
            continue
        checked += 1
        if source.regime == STRUCTURED:
            found += _parse_findings(source, subject, body)
        if not source.digest:
            continue
        seen = "sha256:" + hashlib.sha256(body).hexdigest()
        if seen != source.digest:
            found.append(
                Finding(
                    REASON_SOURCE_CHANGED,
                    subject,
                    f"changed and must be re-read; recorded {source.digest}, fetched {seen}",
                )
            )
    return found, checked


def _parse_findings(source: Source, subject: str, body: bytes) -> list[Finding]:
    """Whether a structured source parses, and whether that matches the record.

    Args:
        source: The declared source.
        subject: What a finding would be about.
        body: What was fetched.

    Returns:
        At most one finding.

    Symmetric, and the second half is the useful one. Three of the four lifecycle
    files the venue publishes are not currently valid JSON, and a gate that failed
    on that would be red for a defect nobody here can fix -- a signal that is always
    red is a signal nobody reads. So an unparseable source whose registry row
    **declares** it unparseable is recorded rather than failed, exactly as the wheel
    survey records an owned gap.

    The other direction closes the loop: a source declared unparseable that now
    parses means the venue fixed it and the registry is stale, which fails so that
    somebody removes the declaration. Without that, the exemption would outlive its
    reason and quietly disable the check.
    """
    try:
        json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as fault:
        if source.known_unparseable:
            return []
        return [
            Finding(
                REASON_STRUCTURED_UNPARSEABLE,
                subject,
                f"is declared structured and does not parse: {fault}",
            )
        ]
    if source.known_unparseable:
        return [
            Finding(
                REASON_UNPARSEABLE_RECOVERED,
                subject,
                "is declared unparseable and now parses; the registry row is stale",
            )
        ]
    return []


def _inventory(declaration: Declaration, *, digest: str, schema: object) -> dict[str, object]:
    """What the registry contains, as counts and identities rather than as a copy.

    Args:
        declaration: The registry.
        digest: The declaration file's own content digest.
        schema: The shape number the document announces.

    Returns:
        A mapping every value of which is a string, integer or sorted list.

    A manifest embedding the registry would change whenever the registry did and
    establish nothing about either. What is recorded instead is what somebody
    comparing two runs would actually ask: which families were seen, which sources
    were rested on, and what each one hashed to.
    """
    return {
        "registry_schema": schema,
        "registry_digest": digest,
        "products": sorted({str(row.get("family")) for row in declaration.products}),
        "environments": sorted({str(row.get("environment")) for row in declaration.environments}),
        "protocols": sorted({str(row.get("protocol")) for row in declaration.surfaces}),
        "sources": [
            {
                "id": item.identifier,
                "regime": item.regime,
                "digest": item.digest,
                "known_unparseable": item.known_unparseable,
            }
            for item in sorted(declaration.sources, key=lambda item: item.identifier)
        ],
    }


def _status_counts(declaration: Declaration) -> dict[str, int]:
    """How many rows carry each status word.

    Args:
        declaration: The registry.

    Returns:
        Every word in :data:`STATUSES` mapped to its count, zeroes included -- an
        absent key would read as an absent question rather than an empty answer.

    Recomputed here rather than read from the package, which this gate does not
    import. If the two ever disagree, one of them is miscounting a document they
    both claim to understand.
    """
    counts = dict.fromkeys(sorted(STATUSES), 0)
    for _subject, row in declaration.capability_rows:
        word = str(row.get("status", ""))
        if word in counts:
            counts[word] += 1
    return counts


def _current_schemas(declaration: Declaration) -> dict[str, str]:
    """Which schema version is current, per family and environment.

    Args:
        declaration: The registry.

    Returns:
        A mapping of ``family/environment`` to the ``id:version`` label.
    """
    found: dict[str, str] = {}
    for row in declaration.schemas:
        if str(row.get("state")) != LATEST:
            continue
        key = f"{row.get('family')}/{row.get('environment')}"
        found[key] = f"{row.get('schema_id')}:{row.get('version')}"
    return found


def run_api_reality(
    *,
    root: Path | None = None,
    refresh: bool = False,
    fetcher: Fetcher | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Outcome:
    """Recompute the registry, publish the manifest, and report one verdict.

    Args:
        root: The repository root. Defaults to the current directory.
        refresh: Whether to ask the venue as well as the document.
        fetcher: What performs one fetch. Defaults to the real one.
        timeout: How long each fetch may take.

    Returns:
        The outcome, whose code is ``0`` when nothing is wrong, ``1`` when
        something is, and ``3`` when there is no registry to judge.
    """
    base = (root or Path.cwd()).resolve()
    path = base / REGISTRY_PATH
    directory = base / ARTEFACT_ROOT / DIRECTORY
    try:
        raw = path.read_bytes()
        declaration = parse_declaration(raw.decode("utf-8"))
    except SchemaError as fault:
        return _publish(
            directory,
            findings=(Finding(REASON_SCHEMA, REGISTRY_PATH, str(fault)),),
            code=EXIT_UNMEASURED,
            run={"registry": REGISTRY_PATH, "reached_network": False, "sources_checked": 0},
            findings_extra={},
        )
    except (OSError, UnicodeDecodeError, RegistryError) as fault:
        return _publish(
            directory,
            findings=(Finding(REASON_UNREADABLE, REGISTRY_PATH, str(fault)),),
            code=EXIT_UNMEASURED,
            run={"registry": REGISTRY_PATH, "reached_network": False, "sources_checked": 0},
            findings_extra={},
        )
    found = list(findings_for(declaration))
    checked = 0
    if refresh:
        extra, checked = _refresh_findings(declaration, fetcher=fetcher or fetch, timeout=timeout)
        found += extra
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    run = {
        "registry": REGISTRY_PATH,
        "reached_network": refresh,
        "sources_checked": checked,
        "counts": {
            "sources": len(declaration.sources),
            "products": len(declaration.products),
            "surfaces": len(declaration.surfaces),
            "environments": len(declaration.environments),
            "endpoints": len(declaration.endpoints),
            "schema_versions": len(declaration.schemas),
        },
        **_inventory(declaration, digest=digest, schema=SUPPORTED_SCHEMA),
    }
    return _publish(
        directory,
        findings=tuple(sorted(found)),
        code=EXIT_GATE_FAILED if found else EXIT_OK,
        run=run,
        findings_extra={
            "status_counts": _status_counts(declaration),
            "current_schemas": _current_schemas(declaration),
        },
        reached_network=refresh,
        checked=checked,
    )


def _publish(
    directory: Path,
    *,
    findings: tuple[Finding, ...],
    code: int,
    run: dict[str, object],
    findings_extra: dict[str, object],
    reached_network: bool = False,
    checked: int = 0,
) -> Outcome:
    """Write the manifest and return the outcome.

    Args:
        directory: Where the manifest goes.
        findings: What was concluded.
        code: The exit code.
        run: What was read, and whether the network was reached.
        findings_extra: The recomputed inventory published beside the findings.
        reached_network: Whether anything was fetched.
        checked: How many sources were re-checked.

    Returns:
        The outcome.

    The manifest is rendered twice and compared before anything is written, and
    then scanned for secret-shaped content. Both produce a **finding** rather than
    an exception, because a gate that raised would leave no artefact and be
    indistinguishable from one that never ran.
    """

    def assemble(items: tuple[Finding, ...], verdict_code: int) -> dict[str, object]:
        return build_manifest(
            run=run,
            findings={
                "count": len(items),
                "items": [item.as_record() for item in items],
                **findings_extra,
            },
            verdict={"code": verdict_code, "reasons": sorted({item.reason for item in items})},
        )

    rendered = render_manifest(assemble(findings, code))
    if rendered != render_manifest(assemble(findings, code)):
        findings = (
            *findings,
            Finding(
                REASON_MANIFEST_NONDETERMINISTIC,
                MANIFEST_NAME,
                "two renderings of the same run disagreed",
            ),
        )
        code = EXIT_GATE_FAILED
        rendered = render_manifest(assemble(findings, code))
    leaks = scan_for_secrets(MANIFEST_NAME, rendered)
    if leaks:
        findings = (
            *findings,
            Finding(REASON_MANIFEST_LEAKAGE, MANIFEST_NAME, describe_findings(leaks)),
        )
        code = EXIT_GATE_FAILED
        rendered = render_manifest(assemble(findings, code))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / MANIFEST_NAME).write_text(rendered, encoding="utf-8", newline="\n")
    return Outcome(code=code, findings=findings, reached_network=reached_network, checked=checked)


def describe(outcome: Outcome) -> str:
    """One outcome as text.

    Args:
        outcome: What the run concluded.

    Returns:
        A line per finding, under a summary line.
    """
    lines = [
        f"api-reality  {len(outcome.findings)} findings, "
        f"{outcome.checked} sources checked, "
        f"network {'reached' if outcome.reached_network else 'not reached'}"
    ]
    lines += [f"  {item.reason}  {item.subject}  {item.detail}" for item in outcome.findings]
    return "\n".join(lines) + "\n"


def known_reasons() -> frozenset[str]:
    """Every reason this gate can report.

    Returns:
        The closed set, so a contract test can compare it against the manifest.
    """
    return REASONS
