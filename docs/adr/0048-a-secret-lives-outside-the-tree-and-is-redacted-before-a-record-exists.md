# ADR-0048 — A secret lives outside the tree, and is redacted before a record exists

## Status

Accepted — Phase 015.

## Context

Eighteen places in this repository defer secret handling to Phase 015. ADR-0004
prohibits committing a credential, ADR-0015 says storage and least-privilege key
usage "are designed in Phase 015", ADR-0025 says Phase 015 "owns the security
baseline", ADR-0027 says "secret storage is Phase 015", and
`docs/CONFIGURATION_POLICY.md` records that how secrets are stored is Phase 015's
question. `tools/quality/evidence/redaction.py` says in its own docstring that it
is not the secret-handling policy "which is Phase 015". Every one of those is a
rule with a hole where its justification should be.

GLOBIN holds no credentials. It reaches no exchange, has no account, and its
runtime dependency list is empty. Writing these rules now looks premature and is
the opposite: the day a credential first exists is the day the rules are least
likely to be written, because there will be something more urgent to do with the
key than decide where it may live.

The mechanisms are already built. Two secret scanners exist — one on filenames,
one on content — plus GitHub's secret scanning and push protection. Log records
redact by field name before the record is constructed. Evidence files are scanned
for secret-shaped text and absolute paths before upload. What was missing was the
statement of what they are for, and therefore the ability to tell whether a
future component complies.

## Decision

**A secret has exactly one permitted home: a local store outside the repository
working tree, on the machine that uses it, readable only by the account that owns
it.** Phase 026 chooses where configuration lives, Phase 028 implements the
store, and Phase 029 defines credential collection. This record fixes the
properties all three are bound by, and
`docs/security/SECURITY_BASELINE.md` states them in full.

**Protection at rest uses an operating-system facility, never a scheme invented
here.** Bespoke cryptography in this repository would be unreviewed cryptography
guarding the one thing worth guarding, and would give the appearance of
protection without the substance.

**A secret is referred to by name, never by value.** That is what makes rotation
a configuration change rather than a code change, and it is what lets every other
rule here be checked by inspecting names rather than values.

**Environment variables are a hand-off, never storage.** A process may receive a
secret in its environment from the store, because that is how a child is given
one without a file. It must not rest there between runs, must not be written to a
shell profile, and must not be set by any file in this repository.

**Continuous integration holds no secret, and that is a rule rather than a
circumstance.** Adding a repository secret would give every workflow run a
credential to leak, on a public repository where a pull request can carry code
anybody wrote (ADR-0046). A phase believing it needs one records the decision as
an ADR first.

**Redaction happens during construction of a record, never at its output.**
Removing a value at the point of display puts the guarantee in the hands of every
sink, formatter and exporter written afterwards, and one of them will forget.
Removing it during construction means a component added in a later phase inherits
the protection without knowing it exists. The two implementations —
`globin.domain.observability` for log records, `tools/quality/evidence/redaction.py`
for published artefacts — are owned by `docs/LOGGING_POLICY.md` and by that module
respectively, and the baseline restates neither.

**Over-redaction is the correct trade**, and **absolute paths are redacted for a
related reason**: on the development host every absolute path contains the
account holder's full name, and evidence bundles are uploaded from a public
repository.

**An API key carries the narrowest permission set the phase using it needs.**
Withdrawal permissions are refused unless a phase's specification requires them
and an ADR records it; read-only work uses a read-only key; a key is restricted
by address and given an expiry where the venue supports either; and a key for one
environment is never reused in another. Whether a given Binance product offers a
particular permission is a question of fact to be verified against primary
documentation when the phase arrives (ADR-0006), not assumed from this record.

**The prohibition on committing a credential admits no exception** — not a test
fixture, not an example, not a placeholder, not a revoked key. A revoked key
still publishes the account identifier and the key format, and a fake key that
looks real defeats every scanner that would have caught the real one by training
the allowlist to ignore that shape.

## Consequences

**Eighteen forward references can be closed.** Each now points at a document that
exists rather than at a phase number.

**Phases 026, 028 and 029 are constrained before they are designed.** That is the
intent, and the cost is that a design discovering a genuinely better arrangement
must supersede this record rather than simply proceed.

**Nothing is implemented by this decision.** No module, no store, no prompt, no
key. A reader looking for code will find only rules, and `README.md`'s absent
capabilities list is unchanged — which a contract test asserts, by checking that
no module under `src/globin/` has quietly acquired a credential-shaped name.

**The rules constrain a future the repository cannot yet test.** Most of what is
written here cannot be enforced by a gate today, because there is nothing to
enforce it against. It is enforced by review and by the checklist in
`docs/security/SECURITY_BASELINE.md`, which is weaker than a test and is what is
available before the thing exists.

**`.globin/` gained a fourth writer, and the same obligation.** Anything written
there is scanned for absolute paths before it is uploaded, governance manifest
included.

## Alternatives Considered

**Defer the whole subject to Phase 028, where the store is implemented.**
Rejected. It is what the eighteen forward references already assume, and it means
the properties of the store would be decided by the phase implementing it — which
is exactly the design work a specification phase exists to do first. The roadmap
separates the two deliberately.

**Permit a secret in a gitignored file inside the tree.** Rejected. It is one
`git add -f` and one `.gitignore` edit from being published, both of which are
ordinary operations, and it puts the credential where every tool that walks the
repository will read it.

**Permit GitHub Actions secrets for future integration testing.** Rejected for
now rather than forever. This repository's CI verifies and authenticates to
nothing, so a secret would be a credential with no use and a run to leak from.
Phases 033 onwards may need one; ADR-0006's capability matrix is where that case
would be made.

**Encrypt secrets in the repository with a committed scheme.** Rejected. It moves
the problem to the key protecting the key, which then has the same question and
no better answer, and it invites the homemade cryptography this record prohibits.

**Redact at the sink rather than at construction.** Rejected. It is the cheaper
implementation and it fails the first time somebody writes a second sink, which
is precisely when a project has grown enough for the failure to matter.

## Risks and Trade-offs

**These rules are mostly unenforceable today.** The characteristic failure is a
future phase reading them, agreeing, and implementing something subtly outside
them — because nothing fails. The observable signal is a credential appearing in
a place this record does not list, and the mitigation is that the baseline
carries a short checklist a reviewer can apply.

**Field-name redaction misses a value interpolated into a message.** That is why
`docs/LOGGING_POLICY.md` requires fields rather than formatted strings, and a log
call that interpolates is the failure mode to watch for.

**Specifying a store before building one may specify the wrong store.** The
properties chosen are deliberately capabilities rather than mechanisms — outside
the tree, owner-readable, OS-protected, name-referenced — so that Phase 028 can
satisfy them with whatever Windows actually offers. If none can, this record is
superseded rather than quietly ignored.

**The least-privilege table describes permissions Binance may not offer in the
shape assumed.** It is written as a constraint on a decision, not as a claim
about the venue, and ADR-0006 governs how the real capabilities are established.

## References

- [`../security/SECURITY_BASELINE.md`](../security/SECURITY_BASELINE.md) — the rules this record decides
- [`../security/VULNERABILITY_RESPONSE.md`](../security/VULNERABILITY_RESPONSE.md) — the credential-exposure lane
- [`../LOGGING_POLICY.md`](../LOGGING_POLICY.md) — log redaction, which this record does not restate
- [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) — the two scanners and their allowlist rules
- [`../engineering/CI_SECURITY.md`](../engineering/CI_SECURITY.md) — why CI holds no secret
- [ADR-0004](0004-official-apis-only-no-scraping.md) — the prohibition this record specifies
- [ADR-0006](0006-product-and-environment-capability-matrix.md) — how a venue's real capabilities are established
- [ADR-0025](0025-structured-logging-is-a-redacted-domain-event.md) — redaction during construction
- [ADR-0046](0046-the-repository-is-public-and-that-changes-the-threat-model.md) — why a leak would now be public
- [ADR-0047](0047-repository-governance-is-declared-once-and-validated-offline.md) — the other half of Phase 015

## Supersedes

None.

## Superseded By

None.
