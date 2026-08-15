"""The inventory as CycloneDX 1.7, generated here so that it is byte-stable.

**Why this is written rather than installed.** ``cyclonedx-py`` exists and would
produce a richer document. It would also stamp each run with a fresh random
``serialNumber`` and the wall clock, so two runs over one unchanged tree would
produce two different files with two different digests. A digest that changes
when nothing changed cannot be evidence of anything, and pinning it down would
mean post-processing the tool's output — at which point the tool is supplying
fields that are then overwritten. ADR-0033 made the same call about the mutation
harness for the same reason, and this follows it.

**Where determinism comes from.** Two fields are ordinarily the source of drift
and both are derived instead of generated:

*The serial number* is a UUID version 5 over the commit, in the URL namespace.
RFC 4122 makes that as valid a UUID as a random one, and it means the same tree
always produces the same serial while two different commits never collide.

*The timestamp* is the commit's own committer date, not the clock. A SBOM
describes a tree, and the moment worth recording is when that tree came to exist
rather than when somebody happened to ask about it.

Everything else follows from the inventory, which is already totally ordered.

**What the document claims, and what it does not.** Every component is something
a manifest in this repository names. There is no transitive closure, because
nothing here resolves one — see :mod:`tools.quality.supply.inventory`. The
``dependencies`` graph therefore states that the root component depends on each
declared component and stops there, which is true. Inventing edges between
components to make the graph look complete would be inventing facts.

Specification: CycloneDX 1.7, published 2025-10-21 and standardised as ECMA-424.
Schema: ``https://cyclonedx.org/schema/bom-1.7.schema.json``.
"""

import hashlib
import json
import uuid
from typing import Final

from tools.quality.supply.inventory import (
    GITHUB_ACTIONS,
    PINNED,
    PRE_COMMIT,
    PYPI,
    Dependency,
)

BOM_FORMAT: Final[str] = "CycloneDX"
"""The one value the specification permits, and a required field."""

SPEC_VERSION: Final[str] = "1.7"
"""The target this phase declares. A reader that supports only 1.6 must refuse
this document rather than read it partially, which is why the field exists."""

SCHEMA_URL: Final[str] = "https://cyclonedx.org/schema/bom-1.7.schema.json"
"""Recorded in the document so that whoever validates it does not have to guess
which schema was meant. Not fetched at generation time: this repository's tooling
makes no network call, and a generator that did would fail offline."""

SERIAL_NAMESPACE: Final[uuid.UUID] = uuid.NAMESPACE_URL
"""The RFC 4122 namespace the serial is derived in.

``NAMESPACE_URL`` rather than a namespace invented here, because the name being
hashed *is* a URL — the repository plus the commit. A bespoke namespace constant
would be one more number nobody can check."""

LIBRARY: Final[str] = "library"
APPLICATION: Final[str] = "application"

BOM_VERSION: Final[int] = 1
"""The revision of this BOM for this serial. Always 1: a second BOM for the same
commit would describe the same tree, so there is never a revision to make."""


def serial_number(repository: str, commit: str) -> str:
    """A stable URN for the BOM describing one commit.

    Args:
        repository: The canonical repository name, such as ``aydhn/GLOBIN``.
        commit: The full commit SHA the BOM describes.

    Returns:
        ``urn:uuid:`` followed by a version 5 UUID.

    Derived rather than generated so that regenerating the SBOM for an unchanged
    tree produces an unchanged file. Two commits produce two serials because the
    commit is part of the hashed name.
    """
    return f"urn:uuid:{uuid.uuid5(SERIAL_NAMESPACE, f'https://github.com/{repository}@{commit}')}"


def _component(entry: Dependency) -> dict[str, object]:
    """One inventory entry as a CycloneDX component.

    Args:
        entry: The dependency.

    Returns:
        The component object.

    ``version`` and ``purl`` appear only for a pinned entry. A range is not a
    version, and a package URL naming one would claim an artefact that no index
    could resolve. The range is preserved as a property instead, so nothing is
    lost and nothing is overstated.
    """
    component: dict[str, object] = {
        "bom-ref": bom_ref(entry),
        "type": LIBRARY,
        "name": entry.name,
        "properties": [
            {"name": "globin:ecosystem", "value": entry.ecosystem},
            {"name": "globin:scope", "value": entry.scope},
            {"name": "globin:resolution", "value": entry.resolution},
            {"name": "globin:source", "value": entry.source},
        ],
    }
    if entry.resolution == PINNED:
        component["version"] = entry.version
        component["purl"] = entry.purl
    else:
        properties = component["properties"]
        if isinstance(properties, list):
            properties.append({"name": "globin:specifier", "value": entry.version})
    return component


def bom_ref(entry: Dependency) -> str:
    """The identifier this document refers to a component by.

    Args:
        entry: The dependency.

    Returns:
        ``<ecosystem>/<name>@<version>#<scope>``.

    Not the package URL, even where there is one. Two inventory entries can name
    the same package in two scopes — ``ruff`` is a development dependency and a
    thing CI installs — and a ``bom-ref`` must be unique within the document. The
    scope suffix is what makes it so, and it makes the reference readable at the
    same time.
    """
    return f"{entry.ecosystem}/{entry.name}@{entry.version}#{entry.scope}"


def build(
    dependencies: tuple[Dependency, ...],
    *,
    repository: str,
    commit: str,
    timestamp: str,
    project: str,
    project_version: str,
    generator_version: str,
) -> dict[str, object]:
    """Assemble the BOM.

    Args:
        dependencies: The collected inventory, already ordered.
        repository: The canonical ``owner/name``.
        commit: The full commit SHA this BOM describes.
        timestamp: The commit's ISO 8601 committer date.
        project: The name of the thing being described.
        project_version: Its version.
        generator_version: The version of GLOBIN that generated this, recorded
            under ``metadata.tools`` because a document should say what made it.

    Returns:
        The document, ready to render.

    Components are ordered by their own ``bom-ref`` rather than by the inventory's
    ordering. Both are total, so either would be deterministic; this one is
    *checkable*, because the key it sorts on is visible in the document. A reader
    — or :func:`validate` — can confirm the order without knowing how the
    inventory happens to sort its dataclass fields.
    """
    root_ref = f"{project}@{project_version}"
    # Sorted on the reference computed from the dependency rather than on the
    # value read back out of the component mapping: the mapping's values are
    # `object`, and a sort key that has to be cast to be compared is a sort key
    # whose ordering the type system cannot check.
    ordered = sorted(dependencies, key=bom_ref)
    components = [_component(entry) for entry in ordered]
    return {
        "$schema": SCHEMA_URL,
        "bomFormat": BOM_FORMAT,
        "specVersion": SPEC_VERSION,
        "serialNumber": serial_number(repository, commit),
        "version": BOM_VERSION,
        "metadata": {
            "timestamp": timestamp,
            "tools": {
                "components": [
                    {
                        "type": APPLICATION,
                        "name": "globin-supply",
                        "version": generator_version,
                    }
                ]
            },
            "component": {
                "bom-ref": root_ref,
                "type": APPLICATION,
                "name": project,
                "version": project_version,
                "properties": [{"name": "globin:commit", "value": commit}],
            },
        },
        "components": components,
        "dependencies": [
            {"ref": root_ref, "dependsOn": [component["bom-ref"] for component in components]},
            *({"ref": component["bom-ref"], "dependsOn": []} for component in components),
        ],
    }


def render(document: dict[str, object]) -> str:
    """Encode the BOM so two generators cannot disagree about bytes.

    Args:
        document: The BOM.

    Returns:
        Indented JSON with sorted keys and a trailing newline.

    Indented rather than the single line the evidence manifest uses, because this
    file is read by people as well as by tools and a 19-component BOM on one line
    is not readable by either. Sorted keys and ASCII-only for the same reasons
    ``tools/quality/evidence/manifest.py`` gives.
    """
    return json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def digest(document: dict[str, object]) -> str:
    """The BOM's stable identity.

    Args:
        document: The BOM.

    Returns:
        ``"sha256:"`` followed by 64 lowercase hexadecimal characters, taken over
        the canonical rendering.

    Held outside the document rather than inside it, for the reason ADR-0042
    states about the evidence artifact: a file cannot contain its own hash.
    """
    return "sha256:" + hashlib.sha256(render(document).encode("utf-8")).hexdigest()


def validate(document: dict[str, object]) -> tuple[str, ...]:
    """Everything wrong with a BOM, checked without a schema validator.

    Args:
        document: The parsed BOM.

    Returns:
        One sentence per problem, empty when there is none.

    A schema validator would be a dependency (``jsonschema``) and a vendored
    schema would be a file nobody rechecks against upstream. What is asserted
    here is what this repository's own generator could plausibly get wrong: the
    two required fields, the declared specification version, component
    uniqueness, referential integrity of the dependency graph, and canonical
    ordering. Those are the failure modes a hand-written generator has. A schema
    would additionally catch shapes this generator cannot produce.
    """
    problems: list[str] = []

    if document.get("bomFormat") != BOM_FORMAT:
        problems.append(f"bomFormat is {document.get('bomFormat')!r}, expected {BOM_FORMAT!r}")
    if document.get("specVersion") != SPEC_VERSION:
        problems.append(
            f"specVersion is {document.get('specVersion')!r}, and this repository "
            f"targets {SPEC_VERSION!r}; a reader would apply the wrong schema"
        )

    serial = document.get("serialNumber")
    if not isinstance(serial, str) or not serial.startswith("urn:uuid:"):
        problems.append(f"serialNumber is {serial!r}, which is not an RFC 4122 URN")

    components = document.get("components")
    if not isinstance(components, list):
        problems.append("components is missing or is not an array")
        return tuple(problems)

    refs: list[str] = []
    for component in components:
        if not isinstance(component, dict):
            problems.append(f"a component is {type(component).__name__}, not an object")
            continue
        if not component.get("type"):
            problems.append(f"component {component.get('name')!r} declares no type")
        if not component.get("name"):
            problems.append("a component declares no name")
        ref = component.get("bom-ref")
        if isinstance(ref, str):
            refs.append(ref)

    duplicates = sorted({ref for ref in refs if refs.count(ref) > 1})
    problems.extend(f"bom-ref {ref!r} identifies more than one component" for ref in duplicates)

    if refs != sorted(refs):
        problems.append(
            "components are not in canonical order, so two runs over one tree "
            "would produce two different digests"
        )

    problems.extend(_graph_problems(document, frozenset(refs)))
    return tuple(problems)


def _graph_problems(document: dict[str, object], known: frozenset[str]) -> tuple[str, ...]:
    """Dependency edges that point at components the document does not contain.

    Args:
        document: The parsed BOM.
        known: Every ``bom-ref`` the components array declares.

    Returns:
        One sentence per dangling reference.

    The root component is a legitimate target that is not in ``components``, so
    it is accepted by name rather than by being added to ``known`` — putting it
    there would also make it a legitimate *component* reference, which it is not.
    """
    metadata = document.get("metadata")
    root = ""
    if isinstance(metadata, dict):
        component = metadata.get("component")
        if isinstance(component, dict):
            root = str(component.get("bom-ref", ""))

    edges = document.get("dependencies")
    if not isinstance(edges, list):
        return ("dependencies is missing or is not an array",)

    problems: list[str] = []
    for edge in edges:
        if not isinstance(edge, dict):
            problems.append(f"a dependency entry is {type(edge).__name__}, not an object")
            continue
        ref = str(edge.get("ref", ""))
        if ref != root and ref not in known:
            problems.append(f"dependencies names {ref!r}, which is not a component in this BOM")
        for target in edge.get("dependsOn", []) or []:
            if target != root and target not in known:
                problems.append(
                    f"{ref!r} depends on {target!r}, which is not a component in this BOM"
                )
    return tuple(problems)


def ecosystem_counts(dependencies: tuple[Dependency, ...]) -> dict[str, int]:
    """How many components each ecosystem contributes.

    Args:
        dependencies: The collected inventory.

    Returns:
        Each of :data:`~tools.quality.supply.inventory.PYPI`,
        :data:`~tools.quality.supply.inventory.GITHUB_ACTIONS` and
        :data:`~tools.quality.supply.inventory.PRE_COMMIT` mapped to its count,
        including the zeroes. A missing key and a zero mean different things to a
        reader, and only one of them is true.
    """
    counts = dict.fromkeys((GITHUB_ACTIONS, PRE_COMMIT, PYPI), 0)
    for entry in dependencies:
        counts[entry.ecosystem] = counts.get(entry.ecosystem, 0) + 1
    return counts
