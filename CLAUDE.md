# CLAUDE.md

Convenience layer for Claude-style coding agents working in this repository.

> **This file is not a source of truth.** [`AGENTS.md`](AGENTS.md) and the active
> phase specification define the rules for every agent. This document only
> summarises them and adds tool-specific navigation. If anything here appears to
> contradict `AGENTS.md`, `AGENTS.md` wins and the contradiction is a bug worth
> fixing.

---

## Mission

GLOBIN is a locally hosted, autonomous research and trading system for Binance
Global, built over a fixed 320-phase programme. It runs on one Windows machine,
uses only free components and only officially documented interfaces.

**It does not trade yet.** Check [`ROADMAP.md`](ROADMAP.md) for the current
phase before assuming any capability exists.

---

## Read these first

| Question | Document |
|---|---|
| What are the binding rules? | [`AGENTS.md`](AGENTS.md) |
| What phase are we in? | [`ROADMAP.md`](ROADMAP.md), [`MEMORY.md`](MEMORY.md) |
| What is durable project truth? | [`MEMORY.md`](MEMORY.md) |
| Why is the architecture like this? | [`docs/ARCHITECTURE_PRINCIPLES.md`](docs/ARCHITECTURE_PRINCIPLES.md) |
| Why was X decided? | [`docs/adr/`](docs/adr/) |
| What sources may I trust? | [`docs/SOURCE_POLICY.md`](docs/SOURCE_POLICY.md) |
| How do I test? | [`docs/TESTING_STRATEGY.md`](docs/TESTING_STRATEGY.md) |
| How do I commit? | [`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md) |
| What does this term mean? | [`docs/GLOSSARY.md`](docs/GLOSSARY.md) |

---

## Repository navigation

```
GLOBIN/
├── src/globin/          Python package. Phase 1: project contract only.
│   ├── project_contract.py   Identity and policy invariants
│   └── roadmap.py            The 20 immutable phase bands
├── tests/               Contract tests enforcing the rules
├── docs/
│   ├── adr/             Architecture Decision Records
│   └── research/        Per-phase source ledgers
└── scripts/verify.ps1   The single verification gate
```

There is deliberately no scaffolding for future components. Directories appear
when they hold real content.

---

## Command discipline

The host is **Windows**. The primary shell is PowerShell; a Bash tool is also
available and takes POSIX syntax. Do not mix the two in one invocation.

The full gate, which is what you must run before committing:

```bash
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

Individual checks, when iterating:

```bash
python -m pytest -q
```

```bash
python -m ruff check .
```

```bash
python -m mypy src/globin tests
```

Tests run against the source tree with no install step, because
`pythonpath = ["src"]` is set in `pyproject.toml`. There is no build in Phase 1.

---

## Test expectations

Write tests alongside behaviour, never afterwards. Test meaningful invariants,
not whole-file snapshots — a test that fails on every editorial improvement
trains people to update expectations without reading them.

The Phase 1 suite exists to make policy enforceable: it asserts project
identity, the master-only branch rule, the 320-phase structure, the absence of
runtime dependencies, and the presence and consistency of required
documentation.

---

## Source policy in brief

Never invent an endpoint, parameter, error code or library signature. Consult
current primary documentation and record it in `docs/research/`. Official
Binance documentation is authoritative for Binance; upstream project
documentation is authoritative for libraries.

Scraping Binance, parsing its pages, or calling undocumented private endpoints
is prohibited without exception.

---

## Git in brief

All work happens on `master`. Verify, inspect the staged diff for secrets,
commit with a message naming the phase, push to `origin/master`, then confirm
local and remote match and the tree is clean. Full procedure in
[`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md).

---

## Phase discipline

Implement the current phase. Not the next one.

Premature implementation is a defect, not initiative: it bypasses the design
work that the later phase was created to do, and it produces code that no test
or document yet describes. If you believe a phase boundary is wrong, say so —
but do not resolve it unilaterally by building ahead.

Equally, do not leave the current phase partly done. Finish it, and state
plainly anything you could not complete.

---

## Reporting

Report evidence rather than assurance: the exact commands you ran, their
results, the commit hash, whether the push succeeded, and anything you could not
verify. Never describe a check as passing unless you ran it and saw it pass.
