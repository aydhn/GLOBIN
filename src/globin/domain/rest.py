"""A REST exchange expressed as values: what is asked, what came back, what it means.

Everything about a REST request that can be decided without a socket, which is
almost all of it. Whether a query renders the same way twice, whether a body is a
JSON object or a WAF's HTML apology, and — the part this module exists for —
whether an operation that produced no clean answer *failed* or merely *did not
answer* are all questions a connection cannot help with.
`adapters/rest_transport.py` is left with the part that genuinely cannot be pure.

**The five-member outcome is the deliverable.** A transport that reports success
and failure has thrown away the state that matters most to a trading system: the
one where GLOBIN sent an order and does not know what happened to it. Binance
documents this explicitly — a 5XX "is important to NOT treat as a failure
operation", and error ``-1007`` says the execution status is unknown — so
:class:`RequestOutcome` carries :attr:`RequestOutcome.UNKNOWN` and nothing in this
repository may collapse it into a failure. Phase 043 owns retry, and it inherits
the rule that ``UNKNOWN`` is never replayed.

**The same status means different things to a read and to a write.** A 503 on a
price query is a confirmed failure: nothing was at stake, and the caller may ask
again freely. A 503 on an order placement is ambiguous, because the matching
engine may have accepted it. :func:`classify` therefore takes the side effect as
an input rather than reading a status table, and the difference is asserted in
both directions.

**Percent-encoding is written out rather than borrowed.** ``urllib`` is declared
I/O-capable in ``docs/architecture/dependency-rules.toml``, so a domain module may
not import it, and :func:`percent_encode` is the consequence. That turned out to be
the better shape anyway, and Phase 035 is where it paid: its signer computes a
signature over the exact query string this module renders, so the signed span is a
literal prefix of what is transmitted. The safe set therefore has to be a stated
constant this repository owns rather than a standard-library default that may be
widened in a future release -- a widening would change what is signed.

What this module does not know: any venue host (they live in Phase 033's registry
and ``tests/architecture/test_api_reality_discipline.py`` fails if one appears
here), how to open a connection, how to sign anything, what the current time is,
or what a rate limit permits.
"""

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

from globin.errors import ValidationError

SCHEMA: Final[str] = "globin.rest.transport"
"""What a document produced by this surface calls itself."""

SCHEMA_VERSION: Final[int] = 1
"""The version every document this surface emits is written against."""

PHASE: Final[int] = 34
"""The phase that built this. Recorded in evidence rather than inferred."""

UNRESERVED: Final[str] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
"""The characters :func:`percent_encode` passes through unchanged.

RFC 3986's *unreserved* set exactly, and deliberately nothing more. Every reserved
character — including ``/``, ``:``, ``@`` and ``+`` — is encoded, because a query
*value* has no structure for them to delimit and leaving one raw is how a symbol
containing a slash becomes two parameters.

**Narrower than the standard library's default.** ``urllib.parse.quote`` leaves
``/`` alone unless told otherwise, which is correct for paths and wrong here. That
mismatch is the reason a hand-written encoder is worth the twelve lines even
setting the layer contract aside.
"""

PERCENT: Final[str] = "%"
"""What introduces an escape. Named so the encoder reads as the RFC does."""

MAX_OPERATION_LENGTH: Final[int] = 64
"""How long a logical operation name may be.

An operation name is GLOBIN's word for a request, not the venue's path, and it
becomes a metric attribute value. Phase 026's cardinality arithmetic requires a
bound on anything that reaches a label, so it is bounded here rather than trusted.
"""

MAX_PATH_LENGTH: Final[int] = 256
"""How long a request path may be, prefix included."""

MAX_QUERY_PARAMETERS: Final[int] = 128
"""How many parameters one request may carry.

A bound rather than a limit anybody has hit. The largest documented Spot request
takes a batch of orders and stays far below this; a request that exceeded it would
be a defect in a caller rather than a legitimate need.
"""

MAX_HEADERS: Final[int] = 32
"""How many headers one request may carry."""

MAX_BODY_BYTES: Final[int] = 1024 * 1024
"""The largest request body this transport will construct."""

MAX_RESPONSE_BYTES: Final[int] = 8 * 1024 * 1024
"""The largest response body this transport will read.

Matched to ``tools/quality/venue/gate.py``'s cap deliberately: the two reach the
same venue and a limit that differed between them would be two opinions about the
same risk. A body at the cap is a failure, never a truncation — a half-read JSON
document that happened to parse would be the worst possible outcome.
"""

MAX_LOGGED_BODY_BYTES: Final[int] = 512
"""How much of a body may reach a diagnostic record.

The brief's rule is that a raw body is never written without bound. This is the
bound. It applies to *every* body including a successful one, because a rule that
only bites on failures is a rule nobody exercises until the day it matters.
"""

NO_STATUS: Final[int] = 0
"""What :class:`RestOutcomeInputs` carries when no HTTP status was received.

Zero rather than ``None`` so the field is always an integer and the classification
table can be written without an optional branch. No real status is zero.
"""

NO_EXCHANGE_CODE: Final[int] = 0
"""What :class:`RestOutcomeInputs` carries when the venue reported no code.

Binance's own codes are negative, and its documented success payloads carry none,
so zero is unambiguous rather than merely unlikely.
"""

AMBIGUOUS_STATUSES: Final[tuple[int, ...]] = (409, 500, 502, 503, 504)
"""HTTP statuses after which a side-effecting operation's fate is not known.

Each is here for a documented reason rather than a cautious one:

``409``
    Binance documents it as a *partially successful* cancel-replace. Half of the
    operation may have happened, which is the definition of ambiguous.
``500``, ``502``, ``503``, ``504``
    Binance's own words are that a 5XX "is important to NOT treat as a failure
    operation; the execution status is UNKNOWN and could have been a success."
    USDⓈ-M Futures repeats the warning for its 503 specifically.

**403, 418 and 429 are deliberately absent.** All three are refusals at the
gateway before anything reached a matching engine — a WAF violation, an IP ban and
a rate-limit rejection respectively — so each is a *confirmed* failure. Adding them
here "to be safe" would be unsafe: it would make an ordinary rate-limit rejection
indistinguishable from a lost order, and Phase 043 would then be unable to retry
the one case that is always retryable.

**A tuple rather than a frozenset**, which is not a taste. A layer package
performs no call at import — ``test_layer_modules_execute_no_work_when_imported``
enforces it as a blanket ban, deliberately stricter than the rule it stands for —
and ``frozenset({...})`` is a call. Membership over five integers costs nothing,
and declaration order survives, which makes the table read as the documentation
does.
"""

AMBIGUOUS_EXCHANGE_CODES: Final[tuple[int, ...]] = (-1006, -1007)
"""Venue error codes after which a side-effecting operation's fate is not known.

Both are transcriptions rather than judgements: the venue says in its own error
text exactly what :attr:`RequestOutcome.UNKNOWN` means.

``-1006``
    ``UNEXPECTED_RESP``, documented as *"An unexpected response was received from
    the message bus. Execution status unknown."*
``-1007``
    ``TIMEOUT``, documented as *"Timeout waiting for response from backend server.
    Send status unknown; execution status unknown."*

**``-1006`` was missing until Phase 036, and its absence was a defect rather than a
decision.** Phase 034 declared ``-1007`` from ``rest-api.md``, which quotes that one
code inline; the full table lives in ``errors.md``, which no phase had read until
Phase 036 needed ``-1021`` from it. A venue code whose own text ends *"Execution
status unknown"* and which GLOBIN classified as a confirmed failure is precisely the
loss of the fact ADR-0089 exists to preserve. See
``docs/research/phase_036_sources.md`` S-01.

**``-1021`` is deliberately not here.** It is a timing rejection at the gate, before
the Matching Engine, so nothing was at stake — the same reading that keeps 403, 418
and 429 out of :data:`AMBIGUOUS_STATUSES`. Marking it ambiguous would make the one
always-safe timing failure permanently unretryable, because
:mod:`globin.domain.clock_sync` permits its bounded recovery only on a *confirmed*
outcome.

Checked *before* the HTTP status, because either code can accompany more than one
status and the code is the more specific statement.
"""

SUCCESS_STATUS_FLOOR: Final[int] = 200
"""The lowest status this transport treats as a completed success."""

SUCCESS_STATUS_CEILING: Final[int] = 300
"""One past the highest status this transport treats as a completed success."""


class HttpMethod(StrEnum):
    """The verbs GLOBIN may send.

    Five members, and the absent ones are the point: ``PATCH``, ``OPTIONS``,
    ``TRACE`` and ``CONNECT`` are not used by any documented Binance REST
    operation, so a caller cannot reach for one. ``HEAD`` is here because a
    connectivity probe has a legitimate use for it.
    """

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    HEAD = "HEAD"


class SideEffect(StrEnum):
    """What is at stake if GLOBIN never learns how a request ended.

    Three members, and the middle one exists for Phase 043 rather than for this
    phase: a request that can be replayed without duplicating anything is a
    different retry proposition from one that cannot, and recording which is which
    now costs nothing while inferring it later would cost correctness.
    """

    READ_ONLY = "read_only"
    """Nothing at the venue changes. An unanswered request may simply be asked again."""

    IDEMPOTENT_WRITE = "idempotent_write"
    """State changes, and sending it twice reaches the same state as sending it once.

    A cancel by identifier is the documented example. Still ambiguous when
    unanswered — GLOBIN does not know the state — but safely resolvable by asking.
    """

    MUTATING = "mutating"
    """State changes, and sending it twice is not the same as sending it once.

    An order placement. This is the member the whole outcome model exists for.
    """


class RequestSecurityIntent(StrEnum):
    """What a request needs from a credential, declared by the caller.

    Declared rather than derived so that the capability gate can refuse *before*
    a credential is fetched, which is what makes a public probe provably
    credential-free: :attr:`PUBLIC` is the only member the probe path accepts, and
    a resolution requiring more is refused with nothing having been read from the
    secret store.

    Phase 035 implemented what the two authenticated members mean on the wire, in
    ``globin.application.auth``. Nothing *here* signs anything, and that is the
    separation rather than a gap: this module renders a request, and an already
    signed one arrives at the transport indistinguishable from any other.
    """

    PUBLIC = "public"
    """No credential of any kind. Market data and connectivity."""

    API_KEY = "api_key"
    """A key is presented and the request is not signed."""

    SIGNED = "signed"
    """A key is presented and the request carries a signature.

    Phase 035 built what that means on the wire, in ``globin.application.auth``.
    This member states the requirement; it does not satisfy it.
    """


class ResponseEncoding(StrEnum):
    """How GLOBIN asks the venue to encode its answer.

    Two members. ``FIX_TEXT`` and ``FIX_SBE`` exist in Phase 033's
    :class:`~globin.domain.api_reality.EncodingKind` and are deliberately not here:
    this is a REST transport, and FIX is a different protocol reached over a
    different socket with a different session model.
    """

    JSON = "json"
    """The default, and what every documented Spot REST endpoint answers with."""

    SBE = "sbe"
    """Simple Binary Encoding, negotiated by header.

    Phase 034 negotiates it and refuses to misread it. It does not decode it —
    :class:`~globin.ports.rest.SbeDecoder` is an interface with no implementation,
    and Phase 047 assesses whether one is worth building.
    """


class TimeUnitPreference(StrEnum):
    """Which unit GLOBIN asks the venue to express response timestamps in.

    Binance Spot documents millisecond timestamps as the default and a header that
    requests microseconds instead. Modelled as a preference rather than a setting
    because the venue is free to answer in whatever it likes; what GLOBIN records
    is what it *asked for*, alongside the answer.

    **This is not clock synchronisation.** No offset is computed, no drift is
    measured and no clock is read here. Phase 036 owns that, in
    :mod:`globin.domain.clock_sync`, and reads its clocks through ports.
    """

    PROVIDER_DEFAULT = "provider_default"
    """Ask for nothing. No header is sent and the venue's default applies."""

    MILLISECONDS = "milliseconds"
    MICROSECONDS = "microseconds"


class EndpointRole(StrEnum):
    """What an endpoint is for, among several the registry offers for one product.

    Returned as data and acted on by nobody. Phase 033 records seven production
    Spot REST endpoints; which to prefer, and whether to move between them, is a
    policy question this phase deliberately does not answer — see
    :mod:`globin.domain.rest_endpoint` on why nothing fails over.

    **Three members, and there is deliberately no environment-specific fourth.**
    Environment is a *dimension* of a resolution rather than a role within one:
    every resolved endpoint is already specific to the environment it was asked
    for, because the candidate set is filtered on environment before a role is
    assigned. A fourth member would be true of every endpoint and would therefore
    distinguish nothing — and worse, it would suggest that endpoints *without* it
    are environment-agnostic, which none is.
    """

    PRIMARY = "primary"
    """The endpoint the venue documents first, and the default."""

    ALTERNATE = "alternate"
    """Documented, equivalent in capability, and differing in performance claims."""

    MARKET_DATA_ONLY = "market_data_only"
    """Documented as serving market data and nothing else.

    The venue publishes exactly such a host, unauthenticated. Handing it a signed
    order would fail in a confusing way, so the role is carried and the capability
    gate refuses the combination outright.
    """


class SendState(StrEnum):
    """How far a request got, which is the input the outcome model turns on.

    Four members forming a ladder, and the first two are separated for a reason
    that is not cosmetic: :attr:`REFUSED` means GLOBIN decided, and
    :attr:`NOT_SENT` means the network decided. An operator reading a diagnostic
    needs to know whether to fix a configuration or a cable.
    """

    REFUSED = "refused"
    """GLOBIN's own gate declined. No socket was opened."""

    NOT_SENT = "not_sent"
    """A connection was attempted and the request provably never left this process.

    A DNS failure, a TLS handshake failure, a refused connection, or a timeout
    while connecting. In every case the bytes were still in this process when it
    ended, which is why this is safe to report as *nothing happened*.
    """

    SENT = "sent"
    """The request left this process and no complete answer came back.

    The state that produces :attr:`RequestOutcome.UNKNOWN` for anything with
    something at stake.
    """

    COMPLETED = "completed"
    """A complete HTTP response arrived. What it *said* is a separate question."""


class RequestOutcome(StrEnum):
    """What GLOBIN knows about an operation's fate. Five members, and no sixth.

    A fifth state was not obvious and is not decoration. Systems that model three
    — success, failure, error — are the ones that place an order twice, because
    every state that is not success gets swept into failure and every failure looks
    retryable.

    **Nothing in this repository may map :attr:`UNKNOWN` onto a failure**, and
    ``tests/contract/test_rest_contract.py`` asserts it.
    """

    SUCCESS_CONFIRMED = "success_confirmed"
    """The venue answered, and the answer was success."""

    FAILURE_CONFIRMED = "failure_confirmed"
    """It is known that the operation did not take effect.

    Either the venue refused it explicitly, or nothing was at stake and no answer
    arrived. Safe to report to a caller as *this did not happen*.
    """

    UNKNOWN = "unknown"
    """Something may have happened at the venue and GLOBIN cannot tell what.

    The reason this module exists. Never retried, never reported as a failure, and
    resolved only by asking the venue about its own state — which is a query a
    later phase builds, not something a transport can do for itself.
    """

    NOT_SENT = "not_sent"
    """The request provably never left this process. Nothing happened anywhere."""

    REJECTED_BEFORE_SEND = "rejected_before_send"
    """GLOBIN refused to send it. Distinct from :attr:`NOT_SENT` because the remedy
    is in this repository or its configuration rather than out on the network."""


class TransportFailureKind(StrEnum):
    """Why no usable answer arrived, at the level GLOBIN can actually distinguish.

    Every member maps from a specific exception the standard library raises, in
    ``adapters/rest_transport.py`` and nowhere else. The mapping is deterministic
    and total: an exception this transport cannot place becomes
    :attr:`UNCLASSIFIED` rather than escaping, because a library exception reaching
    an application layer is the leak ``ENGINEERING_CONTRACT.md`` forbids.
    """

    DNS_FAILURE = "dns_failure"
    TLS_FAILURE = "tls_failure"
    CONNECTION_REFUSED = "connection_refused"
    CONNECTION_RESET = "connection_reset"
    TIMEOUT_BEFORE_SEND = "timeout_before_send"
    TIMEOUT_AFTER_SEND = "timeout_after_send"
    MALFORMED_RESPONSE = "malformed_response"
    DECODE_FAILURE = "decode_failure"
    RESPONSE_TOO_LARGE = "response_too_large"
    POOL_EXHAUSTED = "pool_exhausted"
    UNCLASSIFIED = "unclassified"
    """An exception the mapping did not recognise. Always reported, never swallowed."""


class BodyShape(StrEnum):
    """What arrived in the response body, decided before anything tries to use it.

    The brief requires eight cases be told apart, and the reason is that several of
    them are *not* JSON while arriving on an endpoint that always answers JSON. A
    WAF apology is HTML with a 403; a proxy error is text; an SBE payload is bytes.
    Feeding any of them to a JSON parser produces an exception whose message
    describes column 1 of a document nobody meant to send.
    """

    EMPTY = "empty"
    """No body at all. A 204, or a HEAD."""

    OBJECT = "object"
    ARRAY = "array"
    SCALAR = "scalar"
    """Valid JSON that is a number, string, boolean or null rather than a container."""

    MALFORMED_JSON = "malformed_json"
    """Declared JSON, and not JSON."""

    HTML = "html"
    """A page rather than a payload. What a WAF block looks like."""

    TEXT = "text"
    """Plain text. What an intermediary's error looks like."""

    BINARY = "binary"
    """Bytes, carried opaquely. An SBE payload arrives here and goes no further."""

    UNEXPECTED_CONTENT_TYPE = "unexpected_content_type"
    """A content type the negotiation did not ask for and cannot place."""


class Honoured(StrEnum):
    """Whether a declared timeout was actually applied by the client underneath.

    Phase 024's rule, restated for a new subject: a measurement that was not taken
    is never reported as zero. :class:`TimeoutPolicy` declares four timeouts and
    the standard library's client accepts one, so three of them are
    :attr:`NOT_SUPPORTED` today — a fact worth carrying rather than a field worth
    deleting, because a caller reading ``read_seconds`` deserves to know whether
    anything is enforcing it.
    """

    APPLIED = "applied"
    """The client underneath received this value and enforces it."""

    NOT_SUPPORTED = "not_supported"
    """The client underneath has no such setting. The value is declared, not enforced."""

    SUBSUMED = "subsumed"
    """The client underneath applies one timeout where this policy declares several.

    Not the same as :attr:`NOT_SUPPORTED`: something *is* bounding this phase of the
    exchange, just not separately from its neighbours.
    """


@dataclass(frozen=True, slots=True)
class TimeoutPolicy:
    """How long each phase of an exchange may take, and which bounds are real.

    Raises:
        ValidationError: On a non-positive or non-finite duration.

    **Four fields against a client that takes one.** ``http.client`` applies a
    single timeout covering connection and each socket operation, so this policy is
    partly a declaration of intent. :meth:`honoured` says exactly which parts are
    enforced rather than letting a caller assume all four are, and Phase 045 may
    replace the client underneath without any caller changing.
    """

    connect_seconds: float = 5.0
    read_seconds: float = 10.0
    write_seconds: float = 10.0
    pool_seconds: float = 5.0

    def __post_init__(self) -> None:
        """Refuse a duration that would disable a bound rather than set one."""
        for name in ("connect_seconds", "read_seconds", "write_seconds", "pool_seconds"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                msg = f"{name} must be a number, and is {type(value).__name__}"
                raise ValidationError(msg)
            if not math.isfinite(value):
                msg = f"{name} must be finite, and is {value!r}"
                raise ValidationError(msg)
            if value <= 0:
                msg = f"{name} must be positive; {value!r} would wait for ever"
                raise ValidationError(msg)

    @property
    def effective_seconds(self) -> float:
        """The one number a single-timeout client can actually be given.

        Returns:
            The largest declared bound, so no phase is cut short by another's
            budget. Taking the smallest would time out a legitimate slow read
            because somebody tightened the connect budget.
        """
        return max(self.connect_seconds, self.read_seconds, self.write_seconds)

    def honoured(self) -> dict[str, str]:
        """Which of the four are enforced by the client this transport uses.

        Returns:
            Each field name mapped to a :class:`Honoured` value.
        """
        return {
            "connect_seconds": Honoured.SUBSUMED.value,
            "read_seconds": Honoured.SUBSUMED.value,
            "write_seconds": Honoured.SUBSUMED.value,
            "pool_seconds": Honoured.NOT_SUPPORTED.value,
        }

    def as_record(self) -> dict[str, object]:
        """This policy as plain JSON-safe values.

        Returns:
            The four durations and, beside them, which are enforced.
        """
        return {
            "connect_seconds": self.connect_seconds,
            "read_seconds": self.read_seconds,
            "write_seconds": self.write_seconds,
            "pool_seconds": self.pool_seconds,
            "effective_seconds": self.effective_seconds,
            "honoured": self.honoured(),
        }


type QueryValue = Decimal | bool | int | str | None
"""What a query parameter may hold.

``float`` is absent, and its absence is the point. ``docs/PRECISION_POLICY.md``
forbids a binary float anywhere near a price or a quantity, and a query parameter
is precisely where one would leak to the venue. A caller with a float has a bug
this type makes visible at the boundary rather than in a fill report.
"""


def _require(value: object, expected: type, *, label: str, remedy: str) -> None:
    """Refuse a field whose type is wrong, however it was constructed.

    Args:
        value: What was supplied. Typed as :class:`object` so the check is a real
            one rather than one mypy has already proved redundant.
        expected: The class the field must hold.
        label: How to name the field in a message.
        remedy: What the caller should do instead.

    Raises:
        ValidationError: If ``value`` is not an instance of ``expected``.

    The same helper ``domain/values.py`` carries, for the same reason: these
    dataclasses annotate their fields, so mypy refuses the wrong type at every call
    site it can see. This exists for the ones it cannot — a value read from a
    document, or a test constructing the class directly to prove the refusal.
    """
    if not isinstance(value, expected):
        msg = f"{label} is {type(value).__name__}; {remedy}"
        raise ValidationError(msg)


def percent_encode(text: str) -> str:
    """Encode one value for a query string, deterministically.

    Args:
        text: The value.

    Returns:
        The value with every character outside :data:`UNRESERVED` replaced by its
        UTF-8 bytes in uppercase percent-escapes.

    Uppercase hex because RFC 3986 says producers should normalise to it; a
    signature computed over a lowercase escape would not match one computed over an
    uppercase escape, so this is load-bearing for Phase 035's signer rather than
    tidy -- and since that signer exists, changing the case here would break a
    signature rather than merely look different.
    """
    parts: list[str] = []
    for byte in text.encode("utf-8"):
        character = chr(byte)
        if character in UNRESERVED:
            parts.append(character)
        else:
            parts.append(f"{PERCENT}{byte:02X}")
    return "".join(parts)


def encode_value(value: object) -> str | None:
    """Render one parameter value as the venue will see it.

    Args:
        value: The value. Typed as :class:`object` rather than :data:`QueryValue`
            so that the refusal below is a real check: a parameter typed as the
            union would make the final branch unreachable, and mypy is configured
            to say so. ``domain/values.py`` draws the same distinction for the same
            reason.

    Returns:
        Its wire text, or ``None`` when the parameter is to be omitted entirely.

    Raises:
        ValidationError: On a ``Decimal`` that is not a finite number, or on a type
            outside :data:`QueryValue`.

    **The ``bool`` check precedes the ``int`` check deliberately.** ``bool`` is a
    subclass of ``int`` in Python, so an ``isinstance(value, int)`` test reached
    first would render ``True`` as ``1`` — which some venues accept and Binance
    documents as ``true``. The ordering is asserted by its own test because it is
    exactly the kind of correctness that survives review and dies in a refactor.

    **A ``Decimal`` renders in positional notation with its own scale preserved.**
    ``Decimal("1E-8")`` becomes ``0.00000001`` rather than ``1E-8``, and
    ``Decimal("0.10")`` keeps its trailing zero rather than becoming ``0.1``. The
    venue compares a quantity against a step size, and a scale GLOBIN chose to
    normalise away is a scale the venue never agreed to.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        if not value.is_finite():
            msg = f"a query parameter carries {value!r}, which is not a finite number"
            raise ValidationError(msg)
        return format(value, "f")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    msg = (
        f"a query parameter holds {type(value).__name__}; permitted types are "
        "Decimal, bool, int, str and None"
    )
    raise ValidationError(msg)


@dataclass(frozen=True, slots=True)
class QueryParameters:
    """An ordered, possibly repeating set of query parameters.

    Raises:
        ValidationError: On more than :data:`MAX_QUERY_PARAMETERS` entries, on an
            empty key, or on a value outside :data:`QueryValue`.

    **Order is preserved and never sorted.** Phase 035's signer signs the query
    string as sent, and a signer that re-ordered would produce a signature over a
    string the
    venue never received. Callers that want alphabetical order build it that way.

    **Duplicate keys are kept, not collapsed.** A documented Spot request repeats a
    parameter, and a mapping type would silently keep the last one — losing an
    element of a batch with no error anywhere.

    **Three states, not two.** A key absent from :attr:`items` was never mentioned;
    a key present with ``None`` was mentioned and deliberately omitted; a key
    present with ``""`` is transmitted as ``key=``. The first two render
    identically and mean different things, which is why
    :meth:`declared` and :meth:`transmitted` are separate.
    """

    items: tuple[tuple[str, QueryValue], ...] = ()

    def __post_init__(self) -> None:
        """Refuse a set that could not be rendered, or that nobody is bounding."""
        if len(self.items) > MAX_QUERY_PARAMETERS:
            msg = (
                f"a request carries {len(self.items)} query parameters and the limit "
                f"is {MAX_QUERY_PARAMETERS}"
            )
            raise ValidationError(msg)
        for key, value in self.items:
            if not key:
                msg = "a query parameter has an empty name"
                raise ValidationError(msg)
            encode_value(value)

    def declared(self) -> tuple[str, ...]:
        """Every key the caller mentioned, including those it omitted by value.

        Returns:
            The keys in order, repeats included.
        """
        return tuple(key for key, _ in self.items)

    def transmitted(self) -> tuple[str, ...]:
        """Every key that will actually appear in the query string.

        Returns:
            The keys in order, repeats included, minus those whose value is ``None``.
        """
        return tuple(key for key, value in self.items if encode_value(value) is not None)

    def canonical(self) -> str:
        """The query string, exactly as it will be sent.

        Returns:
            ``key=value`` pairs joined by ``&``, each side percent-encoded, in
            declaration order. Empty when nothing is transmitted — never a bare
            ``?``, which is a different URL from one without it.
        """
        rendered = [
            f"{percent_encode(key)}={percent_encode(text)}"
            for key, value in self.items
            if (text := encode_value(value)) is not None
        ]
        return "&".join(rendered)

    def as_record(self) -> dict[str, object]:
        """These parameters as plain JSON-safe values, with no value included.

        Returns:
            The declared and transmitted key lists, and how many of each. **Values
            are deliberately absent**: a query parameter is where a signature and an
            API key travel, so a record that carried values would be a redaction
            problem rather than a diagnostic.
        """
        return {
            "declared": list(self.declared()),
            "transmitted": list(self.transmitted()),
            "declared_count": len(self.declared()),
            "transmitted_count": len(self.transmitted()),
        }


def join_path(prefix: str, path: str) -> str:
    """Join an endpoint's recorded prefix to a request's path.

    Args:
        prefix: The endpoint's ``path_prefix`` from Phase 033's registry, which may
            be empty and may or may not carry a trailing slash.
        path: The request's path, which may or may not carry a leading slash.

    Returns:
        One path with exactly one separator at the join and no doubled separator
        anywhere, including in the middle of either half.

        **Empty segments are dropped rather than only trimmed**, which is a
        correction a property test made. Stripping the ends left ``a//a`` intact in
        the middle, so the docstring promised something the code did not do. ``//``
        is a different resource and some gateways answer it with a redirect, which
        a transport that never follows one would report as an unexplained 3xx.

    Raises:
        ValidationError: If the result would exceed :data:`MAX_PATH_LENGTH`, if the
            path is empty, or if either part contains a ``?`` or ``#`` — a query or
            a fragment smuggled through the path would bypass
            :class:`QueryParameters` entirely and reach the venue unencoded.
    """
    if not path:
        msg = "a request path is empty"
        raise ValidationError(msg)
    for part, label in ((prefix, "path prefix"), (path, "path")):
        for character in ("?", "#"):
            if character in part:
                msg = f"a {label} contains {character!r}; a query belongs in QueryParameters"
                raise ValidationError(msg)
    segments = [segment for segment in f"{prefix}/{path}".split("/") if segment]
    joined = "/" + "/".join(segments)
    if len(joined) > MAX_PATH_LENGTH:
        msg = f"a request path is {len(joined)} characters and the limit is {MAX_PATH_LENGTH}"
        raise ValidationError(msg)
    return joined


@dataclass(frozen=True, slots=True)
class SbeSchemaReference:
    """Which SBE schema a request asks the venue to answer with.

    Raises:
        ValidationError: On a negative identifier or version.

    **The header this renders into is not spelled here.** Its name comes from
    ``docs/engineering/rest-transport.toml``, which carries provenance for it the
    way every other venue fact in this repository does. A header name pasted into a
    domain module would be the second source of truth Phase 033 exists to prevent,
    differing only in that it is a header rather than a host.
    """

    identifier: int
    version: int

    def __post_init__(self) -> None:
        """Refuse a reference that could not name a real schema."""
        for name in ("identifier", "version"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                msg = f"an SBE schema {name} must be an integer, and is {type(value).__name__}"
                raise ValidationError(msg)
            if value < 0:
                msg = f"an SBE schema {name} is negative: {value}"
                raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This reference as plain JSON-safe values."""
        return {"identifier": self.identifier, "version": self.version}


@dataclass(frozen=True, slots=True)
class RequestBody:
    """A body GLOBIN sends, carried as bytes with its declared content type.

    Raises:
        ValidationError: On a body above :data:`MAX_BODY_BYTES`, or on an empty
            content type.

    Bytes rather than an object because the body is what gets signed, and an object
    re-serialised at send time may not produce the bytes that were signed.
    """

    content: bytes
    content_type: str

    def __post_init__(self) -> None:
        """Refuse a body nothing is bounding, or one that does not say what it is."""
        _require(
            self.content,
            bytes,
            label="a request body",
            remedy="a body is carried as the bytes that will be signed and sent",
        )
        if len(self.content) > MAX_BODY_BYTES:
            msg = f"a request body is {len(self.content)} bytes and the limit is {MAX_BODY_BYTES}"
            raise ValidationError(msg)
        if not self.content_type:
            msg = "a request body declares no content type"
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This body as plain JSON-safe values, with **no content included**.

        Returns:
            Its size and declared type. The bytes themselves never reach a record:
            a signed request's body is exactly where credential material would be.
        """
        return {"content_type": self.content_type, "byte_count": len(self.content)}


@dataclass(frozen=True, slots=True)
class RestRequest:
    """One REST request, complete except for where it is going.

    Raises:
        ValidationError: On an empty or over-long operation name, on more than
            :data:`MAX_HEADERS` headers, on a body attached to a method that
            carries none, or on an SBE reference given with a JSON encoding.

    **The host is absent on purpose.** A request says what to ask and an endpoint
    resolution says where; keeping them apart is what allows
    ``tests/architecture/test_api_reality_discipline.py`` to assert that no venue
    host is spelled anywhere in the package. :meth:`canonical_target` renders
    everything below the host, which is also exactly the span Phase 035's signer
    needs, and does use.

    ``headers`` carries only *safe* headers. Authorization material is added by the
    transport from a credential the caller never handles, which is why there is no
    field for it here and no way to smuggle one in.
    """

    operation: str
    method: HttpMethod
    path: str
    query: QueryParameters | None = None
    body: RequestBody | None = None
    headers: tuple[tuple[str, str], ...] = ()
    encoding: ResponseEncoding = ResponseEncoding.JSON
    schema_reference: SbeSchemaReference | None = None
    time_unit: TimeUnitPreference = TimeUnitPreference.PROVIDER_DEFAULT
    timeouts: TimeoutPolicy | None = None
    side_effect: SideEffect = SideEffect.READ_ONLY
    intent: RequestSecurityIntent = RequestSecurityIntent.PUBLIC
    correlation_id: str = ""

    def __post_init__(self) -> None:
        """Refuse a request that could not be sent, or could be sent wrongly."""
        if not self.operation:
            msg = "a request declares no operation name"
            raise ValidationError(msg)
        if len(self.operation) > MAX_OPERATION_LENGTH:
            msg = (
                f"operation {self.operation!r} is {len(self.operation)} characters and the "
                f"limit is {MAX_OPERATION_LENGTH}"
            )
            raise ValidationError(msg)
        if len(self.headers) > MAX_HEADERS:
            msg = f"a request carries {len(self.headers)} headers and the limit is {MAX_HEADERS}"
            raise ValidationError(msg)
        if self.body is not None and self.method in {HttpMethod.GET, HttpMethod.HEAD}:
            msg = f"a {self.method.value} request carries a body, which the venue will ignore"
            raise ValidationError(msg)
        if self.schema_reference is not None and self.encoding is not ResponseEncoding.SBE:
            msg = (
                "a request names an SBE schema and asks for "
                f"{self.encoding.value}; the reference would be sent and ignored"
            )
            raise ValidationError(msg)
        if self.encoding is ResponseEncoding.SBE and self.schema_reference is None:
            msg = "a request asks for SBE and names no schema; the venue cannot answer"
            raise ValidationError(msg)
        join_path("", self.path)

    @property
    def parameters(self) -> QueryParameters:
        """The query parameters, whether or not any were given.

        Returns:
            The declared set, or an empty one.

        The field is optional because a layer package performs no call at import
        and ``field(default_factory=QueryParameters)`` is one —
        ``domain/bootstrap.py`` records the same constraint and the same remedy.
        This property is where callers stop caring: *no parameters* and *an empty
        set of parameters* render identically, so only construction tells them
        apart.
        """
        return self.query or QueryParameters()

    @property
    def timeout_policy(self) -> TimeoutPolicy:
        """The timeouts this request is bounded by, declared or default.

        Returns:
            The declared policy, or the default one.
        """
        return self.timeouts or TimeoutPolicy()

    def canonical_target(self, prefix: str = "") -> str:
        """Everything below the host, rendered exactly as it will be sent.

        Args:
            prefix: The resolved endpoint's recorded path prefix.

        Returns:
            ``/path`` or ``/path?query``. Stable for one request across any number
            of calls, which is the property Phase 035's signer depends on.
        """
        target = join_path(prefix, self.path)
        query = self.parameters.canonical()
        return f"{target}?{query}" if query else target

    def as_record(self) -> dict[str, object]:
        """This request as plain JSON-safe values, carrying no parameter values.

        Returns:
            A mapping whose every leaf is a string, integer, boolean or list.
        """
        return {
            "operation": self.operation,
            "method": self.method.value,
            "path": self.path,
            "query": self.parameters.as_record(),
            "body": self.body.as_record() if self.body else None,
            "header_names": sorted(name for name, _ in self.headers),
            "encoding": self.encoding.value,
            "schema_reference": (
                self.schema_reference.as_record() if self.schema_reference else None
            ),
            "time_unit": self.time_unit.value,
            "side_effect": self.side_effect.value,
            "intent": self.intent.value,
        }


@dataclass(frozen=True, slots=True)
class RateLimitReport:
    """What the venue said about GLOBIN's consumption, extracted rather than guessed.

    Every field is typed and named. The alternative — leaving these in a raw header
    map — is what the brief forbids, and for a concrete reason: Phase 042's governor
    has to read them, and a governor that re-parses strings out of a dictionary is a
    second parser for the same fact.

    ``used_weight`` and ``order_count`` are mappings because the venue publishes one
    header *per interval*, with the interval encoded in the header name. Which
    intervals exist is the venue's business, so they are keys rather than fields.

    **Nothing here enforces anything.** Phase 041 records documented weights and
    Phase 042 builds the governor. This observes.
    """

    retry_after_seconds: int | None = None
    used_weight: tuple[tuple[str, int], ...] = ()
    order_count: tuple[tuple[str, int], ...] = ()

    def as_record(self) -> dict[str, object]:
        """This report as plain JSON-safe values."""
        return {
            "retry_after_seconds": self.retry_after_seconds,
            "used_weight": dict(self.used_weight),
            "order_count": dict(self.order_count),
        }


@dataclass(frozen=True, slots=True)
class RestTiming:
    """How long an exchange took, in integer nanoseconds.

    Integers rather than floats, matching ``docs/engineering/RUNTIME_TELEMETRY.md``'s
    rule that every telemetry value is an integer with a ``2**53`` ceiling — which
    is not Python's limit but every other JSON reader's.
    """

    elapsed_nanoseconds: int = 0

    def __post_init__(self) -> None:
        """Refuse a negative duration, which would mean a clock went backwards."""
        if self.elapsed_nanoseconds < 0:
            msg = f"an elapsed duration is negative: {self.elapsed_nanoseconds}"
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This timing as plain JSON-safe values."""
        return {"elapsed_nanoseconds": self.elapsed_nanoseconds}


@dataclass(frozen=True, slots=True)
class SbeEnvelope:
    """An SBE payload, carried and not read.

    Raises:
        ValidationError: On a payload above :data:`MAX_RESPONSE_BYTES`.

    Opaque by construction. There is no accessor that returns a decoded field,
    because there is no decoder — :class:`~globin.ports.rest.SbeDecoder` is an
    interface Phase 047 may implement. What this guarantees today is the thing that
    matters: binary bytes reach a caller labelled as binary, and never reach a JSON
    parser that would report a syntax error about them.
    """

    payload: bytes
    schema_reference: SbeSchemaReference | None = None

    def __post_init__(self) -> None:
        """Refuse a payload nothing is bounding."""
        if len(self.payload) > MAX_RESPONSE_BYTES:
            msg = (
                f"an SBE payload is {len(self.payload)} bytes and the limit is {MAX_RESPONSE_BYTES}"
            )
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This envelope as plain JSON-safe values, with no payload included."""
        return {
            "byte_count": len(self.payload),
            "schema_reference": (
                self.schema_reference.as_record() if self.schema_reference else None
            ),
        }


@dataclass(frozen=True, slots=True)
class ExchangeFault:
    """What the venue said when it refused, in its own vocabulary.

    Raises:
        ValidationError: On a code of :data:`NO_EXCHANGE_CODE`, which would mean a
            fault that reports no fault.

    Phase 044 maps every documented code to the internal taxonomy. This carries the
    code and the message so that mapping has something to map, and does not
    interpret either.
    """

    code: int
    message: str = ""

    def __post_init__(self) -> None:
        """Refuse a fault that names no code."""
        if self.code == NO_EXCHANGE_CODE:
            msg = "an exchange fault carries no code"
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This fault as plain JSON-safe values.

        Returns:
            The code and the message. The message is the venue's own text and
            carries no credential, but it is truncated for the same reason a body
            is: it is external input reaching a log.
        """
        return {"code": self.code, "message": self.message[:MAX_LOGGED_BODY_BYTES]}


@dataclass(frozen=True, slots=True)
class RestOutcomeInputs:
    """Everything :func:`classify` reads, gathered so the rule can be tested alone.

    A record rather than five arguments because the classification is the security
    property of this phase, and a property worth a contract test is worth a value
    the test can build without constructing a whole exchange.
    """

    side_effect: SideEffect
    send_state: SendState
    status: int = NO_STATUS
    exchange_code: int = NO_EXCHANGE_CODE
    answer_understood: bool = True
    """Whether the body was decoded into something GLOBIN can act on.

    A 200 whose body did not parse tells GLOBIN that *something* happened and not
    what, which for a mutating request is exactly :attr:`RequestOutcome.UNKNOWN`.
    Defaulting to ``True`` keeps every read-only construction short.

    **Consulted only for a 2xx, and that is a correction rather than an
    optimisation.** Checking it first made a 403 carrying a firewall's HTML page
    report :attr:`RequestOutcome.UNKNOWN` for a mutating request — but Binance
    documents 403 as a WAF violation, which is a refusal at the edge before anything
    reached a matching engine. The status was a complete answer and the body was
    decoration, so treating an unreadable body as uncertainty manufactured doubt
    where the venue had left none. On a non-2xx the status settles it; on a 2xx it
    does not, because *the request was accepted* and *what it did* are different
    questions.
    """

    def as_record(self) -> dict[str, object]:
        """These inputs as plain JSON-safe values."""
        return {
            "side_effect": self.side_effect.value,
            "send_state": self.send_state.value,
            "status": self.status,
            "exchange_code": self.exchange_code,
            "answer_understood": self.answer_understood,
        }


def classify(inputs: RestOutcomeInputs) -> RequestOutcome:
    """Decide what GLOBIN knows about an operation's fate.

    Args:
        inputs: The exchange, reduced to what the decision turns on.

    Returns:
        The outcome.

    The whole rule, in the order it is evaluated:

    1. GLOBIN refused → :attr:`RequestOutcome.REJECTED_BEFORE_SEND`.
    2. The bytes never left → :attr:`RequestOutcome.NOT_SENT`.
    3. The bytes left and no complete answer arrived → ambiguous if anything was at
       stake, otherwise a confirmed failure.
    4. A complete answer arrived carrying an ambiguous venue code → same split.
    5. A complete answer arrived that GLOBIN could not read → same split.
    6. A 2xx carrying no venue code → :attr:`RequestOutcome.SUCCESS_CONFIRMED`.
       A 2xx carrying one is the venue refusing inside a successful envelope, which
       some documented batch endpoints do, and is a confirmed failure.
    7. An ambiguous status → same split.
    8. Anything else → :attr:`RequestOutcome.FAILURE_CONFIRMED`.

    **"At stake" is the only place the side effect is consulted**, and it is
    consulted five times. A read-only request never returns
    :attr:`RequestOutcome.UNKNOWN` from this function, which is not an optimisation
    — it is the statement that there is nothing at the venue to be uncertain about.
    """
    if inputs.send_state is SendState.REFUSED:
        return RequestOutcome.REJECTED_BEFORE_SEND
    if inputs.send_state is SendState.NOT_SENT:
        return RequestOutcome.NOT_SENT
    at_stake = inputs.side_effect is not SideEffect.READ_ONLY
    ambiguous = RequestOutcome.UNKNOWN if at_stake else RequestOutcome.FAILURE_CONFIRMED
    if inputs.send_state is SendState.SENT:
        return ambiguous
    if inputs.exchange_code in AMBIGUOUS_EXCHANGE_CODES:
        return ambiguous
    if SUCCESS_STATUS_FLOOR <= inputs.status < SUCCESS_STATUS_CEILING:
        if not inputs.answer_understood:
            return ambiguous
        if inputs.exchange_code != NO_EXCHANGE_CODE:
            return RequestOutcome.FAILURE_CONFIRMED
        return RequestOutcome.SUCCESS_CONFIRMED
    if inputs.status in AMBIGUOUS_STATUSES:
        return ambiguous
    return RequestOutcome.FAILURE_CONFIRMED


@dataclass(frozen=True, slots=True)
class RestResponse:
    """What came back, normalised, with the venue's own verdict kept separate.

    ``fault`` being set does not make this a transport failure. The exchange
    completed; the venue answered; the answer was a refusal. That distinction is the
    one ``globin.errors`` draws between :class:`~globin.errors.ExchangeError` and
    :class:`~globin.errors.TransportError`, and it is drawn here because collapsing
    it is how a system convinces itself an order failed when it did not.
    """

    status: int
    shape: BodyShape
    outcome: RequestOutcome
    payload: object = None
    binary: SbeEnvelope | None = None
    fault: ExchangeFault | None = None
    rate_limits: RateLimitReport | None = None
    timing: RestTiming | None = None
    encoding: ResponseEncoding = ResponseEncoding.JSON
    content_type: str = ""

    @property
    def limits(self) -> RateLimitReport:
        """What the venue said about consumption, whether or not it said anything.

        Returns:
            The report, or an empty one. An empty report is *the venue sent no
            limit headers*, which is not the same as a limit of zero — every field
            in it is absent rather than nought.
        """
        return self.rate_limits or RateLimitReport()

    def as_record(self) -> dict[str, object]:
        """This response as plain JSON-safe values, carrying no payload.

        Returns:
            Status, shape, outcome, the venue's fault if any, the rate-limit report
            and the timing. **The decoded payload is deliberately absent**: it is
            the answer to a query and may be large, and a diagnostic record is not
            where a caller reads a result.
        """
        return {
            "status": self.status,
            "shape": self.shape.value,
            "outcome": self.outcome.value,
            "encoding": self.encoding.value,
            "content_type": self.content_type,
            "fault": self.fault.as_record() if self.fault else None,
            "binary": self.binary.as_record() if self.binary else None,
            "rate_limits": self.limits.as_record(),
            "timing": (self.timing or RestTiming()).as_record(),
        }


@dataclass(frozen=True, slots=True)
class RestDiagnosticsRecord:
    """One exchange, reduced to what may safely be written down.

    Raises:
        ValidationError: On an empty correlation id, which would make an event
            impossible to tie to its neighbours.

    Every field here is either GLOBIN's own vocabulary or a number. **No URL, no
    query string, no header value and no body appears**, which is what makes this
    safe by construction rather than safe by remembering to redact —
    ``globin.domain.observability.redact`` is a second line of defence over a record
    that already carries nothing sensitive.

    ``host`` is the resolved endpoint's hostname and is the one venue-derived string
    here. It arrives from Phase 033's registry at runtime and is never a literal, so
    the architecture rule forbidding a spelled host is unaffected.
    """

    correlation_id: str
    operation: str
    family: str
    environment: str
    role: str
    host: str
    method: str
    intent: str
    side_effect: str
    encoding: str
    time_unit: str
    send_state: str
    outcome: str
    status: int = NO_STATUS
    exchange_code: int = NO_EXCHANGE_CODE
    failure: str = ""
    response_bytes: int = 0
    elapsed_nanoseconds: int = 0
    rate_limits: RateLimitReport | None = None

    def __post_init__(self) -> None:
        """Refuse a record nothing could be correlated with."""
        if not self.correlation_id:
            msg = "a REST diagnostic record carries no correlation id"
            raise ValidationError(msg)

    @property
    def limits(self) -> RateLimitReport:
        """What the venue said about consumption, whether or not it said anything.

        Returns:
            The report, or an empty one.
        """
        return self.rate_limits or RateLimitReport()

    def as_record(self) -> dict[str, object]:
        """This record as plain JSON-safe values."""
        return {
            "correlation_id": self.correlation_id,
            "operation": self.operation,
            "family": self.family,
            "environment": self.environment,
            "role": self.role,
            "host": self.host,
            "method": self.method,
            "intent": self.intent,
            "side_effect": self.side_effect,
            "encoding": self.encoding,
            "time_unit": self.time_unit,
            "send_state": self.send_state,
            "outcome": self.outcome,
            "status": self.status,
            "exchange_code": self.exchange_code,
            "failure": self.failure,
            "response_bytes": self.response_bytes,
            "elapsed_nanoseconds": self.elapsed_nanoseconds,
            "rate_limits": self.limits.as_record(),
        }


@dataclass(frozen=True, slots=True)
class RestExchange:
    """One completed attempt at a request, however far it got.

    Raises:
        ValidationError: If a successful outcome carries no response, or a
            transport failure carries one.

    **This is returned, never raised, and that is a security decision rather than a
    style one.** An exception is read as *this did not happen*: every caller writes
    ``except TransportError`` and treats the body as the failure path. But
    :attr:`RequestOutcome.UNKNOWN` is exactly the state that is **not** a failure —
    a mutating request whose answer never arrived may well have taken effect — so
    raising it would hand every caller a mechanism for quietly destroying the one
    fact this phase exists to preserve.

    ``globin.errors.TransportError`` and ``globin.errors.ExchangeError`` therefore
    remain for what they were always for: a caller that has read this exchange and
    decided to escalate. The transport itself raises neither.
    """

    operation: str
    outcome: RequestOutcome
    send_state: SendState
    diagnostics: RestDiagnosticsRecord
    response: RestResponse | None = None
    failure: TransportFailureKind | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        """Refuse an exchange that reports one thing and carries another."""
        if self.outcome is RequestOutcome.SUCCESS_CONFIRMED and self.response is None:
            msg = "an exchange reports confirmed success and carries no response"
            raise ValidationError(msg)
        if self.failure is not None and self.response is not None:
            msg = (
                f"an exchange carries both a {self.failure.value} failure and a response; "
                "a transport fault means no answer was understood"
            )
            raise ValidationError(msg)
        if self.failure is not None and not self.detail:
            msg = f"an exchange reports a {self.failure.value} failure and explains nothing"
            raise ValidationError(msg)

    @property
    def at_risk(self) -> bool:
        """Whether something may have happened at the venue that GLOBIN cannot see.

        Returns:
            ``True`` only for :attr:`RequestOutcome.UNKNOWN`.

        A named property rather than a comparison callers write themselves, so that
        the check reads the same everywhere and a search for it finds every site.
        """
        return self.outcome is RequestOutcome.UNKNOWN

    def as_record(self) -> dict[str, object]:
        """This exchange as plain JSON-safe values."""
        return {
            "operation": self.operation,
            "outcome": self.outcome.value,
            "send_state": self.send_state.value,
            "at_risk": self.at_risk,
            "failure": self.failure.value if self.failure else None,
            "detail": self.detail,
            "response": self.response.as_record() if self.response else None,
            "diagnostics": self.diagnostics.as_record(),
        }


ACCEPT_HEADER: Final[str] = "Accept"
"""The header GLOBIN states its preferred response encoding in."""

MEDIA_TYPE_JSON: Final[str] = "application/json"
"""The media type of a JSON response, and what GLOBIN asks for by default."""

MEDIA_TYPE_SBE: Final[str] = "application/sbe"
"""The media type that requests a Simple Binary Encoding response.

Verbatim from Binance's own SBE FAQ: ``"Accept: application/sbe"``. Recorded with
provenance in ``docs/engineering/rest-transport.toml`` and compared against this
constant by ``tests/contract/test_rest_contract.py``, so the two cannot drift.
"""

MEDIA_TYPE_HTML: Final[str] = "text/html"
"""What a firewall's refusal arrives as, on an endpoint that only ever sends JSON."""

MEDIA_TYPE_TEXT_PREFIX: Final[str] = "text/"
"""What an intermediary's plain-text error arrives as."""

SBE_SCHEMA_HEADER: Final[str] = "X-MBX-SBE"
"""The header naming which SBE schema GLOBIN can decode.

Its documented value format is ``<ID>:<VERSION>``, which is character for character
what :attr:`~globin.domain.api_reality.SchemaVersion.label` already renders. Phase
033 recorded the venue's changelog spelling and this phase discovered it was also
the wire format, so no second renderer was written.
"""

TIME_UNIT_HEADER: Final[str] = "X-MBX-TIME-UNIT"
"""The header requesting a non-default timestamp unit."""

TIME_UNIT_MICROSECOND: Final[str] = "MICROSECOND"
"""The one value this header is documented to accept. **Singular, not plural.**

Binance's words are: *"To receive the information in microseconds, please add the
header ``X-MBX-TIME-UNIT:MICROSECOND`` or ``X-MBX-TIME-UNIT:microsecond``."*

**There is deliberately no millisecond constant beside this one.** The
documentation states that responses are *"in milliseconds by default"* and never
lists a header value that selects them, so ``MILLISECOND`` is a spelling GLOBIN
would be inventing. ``docs/SOURCE_POLICY.md`` forbids exactly that, and the
consequence is visible in :func:`negotiation_headers`:
:attr:`TimeUnitPreference.MILLISECONDS` sends **no header**, because asking for the
documented default is the same act as not asking.
"""

RETRY_AFTER_HEADER: Final[str] = "Retry-After"
"""How long the venue asks GLOBIN to wait. Read and recorded; never obeyed here.

Phase 042 builds the governor that acts on it. A transport that slept on this
header would be a rate limiter nobody declared.
"""

USED_WEIGHT_PREFIX: Final[str] = "X-MBX-USED-WEIGHT-"
"""What precedes the interval in a used-weight header.

Binance documents the whole name as ``X-MBX-USED-WEIGHT-(intervalNum)(intervalLetter)``
— so the interval is part of the *header name*, which is why
:class:`RateLimitReport` carries a mapping rather than a field. A fixed field would
have had to guess which intervals the venue publishes.
"""

ORDER_COUNT_PREFIX: Final[str] = "X-MBX-ORDER-COUNT-"
"""What precedes the interval in an order-count header.

Documented as ``X-MBX-ORDER-COUNT-(intervalNum)(intervalLetter)``, exactly as above.
"""

USER_AGENT_HEADER: Final[str] = "User-Agent"
"""The header identifying GLOBIN to the venue."""

USER_AGENT: Final[str] = "GLOBIN"
"""How GLOBIN identifies itself.

Deliberately carries no version, no host name and no account identifier. A user
agent is sent to a third party on every request, so it is the cheapest possible
place to leak which build an operator runs.
"""


def negotiation_headers(request: RestRequest) -> tuple[tuple[str, str], ...]:
    """The headers a request's declared preferences turn into.

    Args:
        request: The request.

    Returns:
        Header name and value pairs, sorted by name so two identical requests
        produce byte-identical header sets — which is what makes a canonical
        request canonical.

    Raises:
        ValidationError: If SBE is asked for without a schema reference. The request
            type already refuses that combination; this is the second assertion, at
            the point the header would have been written.

    **When SBE is asked for, ``application/json`` is deliberately not offered
    alongside it.** Binance documents that an ``Accept`` naming both media types
    *"will fall back to JSON"* when the schema is unsupported — a silent downgrade
    that would hand GLOBIN a JSON body while its own record said SBE. Offering one
    media type removes the downgrade from existence: an unsupported schema then
    produces an SBE-encoded error, which GLOBIN reports as a binary answer it cannot
    read rather than misreading as a success.
    """
    headers: list[tuple[str, str]] = [(USER_AGENT_HEADER, USER_AGENT)]
    if request.encoding is ResponseEncoding.SBE:
        if request.schema_reference is None:
            msg = "a request asks for SBE and names no schema; the venue cannot answer"
            raise ValidationError(msg)
        headers.append((ACCEPT_HEADER, MEDIA_TYPE_SBE))
        headers.append(
            (
                SBE_SCHEMA_HEADER,
                f"{request.schema_reference.identifier}:{request.schema_reference.version}",
            )
        )
    else:
        headers.append((ACCEPT_HEADER, MEDIA_TYPE_JSON))
    if request.time_unit is TimeUnitPreference.MICROSECONDS:
        headers.append((TIME_UNIT_HEADER, TIME_UNIT_MICROSECOND))
    if request.body is not None:
        headers.append(("Content-Type", request.body.content_type))
    headers.extend(request.headers)
    return tuple(sorted(headers))
