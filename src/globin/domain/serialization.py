"""How GLOBIN writes a value down, and how it reads one back years later.

``ENGINEERING_CONTRACT.md`` invariant 20 states the problem this module exists to
solve: persisted data outlives the code that wrote it. A record written today is
read by code that has been changed many times since, and the only thing standing
between those two moments is an agreement about shape. This module is that
agreement.

**Serialization is exact or refused.** That is the same sentence
[ADR-0037](../../../docs/adr/0037-arithmetic-is-exact-or-refused-under-an-explicit-context.md)
makes about arithmetic, and it is chosen here for a different reason. Invariant 22
forbids silent data loss, and a *stored* value is read back and compared against
itself — so a conversion that quietly discards a digit does not merely lose
precision, it breaks the identity ``decode(encode(x)) == x`` that makes the
record trustworthy at all. Every encoder below therefore either produces a value
that reads back identical, or raises. None of them narrows.

The clearest case is :class:`~globin.domain.clock.Instant`.
:attr:`~globin.domain.clock.Instant.epoch_millis` *floors*, because a wire
timestamp that has drifted into the future is the one an exchange rejects
([ADR-0035](../../../docs/adr/0035-milliseconds-are-a-floored-projection.md)).
That is right for a request and wrong for a record: flooring an instant on its way
into storage means the value read back is not the value written. So
:func:`encode_instant` **refuses** an instant carrying sub-millisecond precision
rather than truncating it. A caller who wants the floor asks for it by name — the
projection is already public, and asking is one line.

**Two halves, one subject.**

The first is the *envelope*: how a document says what it is
(:class:`Schema`), and what happens when the version it carries is not the
version the reader knows. An unrecognised version is **refused rather than read**,
which generalises the rule
[ADR-0040](../../../docs/adr/0040-evidence-records-every-gate-and-its-schema-version-is-a-contract.md)
already applies to the evidence manifest. Guessing at an unknown shape is how a
migration becomes a silent corruption.

The second is the *wire forms*: what a :class:`~decimal.Decimal`, an
:class:`~globin.domain.clock.Instant` or a :class:`~globin.domain.values.Price`
looks like once written down. :mod:`globin.domain.values` deliberately left this
open — its :class:`~globin.domain.values.Side` says "no wire format is decided
here" — and this module closes it.

**A float never appears.** Not as an intermediate, not as a convenience.
:mod:`globin.domain.values` refuses to build a magnitude from one, and a module
that accepted floats on the way out would reintroduce at the storage boundary
exactly what that one refuses at the construction boundary. Decimals are written
as text, which is exact and preserves the exponent — and the exponent is
information: :class:`~globin.domain.precision.Increment` documents its trailing
zeros as the venue's own statement of its precision.

**A monotonic reading has no wire form, deliberately.**
:class:`~globin.domain.clock.MonotonicReading` documents its reference point as
undefined and readings from different processes as incomparable. A stored reading
is therefore meaningless to whoever reads it back, and the absence of an encoder
is the decision rather than an omission — ``tests/contract`` asserts it stays
absent.

This module imports no layer, performs no I/O and holds no module-level call. It
reads its sibling domain modules, which is the same intra-layer dependency
:mod:`globin.domain.values` already has on
:mod:`globin.domain.precision`.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from itertools import pairwise
from typing import Final

from globin.domain.clock import (
    MICROSECONDS_PER_MILLISECOND,
    Duration,
    Instant,
    instant_from_epoch_millis,
)
from globin.domain.identifiers import specifications
from globin.domain.precision import Increment, Rounding, increment
from globin.domain.values import (
    SYMBOL_SEPARATOR,
    Currency,
    Price,
    Quantity,
    Side,
    Symbol,
    currency,
    price,
    quantity,
    symbol,
)
from globin.errors import ValidationError

SCHEMA_KEY: Final[str] = "schema"
"""The envelope key naming which schema a document follows.

Spelled the same way ``tools/quality/evidence/manifest.py`` already spells it. The
tooling arrived first and proved the shape; this module makes it the rule for
everything GLOBIN persists rather than a habit of one harness.
"""

VERSION_KEY: Final[str] = "schema_version"
"""The envelope key carrying the schema's version.

Separate from :data:`SCHEMA_KEY` rather than folded into it as ``name@2``. A
version is an integer that gets compared, and burying it in a string would mean
every reader parses before it can compare.
"""

RESERVED_KEYS: Final[tuple[str, ...]] = (SCHEMA_KEY, VERSION_KEY)
"""Keys the envelope owns, which a payload may therefore not use.

A payload field called ``schema`` would overwrite the document's own statement of
what it is. Refusing the collision at :func:`envelope` is cheaper than discovering
it when the record will not parse.

A tuple rather than the ``frozenset`` this obviously wants to be. Python has no
frozenset literal, so spelling it that way means *calling* ``frozenset`` while
this module is being imported, and
``tests/architecture/test_architecture_contract.py`` refuses any call executed at
import in a layer package — the same rule that makes
:func:`globin.domain.clock._epoch` a function instead of a constant. Two entries
make the difference between a hash lookup and a scan unmeasurable.
"""

FIRST_VERSION: Final[int] = 1
"""The version a schema starts at.

One rather than zero. A zeroth version reads as "not yet versioned", which is the
state this module exists to make impossible.
"""

SCHEMA_NAME_ALPHABET: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789."
"""The characters a schema name may contain.

Lowercase, digits and the dot that separates namespace from thing, so that
``globin.evidence.manifest`` is expressible and ``Globin Evidence Manifest`` is
not. A schema name ends up in filenames, log lines and eventually column names,
and every one of those has an opinion about spaces and case.

Deliberately *not* :data:`globin.domain.identifiers.NAME_ALPHABET`, which those
two share most of. That one bounds what a market or a run may be called and
permits an underscore; this one bounds a dotted namespace. They are different
rules that happen to overlap, and importing one to serve as the other would claim
a relationship that the next change to either would falsify.
"""

MIN_SCHEMA_NAME_LENGTH: Final[int] = 3
"""The shortest a schema name may be.

Enough for a name that is not a single letter. A schema is named once and read
for years.
"""

MAX_SCHEMA_NAME_LENGTH: Final[int] = 96
"""The longest a schema name may be.

Long enough for three or four dotted segments, short enough to sit in a column
alongside the record it describes.
"""


class Compatibility(StrEnum):
    """Which directions a schema change can be read across.

    The two directions are genuinely independent, which is why there are four
    members rather than a boolean. A change can be safe for new code reading old
    records and unsafe for old code reading new ones, and a system that ships
    both at once — as any system does during a rollout — has to know which.
    """

    FULL = "full"
    """Readable in both directions. The only change that is safe to deploy in any order."""

    BACKWARD = "backward"
    """New code reads old records; old code cannot read new ones. Deploy readers first."""

    FORWARD = "forward"
    """Old code reads new records; new code cannot read old ones. Migrate the data first."""

    NONE = "none"
    """Readable in neither direction. Requires a migration and a version bump, not a deploy."""


@dataclass(frozen=True, slots=True, order=True)
class Field:
    """One field of a schema, as far as compatibility is concerned.

    Args:
        name: The key the field occupies in the payload.
        required: Whether a reader of this version refuses a record that omits
            it.

    Raises:
        ValidationError: If ``name`` is not a non-empty :class:`str`, or
            ``required`` is not a :class:`bool`.

    Deliberately carries no type. Modelling a field's type would mean inventing a
    type vocabulary, and the authoritative schemas that would need one are Phase
    098's. What this type supports is the question Phase 012 was asked — *can
    this version read that version's records* — and presence and requiredness
    answer it. A type that narrows in place is therefore invisible here, which is
    why ``docs/SERIALIZATION_POLICY.md`` forbids it outright rather than
    classifying it.
    """

    name: str
    required: bool

    def __post_init__(self) -> None:
        """Validate the name and the requiredness flag."""
        _require(self.name, str, label="field name", remedy="pass the key the field occupies")
        if not self.name:
            msg = "field name must not be empty: a field with no key cannot be read back"
            raise ValidationError(msg)
        _require(
            self.required,
            bool,
            label="field required",
            remedy="a field is either demanded by a reader or it is not",
        )


@dataclass(frozen=True, slots=True, order=True)
class Schema:
    """What a persisted document is, and which revision of it.

    Args:
        name: A dotted lowercase name, drawn from :data:`SCHEMA_NAME_ALPHABET`.
        version: The revision, an :class:`int` no lower than
            :data:`FIRST_VERSION`.

    Raises:
        ValidationError: If the name is not a :class:`str` of permitted length
            and alphabet, or the version is not an :class:`int` at or above
            :data:`FIRST_VERSION`.

    Ordering is generated, and it orders by name before version, which is the
    order a migration chain wants to be read in.
    """

    name: str
    version: int

    def __post_init__(self) -> None:
        """Validate the name's shape and the version's floor."""
        _validate_schema_name(self.name)
        _require_version(self.version, label="schema version")

    def __str__(self) -> str:
        """Render the schema as ``name@version``."""
        return f"{self.name}@{self.version}"


@dataclass(frozen=True, slots=True)
class Record:
    """A payload together with the schema it was written under.

    Args:
        schema: What the payload is.
        payload: The fields themselves, none of which may use a key in
            :data:`RESERVED_KEYS`.

    Raises:
        ValidationError: If ``schema`` is not a :class:`Schema`, ``payload`` is
            not a mapping with :class:`str` keys, or a key collides with the
            envelope's own.

    The payload is held rather than the document, so that a caller reasoning
    about a record's *contents* never has to step over the two keys that describe
    it. :func:`envelope` joins them; :func:`parse` separates them again.
    """

    schema: Schema
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        """Validate the schema, the payload's shape and its keys."""
        _require(self.schema, Schema, label="record schema", remedy="pass a Schema")
        _require(
            self.payload,
            Mapping,
            label="record payload",
            remedy="a record is a set of named fields",
        )
        for key in self.payload:
            _require(key, str, label="record payload key", remedy="pass a str")
            if key in RESERVED_KEYS:
                msg = (
                    f"record payload may not use the key {key!r}: the envelope owns it, "
                    f"and a field of that name would overwrite the document's own "
                    f"statement of what it is"
                )
                raise ValidationError(msg)


@dataclass(frozen=True, slots=True)
class Migration:
    """One step from a schema version to the next.

    Args:
        schema_name: The schema this step belongs to.
        from_version: The version it reads.
        to_version: The version it produces, which must be ``from_version + 1``.
        apply: Turns a payload at ``from_version`` into one at ``to_version``.

    Raises:
        ValidationError: If either version is not an :class:`int` at or above
            :data:`FIRST_VERSION`, if ``to_version`` is not exactly one above
            ``from_version``, or if ``apply`` is not callable.

    **One step at a time, never a shortcut.** A migration from 1 straight to 4
    would let versions 2 and 3 stop being exercised while still being claimed as
    readable, and the first record that arrives at version 2 would find the path
    it needed had quietly rotted. Composing single steps costs a few function
    calls and keeps every intermediate version honest.
    """

    schema_name: str
    from_version: int
    to_version: int
    apply: Callable[[Mapping[str, object]], Mapping[str, object]]

    def __post_init__(self) -> None:
        """Validate the schema name, the version step and the callable."""
        _validate_schema_name(self.schema_name)
        _require_version(self.from_version, label="migration from_version")
        _require_version(self.to_version, label="migration to_version")
        if self.to_version != self.from_version + 1:
            msg = (
                f"migration must advance exactly one version, got "
                f"{self.from_version} to {self.to_version}: a step that skips a version "
                f"leaves the versions it skipped claimed as readable and never exercised"
            )
            raise ValidationError(msg)
        _require_callable(self.apply, label="migration apply")


def compatibility(*, before: Iterable[Field], after: Iterable[Field]) -> Compatibility:
    """Classify a schema change by which directions it can be read across.

    Args:
        before: The fields of the earlier version.
        after: The fields of the later version.

    Returns:
        The :class:`Compatibility` the change carries.

    Raises:
        ValidationError: If either side contains something that is not a
            :class:`Field`, or names the same field twice.

    Two independent questions, each answered by one rule:

    *Backward* — can code at ``after`` read a record written at ``before``? Only
    if every field ``after`` requires was already present, because a record from
    ``before`` cannot contain a key that did not exist.

    *Forward* — can code at ``before`` read a record written at ``after``? Only
    if every field ``before`` requires still exists, because an old reader will
    demand a key the new writer stopped emitting. Unknown keys are assumed to be
    ignored, which is the behaviour :func:`parse` gives and which
    ``docs/SERIALIZATION_POLICY.md`` requires of every reader.
    """
    earlier = _field_index(before, label="before")
    later = _field_index(after, label="after")
    backward = all(name in earlier for name, required in later.items() if required)
    forward = all(name in later for name, required in earlier.items() if required)
    if backward and forward:
        return Compatibility.FULL
    if backward:
        return Compatibility.BACKWARD
    if forward:
        return Compatibility.FORWARD
    return Compatibility.NONE


def envelope(record: Record) -> dict[str, object]:
    """Turn a record into the document that gets written down.

    Args:
        record: What to write.

    Returns:
        A new mapping carrying :data:`SCHEMA_KEY`, :data:`VERSION_KEY` and the
        payload's fields, flat rather than nested.

    Flat because the evidence manifest is flat and has been readable for two
    phases, and because nesting the payload under a ``payload`` key buys nothing:
    the reserved keys are already refused at construction, so there is no
    collision left for the nesting to prevent.

    The result is a fresh :class:`dict`, so a caller may serialise it, add to it
    or discard it without reaching back into the record.
    """
    _require(record, Record, label="envelope() record", remedy="pass a Record")
    document: dict[str, object] = {
        SCHEMA_KEY: record.schema.name,
        VERSION_KEY: record.schema.version,
    }
    document.update(record.payload)
    return document


def parse(document: Mapping[str, object], *, expecting: str) -> Record:
    """Read a document back into a record, checking it is the schema expected.

    Args:
        document: What was read from storage.
        expecting: The schema name the caller can handle. A document announcing
            anything else is refused.

    Returns:
        The :class:`Record`, with the two envelope keys removed from the payload.

    Raises:
        ValidationError: If the document is not a mapping, is missing either
            envelope key, announces a different schema, or carries a version that
            is not a valid one.

    The schema name is checked rather than trusted. A reader handed the wrong
    document usually finds out through a missing field several layers later,
    which reports the symptom instead of the cause.

    Note what this does **not** do: it does not compare the version against
    anything. A record at any valid version parses here, and deciding whether
    this reader can use that version is :func:`upgrade`'s job. Splitting the two
    is what lets a caller read a record's version in order to decide what to do
    about it.
    """
    _require(document, Mapping, label="parse() document", remedy="pass what storage returned")
    _validate_schema_name(expecting)
    for key in RESERVED_KEYS:
        if key not in document:
            msg = (
                f"document is missing the {key!r} key: an unversioned record cannot be "
                f"read safely, because nothing in it says what shape it is"
            )
            raise ValidationError(msg)
    announced = document[SCHEMA_KEY]
    if announced != expecting:
        msg = f"document announces schema {announced!r}, expected {expecting!r}"
        raise ValidationError(msg)
    version = _require_version(document[VERSION_KEY], label=f"{expecting} document version")
    payload = {key: value for key, value in document.items() if key not in RESERVED_KEYS}
    return Record(schema=Schema(name=expecting, version=version), payload=payload)


def migration_path(migrations: Iterable[Migration]) -> tuple[Migration, ...]:
    """Order a set of migrations and check the chain has no gap.

    Args:
        migrations: The steps, in any order.

    Returns:
        The same steps, ordered by ``from_version``.

    Raises:
        ValidationError: If a step is not a :class:`Migration`, if the steps do
            not all belong to one schema, if two steps read the same version, or
            if the versions they cover are not contiguous.

    An empty set is permitted and returns empty: a schema that has never changed
    has no migrations, and requiring a placeholder would be requiring a lie.
    """
    ordered = sorted(_validated_migrations(migrations), key=lambda step: step.from_version)
    for earlier, later in pairwise(ordered):
        if earlier.from_version == later.from_version:
            msg = (
                f"two migrations both read version {earlier.from_version} of "
                f"{earlier.schema_name}: the chain would have a fork, and nothing here "
                f"could say which branch a record should take"
            )
            raise ValidationError(msg)
        if later.from_version != earlier.to_version:
            msg = (
                f"migration chain for {earlier.schema_name} has a gap: nothing reads "
                f"version {earlier.to_version}, but a step reads {later.from_version}"
            )
            raise ValidationError(msg)
    return tuple(ordered)


def upgrade(record: Record, *, to: int, migrations: Iterable[Migration]) -> Record:
    """Bring a record forward to the version this reader understands.

    Args:
        record: What was parsed out of storage.
        to: The version the caller's code implements.
        migrations: The steps available, in any order.

    Returns:
        A record at version ``to``.

    Raises:
        ValidationError: If ``to`` is not a valid version, if the record is
            **newer** than ``to``, or if the available steps do not reach ``to``
            from the record's version.

    Three cases, and the middle one is the whole point.

    *Already current* — returned unchanged.

    *Older* — migrated forward one step at a time. Each step's output is checked
    to be a mapping before the next receives it, so a migration that returns
    something else is reported against itself rather than against whichever step
    happens to trip over it later.

    *Newer* — **refused**. A record written by code that knew more than this
    reader cannot be understood by guessing, and the plausible-looking guess —
    ignore the unknown keys and carry on — is the one that silently drops the
    field the newer writer added precisely because it mattered. This is
    ADR-0040's "version 1 is refused rather than read", stated once for
    everything GLOBIN persists.
    """
    _require(record, Record, label="upgrade() record", remedy="pass a Record")
    _require_version(to, label="target version")
    if record.schema.version > to:
        msg = (
            f"cannot read {record.schema}: this reader implements version {to}, and a "
            f"record written at a later version cannot be understood by ignoring what "
            f"it added. Upgrade the reader"
        )
        raise ValidationError(msg)
    if record.schema.version == to:
        return record

    steps = {
        step.from_version: step
        for step in migration_path(migrations)
        if step.schema_name == record.schema.name
    }
    payload = record.payload
    version = record.schema.version
    while version < to:
        step = steps.get(version)
        if step is None:
            msg = (
                f"cannot read {record.schema}: no migration takes {record.schema.name} "
                f"from version {version} to {version + 1}, so the path to {to} is broken"
            )
            raise ValidationError(msg)
        payload = _migrated(step, payload)
        version = step.to_version
    return Record(schema=Schema(name=record.schema.name, version=to), payload=payload)


def encode_decimal(value: Decimal) -> str:
    """Write an exact magnitude down.

    Args:
        value: The magnitude.

    Returns:
        Its text form, exponent and trailing zeros intact.

    Raises:
        ValidationError: If ``value`` is not a :class:`~decimal.Decimal`, or is
            not finite.

    Text, never a number. JSON's number type is a float in every reader that
    matters, and routing an exact magnitude through one is the precision loss
    :mod:`globin.domain.values` refuses at the other boundary.

    ``str`` rather than any normalising form, because the exponent carries
    meaning: :class:`~globin.domain.precision.Increment` documents its trailing
    zeros as the venue's statement of its own precision, and
    :meth:`~decimal.Decimal.normalize` would discard exactly that.

    NaN and infinity are refused rather than encoded. Both are representable as
    Decimals and neither is representable in JSON, so a value that reached
    storage as one would come back as something else or not at all.
    """
    _require(value, Decimal, label="encode_decimal() value", remedy="pass a Decimal")
    if not value.is_finite():
        msg = (
            f"cannot encode the non-finite decimal {value}: JSON has no spelling for it, "
            f"so it could not be read back as what it is"
        )
        raise ValidationError(msg)
    return str(value)


def decode_decimal(text: str) -> Decimal:
    """Read an exact magnitude back.

    Args:
        text: The text :func:`encode_decimal` produced.

    Returns:
        The magnitude, identical to the one encoded.

    Raises:
        ValidationError: If ``text`` is not a :class:`str`, is not a decimal
            literal, or names a non-finite value.

    :class:`~decimal.InvalidOperation` is translated rather than propagated:
    ADR-0022 requires a :mod:`globin.errors` type at a boundary, and a caller
    reading a corrupt record wants to be told which text failed.
    """
    _text(text, label="decode_decimal() text")
    try:
        value = Decimal(text)
    except InvalidOperation:
        msg = f"cannot read {text!r} as a decimal"
        raise ValidationError(msg) from None
    if not value.is_finite():
        msg = f"cannot read {text!r} as a decimal: it names a non-finite value"
        raise ValidationError(msg)
    return value


def encode_instant(value: Instant) -> int:
    """Write a moment down, as whole milliseconds since the Unix epoch.

    Args:
        value: The moment.

    Returns:
        The count, exactly — never floored.

    Raises:
        ValidationError: If ``value`` is not an :class:`~globin.domain.clock.Instant`,
            or carries precision finer than a millisecond.

    Milliseconds because ADR-0035 already settled that the wire form of an
    instant is a whole number of them, and a second spelling for storage would be
    a second thing to reconcile.

    **Sub-millisecond precision is refused, not floored.**
    :attr:`~globin.domain.clock.Instant.epoch_millis` floors, and that is correct
    for a request: a timestamp that has drifted into the future is the one an
    exchange rejects. A record is different. It is read back and compared against
    what was written, so truncating on the way in means the comparison fails
    against a value nobody changed. Invariant 22 forbids exactly that silent
    narrowing. A caller who wants the floor writes ``value.epoch_millis``, which
    is one line and says so.
    """
    _require(value, Instant, label="encode_instant() value", remedy="pass an Instant")
    if value.moment.microsecond % MICROSECONDS_PER_MILLISECOND:
        msg = (
            f"cannot encode {value} exactly: it carries {value.moment.microsecond} "
            f"microseconds, and a stored instant is whole milliseconds. Use "
            f"instant.epoch_millis if flooring is what you meant"
        )
        raise ValidationError(msg)
    return value.epoch_millis


def decode_instant(millis: int) -> Instant:
    """Read a moment back from whole milliseconds since the Unix epoch.

    Args:
        millis: The count :func:`encode_instant` produced.

    Returns:
        The moment, in UTC.

    Raises:
        ValidationError: If ``millis`` is not an :class:`int`, is a
            :class:`bool`, or lies outside the range a
            :class:`~datetime.datetime` can represent.
    """
    return instant_from_epoch_millis(millis)


def encode_duration(value: Duration) -> int:
    """Write a length of time down, in whole nanoseconds.

    Args:
        value: The length.

    Returns:
        The count of nanoseconds, exactly.

    Raises:
        ValidationError: If ``value`` is not a
            :class:`~globin.domain.clock.Duration`.

    Nanoseconds rather than the milliseconds an instant uses, and the asymmetry
    is deliberate. A :class:`~globin.domain.clock.Duration` already *holds*
    nanoseconds because :func:`time.monotonic_ns` reports them, so writing them
    down loses nothing; converting to milliseconds would.
    """
    _require(value, Duration, label="encode_duration() value", remedy="pass a Duration")
    return value.nanoseconds


def decode_duration(nanoseconds: int) -> Duration:
    """Read a length of time back from whole nanoseconds.

    Args:
        nanoseconds: The count :func:`encode_duration` produced.

    Returns:
        The length.

    Raises:
        ValidationError: If ``nanoseconds`` is not a non-negative :class:`int`,
            or is a :class:`bool`.
    """
    return Duration(nanoseconds)


def encode_side(value: Side) -> str:
    """Write a direction down.

    Args:
        value: The side.

    Returns:
        Its member value, ``BUY`` or ``SELL``.

    Raises:
        ValidationError: If ``value`` is not a
            :class:`~globin.domain.values.Side`.

    The member value rather than its name, and for :class:`~enum.StrEnum` those
    coincide today. Writing the value is still the right choice: it is the part
    of the type that is a stated contract, whereas the member name is a Python
    identifier that a later refactor could change without anyone thinking about
    the records already on disk.
    """
    _require(value, Side, label="encode_side() value", remedy="pass a Side")
    return value.value


def decode_side(text: str) -> Side:
    """Read a direction back.

    Args:
        text: The text :func:`encode_side` produced.

    Returns:
        The side.

    Raises:
        ValidationError: If ``text`` is not a :class:`str` naming a member.
    """
    return _member(Side, text, label="side")


def encode_rounding(value: Rounding) -> str:
    """Write a rounding mode down.

    Args:
        value: The mode.

    Returns:
        Its member value.

    Raises:
        ValidationError: If ``value`` is not a
            :class:`~globin.domain.precision.Rounding`.

    A rounding mode is persisted because a stored result is only reproducible
    alongside the mode that produced it — ``EXACT`` and ``FLOOR`` disagree about
    whether a value was acceptable at all.
    """
    _require(value, Rounding, label="encode_rounding() value", remedy="pass a Rounding")
    return value.value


def decode_rounding(text: str) -> Rounding:
    """Read a rounding mode back.

    Args:
        text: The text :func:`encode_rounding` produced.

    Returns:
        The mode.

    Raises:
        ValidationError: If ``text`` is not a :class:`str` naming a member.
    """
    return _member(Rounding, text, label="rounding")


def encode_currency(value: Currency) -> str:
    """Write an asset code down.

    Args:
        value: The currency.

    Returns:
        Its code.

    Raises:
        ValidationError: If ``value`` is not a
            :class:`~globin.domain.values.Currency`.
    """
    _require(value, Currency, label="encode_currency() value", remedy="pass a Currency")
    return value.code


def decode_currency(text: str) -> Currency:
    """Read an asset code back.

    Args:
        text: The text :func:`encode_currency` produced.

    Returns:
        The currency.

    Raises:
        ValidationError: If ``text`` is not a valid code.
    """
    return currency(_text(text, label="currency"))


def encode_symbol(value: Symbol) -> str:
    """Write a market down, as ``BASE/QUOTE``.

    Args:
        value: The symbol.

    Returns:
        The two codes joined by
        :data:`~globin.domain.values.SYMBOL_SEPARATOR`.

    Raises:
        ValidationError: If ``value`` is not a
            :class:`~globin.domain.values.Symbol`.

    The separated spelling rather than the concatenated ``BTCUSDT`` a venue
    publishes. Concatenation is ambiguous — nothing in ``BTCUSDT`` says where the
    base ends — and resolving it needs a table of known assets that GLOBIN does
    not have and should not need in order to read its own records. Translating to
    a venue's spelling is Phase 034's job, at the boundary that talks to it.
    """
    _require(value, Symbol, label="encode_symbol() value", remedy="pass a Symbol")
    return f"{value.base.code}{SYMBOL_SEPARATOR}{value.quote.code}"


def decode_symbol(text: str) -> Symbol:
    """Read a market back from ``BASE/QUOTE``.

    Args:
        text: The text :func:`encode_symbol` produced.

    Returns:
        The symbol.

    Raises:
        ValidationError: If ``text`` is not a :class:`str` holding exactly one
            separator, or either side is not a valid code.
    """
    raw = _text(text, label="symbol")
    parts = raw.split(SYMBOL_SEPARATOR)
    expected_parts = 2
    if len(parts) != expected_parts:
        msg = (
            f"cannot read {raw!r} as a symbol: expected exactly one "
            f"{SYMBOL_SEPARATOR!r} separating base from quote"
        )
        raise ValidationError(msg)
    return symbol(parts[0], parts[1])


def encode_increment(value: Increment) -> str:
    """Write a grid spacing down.

    Args:
        value: The increment.

    Returns:
        Its step, as exact text with trailing zeros intact.

    Raises:
        ValidationError: If ``value`` is not an
            :class:`~globin.domain.precision.Increment`.

    The trailing zeros are the reason this is not
    :meth:`~decimal.Decimal.normalize`'d. ``Increment`` documents them as the
    venue's own statement of its precision, so ``0.10`` and ``0.1`` are the same
    number and different statements, and only one of them is what the venue said.
    """
    _require(value, Increment, label="encode_increment() value", remedy="pass an Increment")
    return encode_decimal(value.step)


def decode_increment(text: str) -> Increment:
    """Read a grid spacing back.

    Args:
        text: The text :func:`encode_increment` produced.

    Returns:
        The increment.

    Raises:
        ValidationError: If ``text`` is not a valid step.
    """
    return increment(decode_decimal(_text(text, label="increment")))


def encode_quantity(value: Quantity) -> dict[str, object]:
    """Write an amount of an asset down.

    Args:
        value: The quantity.

    Returns:
        A mapping of ``amount`` and ``currency``.

    Raises:
        ValidationError: If ``value`` is not a
            :class:`~globin.domain.values.Quantity`.

    Two fields rather than one string like ``"1.5 BTC"``. A denominated value
    whose denomination has to be recovered by splitting text is one bad delimiter
    away from the unit confusion :mod:`globin.domain.values` exists to prevent.
    """
    _require(value, Quantity, label="encode_quantity() value", remedy="pass a Quantity")
    return {"amount": encode_decimal(value.amount), "currency": encode_currency(value.currency)}


def decode_quantity(document: Mapping[str, object]) -> Quantity:
    """Read an amount of an asset back.

    Args:
        document: The mapping :func:`encode_quantity` produced.

    Returns:
        The quantity.

    Raises:
        ValidationError: If the mapping is missing either field, or either field
            is unreadable.
    """
    fields = _fields(document, ("amount", "currency"), label="quantity")
    return quantity(
        decode_decimal(_text(fields["amount"], label="quantity amount")),
        decode_currency(_text(fields["currency"], label="quantity currency")),
    )


def encode_price(value: Price) -> dict[str, object]:
    """Write a price down.

    Args:
        value: The price.

    Returns:
        A mapping of ``amount`` and ``symbol``.

    Raises:
        ValidationError: If ``value`` is not a
            :class:`~globin.domain.values.Price`.
    """
    _require(value, Price, label="encode_price() value", remedy="pass a Price")
    return {"amount": encode_decimal(value.amount), "symbol": encode_symbol(value.symbol)}


def decode_price(document: Mapping[str, object]) -> Price:
    """Read a price back.

    Args:
        document: The mapping :func:`encode_price` produced.

    Returns:
        The price.

    Raises:
        ValidationError: If the mapping is missing either field, or either field
            is unreadable.
    """
    fields = _fields(document, ("amount", "symbol"), label="price")
    return price(
        decode_decimal(_text(fields["amount"], label="price amount")),
        decode_symbol(_text(fields["symbol"], label="price symbol")),
    )


def identifier_storage_width() -> int:
    """How wide a column has to be to hold any GLOBIN identifier.

    Returns:
        The longest ``max_length`` any registered identifier kind declares.

    :mod:`globin.domain.identifiers` deferred this to Phase 012 by name — "a
    database column of the size Phase 012 will choose". This is that choice, and
    it is **derived** rather than written down: registering a seventh kind with a
    longer bound moves this number automatically, where a literal would have to
    be remembered. That is the difference ``SOURCE_OF_TRUTH.md`` draws between a
    tripwire and drift.

    Characters, not bytes. What a storage engine multiplies that by is its
    encoding's business, and Phase 012 does not choose a storage engine.
    """
    return max(spec.max_length for spec in specifications())


def _validated_migrations(migrations: Iterable[Migration]) -> list[Migration]:
    """Check every step is a migration for one schema.

    Args:
        migrations: The steps, in any order.

    Returns:
        The steps as a list.

    Raises:
        ValidationError: If a step is not a :class:`Migration`, or the steps name
            more than one schema.
    """
    steps = list(migrations)
    for step in steps:
        _require(step, Migration, label="migration step", remedy="pass a Migration")
    names = {step.schema_name for step in steps}
    if len(names) > 1:
        msg = (
            f"migrations must all belong to one schema, got {sorted(names)}: a chain "
            f"spanning two schemas has no single version line to be contiguous along"
        )
        raise ValidationError(msg)
    return steps


def _migrated(step: Migration, payload: Mapping[str, object]) -> Mapping[str, object]:
    """Run one migration step and check what it returned.

    Args:
        step: The step to run.
        payload: Its input.

    Returns:
        The migrated payload.

    Raises:
        ValidationError: If the step returns something that is not a mapping with
            :class:`str` keys.

    Checked here rather than at the end of the whole chain so that a step that
    misbehaves is named, instead of the next step being blamed for the argument
    it was handed.
    """
    stepped = f"migration {step.schema_name} {step.from_version} to {step.to_version}"
    result = step.apply(payload)
    _require(result, Mapping, label=f"{stepped} result", remedy="return a mapping")
    for key in result:
        _require(key, str, label=f"{stepped} result key", remedy="return str keys")
    return result


def _field_index(fields: Iterable[Field], *, label: str) -> dict[str, bool]:
    """Index fields by name, refusing a repeat.

    Args:
        fields: The fields of one version.
        label: Which side of the comparison this is, for the message.

    Returns:
        Each field's name mapped to whether it is required.

    Raises:
        ValidationError: If an item is not a :class:`Field`, or a name appears
            twice.
    """
    index: dict[str, bool] = {}
    for field in fields:
        _require(field, Field, label=f"{label} entry", remedy="pass a Field")
        if field.name in index:
            msg = (
                f"{label} names the field {field.name!r} twice: a version has one "
                f"answer per field about whether it is required"
            )
            raise ValidationError(msg)
        index[field.name] = field.required
    return index


def _fields(
    document: Mapping[str, object], names: tuple[str, ...], *, label: str
) -> dict[str, object]:
    """Pull an exact set of keys out of a mapping.

    Args:
        document: What was read.
        names: The keys that must be present.
        label: What the mapping was meant to be, for the message.

    Returns:
        Those keys and their values.

    Raises:
        ValidationError: If ``document`` is not a mapping, or a key is missing.

    Extra keys are permitted and ignored, which is what makes a reader forward
    compatible with a writer that added a field — the property
    :func:`compatibility` assumes when it classifies a change.
    """
    _require(document, Mapping, label=label, remedy="pass a mapping of its fields")
    missing = [name for name in names if name not in document]
    if missing:
        msg = f"{label} is missing {', '.join(missing)}"
        raise ValidationError(msg)
    return {name: document[name] for name in names}


def _member[T: StrEnum](enumeration: type[T], text: object, *, label: str) -> T:
    """Read a member of a string enumeration back from its value.

    Args:
        enumeration: The enumeration to read into.
        text: The stored value.
        label: What it was meant to be, for the message.

    Returns:
        The member.

    Raises:
        ValidationError: If ``text`` is not a :class:`str`, or names no member.

    The message lists the permitted values, because a record holding an
    unrecognised one is usually either a typo or a member that a later version
    added — and the reader needs to know which set it is comparing against.
    """
    raw = _text(text, label=label)
    try:
        return enumeration(raw)
    except ValueError:
        permitted = ", ".join(member.value for member in enumeration)
        msg = f"cannot read {raw!r} as a {label}: expected one of {permitted}"
        raise ValidationError(msg) from None


def _require(value: object, expected: type, *, label: str, remedy: str) -> None:
    """Refuse a value whose type is wrong, however it reached here.

    Args:
        value: What was supplied. Typed as :class:`object` so that the check is
            a real one: a parameter typed as the expected class would make the
            test redundant to mypy, and mypy is configured to say so.
        expected: The class the value must be an instance of.
        label: How to name the value in a message.
        remedy: What the caller should do instead.

    Raises:
        ValidationError: If ``value`` is not an instance of ``expected``.

    The same helper, with the same signature and the same reasoning, as
    :func:`globin.domain.values._require`. It is duplicated rather than imported
    because importing a private name across modules to save nine lines trades a
    real coupling for a small one, and ``values`` would then be unable to change
    its own guard without breaking this one.

    The encoders below annotate their parameters, so mypy already refuses the
    wrong type at every call site it can see. This exists for the call sites it
    cannot: a value read from a document, or a test proving the refusal happens.
    """
    if not isinstance(value, expected):
        msg = f"{label} is {type(value).__name__}; {remedy}"
        raise ValidationError(msg)


def _require_callable(value: object, *, label: str) -> None:
    """Refuse a migration step that cannot be called.

    Args:
        value: What was supplied. Typed as :class:`object` for the reason
            :func:`_require` gives — a parameter typed as
            :class:`~collections.abc.Callable` would make the check redundant to
            mypy, which is configured to report a guard that cannot fire.
        label: How to name the value in a message.

    Raises:
        ValidationError: If ``value`` is not callable.

    Separate from :func:`_require` because callability is not an
    :func:`isinstance` question: a class, a bound method and an object with
    ``__call__`` are all callable and share no base.
    """
    if not callable(value):
        msg = f"{label} is {type(value).__name__}; pass the function that rewrites a payload"
        raise ValidationError(msg)


def _text(value: object, *, label: str) -> str:
    """Refuse anything that is not a string.

    Args:
        value: Whatever was read.
        label: What it was meant to be, for the message.

    Returns:
        The string.

    Raises:
        ValidationError: If ``value`` is not a :class:`str`.
    """
    if not isinstance(value, str):
        msg = f"{label} must be a str, got {type(value).__name__}"
        raise ValidationError(msg)
    return value


def _validate_schema_name(name: object) -> None:
    """Refuse a schema name that is not a dotted lowercase name.

    Args:
        name: Whatever was passed.

    Raises:
        ValidationError: If ``name`` is not a :class:`str` of permitted length,
            contains a character outside :data:`SCHEMA_NAME_ALPHABET`, or begins
            or ends with a dot.

    The leading and trailing dot are refused separately from the alphabet
    because they are the two spellings that pass a character check and still name
    an empty namespace segment.
    """
    if not isinstance(name, str):
        msg = f"schema name must be a str, got {type(name).__name__}"
        raise ValidationError(msg)
    if not MIN_SCHEMA_NAME_LENGTH <= len(name) <= MAX_SCHEMA_NAME_LENGTH:
        msg = (
            f"schema name must be {MIN_SCHEMA_NAME_LENGTH} to {MAX_SCHEMA_NAME_LENGTH} "
            f"characters, got {len(name)} in {name!r}"
        )
        raise ValidationError(msg)
    outside = sorted({character for character in name if character not in SCHEMA_NAME_ALPHABET})
    if outside:
        msg = (
            f"schema name {name!r} contains {''.join(outside)!r}, which is outside the "
            f"permitted alphabet {SCHEMA_NAME_ALPHABET!r}"
        )
        raise ValidationError(msg)
    if name.startswith(".") or name.endswith("."):
        msg = f"schema name {name!r} must not begin or end with a dot: that names an empty segment"
        raise ValidationError(msg)


def _require_version(value: object, *, label: str) -> int:
    """Refuse anything that is not a version number, and narrow what is.

    Args:
        value: Whatever was passed.
        label: What it was meant to be, for the message.

    Returns:
        The version, typed as an :class:`int`.

    Raises:
        ValidationError: If ``value`` is a :class:`bool`, is not an :class:`int`,
            or is below :data:`FIRST_VERSION`.

    Returns the value rather than only checking it, so that a caller reading one
    out of a document gets a narrowed type without an :keyword:`assert`. This is
    the shape :func:`globin.domain.precision._require_rounding` already uses.

    ``bool`` is checked first and separately because :func:`isinstance` reports
    ``True`` as an ``int``, and ``True`` would otherwise pass as version one.
    This is the ordering :mod:`globin.domain.clock` and
    :mod:`globin.domain.values` already use.
    """
    if isinstance(value, bool):
        msg = f"{label} must be an int, got the bool {value!r}: a flag is not a version"
        raise ValidationError(msg)
    if not isinstance(value, int):
        msg = f"{label} must be an int, got {type(value).__name__}"
        raise ValidationError(msg)
    if value < FIRST_VERSION:
        msg = (
            f"{label} must be at least {FIRST_VERSION}, got {value}: version zero reads "
            f"as 'not yet versioned', which is the state a schema version exists to rule out"
        )
        raise ValidationError(msg)
    return value
