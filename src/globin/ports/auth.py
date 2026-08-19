"""The contract through which GLOBIN computes a signature, and the one for a key.

Two protocols, and the split is between *what is done with material* and *how
material becomes a usable key*. Keeping them apart is what lets the HMAC path
exist with no key loading at all — a shared secret is used as bytes and nothing
parses it — while the two asymmetric paths need a loader that can refuse a PEM
before anything tries to sign with it.

**A signer is handed material and cannot fetch it.** :meth:`RequestSigner.sign`
takes a :class:`~globin.domain.secrets.SecretValue`, so the component that
performs cryptography has no access to the store, no reference resolution and no
way to reach for a different credential than the one it was given. That is the
same shape :class:`~globin.ports.rest.RestTransport` has with an endpoint
resolution, and it buys the same property: a signer could not sign with the wrong
key if it wanted to, because it has never seen the alternatives.

**Nothing here returns a partial answer.** A signer either produces a
:class:`~globin.domain.auth.GeneratedSignature` or raises, and the raise is
converted to an :class:`~globin.domain.auth.AuthStatus` by
:mod:`globin.application.auth` at the one place that knows the caller's intent.
That is the arrangement :mod:`globin.ports.secrets` describes for the store, and
the reason is the same: classifying at the port would push the classification out
to every call site, which is where it would be got wrong.

**Absence IS modelled here, and it is the one protocol in this repository where
that is right.** The instinct — and the first draft — was to leave it out: a
factory returns a stand-in, the stand-in raises, and a protocol carrying an
``available`` flag every real implementation answers ``True`` to looks like
ceremony.

What that costs is the *classification*. A stand-in's refusal and a corrupt key's
refusal are both a raise, so a caller that could not tell them apart would report
:attr:`~globin.domain.auth.AuthStatus.INVALID_PRIVATE_KEY_MATERIAL` for a perfectly
good key on a host that is merely missing a library — sending an operator to
re-enrol a credential that was never the problem. :attr:`RequestSigner.available`
makes the two distinguishable without :mod:`globin.application.auth` importing an
adapter to run an ``isinstance`` check, which the layer contract forbids anyway.

See :func:`globin.adapters.signing.asymmetric_signers` and the
``component.library.cryptography`` row in
``docs/engineering/degradation-contract.toml``.
"""

from typing import Protocol

from globin.domain.api_reality import ApiKeyType
from globin.domain.auth import GeneratedSignature, SignatureAlgorithm, SigningPayload
from globin.domain.secrets import SecretValue


class RequestSigner(Protocol):
    """Something that can turn a signing payload and key material into a signature."""

    @property
    def algorithm(self) -> SignatureAlgorithm:
        """Which algorithm this signer implements.

        Returns:
            The algorithm. Read by the selection in
            :mod:`globin.application.auth`, which never asks a signer to compute an
            algorithm it does not claim.
        """
        ...

    @property
    def available(self) -> bool:
        """Whether this signer can actually compute a signature.

        Returns:
            ``True`` for every real implementation, and ``False`` for the stand-in
            a missing library produces.

        Read **before** :meth:`sign` rather than inferred from a raise, so that
        *this host cannot compute this algorithm* and *this key is not usable* stay
        two different answers to an operator. See this module's docstring for why
        that is worth a protocol member.
        """
        ...

    def sign(self, payload: SigningPayload, material: SecretValue) -> GeneratedSignature:
        """Compute one signature.

        Args:
            payload: The exact characters to sign. Already percent-encoded, because
                the venue requires signing the encoded form and
                :func:`globin.domain.auth.signing_payload` is the only thing that
                builds one.
            material: The shared secret or the private key, resolved in the
                narrowest scope that needs it and not held by this object.

        Returns:
            The signature, rendered in this algorithm's documented encoding and
            with **no case transform applied** — RSA and Ed25519 signatures are
            documented case-sensitive.

        Raises:
            ValidationError: If the material is not a usable key for this
                algorithm — a corrupt PEM, a key serialised outside PKCS#8, an
                encrypted key with no passphrase, or a key whose actual algorithm
                contradicts this signer's.
            InternalError: If a well-formed key produced no signature, which is a
                defect rather than an expected outcome.
        """
        ...


class PrivateKeyLoader(Protocol):
    """Something that can turn PEM text into a key of a declared type.

    Separate from :class:`RequestSigner` because loading can fail for reasons
    signing cannot, and an operator needs to be told which happened: a key that
    will not parse is a re-enrolment, and a key that parses and is the wrong type
    is a configuration mistake.

    **Nothing implements this for HMAC**, because there is nothing to load. A
    shared secret is used as bytes, so a loader for it would be a function that
    validated nothing and returned its argument.
    """

    def load(self, material: SecretValue, key_type: ApiKeyType) -> object:
        """Parse private key material and confirm it is the declared type.

        Args:
            material: The PEM text.
            key_type: What the credential declares this key to be.

        Returns:
            An opaque key object this loader's own signer accepts. Deliberately
            :class:`object`: the concrete type belongs to a library the layer
            contract confines to one adapter, and naming it here would put a
            third-party type in a port signature — which
            ``tests/architecture/test_packaging_discipline.py`` already forbids for
            ``packaging`` and which is forbidden here for the same reason.

        Raises:
            ValidationError: If the material does not parse, is not PKCS#8, needs a
                passphrase, or is a key of a different algorithm from ``key_type``.
        """
        ...
