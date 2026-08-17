"""Which span is open right now, and how that survives a context copy.

**No event loop runs in this file, and that is deliberate rather than a
limitation.** On Windows the default loop is `ProactorEventLoop`, whose self-pipe
is built from `socket.socketpair()`, whose Windows fallback calls `connect()` —
which `tests/conftest.py::block_network` turns into a failure. The `network`
marker's own declaration says it is never permitted below the external level, so
it is not an escape hatch either.

The mechanism a task actually uses is `contextvars.copy_context()`:
`asyncio.Task.__init__` copies the current context and runs every step of the
coroutine inside the copy. Testing against `copy_context()` therefore tests the
identical mechanism with no loop, no socket and no marker — the same move the
watchdog made when it proved a whole state machine with a fake clock and no
threads at all.
"""

import contextvars
import itertools
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from globin.application.tracing import SpanScope, span_scope
from globin.domain.clock import Instant, MonotonicReading
from globin.domain.tracing import MAXIMUM_SPAN_DEPTH, SpanContext, SpanKind, SpanStatus
from globin.errors import ValidationError

TRACE = "a" * 32
"""A well-formed trace identifier."""

MOMENT = Instant(datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC))
"""A millisecond-aligned wall reading; the clock never moves in these tests."""


def _identifiers() -> Callable[[], str]:
    """A deterministic span-id minter.

    Returns:
        A callable handing out `0000...0001`, `...0002` and so on.

    Deterministic rather than random, so a failure names the same span twice.
    """
    counter = itertools.count(1)
    return lambda: f"{next(counter):016x}"


@pytest.fixture
def scope() -> SpanScope:
    """A scope with its own context variable and a hand-cranked clock.

    Returns:
        The scope.
    """
    ticks = itertools.count(1_000, 500)
    return span_scope(
        new_span_id=_identifiers(),
        clock=lambda: MOMENT,
        monotonic=lambda: MonotonicReading(next(ticks)),
    )


# ---------------------------------------------------------------------------
# Nesting, and the token that unwinds it
# ---------------------------------------------------------------------------


def test_nothing_is_open_before_anything_opens(scope: SpanScope) -> None:
    """The variable's default, which is what makes a stale value impossible."""
    assert scope.active() is None


def test_a_span_nests_under_whatever_is_open(scope: SpanScope) -> None:
    """The parent link is discovered rather than threaded through every frame.

    This is the one thing a `ContextVar` buys that a parameter cannot, and it is
    the whole justification for using one.
    """
    with scope.span("outer", trace_id=TRACE) as outer:
        assert outer is not None
        assert outer.context.is_root
        with scope.span("inner") as inner:
            assert inner is not None
            assert inner.context.parent_id == outer.context.span_id
            assert inner.context.depth == 1


def test_the_variable_is_restored_when_a_block_ends(scope: SpanScope) -> None:
    """Token reset in `finally`, so no stale span can leak into later work."""
    with scope.span("outer", trace_id=TRACE):
        assert scope.active() is not None
    assert scope.active() is None


def test_the_variable_is_restored_when_a_block_raises(scope: SpanScope) -> None:
    """The path that actually leaks in implementations that get this wrong."""
    planted = "planted"
    with pytest.raises(KeyError), scope.span("outer", trace_id=TRACE):
        raise KeyError(planted)
    assert scope.active() is None


def test_sibling_spans_do_not_nest(scope: SpanScope) -> None:
    """Two spans opened one after the other are both roots of their own."""
    with scope.span("first", trace_id=TRACE) as first:
        assert first is not None
    with scope.span("second", trace_id=TRACE) as second:
        assert second is not None
        assert second.context.is_root


# ---------------------------------------------------------------------------
# Async semantics, proved against the mechanism a task uses
# ---------------------------------------------------------------------------


def test_a_copied_context_sees_the_span_open_when_it_was_copied(scope: SpanScope) -> None:
    """`asyncio.Task.__init__` copies the context, so a child sees the parent span.

    This is the exact guarantee a task inherits, tested through the exact call a
    task makes — with no loop, no socket and no marker.
    """
    with scope.span("outer", trace_id=TRACE) as outer:
        assert outer is not None
        copied = contextvars.copy_context()
    assert copied.run(scope.active) is not None
    assert copied.run(scope.active) == outer.context


def test_a_child_context_cannot_write_back_to_its_parent(scope: SpanScope) -> None:
    """A task's `set` lands in its own copy, so concurrent tasks are isolated.

    That isolation is free rather than engineered, and this asserts it rather than
    trusting it.
    """
    with scope.span("outer", trace_id=TRACE) as outer:
        assert outer is not None
        copied = contextvars.copy_context()

        def _inside() -> None:
            with scope.span("inner"):
                pass

        copied.run(_inside)
        assert scope.active() == outer.context


def test_two_copies_are_isolated_from_each_other(scope: SpanScope) -> None:
    """Concurrent tasks must not see each other's spans."""
    with scope.span("outer", trace_id=TRACE):
        first = contextvars.copy_context()
        second = contextvars.copy_context()

    def _open(name: str) -> SpanContext | None:
        with scope.span(name):
            return scope.active()

    one = first.run(_open, "one")
    two = second.run(_open, "two")
    assert one is not None
    assert two is not None
    assert one.span_id != two.span_id


def test_a_context_copied_before_a_span_never_sees_it(scope: SpanScope) -> None:
    """The documented trap, asserted so it is a known limit rather than a surprise.

    A task created *before* a span opens and awaited *inside* it inherits the
    context as it was at creation — so it sees no parent. The answer is to pass
    `parent=` explicitly, which is what `child_of` exists to name.
    """
    copied = contextvars.copy_context()
    with scope.span("outer", trace_id=TRACE):
        assert copied.run(scope.active) is None


# ---------------------------------------------------------------------------
# Explicit parenting, which crosses every boundary the variable does not
# ---------------------------------------------------------------------------


def test_an_explicit_parent_overrides_what_is_open(scope: SpanScope) -> None:
    """The mechanism for a thread or a task boundary.

    A new thread inherits no context at all, so a worker is handed the
    `SpanContext` as a value — ADR-0026's own prescription, which is the same
    mechanism rather than a new one.
    """
    supplied = SpanContext(trace_id=TRACE, span_id="f" * 16)
    with scope.span("outer", trace_id=TRACE), scope.span("inner", parent=supplied) as inner:
        assert inner is not None
        assert inner.context.parent_id == "f" * 16


# ---------------------------------------------------------------------------
# Bounds and refusals
# ---------------------------------------------------------------------------


def test_a_root_span_without_a_trace_is_refused(scope: SpanScope) -> None:
    """A root with no trace would produce spans nothing could join."""
    with pytest.raises(ValidationError, match="without a trace id"), scope.span("orphan"):
        pass


def test_nesting_past_the_bound_yields_nothing_and_still_runs() -> None:
    """Runaway recursion must not raise, and must not record either.

    The block still executes — instrumentation refusing to record is not a reason
    for the work to stop.
    """
    shallow = span_scope(
        new_span_id=_identifiers(),
        clock=lambda: MOMENT,
        monotonic=lambda: MonotonicReading(1_000),
        maximum_depth=1,
    )
    ran = False
    with (
        shallow.span("outer", trace_id=TRACE),
        shallow.span("middle") as middle,
        shallow.span("inner") as inner,
    ):
        ran = True
        assert middle is not None
        assert middle.context.depth == 1
        assert inner is None
    assert ran
    assert [span.name for span in shallow.drain()] == ["middle", "outer"]


def test_the_declared_depth_bound_is_the_domain_bound(scope: SpanScope) -> None:
    """One number, so a scope cannot permit what a context would refuse."""
    assert scope.maximum_depth == MAXIMUM_SPAN_DEPTH


# ---------------------------------------------------------------------------
# What is collected
# ---------------------------------------------------------------------------


def test_a_completed_span_is_collected_with_its_duration(scope: SpanScope) -> None:
    """The clock is hand-cranked, so the duration is exact rather than plausible."""
    with scope.span("outer", trace_id=TRACE):
        pass
    (span,) = scope.drain()
    assert span.name == "outer"
    assert span.status is SpanStatus.OK
    assert span.took.nanoseconds == 500


def test_an_exception_records_the_type_and_re_raises(scope: SpanScope) -> None:
    """The work's outcome is unchanged; only the span learns something."""
    planted = "planted"
    with pytest.raises(KeyError), scope.span("outer", trace_id=TRACE):
        raise KeyError(planted)
    (span,) = scope.drain()
    assert span.status is SpanStatus.ERROR
    assert span.fault == "KeyError"


def test_an_exception_message_never_reaches_the_span(scope: SpanScope) -> None:
    """A message may carry a path, a credential or an entire request body."""
    message = "SENTINEL-VALUE-4a7c"
    with pytest.raises(ValueError, match="SENTINEL"), scope.span("outer", trace_id=TRACE):
        raise ValueError(message)
    (span,) = scope.drain()
    assert "SENTINEL-VALUE-4a7c" not in repr(span)


def test_inner_spans_are_collected_before_their_parents(scope: SpanScope) -> None:
    """Completion order, which is what a recorder actually observes."""
    with scope.span("outer", trace_id=TRACE), scope.span("inner"):
        pass
    assert [span.name for span in scope.drain()] == ["inner", "outer"]


def test_draining_twice_yields_nothing_the_second_time(scope: SpanScope) -> None:
    """A drain takes; it does not copy."""
    with scope.span("outer", trace_id=TRACE):
        pass
    assert len(scope.drain()) == 1
    assert scope.drain() == ()


def test_a_refused_attribute_set_loses_the_span_rather_than_the_work(
    scope: SpanScope,
) -> None:
    """Instrumentation must never replace the outcome of what it measures.

    The rule `StallEvidenceCollector.capture` states about an incident capture,
    applied to a span: a credential-shaped attribute costs the span and nothing
    else.
    """
    with scope.span("outer", trace_id=TRACE, api_key="planted"):
        pass
    assert scope.drain() == ()


def test_a_bounded_attribute_set_reaches_the_span(scope: SpanScope) -> None:
    """The other direction, so the refusal above is not simply losing everything."""
    with scope.span("outer", trace_id=TRACE, result="ok"):
        pass
    (span,) = scope.drain()
    assert span.attributes.series_key() == "result=ok"


def test_a_client_span_records_its_kind(scope: SpanScope) -> None:
    """Two kinds exist, and the one that is not the default is reachable."""
    with scope.span("outer", trace_id=TRACE, kind=SpanKind.CLIENT):
        pass
    (span,) = scope.drain()
    assert span.kind is SpanKind.CLIENT


# ---------------------------------------------------------------------------
# ADR-0026's boundary, asserted rather than argued
# ---------------------------------------------------------------------------


def test_the_variable_holds_a_span_context_and_nothing_else(scope: SpanScope) -> None:
    """Rule 1 of the four that make the `contextvars` exception defensible.

    Never a logger, never a correlation id, never anything mutable — so the
    variable cannot become the ambient correlation ADR-0026 refused.
    """
    with scope.span("outer", trace_id=TRACE):
        held = scope.active()
    assert isinstance(held, SpanContext)


def test_reaching_the_variable_requires_being_handed_the_scope() -> None:
    """Rule 2: the property ADR-0026 names does not hold here.

    "Any code anywhere, handed nothing" is what a module-level variable would
    give. This one is an instance attribute, so two scopes do not see each other
    and neither is reachable without the object.
    """
    first = span_scope(
        new_span_id=_identifiers(), clock=lambda: MOMENT, monotonic=lambda: MonotonicReading(1)
    )
    second = span_scope(
        new_span_id=_identifiers(), clock=lambda: MOMENT, monotonic=lambda: MonotonicReading(1)
    )
    with first.span("outer", trace_id=TRACE):
        assert first.active() is not None
        assert second.active() is None
