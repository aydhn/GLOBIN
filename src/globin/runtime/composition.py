"""Composition root: where GLOBIN's objects are built and wired together.

The worked example of GLOBIN's wiring convention — plain functions that take what
they cannot know and return fully constructed objects. Nothing is cached, nothing
is global, and nothing runs until a function is called.

The ``repo_root`` argument is not decoration. The architecture review reviews
*this* repository's source tree, so it needs a location, and guessing one by
walking up from ``__file__`` would make the result depend on where the package
happens to be installed. Passing it in keeps the dependency visible and lets a
test point the review at a fixture tree instead. Configuration sources are given
the same way, for the same reason.

These functions build; they do not choose. Phase 027 answered which configuration
sources exist and in what order, and the answer is one function --
:func:`build_config_sources` -- rather than branching spread through the others: a
composition root that grew logic about *what* to construct would be the failure
ADR-0015 names in its own risk section.
"""

import os
import signal
import sys
import threading
import types
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Final, TextIO

import globin
from globin.adapters.api_reality import REGISTRY_PATH, TomlApiRealitySource
from globin.adapters.architecture import AstModuleImportSource, TomlArchitectureContractSource
from globin.adapters.bootstrap import PROJECT_FILE as PROJECT_MANIFEST
from globin.adapters.bootstrap import (
    RUNTIME_CONTRACT_PATH,
    RUNTIME_LOCK,
    DeclaredDependencyProbe,
    FilesystemProjectProbe,
    ProjectRuntimeTree,
    RegisterBackedEntitlements,
    StoreBackedSecrets,
    SystemEnvironmentProbe,
    SystemHostProbe,
    TomlRuntimeBaselineSource,
    find_project_root,
    write,
)
from globin.adapters.clock import SystemClock, SystemMonotonicClock
from globin.adapters.clock_sync import ClockManager, RestServerTimeSource, discipline_from
from globin.adapters.configuration import (
    CliConfigurationSource,
    EnvironmentConfigurationSource,
    OptionalDocumentSource,
    RequiredDocumentSource,
    TomlConfigurationSource,
)
from globin.adapters.degradation import (
    CONTRACT_RELATIVE_PATH as DEGRADATION_CONTRACT_PATH,
)
from globin.adapters.degradation import ContractDegradationProbe, system_arms
from globin.adapters.dependency import installed_versions
from globin.adapters.diagnostics import (
    DIAGNOSTICS_FILE,
    FAULT_FILE_NAME,
    LOG_FILE_NAME,
    FanOutLogSink,
    FaultFile,
    HookRegistry,
    ProcessFaultHooks,
    RotatingFileLogSink,
    RuntimeDiagnostics,
    StandardLibraryBridge,
    StandardLibraryCapture,
    system_hooks,
)
from globin.adapters.diagnostics_http import (
    CachedHealthProjection,
    DiagnosticsEndpoint,
    DiagnosticsSnapshotProjection,
    ReadinessGate,
    ShutdownLiveness,
    TelemetryExposition,
)
from globin.adapters.entitlements import StateGrantRegister
from globin.adapters.environment import (
    DECLARED_TOOLCHAIN,
    PathToolchainProbe,
    windows_system_api,
)
from globin.adapters.health import (
    DiagnosticsStateProbe,
    FilesystemTreeProbe,
    StateLifecycleProbe,
    SystemPlatformProbe,
    SystemThreadProbe,
    TracemallocProbe,
    snapshot_document,
    system_host_probe,
    system_process_probe,
)
from globin.adapters.observability import StreamLogSink, ThresholdLogSink, new_correlation_id
from globin.adapters.provisioning import (
    BoundedProcessRunner,
    MarkerEnvironmentClaim,
    PathToolProbe,
    ReadOnlyProcessRunner,
    RuntimeTreeExecutor,
)
from globin.adapters.runtime_state import (
    AtomicDocumentWriter,
    AtomicStateStore,
    FileOperations,
    PlatformShutdownSignals,
    WindowsInstanceLock,
    register_last_resort,
    resolve_root,
    system_environment,
)
from globin.adapters.runtime_state import ProjectRuntimeTree as UserRuntimeTree
from globin.adapters.runtime_state import render as render_state_document
from globin.adapters.secret_entry import ConsoleSecretEntry
from globin.adapters.secret_environment import environment_secret_provider
from globin.adapters.secret_vault import secret_vault
from globin.adapters.secrets import windows_credential_store
from globin.adapters.serialization import JsonCodec
from globin.adapters.support import ZipArchiveWriter, digest_of
from globin.adapters.watchdog import (
    ImmediateProcessExit,
    ProcessStackEvidence,
    SharedHeartbeatRegistry,
    WatchdogThread,
    heartbeats,
)
from globin.application.architecture_review import ArchitectureReview
from globin.application.bootstrap import BootstrapPipeline
from globin.application.configuration import ConfigurationResolution
from globin.application.diagnostics_http import DiagnosticsService
from globin.application.health import HealthCollector
from globin.application.lifecycle import Lifecycle
from globin.application.observability import Logger
from globin.application.preflight import PreflightRun
from globin.application.provisioning import (
    ProvisioningApply,
    ProvisioningOutcome,
    ProvisioningPlanRun,
    ProvisioningProposal,
)
from globin.application.secrets import ProviderRoutedStore
from globin.application.support import BundleBuilder, Candidate
from globin.application.telemetry import MetricStore, metric_store
from globin.application.watchdog import RuntimeWatchdog
from globin.domain.api_reality import ApiRealitySnapshot
from globin.domain.bootstrap import (
    BootstrapOutcome,
    ProjectIdentity,
    RecordedPath,
    RuntimeContext,
    RuntimePaths,
)
from globin.domain.clock import MonotonicReading
from globin.domain.config_layout import (
    ConfigLayout,
    ConfigRole,
    precedence,
    profile_from,
    resolve_profile,
)
from globin.domain.configuration import (
    PROFILE_VARIABLE,
    GlobinConfig,
    ResolvedConfig,
    default_config,
)
from globin.domain.diagnostics import MAXIMUM_BACKUP_COUNT
from globin.domain.entitlements import required_credentials, required_references
from globin.domain.preflight import PreflightOutcome, PreflightSuite, build_suite
from globin.domain.provisioning import NetworkPolicy, ProvisioningPlan
from globin.domain.rest_contract import TransportContract
from globin.domain.runtime_state import (
    INSTANCE_FILE,
    LIFECYCLE_FILE,
    LOCK_FILE,
    RuntimeArea,
    RuntimeLayout,
)
from globin.domain.secrets import (
    SecretLocator,
    SecretProviderKind,
    provider_permitted,
)
from globin.domain.support import ArtifactKind, safe_member_name
from globin.domain.watchdog import WatchdogEpisode
from globin.errors import ConfigurationError, InternalError
from globin.ports.api_reality import ApiRealitySource
from globin.ports.clock import Clock, MonotonicClock, ServerTimeSource
from globin.ports.configuration import ConfigurationSource
from globin.ports.entitlements import GrantRegister
from globin.ports.provisioning import CapabilityProbe, ProcessRunner
from globin.ports.rest import RestTransport
from globin.ports.runtime_state import ShutdownSignals
from globin.ports.secret_entry import SecretEntry
from globin.ports.secrets import SecretStore
from globin.ports.serialization import Codec
from globin.ports.watchdog import ProcessTerminator

CONTRACT_RELATIVE_PATH: Final[str] = "docs/architecture/dependency-rules.toml"
"""Where the declared contract lives, relative to the repository root."""

PACKAGE_RELATIVE_PATH: Final[str] = "src/globin"
"""Where the package source lives, relative to the repository root."""

ROOT_PACKAGE: Final[str] = "globin"
"""The import namespace the review is scoped to."""

MILLISECONDS_PER_SECOND: Final[float] = 1000.0
"""What a millisecond setting is divided by to reach the seconds a wait takes.

A float because :meth:`threading.Event.wait` takes seconds as a float, and the
one place the conversion happens is here rather than at the call site.
"""

PROFILES: Final[tuple[str, ...]] = ("paper", "demo", "testnet", "live")
"""Every profile this installation declares, in listing order.

The four names are `ROADMAP.md` row 026's and nowhere else's. A fifth is a roadmap
edit rather than a value somebody passes, and
`tests/contract/test_configuration_layout_contract.py` compares this tuple against
that row in both directions.

**They live here rather than in the domain layer, and that is a rule rather than a
preference.** Three of them -- `demo`, `testnet`, `live` -- are venue vocabulary,
and `tests/architecture/test_identifier_discipline.py` refuses venue vocabulary as
a live constant anywhere under `globin.domain`. That refusal is right: a set of
environment names compiled into the innermost layer would answer, quietly and in
the wrong place, the question Phase 035 exists to ask. So
`globin.domain.config_layout` bounds the *shape* of a profile name and this
constant supplies the *instances*, which is `identifiers.py`'s kinds-not-instances
discipline applied to a second subject.

Listing order, not precedence. `paper` is first because it is the default, and the
rest follow the roadmap's own sentence."""

DEFAULT_PROFILE: Final[str] = "paper"
"""The profile assumed when nothing has selected one.

Phase 022 recorded `"default"` here as a placeholder for a concept that did not
exist yet. It exists now, so this is one of the four rather than a fifth name that
is not a profile.

**`paper`, and it must never be `live`.** ADR-0006's "never downgraded to
production" read in the other direction means never silently *upgraded* to it
either, and a default is the quietest upgrade there is.

Phase 027 built the selection this was waiting for: :func:`resolve_run_profile`
orders a launcher argument above `GLOBIN_PROFILE` above this value. What did not
change is that a *misspelled* selection never lands here — `profile_from` refuses an
undeclared name rather than falling back, so this is reached only when nobody
asked."""


def build_architecture_review(repo_root: Path) -> ArchitectureReview:
    """Wire the architecture review against a repository checkout.

    Args:
        repo_root: Absolute path to the repository root — the directory holding
            ``pyproject.toml``.

    Returns:
        An :class:`~globin.application.architecture_review.ArchitectureReview`
        reading the declared contract and this repository's own source tree.

    No file is opened here. Both adapters record their paths and read them when
    the review runs, so constructing the graph stays free of I/O even though
    the objects it contains will perform some.
    """
    return ArchitectureReview(
        contract_source=TomlArchitectureContractSource(repo_root / CONTRACT_RELATIVE_PATH),
        module_source=AstModuleImportSource(repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE),
    )


def build_configuration(sources: Sequence[ConfigurationSource] | None = None) -> GlobinConfig:
    """Resolve GLOBIN's configuration from the declared defaults plus ``sources``.

    Args:
        sources: Weakest first, strongest last. Defaults to none at all, which
            resolves to the declared defaults — the configuration GLOBIN uses
            when an operator has said nothing.

    Returns:
        The validated :class:`~globin.domain.configuration.GlobinConfig`.

    Raises:
        ConfigurationError: If a source supplied an unknown key or an unreadable
            value.

    No file is opened here. A source records its path and reads it when the
    resolution runs, so building the graph stays free of I/O even though the
    objects in it will perform some — the same property
    :func:`build_architecture_review` has.
    """
    return ConfigurationResolution(sources=() if sources is None else tuple(sources)).run()


def resolve_settings(sources: Sequence[ConfigurationSource] | None = None) -> ResolvedConfig:
    """Fold the same sources :func:`build_configuration` folds, without validating.

    Args:
        sources: Weakest first, strongest last.

    Returns:
        The resolved settings, each carrying the origin that set it.

    Raises:
        ConfigurationError: If a source could not produce a layer.

    For the one caller that needs both the model and the settings behind it: a health
    snapshot carries a fingerprint over what was configured, and taking that
    fingerprint from a separate resolution would let it describe a configuration the
    process is not running on.
    """
    return ConfigurationResolution(sources=() if sources is None else tuple(sources)).resolved()


def build_config_layout() -> ConfigLayout:
    """Where GLOBIN's configuration documents sit, relative to the project root.

    Returns:
        The declared :class:`~globin.domain.config_layout.ConfigLayout`.

    A builder rather than a constant, on the rule every layer package here obeys:
    constructing a dataclass is a call, and a call at import is refused. It reaches
    no filesystem and joins nothing to a root -- it returns *spellings*, and
    :func:`configuration_document` is what turns one into a path.
    """
    return ConfigLayout()


def configuration_document(
    repo_root: Path, role: ConfigRole, profile: str, layout: ConfigLayout | None = None
) -> Path:
    """Where one configuration document would be, on this filesystem.

    Args:
        repo_root: The discovered project root.
        role: Which of the four documents.
        profile: Which profile.
        layout: The layout to read, defaulting to the declared one.

    Returns:
        An absolute path. **It is not checked for existence**, deliberately:
        whether a missing document is fatal or an empty layer is Phase 027's
        question, and answering it here by returning ``None`` would settle it.

    Raises:
        ValidationError: If the profile name is not canonical.

    The one place a project-relative spelling meets a real root, which is the same
    division `RuntimePaths` draws between a declared segment and a resolved
    location.
    """
    declared = build_config_layout() if layout is None else layout
    return repo_root / Path(declared.document_for(role, profile))


def resolve_declared_profile(name: str) -> str:
    """Resolve a profile name against the profiles this installation declares.

    Args:
        name: The candidate spelling, from wherever the caller obtained it.

    Returns:
        The declared spelling it names.

    Raises:
        ConfigurationError: If it names none of them.

    Supplies :data:`PROFILES` so that the domain keeps bounding the *shape* of a
    name while the composition root owns the *set*. Where the candidate came from
    -- an environment variable, a launcher argument, a flag, or the precedence
    between them -- is Phase 027's, and this function deliberately takes it as an
    argument rather than reading anything.
    """
    return resolve_profile(name, PROFILES)


def resolve_run_profile(
    requested: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> str:
    """Which profile this run uses, from the launcher, the environment or the default.

    Args:
        requested: What a launcher argument asked for, or ``None``.
        environment: The variables to read, defaulting to this process's own.

    Returns:
        The declared spelling of the selected profile.

    Raises:
        ConfigurationError: If a selection names no declared profile.

    Supplies :data:`PROFILES` and :data:`DEFAULT_PROFILE` to
    :func:`~globin.domain.config_layout.profile_from`, which owns the order. The
    domain bounds the shape and decides the precedence; this function owns the *set*
    and the default, which is the division :func:`resolve_declared_profile` already
    draws.

    The environment is read here rather than in the domain because :mod:`os` is
    I/O-capable, which is the same reason :func:`build_runtime_state` takes one.
    """
    variables = system_environment() if environment is None else environment
    return profile_from(
        requested=requested,
        environment_value=variables.get(PROFILE_VARIABLE),
        declared=PROFILES,
        default=DEFAULT_PROFILE,
    )


def build_config_sources(
    repo_root: Path | None,
    profile: str,
    environment: Mapping[str, str] | None = None,
    layout: ConfigLayout | None = None,
    explicit: Path | None = None,
    overrides: Mapping[str, str] | None = None,
) -> tuple[ConfigurationSource, ...]:
    """Every configuration source, weakest first.

    Args:
        repo_root: The discovered project root, or ``None`` when there is none — an
            installed ``globin`` run from somewhere else has no repository to read
            documents out of.
        profile: The resolved profile, which decides which two of the four documents
            are named.
        environment: The variables to read, defaulting to this process's own.
        layout: The layout to read, defaulting to the declared one.
        explicit: A document named on the command line, or ``None``. Resolved to
            an absolute path here, so that the same document named from two
            working directories is the same source.
        overrides: Values a launcher set with ``--set``, already validated by
            :func:`~globin.adapters.configuration.parse_overrides`.

    Returns:
        The sources in the order :func:`~globin.domain.configuration.resolve` folds
        them: the four computed documents, an explicit one, the environment, and
        the command line.

    **This function is Phase 027's answer, assembled in one place.** The document
    order is :func:`~globin.domain.config_layout.precedence`'s and is not restated
    here; what this adds is where the environment sits relative to those documents,
    and it sits **above all of them**. The reasoning is the one the whole phase
    follows: a variable is set for this invocation and a committed document is set
    for every invocation, so the narrower act wins. It is also the only source an
    operator can use without write access to the tree, which is what makes it the
    right lever for a one-off.

    **Every document is optional; the environment is not.** A missing file means the
    operator did not write one, so it contributes an empty layer through
    :class:`~globin.adapters.configuration.OptionalDocumentSource`. There is no
    equivalent absence for the environment — a process always has one, possibly
    empty — so it is read directly and an unrecognised ``GLOBIN_`` variable is
    refused rather than skipped.

    **With no project root there are no documents at all**, and that is reported by
    returning only the environment source rather than by raising. An installed
    GLOBIN running outside a checkout is a supported situation, and the honest
    consequence is that it runs on declared defaults plus whatever the environment
    says.

    **Phase 030 added the two ends and kept the middle.** An explicit document sits
    above the four computed ones because naming a file is a narrower act than
    having written one into the tree, and the command line sits above everything
    because a flag applies to exactly one run. The order the whole chain follows is
    that one rule — narrowness — rather than five separate judgements, which is
    what makes a seventh source's position a question with an answer instead of a
    preference.

    **An explicit document is required where the computed four are optional.** It
    is wrapped in a :class:`~globin.adapters.configuration.RequiredDocumentSource`
    rather than an optional one, so a path with a typo in it refuses instead of
    contributing an empty layer that nobody would notice.

    **The command-line source is always present, even when it sets nothing.** An
    empty layer is the identity element of the fold, so the chain has one shape,
    and the provenance can show that the source was consulted rather than leaving
    a reader to infer it from an absence.

    No file is opened here. Each source records its path and reads it when the
    resolution runs.
    """
    variables = system_environment() if environment is None else environment
    declared = build_config_layout() if layout is None else layout
    documents: list[ConfigurationSource] = []
    if repo_root is not None:
        for role in precedence():
            path = configuration_document(repo_root, role, profile, declared)
            documents.append(OptionalDocumentSource(TomlConfigurationSource(path), str(path)))
    if explicit is not None:
        chosen = explicit.resolve()
        documents.append(RequiredDocumentSource(TomlConfigurationSource(chosen), str(chosen)))
    return (
        *documents,
        EnvironmentConfigurationSource(variables),
        CliConfigurationSource({} if overrides is None else overrides),
    )


def build_clock() -> Clock:
    """The host's wall clock, as the port.

    Returns:
        A :class:`~globin.adapters.clock.SystemClock`.

    The return type is the **port**, not the adapter, so this function stays the
    only place in the tree that names the concrete clock. That is ADR-0014 and
    ADR-0015 made concrete rather than restated.
    """
    return SystemClock()


def build_monotonic_clock() -> MonotonicClock:
    """The host's monotonic clock, as the port.

    Returns:
        A :class:`~globin.adapters.clock.SystemMonotonicClock`.

    **Phase 036 gave this its second consumer, and the first that depends on the
    guarantee rather than merely on the resolution.** Phase 034's transport uses it
    to time a request; :func:`globin.application.clock_sync.take_sample` uses it to
    bound a clock offset, which means an interval that a wall clock could have
    stepped through would produce a *wrong estimate* rather than a wrong log line.
    """
    return SystemMonotonicClock()


def build_server_time_source(
    transport: RestTransport,
    snapshot: ApiRealitySnapshot,
    contract: TransportContract,
    *,
    stale_sources: Sequence[str] = (),
) -> ServerTimeSource:
    """How GLOBIN asks a venue what time it is, as the port.

    Args:
        transport: Phase 034's REST transport. The only object here that reaches a
            socket.
        snapshot: Phase 033's registry, the only source of endpoints.
        contract: The declared transport contract, the only source of paths.
        stale_sources: Source identifiers past their re-check interval.

    Returns:
        A :class:`~globin.adapters.clock_sync.RestServerTimeSource`.

    The return type is the **port**, so this function stays the only place in the
    tree that names the concrete source — the property :func:`build_clock` has, and
    what lets a WebSocket implementation arrive later with no caller changing.
    """
    return RestServerTimeSource(
        transport=transport,
        snapshot=snapshot,
        contract=contract,
        correlation=new_correlation_id,
        stale_sources=tuple(stale_sources),
    )


def build_clock_manager(
    source: ServerTimeSource,
    *,
    config: GlobinConfig | None = None,
    clock: Clock | None = None,
    monotonic: MonotonicClock | None = None,
) -> ClockManager:
    """The thing that holds one calibration per clock domain.

    Args:
        source: How the venue is asked.
        config: The resolved configuration, or ``None`` for the declared defaults.
        clock: The host's wall clock, or ``None`` to build one.
        monotonic: The host's monotonic clock, or ``None`` to build one.

    Returns:
        The manager, holding no calibration for any domain.

    Raises:
        ValidationError: If the configured thresholds contradict each other. That
            refusal comes from :class:`~globin.domain.clock_sync.ClockDiscipline`,
            so an operator's configuration is judged by the same rules a default is
            — and it happens here, at composition, rather than at the first request.

    **Both clocks default to real ones and neither is read here.** Constructing an
    adapter is not reading it, which is why
    ``tests/architecture/test_clock_discipline.py`` permits the runtime layer to
    build one and still finds no clock call in this module.
    """
    settings = (config or default_config()).clock
    return ClockManager(
        source=source,
        clock=clock or build_clock(),
        monotonic=monotonic or build_monotonic_clock(),
        discipline=discipline_from(
            sample_count=settings.sample_count,
            freshness_ttl_millis=settings.freshness_ttl_millis,
            degraded_grace_millis=settings.degraded_grace_millis,
            max_round_trip_millis=settings.max_round_trip_millis,
            max_uncertainty_millis=settings.max_uncertainty_millis,
            max_offset_jump_millis=settings.max_offset_jump_millis,
            max_wall_divergence_millis=settings.max_wall_divergence_millis,
            network_budget_millis=settings.network_budget_millis,
        ),
    )


def build_codec() -> Codec:
    """The representation GLOBIN persists records in, as the port.

    Returns:
        A :class:`~globin.adapters.serialization.JsonCodec`.

    The return type is the **port**, so this function stays the only place in the
    tree that names the concrete representation — the same property
    :func:`build_clock` has, and for the same reason.

    Nothing in GLOBIN persists a record yet. This exists because ``ROADMAP.md``
    gives Phase 012 the serialization and persistence contracts, and the decision
    worth fixing now is *which* representation a stored record is in — not the
    first caller, which arrives with the phase that has somewhere to put one.
    """
    return JsonCodec()


def build_logger(
    stream: TextIO | None = None,
    correlation_id: str | None = None,
    config: GlobinConfig | None = None,
    clock: Clock | None = None,
) -> Logger:
    """Wire a logger writing JSON Lines to a stream.

    Args:
        stream: Where records go. Defaults to :data:`sys.stderr`, so that log
            output does not contaminate whatever a program writes to standard
            output.
        correlation_id: Ties every record this logger produces to one unit of
            work. Defaults to a fresh one. A test passes its own, and so does a
            caller continuing work that already has an id.
        config: Supplies the severity threshold. Defaults to
            :func:`~globin.domain.configuration.default_config`, whose threshold
            is ``DEBUG`` and therefore discards nothing.
        clock: Stamps each record. Defaults to :func:`build_clock`. A test
            passes a fixed or manually advanced clock and can then assert the
            exact timestamps written.

    Returns:
        A :class:`~globin.application.observability.Logger`.

    Every argument defaults to ``None`` rather than to the value it resolves to.
    ``sys.stderr`` as a default argument would be captured when this module is
    imported, which is both work at import time and the wrong stream if anything
    later replaces it — and reading it here keeps this function the only place
    that knows which stream GLOBIN logs to. The clock is the same argument with
    a stronger reason: a clock captured at import would be ambient time, which
    is what Phase 009 exists to remove.

    The threshold sink is applied unconditionally rather than only when a
    threshold has been configured. ``DEBUG`` is the lowest severity, so at the
    default the wrapper provably changes nothing; wrapping only sometimes would
    give this function a decision to make about *what* to build, and leave one
    arm of it exercised by nobody.
    """
    settings = default_config() if config is None else config
    return Logger(
        sink=ThresholdLogSink(
            inner=StreamLogSink(
                stream=sys.stderr if stream is None else stream,
                clock=build_clock() if clock is None else clock,
            ),
            minimum=settings.logging.min_severity,
        ),
        correlation_id=new_correlation_id() if correlation_id is None else correlation_id,
    )


@dataclass(frozen=True, slots=True)
class Bootstrap:
    """A wired bootstrap, and the location it was wired against.

    Args:
        pipeline: The checks, in order.
        root: Where the project was found, or ``None`` when it was not. Carried
            because the caller needs a real path to write evidence to, and
            :class:`~globin.domain.bootstrap.RecordedPath` deliberately cannot
            supply one.
        paths: The declared runtime tree.

    The two halves are returned together rather than separately because a
    pipeline wired against one root and evidence written under another would be a
    report about one project filed under a different one.
    """

    pipeline: BootstrapPipeline
    root: Path | None
    paths: RuntimePaths

    def run(self, *, stop_at_first_refusal: bool) -> BootstrapOutcome:
        """Perform the checks.

        Args:
            stop_at_first_refusal: ``True`` for a gate, ``False`` for a
                diagnostic.

        Returns:
            What the run concluded.
        """
        return self.pipeline.run(stop_at_first_refusal=stop_at_first_refusal)

    def preflight(self, suite: PreflightSuite | None = None) -> PreflightOutcome:
        """Perform every check and judge it as a suite.

        Args:
            suite: The classification and re-take schedule, defaulting to
                :func:`~globin.domain.preflight.build_suite`.

        Returns:
            What the run concluded, and how long the verdict stays true.

        A method on the wired object rather than a fifth builder, because it needs
        exactly what :meth:`run` needs and nothing else. Wiring it separately would
        create a second way to assemble the same pipeline, and the two would drift.
        """
        return PreflightRun(
            pipeline=self.pipeline, suite=build_suite() if suite is None else suite
        ).run()

    def record(self, outcome: BootstrapOutcome) -> RecordedPath:
        """Write one run's evidence.

        Args:
            outcome: What the run concluded.

        Returns:
            Where the manifest was written, recorded.

        Raises:
            BootstrapManifestError: If the run does not render deterministically.
            OSError: If the file could not be written.
            ConfigurationError: If there is no project root, and therefore
                nowhere inside the project that evidence may go. Nothing is
                written outside it, ever.
        """
        if self.root is None:
            msg = "there is no project root, so there is nowhere to write evidence"
            raise ConfigurationError(msg)
        return write(outcome, root=self.root, paths=self.paths)


@dataclass(frozen=True, slots=True)
class RuntimeState:
    """The mutable runtime tree, wired: where it is, and the three things that use it.

    Args:
        root: The resolved runtime root.
        layout: The declared shape of the tree.
        tree: Creates the five areas and refuses anything that escapes.
        store: Publishes and reads small documents inside them.
        lock: Decides whether this process may be the one coordinator.
        signals: Notices a stop request.

    Returned as one object rather than five because they are only correct
    together: a store writing under one root and a lock taken under another would
    be one process guarding a tree it does not use.
    """

    root: Path
    layout: RuntimeLayout
    tree: UserRuntimeTree
    store: AtomicStateStore
    lock: WindowsInstanceLock
    signals: PlatformShutdownSignals


def build_runtime_state(
    environment: Mapping[str, str] | None = None,
    layout: RuntimeLayout | None = None,
) -> RuntimeState:
    """Wire the mutable runtime tree against the platform's per-user data area.

    Args:
        environment: Where to look up the per-user data area. Defaults to this
            process's own. Passed in rather than read below so that the Phase 027
            seam already exists and so a test substitutes one without touching
            global state.
        layout: The declared tree. Defaults to GLOBIN's.

    Returns:
        The wired :class:`RuntimeState`.

    Raises:
        RuntimePersistenceError: If the platform does not say where per-user
            application data goes. GLOBIN refuses rather than guessing a
            substitute, because a machine-wide coordinator lock whose location
            depended on how the process was started would guard nothing.

    **This resolves a path and creates nothing.** Bringing the tree into existence
    is `prepare`, which the bootstrap calls as a check so that a failure is a
    named refusal rather than an exception from a constructor.
    """
    declared = RuntimeLayout() if layout is None else layout
    root = resolve_root(system_environment() if environment is None else environment, declared)
    return RuntimeState(
        root=root,
        layout=declared,
        tree=UserRuntimeTree(root=root, layout=declared),
        store=AtomicStateStore(root=root, layout=declared, operations=FileOperations()),
        lock=WindowsInstanceLock(root=root, layout=declared, name=LOCK_FILE),
        signals=PlatformShutdownSignals(registrar=_register_handler, installed=[]),
    )


def _register_handler(number: int, handler: Callable[[int, types.FrameType | None], None]) -> None:
    """Install one signal handler, discarding the previous one.

    Args:
        number: The signal number.
        handler: What to run when it arrives.

    :func:`signal.signal` returns the handler it replaced, and GLOBIN has no use
    for it: nothing here restores a previous disposition, because a process that
    installed GLOBIN's shutdown path is not going to hand control back to whatever
    was there before. Narrowing the return to ``None`` here rather than widening
    the port keeps the port describing what GLOBIN actually needs.
    """
    signal.signal(number, handler)


def build_diagnostics(
    state: RuntimeState,
    *,
    correlation_id: str | None = None,
    config: GlobinConfig | None = None,
    clock: Clock | None = None,
    stream: TextIO | None = None,
    hooks: HookRegistry | None = None,
) -> RuntimeDiagnostics:
    """Wire the full diagnostic subsystem against a prepared runtime tree.

    Args:
        state: The runtime tree, already resolved. The log file goes in its logs
            area, which is the one place a growing file is allowed.
        correlation_id: Ties every record in this run together. Defaults to a
            fresh one.
        config: Supplies the severity threshold and the rotation policy.
        clock: Stamps each record. Defaults to :func:`build_clock`.
        stream: Where console records go. Defaults to :data:`sys.stderr`, so that
            ``--json`` output on standard out stays parseable.
        hooks: Where the process fault hooks live. Defaults to the real ones; a
            test passes a registry backed by a dictionary and never touches
            :mod:`sys`.

    Returns:
        The assembled :class:`~globin.adapters.diagnostics.RuntimeDiagnostics`,
        **not started**. Starting it installs process-global hooks, and that is a
        decision for the caller that owns the process rather than a side effect of
        asking for the object.

    **The console and the file are one fan-out, not two loggers.** A second logger
    would mean two correlation ids for one unit of work, and a call site choosing
    between them. One logger writes to a fan-out whose elements hold their own
    thresholds, which is the arrangement ``LOGGING_POLICY.md`` describes.

    **The file sink is never the reason a start-up fails.** ``config`` may turn it
    off, and a tree whose logs area cannot be created is a
    :class:`~globin.domain.bootstrap.ExitCode.PATHS_UNUSABLE` refusal from the
    bootstrap checks rather than a surprise from here.
    """
    settings = default_config() if config is None else config
    ticking = build_clock() if clock is None else clock
    identifier = new_correlation_id() if correlation_id is None else correlation_id
    logs = state.root / state.layout.segment_for(RuntimeArea.LOGS)

    console = ThresholdLogSink(
        inner=StreamLogSink(stream=sys.stderr if stream is None else stream, clock=ticking),
        minimum=settings.logging.min_severity,
    )
    file_sink = RotatingFileLogSink(
        path=logs / LOG_FILE_NAME,
        clock=ticking,
        policy=settings.logging.rotation(),
        handle=None,
        written=0,
    )
    fan_out = FanOutLogSink(
        sinks=(
            console,
            ThresholdLogSink(inner=file_sink, minimum=settings.logging.min_severity),
        )
    )
    logger = Logger(sink=fan_out, correlation_id=identifier)
    return RuntimeDiagnostics(
        logger=logger,
        file_sink=file_sink,
        hooks=ProcessFaultHooks(
            logger=logger,
            registry=system_hooks() if hooks is None else hooks,
            previous={},
        ),
        capture=StandardLibraryCapture(
            bridge=StandardLibraryBridge(sink=fan_out, correlation_id=identifier),
            installed=False,
        ),
        faults=FaultFile(path=logs / FAULT_FILE_NAME, handle=None),
        started=False,
        publish=lambda document: state.store.publish(RuntimeArea.STATE, DIAGNOSTICS_FILE, document),
    )


def build_lifecycle(
    context: RuntimeContext,
    state: RuntimeState,
    clock: Clock | None = None,
    register_fallback: Callable[[Callable[[], None]], None] | None = None,
) -> Lifecycle:
    """Wire one run's lifecycle against a prepared runtime tree.

    Args:
        context: The assembled runtime context. **Only obtainable from a bootstrap
            run in which every check passed**, which is what makes "the lock is
            taken only by a process that was told it may start" a property of the
            types rather than of anybody's discipline.
        state: The wired mutable tree.
        clock: Stamps the records. Defaults to the host's. A test passes a manual
            one and can then assert the exact timestamps written.
        register_fallback: Registers the best-effort `atexit` net. Defaults to the
            real one. A test passes its own, because registering a real callback
            would run it after the test that made it.

    Returns:
        The wired :class:`~globin.application.lifecycle.Lifecycle`.

    The process identifier is read **here** and passed down as a value.
    :mod:`os` is I/O-capable and the application layer may import none, so this is
    the layer that may ask — the same treatment the clock gets.
    """
    return Lifecycle(
        tree=state.tree,
        state=state.store,
        lock=state.lock,
        signals=state.signals,
        clock=build_clock() if clock is None else clock,
        layout=state.layout,
        version=context.identity.version,
        profile=DEFAULT_PROFILE,
        pid=os.getpid(),
        runtime_root=context.runtime_root,
        register_fallback=register_last_resort if register_fallback is None else register_fallback,
    )


VAULT_FALLBACK_SEGMENT: Final[str] = "vault"
"""Where the vault looks when no runtime tree was resolved.

A bare relative segment, which no host will have and every absent-safe factory
answers about rather than creates. It exists so that
:func:`build_secret_providers` can be called with no runtime state -- which
``secrets doctor`` does, because reporting on a mechanism must not require the
tree that mechanism writes into.
"""

DEFAULT_PROVIDER: Final[SecretProviderKind] = SecretProviderKind.CREDENTIAL_MANAGER
"""The mechanism a reference with no locator uses.

The Credential Manager, because that is where every secret GLOBIN could hold
lives today -- so a run with no locators behaves exactly as it did before Phase
031, byte for byte. Beside :data:`DEFAULT_PROFILE`, with the same argument:
reached only when nobody asked.
"""

ENVIRONMENT_PROVIDER_PROFILES: Final[tuple[str, ...]] = ("paper",)
"""Which profiles permit a secret to arrive from the process environment.

**An allow-list, not a deny-list, and the direction is the decision.** A deny-list
naming ``live`` would silently permit the environment provider in every profile
added afterwards; an allow-list refuses a new profile until somebody decides,
which is the direction :func:`~globin.domain.config_layout.resolve_profile`
already takes for an unknown name and which ADR-0006's "never silently upgraded to
live" implies read the other way round.

``paper`` alone, chosen by the owner. The environment is a hand-off rather than a
store -- ``SECURITY_BASELINE.md`` §2 -- and material that arrives that way is
visible to anything that can read this process's environment, so the mechanism is
permitted only where nothing real is at stake.

Here rather than in the domain because ``live``, ``testnet`` and ``demo`` are all
in ``tests/architecture/test_identifier_discipline.py``'s ``VENUE_VOCABULARY`` and
are refused as a live constant anywhere under :mod:`globin.domain`.
"""


def environment_provider_policy() -> dict[str, tuple[str, ...]]:
    """The profile allow-list, in the shape the domain predicate takes.

    Returns:
        Provider value to the profiles that permit it.

    A function rather than a mapping constant so that this module performs no
    call at import, and so that the one provider with a policy is the only one
    named -- :func:`~globin.domain.secrets.provider_permitted` treats a provider
    absent from the mapping as permitted, which is what keeps adding a mechanism
    from silently disabling it.
    """
    return {SecretProviderKind.ENVIRONMENT.value: ENVIRONMENT_PROVIDER_PROFILES}


def build_api_reality_source(repo_root: Path) -> ApiRealitySource:
    """The Binance API reality registry for this run.

    Args:
        repo_root: Where the declaration lives, relative to which the registry is
            found.

    Returns:
        Something satisfying the port. The concrete reader is a detail of this
        function, which is what the composition root is for -- and the annotation
        is what gives the protocol a runtime importer rather than a type-only one.

    Nothing here reaches a network. The registry is a committed document, and
    refreshing it from the venue is a repository-maintenance act performed from
    outside this package.
    """
    return TomlApiRealitySource(path=repo_root / REGISTRY_PATH)


def build_degradation_probe(repo_root: Path) -> ContractDegradationProbe:
    """The degradation survey for this run.

    Args:
        repo_root: Where the declaration lives, relative to which the contract is
            found.

    Returns:
        The probe.

    ``credentials_required`` is derived from
    :func:`~globin.domain.entitlements.required_references` rather than passed,
    so that the moment Phase 039 registers a reference the ``advapi32`` row stops
    being not-applicable and starts being able to refuse a start. Nothing has to
    remember to flip a flag. Phase 035 delivered signing without registering one,
    which is what kept a clean host bootable through a phase that added a
    credential-shaped capability.
    """
    return ContractDegradationProbe(
        contract=repo_root / DEGRADATION_CONTRACT_PATH,
        arms=system_arms(credentials_required=bool(required_references())),
    )


def build_secret_providers(
    state: RuntimeState | None = None,
    *,
    profile: str = DEFAULT_PROFILE,
    locators: tuple[SecretLocator, ...] = (),
    environment: Mapping[str, str] | None = None,
) -> dict[SecretProviderKind, SecretStore]:
    """Every secret mechanism this run has, by kind.

    Args:
        state: The runtime tree, which is where the vault directory lives. Where
            it is absent the vault records that absence rather than guessing a
            path.
        profile: The run's resolved profile, which decides whether the
            environment hand-off is permitted.
        locators: Which mechanism holds which reference.
        environment: The variables the hand-off may read. Handed in, never read
            here.

    Returns:
        One entry per mechanism.

    All three are built every run, and building one is cheap: the Credential
    Manager and the vault are absent-safe factories that answer with a recorded
    state on a host that has neither, and the hand-off holds a boolean. Building
    only the mechanisms a locator names would make the set depend on
    configuration, so ``secrets doctor`` could not report on a mechanism nothing
    currently uses -- which is exactly when an operator asks.
    """
    declared = required_references()
    permitted = provider_permitted(
        SecretProviderKind.ENVIRONMENT, profile, allowed=environment_provider_policy()
    )
    vault_directory = (
        state.root / state.layout.vault if state is not None else Path(VAULT_FALLBACK_SEGMENT)
    )
    return {
        SecretProviderKind.CREDENTIAL_MANAGER: windows_credential_store(declared=declared),
        SecretProviderKind.DPAPI_VAULT: secret_vault(vault_directory, declared=declared),
        SecretProviderKind.ENVIRONMENT: environment_secret_provider(
            environment if environment is not None else {},
            locators,
            permitted=permitted,
        ),
    }


def build_secret_store(
    state: RuntimeState | None = None,
    *,
    profile: str = DEFAULT_PROFILE,
    locators: tuple[SecretLocator, ...] = (),
    environment: Mapping[str, str] | None = None,
) -> SecretStore:
    """The secret store this run has, routed by locator.

    Args:
        state: The runtime tree, for the vault's directory.
        profile: The run's resolved profile.
        locators: Which mechanism holds which reference.
        environment: The variables the hand-off may read.

    Returns:
        A store that reaches **exactly one** mechanism per reference, with no
        fallback between them.

    **Every argument defaults**, so ``build_secret_store()`` with none still
    returns a store whose only reachable mechanism for an unlocated reference is
    the Credential Manager -- which is what every existing caller gets and what it
    got before Phase 031.

    The declared references are fed in from
    :func:`~globin.domain.entitlements.required_references`, which is what
    ``inventory`` resolves one at a time. Empty today, so the inventory is empty
    -- the mechanism exists and the set does not.
    """
    return ProviderRoutedStore(
        providers=build_secret_providers(
            state, profile=profile, locators=locators, environment=environment
        ),
        locators={locator.reference: locator for locator in locators},
        default=DEFAULT_PROVIDER,
    )


def build_grant_register(state: RuntimeState) -> GrantRegister:
    """Where declarations about credentials are kept.

    Args:
        state: The runtime state, for its atomically publishing store.

    Returns:
        The register, in the user-local state area.

    Deliberately not ``.globin/``: that tree is evidence about this repository
    and CI reads it, and this is state about this machine.
    """
    return StateGrantRegister(store=state.store)


def build_secret_entry(stream: TextIO) -> SecretEntry:
    """How GLOBIN asks a person for a credential.

    Args:
        stream: Where the prompt is written. Standard error, so a command
            rendering a document to standard output stays machine-readable.

    Returns:
        A console entry bound to the real standard input.

    :data:`sys.stdin` is read here rather than captured as a default argument,
    which would bind it at import -- the same rule every builder in this module
    follows.
    """
    return ConsoleSecretEntry(stream=stream, stdin=sys.stdin)


def build_bootstrap(
    start: Path,
    sources: Sequence[ConfigurationSource] | None = None,
    runtime_state: RuntimeState | None = None,
    profile: str | None = None,
    explicit: Path | None = None,
    overrides: Mapping[str, str] | None = None,
) -> Bootstrap:
    """Wire the bootstrap against wherever the project turns out to be.

    Args:
        start: Where to begin the search for the project root — normally the
            working directory. Passed in rather than read from :func:`os.getcwd`
            so that the search is testable and so that this function keeps the
            property every builder here has: it is told what it cannot know.
        sources: Configuration sources, weakest first. Defaults to the real chain
            :func:`build_config_sources` assembles for the resolved profile — the four
            documents, then the environment.
        runtime_state: The wired mutable tree. Defaults to
            :func:`build_runtime_state`, which is where it comes from in
            production; a test supplies one rooted in a temporary directory so
            that running the suite never touches a real user profile.
        profile: The resolved profile, which decides which two documents are named.
        explicit: A document named on the command line, or ``None``.
        overrides: Values a launcher set with ``--set``, or ``None``.

    Returns:
        The wired :class:`Bootstrap`.

    **The default changed in Phase 027, and the old one was a hole rather than a
    simplification.** Until this phase the honest answer was "no sources", because
    none existed; the consequence was that `bootstrap check` validated the *declared
    defaults* rather than the configuration the process would actually run on. A
    document or a variable that `as_config` refuses would have passed preflight and
    then failed at start-up — which is the precise inversion of what a fail-closed
    gate is for. The gate now resolves what a run resolves.

    **Unlike every other builder in this module, this one reads the filesystem.**
    The others open nothing because their adapters record a path and read it when
    the use case runs; this one cannot, because *where the project is* is the
    thing every probe below has to be told, and deferring the search would only
    move the same read one call later while leaving each probe to answer it
    separately. The read is one bounded upward walk, and it is the first thing
    the bootstrap is for.
    """
    root = find_project_root(start.resolve())
    state = build_runtime_state() if runtime_state is None else runtime_state
    selected = resolve_run_profile() if profile is None else profile
    chain = (
        build_config_sources(root, selected, explicit=explicit, overrides=overrides)
        if sources is None
        else tuple(sources)
    )
    return Bootstrap(
        pipeline=BootstrapPipeline(
            baseline=TomlRuntimeBaselineSource(
                path=(root or start) / RUNTIME_CONTRACT_PATH,
            ),
            host=SystemHostProbe(root=root),
            project=FilesystemProjectProbe(
                location=root,
                started_from=start.resolve(),
                version_from_package=globin.__version__,
            ),
            dependencies=DeclaredDependencyProbe(
                project_file=(root or start) / PROJECT_MANIFEST,
                lock_file=(root or start) / RUNTIME_LOCK,
                installed=installed_versions,
            ),
            environment=SystemEnvironmentProbe(
                api=windows_system_api(),
                toolchain=PathToolchainProbe(),
                declared=DECLARED_TOOLCHAIN,
            ),
            secrets=StoreBackedSecrets(
                store=windows_credential_store(declared=required_references()),
                required=required_references(),
            ),
            entitlements=RegisterBackedEntitlements(
                register=StateGrantRegister(store=state.store),
                requirements=required_credentials(),
            ),
            degradation=build_degradation_probe(root or start),
            tree=ProjectRuntimeTree(root=root or start),
            runtime_tree=state.tree,
            state=state.store,
            lock=state.lock,
            layout=state.layout,
            configuration_sources=tuple(chain),
        ),
        root=root,
        paths=RuntimePaths(),
    )


def project_identity() -> ProjectIdentity | None:
    """Which GLOBIN this is, without needing to find the project first.

    Returns:
        The name, version and where the version came from, or ``None`` when
        neither installed metadata nor the imported package could supply one.

    ``globin --version`` must work from anywhere, including from an installed
    distribution with no checkout in sight, so it deliberately does not depend on
    the root search succeeding.
    """
    return FilesystemProjectProbe(
        location=None,
        started_from=Path(),
        version_from_package=globin.__version__,
    ).identity()


HEALTH_SNAPSHOT_FILE: Final[str] = "health-snapshot.json"
"""Where a published health snapshot is written inside the state area."""

BUNDLE_DIRECTORY: Final[str] = "support"
"""Where support bundles are published, inside the cache area.

``cache`` rather than ``state``, and the choice is argued in
``docs/engineering/SUPPORT_BUNDLE.md``: a bundle is a bounded, reproducible
artefact an operator may delete without breaking anything, whereas ``state`` holds
the small documents a run publishes atomically about itself. No sixth
:class:`~globin.domain.runtime_state.RuntimeArea` is added.
"""

BUNDLE_MANIFEST_MEMBER: Final[str] = "manifest.json"
"""What the manifest is called inside a bundle."""

BUNDLE_REPORT_MEMBER: Final[str] = "report.txt"
"""What the generation report is called inside a bundle."""

BUNDLE_SNAPSHOT_MEMBER: Final[str] = "snapshot.json"
"""What the health snapshot is called inside a bundle."""


def build_health_collector(
    state: RuntimeState,
    *,
    config: GlobinConfig | None = None,
    logger: Logger | None = None,
    clock: Clock | None = None,
    monotonic: MonotonicClock | None = None,
    started: MonotonicReading | None = None,
    logging_state: DiagnosticsStateProbe | None = None,
) -> HealthCollector:
    """Assemble the collector that takes one health snapshot.

    Args:
        state: The runtime tree, store and lock.
        config: Resolved configuration, defaulting to the declared defaults.
        logger: Where a contained check failure is reported.
        clock: The wall clock.
        monotonic: The monotonic clock.
        started: When the process started, defaulting to now — which makes a
            snapshot taken by a short-lived command report a near-zero uptime
            rather than a wrong one.
        logging_state: What the diagnostics subsystem will say about itself.

    Returns:
        The collector.

    Every probe is chosen here and nowhere else, which is what makes the
    psutil-shaped hole invisible to everything above: the collector is handed a
    :class:`~globin.ports.health.ProcessProbe` and never learns whether the one it
    got reads a process table or records that it could not.
    """
    settings = default_config() if config is None else config
    reader = SystemMonotonicClock() if monotonic is None else monotonic
    return HealthCollector(
        clock=SystemClock() if clock is None else clock,
        monotonic=reader,
        thresholds=settings.diagnostics.thresholds(),
        platform_probe=SystemPlatformProbe(),
        process_probe=system_process_probe(),
        host_probe=system_host_probe(),
        tree_probe=FilesystemTreeProbe(root=state.root, layout=state.layout),
        lifecycle_probe=StateLifecycleProbe(
            store=state.store,
            lock=state.lock,
            area=RuntimeArea.STATE,
            lifecycle_file=LIFECYCLE_FILE,
            instance_file=INSTANCE_FILE,
        ),
        logging_probe=DiagnosticsStateProbe() if logging_state is None else logging_state,
        thread_probe=SystemThreadProbe(),
        memory_probe=TracemallocProbe(),
        logger=build_logger(config=settings) if logger is None else logger,
        started=reader.reading() if started is None else started,
        anchors=runtime_anchors(state),
    )


def runtime_anchors(state: RuntimeState) -> tuple[str, ...]:
    """Every distinct filesystem behind the runtime tree.

    Args:
        state: The runtime tree.

    Returns:
        One anchor per filesystem, deduplicated and sorted.

    Deduplicated because the five areas normally sit on one drive: asking each
    separately would run five identical syscalls and publish five identical
    answers, inviting a reader to believe five filesystems had been checked.
    """
    anchors = {
        (state.root / state.layout.segment_for(area)).anchor or str(state.root)
        for area in state.layout.areas()
    }
    return tuple(sorted(anchor for anchor in anchors if anchor))


def build_bundle_builder(
    state: RuntimeState,
    *,
    config: GlobinConfig | None = None,
    logger: Logger | None = None,
    name: str = "globin-support.zip",
) -> tuple[BundleBuilder, Path]:
    """Assemble the builder that publishes one support bundle.

    Args:
        state: The runtime tree, for where the bundle lands and what goes in it.
        config: Resolved configuration, for the limits.
        logger: Where the outcome is reported.
        name: The archive's filename.

    Returns:
        The builder and the path it will publish to.
    """
    settings = default_config() if config is None else config
    destination = state.root / state.layout.segment_for(RuntimeArea.CACHE) / BUNDLE_DIRECTORY / name
    writer = ZipArchiveWriter(path=destination, operations=FileOperations())
    return (
        BundleBuilder(
            writer=writer,
            limits=settings.diagnostics.limits(),
            logger=build_logger(config=settings) if logger is None else logger,
            render=render_state_document,
            digest=digest_of,
        ),
        destination,
    )


def bundle_candidates(state: RuntimeState, snapshot_bytes: bytes) -> tuple[Candidate, ...]:
    """Every file the allowlist permits in a bundle, in budget order.

    Args:
        state: The runtime tree the files live under.
        snapshot_bytes: The canonical health snapshot, already rendered.

    Returns:
        The candidates, smallest and most valuable first.

    **This table is the allowlist**, and there is no directory walk anywhere. The
    rotated logs are the one group not written out name by name, and they are still
    bounded — by the rotation policy's own backup count — and every member name is
    built through :func:`~globin.domain.support.safe_member_name` rather than taken
    from a directory listing.
    """
    state_area = state.root / state.layout.segment_for(RuntimeArea.STATE)
    logs_area = state.root / state.layout.segment_for(RuntimeArea.LOGS)
    candidates: list[Candidate] = [
        Candidate(
            member=BUNDLE_SNAPSHOT_MEMBER,
            kind=ArtifactKind.SNAPSHOT,
            read=_constant(snapshot_bytes),
        ),
        Candidate(
            member=safe_member_name("state", LIFECYCLE_FILE),
            kind=ArtifactKind.LIFECYCLE,
            read=_reader(state_area / LIFECYCLE_FILE),
        ),
        Candidate(
            member=safe_member_name("state", DIAGNOSTICS_FILE),
            kind=ArtifactKind.DIAGNOSTICS,
            read=_reader(state_area / DIAGNOSTICS_FILE),
        ),
        Candidate(
            member=safe_member_name("logs", FAULT_FILE_NAME),
            kind=ArtifactKind.FAULT,
            read=_reader(logs_area / FAULT_FILE_NAME),
        ),
        Candidate(
            member=safe_member_name("logs", LOG_FILE_NAME),
            kind=ArtifactKind.LOG,
            read=_reader(logs_area / LOG_FILE_NAME),
            redactable=True,
        ),
    ]
    for index in range(1, MAXIMUM_BACKUP_COUNT + 1):
        rotated = logs_area / f"{LOG_FILE_NAME}.{index}"
        if not rotated.exists():
            break
        candidates.append(
            Candidate(
                member=safe_member_name("logs", f"{LOG_FILE_NAME}.{index}"),
                kind=ArtifactKind.ROTATED_LOG,
                read=_reader(rotated),
                redactable=True,
            )
        )
    return tuple(candidates)


def _constant(payload: bytes) -> Callable[[], bytes]:
    """A reader for content already in hand.

    Args:
        payload: The bytes.

    Returns:
        A callable returning them.
    """

    def read() -> bytes:
        return payload

    return read


def _reader(path: Path) -> Callable[[], bytes]:
    """A reader for one file, which raises rather than inventing content.

    Args:
        path: What to read.

    Returns:
        A callable returning the bytes.

    The collector catches the failure and records an exclusion reason, so a file
    that is absent, locked or not a regular file is reported rather than silently
    replaced with nothing.
    """

    def read() -> bytes:
        return path.read_bytes()

    return read


WATCHDOG_FILE: Final[str] = "watchdog.json"
"""Where a stall incident is published inside the state area.

Deliberately **not** a support-bundle candidate, and that absence is the answer to
Phase 024's refusal to put stacks in the health surface. The objection there was
about travel: a health snapshot goes into a bundle and from there to whoever an
operator sends it to. This document is a local post-mortem in the user-local
runtime tree, and ``tests/contract`` asserts it stays out of
:func:`bundle_candidates`.
"""


def build_heartbeats(monotonic: MonotonicClock | None = None) -> SharedHeartbeatRegistry:
    """The heartbeat table every monitored component reports into.

    Args:
        monotonic: The clock a beat is stamped with.

    Returns:
        The registry, which satisfies both watchdog heartbeat ports.

    Built separately from the watchdog because its lifetime is different: a
    component registers once at wiring time, and the watchdog may be armed and
    stood down around it.
    """
    return heartbeats(build_monotonic_clock() if monotonic is None else monotonic)


def build_watchdog(
    state: RuntimeState,
    beats: SharedHeartbeatRegistry,
    *,
    run_id: str,
    correlation_id: str,
    config: GlobinConfig | None = None,
    logger: Logger | None = None,
    clock: Clock | None = None,
    monotonic: MonotonicClock | None = None,
    faults: IO[str] | None = None,
    terminator: ProcessTerminator | None = None,
    new_incident_id: Callable[[], str] | None = None,
) -> WatchdogThread:
    """The watchdog, wired to this runtime tree and not started.

    Args:
        state: The runtime tree its incident is published into.
        beats: The heartbeat table it reads.
        run_id: Which run this is.
        correlation_id: The run's correlation identifier.
        config: Where the thresholds come from.
        logger: Where its records go.
        clock: The wall clock, read once per incident.
        monotonic: The clock every elapsed quantity is measured on.
        faults: An already-open fault file for the native dump. ``None`` when
            diagnostics were never started, which the collector records rather than
            treats as an error.
        terminator: What ends the process. Substituted in tests so that no test
            ever kills the runner.
        new_incident_id: Mints an incident identifier.

    Returns:
        The thread, **not started**. Starting it creates a thread and arms a
        mechanism that can end the process, which is a decision for the caller that
        owns the process — the same rule :func:`build_diagnostics` follows.
    """
    settings = default_config() if config is None else config
    resolved_logger = build_logger(config=settings) if logger is None else logger
    cycle = RuntimeWatchdog(
        monotonic=build_monotonic_clock() if monotonic is None else monotonic,
        clock=build_clock() if clock is None else clock,
        beats=beats,
        policy=settings.watchdog.policy(),
        evidence=ProcessStackEvidence(handle=faults),
        signals=state.signals,
        terminator=ImmediateProcessExit() if terminator is None else terminator,
        logger=resolved_logger,
        run_id=run_id,
        correlation_id=correlation_id,
        new_incident_id=new_correlation_id if new_incident_id is None else new_incident_id,
        episode=WatchdogEpisode(),
        publish=_watchdog_publisher(state),
        enabled=settings.watchdog.enabled,
        escalation_enabled=settings.watchdog.escalation_enabled,
    )
    return WatchdogThread(
        cycle=cycle,
        wake=threading.Event(),
        interval_seconds=settings.watchdog.interval_millis / MILLISECONDS_PER_SECOND,
        logger=resolved_logger,
    )


def _watchdog_publisher(state: RuntimeState) -> Callable[[Mapping[str, object]], None]:
    """How a stall incident reaches disk.

    Args:
        state: The runtime tree.

    Returns:
        A callable that publishes atomically.

    It takes no notice of ``watchdog.escalation_enabled``, and the omission is the
    decision: that switch changes whether the process is ended, never whether the
    evidence is kept. An operator who turned the killing off still wants to know
    what happened — arguably more, since nothing else will tell them.
    """

    def publish(document: Mapping[str, object]) -> None:
        state.store.publish(RuntimeArea.STATE, WATCHDOG_FILE, document)

    return publish


def build_metric_store(logger: Logger | None = None) -> MetricStore:
    """The one registry every measurement is recorded into.

    Args:
        logger: Where a dropped observation is announced. Defaults to one writing to
            standard error.

    Returns:
        The store, which satisfies both telemetry ports at once.

    **One store, and this is the function that makes "one" true.** Phase 026 built the
    store and the two ports but wired neither, so nothing in the product had a
    registry; a phase wanting to record something would have constructed its own, and
    two registries is two answers to "what has this process measured". Phase 027 needs
    a registry for the diagnostics surface, so it builds the shared one rather than a
    private one.

    It records and exports nothing. No pump, no thread, no exporter — those stay
    ADR-0068's "off is an object graph rather than a flag", and a later phase that wants
    delivery builds it beside this rather than inside it.
    """
    return metric_store(build_logger() if logger is None else logger)


def build_diagnostics_endpoint(
    state: RuntimeState,
    signals: ShutdownSignals,
    *,
    run_id: str,
    correlation_id: str,
    config: GlobinConfig | None = None,
    store: MetricStore | None = None,
    logger: Logger | None = None,
    clock: Clock | None = None,
    monotonic: MonotonicClock | None = None,
    started: MonotonicReading | None = None,
    version: str = "",
    profile: str = DEFAULT_PROFILE,
    config_fingerprint_value: str = "",
    context_fingerprint: str = "",
    spawn: Callable[..., Any] | None = None,
) -> tuple[DiagnosticsEndpoint, ReadinessGate]:
    """The diagnostics surface, wired to this runtime and **not started**.

    Args:
        state: The runtime tree the health collector reads.
        signals: Where a stop request arrives, which is what liveness and readiness
            both read.
        run_id: Which run this is.
        correlation_id: The run's correlation identifier.
        config: Where the settings come from.
        store: The metric registry. Defaults to a fresh one, which is right for a
            command and wrong for a run — a run passes the shared store so that what
            the surface reports is what the process measured.
        logger: Where its records go.
        clock: The wall clock, for snapshot stamps.
        monotonic: The clock durations and uptime are measured on.
        started: The reading taken when the process started.
        version: This GLOBIN's version, for the health document.
        profile: The resolved profile.
        config_fingerprint_value: A digest over the resolved configuration.
        context_fingerprint: The bootstrap's own fingerprint.
        spawn: How a thread is created. Substituted in tests.

    Returns:
        The endpoint and the readiness gate. **Two values, because the caller needs
        both**: the endpoint is started and stopped, and the gate is what the run
        advances once its start-up has finished. Returning only the endpoint would
        leave a process that can never report itself ready.

    Raises:
        ValidationError: If the configured address is not loopback, or a bound is
            outside its permitted range. Raised **here**, before a socket exists, which
            is what makes the surface fail closed: there is no path on which an invalid
            configuration produces a listening server.

    **This binds nothing.** Building the graph opens no socket;
    :meth:`~globin.adapters.diagnostics_http.DiagnosticsEndpoint.start` does, and only
    when a caller asks. A caller that finds ``config.diagnostics_http.enabled`` false
    should not call this at all — but calling it and never starting it is also safe,
    which is the property every builder in this module has.
    """
    settings = default_config() if config is None else config
    surface = settings.diagnostics_http
    policy = surface.policy()
    records = build_logger(config=settings) if logger is None else logger
    wall = build_clock() if clock is None else clock
    ticks = build_monotonic_clock() if monotonic is None else monotonic
    origin = ticks.reading() if started is None else started
    registry = build_metric_store(records) if store is None else store
    collector = build_health_collector(
        state, config=settings, logger=records, clock=wall, monotonic=ticks, started=origin
    )
    health = CachedHealthProjection(
        take=lambda: snapshot_document(
            collector.snapshot(
                correlation_id=correlation_id,
                run_id=run_id,
                version=version,
                profile=profile,
                config_fingerprint=config_fingerprint_value,
                context_fingerprint=context_fingerprint,
            )
        ),
        monotonic=ticks,
    )
    exposition = TelemetryExposition(
        source=registry, clock=wall, monotonic=ticks, started=origin, run_id=run_id
    )
    gate = ReadinessGate(signals=signals)
    service = DiagnosticsService(
        surface=surface,
        liveness=ShutdownLiveness(signals=signals),
        readiness=gate,
        health=health,
        snapshot=DiagnosticsSnapshotProjection(health=health, exposition=exposition),
        exposition=exposition,
        recorder=registry,
        logger=records,
        monotonic=ticks,
    )
    endpoint = DiagnosticsEndpoint(
        service=service,
        policy=policy,
        recorder=registry,
        logger=records,
        workers=[],
        spawn=threading.Thread if spawn is None else spawn,
    )
    return endpoint, gate


PROVISIONING_LOCK_FILE: Final[str] = "provisioning.lock"
"""The lock a mutating provisioning run holds.

Beside ``instance.lock`` in the same area, and deliberately **not** that lock. The
coordinator's is a whole-application mutex; a ``setup`` holding it would make its
own ``instance.lock`` check fail against itself, so this is a second
:class:`~globin.adapters.runtime_state.WindowsInstanceLock` with a different name
and the same mechanism. No second adapter, and no second idea of what holding a
lock means.
"""


@dataclass(frozen=True, slots=True)
class Provisioning:
    """A wired provisioning surface.

    Args:
        bootstrap: The wired bootstrap this composes. Not a second pipeline.
        planner: How a plan is produced. Read-only.
        applier: How a plan is applied, or ``None`` for a read-only wiring.
        claim: How a half-built environment is marked.
        capability: How the host's tools are discovered.
        root: Where the project was found, or ``None``.
        paths: The declared runtime tree inside the project.
    """

    bootstrap: Bootstrap
    planner: ProvisioningPlanRun
    applier: ProvisioningApply | None
    claim: MarkerEnvironmentClaim
    capability: CapabilityProbe
    root: Path | None
    paths: RuntimePaths

    def propose(self) -> ProvisioningProposal:
        """Measure the host and say what would change.

        Returns:
            The proposal. Nothing is written.
        """
        return self.planner.run()

    def setup(self) -> ProvisioningOutcome:
        """Bring missing pieces into existence.

        Returns:
            What was done.

        Raises:
            InternalError: If this surface was wired read-only. A caller reaching
                a mutating verb through a read-only wiring has a bug, not bad
                input.
        """
        return self._applier().setup()

    def repair(self, *, recreate: bool = False) -> ProvisioningOutcome:
        """Correct what exists and is wrong.

        Args:
            recreate: Whether the destructive rebuild is permitted.

        Returns:
            What was done.

        Raises:
            InternalError: If this surface was wired read-only.
        """
        return self._applier().repair(recreate=recreate)

    def outstanding(self) -> ProvisioningPlan | None:
        """What an interrupted run left behind, if anything.

        Returns:
            The claim a previous run did not release, or ``None``.
        """
        return self.claim.outstanding()

    def _applier(self) -> ProvisioningApply:
        """The applier, refused when this surface is read-only."""
        if self.applier is None:
            msg = "this provisioning surface was wired read-only and cannot apply a plan"
            raise InternalError(msg)
        return self.applier


def build_process_runner(root: Path, *, read_only: bool) -> ProcessRunner:
    """How child processes are started for one command.

    Args:
        root: Where a child runs.
        read_only: Whether to permit only the declared probes.

    Returns:
        The runner.

    **A read-only command gets a runner that refuses anything but a probe**, in
    production and not only under test. That is what makes ``bootstrap check``
    and ``bootstrap plan`` read-only by construction rather than by review: an
    edit that made the planner try to build something would raise at the runner
    instead of building it.
    """
    runner = BoundedProcessRunner(working_directory=root)
    if read_only:
        return ReadOnlyProcessRunner(inner=runner)
    return runner


def build_provisioning(
    start: Path,
    *,
    policy: NetworkPolicy = NetworkPolicy.OFFLINE,
    read_only: bool = True,
    recreate: bool = False,
    sources: Sequence[ConfigurationSource] | None = None,
    runtime_state: RuntimeState | None = None,
    profile: str | None = None,
    explicit: Path | None = None,
    overrides: Mapping[str, str] | None = None,
) -> Provisioning:
    """Wire the provisioning surface against wherever the project turns out to be.

    Args:
        start: Where to begin the search for the project root.
        policy: What this run may reach. Defaults to
            :attr:`~globin.domain.provisioning.NetworkPolicy.OFFLINE`, because the
            one command that mutates a host must not also be the one that reaches
            the network without being asked.
        read_only: Whether to wire a runner that refuses anything but a probe.
        recreate: Whether a destructive rebuild may be planned.
        sources: Configuration sources, weakest first.
        runtime_state: The wired mutable tree.
        profile: Which profile to resolve.
        explicit: An explicit configuration document.
        overrides: Command-line configuration values.

    Returns:
        The wired surface.

    **This calls :func:`build_bootstrap` rather than re-wiring fourteen probes.**
    Wiring the pipeline separately would create a second way to assemble the same
    thing, and the two would drift --- the reason :meth:`Bootstrap.preflight`
    gives about itself.
    """
    state = build_runtime_state() if runtime_state is None else runtime_state
    bootstrap = build_bootstrap(
        start,
        sources=sources,
        runtime_state=state,
        profile=profile,
        explicit=explicit,
        overrides=overrides,
    )
    working = bootstrap.root if bootstrap.root is not None else start
    runner = build_process_runner(working, read_only=read_only)
    capability = PathToolProbe(runner=runner)
    planner = ProvisioningPlanRun(
        pipeline=bootstrap.pipeline,
        capabilities=capability,
        policy=policy,
        recreate=recreate,
    )
    claim = MarkerEnvironmentClaim(
        writer=AtomicDocumentWriter(operations=FileOperations()),
        root=state.root,
        layout=state.layout,
    )
    applier: ProvisioningApply | None = None
    if not read_only:
        applier = ProvisioningApply(
            proposal=planner,
            executor=RuntimeTreeExecutor(tree=state.tree, layout=state.layout),
            claim=claim,
            lock=WindowsInstanceLock(
                root=state.root, layout=state.layout, name=PROVISIONING_LOCK_FILE
            ),
        )
    return Provisioning(
        bootstrap=bootstrap,
        planner=planner,
        applier=applier,
        claim=claim,
        capability=capability,
        root=bootstrap.root,
        paths=bootstrap.paths,
    )
