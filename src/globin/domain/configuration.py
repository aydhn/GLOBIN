"""The typed configuration model, its defaults, and how layers override.

GLOBIN's configuration is a frozen dataclass, not a document. Everything an
operator may vary is a typed field with a declared default, and the only way to
obtain one of these objects is to hand :func:`as_config` a resolved set of
settings. A configuration that reaches the rest of the system has therefore
already been validated, and there is no partially-configured state for a caller
to observe.

**There is no schema library.** ADR-0003 makes the empty runtime dependency list
an invariant, so pydantic and its relatives were never available — but the
dataclasses are not a consolation prize. A declarative field table would have to
be restated by a dataclass anyway to be typed at all, which is two definitions
and a tripwire test to keep them equal. Here the dataclass *is* the schema:
:func:`section_keys` and :func:`section_defaults` derive the key registry and the
defaults from it, so a new setting is one line and cannot be half-added.

**Validation lives here, not in the adapter.** Reading ``"WARNING"`` as
:attr:`~globin.domain.observability.Severity.WARNING` is a domain rule. Putting
it in the TOML adapter would mean Phase 027's environment-variable source writes
a second copy, and two copies of a validation rule drift. The adapter's whole job
is to parse and flatten; the schema never leaves the core.

**Layers replace values; they never remove them.** A :class:`ConfigLayer` is a
flat mapping of dotted keys, and :func:`resolve` folds an ordered sequence of
them so that the last layer *mentioning* a key wins. Silence is not a value:
there is no unset sentinel, so no layer can delete a setting an earlier one
established. Flat keys are what make that simple — a nested deep-merge would have
to answer whether a table replaces or merges its counterpart, and every answer to
that question surprises somebody.

**Refusal happens once, at binding.** :func:`resolve` is total and never raises;
every rejection is in :func:`as_config`, where the schema and the *origin* of
each value are both in hand, so the message can say which document is wrong
rather than merely that something is.

What this module deliberately does not decide: where configuration files live
and what profiles exist (Phase 026), which sources are consulted and in what
order (Phase 027), how secrets are stored (Phase 028, against the rules in
``docs/security/SECURITY_BASELINE.md``), and what an environment is (Phase 035).
It knows nothing about files, environment variables, or the machine it runs on —
and the baseline is explicit that a secret never arrives through configuration
at all, which is why this module needs no notion of one.
"""

from collections.abc import Mapping, Sequence
from dataclasses import MISSING, dataclass, fields
from typing import Any, Final

from globin.domain.observability import Severity
from globin.errors import ConfigurationError, InternalError, ValidationError

KEY_SEPARATOR: Final[str] = "."
"""What separates a section from a setting name in a resolved key."""

LOGGING_SECTION: Final[str] = "logging"
"""The section name logging settings are filed under."""

DEFAULTS_ORIGIN: Final[str] = "defaults"
"""The origin recorded for values that came from the model's own declarations.

Named rather than left blank so that an error message about a defaulted value
reads the same way as one about a value from a file.
"""

MIN_SEVERITY: Final[str] = f"{LOGGING_SECTION}{KEY_SEPARATOR}min_severity"
"""The one setting GLOBIN has today.

Spelled out here as well as being derivable from :class:`LoggingConfig` because
:func:`as_config` needs a name to bind. The two are compared by
``tests/contract/test_configuration_contract.py``, which is what makes this a
tripwire rather than a copy — see ``docs/engineering/SOURCE_OF_TRUTH.md``.
"""


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """How much of what GLOBIN records is worth keeping.

    Args:
        min_severity: The lowest severity a sink will write. Records below it are
            discarded.

    The default is :attr:`~globin.domain.observability.Severity.DEBUG`, which
    discards nothing. Two arguments land on that value independently. It
    preserves Phase 006's behaviour exactly, so adding configuration changes no
    existing output; and ``ENGINEERING_CONTRACT.md`` invariant 22 makes
    discarding data an explicit decision rather than a side effect, which a
    default of ``INFO`` would quietly violate on GLOBIN's behalf.

    That is not in tension with invariant 2, "fail closed". Failing closed
    governs *ambiguity* — an unreadable severity raises rather than falling back,
    and :func:`as_config` does exactly that. It says nothing about which value a
    declared default should be.
    """

    min_severity: Severity = Severity.DEBUG


@dataclass(frozen=True, slots=True)
class GlobinConfig:
    """Everything an operator may vary, one field per subsystem that has any.

    Args:
        logging: Logging settings.

    One section is the honest width today. Of everything Phases 001-006 built,
    only logging has something an operator may reasonably change: the project
    contract and the roadmap are immutable identity, the error taxonomy has
    nothing to tune, and the architecture review's two paths are constants rather
    than settings. A configuration model is exactly where speculative fields
    accumulate, and ``REPOSITORY_LAYOUT.md`` already refuses the same thing for
    directories — an entry named after a future capability is a claim that the
    capability is being worked on.

    ``logging`` has no default. A nested dataclass default would have to be
    written ``LoggingConfig()``, and a call in a class body is work performed at
    import, which ``tests/architecture/test_architecture_contract.py`` forbids in
    every layer package. :func:`default_config` is the supported way to obtain a
    fully-defaulted instance.
    """

    logging: LoggingConfig


@dataclass(frozen=True, slots=True)
class ConfigLayer:
    """One source's contribution: flat dotted keys, and where they came from.

    Args:
        origin: Where these values came from, in words an operator would
            recognise — a file path, or :data:`DEFAULTS_ORIGIN`. It travels with
            the values so that a later refusal can name the document at fault.
        values: Settings this layer sets, as key/value pairs. Usually easier to
            pass as a mapping; :func:`config_layer` does the conversion.

    Raises:
        ValidationError: If ``origin`` is empty, or a key is set more than once.

    Construction normalises: pairs are sorted by key, so two layers carrying the
    same settings compare equal regardless of the order they were supplied in
    (``ENGINEERING_CONTRACT.md`` invariant 3).

    A layer setting the same key twice is refused rather than resolved by
    position. Within one document that is a mistake with no defensible reading —
    unlike the *between* layers case, which is the whole point of the mechanism.
    """

    origin: str
    values: tuple[tuple[str, object], ...] = ()

    def __post_init__(self) -> None:
        """Validate the origin and the keys, then canonicalise the order."""
        if not self.origin:
            msg = "configuration layer has an empty origin; name where its values came from"
            raise ValidationError(msg)

        seen: set[str] = set()
        repeated: set[str] = set()
        for key, _value in self.values:
            if key in seen:
                repeated.add(key)
            seen.add(key)
        if repeated:
            msg = f"configuration layer {self.origin!r} sets {sorted(repeated)} more than once"
            raise ValidationError(msg)

        object.__setattr__(self, "values", tuple(sorted(self.values, key=_key_of)))


def _key_of(item: tuple[str, object]) -> str:
    """Return the key of a key/value pair, for sorting.

    Args:
        item: One key/value pair.

    Returns:
        The key alone.

    Sorting by the key rather than by the whole pair is not tidiness.
    :class:`~globin.domain.observability.LogEvent` gets away with sorting whole
    items because it sorts a dictionary, whose keys are unique, so the tie-break
    on values never runs. This class accepts a tuple of pairs, where a duplicate
    key *would* reach the value comparison and raise :exc:`TypeError` on two
    values of different types. Duplicates are rejected before the sort anyway;
    keying it means the sort cannot depend on that ordering being correct.
    """
    return item[0]


def config_layer(origin: str, values: Mapping[str, object]) -> ConfigLayer:
    """Build a :class:`ConfigLayer` from a mapping.

    Args:
        origin: Where these values came from.
        values: Dotted keys mapped to their values.

    Returns:
        A canonically ordered :class:`ConfigLayer`.

    Raises:
        ValidationError: As :class:`ConfigLayer`.
    """
    return ConfigLayer(origin=origin, values=tuple(values.items()))


@dataclass(frozen=True, slots=True)
class Setting:
    """One resolved value, and the layer that won it.

    Args:
        key: The dotted setting name.
        value: Whatever the winning layer supplied, not yet validated.
        origin: The :attr:`ConfigLayer.origin` of the layer that supplied it.

    The origin is carried rather than discarded because the question an operator
    asks when configuration surprises them is never "what is the value" — they
    can see that — but "which file set it".
    """

    key: str
    value: object
    origin: str


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    """Every setting any layer mentioned, one entry each, sorted by key.

    Args:
        settings: The winning :class:`Setting` per key.

    Still untyped and still unvalidated: this is the output of the fold, not of
    the schema. :func:`as_config` turns it into a :class:`GlobinConfig`.
    """

    settings: tuple[Setting, ...] = ()

    def keys(self) -> tuple[str, ...]:
        """Return every key that resolved to a value.

        Returns:
            The keys, in sorted order.
        """
        return tuple(setting.key for setting in self.settings)

    def setting(self, key: str) -> Setting:
        """Return the winning setting for ``key``.

        Args:
            key: The dotted setting name.

        Returns:
            The :class:`Setting` that won.

        Raises:
            InternalError: If nothing resolved for ``key``. Callers check
                completeness before asking, so reaching this means a GLOBIN
                invariant broke rather than a document being wrong — the same
                reasoning as
                :meth:`~globin.domain.architecture.ArchitectureContract.policy_for`.
        """
        for setting in self.settings:
            if setting.key == key:
                return setting
        msg = f"no value resolved for {key!r}; resolved keys are {list(self.keys())}"
        raise InternalError(msg)


def section_keys(section: str, model: type[Any]) -> tuple[str, ...]:
    """Return the dotted key of every field on a configuration section.

    Args:
        section: The section name the fields are filed under.
        model: The frozen dataclass declaring the section's settings.

    Returns:
        One dotted key per field, in declaration order.

    ``model`` is typed :class:`typing.Any` because there is no public runtime
    type for "a dataclass". Naming it honestly is better than a cast that claims
    a precision this signature does not have — the same reasoning
    ``docs/engineering/STATIC_ANALYSIS.md`` gives for leaving
    ``disallow_any_explicit`` off.
    """
    return tuple(f"{section}{KEY_SEPARATOR}{item.name}" for item in fields(model))


def section_defaults(section: str, model: type[Any]) -> dict[str, object]:
    """Return the declared default of every field on a configuration section.

    Args:
        section: The section name the fields are filed under.
        model: The frozen dataclass declaring the section's settings.

    Returns:
        Dotted keys mapped to the defaults declared on the dataclass.

    Raises:
        InternalError: If a field declares no default. A setting that cannot be
            resolved without a configuration file makes the defaults layer
            incomplete, which is a defect in the model rather than in anything an
            operator wrote.
    """
    values: dict[str, object] = {}
    for item in fields(model):
        if item.default is MISSING:
            msg = (
                f"setting {section}{KEY_SEPARATOR}{item.name} declares no default; "
                f"every setting must resolve without a configuration file"
            )
            raise InternalError(msg)
        values[f"{section}{KEY_SEPARATOR}{item.name}"] = item.default
    return values


def known_keys() -> tuple[str, ...]:
    """Return every setting an operator may set.

    Returns:
        The dotted keys :func:`as_config` accepts, in declaration order.
    """
    return section_keys(LOGGING_SECTION, LoggingConfig)


def default_layer() -> ConfigLayer:
    """Return the weakest layer: every setting at its declared default.

    Returns:
        A :class:`ConfigLayer` whose origin is :data:`DEFAULTS_ORIGIN`.

    Raises:
        InternalError: As :func:`section_defaults`.

    This belongs at position zero of the sequence given to :func:`resolve`.
    Without it a document that omits a setting resolves to nothing for that key,
    and :func:`as_config` refuses.
    """
    return config_layer(DEFAULTS_ORIGIN, section_defaults(LOGGING_SECTION, LoggingConfig))


def default_config() -> GlobinConfig:
    """Return the configuration GLOBIN uses when nothing overrides anything.

    Returns:
        A :class:`GlobinConfig` with every setting at its declared default.

    Derived by construction rather than by resolution, so that
    ``tests/property/test_configuration_properties.py`` can assert the two routes
    to "the defaults" agree. If they ever disagree, one of them is lying.
    """
    return GlobinConfig(logging=LoggingConfig())


def resolve(layers: Sequence[ConfigLayer]) -> ResolvedConfig:
    """Fold ordered layers into one value per key, later layers winning.

    Args:
        layers: Weakest first, strongest last. :func:`default_layer` belongs at
            position zero.

    Returns:
        A :class:`ResolvedConfig` holding the winning :class:`Setting` for every
        key any layer mentioned, sorted by key.

    **This never raises.** It does not know the schema, so an unknown key is
    carried through rather than rejected here; refusal is :func:`as_config`'s
    job, where the schema and the origin are both available. Keeping the fold
    total is what makes it a mechanism rather than a policy, and it is the
    property Phase 027 will build its source ordering on top of.

    ``layers`` is a :class:`~collections.abc.Sequence` rather than an
    :class:`~collections.abc.Iterable` deliberately.
    :func:`~globin.domain.architecture.import_cycles` shipped a defect in Phase
    005 by reading a one-shot iterable twice and confidently reporting no cycles;
    this reads once, and declaring the narrower type removes the class of mistake
    rather than relying on it not recurring.
    """
    winners: dict[str, Setting] = {}
    for layer in layers:
        for key, value in layer.values:
            winners[key] = Setting(key=key, value=value, origin=layer.origin)
    return ResolvedConfig(settings=tuple(winners[key] for key in sorted(winners)))


def as_config(resolved: ResolvedConfig) -> GlobinConfig:
    """Validate resolved settings and build the typed model.

    Args:
        resolved: The output of :func:`resolve`.

    Returns:
        The validated :class:`GlobinConfig`.

    Raises:
        ConfigurationError: If a key is not a setting, or a value cannot be read
            as the type its setting requires. The operator edits a document, and
            the message names both the key and the document.
        InternalError: If a known setting resolved to nothing. The only way to
            reach this is to resolve without :func:`default_layer`, which no
            operator can do.

    An unknown key is refused rather than ignored. Ignoring it is how a typo
    silently disables a setting an operator believes they have set, which is the
    failure this whole module exists to prevent — and every unknown key is
    reported at once, so fixing one does not merely reveal the next.
    """
    known = known_keys()
    unknown = [item for item in resolved.settings if item.key not in known]
    if unknown:
        detail = ", ".join(f"{item.key!r} (set by {item.origin})" for item in unknown)
        msg = f"unknown setting(s): {detail}; known settings are {sorted(known)}"
        raise ConfigurationError(msg)

    resolved_keys = resolved.keys()
    missing = [key for key in known if key not in resolved_keys]
    if missing:
        msg = (
            f"no value resolved for {missing}; the defaults layer was not included "
            f"in the sequence given to resolve()"
        )
        raise InternalError(msg)

    return GlobinConfig(
        logging=LoggingConfig(min_severity=_severity(resolved.setting(MIN_SEVERITY)))
    )


def _severity(setting: Setting) -> Severity:
    """Read a severity from a resolved value, refusing anything else.

    Args:
        setting: The resolved setting, carrying its origin for the message.

    Returns:
        The :class:`~globin.domain.observability.Severity` it names.

    Raises:
        ConfigurationError: If the value is not a severity name.

    Two refusals are deliberate. **An integer is not accepted**, even though
    :class:`~globin.domain.observability.Severity` is an :class:`~enum.IntEnum`:
    ``25`` is not a member, and a threshold that silently means something between
    two levels is worse than one that refuses. **Case is exact**, matching the
    spelling in ``docs/LOGGING_POLICY.md`` and the existing behaviour of
    ``globin.adapters.architecture``. One spelling, and the message enumerates
    it, so a rejected value tells the operator what to write instead.
    """
    value = setting.value
    if isinstance(value, Severity):
        return value
    names = [member.name for member in Severity]
    if not isinstance(value, str) or value not in names:
        msg = f"{setting.origin}: {setting.key} is {value!r}; expected one of {names}"
        raise ConfigurationError(msg)
    return Severity[value]
