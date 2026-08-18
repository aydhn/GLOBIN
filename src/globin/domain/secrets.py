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
from collections.abc import Mapping, Sequence
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

    PROVIDER_READ_ONLY = "provider_read_only"
    """This mechanism never writes, so the operation had no meaning here.

    Added by Phase 031. Distinct from :attr:`BACKEND_REFUSED`, which says *the
    platform said no*: this says *this mechanism has no write at all*, and the
    two send an operator to different places. ``SECURITY_BASELINE.md`` §2 permits
    the environment "only as a hand-off, never as storage", and a provider that
    could write there would make it the resting place that sentence forbids.
    """

    PROVIDER_NOT_PERMITTED = "provider_not_permitted"
    """GLOBIN's own policy refuses this mechanism under this profile.

    Added by Phase 031. Reported as :attr:`BACKEND_REFUSED` it would send an
    operator hunting for a platform fault that does not exist; the cause is a
    line of policy, and the remediation is to use a mechanism the profile allows
    rather than to repair anything.
    """

    ENVELOPE_CORRUPT = "envelope_corrupt"
    """A stored envelope failed its own integrity check and was not decrypted.

    Added by Phase 031, and it exists because the platform's own check cannot be
    relied on. ``CryptUnprotectData``'s documentation states that on corruption
    it "may return ERROR_INVALID_DATA, ERROR_INVALID_PARAMETER, or in some cases
    **may succeed with corrupted output**", and that applications must not rely
    on a specific code to detect tampering (``phase_031_sources.md`` S-04). The
    envelope therefore carries a digest of its own, checked *before* the platform
    is reached — so this fault means the file was refused rather than decrypted
    wrongly.
    """


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


VARIABLE_ALPHABET: Final[str] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
"""What may appear in an environment variable name GLOBIN agrees to read.

Upper case and underscore, which is the platform convention and — unlike
:data:`NAME_ALPHABET` — is *not* folded, because a variable name is compared by
the operating system rather than by GLOBIN. Windows matches these
case-insensitively and :data:`os.environ` upper-cases its keys there, so a
lower-case spelling would work on one host and not another; requiring the
conventional form makes the two agree.
"""

MAX_VARIABLE_LENGTH: Final[int] = 128
"""The longest environment variable name a locator may name.

Not a platform limit. It is a bound on what GLOBIN will accept so that a locator
cannot carry an unbounded string into a record, for the reason every other length
in this module has one.
"""

CONFIGURATION_PREFIX: Final[str] = "GLOBIN_"
"""The prefix that marks a variable as configuration rather than a secret.

Restated here rather than imported. :mod:`globin.domain.configuration` owns the
value and reaches diagnostics, health, support and watchdog to do its own job;
binding the secret store to all of that for one string would be a coupling the
layer does not need. ``tests/contract/test_secrets_contract.py`` compares the two
constants, so the restatement is checked rather than trusted.
"""


class SecretProviderKind(StrEnum):
    """Which mechanism holds a secret's material.

    A mechanism, never an instance. Adding a member is adopting a store; it is
    not naming a deployment, and nothing here says which environment or which
    machine.

    ``SECRET_STORE_CONTRACT.md`` §7 permits material at rest in a file only under
    conditions the vault meets and the Credential Manager does not need; that the
    two are *disjoint by arithmetic* — one takes what fits
    :data:`MAX_SECRET_BYTES`, the other what does not — is what keeps a second
    mechanism from becoming a second answer to one question.
    """

    CREDENTIAL_MANAGER = "credential_manager"
    DPAPI_VAULT = "dpapi_vault"
    ENVIRONMENT = "environment"


def provider_writable(provider: SecretProviderKind) -> bool:
    """Whether this mechanism may be written to at all.

    Args:
        provider: The mechanism.

    Returns:
        ``False`` for :attr:`SecretProviderKind.ENVIRONMENT`, which is a hand-off
        and not a store — ``SECURITY_BASELINE.md`` §2: "Environment variables are
        permitted only as a hand-off, never as storage."

    **A property of the mechanism, so a caller can refuse a write before
    collecting material rather than after.** That ordering is the one
    :func:`~globin.application.secrets.require_permitted` already argues for:
    there is no branch in which a secret is collected and then discarded, because
    a value that never existed cannot leak.
    """
    return provider is not SecretProviderKind.ENVIRONMENT


def provider_permitted(
    provider: SecretProviderKind,
    profile: str,
    *,
    allowed: Mapping[str, Sequence[str]],
) -> bool:
    """Whether this provider may be used under this profile.

    Args:
        provider: The mechanism.
        profile: The run's resolved profile name.
        allowed: Provider value to the profiles that permit it. **Supplied rather
            than compiled in**: three of the four profile names are venue
            vocabulary, and ``tests/architecture/test_identifier_discipline.py``
            refuses them as a live constant anywhere under ``globin.domain``.

    Returns:
        Whether it is permitted. **A provider absent from the mapping is
        permitted**, so the gate applies only where a phase has declared one and
        adding a mechanism does not silently disable it.

    The same division :func:`~globin.domain.config_layout.resolve_profile` draws:
    the domain bounds the shape, the composition root owns the set. What arrives
    here is a decision about *this run*; the adapter downstream holds a boolean
    rather than a policy, so it cannot re-decide.
    """
    permitted = allowed.get(provider.value)
    if permitted is None:
        return True
    return profile in permitted


def variable_problems(name: str) -> tuple[str, ...]:
    """Judge whether a string may name an environment variable GLOBIN reads.

    Args:
        name: The candidate variable name.

    Returns:
        One sentence per reason it may not be, empty when it may.

    Four refusals: empty, longer than :data:`MAX_VARIABLE_LENGTH`, containing a
    character outside :data:`VARIABLE_ALPHABET`, or **beginning with**
    :data:`CONFIGURATION_PREFIX`.

    **The last is the one that matters, and it is not hypothetical.**
    :class:`~globin.adapters.configuration.EnvironmentConfigurationSource` raises
    on any ``GLOBIN_`` variable that
    :func:`~globin.domain.observability.is_sensitive` matches — and that
    function's fragments include ``api_key``, ``secret``, ``credential``,
    ``token`` and ``private_key``, so every plausible name for a secret variable
    matches. Left unchecked, an operator naming one ``GLOBIN_VENUE_API_KEY``
    would make **every subsequent GLOBIN start-up refuse**, with a message about
    configuration, over a variable they set for the secret store. Refusing at the
    point the name is *chosen* turns a confusing downstream failure into a local
    sentence that names the rule.
    """
    problems: list[str] = []
    if not name:
        problems.append("an environment variable name may not be empty")
        return tuple(problems)
    if len(name) > MAX_VARIABLE_LENGTH:
        problems.append(
            f"an environment variable name may be at most {MAX_VARIABLE_LENGTH} "
            f"characters, and this one is {len(name)}"
        )
    outside = sorted({character for character in name if character not in VARIABLE_ALPHABET})
    if outside:
        spelled = ", ".join(repr(character) for character in outside)
        problems.append(
            f"an environment variable name may hold only upper-case letters, digits "
            f"and underscores, and this one holds {spelled}"
        )
    if name.startswith(CONFIGURATION_PREFIX):
        problems.append(
            f"{name!r} begins with {CONFIGURATION_PREFIX!r}, which marks a variable as "
            f"GLOBIN configuration; a credential-shaped variable with that prefix is "
            f"refused before it is read and would make every later start-up fail "
            f"(see docs/security/SECURITY_BASELINE.md)"
        )
    return tuple(problems)


@dataclass(frozen=True, slots=True, order=True)
class SecretLocator:
    """Which provider holds one reference's material, and where inside it.

    Args:
        provider: The mechanism.
        reference: What it holds.
        variable: The environment variable to read. Non-empty **exactly when**
            the provider is :attr:`SecretProviderKind.ENVIRONMENT`.

    Raises:
        ValidationError: If ``variable`` disagrees with ``provider``, or names a
            variable :func:`variable_problems` refuses.

    **Beside the reference, never a field on it**, and that placement is the
    decision this type exists to record. :class:`SecretReference` is frozen with
    ``order=True`` and is a dictionary key, a sort key and a manifest field
    throughout; a fourth field would reorder every existing sort by its position
    alone. Worse, it would force a choice between two bad outcomes: either
    :func:`store_key` grows a component — which ADR-0074 records as a
    delete-and-recreate migration for every credential already written — or it
    ignores a field the reference carries, so two references comparing unequal
    produce one key. That second outcome is the silent collision the case-folding
    argument was written against.

    ``provider`` is the first field so that ordering groups locators by
    mechanism, which is the rendering an inventory wants.
    """

    provider: SecretProviderKind
    reference: SecretReference
    variable: str = ""

    def __post_init__(self) -> None:
        """Refuse a locator whose variable and provider disagree."""
        if self.provider is SecretProviderKind.ENVIRONMENT:
            if not self.variable:
                msg = (
                    f"{self.provider.value} names no variable for "
                    f"{self.reference.name!r}, and a hand-off with no variable "
                    f"has nowhere to read from"
                )
                raise ValidationError(msg)
            problems = variable_problems(self.variable)
            if problems:
                raise ValidationError("; ".join(problems))
        elif self.variable:
            msg = (
                f"{self.provider.value} reads no environment variable, so "
                f"{self.variable!r} would be carried and never used"
            )
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This locator as a publishable record.

        Returns:
            The provider, the reference's parts and the variable name.

        **The variable's name, never its value.** A name is ordinary data and is
        what an operator needs in order to fix a missing hand-off; the value is
        the secret, and nothing here can reach it.
        """
        return {
            "provider": self.provider.value,
            "environment": self.reference.environment.text,
            "kind": self.reference.kind.value,
            "name": self.reference.name,
            "variable": self.variable,
        }


PEM_ARMOUR: Final[str] = "-----BEGIN"
"""How a PEM-armoured key announces itself.

Named because :func:`entry_problems` uses it to turn one specific oversize
failure into a sentence somebody can act on. ``phase_028_sources.md`` S-11
records that an RSA-4096 key in PEM form is 3324 bytes and does not fit
:data:`MAX_SECRET_BYTES` at all; without this branch the platform answers with
an **undocumented** ``RPC_X_BAD_STUB_DATA``, which names neither the size nor
the ceiling.
"""


def control_characters() -> str:
    """Every C0 control character, plus DEL.

    Returns:
        The thirty-three characters, as one string.

    A function rather than a module constant, and the reason is the layer
    contract rather than taste: ``"".join(...)`` is a call, and
    ``tests/architecture/test_architecture_contract.py`` refuses any call
    executed when a layer module is imported. Written as a constant this was
    caught immediately, which is the tripwire working.

    Built from a range rather than written out, because a literal of thirty-three
    characters is thirty-three chances to omit one.
    """
    return "".join(chr(code) for code in (*range(0x20), 0x7F))


class EntryProblem(StrEnum):
    """Why collected material cannot be stored, in bounded terms.

    **No member carries an index, an offset or a substring of the material.** A
    length is safe -- :meth:`SecretValue.size_bytes` is already documented as
    publishable -- and everything finer is a description of the secret.

    Five members, and no minimum length among them. Any floor would be invented:
    what a real key looks like is a fact about a key type, and choosing one is
    Phase 038's. Non-empty is the only honest lower bound.
    """

    EMPTY = "empty"
    """Nothing was typed."""

    SURROUNDING_WHITESPACE = "surrounding_whitespace"
    """Leading or trailing whitespace.

    **Refused rather than stripped.** Stripping is a transformation nobody asked
    for, and it would make a credential whose true value has leading whitespace
    both unstorable and unreportable. A paste from a browser routinely carries a
    trailing newline, and a store that kept it would produce a credential wrong
    in a way nothing downstream can see.
    """

    CONTROL_CHARACTER = "control_character"
    """A C0 control character or DEL appears in the material.

    Either a paste accident or a terminal artefact -- and, the day Phase 038
    signs a request with this, a request-splitting hazard.
    """

    TOO_LARGE = "too_large"
    """The UTF-8 encoding exceeds :data:`MAX_SECRET_BYTES`."""

    ARMOURED_KEY_TOO_LARGE = "armoured_key_too_large"
    """It looks like a PEM key and it does not fit.

    A narrowing of :attr:`TOO_LARGE` that exists so the message can say "this
    looks like a PEM key of N bytes; the ceiling is 2560" rather than leaving
    somebody to discover the platform limit for themselves.
    """


class EntryFault(StrEnum):
    """Why interactive collection did not produce a value."""

    NOT_INTERACTIVE = "not_interactive"
    """Standard input is not a terminal, so nothing was read.

    Refused **before** any read is attempted. Accepting a pipe would make a
    shell one-liner that pipes a key into this command work, which places
    material in shell history and in the writing process command line -- both
    prohibited by ``SECURITY_BASELINE.md`` section 2.
    """

    ECHO_UNAVAILABLE = "echo_unavailable"
    """The platform could not suppress echo, so collection was abandoned.

    ``SECRET_STORE_CONTRACT.md`` section 5 requires that ``GetPassWarning``
    aborts collection rather than being printed. The abort happens **before the
    operator has typed anything**, because the ``getpass`` fallback warns before
    it reads -- so the value never exists, rather than existing and being
    discarded.
    """

    CANCELLED = "cancelled"
    """The operator ended the entry, or input reached its end."""

    MISMATCH = "mismatch"
    """The two entries differed.

    Also what is reported when the *second* entry is malformed, deliberately:
    the second entry shape is not disclosed, only that it differed.
    """

    REFUSED_FORMAT = "refused_format"
    """The material cannot be stored, and the problems say which rule it broke."""

    ENTRY_UNAVAILABLE = "entry_unavailable"
    """The terminal could not be read at all."""


def entry_problems(material: str) -> tuple[EntryProblem, ...]:
    """Every reason collected material cannot be stored.

    Args:
        material: What was typed.

    Returns:
        The problems, in a fixed order, empty when the material is storable.

    Structural only. **No exchange-specific format rule is applied**, and none
    is invented: what a Binance API key looks like is recorded in
    ``phase_020_sources.md`` S-15 and S-16 as venue documentation this phase
    deliberately does not choose from. Which key type is used against which
    surface is Phase 038's, and its permission model Phase 039's.

    The invariant tying this to the type it guards: the result is empty exactly
    when :class:`SecretValue` would construct without raising. A property test
    asserts it over generated input, so the validator cannot drift from the
    constructor it exists to front-run.
    """
    if not material:
        return (EntryProblem.EMPTY,)
    problems: list[EntryProblem] = []
    if material != material.strip():
        problems.append(EntryProblem.SURROUNDING_WHITESPACE)
    forbidden = control_characters()
    if any(character in forbidden for character in material):
        problems.append(EntryProblem.CONTROL_CHARACTER)
    if len(material.encode("utf-8")) > MAX_SECRET_BYTES:
        if material.startswith(PEM_ARMOUR):
            problems.append(EntryProblem.ARMOURED_KEY_TOO_LARGE)
        else:
            problems.append(EntryProblem.TOO_LARGE)
    return tuple(problems)


@dataclass(frozen=True, slots=True)
class SecretEntryOutcome:
    """What one attempt at interactive collection produced.

    Args:
        value: The collected material, or ``None`` when collection failed.
        fault: Why it failed, or ``None`` when it succeeded.
        problems: Which format rules were broken, when the fault is
            :attr:`EntryFault.REFUSED_FORMAT`.

    Raises:
        InternalError: If both or neither of ``value`` and ``fault`` are set, or
            if ``problems`` disagrees with the fault.

    The exactly-one invariant mirrors :class:`SecretResolution`, and raises for
    the same reason: a value that is simultaneously a success and a failure is a
    defect in this repository rather than a condition a caller should branch on.

    **There is no field a rendering could reach.** :meth:`as_record` emits the
    fault and the problems and has no branch that could emit the value, because
    :class:`SecretValue` has no encoder and no string form to emit.
    """

    value: SecretValue | None = None
    fault: EntryFault | None = None
    problems: tuple[EntryProblem, ...] = ()

    def __post_init__(self) -> None:
        """Refuse an outcome that claims two things at once.

        Raises:
            InternalError: As documented on the class.
        """
        if (self.value is None) == (self.fault is None):
            msg = "a collection outcome carries exactly one of a value and a fault"
            raise InternalError(msg)
        if self.problems and self.fault is not EntryFault.REFUSED_FORMAT:
            msg = "format problems accompany a refused format and nothing else"
            raise InternalError(msg)
        if self.fault is EntryFault.REFUSED_FORMAT and not self.problems:
            msg = "a refused format must say which rule it broke"
            raise InternalError(msg)

    @property
    def collected(self) -> bool:
        """Whether a value was produced.

        Returns:
            Whether collection succeeded.
        """
        return self.value is not None

    def as_record(self) -> dict[str, object]:
        """Render as ordinary data.

        Returns:
            Whether a value was collected, the fault and the problems. The value
            itself has no representation and therefore no way into this mapping.
        """
        return {
            "collected": self.collected,
            "fault": None if self.fault is None else self.fault.value,
            "problems": [problem.value for problem in self.problems],
        }
