"""Writing log records out: the only place logging touches the outside world.

This module holds everything the core deliberately does not — the clock, the
random source, the serialiser and the stream. ``dependency-rules.toml`` lists
``logging``, ``io`` and ``sys`` among the I/O-capable modules, so the inner
layers could not do any of it even if that were desirable.

**Records are JSON Lines**: one object per line, so that a log file is readable
by eye, by ``Select-String``, and by anything that parses JSON, without a format
string to keep in sync. Fields sit under a ``fields`` key rather than being
merged into the envelope, so a field named ``event`` cannot displace the event
name.

**Non-ASCII is escaped.** ``ensure_ascii=True`` costs readability for Turkish or
symbol text and buys the guarantee that a record can be written to a stream
whatever encoding it happens to have. GLOBIN's host is Windows, where a console
stream is frequently not UTF-8, and a logger that raises
:exc:`UnicodeEncodeError` on a symbol name is a logger that fails exactly when
something interesting is happening.

**The standard library's :mod:`logging` is not used.** GLOBIN has no runtime
dependencies yet, so nothing else in the process emits records, and routing
through :mod:`logging` would buy interoperability nobody is asking for at the
price of module-level handler state — the global configuration
``ENGINEERING_CONTRACT.md`` invariant 5 exists to keep out. When a dependency
first emits standard-library records, a second :class:`LogSink` implementation
bridges them; the port is what makes that an addition rather than a rewrite.
"""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, TextIO
from uuid import uuid4

from globin.domain.observability import LogEvent, Severity
from globin.ports.clock import Clock
from globin.ports.observability import LogSink

ENVELOPE_KEYS: Final[tuple[str, ...]] = ("timestamp", "severity", "event", "correlation_id")
"""The keys every record carries, in the order they are written.

Named here so that ``tests/contract/test_observability_contract.py`` can hold the
documented record shape and the emitted one to each other.
"""


def new_correlation_id() -> str:
    """Return a fresh correlation id.

    Returns:
        A 32-character hexadecimal string.

    Generating one reads a source of randomness, which is ambient
    nondeterminism, so it lives out here with the clock rather than in the
    domain. A test that needs a stable id passes its own.
    """
    return uuid4().hex


def _coerce(value: object) -> object:
    """Render a value as something :func:`json.dumps` will accept.

    Args:
        value: A field value, already redacted.

    Returns:
        The value unchanged when JSON can represent it, and :func:`repr` of it
        otherwise.

    This is total: it never raises, and it never refuses. That is a decision
    with a cost, and the cost is that a value with an unhelpful ``repr`` gets
    logged unhelpfully rather than loudly. It is taken because the alternative
    is worse — a logging call that can raise is a diagnostic that can stop the
    work it was describing, and Phases 081-096 will be logging from an order
    loop where that trade is not close.

    Non-finite floats are rendered as text rather than passed through, because
    ``NaN`` and ``Infinity`` are what :mod:`json` emits for them and neither is
    valid JSON for anything that later reads the file.

    Recursion terminates without a depth guard of its own: it walks a structure
    that :func:`globin.domain.observability.redact` has already copied and
    bounded, so nothing cyclic or unboundedly deep survives to reach here.
    """
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, Mapping):
        return {str(key): _coerce(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_coerce(item) for item in value]
    return repr(value)


def as_record(event: LogEvent, timestamp: str) -> dict[str, object]:
    """Build the mapping that gets serialised for one event.

    Args:
        event: The record, already redacted.
        timestamp: When it happened, as an ISO-8601 string.

    Returns:
        A mapping whose first four keys are :data:`ENVELOPE_KEYS`, followed by
        ``fields``. ``fields`` is always present, even when empty, so anything
        reading the output never needs a conditional.

    Separated from the writing so that the record shape can be asserted without
    a stream, and so a future sink emitting some other format has the envelope
    already built.
    """
    return {
        "timestamp": timestamp,
        "severity": event.severity.name,
        "event": event.event,
        "correlation_id": event.correlation_id,
        "fields": {key: _coerce(value) for key, value in event.fields},
    }


@dataclass(frozen=True, slots=True)
class StreamLogSink:
    """Writes each record to a text stream as one line of JSON.

    Args:
        stream: Where records go. The composition root passes
            :data:`sys.stderr`; a test passes a :class:`io.StringIO`.
        clock: Where the timestamp comes from. The composition root passes
            :class:`globin.adapters.clock.SystemClock`; a test passes a fixed
            clock and can then assert the exact timestamp it wrote.

    **The clock has no default, and cannot have one.** ``clock: Clock =
    SystemClock()`` and ``field(default_factory=SystemClock)`` are both calls in
    a class body, and ``tests/architecture/test_architecture_contract.py`` holds
    every layer package to performing no work at import. The architecture rule
    and the design rule agree here: a default clock would be ambient time
    wearing a keyword argument.

    **A write failure propagates.** The stream is not wrapped in a try/except,
    so a closed pipe or a full disk surfaces at the call site rather than
    disappearing — ``ENGINEERING_CONTRACT.md`` invariant 23 forbids swallowing
    an exception silently, and a sink that quietly discards records is a sink
    that is indistinguishable from a working one right up until you need the
    log.

    That is the correct behaviour for *this* sink, not for every sink. When
    Phases 081-096 introduce an order loop that must survive a broken log
    stream, the answer is a decorating sink that degrades deliberately and
    reports that it did — which is an addition behind the same port, not a
    change here. Building it now would be guessing at a failure policy for a
    caller that does not exist.
    """

    stream: TextIO
    clock: Clock

    def emit(self, event: LogEvent) -> None:
        """Write one record, followed by a newline.

        Args:
            event: The record, already redacted.

        The stream is not flushed. Flushing per record costs a system call on a
        path that a trading loop may take often, and the streams GLOBIN writes
        to are line-buffered or flushed at exit.

        The clock is read **per record**, not once when the sink was built. A
        cached reading would stamp every record in a run with the same moment,
        which is worse than no timestamp because it looks like one.
        """
        record = as_record(event, str(self.clock.now()))
        self.stream.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")


@dataclass(frozen=True, slots=True)
class ThresholdLogSink:
    """Passes records at or above a minimum severity to another sink.

    Args:
        inner: Where records that clear the threshold go.
        minimum: The lowest severity worth keeping.

    Filtering is a decorator rather than a field on :class:`StreamLogSink`
    because ``docs/LOGGING_POLICY.md`` makes it a sink's concern: two sinks may
    legitimately want different thresholds — a file at ``DEBUG`` beside a console
    at ``WARNING`` — and a threshold living inside a writing sink would have to be
    reimplemented by every sink written afterwards. That is the argument ADR-0025
    used to reject sink-side redaction, and it applies unchanged here.

    Nor does it live in :class:`~globin.application.observability.Logger`, which
    would be faster because the :class:`~globin.domain.observability.LogEvent`
    would never be built. A logger that filtered would decide for every sink it
    writes to, and the sentence in ``LOGGING_POLICY.md`` that hands this job to
    Phase 007 is the same sentence that calls it a sink's concern.

    **Dropping a record is deliberate data loss.**
    ``ENGINEERING_CONTRACT.md`` invariant 22 permits that only as an explicit
    decision, and it is explicit here: the default configured threshold is
    :attr:`~globin.domain.observability.Severity.DEBUG`, the lowest member, so
    nothing is discarded until an operator asks for it in writing.
    """

    inner: LogSink
    minimum: Severity

    def emit(self, event: LogEvent) -> None:
        """Forward the record if it is severe enough to keep.

        Args:
            event: The record, already redacted.

        The comparison is why :class:`~globin.domain.observability.Severity` is
        an :class:`~enum.IntEnum` borrowing the standard library's numbers — a
        promise its docstring has carried since Phase 006, that thresholds would
        be comparisons rather than a lookup table.
        """
        if event.severity >= self.minimum:
            self.inner.emit(event)
