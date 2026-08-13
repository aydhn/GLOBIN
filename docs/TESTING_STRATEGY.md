# Testing Strategy

## Why testing carries unusual weight here

GLOBIN uses a master-only workflow (ADR-0005), so there is no pull request and
no reviewer standing between a change and the repository. The test suite *is*
the gate.

It also has a second job. Most contributors to this project are agents with no
memory of previous sessions. Prose can be misread or skipped; a failing test
cannot. So wherever a project rule can be expressed executably, it is — this is
principle 10 in [`ARCHITECTURE_PRINCIPLES.md`](ARCHITECTURE_PRINCIPLES.md).

## Test levels

| Level | Scope | Speed | Network |
|---|---|---|---|
| **Contract** | Project invariants: identity, policy, documentation, packaging | Instant | Never |
| **Unit** | One function or class, dependencies substituted | Fast | Never |
| **Integration** | Several components together, still local | Moderate | Never |
| **External** | Real Binance non-production endpoints | Slow | Yes, explicitly opted into |

Phase 1 contains contract tests only, because Phase 1 contains no behaviour.

**No test at the first three levels may touch the network.** External tests
arrive with the API layer (Phases 033-048), must be explicitly marked and
skipped by default, and must never run against production or with live
credentials.

## What Phase 1 tests, and why

| File | Enforces |
|---|---|
| `test_project_contract.py` | Identity is GLOBIN/`globin`; branch is `master`; 320 phases; Binance Global is the only venue; paid runtime services and scraping are prohibited; the contract object is immutable; no trading surface is exposed |
| `test_roadmap_contract.py` | Twenty contiguous 16-phase bands matching the charter; every phase 001-320 present exactly once in ascending order with a unique title and real purpose; no future phase marked complete |
| `test_documentation_contract.py` | Required documents exist, are substantive, open with a heading, state the policies they own, carry no placeholder debt; ADRs are contiguous, well-formed and indexed; the research ledger is properly structured; no branch instruction contradicts master-only |
| `test_packaging_contract.py` | Distribution name matches the package; **runtime dependencies are empty**; the interpreter floor is evidence-based; version is single-sourced; no licence is invented |

The zero-dependency assertion deserves a note. The zero-budget rule (ADR-0003)
is easy to state and easy to erode — one convenient library at a time. Parsing
`pyproject.toml` and asserting the dependency list is empty means the first
runtime dependency cannot be added without also editing a test that says why
that list should stay empty. The policy becomes something CI notices.

## Principles

### Test invariants, not appearances

Never snapshot a whole Markdown file or a formatted report. A test that fails on
every editorial improvement teaches contributors to update expectations without
reading them, which destroys the value of every other assertion in the file.

`ROADMAP.md` illustrates the alternative. Rather than comparing it to a stored
copy, the document is written in a fixed table shape, parsed with one regular
expression, and checked against the band skeleton encoded in
`src/globin/roadmap.py`. Prose can be improved freely; structure cannot silently
break.

### Test the rule, not the restatement

`assert PROJECT_NAME == "GLOBIN"` is worth writing because it pins a value the
rest of the system depends on. A test asserting that a constant equals itself is
not. If a test cannot fail for an interesting reason, delete it.

### Keep test helpers trivial

Helpers written for tests — such as the ROADMAP parser in `tests/conftest.py` —
stay small and obvious. A helper complex enough to contain a bug needs tests of
its own, at which point it belongs in the package.

### Determinism is mandatory

No test may depend on wall-clock time, network availability, execution order, or
random state without an explicit seed. Warnings are errors
(`filterwarnings = ["error"]`), so a deprecation surfaces when it appears rather
than when it breaks.

## Testing that arrives with later phases

Some of the most important verification in this project cannot exist yet, but is
already scheduled:

- **Leakage prevention** (Phases 161-176). Leakage is uniquely dangerous because
  it *improves* results, so it looks like success until real money is committed.
  Tests must actively attempt to leak — shifting labels, fitting scalers outside
  folds — and assert that the framework refuses.
- **Point-in-time correctness** (Phase 101-102). Property tests asserting that no
  query can return data timestamped after its observation time.
- **Execution uncertainty** (Phase 086). Simulated timeouts and 5XX responses,
  asserting the system reconciles rather than assumes.
- **Risk ceilings** (Phase 242). Adversarial tests attempting to breach an
  immutable ceiling through every available path, asserting refusal.
- **Reproducibility** (Phase 158). Identical inputs and seeds must produce
  bit-identical backtest results.

## Running the suite

The full gate, which is what must pass before any commit:

```bash
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

Individual checks while iterating:

```bash
python -m pytest -q
```

```bash
python -m pytest --cov=globin --cov-report=term-missing
```

Tests import from the source tree directly — `pythonpath = ["src"]` is set in
`pyproject.toml` — so no build or install is required.

## Coverage

Coverage is measured but is not a target. High coverage of trivial code proves
nothing, and a coverage threshold reliably produces tests written to satisfy the
threshold. Judge a suite by what it would catch, not by what it executed.
