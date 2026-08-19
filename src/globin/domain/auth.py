"""What authenticating a REST request means, expressed as values.

Everything about signing a request that can be decided without a key and without
a socket — which turns out to be all of it except the signature itself. Which
algorithm a credential implies, which bytes get signed, where the signature goes
afterwards and what makes a request refusable are questions no cryptographic
library helps with, and getting any of them wrong produces a signature over the
wrong string.

**The exact-bytes invariant is the deliverable, and Phase 034 made it nearly
free.** Binance's rule is that *"the signature payload of your request is the
query string concatenated without separator to the HTTP body"*, with *"any
non-ASCII character percent-encoded before signing"*. GLOBIN's query string is
already produced by :meth:`~globin.domain.rest.QueryParameters.canonical`, which
renders in declaration order with both sides through
:func:`~globin.domain.rest.percent_encode`. So appending one parameter yields

.. code-block:: text

    canonical(items + signature) == canonical(items) + "&signature=" + encode(sig)

and the signed span is a literal **prefix** of what goes on the wire — a string
equality a test can assert rather than a property somebody argues for.
:func:`signed_parameters` is the only function that appends it, and
:class:`AuthenticatedRequest` proves the prefix held.

**Signer selection is a lookup, never a branch.** Phase 033's registry already
records ``key_types`` per endpoint, so *which algorithms may sign this* is data
read from a committed document. There is no ``if family == "spot"`` here and no
default: :func:`algorithm_for` is total over
:class:`~globin.domain.api_reality.ApiKeyType` and has no fallback, so a key type
the registry does not list for an endpoint is a refusal rather than a quiet
downgrade to HMAC. ADR-0091 records why that matters more than it looks: HMAC is
the algorithm the venue calls **deprecated**, so *fall back to HMAC* would be
falling back to the one the venue is asking people to leave.

**The taxonomy is an enumeration, not new exception classes.**
:mod:`globin.errors` declares exactly five faults on the axis of *who must act*,
and ``tests/contract/test_error_taxonomy_contract.py`` holds the correspondence
exact in both directions — a sixth kind of fault cannot be added by subclassing.
:class:`AuthStatus` is therefore a reason code in the shape
:class:`~globin.domain.rest_endpoint.ResolutionStatus` and
:class:`~globin.domain.secrets.StoreFault` already use, and a caller that needs to
raise chooses the fault domain the reason implies.

**No secret reaches this module and no key type is loaded here.** A
:class:`CredentialBinding` carries two
:class:`~globin.domain.secrets.SecretReference` values, which are ordinary data by
design. The material is resolved in the narrowest possible scope by
:mod:`globin.application.auth` and handed to a signer; nothing here can hold it,
because nothing here has a field for it.

What this module does not know: any venue host, any base URL, what time it is,
whether a credential exists, or how to compute a signature.
"""

import base64
import binascii
import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.domain.api_reality import ApiKeyType
from globin.domain.auth_timing import (
    RECV_WINDOW_PARAMETER,
    TIMESTAMP_PARAMETER,
    RecvWindow,
    TimestampUnit,
)
from globin.domain.observability import REDACTED
from globin.domain.rest import (
    QueryParameters,
    RequestBody,
    RequestSecurityIntent,
    RestRequest,
    percent_encode,
)
from globin.domain.secrets import SecretReference
from globin.errors import ValidationError

SCHEMA: Final[str] = "globin.rest.auth"
"""What a document produced by this surface calls itself."""

SCHEMA_VERSION: Final[int] = 1
"""The version every document this surface emits is written against."""

PHASE: Final[int] = 35
"""The phase that built this. Recorded in evidence rather than inferred."""

API_KEY_HEADER: Final[str] = "X-MBX-APIKEY"
"""The header a request presents its API key in.

Its exact documented spelling, recorded with provenance in
``docs/engineering/auth-contract.toml`` and compared against this constant by
``tests/contract/test_auth_contract.py``. The Spot testnet document confirms it is
the same header for every key type: the key goes *"in the ``X-MBX-APIKEY`` header
of your requests, exactly the same way as you would do for HMAC-SHA-256 API
Keys."*

**It matches** :data:`~globin.domain.observability.SENSITIVE_KEY_FRAGMENTS`
through ``api_key`` **case-insensitively**, which is what makes a field named
after it redacted by the existing mechanism rather than by a new one.
"""

SIGNATURE_PARAMETER: Final[str] = "signature"
"""What the venue calls the signature parameter. Its exact documented spelling.

Also a member of :data:`~globin.domain.observability.SENSITIVE_KEY_FRAGMENTS`, so
a diagnostic field carrying this name is redacted without anything here asking.
"""

FINGERPRINT_LENGTH: Final[int] = 12
"""How many hexadecimal characters an API key fingerprint carries.

Twelve, which is 48 bits — enough that two keys colliding is not a practical
concern for an operator with a handful of credentials, and far too few to narrow a
search for the key itself.
"""


MAX_SIGNATURE_LENGTH: Final[int] = 1024
"""How long a rendered signature may be before it is refused.

An RSA-4096 signature is 512 bytes, which is 684 characters of base64 and about
900 once percent-encoded — the largest any documented key type produces. This
bounds it with room rather than trimming it close, because the cost of the bound
being slightly loose is nothing and the cost of it being slightly tight is a key
size the venue supports and GLOBIN refuses.
"""


class SecurityType(StrEnum):
    """What a request needs from a credential, in the venue's own vocabulary.

    **Four members, exactly the four the documentation tabulates**, and the
    absence of a fifth is a finding rather than an omission. The table lists
    ``NONE``, ``TRADE``, ``USER_DATA`` and ``USER_STREAM``; ``MARGIN`` appears in
    older material and in no current Spot REST table, so adding it would be
    inventing a security classification for a surface that does not use one.

    **There is no API-key-without-signature tier on this surface.** Quoted:
    *"Except for ``NONE``, all endpoints with a security type are considered
    ``SIGNED`` requests (i.e. including a ``signature``)."* So
    :attr:`requires_api_key` and :attr:`requires_signature` answer identically for
    every member, and they are two properties rather than one because they are two
    questions the venue could in principle answer differently — Phase 033's
    :class:`~globin.domain.api_reality.AuthMechanism` carries an ``API_KEY`` member
    for surfaces beyond REST. Collapsing them here would make a future surface that
    did split them unable to say so.
    """

    NONE = "NONE"
    """Public market data. No key, no signature, and nothing consults the store."""

    TRADE = "TRADE"
    """Placing and cancelling orders."""

    USER_DATA = "USER_DATA"
    """Private account information: order status, trading history."""

    USER_STREAM = "USER_STREAM"
    """Managing user data stream subscriptions. **Signed, like the other two.**"""

    @property
    def requires_api_key(self) -> bool:
        """Whether a request of this type presents an API key.

        Returns:
            ``True`` for everything but :attr:`NONE`.
        """
        return self is not SecurityType.NONE

    @property
    def requires_signature(self) -> bool:
        """Whether a request of this type carries a signature.

        Returns:
            ``True`` for everything but :attr:`NONE`, per the quotation above.
        """
        return self is not SecurityType.NONE

    @property
    def intent(self) -> RequestSecurityIntent:
        """What Phase 034's transport should be told this request needs.

        Returns:
            :attr:`~globin.domain.rest.RequestSecurityIntent.PUBLIC` for
            :attr:`NONE`, and
            :attr:`~globin.domain.rest.RequestSecurityIntent.SIGNED` otherwise.

        Never :attr:`~globin.domain.rest.RequestSecurityIntent.API_KEY`, because
        no Spot REST endpoint is documented as accepting one — the registry records
        ``signed`` or ``none`` on all ten REST rows and ``api_key`` on none. That
        member exists for a surface this module does not serve.
        """
        return (
            RequestSecurityIntent.PUBLIC
            if self is SecurityType.NONE
            else RequestSecurityIntent.SIGNED
        )


class SignatureAlgorithm(StrEnum):
    """How a signature is computed.

    One member per :class:`~globin.domain.api_reality.ApiKeyType`, and the mapping
    is total in both directions. A fourth would be a new key type at the venue,
    which is a registry change and a signer implementation rather than a member
    added here on its own.
    """

    HMAC_SHA256 = "hmac_sha256"
    """*"Use the ``secretKey`` of your API key as the signing key for the
    HMAC-SHA-256 algorithm."* Symmetric, and the algorithm the venue documents as
    deprecated."""

    RSA_PKCS1V15_SHA256 = "rsa_pkcs1v15_sha256"
    """*"the RSASSA-PKCS1-v1_5 algorithm with SHA-256 hash function."*

    **Not PSS.** The testnet document states it outright: *"We currently do not
    support the PSS signature scheme."* The two are interchangeable to a careless
    reading of a library's API and produce signatures the venue rejects."""

    ED25519 = "ed25519"
    """PureEdDSA over Curve25519, per RFC 8032. Takes no separate digest step.

    The venue's recommended key type, and the one whose worked examples in the
    official documentation are unusable — ``docs/research/phase_035_sources.md``
    S-05 records that both are RSA outputs."""


class SignatureEncoding(StrEnum):
    """How a computed signature is rendered before it reaches the query string.

    Two members, and which applies is a property of the algorithm rather than a
    choice: *"Encode the HMAC-SHA-256 output as a hex string"* against *"Encode the
    output in base64"* for both asymmetric types.
    """

    HEX = "hex"
    """Lowercase hexadecimal. The venue documents HMAC signatures as *"not
    case-sensitive"*, so the case is GLOBIN's choice and lowercase is chosen for
    determinism rather than because the venue asked."""

    BASE64 = "base64"
    """Standard base64 with padding, then percent-encoded like any other value.

    **Case is never normalised.** Both asymmetric types are documented
    *"case-sensitive"*, so an ``upper()`` or ``lower()`` anywhere on this path
    invalidates every request. There is no such call, and a test asserts the
    absence."""


class ParameterPlacement(StrEnum):
    """Which parts of a request the signature payload is built from.

    Three members, because the venue's rule names two spans and either may be
    empty: *"the query string concatenated without separator to the HTTP body."*
    A GET has no body and a form POST may have no query, and both are the same rule
    with one span empty.

    Modelled per :class:`SigningProfile` rather than assumed globally, because
    ADR-0091's whole point is that a product's signing contract is read rather than
    inherited. Spot uses :attr:`QUERY_THEN_BODY`, which reduces to *query only* for
    every request GLOBIN sends today.
    """

    QUERY_ONLY = "query_only"
    BODY_ONLY = "body_only"
    QUERY_THEN_BODY = "query_then_body"


class AuthStatus(StrEnum):
    """Whether a request may be signed, and if not, precisely why.

    Twelve refusal members rather than one, and the reason is the reason
    :class:`~globin.domain.rest_endpoint.ResolutionStatus` has nine: an operator
    reading a refusal needs to know whether to enrol a credential, change a
    setting, install a library or stop asking. A single ``refused`` sends all four
    to the same place.

    **These are reason codes, not exception classes.** :mod:`globin.errors`
    declares five faults on the axis of *who must act* and a contract test holds
    the correspondence exact, so a taxonomy of thirteen authentication errors
    cannot be expressed as thirteen classes. Where a caller must raise, the fault
    domain follows from the reason: an absent credential is the operator's to
    supply, a mismatched key type is a configuration fault, and a signer that
    failed on well-formed input is a defect in GLOBIN.
    """

    RESOLVED = "resolved"
    """Every gate passed. A signature can be produced."""

    ENVIRONMENT_FORBIDS_CREDENTIAL = "environment_forbids_credential"
    """The environment's class does not accept a credential at all.

    Gate 1, checked before the registry, before a credential is looked up and
    before a signer is chosen. Internal simulation reaches no venue, so there is
    nobody to present a credential to — see
    :mod:`globin.domain.environment_class`."""

    ENVIRONMENT_UNCLASSIFIED = "environment_unclassified"
    """The environment name has no declared class, so its guarantees are unknown.

    Refused rather than defaulted. ADR-0006 forbids treating *not production* as a
    single thing, and defaulting an unknown name to the safest class would still be
    guessing which environment this is."""

    ENDPOINT_UNRESOLVED = "endpoint_unresolved"
    """Phase 034's endpoint resolution refused, so there is nowhere to send this."""

    AUTHENTICATION_NOT_REQUIRED = "authentication_not_required"
    """The request is public and asked to be signed.

    A refusal rather than a no-op, because signing a public request would attach a
    credential to a call that did not need one — which is a leak, not an
    inefficiency."""

    MISSING_CREDENTIAL = "missing_credential"
    """No credential is configured for this product and environment."""

    CREDENTIAL_TYPE_MISMATCH = "credential_type_mismatch"
    """The configured key type is not among those the endpoint documents.

    The refusal that stops an Ed25519 credential being offered to a surface
    recorded as accepting only HMAC."""

    UNSUPPORTED_AUTH_CAPABILITY = "unsupported_auth_capability"
    """The endpoint's documented authentication mechanism cannot carry this request.

    ``unknown`` counts here alongside ``none``: *not documented* and *documented as
    needing nothing* are different facts and both answer no."""

    UNSUPPORTED_SIGNING_ALGORITHM = "unsupported_signing_algorithm"
    """No algorithm is mapped for the configured key type."""

    SIGNER_UNAVAILABLE = "signer_unavailable"
    """The algorithm is known and nothing on this host can compute it.

    What an absent ``cryptography`` produces for RSA and Ed25519. **Never a
    downgrade to HMAC**: the venue documents HMAC as deprecated, so falling back
    would move the operator onto the algorithm they are being asked to leave, using
    a key they have not enrolled."""

    INVALID_PRIVATE_KEY_MATERIAL = "invalid_private_key_material"
    """The material resolved for this credential is not a usable key of its type.

    A corrupt PEM, a key serialised in a format other than PKCS#8, an
    encrypted key with no passphrase, or a key whose actual algorithm contradicts
    the declared one."""

    INVALID_RECV_WINDOW = "invalid_recv_window"
    """The configured validity window is not one the venue accepts."""

    INVALID_SIGNING_PAYLOAD = "invalid_signing_payload"
    """The request cannot be reduced to a payload, or already carries a signature."""

    SIGNATURE_GENERATION_FAILED = "signature_generation_failed"
    """A signer was selected, given well-formed input, and did not produce a
    signature. Always a defect rather than an expected outcome."""

    SECRET_MATERIALIZATION_FAILED = "secret_materialization_failed"  # noqa: S105 -- a reason, not one
    """The store could not return the material a configured credential names."""

    CAPABILITY_DRIFT = "capability_drift"
    """The registry and the venue's documentation disagree about this surface.

    Recorded as a distinct reason so drift is never silently resolved in either
    direction. Nothing in this phase writes it from a live response —
    :attr:`~globin.domain.api_reality.EvidenceKind.OBSERVED` remains unwritable —
    but a caller comparing a declaration against the registry has somewhere to put
    the disagreement."""

    @property
    def permits(self) -> bool:
        """Whether this status allows a signature to be produced."""
        return self is AuthStatus.RESOLVED


def algorithm_for(key_type: ApiKeyType) -> SignatureAlgorithm:
    """Which algorithm a key type implies.

    Args:
        key_type: The key type, from Phase 033's registry or from configuration.

    Returns:
        The algorithm.

    Raises:
        ValidationError: On a key type with no mapped algorithm, which the
            enumeration being closed already prevents.

    **Total, and with no fallback branch.** A ``return SignatureAlgorithm.HMAC_SHA256``
    at the end would make every unmapped key type silently HMAC, which is the
    single most dangerous default available here: HMAC is the algorithm the venue
    documents as deprecated, so the fallback would move a caller onto it using a
    secret they enrolled for something else. ADR-0091 records the rule.
    """
    mapping = {
        ApiKeyType.HMAC: SignatureAlgorithm.HMAC_SHA256,
        ApiKeyType.RSA: SignatureAlgorithm.RSA_PKCS1V15_SHA256,
        ApiKeyType.ED25519: SignatureAlgorithm.ED25519,
    }
    algorithm = mapping.get(key_type)
    if algorithm is None:
        msg = (
            f"no signature algorithm is mapped for key type {key_type.value!r}; a key type "
            "without an algorithm is refused rather than defaulted"
        )
        raise ValidationError(msg)
    return algorithm


def encoding_for(algorithm: SignatureAlgorithm) -> SignatureEncoding:
    """How an algorithm's output is rendered.

    Args:
        algorithm: The algorithm.

    Returns:
        The encoding.

    Raises:
        ValidationError: On an algorithm with no mapped encoding.

    Total for the same reason as :func:`algorithm_for`, and the default that is
    absent here is subtler: hex would be a *plausible* rendering for an asymmetric
    signature and the venue would reject every one of them, with a message about a
    signature rather than about an encoding.
    """
    mapping = {
        SignatureAlgorithm.HMAC_SHA256: SignatureEncoding.HEX,
        SignatureAlgorithm.RSA_PKCS1V15_SHA256: SignatureEncoding.BASE64,
        SignatureAlgorithm.ED25519: SignatureEncoding.BASE64,
    }
    encoding = mapping.get(algorithm)
    if encoding is None:
        msg = f"no signature encoding is mapped for algorithm {algorithm.value!r}"
        raise ValidationError(msg)
    return encoding


def key_type_for(algorithm: SignatureAlgorithm) -> ApiKeyType:
    """Which key type an algorithm belongs to.

    Args:
        algorithm: The algorithm.

    Returns:
        The key type.

    Raises:
        ValidationError: On an algorithm with no mapped key type.

    The inverse of :func:`algorithm_for`, present so
    ``tests/contract/test_auth_contract.py`` can assert the two are inverses over
    every member rather than checking one direction and trusting the other.
    """
    mapping = {
        SignatureAlgorithm.HMAC_SHA256: ApiKeyType.HMAC,
        SignatureAlgorithm.RSA_PKCS1V15_SHA256: ApiKeyType.RSA,
        SignatureAlgorithm.ED25519: ApiKeyType.ED25519,
    }
    key_type = mapping.get(algorithm)
    if key_type is None:
        msg = f"no key type is mapped for algorithm {algorithm.value!r}"
        raise ValidationError(msg)
    return key_type


def asymmetric(algorithm: SignatureAlgorithm) -> bool:
    """Whether an algorithm signs with a private key rather than a shared secret.

    Args:
        algorithm: The algorithm.

    Returns:
        ``True`` for RSA and Ed25519.

    Named rather than compared inline, so that the places where the distinction
    matters — key loading, case sensitivity, and which absent library withdraws
    which capability — all read the same and a search finds every one.
    """
    return algorithm is not SignatureAlgorithm.HMAC_SHA256


@dataclass(frozen=True, slots=True, order=True)
class CredentialBinding:
    """Which secrets carry one credential, and what kind of key it is.

    Raises:
        ValidationError: If the two references name different environments, or if
            the key identifier and the material are the same reference.

    **Two references and no value.** A :class:`~globin.domain.secrets.SecretReference`
    is ordinary data by design — printable, loggable, serialisable — and a
    :class:`~globin.domain.secrets.SecretValue` is deliberately none of those. This
    type holds only the first kind, so there is no field a secret could occupy and
    no accessor that could return one. Material is resolved by
    :mod:`globin.application.auth` in the narrowest scope that needs it.

    **The two references must not be the same**, which is checked rather than
    assumed. Binance's key identifier is public and travels in a header on every
    request; the secret or private key never leaves this machine. A binding that
    named one reference twice would put the material in the header.
    """

    api_key: SecretReference
    material: SecretReference
    key_type: ApiKeyType

    def __post_init__(self) -> None:
        """Refuse a binding that could send the wrong half of a credential."""
        if self.api_key.environment != self.material.environment:
            msg = (
                f"a credential binds an API key in {self.api_key.environment.text!r} to material "
                f"in {self.material.environment.text!r}; a credential belongs to one environment"
            )
            raise ValidationError(msg)
        if self.api_key == self.material:
            msg = (
                "a credential names one reference for both its API key and its material; the "
                "key identifier is sent in a header on every request and the material never is"
            )
            raise ValidationError(msg)

    @property
    def environment(self) -> str:
        """Which environment this credential belongs to."""
        return self.api_key.environment.text

    @property
    def algorithm(self) -> SignatureAlgorithm:
        """Which algorithm this credential's key type implies."""
        return algorithm_for(self.key_type)

    def as_record(self) -> dict[str, object]:
        """This binding as plain JSON-safe values.

        Returns:
            The environment, the key type, and the two references **by name**.
            Names are what a reference is; no material is reachable from here.
        """
        return {
            "environment": self.environment,
            "key_type": self.key_type.value,
            "algorithm": self.algorithm.value,
            "api_key_name": self.api_key.name,
            "material_name": self.material.name,
        }


@dataclass(frozen=True, slots=True)
class SigningProfile:
    """How one product's surface wants a request signed.

    Raises:
        ValidationError: On an empty parameter or header name, or on an encoding
            that does not match the algorithm.

    **A profile per surface rather than one global rule**, which is ADR-0091 in
    type form. Binance's products are documented separately and nothing guarantees
    they agree; a single hard-coded contract would make a difference between two
    products inexpressible, and the way that failure shows up is a signature the
    other product silently rejects.

    The encoding is checked against the algorithm rather than accepted, because the
    pair is determined by the documentation and a profile carrying a mismatched one
    is a typo that would otherwise reach the venue.
    """

    algorithm: SignatureAlgorithm
    encoding: SignatureEncoding
    placement: ParameterPlacement
    signature_parameter: str = SIGNATURE_PARAMETER
    api_key_header: str = API_KEY_HEADER

    def __post_init__(self) -> None:
        """Refuse a profile that would render a signature the venue cannot read."""
        if not self.signature_parameter:
            msg = "a signing profile names no signature parameter"
            raise ValidationError(msg)
        if not self.api_key_header:
            msg = "a signing profile names no API key header"
            raise ValidationError(msg)
        expected = encoding_for(self.algorithm)
        if self.encoding is not expected:
            msg = (
                f"a signing profile pairs {self.algorithm.value} with {self.encoding.value}; "
                f"the documentation pairs it with {expected.value}"
            )
            raise ValidationError(msg)

    @property
    def case_sensitive(self) -> bool:
        """Whether the venue compares this signature case-sensitively.

        Returns:
            ``True`` for both asymmetric algorithms.

        Carried so the property is legible rather than implied by the encoding.
        Nothing changes case either way — this reports a fact about the venue, and
        the code's rule is simply that no case transform exists anywhere on the
        signing path.
        """
        return asymmetric(self.algorithm)

    def as_record(self) -> dict[str, object]:
        """This profile as plain JSON-safe values."""
        return {
            "algorithm": self.algorithm.value,
            "encoding": self.encoding.value,
            "placement": self.placement.value,
            "signature_parameter": self.signature_parameter,
            "api_key_header": self.api_key_header,
            "case_sensitive": self.case_sensitive,
        }


def spot_profile(algorithm: SignatureAlgorithm) -> SigningProfile:
    """The signing profile Binance documents for Spot REST.

    Args:
        algorithm: Which algorithm the configured key type implies.

    Returns:
        The profile.

    One function rather than a table, because Spot is the one product family whose
    REST surface the registry records as supported and there is nothing yet to
    tabulate against. A second product with a documented REST surface adds a second
    function and a row in ``docs/engineering/auth-contract.toml``; it does not add
    a branch here, because ADR-0091 forbids one product's contract standing in for
    another's.

    :attr:`ParameterPlacement.QUERY_THEN_BODY` is the venue's rule stated exactly
    — *"the query string concatenated without separator to the HTTP body"* — and it
    reduces to *query only* for every request GLOBIN sends today, because nothing
    yet sends a body.
    """
    return SigningProfile(
        algorithm=algorithm,
        encoding=encoding_for(algorithm),
        placement=ParameterPlacement.QUERY_THEN_BODY,
    )


class GeneratedSignature:
    """A computed signature, which refuses to render itself.

    Args:
        rendered: The signature as it will appear in the query string, before
            percent-encoding.
        algorithm: Which algorithm produced it.

    Raises:
        ValidationError: On an empty signature, one longer than
            :data:`MAX_SIGNATURE_LENGTH`, or one whose characters are outside the
            algorithm's encoding.

    **Shaped after** :class:`~globin.domain.secrets.SecretValue`, and for the same
    reasons rather than by imitation. A signature is not a secret in the sense a
    key is — it is sent to the venue in clear — but it is derived from one, it is
    listed in :data:`~globin.domain.observability.SENSITIVE_KEY_FRAGMENTS`, and a
    stray ``repr`` in a traceback is exactly how one reaches a log. So:
    :meth:`__str__`, :meth:`__repr__` and :meth:`__format__` all yield
    :data:`~globin.domain.observability.REDACTED`, there is no ``__dict__`` for
    :func:`vars` to walk, and the one accessor is named for what it is.

    It is **unhashable** for the reason ``SecretValue`` is: defining
    :meth:`__eq__` without ``__hash__`` makes it so, and an unhashable object
    cannot become a dictionary key or a set member, which removes two ways it could
    reach a structure that is later rendered.

    **No case transform exists on this type.** RSA and Ed25519 signatures are
    documented case-sensitive, so an ``upper()`` or ``lower()`` here would
    invalidate every asymmetric request while leaving every HMAC test passing.
    """

    __slots__ = ("_algorithm", "_rendered")

    def __init__(self, rendered: str, algorithm: SignatureAlgorithm) -> None:
        """Store a signature after checking it could be one.

        Args:
            rendered: The signature text.
            algorithm: Which algorithm produced it.

        Raises:
            ValidationError: As documented on the class.
        """
        if not rendered:
            msg = f"a {algorithm.value} signer produced an empty signature"
            raise ValidationError(msg)
        if len(rendered) > MAX_SIGNATURE_LENGTH:
            msg = (
                f"a {algorithm.value} signature is {len(rendered)} characters and the limit "
                f"is {MAX_SIGNATURE_LENGTH}"
            )
            raise ValidationError(msg)
        encoding = encoding_for(algorithm)
        if encoding is SignatureEncoding.HEX:
            try:
                bytes.fromhex(rendered)
            except ValueError as fault:
                msg = f"a {algorithm.value} signature is declared hex and is not"
                raise ValidationError(msg) from fault
        else:
            try:
                base64.b64decode(rendered, validate=True)
            except (binascii.Error, ValueError) as fault:
                msg = f"a {algorithm.value} signature is declared base64 and is not"
                raise ValidationError(msg) from fault
        self._rendered = rendered
        self._algorithm = algorithm

    @property
    def algorithm(self) -> SignatureAlgorithm:
        """Which algorithm produced this signature. Safe to publish."""
        return self._algorithm

    def __str__(self) -> str:
        """Render as the redaction marker."""
        return REDACTED

    def __repr__(self) -> str:
        """Render as the redaction marker.

        Matters more than :meth:`__str__`, because a traceback, a debugger, a
        ``%r`` format and a container's rendering all reach for this one.
        """
        return REDACTED

    def __format__(self, format_spec: str) -> str:
        """Render as the redaction marker, whatever was asked for.

        Args:
            format_spec: Ignored.

        Returns:
            :data:`~globin.domain.observability.REDACTED`.

        Overridden because :meth:`object.__format__` with a non-empty spec does not
        route through :meth:`__str__`, so ``f"{signature:>40}"`` would otherwise
        raise — and a raising redaction is one somebody removes.
        """
        return REDACTED

    def __eq__(self, other: object) -> bool:
        """Compare two signatures by value and algorithm.

        Args:
            other: The object to compare against.

        Returns:
            ``True`` when both carry the same text from the same algorithm.

        Not constant-time, and deliberately not. ``SecretValue`` compares with
        :func:`hmac.compare_digest` because a timing leak there reveals key
        material; a signature is transmitted in clear on every request, so there is
        nothing to leak, and pretending otherwise would suggest this type offers a
        guarantee it does not.
        """
        if not isinstance(other, GeneratedSignature):
            return NotImplemented
        return self._rendered == other._rendered and self._algorithm is other._algorithm

    __hash__ = None  # type: ignore[assignment]

    def value(self) -> str:
        """The signature itself, for the one caller that must have it.

        Returns:
            The rendered signature, unchanged.

        Named for what it is rather than for what it does, matching
        ``SECRET_STORE_CONTRACT.md`` §5's prohibition on the vocabulary of display
        — ``reveal``, ``dump``, ``export`` — which a contract test enforces against
        module and command names.
        """
        return self._rendered

    def as_record(self) -> dict[str, object]:
        """This signature as plain JSON-safe values, **without the signature**.

        Returns:
            Its algorithm and its length. The value has no representation here and
            cannot acquire one by accident, because it is not read.
        """
        return {"algorithm": self._algorithm.value, "length": len(self._rendered)}


@dataclass(frozen=True, slots=True)
class SigningPayload:
    """The exact characters a signature is computed over.

    Raises:
        ValidationError: If either span carries the signature parameter, which
            would mean signing a request that already claims to be signed.

    Two spans rather than one string, because the venue's rule names two and a
    reader checking an implementation against the documentation should find the
    same two. :attr:`text` is their concatenation *without separator*, which is the
    documentation's own wording.

    **:meth:`as_record` carries lengths and never the text.** A signing payload for
    an order holds the symbol, the side, the quantity and the price; it is not
    credential material and it is not a diagnostic field either.
    """

    query_span: str
    body_span: str = ""

    def __post_init__(self) -> None:
        """Refuse a payload that already carries a signature."""
        marker = f"{SIGNATURE_PARAMETER}="
        for span, label in ((self.query_span, "query"), (self.body_span, "body")):
            if span.startswith(marker) or f"&{marker}" in span:
                msg = (
                    f"a signing payload's {label} span already carries a {SIGNATURE_PARAMETER} "
                    "parameter; the signature is appended after the payload is built, never before"
                )
                raise ValidationError(msg)

    @property
    def text(self) -> str:
        """The payload, as the characters that get signed.

        Returns:
            The query span concatenated to the body span **without separator**,
            exactly as documented.
        """
        return f"{self.query_span}{self.body_span}"

    def as_bytes(self) -> bytes:
        """The payload as the bytes a signer receives.

        Returns:
            UTF-8, stated explicitly rather than left to a default.

        The encoding is named because the venue's rule is about *characters* —
        *"any non-ASCII character must be percent-encoded before signing"* — and
        after percent-encoding every character is ASCII, so UTF-8 and ASCII agree
        here. Naming it anyway means the one case where they would not is a
        decision rather than an accident.
        """
        return self.text.encode("utf-8")

    def as_record(self) -> dict[str, object]:
        """This payload as plain JSON-safe values, **carrying no payload**.

        Returns:
            The length of each span and of the whole. The characters themselves
            never reach a record.
        """
        return {
            "query_length": len(self.query_span),
            "body_length": len(self.body_span),
            "total_length": len(self.text),
        }


def signing_payload(
    parameters: QueryParameters,
    body: RequestBody | None,
    profile: SigningProfile,
) -> SigningPayload:
    """Reduce a request to the exact characters that will be signed.

    Args:
        parameters: The query parameters, **already carrying the timestamp and
            window** and not yet carrying a signature.
        body: The request body, if there is one.
        profile: Which spans this surface signs.

    Returns:
        The payload.

    Raises:
        ValidationError: If the body is not valid UTF-8, or if the parameters
            already carry a signature.

    **The query span is** :meth:`~globin.domain.rest.QueryParameters.canonical`
    **and nothing else**, which is the whole exact-bytes guarantee in one line. It
    is not re-rendered, not re-ordered and not re-encoded: the string this signs is
    the string :meth:`~globin.domain.rest.RestRequest.canonical_target` will put on
    the wire, because both call the same method on the same frozen value.

    The body is decoded rather than re-serialised, for the reason
    :class:`~globin.domain.rest.RequestBody` holds bytes at all — an object
    re-serialised at send time may not produce the bytes that were signed.
    """
    if any(key == profile.signature_parameter for key in parameters.declared()):
        msg = (
            f"the parameters already carry {profile.signature_parameter!r}; a signature is "
            "appended after the payload is built, never included in it"
        )
        raise ValidationError(msg)
    signs_query = profile.placement is not ParameterPlacement.BODY_ONLY
    query_span = parameters.canonical() if signs_query else ""
    body_span = ""
    if body is not None and profile.placement is not ParameterPlacement.QUERY_ONLY:
        try:
            body_span = body.content.decode("utf-8")
        except UnicodeDecodeError as fault:
            msg = (
                "a request body is not valid UTF-8 and cannot be part of a signing payload; "
                "the venue's rule concatenates the body as characters"
            )
            raise ValidationError(msg) from fault
    return SigningPayload(query_span=query_span, body_span=body_span)


def timed_parameters(
    parameters: QueryParameters,
    *,
    timestamp: int,
    recv_window: RecvWindow | None = None,
) -> QueryParameters:
    """Add the timing parameters a signed request must carry.

    Args:
        parameters: What the caller asked for.
        timestamp: The moment, already in the unit the caller chose.
        recv_window: The validity window, or ``None`` to send none.

    Returns:
        A new parameter set with ``timestamp`` and, when given, ``recvWindow``
        appended in that order.

    Raises:
        ValidationError: If either parameter is already present, which would mean
            the venue receiving two and choosing one.

    **Appended rather than merged**, so declaration order is preserved and the
    canonical rendering stays a function of the caller's own ordering plus a fixed
    suffix. That is what keeps the signed span predictable enough to assert.

    The window is rendered by :meth:`~globin.domain.auth_timing.RecvWindow.__str__`,
    which preserves the operator's scale — ``5000.000`` stays ``5000.000`` — because
    the venue sees the rendering and GLOBIN signs what the venue sees.
    """
    declared = set(parameters.declared())
    for name in (TIMESTAMP_PARAMETER, RECV_WINDOW_PARAMETER):
        if name in declared:
            msg = (
                f"a request already carries {name!r}; the timing parameters are added once, "
                "by the signing path, so that the value signed is the value sent"
            )
            raise ValidationError(msg)
    items = list(parameters.items)
    items.append((TIMESTAMP_PARAMETER, timestamp))
    if recv_window is not None:
        items.append((RECV_WINDOW_PARAMETER, str(recv_window)))
    return QueryParameters(items=tuple(items))


def signed_parameters(
    parameters: QueryParameters,
    signature: GeneratedSignature,
    profile: SigningProfile,
) -> QueryParameters:
    """Append the signature to a request's parameters.

    Args:
        parameters: Exactly what was signed.
        signature: What signing produced.
        profile: Which parameter name the signature takes.

    Returns:
        A new parameter set whose canonical rendering is the signed span, an ``&``,
        the parameter name, an ``=`` and the percent-encoded signature.

    Raises:
        ValidationError: If a signature is already present.

    **The one place a signature is added**, so the invariant has one site to hold
    rather than several to keep consistent. Appending is what makes the signed span
    a literal prefix of the transmitted query string, which
    :meth:`AuthenticatedRequest.wire_matches` then asserts rather than assumes.
    """
    if any(key == profile.signature_parameter for key in parameters.declared()):
        msg = (
            f"a request already carries {profile.signature_parameter!r} and cannot be signed twice"
        )
        raise ValidationError(msg)
    appended = (profile.signature_parameter, signature.value())
    return QueryParameters(items=(*parameters.items, appended))


@dataclass(frozen=True, slots=True)
class AuthenticatedRequest:
    """A signed request, with the evidence that what was signed is what is sent.

    Raises:
        ValidationError: If the request carries no signature, if the signed span is
            empty, or if the API key header is missing from the request.

    **Frozen, and that is the retry contract.** Phase 043 owns retry and inherits
    one rule from here: this object cannot be edited, so a retry that changed a
    parameter would have to build a new request, which means signing again. There
    is no path by which a mutated request keeps an old signature, because there is
    no path by which a request is mutated. :meth:`requires_resignature` is the
    declared hook for that later phase; nothing calls it yet, and it is a
    predicate rather than a mechanism precisely so it adds no behaviour now.

    **The proof is** :meth:`wire_matches`, and it is a string comparison rather
    than an argument. The transport re-renders the target from this same frozen
    request, so the bytes it sends are produced by the same method that produced
    the signed span — but "produced by the same method" is a claim about code, and
    a comparison of the two strings is a claim about this request.
    """

    request: RestRequest
    signed_span: str
    profile: SigningProfile
    timestamp: int
    timestamp_unit: TimestampUnit
    recv_window: RecvWindow | None = None

    def __post_init__(self) -> None:
        """Refuse a request that claims to be signed and is not."""
        if not self.signed_span:
            msg = "an authenticated request records an empty signed span"
            raise ValidationError(msg)
        if self.profile.signature_parameter not in self.request.parameters.transmitted():
            msg = (
                f"an authenticated request carries no {self.profile.signature_parameter!r} "
                "parameter; signing produced nothing that reaches the wire"
            )
            raise ValidationError(msg)
        names = {name.lower() for name, _ in self.request.headers}
        if self.profile.api_key_header.lower() not in names:
            msg = (
                f"an authenticated request carries no {self.profile.api_key_header} header; "
                "a signature without a key identifies nobody"
            )
            raise ValidationError(msg)

    def wire_matches(self, prefix: str = "") -> bool:
        """Whether the bytes that were signed are the bytes that will be sent.

        Args:
            prefix: The resolved endpoint's recorded path prefix.

        Returns:
            ``True`` when the transmitted query string begins with the signed span
            followed by the signature parameter, and nothing has been re-encoded in
            between.

        The invariant this phase exists to guarantee, checked rather than argued
        for. A ``False`` here means the request was signed over one string and
        would be sent as another, which the venue answers with ``-1022
        INVALID_SIGNATURE`` and which no offline test that compared *parameters*
        rather than *characters* would catch.
        """
        target = self.request.canonical_target(prefix)
        _, separator, query = target.partition("?")
        if not separator:
            return False
        expected = f"{self.signed_span}&{self.profile.signature_parameter}="
        return query.startswith(expected)

    def requires_resignature(self, now: int) -> bool:
        """Whether replaying this request would present a stale timestamp.

        Args:
            now: The current moment, in :attr:`timestamp_unit`.

        Returns:
            ``True`` when the elapsed time exceeds the declared window, or when no
            window was declared at all.

        **The declared hook Phase 043 plugs into, and nothing calls it here.** This
        phase builds no retry engine and there is no loop for this to control. It
        exists so the later phase inherits an answer rather than inventing one: a
        signed request has an expiry, replaying it after that expiry sends a
        request the venue will reject, and re-signing means building a new request
        because this one is frozen.

        A request with no declared window returns ``True`` unconditionally, which is
        the conservative direction: without a window GLOBIN cannot say the request
        is still valid, and *re-sign* is always safe where *replay* may not be.
        """
        if self.recv_window is None:
            return True
        per_millisecond = 1000 if self.timestamp_unit is TimestampUnit.MICROSECONDS else 1
        elapsed_millis = (now - self.timestamp) / per_millisecond
        return elapsed_millis > float(self.recv_window.millis)

    def as_record(self) -> dict[str, object]:
        """This request as plain JSON-safe values, **carrying no signature**.

        Returns:
            The request's own record, the profile, the timing, and the length of
            the signed span. **Neither the signature nor the signed span itself
            appears**: the span is the query string, which carries every parameter
            the caller sent.
        """
        return {
            "request": self.request.as_record(),
            "profile": self.profile.as_record(),
            "timestamp_unit": self.timestamp_unit.value,
            "recv_window": self.recv_window.as_record() if self.recv_window else None,
            "signed_span_length": len(self.signed_span),
        }


def api_key_fingerprint(api_key: str) -> str:
    """A short, non-reversible label for an API key.

    Args:
        api_key: The key identifier.

    Returns:
        The first :data:`FINGERPRINT_LENGTH` characters of the SHA-256 digest of
        the key, or an empty string for an empty key.

    Raises:
        ValidationError: Never; an empty key yields an empty fingerprint.

    **For telling two keys apart, not for identifying one.** An operator with two
    credentials enrolled needs to know which one a refusal was about, and printing
    a prefix of the key itself would publish part of the key. A truncated digest
    answers the question without carrying anything reversible: the key is 64
    characters of high-entropy text, so a preimage is not recoverable from twelve
    hex characters of its digest.

    It is **not** a secret fingerprint in the sense
    ``docs/security/SECRET_VAULT.md`` refuses — that document's point is that DPAPI
    derives a fresh key per call so two protections of one value differ, which
    makes a digest of *ciphertext* meaningless. This digests the key identifier
    itself, which is stable, and the key identifier is the half of a credential that
    travels in a header on every request.
    """
    if not api_key:
        return ""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


def encoded_signature(signature: GeneratedSignature) -> str:
    """A signature as it appears in the query string.

    Args:
        signature: What signing produced.

    Returns:
        The signature percent-encoded by
        :func:`~globin.domain.rest.percent_encode`.

    Present so the encoding step is named and testable on its own, and because the
    venue documents it as its own step: *"Percent-encode the base64 string."* The
    documented worked example encodes ``/`` to ``%2F``, ``+`` to ``%2B`` and ``=``
    to ``%3D``, all three of which GLOBIN's encoder already produces because none is
    in RFC 3986's unreserved set.

    **Callers do not normally use this.** :func:`signed_parameters` appends the raw
    signature and lets :meth:`~globin.domain.rest.QueryParameters.canonical` encode
    it, so the signature is encoded by the same function as every other value. This
    exists for the test that compares GLOBIN's output against the venue's published
    example.
    """
    return percent_encode(signature.value())


__all__ = [
    "API_KEY_HEADER",
    "FINGERPRINT_LENGTH",
    "MAX_SIGNATURE_LENGTH",
    "PHASE",
    "SCHEMA",
    "SCHEMA_VERSION",
    "SIGNATURE_PARAMETER",
    "AuthStatus",
    "AuthenticatedRequest",
    "CredentialBinding",
    "GeneratedSignature",
    "ParameterPlacement",
    "SecurityType",
    "SignatureAlgorithm",
    "SignatureEncoding",
    "SigningPayload",
    "SigningProfile",
    "algorithm_for",
    "api_key_fingerprint",
    "asymmetric",
    "encoded_signature",
    "encoding_for",
    "key_type_for",
    "signed_parameters",
    "signing_payload",
    "spot_profile",
    "timed_parameters",
]
