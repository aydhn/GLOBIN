"""Provisioning composed, with the three properties that cannot be asserted from types.

**Read-only-ness, idempotency and interruption safety** are claims about what a
run *did*, so they are asserted over real filesystem state rather than over a
return value. Each is checked with a negative control beside it: a helper that
could only ever report "unchanged" would make the first two pass for ever, which
is the failure mode `tests/contract/test_isolation_contract.py` already names.

Every process here is a double. The suite's offline guard patches sockets in one
interpreter and a child has its own view of the world, so a test that started a
real child would be a test that could reach the network — and `ProcessRunner` is
injected precisely so it does not have to.
"""

import hashlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from globin.adapters.provisioning import MARKER_NAME, MarkerEnvironmentClaim
from globin.adapters.runtime_state import AtomicDocumentWriter, FileOperations
from globin.application.provisioning import (
    ProvisioningApply,
    ProvisioningOutcome,
    ProvisioningPlanRun,
)
from globin.domain.bootstrap import (
    BootstrapOutcome,
    BootstrapReport,
    CheckOutcome,
    CheckStatus,
    check_identifiers,
)
from globin.domain.process import CommandRequest, CommandResult, HostCapability, Tool, ToolPresence
from globin.domain.provisioning import (
    ActionOutcome,
    NetworkPolicy,
    ProvisioningAction,
    ProvisioningJournal,
    ProvisioningPlan,
    ProvisioningStep,
)
from globin.domain.runtime_state import RuntimeArea, RuntimeLayout
from globin.errors import ValidationError

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


@dataclass
class RecordingRunner:
    """A process runner that records and never starts anything.

    Every request is kept, so a test can assert not merely that nothing ran but
    that the only things asked for were the declared probes.
    """

    asked: list[CommandRequest] = field(default_factory=list)
    answer: str = "1.0.0"

    def run(self, request: CommandRequest) -> CommandResult:
        """Record the request and answer as a successful probe."""
        self.asked.append(request)
        return CommandResult(request=request, exit_code=0, stdout=self.answer)


@dataclass
class ScriptedProbe:
    """A capability probe with a fixed answer."""

    launcher: Tool | None = Tool.LEGACY_LAUNCHER

    def capabilities(self) -> HostCapability:
        """Answer with one launcher present, or none."""
        return HostCapability(
            tools=tuple(ToolPresence(tool=tool, present=tool is self.launcher) for tool in Tool)
        )


@dataclass
class ScriptedPipeline:
    """A bootstrap pipeline answering from a script of reports.

    The script *runs out*: a pipeline that kept answering after its script ended
    would turn "the run measured more times than expected" into a passing test.
    """

    reports: list[BootstrapReport]
    calls: int = 0

    def run(self, *, stop_at_first_refusal: bool = True) -> BootstrapOutcome:  # noqa: ARG002
        """Answer with the next scripted report.

        The keyword is accepted and ignored: this double answers from a script,
        so what a real pipeline would do with it is not its business. It is in
        the signature because the port has it.
        """
        assert self.calls < len(self.reports), "the run measured more times than the script covers"
        report = self.reports[self.calls]
        self.calls += 1
        return BootstrapOutcome(report=report)


@dataclass
class ScriptedExecutor:
    """An executor with a fixed outcome per action identifier."""

    outcomes: dict[str, ActionOutcome] = field(default_factory=dict)
    applied: list[str] = field(default_factory=list)

    def apply(self, action: ProvisioningAction) -> ProvisioningStep:
        """Record the action and answer with its scripted outcome."""
        self.applied.append(action.identifier)
        outcome = self.outcomes.get(action.identifier, ActionOutcome.APPLIED)
        return ProvisioningStep(action=action, outcome=outcome, detail="a scripted outcome")


@dataclass
class FakeLock:
    """A lock that records whether it was held."""

    held: int = 0

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Enter and leave, counting."""
        self.held += 1
        yield

    def probe(self) -> str:
        """Never held by anybody else in these tests."""
        return ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def report(*failing: str) -> BootstrapReport:
    """A report in which exactly the named checks failed."""
    return BootstrapReport(
        outcomes=tuple(
            CheckOutcome(
                identifier=name,
                status=CheckStatus.FAIL if name in failing else CheckStatus.PASS,
                summary="a summary",
                remediation="do the thing" if name in failing else "",
            )
            for name in check_identifiers()
        )
    )


def tree_fingerprint(*roots: Path) -> tuple[tuple[str, int, str], ...]:
    """Every file under each root, with its size and digest.

    Args:
        roots: Where to walk.

    Returns:
        One entry per file, sorted, so two calls compare.

    Content and size rather than modification time: a run that rewrote a file
    with identical bytes has still not changed anything a later run depends on,
    and `st_mtime_ns` would report it as a difference on some filesystems and not
    on others.
    """
    found: list[tuple[str, int, str]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            payload = path.read_bytes()
            found.append(
                (
                    str(path.relative_to(root)).replace("\\", "/"),
                    len(payload),
                    hashlib.sha256(payload).hexdigest(),
                )
            )
    return tuple(sorted(found))


def claim_for(root: Path) -> MarkerEnvironmentClaim:
    """A real claim, writing into a temporary runtime tree."""
    return MarkerEnvironmentClaim(
        writer=AtomicDocumentWriter(operations=FileOperations()), root=root
    )


def applier(
    root: Path,
    *,
    reports: Sequence[BootstrapReport],
    outcomes: dict[str, ActionOutcome] | None = None,
    policy: NetworkPolicy = NetworkPolicy.CACHE_ONLY,
    recreate: bool = False,
) -> tuple[ProvisioningApply, ScriptedExecutor, FakeLock]:
    """A wired applier over doubles, and the two doubles a test asserts about."""
    pipeline = ScriptedPipeline(reports=list(reports))
    executor = ScriptedExecutor(outcomes=dict(outcomes or {}))
    lock = FakeLock()
    planner = ProvisioningPlanRun(
        pipeline=pipeline,  # type: ignore[arg-type]
        capabilities=ScriptedProbe(),
        policy=policy,
        recreate=recreate,
    )
    return (
        ProvisioningApply(
            proposal=planner,
            executor=executor,
            claim=claim_for(root),
            lock=lock,
        ),
        executor,
        lock,
    )


# ---------------------------------------------------------------------------
# Read-only-ness
# ---------------------------------------------------------------------------


def test_producing_a_plan_starts_no_process_and_writes_nothing(tmp_path: Path) -> None:
    """`plan` measures and derives. It does not act.

    The strongest guarantee is elsewhere and free: the planner is in the domain
    layer, which may perform no I/O. This asserts it about a real run.
    """
    runner = RecordingRunner()
    planner = ProvisioningPlanRun(
        pipeline=ScriptedPipeline(reports=[report("python.environment")]),  # type: ignore[arg-type]
        capabilities=ScriptedProbe(),
        policy=NetworkPolicy.OFFLINE,
    )
    before = tree_fingerprint(tmp_path)
    proposal = planner.run()
    assert tree_fingerprint(tmp_path) == before
    assert runner.asked == []
    assert not proposal.plan.empty


def test_the_fingerprint_helper_reports_a_difference_when_there_is_one(tmp_path: Path) -> None:
    """The negative control.

    Without this, a helper that returned a constant would make every
    "nothing changed" assertion in this module pass for ever.
    """
    before = tree_fingerprint(tmp_path)
    (tmp_path / "written.txt").write_text("x", encoding="utf-8")
    assert tree_fingerprint(tmp_path) != before


def test_the_fingerprint_helper_notices_a_rewrite_with_different_content(
    tmp_path: Path,
) -> None:
    """A file replaced in place is a change, and is reported as one."""
    target = tmp_path / "written.txt"
    target.write_text("before", encoding="utf-8")
    first = tree_fingerprint(tmp_path)
    target.write_text("after!", encoding="utf-8")
    assert tree_fingerprint(tmp_path) != first


# ---------------------------------------------------------------------------
# Applying a plan
# ---------------------------------------------------------------------------


def test_a_healthy_host_applies_nothing_and_writes_no_claim(tmp_path: Path) -> None:
    """A plan with nothing to do must not leave a marker.

    Otherwise a check over an untouched host would read as interrupted.
    """
    apply, executor, lock = applier(tmp_path, reports=[report(), report()])
    outcome = apply.setup()
    assert outcome.journal.steps == ()
    assert executor.applied == []
    assert not (tmp_path / RuntimeLayout().segment_for(RuntimeArea.RUN) / MARKER_NAME).exists()
    assert lock.held == 1


def test_a_failing_check_is_applied_and_the_claim_is_released(tmp_path: Path) -> None:
    apply, executor, _ = applier(tmp_path, reports=[report("python.environment"), report()])
    outcome = apply.setup()
    assert executor.applied == ["environment.create"]
    assert outcome.changed
    assert outcome.journal.complete
    assert not (tmp_path / RuntimeLayout().segment_for(RuntimeArea.RUN) / MARKER_NAME).exists()


def test_a_second_run_over_an_unchanged_host_is_a_no_op(tmp_path: Path) -> None:
    """Idempotency, asserted three independent ways.

    The journal's own word is the weakest of the three -- it is the executor's
    account of itself. The empty plan is stronger, because it is recomputed from a
    fresh measurement. The unchanged tree is strongest.
    """
    first, _first_executor, _ = applier(tmp_path, reports=[report("python.environment"), report()])
    first.setup()
    settled = tree_fingerprint(tmp_path)

    second, second_executor, _ = applier(tmp_path, reports=[report(), report()])
    outcome = second.setup()

    assert outcome.before.plan.empty
    assert not outcome.changed
    assert second_executor.applied == []
    assert tree_fingerprint(tmp_path) == settled


def test_an_action_the_policy_forbids_is_refused_rather_than_attempted(
    tmp_path: Path,
) -> None:
    apply, executor, _ = applier(
        tmp_path, reports=[report("dependency.lock"), report()], policy=NetworkPolicy.OFFLINE
    )
    outcome = apply.setup()
    assert executor.applied == []
    assert [step.outcome for step in outcome.journal.steps] == [ActionOutcome.REFUSED]
    assert "offline" in outcome.journal.steps[0].detail


def test_the_destructive_action_is_refused_by_setup_and_named_in_the_refusal(
    tmp_path: Path,
) -> None:
    """`setup` cannot delete, and says which command can."""
    apply, executor, _ = applier(
        tmp_path, reports=[report("python.environment"), report()], recreate=True
    )
    outcome = apply.setup()
    assert executor.applied == []
    assert outcome.journal.steps[0].outcome is ActionOutcome.REFUSED
    assert "repair --recreate" in outcome.journal.steps[0].detail


def test_repair_with_recreate_admits_the_destructive_action(tmp_path: Path) -> None:
    apply, executor, _ = applier(
        tmp_path, reports=[report("python.environment"), report()], recreate=True
    )
    outcome = apply.repair(recreate=True)
    assert executor.applied == ["environment.recreate"]
    assert outcome.journal.complete


def test_a_mutating_run_holds_the_lock(tmp_path: Path) -> None:
    """Two mutating runs cannot interleave."""
    apply, _, lock = applier(tmp_path, reports=[report(), report()])
    apply.setup()
    assert lock.held == 1


# ---------------------------------------------------------------------------
# Interruption
# ---------------------------------------------------------------------------


def test_a_failed_step_stops_the_run_and_leaves_the_claim(tmp_path: Path) -> None:
    """The whole safety argument, in one test.

    The claim is written before the first mutation and released only after the
    last one completes, so a run that stopped part-way leaves it behind.
    """
    apply, executor, _ = applier(
        tmp_path,
        reports=[report("paths.runtime", "python.environment"), report()],
        outcomes={"paths.create": ActionOutcome.FAILED},
    )
    outcome = apply.setup()

    assert executor.applied == ["paths.create"]
    assert [step.outcome for step in outcome.journal.steps] == [
        ActionOutcome.FAILED,
        ActionOutcome.NOT_ATTEMPTED,
    ]
    assert not outcome.journal.complete
    assert (tmp_path / RuntimeLayout().segment_for(RuntimeArea.RUN) / MARKER_NAME).exists()


def test_an_incomplete_run_takes_no_re_measurement_and_cannot_read_as_ready(
    tmp_path: Path,
) -> None:
    """A caller must not get a clean verdict by ignoring the part that says otherwise."""
    apply, _, _ = applier(
        tmp_path,
        reports=[report("paths.runtime"), report()],
        outcomes={"paths.create": ActionOutcome.FAILED},
    )
    outcome = apply.setup()
    assert outcome.after is None
    assert int(outcome.exit_code) != 0


def test_carrying_a_re_measurement_on_an_incomplete_run_is_refused(tmp_path: Path) -> None:
    """Guard the invariant, since the code above never constructs one."""
    plan = ProvisioningPlan(policy=NetworkPolicy.OFFLINE)
    incomplete = ProvisioningJournal(
        plan=ProvisioningPlan(
            policy=NetworkPolicy.OFFLINE,
            actions=(
                ProvisioningAction(
                    spec=__import__(
                        "globin.domain.provisioning", fromlist=["action_spec_for"]
                    ).action_spec_for("paths.create"),
                    reason="a reason",
                ),
            ),
        ),
        steps=(),
    )
    apply, _, _ = applier(tmp_path, reports=[report(), report()])
    proposal = apply.proposal.run()
    with pytest.raises(ValidationError, match="did not complete"):
        ProvisioningOutcome(
            before=proposal, journal=incomplete, after=BootstrapOutcome(report=report())
        )
    assert plan.empty


def test_an_outstanding_claim_is_visible_to_a_later_run(tmp_path: Path) -> None:
    """The next command sees what an interrupted one left."""
    apply, _, _ = applier(
        tmp_path,
        reports=[report("paths.runtime"), report()],
        outcomes={"paths.create": ActionOutcome.FAILED},
    )
    apply.setup()
    assert claim_for(tmp_path).outstanding() is not None


def test_releasing_a_claim_that_was_never_made_is_not_an_error(tmp_path: Path) -> None:
    """Idempotent, so a caller does not have to track whether it made one."""
    claim = claim_for(tmp_path)
    claim.release()
    claim.release()
    assert claim.outstanding() is None


def test_an_outstanding_claim_does_not_widen_what_a_later_run_may_reach(
    tmp_path: Path,
) -> None:
    """A marker from an older or damaged run must not grant a policy.

    The plan inside it is deliberately not reconstructed: reading it tells a
    caller that a run was interrupted, and trusting its contents would mean
    trusting a document a process that did not finish wrote.
    """
    claim = claim_for(tmp_path)
    claim.claim(ProvisioningPlan(policy=NetworkPolicy.ONLINE_ALLOWED))
    recovered = claim.outstanding()
    assert recovered is not None
    assert recovered.policy is NetworkPolicy.ONLINE_ALLOWED

    target = tmp_path / RuntimeLayout().segment_for(RuntimeArea.RUN) / MARKER_NAME
    target.write_text('{"schema":"x","plan":{"policy":"invented"}}', encoding="utf-8")
    damaged = claim_for(tmp_path).outstanding()
    assert damaged is not None
    assert damaged.policy is NetworkPolicy.OFFLINE


# ---------------------------------------------------------------------------
# Leak
# ---------------------------------------------------------------------------

SENTINEL = "globin-sentinel-a1b2c3d4e5f6"


def test_no_child_output_reaches_a_published_record() -> None:
    """A child that echoes a credential must not put it in the evidence.

    Redaction matches field *names*, and `stdout` is not a name GLOBIN chose --
    it is text GLOBIN did not write. Passing it through the redactor would look
    like a protection and be none, so the text is not published at all.
    """
    request = CommandRequest(executable="py", arguments=("--version",))
    result = CommandResult(
        request=request,
        exit_code=1,
        stdout=f"api_key={SENTINEL}",
        stderr=f"password={SENTINEL}",
    )
    assert SENTINEL not in str(result.as_record())


def test_the_record_still_says_how_much_the_child_printed() -> None:
    """Not publishing the text is not the same as publishing nothing.

    A reader diagnosing a failure needs to know a child answered at all, which is
    what the byte counts carry.
    """
    request = CommandRequest(executable="py", arguments=("--version",))
    record = CommandResult(request=request, exit_code=0, stdout="abc").as_record()
    assert record["stdout_bytes"] == 3
    assert "stdout" not in record


def test_an_action_globin_cannot_perform_names_the_command_that_can() -> None:
    """What an installed GLOBIN says instead of attempting the impossible.

    The wheel holds the package and nothing else, so `scripts/bootstrap.ps1` is
    not there to run. Reporting the command is more useful than an attempt that
    could only work from a source checkout.
    """
    from globin.adapters.provisioning import RuntimeTreeExecutor
    from globin.domain.provisioning import action_spec_for

    step = RuntimeTreeExecutor().apply(
        ProvisioningAction(spec=action_spec_for("environment.create"), reason="a reason")
    )
    assert step.outcome is ActionOutcome.REFUSED
    assert "scripts/bootstrap.ps1" in step.detail
