# Git Workflow

This document is authoritative for Git procedure in GLOBIN. The reasoning
behind it is in [ADR-0005](adr/0005-master-only-git-workflow.md).

## The rule

**All development happens on `master`. There is no other branch.**

The project must never create or switch to a branch named `main`, nor to
development, feature, release or temporary branches. The remote repository was
empty when Phase 1 initialised it, so the first push established `master` as the
default branch and no alternative has ever existed.

`REQUIRED_GIT_BRANCH = "master"` is asserted by
`tests/contract/test_project_contract.py`, and `tests/contract/test_documentation_contract.py`
scans this document and the other Git-authoritative documents for instructions
that would contradict the rule.

## Repository configuration

Identity is configured **repository-locally**, so the machine's global Git
configuration is left untouched:

```bash
git config user.name "aydhn"
git config user.email "108704389+aydhn@users.noreply.github.com"
```

The remote is:

```bash
git remote -v
```

which must show `origin` pointing at `https://github.com/aydhn/GLOBIN.git` for
both fetch and push.

## Phase procedure

Every phase follows the same sequence. Steps 1 and 2 are not optional, and
step 3 must not be reached until step 2 passes.

### 1. Inspect before changing

```bash
git status --short --branch
```

Confirm the branch is `master` and understand any pre-existing changes.
**Never discard unexplained modifications in the working tree.** They may be the
user's work.

### 2. Verify before staging

```bash
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

This runs the import check, the test suite, lint, format verification and strict
type checking. All must pass. Because there is no review gate on a master-only
workflow, this script *is* the gate.

### 3. Review what is about to be committed

```bash
git add -A
```

```bash
git diff --cached --stat
```

Then inspect the staged content itself and confirm that no credential, private
key, token, cache directory or build artefact is included. `.gitignore` is a
safety net, not a substitute for looking.

### 4. Commit

Use a message naming the phase and what it establishes:

```bash
git commit -m "phase N: short description of what the phase established"
```

The subject line is lowercase, imperative and specific. The body explains what
changed and why, not how.

### 5. Push

```bash
git push origin master
```

The first push of the repository used `git push -u origin master` to set
upstream tracking; subsequent pushes need only the form above.

### 6. Verify synchronization

```bash
git rev-parse HEAD
```

```bash
git rev-parse origin/master
```

Both must print the same commit hash. If they differ, the push did not take
effect and the phase is not complete.

### 7. Confirm a clean tree

```bash
git status --porcelain
```

Output must be empty. Anything printed means work is uncommitted or a generated
file is untracked and unignored.

### 8. Read the continuous integration result

The push is not the end of verification. The workflow runs the same gate on a
hosted Windows runner with none of this machine's advantages — no user-level
toolchain, no warm cache, no developer environment — and it runs the mutation
job, which the local `full` gate deliberately does not.

Find the run for the commit just pushed and report what it concluded. `gh` is the
intended way:

```bash
gh run list --limit 1
```

```bash
gh run view --log-failed
```

The repository is public as of Phase 014
([ADR-0046](adr/0046-the-repository-is-public-and-that-changes-the-threat-model.md)),
so a run can be read without a credential — but `gh` still needs to be present,
and an unauthenticated request is rate-limited far more tightly. If `gh` is
absent, or the request fails for any reason, **say the run was not read** rather
than leaving it out — an omitted CI result is indistinguishable from a passing
one, and Phase 004 was already reported once before its run existed.

## Definition of done

The Git-facing half of "done" is steps 1-8 above: verified, committed on
`master`, pushed, local and remote agreeing, working tree clean, and the
continuous integration result read.

That is not the whole definition. The canonical checklist — scope, tests,
documentation, the diff review and the reporting obligation — is
[`engineering/DEFINITION_OF_DONE.md`](engineering/DEFINITION_OF_DONE.md), and it
is the only copy. This document previously carried its own list; two copies of
one rule diverge, which is the defect
[ADR-0011](adr/0011-documentation-authority-hierarchy.md) exists to remove.

If a push fails for external reasons such as authentication, report that
plainly as an unresolved blocker. Never describe a phase as complete when its
work is not on the remote.

## Things that must not happen

- Committing credentials, API keys, tokens or private keys.
- Committing generated data, models, logs or caches.
- Force-pushing, or rewriting published history.
- Skipping verification because a change "looks trivial".
- Reporting success without having run the checks.
- Deleting working functionality to make a task simpler.
