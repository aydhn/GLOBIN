"""What the provisioning verbs print, and what they return.

The two renderers are pure functions over values the domain built, so they are
tested from literals. `bootstrap plan` is exercised as a whole against this
repository, which is safe precisely because it is the read-only verb — the
assertion that it changed nothing is in
`tests/integration/test_provisioning_end_to_end.py`, and this module asserts what
it *says*.
"""

import io
import json
from pathlib import Path

import pytest

from globin.application.provisioning import ProvisioningOutcome, ProvisioningProposal
from globin.domain.bootstrap import (
    BootstrapOutcome,
    BootstrapReport,
    CheckOutcome,
    CheckStatus,
    check_identifiers,
)
from globin.domain.process import HostCapability, Tool, ToolPresence
from globin.domain.provisioning import (
    ActionOutcome,
    NetworkPolicy,
    ProvisioningAction,
    ProvisioningJournal,
    ProvisioningPlan,
    ProvisioningStep,
    action_spec_for,
    plan_from,
)
from globin.runtime import cli


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


def host() -> HostCapability:
    """A host with the legacy launcher."""
    return HostCapability(
        tools=tuple(ToolPresence(tool=tool, present=tool is Tool.LEGACY_LAUNCHER) for tool in Tool)
    )


def proposal(*failing: str, policy: NetworkPolicy = NetworkPolicy.OFFLINE) -> ProvisioningProposal:
    """A proposal over a report with the named checks failing."""
    measured = report(*failing)
    return ProvisioningProposal(
        outcome=BootstrapOutcome(report=measured),
        capability=host(),
        plan=plan_from(measured, policy=policy, capability=host()),
    )


# ---------------------------------------------------------------------------
# render_plan_human
# ---------------------------------------------------------------------------


def test_a_healthy_host_is_told_there_is_nothing_to_do() -> None:
    text = cli.render_plan_human(proposal(), None)
    assert "Nothing to do" in text
    assert text.endswith("\n")


def test_a_plan_names_each_action_its_class_and_what_follows() -> None:
    """The three things an operator approving a plan is deciding about."""
    text = cli.render_plan_human(proposal("python.environment"), None)
    assert "environment.create" in text
    assert "[create]" in text
    assert "python.environment did not pass" in text
    assert "then: python.environment passes" in text
    assert "on interruption: resumable" in text
    assert "Nothing has been changed" in text


def test_a_destructive_action_is_marked_as_one() -> None:
    measured = report("python.environment")
    destructive = ProvisioningProposal(
        outcome=BootstrapOutcome(report=measured),
        capability=host(),
        plan=plan_from(measured, policy=NetworkPolicy.OFFLINE, capability=host(), recreate=True),
    )
    text = cli.render_plan_human(destructive, None)
    assert "DESTRUCTIVE" in text


def test_an_action_the_policy_forbids_is_named_rather_than_dropped() -> None:
    """A plan that looks complete and is not is worse than one that says so."""
    text = cli.render_plan_human(proposal("dependency.lock"), None)
    assert "needs cache" in text
    assert "offline policy forbids" in text
    assert "dependency.install" in text


def test_an_outstanding_claim_is_the_first_thing_a_reader_sees() -> None:
    text = cli.render_plan_human(proposal(), ProvisioningPlan(policy=NetworkPolicy.OFFLINE))
    assert text.startswith("INCOMPLETE")
    assert "bootstrap repair" in text


# ---------------------------------------------------------------------------
# render_journal_human
# ---------------------------------------------------------------------------


def outcome_with(*steps: tuple[str, ActionOutcome], after: bool) -> ProvisioningOutcome:
    """A run over the named actions, optionally reaching a re-measurement."""
    bound = tuple(
        ProvisioningAction(spec=action_spec_for(name), reason="a reason") for name, _ in steps
    )
    plan = ProvisioningPlan(policy=NetworkPolicy.CACHE_ONLY, actions=bound)
    journal = ProvisioningJournal(
        plan=plan,
        steps=tuple(
            ProvisioningStep(action=entry, outcome=result, detail="a detail")
            for entry, (_, result) in zip(bound, steps, strict=True)
        ),
    )
    return ProvisioningOutcome(
        before=proposal(),
        journal=journal,
        after=BootstrapOutcome(report=report()) if after else None,
    )


def test_a_run_with_nothing_to_do_says_so() -> None:
    text = cli.render_journal_human(
        ProvisioningOutcome(
            before=proposal(),
            journal=ProvisioningJournal(plan=ProvisioningPlan(policy=NetworkPolicy.OFFLINE)),
            after=BootstrapOutcome(report=report()),
        )
    )
    assert "Nothing to do" in text


def test_every_step_is_named_with_its_outcome() -> None:
    text = cli.render_journal_human(
        outcome_with(("paths.create", ActionOutcome.APPLIED), after=True)
    )
    assert "APPLIED" in text
    assert "paths.create" in text
    assert "a detail" in text


def test_an_incomplete_run_says_the_claim_is_still_there() -> None:
    """The sentence an operator needs, on the run that most needs it."""
    text = cli.render_journal_human(
        outcome_with(
            ("paths.create", ActionOutcome.FAILED),
            ("environment.create", ActionOutcome.NOT_ATTEMPTED),
            after=False,
        )
    )
    assert "did not complete" in text
    assert "claim it wrote is still there" in text


def test_a_complete_run_ends_with_the_re_measurement() -> None:
    text = cli.render_journal_human(
        outcome_with(("paths.create", ActionOutcome.APPLIED), after=True)
    )
    assert "PASS" in text


# ---------------------------------------------------------------------------
# render_json_document
# ---------------------------------------------------------------------------


def test_the_json_document_is_canonical() -> None:
    """Sorted keys and compact separators, so two runs compare byte for byte."""
    rendered = cli.render_json_document({"b": 1, "a": {"d": 2, "c": 3}})
    assert rendered == '{"a":{"c":3,"d":2},"b":1}'
    assert json.loads(rendered)["a"]["c"] == 3


def test_the_json_document_is_ascii_only() -> None:
    """A document a reader may paste anywhere."""
    assert cli.render_json_document({"k": "é"}) == '{"k":"\\u00e9"}'


# ---------------------------------------------------------------------------
# The verb, end to end against this repository
# ---------------------------------------------------------------------------


def run(argv: list[str], start: Path | None = None) -> tuple[int, str, str]:
    """Run one command line and capture both streams."""
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, stdout=out, stderr=err, start=start)
    return code, out.getvalue(), err.getvalue()


def test_plan_and_check_answer_identically_for_this_host(repo_root: Path) -> None:
    """The property a launcher branching on either depends on.

    It comes from both reading one report rather than from two tables agreeing,
    which is why it is asserted here against whatever this interpreter happens to
    be. Run from `.venv` both say `0`; run from a bare interpreter both say `12`,
    because `python.environment` legitimately fails and the plan derived from that
    report is not empty.
    """
    planned, plan_out, _ = run(["bootstrap", "plan"], start=repo_root)
    checked, _, _ = run(["bootstrap", "check"], start=repo_root)
    assert planned == checked
    assert plan_out.endswith("\n")


def test_plan_under_json_writes_the_document_to_standard_output(repo_root: Path) -> None:
    """Standard output carries JSON and nothing else.

    That is the rule every other verb here follows, and a human summary goes to
    standard error instead.
    """
    _, out, err = run(["bootstrap", "plan", "--json"], start=repo_root)
    document = json.loads(out)
    assert document["plan"]["policy"] == "offline"
    assert "capability" in document
    assert err.strip()


def test_plan_accepts_a_declared_policy(repo_root: Path) -> None:
    _, out, _ = run(["bootstrap", "plan", "--network", "cache-only", "--json"], start=repo_root)
    assert json.loads(out)["plan"]["policy"] == "cache-only"


def test_plan_reports_whether_a_claim_is_outstanding(repo_root: Path) -> None:
    """The field is always present, so a reader never has to infer its absence."""
    _, out, _ = run(["bootstrap", "plan", "--json"], start=repo_root)
    assert "outstanding" in json.loads(out)


@pytest.mark.parametrize("word", ["verify", "provision", "install"])
def test_a_word_that_is_not_a_verb_is_refused(word: str) -> None:
    with pytest.raises(cli.UsageError):
        cli.parse(["bootstrap", word])
