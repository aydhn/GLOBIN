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

Six levels, one directory each under `tests/`. A test's directory decides its
level; there is no second place to declare it.

| Level | Directory | Scope | Speed | Network |
|---|---|---|---|---|
| **Smoke** | `tests/smoke/` | The smallest set of checks that would catch a broken tree | Instant | Never |
| **Contract** | `tests/contract/` | Project invariants: identity, policy, documentation, packaging, quality configuration | Instant | Never |
| **Architecture** | `tests/architecture/` | The layer contract checked against the real import graph | Instant | Never |
| **Unit** | `tests/unit/` | One module, function or class, dependencies substituted | Fast | Never |
| **Property** | `tests/property/` | An invariant asserted over generated input rather than fixed examples | Fast | Never |
| **Integration** | `tests/integration/` | Several GLOBIN components together, still entirely local | Moderate | Never |
| **External** | Does not exist yet | Real Binance non-production endpoints | Slow | Yes, explicitly opted into |

**No test at any level that exists today may touch the network.** Since Phase 005
that is enforced rather than requested: an autouse fixture refuses outbound
connections, and the section on [isolation](#isolation-and-the-offline-guarantee)
describes how. External tests arrive with the API layer (Phases 033-048), will
carry the `external` marker, are deselected by default, and must never run
against production or with live credentials.

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
- **Property versus unit** is about *whether an invariant exists*. If the claim
  is "for every input in this space, X holds", it is a property test. If the
  claim is "given this input, the answer is that", it is a unit test, and
  dressing it up with a two-element strategy makes it slower without making it
  stronger. See [property-based testing](#property-based-testing) below.

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
| `external` | Talks to a real external system; deselected by default |
| `windows` | Depends on behaviour specific to the Windows host |

`network` and `external` do a second job since Phase 005: either one exempts a
test from the offline guard. Nothing carries them today, and the exemption is
written now so that the guard has a documented door rather than acquiring an
undocumented one later.

`external` also became true in Phase 005. Its description had promised tests
were "skipped by default" since Phase 004 while nothing deselected them — the
selection is now composed into each expression in the command table. It is not in
`addopts`, deliberately: a command-line `-m unit` overrides an `addopts` `-m`, so
the exclusion would have silently vanished from exactly the selective runs.

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

### Autouse

**Two autouse fixtures exist, and adding a third needs an argument.** An autouse
fixture runs for every test in the suite, and unlike an ordinary one it is
invisible at the point of use: a test that depends on it does not say so. The bar
is therefore not "is this useful for many tests" but "would this be worthless
anywhere narrower".

Both current fixtures clear it because they are guarantees, and a guarantee that
holds for most of the suite is not a guarantee. They are described under
[isolation](#isolation-and-the-offline-guarantee).

Anything that merely saves typing is not autouse. Request it by name, so that a
reader of the test can see what it depends on.

## Test data and factories

Later phases will need a great deal of Binance-shaped data, and the habits that
make that bearable are cheaper to establish now than to retrofit. Four rules.

**Build data with a factory, not a literal repeated in twenty tests.** A factory
supplies safe defaults and lets a test override only the field it is actually
about, so the test reads as the one thing that distinguishes it. `layer_policy`
and `architecture_contract` in [`../tests/support.py`](../tests/support.py) are
the worked examples: both default to the strictest possible value, so a test that
permits something has to say so, and a reader learns what the test is about from
the arguments it passes.

Factories are plain functions with keyword arguments. No builder classes, no
inheritance hierarchy, no registry — a factory that needs its own documentation
has become a second system to understand before reading a test.

**Fixture data is small, synthetic and deterministic.** Timestamps are fixed
values, never `now()`. Numeric edge cases — zero, negative, the boundary either
side of a limit — are written out rather than left to be inferred. Nothing is a
captured production payload: a real response is large, mostly irrelevant, and
carries whatever happened to be true on the day it was captured.

**No fixture contains anything credential-shaped**, including a realistic-looking
fake. `test_repository_contract.py` rejects credential-shaped filenames, but a
convincing key inside a document is exactly the thing a future reader copies. Use
an obviously synthetic value such as `SENTINEL-VALUE-4f2a`, which is also what
makes finding it in output unambiguous.

**A document written to be invalid is written at run time, into `tmp_path`.**
`.pre-commit-config.yaml` runs `check-toml` and `check-yaml` over every file in
the tree, so a committed malformed fixture fails the hygiene gate rather than the
test it was written for. `test_architecture_contract.py` and
`test_configuration.py` both write theirs inline.

## Isolation and the offline guarantee

Two rules in this document used to be things a contributor had to remember.
Phase 005 made them fixtures, because both fail in a way that does not produce a
failing test: reaching the network passes on the machine that wrote the test and
fails elsewhere, and leaking process state produces a failure in a *different*
test that did nothing wrong.

**Nothing may open a socket.** `socket.socket.connect`, `socket.socket.connect_ex`
and `socket.create_connection` are replaced for the duration of every test, and
the replacement calls `pytest.fail`. It is deliberately not an `OSError`: a
realistic connection error is what retry code is written to swallow, so once such
code exists it would absorb the guard and the suite would go on reporting itself
offline while doing nothing of the kind. A test marked `external` or `network`
keeps the real socket.

Name resolution is not blocked. Nothing can act on a resolved address without
then connecting, and blocking DNS would only replace a specific message with a
vaguer one. Subprocesses are not covered either — the patch applies to this
interpreter.

**Nothing may leave the process altered.** The environment and the working
directory are captured before each test and compared afterwards; a test that
moved either is failed *and* the state is put back. Both halves matter. Restoring
alone would keep the suite green while the leak stayed; failing alone would name
the culprit and then let the damage reach every test that follows.

Use `monkeypatch.setenv` and `monkeypatch.chdir` to change either deliberately.
They undo themselves, and the guard is the net beneath them rather than a
substitute for them.

The detection itself is a plain function in `tests/support.py` rather than logic
buried in the fixture, so that it can be given its own failing cases — a checker
running in teardown is the easiest place in a suite for a silent failure to hide.
The reasoning behind all of this, including why the network guard must not use
`monkeypatch`, is in
[ADR-0024](adr/0024-tests-are-offline-and-isolated-by-construction.md).

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

### Test doubles

**A hand-written class satisfying a `Protocol` structurally is the default.**
That is what proves a port is a real seam rather than decoration — a mock would
satisfy any interface, including one the production code does not have.

**Where a mock is genuinely the right tool, it must be specified.** Use
`create_autospec(target, spec_set=True)`, never a bare `Mock()` or
`MagicMock()`. The autospec checks call signatures against the real object, so a
test fails when the thing it stands in for changes shape; `spec_set` additionally
refuses attributes the real object does not have, so a typo in an assertion fails
instead of silently creating another mock. An unspecified mock accepts every call
and every attribute, which means it goes on passing after the code it doubles has
gone.

The one place this applies today is the double for `tools.quality.runner.run` in
`tests/unit/test_quality_runner.py`. It replaced a hand-written stub, which had
encoded the runner's signature a second time and would have kept accepting the
old one after the real signature changed.

**Patch where a name is used, not where it is defined.** `main` binds `run` at
import, so patching `tools.quality.runner.run` would leave the bound reference
untouched; the patch goes at `tools.quality.__main__.run`.

**Prefer a real object when one is cheap.** A frozen dataclass built from
literals is clearer than a mock of it, and it cannot drift from the type it
represents.

## What the suite enforces, and why

| File | Enforces |
|---|---|
| `test_project_contract.py` | Identity is GLOBIN/`globin`; branch is `master`; 320 phases; Binance Global is the only venue; paid runtime services and scraping are prohibited; the contract object is immutable; no trading surface is exposed |
| `test_roadmap_contract.py` | Twenty contiguous 16-phase bands matching the charter; every phase 001-320 present exactly once in ascending order with a unique title and real purpose; no future phase marked complete; every artefact that states the delivered frontier in prose — `README.md`, the roadmap banner and the package docstring — agrees with it |
| `test_documentation_contract.py` | Required documents exist, are substantive, open with a heading, state the policies they own, carry no placeholder debt; ADRs are contiguous, well-formed, indexed, carry a known status and a consistent supersession record, and the README's count of them is right; the research ledger is properly structured; no branch instruction contradicts master-only |
| `test_repository_contract.py` | The engineering contracts exist and are committable; every repository-relative Markdown link resolves; change templates ask the right questions; no credential-shaped file would be committed; tool configuration is not duplicated outside `pyproject.toml` |
| `test_packaging_contract.py` | Distribution name matches the package; **runtime dependencies are empty**; the interpreter floor is evidence-based; version is single-sourced; no licence is invented; `CONTRIBUTING.md` names every development tool and counts them correctly |
| `test_architecture_contract.py` | The declared layers exist; no import crosses a boundary outward; the inner layers reach no I/O-capable module; importing a layer performs no work; there is no import cycle; the shared policy modules import no layer |
| `test_architecture_properties.py` | Over generated module names and import graphs: a module belongs to a layer only on a dotted boundary; a path and its dotted name round-trip; a relative import is refused at every depth; a cycle is reported the same way whatever member it is found from; a review does not depend on the order modules are supplied in |
| `test_roadmap_properties.py` | Over generated phase numbers: every phase in 1..320 resolves to exactly one band and every number outside it is refused; band membership agrees with the declared bounds |
| `test_quality_contract.py` | Every test module sits in a taxonomy directory and every level holds real tests; markers are registered, applied and documented; an unregistered marker is genuinely rejected; coverage is branch-aware and gated; the CI workflow is least-privilege, SHA-pinned, secretless and unable to fail quietly; hook and CI tool versions agree; `QUALITY_GATES.md` lists every quality command in order and this table describes every test module |
| `test_quality_runner.py` | A failing step's exit code is propagated unchanged; execution stops at the first failure; a missing tool fails distinctly and is never installed automatically; no verification command modifies the tree; `python -m tools.quality` works as a process |
| `test_error_taxonomy_contract.py` | Every fault descends from one root; the categories and the fault domains correspond exactly and neither may grow alone; no category inherits a builtin error type; the root declares no domain |
| `test_isolation_contract.py` | A connection attempt is refused and a `network`-marked test is not; the drift detector reports added, removed, altered, moved and deleted-directory cases, and stays quiet otherwise |
| `test_import_surface.py` | The package and every layer import cleanly; the declared public surface exists; no trading surface has appeared |
| `test_architecture_review_end_to_end.py` | The composition root wires a review over the real package rather than an empty directory, and that review is clean |
| `test_observability_contract.py` | The redacted-name list and the severity levels in `LOGGING_POLICY.md` and in the code are the same, in both directions; the documented record shape is the emitted one |
| `test_observability.py` | A sensitive name is recognised however it is written; an event redacts itself even when built directly; binding returns a new logger; a value JSON cannot represent is rendered rather than refused; a failed write propagates |
| `test_observability_properties.py` | Over generated input: a value survives exactly when its name is not sensitive, at any nesting depth; redaction is idempotent; no field value can make the sink emit something that is not JSON |
| `test_logging_end_to_end.py` | The wired logger writes parseable records that share a correlation id, and a planted credential does not reach the stream |
| `test_configuration_contract.py` | The settings register in `CONFIGURATION_POLICY.md` and the model declare the same settings, in both directions; each documented default, written back through the binding, resolves to the value the model would have used anyway |
| `test_configuration.py` | A layer refuses an empty origin and a repeated key, and orders itself; the fold never refuses; the key register and the defaults are derived from the dataclass; an unknown key, a misspelled severity and a numeric one are each refused by name; a quoted TOML key containing a dot is refused rather than collided |
| `test_configuration_properties.py` | Over generated layers: resolving never raises; no key is lost or invented; the strongest layer wins whatever came before; silence preserves; an empty layer is the identity; a threshold forwards a record exactly when the record clears it |
| `test_configuration_end_to_end.py` | A severity written in a document actually stops a record being written; a caller configuring nothing sees Phase 006's behaviour unchanged; an unknown setting is refused wherever it sits in the source order, and a value a stronger layer replaces is deliberately not validated |

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

The same source, the same inputs and the same controlled environment must give
the same result. No test may depend on wall-clock time, network availability,
execution order, the machine's environment variables, the working directory it
happened to start in, or unseeded randomness. Warnings are errors
(`filterwarnings = ["error"]`), so a deprecation surfaces when it appears rather
than when it breaks.

Consequences worth spelling out:

- Tests must not share mutable state, so running one alone must give the same
  result as running it in the middle of the suite. The isolation fixtures make
  the common cases of this enforceable rather than aspirational.
- A test that writes must write to `tmp_path`. Leaving the repository in a
  different state than it found it makes the next run depend on the last one.
- No `sleep` as synchronisation, and no assertion of the form "this took roughly
  so long". Both are timing assertions, and a shared CI runner will eventually
  break them. This is also why Hypothesis runs with its per-example deadline
  disabled.
- Never depend on set or dictionary iteration order reaching a reported result —
  `ENGINEERING_CONTRACT.md` invariant 3. `tests/property/` asserts this directly
  for the architecture review, whose output is sorted precisely so that two runs
  over one tree report identically.
- Flaky tests are diagnosed, never retried. There is no rerun plugin, and adding
  one would convert a real defect into an intermittent green build.

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

## Property-based testing

An example-based test asserts what its author thought of. A property test states
something that must hold across a described space of inputs, and Hypothesis
searches that space for a counter-example, then shrinks it to the smallest input
that still fails.

That distinction is not theoretical. The first run of `tests/property/` produced
two failures, both defects in the *tests*: one asserted that a module name never
contains `.py`, which is false for a module legitimately called `py`, and one
generated the source `import as`. Neither is an input a person writing examples
pictures.

### When to write one

When a real invariant exists. The recognisable shapes are an idempotent
operation, a round trip, a total function over a bounded domain, an ordering that
must not depend on input order, and a rule about a whole class of names or paths.
The invariants asserted today include `band_for_phase` being total over 1..320,
cycle detection being canonical and order-independent, and the architecture
review reporting identically however its input is ordered — a rule
`ENGINEERING_CONTRACT.md` had stated since Phase 001 with nothing checking it.

Not for every change. A property test over a two-element strategy is a slow unit
test, and requiring one everywhere would devalue the level. The Definition of
Done asks for one *when an invariant exists*, which is a judgement, not a
checkbox.

Do not restate the implementation. A property asserting that
`top_level_package` returns `module.split(".")[0]` passes forever and catches
nothing. The test to be suspicious of is one that would have to change if the
implementation were rewritten correctly.

### Profiles

Two, registered in `tests/conftest.py`:

| Profile | Used by | Behaviour |
|---|---|---|
| `dev` | `python -m tools.quality property`, and a bare `pytest` | Searches freely, keeps the example database so a past failure replays first |
| `ci` | `python -m tools.quality full`, locally and in CI | `derandomize` — the same code examines the same inputs every run — and no database |

The gate uses `ci` on every machine, not only on the build server. A gate that
searched a different input space per machine could pass where the code was
written and fail where it was reviewed, for no visible reason.

Both disable the per-example deadline, and both print a reproduction blob.

### Reproducing a failure

Hypothesis prints a `@reproduce_failure(...)` decorator with every failure. Paste
it above the test to replay that exact case while fixing it, and delete it
afterwards — it pins one input and would stop the search that found it.

```bash
python -m pytest -q -m property --hypothesis-profile=ci
```

A failure under `ci` reproduces on a rerun by construction. A failure under `dev`
may not, and the printed blob is how it is pinned. Do not fix a property failure
by narrowing the strategy until the failing input can no longer be generated
unless the input was genuinely invalid — as `import as` was, and as a module
called `py` was not.

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

The property level under the exploratory profile, which is the one that searches
for new counter-examples:

```bash
python -m tools.quality property
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
