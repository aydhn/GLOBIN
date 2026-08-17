# Dependency and Supply-Chain Policy

How a candidate dependency is reviewed, what the answer is recorded as, and what
happens when something already adopted turns out to be vulnerable.

[ADR-0003](adr/0003-zero-budget-open-source-dependency-policy.md) said "every
proposed dependency needs a licence and cost review. Phase 014 defines that
process." This is that process. Eleven other places in the repository defer to
it — `pytest-xdist` ([ADR-0036](adr/0036-test-execution-is-sharded-by-a-stable-digest-not-by-a-plugin.md)),
`mutmut` ([ADR-0033](adr/0033-mutation-testing-is-a-repository-native-ast-harness.md))
and a YAML parser ([ADR-0043](adr/0043-ci-trust-is-declared-in-a-manifest-and-every-job-is-bounded.md))
were each refused pending its existence.

Everything here is asserted by the suite and by
`python -m tools.quality supply`. Where this document and the code disagree, the
code is right and the disagreement is a defect —
[`SOURCE_OF_TRUTH.md`](engineering/SOURCE_OF_TRUTH.md).

---

## The threat this is about

A dependency is code you did not write, executing with your privileges, chosen
by someone you have not met, and updated without asking. Four ways that goes
wrong are worth naming separately, because they need different answers.

**The dependency has a known defect.** Someone published an advisory; nobody
here read it. Answered by `pip-audit`, run in CI, fail-closed.

**The dependency changed under you.** A mutable tag now points somewhere else.
Answered by pinning every remote reference to an immutable commit, and by
comparing the pins against a manifest a human verified —
[`engineering/CI_SECURITY.md`](engineering/CI_SECURITY.md).

**The dependency's licence obliges something nobody read.** Answered by
recording the licence and its source for every declared package, in
[`engineering/dependency-reviews.toml`](engineering/dependency-reviews.toml).

**The dependency was never worth having.** The one no tool answers. A scanner
tells you whether what you took is broken; nothing but a person tells you whether
you should have taken it. That is what the review below is for.

---

## Reviewing a candidate

Six questions. All six are answered in writing before adoption, and the answers
go in `dependency-reviews.toml`.

**1. What does it cost transitively?** Not "is it small" — resolve it and count.
`pip-audit` alone took this repository's audited set from a handful to
twenty-six distributions. That is the number to weigh, not the one on the badge.

**2. What is the licence, and where did you read it?** The project's own
published text, not a summary site. Record both. See the allow list below.

**3. Is it maintained?** Release cadence, open issue behaviour, whether one
person could stop and nobody would notice. A dead dependency is a defect with a
delivery date.

**4. Does it run at runtime, or only in development?** ADR-0003's zero-budget
rule binds the runtime absolutely; development tooling is explicitly exempt.
`project.dependencies` is empty and a contract test keeps it that way, so
anything adopted today is a development dependency by construction. Phase 021
introduces the first runtime dependency; when it does, the lock gate refuses to
pass until `pylock.toml` accompanies it, and the severity threshold below needs
the argument it says it needs.

**5. Could this be written instead?** Not always, and not usually. But
ADR-0033's mutation harness, ADR-0036's shard planner and Phase 014's own SBOM
generator are each a few hundred lines that replaced a dependency, and each is
byte-deterministic in a way the tool it replaced was not. Ask; then answer
honestly. `pip-audit` was reviewed under this question and adopted — advisory
range-matching across ecosystems is exactly the kind of thing that fails
silently when written by hand.

**6. What breaks if it disappears?** Reversibility. A test runner is load-bearing
for every test; an audit tool can be swapped in an afternoon.

### Recording the answer

Add a `[[review]]` to
[`engineering/dependency-reviews.toml`](engineering/dependency-reviews.toml) with
the licence, its source, the review date and the verdict. A contract test
compares that register against the generated inventory **in both directions**: a
declared dependency with no review fails the suite, and so does a review for
something no longer declared.

GitHub Actions are reviewed differently and elsewhere. The question there is not
"may we depend on this" but "is this exact commit the one we verified", and
[`engineering/action-pins.toml`](engineering/action-pins.toml) already answers
it under the nine-step procedure in
[`engineering/CI_SECURITY.md`](engineering/CI_SECURITY.md).

---

## Licences

| Verdict | Licences | Why |
|---|---|---|
| **Allowed** | MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0, 0BSD, Zlib, CC0-1.0 | Permissive. No obligation beyond attribution, and the last three not even that. |
| **Allowed with a note** | MPL-2.0, LGPL-3.0 | File-scoped or link-scoped copyleft. Permitted where GLOBIN neither vendors nor modifies the source — `hypothesis` is the standing example, and its record says so. |
| **Refused** | GPL-2.0, GPL-3.0, AGPL-3.0, SSPL, BUSL, any source-available or "fair use" licence | Either obliges more than a personal project should take on, or is not open source at all. |
| **`UNKNOWN`** | Anything unstated, unreadable, or contradicted by its own metadata | **Not safe by default.** Refused until a human reads the project's own text and records it. An unknown licence is an unanswered question, not a permissive one. |

`0BSD`, `Zlib` and `CC0-1.0` joined the allow list in **Phase 021**, and the
reason is worth recording because it is the first time this table was extended.
The first runtime dependency turned out not to publish a single licence
identifier at all, and a policy that only classifies single identifiers would
have forced a choice between recording something untrue and refusing a library
nobody objects to. Each of the three is permissive and two of them are more
permissive than MIT; none was added speculatively, and none is in the table
because it was convenient.

### Compound expressions

A project may publish an SPDX **expression** rather than one identifier. A
compound joined by `AND` is allowed exactly when **every** component is allowed,
because `AND` means all of them apply at once; the expression is recorded whole
in `dependency-reviews.toml` rather than reduced to its most prominent part.
Reducing it would make the register say something the project does not.

The standing example is `numpy`, which publishes
`BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` — its own code under
BSD-3-Clause and four vendored components under the rest.

Phase 026 added the second, `prometheus-client`, which publishes
`Apache-2.0 AND BSD-2-Clause`. Both components were already permitted, so the
rule needed no widening to accept it — but the expression still had to be written
here, and that is the part worth stating rather than leaving to be rediscovered.
`tests/contract/test_supply_contract.py::test_every_licence_is_permitted_by_the_policy`
looks for the recorded licence **as a literal string in this document**, not for
its components. A compound is therefore permitted by being *named* here, one
expression at a time, and never by an argument that the general rule covers it.
That is deliberate: it makes each compound a decision somebody wrote down.

An expression joined by `OR` is **not** covered here. `OR` is a choice, and
choosing is a decision somebody has to make and record rather than a lookup; the
first one that appears gets its own paragraph in this section.

This is an engineering governance control. It records what a project publishes
about itself so that decisions are reviewable. **Nothing here is a legal
opinion**, and a licence question with real consequences belongs with someone
qualified to answer it.

---

## Vulnerabilities

`python -m tools.quality supply` runs `pip-audit` against a requirements file
generated from the inventory, so the audit, the SBOM and the manifest all
describe one set.

**Every non-finding outcome fails.** A scanner has three possible results and two
of them look alike from a distance: found nothing, could not look, found
something. `tools/quality/supply/audit.py` gives each its own outcome, and only
`clean` passes. A run on a day the advisory service is down reports
`service-unreachable` and exits non-zero. `continue-on-error`, `|| true` and
`exit 0` are prohibited and asserted absent.

**No automatic fixing.** `pip-audit --fix` would choose a version, and choosing a
version is the review above. A tool performing that review while running a check
is the process deleting itself.

**Severity threshold.** Any open finding fails the gate, at any severity.

That paragraph used to end by saying the threshold "will need to become
severity-aware" once Phase 021 introduced runtime dependencies, and this is that
argument. **The threshold stays blunt, and the reason it is affordable has
changed.** It used to be that nothing was shipped; now two runtime distributions
are declared and installed, so that reason is gone and a new one has to hold or
the rule has to.

It holds. A severity threshold is a standing decision to ignore a class of
finding **nobody has looked at yet** — it is written before the advisory exists
and applied without anybody reading it. What this repository already has instead
is `docs/engineering/vulnerability-waivers.toml`: a finding that cannot be fixed
today is waived *by name*, with a reason, an owner and a date, and the waiver is
a diff somebody reviewed. That is strictly better information than "low, so it
passed", and it costs an afternoon per occurrence rather than an afternoon per
release.

The blunt rule becomes wrong when the cost of one waiver per finding exceeds the
value of reading each one — which is a function of how many findings arrive, not
of how severe they are. Phase 022 installs the scientific stack and Phases 045
onwards add the exchange SDKs; if the register starts collecting waivers faster
than they can be read, that is the evidence this decision was wrong, and
**Phase 032** — the environment band's consolidation and gate review — is where
it should be revisited with the numbers rather than with a prediction.

### Waivers

A gate with no way to say "yes, and we accept that" is a gate somebody switches
off. A gate whose exceptions never expire becomes a list nobody has looked at.
[`engineering/vulnerability-waivers.toml`](engineering/vulnerability-waivers.toml)
is the middle.

Each waiver carries ten fields: the advisory, the package, the ecosystem, the
exact affected range, the reason, an owner, the date created, the date it
expires, the compensating control, and a reference. All ten are required.
`compensating_control` is the one people most want to omit and the one most worth
demanding — a waiver with no answer to "so what stops this hurting us" is not a
decision, it is a shrug.

Three rules the code enforces:

- **`affected = "*"` is refused.** It would waive the package's entire future,
  including the advisory nobody has published yet.
- **An expired waiver fails the gate.** Expiry is measured against the **commit's
  own date**, not the wall clock, so the same commit gets the same verdict on any
  machine on any day. The expiry date itself is still covered; the day after is
  not.
- **A waiver hides nothing.** It changes a finding's disposition from `open` to
  `waived`. The finding stays in the report and in the manifest, because the
  point is to be able to read later what was accepted and by whom.

---

## Secrets

Two scanners, deliberately, and neither replaces the other.

`tests/contract/test_repository_contract.py` matches **filenames** — `.env`,
`*.pem`, `secrets.toml`. It says why it does not look inside files: "a regular
expression hunting for secrets inside files would miss anything unusual".

`tools/quality/supply/secrets.py` matches **content** — key headers and the
documented token prefixes of specific providers. It covers the shape most real
leaks have, which is a credential inside a file with an ordinary name.

**Findings are reported as fingerprints, never as values.** A scanner that prints
what it found has published it a second time, into a log, an artifact and a step
summary, all of which outlive the file. Each finding carries a truncated SHA-256
and the line it was on.

**No entropy heuristics.** This repository is full of forty-character commits and
SHA-256 digests. A scanner flagging those would be turned off within a week.

**Allowlist entries are per file *and* per pattern**, each with a stated reason.
Exempting a whole file would blind the scanner to every other pattern in it. A
global exemption is prohibited.

### If a credential is ever committed

**Revoke it at the provider before anything else** — before cleaning history,
before reporting, before reading further. A secret in a public repository should
be assumed captured within minutes, and a revoked credential is harmless whatever
the history says.

The remaining steps, and the reasoning for their order, are the credential lane
of [`security/VULNERABILITY_RESPONSE.md`](security/VULNERABILITY_RESPONSE.md).
They were written here first, when there was no runbook to put them in; they now
live with the rest of the response procedure so that one incident is worked from
one document. This section keeps only the first step, because it is the one
somebody needs before they have found the runbook.

Where a key is permitted to live once there is one is
[`security/SECURITY_BASELINE.md`](security/SECURITY_BASELINE.md), which Phase 015
wrote and Phase 028 implements. This document owns the *scanners*; that one owns
the *rules*.

---

## What the platform does, and what it will not

Some controls are GitHub's, not this repository's. They live in a control plane
no commit can reach, and their availability depends on a plan and a visibility
setting.

`tools/quality/supply/capability.py` records each as a state, with the HTTP
status that established it:

| State | Meaning |
|---|---|
| `PASS` | Checked, and enabled. |
| `FAIL` | Checked, available, not enabled. The only state that is somebody's fault. |
| `UNAVAILABLE_BY_PLAN` | This account or visibility cannot have it. |
| `UNAVAILABLE_BY_PERMISSION` | The credential used may not ask. The remedy is a scope, not a subscription. |
| `NOT_APPLICABLE` | The question does not arise here. |
| `NOT_PROBED` | Nothing asked. |
| `ERROR` | The probe itself failed. |

**`UNAVAILABLE` is never `PASS`.** An overall `PASS` while a control is
unavailable is permitted only when that control is *optional* — marked `recorded`
rather than `required` in `capability.py` — and the local compensating control
passed. The pairing is deliberate: content secret scanning compensates for
GitHub secret scanning, `pip-audit` compensates for Dependabot alerts, and the
pin gate compensates for dependency review. Where there is no local
compensation, the control is `required`.

This repository was **private on a personal Free plan** until Phase 014, and
every one of CodeQL, secret scanning, push protection, dependency review,
artifact attestations and rulesets returned a plan refusal. It is now public,
and all of them are available. The evidence for both states is in
[`research/phase_014_sources.md`](research/phase_014_sources.md), because "we
turned it on" is a claim and "here is the 403 that said we could not, and the 200
that says we now can" is evidence.

### Which control lives where

| Control | Configured by | Changed how |
|---|---|---|
| Dependabot **version** updates | `.github/dependabot.yml` | A commit |
| Dependabot **security** updates | Repository setting | The API or the settings page — **no file here can change it** |
| Secret scanning, push protection | Repository setting | Likewise |
| CodeQL | `.github/workflows/codeql.yml` | A commit — advanced setup was chosen over default setup for exactly this reason |
| Rulesets, branch protection | Repository setting | Likewise |
| Action pinning | `.github/workflows/*.yml` + `action-pins.toml` | A commit |

---

## Branch protection, and why the required check is not required

`master` carries a ruleset blocking force-pushes and deletion, with no bypass
actors. It does **not** require a pull request and does **not** require a status
check.

That is not an oversight, and it is not timidity. A required status check is
evaluated on push, and the check can only run *after* the push — so requiring
`Quality gate` on a branch that is written to directly would reject the very
commit that would produce the passing check. GLOBIN's development contract is
master-only ([ADR-0005](adr/0005-master-only-git-workflow.md)), so the two are
incompatible until the workflow changes.

`Quality gate` remains the one check to require, and it is named in
`[tool.globin.workflow] required_check` so that a rule created later names
something stable. What is missing is not knowledge; it is a pull-request-based
workflow, which is a decision for a later phase.

---

## Resolution and locking, delivered in Phase 020

This document owns whether a dependency may be adopted.
[`engineering/DEPENDENCY_LOCKING.md`](engineering/DEPENDENCY_LOCKING.md) owns what
happens to one that has been: how the version that will actually be installed is
fixed, and how anybody checks that the fixing worked.

The division holds inside the tooling too. The inventory still reads what is
*declared* — it runs no resolver and claims no transitive tree, and its own
docstring says so. The lock is *resolved*, which is why it is not a fourth entry
in `inventory.drift()`; the comparison between them lives in the lock gate, which
imports the inventory rather than the other way round.

One thing this changes here rather than there. The vulnerability audit used to run
against a requirements file synthesised from the inventory's exact pins, which
`pip-audit` then resolved against a live index **at audit time** — so the report
described a resolution nobody had installed, and two runs on one commit could
disagree. It now runs `--locked`, which resolves nothing. The audited set is the
locked set, which is the set `scripts/bootstrap.ps1` installs.

---

## Related

- [`engineering/dependency-reviews.toml`](engineering/dependency-reviews.toml) — the verdict on every declared dependency
- [`engineering/vulnerability-waivers.toml`](engineering/vulnerability-waivers.toml) — what has been accepted, and until when
- [`engineering/action-pins.toml`](engineering/action-pins.toml) — what each pinned commit was verified to be
- [`engineering/CI_SECURITY.md`](engineering/CI_SECURITY.md) — the CI trust model and the pin procedure
- [`engineering/QUALITY_GATES.md`](engineering/QUALITY_GATES.md) — which checks are mandatory
- [ADR-0044](adr/0044-dependency-review-is-a-written-process-with-a-generated-inventory.md) — the review process and the generated inventory
- [ADR-0045](adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — capability states
- [ADR-0046](adr/0046-the-repository-is-public-and-that-changes-the-threat-model.md) — what going public changed
