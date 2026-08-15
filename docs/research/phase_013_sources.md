# Phase 013 — Research Source Ledger

Phase 013's CI hardening rests on external facts in two places, and this ledger
records what was read, or resolved, before either was depended on.

The first is **what each pinned commit actually is**. A forty-character SHA is a
claim about an upstream repository, and until this phase the claim beside each one
in `.github/workflows/quality.yml` was checked by nothing. Two of the four were
wrong. Entries S-01 to S-04 record the resolution of every pin against two
independent sources, and what each was observed to be.

The second is **GitHub Actions platform behaviour**: the merge-queue event, the
job execution ceiling, and whether cancellation may be made conditional. Each is
a behaviour the hardening's correctness rests on, and none appeared in an earlier
ledger.

**Ledger conventions.** One entry per claim relied on, not per page read. Each
records where the claim is authoritative, when it was consulted, how far it may be
trusted, the exact statement it supports, and what GLOBIN did as a result.
Official upstream documentation is primary for its own product
([`docs/SOURCE_POLICY.md`](../SOURCE_POLICY.md)). An entry is appended, never
rewritten: if a claim turns out to be wrong, a later phase's ledger records the
correction.

**Entries S-01 to S-04 were verified by resolving the tags on this machine**
(Windows 11, `git` 2.x and the GitHub REST API), not only by reading a page. Each
gives the observed value. Two independent methods were used and agreed exactly on
every tag: the REST tag listing, and `git ls-remote --tags --refs` against the
repository's HTTPS URL. One API is a single point of trust; the raw git protocol
is a different code path to the same upstream.

---

## What the pins are

### S-01 — `actions/checkout@fbc6f39…` is v5.1.0, not v5.0.0

- **Canonical location:** `actions/checkout` — `https://github.com/actions/checkout`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the action's own repository, resolved through both the
  GitHub REST tag listing and the git protocol.
- **Supports:** `fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09` carries the tags
  `v5.1.0` and `v5`. The tag `v5.0.0` is a different commit,
  `08c6903cd8c0fde910a37f88322edcfb5dd907a8`. The workflow's comment read
  `# v5.0.0`.
- **Implication for GLOBIN:** The comment was corrected to `# v5.1.0` and the SHA
  left untouched, because the pin is what executes and changing it would be an
  upgrade rather than a correction. The pin is recorded in
  [`action-pins.toml`](../engineering/action-pins.toml), which the contract suite
  compares against the workflow so the two cannot drift again.

### S-02 — `actions/setup-python@ece7cb06…` is v6.3.0, not v6.0.0

- **Canonical location:** `actions/setup-python` — `https://github.com/actions/setup-python`
- **Accessed:** 2026-08-15
- **Authority:** Primary — as above, both methods agreeing.
- **Supports:** `ece7cb06caefa5fff74198d8649806c4678c61a1` carries the tags
  `v6.3.0` and `v6`. The tag `v6.0.0` is
  `e797f83bcb11b83ae66e0230d6156d7c80228e7c`. The workflow's comment read
  `# v6.0.0`.
- **Implication for GLOBIN:** Corrected to `# v6.3.0`, SHA unchanged, for the
  reason S-01 gives. Both errors share a cause worth recording: a pin taken from a
  moving major tag freezes the commit but not the label, so writing the major's
  first release beside it is wrong the moment the major moves.

### S-03 — `actions/upload-artifact@043fb46d…` is v7.0.1, as claimed

- **Canonical location:** `actions/upload-artifact` — `https://github.com/actions/upload-artifact`
- **Accessed:** 2026-08-15
- **Authority:** Primary — as above, both methods agreeing.
- **Supports:** `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` carries the tags
  `v7.0.1` and `v7`, matching the workflow's comment.
- **Implication for GLOBIN:** Recorded unchanged. A ledger that noted only the
  failures would leave the reader unable to tell a verified pin from an unexamined
  one.

### S-04 — `actions/download-artifact@3e5f45b2…` is v8.0.1, as claimed

- **Canonical location:** `actions/download-artifact` — `https://github.com/actions/download-artifact`
- **Accessed:** 2026-08-15
- **Authority:** Primary — as above, both methods agreeing.
- **Supports:** `3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c` carries the tags
  `v8.0.1` and `v8`, matching the workflow's comment.
- **Implication for GLOBIN:** Recorded unchanged, as S-03.

### S-05 — A tag ref may point at a tag object rather than a commit

- **Canonical location:** Git — *Git Internals: Git References*, `https://git-scm.com/book/en/v2/Git-Internals-Git-References`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the version control system's own reference.
- **Supports:** A lightweight tag's ref points directly at a commit; an annotated
  tag's ref points at a tag object, which must be dereferenced to reach the commit.
  All four references above were observed to be the former, with the REST API
  reporting `"type": "commit"` for each.
- **Implication for GLOBIN:** The update procedure in
  [`CI_SECURITY.md`](../engineering/CI_SECURITY.md) states the dereferencing step
  explicitly, so that a future action published with annotated tags is not pinned
  to a tag object's hash — which would be a valid-looking forty-character SHA that
  GitHub could not resolve to a commit.

---

## GitHub Actions

### S-06 — `merge_group` supports one activity type, and naming it is advised

- **Canonical location:** GitHub Docs, *Events that trigger workflows*, `https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the platform's own documentation.
- **Supports:** The event is written `merge_group:` with
  `types: [checks_requested]`, and `checks_requested` is the only activity type
  supported. The documentation adds that specifying the activity type keeps a
  workflow specific if more are added in future.
- **Implication for GLOBIN:** The trigger is declared with its type named rather
  than left bare, so that a type added later cannot start triggering this workflow
  without a decision.

### S-07 — `GITHUB_REF` under `merge_group` is the merge group's ref

- **Canonical location:** GitHub Docs, *Events that trigger workflows*, `https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows`
- **Accessed:** 2026-08-15
- **Authority:** Primary — as above.
- **Supports:** For a `merge_group` event, `GITHUB_REF` is the ref of the merge
  group, not the base branch it will merge into.
- **Implication for GLOBIN:** The concurrency rule compares `github.ref` against
  `refs/heads/master` to decide whether a superseded run may be cancelled. Because
  a merge-group run's ref is the queue's, it is correctly treated as cancellable —
  only pushes to master itself are protected, which is where the evidence chain
  lives.

### S-08 — `cancel-in-progress` may be an expression

- **Canonical location:** GitHub Docs, *Workflow syntax for GitHub Actions*, `https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax`
- **Accessed:** 2026-08-15
- **Authority:** Primary — as above.
- **Supports:** To conditionally cancel running jobs in the same concurrency
  group, `cancel-in-progress` may be given as an expression using the allowed
  contexts, which are `github`, `inputs` and `vars`. The documentation's own
  example conditions on `github.ref`.
- **Implication for GLOBIN:** Cancellation is expressed as
  `${{ github.ref != 'refs/heads/master' }}` rather than a literal, which is what
  makes ADR-0043's rule expressible at all. The context used is `github`, which is
  among those permitted.

### S-09 — A job runs for at most six hours, then is terminated and fails

- **Canonical location:** GitHub Docs, *Usage limits, billing, and administration*, `https://docs.github.com/en/actions/reference/limits`
- **Accessed:** 2026-08-15
- **Authority:** Primary — as above.
- **Supports:** Each job in a workflow can run for up to 6 hours of execution time
  on a GitHub-hosted runner. If a job reaches this limit, the job is terminated and
  fails. Self-hosted runners allow 5 days.
- **Implication for GLOBIN:** This is what an undeclared `timeout-minutes`
  actually means, and it is why every job now declares one. Six hours is long
  enough that a wedged job resembles a working job for most of a working day, and
  a required check that hangs blocks a branch as effectively as one that fails.

### S-10 — The measured job durations the budgets were derived from

- **Canonical location:** This repository's own CI runs, read through the GitHub
  API — `https://github.com/aydhn/GLOBIN/actions`
- **Accessed:** 2026-08-15
- **Authority:** Primary, and observational rather than documentary: these are
  measurements of this workflow on `windows-latest`, not a published claim.
- **Supports:** Across runs `31848929219`, `31853639648` and `31854207475`, all
  concluding `success`, the maximum observed duration per job was: `quality` 2.48,
  `mutation` 6.48, `shards` 1.83, `evidence` 2.07, `hygiene` 1.02 and `aggregate`
  0.65 minutes.
- **Implication for GLOBIN:** The budgets in
  `[tool.globin.workflow.timeouts]` are five to ten times these values, with a
  floor of ten minutes. Recording the measurements beside the decision is what
  makes a future adjustment an informed edit rather than a guess; the numbers
  describe three runs on one runner generation and should be re-measured before
  being tightened.
