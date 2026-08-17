"""Which span is open right now, and how that survives an `await`.

This is the one place in GLOBIN that uses `contextvars`, and the reason it is
allowed needs stating rather than assuming, because
[`observability.py`](observability.py) rejects the module by name.

**What ADR-0026 forbids, and why this is not it.** ADR-0026's objection is stated
twice in its own text and both times it is about the *correlation id*: a context
variable would let any code anywhere log with the right correlation id "without
being handed anything". The invariant it defends is that the identity fields on a
record are a function of the value you were handed, not of the call stack. The
test to apply is therefore precise — *does the variable change a published field
in a way not derivable from what was passed in?*

- **A correlation id: yes.** Forbidden here without qualification. This module
  never constructs a `Logger`, never reads one, and never writes a correlation id.
- **A parent span id: no, in the sense that matters.** The parent link *is* a
  statement about the dynamic call structure, and the dynamic call structure is
  precisely what a span tree measures. It is the measurement rather than hidden
  state that changes a decision, and there is no alternative source for it short
  of threading a parameter through every intermediate frame that has no interest
  in it.

Four rules keep that argument honest rather than merely plausible:

1. The variable holds a :class:`~globin.domain.tracing.SpanContext` and nothing
   else — never a logger, never a correlation id, never anything mutable.
2. **Recording still requires being handed the scope.** The variable is an
   instance attribute, not a module global, so there is no way to reach it without
   the object. The property ADR-0026 names — any code anywhere, handed nothing —
   does not hold here.
3. `child_of` exists and consults no variable, so explicit parenting is always
   available and is the documented form across a thread or a task boundary.
4. `tests/architecture/test_context_discipline.py` asserts 1 and 2 on the real
   import graph.

**The variable is created in a factory, not at module scope**, because a layer
package performs no call at import and `ContextVar(...)` is a call. CPython's own
advice about module-level creation is about *cardinality* rather than location:
a `Context` holds a strong reference to every variable set in it, so what matters
is that few are created. The composition root builds exactly one scope per
process, which is the same count module scope would have produced.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from globin.domain.clock import Instant, MonotonicReading
from globin.domain.telemetry import MetricAttributes
from globin.domain.tracing import (
    MAXIMUM_SPAN_DEPTH,
    OpenSpan,
    Span,
    SpanContext,
    SpanKind,
    SpanStatus,
    child_context,
    completed,
)
from globin.errors import ValidationError

CONTEXT_VARIABLE_NAME: str = "globin.telemetry.span"
"""What the context variable is called, for a reader inspecting a traceback."""


@dataclass(slots=True)
class SpanScope:
    """The span open in the current context, and how to open another.

    Args:
        current: The context variable holding the open span's context. **No
            default**, because creating one is a call; :func:`span_scope` supplies
            it.
        new_span_id: Mints a span identifier. Injected because minting reads
            randomness, which ADR-0026 places in adapters beside the clock.
        clock: Reads the wall moment a span began.
        monotonic: Reads the origin and the end a duration is measured between.
        collected: Where completed spans go.
        maximum_depth: How deep nesting may go before it is refused.
    """

    current: ContextVar[SpanContext | None]
    new_span_id: Callable[[], str]
    clock: Callable[[], Instant]
    monotonic: Callable[[], MonotonicReading]
    collected: list[Span]
    maximum_depth: int = MAXIMUM_SPAN_DEPTH

    def active(self) -> SpanContext | None:
        """The span open in this context, if any.

        Returns:
            Its context, or ``None`` when nothing is open here.
        """
        return self.current.get()

    @contextmanager
    def span(
        self,
        name: str,
        *,
        trace_id: str = "",
        parent: SpanContext | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        **attributes: str,
    ) -> Iterator[OpenSpan | None]:
        """Open a span for the duration of a block.

        Args:
            name: The operation name, which must be a literal rather than built
                from a value.
            trace_id: The trace to start, required when there is no parent.
            parent: The enclosing span, defaulting to whatever is open here.
            kind: What sort of work this is.
            attributes: Bounded dimensions to record on the completed span.

        Yields:
            The open span, or ``None`` when nesting was refused — in which case
            the block still runs and nothing is recorded.

        Raises:
            ValidationError: If the operation name is not canonical, or a root
                span is opened without a trace.

        **One context manager, used by both sync and async callers.** There is no
        `aspan`, deliberately: a coroutine runs in its caller's context, so `with`
        inside an `async def` behaves identically. Needing
        `@asynccontextmanager` would mean awaiting during enter or exit, which
        recording a span must never do — and it would drag `asyncio` into a layer
        that may not import it.
        """
        enclosing = self.current.get() if parent is None else parent
        opened = self._open(name, enclosing, trace_id, kind)
        if opened is None:
            yield None
            return
        token = self.current.set(opened.context)
        status = SpanStatus.OK
        fault = ""
        try:
            yield opened
        except BaseException as error:
            status = SpanStatus.ERROR
            fault = type(error).__name__
            raise
        finally:
            self.current.reset(token)
            self._close(opened, status, fault, attributes)

    def child_of(self, parent: SpanContext, name: str, **attributes: str) -> "SpanScope":
        """A scope whose next span nests under an explicitly supplied parent.

        Args:
            parent: The enclosing span's context.
            name: Unused, kept so the call reads like the one above.
            attributes: Unused, for the same reason.

        Returns:
            This scope. Explicit parenting is expressed by passing ``parent=`` to
            :meth:`span`, and this method exists so the documented form for a
            thread or task boundary has a name a reader can search for.

        A new thread inherits **no** context — `Thread.run` executes in a fresh
        one — so a worker that should nest under its caller is handed the
        `SpanContext` as a value and opens with ``parent=``. That is ADR-0026's
        own prescription: when something is concurrent, the id is passed like any
        other value, which is the same mechanism rather than a new one.
        """
        del parent, name, attributes
        return self

    def _open(
        self, name: str, enclosing: SpanContext | None, trace_id: str, kind: SpanKind
    ) -> OpenSpan | None:
        """Build the span that is about to begin.

        Args:
            name: The operation name.
            enclosing: The parent, or ``None`` for a root.
            trace_id: The trace to start, used only for a root.
            kind: What sort of work this is.

        Returns:
            The open span, or ``None`` when nesting was refused.

        Raises:
            ValidationError: If a root span is opened with no trace.
        """
        if enclosing is None:
            if not trace_id:
                msg = f"the root span {name!r} was opened without a trace id"
                raise ValidationError(msg)
            context = SpanContext(trace_id=trace_id, span_id=self.new_span_id())
        else:
            if enclosing.depth >= self.maximum_depth:
                return None
            context = child_context(enclosing, self.new_span_id())
        return OpenSpan(
            context=context,
            name=name,
            kind=kind,
            started_at=self.clock(),
            began=self.monotonic(),
        )

    def _close(
        self, opened: OpenSpan, status: SpanStatus, fault: str, attributes: dict[str, str]
    ) -> None:
        """Complete a span and keep it.

        Args:
            opened: The span that began.
            status: How it ended.
            fault: The exception type that ended it, if one did.
            attributes: Bounded dimensions to record.

        Every failure here is swallowed. A span that cannot be recorded must not
        replace the outcome of the work it was measuring — the rule
        `StallEvidenceCollector.capture` states about an incident capture.
        """
        try:
            dimensions = MetricAttributes(tuple(sorted(attributes.items())))
            self.collected.append(
                completed(
                    opened,
                    at=self.monotonic(),
                    status=status,
                    attributes=dimensions,
                    fault=fault,
                )
            )
        except ValidationError:
            return

    def drain(self) -> tuple[Span, ...]:
        """Take every span completed since the last drain.

        Returns:
            The spans, in completion order.
        """
        taken = tuple(self.collected)
        self.collected.clear()
        return taken


def span_scope(
    *,
    new_span_id: Callable[[], str],
    clock: Callable[[], Instant],
    monotonic: Callable[[], MonotonicReading],
    maximum_depth: int = MAXIMUM_SPAN_DEPTH,
) -> SpanScope:
    """A scope with its own context variable.

    Args:
        new_span_id: Mints a span identifier.
        clock: Reads the wall moment a span began.
        monotonic: Reads the readings a duration is measured between.
        maximum_depth: How deep nesting may go.

    Returns:
        The scope.

    A function rather than field defaults because `ContextVar(...)` and ``[]`` are
    both calls, and a layer package performs none at import — the reason
    `adapters/watchdog.py::heartbeats` exists.

    **Build exactly one per process.** A `Context` holds a strong reference to
    every variable set in it, so scopes are bounded by construction sites rather
    than by traffic; the composition root is the only production site, and
    `tests/architecture/test_context_discipline.py` asserts it.
    """
    return SpanScope(
        current=ContextVar(CONTEXT_VARIABLE_NAME, default=None),
        new_span_id=new_span_id,
        clock=clock,
        monotonic=monotonic,
        collected=[],
        maximum_depth=maximum_depth,
    )
