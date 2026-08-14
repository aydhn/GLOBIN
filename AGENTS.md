# AGENTS.md — Instruction contract for coding agents

This file is binding for every automated contributor to GLOBIN, regardless of
which tool or model you are: Codex, Claude, Jules, Cursor, or anything else.

Read it before making changes. It exists because most contributors to this
project arrive with no memory of previous sessions, and the repository is the
only context they have.

---

## 1. The project in one paragraph

GLOBIN is a locally hosted, autonomous cryptocurrency research and trading
system for Binance Global, built over a fixed programme of 320 phases. It runs
on one Windows machine, depends only on free components, and uses only
officially documented interfaces. **It does not currently trade.** See
[`README.md`](README.md) for present maturity and [`ROADMAP.md`](ROADMAP.md) for
the programme.

---

## 2. Before you change anything

1. **Inspect the repository.** Read what exists before writing. Do not assume
   file contents from a filename.
2. **Read the relevant documentation.** At minimum
   [`ROADMAP.md`](ROADMAP.md) for the current phase,
   [`MEMORY.md`](MEMORY.md) for durable facts,
   [`docs/engineering/ENGINEERING_CONTRACT.md`](docs/engineering/ENGINEERING_CONTRACT.md)
   for the invariants your code must satisfy,
   [`docs/ARCHITECTURE_PRINCIPLES.md`](docs/ARCHITECTURE_PRINCIPLES.md), and any
   ADR touching your area.
3. **Confirm the phase you are working on.** Work belongs to a phase. If a task
   spans phases, say so rather than quietly absorbing later work.
4. **Never discard unexplained changes** in the working tree. They may be the
   owner's work in progress. Ask or preserve; do not delete.

---

## 3. Correctness rules

### Do not invent external behaviour

Never guess an API endpoint, parameter name, response field, error code, rate
limit, or library function signature. If external behaviour matters, consult
current primary documentation — see
[`docs/SOURCE_POLICY.md`](docs/SOURCE_POLICY.md) — and record what you used in
the phase's research ledger under `docs/research/`.

A plausible-looking endpoint that does not exist is worse than an admission of
uncertainty, because it survives review and fails in production.

### Do not fabricate results

Never report a command as run, a test as passing, a build as succeeding, or a
capability as verified unless you actually executed it and saw the result. If a
check could not run, say precisely which one and why.

### Mark unverified facts

If a fact is not yet established, state that explicitly and name the phase
responsible for establishing it. Silence must never be mistaken for
confirmation.

---

## 4. Scope rules

- **Do not silently broaden scope.** Implement the current phase. Later phases
  are not "while I'm here" work; premature implementation is a defect because it
  bypasses the design work that phase was meant to do.
- **Do not narrow scope either.** Finish the whole task. If part is blocked,
  complete everything else and state plainly what was left and why.
- **Do not delete working functionality to simplify a task.** If existing
  behaviour is in your way, that is a design discussion, not a deletion.
- **Preserve backward compatibility** unless the phase you are executing
  explicitly changes it.

---

## 5. Hard prohibitions

These are not preferences. Violating any of them is a defect regardless of how
convenient it seemed.

| Never | Why | Reference |
|---|---|---|
| Commit credentials, API keys, tokens or private keys | Permanent exposure in history | ADR-0004 |
| Scrape Binance, parse its web pages, or call undocumented private endpoints | Brittle, unauthorised, unknown provenance | ADR-0004 |
| Add a paid runtime dependency | The runtime must stay free | ADR-0003 |
| Create or switch to any branch other than `master` | Work gets stranded and histories diverge | ADR-0005 |
| Let optimisation relax an absolute risk ceiling | It will, and it will not stop | ADR-0008 |
| Claim a prediction is guaranteed or certain | It is not, and saying so corrupts every downstream decision | ADR-0007 |
| Assume one universal Binance test environment | Coverage genuinely differs per product | ADR-0006 |
| Treat a timeout or 5XX as proof an order failed | Binance documents the state as unknown | ADR-0006 |

---

## 6. Implementation standards

- **Write tests with new behaviour.** Not afterwards, not "in a later phase".
  See [`docs/TESTING_STRATEGY.md`](docs/TESTING_STRATEGY.md).
- **Keep documentation synchronized.** A phase whose documentation contradicts
  its code is incomplete (ADR-0010).
- **Match the surrounding code.** Follow existing naming, structure, typing and
  docstring conventions rather than importing your own.
- **Type everything.** `mypy` runs in strict mode and must pass.
- **Prefer explicit over clever.** This system handles money and will be read by
  contributors with no context.

---

## 7. Verification and delivery

Run the full local gate before committing:

```bash
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

It delegates to `python -m tools.quality full`, which runs `ruff check`,
`ruff format --check`, `mypy`, and then the whole suite under branch coverage
against its floor. All must pass. Because a master-only workflow has no review
gate, this script is the gate.

The steps are defined in `tools/quality/commands.py` and nowhere else, so the
sentence above describes what that table currently contains rather than
duplicating it. Note that `mypy` is invoked without `--strict`: ADR-0018
replaced the alias with the flags it stands for, so that upgrading mypy cannot
silently change what this repository's type contract means.

Then follow [`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md) exactly:

1. Verify (above).
2. Stage, then inspect the staged diff for secrets and generated files.
3. Commit to `master` with a message naming the phase.
4. Push to `origin/master`.
5. Confirm local and remote point at the same commit.
6. Confirm `git status --porcelain` is empty.
7. Look at the continuous integration run for that commit and report its
   conclusion.

**Every completed phase ends pushed, clean, and with its CI result read.** If a
push fails for external reasons such as authentication, report it as an
unresolved blocker rather than describing the phase as complete. The same applies
to step 7: a CI run that could not be reached is reported as unread, never
omitted. The local gate and a hosted runner are different machines, and Phase 004
was already reported once before its run existed.

The full criteria — scope, tests, documentation, diff review, delivery and
reporting — are
[`docs/engineering/DEFINITION_OF_DONE.md`](docs/engineering/DEFINITION_OF_DONE.md).
Work through it before claiming a phase is finished; the steps above are only
its delivery portion.

### Standing authorization

The owner has **pre-authorized commit and push at the end of every phase**. Do
not pause to ask for permission: when the verification gate passes and the
staged diff is clean, commit and push.

This authorization covers the delivery step only. It is not permission to skip
verification, to push work you have not validated, or to proceed past a genuine
blocker. If a check fails, if the staged diff contains something that should not
be committed, or if the phase is incomplete, stop and report — the standing
authorization assumes everything is in order, so establishing that it *is* in
order remains your responsibility.

---

## 8. Reporting

When you finish, report evidence, not assurances:

- The exact commands you ran and their outcomes.
- The commit hash and whether the push succeeded.
- What you deliberately did not do, and why.
- Anything you could not verify.

"Tests pass" is not a report. The command and its result is.

---

## 9. Relationship to other documents

This file and the active phase specification define the rules for all agents.
[`CLAUDE.md`](CLAUDE.md) is a convenience layer for one family of tools and is
**not** an alternate source of truth; where it appears to disagree with this
file, this file wins and the discrepancy is a bug to fix.

For conflicts between any two artefacts in the repository — including code
against documentation — the precedence order is
[`docs/engineering/SOURCE_OF_TRUTH.md`](docs/engineering/SOURCE_OF_TRUTH.md).
It resolves what to believe *while you fix the contradiction*; it never licenses
leaving one in place.
