"""The bootstrap pipeline: the order the checks run in, and where a run stops.

One use case, holding six probes and a configuration source list, producing a
:class:`~globin.domain.bootstrap.BootstrapOutcome`. It reads nothing itself —
every fact arrives through a port — so the whole sequence is exercised from
literals and no test needs a broken machine to prove that a broken machine is
refused.

**Two modes, and the difference is the whole doctor/gate distinction.** A gate
stops at the first refusal, because everything after it would be judging a host
that has already been rejected and because a caller wants the *earliest* cause
rather than a list. A diagnostic keeps going, because the person running it wants
the whole picture and can read past the first line. Same pipeline, same
judgements, same report type: only the stopping rule differs, which is what stops
``doctor`` and ``bootstrap check`` from drifting into two descriptions of the
same host.

**Fail-closed is a property of the type rather than of this function.**
:class:`~globin.domain.bootstrap.BootstrapOutcome` refuses to hold a context
unless the report is ready, so a run that failed cannot hand anything downstream
even if this module tried. Nothing here starts a worker, opens a connection or
schedules anything, and nothing can, because the object that would authorise it
does not exist until every check has passed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from globin.application.configuration import ConfigurationResolution
from globin.domain.bootstrap import (
    BootstrapOutcome,
    BootstrapReport,
    CheckOutcome,
    CheckStatus,
    DependencyReadiness,
    HostFacts,
    InterpreterFacts,
    PathLocation,
    ProjectIdentity,
    RecordedPath,
    RuntimeBaseline,
    RuntimeContext,
    RuntimePaths,
    SecretReadiness,
    architecture_outcome,
    capability_outcome,
    configuration_outcome,
    context_fingerprint,
    dependency_outcome,
    environment_outcome,
    host_outcome,
    identity_outcome,
    implementation_outcome,
    paths_outcome,
    ready_outcome,
    root_outcome,
    secrets_outcome,
    version_outcome,
)
from globin.domain.configuration import GlobinConfig
from globin.domain.environment import EnvironmentCapabilitySnapshot
from globin.domain.runtime_state import (
    LIFECYCLE_FILE,
    LifecycleRecord,
    RuntimeArea,
    RuntimeLayout,
    boundary_outcome,
    lock_outcome,
    persistence_outcome,
    previous_run_outcome,
    read_lifecycle,
)
from globin.errors import ConfigurationError, GlobinError
from globin.ports.bootstrap import (
    DependencyProbe,
    EnvironmentProbe,
    HostProbe,
    ProjectProbe,
    RuntimeBaselineSource,
    RuntimeTree,
    SecretProbe,
)
from globin.ports.configuration import ConfigurationSource
from globin.ports.runtime_state import InstanceLock, RuntimeTreeSource, StateStore
from globin.project_contract import PACKAGE_NAME

PROBE_DOCUMENT: Final[str] = "persistence-probe.json"
"""What the persistence check writes, and then removes.

A real publication rather than an inspection of permissions. A directory that
reports itself writable and then refuses :func:`os.replace` is exactly the case an
inspection misses, and it is the case that matters — the whole state mechanism is
a replace.
"""

UNMEASURED_REMEDIATION: dict[str, str] = {
    "runtime.host": "Fix the declaration this check reads, then run again.",
    "runtime.architecture": "Fix the declaration this check reads, then run again.",
    "environment.capability": "Fix the declaration this check reads, then run again.",
    "python.implementation": "Fix the declaration this check reads, then run again.",
    "python.version": "Fix the declaration this check reads, then run again.",
    "python.environment": "Fix the declaration this check reads, then run again.",
    "project.identity": "Find the project root first; identity is read from underneath it.",
    "dependency.lock": "Find the project root first; the lock is read from underneath it.",
    "config.valid": "Find the project root first; configuration is read from underneath it.",
    "paths.runtime": "Find the project root first; the runtime tree hangs off it.",
    "paths.boundary": "Resolve the runtime root first; there is nothing to bound without one.",
    "state.persistence": "Make the runtime tree usable first; nothing can be written until it is.",
    "state.previous_run": "Make the runtime tree usable first; the record is read from inside it.",
    "instance.lock": "Make the runtime tree usable first; the lock file lives inside it.",
    "secrets.required": "Resolve the earlier refusal first.",
}
"""What to tell an operator when a check could not run at all.

Every entry names the thing to fix rather than the thing that broke, because a
check that never ran has nothing of its own to report. Keyed by identifier so
that a check added by a later phase must supply its own sentence rather than
inherit a vague one.
"""


@dataclass(frozen=True, slots=True)
class BootstrapPipeline:
    """Runs every registered check, in the declared order.

    Args:
        baseline: Supplies the contract the host is judged against.
        host: Observes the machine and the interpreter.
        project: Locates the project and reads its identity.
        dependencies: Reports what is declared, locked and installed.
        environment: Reports what this host is capable of, beyond what the
            contract declares. Separate from ``host`` because the two answer
            different questions: one reads the machine's identity, the other
            judges its fitness.
        secrets: Reports whether required references resolve.
        tree: Prepares the declared tree inside the project.
        runtime_tree: Resolves and prepares the user-local mutable tree. Separate
            from ``tree`` because the two answer different questions: one is
            evidence written *about* this repository, the other is state a running
            GLOBIN keeps. Phase 022 separated them.
        state: Publishes and reads the small documents in that tree.
        lock: Decides whether this process may be the machine's one coordinator.
        layout: The declared shape of the mutable tree.
        configuration_sources: Weakest first, strongest last. Empty resolves to
            the declared defaults, which is what GLOBIN uses when an operator has
            said nothing — and, until Phase 027, all there is.

    Frozen and holding no mutable state, so two runs of the same pipeline against
    the same host produce the same report. Nothing is cached between runs either:
    a bootstrap that reused a measurement would be answering about a host as it
    was rather than as it is.
    """

    baseline: RuntimeBaselineSource
    host: HostProbe
    project: ProjectProbe
    dependencies: DependencyProbe
    environment: EnvironmentProbe
    secrets: SecretProbe
    tree: RuntimeTree
    runtime_tree: RuntimeTreeSource
    state: StateStore
    lock: InstanceLock
    layout: RuntimeLayout
    configuration_sources: tuple[ConfigurationSource, ...] = ()

    def run(self, *, stop_at_first_refusal: bool = True) -> BootstrapOutcome:
        """Perform the checks and assemble what they justify.

        Args:
            stop_at_first_refusal: ``True`` for a gate, which stops as soon as a
                check refuses. ``False`` for a diagnostic, which measures
                everything it still can and records the rest as unmeasured.

        Returns:
            The report, the facts it was formed from, and — only when every
            check passed — the assembled
            :class:`~globin.domain.bootstrap.RuntimeContext`.

        Raises:
            InternalError: If a registered check produced no outcome, which
                would mean this function and :data:`CHECKS` disagree about what
                the pipeline does.
        """
        state = _RunState(
            root=RecordedPath(location=PathLocation.ABSENT),
            paths=RuntimePaths(),
            dependency_readiness=DependencyReadiness(),
            secret_readiness=SecretReadiness(),
            runtime_root=RecordedPath(location=PathLocation.ABSENT),
        )
        outcomes: list[CheckOutcome] = []

        for produce in steps():
            outcome = produce(self, state)
            outcomes.append(outcome)
            if outcome.status in {CheckStatus.FAIL, CheckStatus.UNMEASURED}:
                state.refused = True
                if stop_at_first_refusal:
                    break

        if not state.refused or not stop_at_first_refusal:
            outcomes.append(ready_outcome(tuple(outcomes)))

        report = BootstrapReport(outcomes=tuple(outcomes))
        context = self._context(state) if report.ready else None
        return BootstrapOutcome(report=report, context=context, observed=state.observed())

    def _context(self, state: "_RunState") -> RuntimeContext | None:
        """Assemble the context a passing run justifies.

        Args:
            state: What the run observed.

        Returns:
            The context, or ``None`` when a fact it needs is missing — which
            cannot happen after a ready report, and is handled rather than
            asserted so that the type stays honest.
        """
        if (
            state.identity is None
            or state.host_facts is None
            or state.interpreter_facts is None
            or state.config is None
        ):
            return None
        return RuntimeContext(
            identity=state.identity,
            host=state.host_facts,
            interpreter=state.interpreter_facts,
            config=state.config,
            paths=state.paths,
            root=state.root,
            dependencies=state.dependency_readiness,
            secrets=state.secret_readiness,
            runtime_root=state.runtime_root,
            fingerprint=context_fingerprint(
                identity=state.identity,
                host=state.host_facts,
                interpreter=state.interpreter_facts,
                dependencies=state.dependency_readiness,
            ),
        )


@dataclass(slots=True)
class _RunState:
    """What one run has learned so far.

    Mutable and private, because a pipeline is a sequence and each step reads
    what the ones before it found. It never leaves this module: what escapes is
    the frozen :class:`~globin.domain.bootstrap.BootstrapOutcome`.

    The four fields with no default are the ones whose default would have to be
    constructed, and constructing one in a class body is work performed at
    import, which every layer package is forbidden. :meth:`BootstrapPipeline.run`
    builds them instead, where a call is just a call.
    """

    root: RecordedPath
    paths: RuntimePaths
    dependency_readiness: DependencyReadiness
    secret_readiness: SecretReadiness
    runtime_root: RecordedPath
    refused: bool = False
    baseline: RuntimeBaseline | None = None
    baseline_problem: str = ""
    host_facts: HostFacts | None = None
    interpreter_facts: InterpreterFacts | None = None
    identity: ProjectIdentity | None = None
    config: GlobinConfig | None = None
    config_problem: str = ""
    runtime_ready: bool = False
    previous_run: LifecycleRecord | None = None
    environment: EnvironmentCapabilitySnapshot | None = None

    def observed(self) -> dict[str, object]:
        """The facts this run measured, in the shape the evidence carries.

        Returns:
            Host, interpreter, project, dependency, secret, environment and
            runtime sections. Absent measurements are recorded as ``None``
            rather than omitted, so that a reader can tell "not measured" from
            "measured as nothing".

        The ``environment`` section carries the capability snapshot's own record,
        which includes the compatibility fingerprint. It is safe to publish for
        the reason the whole snapshot is: no type in that chain has a field for a
        path, so there is no branch in which one could appear here.
        """
        return {
            "host": None if self.host_facts is None else _host_record(self.host_facts),
            "interpreter": (
                None
                if self.interpreter_facts is None
                else _interpreter_record(self.interpreter_facts)
            ),
            "project": {
                "root": self.root.as_record(),
                "name": None if self.identity is None else self.identity.name,
                "version": None if self.identity is None else self.identity.version,
                "version_source": None if self.identity is None else self.identity.source,
            },
            "paths": self.paths.declared(),
            "dependencies": self.dependency_readiness.as_record(),
            "secrets": self.secret_readiness.as_record(),
            "environment": (None if self.environment is None else self.environment.as_record()),
            "runtime": {
                "root": self.runtime_root.as_record(),
                "usable": self.runtime_ready,
                "previous_run": (
                    None if self.previous_run is None else self.previous_run.as_record()
                ),
            },
        }


def _host_record(facts: HostFacts) -> dict[str, object]:
    """A host's facts as the evidence carries them.

    Args:
        facts: What was observed.

    Returns:
        The four fields, named as the manifest names them.
    """
    return {
        "system": facts.system,
        "release": facts.release,
        "machine": facts.machine,
        "pointer_bits": facts.pointer_bits,
    }


def _interpreter_record(facts: InterpreterFacts) -> dict[str, object]:
    """An interpreter's facts as the evidence carries them.

    Args:
        facts: What was observed.

    Returns:
        The version fields plus the three recorded paths — never an absolute one.
    """
    return {
        "implementation": facts.implementation,
        "version": facts.version,
        "release_level": facts.release_level,
        "free_threaded": facts.free_threaded,
        "executable": facts.executable.as_record(),
        "prefix": facts.prefix.as_record(),
        "base_prefix": facts.base_prefix.as_record(),
        "in_virtual_environment": facts.in_virtual_environment,
    }


def _unmeasured(identifier: str, summary: str) -> CheckOutcome:
    """A check that could not run at all.

    Args:
        identifier: Which check.
        summary: Why it could not run.

    Returns:
        An unmeasured outcome carrying the remediation declared for it.
    """
    return CheckOutcome(
        identifier=identifier,
        status=CheckStatus.UNMEASURED,
        summary=summary,
        remediation=UNMEASURED_REMEDIATION[identifier],
    )


def _baseline_of(pipeline: BootstrapPipeline, state: _RunState) -> RuntimeBaseline | None:
    """Read the declared baseline once, remembering the failure if there was one.

    Args:
        pipeline: The pipeline, for its baseline source.
        state: The run state, which caches the answer.

    Returns:
        The baseline, or ``None`` when it could not be read.
    """
    if state.baseline is not None or state.baseline_problem:
        return state.baseline
    try:
        state.baseline = pipeline.baseline.baseline()
    except (ConfigurationError, OSError) as fault:
        state.baseline_problem = str(fault)
    return state.baseline


def _observed(
    pipeline: BootstrapPipeline, state: _RunState
) -> tuple[RuntimeBaseline, HostFacts, InterpreterFacts] | None:
    """Read the declaration and the machine once, and remember both.

    Args:
        pipeline: The pipeline, for its baseline source and host probe.
        state: The run state, which caches all three.

    Returns:
        The baseline and what was observed, or ``None`` when the declaration
        could not be read — in which case nothing was observed either, because
        there is nothing to judge it against.

    One helper rather than a guard in each of the five steps that need these.
    Each step re-checking whether the facts had already been read produced two
    branches per step, one of which was unreachable: the first step to need a
    fact always populates it, and the only path on which it does not is the one
    where every later step returns early too.
    """
    baseline = _baseline_of(pipeline, state)
    if baseline is None:
        return None
    if state.host_facts is None:
        state.host_facts = pipeline.host.host()
    if state.interpreter_facts is None:
        state.interpreter_facts = pipeline.host.interpreter()
    return baseline, state.host_facts, state.interpreter_facts


def _root_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Find the project root.

    Args:
        pipeline: The pipeline, for its project probe.
        state: The run state, which records what was found.

    Returns:
        The outcome of ``project.root``.
    """
    state.root = pipeline.project.root()
    return root_outcome(state.root, searched_from=pipeline.project.origin())


def _host_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Judge the operating system.

    Args:
        pipeline: The pipeline, for its host probe and baseline source.
        state: The run state.

    Returns:
        The outcome of ``runtime.host``.
    """
    observed = _observed(pipeline, state)
    if observed is None:
        return _unmeasured("runtime.host", state.baseline_problem)
    baseline, host, _interpreter = observed
    return host_outcome(host, baseline)


def _architecture_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Judge the processor architecture.

    Args:
        pipeline: The pipeline, for its host probe and baseline source.
        state: The run state.

    Returns:
        The outcome of ``runtime.architecture``.
    """
    observed = _observed(pipeline, state)
    if observed is None:
        return _unmeasured("runtime.architecture", state.baseline_problem)
    baseline, host, _interpreter = observed
    return architecture_outcome(host, baseline)


def _capability_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Measure this host's capabilities and judge them.

    Args:
        pipeline: The pipeline, for its environment probe.
        state: The run state, for the baseline and to record the snapshot.

    Returns:
        The outcome of ``environment.capability``.

    Unmeasured when the baseline could not be read, because every capability
    here is judged *against* the declaration and a probe with nothing to compare
    against would be reporting on a host rather than on its fitness.
    """
    baseline = _baseline_of(pipeline, state)
    if baseline is None:
        return _unmeasured("environment.capability", state.baseline_problem)
    state.environment = pipeline.environment.snapshot(baseline)
    return capability_outcome(state.environment)


def _implementation_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Judge which Python implementation is running.

    Args:
        pipeline: The pipeline, for its host probe and baseline source.
        state: The run state.

    Returns:
        The outcome of ``python.implementation``.
    """
    observed = _observed(pipeline, state)
    if observed is None:
        return _unmeasured("python.implementation", state.baseline_problem)
    baseline, _host, interpreter = observed
    return implementation_outcome(interpreter, baseline)


def _version_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Judge the interpreter's version.

    Args:
        pipeline: The pipeline, for its host probe and baseline source.
        state: The run state.

    Returns:
        The outcome of ``python.version``.
    """
    observed = _observed(pipeline, state)
    if observed is None:
        return _unmeasured("python.version", state.baseline_problem)
    baseline, _host, interpreter = observed
    return version_outcome(interpreter, baseline)


def _environment_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Judge whether this interpreter is the project's own.

    Args:
        pipeline: The pipeline, for its host and project probes.
        state: The run state.

    Returns:
        The outcome of ``python.environment``.
    """
    observed = _observed(pipeline, state)
    if observed is None:
        return _unmeasured("python.environment", state.baseline_problem)
    baseline, _host, interpreter = observed
    return environment_outcome(interpreter, baseline)


def _identity_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Read which GLOBIN this is.

    Args:
        pipeline: The pipeline, for its project probe.
        state: The run state.

    Returns:
        The outcome of ``project.identity``.
    """
    if state.root.location is PathLocation.ABSENT:
        return _unmeasured("project.identity", "the project root was not found")
    state.identity = pipeline.project.identity()
    return identity_outcome(state.identity, expected_name=PACKAGE_NAME)


def _dependency_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Read what is declared, locked and installed.

    Args:
        pipeline: The pipeline, for its dependency probe.
        state: The run state.

    Returns:
        The outcome of ``dependency.lock``.
    """
    if state.root.location is PathLocation.ABSENT:
        return _unmeasured("dependency.lock", "the project root was not found")
    state.dependency_readiness = pipeline.dependencies.readiness()
    return dependency_outcome(state.dependency_readiness)


def _configuration_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Bind and validate the configuration.

    Args:
        pipeline: The pipeline, for its configuration sources.
        state: The run state.

    Returns:
        The outcome of ``config.valid``.

    Every GLOBIN fault is caught, not only :class:`ConfigurationError`. A source
    is free to raise a validation fault about its own contents, and a bootstrap
    that let one escape would replace a named check failure with a traceback —
    which is the outcome this phase exists to prevent.
    """
    try:
        state.config = ConfigurationResolution(sources=pipeline.configuration_sources).run()
    except (GlobinError, OSError) as fault:
        state.config_problem = str(fault)
        state.config = None
    return configuration_outcome(state.config, problem=state.config_problem)


def _paths_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Prepare the runtime tree.

    Args:
        pipeline: The pipeline, for its runtime tree.
        state: The run state.

    Returns:
        The outcome of ``paths.runtime``.
    """
    if state.root.location is PathLocation.ABSENT:
        return _unmeasured("paths.runtime", "the project root was not found")
    problems = pipeline.tree.prepare(state.paths)
    return paths_outcome(problems, state.paths)


def _boundary_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Resolve the user-local runtime tree and check it stays inside its root.

    Args:
        pipeline: The pipeline, for its runtime tree.
        state: The run state, which records whether the tree became usable.

    Returns:
        The outcome of ``paths.boundary``.

    Every check after this one writes into that tree, so this is the one that
    decides whether they can run at all. A refusal here makes the next three
    unmeasured rather than failed, which is the honest distinction: nothing about
    persistence or locking was established, because there was nowhere to establish
    it.
    """
    try:
        problems = pipeline.runtime_tree.prepare(pipeline.layout)
    except GlobinError as fault:
        return CheckOutcome(
            identifier="paths.boundary",
            status=CheckStatus.FAIL,
            summary=str(fault),
            remediation=(
                "GLOBIN keeps its mutable state under the platform's per-user application "
                "data area. docs/engineering/RUNTIME_FILESYSTEM.md explains how it is found."
            ),
        )
    state.runtime_ready = not problems
    if state.runtime_ready:
        state.runtime_root = pipeline.runtime_tree.recorded_root()
    return boundary_outcome(problems, pipeline.layout)


def _persistence_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Publish a document and remove it, proving the state mechanism works here.

    Args:
        pipeline: The pipeline, for its state store.
        state: The run state.

    Returns:
        The outcome of ``state.persistence``.

    A real write, a real replace and a real removal. Inspecting permissions would
    be cheaper and would miss the case that matters: a directory that reports
    itself writable and then refuses the replace every published document depends
    on.
    """
    if not state.runtime_ready:
        return _unmeasured("state.persistence", "the runtime tree is not usable")
    try:
        pipeline.state.publish(RuntimeArea.STATE, PROBE_DOCUMENT, {"probe": True})
        pipeline.state.discard(RuntimeArea.STATE, PROBE_DOCUMENT)
    except (GlobinError, OSError) as fault:
        return persistence_outcome(str(fault))
    return persistence_outcome("")


def _previous_run_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Read what the last run recorded, without inferring anything about this one.

    Args:
        pipeline: The pipeline, for its state store.
        state: The run state, which remembers the record.

    Returns:
        The outcome of ``state.previous_run``.

    **An open record is a warning, never a refusal.** Whether an instance is
    running is the lock's question and only the lock's; the process that wrote an
    open record may have died a week ago.
    """
    if not state.runtime_ready:
        return _unmeasured("state.previous_run", "the runtime tree is not usable")
    try:
        document = pipeline.state.read(RuntimeArea.STATE, LIFECYCLE_FILE)
    except (GlobinError, OSError) as fault:
        return previous_run_outcome(None, str(fault))
    if document is None:
        return previous_run_outcome(None)
    try:
        state.previous_run = read_lifecycle(dict(document))
    except GlobinError as fault:
        return previous_run_outcome(None, str(fault))
    return previous_run_outcome(state.previous_run)


def _lock_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Ask whether this process could be the machine's one coordinator.

    Args:
        pipeline: The pipeline, for its lock.
        state: The run state.

    Returns:
        The outcome of ``instance.lock``.

    **This probes; it does not keep the lock.** The pipeline runs inside `doctor`
    as well as inside the gate, and a diagnostic that took the production lock
    would refuse to run beside a running GLOBIN — which is exactly when somebody
    wants to run it. The lock that is *held* is taken by
    :mod:`globin.application.lifecycle`, once, around the whole application.
    """
    if not state.runtime_ready:
        return _unmeasured("instance.lock", "the runtime tree is not usable")
    problem = pipeline.lock.probe()
    return lock_outcome(acquired=not problem, problem=problem)


def _secrets_step(pipeline: BootstrapPipeline, state: _RunState) -> CheckOutcome:
    """Read whether required secret references resolve.

    Args:
        pipeline: The pipeline, for its secret probe.
        state: The run state.

    Returns:
        The outcome of ``secrets.required``.
    """
    state.secret_readiness = pipeline.secrets.readiness()
    return secrets_outcome(state.secret_readiness)


def steps() -> tuple[Callable[[BootstrapPipeline, _RunState], CheckOutcome], ...]:
    """Return one step per registered check except the aggregate, in order.

    Returns:
        The steps the pipeline performs.

    Compared against :func:`~globin.domain.bootstrap.checks` by
    ``tests/contract/test_bootstrap_contract.py``, so a check declared without a
    step — or a step performing a check nobody declared — fails rather than
    silently producing a shorter report.

    A tuple of function references is not a call and would have been legal as a
    constant. It is a function anyway, so that it reads the same way as the
    registry it is compared against: two lists that must stay the same length are
    easier to keep honest when they look alike.
    """
    return (
        _root_step,
        _host_step,
        _architecture_step,
        _capability_step,
        _implementation_step,
        _version_step,
        _environment_step,
        _identity_step,
        _dependency_step,
        _configuration_step,
        _paths_step,
        _boundary_step,
        _persistence_step,
        _previous_run_step,
        _lock_step,
        _secrets_step,
    )
