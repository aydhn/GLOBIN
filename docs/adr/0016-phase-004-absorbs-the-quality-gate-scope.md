# ADR-0016 — Phase 004 absorbs the quality-gate scope from Phase 013

## Status

Accepted — Phase 004.

**Date:** 2026-08-14

## Context

[`ROADMAP.md`](../../ROADMAP.md) assigned Phase 004 the title *Test Architecture
and Fixture Conventions*, with the purpose of defining test layers, directory
structure, fixture scope rules, naming and the boundary between unit, contract
and integration tests. Phase 013 held *Coding Standards, Static Analysis and
Quality Gates*, which owned tightening the lint and type configuration and
consolidating the local verification pathway into a single authoritative gate.

[ADR-0012](0012-phase-003-delivers-architecture-boundaries.md) made that split
explicit and immutable: *"The lint and type configuration stays exactly as Phase
001 set it until Phase 013 revisits it."*

The owner has directed that Phase 004 deliver the full quality backbone: the
test architecture **and** the lint, type, coverage, hook and continuous
integration gates. That is roughly half of Phase 013's stated scope, arriving
nine phases early.

Three things made absorbing this silently unacceptable rather than merely
untidy. [`SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md) treats a
conflict between artefacts as a defect rather than a precedence puzzle. Phase
013's purpose text would have become false while still describing planned work.
And [`TESTING_STRATEGY.md`](../TESTING_STRATEGY.md) positively argued *against*
a coverage threshold, so adding one without amending that document would leave
the repository asserting both positions at once.

Two further facts bore on the decision. First, the work is genuinely coupled: a
test taxonomy is only enforceable if something rejects a test that ignores it,
and the thing that rejects it is the configuration Phase 013 owned. Delivering
the taxonomy without its enforcement would have produced a documented convention
and no mechanism, which is the failure mode this repository exists to avoid.
Second, the cost of the work rises with the size of the codebase it is applied
to, and GLOBIN currently has thirteen source modules.

## Decision

**1. Phase 004 is retitled** *Test Architecture and Quality Gates*, and delivers
the test taxonomy, fixture conventions, the lint and format contract, the static
typing contract, branch-aware coverage with a threshold, the pre-commit gate,
one canonical quality entrypoint and a verification-only CI workflow.

**2. Phase 013 is retitled** *Coding Standards and Documentation Conventions*.
It retains naming, structure, docstring and typing *conventions* — the human
standards — and the docstring linting that enforces them. It no longer owns the
introduction of the gates, because they now exist; it owns tightening them
against the conventions it defines.

**3. The programme's shape is unchanged.** All twenty band ranges are untouched,
every phase number keeps its position, every phase title remains unique, and
Phase 016 remains the band's consolidation and gate review.

**4. `TESTING_STRATEGY.md` is amended** rather than contradicted. Its coverage
section now distinguishes a threshold used as a floor, which catches regression,
from one used as a target, which produces tests written to satisfy it. The
earlier reasoning is restated rather than deleted, because it was not wrong.

This decision does **not** licence further resequencing. It is the second
amendment to the programme and, like the first, it costs an ADR.

## Consequences

- Phase 013 is a smaller phase than the roadmap originally described, and its
  purpose text says so. The honest cost of this merge is visible there.
- The lint and type configuration changed in Phase 004, which ADR-0012
  explicitly said would not happen before Phase 013. That record is Accepted and
  therefore not edited; this record is what a reader finds when they check, and
  the two must be read together. Nothing here supersedes it: its decision about
  what Phase 003 delivers stands untouched, and this record amends a different
  phase boundary. Both remain Accepted.
- A coverage threshold now exists, reversing a documented position. The reversal
  is argued in `TESTING_STRATEGY.md` rather than performed silently.
- A new top-level `tools/` directory exists, with a row in
  [`REPOSITORY_LAYOUT.md`](../engineering/REPOSITORY_LAYOUT.md).
- Later phases inherit working gates rather than conventions awaiting
  enforcement. Every phase from 005 to 012 is now developed under lint, type,
  coverage and CI checks that would otherwise have arrived after them.
- A second precedent for scope amendment now exists. That is the real cost, and
  it is addressed under Risks below rather than minimised here.

## Alternatives Considered

**Deliver only the roadmap's Phase 004 and defer the gates to Phase 013.**
This was the recommended option and was rejected by the owner after the conflict
was put to them explicitly. It would have preserved the programme exactly, at
the cost of nine phases of work developed without lint, type or coverage
enforcement, and a test taxonomy with no mechanism to enforce it.

**Deliver the gates without amending anything.** Rejected outright. It would
have left `ROADMAP.md` describing Phase 013 work that had already happened and
`TESTING_STRATEGY.md` arguing against a threshold the repository enforces. This
is precisely the state the source-of-truth hierarchy exists to prevent, and it
is worse than either coherent alternative.

**Move the whole of Phase 013 into Phase 004 and repurpose 013 entirely.**
Rejected as wider than necessary. Naming, structure and docstring conventions
are human standards that genuinely benefit from being set once there is more
code to apply them to. Only the mechanism needed to move; the conventions did
not.

**Insert a new phase for the quality gates.** Rejected. Band 1 holds exactly
sixteen phases and every slot is occupied, so inserting one would push
*Foundation Consolidation and Phase Gate Review* out of its band, breaking the
rule that each band ends with a gate review.

## Risks and Trade-offs

The genuine risk is precedent, and it is the same risk ADR-0012 identified. That
record warned in its own Risks section that *"the signal that this decision went
wrong would be a second scope amendment without a correspondingly strong
justification."* This is that second amendment, and intellectual honesty
requires saying so plainly rather than arguing the warning does not apply.

What distinguishes this case, and what a future reader should weigh: the
amendment was proposed to the owner as one of three explicit options with the
conflict, the immutable record and the contradicted document named, and it was
chosen deliberately rather than discovered afterwards. The scope moved *earlier*
rather than later, so no work was deferred and nothing was dropped. Band ranges,
phase numbers and band width are untouched.

That is a defence of this instance, not of the pattern. A fixed 320-phase
programme derives its value from being fixed, and two amendments in four phases
is a rate that would destroy it if sustained. The observable signal that this
went wrong is a third amendment before Phase 016; if one is proposed, the right
response is to question whether the roadmap is being treated as a plan or as a
backlog.

A smaller risk: the gates were configured against a codebase of thirteen
modules. A rule set that is comfortable now may prove noisy at two hundred
modules, and Phase 013 should expect to argue with it rather than inherit it
uncritically.

## References

- [`ROADMAP.md`](../../ROADMAP.md) — the amended programme.
- [ADR-0012](0012-phase-003-delivers-architecture-boundaries.md) — the first
  amendment, its precedent, and the warning this record answers.
- [`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md) — why
  an amendment belongs at tier 4 rather than in a table edit.
- [`../TESTING_STRATEGY.md`](../TESTING_STRATEGY.md) — the amended coverage
  position.
- [ADR-0017](0017-test-taxonomy-as-directories.md),
  [ADR-0018](0018-quality-toolchain-and-explicit-strictness.md),
  [ADR-0019](0019-single-quality-entrypoint.md),
  [ADR-0020](0020-verification-only-continuous-integration.md) — the decisions
  this scope change made possible.

## Supersedes

None.

## Superseded By

None.
