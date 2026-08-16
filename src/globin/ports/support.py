"""The ports a support bundle is built through.

Two, and they divide the work at the point where the risk changes. Gathering
candidates is where a path can escape a root or a file can turn out not to be a
file; writing the archive is where a member name can collide or a limit can be
exceeded. Splitting them means the collector can be tested against a source that
never touches a disk, and the writer against candidates that were never on one.

**Bytes, not paths, cross this boundary.** A collector hands the writer content it
has already read, redacted and bounded. The writer therefore cannot be tricked into
reading something the collector refused, because it has no way to read anything.
"""

from typing import Protocol

from globin.domain.support import ArtifactKind, BundleEntry, BundleExclusion, BundleManifest


class ArtifactSource(Protocol):
    """Somewhere bundle candidates come from."""

    def collect(self) -> tuple[tuple[str, ArtifactKind, bytes], tuple[BundleExclusion, ...]]:
        """Gather every candidate that could be shown to be safe.

        Returns:
            The accepted candidates as member name, kind and content, and every
            candidate that was refused with its reason.

        **Both halves are returned, and the second is not optional.** A collector
        that returned only what it accepted would make an exclusion
        indistinguishable from a file that never existed, and the difference is
        exactly what an operator needs when the bundle does not contain the log
        they were looking for.
        """
        ...


class ArchiveWriter(Protocol):
    """Somewhere a bundle can be written."""

    def write(self, entries: tuple[tuple[str, bytes], ...]) -> tuple[BundleEntry, ...]:
        """Write every member and report what was stored.

        Args:
            entries: Member name and content, which the implementation writes in
                lexicographic order regardless of the order given.

        Returns:
            One :class:`~globin.domain.support.BundleEntry` per member, carrying
            the digest of exactly the bytes that were stored.
        """
        ...

    def validate(self, manifest: BundleManifest) -> tuple[str, ...]:
        """Read back what was written and check it against the manifest.

        Args:
            manifest: What the archive is claimed to contain.

        Returns:
            One sentence per disagreement, empty when the archive matches.

        **Read back, rather than trusting the write.** The whole value of a
        manifest is that somebody downstream can verify the archive against it, and
        a manifest generated from the same in-memory objects that produced the
        archive verifies nothing — it establishes only that the code agrees with
        itself. This reopens the finished file.
        """
        ...
