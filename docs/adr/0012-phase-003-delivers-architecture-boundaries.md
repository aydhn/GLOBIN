# ADR-0012 — Phase 003 delivers architecture boundaries; static analysis moves to Phase 013

## Status

Accepted — Phase 003.

**Date:** 2026-08-14

## Context

[`ROADMAP.md`](../../ROADMAP.md) assigned Phase 003 to *Coding Standards and
Static Analysis Baseline*, and Phase 002's commit message repeated that
assignment. The owner has directed that Phase 003 instead establish the
system's architectural boundaries: layers, dependency direction, ports and
adapters, a composition root, and the C4 views describing them.

Two artefacts therefore disagreed about what Phase 003 is.
[`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md) is
explicit that a conflict is a defect rather than a precedence puzzle, so it
cannot be absorbed silently by simply building the architecture and leaving the
roadmap describing something else.

Reviewing the programme showed the roadmap had a real gap rather than merely a
different opinion. Band 1 contains sixteen phases and **none** of them owned
system decomposition, yet later bands assume one already exists: Phase 065-080
is titled *Account and Product Adapters*, Phase 079 is *Unified Account
Abstraction Layer*, and Phase 261 is *Concurrency and Isolation Model*. Each
presupposes a layering the programme never defined, and each would have had to
invent one locally.

The two candidate scopes also differ in when they can be done cheaply. Naming,
docstring and typing conventions can be applied to a codebase of any size,
because the change is mechanical and tool-assisted. A dependency direction
cannot: retrofitting one across two hundred modules means moving code, not
reformatting it. GLOBIN currently has three modules, which is the cheapest this
work will ever be.

## Decision

**1. Phase 003 is retitled** *Architecture Boundaries and Dependency Direction*,
and delivers the layer contract, the C4 System Context and Container views, the
ADR lifecycle rules, and the tests that enforce all of it.

**2. The coding-standards scope moves to Phase 013**, which is retitled *Coding
Standards, Static Analysis and Quality Gates*. Phase 013 already owned the
consolidation of lint, type and test configuration into one authoritative gate;
naming, docstring and typing conventions belong with the tools that enforce
them rather than in a separate phase two slots earlier.

**3. The programme's shape is unchanged.** Band 1 still holds exactly sixteen
phases, all twenty band ranges are untouched, every phase title remains unique,
and Phase 016 remains the band's consolidation and gate review. Nothing was
dropped and nothing was renumbered.

**4. Amending phase scope requires an ADR.** [`ROADMAP.md`](../../ROADMAP.md) is
tier 7 in the authority order; a change to the programme must be recorded at
tier 4, where it is visible to a reader who never opens the roadmap. This record
is that change, and the roadmap has been updated to match it.

This decision does **not** licence resequencing the programme generally. Band
ranges remain immutable and remain encoded in
[`../../src/globin/roadmap.py`](../../src/globin/roadmap.py).

## Consequences

- Phase 013 is now a larger phase than the roadmap originally described. That is
  the honest cost of the merge and is visible in its purpose text.
- The lint and type configuration stays exactly as Phase 001 set it until Phase
  013 revisits it. In particular, docstring linting is **not** enabled here.
  Phase 003 adds no tool configuration at all, so no part of the deferred scope
  has been quietly pulled forward.
- A precedent now exists that phase scope can be amended. It is deliberately
  expensive: it costs an ADR, a roadmap edit and a justification, which is the
  friction that stops it becoming routine.
- Phase 002's commit message still says coding standards is Phase 003. Commit
  messages are historical records and are not rewritten; this record is what a
  reader finds when they check.
- Later phases that assumed a layering now have one to build on, rather than
  each inventing a local convention that a consolidation phase would have to
  reconcile.

## Alternatives Considered

**Build the coding-standards phase now and schedule architecture later.**
Rejected. It contradicts an explicit instruction from the owner, and it defers
the one kind of work that gets more expensive with every phase. Coding standards
applied to three modules and coding standards applied to three hundred cost
roughly the same; a layering does not.

**Cascade every band-1 phase down by one slot.** Rejected. Band 1 is full, so
inserting a phase pushes *Foundation Consolidation and Phase Gate Review* out of
the band, breaking the rule that each band ends with a gate review. Compressing
two unrelated later phases to make room would have caused more damage than the
merge chosen here.

**Deliver both scopes inside Phase 003.** Rejected.
[`../engineering/DEFINITION_OF_DONE.md`](../engineering/DEFINITION_OF_DONE.md)
requires a phase to be finished, not merely started, and two phases of work
delivered as one is how a programme stops meaning anything. Merging the smaller
scope into a phase that already owned related work is the narrower change.

**Build the architecture and leave the roadmap describing static analysis.**
Rejected outright. It would make the roadmap false at exactly the point it is
most consulted, and it is the specific failure the source-of-truth hierarchy
exists to prevent.

## Risks and Trade-offs

The genuine risk is precedent. A fixed 320-phase programme derives its value
from being fixed, and one amendment makes the second easier to argue for. If
scope reassignment becomes common, the roadmap degrades into a rolling backlog
and the phase discipline that keeps agents from building ahead loses its
anchor.

Three things bound that risk, and none of them is a promise: band ranges cannot
change and are checked against code; every phase number keeps its position; and
an amendment must be argued in an ADR rather than made by editing a table. The
signal that this decision went wrong would be a second scope amendment without a
correspondingly strong justification.

## References

- [`ROADMAP.md`](../../ROADMAP.md) — the amended programme.
- [`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md) — the
  authority order that makes an ADR the right place for this.
- [`../research/phase_003_sources.md`](../research/phase_003_sources.md) — the
  evidence base for the architecture work this phase unblocks.

## Supersedes

None.

## Superseded By

None.
