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
| What must all code satisfy? | [`docs/engineering/ENGINEERING_CONTRACT.md`](docs/engineering/ENGINEERING_CONTRACT.md) |
| When am I finished? | [`docs/engineering/DEFINITION_OF_DONE.md`](docs/engineering/DEFINITION_OF_DONE.md) |
| Which document wins a conflict? | [`docs/engineering/SOURCE_OF_TRUTH.md`](docs/engineering/SOURCE_OF_TRUTH.md) |
| Where does this file go? | [`docs/engineering/REPOSITORY_LAYOUT.md`](docs/engineering/REPOSITORY_LAYOUT.md) |
| How do I write documentation? | [`docs/engineering/DOCUMENTATION_STANDARD.md`](docs/engineering/DOCUMENTATION_STANDARD.md) |
| How is the system structured? | [`docs/architecture/README.md`](docs/architecture/README.md) |
| Which layer may import which? | [`docs/architecture/dependency-rules.toml`](docs/architecture/dependency-rules.toml) |
| Why is the architecture like this? | [`docs/ARCHITECTURE_PRINCIPLES.md`](docs/ARCHITECTURE_PRINCIPLES.md) |
| Why was X decided? | [`docs/adr/README.md`](docs/adr/README.md) |
| What sources may I trust? | [`docs/SOURCE_POLICY.md`](docs/SOURCE_POLICY.md) |
| May I add this dependency? | [`docs/DEPENDENCY_POLICY.md`](docs/DEPENDENCY_POLICY.md), [`docs/engineering/dependency-reviews.toml`](docs/engineering/dependency-reviews.toml) |
| How do I test, and where does a test go? | [`docs/TESTING_STRATEGY.md`](docs/TESTING_STRATEGY.md) |
| Which error do I raise? | [`src/globin/errors.py`](src/globin/errors.py), [ADR-0022](docs/adr/0022-error-taxonomy-rooted-in-one-type.md) |
| How do I express a price or a quantity? | [`docs/VALUE_TYPES_POLICY.md`](docs/VALUE_TYPES_POLICY.md) |
| How do I write a value down and read it back? | [`docs/SERIALIZATION_POLICY.md`](docs/SERIALIZATION_POLICY.md) |
| Which checks must pass? | [`docs/engineering/QUALITY_GATES.md`](docs/engineering/QUALITY_GATES.md) |
| Why these lint and type rules? | [`docs/engineering/STATIC_ANALYSIS.md`](docs/engineering/STATIC_ANALYSIS.md) |
| How do I commit? | [`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md) |
| What does this term mean? | [`docs/GLOSSARY.md`](docs/GLOSSARY.md) |

---

## Repository navigation

```text
GLOBIN/
├── src/globin/          Python package, in five architectural layers.
│   ├── project_contract.py   Identity and policy invariants
│   ├── roadmap.py            The 20 immutable phase bands
│   ├── errors.py             The error taxonomy; above the layer stack
│   ├── domain/               Pure concepts, values and rules
│   ├── ports/                Abstract contracts, as typing.Protocol
│   ├── application/          Use cases, coordinating domain through ports
│   ├── adapters/             Concrete implementations; the only I/O
│   └── runtime/              Composition root
├── tests/               The suite; a test's directory decides its marker
│   ├── support.py       Importable helpers (conftest.py holds fixtures only)
│   ├── smoke/           Fastest signal that the tree is not broken
│   ├── contract/        Project rules asserted executably
│   ├── architecture/    The layer contract against the real import graph
│   ├── unit/            One unit, dependencies substituted
│   ├── property/        Invariants over generated input (Hypothesis)
│   └── integration/     Several components together, still local
├── tools/quality/       The canonical quality entrypoint; CI runs this too
│   └── supply/          Dependency inventory, CycloneDX SBOM, audit, secrets
├── docs/
│   ├── architecture/    Layer contract, C4 system context and container views
│   ├── engineering/     How work is done: contracts and standards
│   ├── adr/             Architecture Decision Records + TEMPLATE.md
│   └── research/        Per-phase source ledgers
├── .github/             Templates, and the verification-only CI workflow
└── scripts/verify.ps1   The single verification gate
```

Dependencies point **inward only**: `runtime` → `adapters` → `application` →
`ports` → `domain`. The permitted directions are declared in
[`docs/architecture/dependency-rules.toml`](docs/architecture/dependency-rules.toml)
and enforced by `tests/architecture/test_architecture_contract.py`. Do not add a second copy
of that matrix anywhere.

There is deliberately no scaffolding for future components. Directories appear
when they hold real content. Full placement rules:
[`docs/engineering/REPOSITORY_LAYOUT.md`](docs/engineering/REPOSITORY_LAYOUT.md).

---

## Command discipline

The host is **Windows**. The primary shell is PowerShell; a Bash tool is also
available and takes POSIX syntax. Do not mix the two in one invocation.

The full gate, which is what you must run before committing:

```bash
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

It delegates to the canonical quality command, which is also what CI runs. Every
check is a name in `tools/quality/commands.py`; do not add a check anywhere else.

```bash
python -m tools.quality full
```

Individual checks, when iterating:

```bash
python -m tools.quality fast
```

```bash
python -m pytest -q
```

```bash
python -m tools.quality property
```

```bash
python -m tools.quality lint
```

```bash
python -m tools.quality typecheck
```

Only `fix` and `reformat` modify the tree. Every other command reports and
changes nothing.

One command answers a different question from the rest — not "is this tree good"
but "did this CI run establish that it is". It reads the results of a run's jobs
and the evidence they published, and reduces the two to one verdict. Run locally
it aggregates whatever `evidence` last wrote, using the same evaluator CI uses:

```bash
python -m tools.quality aggregate
```

One more sits outside `full`, and for a reason none of the others has: it
**reaches the network**. `pip-audit` resolves a requirements file against an
index and queries an advisory service, and the capability probe asks GitHub
about repository settings. `full` runs before every commit and must work on an
aeroplane, so this is separate:

```bash
python -m tools.quality supply
```

It reads the three registers that declare a dependency and reports where they
disagree, renders them as a deterministic CycloneDX 1.7 SBOM, audits the
declared toolchain, scans tracked content for credentials, and records what the
platform will and will not do. `--offline` skips both network calls and records
them as unmeasured — which is never a pass, so an offline run cannot exit `0`.
Adding a dependency is a written decision:
[`docs/DEPENDENCY_POLICY.md`](docs/DEPENDENCY_POLICY.md).

Its job in CI is the check named `Quality gate`, which is the one to mark as
required on `master`. Branch protection is a repository setting and no file here
can change it — see
[`docs/engineering/QUALITY_GATES.md`](docs/engineering/QUALITY_GATES.md).

One gate sits outside `full`, because it takes minutes rather than seconds:

```bash
python -m tools.quality mutation
```

It rewrites one module at a time inside a temporary copy of the tree and checks
whether the tests notice, then compares the survivors against
[`docs/engineering/mutation-baseline.toml`](docs/engineering/mutation-baseline.toml).
Nothing writes that file. Read a survivor's recorded argument before changing it
([ADR-0033](docs/adr/0033-mutation-testing-is-a-repository-native-ast-harness.md)).

Tests run against the source tree with no install step, because
`pythonpath = ["src"]` is set in `pyproject.toml`. There is no build in Phase 1.

---

## Test expectations

Write tests alongside behaviour, never afterwards. Test meaningful invariants,
not whole-file snapshots — a test that fails on every editorial improvement
trains people to update expectations without reading them.

The suite exists to make policy enforceable. It asserts project identity, the
master-only branch rule, the 320-phase structure, the absence of runtime
dependencies, the presence and consistency of required documentation, that
every repository-relative Markdown link resolves, that no credential-shaped
file would be committed, and that tool configuration is not duplicated outside
`pyproject.toml`.

Since Phase 5 it also enforces the conditions it runs under. Every test is
offline — an autouse fixture refuses outbound sockets — and every test must leave
the environment and working directory as it found them, or it fails. Use
`monkeypatch.setenv` and `monkeypatch.chdir` rather than changing either
directly. Where a mock is genuinely right, it must be
`create_autospec(..., spec_set=True)`; the default remains a hand-written double
satisfying a `Protocol`. Write a property test when a real invariant exists, not
for every change.

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
