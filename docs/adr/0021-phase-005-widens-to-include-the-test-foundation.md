# ADR-0021 — Phase 005 widens to deliver the error taxonomy and the deterministic test foundation

## Status

Accepted — Phase 005.

**Date:** 2026-08-14

## Context

[`ROADMAP.md`](../../ROADMAP.md) assigned Phase 005 the title *Error Taxonomy and
Exception Hierarchy*, with the purpose of designing the project-wide exception
hierarchy separating configuration, transport, exchange, validation and internal
faults. Three other artefacts name Phase 005 as the phase that does this:
[`ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) invariant 9,
[`architecture/README.md`](../architecture/README.md) under *What this phase did
not decide*, and `src/globin/adapters/architecture.py`, whose module docstring
and two `noqa` comments explained that a single ad-hoc `ValueError` scheme was
kept deliberately "so that Phase 005 inherits one scheme to replace rather than
two".

The owner's brief for this phase described something else: deterministic test
isolation, a fixture and test-double contract, branch coverage and a
property-based testing foundation. Both cannot be Phase 005, and choosing
silently was not available — [`SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md)
treats a conflict between artefacts as a defect rather than a precedence puzzle.

Two facts shaped what the alternatives actually were.

First, **most of the brief already exists.** Phase 004 delivered the taxonomy
directories, the automatic level marker, `strict_markers` as an ini option,
branch coverage over `globin` and `tools` with a threshold, `filterwarnings =
["error"]` and `xfail_strict`. Measured before any change in this phase, branch
coverage stood at 99%. The genuinely new material was narrower than the brief
implied: property-based testing, an enforced offline guarantee, process-state
isolation, and a rule for when `unittest.mock` may be used at all.

Second, **no phase in the programme owns that material.** All 320 rows were
checked. Property tests are mentioned once, in
[`TESTING_STRATEGY.md`](../TESTING_STRATEGY.md), as a technique Phases 101-102
will apply to point-in-time correctness — an application, not the foundation.
Nothing is being pulled forward from a later phase, because there is no later
phase to pull it from.

[ADR-0016](0016-phase-004-absorbs-the-quality-gate-scope.md) anticipated this
moment and named it: *"The observable signal that this went wrong is a third
amendment before Phase 016; if one is proposed, the right response is to question
whether the roadmap is being treated as a plan or as a backlog."* This is that
third amendment. The question was put to the owner in exactly those terms, with
four options, and this one was chosen.

## Decision

**1. Phase 005 is retitled** *Error Taxonomy and Deterministic Test
Foundations*. It delivers the exception hierarchy the roadmap already assigned
it, **and** the deterministic testing foundation: a property level with
Hypothesis, an enforced offline guarantee, process-state isolation, and the
test-double rule.

**2. The amendment widens; it does not displace.** No other phase changes title,
number or purpose. Nothing is deferred, nothing is dropped, band ranges and the
sixteen-phase band width are untouched, and Phase 016 remains the band's
consolidation and gate review. This distinguishes it from both earlier
amendments, each of which moved scope between two phases.

**3. The two halves are delivered together because they are coupled.** The
exception hierarchy is the first production code in this repository written under
the new discipline rather than retrofitted with it: the taxonomy's invariants are
what the property and negative-path tests assert, and replacing the ad-hoc
`ValueError` scheme is what proves the branch coverage was measuring something.
Delivering the testing foundation with no new code to apply it to would have
produced infrastructure whose first real use was a phase away.

**4. This does not licence further resequencing.** It is the third amendment, it
answers a warning rather than escaping it, and the reasoning above is narrow on
purpose: *nothing displaced, nothing deferred, no phase owns the work, and the
two halves need each other*. An amendment that cannot say all four things is not
covered by this precedent.

## Consequences

- `ROADMAP.md` carries a third entry in its *Scope amendments* block, and the
  cost of the programme's fixity is now visible three times in five phases.
- The forward references in `ENGINEERING_CONTRACT.md`, `architecture/README.md`
  and `adapters/architecture.py` remain true and are updated to point at
  `globin.errors` rather than at a future phase.
- Phase 005 is a larger phase than the roadmap described. That is stated in its
  purpose text rather than hidden in the diff.
- Later phases inherit an offline, order-independent suite and a property level
  from Phase 006 rather than from somewhere in the hundreds. Every phase from 006
  onward is developed under guarantees that would otherwise have arrived after
  the code they were meant to protect.
- A sixth entry joins the development toolchain
  ([ADR-0023](0023-property-based-testing-as-a-sixth-taxonomy-level.md)), and the
  contract test pinning that list had to be edited — the deliberate friction
  [`DEFINITION_OF_DONE.md`](../engineering/DEFINITION_OF_DONE.md) describes.

## Alternatives Considered

**Deliver only the roadmap's Phase 005 and set the brief aside.** Governance cost
zero; no ADR, no amendment. Rejected by the owner. It would have left the offline
guarantee and the order-independence rule as prose that contributors are asked to
remember, which is the state this repository exists to avoid, and with no phase
owning the work there was no date at which it would have been revisited.

**Deliver only the brief, retitling Phase 005 to the testing scope.** Rejected as
the most expensive option, not the cheapest. Band 1 holds exactly sixteen phases
and every slot is occupied, so the error taxonomy would have had to displace
another phase — a second retitle. It would also have falsified four documents and
three production-code comments, and left the ad-hoc `ValueError` scheme in place
with its stated reason for existing now pointing at nothing.

**Deliver the brief as further Phase 004 work, leaving Phase 005 next.** The only
option costing no amendment: Phase 004 already owns "fixture scope rules" and the
"branch-coverage contract", so the work is arguably its completion. Rejected
because Phase 004 is `Complete` and pushed. Reopening a completed phase to add a
dependency, a taxonomy level and a rewritten strategy document makes "Complete"
mean less than the roadmap says it does, and the frontier would have stayed at 4
while the tree moved substantially.

**Widen Phase 005, as decided.** Chosen. The only option under which nothing is
displaced, nothing is deferred, and every existing forward reference stays true.

## Risks and Trade-offs

The characteristic failure mode is precedent erosion, and it is worse here than
in either earlier case precisely because this amendment is *comfortable*.
ADR-0012 and ADR-0016 each moved work between phases, which forces a visible
argument about what a phase is for. Widening does not: nothing is taken from
anyone, so there is no counterparty to object. A rule that a phase may absorb
adjacent work as long as nothing is displaced would, applied repeatedly, turn the
programme into a sequence of themes rather than a plan, and it would do so
without any single step looking unreasonable.

The observable signal is a fourth amendment, or a Phase 005 that turns out to
have been two phases: if the retrospective at Phase 016 finds that the testing
half and the error-taxonomy half share no tests, no documents and no reasoning,
then the coupling argued in Decision 3 was rationalisation and this record should
be read as evidence for tightening the rule rather than as a precedent to follow.

A smaller trade-off: the coverage floor stays at 95 while measured coverage is
99.57%. Both [`QUALITY_GATES.md`](../engineering/QUALITY_GATES.md) and
`TESTING_STRATEGY.md` state the floor is a regression detector and not a target,
so raising it in a phase about test quality would have contradicted the documents
this phase was extending. The gap is deliberate and will look like slack to
someone who has not read why.

## References

- [`../../ROADMAP.md`](../../ROADMAP.md) — the amended programme and its third
  scope-amendment entry.
- [ADR-0012](0012-phase-003-delivers-architecture-boundaries.md) and
  [ADR-0016](0016-phase-004-absorbs-the-quality-gate-scope.md) — the first two
  amendments, and the warning this record answers.
- [ADR-0022](0022-error-taxonomy-rooted-in-one-type.md),
  [ADR-0023](0023-property-based-testing-as-a-sixth-taxonomy-level.md),
  [ADR-0024](0024-tests-are-offline-and-isolated-by-construction.md) — the
  decisions this scope change made possible.
- [`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md) — why
  an amendment belongs at tier 4 rather than in a table edit.
- [`../research/phase_005_sources.md`](../research/phase_005_sources.md) — the
  external evidence this phase relied on.

## Supersedes

None. Both earlier amendments remain Accepted, and this record amends a phase
neither of them touched.

## Superseded By

None.
