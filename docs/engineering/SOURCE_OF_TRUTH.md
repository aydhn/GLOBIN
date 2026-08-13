# Source of Truth

When two artefacts in this repository disagree, this document decides which one
is believed while the disagreement is being fixed.

It exists because GLOBIN has no reviewer. Work happens on `master` with no pull
request (ADR-0005), and most contributors are agents with no memory of previous
sessions. "Ask someone which document is right" is not available here, so the
answer has to be written down.

---

## The rule that matters most

**A conflict is a defect, not a puzzle to route around.**

This hierarchy tells you what to trust *while you resolve the contradiction*. It
does not license leaving the contradiction in place. If a document disagrees with
the code, one of them is wrong and the phase is not finished until they agree —
that is [ADR-0010](../adr/0010-living-documentation-responsibilities.md).

Reporting the conflict and continuing is acceptable only when fixing it would
exceed the current phase's scope. In that case say so explicitly, and name the
phase that owns the fix.

---

## Authority order

Highest authority first. Lower tiers describe; higher tiers decide.

| # | Artefact | Owns |
|:-:|---|---|
| 1 | Working code and its passing tests | What the system actually does |
| 2 | [`pyproject.toml`](../../pyproject.toml) | Tool configuration and packaging metadata |
| 3 | [`project_contract.py`](../../src/globin/project_contract.py), [`roadmap.py`](../../src/globin/roadmap.py) | Identity and policy constants encoded for tests |
| 4 | [`docs/adr/`](../adr/README.md) | Accepted architectural decisions and their reasoning |
| 5 | [`ENGINEERING_CONTRACT.md`](ENGINEERING_CONTRACT.md) | General engineering invariants all code must satisfy |
| 6 | [`ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md), [`SOURCE_POLICY.md`](../SOURCE_POLICY.md) | Domain reasoning; which external sources may be trusted |
| 7 | [`ROADMAP.md`](../../ROADMAP.md) | Phase scope, sequence and status |
| 8 | [`AGENTS.md`](../../AGENTS.md), [`CONTRIBUTING.md`](../../CONTRIBUTING.md) | How a change is made and delivered |
| 9 | [`README.md`](../../README.md), [`CLAUDE.md`](../../CLAUDE.md) | Orientation and navigation |

[`MEMORY.md`](../../MEMORY.md) sits outside the ladder. It is a cache of durable
facts asserted elsewhere, kept so a session can start without reading everything.
It never wins a conflict; a stale entry there is a bug in `MEMORY.md`.

---

## Why code outranks documentation

Because code is the only artefact that cannot lie about itself.

A document describing behaviour can drift silently for months. Code cannot: it
either runs or it does not, and its tests either pass or they do not. When
`README.md` claims a capability the code does not have, the code is right about
what exists and the README is wrong about what it described.

This cuts the other way too, and it matters more. **Code being authoritative
about behaviour does not make it authoritative about intent.** If working code
violates an ADR, the code is not thereby correct — it is a defect that a test
failed to catch, and the fix is to change the code, not to rewrite the ADR.
Tier 1 answers *"what does this system do?"*. Tier 4 answers *"what is this
system allowed to do?"*. Never let the first quietly redefine the second.

---

## Why `pyproject.toml` outranks prose about tooling

There is exactly one place where the line length, the lint rule set, the type
checking strictness, the interpreter floor and the test paths are configured.
Any document that restates one of those values is a copy that will fall out of
date, and `tests/test_packaging_contract.py` asserts several of them precisely so
that drift breaks the build.

Documents should name the setting and point at the file rather than repeat the
value. Where a value does appear in prose — the interpreter floor, for instance —
it appears because a contributor needs it before they can run anything, and it is
covered by a test.

---

## Encoded policy, and why it is deliberately duplicated

Tier 3 looks like a violation of "do not copy". It is not, and the exception is
worth understanding.

`src/globin/roadmap.py` holds the twenty band boundaries.
`tests/test_roadmap_contract.py` restates those same boundaries as a literal
tuple. That duplication is the entire point: editing the module alone cannot
silently redefine the programme, because the test still holds the original. The
copy is a **tripwire**, not a second source of truth, and it is only ever
justified when a test compares the two copies and fails when they diverge.

If you find yourself copying a value without a test that compares the copies, you
are creating drift, not a tripwire.

---

## Documents link; they do not copy

The lower tiers exist to orient people, and they are the ones most tempted to
restate a rule for the reader's convenience. Resist it.

- [`README.md`](../../README.md) links to policy; it does not restate policy.
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) links to
  [`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md); it does not reproduce the
  checklist.
- [`CLAUDE.md`](../../CLAUDE.md) is explicitly a convenience layer over
  [`AGENTS.md`](../../AGENTS.md) and says so in its own header.

A restated rule is a rule that will eventually be wrong in one of its locations,
and nothing will tell you which one.

---

## Related

[`DOCUMENTATION_STANDARD.md`](DOCUMENTATION_STANDARD.md) governs a different
question: what each document type is *for* and how it is written. This document
governs only what happens when two of them disagree.
