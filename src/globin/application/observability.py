"""The logger call sites hold: context carried explicitly, never ambiently.

A :class:`Logger` is an immutable value pairing a sink with the context every
record it produces should carry. :meth:`Logger.bind` returns a *new* logger
rather than mutating this one, so passing a logger into a function cannot change
what its caller subsequently logs.

That is the whole reason there is no :mod:`contextvars` here, and it is worth
being explicit about because the ambient alternative is the more common one.
A context variable would let any code anywhere log with the right correlation id
without being handed anything — convenient, and exactly the hidden global state
``ENGINEERING_CONTRACT.md`` invariant 5 forbids. It also makes a test's outcome
depend on what an earlier test set, which the process-state isolation added in
Phase 005 exists to prevent. Explicit binding costs an argument at each boundary
and buys back a logger whose output is a function of what you passed it.

There are no formatting helpers and no ``log(level, ...)`` escape hatch. Five
named methods make the severity of a call site readable without following an
argument, and ``docs/LOGGING_POLICY.md`` says when each is right.
"""

from dataclasses import dataclass, replace

from globin.domain.observability import LogEvent, Severity, log_event
from globin.ports.observability import LogSink


@dataclass(frozen=True, slots=True)
class Logger:
    """A sink plus the context every record written through it carries.

    Args:
        sink: Where records go.
        correlation_id: Ties every record this logger produces to the same piece
            of work. Supplied rather than generated, so a test can pin it and a
            caller can continue an existing unit of work.
        context: Fields attached to every record. Held as sorted pairs so two
            loggers bound with the same fields compare equal.

    Nothing here is mutable, so a :class:`Logger` is safe to store on a
    long-lived object and safe to share.
    """

    sink: LogSink
    correlation_id: str
    context: tuple[tuple[str, object], ...] = ()

    def bind(self, **fields: object) -> "Logger":
        """Return a new logger carrying these fields in addition to its own.

        Args:
            **fields: Context to attach to every record the result produces.
                A name already bound is replaced, so a narrower scope can
                override a wider one.

        Returns:
            A new :class:`Logger`. This one is unchanged.
        """
        merged = dict(self.context)
        merged.update(fields)
        return replace(self, context=tuple(sorted(merged.items())))

    def with_correlation(self, correlation_id: str) -> "Logger":
        """Return a new logger tagging its records with a different unit of work.

        Args:
            correlation_id: The new correlation id.

        Returns:
            A new :class:`Logger` with the same sink and context.
        """
        return replace(self, correlation_id=correlation_id)

    def debug(self, event: str, **fields: object) -> None:
        """Record detail useful only when diagnosing something."""
        self._emit(Severity.DEBUG, event, fields)

    def info(self, event: str, **fields: object) -> None:
        """Record something that happened and that an operator would want to see."""
        self._emit(Severity.INFO, event, fields)

    def warning(self, event: str, **fields: object) -> None:
        """Record something unexpected that GLOBIN handled and continued past."""
        self._emit(Severity.WARNING, event, fields)

    def error(self, event: str, **fields: object) -> None:
        """Record work that did not complete."""
        self._emit(Severity.ERROR, event, fields)

    def critical(self, event: str, **fields: object) -> None:
        """Record a fault that stops GLOBIN doing its job at all."""
        self._emit(Severity.CRITICAL, event, fields)

    def _emit(self, severity: Severity, event: str, fields: dict[str, object]) -> None:
        """Merge context with call-site fields and hand the record to the sink.

        Args:
            severity: How bad the event is.
            event: The static dotted event name.
            fields: Fields supplied at the call site. These win over bound
                context, because the more specific statement about a particular
                event is the one made where the event happened.
        """
        merged = dict(self.context)
        merged.update(fields)
        self.sink.emit(
            log_event(
                severity=severity,
                event=event,
                correlation_id=self.correlation_id,
                fields=merged,
            )
        )


def emitted_event(logger: Logger, severity: Severity, event: str, **fields: object) -> LogEvent:
    """Build the record ``logger`` would produce, without emitting it.

    Args:
        logger: The logger whose context and correlation id to use.
        severity: How bad the event is.
        event: The static dotted event name.
        **fields: Call-site fields, which win over bound context.

    Returns:
        The :class:`~globin.domain.observability.LogEvent` that
        :meth:`Logger.info` and its siblings would hand to the sink.

    This exists so that a caller wanting to inspect or route a record can do so
    without a sink that captures one, and so that the merge rule has a name to
    be tested through rather than being reachable only as a side effect.
    """
    merged = dict(logger.context)
    merged.update(fields)
    return log_event(
        severity=severity,
        event=event,
        correlation_id=logger.correlation_id,
        fields=merged,
    )
