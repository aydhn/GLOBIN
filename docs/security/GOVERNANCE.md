# Repository Governance

Who owns which change, which paths are security-sensitive, and what the platform will and will not
enforce.

This document owns the **ownership and change-control model**. Reporting a vulnerability is
[`../../SECURITY.md`](../../SECURITY.md), responding to one is
[`VULNERABILITY_RESPONSE.md`](VULNERABILITY_RESPONSE.md), and the rules about credentials are
[`SECURITY_BASELINE.md`](SECURITY_BASELINE.md). None of the four restates another.

Everything here is asserted by `tests/contract/test_governance_contract.py` and by
`python -m tools.quality governance`. Where this document and those disagree, they are right and
the disagreement is a defect — [`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md).

---

## The chain this completes

Phase 014 built the detection: a content secret scanner, a generated SBOM, a vulnerability audit,
CodeQL, secret scanning with push protection, and a `master` ruleset. What it did not build was the
human layer around them — who is answerable for a change, how a security-relevant change is
recognised as one, and where a report goes.

The full chain, and where each link is written down:

| Link | Where |
|---|---|
| A change is proposed | `.github/pull_request_template.md` |
| Its owner is identified | `.github/CODEOWNERS` |
| Its security impact is declared | the pull request template's security section |
| Automated gates judge it | [`../engineering/QUALITY_GATES.md`](../engineering/QUALITY_GATES.md) |
| It lands on `master` | [`../GIT_WORKFLOW.md`](../GIT_WORKFLOW.md) |
| A vulnerability is reported | [`../../SECURITY.md`](../../SECURITY.md) |
| It is triaged, fixed and disclosed | [`VULNERABILITY_RESPONSE.md`](VULNERABILITY_RESPONSE.md) |
| The whole arrangement is verified | `python -m tools.quality governance` |

---

## Code ownership

**`.github/CODEOWNERS` is the only code-owners file**, and a second copy anywhere GitHub reads one
— the repository root, or `docs/` — is a governance failure rather than a duplicate. GitHub uses
the first file it finds rather than merging them, so a second copy silently overrides the first.

**There is one owner, `@aydhn`, and it is a personal account rather than an organisation.** That
constrains what can be written: `@org/team` syntax cannot resolve here, and an owner GitHub cannot
resolve is ignored without an error. No team is invented to make the file look more institutional
than the project is.

**Every pattern in the file matches something that exists.** A pattern matching nothing reads as
coverage while providing none, so the governance gate fails on one.

### What ownership does here, and what it does not

**It does** request review from the owner when a pull request touches an owned path. The repository
has been public since Phase 014, so a pull request can arrive from anybody
([ADR-0046](../adr/0046-the-repository-is-public-and-that-changes-the-threat-model.md)), and this is
a real mechanism with a real effect.

**It does not** enforce that the review happens. That would need a ruleset rule requiring
code-owner approval, and here that is `NOT_APPLICABLE` rather than merely switched off:

- GLOBIN develops on `master` with no pull request at all
  ([ADR-0005](../adr/0005-master-only-git-workflow.md)). A rule about pull-request review governs
  an event that does not occur.
- GitHub does not permit anybody to approve their own pull request. A sole maintainer requiring
  their own approval could merge nothing, ever.

**Recording that honestly is the point.** The state is written into the governance manifest with
that reasoning attached, so a reader meets the argument rather than an unexplained gap. It is not
reported as a passing control, and it is not omitted — an absent key and a recorded
`NOT_APPLICABLE` read very differently six months later, and only one of them says anything
([ADR-0045](../adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md)).

**What would change the answer** is a second maintainer. At that point pull-request review becomes
possible, the code-owner rule becomes enforceable, and this section is the record of what was
waiting on it. Until then the compensating control is the one
[`../engineering/QUALITY_GATES.md`](../engineering/QUALITY_GATES.md) names: with no reviewer, the
gates *are* the review, which is why a gate here either fails the build or does not exist.

---

## Security-sensitive paths

A change to a security-sensitive path is one whose defect has a security consequence rather than a
functional one. The inventory lives in
[`../engineering/governance.toml`](../engineering/governance.toml), with a stated reason per entry,
and is compared against the real tree by the governance gate. The categories:

| Category | Why a change here is security-sensitive |
|---|---|
| Workflows | The only place this repository executes code it did not write, and the only holder of a token |
| Action pins and their manifest | A moved tag changes what runs with no diff |
| Dependency declarations and reviews | What is installed, and what was audited |
| Scanner and gate configuration | A gate that cannot fail is decoration |
| CODEOWNERS and the security policy | A change here changes who must look at everything else |
| The quality tooling | It decides whether a commit is acceptable |
| The settings file | It configures every gate above |
| Decision records | They are what makes a control's absence deliberate rather than accidental |

**Paths that do not exist yet are not created to fill the table.** Credential handling, exchange
signing and order execution will all be security-sensitive when the phases that own them arrive.
They are described here as extension points rather than as empty directories, because a directory
created early settles a later phase's design question by accident.

### Recognising one in review

The pull request template asks the questions directly, so that a security-relevant change is
declared rather than noticed: whether Actions permissions changed, whether an action pin or a
dependency moved, whether CODEOWNERS or the security policy changed, whether the secret surface
widened, whether required checks or the SBOM are affected.

**Those questions do not replace a check.** A tick box records what the author believed; the gates
record what is true. Where the two disagree the gate is right, and the template exists to make the
author think before the gate has to.

---

## What the platform enforces, and what it does not

Half of these controls are GitHub features, governed by settings in a control plane no file here
can reach. Each is recorded as a state with the evidence behind it, never as a pass because it
could not be checked. The seven states and the reasoning are
[ADR-0045](../adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md); the probe is
`tools/quality/supply/capability.py`.

| Control | Status | Note |
|---|---|---|
| Private vulnerability reporting | Enabled, and required | Enabled during Phase 015. It is the channel `SECURITY.md` names, so a policy pointing at a switched-off form would route reports into public issues |
| Repository security advisories | Available, recorded | An empty list is the healthy state, so requiring a non-empty answer would demand a vulnerability |
| Secret scanning, push protection | Enabled, and required | Compensating for, not replacing, the local content scanner |
| Dependabot security updates | Enabled, and required | |
| CodeQL | Advanced setup, recorded | Version-controlled rather than configured in a settings page |
| Ruleset on `master` | Active, and required | Blocks deletion and force-push, with no bypass actors |
| Required status check | `NOT_APPLICABLE` | A required check is evaluated on push and can only run after one, so requiring it on a directly-written branch would reject the commit that would produce the passing check |
| Code-owner review | `NOT_APPLICABLE` | See the ownership section above |

**Degraded mode is explicit.** Where the probe cannot run — no network, no `gh`, no credential —
every control is recorded as `NOT_PROBED`, which is never a pass. The offline governance checks
still run, because they read only the working tree, and the gate reports which half was measured.
An offline supply-chain run therefore cannot exit `0`, by construction.

---

## Running the checks

The structural half is offline, reads only the working tree, and runs as part of the ordinary
suite — so it gates every local run and every commit without anybody remembering to invoke it:

```bash
python -m pytest -q tests/contract/test_governance_contract.py
```

The gate itself, which also writes the manifest:

```bash
python -m tools.quality governance
```

It is in neither `fast` nor `full`, for the reason the other standalone gates give: it writes
artefacts, and `full` runs before every commit and reports rather than produces. The assertions
that matter for a commit are in the contract test above, which `full` does run.

The platform half needs the network and a credential, and belongs to the supply-chain gate:

```bash
python -m tools.quality supply
```

In continuous integration both run in the `supply` job, and its artefact carries the governance
manifest alongside the supply manifest.

---

## Drift, and why it is checked separately

Governance decays quietly. Nothing fails when a workflow is added that no owner covers, or when a
scanner's configuration moves and the sensitive-path inventory does not, or when a required check
is renamed and the manifest keeps the old name. Each is invisible until it matters.

So the gate checks the arrangement against the tree rather than against itself:

| Drift | How it is caught |
|---|---|
| A workflow no CODEOWNERS pattern covers | Every file under `.github/workflows/` is matched against the patterns |
| A declared sensitive path that no longer exists | Every entry in `governance.toml` is resolved |
| A CODEOWNERS pattern matching nothing | The same, in the other direction |
| A second CODEOWNERS file | Every location GitHub reads is checked |
| The security policy removed or gutted | Required sections are asserted present |
| An issue template collecting vulnerability detail | Templates are scanned for it |
| The required check renamed | The manifest reads `[tool.globin.workflow] required_check` rather than carrying a copy |
| A manifest disagreeing with the tree | Every path in it is resolved, and it is rebuilt and compared |

---

## Maintenance

**The owner of this arrangement is the repository's owner**, which today is one person. There is no
committee to escalate to and pretending otherwise would be the institutional fiction this document
avoids elsewhere.

What a change must do:

- **Adding a workflow** — add a CODEOWNERS pattern for it, and an entry in `governance.toml` if it
  is security-sensitive. The gate fails until both exist.
- **Adding a scanner or a gate** — declare it in `governance.toml` and register the command in
  `tools/quality/commands.py`, which is the only place a check is defined.
- **Renaming the required check** — change `[tool.globin.workflow] required_check`. Nothing else
  holds a copy.
- **Changing who owns what** — edit `.github/CODEOWNERS` and nothing else. It is the one authority.
- **Changing the reporting channel** — edit `SECURITY.md` and
  `.github/ISSUE_TEMPLATE/config.yml` together, and re-probe the capability.

Band-ending phases reconcile this document against the tree, as
[`../engineering/DOCUMENTATION_STANDARD.md`](../engineering/DOCUMENTATION_STANDARD.md) requires of
every document.

---

## Related

- [`../../SECURITY.md`](../../SECURITY.md) — the reporter-facing policy
- [`VULNERABILITY_RESPONSE.md`](VULNERABILITY_RESPONSE.md) — the response runbook
- [`SECURITY_BASELINE.md`](SECURITY_BASELINE.md) — secret handling and redaction
- [`../engineering/governance.toml`](../engineering/governance.toml) — the declared inventory
- [`../engineering/CI_SECURITY.md`](../engineering/CI_SECURITY.md) — the CI trust model
- [`../engineering/QUALITY_GATES.md`](../engineering/QUALITY_GATES.md) — which checks are mandatory
- [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) — dependency and supply-chain review
- [ADR-0047](../adr/0047-repository-governance-is-declared-once-and-validated-offline.md) — the
  decision behind this model
