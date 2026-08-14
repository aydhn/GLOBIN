# ADR-0020 — Continuous integration verifies, with least privilege and pinned actions

## Status

Accepted — Phase 004.

**Date:** 2026-08-14

## Context

GLOBIN had no continuous integration. The gate was `scripts/verify.ps1`, run by
whoever was making the change, and a master-only workflow
([ADR-0005](0005-master-only-git-workflow.md)) means nothing independent
confirmed it had been run. `AGENTS.md` prohibits reporting a check as passing
without running it, but prohibition is not verification.

Adding CI to a repository that will eventually hold trading logic raises the
question of what a pipeline is *for* before what it should run. Two failure
modes are worth naming, because both are common and both are worse than having
no CI at all.

A pipeline that repairs what it measures — reformatting, applying fixes,
committing corrections — destroys its own result: the thing that passed is no
longer the thing that was committed. And a pipeline with more privilege than it
needs turns every dependency it pulls into a path to the repository. Anyone with
write access to an action's tag can change what runs, and a mutable tag reference
is an open invitation to do so.

## Decision

**1. CI verifies and never repairs.** No step commits, pushes, formats, applies
a fix, or writes to the repository. A contract test asserts the workflow
contains no such step.

**2. Least privilege.** `permissions: contents: read` is declared at workflow
level, so a job added later starts read-only rather than inheriting the
repository default.

**3. Every action is pinned to a full 40-character commit SHA,** with the
release recorded in a trailing comment for humans. A tag is mutable; the SHA is
what executes. A contract test rejects any `uses:` reference that is not a SHA.

**4. No secrets, no exchange, no deployment.** Quality checks need no
credential, and GLOBIN has none. The workflow references no secret, no Binance
endpoint and no testnet, and a contract test asserts this.

**5. CI runs the canonical gate**, `python -m tools.quality full`, rather than
its own list of checks.

**6. The GLOBIN package is not installed.** The suite runs from `src/` via
`pythonpath`. Building a distribution is Phases 017-032 work and must not be
described as verified before then.

**7. No step may fail quietly.** No `continue-on-error`, no `|| true`, no
trailing `exit 0`. A contract test asserts each absence.

## Consequences

- A push to `master` or a pull request targeting it is independently verified,
  so "the gate passed" stops depending on someone remembering to run it.
- Action upgrades are deliberate. A new SHA is a visible diff someone approves,
  rather than a tag moving underneath the repository.
- The workflow runs on `windows-latest`, the only platform GLOBIN declares. That
  is slower and more expensive than Linux, and it is the platform that actually
  exercises the CRLF rules in `.gitattributes`.
- Two interpreters are tested, 3.12 and 3.14. That is the floor
  `requires-python` declares and the version development happens on.
- The interpreter matrix and the pinned tool versions are **provisional** and
  labelled as such in the workflow. Phase 018 owns interpreter selection, Phase
  020 owns dependency locking, and neither is being decided here.
- Because CI cannot fix anything, a formatting failure means a developer runs
  `reformat` locally and commits the result. That is one more round trip, and it
  is the point.

## Alternatives Considered

**No CI, keeping `verify.ps1` as the only gate.** Rejected. It relies entirely
on discipline, and it cannot catch the case that matters most in a master-only
workflow: a change pushed after a gate that was not actually run.

**Pin actions to tags.** Rejected. GitHub's own guidance states that pinning to
a commit SHA is the most secure option, and permits tags only where the
creator is trusted. A trading system's repository is not the place to trade that
margin for convenience.

**Run on `ubuntu-latest`.** Rejected, though it is cheaper and faster. GLOBIN
targets one Windows host, `.gitattributes` encodes Windows-specific line-ending
behaviour, and a Linux-only pipeline would never exercise either. Testing on a
platform the project does not support gives confidence about the wrong thing.

**Let CI apply formatting and push the result.** Rejected outright. It requires
write permission, which defeats the privilege model, and it makes the verified
artefact differ from the committed one.

**Add caching for dependencies and hook environments.** Deferred, not rejected.
It is an optimisation whose configuration would need revisiting when Phase 020
introduces lockfiles.

## Risks and Trade-offs

The characteristic failure of pinned SHAs is staleness. Pins do not update
themselves, so a security fix in an action does not arrive, and the repository
quietly runs an old version indefinitely. That is the accepted cost of not
trusting a mutable tag, but it is a cost: pins need reviewing at band boundaries,
and the observable signal is a pin whose comment names a release several major
versions behind.

The exact tool-version pins carry a sharper version of the same risk, made worse
by their being untested against the interpreter matrix at the time of writing.
This workflow has never executed: it is authored, reviewed and checked by
contract tests, but its first real run happens on push. A pin without a wheel
for one of the two interpreters would fail on that first run.

There is also a subtler risk in CI existing at all. An independent gate makes it
tempting to treat a green pipeline as the definition of correctness, when it
runs exactly the checks someone chose to write. `DEFINITION_OF_DONE.md` puts it
directly: a suite can pass because it asserts nothing interesting.

## References

- [`../engineering/QUALITY_GATES.md`](../engineering/QUALITY_GATES.md) — the CI
  properties and what is deferred.
- [`../research/phase_004_sources.md`](../research/phase_004_sources.md) —
  entries S-07 and S-08 on GitHub Actions security and workflow syntax.
- [ADR-0019](0019-single-quality-entrypoint.md) — the entrypoint CI invokes.
- [ADR-0005](0005-master-only-git-workflow.md) — why there is no reviewer for CI
  to supplement.

## Supersedes

None.

## Superseded By

None.
