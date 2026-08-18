"""The degradation posture as a classification, and the contract that feeds it.

No host, no clock and no platform: every one of the fifteen combinations of three
necessities and five statuses is constructible from literals, which is what
carries the branch floor without a machine that actually lacks anything.

**The opportunistic branch is the test that matters.** Phase 030's inherited rule
is that a capability the registry *predicted* absent must not make a host amber —
the CI quality job installs neither psutil nor either telemetry library on any
run, so under the obvious rule this posture would be amber for ever. A signal that
is always amber is a signal nobody reads, and that is what these assertions
protect.
"""

from pathlib import Path

import pytest

from globin.adapters.degradation import (
    ContractDegradationProbe,
    read_contract,
    system_arms,
)
from globin.domain.bootstrap import CheckStatus
from globin.domain.degradation import (
    DEGRADATION_CHECK,
    MAX_DETAIL_LENGTH,
    MAX_WITHDRAWN,
    ComponentKind,
    ComponentNecessity,
    ComponentObservation,
    ComponentSpec,
    DegradationReport,
    blocks,
    degradation_outcome,
    degrades,
)
from globin.domain.environment import (
    CapabilityReason,
    CapabilityStatus,
    EnvironmentCompatibility,
)
from globin.errors import ValidationError

IDENTIFIER = "component.library.example"


def spec(
    necessity: ComponentNecessity = ComponentNecessity.OPTIONAL,
    identifier: str = IDENTIFIER,
) -> ComponentSpec:
    """A declaration with the withdraws invariant satisfied.

    Args:
        necessity: Which tier.
        identifier: Which component.

    Returns:
        The declaration.
    """
    withdraws = () if necessity is ComponentNecessity.OPPORTUNISTIC else ("example.capability",)
    return ComponentSpec(
        identifier=identifier,
        kind=ComponentKind.LIBRARY,
        necessity=necessity,
        withdraws=withdraws,
    )


def observed(status: CapabilityStatus, identifier: str = IDENTIFIER) -> ComponentObservation:
    """An observation of one component.

    Args:
        status: What was found.
        identifier: Which component.

    Returns:
        The observation.
    """
    return ComponentObservation(identifier=identifier, status=status)


# ---------------------------------------------------------------------------
# The declaration's own invariants
# ---------------------------------------------------------------------------


def test_an_unprefixed_identifier_is_refused() -> None:
    """A component and a check must not be confusable wherever they are published."""
    with pytest.raises(ValidationError, match="does not begin with"):
        ComponentSpec(
            identifier="library.example",
            kind=ComponentKind.LIBRARY,
            necessity=ComponentNecessity.OPPORTUNISTIC,
        )


def test_an_identifier_that_is_only_its_prefix_is_refused() -> None:
    """A prefix names no component."""
    with pytest.raises(ValidationError, match="more than its prefix"):
        ComponentSpec(
            identifier="component.",
            kind=ComponentKind.LIBRARY,
            necessity=ComponentNecessity.OPPORTUNISTIC,
        )


def test_an_opportunistic_component_may_not_withdraw_anything() -> None:
    """An absence that changes nothing withdraws nothing.

    A row claiming both would be contradicting its own tier, and the contradiction
    would surface as a posture that stayed ready while naming a lost capability.
    """
    with pytest.raises(ValidationError, match="withdraws nothing"):
        ComponentSpec(
            identifier=IDENTIFIER,
            kind=ComponentKind.LIBRARY,
            necessity=ComponentNecessity.OPPORTUNISTIC,
            withdraws=("something",),
        )


@pytest.mark.parametrize(
    "necessity",
    [ComponentNecessity.REQUIRED, ComponentNecessity.OPTIONAL],
)
def test_a_blocking_or_amber_component_must_say_what_is_lost(
    necessity: ComponentNecessity,
) -> None:
    """A refusal or an amber nobody can act on is not worth raising."""
    with pytest.raises(ValidationError, match="names nothing it withdraws"):
        ComponentSpec(identifier=IDENTIFIER, kind=ComponentKind.LIBRARY, necessity=necessity)


def test_too_many_withdrawn_capabilities_are_refused() -> None:
    """An unbounded list is a document whose size nobody is watching."""
    with pytest.raises(ValidationError, match="at most"):
        ComponentSpec(
            identifier=IDENTIFIER,
            kind=ComponentKind.LIBRARY,
            necessity=ComponentNecessity.OPTIONAL,
            withdraws=tuple(f"c{index}" for index in range(MAX_WITHDRAWN + 1)),
        )


def test_an_observation_carrying_more_than_a_phrase_is_refused() -> None:
    """A bound is what stops a platform message being pasted in whole.

    That is how a path or a user name reaches a published record.
    """
    with pytest.raises(ValidationError, match="at most"):
        ComponentObservation(
            identifier=IDENTIFIER,
            status=CapabilityStatus.SUPPORTED,
            detail="x" * (MAX_DETAIL_LENGTH + 1),
        )


# ---------------------------------------------------------------------------
# The fold, over every combination
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("necessity", "status", "expected"),
    [
        pytest.param(
            ComponentNecessity.REQUIRED,
            CapabilityStatus.UNSUPPORTED,
            True,
            id="required-and-measured-absent",
        ),
        pytest.param(
            ComponentNecessity.REQUIRED,
            CapabilityStatus.UNKNOWN,
            False,
            id="required-but-unmeasured",
        ),
        pytest.param(
            ComponentNecessity.REQUIRED,
            CapabilityStatus.NOT_APPLICABLE,
            False,
            id="required-but-the-question-does-not-arise",
        ),
        pytest.param(
            ComponentNecessity.OPTIONAL,
            CapabilityStatus.UNSUPPORTED,
            False,
            id="optional-and-absent",
        ),
    ],
)
def test_only_a_measured_required_absence_blocks(
    necessity: ComponentNecessity, status: CapabilityStatus, expected: bool
) -> None:
    """An unmeasured component has not been shown to be absent.

    That is ADR-0045's rule, and the reason a host that cannot answer a question
    is still allowed to run.
    """
    assert blocks(spec(necessity), observed(status)) is expected


@pytest.mark.parametrize(
    "status",
    [CapabilityStatus.UNSUPPORTED, CapabilityStatus.UNKNOWN, CapabilityStatus.DEGRADED],
)
def test_an_opportunistic_absence_never_makes_a_host_amber(
    status: CapabilityStatus,
) -> None:
    """Phase 030's inherited rule, and the whole reason the third tier exists.

    The CI quality job installs neither psutil nor either telemetry library on any
    run. Under the rule `CapabilityCheck.degrading` uses, this posture would be
    amber for ever — and a signal that is always amber is a signal nobody reads.
    """
    assert degrades(spec(ComponentNecessity.OPPORTUNISTIC), observed(status)) is False


@pytest.mark.parametrize(
    "status",
    [CapabilityStatus.UNSUPPORTED, CapabilityStatus.UNKNOWN, CapabilityStatus.DEGRADED],
)
def test_an_optional_component_degrades_on_every_unhappy_status(
    status: CapabilityStatus,
) -> None:
    """Absent, worse than intended and unmeasured are all worth an amber here."""
    assert degrades(spec(ComponentNecessity.OPTIONAL), observed(status)) is True


def test_a_question_that_does_not_arise_never_degrades() -> None:
    """What carries the network and the device.

    `NOT_APPLICABLE` is the question not arising, which is a different thing from
    an answer nobody could get — and only the second is worth reporting.
    """
    for necessity in ComponentNecessity:
        found = observed(CapabilityStatus.NOT_APPLICABLE)
        assert degrades(spec(necessity), found) is False


def test_a_present_component_neither_blocks_nor_degrades() -> None:
    """The happy case, so the rules above are not vacuously true."""
    found = observed(CapabilityStatus.SUPPORTED)
    assert blocks(spec(ComponentNecessity.REQUIRED), found) is False
    assert degrades(spec(ComponentNecessity.OPTIONAL), found) is False


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def report(*pairs: tuple[ComponentSpec, ComponentObservation]) -> DegradationReport:
    """A report over the given pairs.

    Args:
        pairs: Declaration and observation, in order.

    Returns:
        The report.
    """
    return DegradationReport(
        components=tuple(item for item, _ in pairs),
        observations=tuple(found for _, found in pairs),
    )


def test_a_declared_component_that_was_not_observed_is_refused() -> None:
    """A survey that skipped one would report a posture nobody could account for."""
    with pytest.raises(ValidationError, match="declared but not observed"):
        DegradationReport(components=(spec(),), observations=())


def test_an_observation_of_something_undeclared_is_refused() -> None:
    """A report describes the registry it was built from."""
    with pytest.raises(ValidationError, match="observed but not declared"):
        DegradationReport(components=(), observations=(observed(CapabilityStatus.SUPPORTED),))


def test_a_component_observed_twice_is_refused() -> None:
    """Its posture would otherwise depend on the order of a list."""
    with pytest.raises(ValidationError, match="observed twice"):
        DegradationReport(
            components=(spec(),),
            observations=(
                observed(CapabilityStatus.SUPPORTED),
                observed(CapabilityStatus.UNSUPPORTED),
            ),
        )


def test_a_component_declared_twice_is_refused() -> None:
    """An identifier addresses one component."""
    with pytest.raises(ValidationError, match="declared twice"):
        DegradationReport(
            components=(spec(), spec()),
            observations=(observed(CapabilityStatus.SUPPORTED),),
        )


def test_a_ready_posture_names_nothing_lost() -> None:
    """Everything present is the state the check exists to confirm."""
    built = report((spec(), observed(CapabilityStatus.SUPPORTED)))
    assert built.posture() is EnvironmentCompatibility.READY
    assert built.withdrawn() == ()
    assert built.blocking() == ()


def test_a_degraded_posture_names_what_stopped_working() -> None:
    """The phase's headline sentence as data.

    "GLOBIN started, and these named capabilities are not available" is what
    ADR-0076 means by reporting a partial capability.
    """
    built = report((spec(), observed(CapabilityStatus.UNSUPPORTED)))
    assert built.posture() is EnvironmentCompatibility.DEGRADED
    assert built.withdrawn() == ("example.capability",)


def test_a_blocked_posture_wins_over_a_degraded_one() -> None:
    """A process that must refuse is not usefully called merely worse than intended."""
    built = report(
        (spec(ComponentNecessity.REQUIRED), observed(CapabilityStatus.UNSUPPORTED)),
        (
            spec(ComponentNecessity.OPTIONAL, "component.library.other"),
            observed(CapabilityStatus.DEGRADED, "component.library.other"),
        ),
    )
    assert built.posture() is EnvironmentCompatibility.BLOCKED
    assert built.blocking() == (IDENTIFIER,)


def test_a_forgiven_absence_still_appears_in_the_document() -> None:
    """Forgiving an absence in the verdict must never mean hiding it.

    Mirrors `RuntimeHealthSnapshot.unmeasurable` deliberately: the posture stays
    ready and the record still says what could not be measured.
    """
    built = report((spec(ComponentNecessity.OPPORTUNISTIC), observed(CapabilityStatus.UNKNOWN)))
    assert built.posture() is EnvironmentCompatibility.READY
    assert built.unmeasured() == (IDENTIFIER,)


def test_the_posture_does_not_depend_on_the_order_of_observations() -> None:
    """A report is a set of answers, not a sequence."""
    first = spec(ComponentNecessity.OPTIONAL, "component.library.a")
    second = spec(ComponentNecessity.OPTIONAL, "component.library.b")
    forwards = DegradationReport(
        components=(first, second),
        observations=(
            observed(CapabilityStatus.SUPPORTED, "component.library.a"),
            observed(CapabilityStatus.UNSUPPORTED, "component.library.b"),
        ),
    )
    backwards = DegradationReport(
        components=(first, second),
        observations=(
            observed(CapabilityStatus.UNSUPPORTED, "component.library.b"),
            observed(CapabilityStatus.SUPPORTED, "component.library.a"),
        ),
    )
    assert forwards.posture() is backwards.posture()
    assert forwards.as_record() == backwards.as_record()


def test_the_record_carries_the_declaration_beside_the_observation() -> None:
    """An operator reading it should not have to open the contract too."""
    built = report((spec(), observed(CapabilityStatus.SUPPORTED)))
    document = built.as_record()
    components = document["components"]
    assert isinstance(components, list)
    assert components[0]["necessity"] == "optional"
    assert components[0]["status"] == "supported"


# ---------------------------------------------------------------------------
# The judgement
# ---------------------------------------------------------------------------


def test_an_unreadable_contract_is_unmeasured_rather_than_passing() -> None:
    """The only route to unmeasured here, and it is about the declaration."""
    outcome = degradation_outcome(None)
    assert outcome.identifier == DEGRADATION_CHECK
    assert outcome.status is CheckStatus.UNMEASURED


def test_a_degraded_posture_warns_rather_than_fails() -> None:
    """Starting worse than intended is not a refusal.

    The same collapse `capability_outcome` performs, and the exit-code decision
    ignores a warning.
    """
    built = report((spec(), observed(CapabilityStatus.UNSUPPORTED)))
    assert degradation_outcome(built).status is CheckStatus.WARN


def test_a_blocked_posture_fails_and_names_the_component() -> None:
    """An operator has to know which thing to install."""
    built = report((spec(ComponentNecessity.REQUIRED), observed(CapabilityStatus.UNSUPPORTED)))
    outcome = degradation_outcome(built)
    assert outcome.status is CheckStatus.FAIL
    assert IDENTIFIER in outcome.summary


def test_a_ready_posture_passes() -> None:
    """The state this host is in, and the reason the check is not noise."""
    built = report((spec(), observed(CapabilityStatus.SUPPORTED)))
    assert degradation_outcome(built).status is CheckStatus.PASS


# ---------------------------------------------------------------------------
# The contract reader
# ---------------------------------------------------------------------------


def test_the_committed_contract_parses_and_declares_every_component() -> None:
    """The document this repository ships, read the way a run reads it."""
    specs = read_contract(Path("docs/engineering/degradation-contract.toml"))
    assert specs is not None
    assert len(specs) >= 6
    assert all(item.identifier.startswith("component.") for item in specs)


def test_an_absent_contract_is_unmeasured_rather_than_a_crash(tmp_path: Path) -> None:
    """A host with no file is a different thing from a defect in a committed one."""
    assert read_contract(tmp_path / "missing.toml") is None


def test_a_malformed_contract_is_unmeasured(tmp_path: Path) -> None:
    """Unparseable is the same class of answer as absent."""
    target = tmp_path / "broken.toml"
    target.write_text("this is not [ valid toml", encoding="utf-8")
    assert read_contract(target) is None


def test_a_later_schema_is_refused_rather_than_read_anyway(tmp_path: Path) -> None:
    """Fails closed in both directions, like every other schema here."""
    target = tmp_path / "future.toml"
    target.write_text("schema = 99\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="refused rather than read anyway"):
        read_contract(target)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param('kind = "invented"\nnecessity = "optional"', "unknown kind", id="kind"),
        pytest.param(
            'kind = "library"\nnecessity = "invented"', "unknown necessity", id="necessity"
        ),
    ],
)
def test_a_row_outside_its_enumeration_is_refused(tmp_path: Path, body: str, expected: str) -> None:
    """A defect in a committed file, which is not a property of the host."""
    target = tmp_path / "bad.toml"
    target.write_text(
        f'schema = 1\n[[component]]\nid = "component.x.y"\n{body}\n', encoding="utf-8"
    )
    with pytest.raises(ValidationError, match=expected):
        read_contract(target)


def test_a_component_nothing_reaches_is_not_applicable(tmp_path: Path) -> None:
    """GLOBIN has no caller for it, so there is nothing that could have failed."""
    target = tmp_path / "unreached.toml"
    target.write_text(
        'schema = 1\n[[component]]\nid = "component.network.egress"\n'
        'kind = "network"\nnecessity = "opportunistic"\n',
        encoding="utf-8",
    )
    probe = ContractDegradationProbe(contract=target, arms={})
    built = probe.survey()
    assert built is not None
    assert built.posture() is EnvironmentCompatibility.READY
    assert built.observations[0].status is CapabilityStatus.NOT_APPLICABLE


def test_a_component_with_no_wired_factory_is_unknown(tmp_path: Path) -> None:
    """Naming a factory nothing supplies is a wiring defect, and says so."""
    target = tmp_path / "unwired.toml"
    target.write_text(
        'schema = 1\n[[component]]\nid = "component.library.x"\n'
        'kind = "library"\nnecessity = "optional"\nwithdraws = ["a"]\n'
        'reached_through = "globin.adapters.nothing.at_all"\n',
        encoding="utf-8",
    )
    probe = ContractDegradationProbe(contract=target, arms={})
    built = probe.survey()
    assert built is not None
    assert built.observations[0].status is CapabilityStatus.UNKNOWN
    assert built.observations[0].reason is CapabilityReason.PROBE_UNAVAILABLE


def test_an_unreadable_contract_surveys_nothing(tmp_path: Path) -> None:
    """The probe reports the absence rather than inventing an empty registry."""
    probe = ContractDegradationProbe(contract=tmp_path / "gone.toml", arms={})
    assert probe.survey() is None


def test_every_real_arm_answers_on_this_host() -> None:
    """The six factories, called for real, each producing one observation.

    Absent-safe by construction, so this passes on a host with none of them —
    which is the CI quality job, and the reason the survey can be part of a
    start-up rather than a Windows-only extra.
    """
    arms = system_arms()
    for identifier, arm in arms.items():
        found = arm()
        assert found.identifier.startswith("component."), identifier
        assert isinstance(found.status, CapabilityStatus)


def test_the_survey_of_the_committed_contract_covers_every_row() -> None:
    """The end-to-end shape: the real contract, the real factories, one report."""
    probe = ContractDegradationProbe(
        contract=Path("docs/engineering/degradation-contract.toml"), arms=system_arms()
    )
    built = probe.survey()
    assert built is not None
    assert len(built.observations) == len(built.components)


# ---------------------------------------------------------------------------
# The malformed-contract paths, and the arms' absent branches
# ---------------------------------------------------------------------------


def test_too_many_components_are_refused() -> None:
    """A malformed contract must not produce an unbounded document."""
    many = tuple(spec(identifier=f"component.library.n{index}") for index in range(40))
    found = tuple(
        observed(CapabilityStatus.SUPPORTED, f"component.library.n{index}") for index in range(40)
    )
    with pytest.raises(ValidationError, match="at most"):
        DegradationReport(components=many, observations=found)


def test_component_entries_that_are_not_a_list_are_refused(tmp_path: Path) -> None:
    """A table where a list belongs is a defect in a committed file."""
    target = tmp_path / "bad.toml"
    target.write_text('schema = 1\n[component]\nid = "x"\n', encoding="utf-8")
    with pytest.raises(ValidationError, match="not a list"):
        read_contract(target)


def test_a_withdraws_field_that_is_not_a_list_is_refused(tmp_path: Path) -> None:
    """The invariant that makes an amber actionable needs a list to read."""
    target = tmp_path / "bad.toml"
    target.write_text(
        'schema = 1\n[[component]]\nid = "component.x.y"\nkind = "library"\n'
        'necessity = "optional"\nwithdraws = "a"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="withdraws is not a list"):
        read_contract(target)


@pytest.mark.parametrize(
    ("path", "factory", "stand_in"),
    [
        pytest.param(
            "globin.adapters.health.system_process_probe",
            "globin.adapters.health.system_process_probe",
            "globin.adapters.health.UnavailableProcessProbe",
            id="psutil",
        ),
        pytest.param(
            "globin.adapters.telemetry_otel.opentelemetry_bridge",
            "globin.adapters.telemetry_otel.opentelemetry_bridge",
            "globin.adapters.telemetry_otel.UnavailableOpenTelemetry",
            id="opentelemetry",
        ),
        pytest.param(
            "globin.adapters.telemetry_prometheus.prometheus_publisher",
            "globin.adapters.telemetry_prometheus.prometheus_publisher",
            "globin.adapters.telemetry_prometheus.UnavailablePrometheus",
            id="prometheus",
        ),
        pytest.param(
            "globin.adapters.environment.windows_system_api",
            "globin.adapters.environment.windows_system_api",
            "globin.adapters.environment.UnavailableSystemApi",
            id="kernel32",
        ),
        pytest.param(
            "globin.adapters.secret_vault.secret_vault",
            "globin.adapters.secret_vault.secret_vault",
            "globin.adapters.secret_vault.UnavailableSecretVault",
            id="crypt32",
        ),
    ],
)
def test_an_absent_component_is_reported_absent(
    monkeypatch: pytest.MonkeyPatch, path: str, factory: str, stand_in: str
) -> None:
    """The branch a host that has everything never reaches.

    Each factory is replaced with one returning its own stand-in, which is the
    honest way to reach a branch whose whole subject is a machine unlike this one.
    """
    module_path, _, name = stand_in.rpartition(".")
    module = __import__(module_path, fromlist=[name])
    absent_class = getattr(module, name)
    monkeypatch.setattr(factory, lambda *_a, **_k: absent_class())
    observation = system_arms()[path]()
    assert observation.status is CapabilityStatus.UNSUPPORTED


def test_kernel32_without_the_modern_export_is_degraded_rather_than_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real distinction nothing reported before Phase 031.

    ADR-0075 records that a Windows release predating `IsWow64Process2` still
    loads `kernel32` — it just cannot answer the native-architecture question. A
    boolean would have called that absent.
    """
    from globin.adapters.environment import WindowsArchitectureApi

    monkeypatch.setattr(
        "globin.adapters.environment.windows_system_api",
        lambda: WindowsArchitectureApi(library=object(), has_wow64_process2=False),
    )
    observation = system_arms()["globin.adapters.environment.windows_system_api"]()
    assert observation.status is CapabilityStatus.DEGRADED
    assert "IsWow64Process2" in observation.detail


def test_advapi32_is_not_applicable_while_nothing_needs_a_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What keeps the required tier honest today.

    Declared REQUIRED, and observed as a question that does not arise while
    `required_references()` is empty — so the tier is producible from literals
    without refusing a start for a capability no caller uses.
    """
    from globin.adapters.secrets import UnavailableSecretStore

    monkeypatch.setattr(
        "globin.adapters.secrets.windows_credential_store",
        lambda **_k: UnavailableSecretStore(),
    )
    path = "globin.adapters.secrets.windows_credential_store"
    assert system_arms()[path]().status is CapabilityStatus.NOT_APPLICABLE


def test_advapi32_becomes_a_refusal_once_a_credential_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The moment Phase 038 registers a reference, the same declaration refuses.

    Nothing has to remember to flip a flag: the survey derives it from the
    registry.
    """
    from globin.adapters.secrets import UnavailableSecretStore

    monkeypatch.setattr(
        "globin.adapters.secrets.windows_credential_store",
        lambda **_k: UnavailableSecretStore(),
    )
    path = "globin.adapters.secrets.windows_credential_store"
    arms = system_arms(credentials_required=True)
    assert arms[path]().status is CapabilityStatus.UNSUPPORTED


def test_a_component_entry_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    """TOML permits an array of anything; a component is a table."""
    target = tmp_path / "bad.toml"
    target.write_text('schema = 1\ncomponent = ["not a table"]\n', encoding="utf-8")
    with pytest.raises(ValidationError, match="entry is a table"):
        read_contract(target)
