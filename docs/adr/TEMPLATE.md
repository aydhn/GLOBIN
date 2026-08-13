# ADR-NNNN — <short statement of the decision, not the topic>

<!--
Copy this file to `NNNN-kebab-case-title.md`, using the next contiguous number.
Delete this comment and replace every <angle-bracket> prompt.

The title states what was decided. "Master-only Git workflow" is a decision;
"Git branching" is a topic. A reader scanning the index should learn the outcome
without opening the file.

Records 0001-0010 predate this template and carry no `## Alternatives
Considered` section. Records 0001-0011 predate the lifecycle sections added in
Phase 003: `## Risks and Trade-offs`, `## References`, `## Supersedes` and
`## Superseded By`. All of them are Accepted and therefore immutable; do not
retrofit them. `tests/test_documentation_contract.py` requires the full set from
ADR-0012 onwards.
-->

## Status

<Proposed | Accepted | Rejected | Deprecated | Superseded by ADR-NNNN> — Phase NNN.

**Date:** <YYYY-MM-DD>

<!--
Accepted and Rejected records are both immutable. A changed decision becomes a
NEW ADR that supersedes this one; this file then stays in place with its status
updated to `Superseded by ADR-NNNN`, so the reasoning history survives.

A Rejected record is worth keeping, not deleting: it records that the question
was asked and answered, which is what stops the same debate recurring.
-->

## Context

<What is true that forces a decision now? State the pressure, the constraint, or
the failure mode being avoided. Include what was tried or observed.

Context matters as much as the decision itself. A future contributor who
understands only *what* was chosen will eventually undo it; one who understands
*why* can tell whether the reason still applies.

Cite evidence from `docs/research/phase_NNN_sources.md` rather than restating
external documentation here.>

## Decision

<What is now binding, stated so that a reader can tell whether a given change
complies. Prefer "X must Y" over "we should probably Y".

Say what the decision does NOT cover, where that boundary is likely to be
misread.>

## Consequences

<What this costs, not only what it gains. An ADR listing only benefits is
advocacy, and advocacy is what gets reversed the first time the cost is felt.

Include:
- what becomes harder or slower
- what is now prohibited that a contributor might reasonably want
- what enforcement exists, if any (a test, a gate, or nothing but this document)>

## Alternatives Considered

<Each realistic alternative, and the specific reason it was not chosen. "It was
worse" is not a reason. Name the trade-off.

If an alternative was rejected only because of present constraints that may
lift, say so — that tells a future reader when to revisit this record.>

## Risks and Trade-offs

<Not a second Consequences section. Consequences are what follows from the
decision being right; this is what happens if it turns out to be wrong.

Answer two questions:
- What is the characteristic failure mode of this choice?
- What observable signal would tell someone it has occurred?

A record with a low confidence level should say so here. An architecturally
significant decision taken with weak evidence is still worth recording, and
knowing it was weak is what makes revisiting it possible.>

## References

<Repository documents, ADRs and research ledger entries this record depends on.
Link; do not restate. External sources belong in the phase's research ledger,
which this section points at rather than duplicating.>

## Supersedes

<`None`, or a link to the ADR this record replaces. Update that record's Status
in the same commit, so the two never disagree — this is checked by test.>

## Superseded By

<`None`, or a link to the ADR that replaced this one. Filled in later, and it is
the only edit an immutable record accepts.>
