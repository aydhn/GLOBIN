"""What the committed locks resolve to, as inventory entries.

The SBOM used to describe the *declared* set and said so: nothing in this package
resolved a transitive closure, so claiming one would have been inventing edges.
Phase 020 produced a lock and Phase 021 produced a second one, and a lock **is** a
resolved closure — so the closure can now be described from evidence rather than
guessed at, which is the widening ``DEPENDENCY_LOCKING.md`` records against this
phase's name.

**This is not a fourth register inside** :mod:`tools.quality.supply.inventory`.
That module states about itself that it reads manifests and runs no resolver;
a lock is resolved output, and putting one into it would make the claim false.
``DEPENDENCY_LOCKING.md`` says so explicitly, so the reading lives here instead
and the inventory is left describing exactly what it says it describes.

**And it is not a second lock reader.**
:func:`tools.quality.lock.plan.parse_lock` is the one reader, and it is the one
used here. A private ``tomllib`` parse would have avoided one import and created
the second parser this repository spends real effort not having.

**The import is deferred, and that is deliberate rather than lazy.**
``tools.quality.lock.plan`` imports :mod:`tools.quality.supply.inventory`, and
``tools/quality/supply/__init__.py`` re-exports from the supply gate — so an
import of ``lock`` at module scope here closes a cycle through two package
``__init__`` files, and the failure it produces is a partially-initialised module
rather than anything that names the real problem. Deferring it to the one
function that needs it breaks the cycle at a point a reader can see, which is
better than moving a re-export to hide it.

**No edge is claimed.** PEP 751 records what a resolution produced, not why —
pip writes no dependency edges into a lock. So every component from here is
listed as present with nothing depending on it, which is all the evidence
supports. The SBOM's root still depends on what a *manifest* names, and that is
the only relationship anything here knows.
"""

from pathlib import Path
from typing import Final

from tools.quality.supply.inventory import PINNED, PYPI, Dependency

LOCKED: Final[str] = "locked"
"""The scope a transitive component carries.

Its own value rather than ``runtime`` or ``development``, because a transitive
component is not something anybody chose: nothing declares ``six``, and filing it
under a scope that means "somebody decided this" would misdescribe how it got
here. It also keeps every ``bom-ref`` distinct from the declared entry for the
same distribution, which is what stops ``numpy`` appearing twice under one name.
"""

CONFIGURATION_FILE: Final[str] = "docs/engineering/lock-policy.toml"
"""Where the locks are declared, so that this reads the ones that are governed."""


def from_locks(root: Path) -> tuple[Dependency, ...]:
    """Every distribution the committed locks resolve to.

    Args:
        root: The repository root.

    Returns:
        One entry per locked distribution, ordered, with the lock that recorded
        it as the source. Empty when the declaration cannot be read or a lock is
        absent — the lock gate is what refuses in that case, and duplicating the
        refusal here would give one fault two owners.

    Raises:
        SupplyChainError: Never. Declared absent deliberately: this widens a
            document, and a widening that can fail turns a supply-chain report
            into a second gate.

    A distribution locked by both files appears once, attributed to the first
    lock that recorded it. The lock gate already reports a version disagreement
    between two locks as a defect, so there is nothing for this to add.
    """
    # Deferred to break a package cycle. See the module docstring.
    from tools.quality.lock.plan import LockError, parse_declaration, parse_lock

    declaration_text = _read(root / CONFIGURATION_FILE)
    if declaration_text is None:
        return ()
    try:
        declaration = parse_declaration(declaration_text)
    except LockError:
        return ()

    paths = [declaration.dev_path]
    if declaration.runtime_locked:
        paths.append(declaration.runtime_path)

    found: dict[str, Dependency] = {}
    for relative in paths:
        text = _read(root / relative)
        if text is None:
            continue
        try:
            lock = parse_lock(text, path=relative)
        except LockError:
            continue
        for package in lock.packages:
            if package.version is None or package.normalised in found:
                continue
            found[package.normalised] = Dependency(
                ecosystem=PYPI,
                name=package.normalised,
                version=package.version,
                scope=LOCKED,
                resolution=PINNED,
                source=relative,
                direct=False,
            )
    return tuple(sorted(found.values()))


def _read(path: Path) -> str | None:
    """Read a file, or report that it is not there.

    Args:
        path: The file.

    Returns:
        Its contents, or ``None`` when it is missing or unreadable.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
