"""Reading the registry document, and publishing evidence about it.

The only module in the package that parses ``binance-api-reality.toml``. It lives
here rather than in the domain because ``tomllib`` is I/O-capable and
``docs/architecture/dependency-rules.toml`` forbids the inner layers from
importing anything that is.

**Two failures, kept apart.** A declaration that is absent or unparseable produces
``None``, which a caller reports as unmeasured. A declaration that is present and
*wrong* raises :class:`~globin.errors.ValidationError`, because a committed
document contradicting itself is a defect in this repository rather than a fact
about a host. :mod:`globin.adapters.degradation` draws the same line for the same
reason.

**No wall clock and no absolute path reaches the manifest.** No manifest in this
repository carries a timestamp: one that changed because it was built on a
different day could not be compared with itself, and the determinism check would
be measuring the clock.
"""

import hashlib
import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from globin.domain.api_reality import (
    SCHEMA_VERSION,
    ApiKeyType,
    ApiRealitySnapshot,
    AuthMechanism,
    CapabilityRecord,
    EncodingKind,
    EndpointRecord,
    EnvironmentName,
    EnvironmentRecord,
    EvidenceKind,
    KeyPermission,
    ProductFamily,
    ProductProfile,
    ProtocolKind,
    SchemaFamilyName,
    SchemaLifecycleState,
    SchemaVersion,
    SourceAuthority,
    SourceObservation,
    SourceRegime,
    SurfaceCapability,
    SurfaceRecord,
    SurfaceStatus,
    TransportKind,
)
from globin.errors import ValidationError

REGISTRY_PATH: Final[str] = "docs/engineering/binance-api-reality.toml"
"""Where the declaration lives, relative to the repository root.

Spelled once. A second copy of this path is how a reader and a gate end up
disagreeing about which document is the registry.
"""

SCHEMA: Final[str] = "globin.api_reality.manifest"
"""What the published manifest calls itself."""

MANIFEST_SCHEMA_VERSION: Final[int] = 1
"""The manifest shape. Independent of the registry's own :data:`SCHEMA_VERSION`."""

PHASE: Final[int] = 33
"""Which phase published this manifest."""

MANIFEST_NAME: Final[str] = "api-reality-manifest.json"
"""The manifest's filename inside its evidence directory."""

EVIDENCE_DIRECTORY: Final[str] = "api_reality"
"""Where the manifest goes inside the artefact root.

A segment joined onto the artefact root rather than a sixth declared runtime area,
so the count of roots the bootstrap creates does not change.
"""

DIGEST_PREFIX: Final[str] = "sha256:"
"""What a manifest digest begins with."""

DIGEST_KEY: Final[str] = "digest"
"""Which key holds the digest, and is excluded from its own input."""


class RegistryError(ValidationError):
    """The registry document is present and contradicts itself.

    A subclass of :class:`~globin.errors.ValidationError` so that a caller
    catching the taxonomy's validation branch catches this too, and so that the
    exit code a command reports does not need a new class for a defect in a
    committed file.
    """


def render(document: Mapping[str, object]) -> str:
    """One manifest as canonical JSON.

    Args:
        document: The manifest.

    Returns:
        Sorted keys, no incidental whitespace, ASCII only, one trailing newline.
    """
    return (
        json.dumps(dict(document), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    )


def digest(document: Mapping[str, object]) -> str:
    """One manifest's content digest.

    Args:
        document: The manifest, with or without its digest already set.

    Returns:
        :data:`DIGEST_PREFIX` followed by 64 lowercase hexadecimal characters,
        taken over everything except the digest itself.
    """
    payload = {key: value for key, value in document.items() if key != DIGEST_KEY}
    return DIGEST_PREFIX + hashlib.sha256(render(payload).encode("utf-8")).hexdigest()


def _text(row: Mapping[str, object], key: str, *, default: str = "") -> str:
    """One string field, narrowed.

    Args:
        row: A parsed table.
        key: The field.
        default: What an absent field means.

    Returns:
        Its value.

    Raises:
        RegistryError: If present and not a string.
    """
    value = row.get(key, default)
    if not isinstance(value, str):
        msg = f"{key!r} must be a string, and {value!r} is not"
        raise RegistryError(msg)
    return value


def _integer(row: Mapping[str, object], key: str, *, default: int = 0) -> int:
    """One integer field, narrowed.

    Args:
        row: A parsed table.
        key: The field.
        default: What an absent field means.

    Returns:
        Its value.

    Raises:
        RegistryError: If present and not an integer. ``bool`` is refused, because
            it is an ``int`` subclass and a ``true`` where a port belongs would
            otherwise read as 1.
    """
    value = row.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{key!r} must be an integer, and {value!r} is not"
        raise RegistryError(msg)
    return value


def _flag(row: Mapping[str, object], key: str, *, default: bool = False) -> bool:
    """One boolean field, narrowed.

    Args:
        row: A parsed table.
        key: The field.
        default: What an absent field means.

    Returns:
        Its value.

    Raises:
        RegistryError: If present and not a boolean.
    """
    value = row.get(key, default)
    if not isinstance(value, bool):
        msg = f"{key!r} must be true or false, and {value!r} is not"
        raise RegistryError(msg)
    return value


def _strings(row: Mapping[str, object], key: str) -> tuple[str, ...]:
    """One array-of-strings field, narrowed.

    Args:
        row: A parsed table.
        key: The field.

    Returns:
        Its values, or an empty tuple when absent.

    Raises:
        RegistryError: If present and not a list of strings.
    """
    value = row.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        msg = f"{key!r} must be a list of strings, and {value!r} is not"
        raise RegistryError(msg)
    return tuple(str(item) for item in value)


def _tables(document: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    """One array-of-tables, narrowed.

    Args:
        document: The parsed registry.
        key: The array name.

    Returns:
        Its entries, or an empty tuple when absent.

    Raises:
        RegistryError: If present and not an array of tables.
    """
    value = document.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        msg = f"{key!r} must be an array of tables, and {value!r} is not"
        raise RegistryError(msg)
    return tuple(dict(item) for item in value)


def _member[T](enumeration: type[T], value: str, *, field: str) -> T:
    """One enum member from its declared spelling.

    Args:
        enumeration: The enumeration.
        value: The spelling in the document.
        field: What it names, for the message.

    Returns:
        The member.

    Raises:
        RegistryError: If the spelling is not a member. Narrowing here rather than
            letting ``ValueError`` escape keeps every registry fault in one class.
    """
    try:
        return enumeration(value)  # type: ignore[call-arg]
    except ValueError as fault:
        msg = f"{field} is {value!r}, which is not one this GLOBIN recognises"
        raise RegistryError(msg) from fault


def _capability(row: Mapping[str, object]) -> CapabilityRecord:
    """The evidentiary half of one row.

    Args:
        row: A parsed table carrying ``status``, ``evidence`` and ``source``.

    Returns:
        The record.

    Raises:
        RegistryError: If any of the three is missing or unrecognised.
    """
    return CapabilityRecord(
        status=_member(SurfaceStatus, _text(row, "status"), field="a status"),
        evidence=_member(EvidenceKind, _text(row, "evidence"), field="an evidence kind"),
        source=_text(row, "source"),
        condition=_text(row, "condition"),
    )


def _source(row: Mapping[str, object]) -> SourceObservation:
    """One declared source.

    Args:
        row: A parsed ``[[source]]`` table.

    Returns:
        The observation.

    Raises:
        RegistryError: If a field is missing or unrecognised.
    """
    return SourceObservation(
        identifier=_text(row, "id"),
        title=_text(row, "title"),
        location=_text(row, "location"),
        authority=_member(SourceAuthority, _text(row, "authority"), field="a source authority"),
        accessed=_text(row, "accessed"),
        regime=_member(SourceRegime, _text(row, "regime"), field="a source regime"),
        digest=_text(row, "digest"),
        notes=_text(row, "notes"),
        known_unparseable=_flag(row, "known_unparseable"),
    )


def _product(row: Mapping[str, object]) -> ProductProfile:
    """One declared product family.

    Args:
        row: A parsed ``[[product]]`` table.

    Returns:
        The profile.

    Raises:
        RegistryError: If a field is missing or unrecognised.
    """
    from globin.domain.api_reality import ProductScope

    return ProductProfile(
        family=ProductFamily(_text(row, "family")),
        scope=_member(ProductScope, _text(row, "scope"), field="a product scope"),
        title=_text(row, "title"),
        capability=_capability(row),
    )


def _surface(row: Mapping[str, object]) -> SurfaceRecord:
    """One declared product-and-protocol surface.

    Args:
        row: A parsed ``[[surface]]`` table.

    Returns:
        The record.

    Raises:
        RegistryError: If a field is missing or unrecognised.
    """
    return SurfaceRecord(
        family=ProductFamily(_text(row, "family")),
        protocol=_member(ProtocolKind, _text(row, "protocol"), field="a protocol"),
        capability=_capability(row),
    )


def _environment(row: Mapping[str, object]) -> EnvironmentRecord:
    """One declared product-and-environment pair.

    Args:
        row: A parsed ``[[environment]]`` table.

    Returns:
        The record.

    Raises:
        RegistryError: If a field is missing or unrecognised.
    """
    return EnvironmentRecord(
        family=ProductFamily(_text(row, "family")),
        environment=EnvironmentName(_text(row, "environment")),
        semantics=_text(row, "semantics"),
        capability=_capability(row),
        carries_real_capital=_flag(row, "carries_real_capital"),
        host_marker=_text(row, "host_marker"),
    )


def _endpoint(row: Mapping[str, object]) -> EndpointRecord:
    """One declared endpoint.

    Args:
        row: A parsed ``[[endpoint]]`` table.

    Returns:
        The record.

    Raises:
        RegistryError: If a field is missing or unrecognised.
    """
    return EndpointRecord(
        family=ProductFamily(_text(row, "family")),
        environment=EnvironmentName(_text(row, "environment")),
        protocol=_member(ProtocolKind, _text(row, "protocol"), field="a protocol"),
        url=_text(row, "url"),
        transport=_member(TransportKind, _text(row, "transport"), field="a transport"),
        request_encoding=_member(
            EncodingKind, _text(row, "request_encoding"), field="a request encoding"
        ),
        response_encoding=_member(
            EncodingKind, _text(row, "response_encoding"), field="a response encoding"
        ),
        auth=_member(AuthMechanism, _text(row, "auth"), field="an authentication mechanism"),
        capability=_capability(row),
        port=_integer(row, "port"),
        tls_required=_flag(row, "tls_required", default=True),
        sni_required=_flag(row, "sni_required"),
        key_types=tuple(
            _member(ApiKeyType, item, field="a key type") for item in _strings(row, "key_types")
        ),
        key_permissions=tuple(KeyPermission(item) for item in _strings(row, "key_permissions")),
        capabilities=tuple(
            _member(SurfaceCapability, item, field="a capability")
            for item in _strings(row, "capabilities")
        ),
        path_prefix=_text(row, "path_prefix"),
    )


def _schema_version(row: Mapping[str, object]) -> SchemaVersion:
    """One declared schema lifecycle entry.

    Args:
        row: A parsed ``[[schema_version]]`` table.

    Returns:
        The record.

    Raises:
        RegistryError: If a field is missing or unrecognised.
    """
    return SchemaVersion(
        family=SchemaFamilyName(_text(row, "family")),
        environment=EnvironmentName(_text(row, "environment")),
        schema_id=_integer(row, "schema_id"),
        version=_integer(row, "version"),
        state=_member(SchemaLifecycleState, _text(row, "state"), field="a schema state"),
        released=_text(row, "released"),
        source=_text(row, "source"),
        deprecated=_text(row, "deprecated"),
        retired=_text(row, "retired"),
    )


def parse_registry(text: str) -> ApiRealitySnapshot:
    """The registry, from its declared text.

    Args:
        text: The document.

    Returns:
        The snapshot, validated by its own constructor.

    Raises:
        RegistryError: If the document does not parse, announces a schema this
            GLOBIN does not read, or carries a row it cannot narrow.
        ValidationError: If the snapshot contradicts itself.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as fault:
        msg = f"the api reality registry is not valid TOML: {fault}"
        raise RegistryError(msg) from fault
    announced = document.get("schema")
    if announced != SCHEMA_VERSION:
        msg = (
            f"the api reality registry announces schema {announced!r} and this GLOBIN "
            f"reads {SCHEMA_VERSION}; it is refused rather than read anyway"
        )
        raise RegistryError(msg)
    return ApiRealitySnapshot(
        sources=tuple(_source(row) for row in _tables(document, "source")),
        products=tuple(_product(row) for row in _tables(document, "product")),
        surfaces=tuple(_surface(row) for row in _tables(document, "surface")),
        environments=tuple(_environment(row) for row in _tables(document, "environment")),
        endpoints=tuple(_endpoint(row) for row in _tables(document, "endpoint")),
        schemas=tuple(_schema_version(row) for row in _tables(document, "schema_version")),
    )


def read_registry(path: Path) -> ApiRealitySnapshot | None:
    """The registry from a file, or nothing if there is no readable file.

    Args:
        path: Where the declaration lives.

    Returns:
        The snapshot, or ``None`` when the file is absent or cannot be read from
        disk at all.

    Raises:
        RegistryError: If the file exists, is readable, and is wrong. An absent
            registry is a state; a broken one is a defect, and flattening the two
            would let a corrupted document report as merely unmeasured.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_registry(text)


@dataclass(frozen=True, slots=True)
class TomlApiRealitySource:
    """The registry, read from the committed document.

    Args:
        path: Where the declaration lives.
    """

    path: Path

    def snapshot(self) -> ApiRealitySnapshot | None:
        """The registry, or nothing.

        Returns:
            The parsed snapshot, or ``None`` if the declaration is absent.

        Raises:
            RegistryError: If the declaration is present and wrong.
        """
        return read_registry(self.path)


def build(
    *,
    run: Mapping[str, object],
    findings: Mapping[str, object],
    verdict: Mapping[str, object],
) -> dict[str, object]:
    """One manifest, with its digest set last.

    Args:
        run: What was read.
        findings: What was concluded.
        verdict: The single answer.

    Returns:
        The manifest, ready to render.
    """
    document: dict[str, object] = {
        "schema": SCHEMA,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "phase": PHASE,
        "run": dict(run),
        "findings": dict(findings),
        "verdict": dict(verdict),
    }
    document[DIGEST_KEY] = digest(document)
    return document


def summarise(snapshot: ApiRealitySnapshot) -> dict[str, object]:
    """What a manifest records about a snapshot.

    Args:
        snapshot: The registry.

    Returns:
        Counts and identities, never the whole registry: a manifest that embedded
        the document it describes would change whenever the document did and prove
        nothing about either.
    """
    return {
        "sources": len(snapshot.sources),
        "products": len(snapshot.products),
        "surfaces": len(snapshot.surfaces),
        "environments": len(snapshot.environments),
        "endpoints": len(snapshot.endpoints),
        "schema_versions": len(snapshot.schemas),
        "status_counts": snapshot.status_counts(),
        "unrefreshable_sources": list(snapshot.unrefreshable_sources()),
        "registry_digest": digest({"registry": snapshot.as_record()}),
    }


def load(text: str) -> dict[str, object]:
    """One manifest read back, refusing anything that does not verify.

    Args:
        text: The rendered manifest.

    Returns:
        The parsed document.

    Raises:
        RegistryError: If it is not JSON, not an object, announces the wrong schema
            or version, or its digest does not cover its content.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the api reality manifest is not valid JSON: {fault}"
        raise RegistryError(msg) from fault
    if not isinstance(document, dict):
        msg = "the api reality manifest is not a JSON object"
        raise RegistryError(msg)
    if document.get("schema") != SCHEMA:
        msg = f"the api reality manifest announces schema {document.get('schema')!r}"
        raise RegistryError(msg)
    if document.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        msg = f"the manifest announces version {document.get('schema_version')!r}"
        raise RegistryError(msg)
    recorded = document.get(DIGEST_KEY)
    if recorded != digest(document):
        msg = "the api reality manifest was edited after its digest was taken"
        raise RegistryError(msg)
    return dict(document)


def write(document: Mapping[str, object], *, directory: Path) -> Path:
    """Publish one manifest, refusing a rendering that is not reproducible.

    Args:
        document: The manifest.
        directory: Where it goes.

    Returns:
        The path written.

    Raises:
        RegistryError: If two renderings of one manifest disagree.
    """
    rendered = render(document)
    if rendered != render(document):
        msg = "two renderings of the same api reality manifest disagreed"
        raise RegistryError(msg)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / MANIFEST_NAME
    target.write_text(rendered, encoding="utf-8", newline="\n")
    return target
