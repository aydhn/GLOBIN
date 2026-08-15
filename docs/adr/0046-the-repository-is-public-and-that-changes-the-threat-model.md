# ADR-0046 — The repository is public, and that changes the threat model rather than only the settings

## Status

Accepted — Phase 014.

## Context

`aydhn/GLOBIN` was private, owned by a personal account on GitHub's Free plan.
Probed on 2026-08-15, six of the controls Phase 014 was asked to deliver refused
with a plan ceiling: rulesets and branch protection with *"Upgrade to GitHub Pro
or make this repository public"*, code scanning with *"Code scanning is not
enabled for this repository"*, secret scanning and push protection with *"Secret
scanning is disabled on this repository"*, and artifact attestations by
documentation — private repositories need GitHub Enterprise Cloud, which neither
Pro nor Team provides.

[ADR-0003](0003-zero-budget-open-source-dependency-policy.md) prohibits paid
*runtime* services and explicitly exempts development tooling, so buying a plan
was permitted by policy. It was still money, and it would have bought only two of
the six: Pro unlocks rulesets and branch protection, while CodeQL and secret
scanning need GitHub Code Security and Secret Protection separately, and
attestations need Enterprise Cloud regardless.

Making the repository public unlocks all six, for nothing.

## Decision

**The repository is public.**

**The visibility change was gated on a full-history scan, not a working-tree
one.** Publishing exposes all 32 commits, so a credential present in one commit
and removed in the next would be published by the change. The scan covered every
filename ever committed (269 unique paths, no credential-shaped name), the
complete diff of all history (2.8 MB, no key header and no provider token
prefix), and every high-entropy string that was not a digest. The only absolute
paths in history are deliberate test fixtures using the placeholder `C:\Users\Some One\`.
Authorship is a single identity using GitHub's `users.noreply` address, already
public. Evidence: `docs/research/phase_014_sources.md`.

**Six controls were then enabled**: secret scanning, push protection, Dependabot
security updates, CodeQL through a version-controlled advanced setup, and a
`master` ruleset blocking force-pushes and deletion with no bypass actors.

**The ruleset does not require a pull request or a status check.** A required
status check is evaluated on push and the check can only run after the push, so
requiring `Quality gate` on a directly-written branch would reject the commit that
would produce the passing check. GLOBIN's contract is master-only
([ADR-0005](0005-master-only-git-workflow.md)), so the two are incompatible until
the workflow changes.

## Consequences

**Phase 013's CI hardening becomes load-bearing for the first time, and this is
the part that is easy to miss.** `permissions: contents: read`,
`persist-credentials: false`, the `pull_request_target` prohibition and the
untrusted-context rule were all written against a hazard that did not exist: a
private repository nobody could fork has no untrusted contributors. Every one of
those defences is now defending against something real. The same YAML, the same
lines, a different threat model.

Two consequences follow directly. `pull_request` now runs workflows on code
written by anyone, which is exactly why the workflow grants nothing and holds no
secret. And any future job that does need a secret must not be reachable from a
fork's pull request — the constraint that makes attestation a trusted-`master`
job only.

**Everything is now readable, including what is not code.** The research ledgers,
`MEMORY.md`, the ADRs and the reasoning in every comment. That was accepted
deliberately: the reasoning is most of what this repository is, and a system
argued for in public is one whose argument can be checked.

**Nothing about the zero-budget policy changed.** Public repositories cost
nothing, and the runtime still depends on nothing.

**The evidence base for ADR-0045's states doubled.** The same probes now return
availability where they returned refusals, and both are recorded. A capability
model demonstrated to change with a setting rather than with a commit is a
capability model somebody can trust.

## Alternatives Considered

**Stay private and record six `UNAVAILABLE_BY_PLAN` states honestly.** Entirely
defensible, and the machinery to do it was built either way. Rejected because it
delivers a documented absence where the alternative delivers the controls, at no
cost.

**Buy GitHub Pro.** Rejected: it unlocks two of the six, leaves CodeQL and secret
scanning behind separate paid products and attestations behind Enterprise Cloud,
and spends money on a subset of what visibility gives free.

**Go public but leave the security features off.** Rejected as incoherent: the
argument for going public *is* those features.

## Risks and Trade-offs

**Irreversible in effect.** Making a repository private again does not un-publish
what was cloned, forked, cached or indexed. The history scan is what made this
safe to do once, and it cannot be undone if something was missed.

**Fork pull requests can now run CI.** Bounded by the workflow granting
`contents: read`, holding no secret, pinning every action to a commit, and
checking out with `persist-credentials: false`. This is the risk Phase 013 spent
a whole phase reducing before there was anything to reduce.

**A future credential mistake is now a public one.** Push protection is enabled,
which blocks the obvious case at the point of push, and the content scanner runs
in CI. Neither is a substitute for the response procedure in
`docs/DEPENDENCY_POLICY.md`, whose first step is revoke-before-anything-else.

**Attention.** A public repository can attract issues, forks and opinions. Not a
security property, but a real cost for a single-operator project, and it is
better named than discovered.

## References

- [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) — the controls, and which live where
- [`../research/phase_014_sources.md`](../research/phase_014_sources.md) — the history scan and the probe evidence
- [`../engineering/CI_SECURITY.md`](../engineering/CI_SECURITY.md) — the trust model that now matters
- [ADR-0005](0005-master-only-git-workflow.md) — why no required status check
- [ADR-0043](0043-ci-trust-is-declared-in-a-manifest-and-every-job-is-bounded.md) — the hardening this makes load-bearing
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — the states this changed

## Supersedes

None.

## Superseded By

None.
