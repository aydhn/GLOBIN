# ADR-0047 — Repository governance is declared once and validated offline

## Status

Accepted — Phase 015.

## Context

Phase 014 built the detection and Phase 013 built the CI hardening. What neither
built was the layer people meet: who is answerable for a change, how a
security-relevant change is recognised as one, and where somebody sends a
vulnerability report.

That gap became concrete when the repository went public
([ADR-0046](0046-the-repository-is-public-and-that-changes-the-threat-model.md)).
Probed on 2026-08-15, `aydhn/GLOBIN` had no `CODEOWNERS`, no `SECURITY.md`, no
`.github/ISSUE_TEMPLATE/config.yml`, and private vulnerability reporting was
`{"enabled": false}`. The only route a reporter could find was a public issue —
which is the one route a vulnerability must never take, because a public
repository is indexed, cloned and forked continuously and nothing published there
can be withdrawn.

The awkward part is not writing those files. It is that they decay in a way
nothing else in this repository notices. Adding a workflow that no owner covers
fails nothing. Moving a scanner's configuration and leaving the sensitive-path
inventory behind fails nothing. Deleting the section of `SECURITY.md` that names
the reporting channel fails nothing. Each leaves a repository that looks governed
and is not, and each is invisible until the day it matters.

Two further constraints shaped the answer, and both are facts rather than
preferences. The owner is a **personal account**, so `@org/team` syntax cannot
resolve and an unresolvable owner is ignored by GitHub without an error. And
GLOBIN develops on `master` with no pull request
([ADR-0005](0005-master-only-git-workflow.md)), so the enforcement mechanism most
repositories reach for is unavailable here for a structural reason rather than an
oversight.

## Decision

**The governance arrangement is declared in one file and compared against the
tree in both directions.** `docs/engineering/governance.toml` is what a human
wrote down — where each governing file lives, which paths are security-sensitive
and why, what the security policy must say. `tools/quality/governance/` checks it
against what is actually there. Both directions matter and the second is the one
that decays quietly: a declared path that no longer exists and a real workflow
nobody owns are both findings.

**Nothing generates the declaration.** A manifest produced from the tree could
only ever agree with the tree, which is a mirror rather than a check — the
argument `action-pins.toml` already makes about itself. The generated artefact is
the *manifest*, which records what was found; the declaration is the claim it is
found against.

**The gate is entirely offline.** Every check reads the working tree, so it runs
on an aeroplane and so do its tests (ADR-0024). The half of governance that is a
*platform* question — whether private vulnerability reporting is switched on,
whether the ruleset still exists — is two new controls on the existing capability
probe in `tools/quality/supply/capability.py`, which already holds the credential
and the network. **A second probe was rejected**: two mechanisms asking GitHub
the same kind of question are two things to keep in step.

**There is exactly one CODEOWNERS file, and a second is a failure.** GitHub reads
the first candidate it finds — root, `.github/`, or `docs/` — rather than merging
them, so a duplicate silently overrides, and the file being ignored may be the
one somebody is maintaining.

**Coverage means more than the catch-all.** A declared sensitive path must be
matched by a pattern that names it more specifically than `*`. The catch-all
already names the only owner, so a check satisfied by it would be satisfied on
any repository with one, which is to say it would assert nothing.

**Code-owner review and required status checks are recorded as
`NOT_APPLICABLE`, with the argument attached.** Neither is probed, because no API
answer would change them: a required check is evaluated on push and can only run
after one, and GitHub does not permit anybody to approve their own pull request,
so a sole maintainer requiring their own approval could merge nothing. Recording
them is ADR-0045's rule — an absent key and a recorded state read very
differently six months later, and only one of them says anything.

**The assertions that must gate a commit are contract tests, not the command.**
`tests/contract/test_governance_contract.py` runs inside the ordinary suite, so
every `full` run and every pre-commit run gates on it. The `governance` command
exists to write the manifest, and is in neither `fast` nor `full` for the reason
`evidence` gives: it produces an artefact, and `full` reports rather than
produces.

## Consequences

**Adding a workflow now has a second obligation.** A new file under
`.github/workflows/` fails the suite until a CODEOWNERS pattern covers it. That
is deliberate friction on the single most security-relevant change anybody makes
in this repository, and it costs one line.

**The declaration is a maintenance surface.** Nineteen sensitive paths are listed
today, each with a reason, and each must still exist. A directory rename now
breaks a test — which is the point, and is also work.

**The CODEOWNERS matcher is a deliberate subset, and unsupported syntax is a
finding rather than a silent pass.** Negation, character classes and a `**` in
the middle of a pattern are refused by name. Implementing them to a standard
nobody here exercises would be untested code guarding nothing; implementing them
badly would report coverage GitHub does not agree with.

**Private vulnerability reporting became a `REQUIRED` control, so switching it
off now fails the gate.** That is the intended asymmetry: unlike the plan
ceilings ADR-0045 was written for, this is a switch the repository's owner
controls, and a security policy naming a disabled form is worse than one naming
none.

**A sixth gate package exists, and the shape is the fifth one's.** `plan.py` pure,
`manifest.py` schema-and-digest, `gate.py` the only I/O, a hand-written `cli.py`.
Repeating a solved solution is cheaper than inventing a second one, and a reader
who knows one knows all six.

## Alternatives Considered

**Write the files and check nothing.** Rejected. It is the status quo everywhere
else and it is why governance files are so reliably stale: nothing in a normal
development loop reads them, so nothing notices when they stop being true.

**Generate `CODEOWNERS` from the sensitive-path inventory.** Rejected for the
reason nothing generates `action-pins.toml`: the generated file would agree with
its source by construction, and the disagreement is the only thing worth
detecting. It would also put a governance file under a tool's control, when the
tool is what governance is meant to constrain.

**Enforce code-owner review through a ruleset rule.** Rejected as structurally
impossible rather than undesirable — see the Decision. Enabling it would leave
the repository unable to accept any change at all, which is the failure mode the
brief for this phase names: security that makes the development flow unusable.

**Add required status checks while implementing this.** Rejected, and the
reasoning is not new — `docs/DEPENDENCY_POLICY.md` and ADR-0046 already record
it. A required check is evaluated on push and can only run after one, so it would
reject the very commit that would produce the passing check.

**Put the whole thing in the supply-chain gate.** Rejected. `supply` reaches the
network and is deliberately outside `full` for that reason; governance is offline
and its assertions belong where a commit meets them. Merging the two would make
the offline half unrunnable without a credential.

**Invent an owner team, or a `security@` address, so the files look complete.**
Rejected outright. An unresolvable GitHub owner is ignored silently, and a
security address nobody reads is worse than no address: it converts a report that
would have reached somebody into one that reaches nothing while appearing to have
been delivered.

## Risks and Trade-offs

**The declaration can be gamed by shrinking it.** Nothing forces a path to be
listed as sensitive, so the cheapest way to make this gate pass is to remove an
entry. The compensating control is that each entry carries a written reason and
the file is itself a sensitive path, so removing one is a reviewable diff rather
than a silent edit — but a determined author can still do it, and no gate here
can prevent that.

**Pattern matching is asserted against this module's understanding of GitHub,
not against GitHub.** If GitHub changes how CODEOWNERS resolves, this gate keeps
reporting coverage that no longer exists. The signal would be a pull request
whose review request goes somewhere unexpected. The mitigation is the deliberate
subset: the fewer forms supported, the smaller the surface that can be wrong.

**The check for a template soliciting vulnerability detail matches phrases.** A
form asking for exploit detail in wording nobody anticipated passes. It is
fail-safe rather than fail-proof, like every other shape-matching check here, and
a checker claiming otherwise would be worse than one that says what it does.

**Two of the three files describing the reporting channel could drift together.**
The cross-check catches a policy and a chooser that disagree; it cannot catch
both being changed to the same wrong URL. The capability probe is the backstop —
it asks GitHub whether the form is actually there.

## References

- [`../security/GOVERNANCE.md`](../security/GOVERNANCE.md) — the model this record decides
- [`../security/VULNERABILITY_RESPONSE.md`](../security/VULNERABILITY_RESPONSE.md) — the lifecycle it sits inside
- [`../engineering/governance.toml`](../engineering/governance.toml) — the declaration
- [`../research/phase_015_sources.md`](../research/phase_015_sources.md) — the probes and their responses
- [ADR-0005](0005-master-only-git-workflow.md) — why code-owner review is not applicable
- [ADR-0024](0024-tests-are-offline-and-isolated-by-construction.md) — why the gate is offline
- [ADR-0042](0042-one-aggregate-check-decides-a-run-and-the-artifact-digest-lives-outside-the-artifact.md) — why this gate does not decide a run
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — the states this reuses
- [ADR-0046](0046-the-repository-is-public-and-that-changes-the-threat-model.md) — what made this urgent
- [ADR-0048](0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md) — the other half of Phase 015

## Supersedes

None.

## Superseded By

None.
