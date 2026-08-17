"""What a stored secret is, how it is named, and what may be said about it.

This module holds the distinction ``docs/security/SECRET_STORE_CONTRACT.md`` §1
draws and nothing else: a **reference** names a secret and is ordinary data, a
**value** is what resolving one returns and is not. The distinction is enforced
by the type system rather than by care, which is the whole reason both types
exist instead of one string.

**:class:`SecretValue` is deliberately not a dataclass.** Every other value type
in this layer is one, and this is the exception with a reason. §1 requires that
the value "is not a plain field a generic dump helper walks", and a dataclass —
even with ``slots=True`` — is exactly what :func:`dataclasses.asdict` walks, what
:func:`dataclasses.fields` enumerates and what a serialiser written against
either will find. A plain class with ``__slots__`` and a private attribute has no
``__dict__`` for :func:`vars` to return and no field register to walk, so the
failure mode §1 names — "a serialiser meeting the object and doing the obvious
thing" — is designed out rather than documented against.

**No encoder, in the way** :class:`~globin.domain.clock.MonotonicReading` **has
none.** ``docs/SERIALIZATION_POLICY.md`` is exact or refused; for a secret the
answer is refused, so :mod:`globin.domain.serialization` gains nothing here and
``tests/contract/test_secrets_contract.py`` asserts the absence. An absence does
not appear in a diff, which is why it is tested rather than trusted.

**Comparison is constant-time and reveals nothing.** :func:`hmac.compare_digest`
is used rather than ``==``, because a comparison that returns early on the first
differing byte leaks a prefix to anything that can time it. :mod:`hmac` is
reachable here — it is not in the I/O-capable list, and unlike the standard
library's ``secrets`` module it reads no source of randomness, which
``tests/architecture/test_identifier_discipline.py`` forbids this layer from
doing.

**The ceiling is enforced here, not discovered at the adapter.** Windows caps a
credential blob at 2560 bytes, and ``phase_028_sources.md`` S-04 records that
``CredWriteW`` documents *no* error for exceeding it — the observed status on
this host is ``RPC_X_BAD_STUB_DATA``, which describes an RPC marshalling fault
and would be filed under "unknown" by anything classifying against the
documented list. Refusing an oversized value before the call is what turns that
into a named reason. S-11 records why the limit is not academic: an RSA-4096
private key in PEM form is 3324 bytes and does not fit.

What this module does not decide: which secrets GLOBIN requires (Phase 029),
which key type is used (Phases 029 and 038), and what an environment *is*
(Phase 035). It bounds shapes; it registers no instances.
"""

import hmac
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.domain.identifiers import EnvironmentId
from globin.domain.observability import REDACTED
from globin.errors import InternalError, ValidationError

MAX_SECRET_BYTES: Final[int] = 5 * 512
"""The largest value a stored secret may carry, in UTF-8 bytes.

Spelled ``5 * 512`` because that is how Microsoft writes
``CRED_MAX_CREDENTIAL_BLOB_SIZE`` in the ``CREDENTIALW`` reference, and a reader
checking this against the platform should find the same expression rather than a
number they have to recognise. Measured on this host: 2560 succeeds and 2561
fails (``phase_028_sources.md`` S-05).

This is a **domain** bound rather than an adapter detail, because a value that
cannot be stored is a value the caller must be refused — and refusing it here
names the reference, while refusing it at the platform yields an undocumented
error code.
"""

KEY_PREFIX: Final[str] = "GLOBIN"
"""What every store key begins with.

Microsoft's guidance for a generic credential's target name is that it "should
identify the service that uses the credential in addition to the actual target"
and "be prefixed by the name of the company implementing the service"
(``phase_020_sources.md`` S-08). This is that prefix, and it is also what makes
GLOBIN's credentials identifiable in a store shared with every other application
the account uses.
"""

KEY_SEPARATOR: Final[str] = ":"
"""What joins the parts of a store key.

A colon, which is conventional for this platform's target names and which the
name alphabet below excludes — so no part can contain the separator and the key
cannot be ambiguous about where one part ends.
"""

NAME_ALPHABET: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789_-"
"""The characters a secret's logical name may contain.

Written out rather than compiled as a regular expression because a module-level
:func:`re.compile` is a call, and every layer package is held to performing no
work at import.

Deliberately excludes :data:`KEY_SEPARATOR` and every uppercase letter. The
second is not redundant with the case folding in :func:`store_key`: refusing an
uppercase name outright means a caller never forms two names they believe are
distinct, rather than being silently folded together later.
"""

MAX_NAME_LENGTH: Final[int] = 64
"""The longest a secret's logical name may be.

Not a platform limit — the target name may run to 32767 characters
(``phase_020_sources.md`` S-08), so length genuinely does not constrain the
namespace. This is a legibility bound: a name longer than this is describing
something rather than naming it.
"""


class SecretKind(StrEnum):
    """What kind of material a reference points at.

    Bounded, because the kind participates in the store key and in the
    mismatch refusal ``SECRET_STORE_CONTRACT.md`` §3 requires — and a free
    string would make both unfalsifiable.

    These are *shapes of material*, not venue vocabulary and not a register of
    the secrets GLOBIN holds, which is empty. Which key type is used against
    which surface is Phases 029 and 038; ``phase_020_sources.md`` S-15 and S-16
    record what the venue documents and this phase does not choose from it.
    """

    API_KEY = "api_key"
    API_SECRET = "api_secret"  # noqa: S105 -- a kind of material, not one
    PRIVATE_KEY = "private_key"


class SecretSlot(StrEnum):
    """Which copy of a reference's material a key addresses.

    Two members, and the second exists because of a platform limitation rather
    than a preference. ``SECRET_STORE_CONTRACT.md`` §4 requires that rotation
    "writes the new value, reads it back, and only then retires the previous
    one", so that a failure at any step leaves the previous secret resolvable.
    A Windows credential write **replaces** (``phase_020_sources.md`` S-10), so
    by the time the new value is written the old one is already gone — the
    ordering §4 describes is unimplementable if both live under one key.

    So the previous value is moved to :attr:`PREVIOUS` *before* the new one is
    written, and removed only after the new one has been read back and
    verified. The slot is a bounded component of the key rather than a suffix on
    the name, so a reference legitimately named ``venue_key_previous`` cannot
    collide with the previous slot of ``venue_key``.
    """

    CURRENT = "current"
    PREVIOUS = "previous"


class StoreFault(StrEnum):
    """Why a store operation did not produce what was asked for.

    Bounded rather than a message, for the reason
    :class:`~globin.domain.diagnostics_http.ReadinessReason` is: these values
    reach a check summary and an exit-code decision, and a free-text fault is
    how an exception message escapes into a contract.

    ``SECRET_STORE_CONTRACT.md`` §3 requires that absence, an unreachable store,
    an environment mismatch and a wrong kind are each an explicit error and none
    of them a silent ``None``, an empty string or a placeholder. One member per
    case is how that requirement is made checkable.
    """

    ABSENT = "absent"
    ENVIRONMENT_MISMATCH = "environment_mismatch"
    KIND_MISMATCH = "kind_mismatch"
    NO_CREDENTIAL_SET = "no_credential_set"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    BACKEND_REFUSED = "backend_refused"
    VALUE_TOO_LARGE = "value_too_large"
    VERIFICATION_FAILED = "verification_failed"


@dataclass(frozen=True, slots=True, order=True)
class SecretReference:
    """The name of a secret. Never the secret.

    Args:
        environment: Which deployment target this secret belongs to.
        kind: What sort of material it is.
        name: The logical name, lowercase, from :data:`NAME_ALPHABET`.

    Raises:
        ValidationError: If ``name`` is empty, longer than
            :data:`MAX_NAME_LENGTH`, or contains a character outside
            :data:`NAME_ALPHABET`.

    This is ordinary data and is meant to be: printable, loggable, serialisable,
    comparable, and safe in a configuration file, an error message or a
    manifest. ``SECRET_STORE_CONTRACT.md`` §1 says so, and the reason it is worth
    a type rather than a convention is that the *other* type then has somewhere
    to be different.

    Ordering is derived so that a set of references has a deterministic
    rendering — every manifest in this repository sorts what it lists.
    """

    environment: EnvironmentId
    kind: SecretKind
    name: str

    def __post_init__(self) -> None:
        """Validate the logical name.

        Raises:
            ValidationError: As documented on the class.
        """
        if not self.name:
            msg = "a secret reference needs a name"
            raise ValidationError(msg)
        if len(self.name) > MAX_NAME_LENGTH:
            msg = (
                f"secret name is {len(self.name)} characters, "
                f"longer than the {MAX_NAME_LENGTH} permitted"
            )
            raise ValidationError(msg)
        outside = sorted({character for character in self.name if character not in NAME_ALPHABET})
        if outside:
            msg = f"secret name contains characters outside the permitted alphabet: {outside}"
            raise ValidationError(msg)


class SecretValue:
    """Material resolved from a reference, which refuses to render itself.

    Args:
        material: The secret text.

    Raises:
        ValidationError: If ``material`` is empty, or its UTF-8 encoding exceeds
            :data:`MAX_SECRET_BYTES`.

    Four obligations from ``SECRET_STORE_CONTRACT.md`` §1, and each is structural
    rather than advisory:

    - :meth:`__str__`, :meth:`__repr__` and :meth:`__format__` all yield
      :data:`~globin.domain.observability.REDACTED`, reached by reference so
      there is no second literal to drift from the first.
    - There is no ``__dict__`` and no dataclass field register, so
      :func:`vars`, :func:`dataclasses.asdict` and anything written against
      either find nothing to walk.
    - It has no encoder, and a contract test asserts that absence.
    - :meth:`__eq__` is constant-time and returns a plain :class:`bool`, so
      neither the material nor a prefix of it can be inferred from timing or
      from a message.

    It is deliberately **unhashable**: defining :meth:`__eq__` without
    ``__hash__`` makes it so, and that is kept rather than repaired. An
    unhashable object cannot become a dictionary key or a set member, which
    removes two ways material could reach a structure that is later rendered.

    This type makes no claim about erasure. §7 is explicit that CPython offers
    no equivalent of ``SecureZeroMemory`` for a string, so what is claimed is
    bounded lifetime and no persistence — discharged by resolving in the
    narrowest scope that needs the value and holding no cache, not by a call
    that would look like erasure without being it.
    """

    __slots__ = ("_material",)

    def __init__(self, material: str) -> None:
        """Store the material after checking it can be stored at all.

        Args:
            material: The secret text.

        Raises:
            ValidationError: As documented on the class.
        """
        if not material:
            msg = "a secret value cannot be empty"
            raise ValidationError(msg)
        size = len(material.encode("utf-8"))
        if size > MAX_SECRET_BYTES:
            msg = (
                f"a secret value of {size} bytes exceeds the {MAX_SECRET_BYTES}-byte "
                "limit the credential store imposes"
            )
            raise ValidationError(msg)
        self._material = material

    def __str__(self) -> str:
        """Render as the redaction marker.

        Returns:
            :data:`~globin.domain.observability.REDACTED`.
        """
        return REDACTED

    def __repr__(self) -> str:
        """Render as the redaction marker.

        Returns:
            :data:`~globin.domain.observability.REDACTED`.

        ``__repr__`` matters more than ``__str__`` here: it is what a traceback,
        a debugger, a ``%r`` format and a container's rendering all reach for, so
        a type that redacted only ``__str__`` would leak through every one of
        them.
        """
        return REDACTED

    def __format__(self, format_spec: str) -> str:
        """Render as the redaction marker, whatever was asked for.

        Args:
            format_spec: Ignored.

        Returns:
            :data:`~globin.domain.observability.REDACTED`.

        Overridden because :meth:`object.__format__` with a non-empty spec does
        not route through :meth:`__str__` — ``f"{value:>40}"`` would otherwise
        raise, and a raising redaction is one somebody removes.
        """
        return REDACTED

    def __eq__(self, other: object) -> bool:
        """Compare in constant time, without branching on content.

        Args:
            other: The object to compare against.

        Returns:
            ``True`` when ``other`` is a :class:`SecretValue` carrying identical
            material, ``NotImplemented`` handling aside.

        Returns ``NotImplemented`` for a foreign type, matching the convention
        :mod:`globin.domain.values` established: a wrong *type* is not an error,
        a wrong *unit* is.
        """
        if not isinstance(other, SecretValue):
            return NotImplemented
        return hmac.compare_digest(self._material, other._material)

    __hash__ = None  # type: ignore[assignment]

    def size_bytes(self) -> int:
        """How large the material is when encoded.

        Returns:
            The length of the UTF-8 encoding, in bytes.

        Safe to publish: a length is not material, and it is what a store needs
        to report why a write was refused.
        """
        return len(self._material.encode("utf-8"))

    def material(self) -> str:
        """The secret itself, for the one caller that must have it.

        Returns:
            The material.

        Named for what it is rather than for what it does, because
        ``SECRET_STORE_CONTRACT.md`` §5 forbids the vocabulary of display —
        ``reveal``, ``dump``, ``export`` — and a contract test enforces that
        list against module and command names.

        Every call site is a place the material exists as an ordinary string
        with none of this type's protections, so the rule §7 states applies:
        resolve in the narrowest scope that needs it, and keep no cache.
        """
        return self._material


@dataclass(frozen=True, slots=True)
class SecretResolution:
    """What asking the store for one reference produced.

    Args:
        reference: What was asked for.
        value: The material, when it was found and accepted.
        fault: Why not, when it was not.

    Raises:
        InternalError: If both or neither of ``value`` and ``fault`` are set.

    A result type rather than an exception, for the reason
    :class:`~globin.domain.bootstrap.SecretReadiness` is one: absence is an
    ordinary answer to the readiness question and a start-up check must be able
    to receive it without unwinding. ``SECRET_STORE_CONTRACT.md`` §3 requires
    that absence, an unreachable store, an environment mismatch and a wrong kind
    are each *explicit* and never "a silent ``None``, an empty string or a
    placeholder" — a member of :class:`StoreFault` naming which of them happened
    is more explicit than an exception type that erases the distinction, and it
    is what lets :mod:`globin.application.secrets` raise with the cause named.

    The exclusivity is enforced rather than documented: a resolution carrying
    both would let a caller read the value and ignore the fault, and one
    carrying neither is a third state nobody wrote a branch for.
    """

    reference: SecretReference
    value: SecretValue | None = None
    fault: StoreFault | None = None

    def __post_init__(self) -> None:
        """Enforce that exactly one outcome is present.

        Raises:
            InternalError: As documented on the class.
        """
        if (self.value is None) == (self.fault is None):
            msg = (
                "a secret resolution carries exactly one of a value and a fault; "
                f"got value={'set' if self.value is not None else 'unset'} and "
                f"fault={self.fault!r}"
            )
            raise InternalError(msg)

    @property
    def resolved(self) -> bool:
        """Whether the reference produced material.

        Returns:
            ``True`` when a value is present.
        """
        return self.value is not None

    def as_record(self) -> dict[str, object]:
        """This resolution as the mapping a record carries.

        Returns:
            The reference's parts and the fault, and never the value.

        The value has no representation here and cannot acquire one by
        accident: it is not read, so there is no branch in which it is rendered.
        """
        return {
            "environment": self.reference.environment.text,
            "kind": self.reference.kind.value,
            "name": self.reference.name,
            "resolved": self.resolved,
            "fault": self.fault.value if self.fault is not None else None,
        }


def store_key(reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT) -> str:
    """Build the one key a reference is stored under.

    Args:
        reference: The secret's identity.
        slot: Which copy of the material. Defaults to
            :attr:`SecretSlot.CURRENT`, so every ordinary caller spells nothing
            and only rotation names the other.

    Returns:
        The platform target name, lowercase.

    Raises:
        ValidationError: If the reference cannot be classified — which
            :class:`SecretReference` already prevents, so this is the guard on
            a type being constructed some way that bypassed it.

    Exactly one total, pure function maps identity to key, and nothing else
    composes one anywhere; ``SECRET_STORE_CONTRACT.md`` §2 requires that, and a
    second builder is the drift ``SOURCE_OF_TRUTH.md`` exists to prevent.

    **Case is folded last, and that is a correctness requirement rather than
    tidiness.** The platform's target names are case-insensitive
    (``phase_020_sources.md`` S-08), and ``phase_028_sources.md`` S-06 measured
    what that means in practice: a credential written under one spelling is
    returned for another, with no error and no warning. A builder that did not
    fold would produce keys that look distinct, pass a test that writes and
    reads through the same spelling, and collapse the environment isolation §3
    requires — silently, and only once two environments differed by case.

    Length is not a constraint. The platform permits 32767 characters, so the
    key is verbose and unambiguous on purpose; compression would buy nothing and
    cost legibility.
    """
    parts = (
        KEY_PREFIX,
        reference.environment.text,
        reference.kind.value,
        reference.name,
        slot.value,
    )
    if not all(parts):
        msg = f"a store key cannot be built from an incomplete reference: {parts}"
        raise ValidationError(msg)
    return KEY_SEPARATOR.join(parts).lower()
