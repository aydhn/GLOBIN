"""What GLOBIN calls things: the canonical form of every kind of identifier.

A system that names the same thing two ways has two things. ``spot`` and
``SPOT`` are one product spelled twice, ``BTC/USDT`` and ``BTCUSDT`` are one
market spelled twice, and a report grouped by either spelling is wrong in a way
that looks right. This module fixes one spelling per kind and refuses the rest.

Six kinds are registered, and :class:`IdentifierKind` is the list of them.
:func:`specification` answers what each one's canonical form is, in one place,
so that "canonical" is a fact with an address rather than a habit.

**The registry is load-bearing, not descriptive.** Every type below validates
itself by calling :func:`specification`. A registry that merely described the
types alongside them would be a second copy of the rules, free to drift from the
first — the failure ``docs/engineering/SOURCE_OF_TRUTH.md`` names. Here there is
nothing to drift: the description *is* the implementation.

**Kinds are registered; instances are not.** :class:`ProductId` accepts
``product_id("nosuchproduct")`` for the same reason ``Currency("ZZZQ")``
succeeds in :mod:`globin.domain.values`: which products a venue offers is a
capability question answered against the venue (ADR-0006), never a constant
compiled into the domain layer. This module bounds *shape*. Which products exist
is **Phase 033**, what an environment is is **Phase 035**, the capability matrix
is **Phase 036**, and the instrument register is **Phases 049-050**.

Three things remain deliberately absent.

*There is no symbol identifier type.* :class:`~globin.domain.values.Symbol`
already is one, and a second would be the duplicate
``docs/engineering/DEFINITION_OF_DONE.md`` forbids. Instead
:attr:`IdentifierKind.SYMBOL`'s specification is *derived* from that module's
constants, and ``tests/contract/test_identifier_contract.py`` holds a rendered
symbol against it. Deriving rather than restating is why no tripwire is needed.

*There is no wire format.* A canonical identifier is what GLOBIN calls a thing
among its own components. What Binance calls it, and what it will accept in a
request, arrive with **Phases 033-048**. The two are not assumed equal anywhere.

*There is no minting.* Generating an identifier reads a source of randomness,
which ADR-0026 places in the adapters layer beside the clock. Shape is checked
here; :func:`globin.adapters.identifiers.new_run_id` produces one.

This module imports nothing outside :mod:`globin.errors` and
:mod:`globin.domain.values`, performs no I/O and holds no module-level call.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.domain.values import (
    CURRENCY_ALPHABET,
    MAX_CURRENCY_CODE_LENGTH,
    MIN_CURRENCY_CODE_LENGTH,
    SYMBOL_SEPARATOR,
)
from globin.errors import InternalError, ValidationError

NAME_ALPHABET: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789._"
"""The characters a lowercase dotted identifier may contain.

Products, environments and models are named by people and read by machines, so
they get the narrowest alphabet that still expresses a hierarchy: lowercase
letters, digits, a dot to separate levels and an underscore to join words within
one. Uppercase is refused rather than folded, for the reason
:data:`~globin.domain.values.CURRENCY_ALPHABET` gives — one spelling means one
thing to search a log for.

This is the same alphabet as
:data:`~globin.domain.observability.EVENT_NAME_ALPHABET` and is deliberately not
shared with it. An event name and a product identifier answer to different
phases and may legitimately diverge; binding them together now would make one
phase's decision silently constrain another's. The resemblance is convergence,
not duplication, and there is no test comparing them because they are not
required to agree.
"""

OPAQUE_ALPHABET: Final[str] = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
"""The characters an externally round-tripped identifier may contain.

Wider than :data:`NAME_ALPHABET`, and mixed case, because an order identifier
has to survive a journey through somebody else's system and come back
unchanged. Case folding it would be GLOBIN deciding that two distinct
identifiers are one, which is exactly the collision this module exists to
prevent.

The set is the unreserved characters of RFC 3986 minus the tilde and full stop:
every member survives a URL path, a query string, a JSON string and a Windows
filename without escaping. What a venue will actually accept is narrower and is
**Phases 033-048** to establish; this is a bound on GLOBIN's own shape, not a
claim about Binance.
"""

HEX_ALPHABET: Final[str] = "0123456789abcdef"
"""The characters a minted identifier may contain.

Lowercase only, because :meth:`uuid.UUID.hex` is documented to render lowercase
and accepting both spellings would make one run appear to be two.
"""

MIN_NAME_LENGTH: Final[int] = 2
"""The shortest a lowercase dotted identifier may be.

Two for the reason :data:`~globin.domain.values.MIN_CURRENCY_CODE_LENGTH` gives:
a single character is far more often a slicing bug than a name.
"""

MAX_NAME_LENGTH: Final[int] = 64
"""The longest a lowercase dotted identifier may be.

A bound on shape rather than a judgement about naming. Sixty-four leaves room
for a three-level name with descriptive segments and still fits a log column, a
directory name and a database column of the size Phase 012 will choose.
"""

MIN_OPAQUE_LENGTH: Final[int] = 4
"""The shortest an externally round-tripped identifier may be.

Longer than :data:`MIN_NAME_LENGTH` because an identifier that crosses a system
boundary and comes back has to be recognisable in somebody else's logs as well
as in GLOBIN's.
"""

MAX_OPAQUE_LENGTH: Final[int] = 64
"""The longest an externally round-tripped identifier may be.

Deliberately equal to :data:`MAX_NAME_LENGTH`, so that no caller has to
remember which limit applies to which kind. If a venue turns out to impose a
shorter one, Phases 033-048 record that against the venue rather than narrowing
this.
"""

RUN_ID_LENGTH: Final[int] = 32
"""How long a minted run identifier is, exactly.

Thirty-two hexadecimal characters, which is what :meth:`uuid.UUID.hex` produces.
The length is fixed rather than bounded because the value has one producer:
anything else of a different length did not come from
:func:`globin.adapters.identifiers.new_run_id` and should be refused rather than
tolerated.

Equal to the length :func:`globin.adapters.observability.new_correlation_id`
produces, and that alignment is intended: a run and the log records made during
it are the same kind of token, so a reader comparing them is comparing like with
like.
"""


class IdentifierKind(StrEnum):
    """The kinds of thing GLOBIN gives a canonical name.

    The roadmap's Phase 011 names six, and this enumeration is that list. A
    seventh is a visible, reviewable change to this type rather than an
    unnoticed string literal in a later phase — the argument
    :class:`~globin.project_contract.ExchangeScope` makes for the same shape.
    """

    SYMBOL = "SYMBOL"
    """A market: one asset priced in another.

    Carried by :class:`~globin.domain.values.Symbol`, which predates this
    module. There is no second type for it.
    """

    PRODUCT = "PRODUCT"
    """A venue surface with its own endpoints, semantics and limits.

    Which products exist is Phase 033; this bounds what one may be called.
    """

    ENVIRONMENT = "ENVIRONMENT"
    """A deployment target a product may be reached through.

    What an environment *is* — and what it guarantees — is Phase 035. ADR-0006
    already refuses to treat "not production" as a single thing, and naming an
    environment is not the same as classifying one.
    """

    RUN = "RUN"
    """One execution of GLOBIN doing a piece of work.

    The only kind GLOBIN mints itself. See
    :func:`globin.adapters.identifiers.new_run_id`.
    """

    MODEL = "MODEL"
    """A trained artefact that produces predictions.

    Naming one is this phase. Training, versioning and lineage are Phases 097
    and beyond, and nothing here presumes their shape.
    """

    ORDER = "ORDER"
    """An instruction GLOBIN sends a venue.

    Named here so that a later phase has a form to use rather than inventing
    one under deadline. Nothing in this repository places an order: execution
    is Phases 081-096.
    """


@dataclass(frozen=True, slots=True)
class IdentifierSpec:
    """The canonical form of one kind of identifier.

    Args:
        kind: Which kind this describes.
        alphabet: Every character the identifier may contain.
        min_length: The shortest permitted, inclusive.
        max_length: The longest permitted, inclusive. Equal to ``min_length``
            where the length is fixed.
        summary: One line naming what the identifier denotes, for a document
            that reads the registry rather than restating it.

    Built by :func:`specification` and never at import: a layer package performs
    no call while being imported, which ``tests/architecture/test_architecture_contract.py``
    enforces and which rules out a module-level table of these.
    """

    kind: IdentifierKind
    alphabet: str
    min_length: int
    max_length: int
    summary: str


def specifications() -> tuple[IdentifierSpec, ...]:
    """Return every registered specification, in :class:`IdentifierKind` order.

    Returns:
        One specification per kind, in the order the members are declared.

    This is the registry. It is a function rather than a constant because
    building an :class:`IdentifierSpec` is a call, and a layer package may
    perform none at import.

    The :attr:`IdentifierKind.SYMBOL` entry is *derived* from
    :mod:`globin.domain.values` rather than restating it. A symbol renders as
    two currency codes around :data:`~globin.domain.values.SYMBOL_SEPARATOR`, so
    its alphabet and its bounds are that module's, arithmetic included. Restating
    them would be a second copy free to drift; deriving them cannot.
    """
    return (
        IdentifierSpec(
            kind=IdentifierKind.SYMBOL,
            alphabet=CURRENCY_ALPHABET + SYMBOL_SEPARATOR,
            min_length=2 * MIN_CURRENCY_CODE_LENGTH + len(SYMBOL_SEPARATOR),
            max_length=2 * MAX_CURRENCY_CODE_LENGTH + len(SYMBOL_SEPARATOR),
            summary="A market, rendered as base, separator and quote.",
        ),
        IdentifierSpec(
            kind=IdentifierKind.PRODUCT,
            alphabet=NAME_ALPHABET,
            min_length=MIN_NAME_LENGTH,
            max_length=MAX_NAME_LENGTH,
            summary="A venue surface with its own endpoints and limits.",
        ),
        IdentifierSpec(
            kind=IdentifierKind.ENVIRONMENT,
            alphabet=NAME_ALPHABET,
            min_length=MIN_NAME_LENGTH,
            max_length=MAX_NAME_LENGTH,
            summary="A deployment target a product may be reached through.",
        ),
        IdentifierSpec(
            kind=IdentifierKind.RUN,
            alphabet=HEX_ALPHABET,
            min_length=RUN_ID_LENGTH,
            max_length=RUN_ID_LENGTH,
            summary="One execution of GLOBIN doing a piece of work.",
        ),
        IdentifierSpec(
            kind=IdentifierKind.MODEL,
            alphabet=NAME_ALPHABET,
            min_length=MIN_NAME_LENGTH,
            max_length=MAX_NAME_LENGTH,
            summary="A trained artefact that produces predictions.",
        ),
        IdentifierSpec(
            kind=IdentifierKind.ORDER,
            alphabet=OPAQUE_ALPHABET,
            min_length=MIN_OPAQUE_LENGTH,
            max_length=MAX_OPAQUE_LENGTH,
            summary="An instruction GLOBIN sends a venue.",
        ),
    )


def specification(kind: IdentifierKind) -> IdentifierSpec:
    """Return the canonical rules for one kind of identifier.

    Args:
        kind: Which kind to describe.

    Returns:
        Its specification.

    Raises:
        InternalError: If ``kind`` has no entry. A member of
            :class:`IdentifierKind` without one means this module was edited in
            half, which is a GLOBIN defect rather than a caller's mistake.
    """
    for spec in specifications():
        if spec.kind == kind:
            return spec
    msg = (
        f"identifier kind {kind!r} has no specification; every member of "
        f"IdentifierKind must be registered in specifications()"
    )
    raise InternalError(msg)


def satisfies(text: object, spec: IdentifierSpec) -> bool:
    """Report whether ``text`` is in the canonical form ``spec`` describes.

    Args:
        text: The candidate rendering. Typed as :class:`object` for the reason
            :func:`~globin.domain.values._require` gives: a parameter typed as
            :class:`str` would make the check below redundant to mypy, and mypy
            is configured to say so.
        spec: The rules to judge it against.

    Returns:
        Whether the text is the right length and drawn from the right alphabet.

    Answers rather than refuses, which is what lets a test hold a value built by
    another module against this registry without catching an exception to find
    out. The types below refuse; this reports.
    """
    if not isinstance(text, str):
        return False
    if not spec.min_length <= len(text) <= spec.max_length:
        return False
    return not set(text) - set(spec.alphabet)


def _validate(text: object, *, kind: IdentifierKind) -> None:
    """Refuse text that is not the canonical form for ``kind``.

    Args:
        text: What was supplied. Typed as :class:`object` because a caller
            constructing a dataclass directly can pass anything, and the
            annotation on the field is not a check.
        kind: Which specification to judge it against.

    Raises:
        ValidationError: On the first rule the text breaks.

    Length is tested before the alphabet so that the commonest mistake — an
    empty string — is named as a length problem rather than reported as
    containing nothing wrong.
    """
    spec = specification(kind)
    if not isinstance(text, str):
        msg = (
            f"{kind.lower()} identifier is {type(text).__name__}; "
            f"construct it through the matching factory, which refuses in one place"
        )
        raise ValidationError(msg)
    if not spec.min_length <= len(text) <= spec.max_length:
        expected = (
            f"exactly {spec.min_length}"
            if spec.min_length == spec.max_length
            else f"between {spec.min_length} and {spec.max_length}"
        )
        msg = f"{kind.lower()} identifier {text!r} is {len(text)} characters; expected {expected}"
        raise ValidationError(msg)
    stray = sorted(set(text) - set(spec.alphabet))
    if stray:
        msg = (
            f"{kind.lower()} identifier {text!r} contains {stray}; "
            f"permitted characters are {spec.alphabet!r}"
        )
        raise ValidationError(msg)


@dataclass(frozen=True, slots=True)
class ProductId:
    """The canonical name of a venue surface.

    Args:
        text: A lowercase dotted identifier, such as ``"spot"``.

    Raises:
        ValidationError: If ``text`` is outside the length bounds or contains a
            character outside :data:`NAME_ALPHABET`.

    A well-formed name no venue offers is still a :class:`ProductId`. Which
    products exist is Phase 033, and compiling that list into the domain layer
    would make a capability question look like a shape one.
    """

    text: str

    def __post_init__(self) -> None:
        """Validate the text against the product specification."""
        _validate(self.text, kind=IdentifierKind.PRODUCT)

    def __str__(self) -> str:
        """Return the identifier itself."""
        return self.text


@dataclass(frozen=True, slots=True)
class EnvironmentId:
    """The canonical name of a deployment target.

    Args:
        text: A lowercase dotted identifier, such as ``"production"``.

    Raises:
        ValidationError: If ``text`` is outside the length bounds or contains a
            character outside :data:`NAME_ALPHABET`.

    Naming an environment is not classifying one. ADR-0006 refuses to treat
    "not production" as a single thing, and Phase 035 models the classes and
    their guarantees. This type carries a name and asserts nothing about what
    the name promises.
    """

    text: str

    def __post_init__(self) -> None:
        """Validate the text against the environment specification."""
        _validate(self.text, kind=IdentifierKind.ENVIRONMENT)

    def __str__(self) -> str:
        """Return the identifier itself."""
        return self.text


@dataclass(frozen=True, slots=True)
class RunId:
    """The identifier of one execution of GLOBIN doing a piece of work.

    Args:
        text: Exactly :data:`RUN_ID_LENGTH` lowercase hexadecimal characters.

    Raises:
        ValidationError: If ``text`` is the wrong length or contains a character
            outside :data:`HEX_ALPHABET`.

    The length is fixed rather than bounded because this kind has exactly one
    producer. See :func:`globin.adapters.identifiers.new_run_id`, which lives in
    the adapters layer because generating one reads a source of randomness
    (ADR-0026).
    """

    text: str

    def __post_init__(self) -> None:
        """Validate the text against the run specification."""
        _validate(self.text, kind=IdentifierKind.RUN)

    def __str__(self) -> str:
        """Return the identifier itself."""
        return self.text


@dataclass(frozen=True, slots=True)
class ModelId:
    """The canonical name of a trained artefact.

    Args:
        text: A lowercase dotted identifier.

    Raises:
        ValidationError: If ``text`` is outside the length bounds or contains a
            character outside :data:`NAME_ALPHABET`.

    Carries a name and no version. A model's version, its training data and its
    lineage are Phases 097 and beyond, and giving this type a version field now
    would be this phase guessing their shape.
    """

    text: str

    def __post_init__(self) -> None:
        """Validate the text against the model specification."""
        _validate(self.text, kind=IdentifierKind.MODEL)

    def __str__(self) -> str:
        """Return the identifier itself."""
        return self.text


@dataclass(frozen=True, slots=True)
class OrderId:
    """The identifier of an instruction GLOBIN sends a venue.

    Args:
        text: A bounded token drawn from :data:`OPAQUE_ALPHABET`.

    Raises:
        ValidationError: If ``text`` is outside the length bounds or contains a
            character outside :data:`OPAQUE_ALPHABET`.

    Case is significant, because an order identifier crosses a system boundary
    and comes back, and folding it would merge two distinct orders into one.

    Nothing in this repository places an order. This type exists so that
    Phases 081-096 inherit a form rather than inventing one, and what a venue
    will accept is narrower and belongs to Phases 033-048.
    """

    text: str

    def __post_init__(self) -> None:
        """Validate the text against the order specification."""
        _validate(self.text, kind=IdentifierKind.ORDER)

    def __str__(self) -> str:
        """Return the identifier itself."""
        return self.text


def product_id(text: str) -> ProductId:
    """Build a :class:`ProductId`.

    Args:
        text: A lowercase dotted identifier.

    Returns:
        The product identifier.

    Raises:
        ValidationError: As :class:`ProductId`.
    """
    return ProductId(text=text)


def environment_id(text: str) -> EnvironmentId:
    """Build an :class:`EnvironmentId`.

    Args:
        text: A lowercase dotted identifier.

    Returns:
        The environment identifier.

    Raises:
        ValidationError: As :class:`EnvironmentId`.
    """
    return EnvironmentId(text=text)


def run_id(text: str) -> RunId:
    """Build a :class:`RunId` from text that already exists.

    Args:
        text: Exactly :data:`RUN_ID_LENGTH` lowercase hexadecimal characters.

    Returns:
        The run identifier.

    Raises:
        ValidationError: As :class:`RunId`.

    This reads an identifier; it does not mint one. Minting is
    :func:`globin.adapters.identifiers.new_run_id`.
    """
    return RunId(text=text)


def model_id(text: str) -> ModelId:
    """Build a :class:`ModelId`.

    Args:
        text: A lowercase dotted identifier.

    Returns:
        The model identifier.

    Raises:
        ValidationError: As :class:`ModelId`.
    """
    return ModelId(text=text)


def order_id(text: str) -> OrderId:
    """Build an :class:`OrderId`.

    Args:
        text: A bounded token drawn from :data:`OPAQUE_ALPHABET`.

    Returns:
        The order identifier.

    Raises:
        ValidationError: As :class:`OrderId`.
    """
    return OrderId(text=text)
