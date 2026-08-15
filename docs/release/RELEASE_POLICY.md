# Release Policy

This document is authoritative for versioning and release procedure in GLOBIN.
The reasoning behind it is in
[ADR-0049](../adr/0049-a-version-has-one-source-and-a-release-is-frozen-evidence.md).

Git procedure for ordinary work is [`../GIT_WORKFLOW.md`](../GIT_WORKFLOW.md),
and it stays the only copy of that. What is written here is what a *release*
adds on top of it.

---

## The version has one source

```text
src/globin/__init__.py   __version__ = "X.Y.Z"
```

That is the only place a version number is written. `pyproject.toml` declares
`dynamic = ["version"]` and points Hatchling at the same file through
`[tool.hatch.version] path`, so the build backend and every tool read one string.

`tests/contract/test_packaging_contract.py` asserts that the configured path
names the file that defines `__version__`, which is what stops the two drifting
apart.

**Why not `importlib.metadata`.** The Python Packaging Authority recommends
testing that `package.__version__` and `importlib.metadata.version("dist-name")`
agree. That test needs an **installed distribution**, and this repository runs
its suite against the source tree with `pythonpath = ["src"]` and no install
step — [`../../MEMORY.md`](../../MEMORY.md) records that no packaging build has
ever been run, and that build verification belongs to Phases 017-032. The
contract test above is the offline equivalent: it binds the two declarations
without requiring a build that has not happened. When a build does happen, the
recommended runtime comparison is the right thing to add, and it is a Phase
017-032 concern rather than a gap here.

---

## Version format

A GLOBIN version is **three dotted non-negative integers**: `MAJOR.MINOR.PATCH`.

This is simultaneously a PEP 440 *final release* and a Semantic Versioning
*normal version*, which is the point — one string satisfies both the Python
packaging ecosystem and the ordinary reading of a version number.

`tools/quality/release/plan.py` accepts nothing else. PEP 440 also admits
epochs, pre-releases, post-releases, developmental releases and local versions;
this project admits none of them, because a release procedure that has no answer
for a shape should not accept that shape. Widening the pattern is a decision to
be recorded, not a convenience to be added.

### What each number means

| Change | Increment | Applies from |
|---|---|---|
| A backwards-incompatible change to something published | `MAJOR` | `1.0.0` |
| Functionality added, backwards-compatibly | `MINOR` | now |
| A backwards-compatible fix | `PATCH` | now |

### While the major version is zero

Semantic Versioning 2.0.0 clause 4: "Major version zero (0.y.z) is for initial
development. Anything MAY change at any time. The public API SHOULD NOT be
considered stable."

Note the normative words: MAY and SHOULD NOT. The specification permits a great
deal here; what follows is **this project's own narrower commitment**, not
something the specification compels.

While GLOBIN is `0.y.z`:

- `MINOR` is incremented when a phase or band delivers new capability.
- `PATCH` is incremented for corrections that add no capability.
- `MAJOR` stays `0` until there is a public API to define. `pyproject.toml`
  carries `Development Status :: 1 - Planning` and
  `Private :: Do Not Upload`; the package currently exposes project rules rather
  than a trading interface. `1.0.0` is not a milestone to aim at on a schedule —
  it is what the first stable public surface is called, whenever that arrives.

### The baseline

`0.1.0` is the foundation baseline, closing Phases 001-016. It was not chosen to
start a sequence: the version already existed at `src/globin/__init__.py` from
Phase 001 and had never been released. Phase 016 tagged what was already
declared rather than renumbering it.

---

## Tag naming

```text
v0.1.0
```

A release tag is the letter `v` followed by the version, and the relationship is
exactly that prefix and nothing else. `tag_for` and `version_for` in
`tools/quality/release/plan.py` are inverses over valid versions, and the gate
checks the round trip rather than assuming it.

The tag is **annotated**, created with `git tag -a`. A lightweight tag is a bare
pointer with no author, date or message; a release is a claim somebody makes, and
it should carry who made it and when.

### Annotated, signed, and the difference

Three words that get used interchangeably and must not be:

| Term | What it means |
|---|---|
| **Lightweight tag** | A name for a commit. No author, no date, no message. |
| **Annotated tag** | A real Git object: tagger, date, message. Git's own documentation for `-a` describes it as "an **unsigned**, annotated tag object". |
| **Signed tag** | An annotated tag that *additionally* carries a cryptographic signature, made with `-s` or `-u`. |

A signature inside an annotated tag is **optional**, by Git's description. So
"annotated" and "signed" name different guarantees, and a release record using
them interchangeably would be claiming cryptographic provenance it does not have.

**GLOBIN's tags are currently annotated and unsigned.** The development host
holds no signing key material — no `user.signingkey`, no `gpg.format`, no GPG
secret key, no SSH key. The release manifest records `ANNOTATED_UNSIGNED`, and no
document here describes a release as signed.

That limitation is recorded rather than worked around. Generating a key so that a
tag could be called "signed" would produce a signature proving possession of a
key created for that purpose — worth nothing, and reading as worth something.
Adding real signing means the owner providing key material, and it is
`FND-P-05` in [`FOUNDATION_ACCEPTANCE.md`](FOUNDATION_ACCEPTANCE.md) until then.

---

## Preconditions

A release may be cut only when **all** of the following hold. `python -m
tools.quality release ready` checks the ones a machine can check.

| Precondition | Checked by |
|---|---|
| The branch is `master` | `release ready` |
| The working tree is clean | `release ready` |
| `HEAD` and `origin/master` name the same commit | `release ready` |
| The version is a valid final release | `release` |
| The tag the version implies round-trips back to it | `release` |
| The changelog announces the version, exactly once | `release` |
| Every release document exists | `release` |
| `.github/release.yml` is well formed | `release` |
| No criterion identifier repeats or is misfiled | `release` |
| Every criterion names evidence that exists | `release` |
| **Every blocking criterion is `PASS`** | `release` |
| The whole quality gate passes | `python -m tools.quality full` |
| Supply chain and governance pass | `supply`, `governance` |
| The mutation baseline holds | `python -m tools.quality mutation` |
| The CI run for the release commit was **read** | a person |

The last one is not a formality. An omitted CI result is indistinguishable from
a passing one, and this project has reported a phase complete before its run
existed exactly once — which is why
[`../GIT_WORKFLOW.md`](../GIT_WORKFLOW.md) makes reading it part of being done.

---

## Procedure

The order below is not a preference. Under immutability, assets attached after
publication cannot be attached at all, and immutability applies only to releases
published after the setting was enabled.

1. **Enable immutability first, if it is not already on.** It applies to future
   releases only, so a release published before it sits outside the guarantee
   permanently and no later change brings it inside.
2. **Land the work.** Verify, commit on `master`, push, confirm `HEAD` equals
   `origin/master`, confirm the tree is clean, and read the CI result.
3. **Fix the release commit.** Record its full SHA. Everything after this points
   at that commit and nothing else.
4. **Run the gates**, including `release ready`. A blocking criterion that is not
   `PASS` stops here.
5. **Create the annotated tag** on that exact SHA, and push it.
6. **Create the release as a draft**, against the tag that already exists.
   `gh release create <tag> --draft --verify-tag` — the flag matters: without it
   the tool will happily create a *new* tag on whatever it thinks the current
   commit is.
7. **Attach every asset** to the draft.
8. **Publish.**
9. **Verify integrity** with `gh release verify` and `gh release verify-asset`.
10. **Record what actually happened**, including anything that failed.

### Assets

| Asset | What it is |
|---|---|
| `foundation-acceptance.json` | The acceptance matrix as the gate read it |
| `release-manifest.json` | What was judged, and what the gate concluded |
| `sbom.cyclonedx.json` | The dependency inventory, copied from the supply gate |
| `SHA256SUMS` | Digests for every other asset |

**No wheel and no source distribution.** Nothing has ever built one, so
publishing one would attach an unverified artifact to a release that claims to be
verified. That belongs to Phases 017-032.

`SHA256SUMS` never lists itself — a file whose own digest is one of its lines
cannot be written, since the digest would change the contents. The manifest
carries digests for the other assets, `SHA256SUMS` covers the manifest, and
between them every published byte is described exactly once.

---

## What immutability does and does not give you

Once a release is published with immutability enabled, GitHub states that "Git
tags cannot be moved" and "Release assets cannot be modified or deleted". The
title and release notes remain editable.

Publishing also generates a **release attestation**: "a cryptographically
verifiable record of a release containing the release tag, commit SHA, and
release assets", which lets a consumer confirm that what they have "exactly
match[es] the published GitHub releases".

**An attestation proves origin and integrity. It does not prove safety.** That
sentence is this repository's own reasoning and GitHub is not cited for it,
because GitHub does not make the claim. An attestation binds an artifact to the
release that produced it. It says nothing about whether the artifact is correct,
whether the code is free of defects, or whether depending on it is wise. Reading
a green verification as an endorsement is the same category error as reading a
passing test suite as proof of correctness.

These are four separate mechanisms and this document keeps them separate:

| Mechanism | Proves |
|---|---|
| Tag annotation | Who created the tag and when — no cryptography |
| Tag signature | That the tagger held a particular key — **absent here** |
| Release immutability | That the tag and assets have not changed since publication |
| Release attestation | That an artifact came from this release |

None of them implies another.

---

## When a release is wrong

**A published release is never repaired in place. It is superseded.**

Under immutability, repair is mostly impossible anyway — but the rule would hold
regardless, because somebody has already fetched the artifact and their copy will
not change when yours does. A release is a fixed point that other people's work
can refer to, and a fixed point that moves is worse than a wrong one.

So:

| Situation | Response |
|---|---|
| A defect in a released version | Fix it and release the next `PATCH`. |
| Wrong or missing release notes | Edit the notes. Immutability permits this. |
| A missing or wrong asset | Release the next `PATCH`. The asset cannot be added. |
| Wrong commit tagged | Release the next `PATCH` from the right commit. |
| A secret was published | Follow [`../security/VULNERABILITY_RESPONSE.md`](../security/VULNERABILITY_RESPONSE.md). Rotate the credential first — deleting the release does not un-publish it. |

### Prohibited

- **Deleting a published release**, or its tag.
- **Reusing a version number.** `0.1.0` names one commit forever. Publishing a
  second thing under that name makes every existing reference ambiguous.
- **Moving a tag** to a different commit.
- **Force-pushing** over a published tag.

The first, third and fourth are refused by the platform: ruleset `release-tags`
restricts `deletion` and `update` on `refs/tags/v*` with no bypass actors. The
rule is written here as well, because a protection somebody removed and a rule
nobody wrote read identically afterwards.

"Rollback" is therefore not a release operation in GLOBIN. What people usually
mean by it is *depend on the previous version*, which needs no action here — the
previous release still exists, unchanged, which is the whole point.

---

## Re-running the release tooling

Everything is safe to run twice:

- The gate rewrites its manifest from the tree, and two runs over one commit
  produce identical bytes. It is built twice and compared on every run.
- The changelog check refuses a version announced under two headings, so an
  appended section is caught rather than accumulated.
- Ruleset and settings changes are read before they are written, so a second run
  finds them present and leaves them alone rather than creating duplicates.
- Tag and release creation refuse to overwrite. If the tag exists on the right
  commit, that is success; on a different commit, it is a stop.

---

## From Phase 017 onward

Each phase that delivers capability increments `MINOR` and adds a changelog
entry under `Unreleased`; the entry moves under a version heading when that
version is released. Not every phase needs a release — a release is cut when
there is a reason to fix a point, such as closing a band, and the band-closing
consolidation phase is the natural place for one.

The version in `src/globin/__init__.py` is bumped **in the release commit
itself**, so that the commit a tag names is also the commit whose source declares
that version. A version bumped afterwards would leave the tagged tree declaring
the previous one.
