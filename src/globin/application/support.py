"""Building one support bundle: collect, redact, bound, validate, publish.

The order of those five verbs is the design. Nothing is written until everything
has been read and checked, and nothing is published until the finished archive has
been reopened and compared against its own manifest. A bundle that fails any step
leaves no file behind under the name an operator would look for.

**Allowlist, and the allowlist is a table rather than a walk.** :func:`candidates`
names every file that may be collected, one row per artefact kind. There is no
directory traversal anywhere in this module, which is what makes the guarantee
checkable: a reviewer can read the table and know the whole set, rather than
reasoning about what a filter might have let through.

**Redaction reuses Phase 023's redactor and nothing else.** A log line is NDJSON,
so it is parsed, passed through
:func:`~globin.domain.observability.redact`, and re-rendered. Where a line cannot
be parsed it is dropped rather than included unredacted — the one place this module
prefers losing a diagnostic to risking a credential.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from globin.application.observability import Logger
from globin.domain.observability import redact
from globin.domain.support import (
    EXCLUDED_BUDGET_SPENT,
    EXCLUDED_NAME_UNSAFE,
    EXCLUDED_NOT_REGULAR,
    EXCLUDED_TOO_LARGE,
    EXCLUDED_UNREADABLE,
    ArtifactKind,
    BundleEntry,
    BundleExclusion,
    BundleLimits,
    BundleManifest,
    member_problems,
)
from globin.errors import ValidationError

EVENT_BUNDLE_BUILT: Final[str] = "support.bundle.built"
"""A bundle was published."""

EVENT_BUNDLE_REFUSED: Final[str] = "support.bundle.refused"
"""A bundle failed validation and was not published."""

TRUNCATION_NOTICE: Final[bytes] = b"\n[globin: truncated at the configured limit]\n"
"""What is appended to a member the limits cut short.

In the content rather than only in the manifest, because the person reading the
file inside the archive is not necessarily the person who read the manifest, and a
log that simply stops looks like a process that simply stopped.
"""

UNPARSED_NOTICE: Final[bytes] = b"[globin: a log line could not be parsed and was omitted]\n"
"""What replaces a log line the redactor could not safely process."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """One file the allowlist permits, before anything has been read.

    Args:
        member: What it will be called inside the archive.
        kind: Which artefact kind it is.
        read: How to obtain its bytes, injected so the collector needs no
            filesystem of its own.
        redactable: Whether it is NDJSON that should pass through the redactor
            line by line.
    """

    member: str
    kind: ArtifactKind
    read: Callable[[], bytes]
    redactable: bool = False


@dataclass(frozen=True, slots=True)
class Collected:
    """What a collection pass produced.

    Args:
        members: Member name and final content, in no particular order.
        exclusions: Every candidate that was left out, with its reason.
    """

    members: tuple[tuple[str, bytes], ...]
    exclusions: tuple[BundleExclusion, ...]


@dataclass(frozen=True, slots=True)
class BundleBuilder:
    """Turns a set of candidates into a published, validated bundle.

    Args:
        writer: Where the archive is written and read back.
        limits: What the bundle may not exceed.
        logger: Where the outcome is reported.
        render: The canonical JSON renderer, injected because it lives in the
            adapters layer and this one may not import it.
        digest: The content digest, injected for the same reason.

    **Two functions are injected that could have been imported, and the layer
    contract is why.** ``docs/architecture/dependency-rules.toml`` permits
    ``application`` to import ``domain`` and ``ports`` and nothing outward, so
    reaching for ``globin.adapters.support.digest_of`` here would invert the one
    direction the architecture test exists to hold. The composition root supplies
    both, which is also what lets a test build a bundle without hashing anything.
    """

    writer: object
    limits: BundleLimits
    logger: Logger
    render: Callable[[Mapping[str, object]], str]
    digest: Callable[[bytes], str]

    def collect(self, candidates: Sequence[Candidate]) -> Collected:
        """Read every candidate the limits still permit.

        Args:
            candidates: The allowlisted files, in the order they should be tried.

        Returns:
            What was gathered and what was left out.

        **The budget is spent in the order given, and the order is deliberate.**
        The snapshot and the state documents come first because they are small and
        always useful; logs come last because they are the only thing that can be
        large. A collector that read logs first could spend the whole budget on
        them and exclude the snapshot, producing a bundle that says a great deal
        about what happened and nothing about the machine it happened on.
        """
        members: list[tuple[str, bytes]] = []
        exclusions: list[BundleExclusion] = []
        spent = 0
        log_spent = 0
        for candidate in candidates:
            if len(members) >= self.limits.member_count:
                exclusions.append(BundleExclusion(candidate.kind, EXCLUDED_BUDGET_SPENT, "count"))
                continue
            problems = member_problems(candidate.member)
            if problems:
                exclusions.append(BundleExclusion(candidate.kind, EXCLUDED_NAME_UNSAFE))
                continue
            try:
                payload = candidate.read()
            except IsADirectoryError:
                exclusions.append(BundleExclusion(candidate.kind, EXCLUDED_NOT_REGULAR))
                continue
            except (OSError, ValueError):
                exclusions.append(BundleExclusion(candidate.kind, EXCLUDED_UNREADABLE))
                continue

            if candidate.redactable:
                payload = redact_ndjson(payload)
            is_log = candidate.kind in (ArtifactKind.LOG, ArtifactKind.ROTATED_LOG)
            allowance = self._allowance(spent, log_spent, is_log=is_log)
            if allowance <= 0:
                exclusions.append(BundleExclusion(candidate.kind, EXCLUDED_BUDGET_SPENT, "bytes"))
                continue
            if len(payload) > allowance:
                if allowance <= len(TRUNCATION_NOTICE):
                    exclusions.append(BundleExclusion(candidate.kind, EXCLUDED_TOO_LARGE))
                    continue
                payload = payload[: allowance - len(TRUNCATION_NOTICE)] + TRUNCATION_NOTICE
            spent += len(payload)
            if is_log:
                log_spent += len(payload)
            members.append((candidate.member, payload))
        return Collected(tuple(members), tuple(exclusions))

    def _allowance(self, spent: int, log_spent: int, *, is_log: bool) -> int:
        """How many bytes the next member may use.

        Args:
            spent: What has been read so far.
            log_spent: What the log members have used so far.
            is_log: Whether the next member is a log.

        Returns:
            The smallest of the three applicable bounds.

        Three budgets apply at once — per member, per total, and a separate one for
        logs — and the smallest wins. The log budget exists so that a logs area
        which has somehow grown past its own rotation policy cannot crowd out the
        state documents, which are the part that explains what the process was.
        """
        remaining = min(self.limits.member_bytes, self.limits.total_input_bytes - spent)
        if is_log:
            remaining = min(remaining, self.limits.log_bytes - log_spent)
        return remaining

    def build(
        self, candidates: Sequence[Candidate], *, manifest_member: str, report_member: str
    ) -> tuple[BundleManifest, str, int]:
        """Collect, write, validate and publish one bundle.

        Args:
            candidates: The allowlisted files.
            manifest_member: What the manifest is called inside the archive.
            report_member: What the generation report is called.

        Returns:
            The manifest, the finished archive's digest and its size.

        Raises:
            ValidationError: If the archive does not match its manifest, or is
                over the size limit. The partial file is discarded first, so a
                refusal leaves nothing under the final name.

        **The manifest describes every member except itself, and that exclusion is
        forced rather than chosen.** A manifest carrying its own digest would
        describe a file that changes the moment the description is written, which
        has no fixed point. So the manifest is built over the collected members and
        the report, written into the archive last, and
        :meth:`ArchiveWriter.validate` is told its name so it can check the archive
        holds exactly the described set plus that one file. An earlier draft of this
        built the manifest before the report existed and shipped a bundle whose
        index listed one of three members; the archive was internally consistent and
        the index was wrong, which is the failure a self-validating format exists to
        make impossible.
        """
        collected = self.collect(candidates)
        report = _report_text(collected)
        described = (*collected.members, (report_member, report))
        manifest = BundleManifest(
            entries=tuple(
                sorted(_described(described, self.digest), key=lambda entry: entry.member)
            ),
            exclusions=collected.exclusions,
            limits=self.limits,
        )
        manifest_bytes = self.render(_manifest_document(manifest)).encode("utf-8")
        written = self.writer.write((*described, (manifest_member, manifest_bytes)))  # type: ignore[attr-defined]
        problems = self.writer.validate(manifest, manifest_member=manifest_member)  # type: ignore[attr-defined]
        if problems:
            self.writer.discard()  # type: ignore[attr-defined]
            self.logger.error(EVENT_BUNDLE_REFUSED, problems=len(problems))
            msg = f"the bundle did not match its manifest: {problems[0]}"
            raise ValidationError(msg)
        digest, size = self.writer.publish(self.limits.archive_bytes)  # type: ignore[attr-defined]
        self.logger.info(
            EVENT_BUNDLE_BUILT,
            members=len(written),
            excluded=len(manifest.exclusions),
            bytes=size,
        )
        return manifest, digest, size


def _described(
    members: tuple[tuple[str, bytes], ...], digest: Callable[[bytes], str]
) -> tuple[BundleEntry, ...]:
    """Entries for every member the manifest will describe.

    Args:
        members: Member name and content.
        digest: How to hash a member's bytes.

    Returns:
        One entry per member.

    The digest is taken over exactly the bytes that will be stored, before they are
    handed to the archive, so a manifest entry and its member cannot disagree about
    content even if the compression layer changed underneath.
    """
    return tuple(
        BundleEntry(
            member=member,
            kind=_kind_for(member),
            size_bytes=len(payload),
            digest=digest(payload),
        )
        for member, payload in members
    )


def _kind_for(member: str) -> ArtifactKind:
    """Which artefact kind one member name denotes.

    Args:
        member: The member name.

    Returns:
        The kind.

    Derived from the name rather than carried beside it, so the manifest and the
    archive cannot disagree about what a file is.
    """
    if member.endswith("report.txt"):
        return ArtifactKind.REPORT
    if member == "snapshot.json":
        return ArtifactKind.SNAPSHOT
    if member.endswith("faults.txt"):
        return ArtifactKind.FAULT
    if member.startswith("state/"):
        return ArtifactKind.LIFECYCLE
    if member.startswith("logs/") and member.endswith(".log"):
        return ArtifactKind.LOG
    return ArtifactKind.ROTATED_LOG


def _manifest_document(manifest: BundleManifest) -> dict[str, object]:
    """The manifest as a canonical document.

    Args:
        manifest: The manifest.

    Returns:
        The document.
    """
    return {
        "schema": "globin.support.manifest",
        "schema_version": manifest.schema_version,
        "entries": [
            {
                "member": entry.member,
                "kind": str(entry.kind),
                "size_bytes": entry.size_bytes,
                "digest": entry.digest,
                "redacted": entry.redacted,
                "truncated": entry.truncated,
                "source": entry.source,
            }
            for entry in manifest.entries
        ],
        "exclusions": [
            {
                "kind": str(exclusion.kind) if exclusion.kind else "",
                "reason": exclusion.reason,
                "detail": exclusion.detail,
            }
            for exclusion in manifest.exclusions
        ],
        "limits": {
            "total_input_bytes": manifest.limits.total_input_bytes,
            "archive_bytes": manifest.limits.archive_bytes,
            "member_bytes": manifest.limits.member_bytes,
            "log_bytes": manifest.limits.log_bytes,
            "member_count": manifest.limits.member_count,
        }
        if manifest.limits
        else {},
    }


def _report_text(collected: Collected) -> bytes:
    """The human-readable generation report.

    Args:
        collected: What the collection pass produced.

    Returns:
        The report, as UTF-8 bytes with normalised line endings.

    Lists what was included and what was not, because a bundle missing the log
    somebody wanted is otherwise indistinguishable from a bundle where the log did
    not exist. Reason codes rather than paths: an exclusion exists because the file
    could not be shown to be safe, and naming it would publish the one string the
    exclusion was protecting.
    """
    lines = ["GLOBIN support bundle", "", "Included:"]
    lines.extend(f"  {member}" for member, _ in sorted(collected.members))
    if collected.exclusions:
        lines.extend(("", "Excluded:"))
        lines.extend(
            f"  {exclusion.reason}" + (f" ({exclusion.detail})" if exclusion.detail else "")
            for exclusion in collected.exclusions
        )
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def redact_ndjson(payload: bytes) -> bytes:
    """Pass every line of an NDJSON document through the central redactor.

    Args:
        payload: The raw file.

    Returns:
        The same document with sensitive fields replaced.

    **Phase 023's redactor and no other.** Building a second one here would mean
    two lists of sensitive field names, and two lists drift — the one that is not
    the one somebody edits becomes the one that leaks.

    **A line that cannot be parsed is dropped, not passed through.** This is the
    single place in the module that prefers losing a diagnostic to risking a
    credential: an unparseable line cannot be redacted by field name, so including
    it would mean shipping bytes nothing had inspected.

    **What this does not catch is stated rather than implied.** Redaction matches
    field *names*. A credential inside a free-text message, or inside an exception
    string a dependency produced, survives — exactly as
    ``docs/engineering/RUNTIME_DIAGNOSTICS.md`` already says of the live log.
    """
    out: list[bytes] = []
    for raw in payload.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            document = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            out.append(UNPARSED_NOTICE.rstrip(b"\n"))
            continue
        if not isinstance(document, dict):
            out.append(UNPARSED_NOTICE.rstrip(b"\n"))
            continue
        cleaned = redact(document)
        out.append(
            json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
                "utf-8"
            )
        )
    return b"\n".join(out) + (b"\n" if out else b"")
