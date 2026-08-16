# Security Baseline and Secret Handling Rules

Where a secret may live, how it is kept out of everything that outlives it, and what a key is
allowed to do.

This document is the specification the rest of the programme builds against. It decides the rules;
it implements none of them. Phase 026 chooses where configuration lives, **Phase 028 implements the
local secret store**, and Phase 029 defines how a credential is collected and validated. Each is
bound by what is written here.

Reporting a vulnerability is [`../../SECURITY.md`](../../SECURITY.md); responding to one is
[`VULNERABILITY_RESPONSE.md`](VULNERABILITY_RESPONSE.md).

---

## Why this exists before there is a secret

GLOBIN holds no credentials. It reaches no exchange, has no account, and its runtime dependency
list is empty. Writing secret-handling rules now looks premature and is the opposite.

The day a credential first exists is the day the rules are least likely to be written, because
there will be something more urgent to do with the key than decide where it may live. Every
mechanism that would need to be retrofitted — redaction, the commit tripwires, the content scanner,
the evidence scrubber — was cheaper to build against a repository with nothing to lose, and each
one is already in place. What was missing was the statement of what they are for.

Eighteen places in this repository deferred that statement to Phase 015. This is it.

---

## 1. Credentials are never committed

**No credential, API key, token, private key, passphrase, session cookie or personal datum is ever
committed to this repository, in any branch, in any file, at any time, for any reason.**

This is absolute. It is [ADR-0004](../adr/0004-official-apis-only-no-scraping.md) and
[`../../AGENTS.md`](../../AGENTS.md), and it admits no exception — not a test fixture, not an
example, not a placeholder that "is not real", not a revoked key, not a comment, not a commit
message.

Three of those are worth naming because each has a plausible-sounding argument behind it:

- **A revoked key is still not committable.** Committing one publishes the account identifier, the
  key format and the fact that this project holds credentials of that type, and it establishes a
  precedent that the next person applies to a live one.
- **A fake key that looks real is not committable.** It defeats every scanner that would have
  caught the real one, by training the allowlist to ignore that shape.
- **History counts.** A credential removed in a later commit is still in the repository. The remedy
  is revocation, not deletion — [`VULNERABILITY_RESPONSE.md`](VULNERABILITY_RESPONSE.md) sets the
  order.

### What enforces it

Five independent controls, none of which replaces another. Three are in this repository, two
are GitHub's.

| Control | Catches | Where |
|---|---|---|
| Filename tripwire | `.env`, `*.pem`, `*.key`, `secrets.toml` and similar, before staging | `tests/contract/test_repository_contract.py` |
| Content scanner | Key headers and documented provider token prefixes, by fingerprint | `tools/quality/supply/secrets.py` |
| Key-name tripwire | A committed `.toml`, `.json` or `.yaml` naming a key `api_key`, `password`, `token` and the like, whatever its value | `tests/contract/test_repository_contract.py` |
| Secret scanning | Known provider patterns, on the pushed commit | GitHub, recorded as a capability |
| Push protection | The same, at the moment of the push, before it lands | GitHub, recorded as a capability |

The first three run offline and before the commit exists; the last two run on GitHub's side and
catch what a local gate was not run for. Their scope, their allowlist rules and why findings are
reported as fingerprints rather than values are in
[`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md), which owns them.

**None of these is a substitute for reading the diff.** The Git workflow requires the staged
content to be inspected before every commit ([`../GIT_WORKFLOW.md`](../GIT_WORKFLOW.md)), and it
requires it precisely because a scanner only finds shapes somebody anticipated.

---

## 2. Where a secret may live

A secret has exactly one permitted home, and the permission is conditional.

### Permitted

**A local secret store outside the repository tree**, on the machine that uses it, readable only by
the account that owns it. Phase 028 implements it; this document fixes the properties it must have:

| Property | Requirement |
|---|---|
| Location | Outside the repository working tree, so that no Git operation can reach it |
| Ownership | Readable by the operating-system account running GLOBIN, and no other |
| At rest | Protected by an operating-system facility, not by a scheme invented here |
| In memory | Held no longer than the operation needs it |
| In transit | Supplied to the code that uses it through an explicit argument, never through a module-level global |
| On screen | Never printed, echoed or displayed, including during entry |
| Identity | Referred to elsewhere by a *name*, never by its value |

**Homemade cryptography is prohibited.** If protection at rest is required, it uses a facility the
operating system provides and documents. A bespoke scheme in this repository would be unreviewed
cryptography guarding the one thing worth guarding, and would give the appearance of protection
without the substance.

### Prohibited

| Not permitted | Why |
|---|---|
| Anywhere in the repository tree | It is one `git add -A` from being published |
| A configuration file committed to the repository | The same, with a filename that invites it |
| A command-line argument | Visible in the process table to every account on the machine, and recorded in shell history |
| A hard-coded literal | Survives every rotation and every review |
| A log record, a metric or a trace | Outlives the process and is copied to places nobody tracks |
| A CI artifact, job summary or workflow log | Published, retained and, on a public repository, world-readable |
| A GitHub Actions secret | See below |
| A test fixture, even a fake one | Trains every scanner to ignore that shape |
| An error message or a stack trace | Reaches the one output nobody redacts by habit |

**Environment variables are permitted only as a hand-off, never as storage.** A process may receive
a secret in its environment from the store, because that is how a child process is given one
without a file. It must not be the place the secret rests between runs, must not be written to a
shell profile, and must not be set by any file in this repository. The environment is readable by
anything that can read the process, and it is inherited by every child — including tools that log
their own environment on failure.

**GLOBIN's continuous integration holds no secret, and this is a rule rather than a circumstance.**
The workflows reference none and there is none to reference
([`../engineering/CI_SECURITY.md`](../engineering/CI_SECURITY.md)). CI verifies; it never
authenticates to anything. Adding a repository secret would give every workflow run a credential to
leak, on a public repository where a pull request can carry code anybody wrote
([ADR-0046](../adr/0046-the-repository-is-public-and-that-changes-the-threat-model.md)). A phase
that believes it needs one must record the decision as an ADR first.

---

## 3. Redaction

**The principle: a value that must not be published is removed before the record exists, not before
it is displayed.**

Removing it at the point of output puts the guarantee in the hands of every sink, formatter and
exporter written afterwards, and one of them will forget. Removing it during construction means a
component added in a later phase inherits the protection without knowing it exists.

That principle has two implementations, and each is owned elsewhere. This document does not restate
either, because a rule maintained in two places diverges:

| What | Owner |
|---|---|
| Log records — the redacted name fragments, substring matching, nesting depth | [`../LOGGING_POLICY.md`](../LOGGING_POLICY.md) and [ADR-0025](../adr/0025-structured-logging-is-a-redacted-domain-event.md) |
| Evidence artifacts — secret-shaped text and absolute paths in anything CI uploads | `tools/quality/evidence/redaction.py` |

Three consequences of the principle bind any future component:

- **Over-redaction is the correct trade.** Redacting a harmless value is an inconvenience;
  printing a live key is not. A rule that errs must err towards removing too much.
- **Absolute paths are redacted too, and for a related reason.** Every absolute path on the
  development host contains the account holder's full name, and evidence bundles are uploaded to a
  public repository. Paths in anything published are repository-relative.
- **A finding about a secret is reported as a fingerprint.** A scanner that prints what it found has
  published it a second time, into a log, an artifact and a summary, all of which outlive the file.

---

## 4. Least-privilege API keys

GLOBIN has no API key today. When Phases 033 onwards create one, these rules bind the key's
configuration. They are written now because a key's permissions are chosen once, in a hurry, at
creation, and are rarely revisited.

| Rule | Statement |
|---|---|
| Minimum grant | A key carries the narrowest permission set the phase using it needs, and no other. A permission is added when a phase demonstrates it needs it, never in anticipation. |
| Withdrawal by default | Any permission allowing funds to leave the account is refused unless a phase's specification requires it and an ADR records the decision. |
| Separation | Read-only work uses a read-only key. A key that may place an order is not the key used for research or market data. |
| Network restriction | Where the venue supports restricting a key to an address, it is restricted. |
| Rotation | A key is rotatable without a code change, because it is referred to by name and not by value. |
| Expiry | Where the venue supports expiry, it is set. A key with no expiry is a key that outlives the reason it existed. |
| Environment separation | A key for one environment is never reused in another. |
| Provenance | Which key exists, what it may do and why is recorded — the record holds the key's *name and grants*, never its value. |

**These are constraints on a later phase, not a description of anything that exists.** Nothing in
this repository creates, stores, validates or uses an API key today. Whether a given Binance
product and environment even offers a particular permission is a question of fact to be verified
against primary documentation when the phase arrives, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md) and
[ADR-0006](../adr/0006-product-and-environment-capability-matrix.md) — not assumed from this table.

---

## What a change touching secrets must satisfy

- No credential, key, token or personal datum appears in the diff, including in a test fixture.
- The staged content was read, not just the file list.
- A new field carrying a sensitive value has a name the redaction fragments already match, or the
  fragment is added in `observability.py` **and** to the list in
  [`../LOGGING_POLICY.md`](../LOGGING_POLICY.md).
- Anything written to `.globin/` was checked for absolute paths, because that directory is
  uploaded.
- A new secret location is not invented. If one is genuinely needed, this document changes first.
- The gates were run, and `python -m tools.quality supply` among them where the change touches
  dependencies, workflows or scanning.

---

## Related

- [`../../SECURITY.md`](../../SECURITY.md) — how to report a vulnerability
- [`VULNERABILITY_RESPONSE.md`](VULNERABILITY_RESPONSE.md) — the response runbook, including the
  credential-exposure lane
- [`SECRET_STORE_CONTRACT.md`](SECRET_STORE_CONTRACT.md) — the interface a stored secret is reached
  through, and the measured Windows limits the phases implementing it must work inside
- [`GOVERNANCE.md`](GOVERNANCE.md) — ownership and security-sensitive paths
- [`../LOGGING_POLICY.md`](../LOGGING_POLICY.md) — log redaction, which this document does not
  restate
- [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — configuration, which deliberately
  knows nothing about secrets
- [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) — the two scanners and their allowlist rules
- [`../engineering/CI_SECURITY.md`](../engineering/CI_SECURITY.md) — why CI holds no secret
- [ADR-0048](../adr/0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md) —
  the decision this document specifies
