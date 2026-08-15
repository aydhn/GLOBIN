# ADR-0043 — CI trust is declared in a manifest the workflow is compared against, and every job is bounded

## Status

Accepted — Phase 013.

**Date:** 2026-08-15

## Context

[ADR-0020](0020-verification-only-continuous-integration.md) established that CI
verifies rather than repairs, with least privilege and actions pinned to commits.
[ADR-0042](0042-one-aggregate-check-decides-a-run-and-the-artifact-digest-lives-outside-the-artifact.md)
reduced the run to one aggregate check fit to be required on `master`. Both hold.
This record adds what neither covered, and corrects one thing both assumed was
true.

**A pin was accountable to nothing.** Because forty hex characters are unreadable,
each `uses:` carries a trailing comment naming the release. The SHA executes; the
comment does not. Two of this repository's four comments named a version their
commit did not have — `actions/checkout@fbc6f39` was labelled `v5.0.0` and is
`v5.1.0`, `actions/setup-python@ece7cb06` was labelled `v6.0.0` and is `v6.3.0` —
and had been wrong since Phase 012 with no test, no gate and no reviewer noticing.
Nothing broke, which is the point: the comment was the only human-readable account
of what runs against this repository, and half of it was fiction that could not
fail.

**No job was bounded.** No `timeout-minutes` appeared anywhere, so every job ran
until GitHub's six-hour platform ceiling. A required check that hangs blocks a
branch as effectively as one that fails and explains less.

**Cancellation was unconditional.** `cancel-in-progress: true` applied to master
as well as to pull requests. A cancelled job reports `cancelled`, which the
aggregate reads as unmeasured, so a master push arriving during an earlier run
destroyed that commit's evidence — the record ADR-0042 exists to produce.

**The workflow could not run in a merge queue,** which rules the option out by
omission rather than by decision.

### The phase this lands in

`ROADMAP.md` assigns Phase 013 to *Coding Standards and Documentation
Conventions*. The brief the owner supplied described CI security hardening
instead. An audit found most of that brief already delivered by Phase 012 — SHA
pinning, `contents: read`, a namespaced concurrency group, `persist-credentials:
false`, a stable required check, and contract tests for the first three — leaving
the six items above, none of which any phase in the programme owns. Supply-chain
review belongs to Phase 014 and secret handling to Phase 015; neither is this.

This is the ninth such collision. The owner was given four options and chose to
build the hardening **beside** the phase, under
[ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md), with
Phase 013 left `Planned` and its scope untouched.

**One of ADR-0032's six conditions does not hold as written, and that is recorded
rather than argued around.** Condition 2 requires that the phase's own deliverable
be delivered in full in the same commit. It is not: Phase 013 has not started.
The four prior uses of ADR-0032 all landed beside a phase being delivered; this
one lands before it. Conditions 1, 3, 4, 5 and 6 hold unchanged — nothing in the
programme owns this work, no dependency is added, nothing under `src/globin/`
gains behaviour, no gate changes what it does, and it is documented and tested to
the same standard as everything else.

The risk condition 2 guards against is real and is named here plainly: "it is
only tooling" is exactly the sentence somebody would use to spend a phase slot
without doing the phase. What limits it is that Phase 013's deliverable is
unchanged, unstarted and undiminished — `ROADMAP.md` still says what it said, the
status is still `Planned`, `LAST_COMPLETED_PHASE` is still 12, and the pydocstyle
rules Phase 004 parked are still parked with the comment that parks them.

## Decision

**1. Every pinned commit is declared in a manifest, and the workflow is compared
against it in both directions.** `docs/engineering/action-pins.toml` records, per
action, the upstream repository, the full SHA, the tag that SHA carried, and the
date a human verified it. `tests/contract/test_ci_security_contract.py` fails when
the workflow pins something the manifest does not list, when the manifest lists
something the workflow no longer uses, when a version comment disagrees with the
manifest, or when the manifest names a different upstream than the workflow
fetches from.

**2. Nothing generates the manifest.** A file produced from the workflow could
only ever agree with the workflow, which is a mirror rather than a check. It is
written by the person who resolved the tag, and it is a tripwire in the sense
[`SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md) requires: a second copy
justified only because something compares the two.

**3. A SHA is verified against two independent sources that agree.** The GitHub
REST API and the raw git protocol are different code paths to the same upstream;
one API alone is a single point of trust. The procedure is nine steps and lives in
[`CI_SECURITY.md`](../engineering/CI_SECURITY.md). No bot, no automatic updater.

**4. A pin's version comment is corrected, never its SHA, when the two disagree.**
Choosing a different version is an upgrade, and an upgrade is Phase 014's review
process, which does not exist yet. Phase 013 changed no SHA.

**5. Only first-party `actions/*` repositories are used.** A third-party action, a
fork, or a mirror of a familiar name is a decision to be recorded, not a default
that arrives with a copied snippet.

**6. Every job declares `timeout-minutes`, and every budget is declared twice.**
The budgets live in `[tool.globin.workflow.timeouts]` with the measured durations
they were derived from recorded beside them, and the contract module compares that
table against the workflow in both directions. Values are derived from observation,
not chosen for roundness, and carry enough margin that a slow runner produces a
slower run rather than a red one.

**7. Cancellation is conditional, and master is the exception.** A superseded pull
request or merge-queue run is cancelled. A master run is not, because it is the
only thing that produces that commit's evidence. Pushes to master queue instead.

**8. The workflow declares `merge_group`, and nothing enables a merge queue.**
Enabling one is a repository setting no file here can change. Declining to rule it
out is not the same as turning it on.

**9. Untrusted event fields never reach a `run:` block, and the `env:` form is
explicitly permitted.** A checker that forbade its own remedy would be a checker
people switch off, so a test proves the safe shape passes.

**10. Every checker is exercised against a deliberately broken copy, held as a
string.** `check-yaml` runs over everything committed and a file under
`.github/workflows/` is not a fixture but a workflow, so the mutants cannot exist
on disk.

## Consequences

The two wrong version comments are corrected, and the class of defect cannot
recur silently: a comment that drifts from the manifest now fails the suite.

Maintaining a pin costs more than it did. Updating an action is nine steps across
three files rather than one edit, and the manifest must be updated in the same
commit or the suite fails. That is the intended trade: the previous cost was zero
and bought a record that was half wrong.

The manifest goes stale by design. `verified` is a date nothing refreshes, so an
old one is visible as an old one. Nothing forces re-verification, and nothing
should — a scheduled job re-resolving tags would be a network dependency inside a
suite that is offline by construction (ADR-0024).

Master runs no longer cancel, so consecutive pushes queue rather than supersede.
On a repository with one developer this costs a few runner-minutes occasionally
and buys an evidence bundle per commit.

A hung job now fails at its budget instead of at six hours. A budget that turns
out to be too tight will present as a flaky failure, which is why the margins are
wide and why the measured durations are recorded next to the numbers — the next
person to adjust one can see what it was derived from.

`Configuration` gains a field, so anything constructing one directly must supply
it. Only `tests/unit/test_workflow.py` did.

## Alternatives Considered

**Generate the manifest from the workflow.** Rejected: it could only ever agree
with its own input. The disagreement between comment and reality is exactly what
needed catching, and a generator would have reproduced the wrong versions
faithfully.

**Verify SHAs against upstream from within the test suite.** Rejected: the suite
is offline by construction (ADR-0024), and widening that would need an ADR
superseding it. Verification is a human step recorded in a ledger; the suite
checks internal consistency, which is what it can check honestly.

**Add a YAML parser.** Rejected. Three contract tests pin the `dev` extra at
exactly six names, per-package import allowlists would reject `yaml`, and PyYAML
is present locally only as a transitive dependency of `pre-commit`, which four of
the six CI jobs do not install — so a test importing it would pass on this machine
and fail in CI. This also satisfies ADR-0032's third condition, which a parser
would have broken outright.

**Add Dependabot or a renovation bot to keep pins current.** Rejected as out of
scope. Deciding whether to adopt a version is Phase 014's review process; a bot
that opens the pull request does not perform the review, and adding one now would
manufacture a stream of decisions nobody has criteria for.

**Ban untrusted contexts everywhere rather than in `run:` blocks only.**
Rejected: it would forbid the `env:` indirection that is the documented
remediation, leaving no compliant way to use a value that is sometimes legitimately
needed.

**Amend the roadmap so Phase 013 is CI security.** Rejected, and not available:
`MEMORY.md` records the amendment budget as spent, with a standing instruction
that a further one be refused rather than argued.

## Risks and Trade-offs

**The manifest can be wrong.** Nothing checks it against upstream, so a human who
records the wrong tag creates a consistent, tested, incorrect record. The
two-source procedure is the mitigation and it is a procedure, not a gate. This is
an honest limit: the alternative is a network call inside an offline suite.

**Landing tooling before the phase it sits beside is a precedent.** Stated in the
Context because it is the weakest part of this record. If it recurs, ADR-0032's
condition 2 should be rewritten to say what is actually meant rather than being
read past each time.

**Timeout values will age.** They are derived from three runs on
`windows-latest` in August 2026. A slower runner generation, a larger suite or a
third mutation target could bring a real run closer to its budget. The margins are
five to ten times the observed maximum, and the measured values are recorded so
that a future adjustment is an informed edit rather than a guess.

**Not cancelling master runs assumes master pushes are infrequent.** On a
repository with many contributors this would queue runs behind each other and
delay feedback. GLOBIN is master-only with one developer (ADR-0005), so the
assumption holds for as long as that does.

**The untrusted-context list cannot be exhaustive.** The event payload is large
and GitHub adds to it. The list covers the fields documented as
attacker-controlled and seen in real injections; a field added later would not be
caught until somebody adds it.

## References

- [`docs/engineering/CI_SECURITY.md`](../engineering/CI_SECURITY.md)
- [`docs/engineering/action-pins.toml`](../engineering/action-pins.toml)
- [`docs/research/phase_013_sources.md`](../research/phase_013_sources.md)
- [ADR-0020](0020-verification-only-continuous-integration.md)
- [ADR-0024](0024-tests-are-offline-and-isolated-by-construction.md)
- [ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md)
- [ADR-0042](0042-one-aggregate-check-decides-a-run-and-the-artifact-digest-lives-outside-the-artifact.md)

## Supersedes

None.

## Superseded By

None.
