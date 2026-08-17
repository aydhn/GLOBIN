"""Reading configuration from a TOML document, from the environment, or from neither.

These adapters do two things and deliberately not a third. They obtain values from
somewhere, and they present them as the dotted keys
:mod:`globin.domain.configuration` folds. They do **not** decide what any value
means: ``"WARNING"`` is carried through as the string it is, and becomes a
:class:`~globin.domain.observability.Severity` only when
:func:`~globin.domain.configuration.as_config` binds it.

That division paid off exactly as Phase 026 predicted it would.
:class:`EnvironmentConfigurationSource` produces a layer of strings in the same way
:class:`TomlConfigurationSource` does, and inherits the same validation rules rather
than carrying a second copy — ``_flag`` and ``_bounded`` already accepted strings,
with their own docstrings naming this phase as the reason. Not one binder was added
to read the environment.

**The path is given, never guessed.** These classes take whatever they are handed
and open it. Where configuration files live, what they are called and which profiles
exist are Phase 026's decisions; searching for a file or falling back between
locations here would settle them by accident.

**Whether a missing document is fatal is answered here, by a wrapper rather than by
a flag.** Phase 026 left the question open in exactly those words, and
:class:`OptionalDocumentSource` is the answer: a source whose document may be absent
is *wrapped* in one, so the decision is visible at the composition root where the
chain is assembled, instead of being a boolean somebody has to look up.
"""

import tomllib
from collections.abc import Mapping
from pathlib import Path

from globin.domain.configuration import (
    ENVIRONMENT_ORIGIN,
    ENVIRONMENT_PREFIX,
    KEY_SEPARATOR,
    PROFILE_VARIABLE,
    ConfigLayer,
    config_layer,
    environment_names,
)
from globin.domain.observability import is_sensitive
from globin.errors import ConfigurationError
from globin.ports.configuration import ConfigurationSource


def flatten(document: Mapping[str, object], origin: str) -> dict[str, object]:
    """Turn a nested TOML document into flat dotted keys.

    Args:
        document: The parsed document, whose tables are nested mappings.
        origin: Where the document came from, for the message if a key is
            unusable.

    Returns:
        Dotted keys mapped to leaf values. Empty tables contribute nothing,
        because a table with no settings in it sets no settings.

    Raises:
        ConfigurationError: If a key contains :data:`KEY_SEPARATOR`. TOML permits
            it through quoting — ``"a.b" = 1`` is one key, not two — but the
            flattened form could not tell that apart from a table, so the two
            spellings would resolve to the same setting. Refusing is the only
            answer that is not a guess.

    An array of tables flattens to a list value rather than to keys. Nothing in
    GLOBIN's model is a list, so such a value survives to
    :func:`~globin.domain.configuration.as_config` and is refused there, with the
    key and the document named.
    """
    flat: dict[str, object] = {}
    for name, value in document.items():
        if KEY_SEPARATOR in name:
            msg = (
                f"{origin}: key {name!r} contains {KEY_SEPARATOR!r}, which separates "
                f"a section from a setting; rename it or nest it in a table"
            )
            raise ConfigurationError(msg)
        if isinstance(value, Mapping):
            for nested_key, nested_value in flatten(value, origin).items():
                flat[f"{name}{KEY_SEPARATOR}{nested_key}"] = nested_value
            continue
        flat[name] = value
    return flat


class TomlConfigurationSource:
    """Supplies a configuration layer from a TOML document on disk.

    Args:
        path: Location of the document. Given by the caller; this class neither
            searches for one nor knows a default.

    TOML is parsed with the standard library's :mod:`tomllib`, so configuration
    costs no runtime dependency — which matters, because ADR-0003 makes the empty
    runtime dependency list an invariant rather than a default.
    """

    def __init__(self, path: Path) -> None:
        """Bind the reader to a document.

        Args:
            path: The configuration file to read when asked.
        """
        self._path = path

    def layer(self) -> ConfigLayer:
        """Read the document and return its settings as one layer.

        Returns:
            A :class:`~globin.domain.configuration.ConfigLayer` whose origin is
            the path, so that a later refusal names the file that caused it.

        Raises:
            ConfigurationError: If a key cannot be flattened — see
                :func:`flatten`.
            tomllib.TOMLDecodeError: If the document is not valid TOML. That is a
                malformed *file* rather than malformed *configuration*, and
                :mod:`tomllib` already reports the line and column, so it is
                allowed through rather than reworded — the same treatment
                :class:`~globin.adapters.architecture.TomlArchitectureContractSource`
                gives it.
            OSError: If the document cannot be read. Whether a missing file is
                fatal or merely means "this layer is empty" depends on which
                source it is, and that is Phase 027's decision rather than this
                adapter's to guess.
        """
        with self._path.open("rb") as handle:
            document = tomllib.load(handle)
        origin = str(self._path)
        return config_layer(origin, flatten(document, origin))


def reserved_variables() -> tuple[str, ...]:
    """Every ``GLOBIN_`` variable that is deliberately not a setting.

    Returns:
        The reserved names.

    One today. :data:`~globin.domain.configuration.PROFILE_VARIABLE` selects which
    documents are read, so it cannot be one of the settings those documents contain
    without being defined in terms of itself.

    This exists so that :class:`EnvironmentConfigurationSource` can refuse an
    unrecognised variable without that refusal having a hard-coded exception buried
    inside it. A later phase adding a second non-setting variable adds it here, and
    the refusal keeps working unchanged.
    """
    return (PROFILE_VARIABLE,)


class OptionalDocumentSource:
    """A source whose document may simply not be there.

    Args:
        inner: The source to consult.
        origin: What to call the empty layer when the document is absent, so a
            reader of the resolved settings can still see that this source was
            consulted and had nothing to say.

    **The absence that is tolerated is narrow, and narrowness is the whole value.**
    Only "the file is not there" becomes an empty layer. A file that exists and
    cannot be read, a directory where a file should be, a document that is not valid
    TOML, a key that cannot be flattened — every one of those propagates. An operator
    who wrote a configuration file and mistyped its permissions is told; an operator
    who wrote no file at all is not nagged about a file they never intended.

    The tempting alternative was a ``missing_is_empty`` flag on
    :class:`TomlConfigurationSource`. It was refused because it would put the
    decision inside the reader, where a caller assembling a chain cannot see which
    of its documents are required — and *which* documents are required is precisely
    the thing Phase 027 was asked to make explicit.
    """

    def __init__(self, inner: ConfigurationSource, origin: str) -> None:
        """Bind the wrapper to a source.

        Args:
            inner: The source to consult.
            origin: What the empty layer is called when there is no document.
        """
        self._inner = inner
        self._origin = origin

    def layer(self) -> ConfigLayer:
        """Read the document, or return an empty layer when there is none.

        Returns:
            The inner source's layer, or an empty layer with this wrapper's origin.

        Raises:
            ConfigurationError: As the inner source.
            OSError: As the inner source, except for the two absences below.
            tomllib.TOMLDecodeError: As the inner source.

        :exc:`NotADirectoryError` is caught beside :exc:`FileNotFoundError` because
        on Windows a path whose *parent* is missing raises one rather than the other,
        and both mean the same thing here: the document is not present. Catching only
        the obvious one would make an absent ``config/local/`` directory a start-up
        failure on one platform and not on another.
        """
        try:
            return self._inner.layer()
        except (FileNotFoundError, NotADirectoryError):
            return config_layer(self._origin, {})


class EnvironmentConfigurationSource:
    """Supplies a configuration layer from ``GLOBIN_`` environment variables.

    Args:
        environment: The variables to read. Handed in rather than read here, which
            is the treatment :func:`~globin.adapters.runtime_state.resolve_root`
            already gives the environment and is what lets a test set one variable
            without touching the process.

    **The prefix is what makes a typo detectable.** Without a namespace there would
    be no way to tell "a setting spelled wrongly" from "some other program's
    variable", and the choice would be between ignoring typos and refusing to start
    because of somebody else's ``PATH``. With one, an unrecognised ``GLOBIN_``
    variable is unambiguously a mistake about GLOBIN, so it is **refused** — the same
    answer :func:`~globin.domain.configuration.as_config` gives an unknown key, for
    the same reason: a typo that silently disables a setting an operator believes
    they have set is the failure this whole mechanism exists to prevent.

    **A credential-shaped variable is refused before it is looked up.**
    ``SECURITY_BASELINE.md`` says a secret never arrives through configuration at
    all, and the environment is where somebody would try. Refusing on the *name*
    means the value is never read, never carried into a layer, and never anywhere a
    later redaction has to be trusted to catch it — and the message can say what the
    rule is rather than merely that the key is unknown.
    """

    def __init__(self, environment: Mapping[str, str]) -> None:
        """Bind the reader to a set of variables.

        Args:
            environment: The variables to read when asked.
        """
        self._environment = environment

    def layer(self) -> ConfigLayer:
        """Read every recognised variable and return them as one layer.

        Returns:
            A :class:`~globin.domain.configuration.ConfigLayer` whose origin is
            :data:`~globin.domain.configuration.ENVIRONMENT_ORIGIN`.

        Raises:
            ConfigurationError: If any ``GLOBIN_`` variable is credential-shaped, or
                names no setting. Every offending variable is reported at once, so
                fixing one does not merely reveal the next.

        Values stay strings. Nothing here parses ``"true"`` or ``"9464"``, because
        :func:`~globin.domain.configuration.as_config` already reads both and a
        second reader would be a second set of rules.
        """
        settings: dict[str, object] = {}
        credentials: list[str] = []
        unknown: list[str] = []
        recognised = dict(environment_names())
        reserved = reserved_variables()
        for name, value in sorted(self._environment.items()):
            if not name.startswith(ENVIRONMENT_PREFIX) or name in reserved:
                continue
            if is_sensitive(name):
                credentials.append(name)
            elif name in recognised:
                settings[recognised[name]] = value
            else:
                unknown.append(name)
        if credentials:
            msg = (
                f"{ENVIRONMENT_ORIGIN}: {', '.join(credentials)} "
                f"{'looks' if len(credentials) == 1 else 'look'} like a credential; "
                f"no secret reaches GLOBIN through configuration, so no such setting "
                f"exists and the value was not read "
                f"(see docs/security/SECURITY_BASELINE.md)"
            )
            raise ConfigurationError(msg)
        if unknown:
            msg = (
                f"{ENVIRONMENT_ORIGIN}: {', '.join(unknown)} "
                f"{'names' if len(unknown) == 1 else 'name'} no setting; "
                f"settable variables are {sorted(recognised)}"
            )
            raise ConfigurationError(msg)
        return config_layer(ENVIRONMENT_ORIGIN, settings)
