# Repository Layout

Where things live, and the rule that decides where a new thing goes.

The purpose is to make placement a lookup rather than a judgement call. Over 320
phases, "wherever seemed reasonable at the time" produces a tree nobody can
navigate and duplicate homes for the same kind of file.

---

## The tree

As of Phase 003. Every directory listed here holds real content.

```text
GLOBIN/
├── .editorconfig               Editor settings, aligned with ruff and .gitattributes
├── .gitattributes              Line-ending normalisation; LF in the repository
├── .gitignore                  Secrets, generated artefacts, local state
├── .github/
│   ├── ISSUE_TEMPLATE/         Bug report and engineering task templates
│   ├── pull_request_template.md
│   └── workflows/              Continuous integration; verification only
├── .pre-commit-config.yaml     The fast local hook gate
├── AGENTS.md                   Binding instruction contract for coding agents
├── CLAUDE.md                   Convenience layer for one agent family
├── CONTRIBUTING.md             How a person makes a change
├── MEMORY.md                   Durable project memory
├── README.md                   What exists today
├── ROADMAP.md                  The fixed 320-phase programme
├── pyproject.toml              Packaging metadata and all tool configuration
├── docs/
│   ├── PROJECT_CHARTER.md      Mission, scope, non-goals
│   ├── ARCHITECTURE_PRINCIPLES.md
│   ├── SOURCE_POLICY.md
│   ├── TESTING_STRATEGY.md
│   ├── GIT_WORKFLOW.md
│   ├── GLOSSARY.md
│   ├── adr/                    Architecture Decision Records + TEMPLATE.md
│   ├── architecture/           System views and the dependency contract
│   ├── engineering/            Process contracts, and the mutation baseline
│   └── research/               Per-phase source ledgers
├── scripts/
│   └── verify.ps1              The single verification gate
├── src/
│   └── globin/                 The Python package
│       ├── errors.py           The error taxonomy; above the layer stack
│       ├── domain/             Pure concepts, values and rules
│       ├── ports/              Abstract contracts for the outside world
│       ├── application/        Use cases coordinating domain through ports
│       ├── adapters/           Concrete implementations of ports
│       └── runtime/            Composition root
├── tests/                      The suite, one directory per taxonomy level
│   ├── support.py              Importable helpers; conftest.py holds fixtures
│   ├── smoke/                  Fastest signal that the tree is not broken
│   ├── contract/               Project rules asserted executably
│   ├── architecture/           The layer contract against the real import graph
│   ├── unit/                   One unit, dependencies substituted
│   ├── property/               Invariants over generated input
│   └── integration/            Several components together, still local
└── tools/                      Development tooling that acts on the repository
    └── quality/                The canonical quality entrypoint
```

The five packages under `src/globin/` are architectural layers, and which of
them may import which is fixed by
[`../architecture/dependency-rules.toml`](../architecture/dependency-rules.toml)
rather than by convention. Placing a new module is therefore a lookup too: see
[`../architecture/README.md`](../architecture/README.md) for the layer
responsibilities and the test that enforces them.

---

## Placement rules

| Path | Holds | Does not hold |
|---|---|---|
| `src/globin/` | All production Python | Tests, scripts, generated code |
| `src/globin/<layer>/` | Only what that layer's responsibility permits | Anything an outer layer owns; see the dependency contract |
| `tests/` | All automated tests and their fixtures, one directory per taxonomy level | Production code, test *data* of meaningful size, a test outside a level directory |
| `docs/` | Project-level documentation: what GLOBIN is and why | Process rules, decision records |
| `docs/adr/` | One decision per file, numbered, immutable once Accepted or Rejected | Ongoing reasoning that is not a decision |
| `docs/architecture/` | System views and the machine-readable dependency contract | Decisions and their rationale, which belong in `docs/adr/` |
| `docs/engineering/` | Process contracts: how work is done, and the measured evidence a gate compares against | Domain reasoning, decisions |
| `docs/research/` | One source ledger per phase, `phase_NNN_sources.md` | Copied vendor documentation |
| `docs/security/` | The secret-handling rules, the vulnerability response runbook and the ownership model | The reporter-facing policy, which GitHub requires at `SECURITY.md` in the root |
| `docs/release/` | How a version is chosen and a release cut, and what a phase band's completion rests on | The changelog, which convention puts at `CHANGELOG.md` in the root, and the machine-readable acceptance matrix, which lives with the other declarations in `docs/engineering/` |
| `scripts/` | Host-specific entry points that must not be importable — currently the PowerShell gate | Logic worth testing; that belongs in `tools/` |
| `tools/` | Importable, typed, tested development tooling that acts on the repository | Anything the application imports, or that ships in a distribution |
| `.github/` | Repository templates | Configuration that belongs in `pyproject.toml` |

### The `scripts/` and `tools/` split

Both hold things that act on the repository rather than being part of the
product, so the boundary needs stating.

- `tools/` is **importable Python**: typed, unit-tested, and type-checked by the
  same gate as everything else. `tools/quality` decides whether a check passed,
  which is exactly the kind of logic that must not be untestable.
- `scripts/` is **host-specific glue that cannot be imported**: today one
  PowerShell file that resolves the repository root, invokes the gate and
  inspects the working tree. It is thin on purpose.

The test: if it contains a decision worth getting wrong, it belongs in `tools/`
where a test can pin it. If it only exists because the host needs a particular
kind of file to start from, it belongs in `scripts/`.

Neither is `src/globin/`. That holds the application, ships in a distribution,
and is bound by the layer contract — which forbids the inner layers from
importing `subprocess` at all.

### The `docs/` and `docs/engineering/` split

This is the distinction people get wrong, so it is worth stating plainly.

- `docs/` answers **"what is this system and why is it like this?"** — charter,
  architecture principles, source policy, glossary, testing strategy.
- `docs/engineering/` answers **"how do I work on it?"** — the engineering
  contract, the definition of done, the source-of-truth order, documentation
  conventions, and this file.

A useful test: if the document would still be needed by someone who had already
finished all the work and only wanted to understand the system, it belongs in
`docs/`. If it only matters while work is being done, it belongs in
`docs/engineering/`.

### Configuration lives in `pyproject.toml`

There is one machine-readable **configuration** file. `pytest`, `ruff`, `mypy`,
`coverage` and the mutation gate are all configured there and nowhere else. Do
not add `setup.cfg`, `tox.ini`, `.flake8`, `mypy.ini`, `pytest.ini` or a second
table for a tool that already has one — see
[`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md).

Two other `.toml` files exist and neither is configuration, which is the
distinction to hold on to. `docs/architecture/dependency-rules.toml` is a
**contract**: it states what is permitted, and the suite reads it. Since Phase
008, `docs/engineering/mutation-baseline.toml` is **evidence**: it records what
was measured and why each exception was accepted. Settings say how a tool should
behave; a contract says what the code must satisfy; evidence says what was found.
A file that is not the first belongs beside the document explaining it, not in
`pyproject.toml`.

`config/` is reserved for non-secret runtime configuration when a later phase
genuinely needs it. Phase 007 delivered the configuration *model* — see
[`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — and deliberately did
not create the directory: a source is handed a path and never searches for one,
so where configuration files live is still **Phase 026**'s question to answer.

---

## Directories appear when they hold content

There is deliberately no scaffolding for future components — no empty
`src/globin/exchange/`, no placeholder `data/` with a `.gitkeep`.

An empty directory named after a future capability is a claim that the
capability is being worked on. It is not, and 318 such claims would make the
tree unreadable and the roadmap unfalsifiable. `ROADMAP.md` states what is
planned. The tree states what exists. Keeping those two jobs separate is what
lets [`README.md`](../../README.md) be honest about maturity.

Create a directory in the phase that puts real content in it.

---

## Runtime output is never committed

`data/`, `datasets/`, `logs/`, `models/`, `artifacts/`, `checkpoints/`, `runs/`,
`mlruns/`, `optuna_studies/`, `backtest_results/`, `reports/` and `backups/` are
already listed in `.gitignore` even though none of them exist yet.

That ordering is intentional. The ignore rule must exist **before** the first
byte of runtime output is written, because the failure mode — a multi-gigabyte
model binary or a log containing account data committed by accident — is
permanent in Git history and cannot be undone by a later fix.

These paths are local state, never source. Anything under them must be
regenerable from committed code plus recorded inputs
([`ENGINEERING_CONTRACT.md`](ENGINEERING_CONTRACT.md), invariant 12).

---

## Naming

| Kind | Convention | Example |
|---|---|---|
| Python modules and packages | `lower_snake_case` | `project_contract.py` |
| Test modules | `test_<subject>_contract.py` for contract tests | `test_roadmap_contract.py` |
| ADRs | `NNNN-kebab-case-title.md`, contiguous from `0001` | `0005-master-only-git-workflow.md` |
| Research ledgers | `phase_NNN_sources.md`, zero-padded | `phase_002_sources.md` |
| Documents | `SCREAMING_SNAKE_CASE.md` | `SOURCE_OF_TRUTH.md` |
| Machine-readable contracts | `lower-kebab-case` with the format's extension | `dependency-rules.toml` |

The last row exists because a file that tools parse is not a document. Naming it
like one invites a reader to edit it as prose, and the difference matters: a
document may be improved freely, while a contract file changes what the tests
enforce.

Root-level documents keep their conventional names (`README.md`, `AGENTS.md`,
`CONTRIBUTING.md`) because tools and platforms recognise them.

---

## Moving things

Do not reorganise for aesthetics. A rename shows up in every future `git blame`,
breaks every link that pointed at the old path, and costs review attention that
should have gone to behaviour.

Move a file when its current location is actively misleading, and say why in the
commit message. Phase 002 moved nothing: the Phase 1 layout was already
consistent, and `docs/engineering/` was added alongside it rather than by
rearranging what existed.
