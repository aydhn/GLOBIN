"""Writing a support bundle, reading it back, and publishing it atomically.

The judgement about what may go in a bundle is
:mod:`globin.domain.support`'s. This is the half that touches a disk: it reads
candidates, redacts them, writes the archive, reopens it to check the manifest is
true, and only then moves it into place.

**Determinism is claimed narrowly and the narrow claim is the honest one.** Two
runs *at different times* produce different archives, because a log grows and a
timestamp moves; promising otherwise would be a guarantee nobody could keep. What
is guaranteed for the same logical inputs is the member list, the member order, the
member names, the canonical JSON bytes of the snapshot and manifest, the ZIP
metadata, the compression method and level, and the normalised member timestamps.
Everything a *reader* would compare is stable; only what was measured moves.

**Validation reopens the finished file.** A manifest generated from the same
in-memory objects that produced the archive establishes only that the code agrees
with itself. This reads the archive back through :mod:`zipfile`, recomputes every
digest and compares the member set both ways.

**Publication is atomic.** An incomplete bundle never appears under the final name:
the archive is built under a temporary name in the destination's own directory,
validated, hashed, and then moved with :func:`os.replace`. That is Phase 022's
publication sequence applied to bytes rather than to a JSON document, and it reuses
:class:`~globin.adapters.runtime_state.FileOperations` so that the same injected
seams work here.
"""

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from globin.adapters.runtime_state import FileOperations
from globin.domain.support import (
    ArtifactKind,
    BundleEntry,
    BundleManifest,
    member_problems,
)
from globin.errors import ValidationError

DIGEST_PREFIX: Final[str] = "sha256:"
"""What a recorded digest is prefixed with, as everywhere else in this repository."""

NORMALISED_TIMESTAMP: Final[tuple[int, int, int, int, int, int]] = (1980, 1, 1, 0, 0, 0)
"""The modification time every member is stamped with.

The ZIP format cannot represent a date before 1980, so this is the earliest legal
value rather than an arbitrary one. Real modification times are deliberately
discarded: they are the largest source of nondeterminism in an archive, they vary
with when a file happened to be touched rather than with its content, and on this
host they would additionally record when an operator was at their machine.
"""

MEMBER_PERMISSIONS: Final[int] = 0o644 << 16
"""The external attributes every member carries.

Fixed rather than copied from disk. Windows and POSIX disagree about what a file's
mode even is, so an archive built on one and extracted on the other would otherwise
carry whichever answer the building host happened to give.
"""

COMPRESSION: Final[int] = zipfile.ZIP_DEFLATED
"""The one compression method a bundle uses."""

COMPRESSION_LEVEL: Final[int] = 6
"""The one compression level.

Named rather than left to the library's default, because the default is a property
of the interpreter's version and a bundle's bytes should not change when Python
does.
"""

TEMPORARY_SUFFIX: Final[str] = ".partial"
"""What an in-progress bundle is called before it is validated and moved."""


def digest_of(payload: bytes) -> str:
    """The recorded digest of some bytes.

    Args:
        payload: What to hash.

    Returns:
        A ``sha256:`` prefixed lowercase hex digest.
    """
    return f"{DIGEST_PREFIX}{hashlib.sha256(payload).hexdigest()}"


@dataclass(frozen=True, slots=True)
class ZipArchiveWriter:
    """Builds one bundle archive and can read it back.

    Args:
        path: Where the finished archive will live.
        operations: The injected filesystem seams, so a test can make a flush or a
            replace fail without needing a broken disk.
        temporary: The in-progress path, derived from ``path``.
    """

    path: Path
    operations: FileOperations

    @property
    def temporary(self) -> Path:
        """The in-progress path, beside the final one.

        Returns:
            The path.

        Beside it, and not in the system temporary directory: :func:`os.replace` is
        only atomic within one filesystem, and a temporary file on another volume
        would turn the publication into a copy that can be interrupted halfway.

        A property rather than a field computed in ``__post_init__``, because a
        ``dataclasses.field(init=False)`` is a call in a class body and
        ``tests/architecture/test_architecture_contract.py`` holds every layer
        package to performing no work at import.
        """
        return self.path.with_name(self.path.name + TEMPORARY_SUFFIX)

    def write(self, entries: tuple[tuple[str, bytes], ...]) -> tuple[BundleEntry, ...]:
        """Write every member, in lexicographic order.

        Args:
            entries: Member name and content, in any order.

        Returns:
            One entry per member, carrying the digest of exactly the stored bytes.

        Raises:
            ValidationError: If a member name is unsafe, or two members collide.

        Sorted here rather than trusting the caller. The order a collector happens
        to finish in is not a property anybody should be able to observe in the
        archive, and sorting at the last possible moment means no intermediate step
        has to preserve it.
        """
        ordered = sorted(entries, key=lambda item: item[0])
        self._refuse_collisions(tuple(name for name, _ in ordered))
        self.operations.makedirs(self.path.parent)
        written: list[BundleEntry] = []
        with zipfile.ZipFile(
            self.temporary, "w", compression=COMPRESSION, compresslevel=COMPRESSION_LEVEL
        ) as archive:
            for member, payload in ordered:
                info = zipfile.ZipInfo(filename=member, date_time=NORMALISED_TIMESTAMP)
                info.compress_type = COMPRESSION
                info.external_attr = MEMBER_PERMISSIONS
                info.create_system = 0
                archive.writestr(info, payload)
                written.append(
                    BundleEntry(
                        member=member,
                        kind=_kind_of(member),
                        size_bytes=len(payload),
                        digest=digest_of(payload),
                    )
                )
        return tuple(written)

    @staticmethod
    def _refuse_collisions(members: tuple[str, ...]) -> None:
        """Refuse a member set that cannot be extracted.

        Args:
            members: Every member name.

        Raises:
            ValidationError: If a name is unsafe, repeated, or repeated under a
                case-insensitive comparison.

        The case comparison is not theoretical on the target host. Windows treats
        ``logs/Globin.log`` and ``logs/globin.log`` as one name, so an archive
        containing both extracts to a single file and the manifest then describes a
        member that is not on disk.
        """
        for member in members:
            problems = member_problems(member)
            if problems:
                raise ValidationError(problems[0])
        if len(set(members)) != len(members):
            msg = "a bundle would contain the same member twice"
            raise ValidationError(msg)
        folded = [member.casefold() for member in members]
        if len(set(folded)) != len(folded):
            msg = (
                "a bundle would contain two members differing only in case, which a "
                "case-insensitive filesystem cannot extract"
            )
            raise ValidationError(msg)

    def validate(self, manifest: BundleManifest, *, manifest_member: str) -> tuple[str, ...]:
        """Reopen the archive and check it against the manifest.

        Args:
            manifest: What the archive is claimed to contain.
            manifest_member: The manifest's own name, which it cannot describe
                and which the archive must nonetheless hold.

        Returns:
            One sentence per disagreement, empty when the archive matches.

        Six questions, and the set comparison is deliberately made in both
        directions. A manifest missing a member that is present is as wrong as a
        manifest naming one that is not: the first means something was written
        that nobody described, which is the shape a leak has.
        """
        problems: list[str] = []
        try:
            with zipfile.ZipFile(self.temporary, "r") as archive:
                broken = archive.testzip()
                if broken is not None:
                    return (f"the archive is corrupt at {broken}",)
                present = tuple(archive.namelist())
                if manifest_member not in present:
                    return (f"the archive does not hold its own manifest {manifest_member!r}",)
                described = tuple(name for name in present if name != manifest_member)
                problems.extend(self._member_problems(described, manifest))
                problems.extend(self._digest_problems(archive, manifest))
        except (OSError, zipfile.BadZipFile) as fault:
            return (f"the archive could not be read back: {type(fault).__name__}",)
        return tuple(problems)

    @staticmethod
    def _member_problems(present: tuple[str, ...], manifest: BundleManifest) -> list[str]:
        """Compare the archive's member set against the manifest's, both ways.

        Args:
            present: What the archive holds.
            manifest: What it should hold.

        Returns:
            One sentence per disagreement.
        """
        problems: list[str] = []
        described = {entry.member for entry in manifest.entries}
        actual = set(present)
        for missing in sorted(described - actual):
            problems.append(f"the manifest names {missing!r} and the archive omits it")
        for unexpected in sorted(actual - described):
            problems.append(f"the archive holds {unexpected!r} and the manifest omits it")
        if len(present) != len(actual):
            problems.append("the archive holds a duplicated member name")
        return problems

    @staticmethod
    def _digest_problems(archive: zipfile.ZipFile, manifest: BundleManifest) -> list[str]:
        """Recompute every recorded digest from the stored bytes.

        Args:
            archive: The opened archive.
            manifest: What the digests should be.

        Returns:
            One sentence per mismatch.
        """
        problems: list[str] = []
        for entry in manifest.entries:
            try:
                payload = archive.read(entry.member)
            except KeyError:
                continue
            if len(payload) != entry.size_bytes:
                problems.append(
                    f"{entry.member!r} stores {len(payload)} bytes and the manifest "
                    f"records {entry.size_bytes}"
                )
            recomputed = digest_of(payload)
            if recomputed != entry.digest:
                problems.append(f"{entry.member!r} does not match its recorded digest")
        return problems

    def publish(self, limit: int) -> tuple[str, int]:
        """Move the validated archive into place, atomically.

        Args:
            limit: The largest archive that may be published.

        Returns:
            The finished archive's digest and its size in bytes.

        Raises:
            ValidationError: If the archive is over the limit. The partial file is
                removed first, so a refusal leaves nothing behind.

        The size is checked *here*, after the archive exists, rather than by adding
        up the members beforehand. Compression means the sum of the inputs is not
        the size of the output, and a limit on the finished file is what an
        operator actually cares about — it is the thing they have to send.
        """
        size = self.temporary.stat().st_size
        if size > limit:
            self.discard()
            msg = f"the bundle is {size} bytes and the limit is {limit}"
            raise ValidationError(msg)
        payload = self.temporary.read_bytes()
        self.operations.replace(self.temporary, self.path)
        return digest_of(payload), size

    def discard(self) -> None:
        """Remove the in-progress archive, if there is one.

        Called on every failure path, so a refused bundle leaves no ``.partial``
        file for somebody to find later and mistake for a real one.
        """
        try:
            self.operations.unlink(self.temporary)
        except OSError:
            return


def _kind_of(member: str) -> ArtifactKind:
    """Infer a member's artifact kind from the area it was filed under.

    Args:
        member: The member name.

    Returns:
        The kind.

    Raises:
        ValidationError: If the member is not one the allowlist produces.

    Deliberately derived from the member name rather than carried alongside it.
    The name is what ends up in the archive and in the manifest, so deriving the
    kind from it means the two cannot disagree — and a member nobody's allowlist
    produced has no kind at all, which is the refusal below rather than a default.
    """
    table = {
        "snapshot.json": ArtifactKind.SNAPSHOT,
        "manifest.json": ArtifactKind.MANIFEST,
        "report.txt": ArtifactKind.REPORT,
        "state/lifecycle.json": ArtifactKind.LIFECYCLE,
        "state/diagnostics.json": ArtifactKind.DIAGNOSTICS,
        "state/bootstrap-manifest.json": ArtifactKind.BOOTSTRAP,
        "logs/faults.txt": ArtifactKind.FAULT,
    }
    if member in table:
        return table[member]
    if member.startswith("logs/") and member.endswith(".log"):
        return ArtifactKind.LOG
    if member.startswith("logs/"):
        return ArtifactKind.ROTATED_LOG
    msg = f"{member!r} is not a member the allowlist produces"
    raise ValidationError(msg)
