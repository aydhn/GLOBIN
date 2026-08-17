"""Spans as values: what one is, and the pure rules a tree of them obeys.

A span is the third telemetry shape. A counter says *how many*; a histogram says
*how long, distributed*; a span says *this particular unit of work took this long
and happened inside that one*. The last is the only one whose meaning depends on
its position in a call structure, which is what makes it a different subject
rather than a metric with extra fields.

**Nothing here is mutable and nothing here is ambient.** There is no current-span
variable, no stack and no registry. Propagation — the question of which span is
open right now — belongs to the object that owns a `ContextVar`, and a domain
module holding ambient state would be the hidden global state
`ENGINEERING_CONTRACT.md` invariant 5 forbids regardless of which module it lives
in.

**A duration is never computed here.** `MonotonicReading.since` already refuses a
reading that went backwards and names both readings when it does, so
:func:`completed` delegates rather than subtracting. That is exactly why `Instant`
defines no subtraction: the only route to a `Duration` is through the type that
refuses the wrong order.

**Identifiers are never minted here.** Generating one reads randomness, which
ADR-0026 places in adapters beside the clock, and
`tests/architecture/test_identifier_discipline.py` enforces it on the real import
graph.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.domain.clock import Duration, Instant, MonotonicReading
from globin.domain.identifiers import HEX_ALPHABET
from globin.domain.telemetry import MetricAttributes
from globin.errors import ValidationError

#: How many hex characters a trace identifier carries.
#:
#: Sixteen bytes, which is W3C `traceparent`'s width. Declared here rather than
#: derived from `uuid`, because the two agree by coincidence rather than by rule.
TRACE_ID_LENGTH: Final[int] = 32

#: How many hex characters a span identifier carries. Eight bytes, per W3C.
SPAN_ID_LENGTH: Final[int] = 16

#: The deepest a span may nest before further nesting is refused.
#:
#: Deep nesting means instrumentation per recursive frame, which is the trace
#: equivalent of unbounded cardinality — a bound rather than a preference.
MAXIMUM_SPAN_DEPTH: Final[int] = 16

#: The most spans one published batch may carry.
#:
#: Bounded so a batch cannot quietly become a data export, which is the argument
#: `MAXIMUM_MEMBER_COUNT` makes about a support bundle.
MAXIMUM_SPANS_PER_BATCH: Final[int] = 256

#: The longest an operation name may be.
MAXIMUM_OPERATION_LENGTH: Final[int] = 60

#: Every character an operation name may contain.
#:
#: Lowercase dotted, the same shape a metric name has, because an operation name
#: is read beside one and a second convention would be one more thing to remember.
OPERATION_ALPHABET: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789._"

#: The identifier a root span carries in place of a parent.
NO_PARENT: Final[str] = ""


class SpanKind(StrEnum):
    """What sort of work a span describes.

    Two members, closed. GLOBIN makes no inbound calls, so `SERVER` would be a
    member nothing could ever produce. A third is a visible edit by the phase that
    needs it — `IdentifierKind`'s argument.
    """

    INTERNAL = "internal"
    CLIENT = "client"


class SpanStatus(StrEnum):
    """How a span ended.

    Three members matching OpenTelemetry's exactly, so an exporter needs no
    mapping table. A mapping between two enumerations is a thing that drifts, and
    `Severity` borrowed `logging`'s numbers for the same reason.
    """

    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


def operation_problems(name: str) -> tuple[str, ...]:
    """Judge whether a string is a canonical operation name.

    Args:
        name: The candidate.

    Returns:
        One sentence per reason it is not, empty when it is canonical.

    The classic trace failure is an operation name built from a value — a request
    path, an order identifier — which is the same disease as an unbounded metric
    attribute and is refused for the same reason.
    """
    problems: list[str] = []
    if not name:
        return ("the operation name is empty",)
    if len(name) > MAXIMUM_OPERATION_LENGTH:
        problems.append(f"the operation name {name!r} is longer than {MAXIMUM_OPERATION_LENGTH}")
    outside = sorted({character for character in name if character not in OPERATION_ALPHABET})
    if outside:
        problems.append(
            f"the operation name {name!r} contains {''.join(outside)!r}, "
            f"which is outside the operation alphabet"
        )
    if name.startswith(".") or name.endswith("."):
        problems.append(f"the operation name {name!r} begins or ends with a separator")
    return tuple(problems)


def _identifier_problems(value: str, *, width: int, named: str) -> list[str]:
    """Judge one hex identifier.

    Args:
        value: The candidate.
        width: How many characters it must have.
        named: What to call it in a message.

    Returns:
        One sentence per problem.
    """
    problems: list[str] = []
    if len(value) != width:
        problems.append(f"the {named} {value!r} is not {width} characters")
    if any(character not in HEX_ALPHABET for character in value):
        problems.append(f"the {named} {value!r} is not lowercase hexadecimal")
    elif value and set(value) == {"0"}:
        problems.append(f"the {named} is all zeroes, which W3C reserves as invalid")
    return problems


@dataclass(frozen=True, slots=True)
class SpanContext:
    """Which trace a span belongs to, and what it hangs off.

    Args:
        trace_id: The trace, thirty-two lowercase hex characters.
        span_id: This span, sixteen lowercase hex characters.
        parent_id: The enclosing span, or empty for a root.
        depth: How many spans enclose this one.

    Raises:
        ValidationError: If either identifier is malformed or all zeroes, if the
            parent is neither empty nor well formed, if a span is its own parent,
            or if the depth is out of range.

    **All-zero is refused explicitly**, because it is exactly what a half-written
    propagator emits: a value that looks like an identifier and joins every trace
    to every other. W3C reserves it as invalid for the same reason.
    """

    trace_id: str
    span_id: str
    parent_id: str = NO_PARENT
    depth: int = 0

    def __post_init__(self) -> None:
        """Refuse a context that could not describe a real position in a tree."""
        problems = _identifier_problems(self.trace_id, width=TRACE_ID_LENGTH, named="trace id")
        problems.extend(_identifier_problems(self.span_id, width=SPAN_ID_LENGTH, named="span id"))
        if self.parent_id != NO_PARENT:
            problems.extend(
                _identifier_problems(self.parent_id, width=SPAN_ID_LENGTH, named="parent id")
            )
        if self.parent_id == self.span_id:
            problems.append("a span cannot be its own parent")
        if not 0 <= self.depth <= MAXIMUM_SPAN_DEPTH:
            problems.append(f"the depth {self.depth} is outside 0..{MAXIMUM_SPAN_DEPTH}")
        if self.depth == 0 and self.parent_id != NO_PARENT:
            problems.append("a root span carries a parent")
        if self.depth > 0 and self.parent_id == NO_PARENT:
            problems.append("a nested span carries no parent")
        if problems:
            raise ValidationError("; ".join(problems))

    @property
    def is_root(self) -> bool:
        """Whether nothing encloses this span.

        Returns:
            Whether it has no parent.
        """
        return self.parent_id == NO_PARENT


@dataclass(frozen=True, slots=True)
class OpenSpan:
    """A span that has begun and not yet ended.

    Args:
        context: Where it sits in the trace.
        name: What it is doing.
        kind: What sort of work it is.
        started_at: The wall moment, for a human reading a log beside it.
        began: The monotonic origin its duration is measured from.

    Raises:
        ValidationError: If the operation name is not canonical.

    Two clock readings rather than one because they answer different questions: a
    person finds a span by its wall time, and only a monotonic reading can be
    subtracted. The completed span keeps the first and drops the second, since a
    `MonotonicReading` has no wire form at all and `serialization.py` asserts that
    absence stays.
    """

    context: SpanContext
    name: str
    kind: SpanKind
    started_at: Instant
    began: MonotonicReading

    def __post_init__(self) -> None:
        """Refuse an operation name that could not be compared across runs."""
        problems = operation_problems(self.name)
        if problems:
            raise ValidationError("; ".join(problems))


@dataclass(frozen=True, slots=True)
class Span:
    """A span that has ended.

    Args:
        context: Where it sat in the trace.
        name: What it was doing.
        kind: What sort of work it was.
        status: How it ended.
        started_at: The wall moment it began.
        took: How long it took, from monotonic readings.
        attributes: Its bounded dimensions. **Required rather than defaulted**,
            because `MetricAttributes()` in a class body is a call and a layer
            package performs none at import -- the trap `GlobinConfig.logging`
            already documents about itself.
        fault: The exception *type* that ended it, empty when none did.

    Raises:
        ValidationError: If the name is not canonical, or a fault is recorded
            without an error status.

    **`fault` is a type name, never a message.** An exception message is arbitrary
    text that may contain a path, a credential or an entire request body, and a
    span travels. The type is bounded by the classes that exist, which makes it a
    dimension rather than a payload — the same distinction `attribute_problems`
    draws for a metric.
    """

    context: SpanContext
    name: str
    kind: SpanKind
    status: SpanStatus
    started_at: Instant
    took: Duration
    attributes: MetricAttributes
    fault: str = ""

    def __post_init__(self) -> None:
        """Refuse a span whose ending contradicts itself."""
        problems = list(operation_problems(self.name))
        if self.fault and self.status is not SpanStatus.ERROR:
            problems.append("a fault is recorded without an error status")
        if self.fault and not self.fault.isidentifier():
            problems.append(f"the fault {self.fault!r} is not a type name")
        if problems:
            raise ValidationError("; ".join(problems))

    def document(self) -> dict[str, object]:
        """This span, ready to publish.

        Returns:
            A JSON-safe mapping with no float anywhere.
        """
        return {
            "trace_id": self.context.trace_id,
            "span_id": self.context.span_id,
            "parent_id": self.context.parent_id,
            "depth": self.context.depth,
            "name": self.name,
            "kind": self.kind.value,
            "status": self.status.value,
            "started_at": self.started_at.epoch_millis,
            "took_nanoseconds": self.took.nanoseconds,
            "attributes": self.attributes.series_key(),
            "fault": self.fault,
        }


def completed(
    open_span: OpenSpan,
    *,
    at: MonotonicReading,
    status: SpanStatus,
    attributes: MetricAttributes | None = None,
    fault: str = "",
) -> Span:
    """End a span.

    Args:
        open_span: The span that began.
        at: The monotonic reading it ended at.
        status: How it ended.
        attributes: Its bounded dimensions, defaulting to none at all.
        fault: The exception type that ended it, if one did.

    Returns:
        The completed span.

    Raises:
        ValidationError: If the ending reading is earlier than the beginning, or
            the resulting span contradicts itself.

    The duration is `at.since(open_span.began)` and nothing else. That call already
    refuses a reading that went backwards and names both readings when it does, so
    there is no arithmetic here to get wrong.
    """
    return Span(
        context=open_span.context,
        name=open_span.name,
        kind=open_span.kind,
        status=status,
        started_at=open_span.started_at,
        took=at.since(open_span.began),
        attributes=MetricAttributes() if attributes is None else attributes,
        fault=fault,
    )


def child_context(parent: SpanContext, span_id: str) -> SpanContext:
    """The context one span inside another carries.

    Args:
        parent: The enclosing span's context.
        span_id: The new span's identifier.

    Returns:
        A context in the same trace, one level deeper.

    Raises:
        ValidationError: If the resulting context would be invalid, which includes
            nesting past :data:`MAXIMUM_SPAN_DEPTH`.
    """
    return SpanContext(
        trace_id=parent.trace_id,
        span_id=span_id,
        parent_id=parent.span_id,
        depth=parent.depth + 1,
    )


@dataclass(frozen=True, slots=True)
class SpanBatch:
    """Spans of one trace, ready to publish.

    Args:
        trace_id: The trace they all belong to.
        spans: The spans, in canonical order.

    Raises:
        ValidationError: If a span belongs to another trace, if an identifier
            repeats, if the batch is oversized, or if the order is not canonical.

    **A repeated span identifier is refused**, which is the strongest guarantee
    available against a double-close without holding mutable state: an
    `OpenSpan` is a value, so completing it twice yields two equal spans and
    corrupts nothing, but a *published* batch containing both is a lie about how
    many things happened. `BundleManifest` refuses a repeated member for the same
    reason.

    Canonical order is `(started_at, span_id)`, so two spans opened in the same
    millisecond still order deterministically — the tie-break
    `HeartbeatSnapshot.quietest` uses, and for the same published-digest reason.
    """

    trace_id: str
    spans: tuple[Span, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a batch that could not have come from one trace."""
        problems = _identifier_problems(self.trace_id, width=TRACE_ID_LENGTH, named="trace id")
        if len(self.spans) > MAXIMUM_SPANS_PER_BATCH:
            problems.append(f"a batch of {len(self.spans)} exceeds {MAXIMUM_SPANS_PER_BATCH}")
        identifiers = [span.context.span_id for span in self.spans]
        if len(set(identifiers)) != len(identifiers):
            problems.append("a span id appears twice, which a double close would produce")
        for span in self.spans:
            if span.context.trace_id != self.trace_id:
                problems.append(f"the span {span.context.span_id} belongs to another trace")
        ordering = [(span.started_at.epoch_millis, span.context.span_id) for span in self.spans]
        if ordering != sorted(ordering):
            problems.append("the spans are not in canonical order")
        if problems:
            raise ValidationError("; ".join(problems))

    def roots(self) -> tuple[Span, ...]:
        """Every span nothing in this batch encloses.

        Returns:
            The roots, in canonical order.
        """
        return tuple(span for span in self.spans if span.context.is_root)

    def children_of(self, span: Span) -> tuple[Span, ...]:
        """Every span directly inside one.

        Args:
            span: The enclosing span.

        Returns:
            Its children, in canonical order.
        """
        return tuple(
            candidate
            for candidate in self.spans
            if candidate.context.parent_id == span.context.span_id
        )

    def orphans(self) -> tuple[Span, ...]:
        """Every span whose parent is not in this batch.

        Returns:
            The orphans, in canonical order.

        **Reported rather than refused.** A span whose parent is still open, or
        was published in an earlier batch, is entirely ordinary; refusing would
        raise inside a recorder for a situation that is not an error.
        """
        present = {span.context.span_id for span in self.spans}
        return tuple(
            span
            for span in self.spans
            if not span.context.is_root and span.context.parent_id not in present
        )

    def document(self) -> dict[str, object]:
        """This batch, ready to publish.

        Returns:
            A JSON-safe mapping.
        """
        return {
            "trace_id": self.trace_id,
            "spans": [span.document() for span in self.spans],
        }
