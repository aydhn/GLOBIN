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
| Completed phases | **001-006** |
| Phase 001 | **Repository Foundation and Engineering Contract.** Validation passed and commit `c7504c4` was pushed to `origin/master`; local and remote verified identical and the tree left clean. |
| Phase 002 | **Documentation System and Style Guide.** Established the engineering contracts under `docs/engineering/`, the documentation authority order (ADR-0011), the ADR template, and the GitHub change templates. Commit `9c46313`, pushed. |
| Phase 003 | **Architecture Boundaries and Dependency Direction.** Five layers under `src/globin/`, the inward dependency contract in `docs/architecture/dependency-rules.toml`, C4 system context and container views, the ADR lifecycle with supersession rules, and `tests/architecture/test_architecture_contract.py` enforcing all of it. Commit `990e5f4`, pushed. |
| Phase 004 | **Test Architecture and Quality Gates.** Five test levels as directories under `tests/`, markers derived from the directory, `tests` as a package with helpers in `tests/support.py`; explicit mypy flags in place of `strict = true`; branch coverage gated at 95; `.pre-commit-config.yaml`; the canonical entrypoint `tools/quality`; and a SHA-pinned, least-privilege, verification-only CI workflow. Commit `abb96a9`, pushed. **CI is confirmed working:** the first run on that commit succeeded on both Python 3.12 and 3.14, and the pre-commit job passed. The phase was reported before that run existed, so ADR-0020 and the Phase 004 research ledger still describe the workflow as never executed — correct for their date, and superseded by this row. |
| Phase 005 | **Error Taxonomy and Deterministic Test Foundations.** `globin.errors` — one root, five categories divided by who must act — replacing the ad-hoc `ValueError` scheme in the adapters and domain layers. Plus a `property` taxonomy level with Hypothesis, autouse fixtures that refuse outbound sockets and fail a test leaking process state, the `create_autospec` rule for mocks, and the `external` deselection that Phase 004's marker description had promised but nothing performed. ADR-0021 to ADR-0024. Commit `7f65d25`, pushed. |
| Last completed | **006 — Structured Logging Foundation.** `observability.py` in all four layers plus `build_logger` in the composition root: a `LogEvent` domain value that redacts itself in `__post_init__`, a one-method `LogSink` port, an immutable `Logger` whose `bind` returns a new logger, and a `StreamLogSink` writing JSON Lines. Correlation is explicit, never a context variable; the timestamp is stamped by the adapter so Phase 009 keeps the clock decision. `docs/LOGGING_POLICY.md` owns the severity meanings and the redacted-name list, and a contract test compares that document against the code in both directions. ADR-0025 and ADR-0026. Commit `9913edb`, pushed. |
| Next phase | **007 — Configuration Model and Schema Contract.** Not started. |
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
