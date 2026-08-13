# GLOBIN

A locally hosted, autonomous cryptocurrency research and trading system for
Binance Global, built over a fixed programme of 320 phases.

---

## Current status: Phase 001 of 320 — foundation only

> **GLOBIN does not trade. Live trading is not implemented.**
>
> There is no exchange connection, no authentication, no market data, no
> strategy, no backtesting and no machine learning in this repository. There are
> no credentials, and no code capable of using any.
>
> This is deliberate. Phase 1 builds the engineering foundation: the rules every
> later phase must follow, the documentation that carries them, and the tests
> that enforce them.

### What exists right now

| Component | State |
|---|---|
| Repository, branch policy, engineering contract | Implemented |
| 320-phase roadmap, every phase named | Implemented |
| Architecture decision records (10) | Implemented |
| Research source ledger with primary sources | Implemented |
| `globin` package — project contract constants only | Implemented |
| Contract test suite and verification gate | Implemented |
| Everything else | Not started |

### What does not exist

Binance API integration, request signing, credential handling, WebSocket
clients, market data ingestion, order books, an execution engine, backtesting,
technical indicators, strategies, machine learning, reinforcement learning,
optimisation, portfolio and risk management, the Telegram interface, the
orchestrator, and the `start_windows_paper.bat` / `start_windows_live.bat`
launchers.

Their contracts are documented. Their implementations belong to later phases and
have not been written.

---

## What GLOBIN is intended to become

A system that runs unattended on one Windows machine and, within governed
limits, collects market data, researches strategies, validates them honestly,
trains and re-trains models, optimises parameters, manages portfolio risk, and
executes trades on Binance Global — reporting to its operator through Telegram
and progressing to live capital only after passing defined evidence gates.

Its objective is a **measurable probabilistic edge after realistic costs and
out-of-sample validation**. Not certainty. No component of this system will ever
claim to guarantee a profitable prediction.

---

## Core rules

These are non-negotiable and are enforced by tests, not just documented.

| Rule | Meaning |
|---|---|
| **Binance Global only** | One venue. No multi-exchange abstraction. |
| **Zero budget** | The runtime depends only on free and open components. No paid APIs, data, databases, monitoring or cloud compute. |
| **Official interfaces only** | No scraping, no browser automation, no undocumented private endpoints. |
| **`master` only** | All development happens on `master`, pushed after every completed phase. |
| **Bounded autonomy** | The system may adapt, but may never raise its own absolute risk ceilings. |
| **Evidence over assertion** | Claims about external behaviour cite primary sources with access dates. |

---

## Non-goals

Multi-exchange support; high-frequency or latency-arbitrage trading; cloud or
distributed deployment; any paid runtime dependency; scraping; guaranteed
returns; a general-purpose framework for other users; unsupervised capital
escalation.

See [`docs/PROJECT_CHARTER.md`](docs/PROJECT_CHARTER.md) for the reasoning.

---

## Development approach

The programme is twenty immutable bands of sixteen phases each — from repository
foundation, through exchange integration, data, research, learning and risk, to
staged live activation. Phases are implemented **in order**; building ahead is
treated as a defect because it bypasses the design work the later phase exists to
do.

Every phase ends the same way: tests pass, documentation matches the code, a
commit lands on `master`, it is pushed to `origin/master`, and the working tree
is clean.

Full index: [`ROADMAP.md`](ROADMAP.md).

---

## Repository structure

```
GLOBIN/
├── README.md              This file
├── AGENTS.md              Binding instruction contract for coding agents
├── CLAUDE.md              Agent-specific convenience layer
├── MEMORY.md              Durable project memory
├── ROADMAP.md             The fixed 320-phase programme
├── CONTRIBUTING.md        How to work in this repository
├── pyproject.toml         Project metadata and tool configuration
├── docs/
│   ├── PROJECT_CHARTER.md        Mission, scope, non-goals
│   ├── ARCHITECTURE_PRINCIPLES.md Durable technical reasoning
│   ├── SOURCE_POLICY.md          Which sources may be trusted
│   ├── TESTING_STRATEGY.md       What is tested and why
│   ├── GIT_WORKFLOW.md           Branch, commit and push procedure
│   ├── GLOSSARY.md               Shared vocabulary
│   ├── adr/                      Architecture Decision Records
│   └── research/                 Per-phase source ledgers
├── scripts/verify.ps1     The single verification gate
├── src/globin/            The Python package
└── tests/                 Contract tests
```

---

## Running the checks

Requires Python 3.12 or later. The development toolchain is `pytest`,
`pytest-cov`, `ruff` and `mypy`.

```bash
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

This runs the import check, the test suite, lint, format verification and strict
type checking. Tests read the package directly from `src/`, so no build or
install step is needed.

---

## Documentation map

Start with [`AGENTS.md`](AGENTS.md) if you are an automated contributor, or
[`CONTRIBUTING.md`](CONTRIBUTING.md) if you are a person. Both point onward to
the charter, principles and decision records.

---

## Licence

No licence has been selected. All rights are reserved by the owner. A licence
will be added only if and when the owner chooses one — this project does not
invent legal decisions on the owner's behalf.
