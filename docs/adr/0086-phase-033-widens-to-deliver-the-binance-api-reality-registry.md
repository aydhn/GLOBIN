# ADR-0086 — Phase 033 widens to deliver the Binance API reality registry

## Status

Accepted — Phase 033. **Date:** 2026-08-19

## Context

`ROADMAP.md` row 033 reads *Binance Product Family Inventory*, with the purpose
*"Enumerate the officially documented product families and the surfaces each one
exposes."* One clause, one deliverable.

This phase's brief described the band. It asked additionally for an environment
model separating production, demo and testnet by semantics rather than by a
boolean; a product-by-environment capability matrix; a canonical endpoint registry
holding every base URL so none is spelled elsewhere; official-source provenance on
every record; SBE and FIX schema lifecycle tracking; a deterministic snapshot and
diff; and a network refresh with drift classification.

An audit of that brief against the tree found **none of it delivered, and none of
it partly delivered.** This is the opposite finding from the sixteenth amendment,
whose audit found most of its brief already built. Nothing under `src/globin`
mentions Binance. `project_contract.py` names the venue and `roadmap.py` names the
band; no module, document or contract records a single fact about what Binance
exposes. The subject is empty.

It is empty and it is also owned. Four rows in this band name parts of the brief
**by title**:

| Row | Title | What of the brief it owns |
|---|---|---|
| 034 | *Official Documentation Ingestion and Change Tracking* | the refresh, and detecting that documentation changed |
| 035 | *Environment Classification Model* | production, testnet and demo as distinct classes |
| 036 | *Product and Environment Capability Matrix* | the matrix itself |
| 037 | *Base URL and Endpoint Registry* | base URLs with no hard-coded literals |

A third artefact names the same division, and it is an accepted record rather than
a plan. [ADR-0006](0006-product-and-environment-capability-matrix.md) closes with
*"Phase 036 exists specifically to build this matrix, and Phases 033-035 exist to
gather what it needs."* `SOURCE_OF_TRUTH.md` treats a conflict between artefacts
as a defect rather than a precedence puzzle, so this one is named here rather than
resolved by out-voting it: this amendment contradicts that sentence, and ADR-0006
is immutable, so the contradiction is recorded and Phase 048 inherits it.

The same record cuts the other way twice, and both are load-bearing. Its fifth
rule — *"The matrix is built from documented evidence and is re-verified when
Binance documentation changes, not assumed once and trusted forever"* — is a
standing requirement for exactly the refresh and drift machinery the brief asks
for, written in Phase 001 and unowned by any row until now. And its third rule,
that an unmapped combination is refused rather than downgraded, is the property
the registry's query surface must make expressible.

The owner was shown the conflict, the four rows that own the work by name, and a
choice between delivering row 033 alone, delivering the brief whole, or a middle
option deferring only the networked refresh. The answer was to deliver both.

## Decision

**Phase 033 delivers the product family inventory its title names, and the Binance
API reality registry alongside it.** This is the seventeenth scope amendment.

Scored against the four-part test `ROADMAP.md` states — *nothing displaced,
nothing deferred, no phase owns the work, and the two halves need each other*.

**Nothing deferred: MET.** Both halves ship in the same commit range. The product
families and their surfaces are enumerated, and so are the environments, the
endpoint families, the auth mechanisms, the schema lifecycle, the snapshot, the
diff and the refresh.

**The two halves need each other: MET.** A product family inventory with no
environment axis answers no question the band asks next. *Does Spot support FIX*
is not answerable without knowing that Spot FIX exists in production, demo and
testnet with different hosts and the same Ed25519 restriction; *may this key sign
this request* is not answerable from a list of product names. The inventory is the
row axis of a matrix, and a matrix with one axis is a list. More particularly, the
provenance and status machinery — the part that makes the inventory trustworthy
rather than merely present — has nothing to be exercised against if the only thing
recorded is eight product names, every one of which is documented and none of
which is `UNKNOWN`, `RESTRICTED` or `DEPRECATED`.

**Nothing displaced: FAILED.** Rows 034, 035, 036 and 037 are substantially
consumed. What remains for each is stated below, and it is real work, but it is
less than the row implies.

**No phase owns the work: FAILED, and by title.** Four rows own it by title. The
sixteenth amendment's one saving statement was *"No phase owns it by title, which
is the one thing the ninth, tenth and fifteenth could not say."* This amendment
cannot say it either, and it fails the condition more comprehensively than any
record before it: four titles, not one.

**Two of four.**

### This is the largest displacement inside a band the programme has made

Every previous amendment displaced either a handful of far-future rows — 257
through 315, two hundred and fifty phases away — or, in the fourth, the two rows
immediately following. This one displaces the **four consecutive rows immediately
following**, which is twice the reach of the fourth and the only comparable case.

That is offered as evidence rather than as defence. `GRANULARITY_REVIEW.md` found
that *no phase owns the work* has been met once in thirteen scorings and that the
condition therefore carries almost no information. A seventeenth failure does not
strengthen that finding; a failure against **four titles at once, in the band the
amendment is opening rather than a band two hundred phases away**, is a different
observation, and Phase 048 inherits it.

### What remains for rows 034 to 037

Recorded here so that those phases arrive told, and so that the displacement is
specific rather than a gesture. **No roadmap row is rewritten** — the eight
amendments before this one recorded displacement in the ledger and left the future
row's text intact, and `GRANULARITY_REVIEW.md` reserves rewriting for Phase 048.

- **034** keeps the *process*: a re-verification cadence, changelog entries
  accumulated into a tracked log across runs rather than compared pairwise, and
  the review workflow when a drift is classified `BREAKING` or
  `SECURITY_RELEVANT`. This phase delivers the mechanism; 034 delivers its use
  over time.
- **035** keeps the *guarantees*. This phase records what Binance documents about
  each environment. What GLOBIN may do in each — whether a testnet result counts
  as validation evidence, whether a strategy may run against demo — is not a
  documented fact about Binance and cannot be sourced here. **Internal
  simulation**, which row 035 names, is documented by nobody and is untouched.
- **036** keeps the *decisions*. This phase records the matrix; refusing an
  unmapped combination at runtime, which `MEMORY.md` invariant 1 requires, needs a
  caller that does not exist until there is a transport.
- **037** keeps *per-operation* endpoints: paths, methods, security type, weights.
  This phase stops at base URLs and endpoint families, which is where a registry
  can stop without guessing.

## Consequences

**GLOBIN records facts about a venue for the first time.** Everything before this
phase was about the repository or the host. The registry is the first artefact
whose correctness depends on something outside this machine, and it is therefore
the first that can be *silently* wrong. That is why every record carries
provenance and why `EvidenceKind.OBSERVED` exists with nothing able to produce it.

**The band's remaining rows arrive partly built.** Four of the fifteen phases
after this one will find their subject substantially present. They are named
above, and in `scope-amendments.toml`.

**The application still reaches no network.** The refresh is a quality gate, not a
product capability, and `src/globin` makes no outbound connection after this phase
any more than before it. The reasoning is in ADR-0087.

**Nothing here is a trading capability.** No credential, no signature, no request,
no order. The registry describes what a venue exposes; using any of it is Phases
038 onward.

## Alternatives Considered

**Deliver row 033 alone — the inventory, with the full evidentiary machinery.**
The strongest option on the roadmap's own terms and the only one needing no ADR.
Declined by the owner. Its cost was that the machinery would have been built and
then exercised against eight uncontested product names, so the parts that matter —
`UNKNOWN` as distinct from `UNSUPPORTED`, `RESTRICTED`, provenance under
disagreement, drift classification — would have had no case to prove themselves
against until Phase 036.

**Deliver everything except the networked refresh, leaving row 034 whole.** Put to
the owner as the middle option, on the reasoning that a diff between two snapshots
is a pure function and legitimately this phase's, while fetching documents over
time is precisely row 034's title. Declined by the owner in favour of delivering
both. Its cost, had it been taken, was that the registry would have carried source
digests nothing could ever check.

**Deliver the registry as tooling under ADR-0032.** Declined for the reason
ADR-0073 and ADR-0084 declined it: that record's fourth condition is that the
addition adds no runtime capability, and Phases 037 onward must read this registry
from inside the package to resolve an endpoint. A `tools/quality/` addition is
unreachable from `globin.adapters`.

**Rewrite rows 034 to 037 to what remains of them.** Declined. Eight prior
amendments displaced future rows without touching their text, and
`GRANULARITY_REVIEW.md` states that it changes no roadmap row for Phases 033-320
and defers the question of the test itself to Phase 048. An amendment that
rewrites four rows of the band it is opening would be resolving that question by
building, which is the error the review names.

## Risks and Trade-offs

**The characteristic failure mode is a registry that is confidently wrong.** A
capability recorded as `SUPPORTED` on a misreading is worse than one recorded
`UNKNOWN`, because everything downstream inherits it without re-checking. The
observable signal is a Phase 038-045 transport failing against a surface the
registry said existed. Three mitigations are structural rather than intended:
provenance is required by construction so no record exists without a source; the
six status words separate *not documented* from *documented absent*; and the
refresh compares digests rather than re-deriving prose, so a changed document
raises a question instead of quietly answering one.

**A second risk is staleness masquerading as knowledge.** The registry is a dated
snapshot of documentation, and `SOURCE_POLICY.md` states that a source consulted
in an earlier phase is evidence about that date rather than about today. The
mitigation is the refresh; the residual risk is that nobody runs it, since it is
outside `full` by design. The observable signal is a source digest whose recorded
access date is many months old.

**A third is that this amendment's own evidence is self-interested.** The argument
that the two halves need each other is made by the phase that benefits from making
it. It is recorded here in the same terms it was put to the owner, and the
counter-argument — that an inventory *is* deliverable alone, which is why the
roadmap drew it that way — is the first alternative above rather than an omission.

**A fourth is specific to the failure count.** Two conditions have now failed
fourteen times in fifteen scorings, and reading a fourteenth failure as
information about *this* amendment rather than about the test would be the error
`GRANULARITY_REVIEW.md` identifies. This record states its score and does not
argue that the score is unfair.

## References

- [`../engineering/BINANCE_API_REALITY.md`](../engineering/BINANCE_API_REALITY.md) — what the registry holds and how to read it.
- [`../engineering/GRANULARITY_REVIEW.md`](../engineering/GRANULARITY_REVIEW.md) — the finding this score is evidence for.
- [`../engineering/scope-amendments.toml`](../engineering/scope-amendments.toml) — the ledger row.
- [`../research/phase_033_sources.md`](../research/phase_033_sources.md) — every source the registry rests on.
- [`../SOURCE_POLICY.md`](../SOURCE_POLICY.md) — which sources may establish a fact about Binance.
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the test scored above.
- [ADR-0006](0006-product-and-environment-capability-matrix.md) — the matrix this registry builds, and the sentence this amendment contradicts.
- [ADR-0004](0004-official-apis-only-no-scraping.md) — why the refresh may read only official machine-readable resources.
- [ADR-0087](0087-the-api-reality-registry-is-declared-with-provenance-and-drift-is-measured-in-two-regimes.md) — the technical decisions this amendment carries.

## Supersedes

Nothing.

## Superseded By

Nothing.
