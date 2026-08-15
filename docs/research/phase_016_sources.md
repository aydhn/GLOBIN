# Phase 016 — Source Ledger

Foundation Consolidation and Phase Gate Review; versioning, release governance
and release integrity.

Every claim Phase 016 makes about an external system is recorded here, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md). Where a source was *probed* rather
than read, the request and the response are written out, on the pattern Phases
014 and 015 established: "the feature is available" is a claim, and a quoted
response body is evidence.

Several entries below record a **documentation gap** rather than a fact. That is
deliberate. S-08, S-10, S-11 and S-14 each name something this phase needed and
could not find written down where it was looked for, and saying so is what keeps
the difference between "GitHub documents this" and "this repository observed
this" visible to whoever reads the release evidence later. Where a gap was
subsequently closed, the entry says so rather than being quietly rewritten: S-12
found the immutable-releases reference only because a rejected request named it.

---

### S-01 — An annotated tag, a signed tag and a lightweight tag are three different objects

- **Canonical location:** Git — `git-tag` documentation —
  `https://git-scm.com/docs/git-tag`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the tool documenting its own behaviour.
- **Supports:** "Tag objects (created with `-a`, `-s`, or `-u`) are called
  "annotated" tags; they contain a creation date, the tagger name and e-mail, a
  tagging message, and an optional cryptographic signature. Whereas a
  "lightweight" tag is simply a name for an object (usually a commit object)."
  `-a`/`--annotate` is documented as "Make an unsigned, annotated tag object",
  while `-s`/`--sign` is "Make a cryptographically signed tag, using the default
  signing key", whose backend "depends on the `gpg.format` configuration
  variable". `-m` "Implies `-a` if none of `-a`, `-s`, or `-u` _&lt;key-id&gt;_ is
  given."
- **Implication for GLOBIN:** This is the whole basis for the three-word signing
  vocabulary in `tools/quality/release/manifest.py`. The signature is
  **optional** inside an annotated tag object, by Git's own description, so
  "annotated" and "signed" name different guarantees and a release record that
  used them interchangeably would be claiming cryptographic provenance it does
  not have. `v0.1.0` is created with `-a`, which the same page defines as
  explicitly *unsigned*, and the manifest records `ANNOTATED_UNSIGNED` rather
  than the absence of a signing field.

### S-02 — `git verify-tag` validates a signature and says nothing about an unsigned tag

- **Canonical location:** Git — `git-verify-tag` documentation —
  `https://git-scm.com/docs/git-verify-tag`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** The whole description is one sentence: "Validates the gpg
  signature created by `git` `tag` in the tag objects listed on the command
  line." The page documents `--raw` and `-v`/`--verbose` only. It states no exit
  status, and it says nothing about the behaviour when a tag carries no
  signature.
- **Implication for GLOBIN:** The release procedure does not run `git verify-tag`
  against `v0.1.0` and does not describe its absence as a verification step. A
  command whose unsigned-tag behaviour is undocumented cannot be cited as
  evidence of anything, in either direction, and inventing an expected exit code
  for it would be exactly the fabrication
  [`../SOURCE_POLICY.md`](../SOURCE_POLICY.md) forbids. The honest record is that
  no signature exists to verify — see S-14.

### S-03 — `0.1.0` is a PEP 440 final release

- **Canonical location:** Python Packaging Authority — Version specifiers —
  `https://packaging.python.org/en/latest/specifications/version-specifiers/`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the specification itself.
- **Supports:** The public version scheme is `[N!]N(.N)*[{a|b|rc}N][.postN][.devN]`.
  "A version identifier that consists solely of a release segment and optionally
  an epoch identifier is termed a "final release"." The release segment "consists
  of one or more non-negative integer values, separated by dots", and the common
  variants are "two components ("major.minor") or three components
  ("major.minor.micro")". Normalisation: "All integers are interpreted via the
  `int()` built in and normalize to the string form of the output."
- **Implication for GLOBIN:** `0.1.0` is a final release under the scheme, so the
  version already carried at `src/globin/__init__.py` needed no change to be
  taggable. `RELEASE_VERSION_RE` in `tools/quality/release/plan.py` is
  deliberately *narrower* than PEP 440 — three dotted integers and nothing else —
  because a GLOBIN release tag names a final release and admitting epochs,
  pre-releases or local versions would admit shapes the release procedure has no
  answer for. The spec gives no worked normalisation example for `0.1.0`
  specifically; that it normalises to itself follows from the integer rule rather
  than from a quotable line, and is not asserted as a quotation anywhere.

### S-04 — Major version zero carries no stability obligation

- **Canonical location:** Semantic Versioning 2.0.0 —
  `https://semver.org/spec/v2.0.0.html`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** Clause 4: "Major version zero (0.y.z) is for initial development.
  Anything MAY change at any time. The public API SHOULD NOT be considered
  stable." Clause 5: "Version 1.0.0 defines the public API."
- **Implication for GLOBIN:** The foundation baseline is `0.1.0` rather than
  `1.0.0` because there is no public API to define — `pyproject.toml` carries
  `Development Status :: 1 - Planning` and the package exposes project rules
  rather than a trading interface. Note the normative keywords: MAY and SHOULD
  NOT, not MUST. [`../release/RELEASE_POLICY.md`](../release/RELEASE_POLICY.md)
  therefore states the 0.x rule as this project's own commitment, not as
  something the specification compels.

### S-05 — A version may be single-sourced from the package, and consistency should be tested

- **Canonical location:** Python Packaging Authority — Single-sourcing the
  Project Version —
  `https://packaging.python.org/en/latest/discussions/single-source-version/`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** Three documented options: extract from the version control
  system; hard-code into `pyproject.toml`; or hard-code "into the source code —
  either in a special purpose file … or as an attribute in a particular module,
  such as `__init__.py`". On consistency, the page recommends an automated test
  that `import_name.__version__` and `importlib.metadata.version("dist-name")`
  report the same value, and directs the reader to "Consult your build system's
  documentation for their recommended method".
- **Implication for GLOBIN:** The third option is the one this repository already
  chose at Phase 001 — `__version__` in `src/globin/__init__.py`, read by
  Hatchling through `[tool.hatch.version] path`. Phase 016 keeps it rather than
  replacing it. The recommended consistency test is deliberately **not** written
  in the form the page describes: `importlib.metadata.version("globin")` requires
  an installed distribution, and this repository runs its suite against the
  source tree with `pythonpath = ["src"]` and no install step. The equivalent
  check is `tests/contract/test_packaging_contract.py`, which asserts that
  `[tool.hatch.version] path` names the file that defines `__version__` — binding
  the two sources without requiring a build that
  [`../../MEMORY.md`](../../MEMORY.md) records as deferred to Phases 017-032. The
  page contains no code blocks at all, so no `pyproject.toml` snippet is
  attributed to it.

### S-06 — `.github/release.yml` has a documented schema, and `*` is its catch-all

- **Canonical location:** GitHub Docs — Automatically generated release notes —
  `https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the platform documenting its own behaviour.
- **Supports:** The file lives at `.github/release.yml`. The top-level key is
  `changelog`; under it `exclude` (with `labels` and `authors`) and `categories`,
  a list whose items carry `title`, `labels`, and an optional nested `exclude`.
  `categories[].labels` is documented as "Labels that qualify a pull request for
  this category. Use `*` as a catch-all for pull requests that didn't match any
  of the previous categories." `exclude.authors` is "A list of user or bot login
  handles whose pull requests are to be excluded from release notes."
- **Implication for GLOBIN:** The configuration written this phase uses only
  labels that exist in this repository's taxonomy, and carries the `*` catch-all,
  which `release_notes_problems` in `tools/quality/release/plan.py` checks for by
  name. Without it a pull request matching no category is dropped from the notes
  silently, which reads to a release's audience as "nothing else changed".
  `exclude.authors` is documented and deliberately **unused**: excluding
  Dependabot would hide precisely the dependency changes
  [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) exists to keep visible.

### S-07 — Assets are attached before publication, and immutability makes that ordering load-bearing

- **Canonical location:** GitHub Docs — Managing releases in a repository —
  `https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** "If you have enabled immutable releases for your repository, you
  can only edit the title and release notes after a release is published." The
  recommended ordering is stated outright: "If you have enabled immutable
  releases for your repository, it's recommended to create releases as drafts
  first, attach all assets, and then publish." — "This ensures all assets are in
  place before the release becomes immutable."
- **Implication for GLOBIN:** This is the source for the draft → attach →
  publish sequence in [`../release/RELEASE_POLICY.md`](../release/RELEASE_POLICY.md),
  and the reason it is written as a requirement rather than a preference. Under
  immutability an asset forgotten before publication cannot be added afterwards,
  so the recovery is a new version — which is why the policy's answer to a
  mistaken release is roll-forward rather than repair.

### S-08 — Immutable releases lock the tag and the assets, and generate a release attestation

- **Canonical location:** GitHub Docs — Immutable releases —
  `https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** Once published, "Git tags cannot be moved" and "Release assets
  cannot be modified or deleted". A release attestation is "a cryptographically
  verifiable record of a release containing the release tag, commit SHA, and
  release assets", which lets consumers confirm that "the releases and artifacts
  they are using exactly match the published GitHub releases". Enabling it is
  documented as a repository setting: Settings, the "Releases" section, then
  "Enable release immutability" — and "immutability will only apply to future
  releases".
- **Gap recorded:** The page states what an attestation proves. It does **not**
  state what an attestation does not prove, and it documents **no REST API
  endpoint** for the setting — only the web interface. The endpoint exists all
  the same, under the REST reference for repositories; S-12 records how it was
  found and what it accepts.
- **Implication for GLOBIN:** Two consequences. First, "only apply to future
  releases" fixes the ordering of the whole phase: the setting must be enabled
  *before* `v0.1.0` is published, or the release is created outside the guarantee
  and cannot be brought inside it. Second, the claim that provenance is not
  safety is this repository's own reasoning and is written as such in
  [`../release/RELEASE_POLICY.md`](../release/RELEASE_POLICY.md) — an attestation
  binds an artifact to the release that produced it, which is a statement about
  origin and integrity and not a statement about whether the artifact is
  correct or safe to run. GitHub is not cited for that sentence, because GitHub
  does not make it.

### S-09 — Ruleset rule types and targets are named exactly by the REST API reference

- **Canonical location:** GitHub Docs — REST API — Repository rules —
  `https://docs.github.com/en/rest/repos/rules?apiVersion=2022-11-28`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** Creating a ruleset is `POST /repos/{owner}/{repo}/rulesets`, with
  body fields `name` (required), `target`, `enforcement` (required),
  `bypass_actors`, `conditions` and `rules`. `target` accepts `branch`, `tag`,
  `push` and `repository`. The rule `type` identifiers include `creation`,
  `update`, `deletion`, `non_fast_forward`, `required_signatures`,
  `tag_name_pattern`, `required_linear_history` and `required_status_checks`.
- **Implication for GLOBIN:** The tag ruleset added this phase uses
  `target: "tag"` with `deletion` and `update`, which are the two rules that
  answer the two ways a published tag stops meaning what it meant: deleting it,
  and moving it to another commit. `required_signatures` is deliberately not
  used — it would refuse every tag this repository can currently create (S-14),
  turning a protection into a block. The identifiers are taken from this
  reference rather than from the prose page on available rules, which describes
  the rules in interface language and names none of them.

### S-10 — The prose rules page describes tag applicability but names no identifiers

- **Canonical location:** GitHub Docs — Available rules for rulesets —
  `https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** "You can create branch or tag rulesets to control how users can
  interact with selected branches and tags in a repository." "Restrict
  deletions": only users with bypass permissions "can delete branches or tags
  whose name matches the pattern you specify. This rule is selected by default."
  "Restrict updates": they "can push to branches or tags whose name matches the
  pattern you specify." "Require signed commits" is worded for branches only.
- **Gap recorded:** The page contains none of the API `type` identifiers, and it
  never states outright that a given rule is branch-only — tag applicability is
  inferred from each rule's wording.
- **Implication for GLOBIN:** Two pages were read because neither alone answers
  the question. This one establishes that `deletion` and `update` are meaningful
  for tags; S-09 establishes what they are called. Nothing in this repository
  cites this page for an identifier.

### S-11 — `gh` documents release verification in its own help output

- **Canonical location:** GitHub CLI, version 2.97.0, as installed on the
  development host — `gh release verify --help` and
  `gh release verify-asset --help`. Project home:
  `https://github.com/cli/cli`
- **Accessed:** 2026-08-15
- **Authority:** Primary — upstream tooling documenting itself, which
  [`../SOURCE_POLICY.md`](../SOURCE_POLICY.md) treats as authoritative for the
  tool.
- **Supports:** `gh release verify`: "Verify that a GitHub Release is accompanied
  by a valid cryptographically signed attestation." — "An attestation is a claim
  made by GitHub regarding a release and its assets." — it "fetches the
  attestation for the release and prints metadata about all assets referenced in
  the attestation, including their digests." `gh release verify-asset`: "Verify
  that a given asset file originated from a specific GitHub Release using
  cryptographically signed attestations." — "It ensures the asset's integrity by
  validating that the asset's digest matches the subject in the attestation and
  that the attestation is associated with the release."
- **Gap recorded:** Neither the immutable-releases page (S-08) nor the
  managing-releases page (S-07) mentions either command. The capability was
  established from the installed binary, not from the documentation site.
- **Implication for GLOBIN:** Both commands exist in the version on this host, so
  release integrity verification is a real step rather than an aspiration. Both
  depend on an attestation, and an attestation is produced by publishing under
  immutability (S-08) — so if the setting cannot be enabled, these commands have
  nothing to verify and the release manifest records that as unmeasured rather
  than as a pass.

### S-12 — Probe: immutable releases were observably off before this phase

- **Canonical location:** GitHub REST API, this repository —
  `https://api.github.com/repos/aydhn/GLOBIN/immutable-releases`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the platform reporting its own state.
- **Supports:** `gh api repos/aydhn/GLOBIN/immutable-releases` returned
  `HTTP/2.0 200 OK` with the body `{"enabled":false,"enforced_by_owner":false}`.
  The response carried `X-Accepted-Oauth-Scopes: repo` and
  `X-Github-Api-Version-Selected: 2022-11-28`, so the endpoint is a versioned
  part of the API rather than an internal route.

  The write method is `PUT`, and it takes **no body**. `PUT` with
  `enabled=true` was refused with `422` and the message `"enabled" is not a
  permitted key` — which also named the reference this phase had failed to find:
  `https://docs.github.com/rest/repos/repos#enable-immutable-releases`. `PUT`
  with an empty body returned `HTTP/2.0 204 No Content`, and the confirming read
  returned `{"enabled":true,"enforced_by_owner":false}`.
- **Implication for GLOBIN:** The starting state and the change are both
  evidence rather than memory, which is the whole point of recording a probe.
  Note what the failed attempt bought: a `422` naming the permitted keys is how
  the documented shape was found, so the endpoint is used as documented rather
  than as guessed. The setting shape matches `vulnerability-alerts` and
  `automated-security-fixes` — a bodyless `PUT` to enable — which is the
  platform's convention for a boolean sub-resource. Because immutability applies
  only to future releases (S-08), enabling it **before** `v0.1.0` is published
  is not a preference: a release published first would sit outside the guarantee
  permanently, and no later setting change would bring it inside.

### S-13 — Probe: one branch ruleset existed, and no tag ruleset

- **Canonical location:** GitHub REST API, this repository —
  `https://api.github.com/repos/aydhn/GLOBIN/rulesets`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** `gh api repos/aydhn/GLOBIN/rulesets` returned one entry: id
  `20887017`, name `master-baseline`, `"target":"branch"`,
  `"enforcement":"active"`. Reading it in full gave
  `"conditions":{"ref_name":{"exclude":[],"include":["refs/heads/master"]}}`,
  `"rules":[{"type":"deletion"},{"type":"non_fast_forward"}]`,
  `"bypass_actors":[]` and `"current_user_can_bypass":"never"`. `gh api repos/aydhn/GLOBIN`
  reported `"permissions":{"admin":true,...}` and `"visibility":"public"`.
  A second read confirmed no ruleset with `"target":"tag"` existed. The tag
  ruleset was then created with `POST`, returning id `20890821`, name
  `release-tags`, `"target":"tag"`, `"enforcement":"active"`,
  `"conditions":{"ref_name":{"exclude":[],"include":["refs/tags/v*"]}}`,
  `"rules":[{"type":"deletion"},{"type":"update"}]`, `"bypass_actors":[]` and
  `"current_user_can_bypass":"never"`. Ruleset `20887017` was re-read afterwards
  and was unchanged.
- **Implication for GLOBIN:** The tag ruleset is **added beside** the branch one
  rather than replacing or editing it, and the existing rule set is left
  byte-identical. It also gave the house style to match: enforcement active, no
  bypass actors, and the narrowest rule set that answers the threat. Reading the
  list first is what makes a re-run of this phase idempotent — a second run finds
  the tag ruleset present and leaves it alone rather than creating a duplicate.

  Note which rule is **absent** and why. `creation` is not restricted, because
  restricting it would refuse the very push that publishes `v0.1.0`; the two
  rules chosen answer the two ways a tag that already exists stops meaning what
  it meant, which is being moved and being deleted.

### S-14 — Probe: this host holds no signing key material of any kind

- **Canonical location:** The development host's Git and GPG configuration, read
  directly. Git's documentation for the settings consulted:
  `https://git-scm.com/docs/git-config`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the machine reporting its own state.
- **Supports:** `git config --get commit.gpgsign`, `--get tag.gpgsign`,
  `--get user.signingkey` and `--get gpg.format` each exited `1`, which is Git's
  code for a setting that is not present. `gpg --list-secret-keys` created an
  empty keyring and listed nothing. There is no `~/.ssh` directory.
- **Implication for GLOBIN:** Tag signing is **unavailable**, and this phase does
  not manufacture it. Generating a key to satisfy a checklist would produce a
  signature that proves possession of a key created for the purpose, which is
  worth nothing and reads as worth something — the precise failure
  [`../security/SECURITY_BASELINE.md`](../security/SECURITY_BASELINE.md) is
  written against. `v0.1.0` is an unsigned annotated tag, the manifest records
  `UNAVAILABLE`, and no document describes the release as signed. Note also what
  this does *not* block: nothing in this repository's policy required a signed
  release, so the absence is a recorded limitation rather than a failed gate.
