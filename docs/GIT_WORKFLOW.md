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
`tests/test_project_contract.py`, and `tests/test_documentation_contract.py`
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

## Definition of done

A phase is complete only when **all** of the following hold:

1. Phase-specific tests pass.
2. Required regression checks pass.
3. No secrets or generated artefacts are committed.
4. Documentation matches the implementation.
5. A meaningful commit exists on `master`.
6. The commit is pushed to `origin/master`.
7. Local `master` and `origin/master` are the same commit.
8. `git status --porcelain` is empty.

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
