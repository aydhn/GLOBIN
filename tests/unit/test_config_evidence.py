"""What a resolved configuration can be asked about itself.

``test_configuration.py`` owns the model — what binds, what is refused, what the
fold does. This owns the projection Phase 030 added on top: who set what, what it
digests to, and how two runs differ.

Every layer here is built by hand. Nothing reads a file, because what is under
test is the account rather than the reading.
"""

import pytest

from globin.domain.config_evidence import (
    CONFIG_SCHEMA_VERSION,
    MAXIMUM_DOCUMENT_BYTES,
    ConfigProvenance,
    ConfigSnapshot,
    check_schema_version,
    compare,
    display_of,
    document_size_problem,
    effective_values,
    evidence_fingerprint,
    field_digest,
    provenance_of,
    sensitive_keys,
    snapshot_from,
    snapshot_of,
    supported_schema_versions,
    unmeasured_drift,
)
from globin.domain.configuration import (
    COMMAND_LINE_ORIGIN,
    ENVIRONMENT_ORIGIN,
    MIN_SEVERITY,
    config_fingerprint,
    config_layer,
    default_config,
    default_layer,
    known_keys,
    resolve,
)
from globin.domain.observability import REDACTED
from globin.errors import ConfigurationError, ValidationError

DOCUMENT_ORIGIN: str = "config/profiles/paper.toml"


def _layers(*overlays: tuple[str, dict[str, object]]) -> tuple[object, ...]:
    """The defaults, then one layer per overlay."""
    return (default_layer(), *(config_layer(origin, values) for origin, values in overlays))


def _account(*overlays: tuple[str, dict[str, object]]) -> ConfigProvenance:
    """The account for a chain of overlays over the defaults."""
    return provenance_of(_layers(*overlays))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_the_account_covers_every_key_any_layer_mentioned() -> None:
    """A projection of the fold, so it describes exactly what the fold saw."""
    account = _account((DOCUMENT_ORIGIN, {MIN_SEVERITY: "INFO"}))
    assert set(account.keys()) == set(known_keys())


def test_the_winning_source_is_named() -> None:
    """The question an operator actually asks is which file set it."""
    account = _account(
        (DOCUMENT_ORIGIN, {MIN_SEVERITY: "INFO"}),
        (ENVIRONMENT_ORIGIN, {MIN_SEVERITY: "WARNING"}),
    )
    assert account.field(MIN_SEVERITY).origin == ENVIRONMENT_ORIGIN


def test_the_count_of_overruled_layers_is_carried() -> None:
    """Not recoverable from a resolved configuration, which is why layers are the input."""
    account = _account(
        (DOCUMENT_ORIGIN, {MIN_SEVERITY: "INFO"}),
        (ENVIRONMENT_ORIGIN, {MIN_SEVERITY: "WARNING"}),
        (COMMAND_LINE_ORIGIN, {MIN_SEVERITY: "ERROR"}),
    )
    field = account.field(MIN_SEVERITY)
    assert field.overridden == 3
    assert field.priority == 3


def test_a_key_only_the_defaults_set_overrules_nothing() -> None:
    """The identity case, so the count is a count rather than an off-by-one."""
    assert _account().field(MIN_SEVERITY).overridden == 0


def test_an_unregistered_key_still_has_provenance_and_is_marked() -> None:
    """Naming the document that set an unknown key is exactly what an operator needs."""
    account = _account((DOCUMENT_ORIGIN, {"logging.nope": 1}))
    assert account.unknown() == ("logging.nope",)
    assert account.field("logging.nope").origin == DOCUMENT_ORIGIN


def test_asking_about_a_key_that_resolved_to_nothing_is_the_operator_fault() -> None:
    """A mistyped key is a document to fix, not a GLOBIN defect."""
    with pytest.raises(ConfigurationError, match="nothing resolved"):
        _account().field("logging.not_a_setting")


def test_an_account_describing_one_key_twice_cannot_be_constructed() -> None:
    """The invariant the projection rests on, asserted where it is declared."""
    fields = _account().fields
    with pytest.raises(ValidationError, match="more than once"):
        ConfigProvenance(fields=(fields[0], fields[0]))


def test_the_account_records_every_layer_including_the_empty_ones() -> None:
    """A source that said nothing was still consulted, and the report says so."""
    account = _account((DOCUMENT_ORIGIN, {}), (COMMAND_LINE_ORIGIN, {}))
    assert [layer.origin for layer in account.layers][-2:] == [
        DOCUMENT_ORIGIN,
        COMMAND_LINE_ORIGIN,
    ]
    assert account.layers[-1].count == 0


# ---------------------------------------------------------------------------
# Digests and displays
# ---------------------------------------------------------------------------


def test_a_display_is_redacted_by_key_name() -> None:
    """One redactor, so a dump and a log record cannot hide different things."""
    assert display_of("venue.api_key", "sk-live-1234") == repr(REDACTED)


def test_an_ordinary_display_is_the_value() -> None:
    """Over-redaction would make the dump useless; the rule is the field name."""
    assert display_of(MIN_SEVERITY, "INFO") == repr("INFO")


def test_a_digest_distinguishes_a_string_from_a_number() -> None:
    """``str`` renders both identically, which is the hardest change to notice."""
    assert field_digest("a.b", "1") != field_digest("a.b", 1)


def test_the_same_value_under_two_keys_digests_differently() -> None:
    """The key is folded in, so a drift report cannot confuse two settings."""
    assert field_digest("a.b", True) != field_digest("c.d", True)


def test_a_digest_is_stable_across_calls() -> None:
    """A comparison that moved on its own would report drift that nobody caused."""
    assert field_digest("a.b", 7) == field_digest("a.b", 7)


def test_a_credential_shaped_key_is_reported_so_the_refusal_can_say_why() -> None:
    """Being told the rule beats being told the key is merely unknown."""
    account = _account((DOCUMENT_ORIGIN, {"venue.api_key": "x"}))
    assert sensitive_keys(account) == ("venue.api_key",)


def test_no_committed_setting_is_credential_shaped() -> None:
    """The register is clean today, and this fails the day something is added."""
    assert sensitive_keys(_account()) == ()


# ---------------------------------------------------------------------------
# The two fingerprints
# ---------------------------------------------------------------------------


def test_the_evidence_fingerprint_moves_when_only_the_source_moves() -> None:
    """The question the semantic digest deliberately cannot answer."""
    from_document = _account((DOCUMENT_ORIGIN, {MIN_SEVERITY: "INFO"}))
    from_environment = _account((ENVIRONMENT_ORIGIN, {MIN_SEVERITY: "INFO"}))
    assert evidence_fingerprint(from_document) != evidence_fingerprint(from_environment)


def test_the_semantic_fingerprint_does_not() -> None:
    """The counterpart property, asserted on the same pair so the split is visible."""
    document = config_fingerprint(resolve(_layers((DOCUMENT_ORIGIN, {MIN_SEVERITY: "INFO"}))))  # type: ignore[arg-type]
    environment = config_fingerprint(
        resolve(_layers((ENVIRONMENT_ORIGIN, {MIN_SEVERITY: "INFO"})))  # type: ignore[arg-type]
    )
    assert document == environment


def test_the_evidence_fingerprint_carries_no_value() -> None:
    """It travels wherever the semantic one may, which requires it to disclose nothing."""
    account = _account((DOCUMENT_ORIGIN, {MIN_SEVERITY: "INFO"}))
    assert "INFO" not in evidence_fingerprint(account)


def test_the_evidence_fingerprint_is_stable() -> None:
    """A digest that moved on its own would train people to ignore it."""
    account = _account((DOCUMENT_ORIGIN, {MIN_SEVERITY: "INFO"}))
    assert evidence_fingerprint(account) == evidence_fingerprint(account)


# ---------------------------------------------------------------------------
# Snapshots and drift
# ---------------------------------------------------------------------------


def _snapshot(*overlays: tuple[str, dict[str, object]], profile: str = "paper") -> ConfigSnapshot:
    """A snapshot of one chain, with its semantic fingerprint computed over the same fold."""
    layers = _layers(*overlays)
    return snapshot_of(
        provenance_of(layers),  # type: ignore[arg-type]
        profile=profile,
        semantic=config_fingerprint(resolve(layers)),  # type: ignore[arg-type]
    )


def test_no_baseline_is_unmeasured_rather_than_clean() -> None:
    """A first run has established nothing, which is not the same as nothing having moved."""
    drift = compare(None, _snapshot())
    assert drift.measured is False
    assert drift.moved is False


def test_the_unmeasured_verdict_says_so_in_its_record() -> None:
    """A reader of the manifest must be able to tell the two apart too."""
    assert unmeasured_drift().as_record()["measured"] is False


def test_an_unchanged_configuration_reports_nothing() -> None:
    """The identity case; without it, every other assertion here proves little."""
    drift = compare(_snapshot(), _snapshot())
    assert not drift.moved
    assert drift.semantic is False


def test_a_changed_value_is_reported_as_changed() -> None:
    """The comparison reads digests, so it works on fields a display would hide."""
    before = _snapshot((DOCUMENT_ORIGIN, {MIN_SEVERITY: "INFO"}))
    after = _snapshot((DOCUMENT_ORIGIN, {MIN_SEVERITY: "WARNING"}))
    drift = compare(before, after)
    assert drift.changed == (MIN_SEVERITY,)
    assert drift.semantic is True


def test_a_value_that_began_arriving_from_elsewhere_is_reported_without_semantic_drift() -> None:
    """The case the semantic fingerprint is deliberately blind to."""
    before = _snapshot((DOCUMENT_ORIGIN, {MIN_SEVERITY: "INFO"}))
    after = _snapshot((ENVIRONMENT_ORIGIN, {MIN_SEVERITY: "INFO"}))
    drift = compare(before, after)
    assert drift.reorigined == (MIN_SEVERITY,)
    assert drift.changed == ()
    assert drift.semantic is False


def test_an_added_key_is_reported() -> None:
    """An unknown key appearing is a change worth seeing before it is refused."""
    drift = compare(_snapshot(), _snapshot((DOCUMENT_ORIGIN, {"logging.nope": 1})))
    assert drift.added == ("logging.nope",)


def test_a_removed_key_is_reported() -> None:
    """The mirror, so the comparison is not one-directional."""
    drift = compare(_snapshot((DOCUMENT_ORIGIN, {"logging.nope": 1})), _snapshot())
    assert drift.removed == ("logging.nope",)


def test_a_credential_shaped_key_is_compared_without_its_value_appearing() -> None:
    """Redaction protects the display; the digest is what makes the comparison work."""
    before = _snapshot((DOCUMENT_ORIGIN, {"venue.api_key": "sk-live-aaaa"}))
    after = _snapshot((DOCUMENT_ORIGIN, {"venue.api_key": "sk-live-bbbb"}))
    drift = compare(before, after)
    assert drift.changed == ("venue.api_key",)
    assert "sk-live" not in repr(drift.as_record())


def test_a_drift_record_carries_no_value_for_any_key() -> None:
    """The document most likely to be pasted somewhere else carries the least."""
    record = compare(_snapshot(), _snapshot((DOCUMENT_ORIGIN, {MIN_SEVERITY: "WARNING"})))
    assert "WARNING" not in repr(record.as_record())


def test_a_published_snapshot_reads_back_as_the_same_comparison() -> None:
    """The baseline survives a round trip, which is the only way drift works at all."""
    snapshot = _snapshot((DOCUMENT_ORIGIN, {MIN_SEVERITY: "INFO"}))
    restored = snapshot_from(snapshot.as_record())
    assert not compare(restored, snapshot).moved


def test_a_snapshot_record_carries_no_display() -> None:
    """The least it can hold while still answering "did this change" is what it holds."""
    record = _snapshot((DOCUMENT_ORIGIN, {MIN_SEVERITY: "INFO"})).as_record()
    assert "INFO" not in repr(record)


# ---------------------------------------------------------------------------
# The schema version
# ---------------------------------------------------------------------------


def test_the_declared_version_is_supported() -> None:
    """A contract nobody can read would be a contract nobody can write against."""
    assert CONFIG_SCHEMA_VERSION in supported_schema_versions()


def test_a_supported_version_is_accepted() -> None:
    """The positive case first, so the refusals below are not vacuous."""
    assert check_schema_version(CONFIG_SCHEMA_VERSION, "somewhere") == CONFIG_SCHEMA_VERSION


@pytest.mark.parametrize(
    "declared",
    [
        pytest.param(CONFIG_SCHEMA_VERSION + 1, id="from-the-future"),
        pytest.param(0, id="from-before-there-was-one"),
        pytest.param("1", id="a-string-that-looks-right"),
        pytest.param(1.0, id="a-float-that-looks-right"),
        pytest.param(True, id="a-boolean-python-would-call-one"),
        pytest.param(None, id="nothing"),
    ],
)
def test_an_unsupported_contract_version_fails_closed(declared: object) -> None:
    """Neither direction is silently upgraded; there is no migration engine to do it."""
    with pytest.raises(ConfigurationError, match="config_schema_version"):
        check_schema_version(declared, "somewhere")


# ---------------------------------------------------------------------------
# Bounds and effective values
# ---------------------------------------------------------------------------


def test_a_document_within_the_ceiling_has_no_problem() -> None:
    """The positive case, so the refusal below means something."""
    assert document_size_problem(MAXIMUM_DOCUMENT_BYTES, "somewhere") == ""


def test_an_oversized_document_is_refused_with_a_reason_an_operator_can_act_on() -> None:
    """A parse error on byte four million is not a diagnosis."""
    problem = document_size_problem(MAXIMUM_DOCUMENT_BYTES + 1, "somewhere")
    assert "ceiling" in problem


def test_effective_values_cover_every_registered_setting() -> None:
    """A dump missing a setting would be a dump nobody could rely on."""
    assert set(effective_values(default_config())) == set(known_keys())


def test_an_enumeration_is_rendered_as_the_name_a_document_accepts() -> None:
    """A dumped value must be pasteable back into a document unchanged."""
    assert effective_values(default_config())[MIN_SEVERITY] == "DEBUG"
