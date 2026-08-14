"""What a log record *is*, expressed as pure domain types.

GLOBIN logs structured events, not sentences. A call site names an event and
attaches fields; it never interpolates a value into a message. That choice is
what makes the guarantee in this module possible: if a secret can only ever
arrive as a field *value*, then inspecting field *names* is enough to stop it
reaching an output stream.

:class:`LogEvent` therefore redacts itself in ``__post_init__``. Redaction is
not a step a sink is asked to remember — it has already happened by the time an
event exists, so a sink written three phases from now by someone who never read
this file cannot leak a credential by forgetting to call something.
``ENGINEERING_CONTRACT.md`` invariant 24 is absolute, and an absolute rule
enforced by convention is not enforced at all.

Two things are deliberately absent.

*There is no timestamp.* Reading the clock is ambient nondeterminism, and Phase
009 owns the injectable clock abstraction. The adapter stamps the time as it
serialises, which keeps this module testable without freezing anything and
leaves Phase 009 a clean seam rather than a competing scheme to remove.

*There is no severity threshold.* Deciding which events are worth keeping is a
sink's concern, and Phase 007 settled it there:
:class:`globin.adapters.observability.ThresholdLogSink` compares against a
minimum supplied by :class:`globin.domain.configuration.LoggingConfig`. Severity
here only says how bad something is, which is what lets two sinks hold different
thresholds over the same events.

This module imports nothing outside :mod:`globin.errors`, performs no I/O and
holds no module-level call — ``docs/architecture/dependency-rules.toml`` lists
``logging`` among the I/O-capable modules, so the domain layer could not import
it even if that were desirable.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

from globin.errors import ValidationError


class Severity(IntEnum):
    """How bad an event is, ordered so that thresholds are comparisons.

    The numeric values are the ones the standard library's :mod:`logging` uses.
    That is a deliberate borrowing rather than an accident: it means an adapter
    bridging to :mod:`logging` needs no mapping table, and a mapping table
    between two enumerations is a thing that drifts. Nothing in the core imports
    :mod:`logging` to obtain them, so the borrowing costs no dependency.

    What each level means is policy, and policy lives in
    ``docs/LOGGING_POLICY.md``. ``tests/contract/test_observability_contract.py``
    fails if a member here is missing from that document.
    """

    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


SENSITIVE_KEY_FRAGMENTS: Final[tuple[str, ...]] = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "passphrase",
    "password",
    "private_key",
    "secret",
    "session_id",
    "signature",
    "token",
)
"""Field-name fragments whose values never reach an output stream.

Matching is a case-insensitive **substring** test, not an exact-set membership
test, and the difference is load-bearing. A field called ``binance_api_key`` is
exactly the one that must not be printed, and an exact-set rule would miss it.
The cost is over-redaction — a field called ``token_count`` loses a harmless
integer — and that trade is taken knowingly. Redacting a number nobody needed is
an inconvenience; printing a live API secret is the failure
``ENGINEERING_CONTRACT.md`` invariant 24 exists to make impossible.

This is a mechanism with a defensible starting list, not GLOBIN's secret
inventory. Phase 015 establishes the security baseline and secret-handling
rules; when it does, this list is where the field-name half of that policy
lands. The same list is restated in ``docs/LOGGING_POLICY.md`` and the two are
compared by a contract test.
"""

REDACTED: Final[str] = "[redacted]"
"""What replaces a sensitive value. A constant so that tests and documentation
agree with the implementation instead of quoting it."""

MAX_REDACTION_DEPTH: Final[int] = 8
"""How far redaction descends into nested structures before refusing to look.

Beyond this the value is replaced rather than rendered. Refusing to look and
refusing to print are the same decision here: a structure this deep inside a log
field is already a mistake, and a value nobody has inspected must not be
emitted. It also terminates on a self-referential structure, which would
otherwise recurse until the stack ran out.
"""

EVENT_NAME_ALPHABET: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789._"
"""The characters an event name may contain.

Written out rather than compiled as a regular expression because a module-level
:func:`re.compile` is a call, and ``tests/architecture/test_architecture_contract.py``
holds every layer package to performing no work at import.
"""


def is_sensitive(key: str) -> bool:
    """Whether a field with this name must have its value redacted.

    Args:
        key: The field name, in whatever case the caller wrote it.

    Returns:
        ``True`` if any entry of :data:`SENSITIVE_KEY_FRAGMENTS` appears
        anywhere in ``key``, compared case-insensitively.
    """
    lowered = key.lower()
    return any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS)


def redact(fields: Mapping[str, object]) -> dict[str, object]:
    """Return a copy of ``fields`` with every sensitive value replaced.

    Args:
        fields: Field names mapped to their values. Values may be nested
            mappings or sequences; both are descended into, because a secret one
            level down is still a secret.

    Returns:
        A new mapping. Nothing in the result aliases the input, so a caller that
        mutates its own dictionary afterwards cannot change what gets logged.

    The result is a copy rather than a view for exactly that reason: a
    :class:`LogEvent` that shared structure with its caller would be redacted at
    construction and mutable afterwards, which is a guarantee with a hole in it.
    """
    return {key: _redacted_value(key, value, 0) for key, value in fields.items()}


def _redacted_value(key: str, value: object, depth: int) -> object:
    """Redact one field, descending into nested structures.

    Args:
        key: The name this value was filed under. Sensitivity is decided by the
            name, so it has to travel with the value.
        value: The value itself.
        depth: How many levels of nesting have already been entered.

    Returns:
        The value, a redacted stand-in, or a structure of the same shape whose
        sensitive parts have been replaced.
    """
    if is_sensitive(key):
        return REDACTED
    if depth >= MAX_REDACTION_DEPTH:
        return REDACTED
    if isinstance(value, Mapping):
        return {
            nested_key: _redacted_value(str(nested_key), nested_value, depth + 1)
            for nested_key, nested_value in value.items()
        }
    # `str` and `bytes` are Sequences, and descending into one would turn a
    # password into a tuple of its characters — redacted per character, which is
    # to say not redacted at all.
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(_redacted_value(key, item, depth + 1) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class LogEvent:
    """One structured, already-redacted thing that happened.

    Args:
        severity: How bad it is.
        event: A static dotted name such as ``architecture.review.completed``.
            Not a sentence, and never interpolated — see the module docstring
            for why the whole redaction guarantee rests on that.
        correlation_id: Ties this event to the others produced by the same piece
            of work.
        fields: Structured detail, as name/value pairs. Passing a mapping is
            usually easier; :func:`log_event` does the conversion.

    Raises:
        ValidationError: If ``event`` is empty, contains a character outside
            :data:`EVENT_NAME_ALPHABET`, or ``correlation_id`` is empty.

    Construction normalises: fields are redacted and sorted by name, so two
    events carrying the same detail compare equal and serialise identically
    regardless of the order the caller happened to supply. There is no way to
    build an unredacted instance — direct construction runs the same
    ``__post_init__`` that :func:`log_event` does.
    """

    severity: Severity
    event: str
    correlation_id: str
    fields: tuple[tuple[str, object], ...] = ()

    def __post_init__(self) -> None:
        """Validate the names and replace ``fields`` with its canonical form."""
        if not self.event:
            msg = "event name is empty; name the event, for example 'order.submitted'"
            raise ValidationError(msg)
        stray = sorted(set(self.event) - set(EVENT_NAME_ALPHABET))
        if stray:
            msg = (
                f"event name {self.event!r} contains {stray}; "
                f"event names are lowercase dotted identifiers"
            )
            raise ValidationError(msg)
        if not self.correlation_id:
            msg = f"event {self.event!r} has an empty correlation id"
            raise ValidationError(msg)
        redacted = redact(dict(self.fields))
        object.__setattr__(self, "fields", tuple(sorted(redacted.items())))

    def as_mapping(self) -> dict[str, object]:
        """Return the fields as a mapping, for a sink that wants one.

        Returns:
            A new dictionary. Insertion order is the canonical sorted order.
        """
        return dict(self.fields)


def log_event(
    severity: Severity,
    event: str,
    correlation_id: str,
    fields: Mapping[str, object] | None = None,
) -> LogEvent:
    """Build a :class:`LogEvent` from a mapping of fields.

    Args:
        severity: How bad the event is.
        event: A static dotted event name.
        correlation_id: Ties this event to related ones.
        fields: Structured detail, or ``None`` for an event with none.

    Returns:
        A redacted, canonically ordered :class:`LogEvent`.

    Raises:
        ValidationError: As :class:`LogEvent`.
    """
    return LogEvent(
        severity=severity,
        event=event,
        correlation_id=correlation_id,
        fields=tuple((fields or {}).items()),
    )
