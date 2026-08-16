"""The configuration units: layers, the fold, the schema and the TOML source.

Four things are checked here, and the split matters. The *fold* is tested for
what it does with layers that disagree; the *schema* for what it derives from the
model; the *binding* for every way it refuses; and the *source* for what it makes
of a document. Whether the composition root wires them together is
``tests/integration/test_configuration_end_to_end.py``, and whether the fold's
laws hold over generated layers is
``tests/property/test_configuration_properties.py``.

Every refusal has a test, including the two that raise
:exc:`~globin.errors.InternalError`. Those are unreachable through any document
an operator could write — which is exactly why they would otherwise ship
unexercised, and a guard nobody has seen fire is indistinguishable from one that
cannot.
"""

import tomllib
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path

import pytest

from globin.adapters.configuration import TomlConfigurationSource, flatten
from globin.domain.configuration import (
    DEFAULTS_ORIGIN,
    KEY_SEPARATOR,
    LOGGING_SECTION,
    MIN_SEVERITY,
    ROTATION_BACKUP_COUNT,
    ROTATION_MAX_BYTES,
    ConfigLayer,
    LoggingConfig,
    ResolvedConfig,
    Setting,
    as_config,
    config_layer,
    default_config,
    default_layer,
    known_keys,
    resolve,
    section_defaults,
    section_keys,
)
from globin.domain.observability import Severity
from globin.errors import ConfigurationError, InternalError, ValidationError
from tests.support import resolved_configuration


@dataclass(frozen=True, slots=True)
class _Defaulted:
    """A synthetic section, standing in for a model with more than one setting."""

    first: int = 1
    second: str = "two"


@dataclass(frozen=True, slots=True)
class _Undefaulted:
    """A synthetic section whose setting declares no default, which is a defect."""

    required: int


def _resolved(**values: object) -> ResolvedConfig:
    """Resolve the defaults with one override layer on top."""
    return resolved_configuration(**values)


# --------------------------------------------------------------------------
# Layers
# --------------------------------------------------------------------------


def test_a_layer_must_say_where_its_values_came_from() -> None:
    with pytest.raises(ValidationError, match="empty origin"):
        ConfigLayer(origin="", values=(("a", 1),))


def test_a_layer_may_not_set_the_same_key_twice() -> None:
    with pytest.raises(ValidationError, match="more than once"):
        ConfigLayer(origin="test", values=(("a", 1), ("b", 2), ("a", 3)))


def test_the_duplicate_message_names_every_repeated_key() -> None:
    with pytest.raises(ValidationError) as refused:
        ConfigLayer(origin="test", values=(("a", 1), ("a", 2), ("b", 3), ("b", 4)))
    assert "'a', 'b'" in str(refused.value)


def test_a_layer_is_ordered_by_key_whatever_order_it_was_given() -> None:
    forwards = config_layer("test", {"a": 1, "b": 2})
    backwards = ConfigLayer(origin="test", values=(("b", 2), ("a", 1)))
    assert forwards == backwards
    assert forwards.values == (("a", 1), ("b", 2))


def test_a_layer_sorts_by_key_alone_so_unorderable_values_are_no_obstacle() -> None:
    """Sorting whole pairs would compare an ``int`` with a ``str`` and raise."""
    layer = ConfigLayer(origin="test", values=(("b", 1), ("a", "one")))
    assert layer.values == (("a", "one"), ("b", 1))


def test_a_layer_may_be_empty() -> None:
    assert config_layer("test", {}).values == ()


# --------------------------------------------------------------------------
# The fold
# --------------------------------------------------------------------------


def test_a_later_layer_overrides_an_earlier_one_and_records_that_it_did() -> None:
    resolved = resolve(
        (config_layer("weak", {"a": 1}), config_layer("strong", {"a": 2})),
    )
    assert resolved.setting("a") == Setting(key="a", value=2, origin="strong")


def test_a_key_a_later_layer_does_not_mention_survives() -> None:
    resolved = resolve(
        (config_layer("weak", {"a": 1}), config_layer("strong", {"b": 2})),
    )
    assert resolved.setting("a") == Setting(key="a", value=1, origin="weak")


def test_resolving_nothing_resolves_nothing() -> None:
    assert resolve(()) == ResolvedConfig()


def test_the_fold_does_not_know_the_schema_and_so_carries_an_unknown_key() -> None:
    """Refusal belongs to :func:`as_config`, where the origin is in hand."""
    resolved = resolve((config_layer("test", {"nonsense": 1}),))
    assert resolved.keys() == ("nonsense",)


def test_keys_come_back_sorted() -> None:
    resolved = resolve((config_layer("test", {"c": 3, "a": 1, "b": 2}),))
    assert resolved.keys() == ("a", "b", "c")


def test_asking_for_a_setting_that_did_not_resolve_is_an_internal_error() -> None:
    with pytest.raises(InternalError, match="no value resolved"):
        ResolvedConfig().setting("logging.min_severity")


# --------------------------------------------------------------------------
# The schema, derived from the model
# --------------------------------------------------------------------------


def test_the_key_registry_is_derived_from_the_dataclass() -> None:
    assert section_keys("demo", _Defaulted) == ("demo.first", "demo.second")


def test_defaults_are_derived_from_the_dataclass() -> None:
    assert section_defaults("demo", _Defaulted) == {"demo.first": 1, "demo.second": "two"}


def test_a_setting_with_no_declared_default_is_a_defect_in_the_model() -> None:
    with pytest.raises(InternalError, match="declares no default"):
        section_defaults("demo", _Undefaulted)


def test_the_known_keys_are_exactly_what_as_config_binds() -> None:
    """The tripwire that lets each key name be spelled out separately.

    Compared as a set rather than a tuple. `known_keys()` derives its order from
    the dataclass's field order, and a phase adding a field in the middle of a
    section would otherwise fail here for a reason that is not about correctness —
    the ordering is not a promise this module makes to anybody.
    """
    assert set(known_keys()) == {MIN_SEVERITY, ROTATION_MAX_BYTES, ROTATION_BACKUP_COUNT}


def test_the_defaults_layer_records_where_its_values_came_from() -> None:
    assert default_layer().origin == DEFAULTS_ORIGIN


def test_the_two_routes_to_the_defaults_agree() -> None:
    assert as_config(resolve((default_layer(),))) == default_config()


def test_the_default_threshold_discards_nothing() -> None:
    assert default_config().logging.min_severity is Severity.DEBUG
    assert default_config().logging.min_severity is min(Severity)


# --------------------------------------------------------------------------
# Binding and refusal
# --------------------------------------------------------------------------


@pytest.mark.parametrize("severity", list(Severity), ids=lambda item: item.name)
def test_every_severity_can_be_configured_by_name(severity: Severity) -> None:
    config = as_config(_resolved(**{MIN_SEVERITY: severity.name}))
    assert config.logging.min_severity is severity


def test_a_severity_that_is_already_one_is_accepted() -> None:
    """How the defaults layer's own value arrives, since it is never a string."""
    config = as_config(_resolved(**{MIN_SEVERITY: Severity.ERROR}))
    assert config.logging.min_severity is Severity.ERROR


def test_a_severity_spelled_in_the_wrong_case_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="expected one of"):
        as_config(_resolved(**{MIN_SEVERITY: "warning"}))


def test_a_number_is_not_a_severity() -> None:
    """``25`` is between two levels, and a threshold that means "between" is worse.

    than one that refuses.
    """
    with pytest.raises(ConfigurationError, match="expected one of"):
        as_config(_resolved(**{MIN_SEVERITY: 25}))


def test_the_numeric_value_of_a_real_level_is_refused_too() -> None:
    with pytest.raises(ConfigurationError, match="expected one of"):
        as_config(_resolved(**{MIN_SEVERITY: 30}))


def test_a_refused_value_names_the_document_that_set_it() -> None:
    with pytest.raises(ConfigurationError) as refused:
        as_config(resolve((default_layer(), config_layer("some-file.toml", {MIN_SEVERITY: "no"}))))
    assert "some-file.toml" in str(refused.value)


def test_an_unknown_setting_is_refused_rather_than_ignored() -> None:
    with pytest.raises(ConfigurationError, match="unknown setting") as refused:
        as_config(_resolved(**{"logging.colour": "green"}))
    message = str(refused.value)
    assert "logging.colour" in message
    assert "test" in message


def test_every_unknown_setting_is_reported_at_once() -> None:
    """Fixing one typo should not merely reveal the next."""
    with pytest.raises(ConfigurationError) as refused:
        as_config(_resolved(**{"logging.colour": 1, "trading.enabled": True}))
    message = str(refused.value)
    assert "logging.colour" in message
    assert "trading.enabled" in message


def test_binding_without_the_defaults_layer_is_an_internal_error() -> None:
    """Not something a document can cause, which is why it is not an operator's fault."""
    with pytest.raises(InternalError, match="defaults layer"):
        as_config(resolve(()))


# --------------------------------------------------------------------------
# Flattening a document
# --------------------------------------------------------------------------


def test_a_nested_table_becomes_a_dotted_key() -> None:
    document: dict[str, object] = {"logging": {"min_severity": "INFO"}}
    assert flatten(document, "test") == {MIN_SEVERITY: "INFO"}


def test_nesting_may_go_deeper_than_one_table() -> None:
    assert flatten({"a": {"b": {"c": 1}}}, "test") == {"a.b.c": 1}


def test_a_table_with_nothing_in_it_sets_nothing() -> None:
    assert flatten({"logging": {}}, "test") == {}


def test_a_top_level_value_keeps_its_bare_name() -> None:
    assert flatten({"loud": True}, "test") == {"loud": True}


def test_an_array_of_tables_survives_as_a_value_to_be_refused_later() -> None:
    assert flatten({"rules": [{"a": 1}]}, "test") == {"rules": [{"a": 1}]}


@pytest.mark.parametrize(
    "document",
    [
        pytest.param({"a.b": 1}, id="at the top level"),
        pytest.param({"section": {"a.b": 1}}, id="inside a table"),
    ],
)
def test_a_quoted_key_containing_the_separator_is_refused(document: dict[str, object]) -> None:
    """TOML's ``"a.b" = 1`` is one key; flattened it would be indistinguishable.

    from a table, so the two spellings would collide.
    """
    with pytest.raises(ConfigurationError, match="separates"):
        flatten(document, "test")


def test_the_separator_the_message_complains_about_is_the_one_in_use() -> None:
    assert KEY_SEPARATOR in MIN_SEVERITY
    assert MIN_SEVERITY.startswith(f"{LOGGING_SECTION}{KEY_SEPARATOR}")


# --------------------------------------------------------------------------
# The TOML source
# --------------------------------------------------------------------------


def _document(tmp_path: Path, text: str) -> Path:
    """Write a document, always as UTF-8 without a byte-order mark.

    PowerShell's default encoding writes one, and ``tomllib`` rejects it.
    """
    path = tmp_path / "globin.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_document_becomes_a_layer_named_after_its_path(tmp_path: Path) -> None:
    path = _document(tmp_path, '[logging]\nmin_severity = "WARNING"\n')
    layer = TomlConfigurationSource(path).layer()
    assert layer.origin == str(path)
    assert layer.values == ((MIN_SEVERITY, "WARNING"),)


def test_a_document_resolves_through_to_a_configuration(tmp_path: Path) -> None:
    path = _document(tmp_path, '[logging]\nmin_severity = "ERROR"\n')
    config = as_config(resolve((default_layer(), TomlConfigurationSource(path).layer())))
    assert config.logging.min_severity is Severity.ERROR


def test_an_empty_document_overrides_nothing(tmp_path: Path) -> None:
    path = _document(tmp_path, "")
    config = as_config(resolve((default_layer(), TomlConfigurationSource(path).layer())))
    assert config == default_config()


def test_a_document_that_is_not_valid_toml_fails_as_a_parse_error(tmp_path: Path) -> None:
    """Left unwrapped: ``tomllib`` reports the line and column, which is worth.

    more than a reworded message.
    """
    path = _document(tmp_path, "this is not = = toml\n")
    with pytest.raises(tomllib.TOMLDecodeError):
        TomlConfigurationSource(path).layer()


def test_a_document_that_is_not_there_fails_as_a_read_error(tmp_path: Path) -> None:
    """Whether a missing source is fatal is Phase 027's decision, not this one's."""
    with pytest.raises(OSError, match=r"absent\.toml"):
        TomlConfigurationSource(tmp_path / "absent.toml").layer()


def test_an_unknown_setting_in_a_document_names_the_file(tmp_path: Path) -> None:
    path = _document(tmp_path, '[logging]\ncolour = "green"\n')
    with pytest.raises(ConfigurationError) as refused:
        as_config(resolve((default_layer(), TomlConfigurationSource(path).layer())))
    assert str(path) in str(refused.value)
    assert "logging.colour" in str(refused.value)


def test_a_model_section_is_frozen() -> None:
    config = LoggingConfig()
    with pytest.raises(FrozenInstanceError):
        config.min_severity = Severity.ERROR  # type: ignore[misc]
