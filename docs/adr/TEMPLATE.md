# ADR-NNNN — <short statement of the decision, not the topic>

<!--
Copy this file to `NNNN-kebab-case-title.md`, using the next contiguous number.
Delete this comment and replace every <angle-bracket> prompt.

The title states what was decided. "Master-only Git workflow" is a decision;
"Git branching" is a topic. A reader scanning the index should learn the outcome
without opening the file.

Records 0001-0010 predate this template and carry no `## Alternatives
Considered` section. They are Accepted and therefore immutable; do not
retrofit them.
-->

## Status

<Proposed | Accepted | Superseded by ADR-NNNN | Deprecated> — Phase NNN.

**Date:** <YYYY-MM-DD>

<!--
Accepted records are immutable. A changed decision becomes a NEW ADR that
supersedes this one; this file then stays in place with its status updated to
`Superseded by ADR-NNNN`, so the reasoning history survives.
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
