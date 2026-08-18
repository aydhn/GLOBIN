# Changelog

Every released version of GLOBIN is announced here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) as
[`docs/release/RELEASE_POLICY.md`](docs/release/RELEASE_POLICY.md) applies it.

**A version appears here exactly once.** `python -m tools.quality release`
refuses a changelog that announces one version under two headings, because a
reader of the second cannot tell which describes the release.

**No dates are invented.** Phases 001-015 were delivered before this file
existed, and their individual commit dates are in the Git history rather than
reconstructed here. The `0.1.0` entry groups what the foundation band produced,
by capability rather than by phase, and every group below names something that
can be opened and read.

---

## [Unreleased]

### A credential can be handed to GLOBIN, and refused before it is used

- **Collection is interactive only, and three refusals happen before material
  exists.** A pipe is refused *before* `getpass` is called, because accepting one
  puts the key in shell history and in a process command line. A terminal that
  cannot suppress echo aborts *before the operator has typed anything* --
  `getpass`'s fallback warns before it reads, so converting that warning to an
  error means the value never exists rather than existing and being discarded.
  The material is asked for twice, and there is no flag that turns the
  confirmation off.
- **Whitespace is refused rather than stripped**, along with control characters
  and anything over the measured 2560-byte ceiling. No minimum length is
  invented: what a real key looks like is a fact about a key type, and that is
  Phase 038's. A real PEM key cannot be collected at a single-line prompt at all,
  because it is multi-line -- stated rather than discovered at a terminal.
- **Permission verification has no state meaning "confirmed".** GLOBIN reaches no
  venue, so a member meaning the issuer agrees would be a lie with a name. What
  is decidable locally is containment: a credential is refused for an operation
  whose demanded grants are not a subset of what an operator declared, and the
  converse is never claimed. A demanded `transfer` is withheld **whatever the
  declaration says**, checked before the declaration is consulted.
- `require_permitted` computes the verdict and returns **without touching the
  store** when it refuses. There is no branch in which material is resolved and
  then discarded.
- **`globin secrets` has six verbs and no seventh** -- set, verify, list, delete,
  rotate, health -- matching `SECRET_STORE_CONTRACT.md` section 5 exactly, with a
  contract test comparing the two. `--json` is refused for `set` and `rotate`.
- **Nothing is required to start, and the emptiness is now a derivation.** The
  registry exists and is wired through the composition root, so Phase 038 adds one
  entry and start-up begins demanding it with no plumbing in between.
- Exit code `25` joins the contract, deliberately distinct from `15`: one means
  go and store a credential, the other means go and change a key's permissions.

### A running GLOBIN can finally see its own dependency versions

- **The defect this closes:** `installed_distributions()` walked every
  distribution's metadata and then discarded the version, so an environment two
  minor releases from its lock reported ready. The gate's own twin had returned
  name-and-version pairs since Phase 020; the runtime was the anomaly.
- **`packaging` is adopted as a runtime dependency**, narrowly reversing ADR-0052
  decision 9. It cost nothing: it declares no dependencies of its own and was
  already in `pylock.toml` as a transitive of `ta-lib`, so the lock needed no
  regeneration. Its `Apache-2.0 OR BSD-2-Clause` licence is the register's first
  `OR` expression, and the choice -- Apache-2.0 -- is recorded rather than
  inferred.
- **The runtime writes no second PEP 751 parser.** `packaging.pylock` is the
  specification's reference implementation, so the two-reader tripwire now checks
  the delivered Phase 020 parser *against the specification* rather than pinning
  two hand-written readers to each other.
- `ReadinessReason.DEPENDENCY_UNREADY` finally has a caller. It was declared in
  Phase 027 and nothing anywhere set it.
- **A new gate, `materialize`, asks whether the locked environment could be built
  from local bytes.** Its network fallback is unreachable rather than un-taken:
  the module that decides imports nothing that could reach an index. A corrupt
  cached artefact is left in place and reported -- not deleted, which would
  destroy the evidence, and not re-fetched, which would make the cache a network
  client. An empty wheelhouse is `unmeasured` rather than failed, exactly as
  `drift` treats an unrecorded baseline.
- **The clean-room harness never touches the environment you are using**, held by
  three independent mechanisms and asserted directly: a decoy `.venv` is proved
  byte-for-byte unchanged after both a successful and a failing run.

### Fixed

- `globin --help` claimed `doctor` reports fifteen checks; it reported seventeen
  and now reports eighteen.
- `getpass` was absent from the I/O-capable module list, so nothing stopped an
  inner layer importing a module that reads a terminal.
- Three documentation blocks that had contradicted the tree since Phase 021 --
  `DEPENDENCY_LOCKING.md`'s "Why there is no runtime lock", `DEPENDENCY_POLICY.md`'s
  claim that `project.dependencies` is empty, and `pyproject.toml`'s Phase 1 note.
- A capacity test in the diagnostics surface assumed a connection was accepted as
  soon as it was opened. It was a race in the test rather than in the surface, and
  it stayed hidden until the suite grew heavy enough to widen it.

### GLOBIN has somewhere to keep a credential, and still keeps none

- **The store is the Windows Credential Manager, reached through `ctypes`.** No new
  dependency: `ctypes` was already permitted. `keyring` was declined because a written
  six-question review and two lock updates is a high price for wrapping four calls, and
  a DPAPI-encrypted file was declined on the store contract's own words — "the material
  is **not at rest in a file this repository can reach**", and a DPAPI file is a file.
- **A reference is not a value, and the type system enforces it.** A `SecretReference`
  is ordinary data: printable, loggable, safe in a manifest. A `SecretValue` is
  deliberately **not a dataclass**, so `vars()` raises and `dataclasses.asdict` finds no
  field register; it is **unhashable**, so it cannot become a dict key or a set member;
  it has **no encoder**, in the way `MonotonicReading` has no wire form; and it
  overrides `__format__` as well as `__str__` and `__repr__`, because
  `object.__format__` with a non-empty spec does not route through `__str__` — a type
  redacting only the two a reader expects would *raise* on `f"{value:>40}"`, and a
  redaction that raises is one somebody removes.
- **One key builder, and it folds case because the platform collides silently.** A
  Windows target name is case-insensitive; measured, a credential written under one
  spelling is returned for another with **no error and no warning**. An unfolded builder
  would produce keys that look distinct, pass a test that writes and reads through one
  spelling, and collapse the environment isolation — only once two environments differed
  by case.
- **Rotation is constructed, and the platform forces a step the contract did not spell.**
  A Windows write *replaces*, so by the time the new value is written the old one is
  gone and "only then retire the previous one" would retire nothing. The previous value
  therefore moves to a second slot **first**, and the slot is a bounded key component
  rather than a name suffix — otherwise a reference called `venue_key_previous` would
  address the previous slot of `venue_key` and a rotation would destroy an unrelated
  secret. The outcome reports **whether working material is still obtainable**, because
  that is what an operator is about to ask.
- **Three facts were measured that no document carries.** The oversize failure is
  **1783 `RPC_X_BAD_STUB_DATA`**, which `CredWriteW` documents nowhere — code matching
  the documented list would file the one failure the ceiling exists to cause under
  "unknown". An **RSA-4096 private key in PEM form is 3324 bytes and does not fit** the
  2560-byte ceiling at all; Ed25519 is 122. And the blob encoding had to be **UTF-8**
  rather than the obvious UTF-16: under UTF-16 an ASCII secret encodes to twice its
  length, so a 2560-character key would satisfy the domain and be refused by the
  platform. An API key is ASCII. **A test found that, not a review.**
- **The leak gate covers the four surfaces the contract said nothing covered** —
  an exception's `str`, `repr` and `args`; a traceback with chained causes and notes;
  standard output and error; and the process command line, read from a **real child
  process** so it is what the operating system recorded rather than what a test believes
  it passed.
- **GLOBIN still holds no credentials.** The required set is empty, and empty because
  nothing has needed one. Collecting and validating one is Phase 029's.

### A host now says what it is capable of, and refuses to guess

- **Native architecture is separated from process architecture**, and only
  `IsWow64Process2` may answer the first. Microsoft documents `GetNativeSystemInfo` as
  reporting an ARM64 host "as if the system is x86", and its own Remarks route the
  question elsewhere — so where the modern API is absent the native architecture is
  **`UNKNOWN` rather than a guess**. This changed the phase's plan, which had said to
  fall back.
- **`IMAGE_FILE_MACHINE_UNKNOWN` is `0` and means *not emulated*.** A mapping written
  against the constant's name would report every ordinary native host as unmeasured —
  and this host returns that value on every run, so the mistake would have been
  permanent rather than rare.
- **An unmeasurable required capability degrades rather than blocks.** A capability that
  could not be measured has not been shown to be absent. `IsWow64Process2` arrived in
  Windows 10 version 1709 and the runtime contract declares a floor of "10", so a
  supported host may be unable to answer at all — and CI's runner is a legitimate
  machine that cannot answer everything this one can.
- **The compatibility fingerprint excludes volatile fields by type, not by filter.** It
  is computed over a projection with exactly two fields and nowhere to put a timestamp,
  a process id or a duration. A denylist would be a list somebody must remember to
  extend, and the failure when they do not is a fingerprint that changes every run.
- **Every toolchain capability is optional and there is no way to declare one required.**
  GLOBIN invokes none of them at run time. `pwsh` is not listed at all, because
  PowerShell 7 is absent here and nothing runs it.
- **Exit code `24`, deliberately not `10`.** The latter means the host failed the
  declared contract; the former means it satisfies it and lacks a capability the
  contract does not describe. A launcher should treat those differently.
- New command: `globin diagnostics environment`. New check: `environment.capability`.
  ADR-0073, ADR-0074, ADR-0075.

### Configuration resolves from four sources in a declared order

- **Precedence is two functions and one assembly point.** `precedence()` orders the
  four documents weakest first — base, profile, local base, local profile — on two
  rules: specific beats general, uncommitted beats committed. `profile_from()` orders a
  `--profile` argument above `GLOBIN_PROFILE` above the declared default, because the
  more deliberate act wins. `build_config_sources()` puts the environment **above every
  document**, for the same reason. Phase 026 deliberately returned the four documents as
  a *mapping* so nobody could mistake a listing order for a precedence; that mapping is
  unchanged, and the order now lives beside it rather than inside it.
- **An environment variable name is derived, never declared beside the key.**
  `telemetry.enabled` becomes `GLOBIN_TELEMETRY_ENABLED`. Derivation risks two keys
  colliding on one name, so a contract test asserts the map is injective over every
  known key rather than hoping.
- **An unrecognised `GLOBIN_` variable is refused, and a credential-shaped one is
  refused before it is even looked up.** The prefix is what makes a typo *detectable*;
  the alternative was ignoring typos or refusing to start because of somebody else's
  `PATH`. A variable whose name looks like a credential is refused with the reason,
  because `SECURITY_BASELINE.md` says no secret reaches GLOBIN through configuration and
  the environment is where somebody would try.
- **A missing document is answered by a wrapper, not a flag.** Absence becomes an empty
  layer; a file that exists and cannot be read, a malformed document and an unflattenable
  key all propagate. The decision sits at the composition root, where a reader can see
  which documents are required.
- **Preflight now validates what a run will actually use.** `bootstrap check` resolved
  *no sources at all*, so it validated the declared defaults while the process ran on
  something else — a document or variable the model refuses passed the gate and failed at
  start-up. That was a hole rather than a simplification, and closing it means a bad
  configuration is refused earlier and louder.
- **A superscript two would have crashed the CLI.** `_bounded` screened strings with
  `str.isdigit`, which is true for characters `int` refuses, so the pair raised
  `ValueError` on input it had just accepted — escaping the error taxonomy entirely.
  Unreachable while every string came from a TOML document; live the moment environment
  variables arrived. Found by a property test over generated text, fixed with
  `str.isdecimal`, in both places that had it.

### And, as the eleventh scope amendment, a loopback diagnostics surface

- **Five routes, read-only, off by default.** `/health/live`, `/health/ready`,
  `/health/runtime`, `/metrics`, and `/diagnostics/snapshot` — the last off even when the
  surface is on. With the surface disabled **no server, socket, queue or worker thread is
  constructed**, so opening nothing is a property of the object graph rather than of a
  branch.
- **The bind address is a type, not a literal or a string.** `LoopbackAddress` refuses
  anything `ipaddress` does not call loopback, so the setting **cannot hold** a wildcard,
  a LAN address or a hostname — and the refusal covers spellings a denylist would not
  have enumerated: four zeroes, a bare zero, hexadecimal, a bare pair of colons, an
  IPv4-mapped form, loopback written as a decimal integer. Phase 026 refused an address
  setting outright and was right about the danger; a literal made `::1` unreachable and
  put the guarantee in a constant somebody could edit.
- **Liveness cannot reach a health probe, and that is structural.** A liveness endpoint
  that failed when a disk filled up would turn a disk problem into a restart loop. Its
  port has one method and no way to reach a snapshot, which is asserted by a test where
  the health projection *raises* and liveness still answers.
- **A bounded pool, not a thread per connection.** `ThreadingHTTPServer` is unbounded by
  construction and marks its threads daemons; instead a fixed pool of non-daemon workers
  drains a bounded queue, and a full queue is a deterministic 503 written on the accept
  loop. Twenty requests through a pool of two leave the thread count unmoved, which a
  test measures rather than claims.
- **`GET` and `HEAD` only — and defining two handlers was not enough.** The standard
  library answers every other verb through `send_error`, which writes a **generic HTML
  page** with the requested method in the body, no cache directive and no sniffing
  refusal; the same path handles a malformed request line. One override closes all of it.
  Every response now carries `no-store`, `nosniff`, an explicit length, and **no `Server`
  header** — no Python version reaches a client.
- **Both exposition formats are encoded by GLOBIN, so `/metrics` needs no library.**
  Negotiation follows the scrape protocol's own rule and is **total**: there is no 406,
  because the specification's answer when nothing offered is supported is to fall back to
  Prometheus text 0.0.4. A version GLOBIN does not produce is a non-match rather than a
  near-match. OpenMetrics gained the counter family/sample split, cumulative `_bucket`
  samples through `+Inf`, and the `# EOF` its specification requires — which is also why
  an oversized response is **refused rather than truncated**.
- **Phase 026's dormant listener is gone.** It served a registry GLOBIN never populated
  and had no production caller, so two ways to open a socket — one working, one empty —
  became one. `start_http_server` joins the forbidden list beside its two siblings, and
  the architecture test now names the single module that may reach a socket and asserts it
  contains **no address literal of any kind**.
- **Five new metric families, every budget the exact product of its own domains.** The
  dimensions a remote party could otherwise choose are absent by construction: the route
  *enum* is recorded, whose unrecognised member is the single value `unknown`, so ten
  thousand invented paths produce one series.
- Details: [`docs/engineering/DIAGNOSTICS_ENDPOINT.md`](docs/engineering/DIAGNOSTICS_ENDPOINT.md),
  [ADR-0070](docs/adr/0070-phase-027-widens-to-deliver-the-loopback-diagnostics-surface.md),
  [ADR-0071](docs/adr/0071-configuration-precedence-is-declared-and-an-environment-variable-is-a-derived-name.md),
  [ADR-0072](docs/adr/0072-the-diagnostics-surface-is-loopback-only-read-only-and-bounded-by-construction.md).

### Configuration has a place to live, and four profiles that name documents

- **`config/` exists**, holding a base document, four profiles and a Git-ignored
  `config/local/` for an operator's own overrides. It is a **third** kind of
  location: `.globin/` is evidence about this repository and the user-local tree is
  state about this machine, and every area of that tree is documented *safe to
  delete* — an authored document there would be the first un-deletable thing in a
  tree whose whole design rests on disposability. Configuration is authored operator
  intent, and a document that will one day select live trading must be diffable.
- **Nothing searches.** Given a layout and a profile the candidate documents are a
  pure function of the two: no upward walk, no fallback chain, no
  first-one-that-exists. Each of those is a *precedence* decision and precedence is
  Phase 027's, so `documents_for` returns a **mapping** rather than a sequence — a
  tuple has an order and a reader would read that order as the precedence nobody has
  chosen yet.
- **A profile names a document, not an environment.** `as_config` refuses every key
  outside the register, so a profile document is structurally incapable of asserting
  what an environment is. Phase 035 still owns that question.
- **The four documents set nothing, and that is the deliverable.** GLOBIN does not
  trade, so no setting differs between them for a reason anybody could defend today;
  a contract test folds all five over the declared defaults and asserts the result
  **is** the declared defaults. The day one sets a value, that test fails.
- **A tripwire refused the obvious design and was right.** The first version put a
  four-member `Profile` enum in the domain layer; `demo`, `testnet` and `live` are
  venue vocabulary, which `test_identifier_discipline.py` forbids there — because a
  set of environment names in the innermost layer answers Phase 035's question
  quietly and in the wrong place. The domain now bounds a profile name's *shape* and
  `composition.PROFILES` names the instances.
- `DEFAULT_PROFILE` changes from `"default"` to `"paper"`, so `run/instance.json`
  and every health snapshot record a different value. It must never be `live`:
  ADR-0006's "never downgraded to production" read in the direction nobody writes
  down.
- **`build_configuration` still passes no sources, deliberately.** Phase 026 defines
  where documents live; Phase 027 implements precedence.

### GLOBIN can measure itself, and cardinality is arithmetic rather than a hope

- **A provider-neutral telemetry contract.** Counters, gauges and histograms with
  canonical `globin.*` names; nothing under `domain`, `ports` or `application` names
  OpenTelemetry or Prometheus, and an architecture test enforces one import site per
  library on the real import graph.
- **Every attribute key declares a bounded value set**, so the most series a family
  can produce is a product computable when the descriptor is written — and a
  descriptor that could exceed its own budget **cannot be constructed**. The runtime
  budget check still exists and is provably unreachable for a correct registry: a
  property test asserts it never fires, and a unit test reaches it only by
  pre-filling a family by hand.
- **Two denylists, disjoint, and the disjointness is asserted.** `is_sensitive` is
  reused from the logging module and answers *would this value be a secret*; a second
  list answers *would it be unbounded*. An order id is not a secret and is fatal as a
  label. Two shape rules catch the rest without enumerating spellings: a key equal to
  `id` or ending `_id`, and any key ending `_at`, `_ms`, `_ns` or `_time`.
- **A credential-shaped attribute is refused where a log field is substituted**, and
  the contradiction with ADR-0025 is deliberate: a log field is a leaf, so
  substituting loses one datum, while an attribute is a *dimension*, so substituting
  merges two series under a name that means nothing.
- **Every value is an integer.** A duration is nanoseconds — which costs nothing,
  since `MonotonicReading.since` already returns them — and a ratio is parts per
  million. The ceiling is `2**53 - 1`, and **that is not Python's limit**: every JSON
  reader that is not Python holds numbers as doubles and silently drops low bits past
  it, which is the corruption the float ban prevents arriving through the integer
  door.
- **Spans, with the one context variable ADR-0026 permits.** That record refuses
  `contextvars` for the *correlation id* and it stays refused; the span scope holds a
  `SpanContext` and nothing else, is an instance attribute rather than a module
  global, and never touches a `Logger`. A tripwire asserts both.
- **Async propagation is tested with no event loop, and that is a finding.** Starting
  one fails here: Windows' `ProactorEventLoop` builds its self-pipe from
  `socket.socketpair()`, whose fallback calls `connect()`, which the offline guard
  refuses. The mechanism a task uses is `contextvars.copy_context()`, so that is what
  the tests exercise — identical behaviour, no socket, no marker.
- **Delivery is bounded and retirement is permanent.** The queue drops the *oldest*,
  because during an incident the observation most worth having is the one that just
  happened. The state machine has one edge into `STOPPED` and **none out**, so
  "GLOBIN never hammers a dead endpoint" is a property of the graph. A batch is
  consumed only on `DELIVERED` — a first version restored only on backpressure, which
  made a transient failure lose data silently.
- **Export is off by default, and "off" is an object graph rather than a flag**: no
  exporter, queue, pump or thread is constructed, so opening no socket is structural.
- **The Prometheus listener binds `127.0.0.1` as a literal and nothing can widen
  it.** `start_http_server` defaults its address to `0.0.0.0` — measured on the
  installed package, because the published documentation does not state it at all —
  which is the class of mitigation this repository refuses to leave to memory. There
  is no address setting, and a tripwire forbids every other route to a listener.
- `globin diagnostics telemetry` reports what the registry declares and what the
  configuration would do. It records nothing, starts nothing and binds nothing, and
  returns `OK` even when export is retired: a dropped observation is a fact about the
  observation rather than about the work. Exit code 24 stays free.

### Four runtime dependencies, and what they actually cost

- `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`
  and `prometheus-client`, each with a written six-question review. **`pylock.toml`
  goes from eleven distributions to twenty-six**, measured with
  `pip install --dry-run --ignore-installed` on the pinned interpreter before the
  choice was confirmed rather than after.
- Only two arrivals are compiled and neither needs a compiler: `charset-normalizer`
  publishes a native `cp314` wheel and `protobuf` a `cp310-abi3` one — a stable-ABI
  wheel serving 3.14 through a tag that does not name it, which is the Phase 018
  lesson from the other side.
- **A trap worth recording:** `opentelemetry-api` required `importlib-metadata`
  unconditionally through 1.41.0 and dropped it at 1.42.0, in the same release that
  raised `requires_python`. A review written from memory would have declared a
  dependency this repository does not take.
- `Apache-2.0 AND BSD-2-Clause` had to be written into `DEPENDENCY_POLICY.md`
  **verbatim**: the compound rule reads as though it covers any expression whose
  components are permitted, but the contract test looks for the recorded licence as a
  literal string. A compound is permitted by being *named*, one at a time.
- Neither provider library enters `stack-contract.toml`, because that contract feeds
  the forbidden-import tripwire and listing an *adopted* library would forbid the
  adapter that imports it. The gap and its fix are recorded in ADR-0068.
- **No `DELIVERED_PHASE` constant rose**, and the reason is written down because the
  reflex is to bump them: both are floors bounding registers whose lowest entries name
  phases 045 and 097.

### The tenth scope amendment, and the signal it confirms

- Phase 026 delivers its roadmap title **and** the telemetry foundation. It scores
  one of four against ADR-0021 and is the **second consecutive** amendment to collide
  with a phase title — Phase 280, *Operational Metrics Collection*. ADR-0067 says so
  rather than treating it as normalised.
- ADR-0064 predicted that a tenth amendment before Phase 032 would be evidence the
  roadmap is being treated as a backlog. **It has happened**, and the response is
  recorded rather than deferred: Phase 032 must examine whether Phases 017-032 were
  drawn at a granularity that describes the work, with all ten amendments in front of
  it.
- ADR-0067, ADR-0068 and ADR-0069.

### The native TA-Lib library, provisioned and proved present

- **`ta-lib` is a declared, locked runtime dependency**, and the wheel carries the
  native C library — measured on this host rather than concluded from
  `ta_lib-0.7.1-cp314-cp314-win_amd64.whl`.
  [`docs/engineering/wheel-survey.toml`](docs/engineering/wheel-survey.toml) had
  refused to draw that conclusion from a filename and filed the question against
  this phase by name.
- **Three probes in
  [`stack-contract.toml`](docs/engineering/stack-contract.toml) recompute it.** The
  C library answers with its own version, so it linked and initialised; the
  indicator table is complete, which is the failure a version string cannot catch;
  and a moving average is seeded at `timeperiod - 1`, because an indicator one bar
  short is look-ahead arriving as a plausible number.
- `ta-lib` left the wheel survey for the stack contract, as `numpy` and `pandas` did
  in Phase 022, and `DELIVERED_PHASE` rose 22 → 25 in both gates. **Raising the
  stack gate's floor found a stale deferral** that had been false since Phase 023
  shipped, which is exactly what a floor left too low cannot catch.
- Its review records one surprise: upstream declares `build`, a PEP 517 build
  *frontend*, as an install requirement of a wheel that needs no building, so
  `packaging`, `pyproject_hooks` and `colorama` arrive with it.

### A watchdog, so a wedged process does not stay open for ever

- **A heartbeat is a sequence, not a timestamp.** A component looping inside a
  wedged call rewrites a timestamp indefinitely, so *alive* and *progressing* are
  recorded as different observations. Beating a name nobody registered raises rather
  than doing nothing.
- **The escalation deadline is measured from the stall, not from the request**, so a
  slow evidence capture cannot postpone the end of the process. Recovery has exactly
  one inbound edge, so a component that resumes after a confirmed stall is recorded
  and ignored — a run whose evidence claims a stall it then denies is worth nothing.
- **Exactly one incident per stall is a property of the transition graph** rather
  than of a counter: one edge enters `stalled`, and the machine is confined to one
  thread. `threading` being I/O-capable pushed the state machine out of the
  application layer, which is why the whole chain is testable with a fake clock and
  **no threads at all**.
- **GLOBIN starts its first thread.** Non-daemon, waiting on an `Event` rather than
  sleeping, and disarmed before it is joined. Termination is `os._exit` behind an
  injected port, because `sys.exit` from a background thread ends only that thread —
  and no test ever kills the runner.
- **Phase 024's refusal to publish stacks is answered by destination.** A stall
  incident goes to the user-local `state/watchdog.json`, is deliberately not a
  support-bundle candidate, and reduces every frame path through the reduction Phase
  024 already used for allocation sites. No locals are ever read.
  [`RUNTIME_WATCHDOG.md`](docs/engineering/RUNTIME_WATCHDOG.md), ADR-0066.
- Exit code `23`, six `watchdog` settings, and **no driver**: no command starts one,
  because the long-lived process is Phase 257's.

### Which workloads benefit from a GPU, measured rather than assumed

- **`python -m tools.quality benchmark`** reads
  [`docs/engineering/benchmark-contract.toml`](docs/engineering/benchmark-contract.toml),
  measures every workload it can with the declared warmup, repeat count and
  reduction, and recomputes each verdict from the recorded nanoseconds against the
  declared speedup threshold. Evidence lands in
  `.globin/benchmark/benchmark-manifest.json`.
- **This is the one manifest in the repository that is not byte-stable between
  runs, and it says so rather than hoping nobody notices.** `run.observed` holds
  timings, which move; `findings` holds verdicts, which are a pure function of the
  contract and those timings. The determinism check every other gate applies to its
  whole document is applied here to the findings half only, which is the honest
  form of the check rather than a weakening of it.
- **Every CUDA workload records `unavailable` today**, naming `torch` and Phase
  183. That is a measurement, not a hole: nothing here is stubbed or simulated,
  because a harness inventing a figure for an unavailable backend would be the
  failure ADR-0045 exists to prevent, dressed as a measurement.
- Two traps are handled rather than remembered. A CUDA timing that does not
  synchronise measures submission and reports a speedup of several hundred; a
  threshold of `1.0` would recommend moves that lose once the device transfer is
  paid for. See [`GPU_BENEFIT.md`](docs/engineering/GPU_BENEFIT.md).
- Four capabilities in `gpu-contract.toml` moved from phase 24 to **phase 31**.
  Phase 024 consumes them; Phase 031 owns what GLOBIN does when they are absent.

### A running GLOBIN can say how it is doing

- **`globin diagnostics snapshot`** measures this runtime once and reports one of
  `healthy`, `degraded` or `unhealthy` through the three exit codes every gate
  already speaks. `--json` puts the canonical document on standard output and
  nothing else.
- **A measurement that was not taken is never zero.** Every numeric field carries
  an `Availability` — `measured`, `unavailable`, `unsupported` or `denied` — so
  "psutil is not installed", "Windows has no such counter" and "the operating
  system refused" are three different facts rather than one number and three
  zeroes. No instantaneous CPU percentage is reported at all, because the first
  `cpu_percent` call on a process is documented as meaningless.
- **An unmeasurability that was predicted does not make a system amber.** The CI
  job has no psutil on any run, so a strict rule would report `degraded` forever —
  and a signal that is always amber is one nobody reads.
- **`globin diagnostics bundle`** writes a redacted support archive, validates it
  against its own SHA-256 manifest by reopening the finished file, and publishes it
  atomically. The allowlist is a table with no directory walk anywhere; the
  manifest describes every member except itself; and a `.partial` file never
  appears under the name an operator would look for. See
  [`SUPPORT_BUNDLE.md`](docs/engineering/SUPPORT_BUNDLE.md).
- **`globin diagnostics memory`** runs the allocator tracer for one snapshot and
  switches it off again. A separate verb rather than a flag, because it costs the
  whole process on every allocation while it runs.
- `psutil` is the third runtime dependency and the **first this repository
  imports**, reached through one factory in one adapter so its absence is a
  recorded state rather than an import error.

### Fixed

- **`python -m tools.quality.lock relock` could not regenerate the runtime lock,
  and the gate could not see that it had not.** Both were written in Phase 020,
  when `project.dependencies` was empty; Phase 021 created `pylock.toml` and
  nothing in the tooling learned about it. Declaring a runtime dependency and
  leaving the lock untouched produced a clean `passed`. `relock` and `upgrade` now
  regenerate both locks, and a new `runtime_coverage` finding asks whether the
  runtime lock holds what has been declared.

### GPU capability, measured rather than assumed

- **`python -m tools.quality gpu`** reads
  [`docs/engineering/gpu-contract.toml`](docs/engineering/gpu-contract.toml),
  compares its target against the runtime contract, and asks `nvidia-smi` only the
  fields the contract permits — recording a **state** for each of five
  capabilities rather than a pass. Reaches no network, and has no networked
  subcommand at all: what this host has is answerable from this host.
- **Absence is a state, not a failure.** A machine with no NVIDIA device records
  `ABSENT` and exits `0`, which is what lets the gate run at all on the GPU-less
  `windows-latest` runner CI uses. `ABSENT` and `UNMEASURABLE` are kept apart
  because *we asked and there is none* and *there was nothing to ask* are
  different facts. `ERROR` always fails, whatever the capability's policy: not
  knowing why is a different fact from knowing why.
- **The contract declares an interface, not a baseline.** No driver version, no
  compute capability and no device name is committed, so nothing goes red on a
  driver update and no value is ever bumped without being read. The observed
  values live in the regenerated `.globin/gpu/gpu-manifest.json`.
- **Four traps were measured on the target host, not assumed.** `cuda_version` is
  not a queryable field *and asking for it breaks the entire query*; `DRIVER
  version` and `CUDA version` are both answered by the driver with the word
  *Deprecated*; and the banner spelling has already changed. A detector reading
  any of them would publish a sentence where a version belongs. Hence the
  `[[forbidden_field]]` table, checked against the interface table in the same
  file, plus a shape check on every recorded value.
- **A CUDA runtime and a CUDA toolkit are asked separately**, and neither is
  inferred from the other. The development host has the first without the second,
  which is the proof the inference would be wrong — and the distinction is what
  Phase 024 needs when it asks which workloads benefit.
- Nothing here times anything. Detection is Phase 023; benefit is Phase 024.

### The runtime explains itself

- **GLOBIN logs.** Phase 006 built the logging subsystem and nothing in the
  product called it — `build_logger` had no production caller and the CLI printed
  with `print`. There is now a lifecycle event vocabulary, a fan-out to a console
  and a bounded file, and a diagnostics subsystem the composition root assembles.
- **A fifth runtime area, `logs/`, and it is bounded because it is the only one
  appended to.** Every other area holds small documents published whole and
  atomically; a log is the one thing GLOBIN writes that grows, which is exactly
  the risk ADR-0059 named about adding a directory. `RotationPolicy` is a
  validated value type — a policy that could not be honoured cannot be constructed
  — and `ceiling_bytes()` states the worst case as a number rather than leaving a
  reviewer to multiply. Eight mebibytes at the defaults.
- **The file sink flushes every record and the stream sink does not.** The file
  exists so a process that dies badly leaves an explanation behind, and an
  explanation still in a buffer when the interpreter is killed is not one.
- **The three process fault hooks, installed through an injected registry.**
  `sys.excepthook`, `threading.excepthook` and `sys.unraisablehook` are replaced
  and put back — not chained to, because the default prints prose to standard
  error and one fault should produce one report. `SystemExit` and
  `KeyboardInterrupt` are `INFO`: an operator who sees `CRITICAL` on every Ctrl-C
  stops reading it.
- **`faulthandler`, to its own non-JSON file.** A native traceback is written by C
  with no encoder involved, which is why it still works when the interpreter
  cannot run Python — so it goes beside the log rather than in it. No signal is
  registered: `faulthandler.register` does not exist on Windows, measured rather
  than assumed.
- **A bridge for standard-library records and Python warnings**, which is the
  addition `adapters/observability.py` anticipated in Phase 006. GLOBIN's own call
  sites still do not use `logging`, and
  `tests/architecture/test_logging_discipline.py` fails if that changes.
- **The existing design was extended, not replaced.** ADR-0026's explicit
  correlation stands — no `contextvars` — the record envelope is unchanged, and
  the warning *filters* are untouched.
- **What redaction does not cover is stated rather than implied.** It matches
  field names, so a credential inside an exception message is written. Nothing can
  close that until Phase 028 gives GLOBIN a set of secret values to scan for; the
  defence until then is the rule that a secret is never passed to a diagnostic.
- ADR-0060 records both halves, and scores the **seventh scope amendment** against
  ADR-0021's four criteria at one of four — failing the "no phase owns the work"
  criterion worse than any amendment before it, because Phase 006 has already
  shipped.

### The scientific stack, verified rather than assumed

- **`python -m tools.quality stack`** recomputes what
  `docs/engineering/stack-contract.toml` declares against this environment. Four
  registers name a version — `pyproject.toml`, `pylock.toml`, the installed
  `.dist-info` and the contract — and the gate's first job is to hold all four
  against each other. Each artefact's own `WHEEL` record is read for the PEP 425
  tag it was built from, which is what catches a wheel for another ABI.
- **Seven behaviour probes**, each defending a rule written down elsewhere:
  `float64` is IEEE-754 binary64; non-finite results propagate rather than being
  substituted; a 64-bit overflow wraps **and says so**; a float column survives a
  frame round trip bit-identically; a missing value does not become `0.0`; a
  UTC-aware timestamp keeps its instant and its awareness; and copy-on-write is
  active. Each was run on the target host before it was written down.
- **Nothing under `src/globin` imports `numpy` or `pandas`**, and
  `tests/architecture/test_stack_discipline.py` fails if anything starts.
  Verifying is not adopting: `docs/PRECISION_POLICY.md` rule 1 is a one-way door,
  and Phases 113-128 own the numeric type indicators and models use.
- **`numpy` and `pandas` left `wheel-survey.toml`**, and `DELIVERED_PHASE` rose
  from `18` to `22`. ADR-0052 refuses a survey entry naming a phase that has
  shipped; the question moved rather than closed, because once a library is
  installed the answerable question is whether it computes.
- ADR-0058 records the decisions, including why upstream's own test suites are
  deliberately not run.

### A runtime filesystem, and a process lifecycle

- **GLOBIN keeps mutable state in a user-local tree** under the Windows Known
  Folder Microsoft documents as `%LOCALAPPDATA%`, in a `GLOBIN` namespace, with
  four areas whose difference is a promise about deletion: `state`, `cache`,
  `run`, `tmp`. `.globin/` inside the checkout stays what it was — evidence about
  *this repository*, read by CI. **No secret, no credential and no bulk data ever
  goes in the runtime tree.**
- **Every small document is published atomically**: a temporary file in the
  destination's own directory, `flush`, `os.fsync`, close, `os.replace`. A reader
  never observes a truncated document, and a failed write leaves the previous one
  intact — asserted by breaking each stage alone. `NaN` and `Infinity` are refused
  rather than written, because they are not JSON.
- **One coordinator per machine**, decided by a non-blocking `msvcrt.locking`
  acquisition and by nothing else. **The presence of `instance.lock` is never
  evidence that GLOBIN is running**: a crashed process leaves one behind, so a
  stale file must not block a start-up and is never deleted on a guess. Proved
  across real Windows processes, including one that leaves through `os._exit`.
- **Shutdown is `try`/`finally` in a fixed order**, and every step is reached even
  if the one before it failed. Signals are registered only where the platform has
  them, a handler sets a flag and returns, and `atexit` is a best-effort net that
  nothing rests on — Python's own documentation says it does not run on a hard
  kill, which is the case crash safety is about. What makes a crash survivable is
  atomic publication.
- **Four checks and three exit codes joined the bootstrap** — `paths.boundary`,
  `state.persistence`, `state.previous_run`, `instance.lock`, and codes `19`, `20`
  and `21`. `globin doctor` probes the lock and does not keep it, so a read-only
  diagnostic still runs beside a running GLOBIN.
- **An unclean previous run is a warning, not a refusal.** Whether an instance is
  running is the lock's question and only the lock's.
- ADR-0059 records the decisions; **ADR-0057 records that delivering this in Phase
  022 was the programme's sixth scope amendment, that it scored one of ADR-0021's
  four criteria, and that it is the weakest amendment in the programme.**

### Runtime dependencies and the installed application

- **`project.dependencies` is no longer empty.** `numpy` and `pandas` are
  declared, each with the six-question review from `docs/DEPENDENCY_POLICY.md`
  recorded in `docs/engineering/dependency-reviews.toml` at `scope = "runtime"`.
  The invariant that held from Phase 001 to Phase 020 ended deliberately, and the
  contract test that asserted it now compares the declared set against the
  reviewed set **in both directions** rather than asserting emptiness — which
  catches a dependency added without a review, and a review left behind for
  something no longer declared.
- **`pylock.toml` arrived in the same commit**, which is the pairing
  `LOCK_RUNTIME_UNLOCKED` had been enforcing since Phase 020. It records five
  distributions with digests, and `tools/quality/lock` recomputes every claim it
  makes about itself exactly as it does for `pylock.dev.toml` — a committed lock
  nobody validated would make ADR-0054 true of one file and false of the other.
- `[runtime] roots` is compared against `project.dependencies` in both
  directions, as `[dev] roots` already was against the `dev` extra.
- **`scripts/bootstrap.ps1` installs three things now**: the toolchain, the
  runtime lock, and GLOBIN itself with `--no-deps --editable`. The order is what
  makes `--no-deps` safe, and installing the project is what creates the `globin`
  command.
- `lock installed` compares the environment against **both** locks, and knows
  that the project's own distribution is expected to be installed —
  declared in a `[project]` table rather than filed under `[environment] seeded`,
  which means something else.
- The SBOM describes the locked transitive set as well as the declared set:
  seventy-nine components against twenty-five. The dependency graph stays
  narrower on purpose, because PEP 751 records no edges.
- **PEP 735 was decided and not adopted**, and the vulnerability threshold stays
  blunt with the waiver register as its pressure valve. Both were deferred into
  this phase by name; both are now answered in ADR-0055.
- `docs/DEPENDENCY_POLICY.md` gained `0BSD`, `Zlib` and `CC0-1.0`, and a rule for
  compound SPDX expressions. `numpy` publishes an expression rather than an
  identifier, and recording only its most prominent part would have made the
  register say something the project does not.
- **Nothing imports either package.** Phase 022 installs and verifies the
  scientific stack; this phase declared, reviewed and locked it, and makes no
  claim about whether it computes correctly.

### Application bootstrap

- **GLOBIN has an entry point.** `globin` is a console script and
  `python -m globin` reaches the same `main`; neither wrapper holds logic, and a
  contract test asserts that rather than trusting it.
- `globin doctor` reports on this host and keeps going past a problem;
  `globin bootstrap check` refuses at the first one; `globin bootstrap evidence`
  writes `.globin/bootstrap/bootstrap-manifest.json`. One pipeline, one report
  type, one set of judgements — only the stopping rule differs.
- **Twelve checks**, from finding the project root to the aggregate, each with a
  stable identifier, a category, an exit code and a remediation sentence.
- **Fail-closed is a property of a type.** `BootstrapOutcome` refuses to hold a
  `RuntimeContext` unless every check passed, so a run that failed cannot hand
  anything downstream — there is no flag to read and no convention to remember.
- **A stable exit-code contract.** `0`, `1`, `2` and `3` keep the meanings every
  gate under `tools/` gives them; `10` upwards name the failure class, one code
  per class, pinned to literals by a contract test. The earliest failing check
  decides, and unmeasured outranks failed.
- **No absolute path can reach the evidence**, structurally rather than by
  filtering: a path becomes a three-outcome `RecordedPath` at the moment it is
  observed, and the domain cannot hold a `Path` at all because it may import no
  I/O-capable module. The runtime tree is therefore declared *relative to the
  project root*, and only two of its six roots are ever created.
- **Working-directory independent.** The root is found by a bounded upward search
  for a `pyproject.toml` that names this project, so a checkout nested inside an
  unrelated repository does not borrow its parent.
- No secret value reaches any output. Every observed field is redacted where the
  record is built, and `tests/contract/test_bootstrap_contract.py` applies the
  verifier's own scanner to what was produced — two mechanisms, neither importing
  the other, with five sentinel values asserted absent by their own text.
- **Phases 026 to 030 keep their work.** `checks()` is a registry rather than a
  fixed list, and the checks whose subject does not exist yet are absent from it
  rather than present as placeholders: a check reporting `unmeasured` claims a
  measurement somebody attempted.
- This is the programme's **fifth scope amendment**, and ADR-0056 records it
  against ADR-0021's four criteria one by one, including the two it fails.

### Dependency locking

- The development toolchain is locked. `pylock.dev.toml` records all forty-nine
  distributions the seven declared tools resolve to, each with a digest, in the
  PEP 751 format `pip lock` produces. Before this, seven were pinned by the
  workflows and the other forty-two entered an environment at whatever version an
  index served that day.
- **The lock is load-bearing rather than decorative.** `scripts/bootstrap.ps1`
  builds `.venv` from it and pip verifies every digest; an unreadable lock is a
  refusal rather than a silent fall back to the pins, and `-FromPins` restores the
  previous behaviour as a deliberate act.
- **The vulnerability audit changed meaning, not only scope.** It ran against a
  requirements file synthesised from the pins, which `pip-audit` then resolved
  against a live index *at audit time* — so the report described a resolution
  nobody had installed, and two runs on one commit could disagree.
  `pip-audit --locked` resolves nothing, so the audited set is the installed set.
- Every claim the lock makes is **recomputed from the lock's own evidence** by
  `python -m tools.quality lock`, offline: each digest, each artefact host, each
  wheel's PEP 425 tags against the runtime contract, and each version the four
  registers carry. pip wrote the file and labels the feature experimental;
  validating it with pip would establish only that pip agrees with itself.
- `lock installed` compares this environment; `lock relock` and `lock upgrade`
  regenerate the lock and reach the index. A relock holds the workflow pins and
  the producer, so it records the transitive set rather than upgrading the tools
  somebody chose. A regenerated lock that is wrong *about itself* is refused and
  set aside with the committed file untouched; one that merely disagrees with the
  pins is kept, and the exact edits are printed.
- **There is no runtime lock, and that is enforced rather than remembered.**
  `project.dependencies` is empty, and `pip-audit --locked` raises on a lock
  recording no packages — so creating one would break the gate this work
  strengthens. `LOCK_RUNTIME_UNLOCKED` fails the moment a runtime dependency is
  declared without `pylock.toml` beside it, which is Phase 021's to add.
- What the gate cannot check is stated rather than implied: pip records no
  dependency edges, so nothing offline can prove every locked package is reachable
  from a declared root.

### Secret store contract

- [`docs/security/SECRET_STORE_CONTRACT.md`](docs/security/SECRET_STORE_CONTRACT.md)
  records what Windows actually offers a credential store, closing a question
  ADR-0048 left open when it chose the store's properties as capabilities "so that
  Phase 028 can satisfy them with whatever Windows actually offers".
- **No store is implemented and no mechanism is chosen.** The measured limits bind
  Phases 026 to 029: a credential blob has a documented 2560-byte ceiling, a target
  name is case-insensitive and cannot be edited after creation, a write replaces
  with no compare-and-swap, and the protection separates accounts rather than
  processes. No claim of memory erasure is made, because CPython cannot support one.

### Environment drift

- The machine the gates are measured on is now compared against a baseline a
  person accepted, not only against the contract.
  `python -m tools.quality.drift accept` records this host;
  `python -m tools.quality drift` reports what has changed since and writes
  `.globin/drift/drift-manifest.json`. `check` never records a baseline — one that
  recorded whatever it found would certify its own observation.
- **With no accepted baseline the verdict is `unmeasured`, not clean.** A fresh
  clone exits `3`. "Could not look" and "looked and found nothing" are different
  facts and the three-valued verdict vocabulary exists so they never share a
  colour.
- Each way a host can diverge is classified in
  [`docs/engineering/drift-policy.toml`](docs/engineering/drift-policy.toml), and
  every recorded repair verdict is recomputed from the action declared beside it:
  an entry claiming a fault is repairable in place whose own declaration does not
  support that fails offline.
- **`drift` fails where `runtime` correctly passes.** The contract declares a
  patch floor, so an interpreter that went *backwards* satisfies it; a
  `PIP_INDEX_URL` or a machine-wide `pip.ini` appearing violates nothing at all.
  Those are changes somebody made to the machine, and they were previously
  invisible.
- **Repair short of recreating the environment now exists, for one fault.**
  `RUNTIME_BASELINE.md` answered five distinct `.venv` faults with "rebuild with
  `-Recreate`"; four of them need it. `pyvenv.cfg` is read at interpreter
  start-up, so `python -m tools.quality.drift repair` corrects
  `include-system-site-packages` by rewriting one key. Everything else names what
  a person should run, or something outside the repository this tooling may not
  touch.
- Reasoning:
  [ADR-0053](docs/adr/0053-drift-is-measured-against-an-accepted-baseline-and-repair-is-a-classification.md),
  and [`docs/engineering/ENVIRONMENT_DRIFT.md`](docs/engineering/ENVIRONMENT_DRIFT.md)
  for what to do about each finding.

### Documentation and secret hygiene

- A policy document may no longer defer a question to a phase that has already
  answered it. Four rows did — in the configuration, identifier, precision and
  value-type policies — telling a reader a question was open, and pointing at the
  wrong number. The convention for recording a met deferral already existed in two
  of the same tables and had simply not been applied; a contract test now compares
  every such row against `ROADMAP.md` in both directions.
- A fifth secret-hygiene control: a committed `.toml`, `.json` or `.yaml` naming a
  key `api_key`, `password`, `token` or similar is refused, whatever its value.
  The filename tripwire does not see it, and the content scanner matches issuer
  grammars rather than key names. The register is reused rather than restated.

### Wheel availability

- The libraries the roadmap schedules are surveyed against the pinned interpreter
  in [`docs/engineering/wheel-survey.toml`](docs/engineering/wheel-survey.toml),
  recording for each the version read, its published `Requires-Python` and the
  wheel filenames the index offers. `python -m tools.quality wheels` recomputes
  every recorded verdict from those filenames offline and writes
  `.globin/wheels/wheel-manifest.json`; `python -m tools.quality.wheels probe`
  asks the index whether the record is still true.
- **Every scheduled library has a wheel for CPython 3.14 on `win_amd64`**, so the
  runtime contract is unchanged. Reasoning and the three findings are in
  [`docs/engineering/WHEEL_AVAILABILITY.md`](docs/engineering/WHEEL_AVAILABILITY.md).
- A gap is recorded and owned rather than treated as a failure: a verdict of
  `source-only` or `absent` must name the phase answering for it, and only an
  unowned gap fails the gate.
- Nothing is resolved, locked or adopted. `project.dependencies` is still empty
  and dependency resolution remains Phase 020's.

### Runtime baseline

- The supported Windows host, CPython and project environment are declared in
  [`docs/engineering/runtime-contract.toml`](docs/engineering/runtime-contract.toml)
  and checked against the machine by `python -m tools.quality runtime`, which
  writes `.globin/runtime/runtime-manifest.json`.
- `scripts/bootstrap.ps1` builds `.venv` from a verified interpreter and installs
  the toolchain the workflows already pin; `scripts/preflight.ps1` diagnoses a
  host and changes nothing.
- `scripts/verify.ps1` now runs under `.venv\Scripts\python.exe` and refuses to
  run without it, so which interpreter measured a result is recorded rather than
  decided by `PATH` order. No automation depends on activation.
- Every path outside the repository is recorded in the evidence as a fingerprint
  rather than a path, and `pip` configuration is recorded as which scopes exist —
  never a value.
- A `Runtime baseline` job builds the environment on a clean Windows runner with
  the same script a developer runs.
- Reasoning:
  [ADR-0050](docs/adr/0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md),
  and [ADR-0051](docs/adr/0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md)
  for the roadmap amendment it required.

---

## [0.1.0] - 2026-08-15

The foundation baseline: the first version of GLOBIN, closing Phases 001-016.

**This release does not trade.** It has no exchange connection, no credentials,
no market data, no strategy and no backtesting. What it contains is the
repository, the rules every later phase obeys, and the verification backbone that
makes those rules enforceable rather than merely written down. Anything that
talks to an exchange belongs to Phase 033 and beyond.

### Repository and engineering foundation

- Project identity, the master-only branch rule and the exchange scope, encoded
  in `globin.project_contract` and asserted rather than documented.
- The fixed 320-phase programme as twenty bands of sixteen, in `globin.roadmap`.
- The engineering contract, definition of done, documentation standard,
  repository layout and an explicit nine-tier authority order for resolving
  conflicts between documents.
- One error taxonomy: a single root, five categories chosen by who must act, and
  no inheritance from builtins.

### Architecture

- Five layers — domain, ports, application, adapters, runtime — with
  dependencies pointing inward, declared machine-readably in
  `docs/architecture/dependency-rules.toml` and enforced against the real import
  graph read from the AST.
- One composition root, and no work performed at import time.
- Domain value types over `Decimal`: exact arithmetic or refusal, rounding always
  an argument, an injected clock behind two ports, and identifiers that register
  kinds rather than instances.
- Forty-nine architecture decision records, indexed, with superseded decisions
  kept rather than deleted.

### Tests and quality

- Six test levels decided by directory, with markers applied by a collection
  hook so the layout and the selection cannot disagree.
- Offline by construction: an autouse fixture refuses outbound sockets, and a
  second restores the environment and working directory a test changed.
- Property-based testing under two Hypothesis profiles, the CI one derandomised.
- Branch coverage over both the package and the tooling, against a floor of 95.
- Mutation testing as a repository-native harness, gated by a committed survivor
  set whose every entry carries a written argument.
- Deterministic sharded execution, proving the suite's result is invariant under
  partitioning into separate processes.

### Continuous integration

- One command table defines every check, and the local gate, the pre-commit hook
  and CI all read it — so they cannot drift.
- One aggregate check decides a run, and a required job that never started is
  recorded as unmeasured rather than passing by omission.
- Machine-readable test evidence with a versioned, self-digesting manifest and a
  checksum file, carrying no wall clock and no absolute path.

### Supply chain and security

- Dependency inventory across the three registers that declare a dependency,
  with drift reported rather than reconciled silently.
- A deterministic CycloneDX 1.7 SBOM generated in-repository, built twice and
  byte-compared on every run.
- Vulnerability audit with an expiring waiver register judged against the commit
  date, and a credential scanner reporting digests rather than values.
- Every GitHub Action pinned to a full commit SHA, declared in a manifest and
  compared against the workflows in both directions.
- A read-only token by default, no repository secrets, and no privileged
  triggers a fork could reach.

### Repository governance

- Code ownership declared once and validated offline, with every
  security-sensitive path owned more specifically than by the catch-all.
- A private vulnerability reporting channel, a written response runbook, and
  public issue templates that do not solicit exploit detail.
- Secret-handling rules: a secret lives outside the tree and is redacted before a
  record of it exists.

### Release governance

- A single-source project version, read by the build backend from the same file
  that defines it.
- This changelog, a release policy, and the Phase 001-016 foundation acceptance
  matrix in both prose and machine-readable form.
- A release gate that checks the contract deterministically, publishes evidence
  as release assets and covers every asset with a SHA-256 digest.
- Tag protection against deletion and movement, and release immutability enabled
  before this release was published.

### Known limitations

- **The release tag is annotated and unsigned.** This host holds no signing key
  material, and none was manufactured to satisfy a checklist. Recorded as
  `FND-P-05` in the acceptance matrix.
- **No packaging build has been run.** `pyproject.toml` declares a distribution
  and Hatchling can read its version, but no wheel or source distribution has
  been produced or verified. That belongs to Phases 017-032.

[Unreleased]: https://github.com/aydhn/GLOBIN/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/aydhn/GLOBIN/releases/tag/v0.1.0
