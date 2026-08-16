# Application bootstrap

How a GLOBIN process decides whether it may start, what it is told when it may
not, and what the rest of the system is handed when it may.

**This reaches no network.** No exchange is contacted, no credential is read and
no order is placed. Binance interfaces begin at Phase 033; the launchers that
will call this begin at Phase 289. What is here is the local machinery both will
need, and nothing else.

The decisions are in
[ADR-0056](../adr/0056-phase-021-widens-to-deliver-the-application-bootstrap.md),
which also records that delivering this in Phase 021 was the programme's fifth
scope amendment and which of ADR-0021's four criteria it failed. This document is
how to use what that decided.

---

## The lifecycle

```text
globin / python -m globin
  → parse the command line
  → find the project root            bounded upward search for a pyproject.toml
  → read the declared baseline       docs/engineering/runtime-contract.toml
  → judge the host                   system, release, architecture, pointer width
  → judge the interpreter            implementation, version, build
  → judge the environment            sys.prefix against the declared .venv
  → read the project's identity      installed metadata, else the package
  → read dependency readiness        declared, locked, installed
  → bind and validate configuration  the Phase 007 model
  → prepare the runtime tree         only the allowlisted roots are created
  → resolve the mutable tree         user-local, and every area inside its root
  → probe state persistence          a document written, replaced and removed
  → read the previous run's record   a diagnostic, never a claim about this one
  → probe the coordinator lock       acquired and released; ownership is later
  → check secret readiness           empty today, and true over an empty set
  → assemble the RuntimeContext      only if every check passed
  → write the evidence               .globin/bootstrap/bootstrap-manifest.json
  → READY
```

`project.root` is first because everything after it is read from underneath the
root. The order is the dependency order, and it is also what the exit code reads:
the **earliest** failing check decides, so a caller is told the first thing that
was wrong rather than an arbitrary one.

**A gate stops at the first refusal; a diagnostic does not.** `bootstrap check`
refuses as soon as something fails, because everything after it would be judging
a host that has already been rejected. `doctor` measures everything it still can
and records the rest as unmeasured. One pipeline, one report type, one set of
judgements — only the stopping rule differs.

---

## Fail-closed

`RuntimeContext` is the object that authorises everything downstream, and
[`BootstrapOutcome`](../../src/globin/domain/bootstrap.py) refuses to hold one
unless every registered check passed. A run that failed therefore cannot hand
anything on, because there is nothing to hand: no flag to read, no convention to
remember, and no path by which a worker, a connection or a scheduler could be
started by a process that was told not to start.

---

## The command line

```text
globin --help
globin --version
globin doctor [--json]
globin bootstrap check [--json]
globin bootstrap evidence
```

`globin` is the console script `pyproject.toml` declares; `python -m globin`
reaches the same `main` through `globin/__main__.py`. Neither wrapper holds
logic, and a contract test asserts that rather than trusting it.

**The console script exists only once GLOBIN is installed.** `scripts/bootstrap.ps1`
installs it. Running from a source checkout, `python -m globin` works and
`globin` does not — and `doctor` says so as a warning on `project.identity`
rather than leaving a reader to wonder why a command is not found.

| Command | What it does | Writes |
|---|---|---|
| `--version` | The version, from installed metadata or the package | Nothing |
| `doctor` | Reports on the host and keeps going past a problem | The runtime tree |
| `doctor --json` | The same report as one JSON document | The runtime tree |
| `bootstrap check` | Refuses unless every check passes; stops at the first | The runtime tree |
| `bootstrap check --json` | The same, as JSON | The runtime tree |
| `bootstrap evidence` | Runs the gate and writes the manifest | The manifest |

Under `--json`, **standard output carries JSON and nothing else**; the human
table goes to standard error. A caller piping this into a parser gets a document;
a person watching the terminal still sees what happened.

`doctor` and `bootstrap check` are read-only apart from creating the evidence
directory. Neither changes configuration, rotates a secret, writes a credential,
installs a dependency, edits a lock or touches the source tree. Two runs in a row
report the same thing.

---

## Exit codes

`0`, `1`, `2` and `3` keep the meanings every gate under `tools/` gives them.
From `10` upwards, one code per failure class, so a launcher can branch on the
reason without parsing English.

| Code | Meaning |
|---:|---|
| 0 | Every check passed |
| 1 | The run could not be completed |
| 2 | The command line was not understood |
| 3 | A check could not be measured, which is never a pass |
| 10 | This host is not a supported one |
| 11 | This interpreter is not the declared one |
| 12 | This is not the project's own environment |
| 13 | A declared dependency is missing or unlocked |
| 14 | The configuration did not validate |
| 15 | A required secret reference did not resolve |
| 16 | The project root or its runtime tree is unusable |
| 17 | The bootstrap failed in a way it does not account for |
| 18 | This GLOBIN could not state its own name and version |
| 19 | The recorded runtime state could not be read |
| 20 | Another GLOBIN coordinator is already running on this machine |
| 21 | The runtime state could not be written |
| 22 | A diagnostic could not be produced, which is not a health verdict |
| 23 | The watchdog ended this process, which did not stop when asked. **No command returns this** — the watchdog terminates rather than returning, so a launcher seeing it knows the run did not choose its own ending. See [`RUNTIME_WATCHDOG.md`](RUNTIME_WATCHDOG.md). |

Unmeasured outranks failed: a check that could not run has not passed, and
reporting it as a specific failure would claim knowledge nobody has.

`22` is Phase 024's, and it is the one code here that is not about starting up.
`globin diagnostics snapshot` reports a *health state* through the same three
codes every gate under `tools/` uses — `0` healthy, `1` unhealthy, `3` degraded —
so a script that branches on one command branches on this one. That leaves the
case where no snapshot could be produced at all, which is not a health state but a
failure to measure one, and this is its code. Collapsing the two would make *the
process is unhealthy* and *nobody could tell* indistinguishable to the consumer
that most needs them apart.

`tests/contract/test_bootstrap_contract.py` pins every number to a literal. A
launcher reads these, so changing one is a breaking change.

---

## The checks

| Identifier | Answers |
|---|---|
| `project.root` | Where the project is, found by bounded upward search |
| `runtime.host` | The operating system and its release |
| `runtime.architecture` | The processor architecture and pointer width |
| `python.implementation` | CPython, and not a free-threaded build |
| `python.version` | The declared minor line exactly, the patch as a floor |
| `python.environment` | `sys.prefix` is the project's own `.venv` |
| `project.identity` | Which GLOBIN this is, and where the version came from |
| `dependency.lock` | Declared, locked and installed |
| `config.valid` | The configuration binds and validates |
| `paths.runtime` | The declared roots are usable |
| `secrets.required` | Every required reference resolves |
| `bootstrap.ready` | The aggregate |

`globin.domain.bootstrap.checks()` is the registry, and it is a function so that
a later phase adds to it rather than rewriting it.

### What is deliberately not registered

A check whose subject does not exist would have to report `unmeasured`, and that
would claim a measurement somebody attempted. These are absent instead, each with
the phase that owns it:

| Not registered | Owner |
|---|---|
| Which configuration files exist, and what profiles they describe | Phase 026 |
| Which sources are consulted, and in what order | Phase 027 |
| Whether the local secret store holds a reference | Phase 028 |
| Collecting and validating a credential | Phase 029 |
| The wider health-check suite a long-running process needs | Phase 030 |

`secrets.required` **is** registered and passes today, because GLOBIN holds no
credential — so the set of references a start-up must resolve is empty and the
claim over it is true. Its summary says that is why, because a vacuous truth and
a skipped check look identical in a log and mean opposite things.

Nothing under `src/globin/` carries a credential-shaped name.
[`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md)
§1 gives the reference type to Phase 028 and forbids the name until `README.md`
says the capability exists; a contract test enforces it.

---

## Remediation

| Symptom | What to do |
|---|---|
| `no project root was found` | Run from inside a checkout. The search reads `pyproject.toml` and stops after twelve directories, so it will not borrow an unrelated parent project. |
| `this interpreter is not running inside a virtual environment` | Build `.venv` with `scripts/bootstrap.ps1` and run through `.venv\Scripts\python.exe`. |
| `this interpreter belongs to a different environment` | Same, and check what `python` resolves to — `sys.prefix` is what decides, not `PATH`. |
| `this is Python X, and the contract declares Y` | A tree verified on one line has not been verified on another. Rebuild `.venv`, or raise the line deliberately in `runtime-contract.toml`. |
| `declared but not installed` | `scripts/bootstrap.ps1`. Do not install the packages individually: the lock is what makes the set reproducible. |
| `no runtime lock accompanies them` | The checkout is incomplete. Fetch it again rather than resolving versions locally. |
| `the configuration could not be bound` | Correct the setting the message names. [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) lists every key and its permitted values. |
| `the ... root could not be created` | Make the named location writable. GLOBIN creates nothing outside the project root. |
| `could not state its own name and version` | The project is not installed. `scripts/bootstrap.ps1` installs it, which is also what creates the `globin` command. |

No example here contains a secret, and none ever should: a document that shows
what a credential looks like has published its shape.

---

## RuntimeContext

What it carries:

- the application's name, version, and **where that version was read from**
- the host and the interpreter, as observed
- the validated `GlobinConfig`
- the declared `RuntimePaths`
- where the project root was found, recorded
- dependency readiness and secret readiness, as metadata
- a deterministic fingerprint over all of the above

What it deliberately does not carry: the process environment, the contents of any
file, a mutable field, a handle to anything open, and — above all — a secret
value. A module needing one of those asks for it explicitly, which keeps the
dependency visible instead of letting this object become ambient state.

Its `__repr__` is written out rather than generated, because the generated one
would expand every field and this is precisely the type a debugger gets pointed
at.

**The fingerprint is deterministic.** No process identifier, no clock reading and
no random value is folded in, so two runs on an unchanged host agree and a change
means something worth knowing about actually changed. A correlation identifier is
volatile on purpose and is a separate thing.

---

## Runtime paths

`RuntimePaths` declares the tree **relative to the project root**, as strings.
The domain may import no I/O-capable module and `pathlib` is one, and the
constraint turns out to be the better design: the adapter is the only thing that
knows where the root is, so an absolute path cannot reach the evidence by being
forgotten.

| Root | Default | Created |
|---|---|:---:|
| `config` | `config` | no — Phase 026 |
| `artifacts` | `.globin` | yes |
| `evidence` | `.globin/bootstrap` | yes |
| `logs` | `.globin/logs` | no |
| `state` | `.globin/state` | no |
| `cache` | `.globin/cache` | no |

**A declared root is a reservation, not a claim that anything writes there.**
Only the roots in `CREATED_PATHS` are brought into existence;
[`REPOSITORY_LAYOUT.md`](REPOSITORY_LAYOUT.md) refuses an empty directory named
after a future capability, and a field on a dataclass makes no such claim because
the class is a map rather than a tree.

There is no temporary root. Temporary work belongs in the platform's own
temporary directory through `tempfile`, which cleans up after itself.

A declared root that resolves outside the project is refused before anything is
created. It cannot happen with the defaults, which is exactly when a boundary
check is cheap.

---

## Working-directory independence

The project root is found by searching upwards from the working directory for a
`pyproject.toml` that **names this project**, at most twelve directories. Reading
the file rather than trusting the filename is what makes a checkout nested inside
an unrelated repository work instead of silently borrowing its parent, and the
bound is what stops the search wandering.

Run from the repository root or from any directory inside it, the same project is
found and the same facts are reported. `project.root`'s summary names where the
search started, which differs — that is diagnostic information, not drift.

---

## Evidence

`.globin/bootstrap/bootstrap-manifest.json`, written by `bootstrap evidence`.

The shape is the one every gate under `.globin` already uses: sorted keys,
compact separators, ASCII only, one line and a trailing newline, and a digest
over everything except the digest field. The reader refuses a document whose
schema, version or digest disagrees.

```text
schema          globin.bootstrap.manifest
schema_version  1
phase           21
observed        host, interpreter, project, paths, dependencies, secrets
checks          id, category, status, summary, remediation
verdict         ready, exit_code, reasons, fingerprint
digest          sha256:...
```

**No absolute path appears**, structurally rather than by filtering: a path is
turned into a `RecordedPath` at the moment it is observed, and that type carries
either a project-relative spelling, or a fingerprint, or nothing — never a
spelling for something outside the project.

**No secret value appears.** Every observed field passes through
`globin.domain.observability.redact` before it is placed, so a field whose *name*
looks like a credential is replaced whatever produced it. The verifier's own
scanner, `tools/quality/evidence/redaction`, is applied to the result in
`tests/contract/test_bootstrap_contract.py` — two mechanisms, neither importing
the other.

**A refused run still writes its evidence.** A gate that failed silently and left
no artefact is indistinguishable from one that never ran.

`.globin/` is git-ignored. Nothing here writes anywhere else, and with no project
root there is nowhere inside the project to write, so `bootstrap evidence`
refuses rather than falling back.

---

## What Phase 022 added

Four checks and three exit codes, and the registry took them without changing
shape — which was the seam's first real test. They sit after `paths.runtime`, in
dependency order: the mutable tree must resolve inside its own root before
anything can be written, a document must publish before the previous run's can be
read, and the lock is probed last because it is the only one whose answer can
change between two runs a second apart.

| Check | Asks |
|---|---|
| `paths.boundary` | Does the user-local runtime tree resolve, and does every area stay inside its root |
| `state.persistence` | Can a document be written, replaced and removed here — probed by doing it |
| `state.previous_run` | What did the last run record, **without** inferring that anything is running |
| `instance.lock` | Could this process be the machine's one coordinator |

`instance.lock` **probes and does not keep the lock.** This pipeline runs inside
`doctor` as well as inside the gate, and a diagnostic that took the production
lock would refuse to run beside a running GLOBIN — which is exactly when somebody
wants to run it. The lock that is *held* is taken by
`globin.application.lifecycle`, once, around the whole application.

The full contract, including what happens on each kind of ending, is in
[`RUNTIME_FILESYSTEM.md`](RUNTIME_FILESYSTEM.md).

---

## Handoff to Phase 023

The public surface these phases established, which later phases build on rather
than replace:

| Contract | Where |
|---|---|
| The check registry | `globin.domain.bootstrap.checks()` |
| Status and exit codes | `CheckStatus`, `ExitCode` |
| The report and its reduction | `BootstrapReport`, `exit_code_for` |
| The context | `RuntimeContext`, `context_fingerprint` |
| The path model | `RuntimePaths`, `RecordedPath`, `CREATED_PATHS` |
| The probes | `globin.ports.bootstrap` — six protocols |
| The pipeline | `globin.application.bootstrap.BootstrapPipeline` |
| Wiring | `globin.runtime.composition.build_bootstrap` |
| The entry point | `globin.runtime.cli.main` |
| The evidence schema | `globin.adapters.bootstrap` — `SCHEMA`, `SCHEMA_VERSION` |
| The mutable tree | `globin.domain.runtime_state` — `RuntimeLayout`, `RuntimeArea` |
| The lifecycle record | `LifecycleRecord`, `InstanceMetadata`, `read_lifecycle` |
| The runtime ports | `globin.ports.runtime_state` — four protocols |
| One run | `globin.application.lifecycle.Lifecycle`, `Session` |

Open, and not blocking:

- **`bootstrap.ready` is the only check that can produce exit code 1**, and it
  does so only when nothing before it failed. That path is narrow and lightly
  exercised.
- **The registry has one consumer.** Whether the seam fits Phases 026 to 030 is
  not yet known, and ADR-0056 records that as the main risk.
- **`config.valid` binds the declared defaults and nothing else**, because no
  configuration source exists to consult. Phase 027 is where that becomes a real
  question.
- **Nothing imports `numpy` or `pandas`**, and Phase 022 verified them without
  adopting them — a tripwire now fails if anything starts. Phases 113-128 own the
  numeric type indicators and models use.
- **The coordinator lock is narrow.** It guards one top-level process against
  being started twice. Phases 257 onwards need something broader for workers and
  child processes, and this cannot correctly become it.
- **An unclean previous run is a diagnostic and nothing more.** Nothing is
  resumed, repaired or replayed; that is Phase 267, and trading reconciliation is
  Phase 095.

---

## Related

- [ADR-0056](../adr/0056-phase-021-widens-to-deliver-the-application-bootstrap.md) — the decision, and the amendment record
- [ADR-0055](../adr/0055-the-first-runtime-dependencies-are-introduced-and-globin-becomes-installed.md) — the dependencies and the install
- [`RUNTIME_BASELINE.md`](RUNTIME_BASELINE.md) — the host contract this reads
- [`DEPENDENCY_LOCKING.md`](DEPENDENCY_LOCKING.md) — the locks this checks against
- [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — the settings register
- [`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md) — why secret readiness is measured and no store exists
