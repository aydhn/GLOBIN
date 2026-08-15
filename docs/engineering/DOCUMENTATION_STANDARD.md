# Documentation Standard

What each kind of document is for, who keeps it current, when it is revisited,
and how it is written.

Documentation in GLOBIN is a deliverable, not a courtesy
([ADR-0010](../adr/0010-living-documentation-responsibilities.md)). Most
contributors here are agents starting with no memory of previous sessions, so
the repository is the only context that survives. A document that is wrong is
worse than one that is missing: missing prompts a question, wrong prompts
confident action.

This document governs **taxonomy and craft**. Two neighbours govern the other
questions: [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md) decides which artefact
wins when two disagree, and [`REPOSITORY_LAYOUT.md`](REPOSITORY_LAYOUT.md)
decides which directory a file belongs in.

---

## Document types

| Type | Answers | Lifecycle |
|---|---|---|
| **Charter** | What is GLOBIN for, and what is it explicitly not for? | Rarely changes; a change is a change of project |
| **Principles** | What durable technical reasoning constrains the design? | Grows as domain understanding deepens |
| **ADR** | What was decided, why, and at what cost? | **Immutable once Accepted**; superseded by a new ADR |
| **Engineering contract** | What must all code satisfy, forever? | Grows slowly; entries are added, rarely removed |
| **Standard** | How is a recurring class of work done? | Revised when the practice genuinely changes |
| **Policy** | What is permitted, and what is prohibited? | Revised when scope or risk posture changes |
| **Workflow** | What are the steps, in order? | Revised when the procedure changes |
| **Roadmap** | What is planned, in what order, and what is done? | Status changes every phase; structure never |
| **Research ledger** | What external evidence was relied on, and when? | Append-only per phase; never rewritten |
| **Memory** | What durable facts should a new session load first? | Updated every phase; entries removed when false |
| **Orientation** | Where do I start, and what exists today? | Updated whenever maturity changes |

### One subject, one owner

Every class of fact has exactly one document that owns it. Others link.

| Subject | Owner |
|---|---|
| Mission, scope, non-goals | [`PROJECT_CHARTER.md`](../PROJECT_CHARTER.md) |
| Domain and architectural reasoning | [`ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md) |
| Universal engineering invariants | [`ENGINEERING_CONTRACT.md`](ENGINEERING_CONTRACT.md) |
| When work is finished | [`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md) |
| Which sources may be trusted | [`SOURCE_POLICY.md`](../SOURCE_POLICY.md) |
| What is tested and why | [`TESTING_STRATEGY.md`](../TESTING_STRATEGY.md) |
| Which checks are mandatory, and what a failure means | [`QUALITY_GATES.md`](QUALITY_GATES.md) |
| Lint and type rules, and how to obtain an exception | [`STATIC_ANALYSIS.md`](STATIC_ANALYSIS.md) |
| What CI is trusted with, and how a pin is verified | [`CI_SECURITY.md`](CI_SECURITY.md) |
| Git procedure | [`GIT_WORKFLOW.md`](../GIT_WORKFLOW.md) |
| Where files live | [`REPOSITORY_LAYOUT.md`](REPOSITORY_LAYOUT.md) |
| Precedence between artefacts | [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md) |
| Terminology | [`GLOSSARY.md`](../GLOSSARY.md) |
| Agent obligations | [`AGENTS.md`](../../AGENTS.md) |
| Phase scope and status | [`ROADMAP.md`](../../ROADMAP.md) |

If you cannot name the owner of a fact you are about to write, you are probably
about to duplicate one.

---

## Review cadence

Documentation is not reviewed on a calendar. It is reviewed when the thing it
describes changes.

- **Every phase** updates the documents its work touched. This is part of the
  [Definition of Done](DEFINITION_OF_DONE.md), not follow-up work.
- **Every phase** updates [`ROADMAP.md`](../../ROADMAP.md) status and
  [`MEMORY.md`](../../MEMORY.md) programme state.
- **Every phase relying on external behaviour** adds
  `docs/research/phase_NNN_sources.md`.
- **Every band-ending phase** (016, 032, 048, … 320) reconciles the band's
  documentation and resolves contradictions accumulated across sixteen phases.
  These phases exist for exactly this.
- **Accepted ADRs are never revised.** A changed decision becomes a new ADR that
  supersedes the old one, and the old one stays with its status updated. The
  reasoning history is the point.

---

## Writing conventions

### Structure

- Open with a level-1 heading naming the document. Enforced by
  `tests/contract/test_documentation_contract.py`.
- One sentence under the heading saying what the document is for.
- Use `##` and `###`; do not skip levels.
- Prefer tables for enumerable facts, prose for reasoning. A table of reasoning
  is unreadable; a paragraph listing eleven directories is worse.

### Language

- **British English** in prose: `behaviour`, `optimisation`, `normalise`,
  `recognise`, `licence` as a noun.
- **Two established exceptions**, both inherited from Phase 1 and both
  deliberate:
  - `synchronized` / `synchronization` are used consistently in prose. One
    occurrence is inside [ADR-0005](../adr/0005-master-only-git-workflow.md),
    which is Accepted and therefore immutable — the exception is mandatory, not
    merely convenient.
  - Roadmap band and phase **titles** are fixed identifiers
    (`Optimization and Parameter Governance`). They are pinned by
    [`roadmap.py`](../../src/globin/roadmap.py) and asserted by tests. Never
    re-spell a title; the surrounding purpose prose stays British.
- Plain, direct sentences. This is a technical document read under time
  pressure by someone deciding whether they may do something.

### Mechanics

- Wrap at **100 columns**, matching `tool.ruff.line-length` in
  [`pyproject.toml`](../../pyproject.toml) and `max_line_length` in
  `.editorconfig`.
- **Relative links** between repository documents, never absolute URLs to the
  GitHub web interface. They must resolve from the containing file's directory —
  enforced by `tests/contract/test_repository_contract.py`.
- **Language-tagged fenced code blocks** (` ```bash `, ` ```python `,
  ` ```text `), one command per block so it can be copied and run.
- Reference code as `` `path/to/file.py` `` in backticks.
- UTF-8, LF in the repository, final newline. Governed by `.gitattributes` and
  `.editorconfig`; do not restate their values in prose.

### Tone

- Explain **why**, not just what. A rule without its reason gets removed by the
  next person who finds it inconvenient.
- Name the cost of a decision. A document that lists only benefits is marketing.
- Address the reader as someone competent who lacks context, not as someone who
  needs persuading.

---

## Prohibited

**Marketing register.** No superlatives, no promotional framing. GLOBIN's
documentation describes an unfinished system honestly.

**Any claim of guaranteed return, win-rate or profitability.** Not in
documentation, not in code comments, not in commit messages, not in logs. The
stated objective is a probabilistic edge after realistic costs
([`ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md)).

**Future work in the present tense.** Write "the execution engine is implemented
in Phases 081-096", never "the execution engine handles retries". The second
sentence is a lie with a delayed fuse — it will be read as a description of
existing behaviour.

**Unmarked uncertainty.** If a fact is not established, say so and name the phase
that must establish it. Silence must never be mistaken for confirmation.

**Duplication.** Link to the owner instead. If a reader genuinely needs a fact in
two places, that is a signal the owner is in the wrong document, not a licence to
copy it.

**`TODO`, `FIXME`, `XXX`, `TBD` and placeholder text.** Rejected by
`tests/contract/test_documentation_contract.py`. Unfinished thinking is recorded as a
roadmap phase or an issue, not as a marker that will be read as a promise and
then forgotten. Template files use angle-bracket guidance
(`<what forces this decision?>`) instead.

---

## Enforcement

Conventions that can be checked are checked, because prose can be skipped and a
failing test cannot ([`TESTING_STRATEGY.md`](../TESTING_STRATEGY.md)).

| Convention | Enforced by |
|---|---|
| Required documents exist and are substantive | `test_documentation_contract.py` |
| Documents open with a level-1 heading | `test_documentation_contract.py` |
| Each document states the policies it owns | `test_documentation_contract.py` |
| No placeholder debt | `test_documentation_contract.py` |
| No instruction contradicting `master`-only | `test_documentation_contract.py` |
| ADRs are contiguous, well-formed and indexed | `test_documentation_contract.py` |
| Research ledgers are structured and dated | `test_documentation_contract.py` |
| Relative links resolve | `test_repository_contract.py` |
| `ROADMAP.md` matches the encoded band skeleton | `test_roadmap_contract.py` |

The rest — tone, register, honesty about maturity — cannot be automated and is
the contributor's obligation under
[`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md).
