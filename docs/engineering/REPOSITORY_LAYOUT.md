# Repository Layout

Where things live, and the rule that decides where a new thing goes.

The purpose is to make placement a lookup rather than a judgement call. Over 320
phases, "wherever seemed reasonable at the time" produces a tree nobody can
navigate and duplicate homes for the same kind of file.

---

## The tree

As of Phase 002. Every directory listed here holds real content.

```text
GLOBIN/
├── .editorconfig               Editor settings, aligned with ruff and .gitattributes
├── .gitattributes              Line-ending normalisation; LF in the repository
├── .gitignore                  Secrets, generated artefacts, local state
├── .github/
│   ├── ISSUE_TEMPLATE/         Bug report and engineering task templates
│   └── pull_request_template.md
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
│   ├── engineering/            Process contracts — how work is done
│   └── research/               Per-phase source ledgers
├── scripts/
│   └── verify.ps1              The single verification gate
├── src/
│   └── globin/                 The Python package
└── tests/                      Contract tests
```

---

## Placement rules

| Path | Holds | Does not hold |
|---|---|---|
| `src/globin/` | All production Python | Tests, scripts, generated code |
| `tests/` | All automated tests and their fixtures | Production code, test *data* of meaningful size |
| `docs/` | Project-level documentation: what GLOBIN is and why | Process rules, decision records |
| `docs/adr/` | One decision per file, numbered, immutable once Accepted | Ongoing reasoning that is not a decision |
| `docs/engineering/` | Process contracts: how work is done | Domain reasoning, decisions |
| `docs/research/` | One source ledger per phase, `phase_NNN_sources.md` | Copied vendor documentation |
| `scripts/` | Maintenance and development helpers that genuinely earn their place | Anything importable by the package |
| `.github/` | Repository templates | Configuration that belongs in `pyproject.toml` |

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

There is one machine-readable configuration file. `pytest`, `ruff`, `mypy` and
`coverage` are all configured there and nowhere else. Do not add `setup.cfg`,
`tox.ini`, `.flake8`, `mypy.ini`, `pytest.ini` or a second table for a tool that
already has one — see [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md).

`config/` is reserved for non-secret runtime configuration when a later phase
genuinely needs it. **Phase 007** owns the configuration model. Creating the
directory before then would be premature.

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
