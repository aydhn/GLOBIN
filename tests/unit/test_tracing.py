"""Spans as values, and the rules a published batch obeys.

Which span is open right now is `test_span_scope.py`'s subject. This owns what a
span *is* — the identifiers it may carry, the duration it delegates rather than
computes, and the refusals that keep a batch from lying about how many things
happened.
"""

from datetime import UTC, datetime

import pytest

from globin.domain.clock import Instant, MonotonicReading
from globin.domain.telemetry import MetricAttributes
from globin.domain.tracing import (
    MAXIMUM_OPERATION_LENGTH,
    MAXIMUM_SPAN_DEPTH,
    MAXIMUM_SPANS_PER_BATCH,
    NO_PARENT,
    OpenSpan,
    Span,
    SpanBatch,
    SpanContext,
    SpanKind,
    SpanStatus,
    child_context,
    completed,
    operation_problems,
)
from globin.errors import ValidationError

TRACE = "a" * 32
"""A well-formed trace identifier."""

SPAN = "b" * 16
"""A well-formed span identifier."""

MOMENT = Instant(datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC))
"""A millisecond-aligned wall reading."""


def opened(**overrides: object) -> OpenSpan:
    """A span that has begun, with fields replaced.

    Args:
        overrides: Fields to replace.

    Returns:
        The open span.
    """
    fields: dict[str, object] = {
        "context": SpanContext(trace_id=TRACE, span_id=SPAN),
        "name": "bootstrap.preflight",
        "kind": SpanKind.INTERNAL,
        "started_at": MOMENT,
        "began": MonotonicReading(1_000),
    }
    fields.update(overrides)
    return OpenSpan(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Identifiers: the all-zero case is the one that matters
# ---------------------------------------------------------------------------


def test_a_well_formed_context_is_a_root() -> None:
    """The positive case, so the refusals below mean something."""
    context = SpanContext(trace_id=TRACE, span_id=SPAN)
    assert context.is_root
    assert context.parent_id == NO_PARENT


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        pytest.param({"trace_id": "a" * 31}, "not 32 characters", id="short-trace"),
        pytest.param({"span_id": "b" * 15}, "not 16 characters", id="short-span"),
        pytest.param({"trace_id": "A" * 32}, "not lowercase", id="uppercase-trace"),
        pytest.param({"trace_id": "z" * 32}, "not lowercase", id="non-hex-trace"),
        pytest.param({"trace_id": "0" * 32}, "all zeroes", id="zero-trace"),
        pytest.param({"span_id": "0" * 16}, "all zeroes", id="zero-span"),
        pytest.param({"parent_id": SPAN, "depth": 1}, "its own parent", id="self-parent"),
        pytest.param({"depth": MAXIMUM_SPAN_DEPTH + 1}, "outside 0", id="too-deep"),
        pytest.param({"parent_id": "c" * 16}, "root span carries a parent", id="root-with-parent"),
        pytest.param({"depth": 1}, "nested span carries no parent", id="nested-without-parent"),
    ],
)
def test_a_malformed_context_is_refused(fields: dict[str, object], expected: str) -> None:
    """All-zero is refused explicitly, and it is the case worth naming.

    It is exactly what a half-written propagator emits — a value that looks like
    an identifier and joins every trace to every other — which is why W3C reserves
    it as invalid rather than merely discouraging it.
    """
    base: dict[str, object] = {"trace_id": TRACE, "span_id": SPAN}
    base.update(fields)
    with pytest.raises(ValidationError, match=expected):
        SpanContext(**base)  # type: ignore[arg-type]


def test_a_child_nests_one_level_under_its_parent() -> None:
    """The relation a whole trace tree is built from."""
    parent = SpanContext(trace_id=TRACE, span_id=SPAN)
    child = child_context(parent, "c" * 16)
    assert child.trace_id == TRACE
    assert child.parent_id == SPAN
    assert child.depth == 1
    assert not child.is_root


def test_nesting_past_the_bound_is_refused() -> None:
    """Deep nesting is instrumentation per recursive frame.

    That is the trace equivalent of unbounded cardinality, so it is a bound rather
    than a preference.
    """
    deep = SpanContext(trace_id=TRACE, span_id=SPAN, parent_id="c" * 16, depth=MAXIMUM_SPAN_DEPTH)
    with pytest.raises(ValidationError, match="outside 0"):
        child_context(deep, "d" * 16)


# ---------------------------------------------------------------------------
# Operation names: the classic trace failure
# ---------------------------------------------------------------------------


def test_a_canonical_operation_name_has_no_problems() -> None:
    """Lowercase dotted, the same shape a metric name has."""
    assert operation_problems("bootstrap.preflight") == ()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        pytest.param("", "empty", id="empty"),
        pytest.param("GET /orders/17", "outside the operation", id="built-from-a-value"),
        pytest.param("Bootstrap", "outside the operation", id="uppercase"),
        pytest.param("a" * (MAXIMUM_OPERATION_LENGTH + 1), "longer than", id="too-long"),
        pytest.param(".leading", "begins or ends", id="leading-dot"),
        pytest.param("trailing.", "begins or ends", id="trailing-dot"),
    ],
)
def test_a_name_built_from_a_value_is_refused(name: str, expected: str) -> None:
    """An operation name built from a request path is unbounded cardinality.

    It is the same disease as an unbounded metric attribute, and it is refused for
    the same reason rather than tolerated because traces feel different.
    """
    problems = operation_problems(name)
    assert problems
    assert any(expected in problem for problem in problems)


# ---------------------------------------------------------------------------
# Completion: the duration is delegated, not computed
# ---------------------------------------------------------------------------


def test_a_completed_span_takes_its_duration_from_the_monotonic_readings() -> None:
    """No arithmetic here, so there is none to get wrong."""
    span = completed(opened(), at=MonotonicReading(5_000), status=SpanStatus.OK)
    assert span.took.nanoseconds == 4_000
    assert span.started_at == MOMENT


def test_a_reading_that_went_backwards_is_refused_by_the_clock() -> None:
    """`Instant` defines no subtraction precisely so this path exists.

    The only route to a `Duration` is through the type that refuses the wrong
    order, so nothing here has to check it.
    """
    with pytest.raises(ValidationError):
        completed(opened(), at=MonotonicReading(500), status=SpanStatus.OK)


def test_a_fault_records_the_type_and_never_a_message() -> None:
    """A message is arbitrary text that may carry a path or a credential.

    A span travels, so it carries the exception *type* — bounded by the classes
    that exist, which makes it a dimension rather than a payload.
    """
    span = completed(
        opened(), at=MonotonicReading(2_000), status=SpanStatus.ERROR, fault="KeyError"
    )
    assert span.fault == "KeyError"


def test_a_fault_without_an_error_status_is_refused() -> None:
    """A span that failed and says it succeeded is worse than no span."""
    with pytest.raises(ValidationError, match="without an error status"):
        completed(opened(), at=MonotonicReading(2_000), status=SpanStatus.OK, fault="KeyError")


def test_a_fault_that_is_not_a_type_name_is_refused() -> None:
    """The guard that stops a message being smuggled through the fault field."""
    with pytest.raises(ValidationError, match="not a type name"):
        completed(
            opened(),
            at=MonotonicReading(2_000),
            status=SpanStatus.ERROR,
            fault="KeyError: /home/someone/secret",
        )


def test_a_completed_span_publishes_integers_and_no_reading() -> None:
    """A monotonic reading has no wire form, so it must not reach a document."""
    document = completed(opened(), at=MonotonicReading(3_000), status=SpanStatus.OK).document()
    assert document["took_nanoseconds"] == 2_000
    assert isinstance(document["started_at"], int)
    assert "began" not in document


# ---------------------------------------------------------------------------
# Batches: the strongest available guarantee against a double close
# ---------------------------------------------------------------------------


def _span(span_id: str, *, millis: int = 0, parent: str = NO_PARENT) -> Span:
    """One completed span, for batch assembly.

    Args:
        span_id: Its identifier.
        millis: How far after the base moment it started.
        parent: Its parent, or empty for a root.

    Returns:
        The span.
    """
    depth = 0 if parent == NO_PARENT else 1
    context = SpanContext(trace_id=TRACE, span_id=span_id, parent_id=parent, depth=depth)
    started = Instant(datetime(2026, 8, 17, 12, 0, 0, millis * 1000, tzinfo=UTC))
    return Span(
        context=context,
        name="bootstrap.preflight",
        kind=SpanKind.INTERNAL,
        status=SpanStatus.OK,
        started_at=started,
        took=MonotonicReading(2_000).since(MonotonicReading(1_000)),
        attributes=MetricAttributes(),
    )


def test_a_batch_reports_its_roots_and_children() -> None:
    """The tree, read back from a flat list."""
    root = _span("a" * 16)
    child = _span("c" * 16, millis=1, parent="a" * 16)
    batch = SpanBatch(trace_id=TRACE, spans=(root, child))
    assert batch.roots() == (root,)
    assert batch.children_of(root) == (child,)


def test_an_orphan_is_reported_rather_than_refused() -> None:
    """A span whose parent is still open, or shipped earlier, is ordinary.

    Refusing would raise inside a recorder for a situation that is not an error.
    """
    orphan = _span("c" * 16, parent="f" * 16)
    batch = SpanBatch(trace_id=TRACE, spans=(orphan,))
    assert batch.orphans() == (orphan,)


def test_a_repeated_span_id_is_refused() -> None:
    """The strongest guarantee against a double close without mutable state.

    An `OpenSpan` is a value, so completing it twice yields two equal spans and
    corrupts nothing. A *published* batch containing both is a lie about how many
    things happened, and that is what this refuses — `BundleManifest`'s rule about
    a repeated member.
    """
    span = _span("a" * 16)
    with pytest.raises(ValidationError, match="appears twice"):
        SpanBatch(trace_id=TRACE, spans=(span, span))


def test_a_span_from_another_trace_is_refused() -> None:
    """A batch names one trace, so every span in it must belong to that trace."""
    stray = Span(
        context=SpanContext(trace_id="f" * 32, span_id="a" * 16),
        name="bootstrap.preflight",
        kind=SpanKind.INTERNAL,
        status=SpanStatus.OK,
        started_at=MOMENT,
        took=MonotonicReading(2_000).since(MonotonicReading(1_000)),
        attributes=MetricAttributes(),
    )
    with pytest.raises(ValidationError, match="another trace"):
        SpanBatch(trace_id=TRACE, spans=(stray,))


def test_spans_out_of_canonical_order_are_refused() -> None:
    """Order is enforced rather than repaired, so a published digest means something.

    The tie-break is the span id, so two spans opened in the same millisecond
    still order deterministically.
    """
    first = _span("a" * 16, millis=0)
    second = _span("b" * 16, millis=5)
    assert len(SpanBatch(trace_id=TRACE, spans=(first, second)).spans) == 2
    with pytest.raises(ValidationError, match="canonical order"):
        SpanBatch(trace_id=TRACE, spans=(second, first))


def test_an_oversized_batch_is_refused() -> None:
    """Bounded so a batch cannot quietly become a data export."""
    spans = tuple(
        _span(f"{index:016x}", millis=index) for index in range(1, MAXIMUM_SPANS_PER_BATCH + 2)
    )
    with pytest.raises(ValidationError, match="exceeds"):
        SpanBatch(trace_id=TRACE, spans=spans)


def test_the_two_span_kinds_are_closed() -> None:
    """GLOBIN makes no inbound calls, so `SERVER` would name nothing."""
    assert set(SpanKind) == {SpanKind.INTERNAL, SpanKind.CLIENT}


def test_the_status_vocabulary_matches_opentelemetry() -> None:
    """Borrowed exactly, so an exporter needs no mapping table to drift."""
    assert {status.value for status in SpanStatus} == {"unset", "ok", "error"}
