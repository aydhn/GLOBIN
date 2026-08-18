"""What a release publishes, and the checksum file that describes it.

**Evidence, not software.** Every asset here is a record of what the gates
established about one commit. No wheel and no source distribution is built:
Since Phase 032 the reason has changed: building *is* verified now -- the
measurements are in
[`../../../docs/engineering/QUALITY_GATES.md`](../../../docs/engineering/QUALITY_GATES.md)
-- but it is verified rather than *gated*, because `hatchling` is absent from
`pylock.dev.toml` and build isolation therefore reaches an index. Publishing a
distribution from a release gate that runs offline would mean attaching an
artefact this gate did not build.

**The checksum file never lists itself.** A file whose own digest is one of its
lines cannot be written — the digest changes the contents, which changes the
digest. Excluding it is not a simplification; it is the only consistent choice,
and :func:`checksum_document` refuses rather than silently dropping it, so a
caller who adds it by mistake is told.

Digests are computed by ``tools/quality/evidence/checksums.py`` rather than
recomputed here. That module already sorts by name, writes lowercase hexadecimal
and uses the two-space separator ``sha256sum`` expects, and a second
implementation would be a second thing to keep in step.
"""

from collections.abc import Mapping
from typing import Final

from tools.quality.evidence.checksums import render as render_checksums
from tools.quality.release.plan import ReleaseError

MANIFEST_FILE: Final[str] = "release-manifest.json"
"""The release gate's own record: what was judged, and what it concluded."""

ACCEPTANCE_FILE: Final[str] = "foundation-acceptance.json"
"""The foundation matrix, machine-readable, as the gate read it."""

SBOM_FILE: Final[str] = "sbom.cyclonedx.json"
"""The CycloneDX inventory, produced by ``python -m tools.quality supply``.

Copied into the release rather than regenerated, so that the document published
is byte-identical to the one the supply-chain gate signed a provenance statement
about in CI. Regenerating it here would produce a second document that ought to
be identical and would have to be checked.
"""

CHECKSUM_FILE: Final[str] = "SHA256SUMS"
"""Digests for every other asset. Never for itself."""

ENVIRONMENT_ACCEPTANCE_FILE: Final[str] = "environment-acceptance.json"
"""The environment band's matrix as the gate read it, added by Phase 032.

A second file rather than a section of the first, matching the declarations it
comes from: a release freezes each band's certification separately, and a reader
asking whether the environment band passed should not have to parse a document
that also answers for a band frozen two releases ago.
"""

PUBLISHED: Final[tuple[str, ...]] = (
    ACCEPTANCE_FILE,
    ENVIRONMENT_ACCEPTANCE_FILE,
    MANIFEST_FILE,
    SBOM_FILE,
)
"""Every asset carrying content, in a stable order.

:data:`CHECKSUM_FILE` is deliberately not a member: it describes this set, so
including it would make the set self-referential in exactly the way the module
docstring rules out.
"""


def published_names() -> tuple[str, ...]:
    """Every file a release publishes, checksum file included.

    Returns:
        The names, sorted, so that two callers listing the release agree about
        order without either of them sorting.
    """
    return tuple(sorted((*PUBLISHED, CHECKSUM_FILE)))


def missing(available: Mapping[str, bytes]) -> tuple[str, ...]:
    """Every content asset that was expected and is not present.

    Args:
        available: Each asset's name and its contents.

    Returns:
        The absent names, sorted.

    An asset that does not exist is a finding rather than an omission. A release
    published with one of its three evidence documents quietly missing would look
    complete to anybody who did not know how many there should be.
    """
    return tuple(sorted(name for name in PUBLISHED if name not in available))


def checksum_document(available: Mapping[str, bytes]) -> str:
    """The ``SHA256SUMS`` file for a set of assets.

    Args:
        available: Each asset's name and its contents.

    Returns:
        One ``digest  name`` line per asset, sorted by name.

    Raises:
        ReleaseError: If the checksum file appears among its own inputs.

    Sorting is by name and comes from
    :func:`tools.quality.evidence.checksums.render`, so the file does not depend
    on the order a directory happened to be walked in — which is what makes two
    runs over one commit produce one document.
    """
    if CHECKSUM_FILE in available:
        msg = (
            f"{CHECKSUM_FILE} cannot be one of its own entries: its digest would "
            f"describe a file that does not yet contain the digest"
        )
        raise ReleaseError(msg)
    return render_checksums(dict(available))
