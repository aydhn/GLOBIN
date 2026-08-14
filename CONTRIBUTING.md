# Contributing to GLOBIN

For people. Automated contributors should read [`AGENTS.md`](AGENTS.md), which
is binding.

## Before you start

Read, in order:

1. [`README.md`](README.md) — what actually exists today
2. [`ROADMAP.md`](ROADMAP.md) — the current phase
3. [`docs/PROJECT_CHARTER.md`](docs/PROJECT_CHARTER.md) — scope and non-goals
4. [`docs/engineering/ENGINEERING_CONTRACT.md`](docs/engineering/ENGINEERING_CONTRACT.md) — what all code must satisfy
5. [`docs/ARCHITECTURE_PRINCIPLES.md`](docs/ARCHITECTURE_PRINCIPLES.md) — why things are the way they are
6. Any [ADR](docs/adr/README.md) touching your area

The single most common mistake in this repository is implementing something
from a later phase. Check the roadmap first.

If two documents appear to disagree, the precedence order is
[`docs/engineering/SOURCE_OF_TRUTH.md`](docs/engineering/SOURCE_OF_TRUTH.md) —
and the disagreement is a defect worth fixing, not just working around.

## Environment

Python 3.12 or later. The floor is evidence-based rather than arbitrary: XGBoost,
scheduled for Phase 182, requires 3.12 while the rest of the planned stack
requires 3.10. Choosing the strictest known constraint now avoids a breaking
change later. See `docs/research/phase_001_sources.md`.

The development toolchain is `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `mypy`
and `pre-commit`, declared
under the `dev` extra in `pyproject.toml`. All six are free and open source, as
required by [ADR-0003](docs/adr/0003-zero-budget-open-source-dependency-policy.md).

Tests import the package straight from `src/` because `pythonpath = ["src"]` is
configured, so **no build or install step is required** to work on the project.

Formal virtual environment and dependency locking are the subject of Phases
17-32 and are deliberately not solved yet.

## The verification gate

```bash
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

This runs, in order and failing fast:

| Check | Command |
|---|---|
| Lint | `python -m ruff check .` |
| Formatting | `python -m ruff format --check .` |
| Strict typing | `python -m mypy src/globin tests tools` |
| Tests and branch coverage | `python -m pytest -q --cov=globin --cov=tools --cov-branch` |
| Working tree | `git status --porcelain` |

The first four are not listed here as a second source of truth: `verify.ps1`
delegates to `python -m tools.quality full`, which reads the command table in
`tools/quality/commands.py`. That table is the definition, and the pre-commit
hook and CI read it too. The rows above say what the table currently contains.

**Run it before staging, not after committing.** GLOBIN uses a master-only
workflow with no pull request and no reviewer, so this script is the only gate
between a change and the repository.

To iterate on one check, run it directly:

```bash
python -m pytest -q
```

```bash
python -m ruff check . --fix
```

## Code standards

- **Type everything.** `mypy` runs in strict mode.
- **Line length 100**, enforced by `ruff format`.
- **Absolute imports only.** Relative imports are banned by lint configuration.
- **Match the surrounding code.** Follow the existing naming, structure and
  docstring conventions rather than introducing your own.
- **Explain the non-obvious in docstrings**, especially *why* a design is the way
  it is. Do not narrate what the code plainly says.
- **Prefer explicit over clever.** This system handles money and is read by
  contributors with no prior context.

## Tests

Write tests with the behaviour, not afterwards.

Test invariants rather than appearances. Never snapshot a whole document or
formatted report: a test that fails on every editorial improvement teaches people
to update expectations without reading them, which quietly destroys the value of
every other assertion nearby.

Full reasoning in [`docs/TESTING_STRATEGY.md`](docs/TESTING_STRATEGY.md).

## Documentation

Documentation is part of the change, not follow-up work. A phase whose
documentation contradicts its code is incomplete
([ADR-0010](docs/adr/0010-living-documentation-responsibilities.md)).

Document types, ownership, review cadence and writing conventions — including
the house spelling and the 100-column wrap — are in
[`docs/engineering/DOCUMENTATION_STANDARD.md`](docs/engineering/DOCUMENTATION_STANDARD.md).
Where a new file belongs is in
[`docs/engineering/REPOSITORY_LAYOUT.md`](docs/engineering/REPOSITORY_LAYOUT.md).

If you make a decision with lasting consequence, write an ADR from
[`docs/adr/TEMPLATE.md`](docs/adr/TEMPLATE.md). Accepted ADRs are immutable — a
changed decision becomes a *new* ADR superseding the old one, so the reasoning
history survives.

If you rely on external behaviour, record the source in
`docs/research/phase_NNN_sources.md` with its canonical location, access date and
authority. Never guess an endpoint, parameter or library signature.

If something is not yet verified, say so and name the phase that must verify it.
Silence must not look like confirmation.

## Git

All work happens on `master`. There is no other branch.

```bash
git status --short --branch
```

```bash
git add -A
```

```bash
git diff --cached --stat
```

Inspect the staged content for credentials, tokens, keys, caches and build
output before committing. `.gitignore` is a safety net, not a substitute for
looking.

```bash
git commit -m "phase N: what this phase established"
```

```bash
git push origin master
```

Then confirm `git rev-parse HEAD` and `git rev-parse origin/master` match, and
that `git status --porcelain` is empty. Full procedure and the definition of a
completed phase are in [`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md).

## Things that are never acceptable

- Committing credentials, API keys, tokens or private keys.
- Scraping Binance or calling undocumented private endpoints.
- Adding a paid runtime dependency.
- Reporting a check as passing without having run it.
- Deleting working functionality to make a task simpler.
- Claiming any prediction is guaranteed.
- Implementing a later phase early.

## Reporting your work

Report evidence rather than assurance: the exact commands you ran, their
results, the commit hash, whether the push succeeded, and anything you could not
verify or deliberately left out.

## Before you call it done

Work through
[`docs/engineering/DEFINITION_OF_DONE.md`](docs/engineering/DEFINITION_OF_DONE.md).
It is the canonical checklist and the only copy — scope, tests, documentation,
the gate, the diff review, delivery and reporting.
