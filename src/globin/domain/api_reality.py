"""What Binance documents it exposes, and how sure GLOBIN is of each claim.

Phase 033's titled scope is the product family inventory. ADR-0086 widened it to
the whole reality registry, and ADR-0087 carries the decisions below.

**This module describes a venue, which nothing before it did.** Every earlier
domain module describes this repository or this host, and is therefore checkable
by looking. A claim here is checkable only against a document somebody read on a
day, which is why :class:`SourceObservation` is required by construction rather
than attached where convenient. A capability with no source is not a weak claim;
it is not a claim.

**No venue instance is named here, and the first draft of this module got that
wrong.** Product families, environments, key permissions and schema families were
written as enumerations, and ``tests/architecture/test_identifier_discipline.py``
refused them -- a rule written in Phase 011 that names Phase 036 as the moment it
would bite. It was right, and the reason is the one that record gives: which
products a venue offers changes without GLOBIN being redeployed, so a tuple
compiled into the innermost layer would be wrong quietly. Those four are now
:class:`ProductFamily`, :class:`EnvironmentName`, :class:`KeyPermission` and
:class:`SchemaFamilyName` -- validated shapes with **no list of known values**,
following :class:`~globin.domain.values.Currency`. Their instances live in
``docs/engineering/binance-api-reality.toml``, which is also where ADR-0087 says
the single copy of a Binance fact belongs.

What remains an enumeration is what **GLOBIN** decides rather than what Binance
offers: a status vocabulary, an evidence kind, a scope, a risk.

**Six status words, and the axis is documentation rather than measurement.**
:class:`~globin.domain.environment.CapabilityStatus` is deliberately not reused:
it answers *what did we measure about this host*, and its ``DEGRADED`` and
``NOT_APPLICABLE`` mean nothing about a remote venue's contract, while
:attr:`SurfaceStatus.DEPRECATED`, :attr:`SurfaceStatus.ANNOUNCED` and
:attr:`SurfaceStatus.RESTRICTED` mean nothing about a host. The two enumerations
share three spellings and no subject.

**The distinction the phase exists for is** :attr:`SurfaceStatus.UNKNOWN`
**against** :attr:`SurfaceStatus.UNSUPPORTED`. Binance publishes a machine-readable
specification for Spot and for no other product family, so most of what this
registry can say about margin, futures, options and portfolio margin is that it
does not know -- and *does not know* must never be read as *does not exist*.

**A FIX endpoint's two encodings are separate fields, and that was measured rather
than assumed.** One documented port takes FIX text and answers in FIX SBE, so a
single ``encoding`` per endpoint cannot describe it
(``docs/research/phase_033_sources.md``, S-05).

**Nothing here performs I/O, and nothing here reaches the venue.** The registry is
parsed by :mod:`globin.adapters.api_reality` because ``tomllib`` is I/O-capable,
and it is refreshed by ``tools/quality/venue`` because no module in this
package may open an outbound connection.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.errors import ValidationError

SCHEMA_VERSION: Final[int] = 1
"""The registry shape this module reads.

A document announcing anything else is refused rather than read anyway, which is
the rule every declared contract in this repository follows.
"""

MAX_TEXT_LENGTH: Final[int] = 240
"""The longest free-text phrase any record may carry.

Semantics, conditions and notes are phrases. The bound is what stops a paragraph
of documentation being pasted into a published record, which is how a registry
becomes a stale copy of the thing it points at.
"""

MIN_SLUG_LENGTH: Final[int] = 2
"""The shortest a family or environment name may be."""

MAX_SLUG_LENGTH: Final[int] = 48
"""The longest a family or environment name may be."""

SLUG_ALPHABET: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789_"
"""What a family or environment name is spelled with.

Lowercase, digits and underscores. No hyphen, no space and no case, so that two
spellings of one family cannot both be declared and silently coexist.
"""

MAX_PERMISSION_LENGTH: Final[int] = 32
"""The longest key permission the venue is assumed to spell."""

PERMISSION_ALPHABET: Final[str] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
"""What a key permission is spelled with.

Uppercase, because that is how Binance writes them and a permission compared
case-insensitively would let two spellings of one grant diverge.
"""

MAX_SOURCES: Final[int] = 64
"""The most sources one snapshot may cite."""

MAX_PRODUCTS: Final[int] = 32
"""The most product families one snapshot may record."""

MAX_SURFACES: Final[int] = 256
"""The most product-and-protocol surfaces one snapshot may record."""

MAX_ENVIRONMENTS: Final[int] = 128
"""The most product-and-environment pairs one snapshot may record."""

MAX_ENDPOINTS: Final[int] = 512
"""The most endpoints one snapshot may record.

Spot alone contributes roughly fifty across three environments, nine of them FIX
per environment. The bound is well above that and exists so a malformed document
cannot produce an unbounded snapshot.
"""

MAX_SCHEMAS: Final[int] = 128
"""The most schema versions one snapshot may record."""

MAX_FINDINGS: Final[int] = 512
"""The most differences one diff may report.

A diff between two unrelated snapshots would otherwise be bounded only by their
sizes multiplied together.
"""

DATE_LENGTH: Final[int] = 10
"""The length of an ISO ``YYYY-MM-DD`` date.

Dates are held as text and validated by shape rather than parsed into
:class:`datetime.date`. Nothing here does arithmetic on them, and a domain module
importing a date library to store a string would be borrowing a clock it never
reads.
"""

DIGEST_PREFIX: Final[str] = "sha256:"
"""What a content digest begins with, spelled as the rest of the repository does."""

DIGEST_LENGTH: Final[int] = 64
"""How many hexadecimal characters follow :data:`DIGEST_PREFIX`."""

HEX_ALPHABET: Final[str] = "0123456789abcdef"
"""What a digest body is spelled with, lowercase so two spellings cannot differ."""

HTTPS_SCHEME: Final[str] = "https://"
"""The only scheme a request-response endpoint may use."""

WEBSOCKET_SCHEME: Final[str] = "wss://"
"""The only scheme a streaming endpoint may use.

The unencrypted spelling is absent deliberately: Binance documents none, and
admitting it would let a plaintext endpoint be recorded without anything noticing.
"""

FIX_SCHEME: Final[str] = "tcp+tls://"
"""The only scheme a FIX endpoint may use, as Binance spells it."""

PERMITTED_SCHEMES: Final[tuple[str, ...]] = (HTTPS_SCHEME, WEBSOCKET_SCHEME, FIX_SCHEME)
"""Every scheme an endpoint may carry, and no fourth.

Each one is encrypted. There is no plaintext member to select by accident.
"""


def _require_text(value: str, *, field: str, limit: int = MAX_TEXT_LENGTH) -> None:
    """Refuse an empty or oversized phrase.

    Args:
        value: The text.
        field: Its name, for the message.
        limit: The longest it may be.

    Raises:
        ValidationError: If it is empty, blank, or longer than ``limit``.
    """
    if not value or not value.strip():
        msg = f"{field} may not be empty"
        raise ValidationError(msg)
    if len(value) > limit:
        msg = f"{field} is {len(value)} characters and the limit is {limit}"
        raise ValidationError(msg)


def _require_date(value: str, *, field: str) -> None:
    """Refuse anything that is not an ISO ``YYYY-MM-DD`` date.

    Args:
        value: The candidate.
        field: Its name, for the message.

    Raises:
        ValidationError: If the shape is wrong.

    Checked by shape rather than parsed. Nothing here does arithmetic on a date,
    and a domain module importing a date library to validate a string it only ever
    writes back out would be carrying a dependency for appearances.
    """
    wrong_shape = len(value) != DATE_LENGTH or value[4] != "-" or value[7] != "-"
    if wrong_shape or not (value[:4] + value[5:7] + value[8:]).isdigit():
        msg = f"{field} must be an ISO YYYY-MM-DD date, and {value!r} is not"
        raise ValidationError(msg)


def _require_digest(value: str, *, field: str) -> None:
    """Refuse anything that is not a lowercase ``sha256:`` hex digest.

    Args:
        value: The candidate.
        field: What it belongs to, for the message.

    Raises:
        ValidationError: If the prefix, length or alphabet is wrong.
    """
    if not value.startswith(DIGEST_PREFIX):
        msg = f"{field} carries a digest that does not begin {DIGEST_PREFIX!r}"
        raise ValidationError(msg)
    body = value[len(DIGEST_PREFIX) :]
    if len(body) != DIGEST_LENGTH or set(body) - set(HEX_ALPHABET):
        msg = (
            f"{field} carries a digest that is not {DIGEST_LENGTH} lowercase hexadecimal characters"
        )
        raise ValidationError(msg)


@dataclass(frozen=True, slots=True, order=True)
class ProductFamily:
    """A product family Binance documents, validated for shape and nothing else.

    Args:
        slug: The family name, such as ``"spot"`` or ``"usds_m_futures"``.

    Raises:
        ValidationError: If the slug is outside the length bounds or contains a
            character outside :data:`SLUG_ALPHABET`.

    **There is deliberately no list of known families here.** Which products a
    venue offers is answered against the venue and changes without GLOBIN being
    redeployed; the instances live in the registry document. This follows
    :class:`~globin.domain.values.Currency`, which refuses a list of known codes
    for the same reason.
    """

    slug: str

    def __post_init__(self) -> None:
        """Validate the slug's length and alphabet."""
        _require_slug(self.slug, field="a product family")

    def __str__(self) -> str:
        """The slug, for a message or a rendered record."""
        return self.slug


@dataclass(frozen=True, slots=True, order=True)
class EnvironmentName:
    """A venue environment, validated for shape and nothing else.

    Args:
        slug: The environment name, such as ``"production"`` or ``"testnet"``.

    Raises:
        ValidationError: If the slug is outside the length bounds or contains a
            character outside :data:`SLUG_ALPHABET`.

    ADR-0006 requires that environment classes are never conflated, and this type
    is what stops one being passed where a product family is wanted. It does
    **not** enumerate them: that record names four classes, Binance documents
    three, and Phase 035 owns the fourth. A registry that could only express what
    this module had been compiled with could not record a new one.
    """

    slug: str

    def __post_init__(self) -> None:
        """Validate the slug's length and alphabet."""
        _require_slug(self.slug, field="an environment name")

    def __str__(self) -> str:
        """The slug, for a message or a rendered record."""
        return self.slug


@dataclass(frozen=True, slots=True, order=True)
class SchemaFamilyName:
    """A published schema lifecycle, validated for shape and nothing else.

    Args:
        slug: The family name, such as ``"spot_sbe"``.

    Raises:
        ValidationError: If the slug is outside the length bounds or contains a
            character outside :data:`SLUG_ALPHABET`.

    Families are kept apart because their identifiers collide: two of Binance's
    lifecycles both number from 1, so ``1:1`` is ambiguous without the family.
    """

    slug: str

    def __post_init__(self) -> None:
        """Validate the slug's length and alphabet."""
        _require_slug(self.slug, field="a schema family")

    def __str__(self) -> str:
        """The slug, for a message or a rendered record."""
        return self.slug


@dataclass(frozen=True, slots=True, order=True)
class KeyPermission:
    """A permission a key may carry, spelled as the venue spells it.

    Args:
        spelling: The permission, uppercase, such as ``"FIX_API"``.

    Raises:
        ValidationError: If the spelling is empty, too long, or contains a character
            outside :data:`PERMISSION_ALPHABET`.

    Shape only, again with no list of known grants. Which permissions exist is the
    venue's to decide, and Phase 039 is what verifies that a key actually holds
    one.
    """

    spelling: str

    def __post_init__(self) -> None:
        """Validate the spelling's length and alphabet."""
        if not self.spelling or len(self.spelling) > MAX_PERMISSION_LENGTH:
            msg = (
                f"a key permission is {len(self.spelling)} characters; expected between "
                f"1 and {MAX_PERMISSION_LENGTH}"
            )
            raise ValidationError(msg)
        stray = sorted(set(self.spelling) - set(PERMISSION_ALPHABET))
        if stray:
            msg = (
                f"key permission {self.spelling!r} contains {stray}; permissions are "
                f"uppercase letters, digits and underscores"
            )
            raise ValidationError(msg)

    def __str__(self) -> str:
        """The spelling, for a message or a rendered record."""
        return self.spelling


def _require_slug(value: str, *, field: str) -> None:
    """Refuse a name that is not a lowercase slug.

    Args:
        value: The candidate.
        field: What it names, for the message.

    Raises:
        ValidationError: If the length or alphabet is wrong.
    """
    if not MIN_SLUG_LENGTH <= len(value) <= MAX_SLUG_LENGTH:
        msg = (
            f"{field} is {len(value)} characters; expected between "
            f"{MIN_SLUG_LENGTH} and {MAX_SLUG_LENGTH}"
        )
        raise ValidationError(msg)
    stray = sorted(set(value) - set(SLUG_ALPHABET))
    if stray:
        msg = f"{field} contains {stray}; names are lowercase letters, digits and underscores"
        raise ValidationError(msg)


class ProductScope(StrEnum):
    """What a product family is to GLOBIN, which is not what it is to the venue.

    Three members, and this one **is** an enumeration because GLOBIN decides it.
    A fourth meaning "maybe later" was rejected for the reason
    :class:`~globin.domain.environment.CapabilitySeverity` rejects a third tier:
    it would be an answer every caller had to interpret.
    """

    TRADING = "trading"
    """In scope. GLOBIN intends to trade this, and later bands build adapters."""

    SUPPORTING = "supporting"
    """Not traded, and a trading path may still depend on it.

    A transfer or an account query can need a surface no strategy ever places an
    order through.
    """

    OUT_OF_CURRENT_SCOPE = "out_of_current_scope"
    """Documented by the venue and deliberately not pursued.

    Recorded rather than omitted, so a later reader can tell the difference
    between something nobody considered and something considered and declined.
    """


class ProtocolKind(StrEnum):
    """One way of talking to a product, at the granularity capabilities differ.

    The three FIX members are separate rather than one member with a role field,
    because they differ in every respect that matters: different hosts, different
    permitted key permissions, different rate limits, different capabilities.
    """

    REST = "rest"
    WEBSOCKET_API = "websocket_api"
    WEBSOCKET_MARKET_STREAMS = "websocket_market_streams"
    WEBSOCKET_USER_STREAMS = "websocket_user_streams"
    FIX_ORDER_ENTRY = "fix_order_entry"
    FIX_DROP_COPY = "fix_drop_copy"
    FIX_MARKET_DATA = "fix_market_data"


class TransportKind(StrEnum):
    """What carries a protocol, which is a different question from which protocol."""

    HTTPS = "https"
    WEBSOCKET = "websocket"
    TCP_TLS = "tcp_tls"


class EncodingKind(StrEnum):
    """How a message is encoded on the wire.

    Recorded twice per endpoint -- once for what is sent and once for what is
    received -- because one documented FIX port accepts one encoding and answers
    in another.
    """

    JSON = "json"
    SBE = "sbe"
    FIX_TEXT = "fix_text"
    FIX_SBE = "fix_sbe"


class SurfaceCapability(StrEnum):
    """What an endpoint may be used for, as its own documentation states.

    Present so a market-data-only host cannot be picked out of a list of base URLs
    and handed a signed order. The venue publishes exactly such a host.
    """

    MARKET_DATA = "market_data"
    TRADING = "trading"
    ACCOUNT_DATA = "account_data"
    USER_STREAM = "user_stream"


class SurfaceStatus(StrEnum):
    """What the official documents say about GLOBIN's ability to use a surface.

    Six members on one axis. The axis is *what is documented*, not *what was
    measured*, which is why this is not
    :class:`~globin.domain.environment.CapabilityStatus`.
    """

    SUPPORTED = "supported"
    """Documented, with no condition attached."""

    UNSUPPORTED = "unsupported"
    """Documented as not available. A stated absence, not a missing statement."""

    UNKNOWN = "unknown"
    """The documents do not say, or no admissible source could be read.

    **Never a synonym for no.** It is the honest answer for every product family
    the venue publishes no machine-readable specification for, and reading it as
    absence is the failure this registry exists to prevent.
    """

    DEPRECATED = "deprecated"
    """Documented, still reachable, and announced as going away."""

    ANNOUNCED = "announced"
    """Documented as scheduled and not yet available.

    Distinct from :attr:`UNSUPPORTED` because building against it is premature
    rather than impossible.
    """

    RESTRICTED = "restricted"
    """Documented, subject to a stated eligibility, key or permission condition.

    A record carrying this **must** name the condition, and
    :class:`CapabilityRecord` refuses one that does not. A ``RESTRICTED`` whose
    condition is vague has become a second spelling of :attr:`UNKNOWN`.
    """


class EvidenceKind(StrEnum):
    """How a claim came to be recorded.

    Three members, and one of them cannot be produced. GLOBIN has never contacted
    the venue, so no record here may claim observation; a contract test asserts
    that none does. The member exists because a later phase will have a transport,
    and re-versioning the schema then would be worse than declaring it now.
    """

    DOCUMENTED = "documented"
    """Stated by an official document, read directly."""

    INFERRED = "inferred"
    """Derived from documented facts, and the derivation is GLOBIN's own.

    Kept apart from :attr:`DOCUMENTED` so a reader can tell which claims the venue
    makes and which GLOBIN makes about them.
    """

    OBSERVED = "observed"
    """Seen in a real response.

    Unproducible until a transport exists. Nothing in this repository may write it.
    """


class SourceAuthority(StrEnum):
    """Where a source sits in ``docs/SOURCE_POLICY.md``'s tiers.

    Two members, because that document's third tier is contextual only and can
    never establish a fact about an API. A record citing one would cite nothing.
    """

    PRIMARY = "primary"
    SECONDARY = "secondary"


class SourceRegime(StrEnum):
    """How a source can be re-checked, which is a property of the source.

    Three members, and the third was found rather than designed: the venue's
    derivatives documentation is a client-rendered application with no fetchable
    text form, so it can be neither parsed nor digested.
    """

    STRUCTURED = "structured"
    """Machine-readable. Compared field by field.

    Only the schema lifecycle files are here, and three of the four do not
    currently parse, so this regime covers less than its name suggests.
    """

    DIGEST = "digest"
    """Fetchable text. Compared by digest, and a change is a question for a person.

    Deliberately not parsed. An extractor that mis-reads a changed table produces
    a confident wrong registry, which is worse than a prompt to re-read.
    """

    MANUAL = "manual"
    """Neither parseable nor fetchable. Re-checked by a person, or not at all.

    A source in this regime cannot take part in drift detection, and every record
    citing one is bounded in practice by :attr:`SurfaceStatus.UNKNOWN`.
    """


class AuthMechanism(StrEnum):
    """What a request must carry to be accepted.

    Separate from :class:`ApiKeyType`, which says what may sign it. One documented
    surface accepts three key types and another accepts one, so collapsing the two
    axes would make that inexpressible.
    """

    NONE = "none"
    API_KEY = "api_key"
    SIGNED = "signed"
    UNKNOWN = "unknown"
    """No admissible source established the requirement.

    Present for the same reason :attr:`SurfaceStatus.UNKNOWN` is, and it is not
    :attr:`NONE` -- assuming a surface is public because nothing said otherwise is
    exactly the fail-open this registry refuses.
    """


class ApiKeyType(StrEnum):
    """A signature algorithm documented for a key.

    An enumeration rather than a validated string, because these are cryptographic
    algorithms GLOBIN must implement rather than names a venue invents. A fourth
    would be a signing implementation, not a registry row.
    """

    HMAC = "hmac"
    RSA = "rsa"
    ED25519 = "ed25519"


class SchemaLifecycleState(StrEnum):
    """Where a schema version sits in its published lifecycle.

    The three words the venue's own lifecycle documents use, and no fourth.
    """

    LATEST = "latest"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class DriftClass(StrEnum):
    """What kind of difference two snapshots have."""

    PRODUCT_ADDED = "product_added"
    PRODUCT_REMOVED = "product_removed"
    SURFACE_ADDED = "surface_added"
    SURFACE_REMOVED = "surface_removed"
    ENVIRONMENT_ADDED = "environment_added"
    ENVIRONMENT_REMOVED = "environment_removed"
    ENDPOINT_ADDED = "endpoint_added"
    ENDPOINT_REMOVED = "endpoint_removed"
    ENDPOINT_CHANGED = "endpoint_changed"
    STATUS_CHANGED = "status_changed"
    AUTH_CHANGED = "auth_changed"
    KEY_TYPE_CHANGED = "key_type_changed"
    SCHEMA_ADDED = "schema_added"
    SCHEMA_STATE_CHANGED = "schema_state_changed"
    SOURCE_ADDED = "source_added"
    SOURCE_REMOVED = "source_removed"
    SOURCE_CHANGED = "source_changed"


class DriftRisk(StrEnum):
    """How much attention a difference deserves.

    Four members. Nothing computes an aggregate from them, because a maximum over
    a list of risks reports the worst finding and hides the count.
    """

    INFORMATIONAL = "informational"
    """Something appeared, and nothing GLOBIN relied on changed."""

    REVIEW_REQUIRED = "review_required"
    """A person must look. Every prose-source digest change lands here."""

    BREAKING = "breaking"
    """Something GLOBIN could rely on stopped being available."""

    SECURITY_RELEVANT = "security_relevant"
    """An authentication or key rule changed.

    Separate from :attr:`BREAKING` because the response differs: a broken surface
    is re-planned, and a changed key rule is checked against what GLOBIN holds
    before anything else happens.
    """


@dataclass(frozen=True, slots=True, order=True)
class SourceObservation:
    """One official document, and when it was read.

    Every capability-bearing record names one of these. A claim about a venue with
    no source is not a weaker claim; there is nothing to check it against.

    Raises:
        ValidationError: On an empty identifier, title or location; on a location
            that is not ``https``; on a malformed access date; on a
            :attr:`SourceRegime.MANUAL` source carrying a digest, which it cannot
            honestly have; or on a malformed digest.
    """

    identifier: str
    title: str
    location: str
    authority: SourceAuthority
    accessed: str
    regime: SourceRegime
    digest: str = ""
    notes: str = ""
    known_unparseable: bool = False
    """Whether this source is declared structured and known not to parse today.

    Recorded rather than discovered. Three of the four lifecycle documents the
    venue publishes are not currently valid JSON, and an owned defect is reported
    while an unowned one fails -- the rule the wheel survey already applies to a
    missing wheel.
    """

    def __post_init__(self) -> None:
        """Refuse a source that could not be gone back to."""
        _require_text(self.identifier, field="a source identifier")
        _require_text(self.title, field="a source title")
        _require_text(self.location, field="a source location")
        if not self.location.startswith(HTTPS_SCHEME):
            msg = f"a source location must be https, and {self.location!r} is not"
            raise ValidationError(msg)
        _require_date(self.accessed, field="a source access date")
        if self.regime is SourceRegime.MANUAL and self.digest:
            msg = (
                f"source {self.identifier!r} is manual and carries a digest; a source "
                "with no fetchable text form cannot have been hashed"
            )
            raise ValidationError(msg)
        if self.digest:
            _require_digest(self.digest, field=f"source {self.identifier!r}")
        if self.notes:
            _require_text(self.notes, field="a source note")

    @property
    def refreshable(self) -> bool:
        """Whether an automated refresh can re-check this source at all."""
        return self.regime is not SourceRegime.MANUAL

    def as_record(self) -> dict[str, object]:
        """This source as plain JSON-safe values.

        Returns:
            A mapping with enum members replaced by their values.
        """
        return {
            "identifier": self.identifier,
            "title": self.title,
            "location": self.location,
            "authority": self.authority.value,
            "accessed": self.accessed,
            "regime": self.regime.value,
            "digest": self.digest,
            "notes": self.notes,
            "known_unparseable": self.known_unparseable,
        }


@dataclass(frozen=True, slots=True, order=True)
class CapabilityRecord:
    """The evidentiary half of every claim, carried by composition rather than repeated.

    Raises:
        ValidationError: On :attr:`SurfaceStatus.RESTRICTED` with no condition
            named, on a condition attached to any other status, or on an empty
            source identifier.
    """

    status: SurfaceStatus
    evidence: EvidenceKind
    source: str
    condition: str = ""

    def __post_init__(self) -> None:
        """Refuse a claim that could not be acted on or traced."""
        _require_text(self.source, field="a capability source identifier")
        if self.status is SurfaceStatus.RESTRICTED and not self.condition:
            msg = "a RESTRICTED capability must name the condition that restricts it"
            raise ValidationError(msg)
        if self.condition and self.status is not SurfaceStatus.RESTRICTED:
            msg = (
                f"a {self.status.value} capability carries a condition; only RESTRICTED "
                "means documented-subject-to-a-condition"
            )
            raise ValidationError(msg)
        if self.condition:
            _require_text(self.condition, field="a capability condition")

    @property
    def usable(self) -> bool:
        """Whether the documents say this may be used today.

        ``DEPRECATED`` is usable and going away; ``ANNOUNCED`` is not usable yet;
        ``UNKNOWN`` is not usable, because nothing said that it was.
        """
        return self.status in {
            SurfaceStatus.SUPPORTED,
            SurfaceStatus.RESTRICTED,
            SurfaceStatus.DEPRECATED,
        }

    def as_record(self) -> dict[str, object]:
        """This claim as plain JSON-safe values.

        Returns:
            A mapping with enum members replaced by their values.
        """
        return {
            "status": self.status.value,
            "evidence": self.evidence.value,
            "source": self.source,
            "condition": self.condition,
        }


@dataclass(frozen=True, slots=True, order=True)
class ProductProfile:
    """One product family, what it is to GLOBIN, and what is known about it.

    Raises:
        ValidationError: On an empty title.
    """

    family: ProductFamily
    scope: ProductScope
    title: str
    capability: CapabilityRecord

    def __post_init__(self) -> None:
        """Refuse a product with no readable name."""
        _require_text(self.title, field="a product title")

    def as_record(self) -> dict[str, object]:
        """This product as plain JSON-safe values.

        Returns:
            A mapping with value types and enum members flattened to strings.
        """
        return {
            "family": self.family.slug,
            "scope": self.scope.value,
            "title": self.title,
            "capability": self.capability.as_record(),
        }


@dataclass(frozen=True, slots=True, order=True)
class SurfaceRecord:
    """One product and one protocol, and whether the venue documents the pair.

    This is the roadmap row's *surfaces each one exposes*, and it is deliberately
    separate from :class:`EndpointRecord`: a surface can be documented as supported
    while no endpoint for it is known, which is exactly the state every product
    without a machine-readable specification is in.
    """

    family: ProductFamily
    protocol: ProtocolKind
    capability: CapabilityRecord

    @property
    def identity(self) -> tuple[str, str]:
        """What makes this surface unique within a snapshot."""
        return (self.family.slug, self.protocol.value)

    def as_record(self) -> dict[str, object]:
        """This surface as plain JSON-safe values.

        Returns:
            A mapping with value types and enum members flattened to strings.
        """
        return {
            "family": self.family.slug,
            "protocol": self.protocol.value,
            "capability": self.capability.as_record(),
        }


@dataclass(frozen=True, slots=True, order=True)
class EnvironmentRecord:
    """One product in one environment, with the guarantees the venue states for it.

    ``host_marker`` is what makes the snapshot's production-mixing check possible
    without this module knowing any environment's name. A non-production
    environment declares the substring its hosts are spelled with, and endpoints
    are checked against it.

    Raises:
        ValidationError: On empty semantics; on a production environment declaring
            a host marker; or on a non-production environment declaring none. An
            environment whose guarantees are unstated is the assumption ADR-0006
            exists to prevent, so the field is required even when the honest
            content is "no admissible source".
    """

    family: ProductFamily
    environment: EnvironmentName
    semantics: str
    capability: CapabilityRecord
    carries_real_capital: bool = False
    host_marker: str = ""

    def __post_init__(self) -> None:
        """Refuse an environment recorded without its guarantees or its marker."""
        _require_text(self.semantics, field="environment semantics")
        if self.carries_real_capital and self.host_marker:
            msg = (
                f"{self.environment.slug} says real capital is at risk and carries the host "
                f"marker {self.host_marker!r}; the live environment is the unmarked one"
            )
            raise ValidationError(msg)
        if not self.carries_real_capital and not self.host_marker:
            msg = (
                f"{self.environment.slug} risks no real capital and declares no host marker; "
                "without one, an endpoint filed here cannot be told from a live one"
            )
            raise ValidationError(msg)
        if self.host_marker:
            _require_slug(self.host_marker, field="an environment host marker")

    @property
    def identity(self) -> tuple[str, str]:
        """What makes this environment record unique within a snapshot."""
        return (self.family.slug, self.environment.slug)

    def as_record(self) -> dict[str, object]:
        """This environment as plain JSON-safe values.

        Returns:
            A mapping with value types and enum members flattened to strings.
        """
        return {
            "family": self.family.slug,
            "environment": self.environment.slug,
            "semantics": self.semantics,
            "carries_real_capital": self.carries_real_capital,
            "host_marker": self.host_marker,
            "capability": self.capability.as_record(),
        }


@dataclass(frozen=True, slots=True, order=True)
class EndpointRecord:
    """One reachable address, and everything that decides whether it may be used.

    ``request_encoding`` and ``response_encoding`` are separate because the venue
    documents a FIX port that accepts one and answers in the other. ``port`` is
    part of the identity for the same reason: three FIX ports share a host and
    differ only in encoding.

    Raises:
        ValidationError: On an unpermitted scheme; on a FIX endpoint with no port
            or without TLS and SNI required; on a key type declared where the
            mechanism is :attr:`AuthMechanism.NONE`; or on an endpoint claiming
            :attr:`SurfaceCapability.TRADING` without authentication.
    """

    family: ProductFamily
    environment: EnvironmentName
    protocol: ProtocolKind
    url: str
    transport: TransportKind
    request_encoding: EncodingKind
    response_encoding: EncodingKind
    auth: AuthMechanism
    capability: CapabilityRecord
    port: int = 0
    tls_required: bool = True
    sni_required: bool = False
    key_types: tuple[ApiKeyType, ...] = ()
    key_permissions: tuple[KeyPermission, ...] = ()
    capabilities: tuple[SurfaceCapability, ...] = ()
    path_prefix: str = ""

    def __post_init__(self) -> None:
        """Refuse an endpoint that could be used wrongly without anything noticing."""
        _require_text(self.url, field="an endpoint url")
        if not self.url.startswith(PERMITTED_SCHEMES):
            msg = (
                f"endpoint {self.url!r} uses a scheme outside "
                f"{', '.join(PERMITTED_SCHEMES)}; every documented endpoint is encrypted"
            )
            raise ValidationError(msg)
        self._check_fix_requirements()
        if self.auth is AuthMechanism.NONE and self.key_types:
            msg = f"endpoint {self.url!r} needs no authentication and declares key types"
            raise ValidationError(msg)
        unauthenticated = self.auth in {AuthMechanism.NONE, AuthMechanism.UNKNOWN}
        if SurfaceCapability.TRADING in self.capabilities and unauthenticated:
            msg = (
                f"endpoint {self.url!r} claims trading with {self.auth.value} "
                "authentication; an unauthenticated trading surface is not documented"
            )
            raise ValidationError(msg)

    def _check_fix_requirements(self) -> None:
        """Refuse a FIX endpoint missing a port, TLS or SNI.

        Raises:
            ValidationError: If any of the three is absent.

        SNI is required rather than recommended because the venue documents that a
        client omitting it may receive an unexpected certificate -- a failure that
        produces *a* certificate rather than none.
        """
        if self.transport is not TransportKind.TCP_TLS:
            return
        if self.port <= 0:
            msg = f"FIX endpoint {self.url!r} must record the port it is reached on"
            raise ValidationError(msg)
        if not (self.tls_required and self.sni_required):
            msg = (
                f"FIX endpoint {self.url!r} must require TLS and SNI; a client omitting "
                "SNI may receive an unexpected certificate"
            )
            raise ValidationError(msg)

    @property
    def identity(self) -> tuple[str, str, str, str, int]:
        """What makes this endpoint unique within a snapshot."""
        return (
            self.family.slug,
            self.environment.slug,
            self.protocol.value,
            self.url,
            self.port,
        )

    def as_record(self) -> dict[str, object]:
        """This endpoint as plain JSON-safe values.

        Returns:
            A mapping with value types flattened to strings and tuples to lists.
        """
        return {
            "family": self.family.slug,
            "environment": self.environment.slug,
            "protocol": self.protocol.value,
            "url": self.url,
            "transport": self.transport.value,
            "request_encoding": self.request_encoding.value,
            "response_encoding": self.response_encoding.value,
            "auth": self.auth.value,
            "port": self.port,
            "tls_required": self.tls_required,
            "sni_required": self.sni_required,
            "key_types": [item.value for item in self.key_types],
            "key_permissions": [item.spelling for item in self.key_permissions],
            "capabilities": [item.value for item in self.capabilities],
            "path_prefix": self.path_prefix,
            "capability": self.capability.as_record(),
        }


@dataclass(frozen=True, slots=True, order=True)
class SchemaVersion:
    """One published schema version and where it sits in its lifecycle.

    Raises:
        ValidationError: On a negative identifier or version; on a
            :attr:`SchemaLifecycleState.RETIRED` entry with no retirement date; on
            a :attr:`SchemaLifecycleState.LATEST` entry carrying one; or on a
            malformed date.
    """

    family: SchemaFamilyName
    environment: EnvironmentName
    schema_id: int
    version: int
    state: SchemaLifecycleState
    released: str
    source: str
    deprecated: str = ""
    retired: str = ""

    def __post_init__(self) -> None:
        """Refuse a lifecycle entry that contradicts its own state."""
        if self.schema_id < 0 or self.version < 0:
            msg = f"schema {self.schema_id}:{self.version} has a negative component"
            raise ValidationError(msg)
        _require_text(self.source, field="a schema source identifier")
        _require_date(self.released, field="a schema release date")
        if self.deprecated:
            _require_date(self.deprecated, field="a schema deprecation date")
        if self.retired:
            _require_date(self.retired, field="a schema retirement date")
        if self.state is SchemaLifecycleState.RETIRED and not self.retired:
            msg = f"schema {self.label} is retired and records no retirement date"
            raise ValidationError(msg)
        if self.state is SchemaLifecycleState.LATEST and (self.deprecated or self.retired):
            msg = f"schema {self.label} is the latest and carries a deprecation or retirement date"
            raise ValidationError(msg)

    @property
    def label(self) -> str:
        """The ``id:version`` spelling the venue's own changelog uses."""
        return f"{self.schema_id}:{self.version}"

    @property
    def identity(self) -> tuple[str, str, int, int]:
        """What makes this schema version unique within a snapshot."""
        return (self.family.slug, self.environment.slug, self.schema_id, self.version)

    def as_record(self) -> dict[str, object]:
        """This schema version as plain JSON-safe values.

        Returns:
            A mapping with value types and enum members flattened to strings.
        """
        return {
            "family": self.family.slug,
            "environment": self.environment.slug,
            "schema_id": self.schema_id,
            "version": self.version,
            "state": self.state.value,
            "released": self.released,
            "deprecated": self.deprecated,
            "retired": self.retired,
            "source": self.source,
        }


def _duplicates(identities: list[object]) -> list[str]:
    """Every identity appearing more than once, as text, sorted.

    Args:
        identities: The identities, in the order they were declared.

    Returns:
        The repeated ones, spelled for a message.
    """
    seen: set[object] = set()
    repeated: set[object] = set()
    for identity in identities:
        if identity in seen:
            repeated.add(identity)
        seen.add(identity)
    return sorted(str(item) for item in repeated)


@dataclass(frozen=True, slots=True)
class ApiRealitySnapshot:
    """Everything the registry records, checked for internal consistency.

    Raises:
        ValidationError: On any bound exceeded; on a repeated identity in any
            collection; on a record citing a source that is not declared; on more
            than one :attr:`SchemaLifecycleState.LATEST` per family and
            environment; on an endpoint whose surface is documented
            :attr:`SurfaceStatus.UNSUPPORTED`; on an endpoint in an environment the
            snapshot does not declare; or on an endpoint whose host contradicts
            that environment.
    """

    sources: tuple[SourceObservation, ...] = ()
    products: tuple[ProductProfile, ...] = ()
    surfaces: tuple[SurfaceRecord, ...] = ()
    environments: tuple[EnvironmentRecord, ...] = ()
    endpoints: tuple[EndpointRecord, ...] = ()
    schemas: tuple[SchemaVersion, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a snapshot that contradicts itself."""
        self._check_bounds()
        self._check_identities()
        self._check_sources_exist()
        self._check_one_latest_schema()
        self._check_endpoints_against_surfaces()
        self._check_endpoint_hosts_match_environment()

    def _check_bounds(self) -> None:
        """Refuse a snapshot whose size depends on nothing anybody is watching."""
        limits: tuple[tuple[int, int, str], ...] = (
            (len(self.sources), MAX_SOURCES, "sources"),
            (len(self.products), MAX_PRODUCTS, "products"),
            (len(self.surfaces), MAX_SURFACES, "surfaces"),
            (len(self.environments), MAX_ENVIRONMENTS, "environments"),
            (len(self.endpoints), MAX_ENDPOINTS, "endpoints"),
            (len(self.schemas), MAX_SCHEMAS, "schemas"),
        )
        for count, limit, name in limits:
            if count > limit:
                msg = f"a snapshot carries {count} {name} and the limit is {limit}"
                raise ValidationError(msg)

    def _check_identities(self) -> None:
        """Refuse a repeated identity, which would make a lookup ambiguous."""
        groups: tuple[tuple[list[object], str], ...] = (
            ([item.identifier for item in self.sources], "source"),
            ([item.family.slug for item in self.products], "product"),
            ([item.identity for item in self.surfaces], "surface"),
            ([item.identity for item in self.environments], "environment"),
            ([item.identity for item in self.endpoints], "endpoint"),
            ([item.identity for item in self.schemas], "schema"),
        )
        for identities, name in groups:
            repeated = _duplicates(identities)
            if repeated:
                msg = f"{name} declared more than once: {', '.join(repeated)}"
                raise ValidationError(msg)

    def _check_sources_exist(self) -> None:
        """Refuse a claim citing a source the snapshot does not carry."""
        declared = {item.identifier for item in self.sources}
        cited: set[str] = {item.capability.source for item in self.products}
        cited |= {item.capability.source for item in self.surfaces}
        cited |= {item.capability.source for item in self.environments}
        cited |= {item.capability.source for item in self.endpoints}
        cited |= {item.source for item in self.schemas}
        missing = sorted(cited - declared)
        if missing:
            msg = f"records cite sources that are not declared: {', '.join(missing)}"
            raise ValidationError(msg)

    def _check_one_latest_schema(self) -> None:
        """Refuse two current schemas for one family and environment."""
        seen: dict[tuple[str, str], str] = {}
        for schema in self.schemas:
            if schema.state is not SchemaLifecycleState.LATEST:
                continue
            key = (schema.family.slug, schema.environment.slug)
            if key in seen:
                msg = (
                    f"{key[0]} in {key[1]} declares both {seen[key]} and {schema.label} "
                    "as the latest schema"
                )
                raise ValidationError(msg)
            seen[key] = schema.label

    def _check_endpoints_against_surfaces(self) -> None:
        """Refuse an endpoint for a surface documented as unavailable."""
        unsupported = {
            surface.identity
            for surface in self.surfaces
            if surface.capability.status is SurfaceStatus.UNSUPPORTED
        }
        for endpoint in self.endpoints:
            key = (endpoint.family.slug, endpoint.protocol.value)
            if key in unsupported:
                msg = (
                    f"endpoint {endpoint.url!r} exists for {key[0]}/{key[1]}, which is "
                    "recorded as unsupported"
                )
                raise ValidationError(msg)

    def _check_endpoint_hosts_match_environment(self) -> None:
        """Refuse a host that contradicts the environment it is filed under.

        Raises:
            ValidationError: If an endpoint names an undeclared environment, or its
                URL does not carry that environment's marker, or a production
                endpoint carries somebody else's.

        The failure this prevents is the one ADR-0006 calls the dangerous one: an
        endpoint labelled non-production that routes to real capital, or the
        reverse. It is driven entirely by declared markers, so a fourth environment
        needs no change here.
        """
        markers = {item.environment.slug: item.host_marker for item in self.environments}
        others = {marker for marker in markers.values() if marker}
        for endpoint in self.endpoints:
            slug = endpoint.environment.slug
            if slug not in markers:
                msg = (
                    f"endpoint {endpoint.url!r} is filed under {slug}, which the snapshot "
                    "does not declare for that product"
                )
                raise ValidationError(msg)
            lowered = endpoint.url.lower()
            marker = markers[slug]
            if marker and marker not in lowered:
                msg = (
                    f"endpoint {endpoint.url!r} is filed under {slug} and its host does "
                    f"not contain {marker!r}"
                )
                raise ValidationError(msg)
            if marker:
                continue
            stray = sorted(item for item in others if item in lowered)
            if stray:
                msg = (
                    f"endpoint {endpoint.url!r} is filed under {slug}, which is production, "
                    f"and its host is spelled like {', '.join(stray)}"
                )
                raise ValidationError(msg)

    def product(self, family: ProductFamily) -> ProductProfile | None:
        """One product family, or nothing.

        Args:
            family: Which family.

        Returns:
            Its profile, or ``None`` if the registry has no entry.

        ``None`` means *the registry was never told*, which is a different answer
        from a profile recording :attr:`SurfaceStatus.UNKNOWN` -- that one means
        *the documents do not say*. Both refuse; a caller that cannot tell them
        apart cannot report which.
        """
        return next((item for item in self.products if item.family == family), None)

    def surface(self, family: ProductFamily, protocol: ProtocolKind) -> SurfaceRecord | None:
        """One product-and-protocol surface, or nothing.

        Args:
            family: Which family.
            protocol: Which protocol.

        Returns:
            Its record, or ``None`` if the registry has no entry.
        """
        key = (family.slug, protocol.value)
        return next((item for item in self.surfaces if item.identity == key), None)

    def environment(
        self, family: ProductFamily, environment: EnvironmentName
    ) -> EnvironmentRecord | None:
        """One product-and-environment pair, or nothing.

        Args:
            family: Which family.
            environment: Which environment.

        Returns:
            Its record, or ``None`` if the registry has no entry.
        """
        key = (family.slug, environment.slug)
        return next((item for item in self.environments if item.identity == key), None)

    def endpoints_for(
        self,
        family: ProductFamily,
        environment: EnvironmentName,
        protocol: ProtocolKind | None = None,
    ) -> tuple[EndpointRecord, ...]:
        """Every endpoint matching a product, an environment and optionally a protocol.

        Args:
            family: Which family.
            environment: Which environment.
            protocol: Which protocol, or ``None`` for all of them.

        Returns:
            The matching endpoints, in declaration order. Empty means the registry
            has none, never that none exist.
        """
        return tuple(
            item
            for item in self.endpoints
            if item.family == family
            and item.environment == environment
            and (protocol is None or item.protocol is protocol)
        )

    def current_schema(
        self, family: SchemaFamilyName, environment: EnvironmentName
    ) -> SchemaVersion | None:
        """The schema version recorded as current, or nothing.

        Args:
            family: Which schema family.
            environment: Which environment.

        Returns:
            The single :attr:`SchemaLifecycleState.LATEST` entry, or ``None``.
        """
        return next(
            (
                item
                for item in self.schemas
                if item.family == family
                and item.environment == environment
                and item.state is SchemaLifecycleState.LATEST
            ),
            None,
        )

    def capabilities_with_status(self, status: SurfaceStatus) -> tuple[str, ...]:
        """Every record carrying one status, named.

        Args:
            status: Which status.

        Returns:
            Identities as text, sorted, so a count and a listing always agree.
        """
        found = [
            f"product/{item.family.slug}"
            for item in self.products
            if item.capability.status is status
        ]
        found += [
            f"surface/{item.family.slug}/{item.protocol.value}"
            for item in self.surfaces
            if item.capability.status is status
        ]
        found += [
            f"environment/{item.family.slug}/{item.environment.slug}"
            for item in self.environments
            if item.capability.status is status
        ]
        found += [
            f"endpoint/{item.url}" for item in self.endpoints if item.capability.status is status
        ]
        return tuple(sorted(found))

    def status_counts(self) -> dict[str, int]:
        """How many records carry each status.

        Returns:
            Every :class:`SurfaceStatus` value mapped to its count, including the
            zeroes -- an absent key would read as an absent question.
        """
        return {
            status.value: len(self.capabilities_with_status(status)) for status in SurfaceStatus
        }

    def unrefreshable_sources(self) -> tuple[str, ...]:
        """Every source no automated refresh can re-check.

        Returns:
            Their identifiers, sorted. A registry whose sources are mostly here is
            one whose drift detection covers less than it appears to, which is why
            the count is published rather than left to be discovered.
        """
        return tuple(sorted(item.identifier for item in self.sources if not item.refreshable))

    def as_record(self) -> dict[str, object]:
        """The whole snapshot as plain JSON-safe values.

        Returns:
            A mapping whose every leaf is a string, integer, boolean or list.
        """
        return {
            "sources": [item.as_record() for item in self.sources],
            "products": [item.as_record() for item in self.products],
            "surfaces": [item.as_record() for item in self.surfaces],
            "environments": [item.as_record() for item in self.environments],
            "endpoints": [item.as_record() for item in self.endpoints],
            "schemas": [item.as_record() for item in self.schemas],
        }


@dataclass(frozen=True, slots=True, order=True)
class DriftFinding:
    """One difference between two snapshots, classified.

    Raises:
        ValidationError: On an empty subject or summary.
    """

    drift: DriftClass
    risk: DriftRisk
    subject: str
    summary: str
    before: str = ""
    after: str = ""

    def __post_init__(self) -> None:
        """Refuse a finding nobody could act on."""
        _require_text(self.subject, field="a drift subject")
        _require_text(self.summary, field="a drift summary")

    def as_record(self) -> dict[str, object]:
        """This finding as plain JSON-safe values.

        Returns:
            A mapping with enum members replaced by their values.
        """
        return {
            "drift": self.drift.value,
            "risk": self.risk.value,
            "subject": self.subject,
            "summary": self.summary,
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True, slots=True)
class ApiRealityDiff:
    """Every classified difference between two snapshots.

    Raises:
        ValidationError: If more findings are carried than :data:`MAX_FINDINGS`.
    """

    findings: tuple[DriftFinding, ...] = ()

    def __post_init__(self) -> None:
        """Refuse an unbounded diff."""
        if len(self.findings) > MAX_FINDINGS:
            msg = f"a diff carries {len(self.findings)} findings and the limit is {MAX_FINDINGS}"
            raise ValidationError(msg)

    @property
    def empty(self) -> bool:
        """Whether the two snapshots said the same thing."""
        return not self.findings

    def at_risk(self, risk: DriftRisk) -> tuple[DriftFinding, ...]:
        """Every finding at one risk level.

        Args:
            risk: Which level.

        Returns:
            The matching findings, in the order they were produced.
        """
        return tuple(item for item in self.findings if item.risk is risk)

    @property
    def demands_attention(self) -> bool:
        """Whether anything here is more than informational."""
        return any(item.risk is not DriftRisk.INFORMATIONAL for item in self.findings)

    def as_record(self) -> dict[str, object]:
        """This diff as plain JSON-safe values.

        Returns:
            A mapping carrying the findings and a count per risk level.
        """
        return {
            "findings": [item.as_record() for item in self.findings],
            "counts": {risk.value: len(self.at_risk(risk)) for risk in DriftRisk},
        }


STATUS_RISK: Final[dict[SurfaceStatus, DriftRisk]] = {
    SurfaceStatus.UNSUPPORTED: DriftRisk.BREAKING,
    SurfaceStatus.UNKNOWN: DriftRisk.BREAKING,
    SurfaceStatus.DEPRECATED: DriftRisk.REVIEW_REQUIRED,
    SurfaceStatus.RESTRICTED: DriftRisk.REVIEW_REQUIRED,
    SurfaceStatus.SUPPORTED: DriftRisk.INFORMATIONAL,
    SurfaceStatus.ANNOUNCED: DriftRisk.INFORMATIONAL,
}
"""How much attention a status transition deserves, keyed by where it landed.

Read only when the status actually moved. **Landing on
:attr:`SurfaceStatus.UNKNOWN` is breaking**, which is the entry most likely to be
argued with: it means a capability GLOBIN could describe is now one it cannot, and
treating a loss of knowledge as informational is how a registry decays quietly.
Landing on :attr:`SurfaceStatus.SUPPORTED` is informational however it arrived --
gaining a capability breaks nothing.
"""


def _source_findings(before: ApiRealitySnapshot, after: ApiRealitySnapshot) -> list[DriftFinding]:
    """Differences in the documents the two snapshots rest on.

    Args:
        before: The earlier snapshot.
        after: The later one.

    Returns:
        One finding per added, removed or altered source.

    A changed digest is :attr:`DriftRisk.REVIEW_REQUIRED` and never more, because
    nothing here knows what changed inside the document -- that is the whole reason
    the digest regime exists.
    """
    older = {item.identifier: item for item in before.sources}
    newer = {item.identifier: item for item in after.sources}
    findings: list[DriftFinding] = []
    for identifier in sorted(set(newer) - set(older)):
        findings.append(
            DriftFinding(
                drift=DriftClass.SOURCE_ADDED,
                risk=DriftRisk.INFORMATIONAL,
                subject=f"source/{identifier}",
                summary=f"source {identifier} is now cited",
                after=newer[identifier].location,
            )
        )
    for identifier in sorted(set(older) - set(newer)):
        findings.append(
            DriftFinding(
                drift=DriftClass.SOURCE_REMOVED,
                risk=DriftRisk.REVIEW_REQUIRED,
                subject=f"source/{identifier}",
                summary=f"source {identifier} is no longer cited",
                before=older[identifier].location,
            )
        )
    for identifier in sorted(set(older) & set(newer)):
        was, now = older[identifier], newer[identifier]
        if was.digest == now.digest and was.location == now.location:
            continue
        findings.append(
            DriftFinding(
                drift=DriftClass.SOURCE_CHANGED,
                risk=DriftRisk.REVIEW_REQUIRED,
                subject=f"source/{identifier}",
                summary=f"source {identifier} changed and must be re-read",
                before=was.digest or was.location,
                after=now.digest or now.location,
            )
        )
    return findings


def _product_findings(before: ApiRealitySnapshot, after: ApiRealitySnapshot) -> list[DriftFinding]:
    """Differences in which product families are recorded.

    Args:
        before: The earlier snapshot.
        after: The later one.

    Returns:
        One finding per added or removed family, plus one per status move.
    """
    older = {item.family: item for item in before.products}
    newer = {item.family: item for item in after.products}
    findings: list[DriftFinding] = []
    for family in sorted(set(newer) - set(older)):
        findings.append(
            DriftFinding(
                drift=DriftClass.PRODUCT_ADDED,
                risk=DriftRisk.INFORMATIONAL,
                subject=f"product/{family.slug}",
                summary=f"{family.slug} is now recorded",
            )
        )
    for family in sorted(set(older) - set(newer)):
        findings.append(
            DriftFinding(
                drift=DriftClass.PRODUCT_REMOVED,
                risk=DriftRisk.BREAKING,
                subject=f"product/{family.slug}",
                summary=f"{family.slug} is no longer recorded",
            )
        )
    for family in sorted(set(older) & set(newer)):
        findings.extend(
            _status_finding(
                subject=f"product/{family.slug}",
                was=older[family].capability,
                now=newer[family].capability,
            )
        )
    return findings


def _status_finding(
    *, subject: str, was: CapabilityRecord, now: CapabilityRecord
) -> list[DriftFinding]:
    """One finding if a status moved, and none if it did not.

    Args:
        subject: What the finding is about.
        was: The earlier claim.
        now: The later one.

    Returns:
        A single-item list, or an empty one.
    """
    if was.status is now.status:
        return []
    return [
        DriftFinding(
            drift=DriftClass.STATUS_CHANGED,
            risk=STATUS_RISK[now.status],
            subject=subject,
            summary=f"{subject} moved from {was.status.value} to {now.status.value}",
            before=was.status.value,
            after=now.status.value,
        )
    ]


def _surface_findings(before: ApiRealitySnapshot, after: ApiRealitySnapshot) -> list[DriftFinding]:
    """Differences in which protocols each product exposes.

    Args:
        before: The earlier snapshot.
        after: The later one.

    Returns:
        One finding per added or removed surface, plus one per status move.
    """
    older = {item.identity: item for item in before.surfaces}
    newer = {item.identity: item for item in after.surfaces}
    findings: list[DriftFinding] = []
    for key in sorted(set(newer) - set(older)):
        findings.append(
            DriftFinding(
                drift=DriftClass.SURFACE_ADDED,
                risk=DriftRisk.INFORMATIONAL,
                subject=f"surface/{key[0]}/{key[1]}",
                summary=f"{key[0]} now exposes {key[1]}",
            )
        )
    for key in sorted(set(older) - set(newer)):
        findings.append(
            DriftFinding(
                drift=DriftClass.SURFACE_REMOVED,
                risk=DriftRisk.BREAKING,
                subject=f"surface/{key[0]}/{key[1]}",
                summary=f"{key[0]} no longer exposes {key[1]}",
            )
        )
    for key in sorted(set(older) & set(newer)):
        findings.extend(
            _status_finding(
                subject=f"surface/{key[0]}/{key[1]}",
                was=older[key].capability,
                now=newer[key].capability,
            )
        )
    return findings


def _environment_findings(
    before: ApiRealitySnapshot, after: ApiRealitySnapshot
) -> list[DriftFinding]:
    """Differences in which environments each product is documented for.

    Args:
        before: The earlier snapshot.
        after: The later one.

    Returns:
        One finding per added or removed pair, plus one per status move.
    """
    older = {item.identity: item for item in before.environments}
    newer = {item.identity: item for item in after.environments}
    findings: list[DriftFinding] = []
    for key in sorted(set(newer) - set(older)):
        findings.append(
            DriftFinding(
                drift=DriftClass.ENVIRONMENT_ADDED,
                risk=DriftRisk.INFORMATIONAL,
                subject=f"environment/{key[0]}/{key[1]}",
                summary=f"{key[0]} is now documented for {key[1]}",
            )
        )
    for key in sorted(set(older) - set(newer)):
        findings.append(
            DriftFinding(
                drift=DriftClass.ENVIRONMENT_REMOVED,
                risk=DriftRisk.BREAKING,
                subject=f"environment/{key[0]}/{key[1]}",
                summary=f"{key[0]} is no longer documented for {key[1]}",
            )
        )
    for key in sorted(set(older) & set(newer)):
        findings.extend(
            _status_finding(
                subject=f"environment/{key[0]}/{key[1]}",
                was=older[key].capability,
                now=newer[key].capability,
            )
        )
    return findings


def _endpoint_change_findings(
    subject: str, was: EndpointRecord, now: EndpointRecord
) -> list[DriftFinding]:
    """Every difference between two endpoints sharing an identity.

    Args:
        subject: What the findings are about.
        was: The earlier record.
        now: The later one.

    Returns:
        Findings for authentication, key types, and everything else that moved.

    Authentication and key-type moves are :attr:`DriftRisk.SECURITY_RELEVANT`
    rather than breaking, and the separation is the point: a broken surface is
    re-planned, and a changed key rule is checked against what GLOBIN holds before
    anything else happens.
    """
    findings: list[DriftFinding] = []
    if was.auth is not now.auth:
        findings.append(
            DriftFinding(
                drift=DriftClass.AUTH_CHANGED,
                risk=DriftRisk.SECURITY_RELEVANT,
                subject=subject,
                summary=f"{subject} now requires {now.auth.value} authentication",
                before=was.auth.value,
                after=now.auth.value,
            )
        )
    if was.key_types != now.key_types or was.key_permissions != now.key_permissions:
        findings.append(
            DriftFinding(
                drift=DriftClass.KEY_TYPE_CHANGED,
                risk=DriftRisk.SECURITY_RELEVANT,
                subject=subject,
                summary=f"{subject} changed which keys and permissions it accepts",
                before=_key_summary(was),
                after=_key_summary(now),
            )
        )
    moved = (
        was.request_encoding is not now.request_encoding
        or was.response_encoding is not now.response_encoding
        or was.transport is not now.transport
        or was.tls_required != now.tls_required
        or was.sni_required != now.sni_required
        or was.capabilities != now.capabilities
        or was.path_prefix != now.path_prefix
    )
    if moved:
        findings.append(
            DriftFinding(
                drift=DriftClass.ENDPOINT_CHANGED,
                risk=DriftRisk.REVIEW_REQUIRED,
                subject=subject,
                summary=f"{subject} changed how it must be spoken to",
            )
        )
    findings.extend(_status_finding(subject=subject, was=was.capability, now=now.capability))
    return findings


def _key_summary(endpoint: EndpointRecord) -> str:
    """One endpoint's key rules as a short phrase.

    Args:
        endpoint: The record.

    Returns:
        Key types and permissions, comma separated, or ``none``.
    """
    parts = [item.value for item in endpoint.key_types]
    parts += [item.spelling for item in endpoint.key_permissions]
    return ", ".join(parts) if parts else "none"


def _endpoint_findings(before: ApiRealitySnapshot, after: ApiRealitySnapshot) -> list[DriftFinding]:
    """Differences in the addresses each surface is reached at.

    Args:
        before: The earlier snapshot.
        after: The later one.

    Returns:
        One finding per added or removed endpoint, plus each field-level move.
    """
    older = {item.identity: item for item in before.endpoints}
    newer = {item.identity: item for item in after.endpoints}
    findings: list[DriftFinding] = []
    for key in sorted(set(newer) - set(older)):
        findings.append(
            DriftFinding(
                drift=DriftClass.ENDPOINT_ADDED,
                risk=DriftRisk.INFORMATIONAL,
                subject=f"endpoint/{key[3]}",
                summary=f"{key[0]} in {key[1]} gained an endpoint for {key[2]}",
                after=key[3],
            )
        )
    for key in sorted(set(older) - set(newer)):
        findings.append(
            DriftFinding(
                drift=DriftClass.ENDPOINT_REMOVED,
                risk=DriftRisk.BREAKING,
                subject=f"endpoint/{key[3]}",
                summary=f"{key[0]} in {key[1]} lost its {key[2]} endpoint",
                before=key[3],
            )
        )
    for key in sorted(set(older) & set(newer)):
        findings.extend(_endpoint_change_findings(f"endpoint/{key[3]}", older[key], newer[key]))
    return findings


def _schema_findings(before: ApiRealitySnapshot, after: ApiRealitySnapshot) -> list[DriftFinding]:
    """Differences in the published schema lifecycles.

    Args:
        before: The earlier snapshot.
        after: The later one.

    Returns:
        One finding per newly recorded version and per lifecycle move.

    A retirement is :attr:`DriftRisk.BREAKING` and a deprecation is not: Binance
    documents that a deprecated schema stays supported for at least six months, so
    a deprecation is a deadline and a retirement is a closed door.
    """
    older = {item.identity: item for item in before.schemas}
    newer = {item.identity: item for item in after.schemas}
    findings: list[DriftFinding] = []
    for key in sorted(set(newer) - set(older)):
        entry = newer[key]
        findings.append(
            DriftFinding(
                drift=DriftClass.SCHEMA_ADDED,
                risk=DriftRisk.INFORMATIONAL,
                subject=f"schema/{key[0]}/{key[1]}/{entry.label}",
                summary=f"{key[0]} in {key[1]} published {entry.label}",
                after=entry.state.value,
            )
        )
    for key in sorted(set(older) & set(newer)):
        was, now = older[key], newer[key]
        if was.state is now.state:
            continue
        retired = now.state is SchemaLifecycleState.RETIRED
        findings.append(
            DriftFinding(
                drift=DriftClass.SCHEMA_STATE_CHANGED,
                risk=DriftRisk.BREAKING if retired else DriftRisk.REVIEW_REQUIRED,
                subject=f"schema/{key[0]}/{key[1]}/{now.label}",
                summary=f"{now.label} moved from {was.state.value} to {now.state.value}",
                before=was.state.value,
                after=now.state.value,
            )
        )
    return findings


def diff(before: ApiRealitySnapshot, after: ApiRealitySnapshot) -> ApiRealityDiff:
    """Every classified difference between two snapshots.

    Args:
        before: The earlier snapshot.
        after: The later one.

    Returns:
        The differences, grouped by subject in a fixed order so two runs over the
        same pair produce byte-identical output.

    Raises:
        ValidationError: If the two snapshots differ in more than
            :data:`MAX_FINDINGS` ways.

    A pure function of its two arguments. It reaches no network and reads no clock,
    which is what makes drift detection this phase's work rather than the phase
    that fetches documents.
    """
    findings = (
        _source_findings(before, after)
        + _product_findings(before, after)
        + _surface_findings(before, after)
        + _environment_findings(before, after)
        + _endpoint_findings(before, after)
        + _schema_findings(before, after)
    )
    return ApiRealityDiff(findings=tuple(findings))
