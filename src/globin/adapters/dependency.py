"""Reading the lock, the marker environment and what is installed.

The observation half of :mod:`globin.domain.dependency`. Everything here touches
the world -- a file's bytes, this interpreter's metadata, this host's platform --
and everything it returns is a plain value the domain can judge without touching
anything.

**This module does not parse PEP 751 by hand, and that is the point.**
``packaging.pylock`` is the specification's own reference implementation, public
API since packaging 26.0, and Phase 029 adopted ``packaging`` partly to get it.
:func:`read_lock` is a translation layer: it hands the document to
``Pylock.from_dict`` and turns the two ways that can fail into
:class:`~globin.domain.dependency.LockState` values, because a start-up check
reports refusals rather than raising them at whoever called it.

The alternative was a second hand-written parser, and
``docs/engineering/SOURCE_OF_TRUTH.md`` is explicit that a second copy of a fact
is only ever justified when a test compares the copies. There is still a second
reader in this repository -- ``tools/quality/lock/plan.py``, written in Phase 020
before ``packaging`` was available here -- and
``tests/contract/test_dependency_reader_contract.py`` is that comparison. Note
which way round it now runs: the *reference* implementation is the yardstick and
the hand-written gate parser is the thing being checked.

**One thing the reference implementation does not report, and this module adds.**
``Pylock.from_dict`` ignores keys it does not recognise rather than collecting
them, so PEP 751's *"a tool SHOULD warn when an unknown key is seen"* cannot be
satisfied by asking it. :func:`unknown_keys` audits the raw document against the
specification's key set. That is a key audit on top of the reference parser, not
a rival to it.

**Why there is no absent-safe factory here.** ``psutil`` gets one because it is
genuinely missing on every CI run; ``packaging`` is present wherever pytest is,
and is pinned explicitly in the workflow so that the availability is a
declaration rather than a circumstance. There is also no degraded answer worth
giving: a dependency inventory that cannot compare versions is not a degraded
inventory, it is the defect Phase 029 exists to remove.
"""

import sys
import tomllib
from collections.abc import Mapping
from importlib import metadata

from packaging.markers import default_environment
from packaging.pylock import (
    Pylock,
    PylockUnsupportedVersionError,
    PylockValidationError,
)
from packaging.tags import Tag, sys_tags

from globin.domain.dependency import (
    LockedEntry,
    LockReading,
    LockState,
    canonical_name,
)

PYTHON_FULL_VERSION: str = "python_full_version"
"""The marker environment key carrying the interpreter's complete version.

Named rather than spelled inline at three call sites, because a typo in a
dictionary key produces an empty string and an empty ``requires-python``
comparison that silently admits everything.
"""


def known_top_level() -> frozenset[str]:
    """Every top-level key PEP 751 defines.

    Returns:
        The nine key names, as they appear in the document.

    A function rather than a module constant because
    ``tests/architecture/test_architecture_contract.py`` refuses any call
    executed at import time, and ``frozenset({...})`` is a call. Every registry
    in this package is a function for the same reason.
    """
    return frozenset(
        {
            "lock-version",
            "environments",
            "requires-python",
            "extras",
            "dependency-groups",
            "default-groups",
            "created-by",
            "packages",
            "tool",
        }
    )


def known_package_keys() -> frozenset[str]:
    """Every key PEP 751 defines inside a ``[[packages]]`` entry.

    Returns:
        The thirteen key names, as they appear in the document.
    """
    return frozenset(
        {
            "name",
            "version",
            "marker",
            "requires-python",
            "dependencies",
            "index",
            "vcs",
            "directory",
            "archive",
            "sdist",
            "wheels",
            "attestation-identities",
            "tool",
        }
    )


def unknown_keys(document: Mapping[str, object]) -> tuple[str, ...]:
    """Every key in a lock document the specification does not define.

    Args:
        document: The parsed TOML, before validation.

    Returns:
        Sorted, de-duplicated key names. A key inside a package entry is
        reported as ``packages.<key>`` so the caller can tell the two levels
        apart without a second traversal.

    This is what makes PEP 751's SHOULD-warn clause answerable. The reference
    implementation reads the keys it knows and ignores the rest, which is
    correct behaviour for a parser and useless for a warning.

    Only two levels are audited. Going deeper -- into ``wheels``, ``vcs`` or
    ``tool`` -- would report a key for every artefact in a lock with several
    hundred of them, and ``tool`` is explicitly the place the specification
    reserves for keys it does not define.
    """
    found: set[str] = set(document) - known_top_level()
    packages = document.get("packages")
    if isinstance(packages, list):
        permitted = known_package_keys()
        for entry in packages:
            if isinstance(entry, dict):
                found.update(f"packages.{key}" for key in set(entry) - permitted)
    return tuple(sorted(found))


def read_lock(text: str) -> LockReading:
    """Read a PEP 751 lock document.

    Args:
        text: The file's contents.

    Returns:
        What this reader made of it, including the ways it failed.

    Never raises. Every refusal is a
    :class:`~globin.domain.dependency.LockState`, because the caller is a
    start-up check whose whole job is to report a problem with a remedy rather
    than to terminate on one.

    The two failure branches are the specification's own, in its own words.
    ``PylockUnsupportedVersionError`` is *"If a tool doesn't support a major
    version, it MUST raise an error"* -- the reference implementation enforces
    ``1 <= lock-version < 2`` -- and it is caught **first** because it is a
    subclass of the general validation error and a broader ``except`` above it
    would swallow the distinction. Everything else is
    :attr:`~globin.domain.dependency.LockState.UNREADABLE`.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return LockReading(state=LockState.UNREADABLE)

    declared = document.get("lock-version")
    version = declared if isinstance(declared, str) else ""

    try:
        lock = Pylock.from_dict(document)
    except PylockUnsupportedVersionError:
        return LockReading(state=LockState.UNSUPPORTED, lock_version=version)
    except PylockValidationError:
        return LockReading(state=LockState.UNREADABLE, lock_version=version)

    unrecognised = unknown_keys(document)
    entries = tuple(
        LockedEntry(
            name=canonical_name(str(package.name)),
            version="" if package.version is None else str(package.version),
            marker="" if package.marker is None else str(package.marker),
            requires_python=(
                "" if package.requires_python is None else str(package.requires_python)
            ),
        )
        for package in lock.packages
    )
    return LockReading(
        state=LockState.NEWER_MINOR if unrecognised else LockState.PRESENT,
        lock_version=str(lock.lock_version),
        entries=entries,
        unknown_keys=unrecognised,
        requires_python=("" if lock.requires_python is None else str(lock.requires_python)),
    )


def marker_environment() -> dict[str, str]:
    """The PEP 508 marker environment for this interpreter and host.

    Returns:
        The standard marker names mapped to their values here.

    Read in this module and nowhere else, then passed down as a value.
    ``Marker.evaluate()`` with no argument would read :mod:`platform` and
    :mod:`sys` itself, which is an observation the domain may not make;
    ``tests/architecture/test_packaging_discipline.py`` refuses the no-argument
    form anywhere under the package.

    Rebuilt key by key rather than handed to ``dict``. ``Environment`` is a
    ``TypedDict`` whose values are typed ``object``, so copying it wholesale
    produces a ``dict[str, object]`` and the domain's ``Mapping[str, str]``
    would be a lie the type checker correctly refuses.
    """
    return {key: str(value) for key, value in default_environment().items()}


def python_full_version(environment: Mapping[str, str]) -> str:
    """The interpreter's complete version, as the marker environment spells it.

    Args:
        environment: A marker environment.

    Returns:
        The version, or the empty string when the key is absent.
    """
    return environment.get(PYTHON_FULL_VERSION, "")


def host_tags() -> frozenset[Tag]:
    """Every PEP 425 tag this interpreter can install.

    Returns:
        The tags ``packaging`` computes for the running interpreter.

    **This answers a different question from the one the wheel gate asks, and
    conflating them is a real defect rather than a tidiness concern.** This is
    *"could this interpreter install that artefact"*, which is machine-specific
    by construction. ``tools/quality/wheels`` asks *"does a wheel exist serving
    the declared target"*, which must return the same verdict on a 3.12 runner,
    a 3.14 runner and a Linux development box. Using this function gate-side
    would make the offline gate reject the committed lock on the 3.12 matrix leg.
    """
    return frozenset(sys_tags())


def installed_versions() -> dict[str, str]:
    """Every distribution this interpreter can import metadata for, with versions.

    Returns:
        Canonicalised distribution name mapped to installed version.

    Read through :mod:`importlib.metadata` rather than by running ``pip list``:
    it is the standard library's own view of the environment it is running in,
    needs no child process, and therefore cannot become a network call by
    accident.

    **The version is the whole reason this exists.** Its predecessor,
    ``globin.adapters.bootstrap.installed_distributions``, walked exactly this
    metadata and returned only the names -- so a distribution installed at a
    version the lock does not name was reported as present and correct. The
    gate's own twin in ``tools/quality/lock/gate.py`` has returned name-to-version
    pairs since Phase 020; the runtime was the anomaly.

    A distribution whose metadata carries no name is skipped rather than
    recorded under an empty key. That happens with a partially removed
    distribution, and inventing a name for it would put a fiction in the
    inventory.
    """
    found: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        if name:
            found[canonical_name(str(name))] = distribution.version
    return found


def interpreter_version() -> str:
    """This interpreter's version, without consulting the marker environment.

    Returns:
        The ``major.minor.micro`` version.

    A cheaper answer than :func:`marker_environment` for the caller that needs
    only the version, and the one place :mod:`sys` is read for it.
    """
    info = sys.version_info
    return f"{info.major}.{info.minor}.{info.micro}"
