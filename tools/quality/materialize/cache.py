"""The wheelhouse: local artefact bytes, addressed by the digest the lock names.

The only module in this package that reads a file, and it reads them one chunk at
a time so that a large wheel does not have to be resident to be verified.

**Nothing here fetches.** The wheelhouse is populated by a separate, explicitly
networked subcommand that verifies every byte before it names a file, so a
partial or corrupted download never lands under a valid key. Thereafter
verification runs entirely against local bytes, which is what lets the offline
gate mean something.
"""

import hashlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tools.quality.materialize.plan import WEAK_ALGORITHMS, CacheKey

CHUNK: Final[int] = 1 << 20
"""How many bytes are hashed at a time.

A megabyte. Large enough that hashing is not dominated by call overhead, small
enough that a wheel of any size is verified in bounded memory.
"""

WHEELHOUSE: Final[str] = ".globin/wheelhouse"
"""Where artefacts live, relative to the repository root.

Inside ``.globin/`` because it is evidence about this repository rather than
state about this machine, and because it must be reachable from a checkout that
has never started GLOBIN.
"""


class CacheError(Exception):
    """The wheelhouse could not be read."""


@dataclass(frozen=True, slots=True)
class Wheelhouse:
    """A directory of artefacts addressed by their digests.

    Args:
        root: Where the artefacts live.
    """

    root: Path

    def digests(self, keys: tuple[CacheKey, ...]) -> dict[str, str]:
        """Hash every artefact that is present, and report what it actually is.

        Args:
            keys: The artefacts to look for.

        Returns:
            Cache-relative path to the digest its bytes hash to. A key with no
            file present is **absent from the mapping** rather than mapped to an
            empty string, so that "not fetched" and "fetched and wrong" cannot be
            confused by a caller reading a truthy test.

        Raises:
            CacheError: If an algorithm this repository refuses is asked for.

        The bytes are hashed rather than the filename trusted. A wheelhouse is a
        directory somebody could write to, so the only fact it establishes on its
        own is that a file exists under a name.
        """
        found: dict[str, str] = {}
        for key in keys:
            if key.algorithm in WEAK_ALGORITHMS:
                msg = f"{key.name}: {key.algorithm} is too weak to address an artefact by"
                raise CacheError(msg)
            path = self.root / Path(key.relative())
            if not path.is_file():
                continue
            found[key.relative()] = _digest_of(path, key.algorithm)
        return found

    def entries(self) -> Iterator[Path]:
        """Every file the wheelhouse holds.

        Yields:
            Each artefact's path.

        Used for reporting how large the wheelhouse is, never for deciding what
        is in it -- that is the lock's question, and answering it by walking a
        directory would make the directory the source of truth.
        """
        if not self.root.is_dir():
            return
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                yield path


def _digest_of(path: Path, algorithm: str) -> str:
    """Hash one file.

    Args:
        path: What to hash.
        algorithm: Which digest to use.

    Returns:
        The lowercase hexadecimal digest.

    Raises:
        CacheError: If the file could not be read.
    """
    engine = hashlib.new(algorithm)
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(CHUNK):
                engine.update(chunk)
    except OSError as fault:
        msg = f"{path.name} could not be read: {fault}"
        raise CacheError(msg) from fault
    return engine.hexdigest()


def corrupt_paths(keys: tuple[CacheKey, ...], digests: Mapping[str, str]) -> tuple[str, ...]:
    """Every cached artefact whose bytes are not what the lock names.

    Args:
        keys: The artefacts that were looked for.
        digests: What each present artefact actually hashed to.

    Returns:
        The cache-relative paths, sorted.

    Reported so an operator can remove them by hand. **Nothing here deletes
    one**: removing the evidence of a corruption is how the ability to diagnose
    it is lost, and a gate that silently repaired the cache would be hiding the
    only signal that something on this machine is wrong.
    """
    return tuple(
        sorted(
            key.relative()
            for key in keys
            if key.relative() in digests and digests[key.relative()].lower() != key.digest
        )
    )
