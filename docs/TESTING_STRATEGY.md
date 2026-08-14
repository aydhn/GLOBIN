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

Five levels, one directory each under `tests/`. A test's directory decides its
level; there is no second place to declare it.

| Level | Directory | Scope | Speed | Network |
|---|---|---|---|---|
| **Smoke** | `tests/smoke/` | The smallest set of checks that would catch a broken tree | Instant | Never |
| **Contract** | `tests/contract/` | Project invariants: identity, policy, documentation, packaging, quality configuration | Instant | Never |
| **Architecture** | `tests/architecture/` | The layer contract checked against the real import graph | Instant | Never |
| **Unit** | `tests/unit/` | One module, function or class, dependencies substituted | Fast | Never |
| **Integration** | `tests/integration/` | Several GLOBIN components together, still entirely local | Moderate | Never |
| **External** | Does not exist yet | Real Binance non-production endpoints | Slow | Yes, explicitly opted into |

**No test at any level that exists today may touch the network.** External tests
arrive with the API layer (Phases 033-048), will carry the `external` marker, must
be skipped by default, and must never run against production or with live
credentials.

### Choosing a level

The distinctions that are easy to get wrong:

- **Unit versus integration** is about *collaborators*, not size. If the
  dependencies are substituted, it is a unit test however many lines it takes.
  If real collaborators are wired together — normally through the composition
  root — it is integration.
- **Integration versus external** is about *the network*. Several components in
  one process is integration. Another system on the far side of a socket is
  external, and does not exist in the repository yet.
- **Contract versus everything else** is about *what is asserted*. A contract
  test asserts a project rule — a policy, a layout, a configuration — rather
  than the behaviour of code. It is the level that makes a written rule
  enforceable.
- **Architecture** is contract-level in spirit, separated because it is the one
  body of checks that reads the source tree as data.
- **Smoke** is not a lighter unit test. Ask whether it would fail for a change
  that makes the repository unusable. If it would only fail for a subtle logic
  error, it belongs at a later level.

### Markers

Every test carries exactly one **level** marker, applied automatically from its
directory by a collection hook in `tests/conftest.py`. Deriving it means
`pytest -m unit` cannot disagree with the layout, and a moved file cannot keep a
stale label.

Four **attribute** markers are registered and applied by hand. They describe a
property of a test rather than its level, so a test may carry none or several:

| Marker | Meaning |
|---|---|
| `slow` | Worth deselecting during a tight edit loop |
| `network` | Requires network access; never permitted below the external level |
| `external` | Talks to a real external system; skipped by default |
| `windows` | Depends on behaviour specific to the Windows host |

Markers are registered in `pyproject.toml`, and `strict_markers` makes an
unregistered one a collection error rather than a warning.

That distinction was learned the hard way and is worth stating: the flag
`--strict-markers` placed in `addopts` does **not** take effect — pytest emits
`PytestUnknownMarkWarning` and the run passes. Only the ini option is enforced.
The repository carried the ineffective form from Phase 001 until Phase 004
tested it, which is why `tests/contract/test_quality_contract.py` now proves the
behaviour against a throwaway project rather than asserting that a string
appears in a list.

Select a level, or exclude an attribute:

```bash
python -m pytest -m unit
```

```bash
python -m pytest -m "not slow"
```

## Fixtures

Fixtures are declared at the narrowest scope that serves them.

| Where | Holds |
|---|---|
| `tests/conftest.py` | Only genuinely repository-wide fixtures, inherited by every level |
| `tests/<level>/conftest.py` | Fixtures shared across one level, when one is needed |
| The test module itself | Anything used by a single module |

A root `conftest.py` applies to every test in the suite, so everything added
there is paid for by the whole suite. It is the most convenient place to put a
fixture and usually the wrong one.

Two rules keep this workable:

- **Fixtures go in `conftest.py`; importable helpers go in `tests/support.py`.**
  A `conftest.py` is loaded by pytest rather than imported by name, so
  `from conftest import ...` only ever worked because pytest happened to place
  `tests/` on `sys.path`. Helpers a test imports live in a real module.
- **Session scope for immutable repository state.** The fixtures that read
  `ROADMAP.md` or ask Git which files are committable are `scope="session"`:
  re-reading per test would be slower and could not produce a different answer.
  A fixture whose value a test may mutate must not be session-scoped.

## Naming

| Kind | Convention |
|---|---|
| Test module | `test_<subject>.py`, in the directory for its level |
| Contract module | `test_<subject>_contract.py` |
| Test function | `test_<the rule being asserted>` — a sentence, not a label |
| Test double | A private class, `_FixedContract`; never `Mock` or `MagicMock` |

Function names are long on purpose. A failing line in CI output should already
be the diagnosis: `test_domain_imports_no_outer_layer` says what broke, where
`test_imports_2` requires someone to open the file.

Test doubles are hand-written classes satisfying a `Protocol` structurally. That
is what proves a port is a real seam rather than decoration — a mock would
satisfy any interface, including one the production code does not have.

## What the suite enforces, and why

| File | Enforces |
|---|---|
| `test_project_contract.py` | Identity is GLOBIN/`globin`; branch is `master`; 320 phases; Binance Global is the only venue; paid runtime services and scraping are prohibited; the contract object is immutable; no trading surface is exposed |
| `test_roadmap_contract.py` | Twenty contiguous 16-phase bands matching the charter; every phase 001-320 present exactly once in ascending order with a unique title and real purpose; no future phase marked complete |
| `test_documentation_contract.py` | Required documents exist, are substantive, open with a heading, state the policies they own, carry no placeholder debt; ADRs are contiguous, well-formed, indexed, carry a known status and a consistent supersession record; the research ledger is properly structured; no branch instruction contradicts master-only |
| `test_repository_contract.py` | The engineering contracts exist and are committable; every repository-relative Markdown link resolves; change templates ask the right questions; no credential-shaped file would be committed; tool configuration is not duplicated outside `pyproject.toml` |
| `test_packaging_contract.py` | Distribution name matches the package; **runtime dependencies are empty**; the interpreter floor is evidence-based; version is single-sourced; no licence is invented |
| `test_architecture_contract.py` | The declared layers exist; no import crosses a boundary outward; the inner layers reach no I/O-capable module; importing a layer performs no work; there is no import cycle; the shared policy modules import no layer |
| `test_quality_contract.py` | Every test module sits in a taxonomy directory and every level holds real tests; markers are registered and applied; an unregistered marker is genuinely rejected; coverage is branch-aware and gated; the CI workflow is least-privilege, SHA-pinned, secretless and unable to fail quietly; hook and CI tool versions agree |
| `test_quality_runner.py` | A failing step's exit code is propagated unchanged; execution stops at the first failure; a missing tool fails distinctly and is never installed automatically; no verification command modifies the tree |
| `test_import_surface.py` | The package and every layer import cleanly; the declared public surface exists; no trading surface has appeared |
| `test_architecture_review_end_to_end.py` | The composition root wires a review over the real package rather than an empty directory, and that review is clean |

The architecture tests are contract-level despite reading source files, because
they assert a project invariant rather than a behaviour. They parse the syntax
tree rather than importing the modules — importing would execute them, and one
of the rules under test is that importing executes nothing.

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

Helpers written for tests — such as the ROADMAP parser in `tests/support.py` —
stay small and obvious. A helper complex enough to contain a bug needs tests of
its own, at which point it belongs in the package.

### Determinism is mandatory

No test may depend on wall-clock time, network availability, execution order, or
random state without an explicit seed. Warnings are errors
(`filterwarnings = ["error"]`), so a deprecation surfaces when it appears rather
than when it breaks.

Two consequences worth spelling out. Tests must not share mutable state, so
running one alone must give the same result as running it in the middle of the
suite. And a test that writes must write to `tmp_path`: leaving the repository
in a different state than it found it makes the next run depend on the last one.

### Guard every checker with its failing case

A validator whose negative case is never exercised is indistinguishable from one
that cannot fail. A regex refactor is enough to make a check silently match
nothing, and nothing goes red.

So each checker in this suite has a companion test that feeds it something bad
and asserts it complains: the link checker is given a broken link, the
architecture review a synthetic violation, the import-time check a module that
does work, and the marker configuration an unregistered marker.

Where a negative case could pass because the harness itself is broken, a
positive control runs alongside it — the same fixture with only the thing under
test changed. That pairing is what caught the ineffective `--strict-markers`
configuration described above.

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

The same checks, invoked directly — this is what CI runs:

```bash
python -m tools.quality full
```

While iterating:

```bash
python -m pytest -q
```

```bash
python -m tools.quality fast
```

Tests import from the source tree directly — `pythonpath` is set in
`pyproject.toml` — so no build or install is required. The command table behind
these is described in
[`engineering/QUALITY_GATES.md`](engineering/QUALITY_GATES.md).

## Coverage

Branch coverage is measured over `globin` and `tools` and gated at a
repository-wide floor. The policy — the threshold, what is excluded and why — is
in [`engineering/QUALITY_GATES.md`](engineering/QUALITY_GATES.md), which owns it.

What belongs here is the reasoning about what the number means, because that is
easy to get backwards.

**Coverage is a floor, not a target.** Phase 004 introduced a threshold, which
reverses this document's earlier position that no threshold should exist. The
earlier reasoning was sound and remains true: high coverage of trivial code
proves nothing, and a threshold set as a *goal* reliably produces tests written
to satisfy it. What changed is the recognition that the same number used as a
*floor* catches something a goal never could — a module quietly losing its
tests, which is invisible in a green suite.

So the threshold sits deliberately below the actual figure. It is not there to
be raised, and raising it by adding tests that assert nothing would improve the
metric while making the suite worse. Judge a suite by what it would catch, not
by what it executed. A line-covered branch that has only ever been taken one way
is not tested, which is why the measurement is branch-aware rather than
line-based.
