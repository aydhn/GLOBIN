"""The contracts for sending a REST request and for reading a binary answer.

Two protocols. One has an implementation in this repository and one deliberately
does not.

**A transport is handed its destination and cannot choose one.**
:meth:`RestTransport.send` takes a
:class:`~globin.domain.rest_endpoint.EndpointResolution` rather than a product and
an environment, so the component that opens a socket has no access to the registry
and no way to pick a different host from the one it was given. That is what makes
"no silent endpoint substitution" a property of the object graph rather than a rule
somebody has to keep following: the transport could not substitute an endpoint if
it wanted to, because it has never seen the alternatives.

**Nothing here raises for a network condition.** The return type is a
:class:`~globin.domain.rest.RestExchange`, which carries an outcome including
:attr:`~globin.domain.rest.RequestOutcome.UNKNOWN`. That module's docstring gives
the reason at length; the short form is that an exception means *this did not
happen*, and the whole point of ``UNKNOWN`` is that GLOBIN cannot say so.
"""

from typing import Protocol

from globin.domain.rest import RestExchange, RestRequest, SbeEnvelope
from globin.domain.rest_endpoint import EndpointResolution


class RestTransport(Protocol):
    """Something that can send a REST request to an already-chosen endpoint.

    Implemented by :class:`globin.adapters.rest_transport.HttpRestTransport`, and by
    hand-written doubles in the tests. The lifecycle is explicit in both directions
    because a connection pool that opened itself lazily would make "did this test
    leak a socket" unanswerable.
    """

    def open(self) -> None:
        """Make the transport ready to send.

        Idempotent: opening an open transport is not an error, because a caller that
        had to track the state would end up keeping a second copy of it.
        """
        ...

    def send(self, resolution: EndpointResolution, request: RestRequest) -> RestExchange:
        """Send one request and report everything knowable about what happened.

        Args:
            resolution: Where to send it. A refused resolution is reported as
                :attr:`~globin.domain.rest.RequestOutcome.REJECTED_BEFORE_SEND` with
                no socket opened.
            request: What to send.

        Returns:
            The exchange, whatever its outcome. **Never raises for a network,
            protocol or venue condition** — see this module's docstring.

        Raises:
            ValidationError: Only for a fault in GLOBIN itself, such as a request
                that could not be constructed. A defect here is a defect in a
                caller, not a property of the network.
        """
        ...

    def close(self) -> None:
        """Release every connection this transport holds.

        Idempotent, and safe to call on a transport that was never opened. After it
        returns, the transport holds no socket — which is what the lifecycle tests
        assert rather than assume.
        """
        ...


class SbeDecoder(Protocol):
    """Something that can turn an SBE payload into values GLOBIN can use.

    **Nothing in this repository implements this, and that is the deliverable.**
    Phase 034 negotiates SBE, refuses combinations the registry does not support,
    and carries a binary answer in an opaque
    :class:`~globin.domain.rest.SbeEnvelope` that no JSON parser will ever see.
    Whether decoding SBE is worth the schema tooling it requires is the question
    Phase 047 was created to answer, and answering it early by writing a decoder
    would be the premature implementation ``CLAUDE.md`` calls a defect.

    Declaring the interface now costs nothing and buys one thing: the envelope has
    somewhere to go later without any caller changing.
    """

    def decode(self, envelope: SbeEnvelope) -> object:
        """Turn a binary payload into a value.

        Args:
            envelope: The payload and the schema it was encoded against.

        Returns:
            Whatever the schema describes.
        """
        ...
