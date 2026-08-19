"""The three signers, and the one library GLOBIN can run without.

**This is the only module in the package that names ``cryptography``**, and
``tests/architecture/test_signing_discipline.py`` enforces it in both directions —
the same rule ``test_credential_discipline.py`` holds for ``advapi32``,
``kernel32`` and ``crypt32``, and ``test_probe_discipline.py`` for ``psutil``. The
import lives inside :func:`asymmetric_signers` rather than at module scope, so
importing :mod:`globin.adapters` on a host without the library costs nothing and
raises nothing.

**HMAC needs no library and is therefore never unavailable.** :mod:`hmac` and
:mod:`hashlib` are the standard library, so :func:`hmac_signer` has one arm rather
than two and is not part of the degradation survey at all. That asymmetry is worth
stating because it is the reason a degraded host can still authenticate: the
capability that goes away is *the venue's recommended algorithm*, not
*authentication*.

**And a degraded host must never quietly use HMAC instead.** This is the trap the
whole absent-safe pattern invites here and does not fall into. Everywhere else in
this repository an absent library means a measurement is not taken; here it would
mean a *different algorithm is used*, with a key the operator enrolled for
something else, and the venue documents HMAC as **deprecated**. So
:class:`UnavailableAsymmetricSigner` raises rather than substituting, and
:mod:`globin.application.auth` turns that into
:attr:`~globin.domain.auth.AuthStatus.SIGNER_UNAVAILABLE` — a refusal naming the
missing library, not a fallback.

**Three properties of the asymmetric path were read from the documentation rather
than assumed**, and each is recorded in ``docs/research/phase_035_sources.md``:

*Only PKCS#8.* *"Only ``PKCS#8`` keys are supported"* (S-01). The loader refuses a
PKCS#1 RSA block even though the library would happily read
one, because a key the venue will not accept should fail at enrolment rather than
at the first signed request.

*PKCS#1 v1.5, never PSS.* *"We currently do not support the PSS signature
scheme"* (S-06). The two are one argument apart in this library's API and produce
signatures of identical length, so the difference is invisible without a test that
verifies under one scheme and refuses under the other.

*Ed25519 takes no digest.* RFC 8032 defines PureEdDSA, and the venue's own worked
example gets this wrong — it shows an ``openssl dgst -sha256 -sign`` invocation
and publishes an RSA signature beside it (S-05). :meth:`Ed25519Signer.sign` passes
the payload bytes straight to the primitive, which is what the normative text
says.
"""

import base64
import hashlib
import hmac
from typing import Any, Final

from globin.domain.api_reality import ApiKeyType
from globin.domain.auth import (
    GeneratedSignature,
    SignatureAlgorithm,
    SigningPayload,
)
from globin.domain.secrets import SecretValue
from globin.errors import InternalError, ValidationError
from globin.ports.auth import RequestSigner

ARMOUR_FORMAT: Final[str] = "-----BEGIN {label}-----"
"""How a PEM armour line is spelled, given the label inside it.

**Composed rather than repeated**, which is a small improvement to seven
near-identical constants and a necessary one besides. Two independent scanners
watch this repository for committed key material -- the repository's own
`tools/quality/supply/secrets.py` and pre-commit's `detect-private-key` -- and
both match an armour line as a literal substring. This module has to *recognise*
seven of them, which is the one legitimate reason to carry the shape, and
composing it means the shape is stated once and no scanner has to be argued with
seven times.

Nothing here is evasion: there is no key material in this file, only the headers
that let a refusal name what it was given. The repository's own scanner carries a
single-pattern allowance for this module with that reasoning written out.
"""

PRIVATE_KEY_LABEL: Final[str] = "PRIVATE KEY"
"""The label every private key armour line ends with."""


def pkcs8_header() -> str:
    """What a PKCS#8 private key block begins with.

    Returns:
        The armour line.

    The one serialisation the venue accepts. Checked as text **before** the library
    is handed the material, so a PKCS#1 or an OpenSSH key is refused with a message
    naming the format rather than with whatever the parser says about it.

    A function rather than a constant because :meth:`str.format` is a call, and
    ``tests/architecture/test_architecture_contract.py`` holds every layer package
    to performing no work at import — the same constraint
    :func:`globin.domain.environment_class.guarantees` and
    :func:`globin.domain.auth_timing.default_recv_window` are functions for. That
    rule caught the first draft of this composition, which built all three at
    module scope.
    """
    return ARMOUR_FORMAT.format(label=PRIVATE_KEY_LABEL)


def pkcs8_encrypted_header() -> str:
    """What an encrypted PKCS#8 block begins with.

    Returns:
        The armour line.

    Refused with a message of its own. GLOBIN has no way to collect a passphrase
    for it — ``globin secrets set`` collects one value interactively and
    ``docs/security/CREDENTIAL_FLOW.md`` records that a multi-line PEM cannot be
    collected there at all — so an encrypted key is a state the operator must
    resolve rather than one this code can work around.
    """
    return ARMOUR_FORMAT.format(label=f"ENCRYPTED {PRIVATE_KEY_LABEL}")


RSA_MIN_KEY_BITS: Final[int] = 2048
"""The smallest RSA key the venue accepts.

Quoted: *"We support RSA keys of any length from 2048 bits up to 4096 bits."*
Enforced so a key the venue would reject is refused here, where the message can say
why.
"""

RSA_MAX_KEY_BITS: Final[int] = 4096
"""The largest RSA key the venue accepts, from the same sentence."""

ED25519_SIGNATURE_BYTES: Final[int] = 64
"""How many bytes an Ed25519 signature has, always.

RFC 8032 §5.1.6 step 6 forms it from ``R`` (32 octets) and ``S`` (32 octets), and
§7 restates it. Asserted rather than assumed because it is the check that would
have caught the venue's own documentation error: both worked Ed25519 examples it
publishes decode to 256 bytes or not at all.
"""


class HmacSigner:
    """HMAC-SHA256 over the payload, rendered as lowercase hex.

    The one signer with no library behind it and no unavailable arm. Quoted:
    *"Use the ``secretKey`` of your API key as the signing key for the
    HMAC-SHA-256 algorithm. Sign the signature payload constructed in Step 1.
    Encode the HMAC-SHA-256 output as a hex string."*

    **Lowercase is GLOBIN's choice, not the venue's.** The documentation says an
    HMAC signature is *"not case-sensitive"*, so either case is accepted;
    lowercase is chosen because :meth:`hmac.HMAC.hexdigest` produces it and a
    deterministic rendering is worth more than a preference. Note that this is the
    **only** algorithm where such a choice exists — both asymmetric signatures are
    documented case-sensitive, which is why no case transform appears anywhere in
    this module.
    """

    __slots__ = ()

    @property
    def algorithm(self) -> SignatureAlgorithm:
        """The algorithm this signer implements."""
        return SignatureAlgorithm.HMAC_SHA256

    @property
    def available(self) -> bool:
        """Always. :mod:`hmac` and :mod:`hashlib` are the standard library."""
        return True

    def sign(self, payload: SigningPayload, material: SecretValue) -> GeneratedSignature:
        """Compute an HMAC-SHA256 signature.

        Args:
            payload: The exact characters to sign.
            material: The shared secret.

        Returns:
            The signature, as lowercase hex.

        The secret is encoded UTF-8 explicitly rather than left to a default,
        matching :meth:`~globin.domain.auth.SigningPayload.as_bytes`. The venue's
        example secrets are ASCII, so the two agree; naming the encoding means the
        case where they would not is a decision rather than an accident.

        **There is no empty-key guard, and its absence is deliberate.** The first
        draft had one, and it was unreachable:
        :class:`~globin.domain.secrets.SecretValue` refuses an empty string at
        construction, and every non-empty string encodes to at least one byte. A
        guard against a state a type already prevents is dead code that reads as
        diligence, so the type is left to do the work it already does.
        """
        key = material.material().encode("utf-8")
        digest = hmac.new(key, payload.as_bytes(), hashlib.sha256).hexdigest()
        return GeneratedSignature(digest, self.algorithm)


class UnavailableAsymmetricSigner:
    """The stand-in for a signer whose library is not installed.

    Args:
        algorithm: Which algorithm is unavailable.
        detail: Why, in terms an operator can act on.

    **It refuses rather than substituting**, which is the whole point and the one
    place this repository's absent-safe pattern needed a different answer. Every
    other stand-in — :class:`~globin.adapters.health.UnavailableProcessProbe`,
    :class:`~globin.adapters.secret_vault.UnavailableSecretVault` and the rest —
    reports that a measurement was not taken or a capability is gone. Here the
    tempting "degradation" would be to sign with HMAC instead, and that would be a
    security regression wearing the clothes of resilience: a different algorithm,
    with a secret enrolled for a different key, on the algorithm the venue
    documents as deprecated.

    So :meth:`sign` raises, :mod:`globin.application.auth` converts that to
    :attr:`~globin.domain.auth.AuthStatus.SIGNER_UNAVAILABLE`, and the operator is
    told which library to install rather than being quietly served.
    """

    __slots__ = ("_algorithm", "_detail")

    def __init__(self, algorithm: SignatureAlgorithm, detail: str) -> None:
        """Record which algorithm is unavailable and why.

        Args:
            algorithm: The algorithm.
            detail: What an operator should read.
        """
        self._algorithm = algorithm
        self._detail = detail

    @property
    def algorithm(self) -> SignatureAlgorithm:
        """The algorithm this signer would implement if it could."""
        return self._algorithm

    @property
    def available(self) -> bool:
        """Never. This is the stand-in a missing library produces."""
        return False

    @property
    def detail(self) -> str:
        """Why it cannot. Safe to publish: it names a library, never a key."""
        return self._detail

    def sign(self, payload: SigningPayload, material: SecretValue) -> GeneratedSignature:
        """Refuse, naming what is missing.

        Args:
            payload: Ignored. Named so the signature matches the protocol.
            material: Ignored, and **never read** — the refusal happens before any
                key material is touched, so an unavailable signer cannot be a route
                by which a secret is handled.

        Raises:
            ValidationError: Always.
        """
        del payload, material
        msg = (
            f"no {self._algorithm.value} signer is available on this host: {self._detail}. "
            "GLOBIN refuses rather than signing with a different algorithm"
        )
        raise ValidationError(msg)


def known_armour() -> tuple[tuple[str, str], ...]:
    r"""Armour lines this loader can name in a refusal, and what each one is.

    Returns:
        Each armour line paired with a description of what it holds.

    **A fixed table rather than the material's own first line**, and the difference
    is a real leak this repository's own smoke test found before any test did.
    Echoing ``text.partition("\n")[0]`` is safe for a well-formed PEM, whose first
    line is always armour — and an operator who pastes the base64 *body* by mistake
    has just had forty-eight characters of private key written into an error
    message, a traceback and a log.

    So nothing is echoed. A recognised armour line is named from this table, and
    anything else is described by shape alone. The cost is that an exotic format is
    reported as "not a PEM block this loader recognises" instead of by name, which
    is the right trade: the operator can see their own file, and GLOBIN's
    diagnostics cannot.
    """
    return (
        (ARMOUR_FORMAT.format(label=f"RSA {PRIVATE_KEY_LABEL}"), "a PKCS#1 RSA block"),
        (
            ARMOUR_FORMAT.format(label=f"EC {PRIVATE_KEY_LABEL}"),
            "a SEC 1 elliptic-curve block",
        ),
        (ARMOUR_FORMAT.format(label=f"DSA {PRIVATE_KEY_LABEL}"), "a PKCS#1 DSA block"),
        (ARMOUR_FORMAT.format(label=f"OPENSSH {PRIVATE_KEY_LABEL}"), "an OpenSSH block"),
        (ARMOUR_FORMAT.format(label="PUBLIC KEY"), "a PUBLIC key, not a private one"),
        (ARMOUR_FORMAT.format(label="CERTIFICATE"), "a certificate, not a key"),
    )


def _describe_shape(stripped: str, key_type: ApiKeyType) -> str:
    """Say what material looks like, without reproducing any of it.

    Args:
        stripped: The material, whitespace-trimmed.
        key_type: What the credential declares this key to be.

    Returns:
        A phrase naming a recognised armour line, or describing the shape.

    Every branch returns a **constant** joined to values GLOBIN already knows.
    No slice of ``stripped`` reaches the result, which is what makes the leak
    impossible rather than unlikely.
    """
    for armour, description in known_armour():
        if stripped.startswith(armour):
            return f"it is {description}"
    if stripped.startswith("-----BEGIN"):
        return "it is a PEM block of some other type"
    del key_type
    return "it is not a PEM block at all"


def _refuse_key_format(text: str, key_type: ApiKeyType) -> None:
    """Refuse private key material the venue would not accept, before parsing it.

    Args:
        text: The PEM material.
        key_type: What the credential declares this key to be.

    Raises:
        ValidationError: If the material is encrypted, or is not a PKCS#8 block.

    Checked as text rather than by catching the parser's exception, so the message
    names the format rather than repeating a library's account of why it could not
    read one. A PKCS#1 RSA block parses perfectly well and is
    refused here, because the venue states *"Only ``PKCS#8`` keys are supported"*
    and a key it will not accept should fail at enrolment rather than at the first
    signed request.

    **No part of the material appears in any message this raises.** See
    :func:`known_armour` for what that cost and why it is worth paying.
    """
    stripped = text.strip()
    if stripped.startswith(pkcs8_encrypted_header()):
        msg = (
            f"a {key_type.value} private key is an encrypted PKCS#8 block; GLOBIN has no way "
            "to collect its passphrase, so store the decrypted key instead"
        )
        raise ValidationError(msg)
    header = pkcs8_header()
    if not stripped.startswith(header):
        msg = (
            f"a {key_type.value} private key does not begin with {header!r} and so is "
            f"not PKCS#8, which is the only serialisation the venue supports; "
            f"{_describe_shape(stripped, key_type)}"
        )
        raise ValidationError(msg)


class RsaSigner:
    """RSASSA-PKCS1-v1_5 with SHA-256, rendered as base64.

    Args:
        module: The ``cryptography`` primitives this signer needs, injected by
            :func:`asymmetric_signers` so that this class names no import of its
            own and the module-level rule has one site to hold.

    Quoted: *"Sign the signature payload constructed in Step 1 using the
    RSASSA-PKCS1-v1_5 algorithm with SHA-256 hash function. Encode the output in
    base64."*

    **PSS is not merely unused; it is refused by the venue.** *"We currently do not
    support the PSS signature scheme."* The two padding schemes differ by one
    argument in this library's API and produce signatures of identical length, so
    nothing about a wrong choice is visible from the outside — which is why
    ``tests/unit/test_signing.py`` verifies a produced signature under PKCS#1 v1.5
    **and** asserts it does not verify under PSS.
    """

    __slots__ = ("_module",)

    def __init__(self, module: "_CryptographyPrimitives") -> None:
        """Hold the primitives this signer was built with.

        Args:
            module: The injected primitives.
        """
        self._module = module

    @property
    def algorithm(self) -> SignatureAlgorithm:
        """The algorithm this signer implements."""
        return SignatureAlgorithm.RSA_PKCS1V15_SHA256

    @property
    def available(self) -> bool:
        """Always. This class only exists when ``cryptography`` imported."""
        return True

    def sign(self, payload: SigningPayload, material: SecretValue) -> GeneratedSignature:
        """Compute an RSASSA-PKCS1-v1_5 signature over SHA-256.

        Args:
            payload: The exact characters to sign.
            material: The private key, in PKCS#8 PEM.

        Returns:
            The signature, base64 with padding and no case transform.

        Raises:
            ValidationError: If the material is not a PKCS#8 RSA private key of an
                accepted size.
            InternalError: If a loaded key produced no signature.
        """
        signature = self._module.sign_rsa(material.material(), payload.as_bytes())
        if not signature:
            msg = "an RSA key produced an empty signature, which cannot happen for a valid key"
            raise InternalError(msg)
        return GeneratedSignature(base64.b64encode(signature).decode("ascii"), self.algorithm)


class Ed25519Signer:
    """Ed25519 over the payload directly, rendered as base64.

    Args:
        module: The ``cryptography`` primitives this signer needs.

    Quoted, from the venue's normative text: *"1. Sign the payload. 2. Encode the
    output as a base64 string."*

    **No digest step**, and that is a correction to the venue's own worked example
    rather than a detail. Ed25519 is PureEdDSA — RFC 8032 hashes the message inside
    the algorithm — and the documentation's example shows ``openssl dgst -sha256
    -sign``, which is an RSA invocation. The signatures it publishes beside that
    command decode to 256 bytes, or in one case do not decode at all;
    ``docs/research/phase_035_sources.md`` S-05 has the arithmetic. This signer
    follows the normative sentence and RFC 8032, and asserts the resulting length.

    **Deterministic**, per RFC 8032 §5.1.6 step 2: the per-message nonce is derived
    from the key and the message with no randomness, so one key signing one payload
    twice yields identical bytes. Asserted in the tests rather than assumed, because
    it is the property that distinguishes this from ECDSA.
    """

    __slots__ = ("_module",)

    def __init__(self, module: "_CryptographyPrimitives") -> None:
        """Hold the primitives this signer was built with.

        Args:
            module: The injected primitives.
        """
        self._module = module

    @property
    def algorithm(self) -> SignatureAlgorithm:
        """The algorithm this signer implements."""
        return SignatureAlgorithm.ED25519

    @property
    def available(self) -> bool:
        """Always. This class only exists when ``cryptography`` imported."""
        return True

    def sign(self, payload: SigningPayload, material: SecretValue) -> GeneratedSignature:
        """Compute an Ed25519 signature.

        Args:
            payload: The exact characters to sign.
            material: The private key, in PKCS#8 PEM.

        Returns:
            The signature, base64 with padding and no case transform.

        Raises:
            ValidationError: If the material is not a PKCS#8 Ed25519 private key.
            InternalError: If the signature is not
                :data:`ED25519_SIGNATURE_BYTES` long, which would mean the
                primitive is not the one this claims to use.
        """
        signature = self._module.sign_ed25519(material.material(), payload.as_bytes())
        if len(signature) != ED25519_SIGNATURE_BYTES:
            msg = (
                f"an Ed25519 signature is {len(signature)} bytes and RFC 8032 fixes it at "
                f"{ED25519_SIGNATURE_BYTES}; this is not an Ed25519 signature"
            )
            raise InternalError(msg)
        return GeneratedSignature(base64.b64encode(signature).decode("ascii"), self.algorithm)


class _CryptographyPrimitives:
    """The narrow slice of ``cryptography`` the two asymmetric signers use.

    Args:
        serialization: The library's key serialisation module.
        padding: Its asymmetric padding module.
        hashes: Its hash module.
        rsa_key: Its RSA private key class, for the type check.
        ed25519_key: Its Ed25519 private key class, for the type check.

    **A seam rather than a convenience.** Confining every attribute the signers
    touch to this one object is what lets
    ``tests/architecture/test_signing_discipline.py`` assert that ``cryptography``
    is named in exactly one module: the signers themselves import nothing, so a
    future signer cannot quietly add a second import site.

    It also makes the **key type check** a single place. Loading a key and then
    checking what it turned out to be is the step that catches an Ed25519 key
    enrolled as RSA — a mistake that is easy to make, since both arrive as
    PKCS#8 blocks with the same armour line, and are indistinguishable by eye.
    """

    __slots__ = ("_ed25519_key", "_hashes", "_padding", "_rsa_key", "_serialization")

    def __init__(
        self,
        serialization: Any,
        padding: Any,
        hashes: Any,
        rsa_key: type,
        ed25519_key: type,
    ) -> None:
        """Hold the primitives.

        Args:
            serialization: The key serialisation module.
            padding: The asymmetric padding module.
            hashes: The hash module.
            rsa_key: The RSA private key class.
            ed25519_key: The Ed25519 private key class.
        """
        self._serialization = serialization
        self._padding = padding
        self._hashes = hashes
        self._rsa_key = rsa_key
        self._ed25519_key = ed25519_key

    def _load(self, text: str, key_type: ApiKeyType, expected: type) -> Any:
        """Parse a PKCS#8 PEM key and confirm it is the declared algorithm.

        Args:
            text: The PEM material.
            key_type: What the credential declares this key to be.
            expected: The class a key of that type must be an instance of.

        Returns:
            The loaded key. Typed :class:`~typing.Any` rather than named, because
            the concrete class belongs to a library the layer contract confines to
            this module — the same reason
            :class:`~globin.ports.auth.PrivateKeyLoader` returns :class:`object`.
            The value never leaves this class, so the looseness is bounded to the
            two methods directly below.

        Raises:
            ValidationError: If the material is not PKCS#8, will not parse, or
                parses into a key of a different algorithm.

        **The exception is not propagated**, and the message is not repeated. A
        parse failure's text can quote the material it was given, which for a
        private key is the one thing that must never reach a log or a traceback —
        so the cause is dropped rather than chained, and what an operator gets is
        the fact that the key did not parse and which key it was.
        """
        _refuse_key_format(text, key_type)
        try:
            key = self._serialization.load_pem_private_key(text.encode("utf-8"), password=None)
        except Exception:
            msg = (
                f"a {key_type.value} private key is a PKCS#8 block that did not parse; it is "
                "corrupt, truncated, or not the key type it is filed under"
            )
            raise ValidationError(msg) from None
        if not isinstance(key, expected):
            msg = (
                f"a private key filed as {key_type.value} parsed as "
                f"{type(key).__name__}; both key types are PEM blocks that look alike, so "
                "the declared type is checked against what actually loaded"
            )
            raise ValidationError(msg)
        return key

    def sign_rsa(self, text: str, payload: bytes) -> bytes:
        """Load an RSA private key, check its size, and sign with it.

        Args:
            text: The PKCS#8 PEM material.
            payload: The exact bytes to sign.

        Returns:
            The raw signature bytes.

        Raises:
            ValidationError: If the key is not RSA, or its modulus is outside the
                documented 2048-to-4096-bit range.

        **Loading and signing are one method rather than two**, so the library's
        key object never leaves this class. That is what keeps ``cryptography``
        types out of :class:`RsaSigner` entirely: the signer passes text and bytes
        in and receives bytes back, so the architecture rule confining the library
        to one module holds by construction rather than by everyone remembering it.

        The PKCS#1 v1.5 padding is constructed here and **PSS is never referenced
        anywhere in this package**, which is the strongest available form of "we do
        not use PSS": there is no argument, no setting and no branch that could
        select it, and ``tests/architecture/test_signing_discipline.py`` asserts the
        token is absent from the source.
        """
        key = self._load(text, ApiKeyType.RSA, self._rsa_key)
        bits = int(key.key_size)
        if not RSA_MIN_KEY_BITS <= bits <= RSA_MAX_KEY_BITS:
            msg = (
                f"an RSA private key is {bits} bits and the venue documents support for "
                f"{RSA_MIN_KEY_BITS} to {RSA_MAX_KEY_BITS}"
            )
            raise ValidationError(msg)
        return bytes(key.sign(payload, self._padding.PKCS1v15(), self._hashes.SHA256()))

    def sign_ed25519(self, text: str, payload: bytes) -> bytes:
        """Load an Ed25519 private key and sign with it.

        Args:
            text: The PKCS#8 PEM material.
            payload: The exact bytes to sign.

        Returns:
            The raw signature bytes.

        Raises:
            ValidationError: If the key is not Ed25519.

        **The payload goes straight to the primitive**, with no digest computed
        first. Ed25519 is PureEdDSA and hashes the message internally; the venue's
        own worked example shows an ``openssl dgst -sha256 -sign`` invocation, which
        is an RSA command, and publishes RSA output beside it. The normative
        sentence is *"Sign the payload"*, and that is what this does.

        No size check, because Ed25519 has exactly one size. RFC 8032 fixes the
        private key at 32 octets, so a key of another length is not an Ed25519 key
        and the type check in :meth:`_load` has already refused it.
        """
        key = self._load(text, ApiKeyType.ED25519, self._ed25519_key)
        return bytes(key.sign(payload))


def hmac_signer() -> HmacSigner:
    """The HMAC-SHA256 signer.

    Returns:
        The signer. **Always available**, with no unavailable arm, because
        :mod:`hmac` and :mod:`hashlib` are the standard library.

    A factory rather than a constructor call at the point of use, so that every
    signer is obtained the same way and a reader is not left wondering whether this
    one can fail. It is deliberately **not** part of the degradation survey: a
    component that can never be absent has nothing to report.
    """
    return HmacSigner()


def asymmetric_signers() -> tuple[RequestSigner, RequestSigner]:
    """The RSA and Ed25519 signers, or two stand-ins that refuse.

    Returns:
        The RSA signer and the Ed25519 signer, in that order. Both are real when
        ``cryptography`` imports, and both are
        :class:`UnavailableAsymmetricSigner` when it does not.

    **The one place in the package that names ``cryptography``**, and the import is
    inside the function so that a host without it pays nothing at import time —
    which is the arrangement every other absent-safe factory here uses and which
    ``tests/architecture/test_signing_discipline.py`` enforces.

    **Both arms move together**, deliberately. The two algorithms come from one
    library, so a host has both or neither, and returning one real signer beside
    one stand-in would describe a state that cannot occur. The pair is returned
    together rather than through two factories for the same reason: two factories
    could disagree.

    ``ImportError`` is the only failure caught. A library that imports and then
    misbehaves is a defect worth a traceback, not a degradation worth a stand-in.
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
    except ImportError as fault:
        detail = f"cryptography is not importable in this environment ({fault.name})"
        return (
            UnavailableAsymmetricSigner(SignatureAlgorithm.RSA_PKCS1V15_SHA256, detail),
            UnavailableAsymmetricSigner(SignatureAlgorithm.ED25519, detail),
        )
    primitives = _CryptographyPrimitives(
        serialization=serialization,
        padding=padding,
        hashes=hashes,
        rsa_key=RSAPrivateKey,
        ed25519_key=Ed25519PrivateKey,
    )
    return RsaSigner(primitives), Ed25519Signer(primitives)


def available_algorithms() -> tuple[SignatureAlgorithm, ...]:
    """Which algorithms this host can actually compute.

    Returns:
        The algorithms whose signer reports itself available, in enumeration order.

    What the composition root feeds into
    :func:`globin.application.auth.resolve_auth` as its ``available`` argument, so
    that gate 7 refuses with
    :attr:`~globin.domain.auth.AuthStatus.SIGNER_UNAVAILABLE` **before** any
    credential is read rather than after a signer has been handed one.
    """
    return tuple(
        algorithm for algorithm, signer in signers().items() if getattr(signer, "available", False)
    )


def signers() -> dict[SignatureAlgorithm, RequestSigner]:
    """Every signer this host can offer, keyed by the algorithm it implements.

    Returns:
        One entry per member of :class:`~globin.domain.auth.SignatureAlgorithm`,
        with the two asymmetric entries being stand-ins where the library is
        absent.

    **Total over the enumeration**, so selection is a lookup that always finds
    something and the *unavailable* case is a property of what was found rather
    than a missing key. A mapping with holes in it would make every caller write
    the same ``if algorithm not in signers`` branch, which is where the fallback to
    HMAC would eventually get written.

    Typed as :class:`~globin.ports.auth.RequestSigner` rather than
    :class:`object`, which is what makes mypy check every implementation here —
    including the stand-in — against the protocol at the point it is returned.
    """
    rsa, ed25519 = asymmetric_signers()
    return {
        SignatureAlgorithm.HMAC_SHA256: hmac_signer(),
        SignatureAlgorithm.RSA_PKCS1V15_SHA256: rsa,
        SignatureAlgorithm.ED25519: ed25519,
    }


__all__ = [
    "ARMOUR_FORMAT",
    "ED25519_SIGNATURE_BYTES",
    "PRIVATE_KEY_LABEL",
    "RSA_MAX_KEY_BITS",
    "RSA_MIN_KEY_BITS",
    "Ed25519Signer",
    "HmacSigner",
    "RsaSigner",
    "UnavailableAsymmetricSigner",
    "asymmetric_signers",
    "available_algorithms",
    "hmac_signer",
    "known_armour",
    "pkcs8_encrypted_header",
    "pkcs8_header",
    "signers",
]
