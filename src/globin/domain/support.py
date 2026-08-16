"""What may go into a support bundle, and what a member name may look like.

A support bundle is the archive an operator sends somewhere when GLOBIN has
misbehaved. That one sentence contains the whole threat model: the file leaves the
machine, it leaves it because something is already wrong, and the person sending it
is not going to audit the contents first.

**Allowlist, never denylist.** A collector that zipped the runtime tree and
excluded known-bad names would be one unanticipated file away from shipping it.
:class:`ArtifactKind` enumerates what may be included, and anything without a kind
is excluded with a recorded reason. The cost is that a genuinely useful new file
does not appear until somebody adds a kind for it, which is the correct direction
to fail in.

**Every judgement here is pure string and integer work**, so path safety is
testable without a filesystem and without Windows. That matters because the
interesting cases — a member escaping the root, two names colliding under a
case-insensitive comparison, a reserved device name — are exactly the ones that are
awkward to reproduce by making real files.

Nothing here reads, writes, compresses or hashes anything. The archive is
``globin.adapters.support``'s.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.errors import ValidationError

BUNDLE_SCHEMA_VERSION: Final[int] = 1
"""The manifest's shape version."""

MEMBER_SEPARATOR: Final[str] = "/"
"""The one separator an archive member name may contain.

POSIX-style regardless of the host, because that is what the ZIP format specifies
and because a member written with a backslash on Windows is a member that extracts
into a file with a backslash in its name everywhere else.
"""

MAXIMUM_MEMBER_LENGTH: Final[int] = 120
"""How long one member name may be.

Well under the limits either platform imposes, so an archive built here always
extracts. Extraction failing because a name was too long is a failure at the worst
possible moment: after the operator has sent the file and while somebody is trying
to read it.
"""

RESERVED_STEMS: Final[tuple[str, ...]] = (
    "con",
    "prn",
    "aux",
    "nul",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
)
"""Names Windows reserves for devices, which cannot be created as files.

Checked on the *stem*, because ``con.txt`` is reserved as surely as ``con`` is.
GLOBIN never generates one of these itself; the check exists because a member name
is partly derived from a filename on disk, and a file that arrived some other way
should not produce an archive nobody can extract.
"""


class ArtifactKind(StrEnum):
    """What sort of thing a bundle member is.

    The allowlist. A candidate whose kind is not one of these is excluded, and the
    exclusion is recorded rather than silent.
    """

    SNAPSHOT = "snapshot"
    """The canonical runtime health snapshot."""

    MANIFEST = "manifest"
    """The bundle's own index. Always present, always last to be written."""

    REPORT = "report"
    """The human-readable generation report, including what was left out."""

    LOG = "log"
    """The live runtime log, redacted line by line and possibly truncated."""

    ROTATED_LOG = "rotated_log"
    """A rotated predecessor of the live log, under the same treatment."""

    FAULT = "fault"
    """The `faulthandler` text file. Native tracebacks, path-sanitised."""

    LIFECYCLE = "lifecycle"
    """The Phase 022 lifecycle record for this run and the previous one."""

    DIAGNOSTICS = "diagnostics"
    """The Phase 023 diagnostics subsystem's own record of itself."""

    BOOTSTRAP = "bootstrap"
    """The Phase 021 bootstrap manifest, which explains why the process started."""


EXCLUDED_NOT_ALLOWLISTED: Final[str] = "BUNDLE_NOT_ALLOWLISTED"
"""The candidate has no artifact kind, so nothing decided it was safe."""

EXCLUDED_OUTSIDE_ROOT: Final[str] = "BUNDLE_OUTSIDE_ROOT"
"""The candidate resolves outside the approved root."""

EXCLUDED_NOT_REGULAR: Final[str] = "BUNDLE_NOT_REGULAR"
"""The candidate is a directory, a link, a device or a reparse point."""

EXCLUDED_TOO_LARGE: Final[str] = "BUNDLE_TOO_LARGE"
"""The candidate is over the per-file limit and truncation was not permitted."""

EXCLUDED_BUDGET_SPENT: Final[str] = "BUNDLE_BUDGET_SPENT"
"""An earlier member used the total byte or file-count budget."""

EXCLUDED_UNREADABLE: Final[str] = "BUNDLE_UNREADABLE"
"""The candidate could not be read. The reason is not reproduced, because an
operating-system error message quotes the path it failed on."""

EXCLUDED_NAME_UNSAFE: Final[str] = "BUNDLE_NAME_UNSAFE"
"""The candidate's member name could not be made safe."""

EXCLUDED_DUPLICATE: Final[str] = "BUNDLE_DUPLICATE"
"""Another member already claims that name, or one differing only in case."""

EXCLUSION_REASONS: Final[tuple[str, ...]] = (
    EXCLUDED_NOT_ALLOWLISTED,
    EXCLUDED_OUTSIDE_ROOT,
    EXCLUDED_NOT_REGULAR,
    EXCLUDED_TOO_LARGE,
    EXCLUDED_BUDGET_SPENT,
    EXCLUDED_UNREADABLE,
    EXCLUDED_NAME_UNSAFE,
    EXCLUDED_DUPLICATE,
)
"""Every reason a candidate may be left out, as a closed set.

A tuple rather than a ``frozenset`` for the reason
:data:`globin.domain.health.REASONS` gives: building a frozenset is a call, and
a layer package performs none at import.
"""

MINIMUM_ARCHIVE_BYTES: Final[int] = 4_096
"""The smallest total archive a limit may permit.

A bundle always carries a snapshot, a manifest and a report, so a limit below this
describes an archive that could never be built. Refusing the limit is better than
building nothing and reporting a budget.
"""

MAXIMUM_ARCHIVE_BYTES: Final[int] = 268_435_456
"""The largest total archive a limit may permit — 256 MiB.

A ceiling on the ceiling. ``RUNTIME_FILESYSTEM.md`` forbids bulk data in the
runtime tree, so a bundle approaching this size means something else has gone
wrong, and permitting a gigabyte would let that go unnoticed until an operator
tried to send one.
"""

MAXIMUM_MEMBER_COUNT: Final[int] = 512
"""The largest member count a limit may permit."""


@dataclass(frozen=True, slots=True)
class BundleLimits:
    """What a bundle may not exceed.

    Args:
        total_input_bytes: How much may be read from disk in total.
        archive_bytes: How large the finished archive may be.
        member_bytes: How large one member may be before it is truncated.
        log_bytes: How much log text may be included, across every log member.
        member_count: How many members there may be.

    Raises:
        ValidationError: If any bound is outside its declared range, or if the
            per-member bound exceeds the total.

    **A limit that cannot be honoured must not exist**, which is the rule
    :class:`~globin.domain.diagnostics.RotationPolicy` established for the same
    reason: a value validated only where it is used is a value that has already
    travelled through code that assumed it was sane.
    """

    total_input_bytes: int
    archive_bytes: int
    member_bytes: int
    log_bytes: int
    member_count: int

    def __post_init__(self) -> None:
        """Refuse a set of limits that describes an impossible bundle.

        Raises:
            ValidationError: As described above.
        """
        for name in ("total_input_bytes", "archive_bytes", "member_bytes", "log_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                msg = f"{name} is a positive count of bytes, and {value!r} is not one"
                raise ValidationError(msg)
        if not MINIMUM_ARCHIVE_BYTES <= self.archive_bytes <= MAXIMUM_ARCHIVE_BYTES:
            msg = (
                f"archive_bytes is between {MINIMUM_ARCHIVE_BYTES} and "
                f"{MAXIMUM_ARCHIVE_BYTES}, and {self.archive_bytes} is not"
            )
            raise ValidationError(msg)
        if isinstance(self.member_count, bool) or not 0 < self.member_count <= MAXIMUM_MEMBER_COUNT:
            msg = (
                f"member_count is between 1 and {MAXIMUM_MEMBER_COUNT}, "
                f"and {self.member_count!r} is not"
            )
            raise ValidationError(msg)
        if self.member_bytes > self.total_input_bytes:
            msg = (
                f"member_bytes ({self.member_bytes}) exceeds total_input_bytes "
                f"({self.total_input_bytes}), so the first member could spend the whole budget"
            )
            raise ValidationError(msg)


@dataclass(frozen=True, slots=True)
class BundleEntry:
    """One member of a finished bundle, as the manifest records it.

    Args:
        member: The archive member name, normalised and safe.
        kind: What sort of artefact it is.
        size_bytes: The member's size as stored, after any truncation.
        digest: A ``sha256:`` prefixed hex digest of exactly those bytes.
        redacted: Whether redaction altered the content on the way in.
        truncated: Whether a limit cut it short.
        source: Where it came from, as a runtime-relative label rather than a
            path. ``logs/globin.log``, never a user profile directory.

    Raises:
        ValidationError: If the member name is unsafe or the digest malformed.
    """

    member: str
    kind: ArtifactKind
    size_bytes: int
    digest: str
    redacted: bool = False
    truncated: bool = False
    source: str = ""

    def __post_init__(self) -> None:
        """Refuse an entry that names an unsafe member or a malformed digest.

        Raises:
            ValidationError: As described above.
        """
        problems = member_problems(self.member)
        if problems:
            msg = f"a bundle entry names an unsafe member: {problems[0]}"
            raise ValidationError(msg)
        if not self.digest.startswith("sha256:") or len(self.digest) != len("sha256:") + 64:
            msg = f"a bundle entry's digest is a sha256 hex digest, and {self.digest!r} is not"
            raise ValidationError(msg)
        if isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            msg = f"a bundle entry's size is a byte count, and {self.size_bytes!r} is not one"
            raise ValidationError(msg)


@dataclass(frozen=True, slots=True)
class BundleExclusion:
    """One candidate that was not included, and why.

    Args:
        kind: What it would have been, where that was known.
        reason: A code from :data:`EXCLUSION_REASONS`.
        detail: A short, path-free note.

    **No path.** The whole point of excluding something is that it could not be
    shown to be safe, and a rejection message naming the file it rejected would
    publish the one string the exclusion was protecting.
    """

    kind: ArtifactKind | None
    reason: str
    detail: str = ""

    def __post_init__(self) -> None:
        """Refuse an undeclared reason code.

        Raises:
            ValidationError: If ``reason`` is not declared.
        """
        if self.reason not in EXCLUSION_REASONS:
            msg = f"{self.reason!r} is not a declared bundle exclusion reason"
            raise ValidationError(msg)


@dataclass(frozen=True, slots=True)
class BundleManifest:
    """The bundle's index: what is inside, and what deliberately is not.

    Args:
        entries: Every member, ordered by member name.
        exclusions: Every candidate that was left out.
        limits: The limits the build was run under.
        schema_version: The manifest's shape version.

    Raises:
        ValidationError: If two entries claim the same name, if two claim names
            differing only in case, or if the entries are not in member order.

    **The case check is not theoretical on the target host.** Windows compares
    filenames case-insensitively, so an archive containing both ``logs/Globin.log``
    and ``logs/globin.log`` extracts to one file on the machine most likely to be
    reading it, and the second silently replaces the first. The archive format
    permits both; the platform does not; the manifest would then describe two
    members and two digests, one of which no longer exists on disk.
    """

    entries: tuple[BundleEntry, ...] = ()
    exclusions: tuple[BundleExclusion, ...] = ()
    limits: BundleLimits | None = None
    schema_version: int = BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Refuse a manifest whose members collide or are out of order.

        Raises:
            ValidationError: As described above.
        """
        members = [entry.member for entry in self.entries]
        if members != sorted(members):
            msg = "a bundle manifest lists its entries in member order, and this one does not"
            raise ValidationError(msg)
        duplicates = _repeated(members)
        if duplicates:
            msg = f"a bundle manifest names the same member twice: {duplicates}"
            raise ValidationError(msg)
        folded = _repeated([member.casefold() for member in members])
        if folded:
            msg = (
                "a bundle manifest names two members differing only in case, which "
                f"a case-insensitive filesystem cannot extract: {folded}"
            )
            raise ValidationError(msg)

    def total_bytes(self) -> int:
        """How large the members are, before compression.

        Returns:
            The sum of every entry's stored size.
        """
        return sum(entry.size_bytes for entry in self.entries)


def _repeated(values: list[str]) -> list[str]:
    """Every value appearing more than once, sorted.

    Args:
        values: The values to inspect.

    Returns:
        The repeated ones, each named once.
    """
    seen: set[str] = set()
    twice: set[str] = set()
    for value in values:
        if value in seen:
            twice.add(value)
        seen.add(value)
    return sorted(twice)


def member_problems(member: str) -> tuple[str, ...]:
    r"""Every reason a member name is not safe to write into an archive.

    Args:
        member: The candidate name.

    Returns:
        One sentence per problem, empty when the name is safe.

    Six refusals, and each has a real failure behind it rather than a style
    preference:

    * **Empty, or over the length bound.** Neither extracts reliably.
    * **A backslash.** The ZIP format specifies forward slashes; a backslash is a
      literal character in a member name, so ``logs\\globin.log`` extracts on
      POSIX as a single file with a backslash in it.
    * **Absolute, whether by leading slash or by drive letter.** An extractor
      honouring it writes outside the directory the operator chose. This is the
      classic archive traversal, and the fact that most modern extractors defend
      against it is not a reason to emit one.
    * **A ``..`` segment.** The same attack by a different spelling, and the one
      that survives naive normalisation.
    * **A reserved device stem.** Cannot be created on Windows at all.
    * **A control character, a trailing dot or a trailing space.** Windows
      silently strips the last two when creating a file, so the name in the
      manifest and the name on disk would differ — and the manifest is what the
      digests are checked against.
    """
    problems: list[str] = []
    if not member:
        problems.append("a member name is not empty")
        return tuple(problems)
    if len(member) > MAXIMUM_MEMBER_LENGTH:
        problems.append(f"{member!r} is longer than {MAXIMUM_MEMBER_LENGTH} characters")
    if "\\" in member:
        problems.append(f"{member!r} contains a backslash; members use {MEMBER_SEPARATOR!r}")
    if member.startswith(MEMBER_SEPARATOR):
        problems.append(f"{member!r} is absolute")
    if len(member) > 1 and member[1] == ":":
        problems.append(f"{member!r} names a drive")
    segments = member.split(MEMBER_SEPARATOR)
    if any(segment in {"", ".", ".."} for segment in segments):
        problems.append(f"{member!r} has an empty, current or parent segment")
    for segment in segments:
        stem = segment.split(".", maxsplit=1)[0].casefold()
        if stem in RESERVED_STEMS:
            problems.append(f"{member!r} contains the reserved name {segment!r}")
        if segment != segment.rstrip(" ."):
            problems.append(f"{member!r} has a segment ending in a dot or a space")
    if any(character < " " or character == "\x7f" for character in member):
        problems.append(f"{member!r} contains a control character")
    return tuple(problems)


def safe_member_name(area: str, filename: str) -> str:
    """Build the archive member name for one collected file.

    Args:
        area: The runtime area the file came from, such as ``logs``.
        filename: The file's own name, with no directory part.

    Returns:
        A normalised, POSIX-style, relative member name.

    Raises:
        ValidationError: If the result would not be safe.

    Deliberately built from two known-good pieces rather than derived from a
    resolved path. A function that took an absolute path and made it relative
    would have to decide what to do with every awkward shape a real path can
    have; this one cannot produce those shapes, because it never sees one.
    """
    member = f"{area}{MEMBER_SEPARATOR}{filename}" if area else filename
    problems = member_problems(member)
    if problems:
        msg = f"a collected file has no safe member name: {problems[0]}"
        raise ValidationError(msg)
    return member
