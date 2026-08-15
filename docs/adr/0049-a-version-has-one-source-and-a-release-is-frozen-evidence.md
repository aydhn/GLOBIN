# ADR-0049 — A version has one source, and a release is frozen evidence

## Status

Accepted — Phase 016.

## Context

Phase 016 is the band-closing consolidation phase for Phases 001-016. Roadmap
rule 6 gives it one job: "pay down inconsistency before the next band builds on
top of it".

Fifteen phases had produced a repository that could answer *is this tree good?*
in a dozen ways — lint, types, coverage, mutation, shards, evidence, aggregate,
supply, governance — and could not answer two others at all:

1. **Is the foundation, as a whole, finished?** Every gate reports on a slice.
   Nothing reduced the slices to a verdict about the band, so "Phases 001-015 are
   complete" rested on the roadmap's status column and a reader's trust.
2. **What version is this?** `src/globin/__init__.py` had carried
   `__version__ = "0.1.0"` since Phase 001 and `[tool.hatch.version]` had pointed
   at it just as long — but nothing said what the number *meant*, when it should
   change, or how it related to anything published. There were no tags and no
   releases. `SECURITY.md` said so outright: "There is no release, and this table
   deliberately does not invent one… Versioning and release policy belong to a
   later phase."

This is that later phase.

Three facts about the environment shaped the answer, and each was probed rather
than assumed (`docs/research/phase_016_sources.md`):

- **The host holds no signing key material.** No `user.signingkey`, no
  `gpg.format`, no GPG secret key, no `~/.ssh`.
- **Immutable releases were available and switched off**, and GitHub applies
  immutability only to releases published *after* the setting changes.
- **One branch ruleset existed and no tag ruleset did**, so a tag could be moved
  or deleted by anyone who could push.

A fourth fact constrained the shape of any version contract: **no packaging build
has ever been run**, and `MEMORY.md` forbids describing one as verified before
Phases 017-032. So whatever was decided had to hold without a build.

## Decision

### 1. The version has exactly one source, and it is the one already there

`__version__` in `src/globin/__init__.py`, read by Hatchling through
`[tool.hatch.version] path`. Phase 016 **kept** this rather than replacing it.

The Python Packaging Authority recommends proving consistency with a test that
`package.__version__` and `importlib.metadata.version("dist-name")` agree. That
test needs an installed distribution, and this repository runs against the source
tree with no install step. The offline equivalent — asserting that the configured
Hatchling path names the file that defines `__version__` — already existed in
`tests/contract/test_packaging_contract.py` and is what binds the two
declarations. The runtime comparison is the right thing to add when a build
exists, and it is Phases 017-032's to add.

`0.1.0` was not chosen. It was already declared, had never been released, and is
a valid PEP 440 final release. Phase 016 tagged what was there.

### 2. A release tag is `v` plus the version, and nothing else

`tag_for` and `version_for` are inverses over valid versions, and the gate checks
the round trip rather than trusting it.

The accepted version pattern is deliberately **narrower than PEP 440**: three
dotted integers, no epochs, pre-releases, post-releases or local versions. A
release procedure with no answer for a shape should not accept that shape.

### 3. Five mechanisms, kept separate, because they are separate

The single most likely way for release documentation to become dishonest is to
let these blur:

| Mechanism | What it proves |
|---|---|
| Tag annotation | Who created the tag and when. No cryptography. |
| Tag signature | The tagger held a particular key. |
| Commit signature | The committer held a particular key. |
| Release immutability | Tag and assets are unchanged since publication. |
| Release attestation | An artifact came from this release. |

None implies another. Git's own documentation for `git tag -a` describes it as
making "an **unsigned**, annotated tag object", and a signature inside an
annotated tag is optional — so "annotated" and "signed" name different
guarantees. The manifest records a closed three-word vocabulary
(`ANNOTATED_UNSIGNED`, `SIGNED_VERIFIED`, `UNAVAILABLE`) rather than a boolean,
and a contract test asserts nothing else can be emitted.

**GLOBIN's tags are annotated and unsigned, and this is recorded rather than
worked around.** Generating a key so a tag could be called "signed" would produce
a signature proving possession of a key created for that purpose: worth nothing,
and reading as worth something. This extends
[ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) from
platform capabilities to host capabilities — an absence is recorded, never
rounded to a pass.

We also decline to cite GitHub for a claim it does not make. GitHub documents
what a release attestation proves; it says nothing about what it does not prove.
The sentence **"an attestation proves origin and integrity, not safety"** is this
repository's own reasoning and is attributed as such.

### 4. Acceptance is a declaration compared against the tree, not a re-run

`docs/engineering/foundation-acceptance.toml` records fifty-four criteria across
sixteen categories. The gate checks the mechanical half — no repeated or misfiled
identifier, every evidence path present, every category populated, no blocking
criterion unmet — and does not re-execute fifteen phases of gates to re-derive
the judgement.

This is the same shape as
[`mutation-baseline.toml`](../engineering/mutation-baseline.toml) and
[`dependency-reviews.toml`](../engineering/dependency-reviews.toml): a human
judgement written where it can be reviewed, argued with and diffed, with a gate
holding it to account for the parts a machine can check. Nothing generates it.

The status vocabulary is four words with **no `WARN`**. A warning has no release
semantics until somebody defines them, and the definition it acquires in practice
is "proceed anyway".

### 5. The release gate has two subcommands, because there are two questions

`check` asks whether the release *contract* holds. It is deterministic over a
commit, reaches nothing, and is what CI runs.

`ready` adds the release *preconditions*: branch, worktree, agreement with the
remote.

Splitting them is not tidiness. Repository state is not a property of a commit —
a CI checkout legitimately differs from a developer's tree — and folding it into
the default gate would make an unmeasurable condition fail every run. Since
unmeasured outranks failed, that failure would also be the loudest possible one,
for the least real reason.

The gate is in neither `fast` nor `full`, for the reason
[ADR-0047](0047-repository-governance-is-declared-once-and-validated-offline.md)
gives about the governance gate: it **writes artefacts**, and `full` runs before
every commit and reports rather than produces. What must gate a commit lives in
`tests/contract/test_release_contract.py`, which the coverage step already runs.

### 6. A published release is superseded, never repaired

Immutability is enabled, and the tag ruleset restricts `deletion` and `update` on
`refs/tags/v*` with no bypass actors. `creation` is deliberately unrestricted —
restricting it would refuse the very push that publishes a release.

But the rule would hold without the enforcement, because somebody has already
fetched the artifact and their copy does not change when ours does. A release is
a fixed point other work refers to, and a fixed point that moves is worse than a
wrong one. A defect is answered by the next version; a wrong asset is answered by
the next version; a leaked secret is answered by rotating the credential, because
deleting a release does not un-publish it.

"Rollback" is therefore not a release operation here. What it usually means —
depend on the previous version — needs no action, since the previous release
still exists unchanged.

## Consequences

**Good.**

- The band's completeness is answerable from a file rather than from trust, and
  the answer is re-derivable on any machine.
- The version, the tag, the changelog and the acceptance matrix are mutually
  checked, so no one of them can be updated alone.
- A published release cannot be silently altered, by us or by anyone.
- The signing gap is visible in the evidence rather than absent from it, which is
  the difference between a limitation and a surprise.

**Costs, accepted.**

- **A sixth manifest schema.** `globin.release.manifest` joins evidence, supply,
  execution, workflow and governance. The alternative — extending one of them —
  would have coupled release evidence to a schema owned by a different question.
  The canonical JSON writer and digest are imported rather than re-implemented.
- **A fifty-four-row declaration to maintain.** It goes stale if nobody edits it,
  exactly as the mutation baseline does. The mitigations are the same: every
  evidence path is checked to exist, every category must be populated, and both
  documents are compared to each other in both directions.
- **The acceptance statuses are asserted, not computed.** A person can write
  `PASS` beside a criterion that does not hold. This is a real limit and is
  stated plainly in the document rather than papered over; the gate checks the
  evidence exists, not that it says what the reason claims.
- **`ready` can disagree with itself between runs**, because it asks about the
  working tree. That is why it is separate and why CI does not run it.

**What this does not decide.** Whether GLOBIN is ever published to an index —
`pyproject.toml` still carries `Private :: Do Not Upload`. Whether a build works,
which is Phases 017-032's question. And what signing backend to adopt if key
material ever arrives.

## Alternatives Considered

**Derive the version from Git tags** (`hatch-vcs` or similar). Rejected on two
counts. It adds a build dependency, which the `dev` extra is pinned against at
seven entries. And it inverts the failure this phase had: the version would
become unreadable without a tag, so a fresh clone at a commit between releases
would report something like `0.1.1.dev4+g1a2b3c4` — a shape the release procedure
would then have to accept or refuse. Reading a literal from a file has neither
problem, and the literal was already there.

**Generate a signing key so tags could be signed.** Rejected, and it is worth
saying why plainly: it would have made the acceptance matrix show fifty-four
green rows. A key created to satisfy a checklist proves possession of a key
created to satisfy a checklist. The signature would be real cryptography
attesting to nothing, and its presence would stop anybody asking the question the
absence provokes.

**Fold release readiness into `full`.** Rejected because `full` runs before every
commit and reports rather than produces, and this gate writes three artefacts.
The same reasoning kept `evidence`, `shards`, `mutation`, `supply` and
`governance` out of it.

**One subcommand rather than two.** Rejected after working through what CI would
do with it: the release preconditions ask about the working tree, a CI checkout
legitimately differs from a developer's, and the resulting unmeasured verdict
outranks failure. The gate would have been red on every push for a reason that
was not a defect.

**Compute the acceptance statuses instead of declaring them.** Attractive, and
rejected as dishonest in a subtler way than it first appears. A gate that ran
every underlying check and reported the result would be re-running gates that
already exist and already run; what it could *not* do is judge whether a
requirement like "documentation is kept live by tests" is met, because that is a
reading of the evidence rather than a measurement of it. Declaring the judgement
and checking the mechanical half says exactly what is known and by whom.

**Extend an existing manifest schema** rather than adding a sixth. Rejected
because release evidence would then be versioned by a schema owned by a different
question, and a change to either would force a version bump in both.

## Risks and Trade-offs

**The declaration can lie.** A person can write `PASS` beside a criterion that
does not hold, and no test here would catch it. This is the central limitation
and it is stated in the document rather than hidden: the gate checks that the
evidence exists, not that it demonstrates what the reason claims. The mitigations
are that every path is checked to exist, that both documents must agree, and that
the file is small enough to read in full during review.

**Fifty-four rows go stale.** The same risk `mutation-baseline.toml` carries. The
countermeasures are the same, and one is load-bearing: every category must be
populated, so deleting an inconvenient criterion fails rather than quietly
shrinking the matrix.

**Immutability removes the ability to correct a mistake.** Accepted deliberately.
An asset forgotten before publication cannot be added afterwards, and the answer
is a new version. That cost buys the guarantee that a release somebody depends on
cannot change under them, which is the more valuable of the two.

**The tag ruleset could block a legitimate operation.** `update` and `deletion`
are restricted with no bypass actors, including for the owner. If a tag is ever
pushed to the wrong commit, it cannot be moved or removed — the recovery is a new
version. `creation` was deliberately left unrestricted, because restricting it
would have refused the very push that publishes a release.

**A sixteen-category matrix invites box-ticking.** A reviewer skimming fifty-four
`PASS` rows learns less than one reading five. The `reason` field is required for
every criterion, including passing ones, specifically so that each row has to say
something rather than merely be green.

## References

- [ADR-0011](0011-documentation-authority-hierarchy.md) — one owner per fact,
  which is why `GIT_WORKFLOW.md` links to the release policy instead of
  duplicating it.
- [ADR-0040](0040-evidence-records-every-gate-and-its-schema-version-is-a-contract.md)
  — the manifest shape and the schema-version contract this reuses.
- [ADR-0042](0042-one-aggregate-check-decides-a-run-and-the-artifact-digest-lives-outside-the-artifact.md)
  — one required check, which is why release readiness did not become a second.
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — a
  capability is a recorded state, extended here from the platform to the host.
- [ADR-0047](0047-repository-governance-is-declared-once-and-validated-offline.md)
  — the declaration-plus-offline-gate shape this follows.
- [`../release/RELEASE_POLICY.md`](../release/RELEASE_POLICY.md) and
  [`../release/FOUNDATION_ACCEPTANCE.md`](../release/FOUNDATION_ACCEPTANCE.md) —
  what this record decided, written for the person who has to follow it.
- [`../research/phase_016_sources.md`](../research/phase_016_sources.md) — every
  external claim, including the four documentation gaps and the probes that
  established the host's and the platform's actual state.

## Supersedes

Nothing. This is the first record about versioning or release in GLOBIN.

It does, however, retire a claim: `SECURITY.md` stated that "GLOBIN has never
been published, tagged, packaged or distributed" and that "Versioning and release
policy belong to a later phase". That was accurate when written and is now false;
the document has been rewritten rather than left standing.

## Superseded By

Nothing yet.
