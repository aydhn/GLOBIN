# GLOBIN Roadmap — 320 Phases

This is the fixed development programme for GLOBIN. It is a contract, not a
suggestion.

## How to read this document

The programme is divided into **twenty bands of exactly sixteen phases**. The
band boundaries are immutable and are additionally encoded in
[`src/globin/roadmap.py`](src/globin/roadmap.py) so that this document and the
codebase cannot drift apart — `tests/contract/test_roadmap_contract.py` checks one
against the other.

Every phase row is machine-parsed. The table shape below is therefore part of
the contract:

| Column | Meaning |
|--------|---------|
| Phase | Zero-padded three-digit phase number, unique across the programme |
| Title | Short unique name for the phase |
| Purpose | What the phase must deliver |
| Status | `Planned`, `Active`, or `Complete` |

### Rules

1. The twenty band ranges must never change.
2. Every phase number from 001 to 320 appears exactly once, in ascending order.
3. Phase titles are unique across the whole programme.
4. A phase is marked `Complete` only after its tests pass, its documentation is
   synchronized, and its commit is pushed to `origin/master`.
5. Later phases are not implemented early. Scope leakage is a defect — see
   [`AGENTS.md`](AGENTS.md).
6. Each band ends with a consolidation and gate-review phase. That phase exists
   to pay down inconsistency before the next band builds on top of it.

> **Phases 001-033 are complete. Phase 034 is next and has not started.**
> Nothing beyond Phase 033 is implemented. The environment band is closed and
> frozen as `v0.2.0`; what that certifies, and the one criterion it could not,
> are in
> [`docs/release/ENVIRONMENT_ACCEPTANCE.md`](docs/release/ENVIRONMENT_ACCEPTANCE.md). GLOBIN does not trade, does not
> connect to any exchange, and **holds no credentials** -- it now has somewhere to
> put one and a way to be handed one, which is still a different thing. See
> [`README.md`](README.md).
>
> **Phase 028 built the secret store, and measured what Windows would not tell it.**
> The Credential Manager, reached through `ctypes` with no new dependency: a reference
> is ordinary data and a value has no string form, no encoder, no `__dict__` and no
> hash. One key builder folds case, because the platform's target names are
> case-insensitive and the collision is **silent** -- a credential written under one
> spelling is returned for another with no error. Rotation is constructed rather than
> inherited: a Windows write *replaces*, so the previous value is moved aside before
> the new one lands, or step 3 would retire something already gone. Two facts the
> documentation does not carry were measured: the oversize failure is an **undocumented**
> `RPC_X_BAD_STUB_DATA`, and an **RSA-4096 key in PEM form does not fit** the 2560-byte
> ceiling at all. See [`docs/security/SECRET_STORE.md`](docs/security/SECRET_STORE.md).
>
> **Phase 029 gave GLOBIN a way to be handed a credential, and a way to refuse
> to use one.** Collection is interactive only -- a pipe is refused **before**
> `getpass` is called, because accepting one puts material in shell history --
> and a platform that cannot suppress echo aborts **before the operator types
> anything**, since `getpass` warns before it reads. Permission verification is
> containment against a declaration, and `VerificationState` deliberately has
> **no member meaning confirmed**: GLOBIN reaches no venue, so the rule that a
> capability is a recorded state rather than a pass is enforced by there being
> nothing to write. A demanded `transfer` is `WITHHELD` **whatever the
> declaration says**. `required` is still empty, and now empty by *derivation* --
> the registry exists, and Phase 038 fills it.
>
> **Alongside it, and as the thirteenth scope amendment, the dependency
> attestation.** Until now a running GLOBIN read every distribution's metadata
> and **threw the version away**, so an environment two releases from its lock
> reported ready. It now carries an inventory, a fingerprint that cannot see the
> lock's producer, and the caller that finally sets `DEPENDENCY_UNREADY` -- a
> readiness word declared at Phase 027 that nothing had ever set. `packaging` was
> adopted as a runtime dependency, which reverses ADR-0052 decision 9 and cost
> nothing: it was already in the lock as a transitive. It brought
> `packaging.pylock`, a complete PEP 751 implementation, so the second reader is
> the **reference** one and the tripwire now checks the delivered Phase 020
> parser against the specification. The materialization gate reaches no network
> because `plan.py` imports nothing that could.
>
> **Alongside it, and as the twelfth scope amendment, the environment capability
> inventory.** Native architecture is separated from process architecture, and only
> `IsWow64Process2` may answer the first -- Microsoft documents `GetNativeSystemInfo`
> as reporting an ARM64 host *as if it were x86*, so where the modern API is absent the
> answer is **`UNKNOWN` rather than a guess**. An unmeasurable required capability
> **degrades rather than blocks**, which is what keeps a supported host startable.
> The compatibility fingerprint excludes volatile fields **by type**: it is computed
> over a projection with nowhere to put a timestamp, rather than over a snapshot with a
> denylist somebody must remember to extend. See
> [`docs/engineering/ENVIRONMENT_CAPABILITY.md`](docs/engineering/ENVIRONMENT_CAPABILITY.md).
>
> **Phase 026 gave configuration a place to live, and gave GLOBIN a way to measure
> itself.** `config/` holds a base document and four profiles, and **nothing
> searches** -- given a layout and a profile the candidate documents are a pure
> function of the two, because a search order *is* a precedence and precedence is
> Phase 027's. A profile names a **document**, not an environment: `as_config`
> refuses every key outside the register, so a profile document is structurally
> incapable of asserting what an environment is. The four set nothing, and a
> contract test asserts they fold to exactly the declared defaults.
>
> **Alongside it, and as the tenth scope amendment, the telemetry foundation.**
> Every attribute key declares a bounded value set, so the most series a metric can
> produce is a **product computable when the descriptor is written** -- a descriptor
> that could exceed its own budget cannot be constructed. Export is off by default
> and "off" is an object graph rather than a flag: no exporter, queue, pump or
> thread exists, so opening no socket is structural. The Prometheus listener binds
> `127.0.0.1` as a **literal** with no address setting, because the library's own
> default is every interface. See
> [`docs/engineering/RUNTIME_TELEMETRY.md`](docs/engineering/RUNTIME_TELEMETRY.md)
> and [`docs/engineering/CONFIGURATION_LAYOUT.md`](docs/engineering/CONFIGURATION_LAYOUT.md).
>
> **Phase 022 verified the scientific stack, and gave GLOBIN somewhere to live.**
> `python -m tools.quality stack` recomputes what
> [`docs/engineering/stack-contract.toml`](docs/engineering/stack-contract.toml)
> declares against this environment — four registers of a version held against
> each other, each artefact's own record of the wheel it came from, and **seven
> behaviour probes** run against the real libraries, each defending a rule written
> down elsewhere in this repository. `numpy` and `pandas` left the wheel survey in
> the same commit: that file asks whether a wheel *exists*, and once a library is
> installed the remaining question is whether it *computes*. **Nothing under
> `src/globin` imports either, and a tripwire fails if anything starts** — Phases
> 113-128 own the numeric type indicators use, and `PRECISION_POLICY.md` rule 1 is
> a one-way door cheapest to hold now. See
> [`docs/engineering/SCIENTIFIC_STACK.md`](docs/engineering/SCIENTIFIC_STACK.md).
>
> **Alongside it, and as the sixth scope amendment, the runtime filesystem and the
> process lifecycle.** GLOBIN now keeps mutable state in a user-local tree —
> `state`, `cache`, `run`, `tmp` — publishes every small document atomically,
> guarantees one coordinator per machine with a real operating-system lock, and
> shuts down in a fixed order that is reached whatever the application did.
> **The presence of a lock file is never evidence that GLOBIN is running**: a
> crashed process leaves one behind, so ownership is decided by an acquisition and
> by nothing else. Four checks joined the bootstrap and three exit codes joined its
> contract. This is the weakest amendment in the programme by ADR-0021's test —
> one of four — and
> [ADR-0057](docs/adr/0057-phase-022-widens-to-deliver-the-runtime-filesystem-and-lifecycle.md)
> says so rather than arguing it. See
> [`docs/engineering/RUNTIME_FILESYSTEM.md`](docs/engineering/RUNTIME_FILESYSTEM.md).
>
> **Phase 021 ended the zero-dependency era, and gave GLOBIN a way in.**
> `project.dependencies` names `numpy` and `pandas`, each with a written
> six-question review, and `pylock.toml` arrived in the same commit — the pairing
> Phase 020's gate had been waiting for. `scripts/bootstrap.ps1` now installs the
> toolchain, the runtime lock and GLOBIN itself, which is what creates the
> `globin` command; `globin doctor` and `globin bootstrap check` answer whether
> this host may start GLOBIN at all, and refuse fail-closed when it may not.
> **Nothing imports either package**, and Phase 022 has now verified them without
> adopting them; this phase declared, reviewed and locked them. See
> [`docs/engineering/BOOTSTRAP.md`](docs/engineering/BOOTSTRAP.md) and
> [`docs/engineering/DEPENDENCY_LOCKING.md`](docs/engineering/DEPENDENCY_LOCKING.md).
>
> **It also closed a question Phase 015 left open rather than unanswered.**
> [ADR-0048](docs/adr/0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md)
> chose the secret store's properties as capabilities "so that Phase 028 can
> satisfy them with whatever Windows actually offers", and nobody had established
> what Windows offers.
> [`docs/security/SECRET_STORE_CONTRACT.md`](docs/security/SECRET_STORE_CONTRACT.md)
> records the measured limits. **No store is implemented and no mechanism is
> chosen** — that remains Phases 027 to 029.
>
> **Phase 016 closed the first band and cut `v0.1.0`.** What that certifies, and
> the one criterion it could not, are in
> [`docs/release/FOUNDATION_ACCEPTANCE.md`](docs/release/FOUNDATION_ACCEPTANCE.md).
>
> **Phase 015 wrote the secret-handling rules; it built no secret store.** Where
> a credential may live, how it is redacted and what an API key may do are
> specified in
> [`docs/security/SECURITY_BASELINE.md`](docs/security/SECURITY_BASELINE.md).
> Phase 028 implements the store and Phase 029 the credential flow — the roadmap
> separates specification from implementation deliberately, and this is the
> boundary.
>
> **The repository is public as of Phase 014.** That was the decision that made
> CodeQL, secret scanning, push protection, dependency review and rulesets
> available at all — every one of them refused with a plan ceiling while it was
> private. [ADR-0046](docs/adr/0046-the-repository-is-public-and-that-changes-the-threat-model.md)
> records what that changes about the threat model, which is more than it changes
> about the settings.

> **Scope amendments.** Seventeen have been made. Each cost an ADR, and each is
> recorded here so that the programme's history is visible without opening the
> decision log. Band ranges, phase numbers and the sixteen-phase band width are
> unchanged by all seventeen.
>
> This count said *seven* while listing eight from Phase 024 until Phase 025
> repaired it. Nothing tested it, which is why it drifted and why it was worth
> reading sceptically. **Phase 032 bound it**: the ledger in
> [`docs/engineering/scope-amendments.toml`](docs/engineering/scope-amendments.toml)
> now carries one row per amendment, and
> `tests/contract/test_granularity_contract.py` compares the spelled count above
> against its length, checks every ordinal below appears exactly once and in
> ascending order, and recomputes each score from its four conditions. The two
> ways this paragraph has drifted are now two failing tests. **It had drifted again by Phase 030**, in two ways at once:
> the count read thirteen while the list stopped at eleven, and the tenth was
> filed below the eleventh. Phase 030 repaired both and added its own, which is
> why three entries below carry that phase's number.
>
> **First.** Phase 003 originally read *Coding Standards and Static Analysis
> Baseline*, and Phase 013 read *Continuous Verification Script and Quality
> Gates*. Phase 003 now delivers architecture boundaries, and the
> coding-standards scope moved into Phase 013. Reasoning in
> [ADR-0012](docs/adr/0012-phase-003-delivers-architecture-boundaries.md).
>
> **Second.** Phase 004 originally read *Test Architecture and Fixture
> Conventions*. It now also delivers the quality gates — lint, typing, coverage,
> the pre-commit hook and continuous integration — which Phase 013 previously
> owned. Phase 013 retains the *conventions* those gates enforce. Reasoning in
> [ADR-0016](docs/adr/0016-phase-004-absorbs-the-quality-gate-scope.md), which
> also states plainly what a second amendment costs.
>
> **Third.** Phase 005 originally read *Error Taxonomy and Exception Hierarchy*.
> It still delivers that, and now also delivers the deterministic testing
> foundation: the property level, the enforced offline guarantee, process-state
> isolation and the test-double rule. Unlike the first two, this amendment
> *widens* a phase rather than moving scope between two — no phase is displaced,
> nothing is deferred, and no other title changes. ADR-0016 named a third
> amendment before Phase 016 as the signal that the roadmap is being treated as a
> backlog;
> [ADR-0021](docs/adr/0021-phase-005-widens-to-include-the-test-foundation.md)
> answers that warning rather than arguing it away, and states the four
> conditions that would have to hold before this precedent applies again.
>
> **Fourth.** Phase 017 originally read *Windows Host Requirements Survey*, Phase
> 018 *Python Interpreter Selection and Pinning*, and Phase 019 *Virtual
> Environment Lifecycle Management*. Phase 017 now delivers all three. Phase 018
> takes the wheel-availability survey that its own title made a precondition of
> pinning and that Phase 017 did not do; Phase 019 takes drift detection and
> repair, which Phase 017 also did not do.
>
> **This one fails the test.** ADR-0021 said an amendment must be able to say
> *nothing displaced, nothing deferred, no phase owns the work, and the two halves
> need each other*, and that one which cannot say all four is not covered by its
> precedent. This displaces two phases, and both owned their work by name.
> [ADR-0051](docs/adr/0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md)
> records that rather than arguing it, on the owner's decision and with the
> alternatives that were declined. A fifth amendment has a higher bar than a
> fourth did, not a lower one.
>
> **Fifth.** Phase 021 delivers the application bootstrap alongside the runtime
> dependencies its title names — one entry point, a deterministic startup
> pipeline, a typed runtime context, an exit-code contract and secret-safe
> evidence. Phase 030 owns a bootstrap health-check suite by name, and its core
> arrives here.
>
> **It fails the same test the fourth did, and clears one the fourth could not.**
> Nothing is deferred, but work is displaced and a phase owns it. What it can say
> that the fourth could not is that the two halves genuinely need each other: a
> console entry point exists only once something is installed, installing GLOBIN
> makes `project.dependencies` real, and the lock gate refused the install until
> both existed.
> [ADR-0056](docs/adr/0056-phase-021-widens-to-deliver-the-application-bootstrap.md)
> records that against ADR-0021's four criteria one by one, on the owner's
> decision. A sixth amendment makes its own argument; it does not cite this one.
>
> **Sixth.** Phase 022 still delivers the scientific stack its title names, and
> now also delivers the application's mutable runtime filesystem and its process
> lifecycle: a user-local runtime tree, atomic state publication, a single-instance
> coordinator lock, graceful shutdown and crash-safe lifecycle evidence.
>
> **It is the weakest amendment in the programme, and it makes its own argument
> rather than citing the fifth.** Restating ADR-0021's test in full: nothing is
> deferred and no other title changes, but work is displaced, eight planned phases
> own parts of it by name — 026, 030, 257, 262, 266, 267, 268 and 270 — and the
> two halves do **not** need each other. Either could have shipped alone, and no
> gate refused until both existed, which is the one criterion the fifth amendment
> could claim and this one cannot. **One of four**, where the fourth and fifth each
> scored two.
> [ADR-0057](docs/adr/0057-phase-022-widens-to-deliver-the-runtime-filesystem-and-lifecycle.md)
> records that, and the three courses the conflict was surfaced with, on the
> owner's decision. A seventh amendment cannot cite this one either, and cannot
> cite the series.
>
> **Seventh.** Phase 023 still delivers the NVIDIA driver and CUDA capability
> detection its title names, and now also gives the running application its
> diagnostics: a bounded log file in the runtime tree, a lifecycle event
> vocabulary, the three process fault hooks, `faulthandler`, and a bridge for
> third-party standard-library records and Python warnings.
>
> **It scores one of four, and fails the third criterion worse than any amendment
> before it.** Restating ADR-0021's test in full: nothing is deferred and no other
> title changes, but work is displaced — rotation and retention are Phase 282's by
> name, with parts of 026, 027 and 030 arriving too — the two halves do not need
> each other, and **the phase that owns the work has already shipped**. Phase 006
> delivered the structured logging foundation and is marked `Complete`; every
> previous amendment displaced work forwards into phases that had not started.
> What shipped is the part Phase 006 could not have built, because in Phase 006
> there was no application to instrument, and the overlap was refused rather than
> rebuilt: the record schema is unchanged, ADR-0026's explicit correlation stands,
> and the standard library's `logging` did not enter GLOBIN's call sites.
> [ADR-0060](docs/adr/0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md)
> records that, and the four courses the conflict was surfaced with, on the
> owner's decision. An eighth amendment can cite neither this one nor the series,
> and must additionally say which completed phase it overlaps.
>
> **Eighth.** Phase 024 still delivers the GPU runtime verification harness its
> title names, and now also gives the running application its health surface: a
> typed runtime health snapshot, process and host resource diagnostics, bounded
> thread and memory introspection, and a redacted, self-validating support bundle.
>
> **It scores one of four, and it makes its own argument rather than citing the
> series.** Restating ADR-0021's test in full: nothing is deferred and no other
> title changes, but work is displaced -- parts of 030, 260, 276, 280, 282 and 301
> arrive here -- six planned phases own it by name, and the two halves do not need
> each other. What it can say that the seventh could not is the thing ADR-0060
> demanded of it: **it overlaps no completed phase.** Every phase it displaces has
> not started, which is a return to the shape of the fourth, fifth and sixth rather
> than an improvement on any of them.
> [ADR-0061](docs/adr/0061-phase-024-widens-to-deliver-runtime-health-and-support-bundles.md)
> records that, and the four courses the conflict was surfaced with, on the owner's
> decision. A ninth amendment inherits nothing from this one.
>
> **Ninth.** Phase 025 still delivers the TA-Lib native library provisioning its
> title names, and now also gives the running application its watchdog: a monotonic
> heartbeat registry, a suspect threshold distinct from a confirmed stall, bounded
> and redacted stall evidence, a graceful shutdown request and a bounded escalation
> to a hard exit.
>
> **It scores one of four, and it fails the third criterion in a way no predecessor
> did.** Restating ADR-0021's test in full: nothing is deferred and no other title
> changes, but work is displaced -- parts of 030, 262, 266 and 302 arrive here --
> and the two halves do not need each other. What is new is that Phase 263 owns this
> work **by its title**, *Supervisor and Watchdog*, rather than merely inside its
> purpose text; every earlier amendment collided with a purpose at most. What it can
> say in return is the thing ADR-0061 could also say and this one had to earn
> separately: **it overlaps no completed phase**, and the collision with 263 is
> refused rather than rebuilt -- recovery, restart, subsystem ordering and draining
> are all absent by design, and the watchdog is delivered on the lifecycle seam with
> no driver at all, because the long-lived process is Phase 257's.
> [ADR-0064](docs/adr/0064-phase-025-widens-to-deliver-the-runtime-watchdog.md)
> records that, and the three courses the conflict was surfaced with, on the owner's
> decision. A tenth amendment inherits nothing from this one and must additionally
> say whether it too collides with a title.
>
> **Tenth.** Phase 026 still delivers the configuration file layout and the paper,
> demo, testnet and live profile structure its title names, and now also gives the
> running application its telemetry foundation: a provider-neutral typed contract, a
> metric registry whose cardinality is bounded by construction rather than policed at
> runtime, span values with `contextvars` propagation, a bounded and failure-safe
> delivery path, two provider bridges, a fourth configuration section and a read-only
> command.
>
> **It scores one of four, and it is the second consecutive amendment to collide with
> a phase title.** Restating ADR-0021's test in full: nothing is deferred and no other
> title changes, but work is displaced -- parts of 280, 282 and 315 arrive here -- and
> the two halves do not need each other. Phase 280 owns this work **by its title**,
> *Operational Metrics Collection*. The ninth collided with a title too, and two in a
> row is materially worse than a repeat of an earlier shape;
> [ADR-0067](docs/adr/0067-phase-026-widens-to-deliver-the-telemetry-foundation.md)
> says so rather than treating it as normalised. What it can say in return: **it
> overlaps no completed phase**, and the collision with 280 is refused rather than
> rebuilt -- that phase's verb is *collect*, this phase's are *declare*, *bound* and
> *record*, and collection, retention, dashboards and alerting are absent by design
> with their owning phases named.
>
> **The signal ADR-0064 named has fired.** That record said a tenth amendment before
> the band closes at Phase 032 would be evidence the roadmap is being treated as a
> backlog, and that the right response is to question the roadmap's granularity rather
> than to write an eleventh argument. **Phase 032 must therefore examine whether Phases
> 017-032 were drawn at a granularity that describes the work, with all ten amendments
> in front of it.** An eleventh before then is not another argument to be weighed.

> **Eleventh, and taken against this document's own refusal.** Phase 027 still
> delivers the environment variable and profile resolution its title names -- one
> declared document order, one declared profile order, the environment above every
> document, and a preflight that resolves what a run resolves rather than the declared
> defaults it used to validate. Alongside it, the loopback diagnostics surface:
> liveness, readiness, a redacted runtime health projection and a
> Prometheus/OpenMetrics scrape, read-only and bounded, on an address a value type
> refuses to widen.
>
> **The paragraph above says an eleventh "is not another argument to be weighed", and
> that sentence was put to the owner verbatim** along with the two courses it implies --
> bring the granularity review forward now, or deliver the titled scope alone. The owner
> chose to proceed. **It scores two of ADR-0021's four conditions**, and the two it
> fails are the two the tenth failed: work is displaced (Phase 280 *Operational Metrics
> Collection* and Phase 315 *Live Monitoring and Escalation* own collection and
> escalation; this phase neither collects, retains, dashboards nor alerts, and names
> them), and the two halves do not need each other. Three in a row is worse than two.
>
> **Nothing here answers the granularity question.** It remains Phase 032's, now with
> eleven amendments in front of it, and a twelfth may cite neither this record nor the
> owner's having overridden the refusal once.
> [ADR-0070](docs/adr/0070-phase-027-widens-to-deliver-the-loopback-diagnostics-surface.md)
> carries the whole of it.

> **Twelfth.** Phase 028 still delivers the local secret store its title names -- the
> Windows Credential Manager reached through `ctypes`, a reference that is ordinary data
> beside a value that has no string form, one case-folding key builder, and a rotation
> that moves the previous value aside before writing the new one. Alongside it, the
> environment capability inventory: native architecture separated from process
> architecture and measured only through the API that can tell them apart, emulation
> state, bounded toolchain discovery, and a compatibility fingerprint that excludes
> everything volatile.
>
> **It scores two of ADR-0021's four conditions.** Nothing is deferred and no title
> changes; work is displaced, and the two halves do not need each other -- a credential
> store does not require an inventory of the host, and the inventory would be just as
> true without one.
> [ADR-0073](docs/adr/0073-phase-028-widens-to-deliver-the-environment-capability-inventory.md)
> carries it.
>
> **Thirteenth.** Phase 029 still delivers the credential prompting and validation flow
> its title names -- six verbs and no seventh, interactive collection that refuses a pipe
> before `getpass` is called, and a permission model with no member meaning *confirmed*.
> Alongside it, the dependency attestation: a runtime inventory that can finally see a
> version, a second PEP 751 reader that is the specification's own implementation, and an
> offline materialization gate whose network fallback is unreachable rather than un-taken.
>
> **It scores two of four**, and its own record closes by saying that a fourteenth
> inherits nothing from it, may not cite it, and may not cite the count above.
> [ADR-0076](docs/adr/0076-phase-029-widens-to-deliver-the-dependency-attestation.md)
> carries it.
>
> **Fourteenth.** Phase 030 still delivers the bootstrap health check suite its title
> names -- the eighteen-check registry classified by whether each answer survives the run,
> a re-take schedule that cannot be constructed if it could not be honoured, and a
> `bootstrap preflight` that runs every check *and* gates. Alongside it, configuration
> made able to explain itself: a command-line value layer above the environment, an
> explicit document whose absence is fatal where the four computed ones are optional,
> per-field provenance, a declared contract version, a bounded document size, and a
> semantic fingerprint held apart from one that sees where a value came from.
>
> **It scores four of ADR-0021's four conditions, and that is the first time.**
> *Nothing displaced*: the configuration layout and its precedence are Phases 026 and 027,
> both complete, and a completed phase cannot be displaced. *Nothing deferred*: the titled
> scope ships whole in the same commit. *No phase owns the work*: Phase 291 *Interactive
> Configuration Wizard* owns **collecting** configuration an operator has not supplied,
> which this neither does nor enables, and Phase 283 owns backing it up; neither owns
> explaining a resolution. *The two halves need each other*: `config.valid` is one of the
> eighteen checks the suite is made of, and a suite that gates a long-running process on
> configuration while reporting one sentence when it refuses is not a gate anybody can act
> on.
>
> **Scoring four does not answer the granularity question, and this record does not claim
> it does.** That question is still Phase 032's, now with fourteen amendments in front of
> it. What this one can add to it is a data point rather than an argument: an amendment
> that passes all four conditions was available inside a band whose granularity is under
> review, which is evidence about the phase boundary rather than about the test.
> [ADR-0079](docs/adr/0079-phase-030-widens-to-deliver-the-configuration-evidence-surface.md)
> carries the whole of it.

> **Fifteenth.** Phase 031 still delivers the offline and degraded installation
> handling its title names -- a declared registry of every component GLOBIN reaches
> for, a necessity per component, a posture folded from what each of six absent-safe
> factories actually returned rather than from what was hoped, and a network row that
> is declared rather than probed because a probe would be a mechanism with no caller
> *and* would remove a guarantee the architecture tests currently prove. Alongside it,
> the user-scoped secret vault: a DPAPI-protected envelope for key material the
> Credential Manager's 2560-byte ceiling structurally cannot hold, admitted by
> arithmetic rather than by policy, carrying its own integrity check because the
> platform documents that its own may succeed on corrupted input.
>
> **It scores one of ADR-0021's four conditions, which is the joint-worst in the
> programme and arrives directly after the only amendment to score four.** Nothing is
> deferred. But Phase 292 *Credential Collection and Persistence Flow* owns storing
> credentials **by its title** -- the third title-level collision after 263 and 280 --
> the work overlaps two **completed** phases, 028 and 029, and the two halves do not
> need each other. Two bridges that would have connected them are refused in the
> record rather than left unmentioned, one of them because the store contract forbids
> it by name.
>
> **That a four and a one arrived in consecutive phases is the entry's substance
> rather than an accident of ordering**, and it is offered to Phase 032 as evidence
> about the granularity rather than as an argument about the test.
> [ADR-0082](docs/adr/0082-phase-031-widens-to-deliver-the-user-scoped-secret-vault.md)
> carries the whole of it, cites neither the fourteenth's score nor the count, and
> closes by forbidding a sixteenth from citing any of this.

> **Sixteenth.** Phase 032 still delivers the environment consolidation and phase
> gate review its title names -- the band certified by a second acceptance matrix
> that one evaluator recomputes, `v0.2.0` cut against it, and the granularity
> review this document has been holding since ADR-0064 named the signal.
> Alongside it, the bootstrap provisioning surface: a plan derived from a report
> and from nothing else, a network policy that is declared rather than probed, a
> claim that makes an interrupted run visible, and one bounded process runner.
>
> **It scores two of four, and it cites nothing.** ADR-0082 forbade a sixteenth
> from citing any prior record or the count, so
> [ADR-0084](docs/adr/0084-phase-032-widens-to-deliver-the-bootstrap-provisioning-surface.md)
> argues from scratch. *Nothing deferred*: both halves ship together. *The two
> halves need each other*: a band cannot be certified as producing a reproducible
> host while the path from a clean clone to a working environment is the one thing
> no gate recomputes, and five environment-lifecycle criteria became measurements
> rather than assertions because of it. It fails the other two -- work is
> displaced, and Phase 291 *Interactive Configuration Wizard* owns part of it by
> purpose. **No phase owns it by title**, which is the one thing the ninth, tenth
> and fifteenth could not say.
>
> **The review it delivers judges the amendment it is**, and says so rather than
> working around it. Its central finding is that **two of the four conditions
> carry almost no information** across this programme -- one met every time, one
> met once -- and that this band's rows describe provisioning steps while eleven
> consecutive phases delivered the running application's substrate, for which the
> band has no rows at all. It proposes no replacement test and rewrites no roadmap
> row: a review conducted inside a phase it must score is not a disinterested one.
> Phase 048 inherits both findings and this amendment as evidence.


> **Seventeenth.** Phase 033 still delivers the Binance product family inventory
> its title names -- every officially documented product family, classified by
> whether GLOBIN trades it, and the REST, WebSocket, FIX and encoding surfaces
> each one exposes. Alongside it, the API reality registry: production, demo and
> testnet as distinct kinds rather than a boolean, the capability matrix over
> them, every base URL and endpoint family in one document, the SBE and FIX schema
> lifecycle, six status words that keep *not documented* apart from *documented
> absent*, and a refresh that classifies drift.
>
> **It scores two of four, and it fails *no phase owns the work* against four
> titles at once.** Rows 034, 035, 036 and 037 name the ingestion process, the
> environment model, the capability matrix and the endpoint registry by title.
> The sixteenth's one saving statement was that no phase owned its work by title;
> this one cannot say it, and fails the condition more comprehensively than any
> record before it. It is also the largest displacement inside a band the
> programme has made -- the four consecutive rows immediately following, twice the
> reach of the fourth, which displaced 018 and 019 and is the only comparable case.
> *Nothing deferred*: both halves ship together. *The two halves need each other*:
> an inventory with no environment axis is the row labels of a matrix, and the
> provenance and status machinery has nothing to prove itself against if the only
> thing recorded is eight uncontested product names.
>
> **A third artefact named the division, and it is an accepted record rather than
> a plan.** [ADR-0006](docs/adr/0006-product-and-environment-capability-matrix.md)
> closes with *"Phase 036 exists specifically to build this matrix, and Phases
> 033-035 exist to gather what it needs."* That sentence is contradicted here, the
> record is immutable, and
> [ADR-0086](docs/adr/0086-phase-033-widens-to-deliver-the-binance-api-reality-registry.md)
> states the contradiction rather than out-voting it. The same ADR supplies the
> requirement the refresh answers -- that the matrix is re-verified when Binance
> documentation changes rather than assumed once -- which no row had owned.
>
> **No roadmap row is rewritten.** The eight amendments before this one recorded
> displacement and left the future row's text intact, and the granularity review
> reserves rewriting for Phase 048.


---

## Phases 001-016 — Repository Foundation and Engineering Contract

Establishes the repository, the rules every later phase obeys, and the
verification backbone that makes those rules enforceable rather than merely
written down.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 001 | Repository Foundation and Engineering Contract | Create the repository, master-only workflow, living documentation, ADR set, project contract module and invariant test suite. | Complete |
| 002 | Documentation System and Style Guide | Define document types, ownership, review cadence and the writing conventions all later documentation follows. | Complete |
| 003 | Architecture Boundaries and Dependency Direction | Establish the layer contract, the inward dependency direction, the ports and adapters boundary, the composition root, the C4 system and container views, and the ADR lifecycle. | Complete |
| 004 | Test Architecture and Quality Gates | Define test layers, directory structure, fixture scope rules and naming; enforce them with a lint, typing and branch-coverage contract, a pre-commit gate, one canonical quality entrypoint and a verification-only CI workflow. | Complete |
| 005 | Error Taxonomy and Deterministic Test Foundations | Design the project-wide exception hierarchy separating configuration, transport, exchange, validation and internal faults, and establish the deterministic testing foundation that proves it: a property level, an enforced offline guarantee, process-state isolation and the test-double rule. | Complete |
| 006 | Structured Logging Foundation | Establish structured, correlation-aware logging with severity policy and redaction of sensitive fields. | Complete |
| 007 | Configuration Model and Schema Contract | Define the typed configuration model, validation rules, defaults and layered override precedence. | Complete |
| 008 | Domain Value Types and Units | Introduce explicit types for prices, quantities, symbols, sides and currencies to prevent unit confusion. | Complete |
| 009 | Time, Clock and Timezone Discipline | Establish UTC-only internal time, millisecond conventions, monotonic clocks and an injectable clock abstraction. | Complete |
| 010 | Decimal and Numeric Precision Policy | Decide where decimal arithmetic is mandatory versus floating point, and define rounding and tick-size behaviour. | Complete |
| 011 | Identifier and Naming Registry | Define canonical identifiers for symbols, products, environments, runs, models and orders across the system. | Complete |
| 012 | Serialization and Persistence Contracts | Establish schema evolution rules and forward and backward compatibility guarantees for persisted structures. | Complete |
| 013 | Coding Standards and Documentation Conventions | Fix naming, structure, docstring and typing conventions, and tighten the existing lint and type configuration to match them, including the docstring rules Phase 004 deliberately left unselected. | Complete |
| 014 | Dependency Review and Licence Audit Process | Define how a candidate dependency is reviewed for cost, licence, maintenance health and supply-chain risk. | Complete |
| 015 | Security Baseline and Secret Handling Rules | Specify secret storage, redaction, least-privilege API key usage and the prohibition on committing credentials. | Complete |
| 016 | Foundation Consolidation and Phase Gate Review | Reconcile the foundation band, resolve inconsistencies and certify readiness for environment work. | Complete |

---

## Phases 017-032 — Windows Environment, Dependencies and Bootstrap

Turns a bare Windows machine into a reproducible GLOBIN development and runtime
host, including honest verification of GPU capability rather than assumption.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 017 | Windows Host and CPython Runtime Baseline | Declare the supported host and interpreter, check both against the machine, and build the project virtual environment deterministically. | Complete |
| 018 | Wheel Availability Survey for the Planned Stack | Verify every library the roadmap schedules has a Windows wheel for the pinned interpreter, and record each gap rather than assuming one. | Complete |
| 019 | Environment Drift Detection and Repair | Detect divergence from the runtime contract as it appears, and define repair short of recreating the environment. | Complete |
| 020 | Dependency Resolution and Lockfile Strategy | Choose the locking mechanism and define reproducible resolution, upgrade and audit procedures. | Complete |
| 021 | Core Runtime Dependency Introduction | Introduce the first runtime dependencies under the zero-budget policy with explicit justification per package. | Complete |
| 022 | Scientific Stack Installation and Verification | Install and verify the numerical and dataframe stack, confirming correctness rather than assuming it; and, as the sixth scope amendment, deliver the application's mutable runtime filesystem, atomic state publication, single-instance coordinator lock and graceful shutdown. | Complete |
| 023 | NVIDIA Driver and CUDA Capability Detection | Detect GPU presence, driver version, compute capability and CUDA availability without assuming any of them; and, as the seventh scope amendment, give the running application its diagnostics -- a bounded log file in the runtime tree, a lifecycle event vocabulary, the process fault hooks, `faulthandler`, and a bridge for standard-library records. | Complete |
| 024 | GPU Runtime Verification Harness | Build a harness that proves which workloads actually benefit from GPU execution on this host; and, as the eighth scope amendment, give the running application its health surface -- a typed runtime health snapshot, process and host resource diagnostics, bounded thread and memory introspection, and a redacted, self-validating support bundle. | Complete |
| 025 | TA-Lib Native Library Provisioning | Provision the native TA-Lib dependency required by the Python wrapper on Windows, with a documented fallback, measured on this host rather than read off a filename; and, as the ninth scope amendment, give the running application its watchdog -- a monotonic heartbeat registry, a suspect threshold distinct from a confirmed stall, bounded and redacted stall evidence, a graceful shutdown request and a bounded escalation to a hard exit. | Complete |
| 026 | Configuration File Layout and Profiles | Define on-disk configuration locations and the paper, demo, testnet and live profile structure; and, as the tenth scope amendment, give the running application its telemetry foundation -- a provider-neutral metric contract, cardinality bounded by construction, span context propagation, a bounded and failure-safe export path, and two provider bridges that are absent without breaking anything. | Complete |
| 027 | Environment Variable and Profile Resolution | Implement deterministic precedence between defaults, files, environment variables and launcher selection; and, as the eleventh scope amendment, give the running application its loopback diagnostics surface -- liveness, readiness, a redacted runtime health projection and a Prometheus/OpenMetrics scrape, bounded and read-only, on an address a value type refuses to widen. | Complete |
| 028 | Local Secret Storage Mechanism | Implement the approved local secret store so credentials never reach the repository or plain configuration; and, as the twelfth scope amendment, deliver the environment capability inventory -- native versus process architecture, emulation state, bounded toolchain discovery, and a compatibility fingerprint that excludes everything volatile. | Complete |
| 029 | Credential Prompting and Validation Flow | Define interactive credential collection, format validation and permission verification before use; and, as the thirteenth scope amendment, deliver the dependency attestation -- a runtime inventory that can finally see a version, a second PEP 751 reader that is the specification's own, and an offline materialization gate whose network fallback is unreachable rather than un-taken. | Complete |
| 030 | Bootstrap Health Check Suite | Implement the preflight checks that must pass before any long-running GLOBIN process starts, classifying every check by whether its answer survives the run and declaring the schedule the perishable ones imply; and, as the fourteenth scope amendment, make configuration able to explain itself -- a command-line value layer above the environment, an explicit document whose absence is fatal, per-field provenance, a declared contract version, and a semantic fingerprint separated from the one that sees where a value came from. | Complete |
| 031 | Offline and Degraded Installation Handling | Define behaviour when the network, GPU or optional native components are unavailable, declaring a necessity per component and folding a posture from what each factory actually returned; and, as the fifteenth scope amendment, deliver the user-scoped secret vault -- a DPAPI-protected envelope for material the credential store's 2560-byte ceiling refuses, admitted by arithmetic, carrying its own integrity check, and with no fallback edge between the two mechanisms. | Complete |
| 032 | Environment Consolidation and Phase Gate Review | Reconcile the environment band and certify a reproducible host before exchange integration begins, answering on the record whether Phases 017-032 were drawn at a granularity that describes the work; and, as the sixteenth scope amendment, deliver the bootstrap provisioning surface -- a plan derived from a report and from nothing else, a network policy that is declared rather than probed, a claim that makes an interrupted run visible, and one bounded process runner in the one module permitted to start a child. | Complete |

---

## Phases 033-048 — Binance API Reality Map and Capability Matrix

Maps what Binance actually exposes per product and per environment, and builds
the transport, authentication and rate-limit machinery on top of that reality.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 033 | Binance Product Family Inventory | Enumerate the officially documented product families and the surfaces each one exposes; and, as the seventeenth scope amendment, deliver the Binance API reality registry -- production, demo and testnet as distinct kinds, the capability matrix over them, every base URL and endpoint family in one declared document, the SBE and FIX schema lifecycle, six status words that keep *not documented* apart from *documented absent*, and a refresh that classifies drift from official machine-readable sources only. | Complete |
| 034 | Official Documentation Ingestion and Change Tracking | Establish a repeatable process for consuming official Binance documentation and detecting changes to it. | Planned |
| 035 | Environment Classification Model | Model production, testnet, demo and internal simulation as distinct classes with distinct guarantees. | Planned |
| 036 | Product and Environment Capability Matrix | Build the authoritative matrix of which products support which environments, driven by documented evidence. | Planned |
| 037 | Base URL and Endpoint Registry | Centralise base URLs and endpoint definitions per product and environment with no hard-coded literals. | Planned |
| 038 | Request Signing and Authentication | Implement the documented signing schemes and keep signing logic isolated and testable. | Planned |
| 039 | API Key Permission Model and Validation | Verify key permissions and refuse operations the configured key is not entitled to perform. | Planned |
| 040 | Server Time Synchronization and Drift Control | Implement server time synchronization, drift measurement and the response to excessive clock skew. | Planned |
| 041 | Rate Limit Weight Registry | Record the documented request weights and order-count costs for every endpoint the system uses. | Planned |
| 042 | Rate Limit Governor and Token Buckets | Implement proactive limiting that respects reported usage headers rather than reacting only to rejections. | Planned |
| 043 | Retry, Backoff and Idempotency Policy | Define which failures are retryable, with what backoff, and which operations require idempotency keys. | Planned |
| 044 | Error Code Mapping and Classification | Map documented exchange error codes to the internal taxonomy with explicit retryable and fatal classification. | Planned |
| 045 | REST Transport Layer | Implement the REST client with timeouts, connection reuse, instrumentation and limit integration. | Planned |
| 046 | WebSocket Transport and Stream Lifecycle | Implement connection lifecycle, keepalive, subscription management and backpressure for streams. | Planned |
| 047 | FIX and SBE Interface Assessment | Evaluate whether the documented FIX and SBE interfaces provide material value for this system. | Planned |
| 048 | API Layer Consolidation and Phase Gate Review | Reconcile the API band and certify the transport foundation before data acquisition begins. | Planned |

---

## Phases 049-064 — Market Data Acquisition and Instrument Registry

Acquires complete, verifiable market data. Completeness is treated as a
measured property, not an assumption.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 049 | Instrument Registry and Symbol Metadata | Build the registry of tradable instruments with their metadata, status and product association. | Planned |
| 050 | Exchange Filter and Trading Rule Ingestion | Ingest lot size, notional, price and other filters so orders can be validated before submission. | Planned |
| 051 | Kline Acquisition and Interval Handling | Acquire candlestick data across intervals with correct boundary and closure semantics. | Planned |
| 052 | Historical Backfill from Binance Public Data | Bulk-load historical archives from the official public data resource without API keys. | Planned |
| 053 | Archive Integrity and Checksum Verification | Verify downloaded archives against their published checksums before any data is trusted. | Planned |
| 054 | Trade and Aggregate Trade Streams | Acquire individual and aggregated trade data with correct ordering and deduplication. | Planned |
| 055 | Order Book Snapshot and Depth Diff Handling | Implement the documented snapshot plus differential update procedure correctly. | Planned |
| 056 | Order Book Reconstruction and Validation | Maintain a correct local book with sequence validation and automatic resynchronization on divergence. | Planned |
| 057 | Book Ticker and Best Quote Feeds | Acquire best bid and ask feeds for spread measurement and execution modelling. | Planned |
| 058 | Mark Price, Index Price and Funding Feeds | Acquire derivatives-specific reference prices and funding information. | Planned |
| 059 | Options Market Data Acquisition | Acquire options chains, quotes and any published greeks or implied volatility surfaces. | Planned |
| 060 | Stream Multiplexing and Subscription Management | Manage many symbol and stream subscriptions within connection and rate constraints. | Planned |
| 061 | Reconnection, Resubscription and Gap Detection | Detect disconnections and data gaps, then recover and backfill deterministically. | Planned |
| 062 | Data Completeness Auditing | Continuously measure coverage and missing intervals rather than assuming feeds are complete. | Planned |
| 063 | Market Data Normalization Layer | Normalise heterogeneous product feeds into consistent internal representations. | Planned |
| 064 | Market Data Consolidation and Phase Gate Review | Reconcile the market data band and certify feed correctness before account integration. | Planned |

---

## Phases 065-080 — Account and Product Adapters

Implements per-product account access, honouring the fact that each Binance
product family has its own semantics, limits and availability.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 065 | Account Capability Discovery | Discover at runtime which products and permissions the configured account actually has. | Planned |
| 066 | Spot Account Adapter | Implement spot account access including balances, trade history and account status. | Planned |
| 067 | Spot Balance and Position View | Derive a consistent spot holdings view including locked and free balance semantics. | Planned |
| 068 | Cross Margin Account Adapter | Implement cross margin account access, margin level and asset details. | Planned |
| 069 | Isolated Margin Account Adapter | Implement isolated margin account access with per-pair isolation semantics. | Planned |
| 070 | Margin Borrow and Interest Model | Model borrowing capacity, interest accrual and repayment obligations accurately. | Planned |
| 071 | USDS-M Futures Account Adapter | Implement USDS-margined futures account access, balances and account configuration. | Planned |
| 072 | USDS-M Position and Leverage Semantics | Model position mode, leverage, margin type and unrealised profit and loss correctly. | Planned |
| 073 | COIN-M Futures Account Adapter | Implement coin-margined futures account access and balance semantics. | Planned |
| 074 | COIN-M Contract and Delivery Semantics | Model contract multipliers, expiry and delivery behaviour for coin-margined products. | Planned |
| 075 | Options Account Adapter | Implement options account access, positions and exercise-related information where documented. | Planned |
| 076 | Portfolio Margin Account Adapter | Implement portfolio margin account access and unified margin semantics. | Planned |
| 077 | Portfolio Margin Pro Assessment and Adapter | Verify actual availability and implement access only where genuinely supported. | Planned |
| 078 | User Data Stream and Account Event Handling | Consume authenticated account event streams with correct listen key lifecycle handling. | Planned |
| 079 | Unified Account Abstraction Layer | Provide a common account interface without hiding genuine product-specific differences. | Planned |
| 080 | Account Adapter Consolidation and Phase Gate Review | Reconcile the account band and certify adapter correctness before execution work. | Planned |

---

## Phases 081-096 — Order Lifecycle and Execution Engine

Builds order execution around the documented reality that a failed request does
not prove a failed operation.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 081 | Order Domain Model and Types | Define the internal order model covering all supported types, sides and time-in-force values. | Planned |
| 082 | Pre-Trade Validation Against Exchange Filters | Reject invalid orders locally before submission using the ingested exchange filters. | Planned |
| 083 | Client Order Identifier and Idempotency Keys | Generate deterministic client order identifiers that make retries safe and traceable. | Planned |
| 084 | Order State Machine | Model order states and legal transitions explicitly, including indeterminate states. | Planned |
| 085 | Order Submission Pipeline | Implement submission with validation, limiting, timeout handling and structured auditing. | Planned |
| 086 | Uncertain Execution State Resolution | Resolve timeouts and server errors by querying authoritative state rather than assuming failure. | Planned |
| 087 | Order Cancellation and Replacement | Implement cancellation and cancel-replace semantics with correct race handling. | Planned |
| 088 | Batch and Multi-Order Operations | Implement batch operations where documented, including partial failure handling. | Planned |
| 089 | Conditional and Advanced Order Types | Support stop, trailing and other documented advanced order types per product. | Planned |
| 090 | Algo Trading Interface Integration | Integrate the officially documented algorithmic order facilities where they add value. | Planned |
| 091 | Margin Borrow and Repay Execution | Implement borrow and repay operations as first-class auditable actions. | Planned |
| 092 | Leverage and Margin Mode Control | Implement safe, validated changes to leverage and margin mode with guard rails. | Planned |
| 093 | Position Lifecycle Management | Track position opening, adjustment, reduction and closure across products. | Planned |
| 094 | Fill and Execution Report Processing | Process fills and execution reports into accurate internal position and cost basis state. | Planned |
| 095 | Order and Position Reconciliation Engine | Continuously reconcile local state against authoritative exchange state and repair divergence. | Planned |
| 096 | Execution Consolidation and Phase Gate Review | Reconcile the execution band and certify order handling correctness. | Planned |

---

## Phases 097-112 — Point-in-Time Data Platform

Guarantees that research can only ever see what was actually knowable at the
time. This is the foundation that makes later validation trustworthy.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 097 | Storage Architecture Selection | Select the local storage engines and formats against the zero-budget and local-host constraints. | Planned |
| 098 | Canonical Data Schemas | Define authoritative schemas for every dataset the system produces or consumes. | Planned |
| 099 | Columnar Storage Layout and Partitioning | Define partitioning, file sizing and layout for efficient local analytical access. | Planned |
| 100 | Dataset Catalog and Discovery | Build the catalogue that records what data exists, its coverage and its quality state. | Planned |
| 101 | Point-in-Time Correctness Model | Define observation time versus event time and the rules that prevent lookahead. | Planned |
| 102 | As-Of Join and Snapshot Semantics | Implement joins and snapshots that respect knowledge boundaries at every timestamp. | Planned |
| 103 | Data Versioning and Immutability | Make datasets immutable and versioned so any research result can be re-derived exactly. | Planned |
| 104 | Ingestion Pipeline Orchestration | Coordinate acquisition, validation and publication of datasets as an auditable pipeline. | Planned |
| 105 | Data Quality Validation Rules | Encode schema, range, monotonicity and continuity checks as enforced quality gates. | Planned |
| 106 | Outlier, Gap and Anomaly Detection | Detect suspicious data automatically instead of letting it silently enter research. | Planned |
| 107 | Corporate Action and Symbol Change Handling | Handle delistings, renames and contract changes without corrupting historical series. | Planned |
| 108 | Data Lineage and Provenance Tracking | Record where every dataset came from and how it was derived. | Planned |
| 109 | Replay Engine for Historical Streams | Replay historical data in event order to drive deterministic simulation. | Planned |
| 110 | Compression and Retention Policy | Define retention, compaction and archival so local storage stays bounded. | Planned |
| 111 | Storage Performance Benchmarking | Measure read and write performance and tune layout against evidence. | Planned |
| 112 | Data Platform Consolidation and Phase Gate Review | Reconcile the data band and certify point-in-time correctness before feature work. | Planned |

---

## Phases 113-128 — Technical Analysis and Feature Factory

Produces the feature surface strategies and models consume, with multi-timeframe
alignment handled as a correctness problem rather than a convenience.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 113 | Indicator Library Evaluation and Selection | Evaluate free indicator libraries for correctness, coverage, licence and Windows viability. | Planned |
| 114 | TA-Lib Integration Layer | Wrap the native indicator library behind a typed interface with a pure-Python fallback path. | Planned |
| 115 | Core Trend Indicator Set | Implement and validate moving average and trend-strength indicators against reference values. | Planned |
| 116 | Momentum and Oscillator Indicator Set | Implement and validate momentum and oscillator indicators with correct warm-up handling. | Planned |
| 117 | Volatility Indicator Set | Implement volatility measures used for sizing, stops and regime classification. | Planned |
| 118 | Volume and Flow Indicator Set | Implement volume-derived and order-flow-derived indicators. | Planned |
| 119 | Candlestick Pattern Recognition | Detect documented candlestick formations with explicit, testable definitions. | Planned |
| 120 | Chart Pattern Detection | Detect larger structural formations with quantified rather than subjective criteria. | Planned |
| 121 | Support, Resistance and Level Detection | Derive price levels algorithmically with reproducible parameters. | Planned |
| 122 | Divergence Detection | Detect price and indicator divergences with precise, testable rules. | Planned |
| 123 | Market Regime and Volatility State Features | Produce features describing trend, range and volatility regimes. | Planned |
| 124 | Order Book Microstructure Features | Derive imbalance, depth and spread features from book and quote data. | Planned |
| 125 | Derivatives-Specific Features | Derive basis, funding, open interest and term-structure features. | Planned |
| 126 | Multi-Timeframe Feature Alignment | Align features across timeframes without leaking information backwards in time. | Planned |
| 127 | Feature Registry and Metadata | Catalogue every feature with definition, parameters, warm-up cost and lineage. | Planned |
| 128 | Feature Factory Consolidation and Phase Gate Review | Reconcile the feature band and certify leakage-free feature computation. | Planned |

---

## Phases 129-144 — Strategy Registry and Signal Composition

Turns features into normalised, comparable signals and defines how multiple
strategies combine without becoming an unauditable blend.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 129 | Strategy Interface Contract | Define the interface every strategy implements, including state and parameter handling. | Planned |
| 130 | Strategy Registry and Discovery | Build registration, discovery and metadata for available strategies. | Planned |
| 131 | Signal Representation and Normalization | Define a common signal representation so heterogeneous strategies are comparable. | Planned |
| 132 | Baseline Trend-Following Strategy | Implement a reference trend strategy as a validation baseline for the framework. | Planned |
| 133 | Baseline Mean-Reversion Strategy | Implement a reference mean-reversion strategy with explicit regime assumptions. | Planned |
| 134 | Baseline Breakout Strategy | Implement a reference breakout strategy including false-breakout handling. | Planned |
| 135 | Derivatives Basis and Funding Strategy | Implement a strategy exploiting documented derivatives-specific structure. | Planned |
| 136 | Signal Confidence and Scoring Model | Attach calibrated confidence to signals rather than treating them as binary. | Planned |
| 137 | Confluence and Ensemble Aggregation | Combine multiple signals with defined, auditable aggregation rules. | Planned |
| 138 | Regime-Conditional Strategy Routing | Enable or suppress strategies based on detected market regime. | Planned |
| 139 | Multi-Timeframe Signal Coordination | Coordinate signals across timeframes with explicit precedence and conflict resolution. | Planned |
| 140 | Entry and Exit Rule Composition | Separate entry, exit, scaling and invalidation rules into composable units. | Planned |
| 141 | Signal Filtering and Suppression | Apply liquidity, spread, session and event filters before signals reach execution. | Planned |
| 142 | Strategy Parameter Schema | Define typed, validated parameter schemas that optimisation can safely search. | Planned |
| 143 | Strategy Versioning and Provenance | Version strategies so any historical result maps to exact logic and parameters. | Planned |
| 144 | Strategy Layer Consolidation and Phase Gate Review | Reconcile the strategy band and certify signal correctness before backtesting. | Planned |

---

## Phases 145-160 — Event-Driven Backtesting and Benchmarking

Simulates trading with realistic costs. A backtest that ignores fees, spread,
funding or liquidation is treated as a defect, not an approximation.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 145 | Backtest Engine Architecture | Design the event-driven engine and its strict separation from live execution. | Planned |
| 146 | Event Loop and Clock Simulation | Implement deterministic event ordering and simulated time progression. | Planned |
| 147 | Order Matching Simulation | Simulate fills against historical book and trade data with defensible assumptions. | Planned |
| 148 | Fee Schedule Modeling | Model maker, taker and tier-dependent fees per product accurately. | Planned |
| 149 | Spread and Slippage Modeling | Model spread cost and slippage from observed data rather than fixed guesses. | Planned |
| 150 | Market Impact and Capacity Modeling | Estimate impact and the capital capacity beyond which results stop being achievable. | Planned |
| 151 | Funding Rate Simulation | Apply historical funding payments to perpetual positions. | Planned |
| 152 | Margin Interest and Borrow Cost Simulation | Apply borrowing and interest costs to margin positions. | Planned |
| 153 | Liquidation Simulation | Simulate margin calls and liquidation using documented mechanics. | Planned |
| 154 | Latency Modeling | Model decision, network and exchange latency and its effect on fills. | Planned |
| 155 | Portfolio Accounting in Backtest | Maintain accurate multi-asset, multi-product accounting throughout simulation. | Planned |
| 156 | Performance Metric Suite | Compute risk-adjusted return, drawdown, exposure and trade statistics consistently. | Planned |
| 157 | Benchmark and Baseline Comparison | Compare every strategy against buy-and-hold and random baselines. | Planned |
| 158 | Backtest Reproducibility and Seeding | Guarantee bit-identical reruns given identical inputs and seeds. | Planned |
| 159 | Backtest Result Storage and Reporting | Persist results with full configuration and data lineage for later audit. | Planned |
| 160 | Backtesting Consolidation and Phase Gate Review | Reconcile the backtesting band and certify simulation realism. | Planned |

---

## Phases 161-176 — Research Validation and Leakage Control

Decides what counts as evidence. These phases define the gates that any
candidate must pass before it is allowed to influence capital.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 161 | Leakage Taxonomy and Prevention Rules | Enumerate every leakage mechanism and the structural control that prevents each one. | Planned |
| 162 | Train, Validation and Test Splitting Policy | Define chronological splitting rules that forbid shuffled splits on time series. | Planned |
| 163 | Purged and Embargoed Cross-Validation | Implement purging and embargo so overlapping labels cannot leak across folds. | Planned |
| 164 | Walk-Forward Evaluation Framework | Implement rolling and anchored walk-forward evaluation as the primary honesty test. | Planned |
| 165 | Out-of-Sample Holdout Governance | Reserve and govern a final holdout, including limits on how often it may be consulted. | Planned |
| 166 | Sample Size and Statistical Power Requirements | Define minimum trade and observation counts before a result may be believed. | Planned |
| 167 | Multiple Testing and Selection Bias Control | Correct for the number of hypotheses tested during search and selection. | Planned |
| 168 | Monte Carlo and Bootstrap Resampling | Estimate result distributions rather than trusting a single equity path. | Planned |
| 169 | Parameter Sensitivity and Robustness Testing | Reject results that only survive on a knife-edge of parameter space. | Planned |
| 170 | Stress Scenario Construction | Evaluate candidates against crashes, gaps, illiquidity and outage scenarios. | Planned |
| 171 | Regime-Segmented Performance Analysis | Measure performance separately per regime instead of hiding it in an average. | Planned |
| 172 | Transaction Cost Sensitivity Analysis | Determine the cost level at which an edge disappears entirely. | Planned |
| 173 | Statistical Significance Testing Suite | Apply appropriate tests for time-series performance comparison. | Planned |
| 174 | Research Result Reproducibility | Ensure every reported result can be regenerated from recorded inputs. | Planned |
| 175 | Evidence Gate Definition | Codify the machine-checkable gates a candidate must pass to be promotable. | Planned |
| 176 | Validation Consolidation and Phase Gate Review | Reconcile the validation band and certify the evidence standard before modelling. | Planned |

---

## Phases 177-192 — Supervised Machine Learning

Applies supervised learning under the validation regime already established.
Models are candidates for evidence, never sources of guarantees.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 177 | Prediction Problem Formulation | Define precisely what is predicted, over what horizon, and why it is tradable. | Planned |
| 178 | Labeling Methodology | Implement labelling that reflects realistic exits and avoids lookahead. | Planned |
| 179 | Dataset Assembly and Feature Matrices | Assemble point-in-time correct training datasets from the data platform. | Planned |
| 180 | Feature Scaling and Encoding Pipelines | Fit transformations inside folds only, preventing preprocessing leakage. | Planned |
| 181 | Baseline Linear and Tree Models | Establish simple baselines that complex models must actually beat. | Planned |
| 182 | Gradient Boosting Model Integration | Integrate gradient boosting with honest CPU versus GPU capability assessment. | Planned |
| 183 | Neural Network Model Integration | Integrate neural models where evidence justifies their additional complexity. | Planned |
| 184 | Sequence Model Exploration | Evaluate sequence architectures against simpler alternatives on equal terms. | Planned |
| 185 | Symbol-Specific Model Specialization | Determine when per-symbol models beat pooled models given available sample size. | Planned |
| 186 | Regime-Specific Model Specialization | Determine when per-regime specialisation is justified by evidence. | Planned |
| 187 | Probability Calibration | Calibrate predicted probabilities so they can be used for sizing decisions. | Planned |
| 188 | Model Evaluation Metric Suite | Evaluate models on economically meaningful metrics, not accuracy alone. | Planned |
| 189 | Feature Importance and Interpretability | Explain model behaviour well enough to detect spurious or leaked features. | Planned |
| 190 | Model Serialization and Registry | Persist models with full metadata, training lineage and reproducibility information. | Planned |
| 191 | Inference Pipeline and Latency Budget | Serve predictions within the latency the trading cadence allows. | Planned |
| 192 | Supervised Learning Consolidation and Phase Gate Review | Reconcile the supervised band and certify model governance. | Planned |

---

## Phases 193-208 — Reinforcement Learning

Explores reinforcement learning where it is justified, including the honest
possibility that it is not.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 193 | Reinforcement Learning Applicability Assessment | Decide, with evidence, where reinforcement learning beats supervised alternatives. | Planned |
| 194 | Gymnasium Trading Environment Design | Implement a standards-compliant trading environment with correct episode semantics. | Planned |
| 195 | Observation Space Construction | Define observations that contain no future information and are properly scaled. | Planned |
| 196 | Action Space Design | Define an action space that maps cleanly onto executable, valid orders. | Planned |
| 197 | Reward Function Design | Design rewards reflecting risk-adjusted economics rather than raw profit. | Planned |
| 198 | Risk and Constraint Penalties | Encode risk limits into the environment so violations are learned against. | Planned |
| 199 | Environment Determinism and Seeding | Guarantee reproducible episodes under fixed seeds. | Planned |
| 200 | Environment Validation and Sanity Checks | Verify the environment cannot be exploited through simulation artefacts. | Planned |
| 201 | PPO Agent Integration | Integrate a policy-gradient agent with documented, versioned hyperparameters. | Planned |
| 202 | Alternative Algorithm Evaluation | Compare alternative free algorithms on equal footing before committing. | Planned |
| 203 | Training Loop and Checkpointing | Implement resumable training with checkpointing and run metadata. | Planned |
| 204 | Vectorized Environment Scaling | Scale environment throughput within local hardware limits. | Planned |
| 205 | CPU Versus GPU Training Benchmark | Measure which reinforcement learning workloads actually benefit from the GPU. | Planned |
| 206 | Offline Policy Evaluation | Evaluate learned policies offline before any simulated capital is committed. | Planned |
| 207 | Policy Robustness and Stress Testing | Test policies against regimes and shocks absent from training data. | Planned |
| 208 | Reinforcement Learning Consolidation and Phase Gate Review | Reconcile the reinforcement band and certify policy governance. | Planned |

---

## Phases 209-224 — Optimization and Parameter Governance

Searches parameter space without letting the search itself manufacture the
result. Optimisation is treated as a primary source of overfitting risk.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 209 | Optimization Objective Definition | Define objectives that reward robustness rather than peak historical return. | Planned |
| 210 | Search Space Specification | Specify typed, bounded search spaces derived from strategy parameter schemas. | Planned |
| 211 | Optuna Study Infrastructure | Establish persistent studies with durable local storage and resumability. | Planned |
| 212 | Sampler Selection and Configuration | Select samplers appropriate to the search space and evaluation cost. | Planned |
| 213 | Pruning Strategy Configuration | Terminate hopeless trials early without prematurely discarding slow starters. | Planned |
| 214 | Multi-Objective Optimization | Optimise return, risk and stability jointly rather than collapsing them too early. | Planned |
| 215 | Overfitting Control in Optimization | Constrain search so results survive out-of-sample evaluation. | Planned |
| 216 | Nested and Walk-Forward Optimization | Nest optimisation inside walk-forward so selection itself is validated. | Planned |
| 217 | Distributed and Parallel Trial Execution | Run trials in parallel within local CPU, GPU and memory limits. | Planned |
| 218 | Resource-Aware Trial Scheduling | Schedule trials against measured resource cost rather than assumed cost. | Planned |
| 219 | Early Termination Rules | Define when an entire study should stop rather than continue burning resources. | Planned |
| 220 | Optimization Result Analysis | Analyse result surfaces for plateaus and instability, not just best values. | Planned |
| 221 | Parameter Set Versioning | Version parameter sets so any deployed configuration is traceable. | Planned |
| 222 | Parameter Promotion Criteria | Define what a parameter set must prove before it may be used. | Planned |
| 223 | Optimization Audit Trail | Record every study, trial and decision for later audit. | Planned |
| 224 | Optimization Consolidation and Phase Gate Review | Reconcile the optimisation band and certify anti-overfitting controls. | Planned |

---

## Phases 225-240 — Continual and Autonomous Learning

Lets the system adapt over time under governance. Adaptation must never mean
"change anything until recent backtest profit increases".

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 225 | Model Registry and Lifecycle States | Define registered, candidate, shadow, champion, retired and rejected lifecycle states. | Planned |
| 226 | Data Drift Detection | Detect distribution shift in inputs relative to training conditions. | Planned |
| 227 | Concept Drift Detection | Detect decay in the relationship between features and outcomes. | Planned |
| 228 | Performance Degradation Monitoring | Distinguish genuine degradation from ordinary variance before reacting. | Planned |
| 229 | Retraining Trigger Policy | Define evidence-based triggers for retraining instead of blind periodic retraining. | Planned |
| 230 | Scheduled Retraining Pipeline | Automate retraining end to end with full lineage capture. | Planned |
| 231 | Candidate Model Construction | Produce challengers under the same validation regime as any manual research. | Planned |
| 232 | Champion-Challenger Evaluation | Compare challengers against the incumbent on identical, fair evaluation. | Planned |
| 233 | Promotion Gate Enforcement | Enforce the evidence gates mechanically so no candidate can bypass them. | Planned |
| 234 | Shadow Evaluation of Challengers | Run challengers without capital until they earn promotion. | Planned |
| 235 | Automated Rollback Mechanism | Revert to the previous champion automatically when degradation is confirmed. | Planned |
| 236 | Adaptation Audit Trail | Record every autonomous change with its justification and evidence. | Planned |
| 237 | Governance Boundary Enforcement | Make it structurally impossible for adaptation to relax absolute risk ceilings. | Planned |
| 238 | Catastrophic Forgetting and Stability Controls | Prevent retraining from destroying previously validated capability. | Planned |
| 239 | Autonomous Research Refresh Cycle | Schedule recurring data collection, research and re-evaluation autonomously. | Planned |
| 240 | Continual Learning Consolidation and Phase Gate Review | Reconcile the continual learning band and certify governance integrity. | Planned |

---

## Phases 241-256 — Portfolio and Risk Management

Protects capital. The upper risk bounds defined here are immutable and are not
subject to autonomous modification.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 241 | Risk Constraint Taxonomy | Classify constraints as immutable ceilings, policy limits or tunable preferences. | Planned |
| 242 | Immutable Upper Risk Bound Enforcement | Implement absolute ceilings no strategy, model or optimiser can raise. | Planned |
| 243 | Position Sizing Models | Implement sizing driven by volatility, confidence and account equity. | Planned |
| 244 | Per-Trade Risk Limits | Bound the loss any single position can inflict. | Planned |
| 245 | Portfolio Exposure Aggregation | Aggregate exposure across products, symbols and directions into one view. | Planned |
| 246 | Correlation and Concentration Control | Prevent apparent diversification that is actually a single concentrated bet. | Planned |
| 247 | Leverage and Margin Utilization Limits | Bound leverage and margin usage across all margin-bearing products. | Planned |
| 248 | Liquidation Distance Monitoring | Continuously monitor distance to liquidation and act before it is reached. | Planned |
| 249 | Drawdown Control and Circuit Breakers | Halt or reduce trading automatically when drawdown thresholds are breached. | Planned |
| 250 | Loss Streak and Cooldown Rules | Impose cooldowns after abnormal loss sequences. | Planned |
| 251 | Capital Allocation Across Strategies | Allocate capital by validated evidence and correlation, not recent profit alone. | Planned |
| 252 | Cross-Product Risk Netting | Account for offsetting exposure across products without understating true risk. | Planned |
| 253 | Pre-Trade Risk Gate | Make every order pass a mandatory risk check that cannot be bypassed. | Planned |
| 254 | Post-Trade Risk Reassessment | Reassess portfolio risk after every fill and react to breaches. | Planned |
| 255 | Kill Switch and Emergency Flatten | Provide a reliable emergency stop that halts trading and can flatten exposure. | Planned |
| 256 | Risk Consolidation and Phase Gate Review | Reconcile the risk band and certify capital protection before autonomy. | Planned |

---

## Phases 257-272 — Autonomous Orchestration

Runs everything continuously and safely on a single Windows host, with explicit
scheduling instead of an uncontrolled loop of expensive jobs.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 257 | Orchestrator Architecture | Design the long-lived process that owns and supervises all subsystems. | Planned |
| 258 | Task Graph and Dependency Model | Model jobs and their dependencies explicitly as a directed graph. | Planned |
| 259 | Job Scheduling Engine | Schedule recurring work by priority, dependency and resource availability. | Planned |
| 260 | Resource Governor for CPU and GPU | Prevent concurrent heavy jobs from exhausting the host or starving trading. | Planned |
| 261 | Concurrency and Isolation Model | Define threading, process and isolation boundaries between subsystems. | Planned |
| 262 | Subsystem Lifecycle Management | Start, stop and restart subsystems in correct dependency order. | Planned |
| 263 | Supervisor and Watchdog | Detect hung or dead components and recover them automatically. | Planned |
| 264 | Failure Detection and Classification | Classify failures as transient, persistent or fatal and respond accordingly. | Planned |
| 265 | Retry and Recovery Policies | Define per-subsystem recovery behaviour including give-up conditions. | Planned |
| 266 | Persistent Orchestration State | Persist scheduling and subsystem state so restarts resume correctly. | Planned |
| 267 | Crash Recovery and Resumption | Recover coherently from unexpected termination without duplicating work. | Planned |
| 268 | Graceful Shutdown and Draining | Shut down cleanly without abandoning in-flight orders or corrupting state. | Planned |
| 269 | Long-Duration Stability Controls | Prevent leaks, unbounded growth and degradation over multi-day runs. | Planned |
| 270 | Windows Service and Continuity Behavior | Survive sleep, updates, session changes and other Windows host events. | Planned |
| 271 | Runtime Profile Selection | Enable the correct subsystem set for the selected paper or live profile. | Planned |
| 272 | Orchestration Consolidation and Phase Gate Review | Reconcile the orchestration band and certify unattended operation. | Planned |

---

## Phases 273-288 — Telegram Interface and Operations

Makes the system observable and controllable by its operator, and survivable
when something goes wrong.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 273 | Telegram Bot Integration | Integrate the official Bot API as the operator communication channel. | Planned |
| 274 | Authentication and Authorization of Operators | Ensure only authorised chat identities can issue commands. | Planned |
| 275 | Command Surface Design | Design a clear, safe command set with confirmation for dangerous actions. | Planned |
| 276 | Status and Reporting Commands | Expose positions, performance, health and current activity on demand. | Planned |
| 277 | Control and Intervention Commands | Allow pausing, resuming, flattening and emergency stop from the operator channel. | Planned |
| 278 | Alert Taxonomy and Routing | Classify alerts by severity and route them so critical events are never buried. | Planned |
| 279 | Alert Throttling and Deduplication | Prevent alert storms from destroying the operator's attention. | Planned |
| 280 | Operational Metrics Collection | Collect health, latency, throughput and error metrics locally. | Planned |
| 281 | Audit Log and Immutable Event Trail | Record every decision and action in an append-only, reviewable trail. | Planned |
| 282 | Log Rotation and Retention | Bound log growth while preserving what audit and debugging require. | Planned |
| 283 | Backup and Restore Procedures | Back up configuration, state, models and data, and verify restoration works. | Planned |
| 284 | Disaster Recovery Runbook | Document and rehearse recovery from total host loss. | Planned |
| 285 | Incident Response Procedures | Define triage and response for outages, divergence and unexpected losses. | Planned |
| 286 | Maintenance Mode and Scheduled Downtime | Support safe maintenance without abandoning open positions. | Planned |
| 287 | Operational Documentation and Runbooks | Write the procedures an operator follows during normal and abnormal operation. | Planned |
| 288 | Operations Consolidation and Phase Gate Review | Reconcile the operations band and certify operability. | Planned |

---

## Phases 289-304 — Windows Launchers and System Integration

Delivers the two user-facing entry points and proves the assembled system runs
for days without intervention.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 289 | Launcher Contract Specification | Finalise exactly what each launcher must do, verify and refuse to do. | Planned |
| 290 | Repository and Prerequisite Discovery | Locate the repository and validate Windows prerequisites reliably. | Planned |
| 291 | Interactive Configuration Wizard | Collect missing configuration interactively with validation and safe defaults. | Planned |
| 292 | Credential Collection and Persistence Flow | Collect and store credentials securely, never writing them into the repository. | Planned |
| 293 | Paper Launcher Implementation | Implement the paper entry point selecting demo, testnet or simulated execution correctly. | Planned |
| 294 | Live Launcher Implementation | Implement the live entry point with mandatory preflight and risk verification. | Planned |
| 295 | Runtime Profile Wiring | Wire launcher selection through to orchestrator profile and product routing. | Planned |
| 296 | Subsystem Startup Ordering | Start every required subsystem in correct dependency order with health gating. | Planned |
| 297 | Preflight Verification Gate | Block startup when environment, credentials, connectivity or risk checks fail. | Planned |
| 298 | Full-System Integration Testing | Test the assembled system end to end rather than component by component. | Planned |
| 299 | End-to-End Paper Trading Validation | Validate the complete decision-to-execution path in a non-production environment. | Planned |
| 300 | Long-Duration Soak Testing | Run continuously for days and measure stability, drift and resource behaviour. | Planned |
| 301 | Resource Consumption Profiling | Profile CPU, GPU, memory, disk and network against host capacity. | Planned |
| 302 | Failure Injection and Resilience Testing | Inject disconnections, errors and restarts to prove recovery actually works. | Planned |
| 303 | User Operating Guide | Write the guide the operator uses to run GLOBIN day to day. | Planned |
| 304 | Integration Consolidation and Phase Gate Review | Reconcile the integration band and certify readiness for live evaluation. | Planned |

---

## Phases 305-320 — Live Readiness and Staged Activation

Moves to real capital gradually and reversibly. Nothing here is a single
irreversible switch.

| Phase | Title | Purpose | Status |
|:-----:|-------|---------|:------:|
| 305 | Live Readiness Criteria Definition | Define the objective, measurable conditions required before live trading. | Planned |
| 306 | Shadow Mode Execution | Generate live decisions without sending orders and compare against reality. | Planned |
| 307 | Live Order Path Verification | Verify the real order path with minimal size under close supervision. | Planned |
| 308 | Minimal Capital Canary Deployment | Trade the smallest meaningful capital to expose real-world differences safely. | Planned |
| 309 | Live Reconciliation Validation | Prove local state matches exchange state continuously under live conditions. | Planned |
| 310 | Staged Capital Progression Policy | Define the evidence required before each capital increase. | Planned |
| 311 | Live Risk Acceptance Criteria | Define the risk behaviour live trading must demonstrate to continue. | Planned |
| 312 | Live Performance Acceptance Criteria | Define the performance evidence required to justify continued operation. | Planned |
| 313 | Failure Drill Execution | Rehearse outages, disconnections and emergency stops against live conditions. | Planned |
| 314 | Rollback and Deactivation Procedures | Ensure live trading can be wound down safely and quickly at any point. | Planned |
| 315 | Live Monitoring and Escalation | Operate continuous monitoring with defined escalation thresholds. | Planned |
| 316 | Regulatory and Account Compliance Review | Confirm operation remains within Binance terms and applicable obligations. | Planned |
| 317 | Operational Handover Documentation | Document everything required to operate the system without its authors. | Planned |
| 318 | Full System Audit | Audit the complete system against every ADR and stated invariant. | Planned |
| 319 | Final Documentation Synchronization | Bring all documentation into exact agreement with the implemented system. | Planned |
| 320 | Programme Completion and Final Acceptance | Verify all acceptance criteria and formally close the 320-phase programme. | Planned |

---

## Programme invariants

These hold for every phase and are enforced by tests where practical:

- Development happens on `master` only, and every completed phase is pushed to
  `origin/master` with a clean working tree.
- The runtime depends on free and open components only.
- Data comes from officially documented interfaces; scraping is prohibited.
- Binance Global is the only venue in scope.
- No prediction is presented as a guarantee. The objective is a measurable
  probabilistic edge after realistic costs and out-of-sample validation.
- Autonomous adaptation may never raise the system's absolute risk ceilings.
