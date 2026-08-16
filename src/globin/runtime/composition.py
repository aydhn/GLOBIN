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

These functions build; they do not choose. Which configuration sources exist and
in what order they are consulted is Phase 027's decision, and a composition root
that grew branching logic about *what* to construct would be the failure
ADR-0015 names in its own risk section.
"""

import os
import signal
import sys
import types
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

import globin
from globin.adapters.architecture import AstModuleImportSource, TomlArchitectureContractSource
from globin.adapters.bootstrap import PROJECT_FILE as PROJECT_MANIFEST
from globin.adapters.bootstrap import (
    RUNTIME_CONTRACT_PATH,
    RUNTIME_LOCK,
    DeclaredDependencyProbe,
    FilesystemProjectProbe,
    NoSecretsRequired,
    ProjectRuntimeTree,
    SystemHostProbe,
    TomlRuntimeBaselineSource,
    find_project_root,
    installed_distributions,
    write,
)
from globin.adapters.clock import SystemClock, SystemMonotonicClock
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
from globin.adapters.observability import StreamLogSink, ThresholdLogSink, new_correlation_id
from globin.adapters.runtime_state import (
    AtomicStateStore,
    FileOperations,
    PlatformShutdownSignals,
    WindowsInstanceLock,
    register_last_resort,
    resolve_root,
    system_environment,
)
from globin.adapters.runtime_state import ProjectRuntimeTree as UserRuntimeTree
from globin.adapters.serialization import JsonCodec
from globin.application.architecture_review import ArchitectureReview
from globin.application.bootstrap import BootstrapPipeline
from globin.application.configuration import ConfigurationResolution
from globin.application.lifecycle import Lifecycle
from globin.application.observability import Logger
from globin.domain.bootstrap import (
    BootstrapOutcome,
    ProjectIdentity,
    RecordedPath,
    RuntimeContext,
    RuntimePaths,
)
from globin.domain.configuration import GlobinConfig, default_config
from globin.domain.runtime_state import LOCK_FILE, RuntimeArea, RuntimeLayout
from globin.errors import ConfigurationError
from globin.ports.clock import Clock, MonotonicClock
from globin.ports.configuration import ConfigurationSource
from globin.ports.serialization import Codec

CONTRACT_RELATIVE_PATH: Final[str] = "docs/architecture/dependency-rules.toml"
"""Where the declared contract lives, relative to the repository root."""

PACKAGE_RELATIVE_PATH: Final[str] = "src/globin"
"""Where the package source lives, relative to the repository root."""

ROOT_PACKAGE: Final[str] = "globin"
"""The import namespace the review is scoped to."""

DEFAULT_PROFILE: Final[str] = "default"
"""The profile name recorded until Phase 026 defines any.

A literal rather than a lookup, and named rather than left blank, because the
instance record has a field for it and an empty one would read as "no profile"
rather than as "profiles do not exist yet". Phase 026 decides what a profile is
and Phase 027 decides how one is selected; this is what the field says until
then."""


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

    Nothing in GLOBIN measures an elapsed interval yet. This exists because
    ``ROADMAP.md`` gives Phase 009 "monotonic clocks" by name, and because the
    decision worth fixing now is *which* guarantee an elapsed measurement rests
    on — not the first call site, which arrives with the code that needs it.
    """
    return SystemMonotonicClock()


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


def build_bootstrap(
    start: Path,
    sources: Sequence[ConfigurationSource] | None = None,
    runtime_state: RuntimeState | None = None,
) -> Bootstrap:
    """Wire the bootstrap against wherever the project turns out to be.

    Args:
        start: Where to begin the search for the project root — normally the
            working directory. Passed in rather than read from :func:`os.getcwd`
            so that the search is testable and so that this function keeps the
            property every builder here has: it is told what it cannot know.
        sources: Configuration sources, weakest first. Until Phase 027 decides
            which of them exist, the honest answer is none, which resolves to the
            declared defaults.
        runtime_state: The wired mutable tree. Defaults to
            :func:`build_runtime_state`, which is where it comes from in
            production; a test supplies one rooted in a temporary directory so
            that running the suite never touches a real user profile.

    Returns:
        The wired :class:`Bootstrap`.

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
                installed=installed_distributions,
            ),
            secrets=NoSecretsRequired(),
            tree=ProjectRuntimeTree(root=root or start),
            runtime_tree=state.tree,
            state=state.store,
            lock=state.lock,
            layout=state.layout,
            configuration_sources=() if sources is None else tuple(sources),
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
