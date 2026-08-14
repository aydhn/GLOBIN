# ADR-0032 — Verification tooling may be added outside phase scope, under six conditions

## Status

Accepted — Phase 008.

**Date:** 2026-08-14

## Context

`ROADMAP.md` assigns Phase 008 to *Domain Value Types and Units*. The brief the
owner supplied for the phase described test architecture, regression fixtures,
deterministic test selection and mutation testing instead. An audit against the
repository found every item of it already delivered — strict markers and the
command table in Phase 004, executable architecture tests in Phase 003, the
autospec rule and the offline guard in Phase 005 — with two exceptions:
serialization round-trip contracts, which **Phase 012 owns**, and mutation
testing, which **no phase in the programme owns at all**.

This is the sixth time such a brief has collided with the roadmap.
[ADR-0012](0012-phase-003-delivers-architecture-boundaries.md),
[ADR-0016](0016-phase-004-absorbs-the-quality-gate-scope.md) and
[ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) are the three
amendments that were made; a fourth was proposed at Phase 006 and refused, and a
fifth at Phase 007 and refused. `MEMORY.md` records the standing instruction that
a further one "should be refused rather than argued".

The conflict was put to the owner with four options. He chose to deliver the
roadmap's phase as written **and** to add the mutation gate as tooling rather
than as phase scope, with this record as the condition of doing so.

The distinction is not a technicality. `tools/quality` itself was not a phase
deliverable in the sense a module is: it is the machinery by which every phase is
verified. But "it is only tooling" is also exactly the sentence somebody will use
to absorb real scope, which is why the permission below is narrow on purpose.

## Decision

**1. Verification tooling may be added in a phase that does not name it, if and
only if all six of the following hold.**

1. **It displaces no phase.** Nothing in the programme owns the work, so nothing
   is moved out of a band to make room.
2. **It defers nothing.** The phase's own deliverable is delivered in full, in
   the same commit.
3. **It adds no dependency.** The `dev` extra is unchanged, and the toolchain
   `test_packaging_contract.py` pins stays the same size.
4. **It adds no runtime capability.** Nothing under `src/globin/` gains behaviour
   because of it. Tooling verifies; it does not participate.
5. **It only reports.** The tool does not modify the working tree, and it is not
   added to `fast` or `full`, so no existing gate changes what it does.
6. **It is documented and tested to the same standard as everything else** —
   a row in the command table, a row in `QUALITY_GATES.md`, tests at the levels
   `TESTING_STRATEGY.md` describes, and the branch coverage floor held.

**2. An addition that cannot state all six is not covered by this record.** It is
a scope amendment, and it costs an ADR that says so, under the conditions
ADR-0021 already set.

**3. This is not a licence to reopen a settled decision.** The mutation gate does
not change the coverage floor, the Windows-only CI matrix, or the offline guard —
the three decisions `MEMORY.md` marks as taken and not to be re-argued.

**4. The roadmap text is unchanged.** No phase is renamed, no status moves, and
`MEMORY.md`'s count of three amendments stays three. This record is not a fourth,
and the distinction is the whole point: an amendment changes what a phase *is*,
and this changes nothing about any phase.

## Consequences

Phase 008 delivers its own scope plus a verification gate the programme never
scheduled. `python -m tools.quality mutation` exists, CI runs it, and
`docs/engineering/mutation-baseline.toml` is a committed artefact somebody has to
maintain.

The six conditions are now the test a future proposal has to pass, and they are
deliberately hard to satisfy. Condition 3 alone rules out most tools worth
wanting: anything that arrives as a dependency needs Phase 014's review process,
which does not exist yet.

A reader encountering the mutation gate and asking "which phase asked for this"
has an answer, in the place the repository keeps answers to that question. That
is the actual work this record does. Undocumented tooling is indistinguishable
from scope leakage six phases later.

## Alternatives Considered

**Amend Phase 008 to the brief.** A sixth proposal of the kind twice refused. It
would displace *Domain Value Types and Units* from a band whose sixteen slots are
all occupied, failing three of ADR-0021's four conditions before the argument
even starts.

**Deliver Phase 008 alone and defer mutation testing entirely.** Defensible, and
the most conservative reading of `MEMORY.md`. It was offered and not chosen. Its
cost is that no phase would ever pick the work up, because none names it — the
scope would simply cease to exist rather than being scheduled.

**Add the gate with no record at all**, on the grounds that tooling is not phase
scope and needs no permission. This is the option that would have been easiest
and is the one most worth refusing: it is precisely how the sentence "it is only
tooling" becomes load-bearing without anyone having examined it.

**Write the conditions as guidance rather than as a test.** Softer, and useless.
ADR-0021's four conditions work because an amendment that cannot state all four
is not covered; six conditions stated as preferences would be six conditions
argued around.

## Risks and Trade-offs

The characteristic failure is condition creep: a later addition that satisfies
five of the six, with a paragraph explaining why the sixth does not really apply.
The observable signal is an ADR citing this one while arguing that one condition
is unnecessary in its particular case. That argument is the thing this record
exists to make visible, and it should be answered by refusing rather than by
extending.

The second risk is subtler. By making tooling additions legitimate, this record
makes it slightly easier to spend a phase on machinery rather than on the
programme. The countermeasure is condition 2: the phase's own deliverable comes
first and in full, and a phase that delivers only tooling has not satisfied it.

## References

- [`ROADMAP.md`](../../ROADMAP.md)
- [`MEMORY.md`](../../MEMORY.md), the amendment history and the three settled decisions
- [`docs/engineering/QUALITY_GATES.md`](../engineering/QUALITY_GATES.md)
- [ADR-0019](0019-single-quality-entrypoint.md)
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md)
- [ADR-0033](0033-mutation-testing-is-a-repository-native-ast-harness.md)

## Supersedes

None.

## Superseded By

None.
