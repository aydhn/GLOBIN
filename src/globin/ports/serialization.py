"""The contract a persisted representation satisfies.

One port, because there is one question: what does a document look like once it
has left the process, and how does it come back? :mod:`globin.domain.serialization`
decides what a record *means* — its schema, its version, the wire form of each
value — and this decides how that meaning is spelled.

**A codec performs no I/O, and is still a port.** Every other port in GLOBIN
fronts something outside the process: a clock, a configuration file, a log sink.
This one fronts a *choice* instead. Rendering JSON touches nothing, but which
representation GLOBIN writes is an outside-world commitment — it is what a later
phase's storage engine, a support tool and anything reading a GLOBIN artefact
will have to agree with. Phases 159 and 190 persist results and models and may
well want a columnar format; expressing that as a second implementation of this
protocol is the whole reason the seam exists.

What is *not* here is storage itself. There is no ``save``, no ``load``, no path
and no handle. Turning text into a file or a row is genuinely outside the
process, and it belongs to the phases that own a place to put it — Phase 159 for
backtest results, Phase 190 for models, Phase 266 for orchestration state. A port
invented here for a caller that does not exist would be the scaffolding
``REPOSITORY_LAYOUT.md`` refuses.

Not :func:`~typing.runtime_checkable`, matching
:class:`globin.ports.clock.Clock` and :class:`globin.ports.observability.LogSink`.
Conformance is checked by mypy where an implementation is assigned to this type,
which is stronger than an :func:`isinstance` call comparing method names.
"""

from collections.abc import Mapping
from typing import Protocol


class Codec(Protocol):
    """A two-way translation between a document and its stored text."""

    def encode(self, document: Mapping[str, object]) -> str:
        """Render a document as text.

        Args:
            document: What :func:`globin.domain.serialization.envelope` produced —
                a mapping with :class:`str` keys, carrying the schema, its
                version and the payload.

        Returns:
            The text, with no trailing newline. Whoever writes it to a file
            decides the terminator and the encoding; a codec that appended one
            would be making a file's decision on a value's behalf.

        Raises:
            ValidationError: If the document holds anything the representation
                cannot carry back unchanged.

        The contract is round-trip identity: ``decode(encode(d)) == d`` for every
        document this accepts. An implementation that would have to narrow a
        value in order to render it must raise instead, because a record that
        reads back as something else is worse than one that could not be written.
        """
        ...

    def decode(self, text: str) -> Mapping[str, object]:
        """Read a document back from text.

        Args:
            text: What :meth:`encode` produced.

        Returns:
            The document, as a mapping with :class:`str` keys.

        Raises:
            ValidationError: If the text is malformed, is not a document at its
                top level, or holds a value this representation should never
                have written.

        Refusing on the way *in* as well as on the way out is deliberate. A
        document that arrived from somewhere else — an older writer, a hand
        edit, a corrupted file — is exactly the case where a permissive reader
        turns a detectable fault into a silent one.
        """
        ...
