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
| `test_documentation_contract.py` | Required documents exist, are substantive, open with a heading, state the policies they own, carry no placeholder debt; ADRs are contiguous, well-formed, indexed, carry a known status and a consistent supersession record, and the README's count of them is right; the research ledger is properly structured; no branch instruction contradicts master-only; the README's maturity table claims only known states, still admits that everything else is unbuilt, links every implemented capability to what proves it, and its list of absent capabilities is still true of the package |
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
| `test_values_contract.py` | The types, the bounds and the operation matrix in `VALUE_TYPES_POLICY.md` and the code agree in both directions; every documented outcome is produced by running the attempt rather than by comparing strings |
| `test_values.py` | Every way an amount can be inexact is refused by name — a float, a bool, `NaN`, negative zero, a float-derived decimal, an absurd magnitude; a price of zero is refused and a quantity of zero is not; comparison answers within a denomination, refuses across two and raises `TypeError` across types; quantities add and subtract exactly while a price gains no arithmetic at all |
| `test_values_properties.py` | Over generated values: every code the alphabet describes is accepted and every other refused; an amount survives being written down and read back; ordering is a total order within one denomination and always refuses across two; equality never raises for any pair of any type |
| `test_clock_contract.py` | The types, the bounds and the operation matrix in `TIME_POLICY.md` and the code agree in both directions; every documented outcome is produced by running the attempt; the document still names the phases it defers to and still answers the Phase 010 boundary |
| `test_clock.py` | Every way a moment can be wrong is refused by name — naive, a `date`, a non-UTC offset, a `tzinfo` that cannot report one, a bool where a count belongs, a value off the end of the calendar; milliseconds floor towards the past on both sides of the epoch; readings subtracted in the wrong order are refused; no test asserts that two real clock readings differ |
| `test_clock_properties.py` | Over generated instants: converting an offset never moves the point; every naive moment is refused; the millisecond projection is monotone, never moves an instant forward, and round-trips exactly from a whole millisecond; ordering is total and never refuses; equality never raises for any pair |
| `test_clock_discipline.py` | No module in the domain, ports or application layers calls an ambient clock, anywhere including inside a function; exactly one adapter reads the host clock; the dependency contract still lists `time` as I/O-capable and `datetime` as not |
| `test_precision_discipline.py` | No module under `src/globin` reads, sets or borrows the ambient decimal context, anywhere including inside a function; no module outside the domain layer reads `.amount` off a value; each guard is exercised by a case it must catch and one it must spare |
| `test_precision_contract.py` | The bounds table, the rounding-mode table and the deferral list in `PRECISION_POLICY.md` and the code agree in both directions, with each documented bound compared against the value the module actually holds |
| `test_precision.py` | Every increment refusal by name; each of the four rounding modes on both sides of its boundary, including both tie directions; an exact sum that cannot be represented is refused rather than rounded; the digit budget is rederived from the published value bounds; a hostile ambient context changes nothing and the caller's context is left untouched |
| `test_precision_properties.py` | Over generated magnitudes and grids: exact arithmetic agrees with `fractions.Fraction` or refuses; alignment is total, idempotent, bounded by one increment, direction-correct per mode and order-preserving; a hostile ambient context changes no answer |
| `test_precision_end_to_end.py` | One order-shaped calculation composes alignment, notional, a ceiling-rounded fee and a balance reduction, with every intermediate exact, every rounding named, and the whole result unchanged under a hostile ambient context |
| `test_identifier_discipline.py` | No module under `src/globin/domain` names a product, an environment or an asset as a live constant, docstrings excluded; no module there reads a source of randomness; each guard is exercised by a case it must catch and one it must spare |
| `test_identifier_contract.py` | The kinds table, the constants table and the operation matrix in `IDENTIFIER_POLICY.md` and the registry agree in both directions; each documented description is the specification's own summary rather than a second author's; every documented outcome is produced by running the attempt; the symbol form is derived from Phase 008's bounds rather than restated |
| `test_identifiers.py` | Every kind has a specification, and one without is an internal fault rather than a validation failure; each identifier accepts its canonical form and is refused by the rule it breaks for the wrong case, the wrong length, a stray character and a non-string; a fixed-length kind says `exactly` rather than `between`; two kinds carrying the same text are not equal |
| `test_identifier_properties.py` | Over generated text: the reporting predicate and every constructor agree on what each form admits; validity survives permutation; one character outside the alphabet is refused wherever it sits; minted run identifiers fit the registry's form and never repeat |
| `test_serialization_contract.py` | Every wire form has a reader as well as a writer; a monotonic reading has no encoder and the policy says why; the evidence manifest's envelope keys are the ones the domain defines and its schema name is legal under the rule this phase wrote; the envelope keys, the derived identifier column width and all four compatibility answers appear in `SERIALIZATION_POLICY.md` |
| `test_serialization.py` | Every refusal by name: a schema name outside the alphabet, at either length bound, or with an empty segment; version zero and a boolean version; a payload colliding with an envelope key; a migration that skips a version, a chain with a gap or a fork, and one spanning two schemas; a record newer than its reader; a non-finite decimal in both directions; an instant carrying microseconds; and the three `json` defaults that would each break the round trip |
| `test_serialization_properties.py` | Over generated values: every wire form read back is the value written, with a decimal compared by `compare_total` so a lost exponent fails; rendering does not depend on key insertion order; compatibility is a duality, so backward one way round is forward the other; a record ahead of its reader is refused for every version pair |
| `test_serialization_end_to_end.py` | One fill-shaped record from domain values to stored text and back through the composition root, with the stated precision reaching the bytes; the same record renders identically from separately built codecs; a stored record is migrated after it was written; a record from a newer writer is refused at the boundary; a truncated document stays a detectable fault |
| `test_evidence.py` | The pure half of the evidence package, from literals: a JUnit report is read into counts that add up and refused when malformed; coverage totals are copied and never recomputed; a checksum manifest is sorted, self-excluding and round-trips; secret-shaped content and an absolute path are both found while a relative path and `pythonnousersite` are spared; Ruff and mypy output is read into one ordered shape and every reported path is reduced to the repository; an edited manifest fails its own digest and an unsupported schema version is refused |
| `test_evidence_contract.py` | ADR-0032's mechanically checkable conditions for the evidence gate: no dependency added in the manifest or in the imports, nothing under `src/globin` importing the tooling, absent from `fast` and `full`, writing only inside the ignored run directory, documented in `QUALITY_GATES.md`, printing only ASCII; no tool it starts can rewrite the tree and each writes its own evidence file; and a CI job that installs every tool the gate starts and uploads on `always()` without masking a failure |
| `test_evidence_end_to_end.py` | The gate composed with an injected process runner: a passing run writes and verifies every file and records a verdict for all five gates; a failing suite still produces evidence and still exits non-zero; coverage below the floor is recorded before it is reported; an unwritten report is unmeasured rather than passing; no published file carries this machine's repository path and the raw coverage database is not left behind; the previous run is pruned; a tampered artifact, an edited manifest, a corrupt report and a leaked secret each fail verification |
| `test_execution.py` | Collection output is parsed and checked against pytest's own count; a node ID escaped by pytest survives and a malformed one does not; the manifest digest ignores order and volatile metadata and changes when the tests or the selection do; an edited manifest is refused; the partition is complete, disjoint, balanced within one and independent of both input order and the interpreter's hash seed; only pytest's `0` and `1` are verdicts about tests |
| `test_execution_end_to_end.py` | The gate runs every shard exactly once with its own args file and its own coverage data; exit `4` and `5` are unmeasured and outrank a failure; a child that never returns is reported rather than waited for; the args files together account for every test and contain no blank line; stale files from a wider run are removed; a failure prints its seed and a replay line |
| `test_workflow.py` | Reading a CI run without a CI run: each of the four job results GitHub documents, and every other value — including a differently cased one — read as unmeasured; a required job absent from the context is unmeasured rather than omitted; a job that is not required does not become one; the declared configuration is refused when absent, empty or the wrong type; the aggregate announces its schema, records its verdict rather than leaving it derivable, is sealed against editing, renders identically twice and names no absolute path; the summary leads with the verdict, carries the artifact digest and the reproduction commands, and renders a malformed section as blanks rather than raising |
| `test_workflow_cli.py` | The entry point and the branches a passing run never reaches: no argument runs the default and an unknown or repeated word is refused; `--help` exits zero and documents all four exit codes; a bad command line exits `2`, distinct from any verdict; the module starts as a process; and an unreadable configuration, an unparseable settings file, a manifest whose gates section is not a mapping, a gate entry that is not a mapping, and a summary that cannot be written are each handled without turning into a pass |
| `test_workflow_contract.py` | ADR-0032's mechanically checkable conditions for the aggregate gate: no dependency, standard library and this repository only, nothing importing `globin`, absent from `fast` and `full`, writing only inside the ignored run directory, printing only ASCII; the declared required jobs, check name, artifact and retention each compared against the workflow in both directions; no two jobs sharing a check name; the aggregate depending on every required job and running after one of them failed; and the circular-digest guard — the aggregate is not inside the bundle whose digest it records |
| `test_workflow_end_to_end.py` | The exit-code contract against real files: everything passing is `0`, a failed required job or evidence gate is `1`, and a job that was skipped, cancelled, absent, unrecognised or unreported is `3` — as is a missing, unreadable, tampered or gate-short manifest; unmeasured outranks failed; the aggregate is written even when the run failed and leaves no partial file; the artifact digest is recorded when CI supplies one and named as missing when it does not; the step summary is appended only when GitHub asks for one; and a reader refuses an aggregate from a later schema version or another schema |
| `test_execution_contract.py` | The execution commands are reachable only through the one command table, sit between `coverage` and `mutation`, are absent from `fast` and `full`, and claim not to modify the tree; every declared requirement carries a review record and no command retries a test; the run directory is ignored by Git |
| `test_ci_security_contract.py` | What CI is trusted to do: every remote action pinned to a full commit, carrying a readable version, and agreeing with `action-pins.toml` in both directions on version and upstream, with no third-party action among them; no elevated trigger and no untrusted event field reaching a shell, while the same field passed through `env:` is spared; no over-broad scope, no missing permissions block and no masked failure; every job bounded by a timeout that matches the declared budget, covering every required job and the aggregate; the concurrency group namespaced by workflow and master runs never cancelled; the queue trigger present and no display name claimed twice — and every one of those checkers watched failing against a deliberately broken copy held as a string, never a file |
| `test_mutation_contract.py` | The mutation configuration, its baseline and the command table name the same modules and paths; every recorded survivor is well-formed, names an operator that exists and carries an argument no placeholder could satisfy |
| `test_mutation.py` | Each operator finds its own site and no other; the excluded kinds produce none; enumeration is deterministic, uniquely identified and ordered explicitly; every mutant parses and changes one line; every pytest exit code means what pytest says, and only `0` and `1` are verdicts |
| `test_mutation_sandbox.py` | The throwaway tree is built without stale bytecode, a module can be replaced inside it without touching the real one, an exit code is reported unjudged, and a child that never returns is reported as stopped rather than waited for |
| `test_mutation_end_to_end.py` | The gate refuses to start on a configuration or baseline it cannot read; stops when the unmutated subset already fails; stops when a module replaced by `raise ImportError` still passes; and fails on a survivor the baseline does not expect, printing a block that will not pass review unread |
| `test_supply_workflows.py` | Every reference shape a workflow may carry: a full commit with a three-part version comment is accepted, while a mutable tag, a branch, a short SHA and both length boundaries either side of forty are refused; a comment that is missing, a bare major or not a version is refused; a `./` reference is not an external dependency at all; a Docker action is judged by digest rather than by commit and none is used here; a subdirectory action reports its repository so two subpaths at one commit are one dependency; exact `pip install` pins are read and ranges are not; and two jobs pinning one package differently is refused rather than resolved |
| `test_supply_inventory.py` | The three registers, and the drift between them: the real tree collects in a total order with no runtime dependency and no disagreement, and reads reproducibly; a missing or malformed manifest is refused rather than read as empty; a tool CI installs but `pyproject.toml` does not declare, a pin violating its own lower bound, and a hook revision disagreeing with the version the gate installs are each reported, while the matching cases are not; and a package URL names the ecosystem that can actually update it |
| `test_supply_sbom.py` | The two fields the specification requires; two builds of one inventory rendering byte-identically; a serial derived from the commit rather than generated, distinct per commit and per repository; a ranged dependency carrying no version and no package URL but keeping its specifier; one package in two scopes producing two distinguishable components; components ordered by the key the document itself shows; a graph stating only what is known — and the validator watched failing on a wrong specification version, a wrong format, a duplicate component, components out of order, an edge pointing at nothing, a component with no type, a missing components array and a serial that is not a URN |
| `test_supply_secrets.py` | Every pattern has a sample and finds its own shape; **no finding contains the matched text, nor a recognisable prefix of it** — the property the scanner exists to preserve, since a report that repeats a secret has published it a second time; a fingerprint is stable and short; the allowlist is per file and per pattern with a reason, exempting nothing wholesale, and no entry is stale; a file of commits, digests and seeds produces nothing, because this is not an entropy heuristic; several findings in one file are reported separately by line; and binary suffixes are not read as text |
| `test_supply_waivers.py` | A complete waiver is read and an absent register is not an error; each of the ten fields is required; a range meaning every version is refused in four spellings; an unknown schema version, a quoted date and an expiry preceding its creation are each refused; expiry is inclusive of its own date and fails the day after; and a waiver marks a finding rather than removing it, matching case-insensitively on the package and exactly on the advisory |
| `test_supply_audit.py` | The judgement without the audit: a clean result, a finding read with its fix versions, and a waiver changing only the disposition; unparseable output raising rather than reporting nothing; every failure mode — connection, timeout, retries, certificate, collection and unknown — classified as something that is not clean and saying so in words; only a completed audit counted as measured; the open count excluding waived findings while the report does not; a sorted, deduplicated requirements file; and an empty pinned set treated as a failure rather than a clean audit |
| `test_supply_capability.py` | Each response shape mapping to its own state, using the prose GitHub actually returned: a plan ceiling and a missing scope distinguished though both are `403`; an unrecognised `404` read as a failure rather than an absence; a setting read from a JSON path and compared to its expected value; a control known to be unenableable reported as unavailable rather than as a permanent failure; a body that is not JSON and a missing key each an error rather than a verdict; only a required control being off counted as a policy failure; and `UNAVAILABLE` and `NOT_PROBED` never masked as a pass |
| `test_supply_contract.py` | Phase 014's own conditions: the manifest announces its schema and version, is sealed against editing, refuses another schema or version and renders identically twice; every reason code the gate can emit is in the declared closed set; the review register and the generated inventory agree in both directions, every review carries every field, and every licence is one the policy classifies; every capability state the code can produce is explained in the policy; no module can mask a failure and none but the two named starts a process — both checked against code with docstrings and comments removed, because each forbidden string appears in the prose explaining why it is forbidden |
| `test_supply_runner.py` | The two functions that leave the process, driven by an injected runner rather than by a network: a clean child, a finding, and — the case that failed in practice — exit 1 with no payload read as a collection failure rather than as a finding count of zero; an undocumented exit code, a child that never returns and one that cannot be started, each classified as something that is not clean; output that cannot be read never guessed at; and for the probe, every control asked and recorded, a plan refusal recorded as one rather than as a failure, and a probe that could not run reported as an error rather than a pass |
| `test_supply_cli.py` | The entry point and the branches a passing run never reaches: every accepted spelling of the command line and four refusals; a bad line exiting `2`, distinct from every verdict; the usage documenting all four codes; an unwritable directory unmeasured rather than passing; the module started as a process; and the gate's own failure paths — an online run measuring both network checks, a vulnerability and a required control switched off each failing, and an unreadable tree, a malformed waiver register, a missing commit date and a tree Git cannot list each recorded as unmeasured rather than as clean |
| `test_supply_end_to_end.py` | The gate composed offline: a clean tree writes an inventory, a CycloneDX document and a sealed manifest, and returns zero; the SBOM written to disk is byte-identical to a second independent build; an unmeasured audit and an unmeasured platform probe are recorded as such and outrank a pass; the manifest names no absolute path and carries no wall-clock time; and the entry point refuses an unknown word with an exit code distinct from every verdict |

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
