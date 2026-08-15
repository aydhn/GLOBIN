# Security Policy

How to report a vulnerability in GLOBIN, and what happens after you do.

This file is the entry point. The procedure behind it — triage, remediation,
verification and disclosure — is
[`docs/security/VULNERABILITY_RESPONSE.md`](docs/security/VULNERABILITY_RESPONSE.md), and the
rules about credentials are
[`docs/security/SECURITY_BASELINE.md`](docs/security/SECURITY_BASELINE.md). Neither is restated
here.

---

## What GLOBIN currently is

Read this before deciding whether you have found a vulnerability, because it changes what is
plausible.

GLOBIN is at **Phase 015 of a fixed 320-phase programme**. It does not trade, holds no
credentials, connects to no exchange, reaches no network at runtime, and has no runtime
dependencies at all. What exists today is tooling, tests, contracts and documentation. See
[`README.md`](README.md) for the current capability surface and [`ROADMAP.md`](ROADMAP.md) for
what is planned.

The consequence is that the realistic attack surface is the **repository and its continuous
integration**, not a running system: the workflows, the actions they execute, the quality tooling,
and anything that could cause a credential to exist where it should not.

## Supported versions

**Support means the tip of `master`, and a release is a marker rather than a supported branch.**

| Version | Supported |
|---|---|
| `master` at its current commit | Yes |
| `v0.1.0` and any earlier release | No — superseded by `master` |
| Anything else | No |

Until Phase 016 this section said GLOBIN "has never been published, tagged, packaged or
distributed" and that "Versioning and release policy belong to a later phase". That was accurate
when written. Phase 016 was that later phase: GLOBIN now has a version contract, a release
policy, and the tag `v0.1.0`. The claim is corrected here rather than left standing.

What has **not** changed is where a fix lands. `pyproject.toml` still carries
`Private :: Do Not Upload`; nothing is published to an index, no packaging build has been run,
and there are no downstream consumers pinned to a version. A fix is therefore delivered by a
commit to `master`, not by patching a past release — and a past release is never modified in
place, because [`docs/release/RELEASE_POLICY.md`](docs/release/RELEASE_POLICY.md) makes a
published release immutable and answers a defect with the next version.

Releases are points in history that evidence refers to. They are not branches anybody
backports to, and listing one as "supported" would promise maintenance that does not exist.

## What counts as a vulnerability here

Report privately:

- A way to execute code, exfiltrate data, or obtain the `GITHUB_TOKEN` through a workflow, an
  action, or content this repository processes.
- A privilege-escalation path through the CI configuration — a trigger that grants more than it
  should, an interpolation that turns attacker-controlled text into script, an unpinned or
  hijackable action.
- A credential, key or token committed to this repository or reachable in its history, or a way
  to cause one to be committed.
- A defect in the quality or supply-chain tooling that would let a gate report a pass it did not
  establish — a check that cannot fail is a security problem, not a cosmetic one.
- A supply-chain issue in a declared dependency that this repository's audit does not catch.
- Anything that would cause a secret to be written to a log, an artifact or a job summary.

Report as an ordinary issue instead:

- Incorrect behaviour with no security consequence — [open a bug
  report](https://github.com/aydhn/GLOBIN/issues/new?template=bug_report.md).
- Documentation that is wrong or out of date, unless the error is itself the vulnerability.
- A missing feature belonging to a later phase. Check [`ROADMAP.md`](ROADMAP.md) first;
  unimplemented is not vulnerable.

## How to report

**Use GitHub's private vulnerability reporting:**

**<https://github.com/aydhn/GLOBIN/security/advisories/new>**

This opens a private advisory visible only to you and the maintainer. It is the preferred channel
because it is the only one that keeps the report confidential until a fix exists, and because it
is where a GHSA identifier and a coordinated disclosure are drafted if the report warrants them.

**Do not open a public issue, pull request, discussion or commit message containing vulnerability
detail, a proof of concept, or a credential.** A public repository is indexed, cloned and forked
continuously; anything published there should be assumed captured immediately and cannot be
withdrawn by deleting it.

**If private reporting is unavailable to you** — the form is not reachable, or you have no GitHub
account — open a public issue containing *only* the sentence "I would like to report a security
issue privately", with **no** technical detail, and wait to be contacted. An empty request to make
contact discloses nothing.

**If a credential is exposed, revoke it before reporting.** Revocation is faster than any process
here and is the only step that reliably ends the exposure. The reasoning is in
[`docs/security/VULNERABILITY_RESPONSE.md`](docs/security/VULNERABILITY_RESPONSE.md).

### What to include

A report that can be reproduced is acted on; one that cannot is guessed at. Please include:

- **What you found**, in one or two sentences.
- **Where** — the file, workflow, job or command, and the commit (`git rev-parse HEAD`) you
  observed it on.
- **How to reproduce it**, from a clean tree, as exact steps or a command.
- **What an attacker gains**, and what they would need first — an account, a pull request, a
  network position, prior access.
- **Any proof of concept**, with real credentials redacted. Never paste a live secret; a
  fingerprint or a truncated value is enough to identify one.
- **How you would like to be credited**, if the report is published, and whether you want to be
  named at all.

## What happens next

The full state machine, with the evidence and exit criteria for each stage, is
[`docs/security/VULNERABILITY_RESPONSE.md`](docs/security/VULNERABILITY_RESPONSE.md). In outline:

1. **Acknowledgement** — the report is confirmed as received, without a verdict.
2. **Triage** — severity is assigned from the deterministic matrix in the runbook, not from
   impression.
3. **Validation** — the report is confirmed or explained, in writing either way. A rejected report
   receives the reasoning, not a closure.
4. **Remediation** — a fix, with a regression test that fails without it.
5. **Verification** — the full gate, plus the supply-chain gate where the finding touches
   dependencies or CI.
6. **Disclosure** — coordinated with the reporter, after the fix is on `master`.

**No timelines are promised.** GLOBIN is maintained by one person as an unfunded personal project,
and a service-level commitment nobody can keep is worse than none: it teaches reporters that the
stated process is decorative. Reports are handled as promptly as circumstances allow, and a report
that has gone quiet is worth a polite follow-up on the same private advisory.

**No bounty is offered.** [ADR-0003](docs/adr/0003-zero-budget-open-source-dependency-policy.md)
makes this a zero-budget project, and that applies to rewards as well as to dependencies. Credit
in the published advisory is offered instead, where the reporter wants it.

## Scope

**In scope:** this repository — its source, tests, tooling, workflows, actions configuration and
documentation — and the GitHub repository settings that govern them.

**Out of scope:** GitHub itself (report to
[GitHub](https://docs.github.com/en/site-policy/security-policies/coordinated-disclosure-of-security-vulnerabilities)),
Binance (GLOBIN does not connect to it and has no account with it), and the maintainer's personal
infrastructure. Findings that require an attacker to already control the maintainer's machine are
out of scope, because at that point this repository is not the weakest link.

**Testing must not damage anything.** Do not attempt denial of service, do not run automated
scanners against GitHub's infrastructure, and do not access data belonging to anyone else. Reading
this repository, running its tooling locally and reasoning about its configuration are all
sufficient to find anything here.

## Related

- [`docs/security/VULNERABILITY_RESPONSE.md`](docs/security/VULNERABILITY_RESPONSE.md) — the
  response runbook and the triage matrix
- [`docs/security/SECURITY_BASELINE.md`](docs/security/SECURITY_BASELINE.md) — secret handling,
  redaction and least-privilege rules
- [`docs/security/GOVERNANCE.md`](docs/security/GOVERNANCE.md) — ownership, sensitive paths and
  change control
- [`docs/engineering/CI_SECURITY.md`](docs/engineering/CI_SECURITY.md) — what CI is trusted with
- [`docs/DEPENDENCY_POLICY.md`](docs/DEPENDENCY_POLICY.md) — dependency and supply-chain review
