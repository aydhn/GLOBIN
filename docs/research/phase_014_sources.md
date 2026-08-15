# Phase 014 — Source Ledger

Dependency Review and Licence Audit Process; supply-chain security.

Every claim Phase 014 makes about an external system is recorded here, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md). Where a source was *probed* rather
than read, the request and the response are written out: "the feature was
unavailable" is a claim, and a quoted `403` is evidence.

---

### S-01 — CycloneDX 1.7 exists, and is the current specification

- **Canonical location:** OWASP CycloneDX — `https://cyclonedx.org/specification/overview/`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the specification's own publisher.
- **Supports:** Current version **1.7**, released **2025-10-21**, and published
  as an international standard, **ECMA-424**, on 2025-12-10.
- **Implication for GLOBIN:** The brief asked for CycloneDX 1.7 and 1.7 is real,
  so `tools/quality/supply/sbom.py` targets it. Had it not existed the target
  would have been 1.6 and the discrepancy recorded here rather than silently
  substituted.

### S-02 — The required fields of a CycloneDX 1.7 JSON BOM

- **Canonical location:** OWASP CycloneDX JSON reference — `https://cyclonedx.org/docs/1.7/json/`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the specification's own documentation.
- **Supports:** `bomFormat` is required and must be `CycloneDX`; `specVersion`
  is required and must be `1.7`. `serialNumber` is recommended and must be an
  RFC 4122 UUID in `urn:uuid:` form. A component requires `type` and `name`.
  `metadata` may carry `timestamp` (ISO 8601), `tools` and `component`. The
  schema is published at `https://cyclonedx.org/schema/bom-1.7.schema.json`.
- **Implication for GLOBIN:** Those fields are emitted, and the schema URL is
  recorded in the document's `$schema` — but **not fetched at generation time**,
  because this repository's tooling makes no network call outside the audit job.
  Validation against the published schema is **not** performed: it would need
  `jsonschema` (a dependency) or a vendored copy (a file nobody rechecks).
  `sbom.validate` instead asserts what a hand-written generator can plausibly get
  wrong — the required fields, component uniqueness, referential integrity and
  canonical ordering. Recorded as a limit in ADR-0044 rather than left to be
  discovered.

### S-03 — Artifact attestations need Enterprise Cloud on a private repository

- **Canonical location:** GitHub Docs — `https://docs.github.com/en/actions/concepts/security/artifact-attestations`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the platform's own documentation.
- **Supports:** On GitHub Free, Pro or Team, artifact attestations are available
  **only for public repositories**. Private or internal repositories require
  GitHub Enterprise Cloud.
- **Implication for GLOBIN:** This is the one control that no upgrade short of
  Enterprise Cloud would have unlocked, which is part of why visibility rather
  than a subscription was the answer (ADR-0046).

### S-04 — Secret scanning and push protection need paid security on a private repository

- **Canonical location:** GitHub Docs — `https://docs.github.com/en/code-security/concepts/secret-security/push-protection`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** Free for public repositories. On private repositories both
  require GitHub Secret Protection, available on Team or Enterprise Cloud. A
  personal Free account cannot enable either on a private repository.
- **Implication for GLOBIN:** Consistent with the `404` observed in S-07, and one
  of the six controls that became available on going public.

### S-05 — Dependency review needs paid security on a private repository

- **Canonical location:** GitHub Docs — `https://docs.github.com/en/code-security/supply-chain-security/understanding-your-software-supply-chain/about-dependency-review`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** Quoted — "The action is available for all public repositories, as
  well as private repositories that have GitHub Code Security or GitHub Advanced
  Security enabled."
- **Implication for GLOBIN:** Unavailable while private; available now. The local
  compensating control is the pin gate in `tools/quality/supply/workflows.py`.

### S-06 — Dependabot's ecosystem identifiers, and what `pre-commit` does not support

- **Canonical location:** GitHub Docs — `https://docs.github.com/en/code-security/dependabot/ecosystems-supported-by-dependabot/supported-ecosystems-and-repositories`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** `pip` is the single identifier covering pip, pipenv, pip-compile
  and poetry — there is no separate identifier per Python tool. `github-actions`
  and `pre-commit` are identifiers in their own right. **`pre-commit` supports
  version updates but not security updates.** Corroborated by observation: the
  dependency graph had already been parsing this repository as `pip` before
  anything was configured, in run `Graph Update: pip in /. #1526126659` against
  commit `c5cf451`.
- **Implication for GLOBIN:** `.github/dependabot.yml` declares exactly those
  three, none invented, and records the missing security updates for `pre-commit`
  so the absence is not later read as a misconfiguration.

### S-07 — Capability probe while the repository was private

- **Canonical location:** GitHub REST API — `https://docs.github.com/en/rest`, queried against `repos/aydhn/GLOBIN`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the platform answering about itself. Requests made as
  `aydhn` (`admin: true`; token scopes `gist, read:org, repo, workflow`).
- **Supports:**

  | Endpoint | Response |
  |---|---|
  | `GET .../rulesets` | `403` — *"Upgrade to GitHub Pro or make this repository public to enable this feature."* |
  | `GET .../branches/master/protection` | `403` — same message |
  | `GET .../code-scanning/alerts` | `403` — *"Code scanning is not enabled for this repository."* |
  | `GET .../code-scanning/analyses` | `403` — *"This API operation needs the `admin:repo_hook` scope."* |
  | `GET .../secret-scanning/alerts` | `404` — *"Secret scanning is disabled on this repository."* |
  | `GET .../vulnerability-alerts` | `204` — Dependabot alerts already enabled |
  | `GET .../dependabot/alerts` | `200 []` |
  | `GET .../automated-security-fixes` | `200 {"enabled":false,"paused":false}` |
  | `GET .../dependency-graph/sbom` | `200`, an SPDX-2.3 document |
  | `GET .../` → `.security_and_analysis` | `null` |

- **Implication for GLOBIN:** Two `403`s with opposite remedies — one names a
  plan, the other names a scope — is the whole argument for ADR-0045's separation
  of `UNAVAILABLE_BY_PLAN` from `UNAVAILABLE_BY_PERMISSION`. The marker strings
  in `capability.py` are taken from these responses rather than guessed.

### S-08 — Full-history scan taken before the visibility change

- **Canonical location:** This repository's own history — `https://github.com/aydhn/GLOBIN`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the artefact being published.
- **Supports:** Publishing exposes all 32 commits, not the working tree, so the
  scan covered history rather than `HEAD`.

  | Check | Method | Result |
  |---|---|---|
  | Credential-shaped filenames | `git rev-list --objects --all`, 269 unique paths, against `CREDENTIAL_FILENAMES` | **0** |
  | Key headers and provider token prefixes | `git log -p --all`, 2,864,781 bytes | **0** |
  | Binance-key-shaped strings | 64-character mixed-case alphanumerics, excluding pure hex so digests do not mask a key | **0** |
  | Authorship | `git log --all --format` | one identity, `108704389+aydhn@users.noreply.github.com`, already public |
  | Absolute paths and real names | grep over full history | 7 matches, **all deliberate test fixtures** using the placeholder `C:\Users\Some One\` |
  | Evidence artefacts | `.gitignore:76` | `.globin/` ignored and untracked |

- **Implication for GLOBIN:** The scan is what made the change safe to make once,
  and it cannot be undone if something had been missed. Recorded here so the
  basis for the decision is auditable rather than asserted.

### S-09 — Capability probe after the repository became public

- **Canonical location:** GitHub REST API — `https://docs.github.com/en/rest`, queried against `repos/aydhn/GLOBIN`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:**

  | Endpoint | Before | After |
  |---|---|---|
  | `rulesets` | `403` plan | `200 []` |
  | `branches/master/protection` | `403` plan | `404 "Branch not protected"` — available, unset |
  | `code-scanning/analyses` | `403` | `404 "no analysis found"` — available, nothing analysed yet |
  | `secret-scanning/alerts` | `404` disabled | available |
  | `.security_and_analysis` | `null` | the full toggle set, all `disabled` |

  Enabled afterwards, each read back to confirm: `secret_scanning` → `enabled`;
  `secret_scanning_push_protection` → `enabled`; `automated-security-fixes` →
  `enabled`; ruleset `master-baseline`, id `20887017`, `active`, rules
  `deletion` and `non_fast_forward`, `bypass_actors: []`.

  **Refused twice, and recorded rather than retried:** `PATCH /repos/{owner}/{repo}`
  with `security_and_analysis[secret_scanning_non_provider_patterns][status]=enabled`
  returns `200` with the status still `disabled`.

- **Implication for GLOBIN:** `security_and_analysis` changing from `null` to a
  populated object is the cleanest single piece of evidence that a plan ceiling,
  not a permission, was the obstacle. The silently-refused `PATCH` cannot be
  detected by any classification rule, so it is recorded as that control's
  `unavailable_reason` — otherwise the manifest would carry a permanent `FAIL`
  nobody can fix, which trains people to ignore the manifest.

### S-10 — `github/codeql-action@v4.37.7` is an annotated tag, and the two sources disagreed

- **Canonical location:** `github/codeql-action` — `https://github.com/github/codeql-action`
- **Accessed:** 2026-08-15
- **Authority:** Primary — resolved through both the GitHub REST API and the raw
  git protocol, which is what `CI_SECURITY.md` step 3 requires.
- **Supports:** The two sources returned **different** SHAs:
  `git ls-remote --tags --refs` gave `faaa5d804fc648d0fdb28822a8e36cf7d0a6132c`;
  `gh api .../tags` gave `ff2f1c621b7f889edc0d3c761ac2e6a3f8cdb0dd`.
  Dereferencing resolved it two ways: `refs/tags/v4.37.7^{}` is `ff2f1c62…`, and
  `GET /git/ref/tags/v4.37.7` reports `{"type":"tag"}` whose
  `GET /git/tags/faaa5d80…` yields `{"object":{"sha":"ff2f1c62…","type":"commit"}}`.
  `faaa5d80…` is the tag object; `ff2f1c62…` is the commit.
- **Implication for GLOBIN:** The **commit** is pinned in
  `.github/workflows/codeql.yml` and recorded in
  [`action-pins.toml`](../engineering/action-pins.toml). This is the first real
  use of the two-source procedure, and the first time it caught something.

### S-11 — CodeQL default setup was not configured

- **Canonical location:** GitHub REST API — `https://docs.github.com/en/rest/code-scanning`, `GET repos/aydhn/GLOBIN/code-scanning/default-setup`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** `{"state":"not-configured","languages":["actions","python"],"query_suite":"default",…}`
- **Implication for GLOBIN:** Checked **before** writing the advanced-setup
  workflow, because the two are mutually exclusive and running both produces two
  sets of alerts for one codebase. Nothing was overridden. GitHub's own detection
  reports `actions` and `python`, which is where the workflow's matrix comes from
  rather than from a guess — and `actions` is the pack most relevant to a
  repository whose only remote code execution is its own CI.

### S-12 — `pip-audit`, its licence and its measured cost

- **Canonical location:** PyPA — `https://github.com/pypa/pip-audit`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the project's own repository and `LICENSE`.
- **Supports:** Apache-2.0. Adopted at **2.9.0**. Measured: the six previously
  declared tools plus `pip-audit` resolve to **26 distributions**. Run against
  that set, `pip-audit --strict` reported 0 vulnerabilities and exit 0.
- **Implication for GLOBIN:** Adopted through the process this phase defines, with
  the review recorded in
  [`dependency-reviews.toml`](../engineering/dependency-reviews.toml). A design
  error was found by running it: audited against the *ambient environment*,
  `--strict` failed on `binokx (0.1.0)`, a local package on the developer's
  machine unrelated to GLOBIN — so "audit what is installed" measures the machine,
  not the repository. Changed to audit a requirements file generated from the
  inventory (ADR-0044).

---

## Deferred, with the reason

**Dependency resolution and locking** — Phase 020. The inventory reads what is
declared and says so; nothing here writes a lockfile.

**Severity-aware vulnerability thresholds** — any open finding currently fails, at
any severity. Affordable while the toolchain is seven development-only packages;
it will need revisiting when Phase 021 introduces runtime dependencies.

**Required status checks on `master`** — incompatible with ADR-0005's master-only
workflow, because a required check is evaluated on push and can only run after
one. Reasoning in [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md).

**Secret storage** — Phase 015 designs it, Phase 028 implements it. Phase 014
delivers detection and the response procedure, which are needed before there is
anything to store.

**The `supply` job's timeout** — 15 minutes with no measured run behind it,
because this is the job's first commit. It is the only budget in
`[tool.globin.workflow.timeouts]` not derived from observation, and should be
revisited against a real duration.
