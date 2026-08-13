---
name: Engineering task
about: Propose work that belongs to a phase of the GLOBIN programme
---

<!--
GLOBIN follows a fixed 320-phase programme (`ROADMAP.md`). Phases are
implemented in order, and implementing ahead is treated as a defect because it
bypasses the design work the later phase exists to do.

Before opening this: check whether the work is already a planned phase. If it
is, this issue is about *executing* that phase, not about adding scope.
-->

## Task

What needs to be done, in one or two sentences:

## Phase

- Phase this belongs to (`ROADMAP.md`): <NNN of 320>
- [ ] This is the current phase
- [ ] This is a later phase and should not be implemented yet
- [ ] This does not map to any existing phase — explain below

If it maps to no phase, say why the programme does not already cover it. A gap
in a fixed roadmap is a significant claim and needs the reasoning stated.

## Rationale

Why this is worth doing, and what breaks or stays broken without it:

## Acceptance criteria

How anyone can tell it is finished. Be specific enough that two people would
agree on the answer.

- [ ]
- [ ]
- [ ]

Beyond these, `docs/engineering/DEFINITION_OF_DONE.md` applies in full.

## Out of scope

What this task deliberately does not include, and which phase owns it:

## Constraints

Which existing decisions bound the solution — ADRs, invariants in
`docs/engineering/ENGINEERING_CONTRACT.md`, or principles in
`docs/ARCHITECTURE_PRINCIPLES.md`:

## Dependencies

- [ ] Needs no new dependency
- [ ] May need a new dependency — named below, with the ADR-0003 zero-budget
      justification

## Evidence required

External behaviour that must be verified against primary documentation before
implementation, per `docs/SOURCE_POLICY.md`:
