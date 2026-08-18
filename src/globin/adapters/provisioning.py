"""The one module in GLOBIN that starts a process.

Before Phase 032 nothing under ``src/globin`` imported :mod:`subprocess` at all.
``docs/architecture/dependency-rules.toml`` has always *permitted* it here ---
``subprocess`` is in the I/O-capable set and the adapters layer may perform I/O
--- so this is an unbroken property becoming a bounded one rather than a contract
being widened. ``tests/architecture/test_process_discipline.py`` names this module
and fails if a second one reaches for a process, and fails again if this one stops,
which is the shape ``test_library_discipline.py`` already uses for the socket.

**The environment is not built here.** ``tools/quality/runtime`` already does that,
with the recursive-delete guard and the interpreter checks a test can hold, and
this module reaches it the way ``scripts/bootstrap.ps1`` does: as a child process.
That package and this one cannot import each other, and they do not need to ---
what is wanted is the work done, not the function called. One builder, no second
copy of the decisions worth getting wrong.

**Nothing here composes a shell command.** :class:`globin.domain.process.CommandRequest`
cannot hold a shell metacharacter, ``shell=False`` is passed explicitly, and the
child is handed an argument vector. The `S603` suppression below is on the one
call that starts a process, with the reason beside it.
"""

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from globin.adapters.runtime_state import AtomicDocumentWriter
from globin.domain.bootstrap import RecordedPath, recorded_inside, recorded_outside
from globin.domain.process import (
    MAX_CAPTURED_BYTES,
    CommandRequest,
    CommandResult,
    HostCapability,
    Tool,
    ToolPresence,
    probe_commands,
)
from globin.domain.provisioning import (
    ActionOutcome,
    NetworkPolicy,
    Performer,
    ProvisioningAction,
    ProvisioningJournal,
    ProvisioningPlan,
    ProvisioningStep,
)
from globin.domain.runtime_state import RuntimeArea, RuntimeLayout
from globin.errors import ValidationError
from globin.ports.provisioning import ProcessRunner, RuntimeTreePreparer

MARKER_NAME: Final[str] = "provisioning.json"
"""What an unfinished provisioning run leaves behind.

Published into the runtime tree's ``run`` area, beside the instance lock, because
that area is where facts about *this* run live and is the one an operator may
delete when nothing is running.
"""

MARKER_SCHEMA: Final[str] = "globin.provisioning.claim"
MARKER_SCHEMA_VERSION: Final[int] = 1

ENVIRONMENT_ALLOWLIST: Final[tuple[str, ...]] = (
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "LOCALAPPDATA",
    "APPDATA",
    "USERPROFILE",
    "PATH",
)
"""What a child is allowed to inherit, named rather than filtered.

An allowlist rather than a denylist of credential-shaped names, for the reason
``SUPPORT_BUNDLE.md`` gives about its own: a denylist is a list somebody has to
keep extending, and the failure mode is silent. A child that needs something not
here is a child whose need is worth writing down.

``PATH`` is here because resolving an executable is the point, and Windows cannot
start most programs without ``SYSTEMROOT``. Nothing credential-shaped can arrive
through any of these.
"""


def _bounded(text: str, limit: int) -> tuple[str, bool]:
    """Cut a stream at the ceiling, and say whether it was cut.

    Args:
        text: What the child printed.
        limit: How much to keep.

    Returns:
        The kept text, and whether anything was dropped.
    """
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def child_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """The variables a child is given, and no others.

    Args:
        source: Where to read them from. Defaults to this process's environment.

    Returns:
        Only the allowlisted names that are actually set.

    A child inherits nothing by default. The whole environment is never passed
    on, and never dumped into evidence.
    """
    environment = os.environ if source is None else source
    return {name: environment[name] for name in ENVIRONMENT_ALLOWLIST if name in environment}


@dataclass(frozen=True, slots=True)
class BoundedProcessRunner:
    """Starts a child, bounded twice, and reports rather than raises.

    Args:
        capture_bytes: How much of each stream to keep.
        working_directory: Where the child runs. Explicit rather than inherited,
            because a child's idea of "here" is otherwise whatever the caller
            last set.
    """

    working_directory: Path
    capture_bytes: int = MAX_CAPTURED_BYTES

    def run(self, request: CommandRequest) -> CommandResult:
        """Start the child and wait for it.

        Args:
            request: What to run.

        Returns:
            What happened. A timeout is a result carrying ``timed_out=True``, and
            an executable that does not exist is a result carrying a non-zero
            code --- neither raises, because the caller records every outcome the
            same way.

        **The timeout kills the direct child only.** A grandchild it started ---
        ``pip``, in the one case that matters --- is not reaped here, and the
        child GLOBIN starts is the one responsible for cleaning up after its own.
        """
        argv = [request.executable, *request.arguments]
        try:
            completed = subprocess.run(  # noqa: S603 -- vector, never a shell; see module docstring.
                argv,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=request.timeout_millis / 1000,
                check=False,
                cwd=str(self.working_directory),
                env=child_environment(),
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                request=request,
                exit_code=-1,
                stderr="the command did not finish within its timeout",
                timed_out=True,
            )
        except (OSError, ValueError) as fault:
            # A missing executable, or a name the platform refuses. Reported as a
            # failed run rather than raised, so a capability probe over a tool
            # this host does not have is an ordinary answer.
            return CommandResult(request=request, exit_code=-1, stderr=str(fault))

        stdout, cut_out = _bounded(completed.stdout or "", self.capture_bytes)
        stderr, cut_err = _bounded(completed.stderr or "", self.capture_bytes)
        return CommandResult(
            request=request,
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            truncated=cut_out or cut_err,
        )


@dataclass(frozen=True, slots=True)
class ReadOnlyProcessRunner:
    """Permits only the declared probes, and refuses everything else.

    Args:
        inner: What actually starts a process.
        permitted: The requests this runner will pass on.

    **This is what makes ``check`` and ``plan`` read-only in production**, not
    only under test. A read-only command is wired with this runner, so a future
    edit that made the planner try to start something would raise rather than run
    it --- the shape ``LoopbackAddress`` uses in the diagnostics surface, where
    the dangerous value is refused by a type rather than policed by a reviewer.
    """

    inner: ProcessRunner
    permitted: tuple[CommandRequest, ...] | None = None

    def run(self, request: CommandRequest) -> CommandResult:
        """Pass on a permitted request, and refuse anything else.

        Args:
            request: What to run.

        Returns:
            What the inner runner reported.

        Raises:
            ValidationError: If the request is not one of the declared probes.
                Raised rather than returned as a failure, because this is a
                caller bug and not a host condition.
        """
        permitted = probe_commands() if self.permitted is None else self.permitted
        if request not in permitted:
            allowed = ", ".join(sorted(entry.display() for entry in permitted))
            msg = (
                f"a read-only command may run only the declared probes, and "
                f"{request.display()!r} is not one of them. Permitted: {allowed}"
            )
            raise ValidationError(msg)
        return self.inner.run(request)


@dataclass(frozen=True, slots=True)
class PathToolProbe:
    """Discovers the declared tools on ``PATH``, and asks each its version.

    Args:
        runner: How to start a version probe.
        which: How to resolve a name on ``PATH``. Substitutable so a test can
            describe a host without having one.
    """

    runner: ProcessRunner
    which: Callable[[str], str | None] = shutil.which

    def capabilities(self) -> HostCapability:
        """Ask which tools this host has.

        Returns:
            One entry per declared tool.

        **A probe that could not run yields ``measured=False``, never
        ``present=False``.** Absent and could-not-tell are different facts, and
        collapsing them makes a broken ``PATH`` look like a plain host.
        """
        found: list[ToolPresence] = []
        probes = {request.executable: request for request in probe_commands()}
        for tool in Tool:
            located = self.which(tool.value)
            if located is None:
                found.append(ToolPresence(tool=tool, present=False))
                continue
            result = self.runner.run(probes[tool.value])
            if result.timed_out:
                found.append(ToolPresence(tool=tool, measured=False))
                continue
            version = (result.stdout or result.stderr).strip().splitlines()
            found.append(
                ToolPresence(tool=tool, present=True, version=version[0][:80] if version else "")
            )
        return HostCapability(tools=tuple(found))


@dataclass(frozen=True, slots=True)
class MarkerEnvironmentClaim:
    """Marks a half-built environment with a document published atomically.

    Args:
        writer: The Phase 022 atomic publisher, reused rather than reimplemented.
        root: The runtime tree's root.
        layout: Which area the marker goes in.

    The marker is a **claim over the environment**, not evidence about the run.
    It is written before the first mutation and removed only after the last one,
    so a process ended between them leaves it, and the next ``bootstrap check``
    sees an environment somebody was part-way through building.
    """

    writer: AtomicDocumentWriter
    root: Path
    layout: RuntimeLayout | None = None

    @property
    def path(self) -> Path:
        """Where the marker lives."""
        layout = RuntimeLayout() if self.layout is None else self.layout
        return self.root / layout.segment_for(RuntimeArea.RUN) / MARKER_NAME

    def claim(self, plan: ProvisioningPlan) -> None:
        """Record that a plan is being applied.

        Args:
            plan: What is about to be attempted.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.writer.publish(
            self.path,
            {
                "schema": MARKER_SCHEMA,
                "schema_version": MARKER_SCHEMA_VERSION,
                "plan": plan.as_record(),
            },
            label="provisioning claim",
        )

    def release(self) -> None:
        """Record that the plan finished. Idempotent."""
        self.writer.discard(self.path)

    def outstanding(self) -> ProvisioningPlan | None:
        """What a previous run left unfinished.

        Returns:
            ``None`` when nothing is outstanding.

        **The plan is deliberately not reconstructed.** Reading a marker tells a
        caller that a run was interrupted, which is the fact that matters;
        rebuilding the plan it was applying would mean trusting a document
        written by a process that did not finish. A caller that needs the plan
        re-derives it from a fresh measurement.
        """
        document = self.writer.read(self.path)
        if document is None:
            return None
        return ProvisioningPlan(policy=_policy_of(document))


def _policy_of(document: Mapping[str, object]) -> NetworkPolicy:
    """The policy an outstanding claim was made under.

    Args:
        document: The marker.

    Returns:
        The recorded policy, or the conservative default when the marker does not
        carry a readable one --- a marker written by an older or damaged run must
        not widen what a later run is permitted to reach.
    """
    plan = document.get("plan")
    if isinstance(plan, Mapping):
        recorded = plan.get("policy")
        if isinstance(recorded, str):
            try:
                return NetworkPolicy(recorded)
            except ValueError:
                return NetworkPolicy.OFFLINE
    return NetworkPolicy.OFFLINE


@dataclass(frozen=True, slots=True)
class RuntimeTreeExecutor:
    """Performs GLOBIN's own actions, and reports the operator's.

    Args:
        tree: How to bring the runtime tree into existence.
        layout: The declared tree.

    **This starts no child process, and that is the packaging showing through.**
    GLOBIN's wheel contains the package and its metadata and nothing else, so an
    installed GLOBIN has no ``tools/`` to invoke and no ``scripts/`` to run. An
    executor that shelled out to either would work from a source checkout and
    fail everywhere else --- the worst of the two, because it would look correct
    to whoever wrote it.

    What an operator must do is reported with the exact command, which is more
    useful than an attempt that cannot succeed here.
    """

    tree: RuntimeTreePreparer | None = None
    layout: RuntimeLayout | None = None

    def apply(self, action: ProvisioningAction) -> ProvisioningStep:
        """Perform one action, or report who must.

        Args:
            action: What to do.

        Returns:
            The step.
        """
        if action.spec.performer is Performer.OPERATOR:
            return ProvisioningStep(
                action=action,
                outcome=ActionOutcome.REFUSED,
                detail=(f"this is yours to run, and GLOBIN cannot: {action.spec.command}"),
            )
        handlers = {
            "paths.create": self._create_paths,
            "evidence.record": self._record,
        }
        handler = handlers.get(action.identifier)
        if handler is None:
            return ProvisioningStep(
                action=action,
                outcome=ActionOutcome.FAILED,
                detail=f"no executor is wired for {action.identifier}",
            )
        return handler(action)

    def _create_paths(self, action: ProvisioningAction) -> ProvisioningStep:
        """Bring the runtime tree into existence."""
        if self.tree is None:
            return ProvisioningStep(
                action=action,
                outcome=ActionOutcome.FAILED,
                detail="no runtime tree was wired, so the paths cannot be created",
            )
        try:
            problems = self.tree.prepare(RuntimeLayout() if self.layout is None else self.layout)
        except OSError as fault:
            return ProvisioningStep(action=action, outcome=ActionOutcome.FAILED, detail=str(fault))
        if problems:
            # `prepare` reports rather than raises, so an area it could not make
            # usable arrives as a sentence and would otherwise be discarded --
            # leaving a step that claims success over a tree that is not writable.
            return ProvisioningStep(
                action=action, outcome=ActionOutcome.FAILED, detail="; ".join(problems)
            )
        return ProvisioningStep(
            action=action, outcome=ActionOutcome.APPLIED, detail="the runtime tree was created"
        )

    def _record(self, action: ProvisioningAction) -> ProvisioningStep:
        """Evidence is written by the command, not by an action."""
        return ProvisioningStep(
            action=action,
            outcome=ActionOutcome.SATISFIED,
            detail="evidence is published by the command rather than by an action",
        )


MANIFEST_NAME: Final[str] = "provisioning-manifest.json"
SCHEMA: Final[str] = "globin.provisioning.manifest"
SCHEMA_VERSION: Final[int] = 1
PHASE: Final[int] = 32


def build(journal: ProvisioningJournal, capability: HostCapability) -> dict[str, object]:
    """The provisioning manifest, as a mapping.

    Args:
        journal: What was done.
        capability: What the host was found to have.

    Returns:
        The document, with no timestamp anywhere --- so two runs over an
        unchanged host compare, which is what an idempotency test asserts.
    """
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE,
        "capability": capability.as_record(),
        "journal": journal.as_record(),
    }


def record_path(root: Path, relative: str) -> RecordedPath:
    """Record a path the way the evidence carries one.

    Args:
        root: The repository root.
        relative: The path, absolute or relative.

    Returns:
        A repository-relative spelling when it is inside, and a fingerprint when
        it is not.
    """
    candidate = Path(relative)
    try:
        inside = candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return recorded_outside(str(candidate))
    return recorded_inside(inside.as_posix())
