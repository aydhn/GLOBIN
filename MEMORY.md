# MEMORY.md — Durable project memory

Facts that remain true across sessions. This is **not** a session log, a diary,
or a changelog. Entries are concise, auditable, and removed when they stop being
true.

If you are starting a session, read this first, then [`AGENTS.md`](AGENTS.md).

---

## Identity

| Fact | Value |
|---|---|
| Project name | GLOBIN |
| Repository | GLOBIN |
| Python package | `globin` |
| Remote | `https://github.com/aydhn/GLOBIN.git` |
| Branch | `master` — the only branch, and the remote default |
| Encoded in | `src/globin/project_contract.py`, asserted by tests |

---

## Programme status

| Fact | Value |
|---|---|
| Total phases | 320, fixed, in twenty immutable bands of sixteen |
| Completed phases | **001-015** |
| Phase 001 | **Repository Foundation and Engineering Contract.** Validation passed and commit `c7504c4` was pushed to `origin/master`; local and remote verified identical and the tree left clean. |
| Phase 002 | **Documentation System and Style Guide.** Established the engineering contracts under `docs/engineering/`, the documentation authority order (ADR-0011), the ADR template, and the GitHub change templates. Commit `9c46313`, pushed. |
| Phase 003 | **Architecture Boundaries and Dependency Direction.** Five layers under `src/globin/`, the inward dependency contract in `docs/architecture/dependency-rules.toml`, C4 system context and container views, the ADR lifecycle with supersession rules, and `tests/architecture/test_architecture_contract.py` enforcing all of it. Commit `990e5f4`, pushed. |
| Phase 004 | **Test Architecture and Quality Gates.** Five test levels as directories under `tests/`, markers derived from the directory, `tests` as a package with helpers in `tests/support.py`; explicit mypy flags in place of `strict = true`; branch coverage gated at 95; `.pre-commit-config.yaml`; the canonical entrypoint `tools/quality`; and a SHA-pinned, least-privilege, verification-only CI workflow. Commit `abb96a9`, pushed. **CI is confirmed working:** the first run on that commit succeeded on both Python 3.12 and 3.14, and the pre-commit job passed. The phase was reported before that run existed, so ADR-0020 and the Phase 004 research ledger still describe the workflow as never executed — correct for their date, and superseded by this row. |
| Phase 005 | **Error Taxonomy and Deterministic Test Foundations.** `globin.errors` — one root, five categories divided by who must act — replacing the ad-hoc `ValueError` scheme in the adapters and domain layers. Plus a `property` taxonomy level with Hypothesis, autouse fixtures that refuse outbound sockets and fail a test leaking process state, the `create_autospec` rule for mocks, and the `external` deselection that Phase 004's marker description had promised but nothing performed. ADR-0021 to ADR-0024. Commit `7f65d25`, pushed. |
| Phase 006 | **Structured Logging Foundation.** `observability.py` in all four layers plus `build_logger` in the composition root: a `LogEvent` domain value that redacts itself in `__post_init__`, a one-method `LogSink` port, an immutable `Logger` whose `bind` returns a new logger, and a `StreamLogSink` writing JSON Lines. Correlation is explicit, never a context variable; the timestamp is stamped by the adapter so Phase 009 keeps the clock decision. `docs/LOGGING_POLICY.md` owns the severity meanings and the redacted-name list, and a contract test compares that document against the code in both directions. ADR-0025 and ADR-0026. Commit `9913edb`, pushed. |
| Phase 007 | **Configuration Model and Schema Contract.** `configuration.py` in all four layers plus `build_configuration` in the composition root. The model is frozen dataclasses and *is* the schema: the key register and the defaults layer are both derived from `dataclasses.fields()`, so a setting cannot be half-added. Layers are flat dotted keys carrying an origin; `resolve` folds them last-wins and **never raises**, so every refusal lives in `as_config` where the origin can be named. `docs/CONFIGURATION_POLICY.md` owns the settings register, and its contract test feeds each documented default back through the binding rather than comparing strings. The one setting is `logging.min_severity`, honoured by a decorating `ThresholdLogSink` — `StreamLogSink` and `Logger` are untouched. ADR-0027 to ADR-0029. Commit `651f35d`, pushed. |
| Phase 008 | **Domain Value Types and Units.** `values.py` in the domain layer and nowhere else: five denominated types — `Side`, `Currency`, `Symbol`, `Quantity`, `Price` — carrying `Decimal`, never subclassing it. They **compare but do not compute**: `Decimal` arithmetic reads a thread-local context and silently rounds, so the operators wait for Phase 010, while comparison is exact and settles nothing that phase owns. A wrong type returns `NotImplemented`; a wrong *unit* raises `ValidationError`, because mypy could not have caught it. `docs/VALUE_TYPES_POLICY.md` owns the register, and its contract test **executes** each documented operation rather than comparing strings. Delivered with it, as tooling rather than phase scope: a mutation-testing gate. ADR-0030 to ADR-0033. Commits `2490fcb` and `ab2e187`, pushed. **CI is confirmed working, including the new job:** run `31821279313` passed all four jobs on `windows-latest`, and the `Mutation baseline` job reported `48/52 killed, 4 survived` — byte-identical to the local run on a machine with no user-level toolchain and a cold cache, which is the evidence that the mutant identity scheme is deterministic across machines. |
| Phase 009 | **009 — Time, Clock and Timezone Discipline.** `clock.py` in the domain, ports and adapters layers, plus `build_clock` and `build_monotonic_clock` in the composition root. Three types, because *when* is three questions: `Instant` (an aware UTC `datetime`, orders but does not subtract), `Duration` (non-negative whole nanoseconds) and `MonotonicReading` (nanoseconds from an undefined origin, which therefore cannot be rendered as a time). **Two ports, not one** — a wall clock can be stepped and a monotonic one cannot, and Phase 040's server-time clock must be able to implement `Clock` without inventing a monotonic reading. Milliseconds are a **floored projection**, never the representation. ADR-0026's prediction held exactly: one call replaced in one adapter, five construction sites touched, and the observability property tests needed no edit. ADR-0034 and ADR-0035. Delivered with it, as tooling rather than phase scope and on the ADR-0032 pattern: a deterministic sharded-execution gate, ADR-0036 — `pytest-xdist` refused on condition 3 and routed to Phase 014, with its declared-support gap against Python 3.14 recorded in the ledger so that review starts from what was already checked. Commits `0e31ba8` and `5730ab7`, pushed. **CI is confirmed working, including the new job:** run `31830877438` passed all four jobs on `0e31ba8`, and run `31832682805` passed all five on `5730ab7`. The `Sharded execution` job reported `sha256:7ef41f78c0af92a6ae138c4df4f4434da2190cdf170761ab34f6bc2b49a257a9` over 1084 tests in four shards of 271 — byte-identical to the local digest on a runner with a cold cache and no user-level toolchain, which is the evidence that the manifest digest and the shard deal are deterministic across machines. |
| Phase 010 | **Decimal and Numeric Precision Policy.** `precision.py` in the domain layer, and the arithmetic Phase 008 deferred. The whole phase turns on one **measured** fact (S-03): a `decimal.Context` *method* reads only the context it is called on and never touches thread-local state, whereas `localcontext` does. ADR-0031 refused exact arithmetic in the domain on the assumption that `localcontext` was the only route, so **ADR-0037 supersedes it** — the repository's first supersession, which needed four coordinated edits plus the index and the README's ADR count. `add`/`subtract`/`multiply` are **exact or refused**, never rounded; `Quantity` gains `+` and `-`; `Price` deliberately gains none, because a price difference is signed and signed money is Phases 155-156. `notional()` is a named function rather than `*` because the result changes denomination. **Four** rounding modes, not `decimal`'s eight, spelled `FLOOR`/`CEILING` rather than `DOWN`/`UP` so the meaning does not silently change when signed money arrives; `EXACT` is a member so every call site names one. A tick size and a step size are one undenominated `Increment` (ADR-0038), aligned by `divmod` rather than `quantize` — `quantize` cannot express a step of `25`, and `divmod` preserves the venue's stated scale. `EXACT_PRECISION = 128` is **derived** from Phase 008's bounds and a unit test rederives it. Two architecture tripwires: no ambient decimal context anywhere under `src/globin`, and no `.amount` read outside the domain layer — the latter is ADR-0030's own predicted failure turned into a gate. Delivered with it, as tooling rather than phase scope and on the ADR-0032 pattern: a test-evidence gate, `tools/quality/evidence/`. ADR-0037 and ADR-0038. Commits `a5e48b1` and `e2075f6`, pushed. **CI is confirmed working, including the new job:** run `31841628341` passed all six jobs on `e2075f6`. The `Test evidence` job reported `1310 tests, 98.86% coverage, 5 files written` and then `5 files verified`, and uploaded `test-evidence-windows-py314` at 120,088 bytes with the configured thirty-day retention — the evidence pipeline producing, verifying and publishing on a runner with a cold cache and no user-level toolchain, which is what makes it evidence rather than a local convenience. |
| Phase 011 | **011 — Identifier and Naming Registry.** `identifiers.py` in the domain layer and a one-function `identifiers.py` in adapters. The phase turns on a distinction the word *registry* hides: it registers **kinds**, never **instances**. `IdentifierKind` names the six the roadmap does — symbol, product, environment, run, model, order — and `specification(kind)` states each one's canonical form in one place. The registry is **load-bearing, not descriptive**: every type validates itself by calling it, so there is no second copy to drift. `SYMBOL` gets no new type and no restated bounds — its specification is *derived* from Phase 008's `CURRENCY_ALPHABET`, `SYMBOL_SEPARATOR` and length bounds, which is why no tripwire comparing them is needed. `specifications()` is a **function** because a layer package performs no call at import, which rules out a module-level table of dataclass instances. Five new types rather than one carrying a `kind` field, so `ProductId("spot") != EnvironmentId("spot")` falls out of the generated `__eq__` instead of relying on every call site remembering. `product_id("nosuchproduct")` succeeds, for the reason `Currency("ZZZQ")` does: which products a venue offers is Phase 033, what an environment *is* is Phase 035, the matrix is Phase 036, the instrument register is Phases 049-050. Two architecture tripwires, both enforcing rules that previously existed only in prose: no venue vocabulary as a live constant under `src/globin/domain` (docstrings excluded, so prose may name what code may not), and no source of randomness read there — `uuid`, `random` and `secrets` are absent from the I/O-capable list, so nothing else would have noticed. Delivered with it, as tooling rather than phase scope and on the ADR-0032 pattern: the evidence gate now records **five** gates rather than two (ADR-0040). The supplied brief described the evidence work Phase 010 had already delivered; an audit found three things genuinely missing, and those are what was added — Ruff and mypy findings as JSON, a coverage text summary and a browsable tree, and a `gates` section in the manifest at **schema version 2**, with the verdicts removed from `run` so a verdict lives in exactly one place. Every gate runs and the verdict is given afterwards, the one deliberate departure from fail-fast, documented as such in `QUALITY_GATES.md`. It also closed a leak that had shipped in Phase 010's artifacts — see the working rule on tool output below. ADR-0039 and ADR-0040. Commit `87075d8`, pushed. **CI passed all six jobs:** run `31848427550` on `87075d8`. The `Test evidence` job reported `5 gates, 1441 tests, 98.27% coverage, 9 files written` and then `9 files verified`, and uploaded `test-evidence-windows-py314` at 519,715 bytes — up from Phase 010's 120,088, which is the HTML tree and was stated as its cost rather than discovered afterwards. |
| Phase 012 | **012 — Serialization and Persistence Contracts.** `serialization.py` in the domain layer, a `Codec` port and a `JsonCodec` adapter, wired as `build_codec()`. The phase turns on one sentence, deliberately borrowed from ADR-0037: **serialization is exact or refused**. The case that forced it is `Instant`. `epoch_millis` *floors*, and ADR-0035 is right that it should for a request — a timestamp drifted into the future is the one an exchange rejects — but a record is read back and compared against itself, so flooring on the way in silently breaks `decode(encode(x)) == x`. `encode_instant` therefore **refuses** sub-millisecond precision instead of truncating; a caller who wants the floor writes `instant.epoch_millis`, which is one line and says so. The envelope generalises what `tools/quality/evidence/manifest.py` had proved by hand two phases earlier — `schema` plus `schema_version`, with an unknown version **refused rather than read** — and a contract test now compares the two spellings, since the tooling cannot import `globin`. Migrations advance exactly one version, because a step from 1 to 4 leaves 2 and 3 claimed as readable and never exercised. Compatibility is **two** independent answers, not a boolean, and the property test pins the duality: backward one way round is forward the other. `MonotonicReading` gets **no** encoder — its origin is undefined, so a stored reading is a number the reader cannot compare with anything — and a contract test asserts the absence, because an absence does not appear in a diff. Three `json` defaults that each break the round trip are closed rather than documented: non-string keys are silently coerced, `NaN`/`Infinity` are accepted though RFC 8259 defines neither, and floats are native. The identifier column width (64) is **derived** from the registry, closing the forward reference `identifiers.py` left for this phase. Delivered with it, as tooling rather than phase scope and on the ADR-0032 pattern: the aggregate CI gate, `tools/quality/workflow/` and a sixth job named `Quality gate` (ADR-0042). It exists because GitHub reports a job that never ran as *skipped*, and a skipped required check is not a failing one — so a rule trusting the check view could be satisfied by a run in which everything it depended on had failed. The check name carries no OS, interpreter or matrix value, so Phase 018 cannot break it. `upload-artifact`'s `artifact-digest` is captured as a job output and recorded outside the bundle, because an artifact cannot contain its own digest; file-level checksums stay inside it. ADR-0041 and ADR-0042. Commit `b644383`, pushed. **CI passed all seven jobs, including the new one:** run `31853639648` on `b644383`. The `Test evidence` job reported `5 gates, 1683 tests, 98.19% coverage, 9 files written` and uploaded `test-evidence-windows-py314` at 627,942 bytes. The `Quality gate` job then downloaded that artifact, confirmed its SHA-256 as `dffd98a3...`, re-ran `evidence verify` against the published bytes — `9 files verified` — recorded that digest in `aggregate-quality.json`, and printed a verdict for all five jobs and all five evidence gates before `[quality] overall: PASSED`. Both artifacts carry the configured thirty-day retention, expiring 2026-09-14. That is the two-layer integrity model working on a runner rather than in a test: the file checksums travelled inside the bundle, the bundle's own digest was learned after the upload and recorded outside it. |
| Phase 013 | **013 — Coding Standards and Documentation Conventions.** Delivered in two halves, a phase apart. The CI trust hardening landed first as tooling under ADR-0032 — action pins declared in a manifest the workflow is compared against, per-job timeouts, `merge_group`, and cancellation that spares master (ADR-0043) — with the phase left `Planned` and its own scope untouched. Phase 014 closed that scope: pydocstyle `D` is now selected under the **Google** convention, which resolves the D203/D211 and D212/D213 conflicts by argument rather than by an arbitrary ignore entry. 801 findings became 347 under the convention, then 55 once `D103` was exempted in `tests/**` — a category error outside a library, since a test function is public only in that nothing marks it private and its name is already a sentence. The *requirement* was dropped, not the practice: every other `D` rule still holds every docstring that exists to the package's standard. The last five were a real conflict — the formatter inserts a space when a docstring opens with a quotation mark, and `D210` forbids it — and were **reworded rather than suppressed**. Commits `c5cf451` and the Phase 014 commit. |
| Phase 014 | **014 — Dependency Review and Licence Audit Process.** `tools/quality/supply/`, the fifth gate package, and the process eleven places in the repository had been deferring to since ADR-0003. **The repository is now public** (ADR-0046) — that was the decision, and it was the owner's: every one of CodeQL, secret scanning, push protection, dependency review, attestations and rulesets refused with a plan ceiling while it was private, and going public unlocked all of them for nothing. Gated on a full-history scan first, because publishing exposes 32 commits rather than a working tree; 269 paths, 2.8 MB of diff, zero findings. The inventory reads three registers that describe one toolchain — the `dev` extra's lower bounds, the workflows' exact pins, the hook revision — and **compares them**. A correction to the first telling: the ruff pair was already compared, by `test_the_hook_ruff_and_the_ci_ruff_are_the_same_version` since Phase 004 — and that is the check which caught the first Dependabot pull request. What the inventory adds is generality: the old check names `ruff` in two regexes and would not notice a second hook. The SBOM is CycloneDX 1.7, generated here rather than by `cyclonedx-py`, because a tool that stamps a random serial and the wall clock cannot produce the same bytes twice; the serial is a UUIDv5 over the commit and the timestamp is the commit's own date, and the gate **builds it twice and compares** rather than asserting determinism. `pip-audit` is the first dependency adopted *through* the process rather than before it, at a measured cost of 7 declared packages becoming 26 audited. Three corrections found by running the thing: auditing the ambient environment measured the developer's machine rather than the repository; `--strict` exit 1 with empty stdout is a collection failure, not a finding count of zero; and `--offline` was a false name, because ADR-0024's socket guard does not cross a child process. ADR-0044 to ADR-0046. |
| Last completed | **015 — Security Baseline and Secret Handling Rules.** Two halves that the roadmap's title already contained. The **secret-handling rules** are `docs/security/SECURITY_BASELINE.md` (ADR-0048): a secret lives outside the tree in an OS-protected store, is referred to by name and never by value, reaches an environment variable only as a hand-off, and is redacted *while the record is constructed* rather than at any sink — the clause `observability.py` and `evidence/redaction.py` were already implementing without a document saying why. CI holding no secret became a rule rather than a circumstance. Nothing was built: the store is 028's and the credential flow 029's. The **security baseline** is the governance layer the public repository had been missing — `SECURITY.md`, `.github/CODEOWNERS`, an issue chooser that routes reports away from public issues, a security-impact section in the change template, and `docs/security/VULNERABILITY_RESPONSE.md`, a nine-state runbook with a deterministic five-band triage matrix that is explicitly **not** CVSS. Private vulnerability reporting was `{"enabled": false}` and was switched on — `PUT` returned `204`, read-back `{"enabled":true}` — which is what let the policy name a real channel instead of an invented address. A sixth gate package, `tools/quality/governance/`, compares `docs/engineering/governance.toml` against the tree in both directions; the platform half is two new controls on the *existing* capability probe rather than a second one. ADR-0047 and ADR-0048. |
| Next phase | **016 — Foundation Consolidation and Phase Gate Review.** Not started. It is the band's mandatory consolidation phase (roadmap rule 6): reconcile Phases 001-015, resolve inconsistencies and certify readiness for environment work. It is also the point after which ADR-0016's "third amendment" warning expires, so the amendment budget question is genuinely 016's to settle rather than to refuse. |
| Roadmap | [`ROADMAP.md`](ROADMAP.md); band skeleton in `src/globin/roadmap.py` |

**The roadmap has been amended three times.** Band ranges, phase numbers and band
width are unchanged by all three; amending phase scope requires an ADR.

- **Phase 003** originally read *Coding Standards and Static Analysis Baseline*;
  that scope moved into Phase 013.
  [ADR-0012](docs/adr/0012-phase-003-delivers-architecture-boundaries.md).
- **Phase 004** originally read *Test Architecture and Fixture Conventions*; it
  additionally absorbed the quality gates from Phase 013, which now reads
  *Coding Standards and Documentation Conventions* and keeps the conventions
  those gates enforce.
  [ADR-0016](docs/adr/0016-phase-004-absorbs-the-quality-gate-scope.md).
- **Phase 005** originally read *Error Taxonomy and Exception Hierarchy*; it
  still delivers that and now also the deterministic testing foundation. This
  amendment *widens* a phase instead of moving scope between two: nothing is
  displaced, nothing deferred, no other title changes.
  [ADR-0021](docs/adr/0021-phase-005-widens-to-include-the-test-foundation.md).

ADR-0012 warned that a second amendment without strong justification would be
the signal the first was wrong. ADR-0016 is that second amendment, answers the
warning directly, and said a third before Phase 016 should be treated as evidence
the roadmap is being used as a backlog.

**ADR-0021 is that third amendment.** It was put to the owner as one of four
explicit options with the conflict named, and it is the only one under which no
phase is displaced. It does not licence a fourth: the argument turns on four
conditions holding at once — nothing displaced, nothing deferred, no phase owning
the work, and the two halves needing each other — and an amendment that cannot
state all four is not covered by it. **A fourth before Phase 016 should be
refused rather than argued.**

**A fourth was proposed in Phase 006 and refused.** The owner's brief for the
phase described deterministic quality gates, static analysis, typing, branch
coverage and a cross-platform CI backbone — the scope `ROADMAP.md` assigns to
Phase 004 (`Complete`) and Phase 013. An audit against the brief found every
item already delivered except a Linux CI runner. Redefining Phase 006 would have
displaced *Structured Logging Foundation* from a band whose sixteen slots are
all occupied, failing three of ADR-0021's four conditions. The conflict was put
to the owner with four options; he chose to deliver the roadmap's phase as
written. Two decisions were taken with it, both deliberate and both his:

- **CI stays Windows-only.** The brief asked for at least one Linux runner.
  `quality.yml` argues Windows is the only platform GLOBIN declares (ADR-0009)
  and the only one exercising the `.gitattributes` CRLF rules. Left standing.
- **The coverage floor stays at 95** while measured coverage is far higher,
  because `QUALITY_GATES.md` calls the floor a regression detector rather than a
  target and ADR-0021 already recorded that gap as deliberate.

Do not re-open either as though it were an oversight.

**A fifth was proposed in Phase 007 and refused, on the same grounds.** The
owner's brief for the phase described deterministic test architecture, fixture
isolation, property-based testing and a default-deny network guard — the scope
Phase 004 and Phase 005 already own, both `Complete`. ADR-0021 records that this
same brief arrived once before, at Phase 005, and was delivered then. An audit
found every item present, and six live forward references pinned Phase 007 to the
configuration model, one of them a comment in `domain/observability.py`. The
conflict was put to the owner with four options; he chose the roadmap's phase
plus the brief's genuine residue. One decision was taken with it:

- **The offline guard was left exactly as it is.** The brief asked for
  `bind`/`listen`/`accept`/`sendto` and DNS to be blocked as well.
  [ADR-0024](docs/adr/0024-tests-are-offline-and-isolated-by-construction.md)
  evaluated lower-level blocking and rejected it as "too broad", and records the
  remaining bypass routes as knowingly accepted risk. Those are decisions, not
  gaps; widening the guard would need an ADR superseding ADR-0024, which would be
  the repository's first supersession. Not worth spending out of a configuration
  phase. Do not re-open it as an oversight either.

The residue that *was* delivered — an `integration` command in the quality table,
and a written test-data and factory contract in `TESTING_STRATEGY.md` — is defect
repair against Phases 004 and 005, not a widening of Phase 007.

**A sixth was proposed in Phase 008 and also refused — but this time something
was added beside the phase rather than instead of it.** The owner's brief
described executable architecture contracts, regression fixtures, deterministic
test selection and mutation testing. An audit found every item delivered except
two: serialization round-trip contracts, which **Phase 012 owns**, and mutation
testing, which **no phase in the programme owns at all**. The conflict was put to
the owner with four options; he chose the roadmap's phase as written *plus* the
mutation gate as **tooling**, on the condition that the permission be written
down. [ADR-0032](docs/adr/0032-verification-tooling-may-be-added-outside-phase-scope.md)
is that record. It is **not a fourth amendment**: no phase is renamed, no status
moves, and the count above stays three. It states six conditions — displaces no
phase, defers nothing, adds no dependency, adds no runtime capability, only
reports, and is documented and tested like everything else — and an addition that
cannot state all six is a scope amendment wearing a different word.

That permission has now been used five times. The first four were the mutation
gate at Phase 008, the evidence gate at Phase 010, at Phase 011 the extension of
the evidence gate to record lint and typing as well
([ADR-0040](docs/adr/0040-evidence-records-every-gate-and-its-schema-version-is-a-contract.md)),
and at Phase 012 the aggregate CI gate
([ADR-0042](docs/adr/0042-one-aggregate-check-decides-a-run-and-the-artifact-digest-lives-outside-the-artifact.md)).
Each of those four states all six conditions. The fifth, at Phase 013, does not —
see below. **The seventh brief collision was resolved the
same way as the sixth** — the roadmap's phase as written, and the tooling beside
it rather than instead of it — because the Phase 011 brief described the evidence
work Phase 010 had already delivered. **The eighth was resolved the same way
again**: the Phase 012 brief described CI quality-gate aggregation, an audit found
roughly seventy per cent of it already delivered by Phases 004 to 011, and the
part nothing in the programme owns became tooling beside *Serialization and
Persistence Contracts* rather than instead of it. The owner was given the four
options and chose that one.

**The ninth collision was resolved differently, and the difference matters.** The
Phase 013 brief described CI security hardening; the roadmap assigns Phase 013 to
*Coding Standards and Documentation Conventions*. Most of the brief was already
delivered by Phase 012, and the owner chose to build the remainder as tooling with
Phase 013 left `Planned` and unstarted.
[ADR-0043](docs/adr/0043-ci-trust-is-declared-in-a-manifest-and-every-job-is-bounded.md)
is that record, and it is the **first use of ADR-0032 that cannot state all six
conditions**. Condition 2 requires the phase's own deliverable in the same commit;
here the tooling lands *before* the phase rather than beside it. The other five
hold. The deviation is stated in the record rather than argued around, and the
limit on it is that Phase 013's scope is untouched — the status is still `Planned`,
`LAST_COMPLETED_PHASE` is still 12, and the pydocstyle rules Phase 004 parked are
still parked. **If this recurs, condition 2 should be rewritten to say what it
means rather than be read past a second time.**

**Nothing so far implements trading.** No exchange connection, no credentials,
no market data, no strategy, no models. Anything claiming otherwise is wrong.

---

## Binding policies

| Policy | Rule | Reference |
|---|---|---|
| Venue | Binance Global only. No other exchange, no regional deployment. | ADR-0002 |
| Budget | **zero-budget runtime.** Free and open components only. No paid APIs, data, databases, queues, monitoring or cloud compute. Development *tooling* is exempt; the runtime is not. | ADR-0003 |
| Data sources | Officially documented APIs, SDKs, streams and public datasets only. **No scraping**, no browser automation, no undocumented private endpoints. | ADR-0004 |
| Branch | All work on `master`; pushed to `origin/master` after every completed phase. | ADR-0005 |
| Risk | Absolute ceilings are immutable and outside the optimisation search space. | ADR-0008 |
| Autonomy | Candidates reach live influence only through evidence gates the system cannot weaken. | ADR-0007 |
| Claims | No prediction is ever presented as guaranteed. The objective is a probabilistic edge after realistic costs. | — |

---

## Runtime environment

- Target host: a **single Windows computer**, consumer hardware, ~100 Mbps wired.
- An **NVIDIA GPU may be present.** Acceleration is applied only where measured
  benefit exists. Notably, LightGBM's CUDA backend is **not supported on
  Windows** — a concrete reason blanket GPU policies are wrong here.
- Not a high-frequency context: tens of trades per hour at most. Reliability
  outranks latency.
- Interpreter floor is **Python 3.12**, set by XGBoost's requirement — the
  strictest among the planned stack.

---

## Architectural invariants

1. **Product and environment are independent dimensions.** Binance has three
   non-production concepts, not one: testnet (separate infrastructure, own keys,
   monthly resets, `/api` only — no `/sapi`), demo mode (production
   infrastructure, virtual balances, Spot only), and internal simulation.
   Coverage differs per product. An unmapped combination is **refused**, never
   downgraded to production. (ADR-0006)
2. **A timeout or 5XX does not prove failure.** Binance documents execution
   status as unknown in that case. Resolution is by querying authoritative state
   and reconciling — never by assumption.
3. **Rate limits are correctness, not etiquette.** Three limit types, usage
   reported in `X-MBX-USED-WEIGHT-*` and `X-MBX-ORDER-COUNT-*` headers, HTTP 429
   on breach and 418 for bans up to three days. Limiting is proactive.
4. **Point-in-time correctness is structural.** Leakage is uniquely dangerous
   because it *improves* apparent results, so it must be impossible by
   construction rather than caught by review.
5. **Rules are enforced by tests**, not merely written down.
6. **Dependencies point inward.** `runtime` → `adapters` → `application` →
   `ports` → `domain`, never the reverse. `domain`, `ports` and `application`
   reach no I/O-capable module, importing any layer performs no work, and
   concrete implementations are constructed only in `globin.runtime`. The
   permitted directions live in `docs/architecture/dependency-rules.toml` — the
   canonical matrix, with no second copy. (ADR-0013, ADR-0014, ADR-0015)

---

## Future launcher contract

Two entry points will eventually exist — `start_windows_paper.bat` and
`start_windows_live.bat` — and are **not implemented yet**. When built, the
selected profile is authoritative: there is no hidden second toggle that makes
the documented live launcher inert. "All features active" means the orchestrator
has the profile's subsystems enabled and *scheduled*, not that every expensive
job runs simultaneously. (ADR-0009, Phases 289-304)

---

## Working rules

- **Verify before committing:** `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`
  runs `python -m tools.quality full` — lint, format check, type check and the
  branch-coverage suite — then inspects the branch and working tree. There is no
  reviewer on a master-only workflow, so this is the gate.
- **The checks are defined in one place**, `tools/quality/commands.py`. The local
  gate, the pre-commit hook and CI all read that table; none keeps its own list.
  Adding a check means editing the table, not three callers.
- **`--strict-markers` in `addopts` does not work.** pytest downgrades an
  unregistered marker to a warning in that form; only the `strict_markers` ini
  option is enforced. The repository carried the ineffective form from Phase 001
  until Phase 004 tested it. A configuration that is present and spelled
  correctly can still be inert, which is why gates are exercised rather than
  asserted to exist.
- **A layer package may perform no call at import, and the check follows class
  bodies.** That rules out `frozenset({...})`, `auto()`, `field(default_factory=...)`
  and — the one that catches people — a nested dataclass default such as
  `logging: LoggingConfig = LoggingConfig()`, which is why `GlobinConfig.logging`
  is a required field and `default_config()` is a function.
- **Configuration validation lives in `globin.domain.configuration`, never in an
  adapter.** An adapter parses and flattens; it never interprets a value. Phase
  027 adds sources, and each must inherit these rules rather than write a second
  copy (ADR-0027).
- **`resolve` never raises, and a property test asserts it.** Refusal belongs to
  `as_config`, where the origin of a value can be named. Adding a schema check
  inside the fold breaks that test, which is the intended enforcement (ADR-0028).
- **`tests/contract/test_observability_contract.py` parses `LOGGING_POLICY.md`
  with a regex matching any table row whose first cell is an all-caps backticked
  token**, and compares the set to `Severity`. Adding such a row to that document
  fails a test whose message is about severities and names nothing to do with the
  change.
- **A deliberately malformed fixture cannot be committed.** `check-toml` and
  `check-yaml` run over every file in the tree, so an invalid document is written
  into `tmp_path` at run time instead.
- **A number written in prose is bound to its source.** The README's ADR count
  and phase line, the package docstring's maturity line, the `ROADMAP.md` banner,
  the `QUALITY_GATES.md` command table, the `TESTING_STRATEGY.md` marker and
  test-module tables, and the `CONTRIBUTING.md` toolchain list are each compared
  against the thing they describe. Two of them had already drifted when the
  checks were added in Phase 007 — the strategy table was missing the Phase 003
  and 005 property modules, and `CONTRIBUTING.md` had called a five-item list
  "four" since Phase 005. Adding a document that restates something the code
  knows means adding the comparison with it.
- **Every completed phase** ends with tests passing, documentation synchronized,
  a commit on `master`, a successful push, matching local and remote hashes, and
  an empty `git status --porcelain`. The canonical checklist is
  [`docs/engineering/DEFINITION_OF_DONE.md`](docs/engineering/DEFINITION_OF_DONE.md).
- **When two artefacts disagree**, apply
  [`docs/engineering/SOURCE_OF_TRUTH.md`](docs/engineering/SOURCE_OF_TRUTH.md):
  code and its tests rank highest for behaviour, ADRs for permission. A conflict
  is a defect to fix, not merely to route around (ADR-0011).
- **Marking a phase complete requires two edits**, deliberately: the status in
  `ROADMAP.md` and `LAST_COMPLETED_PHASE` in `tests/contract/test_roadmap_contract.py`.
  The constant is a tripwire — raise it only for a phase genuinely delivered. A
  phase adding a research ledger needs a third: `REQUIRED_DOCS` in
  `tests/contract/test_documentation_contract.py`.
- **Tests are offline and process-isolated by fixture, not by convention**
  (Phase 005). An autouse fixture in `tests/conftest.py` refuses outbound
  sockets; another fails any test that leaves an environment variable or the
  working directory changed. Use `monkeypatch.setenv` and `monkeypatch.chdir`.
- **An autouse fixture must not depend on `monkeypatch`.** pytest hoists an
  autouse fixture's dependencies to the front of the closure, so `monkeypatch`
  would then tear down *last* — after the isolation guard has inspected the
  environment — and every `monkeypatch.setenv` would be reported as a leak. The
  network guard saves and restores by hand for this reason (ADR-0024).
- **`PYTEST_CURRENT_TEST` is rewritten by pytest at every test phase**, so any
  environment comparison across a test must exclude it or it fires on every test.
- **Commit and push at phase end are pre-authorized by the owner.** Do not ask
  for permission to deliver a completed, verified phase — just do it. The
  authorization covers delivery only; verifying that the phase really is
  complete and clean beforehand is still required.
- **`Decimal` arithmetic reads a thread-local context and can round silently;
  comparison cannot.** `Decimal('1E+30') + Decimal('1E-30')` returns `1E+30`,
  discarding the addend, while two 31-digit values compare correctly under
  `prec=3`. That split is the entire reason Phase 008's value types order and
  compare but define no arithmetic operator (ADR-0031).
- **Never subclass `Decimal` to make a unit type.** With `class P(Decimal)` and
  `class Q(Decimal)`, `P('2') == Q('2')` is `True` and `P('2') + Q('3')` is a
  plain `Decimal` — the two would be interchangeable exactly where it matters.
- **`isinstance(True, int)` is `True` and `Decimal(True)` is one**, so a `bool`
  guard must precede an `int` guard. **`Decimal('-0').is_signed()` is `True`
  while `Decimal('-0') == 0` is also `True`**, so a non-negativity check is
  `is_signed()` and never `< 0`.
- **A refusal that consults `decimal.getcontext()` is hidden global state.**
  `is_subnormal()` is defined against the ambient `Emin`, so Phase 008 bounds
  magnitude with `adjusted()` — documented as context-free — instead. The whole
  validator accepts identical values under any thread-local precision, and a
  test asserts it.
- **mypy accepts `return NotImplemented` from a `-> bool` comparison dunder**
  under this repository's flags. No `type: ignore` is needed. It also reports
  `Price == Quantity` as a non-overlapping comparison, so a test asserting the
  runtime behaviour has to route one operand through `object`.
- **pytest's `pythonpath` ini entries land at `sys.path[0]`**, resolved against
  rootdir, *after* the interpreter has processed `PYTHONPATH` — verified in
  `_pytest/config/__init__.py`. So `PYTHONPATH` cannot shadow `src/`. The
  mutation harness copies `pyproject.toml` into its sandbox and runs the child
  from there for this reason, and proves it on every run with a canary that
  replaces the target module with `raise ImportError` and requires the subset to
  fail.
- **Do not set `PYTHONNOUSERSITE` for a child process on this machine.** The
  toolchain is installed at user level, so it makes the child unable to find
  pytest. The mutation harness's unmutated control run caught this immediately,
  which is what that control is for.
- **Mutation testing finds what coverage cannot, and the first run proved it.**
  A cross-type comparison test matching `"not supported between instances"`
  accepted a mutant whose message named `Decimal` and `NoneType` instead of the
  two value types. Every line still executed, so coverage was unchanged.
  Tightening the assertion killed eight mutants.
- **The mutation baseline compares the survivor *set*, both ways, and pins no
  count.** A new survivor fails; a recorded survivor that a run kills also fails,
  on the same reasoning as `xfail_strict`. Nothing writes the file — `tomllib`
  cannot emit TOML — so a stale baseline is corrected by a person, and the block
  the tool prints is filled with a placeholder a contract test refuses.
- **`time` is I/O-capable in the dependency contract; `datetime` deliberately is
  not.** `time` holds no value type, so every reason to import it in an inner
  layer is a reason to read the host. Banning `datetime` would make invariant 25
  unimplementable, since "timezone-naive datetimes must not cross a domain
  boundary" presupposes that aware ones do. The gap that leaves —
  `datetime.now(UTC)` in the domain — is closed by an AST rule in
  `tests/architecture/test_clock_discipline.py`, not by the import list.
- **Ruff's `DTZ` rules enforce awareness, never location.** `datetime.now(UTC)`
  inside the domain layer passes every one of them. Anyone proposing to delete
  the clock-discipline test because "the linter already covers it" is wrong, and
  this is the sentence that says why.
- **A `tzinfo` is arbitrary caller-supplied code.** `datetime.utcoffset()` raises
  `TypeError` if it returns a non-`timedelta` and `ValueError` if the offset
  exceeds a day, and `astimezone` raises `OverflowError` within a day of either
  end of the calendar. All three are translated into `ValidationError`, because
  none is a `globin.errors` type and ADR-0022 requires one at a boundary.
- **`datetime.timestamp()` is a float and is not exact at the extremes.**
  Measured: `datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)` is
  `253402300799999999` microseconds after the epoch, and `timestamp()` gives
  `253402300800000000` — a moment that does not exist. Conversions go through
  `timedelta` integer arithmetic instead.
- **No test may assert that two real clock readings differ**, only that the later
  is not smaller. The declared host resolves to `1e-07`, but a Windows host
  falling back to `GetSystemTimeAsFileTime()` is granular to about 15.6 ms and
  returns the same value twice. Distinctness comes from `ManualClock`.
- **`MonotonicReading.since` takes `object`, not `MonotonicReading`.** Annotated
  with the narrow type, mypy proves the runtime guard unreachable and refuses the
  module; without the guard, passing an `Instant` raises `AttributeError` out of a
  domain boundary. The same trade `values.py` makes in its comparison helpers.
- **Ruff's `SIM300` fix flips `a < b` into `b > a`.** That is not equivalent when
  the test exists to record *which* operand is on the left — Python tries the left
  operand's dunder first. The clock contract's operation matrix carries `noqa`
  for exactly that reason.
- **An ADR's `## Supersedes` section is machine-parsed.** Writing "this does not
  supersede ADR-NNNN" in it makes the suite read a supersession claim and fail.
  Say it in the Context instead.
- **A shard child must pass `--cov-fail-under=0`.** `pytest-cov` falls back to
  `fail_under` from `[tool.coverage.report]`, which is 95 here. A shard measures a
  fraction of the suite — measured, one quarter reaches 87.43% — so without the
  flag every shard exits 1 and the gate reports a broken suite while nothing is
  broken.
- **`pytest @file` is argparse's `fromfile_prefix_chars`.** It splits on
  `splitlines` and returns each line verbatim, so a blank line becomes an empty
  positional argument, and a line starting with `@` is expanded as another file.
  It is also a necessity rather than a convenience on Windows: 963 node IDs are
  roughly 60 KB of argv against a 32 767-character limit.
- **pytest escapes special characters inside a parametrised node ID**, so IDs
  legitimately contain backslashes — a newline in a fixture appears as a literal
  `
`, `ç` as `ç`. Four IDs in this repository are spelled that way. Refuse a
  backslash in the *path* part only; the manifest parser's count self-check
  against pytest's own total is what caught the first version dropping all four.
- **pytest exits 4, loudly, for a node ID that no longer exists**, rather than
  skipping it. That makes collection drift observable. Exit 5 — no tests
  collected — is the one that must never be read as success.
- **A tool's own output leaks this machine's paths.** `ruff check .
  --output-format=json` reports each `filename` as an **absolute** path even when
  the target given is `.`, and `coverage xml` writes the repository root into a
  `<source>` element. Every absolute path on this host contains the account
  holder's full name, and `.globin/evidence/` is uploaded to GitHub Actions —
  so the leak was real and shipped in Phase 010's artifacts. Everything written
  now is reduced to repository-relative POSIX, the raw `run.coverage` database is
  deleted once the reports are made because it is binary and cannot be
  normalised, and `redaction.py` fails verification if an absolute path survives.
  Note `relative_files` in `[tool.coverage.run]` is **not** the fix: ADR-0036
  decision 6 refuses that key because it would change what `coverage` and `full`
  do.
- **A gate that starts a child must have that child installed in CI.** The
  evidence job installed neither Ruff nor mypy, and adding them to the gate would
  have failed CI at the preflight with exit 127 — a workflow mistake that reads
  like a gate failure. `test_evidence_contract.py` now compares the tools the gate
  starts against the job's own `pip install` line.
- **An action pin's version comment is checked, and it was wrong twice.** The SHA
  executes and the trailing `# vX.Y.Z` does not, so from Phase 012 until Phase 013
  `actions/checkout@fbc6f39` was labelled `v5.0.0` when it is `v5.1.0`, and
  `actions/setup-python@ece7cb06` was labelled `v6.0.0` when it is `v6.3.0`. Both
  came from pinning a moving major tag and writing that major's first release
  beside it. `docs/engineering/action-pins.toml` now records what was verified and
  `test_ci_security_contract.py` compares it against the workflow both ways.
  Changing a pin means resolving the tag against **two** sources that agree — the
  REST API and `git ls-remote` — and updating workflow, comment and manifest in
  one commit. Correct a wrong comment; never "correct" it by moving the SHA, which
  is an upgrade and belongs to Phase 014.
- **Everything a gate prints must be ASCII.** A Windows console is frequently not
  UTF-8, and the first CI log the sharding gate produced rendered its em dashes as
  replacement characters. `LOGGING_POLICY.md` reached the same conclusion for log
  records from the other direction. `test_execution_contract.py` now walks the
  `print` arguments and `msg` assignments of that package and refuses non-ASCII.
- **`gh` lives at `%LOCALAPPDATA%/Programs/gh/bin/gh.exe`**, extracted from the
  official release zip rather than installed system-wide, and it is **not on
  `PATH`** — invoke it by full path. The token is in the Windows keyring
  (`aydhn`, scopes `gist`, `read:org`, `repo`, `workflow`), so it survives the
  executable being absent; that is why Phase 008 could read a run and Phase 009
  initially could not.
- **Never** commit credentials. **Never** report a check as passing without
  running it. **Never** implement a later phase early. **Never** delete working
  functionality to simplify a task.

---

## Environment notes for this machine

- Git identity is configured **repository-locally** (`aydhn`,
  `108704389+aydhn@users.noreply.github.com`), leaving the global config
  untouched.
- The system Git config sets `core.autocrlf=true`; `.gitattributes` overrides it
  so the repository always stores LF while Windows scripts check out as CRLF.
- `pytest`, `pytest-cov`, `ruff`, `mypy` and `pre-commit` are installed at user
  level; no virtual environment exists yet by design (Phases 17-32). The
  `pre-commit` executable is not on `PATH`; invoke it as `python -m pre_commit`.
- The CI workflow pins exact tool versions matching this machine. Those pins are
  a reproducibility measure, not a lockfile; Phase 020 owns the real one.
- No packaging build has been run. Build verification is deferred to Phases
  17-32 and must not be described as verified before then.
