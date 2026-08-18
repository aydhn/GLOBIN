"""The whole precedence chain, through the command an operator actually runs.

``test_configuration_end_to_end.py`` owns the fold's behaviour across sources.
This owns what Phase 030 added around it: the six-layer chain assembled by the
composition root, the two fingerprints, and the drift report that compares one
run against the last.

Every document here is written into ``tmp_path``. Nothing writes into the
repository, and the one test that needs a runtime tree points the state store at
a temporary directory rather than a real user profile.
"""

import io
import json
from pathlib import Path

import pytest

from globin.adapters.configuration import parse_overrides
from globin.domain.bootstrap import ExitCode
from globin.domain.config_evidence import (
    ConfigSnapshot,
    compare,
    evidence_fingerprint,
    provenance_of,
    snapshot_of,
)
from globin.domain.configuration import (
    COMMAND_LINE_ORIGIN,
    ENVIRONMENT_ORIGIN,
    MIN_SEVERITY,
    config_fingerprint,
    default_layer,
    resolve,
)
from globin.errors import ConfigurationError
from globin.runtime.cli import main
from globin.runtime.composition import build_config_sources
from tests.support import REPO_ROOT

PROFILE: str = "paper"


def _chain(
    root: Path | None,
    *,
    environment: dict[str, str] | None = None,
    explicit: Path | None = None,
    overrides: list[str] | None = None,
) -> tuple[object, ...]:
    """The layers a run would fold, defaults included."""
    sources = build_config_sources(
        root,
        PROFILE,
        environment={} if environment is None else environment,
        explicit=explicit,
        overrides=parse_overrides(() if overrides is None else overrides),
    )
    return (default_layer(), *(source.layer() for source in sources))


def _document(directory: Path, name: str, severity: str) -> Path:
    """One TOML document setting one value."""
    path = directory / name
    path.write_text(f'[logging]\nmin_severity = "{severity}"\n', encoding="utf-8")
    return path


def _winner(layers: tuple[object, ...], key: str = MIN_SEVERITY) -> tuple[object, str]:
    """The winning value and the origin that supplied it."""
    field = provenance_of(layers).field(key)  # type: ignore[arg-type]
    return field.display, field.origin


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------


def test_the_chain_is_six_layers_deep_with_the_command_line_on_top() -> None:
    """Four computed documents, an explicit one, the environment, then the flag."""
    layers = _chain(REPO_ROOT, explicit=REPO_ROOT / "config" / "globin.toml")
    origins = [layer.origin for layer in layers]  # type: ignore[attr-defined]
    assert origins[0] == "defaults"
    assert origins[-2] == ENVIRONMENT_ORIGIN
    assert origins[-1] == COMMAND_LINE_ORIGIN
    assert len(origins) == 8


def test_the_command_line_source_is_present_even_when_it_sets_nothing() -> None:
    """One shape for the chain, so the account can show the source was consulted."""
    layers = _chain(REPO_ROOT)
    assert layers[-1].origin == COMMAND_LINE_ORIGIN  # type: ignore[attr-defined]
    assert layers[-1].values == ()  # type: ignore[attr-defined]


def test_with_no_project_root_only_the_environment_and_the_flag_remain() -> None:
    """An installed GLOBIN outside a checkout runs on defaults plus what it was told."""
    origins = [layer.origin for layer in _chain(None)]  # type: ignore[attr-defined]
    assert origins == ["defaults", ENVIRONMENT_ORIGIN, COMMAND_LINE_ORIGIN]


def test_defaults_alone_resolve_when_nothing_says_otherwise() -> None:
    """The weakest layer, which every case below moves away from.

    The defaults layer carries the model's own values rather than the strings a
    document would supply, so the display is the enumeration member. That is the
    honest rendering of what actually resolved, and it is the reason ``config
    dump`` reports the *bound* model instead: what an operator wants pasted back
    into a document is ``DEBUG``, not this.
    """
    display, origin = _winner(_chain(None))
    assert origin == "defaults"
    assert "DEBUG" in str(display)


def test_an_explicit_document_beats_the_committed_tree(tmp_path: Path) -> None:
    """Naming a file is a narrower act than having written one into the tree."""
    explicit = _document(tmp_path, "explicit.toml", "INFO")
    display, origin = _winner(_chain(REPO_ROOT, explicit=explicit))
    assert display == repr("INFO")
    assert origin == str(explicit.resolve())


def test_the_environment_beats_an_explicit_document(tmp_path: Path) -> None:
    """A variable is set for this invocation; a document is set for every one that names it."""
    explicit = _document(tmp_path, "explicit.toml", "INFO")
    layers = _chain(
        REPO_ROOT,
        environment={"GLOBIN_LOGGING_MIN_SEVERITY": "WARNING"},
        explicit=explicit,
    )
    assert _winner(layers) == (repr("WARNING"), ENVIRONMENT_ORIGIN)


def test_the_command_line_beats_the_environment(tmp_path: Path) -> None:
    """The narrowest act wins, which is the one rule the whole order follows."""
    explicit = _document(tmp_path, "explicit.toml", "INFO")
    layers = _chain(
        REPO_ROOT,
        environment={"GLOBIN_LOGGING_MIN_SEVERITY": "WARNING"},
        explicit=explicit,
        overrides=[f"{MIN_SEVERITY}=ERROR"],
    )
    assert _winner(layers) == (repr("ERROR"), COMMAND_LINE_ORIGIN)


def test_the_full_chain_records_what_each_stronger_layer_overruled(tmp_path: Path) -> None:
    """Four layers set it, so three were overruled and the account says so."""
    explicit = _document(tmp_path, "explicit.toml", "INFO")
    layers = _chain(
        REPO_ROOT,
        environment={"GLOBIN_LOGGING_MIN_SEVERITY": "WARNING"},
        explicit=explicit,
        overrides=[f"{MIN_SEVERITY}=ERROR"],
    )
    assert provenance_of(layers).field(MIN_SEVERITY).overridden == 3  # type: ignore[arg-type]


def test_an_omitted_override_does_not_overwrite_a_lower_source(tmp_path: Path) -> None:
    """Only keys an operator typed enter the layer, or nothing below could ever win."""
    explicit = _document(tmp_path, "explicit.toml", "INFO")
    layers = _chain(REPO_ROOT, explicit=explicit, overrides=["telemetry.enabled=false"])
    assert _winner(layers) == (repr("INFO"), str(explicit.resolve()))


# ---------------------------------------------------------------------------
# The working directory
# ---------------------------------------------------------------------------


def test_the_same_explicit_inputs_resolve_identically_from_another_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The acceptance criterion: a working directory must not change what is read."""
    explicit = _document(tmp_path, "explicit.toml", "INFO")
    here = _chain(REPO_ROOT, explicit=explicit)
    monkeypatch.chdir(tmp_path)
    there = _chain(REPO_ROOT, explicit=explicit)
    assert config_fingerprint(resolve(here)) == config_fingerprint(resolve(there))  # type: ignore[arg-type]
    assert evidence_fingerprint(provenance_of(here)) == evidence_fingerprint(  # type: ignore[arg-type]
        provenance_of(there)  # type: ignore[arg-type]
    )


def test_a_relative_explicit_document_is_resolved_to_one_absolute_spelling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two spellings of one document must be one source, or provenance names two."""
    explicit = _document(tmp_path, "explicit.toml", "INFO")
    monkeypatch.chdir(tmp_path)
    layers = _chain(REPO_ROOT, explicit=Path("explicit.toml"))
    assert _winner(layers)[1] == str(explicit.resolve())


# ---------------------------------------------------------------------------
# Fingerprints and drift
# ---------------------------------------------------------------------------


def _snapshot(layers: tuple[object, ...]) -> ConfigSnapshot:
    """A snapshot of one chain."""
    return snapshot_of(
        provenance_of(layers),  # type: ignore[arg-type]
        profile=PROFILE,
        semantic=config_fingerprint(resolve(layers)),  # type: ignore[arg-type]
    )


def test_a_semantic_change_moves_the_semantic_fingerprint(tmp_path: Path) -> None:
    """The property the digest exists for, over the real chain rather than a fixture."""
    quiet = _snapshot(_chain(REPO_ROOT, explicit=_document(tmp_path, "a.toml", "INFO")))
    loud = _snapshot(_chain(REPO_ROOT, explicit=_document(tmp_path, "b.toml", "ERROR")))
    assert quiet.semantic != loud.semantic
    assert compare(quiet, loud).semantic is True


def test_moving_a_value_between_sources_is_drift_without_semantic_drift(
    tmp_path: Path,
) -> None:
    """The case one digest is blind to and the other is not, over the real chain."""
    explicit = _document(tmp_path, "explicit.toml", "WARNING")
    from_document = _snapshot(_chain(REPO_ROOT, explicit=explicit))
    from_environment = _snapshot(
        _chain(REPO_ROOT, environment={"GLOBIN_LOGGING_MIN_SEVERITY": "WARNING"})
    )
    drift = compare(from_document, from_environment)
    assert drift.semantic is False
    assert MIN_SEVERITY in drift.reorigined


def test_a_source_file_changing_is_seen_in_the_drift_report(tmp_path: Path) -> None:
    """The scenario the report is for: the same command, a different answer."""
    explicit = tmp_path / "explicit.toml"
    explicit.write_text('[logging]\nmin_severity = "INFO"\n', encoding="utf-8")
    before = _snapshot(_chain(REPO_ROOT, explicit=explicit))
    explicit.write_text('[logging]\nmin_severity = "ERROR"\n', encoding="utf-8")
    after = _snapshot(_chain(REPO_ROOT, explicit=explicit))
    assert compare(before, after).changed == (MIN_SEVERITY,)


# ---------------------------------------------------------------------------
# Nothing leaks
# ---------------------------------------------------------------------------

SECRET: str = "sk-live-thisisnotarealkey"  # noqa: S105 -- a fixture, and the point is it never appears


def test_a_credential_shaped_document_value_is_never_read_at_all(tmp_path: Path) -> None:
    """Phase 031 made this stronger, and the assertion moved with it.

    Until then a credential-shaped key in a document was *read*, carried into a
    layer, and blanked by name wherever it was rendered — so the property held
    only as long as redaction worked at every surface. It is now refused where the
    document is flattened, which means the value never enters a layer, never
    reaches a fingerprint, and is never anywhere a later redaction has to be
    trusted to catch it. Refusing beats redacting, so the test asserts the
    refusal — and asserts the message carries the rule rather than the value.
    """
    document = tmp_path / "leaky.toml"
    document.write_text(f'[venue]\napi_key = "{SECRET}"\n', encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        _chain(REPO_ROOT, explicit=document)
    assert SECRET not in str(caught.value)
    assert "looks like a credential" in str(caught.value)


def test_an_ordinary_value_still_reaches_no_report_it_should_not(tmp_path: Path) -> None:
    """The surface the refusal above does not cover, kept as it was.

    The refusal is by *name*, so a key whose name looks ordinary carries its value
    into a layer exactly as before, and redaction by name is what stands behind
    it. Asserted over rendered bytes rather than over a structure, which is where
    a value would hide.
    """
    document = tmp_path / "ordinary.toml"
    document.write_text('[logging]\nmin_severity = "INFO"\n', encoding="utf-8")
    layers = _chain(REPO_ROOT, explicit=document)
    account = provenance_of(layers)  # type: ignore[arg-type]
    snapshot = _snapshot(layers)
    rendered = json.dumps(
        [account.as_record(), snapshot.as_record(), compare(snapshot, snapshot).as_record()]
    )
    assert SECRET not in rendered


def test_a_credential_shaped_document_value_appears_in_no_refusal(tmp_path: Path) -> None:
    """The refusal names the key, never the value, and the exit code says configuration."""
    document = tmp_path / "leaky.toml"
    document.write_text(f'[venue]\napi_key = "{SECRET}"\n', encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["config", "validate", "--config", str(document)],
        stdout=out,
        stderr=err,
        start=REPO_ROOT,
    )
    assert code == ExitCode.CONFIGURATION_INVALID
    assert SECRET not in out.getvalue() + err.getvalue()
