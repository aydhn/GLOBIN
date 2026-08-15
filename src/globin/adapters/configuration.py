"""Reading configuration from a TOML document.

This adapter does two things and deliberately not a third. It reads a document
from a path, and it flattens the nested tables TOML produces into the dotted keys
:mod:`globin.domain.configuration` folds. It does **not** decide what any value
means: ``"WARNING"`` is carried through as the string it is, and becomes a
:class:`~globin.domain.observability.Severity` only when
:func:`~globin.domain.configuration.as_config` binds it.

That division is the point. When Phase 027 adds an environment-variable source it
will produce a layer of strings in exactly the same way, and inherit the same
validation rules rather than writing a second copy that drifts from this one. An
adapter that validated would make every future source a place where the schema
could be re-interpreted slightly differently.

**The path is given, never guessed.** This class takes whatever it is handed and
opens it, the same convention
:func:`~globin.runtime.composition.build_architecture_review` follows for the
repository root. Where configuration files live, what they are called and which
profiles exist are Phase 026's decisions; searching for a file or falling back
between locations here would settle them by accident.
"""

import tomllib
from collections.abc import Mapping
from pathlib import Path

from globin.domain.configuration import KEY_SEPARATOR, ConfigLayer, config_layer
from globin.errors import ConfigurationError


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
