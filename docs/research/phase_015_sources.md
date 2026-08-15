# Phase 015 — Source Ledger

Security Baseline and Secret Handling Rules; repository governance.

Every claim Phase 015 makes about an external system is recorded here, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md). Where a source was *probed* rather
than read, the request and the response are written out: "the feature was
enabled" is a claim, and a quoted `204` is evidence.

Phase 014's ledger established the pattern of recording a probe's exact response
because the response text carried a distinction the status code did not. The same
applies here, once, in S-05: the repository's private vulnerability reporting was
observably off before this phase and observably on after it, and both readings are
below.

---

### S-01 — A CODEOWNERS file has exactly three permitted locations, and only one is used

- **Canonical location:** GitHub Docs — About code owners —
  `https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the platform documenting its own behaviour.
- **Supports:** A CODEOWNERS file may be placed in "the `.github/`, root, or
  `docs/` directory of the repository". Where more than one exists, "GitHub will
  search for them in that order and use the first one it finds" — `.github/`
  first, then root, then `docs/`.
- **Implication for GLOBIN:** This is the whole argument for treating a second
  CODEOWNERS file as a **failure** rather than as a duplicate to tidy later.
  GitHub does not merge them, so an extra copy silently overrides, and the file
  being ignored may be the one somebody is maintaining. The three locations are
  declared as `codeowners_candidates` in
  [`../engineering/governance.toml`](../engineering/governance.toml) and all three
  are checked, rather than only the one in use.

### S-02 — CODEOWNERS follows gitignore syntax with three named exceptions

- **Canonical location:** GitHub Docs — About code owners —
  `https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** CODEOWNERS patterns follow gitignore rules, with these
  exceptions: escaping a leading `#` with `\` "doesn't work", negation with `!`
  is unsupported, and "Using `[ ]` to define a character range doesn't work".
- **Implication for GLOBIN:** `tools/quality/governance/plan.py` implements a
  deliberate subset and refuses the rest by name rather than guessing at it. The
  three forms it rejects — `!`, `[`/`]`, and a `**` in the middle of a pattern —
  are the two GitHub documents as unsupported plus the one this module chose not
  to implement. A pattern outside the subset is reported as a finding, because
  assuming it matches nothing would understate coverage and assuming the reverse
  would overstate it.

### S-03 — An unresolvable owner is ignored silently

- **Canonical location:** GitHub Docs — About code owners —
  `https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** "If you specify a user or team that doesn't exist or has
  insufficient access, a code owner will not be assigned."
- **Implication for GLOBIN:** No owner is invented. `aydhn` owns this repository
  as a **personal account**, so `@org/team` syntax cannot resolve here; writing
  one would produce a file that looks institutional, assigns nobody, and reports
  no error. `tests/contract/test_governance_contract.py` asserts the owner set is
  exactly `{@aydhn}` and that no owner contains a `/`.

### S-04 — Private vulnerability reporting is a public-repository feature, enabled by the owner

- **Canonical location:** GitHub Docs — Configuring private vulnerability
  reporting for a repository —
  `https://docs.github.com/en/code-security/security-advisories/working-with-repository-security-advisories/configuring-private-vulnerability-reporting-for-a-repository`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** "Owners and administrators of public repositories can allow
  security researchers to report vulnerabilities securely" by enabling the
  feature in the repository's settings. The article states no plan requirement
  and does not name GitHub Advanced Security as a prerequisite.
- **Implication for GLOBIN:** The channel `SECURITY.md` names is available to
  this repository because Phase 014 made it public
  ([ADR-0046](../adr/0046-the-repository-is-public-and-that-changes-the-threat-model.md)).
  Had it remained private, the honest `SECURITY.md` would have had to say there
  was no secure channel — the alternative, inventing an address, is the
  anti-pattern this phase's brief names explicitly.

### S-05 — The capability probe, before and after enabling it

- **Canonical location:** GitHub REST API — `https://docs.github.com/en/rest`,
  queried against `repos/aydhn/GLOBIN`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the platform answering about itself. Requests made as
  `aydhn` (token scopes `gist, read:org, repo, workflow`).
- **Supports:**

  | Request | Response |
  |---|---|
  | `GET .../private-vulnerability-reporting` (before) | `200 {"enabled":false}` |
  | `PUT .../private-vulnerability-reporting` | `204 No Content` |
  | `GET .../private-vulnerability-reporting` (after) | `200 {"enabled":true}` |
  | `GET .../security-advisories` | `200 []` |
  | `GET .../rulesets` | `200`, one ruleset: `master-baseline`, id `20887017`, `active` |
  | `GET .../rulesets/20887017` | rules `deletion` and `non_fast_forward`; `bypass_actors: []`; `current_user_can_bypass: "never"` |
  | `GET .../branches/master/protection` | `404 "Branch not protected"` |
  | `GET .../codeowners/errors` | `404` — there was no CODEOWNERS file to have errors in |
  | `GET .../` → `.security_and_analysis` | secret scanning `enabled`, push protection `enabled`, Dependabot security updates `enabled`, non-provider patterns `disabled` |

- **Implication for GLOBIN:** Two of these are load-bearing. The
  `{"enabled":false}` reading is why the control was added as `REQUIRED` rather
  than `RECORDED`: it was observably off, on a public repository whose only
  reporting route was a public issue. The `404` from `codeowners/errors` is the
  cleanest possible confirmation that no CODEOWNERS file existed anywhere, since
  that endpoint reports problems *within* one. The ruleset detail confirms that
  neither a pull-request rule nor a required status check is configured, which is
  the state ADR-0046 recorded and this phase deliberately does not change.

### S-06 — The advisories page renders the report button, which is independent evidence the feature is live

- **Canonical location:** `https://github.com/aydhn/GLOBIN/security/advisories`
  and `https://github.com/aydhn/GLOBIN/security/advisories/new`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the running service, observed unauthenticated.
- **Supports:** The advisories page renders with the heading "Security
  Advisories", the message "There aren't any published security advisories", and
  a **"Report a vulnerability"** button. The `/new` path is a real page that
  returns GitHub's sign-in prompt to an unauthenticated visitor rather than a
  `404`.
- **Implication for GLOBIN:** The button is shown only where private
  vulnerability reporting is enabled, so its presence corroborates S-05 through a
  different code path from the REST API. The link in `SECURITY.md` and
  `.github/ISSUE_TEMPLATE/config.yml` was verified to resolve rather than
  assumed: the reporter-facing documentation describes the UI flow — Security tab,
  then "Report a vulnerability" — and does **not** document the `/new` URL, so it
  is recorded here as observed rather than cited as documented.

### S-07 — The reporter's flow, and what the maintainer may do inside it

- **Canonical location:** GitHub Docs — Privately reporting a security
  vulnerability —
  `https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** A researcher reports through the repository's Security tab and
  the "Report a vulnerability" button, completing an advisory form requiring at
  least a title and description. "You can only report vulnerabilities privately
  for repositories where this feature is enabled." GitHub "automatically adds the
  reporter of the vulnerability as a collaborator and as a credited user on the
  proposed advisory", and a temporary private fork may be started from the
  advisory to work on a fix.
- **Implication for GLOBIN:** Two parts of
  [`../security/VULNERABILITY_RESPONSE.md`](../security/VULNERABILITY_RESPONSE.md)
  rest on this. The private fork is named as the mechanism for the case where the
  fix's diff would itself disclose the finding, rather than being described
  vaguely. And crediting is a real platform behaviour rather than a courtesy the
  runbook invented, which is why the runbook can promise credit and can also
  promise to withhold it where a reporter asks.

### S-08 — The issue chooser's configuration file and its keys

- **Canonical location:** GitHub Docs — Configuring issue templates for your
  repository —
  `https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/configuring-issue-templates-for-your-repository`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** The chooser is configured by `.github/ISSUE_TEMPLATE/config.yml`,
  with the top-level keys `blank_issues_enabled` and `contact_links`, the latter
  taking entries with `name`, `url` and `about`.
- **Implication for GLOBIN:** The file did not exist before this phase, which is
  why the security policy had no route to it from the issue interface at all.
  `blank_issues_enabled: false` is the load-bearing line: with blank issues on,
  the chooser can be bypassed and the contact link is never shown, so the setting
  is what guarantees a reporter passes the security link on the way to opening an
  issue. A contact link navigates away rather than collecting a form, which is
  the distinction that keeps vulnerability detail out of a public issue.

### S-09 — What was checked and could not be established

- **Canonical location:** GitHub Docs — About code owners —
  `https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners`
- **Accessed:** 2026-08-15
- **Authority:** Primary, and its silence is the finding.
- **Supports:** The code-owners article does **not** state whether code-owner
  review requires a paid plan on a public repository, and does **not** state
  whether a user may approve their own pull request.
- **Implication for GLOBIN:** Neither question needed an answer, and recording
  that is better than researching it. Code-owner review is
  `NOT_APPLICABLE` here for a reason that holds regardless: GLOBIN develops on
  `master` with no pull request at all
  ([ADR-0005](../adr/0005-master-only-git-workflow.md)), so a rule governing
  pull-request review governs an event that does not occur. Had the plan question
  been the reason, it would have been an `UNAVAILABLE_BY_PLAN` and a different
  record.

---

## Deferred, with the reason

**Required status checks on `master`** — unchanged from Phase 014, and unchanged
deliberately. A required check is evaluated on push and can only run after one,
so requiring `Quality gate` on a directly-written branch would reject the very
commit that would produce the passing check. Reasoning in
[`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md); the state is recorded as
`NOT_APPLICABLE` in the governance manifest rather than omitted.

**Code-owner review enforcement** — the same shape of answer, different argument.
Adding the ruleset rule would require the sole maintainer to approve their own
pull request, which GitHub does not permit, so the repository would be unable to
accept any change. What would change the answer is a second maintainer, and
[`../security/GOVERNANCE.md`](../security/GOVERNANCE.md) is the record of what is
waiting on that.

**A CVSS calculator** — [`../security/VULNERABILITY_RESPONSE.md`](../security/VULNERABILITY_RESPONSE.md)
defines this repository's own five severity bands and explicitly is not CVSS.
Computing a score here from impression would look like arithmetic while being
opinion; a published score is cited with its vector and the standard's version,
or not at all.

**The secret store itself** — Phase 028 implements it and Phase 029 defines
credential collection. Phase 015 specifies the properties both are bound by,
which is what the roadmap separates the phases to do.

**Whether Binance offers a given API key permission** — the least-privilege rules
in [`../security/SECURITY_BASELINE.md`](../security/SECURITY_BASELINE.md) are
constraints on a later decision, not claims about the venue. What Binance
actually offers is established when the phase arrives, under
[ADR-0006](../adr/0006-product-and-environment-capability-matrix.md).
