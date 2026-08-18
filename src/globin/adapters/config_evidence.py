"""Writing what configuration resolved to, and reading back what it was last time.

Two destinations, and the split is ``CONFIGURATION_LAYOUT.md``'s three-trees table
applied rather than restated.

The **manifest** is evidence about *this repository*: what one run resolved, which
sources it consulted, and what it fingerprinted to. It goes under ``.globin/``,
which is Git-ignored and regenerable, beside every other gate's manifest and in the
same shape — schema, version, phase, sections, digest.

The **snapshot** is state about *this machine*: the least a later run needs in
order to say what changed. It goes in the user-local ``state`` area through
:class:`~globin.adapters.runtime_state.AtomicStateStore`, because a fresh clone
must not inherit a baseline from somebody else's checkout and because a comparison
against a file that Git could have replaced is not a comparison against the
previous run.

**Neither carries a value.** The manifest carries redacted displays and digests;
the snapshot carries digests and origins only. A drift report is the document most
likely to be pasted into a message to somebody else, and the argument for it
carrying the least is that it will travel.
"""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from globin.adapters.bootstrap import record
from globin.domain.bootstrap import RecordedPath, RuntimePaths
from globin.domain.config_evidence import ConfigSnapshot, snapshot_from
from globin.domain.runtime_state import RuntimeArea
from globin.errors import ConfigurationError
from globin.ports.runtime_state import StateStore

SCHEMA: Final[str] = "globin.config.manifest"
"""What this document is."""

SCHEMA_VERSION: Final[int] = 1
"""Which version of that shape it follows."""

PHASE: Final[int] = 30
"""The phase that introduced it."""

MANIFEST_NAME: Final[str] = "config-manifest.json"
"""What the manifest is called."""

EVIDENCE_DIRECTORY: Final[str] = "config"
"""Where it goes, inside the artefact root.

A segment joined onto :attr:`~globin.domain.bootstrap.RuntimePaths.artifacts`
rather than a sixth declared root, so the count of roots the bootstrap creates
does not change and ``.globin`` keeps being spelled in exactly one place.
"""

SNAPSHOT_FILE: Final[str] = "config-snapshot.json"
"""What the drift baseline is called inside the state area."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""What a manifest digest is labelled with."""

DIGEST_KEY: Final[str] = "digest"
"""The key holding the digest, which is excluded from its own input."""


class ConfigManifestError(ConfigurationError):
    """A configuration manifest could not be produced or could not be trusted.

    A :exc:`~globin.errors.ConfigurationError` rather than an internal one because
    every way of reaching it is something an operator can act on: a tree that
    cannot be written to, or a recorded document that has been edited.
    """


def render(document: Mapping[str, object]) -> str:
    """One document, canonically.

    Args:
        document: What to render.

    Returns:
        Sorted keys, no incidental whitespace, ASCII only, one trailing newline.

    The same rendering every other manifest in this repository uses, so that two
    gates' artefacts can be compared byte for byte without anybody having to know
    which produced which.
    """
    return (
        json.dumps(dict(document), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    )


def digest(document: Mapping[str, object]) -> str:
    """A digest over a document, excluding the digest itself.

    Args:
        document: What to digest.

    Returns:
        :data:`DIGEST_PREFIX` followed by 64 lowercase hexadecimal characters.
    """
    payload = {key: value for key, value in document.items() if key != DIGEST_KEY}
    return DIGEST_PREFIX + hashlib.sha256(render(payload).encode("utf-8")).hexdigest()


def build(
    *,
    profile: str,
    provenance: Mapping[str, object],
    fingerprints: Mapping[str, object],
    validation: Mapping[str, object],
    drift: Mapping[str, object],
) -> dict[str, object]:
    """Assemble the manifest.

    Args:
        profile: The profile that was resolved.
        provenance: :meth:`~globin.domain.config_evidence.ConfigProvenance.as_record`.
        fingerprints: The semantic and evidence digests.
        validation: Whether the model bound, and what refused it if not.
        drift: :meth:`~globin.domain.config_evidence.ConfigDrift.as_record`.

    Returns:
        The manifest, digest included.

    **The six documents the brief asked for are six sections of one file.** Every
    area in this repository writes exactly one manifest, and
    ``docs/engineering/QUALITY_GATES.md`` records why: an artefact upload roots at
    the least common ancestor of its paths, and Phase 015 broke a job by adding a
    second one. Six files would also make it possible to hold five that agree and
    one that does not.

    **No timestamp appears anywhere.** The manifest is compared between runs, and
    a clock reading would make every comparison report a change. What makes one
    run distinguishable from another is what it resolved, which is what the
    fingerprints are.
    """
    document: dict[str, object] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE,
        "profile": profile,
        "provenance": dict(provenance),
        "fingerprints": dict(fingerprints),
        "validation": dict(validation),
        "drift": dict(drift),
    }
    document[DIGEST_KEY] = digest(document)
    return document


def load(text: str) -> dict[str, Any]:
    """Read a manifest back, refusing one that cannot be trusted.

    Args:
        text: The rendered manifest.

    Returns:
        The document.

    Raises:
        ConfigManifestError: If it is not JSON, is not this schema, is not a
            version this GLOBIN reads, or does not match its own digest.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the configuration manifest is not JSON: {fault}"
        raise ConfigManifestError(msg) from fault
    if not isinstance(document, dict):
        msg = "the configuration manifest is not an object"
        raise ConfigManifestError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"the document is {document.get('schema')!r} rather than {SCHEMA!r}"
        raise ConfigManifestError(msg)
    if document.get("schema_version") != SCHEMA_VERSION:
        msg = f"the manifest is version {document.get('schema_version')!r}, not {SCHEMA_VERSION}"
        raise ConfigManifestError(msg)
    if document.get(DIGEST_KEY) != digest(document):
        msg = "the configuration manifest does not match its own digest"
        raise ConfigManifestError(msg)
    return document


def write(document: Mapping[str, object], *, root: Path, paths: RuntimePaths) -> RecordedPath:
    """Publish the manifest inside the project.

    Args:
        document: What :func:`build` produced.
        root: The project root. Nothing is ever written outside it.
        paths: The declared tree.

    Returns:
        Where it went, recorded as a fingerprint rather than a spelling.

    Raises:
        ConfigManifestError: If two renderings of the same document disagree.
        OSError: If the file could not be written.

    **Rendered twice and compared before anything is written**, which is the check
    every manifest in this repository performs on itself. A document that does not
    render deterministically cannot be compared between runs, and a comparison
    that silently means nothing is worse than no comparison.
    """
    rendered = render(document)
    if rendered != render(document):
        msg = "two renderings of the same configuration manifest disagreed"
        raise ConfigManifestError(msg)
    directory = (root / paths.artifacts / EVIDENCE_DIRECTORY).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / MANIFEST_NAME
    target.write_text(rendered, encoding="utf-8", newline="\n")
    return record(target, root=root)


def publish_snapshot(store: StateStore, snapshot: ConfigSnapshot) -> None:
    """Record this run's configuration as the baseline a later run compares against.

    Args:
        store: The state store, which publishes atomically.
        snapshot: What this run resolved.

    Raises:
        RuntimePersistenceError: If it could not be written.
    """
    store.publish(RuntimeArea.STATE, SNAPSHOT_FILE, snapshot.as_record())


def read_snapshot(store: StateStore) -> ConfigSnapshot | None:
    """Read the recorded baseline, if there is one.

    Args:
        store: The state store.

    Returns:
        The recorded snapshot, or ``None`` when no run has recorded one.

    Raises:
        ConfigurationError: If a snapshot exists and cannot be read as one. A
            corrupt baseline is reported rather than treated as absent, because
            "no baseline" and "a baseline nobody can read" call for different
            actions and reducing them to one would hide the second for ever.

    ``None`` is the honest answer for a first run and the caller turns it into
    :func:`~globin.domain.config_evidence.unmeasured_drift`, which is not the same
    verdict as "nothing changed".
    """
    document = store.read(RuntimeArea.STATE, SNAPSHOT_FILE)
    if document is None:
        return None
    return snapshot_from(document)
