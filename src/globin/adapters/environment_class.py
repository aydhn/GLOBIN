"""Reading the environment class document.

The only module in the package that parses ``environment-classes.toml``. It lives
here rather than in the domain for two reasons that happen to agree: ``tomllib``
is I/O-capable and ``docs/architecture/dependency-rules.toml`` forbids the inner
layers from importing anything that is, and
``tests/architecture/test_identifier_discipline.py`` refuses a venue environment
*name* anywhere in the domain layer at all.

The second is the interesting one. The first draft of
:mod:`globin.domain.environment_class` carried the name-to-class mapping directly,
and the tripwire caught it — *"a register of instances belongs to the phase that
reads it from the venue, not to the layer that bounds its shape"*. Which
environments a venue publishes changes without GLOBIN being redeployed, so the
mapping is data in a document and this module is what turns it into an
:class:`~globin.domain.environment_class.EnvironmentClassification`.

**Two failures, kept apart**, as :mod:`globin.adapters.api_reality` keeps them. A
declaration that is absent or unparseable produces ``None``, which a caller
reports as unmeasured. A declaration that is present and *wrong* raises
:class:`~globin.errors.ValidationError`, because a committed document
contradicting itself is a defect in this repository rather than a fact about a
host.

**The guarantees are read and compared, never adopted.** The document restates
every boolean :func:`~globin.domain.environment_class.guarantees` declares, and
:func:`disagreements` reports where the two differ. That is the arrangement
``rest-transport.toml`` has with :mod:`globin.domain.rest`, and what the second
copy buys is a *citation*: a boolean in a Python module is a value somebody typed,
while the same boolean in the document carries the source it was read from.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from globin.domain.environment_class import (
    EnvironmentClass,
    EnvironmentClassification,
    EnvironmentGuarantees,
    guarantees,
    guarantees_for,
)
from globin.errors import ValidationError

CLASSES_PATH: Final[str] = "docs/engineering/environment-classes.toml"
"""Where the declaration lives, relative to the repository root.

Spelled once, for the reason :data:`globin.adapters.api_reality.REGISTRY_PATH` is:
a second copy is how a reader and a gate end up looking at different files while
both report success.
"""

SUPPORTED_SCHEMA: Final[int] = 1
"""The document schema version this reader understands.

A document declaring another version is refused rather than read optimistically. A
reader that ignored the version would silently apply this phase's field meanings
to a later phase's fields.
"""

GUARANTEE_FIELDS: Final[tuple[str, ...]] = (
    "carries_real_capital",
    "reaches_venue",
    "accepts_credential",
    "orders_are_binding",
    "market_data_is_real",
    "state_is_venue_owned",
    "feature_parity_with_live",
)
"""Every boolean a class row must carry.

Listed rather than derived from the dataclass, and the redundancy is deliberate:
this tuple is what makes a *missing* field a failure. Deriving it would mean a
field added to the dataclass and forgotten in the document read as ``False``,
which is a guarantee silently weakened rather than a document visibly incomplete.
"""


def _table(document: Any, key: str) -> list[dict[str, Any]]:
    """One array-of-tables from a parsed document.

    Args:
        document: The parsed document.
        key: Which table.

    Returns:
        The rows, or an empty list when the key is absent.

    Raises:
        ValidationError: If the key is present and is not an array of tables.
    """
    rows = document.get(key, [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        msg = f"{CLASSES_PATH} declares {key!r} as something other than an array of tables"
        raise ValidationError(msg)
    return rows


def _class_of(value: object, *, where: str) -> EnvironmentClass:
    """Turn a declared class name into a member.

    Args:
        value: What the document said.
        where: What to name in a message.

    Returns:
        The member.

    Raises:
        ValidationError: If the value is not a member's value.

    Refused rather than defaulted, because an unrecognised class name in a
    committed document means the document and the enumeration have drifted, and
    picking a member on the reader's behalf would hide exactly that.
    """
    if not isinstance(value, str):
        msg = f"{where} names a class that is not a string"
        raise ValidationError(msg)
    try:
        return EnvironmentClass(value)
    except ValueError as fault:
        known = ", ".join(sorted(member.value for member in EnvironmentClass))
        msg = f"{where} names the class {value!r}, which is not one of {known}"
        raise ValidationError(msg) from fault


@dataclass(frozen=True, slots=True)
class DeclaredClass:
    """One class row as the document states it, before comparison.

    Kept as its own type rather than folded straight into an
    :class:`~globin.domain.environment_class.EnvironmentGuarantees`, so that
    :func:`disagreements` compares two independently constructed values. Building
    the domain object *from* the document and then comparing it against itself
    would establish only that the reader is deterministic.
    """

    environment_class: EnvironmentClass
    values: tuple[tuple[str, bool], ...]
    source: str

    @property
    def mapping(self) -> dict[str, bool]:
        """The declared booleans, by field name."""
        return dict(self.values)


def read_classes(path: Path) -> tuple[EnvironmentClassification, tuple[DeclaredClass, ...]] | None:
    """Read the environment class document.

    Args:
        path: Where the document is.

    Returns:
        The classification and the declared class rows, or ``None`` when the
        document is absent or unparseable.

    Raises:
        ValidationError: If the document is present, parses, and is wrong about
            itself — an unsupported schema, an unknown class, a member naming no
            class, a class declared twice, or a class row missing a guarantee.

    A document that names a class GLOBIN does not know **fails** rather than being
    skipped, and a class the document does not mention fails too. Both directions,
    because a classification with a class missing would answer ``None`` for every
    environment filed under it — which reads as *unclassified* and means
    *undeclared*, and the two have different remedies.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None

    schema = document.get("schema")
    if schema != SUPPORTED_SCHEMA:
        msg = (
            f"{CLASSES_PATH} declares schema {schema!r} and this reader understands "
            f"{SUPPORTED_SCHEMA}"
        )
        raise ValidationError(msg)

    declared: list[DeclaredClass] = []
    seen: set[EnvironmentClass] = set()
    for row in _table(document, "class"):
        environment_class = _class_of(row.get("name"), where=f"{CLASSES_PATH} [[class]]")
        if environment_class in seen:
            msg = f"{CLASSES_PATH} declares the class {environment_class.value!r} twice"
            raise ValidationError(msg)
        seen.add(environment_class)
        values: list[tuple[str, bool]] = []
        for field in GUARANTEE_FIELDS:
            value = row.get(field)
            if not isinstance(value, bool):
                msg = (
                    f"{CLASSES_PATH} class {environment_class.value!r} declares {field!r} as "
                    f"{value!r}; every guarantee is a boolean and a missing one is not False"
                )
                raise ValidationError(msg)
            values.append((field, value))
        source = row.get("source")
        if not isinstance(source, str) or not source:
            msg = f"{CLASSES_PATH} class {environment_class.value!r} cites no source"
            raise ValidationError(msg)
        declared.append(
            DeclaredClass(
                environment_class=environment_class,
                values=tuple(values),
                source=source,
            )
        )

    missing = sorted(member.value for member in EnvironmentClass if member not in seen)
    if missing:
        msg = (
            f"{CLASSES_PATH} declares no guarantees for {', '.join(missing)}; every class must "
            "be declared, or an environment filed under it would answer as unclassified"
        )
        raise ValidationError(msg)

    entries: list[tuple[str, EnvironmentClass]] = []
    for row in _table(document, "member"):
        name = row.get("name")
        if not isinstance(name, str) or not name:
            msg = f"{CLASSES_PATH} declares a [[member]] with no name"
            raise ValidationError(msg)
        entries.append((name, _class_of(row.get("class"), where=f"{CLASSES_PATH} member {name!r}")))

    return EnvironmentClassification(entries=tuple(entries)), tuple(declared)


def disagreements(declared: tuple[DeclaredClass, ...]) -> tuple[str, ...]:
    """Where the document and the package disagree about a guarantee.

    Args:
        declared: The rows read from the document.

    Returns:
        One message per disagreement, sorted, or an empty tuple.

    Compared in **both directions** by construction: every class the package
    declares appears in ``declared`` — :func:`read_classes` has already refused a
    document missing one — and every field in :data:`GUARANTEE_FIELDS` is compared
    for each. A field the package gained and the document did not is caught by
    :func:`read_classes`; a value the two disagree about is caught here.

    ``source`` is compared too, because the document's whole contribution is
    provenance: a guarantee that agrees on its value and disagrees about which
    document it was read from is a citation nobody could check.
    """
    problems: list[str] = []
    by_class = {row.environment_class: row for row in declared}
    for entry in guarantees():
        row = by_class.get(entry.environment_class)
        if row is None:
            problems.append(
                f"{entry.environment_class.value}: declared by the package, not by the document"
            )
            continue
        stated = row.mapping
        for field in GUARANTEE_FIELDS:
            package_value = getattr(entry, field)
            if stated[field] != package_value:
                problems.append(
                    f"{entry.environment_class.value}.{field}: the document says "
                    f"{stated[field]} and the package says {package_value}"
                )
        if row.source != entry.source:
            problems.append(
                f"{entry.environment_class.value}.source: the document cites {row.source!r} "
                f"and the package cites {entry.source!r}"
            )
    return tuple(sorted(problems))


def guarantees_of(classification: EnvironmentClassification) -> tuple[EnvironmentGuarantees, ...]:
    """The guarantees of every class this classification actually uses.

    Args:
        classification: The classification.

    Returns:
        The guarantees, one per distinct class named, in enumeration order.

    Read by ``globin auth classes``, which lists what the running configuration
    could encounter rather than every class the programme defines. A class nothing
    is filed under is a definition, not a state this host can be in.
    """
    used = {environment_class for _, environment_class in classification.entries}
    return tuple(guarantees_for(member) for member in EnvironmentClass if member in used)


__all__ = [
    "CLASSES_PATH",
    "GUARANTEE_FIELDS",
    "SUPPORTED_SCHEMA",
    "DeclaredClass",
    "disagreements",
    "guarantees_of",
    "read_classes",
]
