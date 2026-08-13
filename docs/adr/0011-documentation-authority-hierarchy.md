# ADR-0011 — Documentation has an explicit authority order, with code at the top

## Status

Accepted — Phase 002.

**Date:** 2026-08-14

## Context

Phase 001 produced twelve documents, an ADR set and a contract test suite. The
individual documents were sound. The **set** had two structural defects that
would compound across the remaining phases.

First, two documents independently defined when work is finished:
`docs/GIT_WORKFLOW.md` under "Definition of done" and
`docs/PROJECT_CHARTER.md` under "Definition of a completed phase". The two lists
agreed at the time of writing. Nothing kept them agreeing, and nothing said
which one to believe if they diverged.

Second, nothing stated an authority order at all. When a document describes
behaviour the code does not have, a contributor has to decide which to trust.
GLOBIN has no reviewer to ask: work happens on `master` with no pull request
(ADR-0005), and most contributors are agents whose sessions share no memory
(ADR-0010). "Use your judgement" is not available when there is no continuity of
judgement.

A third, smaller problem: `docs/` held two different kinds of document without
distinguishing them — documents describing *what the system is* (charter,
principles, glossary) alongside documents describing *how work is done* (git
workflow, testing strategy). The distinction matters because the two kinds have
different audiences and different review triggers.

## Decision

**1. A single authority order governs the repository**, recorded in
[`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md).
Working code and its passing tests rank highest, then machine-readable
configuration, then policy encoded for tests, then ADRs, then engineering
contracts, then domain reasoning, then the roadmap, then process documents, then
orientation documents.

Code ranks highest because it is the only artefact that cannot misdescribe
itself. This settles *behavioural* questions only. Code that violates an
accepted ADR is a defect, not a redefinition of the ADR — tier 1 answers what
the system does, tier 4 answers what it is permitted to do.

**2. A conflict between tiers is a defect to resolve**, not a precedence puzzle
that licenses leaving the contradiction in place. The order says what to believe
while fixing it.

**3. Documents link rather than copy.** Every class of fact has exactly one
owning document. Where a copy is genuinely required — the roadmap band
boundaries restated in `tests/test_roadmap_contract.py` — it is justified only
because a test compares the copies and fails when they diverge. A copy without
such a test is drift, not a tripwire.

**4. `docs/engineering/` is the canonical home for process contracts.** `docs/`
retains project-level documentation. The boundary is stated in
[`../engineering/REPOSITORY_LAYOUT.md`](../engineering/REPOSITORY_LAYOUT.md).
Phase 002 created the directory alongside the existing files and moved nothing.

**5. [`../engineering/DEFINITION_OF_DONE.md`](../engineering/DEFINITION_OF_DONE.md)
is the single definition of done.** The two prior lists were replaced with
pointers to it.

## Consequences

- Adding a rule now requires deciding which document owns it. This is friction,
  and it is the intended kind: the alternative is the same rule appearing in
  three places and disagreeing with itself within a year.
- Contributors must follow a link to read the full definition of done rather
  than finding it inline in the git workflow. A pointer that is followed is
  better than a copy that is stale.
- `docs/` now has a subdirectory split that a reader must learn. The split is
  documented in one place and no existing file moved, so the cost is one-time.
- Relative links between documents became load-bearing, so
  `tests/test_repository_contract.py` now verifies that every repository-relative
  Markdown link resolves. Without that check, this decision would have made
  broken cross-references *more* likely rather than less.
- ADRs 0001-0010 remain unchanged. This record adds an order over the existing
  documents; it does not reinterpret any earlier decision.
- The order is documented, not executable. Nothing prevents a contributor from
  believing the wrong tier. What the tests enforce is that documents exist, are
  substantive, and that their links resolve — the ranking itself is a rule for
  humans and agents to apply.

## Alternatives Considered

**Leave the order implicit.** Rejected. It was already implicit in Phase 001 and
had already produced two competing definitions of done within a single phase.
The failure mode is silent and compounds.

**Put the definition of done in `CONTRIBUTING.md`.** Rejected. `CONTRIBUTING.md`
addresses people, `AGENTS.md` addresses agents, and both need the same
definition. Placing it in either would have forced the other to copy it,
recreating the defect this record exists to remove.

**Keep a flat `docs/` directory.** Rejected, but narrowly — a flat directory is
simpler and the existing eleven files were navigable. The split was chosen
because the two document kinds have different review triggers: project-level
documents change when the system's design changes, process documents change when
the way of working changes. Conflating them means every phase must scan all of
them to decide what needs updating.

**Rank documentation above code.** Rejected. It is superficially attractive —
intent should govern implementation — but it makes every stale document a source
of authority and gives contributors no way to discover that a document is wrong.
Ranking code first for behavioural questions, while keeping ADRs authoritative
for permission, captures the useful half without that cost.
