"""The pipeline: what runs, in what order, and where a run stops.

Every probe here is a hand-written double satisfying a ``Protocol``, which is
what ``docs/TESTING_STRATEGY.md`` makes the default. That is why this file can
prove a wrong interpreter is refused, a missing project is refused, and nothing
downstream is reached in either case, without owning a wrong interpreter or
deleting a project.
"""

from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, replace

import pytest

from globin.application.bootstrap import UNMEASURED_REMEDIATION, BootstrapPipeline, steps
from globin.domain.bootstrap import (
    AGGREGATE_CHECK,
    CheckStatus,
    DependencyReadiness,
    EntitlementReadiness,
    ExitCode,
    HostFacts,
    InterpreterFacts,
    ProjectIdentity,
    RecordedPath,
    RuntimeBaseline,
    RuntimePaths,
    SecretReadiness,
    check_identifiers,
    recorded_absent,
    recorded_inside,
    recorded_outside,
)
from globin.domain.configuration import ConfigLayer, config_layer
from globin.domain.environment import (
    ArchitectureCapability,
    CapabilityCategory,
    CapabilityCheck,
    CapabilityReason,
    CapabilitySeverity,
    CapabilityStatus,
    EmulationState,
    EnvironmentCapabilitySnapshot,
    MachineArchitecture,
)
from globin.domain.identifiers import RunId
from globin.domain.runtime_state import (
    RuntimeArea,
    RuntimeLayout,
    RuntimePersistenceError,
)
from globin.errors import ConfigurationError

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


BASELINE = RuntimeBaseline(
    system="Windows",
    minimum_release="10",
    implementation="CPython",
    minor_line="3.14",
    minimum_patch="3.14.5",
    architecture="AMD64",
    pointer_bits=64,
    free_threaded=False,
    allow_prerelease=False,
    environment_directory=".venv",
)

HOST = HostFacts(system="Windows", release="11", machine="AMD64", pointer_bits=64)

INTERPRETER = InterpreterFacts(
    implementation="cpython",
    version="3.14.5",
    release_level="final",
    free_threaded=False,
    executable=recorded_inside(".venv/Scripts/python.exe"),
    prefix=recorded_inside(".venv"),
    base_prefix=recorded_outside("C:/Python314"),
    in_virtual_environment=True,
)

IDENTITY = ProjectIdentity(name="globin", version="0.1.0", source="metadata")

ROOT_HERE = recorded_inside(".")
NO_DEPENDENCIES = DependencyReadiness()
NO_SECRETS = SecretReadiness()


@dataclass(frozen=True, slots=True)
class _Baseline:
    """Supplies a baseline, or refuses to."""

    value: RuntimeBaseline | None = BASELINE

    def baseline(self) -> RuntimeBaseline:
        if self.value is None:
            msg = "the runtime contract could not be read"
            raise ConfigurationError(msg)
        return self.value


@dataclass(frozen=True, slots=True)
class _Host:
    """Supplies host and interpreter facts, and counts how often it is asked."""

    host_facts: HostFacts = HOST
    interpreter_facts: InterpreterFacts = INTERPRETER

    def host(self) -> HostFacts:
        return self.host_facts

    def interpreter(self) -> InterpreterFacts:
        return self.interpreter_facts


@dataclass(frozen=True, slots=True)
class _Project:
    """Supplies the project's location and identity."""

    location: RecordedPath = ROOT_HERE
    who: ProjectIdentity | None = IDENTITY

    def root(self) -> RecordedPath:
        return self.location

    def origin(self) -> str:
        return "from the working directory"

    def identity(self) -> ProjectIdentity | None:
        return self.who


@dataclass(frozen=True, slots=True)
class _Dependencies:
    """Supplies dependency readiness."""

    value: DependencyReadiness = NO_DEPENDENCIES

    def readiness(self) -> DependencyReadiness:
        return self.value


@dataclass(frozen=True, slots=True)
class _Secrets:
    """Supplies secret readiness."""

    value: SecretReadiness = NO_SECRETS

    def readiness(self) -> SecretReadiness:
        return self.value


@dataclass(frozen=True, slots=True)
class _Environment:
    """Supplies a capability snapshot, defaulting to a host with nothing wrong.

    The default is a single supported required check rather than an empty
    snapshot. An empty one is also `READY` — `compatibility_of` says so — but it
    would be READY *vacuously*, and a fixture whose healthiness comes from having
    measured nothing cannot distinguish a passing check from a missing one.
    """

    snapshot_value: EnvironmentCapabilitySnapshot | None = None

    def snapshot(self, baseline: RuntimeBaseline) -> EnvironmentCapabilitySnapshot:
        del baseline
        if self.snapshot_value is not None:
            return self.snapshot_value
        return EnvironmentCapabilitySnapshot(
            checks=(
                CapabilityCheck(
                    identifier="environment.architecture.native",
                    category=CapabilityCategory.ARCHITECTURE,
                    severity=CapabilitySeverity.REQUIRED,
                    status=CapabilityStatus.SUPPORTED,
                    observed="amd64",
                    expected="amd64",
                ),
            ),
            architecture=ArchitectureCapability(
                process=MachineArchitecture.AMD64,
                native=MachineArchitecture.AMD64,
                emulation=EmulationState.NATIVE,
            ),
        )


def blocked_environment() -> EnvironmentCapabilitySnapshot:
    """A host whose native architecture is not the declared one."""
    return EnvironmentCapabilitySnapshot(
        checks=(
            CapabilityCheck(
                identifier="environment.architecture.native",
                category=CapabilityCategory.ARCHITECTURE,
                severity=CapabilitySeverity.REQUIRED,
                status=CapabilityStatus.UNSUPPORTED,
                reason=CapabilityReason.ARCHITECTURE_MISMATCH,
                observed="arm64",
                expected="amd64",
            ),
        ),
        architecture=ArchitectureCapability(
            process=MachineArchitecture.ARM64,
            native=MachineArchitecture.ARM64,
            emulation=EmulationState.NATIVE,
        ),
    )


@dataclass(frozen=True, slots=True)
class _Tree:
    """Prepares the runtime tree, and records that it was asked to."""

    problems: tuple[str, ...] = ()
    prepared: list[RuntimePaths] | None = None

    def prepare(self, paths: RuntimePaths) -> tuple[str, ...]:
        if self.prepared is not None:
            self.prepared.append(paths)
        return self.problems


@dataclass(frozen=True, slots=True)
class _RuntimeTree:
    """Resolves the mutable tree, or reports why it could not."""

    problems: tuple[str, ...] = ()

    def prepare(self, layout: RuntimeLayout) -> tuple[str, ...]:
        assert layout is not None
        return self.problems

    def describe(self) -> str:
        return "a temporary runtime root"

    def recorded_root(self) -> RecordedPath:
        return recorded_outside("C:/somewhere/GLOBIN")

    def claim_temporary(self, run_id: RunId) -> None:
        assert run_id is not None

    def release_temporary(self, run_id: RunId) -> None:
        assert run_id is not None


@dataclass(slots=True)
class _State:
    """Holds published documents in memory, or refuses to.

    In memory rather than on disk because these tests are about the *pipeline's*
    sequencing. Whether a real `os.replace` is atomic is
    `tests/unit/test_runtime_state_adapters.py`'s question, and answering it twice
    would make this file fail for reasons that are not about it.
    """

    documents: dict[tuple[str, str], Mapping[str, object]]
    refuse: str = ""

    def publish(self, area: RuntimeArea, name: str, document: Mapping[str, object]) -> None:
        if self.refuse:
            raise RuntimePersistenceError(self.refuse)
        self.documents[(area.value, name)] = document

    def read(self, area: RuntimeArea, name: str) -> Mapping[str, object] | None:
        return self.documents.get((area.value, name))

    def discard(self, area: RuntimeArea, name: str) -> None:
        self.documents.pop((area.value, name), None)


@dataclass(frozen=True, slots=True)
class _Lock:
    """Reports whether the coordinator lock could be taken."""

    problem: str = ""

    def hold(self) -> AbstractContextManager[None]:
        return nullcontext()

    def probe(self) -> str:
        return self.problem


class _Refusing:
    """A configuration source that refuses, as a malformed document would."""

    def layer(self) -> ConfigLayer:
        msg = "logging.min_severity is not a severity"
        raise ConfigurationError(msg)


class _Unknown:
    """A configuration source naming a setting nothing declares."""

    def layer(self) -> ConfigLayer:
        return config_layer("test", {"logging.invented": "yes"})


@dataclass(frozen=True, slots=True)
class _Entitlements:
    """An entitlement probe that demands nothing, which is today's truth."""

    demanded: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()

    def readiness(self) -> EntitlementReadiness:
        """Report what was demanded and how each verdict came out."""
        return EntitlementReadiness(demanded=self.demanded, refused=self.refused)


def pipeline(**overrides: object) -> BootstrapPipeline:
    """A pipeline whose every probe is satisfied, with any one replaced."""
    values: dict[str, object] = {
        "baseline": _Baseline(),
        "host": _Host(),
        "project": _Project(),
        "dependencies": _Dependencies(),
        "environment": _Environment(),
        "secrets": _Secrets(),
        "entitlements": _Entitlements(),
        "tree": _Tree(),
        "runtime_tree": _RuntimeTree(),
        "state": _State(documents={}),
        "lock": _Lock(),
        "layout": RuntimeLayout(),
        "configuration_sources": (),
    }
    values.update(overrides)
    return BootstrapPipeline(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The registry and the steps agree
# ---------------------------------------------------------------------------


def test_there_is_one_step_for_every_check_except_the_aggregate() -> None:
    """A check declared without a step would silently produce a shorter report."""
    assert len(steps()) == len(check_identifiers()) - 1


def test_every_unmeasured_check_has_a_sentence_of_its_own() -> None:
    """Inheriting a vague one is how a check that never ran becomes unactionable."""
    covered = set(UNMEASURED_REMEDIATION)
    expected = set(check_identifiers()) - {AGGREGATE_CHECK, "project.root"}
    assert covered == expected


# ---------------------------------------------------------------------------
# A healthy host
# ---------------------------------------------------------------------------


def test_a_satisfied_host_produces_a_ready_context() -> None:
    """The control, and the only path on which a context exists at all."""
    result = pipeline().run()
    assert result.report.ready
    assert result.ready
    assert result.exit_code is ExitCode.OK
    assert result.context is not None
    assert result.context.identity.version == "0.1.0"
    assert result.context.fingerprint.startswith("sha256:")


def test_the_report_carries_every_check_in_the_declared_order() -> None:
    """The order is the dependency order, and it is what the exit code reads."""
    result = pipeline().run()
    assert tuple(check.identifier for check in result.report.outcomes) == check_identifiers()


def test_two_runs_against_one_unchanged_host_agree() -> None:
    """Deterministic, and nothing is cached between them either."""
    first = pipeline().run()
    second = pipeline().run()
    assert first.report == second.report
    assert first.context is not None
    assert second.context is not None
    assert first.context.fingerprint == second.context.fingerprint


def test_the_runtime_tree_is_prepared_exactly_once() -> None:
    """Preparing it twice in one run would mean two steps owned the same job."""
    prepared: list[RuntimePaths] = []
    pipeline(tree=_Tree(prepared=prepared)).run()
    assert len(prepared) == 1


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        pytest.param(
            {"project": _Project(location=recorded_absent())},
            ExitCode.PATHS_UNUSABLE,
            id="no-project-root",
        ),
        pytest.param(
            {"host": _Host(host_facts=replace(HOST, system="Linux"))},
            ExitCode.HOST_UNSUPPORTED,
            id="unsupported-host",
        ),
        pytest.param(
            {"host": _Host(host_facts=replace(HOST, machine="ARM64"))},
            ExitCode.HOST_UNSUPPORTED,
            id="unsupported-architecture",
        ),
        pytest.param(
            {"host": _Host(interpreter_facts=replace(INTERPRETER, implementation="pypy"))},
            ExitCode.INTERPRETER_MISMATCH,
            id="wrong-implementation",
        ),
        pytest.param(
            {"host": _Host(interpreter_facts=replace(INTERPRETER, version="3.13.1"))},
            ExitCode.INTERPRETER_MISMATCH,
            id="wrong-version",
        ),
        pytest.param(
            {"host": _Host(interpreter_facts=replace(INTERPRETER, in_virtual_environment=False))},
            ExitCode.ENVIRONMENT_MISMATCH,
            id="no-virtual-environment",
        ),
        pytest.param(
            {
                "host": _Host(
                    interpreter_facts=replace(INTERPRETER, prefix=recorded_outside("C:/other"))
                )
            },
            ExitCode.ENVIRONMENT_MISMATCH,
            id="wrong-virtual-environment",
        ),
        pytest.param(
            {"project": _Project(who=None)},
            ExitCode.PROJECT_UNIDENTIFIED,
            id="unidentifiable-project",
        ),
        pytest.param(
            {"dependencies": _Dependencies(DependencyReadiness(declared=("numpy",), locked=False))},
            ExitCode.DEPENDENCY_UNREADY,
            id="unlocked-dependency",
        ),
        pytest.param(
            {
                "dependencies": _Dependencies(
                    DependencyReadiness(declared=("numpy",), locked=True, missing=("numpy",))
                )
            },
            ExitCode.DEPENDENCY_UNREADY,
            id="missing-dependency",
        ),
        pytest.param(
            {"configuration_sources": (_Refusing(),)},
            ExitCode.CONFIGURATION_INVALID,
            id="configuration-refused",
        ),
        pytest.param(
            {"configuration_sources": (_Unknown(),)},
            ExitCode.CONFIGURATION_INVALID,
            id="unknown-setting",
        ),
        pytest.param(
            {"tree": _Tree(problems=("the evidence root could not be created",))},
            ExitCode.PATHS_UNUSABLE,
            id="unusable-runtime-tree",
        ),
        pytest.param(
            {
                "secrets": _Secrets(
                    SecretReadiness(required=("binance.api",), unavailable=("binance.api",))
                )
            },
            ExitCode.SECRETS_UNREADY,
            id="unresolved-secret",
        ),
    ],
)
def test_every_refusal_stops_the_run_and_produces_its_own_exit_code(
    overrides: dict[str, object], code: ExitCode
) -> None:
    """The heart of the phase: no context, and the same failure always the same code.

    A context is what authorises everything downstream, so its absence is what
    "fail-closed" means here — there is nothing to check a flag against, because
    there is nothing to hand on.
    """
    result = pipeline(**overrides).run()
    assert result.exit_code is code
    assert result.context is None
    assert not result.ready
    assert not result.report.ready


def test_a_gate_stops_at_the_first_refusal() -> None:
    """Everything after it would be judging a host that has already been rejected."""
    result = pipeline(project=_Project(location=recorded_absent())).run()
    assert len(result.report.outcomes) == 1
    assert result.report.outcomes[0].identifier == "project.root"


def test_an_unreadable_contract_is_unmeasured_rather_than_failed() -> None:
    """Not knowing is a different answer from knowing the host is wrong."""
    result = pipeline(baseline=_Baseline(value=None)).run()
    assert result.exit_code is ExitCode.UNMEASURED
    assert result.report.outcomes[-1].status is CheckStatus.UNMEASURED
    assert result.report.outcomes[-1].remediation


def test_every_refusal_carries_a_remediation() -> None:
    """A failure a reader cannot act on is a failure reported twice."""
    result = pipeline(host=_Host(host_facts=replace(HOST, system="Linux"))).run()
    for check in result.report.outcomes:
        if check.status is not CheckStatus.PASS:
            assert check.remediation


# ---------------------------------------------------------------------------
# Doctor keeps going
# ---------------------------------------------------------------------------


def test_a_diagnostic_measures_everything_it_still_can() -> None:
    """Same pipeline, same judgements — only the stopping rule differs."""
    result = pipeline(project=_Project(location=recorded_absent())).run(stop_at_first_refusal=False)
    assert tuple(check.identifier for check in result.report.outcomes) == check_identifiers()
    assert result.context is None


def test_a_diagnostic_records_what_it_could_not_measure_as_unmeasured() -> None:
    """Rather than as a failure of a check that never ran."""
    result = pipeline(project=_Project(location=recorded_absent())).run(stop_at_first_refusal=False)
    statuses = {check.identifier: check.status for check in result.report.outcomes}
    assert statuses["project.identity"] is CheckStatus.UNMEASURED
    assert statuses["dependency.lock"] is CheckStatus.UNMEASURED
    assert statuses["paths.runtime"] is CheckStatus.UNMEASURED


def test_a_diagnostic_still_reports_the_earliest_cause() -> None:
    """Going further does not change what a caller is told went wrong.

    Every later check is still measurable here — the project was found, so the
    tree, the configuration and the dependencies can all be read — which is why
    the code is the host's rather than `UNMEASURED`.
    """
    result = pipeline(host=_Host(host_facts=replace(HOST, system="Linux"))).run(
        stop_at_first_refusal=False
    )
    assert result.report.status_of("runtime.host") is CheckStatus.FAIL
    assert result.exit_code is ExitCode.HOST_UNSUPPORTED
    assert result.context is None


def test_a_healthy_diagnostic_matches_a_healthy_gate() -> None:
    """Two views of one host must not describe two hosts."""
    gate = pipeline().run()
    doctor = pipeline().run(stop_at_first_refusal=False)
    assert gate.report == doctor.report


# ---------------------------------------------------------------------------
# What is observed
# ---------------------------------------------------------------------------


def test_the_observed_facts_carry_no_absolute_path() -> None:
    """Every path in the record is a recorded one, which cannot be absolute."""
    observed = pipeline().run().observed
    assert observed is not None
    rendered = str(observed)
    assert "C:/Python314" not in rendered
    assert "C:\\Python314" not in rendered


def test_a_measurement_that_did_not_happen_is_recorded_as_none() -> None:
    """So a reader can tell "not measured" from "measured as nothing"."""
    observed = pipeline(project=_Project(location=recorded_absent())).run().observed
    assert observed is not None
    assert observed["host"] is None
    assert observed["interpreter"] is None
