# ADR-0010 — Documentation is a deliverable, kept live by tests

## Status

Accepted — Phase 001.

## Context

GLOBIN is built over 320 phases, mostly by agents whose sessions do not share
memory. For such a contributor, the repository's documentation is not a
convenience — it is the only available context. An agent that reads a stale
document does not merely lack information; it confidently acts on a false
model of the system.

Documentation drift is therefore not a tidiness problem here. It is a
correctness problem with a delayed fuse.

Ordinary discipline does not prevent drift, because drift is invisible at the
moment it happens. Nothing fails when a document becomes wrong.

## Decision

Documentation is a deliverable of every phase, and where practical its
correctness is **enforced by tests rather than trusted to discipline**.

Document roles are fixed:

| Document | Role |
|---|---|
| `README.md` | What exists now versus what is planned. Must never overstate maturity. |
| `AGENTS.md` | The binding instruction contract for all coding agents. |
| `CLAUDE.md` | Agent-specific convenience layer. Never an alternate source of truth. |
| `MEMORY.md` | Durable project memory: invariants, phase status. Not a session log. |
| `ROADMAP.md` | The fixed 320-phase programme and current position. |
| `CONTRIBUTING.md` | How to work in this repository and verify changes. |
| `docs/PROJECT_CHARTER.md` | Mission, scope, non-goals. |
| `docs/ARCHITECTURE_PRINCIPLES.md` | Durable technical principles and their reasoning. |
| `docs/SOURCE_POLICY.md` | Which sources may be trusted, and in what order. |
| `docs/TESTING_STRATEGY.md` | What is tested, at what level, and why. |
| `docs/GIT_WORKFLOW.md` | Branch, commit, push and verification procedure. |
| `docs/GLOSSARY.md` | Shared vocabulary, so terms mean one thing project-wide. |
| `docs/adr/` | Decisions with their context and consequences. |
| `docs/research/` | Source ledgers per phase, with access dates and authority. |

Rules:

1. A phase is not complete while its documentation contradicts its code.
2. Decisions with lasting consequence get an ADR. ADRs are immutable once
   accepted; a changed decision is a **new** ADR that supersedes the old one, so
   the reasoning history survives.
3. ADR numbering is contiguous from `0001` and never reused.
4. Unverified facts must name the phase responsible for verifying them. Silence
   is not permitted to look like confirmation.
5. No placeholder debt: no empty documents created to satisfy a filename, no
   fabricated commands, and no fabricated test or capability claims.

`tests/test_documentation_contract.py` enforces what is mechanically checkable:
required documents exist, are substantive, open with a heading, state the
policies they own, carry no placeholder markers, contain no branch instruction
contradicting ADR-0005, and the ADR set is contiguous, well-formed and indexed.

## Consequences

- Adding a required document means updating the contract test, which makes the
  addition deliberate.
- Tests check structure and presence, not prose quality. Writing well remains a
  human and agent responsibility; the tests only prevent the failure modes that
  can be detected mechanically.
- The research ledger format is machine-checked, so sources cannot be recorded
  without a location, an access date and an authority assessment.
- Renaming or moving a required document fails the suite loudly rather than
  leaving a dangling reference.
