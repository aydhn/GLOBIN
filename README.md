# GLOBIN

A locally hosted, autonomous cryptocurrency research and trading system for
Binance Global, built over a fixed programme of 320 phases.

---

## Current status: Phase 031 of 320 complete — foundation only

> **GLOBIN does not trade. Live trading is not implemented.**
>
> There is no exchange connection, no authentication, no market data, no
> strategy, no backtesting and no machine learning in this repository. There are
> no credentials, and no code capable of using any.
>
> This is deliberate. The opening phases build the engineering foundation: the
> rules every later phase must follow, the documentation that carries them, and
> the tests that enforce them.

### What exists right now

Every implemented row links to the thing that proves it. That is not decoration:
`tests/contract/test_documentation_contract.py` requires the link, and
`tests/contract/test_repository_contract.py` requires it to resolve, so a
capability cannot be claimed here without pointing at something real.

| Component | State |
|---|---|
| Repository, branch policy, engineering contract — [`ENGINEERING_CONTRACT.md`](docs/engineering/ENGINEERING_CONTRACT.md) | Implemented |
| 320-phase roadmap, every phase named — [`ROADMAP.md`](ROADMAP.md) | Implemented |
| Architecture decision records (83) — [`docs/adr/`](docs/adr/README.md) | Implemented |
| Research source ledgers with primary sources — [`docs/research/`](docs/research/phase_001_sources.md) | Implemented |
| UTC-only internal time: an injected clock, aware instants, milliseconds as a floored projection — [`TIME_POLICY.md`](docs/TIME_POLICY.md) | Implemented |
| Exact decimal arithmetic, four rounding modes, tick and step alignment — [`PRECISION_POLICY.md`](docs/PRECISION_POLICY.md) | Implemented |
| Canonical identifiers: one registered form per kind, and no register of instances in the domain — [`IDENTIFIER_POLICY.md`](docs/IDENTIFIER_POLICY.md) | Implemented |
| Deterministic multi-process test execution, sharded by a stable digest — [`tools/quality/execution/`](tools/quality/execution/__init__.py) | Implemented |
| Machine-readable evidence for every gate: JUnit XML, coverage in four forms, lint and typing findings, a digested manifest and checksums — [`tools/quality/evidence/`](tools/quality/evidence/__init__.py) | Implemented |
| Engineering contracts: done-criteria, authority order, layout, doc standard — [`DEFINITION_OF_DONE.md`](docs/engineering/DEFINITION_OF_DONE.md) | Implemented |
| Change templates for pull requests and issues — [`pull_request_template.md`](.github/pull_request_template.md) | Implemented |
| Architecture: five layers, inward dependency contract, C4 system and container views — [`docs/architecture/`](docs/architecture/README.md) | Implemented |
| `globin` package — project contract constants and the architecture review — [`src/globin/`](src/globin/__init__.py) | Implemented |
| Contract test suite and verification gate — [`verify.ps1`](scripts/verify.ps1) | Implemented |
| Test taxonomy, quality gates, pre-commit hooks and CI — [`TESTING_STRATEGY.md`](docs/TESTING_STRATEGY.md) | Implemented |
| Error taxonomy: one root, five categories by who must act — [`errors.py`](src/globin/errors.py) | Implemented |
| Property-based testing, enforced offline tests, process isolation — [`tests/conftest.py`](tests/conftest.py) | Implemented |
| Structured logging: correlation-aware records that redact secrets by construction — [`LOGGING_POLICY.md`](docs/LOGGING_POLICY.md) | Implemented |
| Typed configuration model: declared defaults, layered overrides, unknown settings refused — [`CONFIGURATION_POLICY.md`](docs/CONFIGURATION_POLICY.md) | Implemented |
| Denominated value types: a price knows its market, a quantity knows its asset, and neither can be a float — [`VALUE_TYPES_POLICY.md`](docs/VALUE_TYPES_POLICY.md) | Implemented |
| Mutation testing over the pure core, gated by a committed survivor set — [`mutation-baseline.toml`](docs/engineering/mutation-baseline.toml) | Implemented |
| Single-source versioning, release policy and a deterministic release gate — [`RELEASE_POLICY.md`](docs/release/RELEASE_POLICY.md) | Implemented |
| Phase 001-016 foundation acceptance, in prose and machine-readable form — [`FOUNDATION_ACCEPTANCE.md`](docs/release/FOUNDATION_ACCEPTANCE.md) | Implemented |
| A hash-pinned dependency lock the environment is built from, with every claim in it recomputed — [`DEPENDENCY_LOCKING.md`](docs/engineering/DEPENDENCY_LOCKING.md) | Implemented |
| The numerical and dataframe stack verified by measurement rather than by importing it, and deliberately not adopted — [`SCIENTIFIC_STACK.md`](docs/engineering/SCIENTIFIC_STACK.md) | Implemented |
| A user-local runtime tree, atomically published state, one coordinator per machine and an ordered shutdown — [`RUNTIME_FILESYSTEM.md`](docs/engineering/RUNTIME_FILESYSTEM.md) | Implemented |
| GPU presence, driver, compute capability and CUDA runtime recorded as states rather than assumed — [`GPU_CAPABILITY.md`](docs/engineering/GPU_CAPABILITY.md) | Implemented |
| Which workloads actually benefit from GPU execution here, measured against a declared method and threshold — [`GPU_BENEFIT.md`](docs/engineering/GPU_BENEFIT.md) | Implemented |
| A typed runtime health snapshot where a measurement that was not taken is never zero — [`RUNTIME_HEALTH.md`](docs/engineering/RUNTIME_HEALTH.md) | Implemented |
| Redacted, allowlist-first support bundles that validate against their own SHA-256 manifest before they are published — [`SUPPORT_BUNDLE.md`](docs/engineering/SUPPORT_BUNDLE.md) | Implemented |
| A liveness watchdog: monotonic heartbeats, a suspect threshold distinct from a confirmed stall, bounded redacted stall evidence and a bounded escalation to a hard exit — [`RUNTIME_WATCHDOG.md`](docs/engineering/RUNTIME_WATCHDOG.md) | Implemented |
| The native TA-Lib C library provisioned and proved present on this host rather than read off a wheel filename — [`SCIENTIFIC_STACK.md`](docs/engineering/SCIENTIFIC_STACK.md) | Implemented |
| A local secret store on the Windows Credential Manager, where a value has no string form, no encoder and no way to reach a terminal — [`SECRET_STORE.md`](docs/security/SECRET_STORE.md) | Implemented |
| A user-scoped DPAPI vault for key material the store's 2560-byte ceiling refuses, admitted by arithmetic and carrying its own integrity check — [`SECRET_VAULT.md`](docs/security/SECRET_VAULT.md) | Implemented |
| Degraded operation: a necessity per component, a posture folded from what each factory returned, and a network declared rather than probed — [`DEGRADED_OPERATION.md`](docs/engineering/DEGRADED_OPERATION.md) | Implemented |
| An environment capability inventory separating native from process architecture, with a fingerprint that excludes everything volatile — [`ENVIRONMENT_CAPABILITY.md`](docs/engineering/ENVIRONMENT_CAPABILITY.md) | Implemented |
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

```text
GLOBIN/
├── README.md              This file
├── AGENTS.md              Binding instruction contract for coding agents
├── CLAUDE.md              Agent-specific convenience layer
├── MEMORY.md              Durable project memory
├── ROADMAP.md             The fixed 320-phase programme
├── CONTRIBUTING.md        How to work in this repository
├── pyproject.toml         Project metadata and tool configuration
├── pylock.dev.toml        The development toolchain, resolved and hash-pinned
├── .github/               Pull request and issue templates
├── docs/
│   ├── PROJECT_CHARTER.md        Mission, scope, non-goals
│   ├── ARCHITECTURE_PRINCIPLES.md Durable technical reasoning
│   ├── SOURCE_POLICY.md          Which sources may be trusted
│   ├── TESTING_STRATEGY.md       What is tested and why
│   ├── GIT_WORKFLOW.md           Branch, commit and push procedure
│   ├── GLOSSARY.md               Shared vocabulary
│   ├── architecture/             System views and the dependency contract
│   ├── engineering/              How work is done: contracts and standards
│   ├── adr/                      Architecture Decision Records
│   └── research/                 Per-phase source ledgers
├── scripts/verify.ps1     The single verification gate
├── src/globin/            The Python package, in five architectural layers
├── tests/                 The suite, one directory per taxonomy level
└── tools/quality/         The canonical quality entrypoint
```

Placement rules are in
[`docs/engineering/REPOSITORY_LAYOUT.md`](docs/engineering/REPOSITORY_LAYOUT.md).

---

## Running the checks

Requires Windows and a CPython the runtime contract accepts; the values are in
[`docs/engineering/runtime-contract.toml`](docs/engineering/runtime-contract.toml)
and the reasoning is in
[`docs/engineering/RUNTIME_BASELINE.md`](docs/engineering/RUNTIME_BASELINE.md).
Build the project environment once:

```bash
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

Then run the gate. It uses `.venv` and refuses to run without one, so which
interpreter measured a result is a recorded fact rather than whatever `PATH`
resolved:

```bash
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

To diagnose a host without changing anything:

```bash
powershell -ExecutionPolicy Bypass -File scripts/preflight.ps1
```

This runs lint, format verification, strict type checking and the test suite
with branch coverage, then reports working-tree state. Tests read the package
directly from `src/`, so no build or install step is needed.

The same checks, invoked directly — this is what continuous integration runs:

```bash
python -m tools.quality full
```

For a faster inner loop:

```bash
python -m tools.quality fast
```

Which checks are mandatory, what a failure means and what is deliberately
deferred are in
[`QUALITY_GATES.md`](docs/engineering/QUALITY_GATES.md).

---

## Documentation map

Start with [`AGENTS.md`](AGENTS.md) if you are an automated contributor, or
[`CONTRIBUTING.md`](CONTRIBUTING.md) if you are a person. Both point onward to
the charter, principles and decision records.

| Question | Document |
|---|---|
| How is the system structured? | [`docs/architecture/README.md`](docs/architecture/README.md) |
| Which layer may import which? | [`dependency-rules.toml`](docs/architecture/dependency-rules.toml) |
| What must all code satisfy? | [`ENGINEERING_CONTRACT.md`](docs/engineering/ENGINEERING_CONTRACT.md) |
| When is a change finished? | [`DEFINITION_OF_DONE.md`](docs/engineering/DEFINITION_OF_DONE.md) |
| Which document wins a conflict? | [`SOURCE_OF_TRUTH.md`](docs/engineering/SOURCE_OF_TRUTH.md) |
| Where does a new file go? | [`REPOSITORY_LAYOUT.md`](docs/engineering/REPOSITORY_LAYOUT.md) |
| How is documentation written? | [`DOCUMENTATION_STANDARD.md`](docs/engineering/DOCUMENTATION_STANDARD.md) |
| Which checks must pass? | [`QUALITY_GATES.md`](docs/engineering/QUALITY_GATES.md) |
| Why these lint and type rules? | [`STATIC_ANALYSIS.md`](docs/engineering/STATIC_ANALYSIS.md) |
| Where does a new test go? | [`TESTING_STRATEGY.md`](docs/TESTING_STRATEGY.md) |
| How is a version chosen and a release cut? | [`RELEASE_POLICY.md`](docs/release/RELEASE_POLICY.md) |
| What changed between versions? | [`CHANGELOG.md`](CHANGELOG.md) |
| Is the foundation band complete, and by what evidence? | [`FOUNDATION_ACCEPTANCE.md`](docs/release/FOUNDATION_ACCEPTANCE.md) |

This file is orientation only. It links to policy rather than restating it, so
that a rule has exactly one home — see
[ADR-0011](docs/adr/0011-documentation-authority-hierarchy.md).

---

## Licence

No licence has been selected. All rights are reserved by the owner. A licence
will be added only if and when the owner chooses one — this project does not
invent legal decisions on the owner's behalf.
