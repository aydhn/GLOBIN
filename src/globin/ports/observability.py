"""The port every log record leaves GLOBIN through.

One method, because one method is all the boundary needs. Where a record ends
up — a stream, a file, a system journal, several at once — is a question about
the outside world, and this layer is the line past which the outside world is
not described.

The narrowness is what makes the guarantee in :mod:`globin.domain.observability`
worth having. A sink receives a :class:`~globin.domain.observability.LogEvent`
that is already redacted, so the set of things a new sink implementer can get
wrong does not include leaking a credential.
"""

from typing import Protocol

from globin.domain.observability import LogEvent


class LogSink(Protocol):
    """Somewhere a log record can be written."""

    def emit(self, event: LogEvent) -> None:
        """Write one record.

        Args:
            event: The record, already redacted and canonically ordered.

        Implementations decide their own failure behaviour, and the choice is a
        real one — see :class:`globin.adapters.observability.StreamLogSink` for
        the reasoning behind the one GLOBIN ships.
        """
        ...
