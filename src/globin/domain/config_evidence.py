"""Why configuration resolved the way it did, and what changed since last time.

:mod:`globin.domain.configuration` owns the *model* — what a setting is, how
layers fold, which values are refused. This owns what a resolved configuration
can be asked **about itself**: which source won each key, how many were
overruled on the way, what the whole thing digests to, and how two runs differ.

**The fold already carries the answer; nothing here re-derives it.**
:class:`~globin.domain.configuration.Setting` has held an origin since Phase 007
and :func:`~globin.domain.configuration.resolve` has always kept it. What was
missing was not the data but a projection of it, and a projection is all this is:
every function below is a pure reading of layers that were already assembled.

**Two fingerprints, and the split is the point.**
:func:`~globin.domain.configuration.config_fingerprint` answers "were these two
runs configured the same way", and deliberately excludes origins so that moving a
file does not look like a change. That is exactly right for its question and
exactly wrong for the other one an operator asks — "did anything about how this
resolved move" — because a value that started coming from the environment instead
of a committed document is a change worth seeing even though the value is
identical. :func:`evidence_fingerprint` answers the second. Neither is the other's
approximation, and collapsing them into one would silently drop whichever question
somebody was not thinking about that day.

**A value is digested as well as displayed, and that is what makes drift safe.**
Redaction protects a display, and a redacted display compares equal to every other
redacted display — so a drift report built on displays would report "unchanged"
for precisely the fields it could not see. Each field therefore carries a
domain-separated digest of its real value, which change detection uses and no
reader can turn back into the value. The digest is weakest against a value with
little entropy — a boolean has two candidates — and strongest against one with a
lot, which is the direction that matters: a credential is unguessable and a
``true`` was never a secret. ``SECURITY_BASELINE.md`` says no secret arrives
through configuration at all, so this protects a case that should not occur rather
than one that does.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Final

from globin.domain.configuration import KEY_SEPARATOR, ConfigLayer, GlobinConfig, known_keys
from globin.domain.observability import is_sensitive, redact
from globin.errors import ConfigurationError, ValidationError

CONFIG_SCHEMA_VERSION: Final[int] = 1
"""The configuration contract this GLOBIN speaks.

One, because this is the first version there has been. It is declared so that a
document written for a later contract can be refused rather than misread — a
document is the one part of GLOBIN an operator writes by hand and keeps across
upgrades, and the failure being prevented is a key that quietly means something
else than it did.
"""

SCHEMA_VERSION_KEY: Final[str] = "config_schema_version"
"""The top-level document key that declares which contract it was written for.

**Reserved rather than registered**, and it has to be.
:func:`~globin.domain.configuration.as_config` refuses every key outside
:func:`~globin.domain.configuration.known_keys`, so a document declaring its own
version through an ordinary setting would be rejected by the very mechanism the
version exists to protect. It is extracted before the document is flattened, which
is the same treatment
:func:`~globin.adapters.configuration.reserved_variables` gives
``GLOBIN_PROFILE``.

Omitting it is not an error. A document that says nothing about its version is
read as this version, because requiring the line would break every document
written before the key existed to make a point about documents written after.
"""

DIGEST_PREFIX: Final[str] = "sha256:"
"""What a digest produced here is labelled with."""

FIELD_DIGEST_DOMAIN: Final[str] = "globin.config.field.1"
"""Domain separation for a field digest.

Folded in so that a digest computed here cannot be compared against one computed
anywhere else for a different purpose, and so that a rainbow table built for bare
values does not answer questions about GLOBIN's.
"""

EVIDENCE_DIGEST_DOMAIN: Final[str] = "globin.config.evidence.1"
"""Domain separation for the provenance digest."""

REDACTED_DIGEST: Final[str] = "unavailable"
"""What stands in for a digest that was deliberately not computed."""

MAXIMUM_DOCUMENT_BYTES: Final[int] = 1_048_576
"""How large a configuration document may be before it is refused.

A mebibyte, against a real register of thirty-seven settings whose fully-written
form is a few kilobytes. The bound is not defending against a large *document* —
nobody writes one — but against a path that turns out to name something else: a
log, an archive, a device. ``tomllib`` reads the whole file into memory before it
decides the file is not TOML, so the size is checked first, and the refusal names
a file that is the wrong shape rather than reporting a parse error on byte
four million.
"""


def document_size_problem(size: int, origin: str) -> str:
    """Why a document of this size cannot be read, if it cannot.

    Args:
        size: The document's size in bytes.
        origin: Where it came from, for the message.

    Returns:
        One sentence, or an empty string when the size is acceptable.

    A ``*_problems``-shaped helper returning a string rather than raising, which
    is the convention this repository uses wherever the caller decides what a
    problem means — here the adapter raises, and a test can ask the question
    without constructing a file.
    """
    if size > MAXIMUM_DOCUMENT_BYTES:
        return (
            f"{origin}: the document is {size} bytes, above the {MAXIMUM_DOCUMENT_BYTES}-byte "
            f"ceiling for a configuration file; check that the path names a configuration "
            f"document rather than something else"
        )
    return ""


def supported_schema_versions() -> tuple[int, ...]:
    """Every configuration contract this GLOBIN can read.

    Returns:
        The supported versions, ascending.

    A function rather than a constant because building a tuple is a call and a
    layer package performs none at import — the same reason
    :func:`~globin.domain.bootstrap.checks` is one.
    """
    return (CONFIG_SCHEMA_VERSION,)


def check_schema_version(value: object, origin: str) -> int:
    """Read a document's declared contract version, or refuse it.

    Args:
        value: Whatever the document put under :data:`SCHEMA_VERSION_KEY`.
        origin: Where the document came from, for the message.

    Returns:
        The declared version.

    Raises:
        ConfigurationError: If the value is not a supported version, is not an
            integer, or is a ``bool``.

    **Fail closed in both directions.** A version from the future is refused
    because this GLOBIN does not know what its keys mean; a version from the past
    is refused because silently upgrading a document is the destructive automatic
    migration ``docs/CONFIGURATION_POLICY.md`` refuses. There is no migration
    engine and this phase does not build one — what it builds is the boundary at
    which one could later be written without having to guess what the old
    documents meant.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        msg = (
            f"{origin}: {SCHEMA_VERSION_KEY} is {value!r}, which is not a version number; "
            f"supported versions are {list(supported_schema_versions())}"
        )
        raise ConfigurationError(msg)
    if value not in supported_schema_versions():
        msg = (
            f"{origin}: {SCHEMA_VERSION_KEY} is {value}, which this GLOBIN does not read; "
            f"supported versions are {list(supported_schema_versions())}"
        )
        raise ConfigurationError(msg)
    return value


def field_digest(key: str, value: object) -> str:
    """A digest of one setting's real value.

    Args:
        key: The dotted setting name, folded in so that the same value under two
            keys does not produce one digest.
        value: The value as the winning layer supplied it.

    Returns:
        :data:`DIGEST_PREFIX` followed by 64 lowercase hexadecimal characters.

    ``repr`` rather than ``str`` because ``"1"`` and ``1`` are different
    configurations that ``str`` renders identically, and a drift report that
    called a string a number would be describing a change nobody made in the one
    direction that is hardest to notice.
    """
    payload = f"{FIELD_DIGEST_DOMAIN}\n{key}\n{value!r}"
    return DIGEST_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def display_of(key: str, value: object) -> str:
    """One setting's value, as it may safely be shown.

    Args:
        key: The dotted setting name.
        value: The value the winning layer supplied.

    Returns:
        The value's ``repr``, or the redaction marker when the key's *name* looks
        credential-shaped.

    Reuses :func:`~globin.domain.observability.redact` rather than testing the
    name here, so that what a configuration dump hides and what a log record hides
    cannot drift apart. That single-source rule is
    ``tests/contract/test_configuration_layout_contract.py``'s already.
    """
    safe = redact({key: value})
    return repr(safe[key])


@dataclass(frozen=True, slots=True)
class LayerRecord:
    """One source's contribution, described without its values.

    Args:
        origin: Where the layer came from, as it named itself.
        priority: Its position in the fold. Zero is weakest.
        count: How many keys it set.
    """

    origin: str
    priority: int
    count: int

    def as_record(self) -> dict[str, object]:
        """This layer as the mapping the evidence carries.

        Returns:
            The origin, priority and key count.
        """
        return {"origin": self.origin, "priority": self.priority, "count": self.count}


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    """One resolved key, and the account of how it got its value.

    Args:
        key: The dotted setting name.
        display: The value as it may safely be shown.
        digest: A digest of the real value, for change detection.
        origin: The layer that won.
        priority: That layer's position in the fold.
        overridden: How many weaker layers also set this key and were overruled.
        known: Whether the key is a registered setting. An unknown key still has
            provenance — naming the document that set it is exactly what an
            operator needs — and it is reported rather than dropped.
    """

    key: str
    display: str
    digest: str
    origin: str
    priority: int
    overridden: int
    known: bool

    def as_record(self) -> dict[str, object]:
        """This field as the mapping the evidence carries.

        Returns:
            Every attribute, with the value only in its safe form.
        """
        return {
            "key": self.key,
            "display": self.display,
            "digest": self.digest,
            "origin": self.origin,
            "priority": self.priority,
            "overridden": self.overridden,
            "known": self.known,
        }


@dataclass(frozen=True, slots=True)
class ConfigProvenance:
    """Every resolved key with its account, and every layer that was consulted.

    Args:
        fields: One per key any layer mentioned, sorted by key.
        layers: One per source, in fold order.

    Raises:
        ValidationError: If a key is described twice.
    """

    fields: tuple[FieldProvenance, ...] = ()
    layers: tuple[LayerRecord, ...] = ()

    def __post_init__(self) -> None:
        """Refuse an account that describes one key twice."""
        keys = [field.key for field in self.fields]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            msg = f"the provenance describes {repeated} more than once"
            raise ValidationError(msg)

    def field(self, key: str) -> FieldProvenance:
        """The account for one key.

        Args:
            key: The dotted setting name.

        Returns:
            Its :class:`FieldProvenance`.

        Raises:
            ConfigurationError: If nothing resolved for that key. An operator who
                asks about a key that is not there has usually mistyped it, which
                is a document to fix rather than a GLOBIN defect — so this is a
                :exc:`~globin.errors.ConfigurationError` where
                :meth:`~globin.domain.configuration.ResolvedConfig.setting`
                raises an internal one.
        """
        for field in self.fields:
            if field.key == key:
                return field
        msg = f"nothing resolved for {key!r}; known settings are {sorted(known_keys())}"
        raise ConfigurationError(msg)

    def keys(self) -> tuple[str, ...]:
        """Every key described, sorted.

        Returns:
            The keys.
        """
        return tuple(field.key for field in self.fields)

    def unknown(self) -> tuple[str, ...]:
        """Every described key that is not a registered setting.

        Returns:
            The keys, sorted.
        """
        return tuple(field.key for field in self.fields if not field.known)

    def as_record(self) -> dict[str, object]:
        """This account as the mapping the evidence carries.

        Returns:
            The layers and the fields, both in a stable order.
        """
        return {
            "layers": [layer.as_record() for layer in self.layers],
            "fields": [field.as_record() for field in self.fields],
        }


def provenance_of(layers: Sequence[ConfigLayer]) -> ConfigProvenance:
    """Account for every key across an ordered set of layers.

    Args:
        layers: Weakest first, strongest last — the same sequence
            :func:`~globin.domain.configuration.resolve` was given. Passing a
            different one would describe a resolution that did not happen.

    Returns:
        A :class:`ConfigProvenance`.

    **This takes layers rather than a resolved configuration, and it has to.**
    :class:`~globin.domain.configuration.ResolvedConfig` holds only winners, so
    the count of what was overruled is not recoverable from it. The alternative
    was to make the fold carry losers, which would change a total function used
    everywhere in order to serve one report.
    """
    winners: dict[str, tuple[object, int, str]] = {}
    seen: dict[str, int] = {}
    records: list[LayerRecord] = []
    for priority, layer in enumerate(layers):
        for key, value in layer.values:
            seen[key] = seen.get(key, 0) + 1
            winners[key] = (value, priority, layer.origin)
        records.append(LayerRecord(origin=layer.origin, priority=priority, count=len(layer.values)))

    registered = set(known_keys())
    fields = tuple(
        FieldProvenance(
            key=key,
            display=display_of(key, winners[key][0]),
            digest=field_digest(key, winners[key][0]),
            origin=winners[key][2],
            priority=winners[key][1],
            overridden=seen[key] - 1,
            known=key in registered,
        )
        for key in sorted(winners)
    )
    return ConfigProvenance(fields=fields, layers=tuple(records))


def evidence_fingerprint(provenance: ConfigProvenance) -> str:
    """A digest over how configuration resolved, origins included.

    Args:
        provenance: The account to digest.

    Returns:
        :data:`DIGEST_PREFIX` followed by 64 lowercase hexadecimal characters.

    **The deliberate counterpart to**
    :func:`~globin.domain.configuration.config_fingerprint`, which excludes
    origins so that moving a file is not a change. This includes them, so that a
    value which began arriving from the environment instead of a committed
    document *is* one. A caller that wants "same configuration" asks the other
    function; a caller that wants "same resolution" asks this one; and because the
    two disagree exactly where they should, neither can be used to answer the
    other's question by accident.

    Values enter as digests rather than as values, so this may be published
    wherever the other may.
    """
    parts = [
        f"{field.key}={field.digest}@{field.priority}:{field.origin}"
        for field in sorted(provenance.fields, key=lambda item: item.key)
    ]
    payload = "\n".join([EVIDENCE_DIGEST_DOMAIN, *parts])
    return DIGEST_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    """What one run's configuration was, in a form a later run can compare against.

    Args:
        schema_version: The contract this snapshot was written under.
        profile: The profile that was resolved.
        semantic: The value-only fingerprint.
        evidence: The fingerprint including origins.
        fields: Key, digest and origin for each resolved key. Displays are
            deliberately **not** carried: a snapshot is written to disk and read
            back later, and the least it can hold while still answering "did this
            change" is the least it should hold.
    """

    schema_version: int
    profile: str
    semantic: str
    evidence: str
    fields: tuple[FieldProvenance, ...] = ()

    def as_record(self) -> dict[str, object]:
        """This snapshot as the mapping that is published.

        Returns:
            The two fingerprints, the profile, the contract version, and one
            entry per key carrying its digest and origin only.
        """
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "semantic_fingerprint": self.semantic,
            "evidence_fingerprint": self.evidence,
            "fields": [
                {"key": field.key, "digest": field.digest, "origin": field.origin}
                for field in sorted(self.fields, key=lambda item: item.key)
            ],
        }


def snapshot_of(provenance: ConfigProvenance, *, profile: str, semantic: str) -> ConfigSnapshot:
    """Reduce an account to the record a later run compares against.

    Args:
        provenance: This run's account.
        profile: The profile that was resolved.
        semantic: The value-only fingerprint, computed by
            :func:`~globin.domain.configuration.config_fingerprint` over the same
            resolution.

    Returns:
        A :class:`ConfigSnapshot`.

    The semantic fingerprint is passed in rather than recomputed here, so that the
    snapshot and the run describe one resolution. Recomputing it would be a second
    resolution, and ``ConfigurationResolution.resolved`` already records why that
    is the wrong shape.
    """
    return ConfigSnapshot(
        schema_version=CONFIG_SCHEMA_VERSION,
        profile=profile,
        semantic=semantic,
        evidence=evidence_fingerprint(provenance),
        fields=provenance.fields,
    )


def snapshot_from(document: Mapping[str, Any]) -> ConfigSnapshot:
    """Read a published snapshot back.

    Args:
        document: What :meth:`ConfigSnapshot.as_record` wrote.

    Returns:
        The snapshot.

    Raises:
        ConfigurationError: If the document is not a snapshot this GLOBIN can
            read. A record written under a contract version this one does not
            support is refused rather than partially understood.
    """
    version = check_schema_version(document.get("schema_version"), "the recorded snapshot")
    entries = document.get("fields", [])
    if not isinstance(entries, list):
        msg = "the recorded snapshot's fields are not a list"
        raise ConfigurationError(msg)
    fields = tuple(
        FieldProvenance(
            key=str(entry["key"]),
            display=REDACTED_DIGEST,
            digest=str(entry["digest"]),
            origin=str(entry["origin"]),
            priority=-1,
            overridden=0,
            known=str(entry["key"]) in set(known_keys()),
        )
        for entry in entries
        if isinstance(entry, Mapping)
    )
    return ConfigSnapshot(
        schema_version=version,
        profile=str(document.get("profile", "")),
        semantic=str(document.get("semantic_fingerprint", "")),
        evidence=str(document.get("evidence_fingerprint", "")),
        fields=fields,
    )


@dataclass(frozen=True, slots=True)
class ConfigDrift:
    """How two runs' configuration differ.

    Args:
        added: Keys the later run resolved and the earlier one did not.
        removed: Keys the earlier run resolved and the later one did not.
        changed: Keys whose value moved.
        reorigined: Keys whose value did not move but whose winning source did.
        semantic: Whether the effective configuration differs at all.
        measured: Whether there was a baseline to compare against.
    """

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    reorigined: tuple[str, ...] = ()
    semantic: bool = False
    measured: bool = True

    @property
    def moved(self) -> bool:
        """Whether anything at all differs."""
        return bool(self.added or self.removed or self.changed or self.reorigined)

    def as_record(self) -> dict[str, object]:
        """This comparison as the mapping the evidence carries.

        Returns:
            Each category as a sorted list, plus the two verdicts.

        **No value appears here, for any key.** The categories name what moved;
        the digests that decided it are in the snapshot. A drift report is the
        document most likely to be pasted into a message to somebody else, which
        is the argument for it carrying the least.
        """
        return {
            "measured": self.measured,
            "semantic_drift": self.semantic,
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": list(self.changed),
            "reorigined": list(self.reorigined),
        }


def unmeasured_drift() -> ConfigDrift:
    """The verdict when there is no baseline to compare against.

    Returns:
        A :class:`ConfigDrift` reporting nothing moved and nothing was measured.

    **Not clean, and the distinction is load-bearing.** A first run has
    established that nothing changed only in the sense that it has established
    nothing at all, and ``tools/quality/drift`` treats an unrecorded baseline the
    same way for the same reason. A caller that cannot tell the two apart will
    eventually report a machine as unchanged because it has never been looked at.
    """
    return ConfigDrift(measured=False)


def compare(before: ConfigSnapshot | None, after: ConfigSnapshot) -> ConfigDrift:
    """Compare a run against the one recorded before it.

    Args:
        before: The recorded snapshot, or ``None`` when there is none.
        after: This run's snapshot.

    Returns:
        A :class:`ConfigDrift`.

    A key whose name is credential-shaped is compared exactly like any other,
    because the comparison reads digests rather than values. That is the whole
    reason the digest exists: redaction protects the display, and two redacted
    displays are always equal, so a report built on them would say "unchanged"
    about precisely the fields it could not see.
    """
    if before is None:
        return unmeasured_drift()

    earlier = {field.key: field for field in before.fields}
    later = {field.key: field for field in after.fields}
    shared = sorted(set(earlier) & set(later))
    changed = tuple(key for key in shared if earlier[key].digest != later[key].digest)
    reorigined = tuple(
        key
        for key in shared
        if earlier[key].digest == later[key].digest and earlier[key].origin != later[key].origin
    )
    return ConfigDrift(
        added=tuple(sorted(set(later) - set(earlier))),
        removed=tuple(sorted(set(earlier) - set(later))),
        changed=changed,
        reorigined=reorigined,
        semantic=before.semantic != after.semantic,
        measured=True,
    )


def sensitive_keys(provenance: ConfigProvenance) -> tuple[str, ...]:
    """Every described key whose name looks credential-shaped.

    Args:
        provenance: The account to inspect.

    Returns:
        The keys, sorted.

    Nothing in :func:`~globin.domain.configuration.known_keys` matches today, so
    a non-empty answer means a document set a key that is both unregistered and
    credential-shaped — which
    :func:`~globin.domain.configuration.as_config` will refuse anyway. Reporting
    it separately means the operator is told *why* it is refused rather than only
    that it is unknown.
    """
    return tuple(field.key for field in provenance.fields if is_sensitive(field.key))


def effective_values(config: GlobinConfig) -> dict[str, object]:
    """Every setting's value as the validated model holds it.

    Args:
        config: The bound model.

    Returns:
        Dotted keys mapped to their bound values, with an enumeration rendered as
        its name.

    **The bound values rather than the resolved ones**, and the difference is the
    point of dumping them. ``GLOBIN_LOGGING_MIN_SEVERITY=WARNING`` resolves to the
    string ``"WARNING"`` and binds to a
    :class:`~globin.domain.observability.Severity`; a dump showing the string
    would be showing what the operator typed, which they already know, rather than
    what GLOBIN made of it, which is the question.

    An enumeration is rendered as its **name** because that is how
    ``docs/CONFIGURATION_POLICY.md`` says a severity is written, so a dumped value
    can be pasted back into a document unchanged. Rendering it as the member's
    repr would produce something no document accepts.
    """
    values: dict[str, object] = {}
    for section in fields(config):
        member = getattr(config, section.name)
        for setting in fields(member):
            value = getattr(member, setting.name)
            values[f"{section.name}{KEY_SEPARATOR}{setting.name}"] = (
                value.name if isinstance(value, Enum) else value
            )
    return values
