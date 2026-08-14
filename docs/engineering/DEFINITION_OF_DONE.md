# Definition of Done

The conditions under which work in GLOBIN may be called complete. This is the
canonical list; [`GIT_WORKFLOW.md`](../GIT_WORKFLOW.md) and
[`PROJECT_CHARTER.md`](../PROJECT_CHARTER.md) point here rather than keeping
their own copies.

"Done" is not a feeling about the work. It is this checklist, and every item is
either true or the work is not done.

---

## 1. The change itself

- [ ] **The scope is stated.** You can say in one sentence what this change
      delivers, and which phase it belongs to.
- [ ] **The scope is neither widened nor narrowed.** Nothing from a later phase
      was implemented along the way; nothing from this phase was quietly
      deferred. If part of the phase is genuinely blocked, everything else is
      finished and the blocked part is reported explicitly.
- [ ] **It fits the existing architecture.** It obeys
      [`ENGINEERING_CONTRACT.md`](ENGINEERING_CONTRACT.md), contradicts no
      accepted ADR, and introduces no second way of doing something the
      repository already does one way.
- [ ] **The implementation is complete.** No `TODO`, `FIXME`, `XXX`, `TBD`,
      placeholder, stub or dummy implementation remains. Work that is not
      finished is not delivered.
- [ ] **New dependencies are justified.** Any addition satisfies
      [ADR-0003](../adr/0003-zero-budget-open-source-dependency-policy.md) and
      says in writing why it is necessary. Adding one also means updating
      `tests/contract/test_packaging_contract.py`, which asserts the runtime dependency
      list is empty — that is deliberate friction, not an obstacle to route
      around.

## 2. Tests

- [ ] **Tests were written with the behaviour, not after it.**
- [ ] **They test invariants, not appearances.** No snapshotting of whole
      documents or formatted output. Reasoning in
      [`TESTING_STRATEGY.md`](../TESTING_STRATEGY.md).
- [ ] **A bug fix carries a regression test** that fails without the fix.
- [ ] **Nothing is skipped, weakened or deleted to make the suite pass.** A
      failing test is information. Suppressing it destroys the information and
      keeps the defect.

## 3. Documentation

- [ ] **Documentation matches the implementation.** A phase whose documentation
      contradicts its code is incomplete
      ([ADR-0010](../adr/0010-living-documentation-responsibilities.md)).
- [ ] **Public interface changes are documented.**
- [ ] **Decisions with lasting consequence have an ADR.** Use
      [`../adr/TEMPLATE.md`](../adr/TEMPLATE.md).
- [ ] **External behaviour relied upon is recorded** in
      `docs/research/phase_NNN_sources.md` with canonical location, access date
      and authority ([`SOURCE_POLICY.md`](../SOURCE_POLICY.md)).
- [ ] **Nothing is described in the present tense that does not yet exist.**
- [ ] **No document duplicates another.** Conventions in
      [`DOCUMENTATION_STANDARD.md`](DOCUMENTATION_STANDARD.md); precedence in
      [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md).

## 4. The verification gate

Run it. Do not infer its result.

```bash
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

- [ ] **Package import** succeeds.
- [ ] **`pytest`** passes in full.
- [ ] **`ruff check`** is clean.
- [ ] **`ruff format --check`** is clean.
- [ ] **`mypy --strict`** is clean.

Because GLOBIN has no pull request and no reviewer (ADR-0005), this script is the
only gate between a change and the repository.

## 5. The diff

- [ ] **You have read it.** `git diff --cached` in full, not just the file list.
- [ ] **No credentials.** No API key, token, private key, `.env` file or
      personal data — in the diff *or* in test fixtures.
- [ ] **No generated or cache artefacts.** No `__pycache__/`, `.pytest_cache/`,
      `.mypy_cache/`, `.ruff_cache/`, coverage output, build output, data,
      models or logs. `.gitignore` is a safety net, not a substitute for looking.
- [ ] **No unexpected files.** Every changed file is one you meant to change.
      Anything else is either a mistake or someone else's work in progress.
- [ ] **No unrelated reformatting** and no mass line-ending change. A large diff
      in files you did not touch means something went wrong.
- [ ] **Repository-relative links resolve.** Enforced by
      `tests/contract/test_repository_contract.py`.
- [ ] **`git diff --check`** reports nothing.

## 6. Delivery

- [ ] **The branch is `master`.** There is no other branch
      ([ADR-0005](../adr/0005-master-only-git-workflow.md)).
- [ ] **One meaningful commit** whose message names the phase and what it
      established.
- [ ] **Pushed to `origin/master`.**
- [ ] **Local and remote agree:** `git rev-parse HEAD` equals
      `git rev-parse origin/master`.
- [ ] **The working tree is clean:** `git status --porcelain` prints nothing.

Procedure in [`GIT_WORKFLOW.md`](../GIT_WORKFLOW.md). Commit and push at phase
end are pre-authorized by the owner ([`AGENTS.md`](../../AGENTS.md)) — that
authorization covers delivery, not verification. Establishing that the work is
actually ready remains the contributor's responsibility.

## 7. Reporting

- [ ] **Evidence, not assurance.** The exact commands run and their results, the
      commit hash, whether the push succeeded.
- [ ] **Anything unverified is named as unverified**, along with the phase that
      must verify it. Silence must never be read as confirmation.
- [ ] **Anything deliberately left out is stated**, with the reason.

---

## What "done" does not mean

**It does not mean the tests passed.** A suite can pass because it asserts
nothing interesting. Judge the suite by what it would catch.

**It does not mean nothing broke.** It means you checked.

**It does not mean the work is perfect.** Phases are allowed to leave things to
later phases — that is the design. What they are not allowed to do is leave
things *silently*.

---

## When you cannot finish

Finish everything that is not blocked, then report the blockage plainly: what is
incomplete, why, and what would unblock it.

Do not mark a phase complete with an outstanding blocker, and do not narrow the
phase to make the blocker disappear. Scaling work down is the owner's decision,
not the contributor's. A phase honestly reported as blocked is recoverable; one
falsely reported as complete corrupts every later phase that builds on it.
