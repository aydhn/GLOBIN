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
| Completed phases | **001** |
| Last completed | **001 — Repository Foundation and Engineering Contract.** Validation passed and commit `c7504c4` was pushed to `origin/master`; local and remote verified identical and the tree left clean. |
| Next phase | **002 — Documentation System and Style Guide.** Not started. |
| Roadmap | [`ROADMAP.md`](ROADMAP.md); band skeleton in `src/globin/roadmap.py` |

**Phase 1 does not implement trading.** No exchange connection, no credentials,
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
  runs import, `pytest`, `ruff check`, `ruff format --check` and `mypy --strict`.
  There is no reviewer on a master-only workflow, so this is the gate.
- **Every completed phase** ends with tests passing, documentation synchronized,
  a commit on `master`, a successful push, matching local and remote hashes, and
  an empty `git status --porcelain`.
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
- `pytest`, `pytest-cov`, `ruff` and `mypy` are installed at user level; no
  virtual environment exists yet by design (Phases 17-32).
- No packaging build has been run. Build verification is deferred to Phases
  17-32 and must not be described as verified before then.
