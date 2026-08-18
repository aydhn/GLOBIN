"""The provisioning adapters: the one module that starts a process, and its neighbours.

**One real child process runs in this module**, and it is `sys.executable` printing
a known string. That is deliberate: `BoundedProcessRunner` is the only place in
GLOBIN where a process is started, and a test that only ever exercised it through
a double would establish that the double works. Everything about *what* is run is
tested from literals; that one case establishes that the mechanism does.

The suite's offline guard permits it: the child is the interpreter already
running, it reaches no network, and the guard patches sockets rather than
processes.
"""

import sys
from pathlib import Path

import pytest

from globin.adapters.provisioning import (
    ENVIRONMENT_ALLOWLIST,
    MARKER_NAME,
    MARKER_SCHEMA,
    BoundedProcessRunner,
    MarkerEnvironmentClaim,
    PathToolProbe,
    ReadOnlyProcessRunner,
    RuntimeTreeExecutor,
    build,
    child_environment,
    record_path,
)
from globin.adapters.runtime_state import AtomicDocumentWriter, FileOperations
from globin.domain.bootstrap import PathLocation
from globin.domain.process import (
    MAX_CAPTURED_BYTES,
    MIN_TIMEOUT_MILLIS,
    CommandRequest,
    CommandResult,
    HostCapability,
    Tool,
    probe_commands,
)
from globin.domain.provisioning import (
    ActionOutcome,
    NetworkPolicy,
    ProvisioningAction,
    ProvisioningJournal,
    ProvisioningPlan,
    action_spec_for,
)
from globin.domain.runtime_state import RuntimeArea, RuntimeLayout
from globin.errors import ValidationError


def action(identifier: str) -> ProvisioningAction:
    """One bound action."""
    return ProvisioningAction(spec=action_spec_for(identifier), reason="a reason")


# ---------------------------------------------------------------------------
# BoundedProcessRunner -- the one place a process is started
# ---------------------------------------------------------------------------


def test_a_child_runs_and_its_output_comes_back(tmp_path: Path) -> None:
    """The mechanism, exercised once against a real child.

    `sys.executable` is the interpreter already running, so this reaches no
    network and needs nothing installed.
    """
    runner = BoundedProcessRunner(working_directory=tmp_path)
    result = runner.run(
        CommandRequest(executable=sys.executable, arguments=("-c", "print('alive')"))
    )
    assert result.ok
    assert "alive" in result.stdout
    assert not result.timed_out


def test_a_child_that_fails_reports_its_code_rather_than_raising(tmp_path: Path) -> None:
    runner = BoundedProcessRunner(working_directory=tmp_path)
    result = runner.run(
        CommandRequest(executable=sys.executable, arguments=("-c", "raise SystemExit(3)"))
    )
    assert not result.ok
    assert result.exit_code == 3


def test_a_child_that_hangs_is_ended_and_reported_as_a_timeout(tmp_path: Path) -> None:
    """A timeout is a result, not an exception.

    A caller deciding what to do about a provisioning action needs the same shape
    of answer whether the child failed or hung; raising for one would put a try
    block at every call site meaning "treat it the same way".
    """
    runner = BoundedProcessRunner(working_directory=tmp_path)
    result = runner.run(
        CommandRequest(
            executable=sys.executable,
            # `__import__` rather than `import time; ...` because a semicolon is
            # a shell metacharacter and `CommandRequest` refuses one -- which is
            # the rule working, caught here rather than in review.
            arguments=("-c", "__import__('time').sleep(30)"),
            timeout_millis=MIN_TIMEOUT_MILLIS,
        )
    )
    assert result.timed_out
    assert not result.ok
    assert "timeout" in result.stderr


def test_an_executable_that_does_not_exist_is_a_failed_run(tmp_path: Path) -> None:
    """A capability probe over a tool this host lacks is an ordinary answer."""
    runner = BoundedProcessRunner(working_directory=tmp_path)
    result = runner.run(CommandRequest(executable="globin-not-a-real-program-a1b2c3"))
    assert not result.ok
    assert not result.timed_out
    assert result.stderr


def test_a_child_that_prints_past_the_ceiling_is_cut_and_says_so(tmp_path: Path) -> None:
    """Output beyond the ceiling is dropped, and the result says so.

    Silently truncating and reporting the whole is how a reader concludes a
    build succeeded from the last line of a log that was cut.
    """
    runner = BoundedProcessRunner(working_directory=tmp_path, capture_bytes=64)
    result = runner.run(
        CommandRequest(executable=sys.executable, arguments=("-c", "print('x' * 500)"))
    )
    assert result.truncated
    assert len(result.stdout) == 64


def test_the_default_capture_ceiling_is_the_declared_one(tmp_path: Path) -> None:
    assert BoundedProcessRunner(working_directory=tmp_path).capture_bytes == MAX_CAPTURED_BYTES


# ---------------------------------------------------------------------------
# The child's environment
# ---------------------------------------------------------------------------


def test_a_child_inherits_only_allowlisted_names() -> None:
    given = child_environment({"PATH": "p", "GLOBIN_SECRET": "s", "RANDOM_THING": "r"})
    assert set(given) == {"PATH"}


def test_reading_the_real_environment_yields_only_allowlisted_names() -> None:
    """The default path, so the allowlist is exercised as it is used."""
    assert set(child_environment()) <= set(ENVIRONMENT_ALLOWLIST)


# ---------------------------------------------------------------------------
# ReadOnlyProcessRunner
# ---------------------------------------------------------------------------


class Recording:
    """A runner that records and answers successfully."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.asked: list[CommandRequest] = []

    def run(self, request: CommandRequest) -> CommandResult:
        """Record and answer."""
        self.asked.append(request)
        return CommandResult(request=request, exit_code=0, stdout="Python 3.14.5")


def test_a_declared_probe_is_passed_through() -> None:
    inner = Recording()
    runner = ReadOnlyProcessRunner(inner=inner)
    result = runner.run(probe_commands()[0])
    assert result.ok
    assert inner.asked == [probe_commands()[0]]


def test_anything_but_a_declared_probe_is_refused() -> None:
    """What makes `check` and `plan` read-only in production, not only under test.

    Raised rather than returned as a failure: this is a caller bug and not a host
    condition, and returning it would let an edit that tried to build something
    read as a host that could not.
    """
    inner = Recording()
    runner = ReadOnlyProcessRunner(inner=inner)
    with pytest.raises(ValidationError, match="only the declared probes"):
        runner.run(CommandRequest(executable=sys.executable, arguments=("-c", "print(1)")))
    assert inner.asked == []


def test_the_permitted_set_defaults_to_the_declared_probes() -> None:
    assert ReadOnlyProcessRunner(inner=Recording()).permitted is None
    inner = Recording()
    ReadOnlyProcessRunner(inner=inner).run(probe_commands()[-1])
    assert inner.asked


# ---------------------------------------------------------------------------
# PathToolProbe
# ---------------------------------------------------------------------------


def test_a_tool_not_on_the_path_is_recorded_absent() -> None:
    probe = PathToolProbe(runner=Recording(), which=lambda _name: None)
    capability = probe.capabilities()
    assert not capability.has(Tool.WINGET)
    assert capability.presence(Tool.WINGET).measured


def test_a_tool_on_the_path_is_asked_its_version() -> None:
    inner = Recording()
    probe = PathToolProbe(runner=inner, which=lambda name: f"C:/bin/{name}")
    capability = probe.capabilities()
    assert capability.has(Tool.LEGACY_LAUNCHER)
    assert capability.presence(Tool.LEGACY_LAUNCHER).version == "Python 3.14.5"
    assert len(inner.asked) == len(Tool)


def test_a_probe_that_times_out_is_unmeasured_rather_than_absent() -> None:
    """A broken PATH must not look like a plain host."""

    class TimingOut:
        def run(self, request: CommandRequest) -> CommandResult:
            return CommandResult(request=request, exit_code=-1, timed_out=True)

    probe = PathToolProbe(runner=TimingOut(), which=lambda name: f"C:/bin/{name}")
    presence = probe.capabilities().presence(Tool.WINGET)
    assert not presence.measured
    assert not presence.present


def test_the_launcher_is_the_manager_when_both_are_present() -> None:
    """Both answer to `py`; only the manager answers to `pymanager`."""
    probe = PathToolProbe(runner=Recording(), which=lambda name: f"C:/bin/{name}")
    assert probe.capabilities().launcher() is Tool.PYTHON_MANAGER


def test_a_host_with_only_the_legacy_launcher_cannot_install_a_runtime() -> None:
    probe = PathToolProbe(
        runner=Recording(),
        which=lambda name: f"C:/bin/{name}" if name == Tool.LEGACY_LAUNCHER.value else None,
    )
    capability = probe.capabilities()
    assert capability.launcher() is Tool.LEGACY_LAUNCHER
    assert not capability.can_install_a_runtime()


# ---------------------------------------------------------------------------
# MarkerEnvironmentClaim
# ---------------------------------------------------------------------------


def claim_for(root: Path) -> MarkerEnvironmentClaim:
    """A real claim over a temporary tree."""
    return MarkerEnvironmentClaim(
        writer=AtomicDocumentWriter(operations=FileOperations()), root=root
    )


def test_a_claim_is_written_where_the_layout_says(tmp_path: Path) -> None:
    claim = claim_for(tmp_path)
    claim.claim(ProvisioningPlan(policy=NetworkPolicy.OFFLINE))
    assert claim.path == tmp_path / RuntimeLayout().segment_for(RuntimeArea.RUN) / MARKER_NAME
    assert claim.path.is_file()
    assert MARKER_SCHEMA in claim.path.read_text(encoding="utf-8")


def test_a_released_claim_is_gone(tmp_path: Path) -> None:
    claim = claim_for(tmp_path)
    claim.claim(ProvisioningPlan(policy=NetworkPolicy.OFFLINE))
    claim.release()
    assert not claim.path.exists()
    assert claim.outstanding() is None


def test_a_claim_round_trips_its_policy(tmp_path: Path) -> None:
    claim = claim_for(tmp_path)
    claim.claim(ProvisioningPlan(policy=NetworkPolicy.CACHE_ONLY))
    recovered = claim.outstanding()
    assert recovered is not None
    assert recovered.policy is NetworkPolicy.CACHE_ONLY


def test_a_marker_with_no_readable_policy_falls_back_to_the_strictest(tmp_path: Path) -> None:
    """The conservative default, for a marker this run cannot read.

    A marker from an older or damaged run must not widen what a later one may
    reach.
    """
    claim = claim_for(tmp_path)
    claim.path.parent.mkdir(parents=True, exist_ok=True)
    claim.path.write_text('{"schema":"x"}', encoding="utf-8")
    recovered = claim.outstanding()
    assert recovered is not None
    assert recovered.policy is NetworkPolicy.OFFLINE


# ---------------------------------------------------------------------------
# RuntimeTreeExecutor
# ---------------------------------------------------------------------------


class FakeTree:
    """A runtime tree that reports what it was told to."""

    def __init__(self, problems: tuple[str, ...] = (), fault: OSError | None = None) -> None:
        """Answer with these problems, or raise this fault."""
        self.problems = problems
        self.fault = fault
        self.prepared = 0

    def prepare(self, layout: RuntimeLayout) -> tuple[str, ...]:  # noqa: ARG002
        """Count the call and answer.

        The layout is accepted and ignored: this double answers from what it was
        constructed with. It is in the signature because the port has it.
        """
        self.prepared += 1
        if self.fault is not None:
            raise self.fault
        return self.problems

    def describe(self) -> dict[str, object]:
        """Unused here."""
        return {}


def test_the_runtime_tree_is_created() -> None:
    tree = FakeTree()
    step = RuntimeTreeExecutor(tree=tree).apply(action("paths.create"))
    assert step.outcome is ActionOutcome.APPLIED
    assert tree.prepared == 1


def test_a_tree_that_reports_a_problem_is_a_failed_step() -> None:
    """A reported problem is a failure, not something to discard.

    `prepare` reports rather than raises, so a discarded report would leave a
    step claiming success over a tree that is not writable.
    """
    step = RuntimeTreeExecutor(tree=FakeTree(problems=("run is read-only",))).apply(
        action("paths.create")
    )
    assert step.outcome is ActionOutcome.FAILED
    assert "read-only" in step.detail


def test_a_tree_that_raises_is_a_failed_step() -> None:
    step = RuntimeTreeExecutor(tree=FakeTree(fault=OSError("disk gone"))).apply(
        action("paths.create")
    )
    assert step.outcome is ActionOutcome.FAILED
    assert "disk gone" in step.detail


def test_an_unwired_tree_is_a_failed_step_rather_than_a_crash() -> None:
    step = RuntimeTreeExecutor().apply(action("paths.create"))
    assert step.outcome is ActionOutcome.FAILED
    assert "no runtime tree" in step.detail


def test_evidence_is_the_command_s_job_rather_than_an_action_s() -> None:
    step = RuntimeTreeExecutor(tree=FakeTree()).apply(action("evidence.record"))
    assert step.outcome is ActionOutcome.SATISFIED


def test_an_operator_action_names_the_command_and_is_not_attempted() -> None:
    tree = FakeTree()
    step = RuntimeTreeExecutor(tree=tree).apply(action("environment.create"))
    assert step.outcome is ActionOutcome.REFUSED
    assert "scripts/bootstrap.ps1" in step.detail
    assert tree.prepared == 0


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


def test_the_manifest_describes_the_run() -> None:
    journal = ProvisioningJournal(plan=ProvisioningPlan(policy=NetworkPolicy.OFFLINE))
    document = build(journal, HostCapability())
    assert document["phase"] == 32
    assert isinstance(document["journal"], dict)
    assert isinstance(document["capability"], dict)


def test_a_path_inside_the_repository_is_recorded_relative(tmp_path: Path) -> None:
    inside = tmp_path / "docs" / "thing.md"
    inside.parent.mkdir(parents=True)
    inside.write_text("x", encoding="utf-8")
    recorded = record_path(tmp_path, str(inside))
    assert recorded.location is PathLocation.REPOSITORY
    assert recorded.path == "docs/thing.md"


def test_a_path_outside_the_repository_is_recorded_as_a_fingerprint(tmp_path: Path) -> None:
    """A path outside the project is a fingerprint, never a spelling.

    It carries an account name often enough that treating it as public is not
    a risk worth taking.
    """
    recorded = record_path(tmp_path / "project", str(tmp_path / "elsewhere" / "thing.md"))
    assert recorded.location is PathLocation.OUTSIDE
    assert recorded.fingerprint
    assert recorded.path is None


def test_a_command_carrying_a_shell_metacharacter_is_refused_before_it_runs() -> None:
    """The rule that shaped the timeout test above.

    `import time; time.sleep(30)` is an ordinary thing to type and an ordinary
    thing to get wrong: the semicolon means nothing to an argument vector and
    everything to a shell, so a caller writing one is composing a shell command
    where a vector is wanted. Refusing costs nothing this phase legitimately
    needs.
    """
    with pytest.raises(ValidationError, match="means something to a shell"):
        CommandRequest(executable=sys.executable, arguments=("-c", "a; b"))
